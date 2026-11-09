"""
app.py — Malva Desktop Entry Point.

Rebranded and evolved from Nana. Run with: python app.py

Architecture:
- pywebview frameless, always-on-top, draggable floating pill
- MalvaSession (audio -> ASR -> transcript -> AI / mode engine)
- Sleep / Focus rules live in malva.shell.policy (pure, tested)
- Every value sent to JavaScript goes through json.dumps; nothing is
  interpolated into script text by hand.
"""

from __future__ import annotations

import os
import sys

# Ensure UTF-8 output on the Windows console.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# WebView2 arguments must be set before pywebview is imported.
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--autoplay-policy=no-user-gesture-required --enable-features=msOverlayScrollbar"
)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import ctypes
import json
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from malva.diagnostics import setup as _setup_diagnostics  # noqa: E402
from malva.desktop.tools import ollama as _web_backend  # noqa: E402
LOG_PATH = _setup_diagnostics()

import webview

from malva.asr.router import ASRRouter
from malva.audio.capture import TrackSource
from malva.desktop.gateway import DesktopGateway
from malva.privacy.manager import PrivacyManager
from malva.shell.policy import parse_sleep_seconds, protected_capture_warning, should_auto_sleep
from malva.shell.session import MODES, MalvaSession, SessionState
from malva.storage import db
from malva.ui.html import PILL_HTML

# ------------------------------------------------------------------ configuration

LOCAL_APP_DATA = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Malva"
LOCAL_APP_DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = LOCAL_APP_DATA / "malva.db"

# One documented default (.env.example matches). 0 disables auto-sleep.
SLEEP_AFTER_SECONDS = parse_sleep_seconds(os.getenv("SLEEP_AFTER_SECONDS"), default=60.0)

WIN_W_COMPACT, WIN_H_COMPACT = 440, 62
WIN_W_EXPANDED, WIN_H_EXPANDED = 440, 450
WIN_W_SLEEP, WIN_H_SLEEP = 175, 46

_IDLE_CHECK_SECONDS = 5


