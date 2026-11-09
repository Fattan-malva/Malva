"""
app.py — Malva Desktop Entry Point (v1.0.0).

Rebranded and evolved from Nana.
Runs directly with: python app.py (no venv required).

Architecture:
- pywebview frameless, always-on-top, draggable floating pill
- Dynamic window resizing (Compact: 440x62, Expanded: 440x440, Sleeping: 175x46)
- MalvaSession (audio -> faster-whisper ASR -> SQLite -> AI Orchestrator)
- Non-blocking startup with in-settings ASR model management
- 100% SVG icon UI (no emojis/unicode symbol hacks)
"""

from __future__ import annotations

import os
import sys

# Ensure UTF-8 output on Windows console
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Force WebView2 arguments before import
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--autoplay-policy=no-user-gesture-required --enable-features=msOverlayScrollbar"
)
# Silence HuggingFace symlinks warning on non-dev Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import ctypes
import json
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import webview

# Malva core imports
from malva.asr.router import ASRRouter
from malva.desktop.gateway import DesktopGateway
from malva.privacy.manager import PrivacyManager
from malva.shell.session import MODES, MalvaSession, SessionState
from malva.storage import db
from malva.ui.html import PILL_HTML

# ------------------------------------------------------------------ configuration

LOCAL_APP_DATA = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Malva"
LOCAL_APP_DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = LOCAL_APP_DATA / "malva.db"

# Idle sleep timer
try:
    SLEEP_AFTER_SECONDS = float(os.getenv("SLEEP_AFTER_SECONDS", "60") or 60)
except ValueError:
    SLEEP_AFTER_SECONDS = 60.0

WAKE_WORD = (os.getenv("WAKE_WORD", "MALVA") or "MALVA").strip().upper()

# Window dimensions
WIN_W_COMPACT = 440
WIN_H_COMPACT = 62

WIN_W_EXPANDED = 440
WIN_H_EXPANDED = 450

WIN_W_SLEEP = 175
WIN_H_SLEEP = 46


# ------------------------------------------------------------------ JS API

class MalvaAPI:
    """Python API exposed to the pywebview JavaScript context."""

    def __init__(self, app: "MalvaApp"):
        self._app = app

    def ui_ready(self) -> None:
        """Called by JS when the page has fully loaded."""
        self._app.on_ui_ready()

    def set_panel_state(self, state: str) -> None:
        """Dynamically resize window based on UI state (compact/expanded/sleeping)."""
        self._app.set_panel_state(state)

    def send_text(self, text: str) -> None:
        """User typed a prompt or query into the input field."""
        self._app.handle_user_text(text)

    def pause_session(self) -> None:
        self._app.session.pause()

    def resume_session(self) -> None:
        self._app.session.resume()

    def emergency_stop(self) -> None:
        self._app.session.stop()

    def change_mode(self, mode: str) -> None:
        if mode in MODES:
            self._app.switch_mode(mode)

    def enable_focus_mode(self) -> None:
        self._app.session.enable_focus_mode()

    def disable_focus_mode(self) -> None:
        self._app.session.disable_focus_mode()

    def enable_hidden_mode(self) -> None:
        status = self._app.privacy.enable_hidden_mode()
        self._app.js(f"window.updateHiddenMode('{status.value}')")

    def disable_hidden_mode(self) -> None:
        self._app.privacy.disable_hidden_mode()
        self._app.js("window.updateHiddenMode('disabled')")

    def enable_system_audio(self) -> None:
        try:
            self._app.session._audio.start_system_audio()
            self._app.sync_sources()
        except Exception as e:
            self._app.js(f"window.showAction('error', '{e}')")

    def disable_system_audio(self) -> None:
        from malva.audio.capture import TrackSource
        self._app.session._audio.stop_track(TrackSource.SYSTEM_AUDIO)
        self._app.sync_sources()

    def set_asr_language(self, lang: str) -> None:
        self._app.database.set_setting("asr_language", lang)
        self._app.asr_router.language = lang
        self._app.sync_asr_status()

    def get_asr_catalog(self) -> list[dict]:
        """Return available models and their download/active status."""
        return self._app.asr_router.get_models_catalog()

    def download_and_load_model(self, model_size: str) -> None:
        """Download or activate a specific Whisper model."""
        self._app.asr_router.load_model_async(model_size)

    def wake_from_sleep(self) -> None:
        self._app.wake()

    def start_drag(self) -> None:
        """Windows native drag support via SendMessage."""
        if self._app.window:
            try:
                user32 = ctypes.windll.user32
                hwnd = self._app.get_hwnd()
                if hwnd:
                    # For always-on-top windows, use PostMessage approach
                    user32.PostMessageW(hwnd, 0x0112, 0xF012, 0)  # WM_SYSCOMMAND + SC_MOVE
                    user32.PostMessageW(hwnd, 0x0201, 1, 0)  # WM_LBUTTONDOWN to trigger move
            except Exception as e:
                print(f"[drag] {e}")

    def update_action_status(self, item_id: str, status: str) -> None:
        self._app.database.update_action_item_status(item_id, status)


