"""
Local-first policy (audit P0 privacy) and Sleep/Focus rules.

These tests assert that NO remote call happens unless the user has opted in,
and that the opt-in is a persisted user choice, not something read from env.
"""

import numpy as np
import pytest

from malva.privacy.manager import PrivacyManager, is_remote_endpoint
from malva.shell.policy import parse_sleep_seconds, should_auto_sleep


class FakeDB:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_setting(self, key, default=""):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


# ------------------------------------------------------------------ endpoint classification

@pytest.mark.parametrize("url, remote", [
    ("", False),
    ("http://localhost:11434/v1/chat/completions", False),
    ("http://127.0.0.1:11434/v1", False),
    ("https://ollama.com/v1/chat/completions", True),
    ("https://api.example.org/x", True),
    ("not a url at all", True),        # fail closed
])
def test_endpoint_classification(url, remote):
    assert is_remote_endpoint(url) is remote


# ------------------------------------------------------------------ cloud opt-in

def test_cloud_is_off_by_default_even_if_env_points_to_cloud(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "https://ollama.com/v1/chat/completions")
    pm = PrivacyManager(db=FakeDB())
    assert pm.local_only is True
    assert pm.allows_cloud_asr() is False
    assert pm.allows_remote_endpoint("https://ollama.com/v1/chat/completions") is False


def test_opt_in_is_persisted_and_reloaded():
    db = FakeDB()
    pm = PrivacyManager(db=db)
    pm.set_cloud_processing(True)
    assert db.values["cloud_processing"] == "1"
    reloaded = PrivacyManager(db=db)
    assert reloaded.cloud_processing is True
    assert reloaded.allows_remote_endpoint("https://ollama.com/v1") is True


def test_opt_in_can_be_revoked():
    db = FakeDB({"cloud_processing": "1"})
    pm = PrivacyManager(db=db)
    pm.set_cloud_processing(False)
    assert PrivacyManager(db=db).local_only is True


def test_localhost_llm_always_allowed_without_cloud():
    pm = PrivacyManager(db=FakeDB())
    assert pm.allows_remote_endpoint("http://localhost:11434/v1") is True


def test_db_read_failure_fails_closed():
    class Broken:
        def get_setting(self, *a, **k):
            raise RuntimeError("db down")
    assert PrivacyManager(db=Broken()).cloud_processing is False


# ------------------------------------------------------------------ ASR never uploads silently

def _audio_stub():
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        wf.writeframes(np.zeros(1600, dtype=np.int16).tobytes())
    return buf.getvalue()


def test_asr_without_local_model_does_not_call_google(monkeypatch):
    from malva.asr import router as asr

    router = asr.ASRRouter(auto_load=False, privacy_manager=PrivacyManager(db=FakeDB()))
    calls = []
    monkeypatch.setattr(router, "_transcribe_cloud", lambda wav: calls.append(wav) or asr.ASRResult(full_text="x", language="id"))
    result = router.transcribe(_audio_stub())
    assert calls == []
    assert result.model_used == asr.LOCAL_MODEL_REQUIRED
    assert result.full_text == ""


def test_asr_local_failure_does_not_fall_back_to_cloud(monkeypatch):
    from malva.asr import router as asr

    class ExplodingModel:
        def transcribe(self, *a, **k):
            raise RuntimeError("cuda oom")

    router = asr.ASRRouter(auto_load=False, privacy_manager=PrivacyManager(db=FakeDB()))
    router._model = ExplodingModel()
    calls = []
    monkeypatch.setattr(router, "_transcribe_cloud", lambda wav: calls.append(wav))
    result = router.transcribe(_audio_stub())
    assert calls == []
    assert result.model_used == asr.LOCAL_FAILED


def test_asr_cloud_used_only_after_opt_in(monkeypatch):
    from malva.asr import router as asr

    pm = PrivacyManager(db=FakeDB({"cloud_processing": "1"}))
    router = asr.ASRRouter(auto_load=False, privacy_manager=pm)
    monkeypatch.setattr(router, "_transcribe_cloud",
                        lambda wav: asr.ASRResult(full_text="halo", language="id", model_used="cloud/google-stt"))
    assert router.transcribe(_audio_stub()).full_text == "halo"