def _js_value(value) -> str:
    """Encode a Python value as a JavaScript literal."""
    return json.dumps(value, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ JS API

class MalvaAPI:
    """Python API exposed to the pywebview JavaScript context."""

    def __init__(self, app: "MalvaApp"):
        self._app = app

    # --- window / lifecycle
    def ui_ready(self) -> None:
        self._app.on_ui_ready()

    def set_panel_state(self, state: str) -> None:
        self._app.set_panel_state(state)


    # --- capture controls
    def pause_session(self) -> None:
        self._app.session.pause()

    def resume_session(self) -> None:
        self._app.session.resume()

    def emergency_stop(self) -> None:
        self._app.session.stop()

    def change_mode(self, mode: str) -> None:
        if mode in MODES:
            self._app.switch_mode(mode)

    def enable_system_audio(self) -> bool:
        return self._app.session.enable_source(TrackSource.SYSTEM_AUDIO)

    def disable_system_audio(self) -> None:
        self._app.session.disable_source(TrackSource.SYSTEM_AUDIO)

    # --- sleep / focus
    def sleep_now(self, confirmed: bool = False) -> dict:
        return self._app.request_sleep(confirmed=bool(confirmed))

    def wake_from_sleep(self) -> None:
        self._app.wake()

    def enable_focus_mode(self) -> None:
        self._app.set_focus(True)

    def disable_focus_mode(self) -> None:
        self._app.set_focus(False)

    # --- hidden mode
    def enable_hidden_mode(self) -> None:
        self._app.privacy.enable_hidden_mode()

    def disable_hidden_mode(self) -> None:
        self._app.privacy.disable_hidden_mode()

    # --- privacy / cloud
    def get_privacy_status(self) -> dict:
        return self._app.privacy.get_status()

    def set_cloud_processing(self, enabled: bool) -> dict:
        self._app.privacy.set_cloud_processing(bool(enabled))
        self._app.sync_asr_status()
        return self._app.privacy.get_status()

    # --- ASR
    def set_asr_language(self, lang: str) -> None:
        if lang not in ("auto", "id", "en"):
            return
        self._app.database.set_setting("asr_language", lang)
        self._app.asr_router.language = lang
        self._app.sync_asr_status()

    def get_asr_catalog(self) -> list[dict]:
        return self._app.asr_router.get_models_catalog()

    def download_and_load_model(self, model_size: str) -> None:
        self._app.asr_router.load_model_async(model_size)

    # --- chat / assistant
    def send_text(self, text: str) -> None:
        self._app.handle_user_text(text)

    def approve_action(self, action_id: str) -> None:
        threading.Thread(target=self._app.session.approve_action, args=(action_id,), daemon=True).start()

    def reject_action(self, action_id: str) -> None:
        self._app.session.reject_action(action_id)

    # --- interview practice
    def start_practice(self, topic: str = "general", interview_type: str = "behavioral") -> None:
        self._app.run_background(self._app.session.start_practice, topic, interview_type)

    def submit_practice_answer(self) -> None:
        self._app.run_background(self._app.session.submit_practice_answer)

    def next_practice_question(self) -> None:
        self._app.run_background(self._app.session.next_practice_question)

    def finish_practice(self) -> None:
        self._app.session.finish_practice()

    # --- notes
    def update_action_status(self, item_id: str, status: str) -> None:
        self._app.database.update_action_item_status(item_id, status)


# ------------------------------------------------------------------ Application

class MalvaApp:
    def __init__(self):
        db.init(DB_PATH)
        self.database = db.get_db()

        self.privacy = PrivacyManager(on_status_change=self._on_privacy_status, db=self.database)
        _web_backend.set_cloud_gate(lambda: self.privacy.cloud_processing)

        tools_enabled = os.getenv("TOOLS_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
        self.desktop = DesktopGateway(session_id="", db=self.database, tools_enabled=tools_enabled)

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

        # Focus is an app-level preference, persisted across restarts and mode switches.
        self.focus_mode = self.database.get_setting("focus_mode", "0") == "1"

        self.session: MalvaSession = None  # type: ignore[assignment]
        self.current_mode = "assistant"
        self._create_session("assistant")

        self.window: webview.Window | None = None
        self._api = MalvaAPI(self)
        self._is_sleeping = False
        self._panel_state = "compact"
        self._idle_thread: threading.Thread | None = None
        self._ui_ready = False

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
        except Exception as e:
            print(f"[window] resize failed: {e}")

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
            focus_mode=self.focus_mode,
        )
        self.desktop.session_id = self.session.session_id

    def switch_mode(self, mode: str) -> None:
        if self._is_sleeping:
            self.wake()
        self._create_session(mode)
        self.session.start()
        self._call("updateMode", mode)
        self._call("updateFocusMode", self.focus_mode)

    def set_focus(self, enabled: bool) -> None:
        """Focus toggles only the flag. Sleep/pause/error states are untouched."""
        self.focus_mode = bool(enabled)
        self.database.set_setting("focus_mode", "1" if self.focus_mode else "0")
        self.session.set_focus(self.focus_mode)

    def run_background(self, fn, *args) -> None:
        """Run a session call that may block on the LLM, reporting failures to the UI."""
        def worker():
            try:
                fn(*args)
            except Exception as e:
                self._call("showNotice", "error", str(e))
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ UI event bridge

    def _on_session_event(self, event: dict) -> None:
        etype = event.get("type", "")

        if etype == "state_change":
            self._call("updateState", event.get("state", SessionState.IDLE))

        elif etype == "session_started":
            self._call("onSessionStarted", event)

        elif etype in ("source_state",):
            self._call("updateSourceStates", event)

        elif etype == "capture_error":
            self._call("showNotice", "error", event.get("message", "Sumber audio gagal dibuka."))

        elif etype == "transcript_segment":
            self._call("addTranscriptSegment", event.get("data", {}))

        elif etype == "transcript_partial":
            self._call("showPartialTranscript", event.get("source", ""), event.get("text", ""))

        elif etype == "audio_levels":
            self._call("updateBars", event.get("source", ""), event.get("levels", []))

        elif etype == "ai_start":
            self._call("startAnswer")
        elif etype == "ai_chunk":
            self._call("appendAnswer", event.get("text", ""))
        elif etype == "ai_end":
            self._call("endAnswer")
        elif etype == "ai_error":
            self._call("showNotice", "error", event.get("message", "AI tidak tersedia."))

        elif etype == "action_proposed":
            self._call("addPendingAction", event.get("action", {}))
        elif etype == "action_result":
            self._call("resolvePendingAction", event)

        elif etype == "voice_input_text":
            self._call("showVoiceText", event.get("text", ""))

        elif etype == "focus_mode":
            self._call("updateFocusMode", bool(event.get("enabled", False)))

        elif etype == "sleep_mode":
            sleeping = bool(event.get("sleeping", False))
            self._call("setSleeping", sleeping)
            self.set_panel_state("sleeping" if sleeping else "compact")

        elif etype == "interview_question":
            self._call("showInterviewQuestion", event.get("data", {}))
        elif etype == "interview_answer_draft":
            self._call("showAnswerDraft", event.get("text", ""))
        elif etype == "interview_feedback":
            self._call("showInterviewFeedback", event.get("data", {}))
        elif etype == "interview_report":
            self._call("showReport", event.get("data", {}))
        elif etype == "meeting_report":
            self._call("showMeetingReport", event.get("data", {}))

        elif etype == "asr_error":
            self._call("showNotice", "warning", event.get("message", ""))
        elif etype == "report_error":
            self._call("showNotice", "error", event.get("message", ""))
        elif etype == "notice":
            self._call("showNotice", "info", event.get("message", ""))
        elif etype == "session_ended":
            self._call("onSessionEnded")

    def _on_privacy_status(self, component: str, status: str) -> None:
        if component == "hidden_mode":
            self._call("updateHiddenMode", status)
        elif component == "cloud_processing":
            self._call("updatePrivacy", self.privacy.get_status())

    def _on_asr_status_update(self, data: dict) -> None:
        self._call("onASRStatusUpdate", data)
        self.sync_asr_status()

    # ------------------------------------------------------------------ interactions

    def handle_user_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.session.touch()
        if self._is_sleeping:
            self.wake()
        threading.Thread(target=self._ask_worker, args=(text,), daemon=True).start()

    def _ask_worker(self, text: str) -> None:
        self._call("startAnswer")
        try:
            self.session.ask(text, on_chunk=lambda c: self._call("appendAnswer", c))
        except Exception as e:
            self._call("showNotice", "error", f"Gagal memproses: {e}")
        finally:
            self._call("endAnswer")

    # ------------------------------------------------------------------ sleep / idle

    def request_sleep(self, confirmed: bool = False) -> dict:
        """Manual Sleep. Protected sessions must confirm because capture will pause."""
        if self._is_sleeping:
            return {"status": "already_sleeping"}
        if self.session.is_protected and not confirmed:
            return {"status": "needs_confirmation", "message": protected_capture_warning(self.session.mode)}
        self.sleep()
        return {"status": "sleeping"}

    def sleep(self) -> None:
        if self._is_sleeping:
            return
        self._is_sleeping = True
        self.session.enter_sleep()
        self.set_panel_state("sleeping")

    def wake(self) -> None:
        if not self._is_sleeping:
            return
        self._is_sleeping = False
        self.session.touch()
        self.session.exit_sleep()
        self.set_panel_state("compact")

    def _idle_monitor(self) -> None:
        while True:
            time.sleep(_IDLE_CHECK_SECONDS)
            try:
                session = self.session
                if should_auto_sleep(
                    mode=session.mode,
                    idle_seconds=session.idle_seconds,
                    threshold_seconds=SLEEP_AFTER_SECONDS,
                    focus_on=self.focus_mode,
                    sleeping=self._is_sleeping,
                    paused=session.is_paused,
                ):
                    self.sleep()
            except Exception as e:
                print(f"[idle] monitor error: {e}")

    # ------------------------------------------------------------------ sync helpers

    def sync_asr_status(self) -> None:
        payload = {"info": self.asr_router.model_info, "catalog": self.asr_router.get_models_catalog()}
        self._call("updateASRStatus", payload)

    def _apply_native_styling(self) -> None:
        hwnd = self.get_hwnd()
        if not hwnd:
            return
        try:
            dwm = ctypes.windll.dwmapi
            corner_pref = ctypes.c_int(2)  # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
            dark_mode = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
        except Exception as e:
            print(f"[win32] styling error: {e}")

    def on_ui_ready(self) -> None:
        if self._ui_ready:
            return  # page reloads must not start a second session
        self._ui_ready = True
        hwnd = self.get_hwnd()
        if hwnd:
            self.privacy.set_window_handle(hwnd)
            self._apply_native_styling()

        self._call("updateMode", self.current_mode)
        self._call("updateFocusMode", self.focus_mode)
        self._call("updatePrivacy", self.privacy.get_status())
        self.sync_asr_status()
        self.session.start()

        self._idle_thread = threading.Thread(target=self._idle_monitor, daemon=True)
        self._idle_thread.start()

    def get_hwnd(self) -> int | None:
        if self.window:
            try:
                return int(self.window.native.Handle.ToInt64())
            except Exception:
                try:
                    return ctypes.windll.user32.FindWindowW(None, "Malva")
                except Exception:
                    pass
        return None

    def _call(self, fn: str, *args) -> None:
        """Call window.<fn>(args...) in the page. Arguments are JSON-encoded."""
        if not self.window:
            return
        script = f"window.{fn} && window.{fn}({', '.join(_js_value(a) for a in args)})"
        try:
            self.window.evaluate_js(script)
        except Exception as e:
            print(f"[js] {fn} failed: {e}")

    # Kept for compatibility with older call sites.
    js = _call

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
            easy_drag=False,
        )
        print("[app] starting window")
        webview.start(debug=False)
        print("[app] window closed")


# ------------------------------------------------------------------ main

if __name__ == "__main__":
    app = MalvaApp()
    app.run()
