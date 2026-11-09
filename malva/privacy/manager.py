"""
malva.privacy.manager — Processing policy, cloud opt-in, and Hidden Mode (Blueprint §11).

Single source of truth for "may this data leave the machine?":

  * cloud_processing is OFF by default and is only turned on by an explicit
    user action (set_cloud_processing(True)). It is persisted in app_settings.
  * It is NOT inferred from environment variables or endpoint URLs. Earlier
    code treated "OLLAMA_URL is not localhost" as consent, which silently
    sent audio and prompts to a cloud provider.
  * ASR (Google STT) and the LLM (remote endpoints) both ask this manager
    before any network call. Blocked calls return a typed reason so the UI
    can say what is missing (e.g. "download a local model").

Hidden Mode uses SetWindowDisplayAffinity (WDA_EXCLUDEFROMCAPTURE). It is NOT
a universal invisibility guarantee; status is always reported honestly.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes  # noqa: F401  (used by Hidden Mode on Windows)
from enum import Enum
from typing import Callable
from urllib.parse import urlparse

# WDA_EXCLUDEFROMCAPTURE = 0x11 (Windows 10 2004+)
WDA_NONE                = 0x00
WDA_EXCLUDEFROMCAPTURE  = 0x11

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_remote_endpoint(url: str) -> bool:
    """True when `url` points somewhere other than this machine. Empty = not remote."""
    if not url or not url.strip():
        return False
    host = (urlparse(url.strip()).hostname or "").lower()
    if not host:
        # Unparseable input is treated as remote: fail closed.
        return True
    return host not in _LOCAL_HOSTS


class HiddenModeStatus(str, Enum):
    DISABLED    = "disabled"
    ACTIVE      = "active"
    UNSUPPORTED = "unsupported"
    FAILED      = "failed"


class PrivacyManager:
    """Holds the processing policy and Hidden Mode state."""

    SETTING_KEY = "cloud_processing"

    def __init__(
        self,
        on_status_change: Callable[[str, str], None] | None = None,
        db=None,
    ):
        """on_status_change(component, status_string) is called on every change."""
        self._on_status_change  = on_status_change
        self._db                = db
        self.hidden_mode_status = HiddenModeStatus.DISABLED
        self._hwnd: int | None  = None
        self.cloud_processing   = self._load_cloud_setting()

    # ------------------------------------------------------------------ policy

    @property
    def local_only(self) -> bool:
        return not self.cloud_processing

    def allows_cloud_asr(self) -> bool:
        """Google STT (or any cloud speech API) may be used only with explicit opt-in."""
        return self.cloud_processing

    def allows_remote_endpoint(self, url: str) -> bool:
        """LLM endpoints: localhost is always fine; remote needs explicit opt-in."""
        return (not is_remote_endpoint(url)) or self.cloud_processing

    def set_cloud_processing(self, enabled: bool) -> None:
        """Explicit user action only. Persisted so the choice survives restarts."""
        self.cloud_processing = bool(enabled)
        if self._db is not None:
            try:
                self._db.set_setting(self.SETTING_KEY, "1" if enabled else "0")
            except Exception as e:
                print(f"[privacy] could not persist cloud setting: {e}")
        self._notify("cloud_processing", "enabled" if enabled else "disabled")

    def enable_cloud_processing(self) -> None:
        self.set_cloud_processing(True)

    def disable_cloud_processing(self) -> None:
        self.set_cloud_processing(False)

    def _load_cloud_setting(self) -> bool:
        if self._db is None:
            return False
        try:
            return self._db.get_setting(self.SETTING_KEY, "0") == "1"
        except Exception:
            return False  # fail closed

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
            "hidden_mode":      self.hidden_mode_status.value,
            "cloud_processing": self.cloud_processing,
            "local_only":       self.local_only,
        }

    def _notify(self, component: str, status: str) -> None:
        if self._on_status_change:
            try:
                self._on_status_change(component, status)
            except Exception as e:
                print(f"[privacy] status callback failed: {e}")