def test_asr_without_privacy_manager_fails_closed(monkeypatch):
    from malva.asr import router as asr

    router = asr.ASRRouter(auto_load=False, privacy_manager=None)
    calls = []
    monkeypatch.setattr(router, "_transcribe_cloud", lambda wav: calls.append(wav))
    router.transcribe(_audio_stub())
    assert calls == []


# ------------------------------------------------------------------ LLM never calls remote silently

class RecordingClient:
    calls: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, *a, **k):
        RecordingClient.calls.append(("stream", a, k))
        raise RuntimeError("should not reach network")

    def post(self, *a, **k):
        RecordingClient.calls.append(("post", a, k))
        raise RuntimeError("should not reach network")


def test_llm_remote_endpoint_blocked_in_local_only(monkeypatch):
    from malva.ai import orchestrator as orc

    RecordingClient.calls = []
    monkeypatch.setattr(orc, "OLLAMA_URL", "https://ollama.com/v1/chat/completions")
    monkeypatch.setattr(orc.httpx, "Client", RecordingClient)

    ai = orc.AIOrchestrator("s1", "assistant", db=None, privacy_manager=PrivacyManager(db=FakeDB()))
    errors = []
    ai.on_error = errors.append
    text, action = ai.ask("halo")
    assert RecordingClient.calls == [], "no HTTP request may be made"
    assert text == "" and action is None
    assert errors and "AI lokal belum berjalan" in errors[0]


def test_llm_remote_endpoint_allowed_after_opt_in(monkeypatch):
    from malva.ai import orchestrator as orc

    RecordingClient.calls = []
    monkeypatch.setattr(orc, "OLLAMA_URL", "https://ollama.com/v1/chat/completions")
    monkeypatch.setattr(orc.httpx, "Client", RecordingClient)
    ai = orc.AIOrchestrator("s1", "assistant", db=None,
                            privacy_manager=PrivacyManager(db=FakeDB({"cloud_processing": "1"})))
    ai.ask("halo")  # network stub raises; orchestrator must still attempt the call
    assert RecordingClient.calls, "opted-in cloud request should be attempted"


def test_llm_missing_endpoint_is_reported(monkeypatch):
    from malva.ai import orchestrator as orc

    monkeypatch.setattr(orc, "OLLAMA_URL", "")
    ai = orc.AIOrchestrator("s1", "assistant", db=None, privacy_manager=PrivacyManager(db=FakeDB()))
    errors = []
    ai.on_error = errors.append
    ai.ask("halo")
    assert errors and "OLLAMA_URL" in errors[0]


# ------------------------------------------------------------------ Sleep / Focus policy

def _sleep(**kw):
    base = dict(mode="assistant", idle_seconds=999, threshold_seconds=60,
                focus_on=False, sleeping=False, paused=False)
    base.update(kw)
    return should_auto_sleep(**base)


def test_assistant_sleeps_after_idle_threshold():
    assert _sleep() is True
    assert _sleep(idle_seconds=10) is False


@pytest.mark.parametrize("mode", ["meeting", "interview_practice", "interview_notes", "voice_input"])
def test_protected_modes_never_auto_sleep(mode):
    assert _sleep(mode=mode) is False


def test_focus_blocks_auto_sleep():
    assert _sleep(focus_on=True) is False


def test_threshold_zero_disables_auto_sleep():
    assert _sleep(threshold_seconds=0) is False


def test_already_sleeping_or_paused_is_not_retriggered():
    assert _sleep(sleeping=True) is False
    assert _sleep(paused=True) is False


@pytest.mark.parametrize("raw, expected", [
    (None, 60.0), ("", 60.0), ("abc", 60.0), ("nan", 60.0),
    ("30", 30.0), ("-5", 0.0), ("0", 0.0),
])
def test_sleep_seconds_parsing(raw, expected):
    assert parse_sleep_seconds(raw) == expected
