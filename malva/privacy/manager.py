"""
malva.privacy.manager — Cloud policy and Hidden Mode (Blueprint §3, §11).

Cloud processing is approved by product decision (Blueprint §3): speech recognition
(Gemini), the LLM (Cloudflare Workers AI) and web search all use cloud services. The approval
is a configuration value, not a per-user toggle, and it is visible in the Setelan tab.

  * CLOUD_ENABLED (default "true") is the only switch. Set it to "false" to block every
    cloud call. Each blocked call returns a typed reason so the UI can say what is missing.
  * Nothing is ever sent to a different service than the ones listed in Blueprint §3.

Hidden Mode uses SetWindowDisplayAffinity (WDA_EXCLUDEFROMCAPTURE). It is NOT
a universal invisibility guarantee; status is always reported honestly.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes  # noqa: F401  (used by Hidden Mode on Windows)
import os
from enum import Enum
from typing import Callable

# WDA_EXCLUDEFROMCAPTURE = 0x11 (Windows 10 2004+)
WDA_NONE                = 0x00
WDA_EXCLUDEFROMCAPTURE  = 0x11

class HiddenModeStatus(str, Enum):
    DISABLED    = "disabled"
    ACTIVE      = "active"
    UNSUPPORTED = "unsupported"
    FAILED      = "failed"


def cloud_enabled_from_env() -> bool:
    """CLOUD_ENABLED defaults to true. Only an explicit false/0/no/off turns cloud off."""
    return os.getenv("CLOUD_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


class PrivacyManager:
    """Holds the cloud policy and Hidden Mode state."""

    def __init__(self, on_status_change: Callable[[str, str], None] | None = None):
        """on_status_change(component, status_string) is called on every change."""
        self._on_status_change  = on_status_change
        self.hidden_mode_status = HiddenModeStatus.DISABLED
        self._hwnd: int | None  = None
        self.cloud_enabled      = cloud_enabled_from_env()

    # ------------------------------------------------------------------ policy

    def allows_cloud(self) -> bool:
        """The single cloud gate. Speech, LLM and web search all ask this."""
        return self.cloud_enabled

    def allows_cloud_asr(self) -> bool:
        return self.allows_cloud()

    def allows_llm(self) -> bool:
        return self.allows_cloud()

    # ------------------------------------------------------------------ Hidden Mode

    def set_window_handle(self, hwnd: int) -> None:
        self._hwnd = hwnd

    def enable_hidden_mode(self) -> HiddenModeStatus:
        """Attempt capture exclusion. Reports the actual outcome."""
        if self._hwnd is None:
            return self._set_hidden(HiddenModeStatus.FAILED)
        try:
            user32 = ctypes.windll.user32
            ret = user32.SetWindowDisplayAffinity(
                ctypes.wintypes.HWND(self._hwnd),
                ctypes.c_uint(WDA_EXCLUDEFROMCAPTURE),
            )
            if ret:
                return self._set_hidden(HiddenModeStatus.ACTIVE)
            err = ctypes.get_last_error()
            if err == 87:  # ERROR_INVALID_PARAMETER: Windows build too old
                return self._set_hidden(HiddenModeStatus.UNSUPPORTED)
            return self._set_hidden(HiddenModeStatus.FAILED)
        except Exception as e:
            print(f"[privacy] hidden mode unavailable: {e}")
            return self._set_hidden(HiddenModeStatus.UNSUPPORTED)

    def disable_hidden_mode(self) -> None:
        if self._hwnd is not None:
            try:
                ctypes.windll.user32.SetWindowDisplayAffinity(
                    ctypes.wintypes.HWND(self._hwnd), ctypes.c_uint(WDA_NONE),
                )
            except Exception as e:
                print(f"[privacy] could not clear display affinity: {e}")
        self._set_hidden(HiddenModeStatus.DISABLED)

    def _set_hidden(self, status: HiddenModeStatus) -> HiddenModeStatus:
        self.hidden_mode_status = status
        self._notify("hidden_mode", status.value)
        return status

    # ------------------------------------------------------------------ status

    def get_status(self) -> dict:
        return {
            "hidden_mode": self.hidden_mode_status.value,
            "cloud_enabled": self.cloud_enabled,
        }

    def _notify(self, component: str, status: str) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(component, status)
            except Exception as e:
                print(f"[privacy] status callback failed: {e}")
