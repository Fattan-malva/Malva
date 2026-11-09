"""
Session behaviour: source startup per mode, state transitions, speech never
executes actions, interview practice advances only on explicit actions,
and Focus never overrides Paused/Sleeping/Error.

Uses a real SQLite database in a temp directory and a fake audio backend.
"""

import threading
import time

import pytest

from conftest import FakePA
from malva.asr.router import ASRResult, LOCAL_MODEL_REQUIRED
from malva.audio.capture import TrackSource
from malva.privacy.manager import PrivacyManager
from malva.shell.session import MalvaSession, SessionState


@pytest.fixture
def real_db(tmp_path, monkeypatch):
    from malva.storage import db as dbmod
    monkeypatch.setattr(dbmod, "_LOCAL", threading.local())  # fresh thread-local connection
    dbmod.init(tmp_path / "malva-test.db")
    return dbmod.get_db()


class FakeASR:
    language = "auto"
    is_local = True

    def __init__(self, text="halo", model_used="local"):
        self.text = text
        self.model_used = model_used

    def transcribe(self, wav):
        return ASRResult(full_text=self.text, language="id", model_used=self.model_used)


class FakeDesktop:
    def __init__(self):
        self.calls = []

    def run(self, tool, args):
        self.calls.append((tool, args))
        return {"ok": True, "result": "done", "error": ""}


def _session(mode, db, events, asr=None, desktop=None):
    return MalvaSession(
        mode=mode,
        db=db,
        asr_router=asr or FakeASR(),
        desktop=desktop or FakeDesktop(),
        privacy=PrivacyManager(db=db),
        on_event=events.append,
    )


def _types(events):
    return [e["type"] for e in events]


WAV = b"RIFF-not-really-a-wav"  # _on_utterance never decodes it when ASR is faked


# ------------------------------------------------------------------ startup per mode

def test_assistant_reports_missing_loopback_and_keeps_microphone(fake_mic_only, real_db):
    events = []
    s = _session("assistant", real_db, events)
    s.start()
    try:
        assert s.state == SessionState.LISTENING
        started = next(e for e in events if e["type"] == "session_started")
        assert started["sources"] == ["microphone"]
        err = next(e for e in events if e["type"] == "capture_error")
        assert err["source"] == "system_audio"
        assert err["code"] == "LOOPBACK_UNAVAILABLE"
    finally:
        s.stop()


def test_meeting_without_loopback_is_error_and_never_opens_mic(fake_mic_only, real_db):
    events = []
    s = _session("meeting", real_db, events)
    s.start()
    try:
        assert s.state == SessionState.ERROR
        assert any(e["type"] == "capture_error" and e["code"] == "LOOPBACK_UNAVAILABLE" for e in events)
        assert all(not pa.opened for pa in FakePA.instances), "meeting must not fall back to mic"
    finally:
        s.stop()


def test_voice_input_never_receives_system_audio(fake_mic_only, real_db):
    events = []
    s = _session("voice_input", real_db, events)
    s.start()
    try:
        with pytest.raises(ValueError):
            s._audio.start_system_audio()
        assert "system_audio" not in [src.value for src in s._audio.active_sources]
    finally:
        s.stop()


# ------------------------------------------------------------------ state transitions

def test_focus_does_not_override_pause_or_sleep(fake_mic_only, real_db):
    events = []
    s = _session("interview_practice", real_db, events)
    s.start()
    try:
        s.pause()
        assert s.state == SessionState.PAUSED
        s.set_focus(True)
        assert s.state == SessionState.PAUSED, "focus must not change state"
        s.set_focus(False)
        assert s.state == SessionState.PAUSED, "unfocus must not force listening"
        s.resume()
        assert s.state == SessionState.LISTENING

        s.enter_sleep()
        assert s.state == SessionState.SLEEPING
        s.set_focus(True)
        assert s.state == SessionState.SLEEPING
        s.exit_sleep()
        assert s.state == SessionState.LISTENING
    finally:
        s.stop()


def test_focus_flag_is_mirrored_and_announced(fake_mic_only, real_db):
    events = []
    s = _session("assistant", real_db, events)
    s.set_focus(True)
    assert s.focus_mode is True
    assert events[-1] == {"type": "focus_mode", "enabled": True}


def test_pause_resume_emits_canonical_state_changes(fake_mic_only, real_db):
    events = []
    s = _session("interview_notes", real_db, events)
    s.start()
    try:
        s.pause()
        s.resume()
        states = [e["state"] for e in events if e["type"] == "state_change"]
        assert SessionState.PAUSED in states
        assert states[-1] == SessionState.LISTENING
    finally:
        s.stop()


