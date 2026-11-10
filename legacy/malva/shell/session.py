"""
malva.shell.session — Session lifecycle manager.

Each session:
  - Has a mode (assistant | meeting | interview_practice | interview_notes | voice_input)
  - Owns an AudioEngine, one streaming transcriber per source, TranscriptCore,
    AIOrchestrator, and mode engine
  - Emits canonical events to the UI (see EVENT_TYPES below)

Behaviour guarantees:
  * Sources start per Blueprint §4. A source that fails to open is reported
    with a typed capture_error; it is never replaced by another source.
  * Every processing path ends in a correct state (listening / paused /
    sleeping / error). Focus does not change the state.
  * Speech never executes desktop actions on its own. An action proposed
    from speech becomes a pending item that the user must approve.
  * Interview Practice advances only on explicit user actions: start,
    finish answer, next question. Speech is never treated as an answer
    unless a question is pending.
  * System audio in Assistant mode is kept as transcript context only and
    does not trigger AI calls by itself.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

from malva.asr.gemini_live import GeminiLiveStream, language_codes_for
from malva.asr.service import ASRService
from malva.asr.types import ASRResult, ASRSegment
from malva.audio.capture import AudioEngine, TrackSource
from malva.audio.devices import AudioDeviceError
from malva.ai.orchestrator import AIOrchestrator
from malva.desktop.gateway import DesktopGateway
from malva.interview.engine import InterviewEngine
from malva.meeting.engine import MeetingEngine
from malva.desktop.gateway import requires_approval
from malva.privacy.manager import PrivacyManager
from malva.shell.policy import VOICE_APPROVAL_WINDOW_SECONDS, voice_decision
from malva.storage.db import Database
from malva.transcript.core import TranscriptCore


# Indonesian by default: auto-detection on short chunks often picks the wrong language.
DEFAULT_ASR_LANGUAGE = "id"

MODES = ("assistant", "meeting", "interview_practice", "interview_notes", "voice_input")

# Sources each mode starts by default (Blueprint §4).
DEFAULT_SOURCES: dict[str, tuple[TrackSource, ...]] = {
    "assistant":          (TrackSource.MICROPHONE, TrackSource.SYSTEM_AUDIO),
    "meeting":            (TrackSource.SYSTEM_AUDIO,),
    "interview_practice": (TrackSource.MICROPHONE,),
    "interview_notes":    (TrackSource.MICROPHONE,),
    "voice_input":        (TrackSource.MICROPHONE,),
}

# Canonical event contract (documented in HANDOFF.md). The UI bridge in app.py
# maps each of these to a JavaScript function.
EVENT_TYPES = (
    "session_started", "session_ended", "source_state", "capture_error",
    "state_change", "transcript_segment", "audio_levels",
    "ai_start", "ai_chunk", "ai_end", "ai_error",
    "action_proposed", "action_result",
    "voice_input_text", "focus_mode", "sleep_mode",
    "interview_question", "interview_answer_draft", "interview_feedback", "interview_report",
    "meeting_report", "transcript_partial", "asr_error", "report_error", "notice",
)

_ASR_NOTICE_COOLDOWN = 30.0


class SessionState:
    IDLE       = "idle"
    LISTENING  = "listening"
    PROCESSING = "processing"
    PAUSED     = "paused"
    SLEEPING   = "sleeping"
    ERROR      = "error"


class MalvaSession:
    def __init__(
        self,
        mode: str,
        db: Database,
        asr: ASRService,
        desktop: DesktopGateway,
        privacy: PrivacyManager,
        on_event: Callable[[dict], None],
        focus_mode: bool = False,
    ):
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode}")
        self.session_id = uuid.uuid4().hex
        self.mode       = mode
        self._db        = db
        self._asr       = asr
        self._desktop   = desktop
        self._privacy   = privacy
        self._on_event  = on_event

        self.state      = SessionState.IDLE
        self.focus_mode = bool(focus_mode)     # app-level preference, mirrored here
        self._running   = False
        self._paused    = False
        self._sleeping  = False
        self._lock      = threading.RLock()
        self._last_activity = time.time()
        self._pending: dict[str, dict] = {}
        self._asr_notice_at = 0.0

        # Interview Practice turn state
        self._practice_question = ""
        self._practice_answer: list[str] = []

        # One streaming transcriber per audio source (see malva/asr/gemini_live.py).
        self._streams: dict[TrackSource, GeminiLiveStream] = {}
        self._streams_lock = threading.Lock()

        self._audio = AudioEngine(
            session_id=self.session_id,
            mode=mode,
            on_pcm=self._on_pcm,
            on_speech=self._on_speech,
            on_levels=self._on_audio_levels,
            on_error=self._on_capture_error,
            db=db,
        )
        self._transcript = TranscriptCore(session_id=self.session_id, db=db)
        self._ai = AIOrchestrator(session_id=self.session_id, mode=mode, db=db, privacy_manager=privacy)
        self._ai.on_error = self._on_ai_error

        self._meeting:   MeetingEngine | None = None
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

        if mode == "assistant":
            self._transcript.add_listener(self._on_transcript_event)

        db.create_session(self.session_id, mode)

    # ------------------------------------------------------------------ start / stop

    def start(self) -> None:
        """Open the sources this mode needs. Failures are reported, not swallowed."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False
            self._sleeping = False

        for source in DEFAULT_SOURCES[self.mode]:
            self._open_source(source)

        self.touch()
        active = self._audio.active_sources
        self._emit({
            "type": "session_started",
            "session_id": self.session_id,
            "mode": self.mode,
            "sources": [s.value for s in active],
            "source_states": self._audio.source_states(),
        })
        if active:
            self._set_state(SessionState.LISTENING)
        else:
            self._set_state(SessionState.ERROR)

    def stop(self) -> None:
        """Stop capture immediately, then finalise reports in the background."""
        with self._lock:
            self._running = False
            self._paused = False
            self._sleeping = False
        self._close_all_streams()
        self._audio.stop_all()
        self._set_state(SessionState.IDLE)
        try:
            self._db.end_session(self.session_id)
        except Exception as e:
            print(f"[session] end_session failed: {e}")
        self._emit({"type": "session_ended", "session_id": self.session_id, "mode": self.mode})
        threading.Thread(target=self._finalize_reports, daemon=True, name="finalize").start()

    def _finalize_reports(self) -> None:
        try:
            if self._meeting:
                self._meeting.finalize()
            elif self.mode == "interview_notes" and self._interview:
                self._interview.finalize_notes()
            elif self.mode == "interview_practice" and self._interview:
                self._interview.finalize_practice()
        except Exception as e:
            self._emit({"type": "report_error", "message": f"Laporan gagal dibuat: {e}"})

    # ------------------------------------------------------------------ sources

    def _open_source(self, source: TrackSource) -> bool:
        try:
            if source == TrackSource.MICROPHONE:
                self._audio.start_microphone()
            else:
                self._audio.start_system_audio()
            self._open_stream(source)
            return True
        except AudioDeviceError as e:
            self._emit({"type": "capture_error", "source": source.value,
                        "code": e.code, "message": e.message})
        except ValueError as e:  # mode invariant (e.g. voice_input + system audio)
            self._emit({"type": "capture_error", "source": source.value,
                        "code": "MODE_RULE", "message": str(e)})
        self._emit_source_states()
        return False

    def enable_source(self, source: TrackSource) -> bool:
        """User toggled a source on from the UI. Mode rules still apply."""
        ok = self._open_source(source)
        self._emit_source_states()
        if ok and self.state == SessionState.ERROR:
            self._set_state(SessionState.LISTENING)
        return ok

    def disable_source(self, source: TrackSource) -> None:
        self._close_stream(source)
        self._audio.stop_track(source)
        self._emit_source_states()
        if self._running and not self._audio.active_sources:
            self._set_state(SessionState.ERROR)

    def _emit_source_states(self) -> None:
        self._emit({"type": "source_state", "states": self._audio.source_states(),
                    "active": [s.value for s in self._audio.active_sources]})

    # ------------------------------------------------------------------ pause / sleep / focus

    def pause(self) -> None:
        self._paused = True
        self._audio.pause_all()
        self._set_state(SessionState.PAUSED)

    def resume(self) -> None:
        self._paused = False
        if self._sleeping:
            return
        self._audio.resume_all()
        self._set_state(SessionState.LISTENING if self._audio.active_sources else SessionState.ERROR)

    def enter_sleep(self) -> None:
        """Resource-saving state. Pauses capture; does not close devices."""
        self._sleeping = True
        self._audio.pause_all()
        self._set_state(SessionState.SLEEPING)
        self._emit({"type": "sleep_mode", "sleeping": True})

    def exit_sleep(self) -> None:
        self._sleeping = False
        self.touch()
        if not self._paused:
            self._audio.resume_all()
        self._emit({"type": "sleep_mode", "sleeping": False})
        self._restore_state()

    def set_focus(self, enabled: bool) -> None:
        """Focus changes only the flag. It never touches the session state."""
        self.focus_mode = bool(enabled)
        self._emit({"type": "focus_mode", "enabled": self.focus_mode})

    # ------------------------------------------------------------------ activity

    def touch(self) -> None:
        self._last_activity = time.time()

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity

    @property
    def is_protected(self) -> bool:
        """True when this mode must not be interrupted by automatic sleep."""
        from malva.shell.policy import PROTECTED_MODES
        return self.mode in PROTECTED_MODES

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    @property
    def is_paused(self) -> bool:
        return self._paused

    def status(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "state": self.state,
            "focus_mode": self.focus_mode,
            "sources": self._audio.source_states(),
            "active_sources": [s.value for s in self._audio.active_sources],
        }

    # ------------------------------------------------------------------ typed input (assistant)

    def ask(self, text: str, on_chunk: Callable[[str], None] | None = None) -> str:
        """Explicit typed instruction. Its tool action runs under the normal policy."""
        self.touch()
        self._set_state(SessionState.PROCESSING)
        try:
            full_text, action = self._ai.ask(text, on_chunk=on_chunk)
            if action:
                result = self._desktop.run(action["tool"], action.get("args", {}))
                follow_up = (f"Tool result: {result['result']}" if result.get("ok")
                             else f"Tool error: {result['error']}")
                follow_text, _ = self._ai.ask(follow_up, on_chunk=on_chunk)
                full_text = (full_text + " " + follow_text).strip()
            return full_text
        finally:
            self._restore_state()

    # ------------------------------------------------------------------ pending actions

    def propose_action(self, tool: str, args: dict, origin: str = "speech") -> str:
        """Non-destructive actions run at once (tools are auto-granted). Destructive ones wait for approval."""
        pid = uuid.uuid4().hex[:12]
        if not requires_approval(tool, args):
            result = self._desktop.run(tool, args)
            self._emit({"type": "action_result", "id": pid, "ok": bool(result.get("ok")),
                        "message": str(result.get("error") or "Selesai")})
            return pid
        with self._lock:
            self._pending[pid] = {"id": pid, "tool": tool, "args": args, "origin": origin,
                                  "created_at": time.time()}
        self._emit({"type": "action_proposed", "action": {k: v for k, v in self._pending[pid].items()
                                                          if k != "created_at"}})
        return pid

    def pending_actions(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._pending.values()]

    def approve_action(self, action_id: str) -> dict:
        with self._lock:
            action = self._pending.pop(action_id, None)
        if action is None:
            return {"ok": False, "error": "Aksi tidak ditemukan atau sudah diproses."}
        result = self._desktop.run(action["tool"], action.get("args", {}), approved=True)
        self._emit({"type": "action_result", "id": action_id, "ok": bool(result.get("ok")),
                    "message": str(result.get("error") or "Selesai")})
        return result

    def _handle_voice_decision(self, text: str) -> bool:
        """Approve or reject the newest pending destructive action by voice. Microphone only."""
        decision = voice_decision(text)
        if decision is None:
            return False
        now = time.time()
        with self._lock:
            candidates = [a for a in self._pending.values()
                          if requires_approval(a["tool"], a.get("args", {}))
                          and now - a.get("created_at", 0) <= VOICE_APPROVAL_WINDOW_SECONDS]
        if not candidates:
            return False
        target = max(candidates, key=lambda a: a["created_at"])["id"]
        if decision == "approve":
            self.approve_action(target)
        else:
            self.reject_action(target)
        return True

    def reject_action(self, action_id: str) -> None:
        with self._lock:
            removed = self._pending.pop(action_id, None)
        if removed:
            self._emit({"type": "action_result", "id": action_id, "ok": False,
                        "message": "Dibatalkan oleh pengguna."})

    # ------------------------------------------------------------------ interview practice

    def start_practice(self, topic: str = "general", interview_type: str = "behavioral") -> str:
        if self.mode != "interview_practice" or self._interview is None:
            raise ValueError("Sesi ini bukan Latihan Wawancara.")
        self.touch()
        self._interview.set_interview_context(topic=topic, interview_type=interview_type)
        self._practice_answer = []
        return self._ask_next_practice_question()

    def submit_practice_answer(self) -> str:
        """User pressed 'Selesai menjawab'. Evaluates everything captured since the question."""
        if self.mode != "interview_practice" or self._interview is None:
            raise ValueError("Sesi ini bukan Latihan Wawancara.")
        answer = " ".join(self._practice_answer).strip()
        if not self._practice_question:
            self._emit({"type": "notice", "message": "Mulai dengan pertanyaan terlebih dahulu."})
            return ""
        if not answer:
            self._emit({"type": "notice", "message": "Belum ada jawaban yang terekam."})
            return ""
        self._practice_answer = []
        self._set_state(SessionState.PROCESSING)
        try:
            return self._interview.evaluate_answer(answer)
        finally:
            self._restore_state()

    def next_practice_question(self) -> str:
        if self.mode != "interview_practice" or self._interview is None:
            raise ValueError("Sesi ini bukan Latihan Wawancara.")
        self._practice_answer = []
        return self._ask_next_practice_question()

    def _ask_next_practice_question(self) -> str:
        self._set_state(SessionState.PROCESSING)
        try:
            question = self._interview.get_next_question()
        finally:
            self._restore_state()
        if question:
            self._practice_question = question
        else:
            self._emit({"type": "notice", "message": "Pertanyaan belum bisa dibuat. Periksa Cloudflare Workers AI (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN) dan CLOUD_ENABLED di .env."})
        return question

    def finish_practice(self) -> None:
        """Generate the practice report in the background and show it when ready."""
        if self._interview is None:
            return
        threading.Thread(target=self._finalize_reports, daemon=True, name="practice-report").start()

    # ------------------------------------------------------------------ pipeline

    # ------------------------------------------------------------------ streaming transcription

    def _open_stream(self, source: TrackSource) -> None:
        """Start (or restart) the cloud transcriber for one source."""
        self._close_stream(source)
        stream = self._asr.open_stream(
            label=source.value,
            on_partial=lambda text: self._on_partial(text, source),
            on_final=lambda text: self._on_final(text, source),
            on_error=lambda code, message: self._on_asr_error(code, message),
        )
        if stream is not None:
            with self._streams_lock:
                self._streams[source] = stream

    def _close_stream(self, source: TrackSource) -> None:
        with self._streams_lock:
            stream = self._streams.pop(source, None)
        if stream is not None:
            stream.close()

    def _close_all_streams(self) -> None:
        with self._streams_lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.close()

    def refresh_asr_streams(self) -> None:
        """Reopen every active transcriber so a changed language setting takes effect."""
        if not self._running:
            return
        for source in self._audio.active_sources:
            self._open_stream(source)

    def _on_pcm(self, pcm: bytes, source: TrackSource, session_id: str) -> None:
        """16 kHz PCM from the capture thread. Forwarded only while listening."""
        if not self._running or self._paused or self._sleeping:
            return
        with self._streams_lock:
            stream = self._streams.get(source)
        if stream is not None:
            stream.push(pcm)

    def _on_speech(self, source: TrackSource) -> None:
        """Speech activity keeps the session awake. Voice itself is not stored here."""
        if self._running and not self._paused and not self._sleeping:
            self.touch()

    def _on_partial(self, text: str, source: TrackSource) -> None:
        """Live text while someone is still speaking. Shown only; never stored or sent to AI."""
        if not self._running or self._paused or self._sleeping:
            return
        self._emit({"type": "transcript_partial", "source": source.value, "text": text})

    def _primary_language(self) -> str:
        codes = language_codes_for(self._db.get_setting("asr_language", DEFAULT_ASR_LANGUAGE))
        return codes[0].split("-")[0] if codes else "und"

    def _on_final(self, text: str, source: TrackSource) -> None:
        """One finished speech turn from the cloud transcriber (stream thread)."""
        text = (text or "").strip()
        if not text or not self._running or self._paused or self._sleeping:
            return
        self._set_state(SessionState.PROCESSING)
        try:
            self.touch()
            if source == TrackSource.MICROPHONE and self._handle_voice_decision(text):
                return  # the user's own voice answered a pending approval
            language = self._primary_language()
            result = ASRResult(
                full_text=text,
                language=language,
                segments=[ASRSegment(text=text, language=language)],
                model_used=self._asr.model_name,
            )
            track = self._audio.get_track(source)
            track_id = track.track_id if track else ""
            self._transcript.ingest(result, track_id=track_id, source_type=source.value)
            self._emit({"type": "transcript_partial", "source": source.value, "text": ""})

            if self.mode == "voice_input":
                self._emit({"type": "voice_input_text", "text": text})
                return
            if self.mode in ("meeting", "interview_notes"):
                return  # listeners already handled the segment
            if self.mode == "interview_practice":
                if self._practice_question:
                    self._practice_answer.append(text)
                    self._emit({"type": "interview_answer_draft",
                                "text": " ".join(self._practice_answer)})
                return
            if source == TrackSource.SYSTEM_AUDIO:
                return  # assistant: system audio is context only, never an automatic prompt

            self._emit({"type": "ai_start"})
            _, action = self._ai.ask(text, on_chunk=lambda c: self._emit({"type": "ai_chunk", "text": c}))
            self._emit({"type": "ai_end"})
            if action:
                self.propose_action(action["tool"], action.get("args", {}), origin="speech")
        finally:
            self._emit({"type": "transcript_partial", "source": source.value, "text": ""})
            self._restore_state()

    def _restore_state(self) -> None:
        if not self._running:
            target = SessionState.IDLE
        elif self._sleeping:
            target = SessionState.SLEEPING
        elif self._paused:
            target = SessionState.PAUSED
        elif self._audio.active_sources:
            target = SessionState.LISTENING
        else:
            target = SessionState.ERROR
        self._set_state(target)

    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit({"type": "state_change", "state": state})

    def _on_asr_error(self, code: str, message: str) -> None:
        """Transcriber problem (missing key, cloud disabled, stream failed). Rate-limited notice."""
        now = time.time()
        if now - self._asr_notice_at < _ASR_NOTICE_COOLDOWN:
            return
        self._asr_notice_at = now
        self._emit({"type": "asr_error", "code": code, "message": message})

    def _on_capture_error(self, source: TrackSource, code: str, message: str) -> None:
        self._emit({"type": "capture_error", "source": source.value, "code": code, "message": message})
        self._emit_source_states()
        if self._running and not self._audio.active_sources:
            self._set_state(SessionState.ERROR)

    def _on_audio_levels(self, source: TrackSource, levels: list[float]) -> None:
        self._emit({"type": "audio_levels", "source": source.value, "levels": levels})

    def _on_ai_error(self, message: str) -> None:
        self._emit({"type": "ai_error", "message": message})

    def _on_transcript_event(self, evt: dict) -> None:
        self._emit({"type": "transcript_segment", "data": evt})

    def _emit(self, event: dict) -> None:
        try:
            self._on_event(event)
        except Exception as e:
            print(f"[session] emit error: {e}")