# ------------------------------------------------------------------ Application

class MalvaApp:
    def __init__(self):
        # 1. Initialize SQLite
        db.init(DB_PATH)
        self.database = db.get_db()

        # 2. Privacy Manager
        self.privacy = PrivacyManager(on_status_change=self._on_privacy_status)

        # 3. Desktop Tool Gateway
        tools_enabled = os.getenv("TOOLS_ENABLED", "true").strip().lower() in (
            "1", "true", "yes", "on"
        )
        self.desktop = DesktopGateway(
            session_id="",
            db=self.database,
            tools_enabled=tools_enabled,
        )

        # 4. ASR Router (non-blocking async startup)
        saved_lang = self.database.get_setting("asr_language", "auto")
        self.asr_router = ASRRouter(
            model_size="small",
            device="cpu",
            compute_type="int8",
            language=saved_lang,
            auto_load=True,
            privacy_manager=self.privacy,
        )
        self.asr_router.set_status_callback(self._on_asr_status_update)

        # 5. Active Session (default: assistant)
        self.session: MalvaSession = None  # type: ignore
        self.current_mode = "assistant"
        self._create_session("assistant")

        # UI state
        self.window: webview.Window | None = None
        self._api = MalvaAPI(self)
        self._last_active_time = time.time()
        self._is_sleeping = False
        self._panel_state = "compact"
        self._idle_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ window sizing

    def set_panel_state(self, state: str) -> None:
        self._panel_state = state
        if not self.window:
            return
        try:
            if state == "expanded":
                self.window.resize(WIN_W_EXPANDED, WIN_H_EXPANDED)
            elif state == "sleeping":
                self.window.resize(WIN_W_SLEEP, WIN_H_SLEEP)
            else:
                self.window.resize(WIN_W_COMPACT, WIN_H_COMPACT)
        except Exception:
            pass

    # ------------------------------------------------------------------ session

    def _create_session(self, mode: str) -> None:
        if self.session:
            self.session.stop()
        self.current_mode = mode
        self.session = MalvaSession(
            mode=mode,
            db=self.database,
            asr_router=self.asr_router,
            desktop=self.desktop,
            privacy=self.privacy,
            on_event=self._on_session_event,
        )
        self.desktop.session_id = self.session.session_id

    def switch_mode(self, mode: str) -> None:
        self._create_session(mode)
        self.session.start()
        self.js(f"window.updateMode('{mode}')")
        self.sync_sources()

    # ------------------------------------------------------------------ UI events

    def _on_session_event(self, event: dict) -> None:
        etype = event.get("type", "")

        if etype == "state_change":
            state = event.get("state", "idle")
            self.js(f"window.updateState('{state}')")

        elif etype == "transcript_segment":
            data = event.get("data", {})
            self.js(f"window.addTranscriptSegment({json.dumps(data)})")
            self._reset_idle_timer()

        elif etype == "ai_chunk":
            text = event.get("text", "")
            self.js(f"window.appendAnswer({json.dumps(text)})")
            self._reset_idle_timer()

        elif etype == "audio_levels":
            levels = event.get("levels", [])
            self.js(f"window.updateBars({json.dumps(levels)})")

        elif etype == "focus_mode":
            active = event.get("enabled", False)
            self.js(f"window.updateFocusMode({json.dumps(active)})")

        elif etype == "sleep_mode":
            sleeping = event.get("sleeping", False)
            self.js(f"window.setSleeping({json.dumps(sleeping)})")
            self.set_panel_state("sleeping" if sleeping else "compact")

        elif etype == "voice_input_text":
            text = event.get("text", "")
            self.js(f"window.showVoiceText({json.dumps(text)})")

        elif etype == "meeting_report":
            data = event.get("data", {})
            for d in data.get("decisions", []):
                self.js(f"window.addDecision({json.dumps(d)})")
            for item in data.get("action_items", []):
                self.js(f"window.addActionItem({json.dumps(item)})")

        elif etype == "interview_report":
            report = event.get("data", {})
            self.js(f"window.appendAnswer({json.dumps(report.get('report', ''))})")

    def _on_privacy_status(self, component: str, status: str) -> None:
        if component == "hidden_mode":
            self.js(f"window.updateHiddenMode('{status}')")

    def _on_asr_status_update(self, data: dict) -> None:
        self.js(f"window.onASRStatusUpdate({json.dumps(data)})")
        self.sync_asr_status()

    # ------------------------------------------------------------------ interactions

    def handle_user_text(self, text: str) -> None:
        self._reset_idle_timer()
        threading.Thread(target=self._ask_worker, args=(text,), daemon=True).start()

    def _ask_worker(self, text: str) -> None:
        self.js("window.startAnswer()")

        def on_chunk(chunk: str) -> None:
            self.js(f"window.appendAnswer({json.dumps(chunk)})")

        full_text = self.session.ask(text, on_chunk=on_chunk)
        self.js("window.endAnswer()")

    # ------------------------------------------------------------------ sleep / idle

    def _reset_idle_timer(self) -> None:
        self._last_active_time = time.time()
        if self._is_sleeping:
            self.wake()

    def _idle_monitor(self) -> None:
        while True:
            time.sleep(5)
            if SLEEP_AFTER_SECONDS <= 0:
                continue
            if self.session.focus_mode:
                # Focus Mode suppresses sleep (Blueprint §7)
                continue
            # Don't sleep if session is actively listening, processing, or focused
            if self.session.state in (SessionState.LISTENING, SessionState.PROCESSING, SessionState.FOCUSED):
                self._last_active_time = time.time()
                continue
            if not self._is_sleeping:
                idle = time.time() - self._last_active_time
                if idle >= SLEEP_AFTER_SECONDS:
                    self.sleep()

    def sleep(self) -> None:
        self._is_sleeping = True
        self.session.enter_sleep()
        self.set_panel_state("sleeping")
        self.js("window.setSleeping(true)")

    def wake(self) -> None:
        self._is_sleeping = False
        self._last_active_time = time.time()
        self.session.exit_sleep()
        self.set_panel_state("compact")
        self.js("window.setSleeping(false)")

    # ------------------------------------------------------------------ sync helpers

    def sync_sources(self) -> None:
        sources = [s.value for s in self.session._audio.active_sources]
        self.js(f"window.updateSources({json.dumps(sources)})")

    def sync_asr_status(self) -> None:
        info = self.asr_router.model_info
        catalog = self.asr_router.get_models_catalog()
        payload = {"info": info, "catalog": catalog}
        self.js(f"window.updateASRStatus({json.dumps(payload)})")

    def _apply_native_styling(self) -> None:
        hwnd = self.get_hwnd()
        if hwnd:
            try:
                dwm = ctypes.windll.dwmapi
                # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
                corner_pref = ctypes.c_int(2)
                dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
                # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                dark_mode = ctypes.c_int(1)
                dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
            except Exception as e:
                print(f"[win32] styling error: {e}")

    def on_ui_ready(self) -> None:
        hwnd = self.get_hwnd()
        if hwnd:
            self.privacy.set_window_handle(hwnd)
            self._apply_native_styling()

        self.js(f"window.updateMode('{self.current_mode}')")
        self.sync_asr_status()
        self.session.start()
        self.sync_sources()

        # Start idle monitor thread
        self._idle_thread = threading.Thread(target=self._idle_monitor, daemon=True)
        self._idle_thread.start()

    def get_hwnd(self) -> int | None:
        if self.window:
            try:
                return int(self.window.native.Handle.ToInt64())
            except Exception:
                try:
                    user32 = ctypes.windll.user32
                    return user32.FindWindowW(None, "Malva")
                except Exception:
                    pass
        return None

    def js(self, script: str) -> None:
        if self.window:
            try:
                self.window.evaluate_js(script)
            except Exception:
                pass

    # ------------------------------------------------------------------ launch

    def run(self) -> None:
        self.window = webview.create_window(
            title="Malva",
            html=PILL_HTML,
            width=WIN_W_COMPACT,
            height=WIN_H_COMPACT,
            frameless=True,
            on_top=True,
            background_color="#000000",
            transparent=False,
            js_api=self._api,
            easy_drag=False,  # Managed via native Win32 start_drag()
        )
        webview.start(debug=False)


# ------------------------------------------------------------------ main

if __name__ == "__main__":
    app = MalvaApp()
    app.run()