def test_processing_always_resolves_back_to_listening(fake_mic_only, real_db):
    events = []
    s = _session("assistant", real_db, events, asr=FakeASR(text=""))
    s.start()
    try:
        s._on_utterance(WAV, TrackSource.MICROPHONE, s.session_id)  # empty transcript
        assert s.state == SessionState.LISTENING
        assert [e["state"] for e in events if e["type"] == "state_change"][-1] == SessionState.LISTENING
    finally:
        s.stop()


# ------------------------------------------------------------------ speech never acts on its own

def test_speech_proposes_action_but_does_not_execute(fake_mic_only, real_db):
    events, desktop = [], FakeDesktop()
    s = _session("assistant", real_db, events, desktop=desktop)
    s.start()
    try:
        s._ai.ask = lambda text, on_chunk=None: ("ketik sesuatu", {"tool": "type_text", "args": {"text": "x"}})
        s._on_utterance(WAV, TrackSource.MICROPHONE, s.session_id)
        assert desktop.calls == [], "speech must never run a desktop action by itself"
        proposed = [e for e in events if e["type"] == "action_proposed"]
        assert proposed and proposed[0]["action"]["tool"] == "type_text"
        assert proposed[0]["action"]["origin"] == "speech"
    finally:
        s.stop()


def test_approve_runs_pending_action_once(fake_mic_only, real_db):
    events, desktop = [], FakeDesktop()
    s = _session("assistant", real_db, events, desktop=desktop)
    s.start()
    try:
        pid = s.propose_action("open_url", {"url": "https://example.org"}, origin="speech")
        assert [a["id"] for a in s.pending_actions()] == [pid]
        result = s.approve_action(pid)
        assert result["ok"] is True
        assert desktop.calls == [("open_url", {"url": "https://example.org"})]
        assert s.approve_action(pid)["ok"] is False  # cannot run twice
    finally:
        s.stop()


def test_reject_discards_without_running(fake_mic_only, real_db):
    desktop = FakeDesktop()
    s = _session("assistant", real_db, [], desktop=desktop)
    pid = s.propose_action("type_text", {"text": "x"})
    s.reject_action(pid)
    assert desktop.calls == []
    assert s.pending_actions() == []


def test_typed_instruction_runs_under_normal_policy(fake_mic_only, real_db):
    desktop = FakeDesktop()
    s = _session("assistant", real_db, [], desktop=desktop)
    s._ai.ask = lambda text, on_chunk=None: ("", {"tool": "open_url", "args": {"url": "x"}}) if "buka" in text else ("ok", None)
    s.ask("buka x")
    assert desktop.calls == [("open_url", {"url": "x"})]


def test_system_audio_is_context_only_in_assistant(fake_mic_only, real_db):
    events = []
    s = _session("assistant", real_db, events)
    s.start()
    try:
        def boom(*a, **k):
            raise AssertionError("system audio must not trigger an AI prompt")
        s._ai.ask = boom
        s._on_utterance(WAV, TrackSource.SYSTEM_AUDIO, s.session_id)
        assert "ai_start" not in _types(events)
    finally:
        s.stop()


# ------------------------------------------------------------------ ASR failure visibility

def test_missing_local_model_is_reported_and_no_ai_call(fake_mic_only, real_db):
    events = []
    s = _session("assistant", real_db, events, asr=FakeASR(model_used=LOCAL_MODEL_REQUIRED))
    s.start()
    try:
        s._ai.ask = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI call expected"))
        s._on_utterance(WAV, TrackSource.MICROPHONE, s.session_id)
        asr_errors = [e for e in events if e["type"] == "asr_error"]
        assert asr_errors and asr_errors[0]["code"] == LOCAL_MODEL_REQUIRED
        assert "tidak dikirim ke cloud" in asr_errors[0]["message"]
        assert s.state == SessionState.LISTENING
    finally:
        s.stop()


# ------------------------------------------------------------------ interview practice flow

def test_practice_ignores_speech_until_a_question_is_asked(fake_mic_only, real_db):
    events = []
    s = _session("interview_practice", real_db, events)
    s.start()
    try:
        s._on_utterance(WAV, TrackSource.MICROPHONE, s.session_id)
        assert "interview_answer_draft" not in _types(events)
    finally:
        s.stop()


