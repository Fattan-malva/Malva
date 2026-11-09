"""
malva.shell.session — Session lifecycle manager.

Each session:
  - Has a mode (assistant|meeting|interview_practice|interview_notes|voice_input)
  - Owns an AudioEngine, ASRRouter, TranscriptCore, AIOrchestrator, and mode engine
  - Manages Focus Mode and Sleep Mode state
  - Sends events to the UI via the event callback
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

from malva.audio.capture import AudioEngine, TrackSource
from malva.asr.router import ASRRouter
from malva.transcript.core import TranscriptCore
from malva.ai.orchestrator import AIOrchestrator
from malva.meeting.engine import MeetingEngine
from malva.interview.engine import InterviewEngine
from malva.desktop.gateway import DesktopGateway
from malva.privacy.manager import PrivacyManager
from malva.storage.db import Database


MODES = ("assistant", "meeting", "interview_practice", "interview_notes", "voice_input")


class SessionState:
    IDLE       = "idle"
    LISTENING  = "listening"
    PROCESSING = "processing"
    PAUSED     = "paused"
    SLEEPING   = "sleeping"
    FOCUSED    = "focused"
    ERROR      = "error"


class MalvaSession:
    """
    One active Malva session. Owns audio → ASR → transcript → AI pipeline.
    Focus Mode: session remains active, suppress non-essential notifications.
    Sleep Mode: audio pipeline stopped, state saved.
    """

    def __init__(
        self,
        mode: str,
        db: Database,
        asr_router: ASRRouter,
        desktop: DesktopGateway,
        privacy: PrivacyManager,
        on_event: Callable[[dict], None],
        asr_language: str = "auto",
    ):
        assert mode in MODES, f"Unknown mode: {mode}"
        self.session_id  = uuid.uuid4().hex
        self.mode        = mode
        self._db         = db
        self._asr        = asr_router
        self._desktop    = desktop
        self._privacy    = privacy
        self._on_event   = on_event

        self.state       = SessionState.IDLE
        self.focus_mode  = False
        self._running    = False
        self._lock       = threading.Lock()

        # Pipeline components
        self._audio = AudioEngine(
            session_id=self.session_id,
            mode=mode,
            on_utterance=self._on_utterance,
            on_levels=self._on_audio_levels,
            db=db,
        )
        self._transcript = TranscriptCore(session_id=self.session_id, db=db)
        self._ai = AIOrchestrator(session_id=self.session_id, mode=mode, db=db, privacy_manager=privacy)

        # Mode engines
        self._meeting:   MeetingEngine   | None = None
        self._interview: InterviewEngine | None = None
        if mode == "meeting":
            self._meeting = MeetingEngine(self.session_id, self._ai, db, self._transcript)
            self._meeting.set_update_callback(self._emit)
            self._transcript.add_listener(self._meeting.on_segment)
        elif mode in ("interview_practice", "interview_notes"):
            self._interview = InterviewEngine(self.session_id, mode, self._ai, db, self._transcript)
            self._interview.set_update_callback(self._emit)
            if mode == "interview_notes":
                self._transcript.add_listener(self._interview.on_segment)

        # Transcript always routes to AI for assistant mode
        if mode == "assistant":
            self._transcript.add_listener(self._on_transcript_event)

        # Create DB record
        db.create_session(self.session_id, mode)

    # ------------------------------------------------------------------ start / stop

    def start(self) -> None:
        """Start audio capture according to mode invariants."""
        if self._running:
            return
        self._running = True
        self.state    = SessionState.LISTENING
        self._emit({"type": "state_change", "state": SessionState.LISTENING})

        if self.mode == "assistant":
            self._audio.start_microphone()
            self._audio.start_system_audio()
        elif self.mode == "interview_practice":
            self._audio.start_microphone()
        elif self.mode == "meeting":
            self._audio.start_system_audio()
        elif self.mode == "interview_notes":
            self._audio.start_microphone()
            # system audio optional — not auto-started
        elif self.mode == "voice_input":
            self._audio.start_microphone()
            # system audio MUST NOT be started in voice_input (Blueprint §4)

        self._emit({"type": "session_started", "session_id": self.session_id,
                    "mode": self.mode, "sources": [s.value for s in self._audio.active_sources]})

    def stop(self) -> str | None:
        """Stop session. Returns finalized report JSON if applicable."""
        self._running = False
        self._audio.stop_all()
        self._ai.stop()
        self._db.end_session(self.session_id)
        self.state = SessionState.IDLE

        report = None
        if self._meeting:
            report = self._meeting.finalize()
        elif self._interview:
            if self.mode == "interview_practice":
                report = self._interview.finalize_practice()
            else:
                report = self._interview.finalize_notes()

        self._emit({"type": "session_ended", "session_id": self.session_id,
                    "mode": self.mode, "report": report})
        return report

    def pause(self) -> None:
        self._audio.pause_all()
        self.state = SessionState.PAUSED
        self._emit({"type": "state_change", "state": SessionState.PAUSED})

    def resume(self) -> None:
        self._audio.resume_all()
        self.state = SessionState.LISTENING
        self._ai.resume()
        self._emit({"type": "state_change", "state": SessionState.LISTENING})

    # ------------------------------------------------------------------ Focus Mode

    def enable_focus_mode(self) -> None:
        """
        Focus Mode: session stays active, suppress non-essential notifications.
        Does NOT silently change audio sources or Windows power policy.
        """
        self.focus_mode = True
        self.state = SessionState.FOCUSED
        self._emit({"type": "focus_mode", "enabled": True})

    def disable_focus_mode(self) -> None:
        self.focus_mode = False
        self.state = SessionState.LISTENING
        self._emit({"type": "focus_mode", "enabled": False})

    # ------------------------------------------------------------------ Sleep Mode (preserved from Nana)

    def enter_sleep(self) -> None:
        """Resource-saving state. Pauses audio pipeline."""
        self._audio.pause_all()
        self.state = SessionState.SLEEPING
        self._emit({"type": "sleep_mode", "sleeping": True})

    def exit_sleep(self) -> None:
        """Wake from sleep — resume audio pipeline."""
        self._audio.resume_all()
        self.state = SessionState.LISTENING
        self._emit({"type": "sleep_mode", "sleeping": False})

    # ------------------------------------------------------------------ assistant interaction

    def ask(self, text: str, on_chunk: Callable[[str], None] | None = None) -> str:
        """Direct text interaction (typing or voice input, already transcribed)."""
        self.state = SessionState.PROCESSING
        self._emit({"type": "state_change", "state": SessionState.PROCESSING})

        full_text, action = self._ai.ask(text, on_chunk=on_chunk)

        if action:
            result = self._desktop.run(action["tool"], action.get("args", {}))
            # Feed result back to AI for follow-up
            if result.get("ok"):
                follow_up = f"Tool result: {result['result']}"
            else:
                follow_up = f"Tool error: {result['error']}"
            full_text2, _ = self._ai.ask(follow_up, on_chunk=on_chunk)
            full_text = (full_text + " " + full_text2).strip()

        self.state = SessionState.LISTENING
        self._emit({"type": "state_change", "state": SessionState.LISTENING})
        return full_text

    # ------------------------------------------------------------------ pipeline

    def _on_utterance(self, wav_bytes: bytes, source: TrackSource, session_id: str) -> None:
        """Called by AudioEngine when an utterance chunk is ready."""
        if not self._running:
            return
        
        try:
            self.state = SessionState.PROCESSING
            self._emit({"type": "state_change", "state": SessionState.PROCESSING})

            # Transcribe
            self._asr.language = self._db.get_setting("asr_language", "auto")
            result = self._asr.transcribe(wav_bytes)
            if not result.full_text.strip():
                return

            # Store in transcript core (never overwrites raw text)
            track = self._audio.get_track(source)
            track_id = track.track_id if track else ""
            self._transcript.ingest(result, track_id=track_id, source_type=source.value)

            # For voice input mode: just emit transcription, no AI call
            if self.mode == "voice_input":
                self._emit({"type": "voice_input_text", "text": result.full_text})
                return

            # For meeting / interview_notes: transcript already routed via listener
            if self.mode in ("meeting", "interview_notes"):
                return

            # For assistant / interview_practice: send to AI
            def on_chunk(chunk: str) -> None:
                self._emit({"type": "ai_chunk", "text": chunk})

            # Interview Practice mode: generate question or evaluate answer
            if self.mode == "interview_practice" and self._interview:
                # Check if we need first question
                if not self._interview._practice.questions_asked:
                    self._interview.get_next_question(on_chunk=on_chunk)
                else:
                    # Evaluate current answer and generate next question
                    self._interview.evaluate_answer(result.full_text, on_chunk=on_chunk)
                    self._interview.get_next_question(on_chunk=on_chunk)
                return

            full_text, action = self._ai.ask(result.full_text, on_chunk=on_chunk)

            if action and self.mode == "assistant":
                confirm_result = self._desktop.run(action["tool"], action.get("args", {}))
                if confirm_result.get("ok"):
                    follow = f"Tool executed: {confirm_result['result']}"
                else:
                    follow = f"Tool failed: {confirm_result['error']}"
                self._ai.ask(follow, on_chunk=on_chunk)
        finally:
            self.state = SessionState.LISTENING
            self._emit({"type": "state_change", "state": SessionState.LISTENING})

    def _on_audio_levels(self, levels: list[float]) -> None:
        self._emit({"type": "audio_levels", "levels": levels})

    def _on_transcript_event(self, evt: dict) -> None:
        self._emit({"type": "transcript_segment", "data": evt})

    def _emit(self, event: dict) -> None:
        try:
            self._on_event(event)
        except Exception as e:
            print(f"[session] emit error: {e}")

