"""
malva.privacy.manager — Privacy and permission management (Blueprint §11).

Hidden Mode uses SetWindowDisplayAffinity (WDA_EXCLUDEFROMCAPTURE).
This is NOT a universal invisibility guarantee. Status is always reported honestly.

Status values:
  active      : capture exclusion successfully applied
  unsupported : Windows version does not support WDA_EXCLUDEFROMCAPTURE
  failed      : API call failed
  disabled    : hidden mode not active
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from enum import Enum
from typing import Callable

# WDA_EXCLUDEFROMCAPTURE = 0x11 (Windows 10 2004+)
WDA_NONE                = 0x00
WDA_MONITOR             = 0x01
WDA_EXCLUDEFROMCAPTURE  = 0x11


class HiddenModeStatus(str, Enum):
    DISABLED     = "disabled"
    ACTIVE       = "active"
    UNSUPPORTED  = "unsupported"
    FAILED       = "failed"


class PrivacyManager:
    """
    Manages Hidden Mode and audio permission state.
    Does not silently alter recording indicators or other app state.
    """

    def __init__(self, on_status_change: Callable[[str, str], None] | None = None):
        """on_status_change(component, status_string) — called on any status change."""
        self._on_status_change  = on_status_change
        self.hidden_mode_status = HiddenModeStatus.DISABLED
        self._hwnd: int | None  = None
        self.cloud_processing   = False   # opt-in only
        self.local_only         = True

    # ------------------------------------------------------------------ Hidden Mode

    def set_window_handle(self, hwnd: int) -> None:
        self._hwnd = hwnd

    def enable_hidden_mode(self) -> HiddenModeStatus:
        """
        Attempt to exclude the Malva window from screen capture.
        Always reports the actual result — never lies about compatibility.
        """
        if self._hwnd is None:
            self.hidden_mode_status = HiddenModeStatus.FAILED
            self._notify("hidden_mode", HiddenModeStatus.FAILED)
            return HiddenModeStatus.FAILED

        try:
            user32 = ctypes.windll.user32
            # Check if the function accepts WDA_EXCLUDEFROMCAPTURE
            ret = user32.SetWindowDisplayAffinity(
                ctypes.wintypes.HWND(self._hwnd),
                ctypes.c_uint(WDA_EXCLUDEFROMCAPTURE),
            )
            if ret:
                self.hidden_mode_status = HiddenModeStatus.ACTIVE
                self._notify("hidden_mode", HiddenModeStatus.ACTIVE)
                return HiddenModeStatus.ACTIVE
            else:
                # Might be unsupported version
                err = ctypes.get_last_error()
                if err == 87:  # ERROR_INVALID_PARAMETER
                    self.hidden_mode_status = HiddenModeStatus.UNSUPPORTED
                    self._notify("hidden_mode", HiddenModeStatus.UNSUPPORTED)
                    return HiddenModeStatus.UNSUPPORTED
                self.hidden_mode_status = HiddenModeStatus.FAILED
                self._notify("hidden_mode", HiddenModeStatus.FAILED)
                return HiddenModeStatus.FAILED
        except Exception:
            self.hidden_mode_status = HiddenModeStatus.UNSUPPORTED
            self._notify("hidden_mode", HiddenModeStatus.UNSUPPORTED)
            return HiddenModeStatus.UNSUPPORTED

    def disable_hidden_mode(self) -> None:
        if self._hwnd is None:
            return
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowDisplayAffinity(
                ctypes.wintypes.HWND(self._hwnd),
                ctypes.c_uint(WDA_NONE),
            )
        except Exception:
            pass
        self.hidden_mode_status = HiddenModeStatus.DISABLED
        self._notify("hidden_mode", HiddenModeStatus.DISABLED)

    # ------------------------------------------------------------------ cloud processing

    def enable_cloud_processing(self) -> None:
        """Cloud processing is opt-in only — never enabled silently."""
        self.cloud_processing = True
        self.local_only       = False
        self._notify("cloud_processing", "enabled")

    def disable_cloud_processing(self) -> None:
        self.cloud_processing = False
        self.local_only       = True
        self._notify("cloud_processing", "disabled")

    # ------------------------------------------------------------------ status summary

    def get_status(self) -> dict:
        return {
            "hidden_mode":       self.hidden_mode_status.value,
            "cloud_processing":  self.cloud_processing,
            "local_only":        self.local_only,
        }

    # ------------------------------------------------------------------ internal

    def _notify(self, component: str, status) -> None:
        if self._on_status_change:
            self._on_status_change(component, str(status.value if hasattr(status, "value") else status))

