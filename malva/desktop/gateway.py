"""
malva.desktop.gateway — Desktop Tool Gateway with Permission + Policy + Audit.

Risk levels (Blueprint §10):
  low      : read window title, inspect screen context
  medium   : click, type, scroll, fill fields
  high     : send email, delete files, change settings
  very_high: arbitrary shell, registry edits (disabled by default)

Tool dispatch reuses tools/ from the existing Nana codebase.
"""

from __future__ import annotations

import json
import uuid
import time
from typing import Any, Callable

from malva.desktop.tools import safety
from malva.storage.db import Database

# Approval is required only for destructive calls (Blueprint §10, user decision 2026-11-09).
# Closing a tab or an app is not destructive and runs without approval.
def requires_approval(tool_name: str, args: dict) -> bool:
    if "delete" in tool_name.lower():
        return True
    return safety.is_destructive(json.dumps(args, ensure_ascii=False, default=str))

# ------------------------------------------------------------------ risk table

TOOL_RISK: dict[str, str] = {
    # Low risk
    "list_windows":     "low",
    "observe_active":   "low",
    "ui_controls":      "low",
    "verify_window":    "low",
    "verify_file":      "low",
    "verify_process":   "low",
    "wait":             "low",
    "web_search":       "low",
    "web_fetch":        "low",
    "browser_tabs":     "low",
    "browser_state":    "low",
    "browser_find":     "low",
    "browser_attach":   "low",
    # Medium risk
    "focus_window":     "medium",
    "open_app":         "medium",
    "open_terminal":    "medium",
    "open_folder":      "medium",
    "open_in_vscode":   "medium",
    "open_url":         "medium",
    "type_text":        "medium",
    "press_key":        "medium",
    "volume_up":        "medium",
    "volume_down":      "medium",
    "volume_mute":      "medium",
    "ui_click":         "medium",
    "ui_type":          "medium",
    "ui_scroll":        "medium",
    "mouse_click":      "medium",
    "dismiss_dialog":   "medium",
    "wait_for_control": "medium",
    "browser_open":     "medium",
    "browser_switch_tab": "medium",
    "browser_search":   "medium",
    "browser_click":    "medium",
    "browser_fill":     "medium",
    "browser_press":    "medium",
    "browser_scroll":   "medium",
    "browser_wait":     "medium",
    "browser_play":     "medium",
    # High risk
    "run_command":      "high",
    "close_tab":        "high",
    "close_browser":    "high",
    "browser_close_tab": "high",
    # Cancel is always allowed
    "cancel_task":      "low",
}

# Default policy per risk level
_DEFAULT_POLICY: dict[str, str] = {
    "low":       "auto",       # Every tool is granted automatically
    "medium":    "auto",
    "high":      "auto",
    "very_high": "auto",
}


class DesktopGateway:
    """
    Single entry point for all desktop actions.
    Every call is checked against permissions, risk policy, and logged.
    """

    def __init__(
        self,
        session_id: str,
        db: Database,
        tools_enabled: bool = True,
        on_confirm: Callable[[str, str, dict], bool] | None = None,
    ):
        """
        on_confirm(tool_name, risk_level, args) -> bool
          Called for high-risk tools to get user approval.
          If None, high-risk tools are auto-rejected.
        """
        self.session_id    = session_id
        self._db           = db
        self.tools_enabled = tools_enabled
        self._on_confirm   = on_confirm
        self._policy       = dict(_DEFAULT_POLICY)

    # ------------------------------------------------------------------ configuration

    def set_policy(self, risk_level: str, policy: str) -> None:
        """Override policy for a risk level: 'auto' | 'confirm' | 'disabled'."""
        assert risk_level in _DEFAULT_POLICY
        assert policy in ("auto", "confirm", "disabled")
        self._policy[risk_level] = policy

    def enable_tools(self) -> None:
        self.tools_enabled = True

    def disable_tools(self) -> None:
        self.tools_enabled = False

    # ------------------------------------------------------------------ dispatch

    def run(self, tool_name: str, args: dict, approved: bool = False) -> dict:
        """
        Execute a tool call. Returns {"ok": bool, "result": any, "error": str}.
        `approved=True` means the user already approved this exact call (UI or voice).
        All calls are logged to tool_audit_logs.
        """
        log_id     = uuid.uuid4().hex
        risk_level = TOOL_RISK.get(tool_name, "very_high")
        policy     = self._policy.get(risk_level, "disabled")
        if policy != "disabled" and requires_approval(tool_name, args):
            policy = "confirm"
        args_json  = json.dumps(args, ensure_ascii=False)

        # 1. Tools globally disabled?
        if not self.tools_enabled:
            self._log(log_id, tool_name, args_json, risk_level, False,
                      error="TOOLS_ENABLED=false")
            return {"ok": False, "result": None, "error": "Desktop tools are disabled."}

        # 2. Policy check
        if policy == "disabled":
            self._log(log_id, tool_name, args_json, risk_level, False,
                      error="Disabled by policy")
            return {"ok": False, "result": None,
                    "error": f"Tool '{tool_name}' is disabled (risk: {risk_level})."}

        if policy == "confirm" and not approved:
            approved = self._ask_confirm(tool_name, risk_level, args)
            if not approved:
                self._log(log_id, tool_name, args_json, risk_level, False,
                          error="User did not approve")
                return {"ok": False, "result": None, "error": "Action not approved by user."}

        # 3. Execute
        try:
            result  = self._dispatch(tool_name, args)
            outcome = json.dumps(result, default=str)[:500]
            self._log(log_id, tool_name, args_json, risk_level, True, outcome=outcome)
            return {"ok": True, "result": result, "error": ""}
        except Exception as e:
            self._log(log_id, tool_name, args_json, risk_level, True, error=str(e))
            return {"ok": False, "result": None, "error": str(e)}

    # ------------------------------------------------------------------ dispatch table

    def _dispatch(self, tool_name: str, args: dict) -> Any:
        from malva.desktop.tools import runner
        return runner.run(tool_name, args)

    # ------------------------------------------------------------------ helpers

    def _ask_confirm(self, tool_name: str, risk_level: str, args: dict) -> bool:
        if self._on_confirm:
            return self._on_confirm(tool_name, risk_level, args)
        return False  # Default: reject if no confirm callback

    def _log(self, log_id: str, tool_name: str, args_json: str, risk_level: str,
              approved: bool, outcome: str = "", error: str = "") -> None:
        self._db.log_tool_action(
            log_id=log_id,
            session_id=self.session_id,
            tool_name=tool_name,
            args_json=args_json,
            risk_level=risk_level,
            approved=approved,
            outcome=outcome,
            error=error,
        )