def test_practice_flow_is_explicit_start_answer_evaluate(fake_mic_only, real_db):
    events = []
    s = _session("interview_practice", real_db, events, asr=FakeASR(text="Saya memimpin tim"))
    s.start()
    evaluated = []
    try:
        s._ai.ask = lambda text, on_chunk=None: ("Ceritakan tantangan terbesar Anda.", None)
        q = s.start_practice(topic="backend", interview_type="behavioral")
        assert q == "Ceritakan tantangan terbesar Anda."
        assert any(e["type"] == "interview_question" for e in events)

        s._on_utterance(WAV, TrackSource.MICROPHONE, s.session_id)
        assert any(e["type"] == "interview_answer_draft" for e in events)
        assert not any(e["type"] == "interview_feedback" for e in events), "speech must not auto-evaluate"

        s._interview.evaluate_answer = lambda answer, on_chunk=None: (evaluated.append(answer) or "bagus")
        feedback = s.submit_practice_answer()
        assert feedback == "bagus"
        assert evaluated == ["Saya memimpin tim"]
    finally:
        s.stop()


def test_submit_without_answer_is_a_notice_not_an_evaluation(fake_mic_only, real_db):
    events = []
    s = _session("interview_practice", real_db, events)
    s._practice_question = "Pertanyaan?"
    s._interview.evaluate_answer = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no evaluation expected"))
    assert s.submit_practice_answer() == ""
    assert any(e["type"] == "notice" for e in events)


def test_empty_question_from_ai_is_not_recorded(fake_mic_only, real_db):
    s = _session("interview_practice", real_db, [])
    s._ai.ask = lambda text, on_chunk=None: ("   ", None)
    assert s.start_practice() == ""
    assert s._interview._practice.questions_asked == []


# ------------------------------------------------------------------ stop

def test_stop_releases_sources_and_ends_session(fake_mic_only, real_db, monkeypatch):
    from malva.meeting.engine import MeetingEngine
    monkeypatch.setattr(MeetingEngine, "finalize", lambda self: {})
    events = []
    s = _session("assistant", real_db, events)
    s.start()
    s.stop()
    assert s.state == SessionState.IDLE
    assert s._audio.active_sources == []
    assert "session_ended" in _types(events)
    time.sleep(0.05)  # let the background finaliser run once


def _wait_for_event(events, etype, text=None, timeout=3.0):
    import time as _t
    end = _t.time() + timeout
    while _t.time() < end:
        for e in list(events):
            if e.get("type") == etype and (text is None or e.get("text") == text):
                return e
        _t.sleep(0.01)
    return None


def test_live_partial_is_shown_but_never_stored(fake_mic_only, real_db):
    events = []
    s = _session("assistant", real_db, events, asr=FakeASR("sedang bicara"))
    s.start()
    try:
        s._on_partial(b"wav", TrackSource.MICROPHONE, s.session_id)
        evt = _wait_for_event(events, "transcript_partial", "sedang bicara")
        assert evt is not None and evt["source"] == "microphone"
        assert "transcript_segment" not in _types(events)
    finally:
        s.stop()


def test_partial_is_dropped_while_a_final_is_in_flight(fake_mic_only, real_db):
    import time as _t
    events = []
    s = _session("assistant", real_db, events, asr=FakeASR("tidak tampil"))
    s.start()
    try:
        s._final_inflight = 1
        s._on_partial(b"wav", TrackSource.MICROPHONE, s.session_id)
        _t.sleep(0.3)
        assert _wait_for_event(events, "transcript_partial", "tidak tampil", timeout=0.1) is None
        s._final_inflight = 0
    finally:
        s.stop()


def test_partial_never_uses_cloud_asr(fake_mic_only, real_db):
    import time as _t

    class CloudOnlyASR(FakeASR):
        is_local = False

        def __init__(self):
            super().__init__("x")
            self.calls = 0

        def transcribe(self, wav):
            self.calls += 1
            return super().transcribe(wav)

    events, asr = [], CloudOnlyASR()
    s = _session("assistant", real_db, events, asr=asr)
    s.start()
    try:
        s._on_partial(b"wav", TrackSource.MICROPHONE, s.session_id)
        _t.sleep(0.3)
        assert asr.calls == 0
    finally:
        s.stop()


def test_final_utterance_clears_live_text(fake_mic_only, real_db):
    events = []
    s = _session("voice_input", real_db, events, asr=FakeASR("kalimat akhir"))
    s.start()
    try:
        s._on_utterance(b"wav", TrackSource.MICROPHONE, s.session_id)
        assert _wait_for_event(events, "voice_input_text", "kalimat akhir") is not None
        clears = [e for e in events if e.get("type") == "transcript_partial" and e.get("text") == ""]
        assert clears, "the final result must clear the live line"
        assert s._final_inflight == 0
    finally:
        s.stop()
