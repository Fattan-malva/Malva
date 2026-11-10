"""
Cloud policy (CLOUD_ENABLED), cloud ASR gating, approval rules, and Sleep/Focus rules.

Cloud is approved by product decision (Blueprint §3). These tests check that the single
switch works and that a disabled cloud or a missing key blocks every remote call.
"""

import pytest

from malva.asr import types as asr_types
from malva.asr.gemini_live import language_codes_for
from malva.asr.service import ASRService
from malva.desktop import gateway
from malva.privacy.manager import PrivacyManager, cloud_enabled_from_env
from malva.shell.policy import parse_sleep_seconds, should_auto_sleep, voice_decision


class FakeDB:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_setting(self, key, default=""):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value

    def log_tool_action(self, **kwargs):
        self.values.setdefault("_audit", []).append(kwargs)


# ------------------------------------------------------------------ CLOUD_ENABLED switch

@pytest.mark.parametrize("raw, enabled", [
    (None, True), ("", True), ("true", True), ("1", True),
    ("false", False), ("FALSE", False), ("0", False), ("no", False), ("off", False),
])
def test_cloud_switch_defaults_to_enabled(monkeypatch, raw, enabled):
    if raw is None:
        monkeypatch.delenv("CLOUD_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CLOUD_ENABLED", raw)
    assert cloud_enabled_from_env() is enabled
    assert PrivacyManager().allows_cloud() is enabled


def test_privacy_status_reports_cloud_enabled(monkeypatch):
    monkeypatch.setenv("CLOUD_ENABLED", "false")
    status = PrivacyManager().get_status()
    assert status["cloud_enabled"] is False
    assert "cloud_processing" not in status


# ------------------------------------------------------------------ ASR gating

def _service(privacy, key="k-test", language="id"):
    return ASRService(privacy=privacy, api_key=key, language_getter=lambda: language)


def test_asr_without_key_reports_not_configured_and_opens_nothing(monkeypatch):
    monkeypatch.setenv("CLOUD_ENABLED", "true")
    errors = []
    stream = _service(PrivacyManager(), key="").open_stream(
        "microphone", on_partial=lambda t: None, on_final=lambda t: None,
        on_error=lambda code, msg: errors.append(code))
    assert stream is None
    assert errors == [asr_types.ASR_NOT_CONFIGURED]


def test_asr_with_cloud_disabled_opens_nothing(monkeypatch):
    monkeypatch.setenv("CLOUD_ENABLED", "false")
    errors = []
    stream = _service(PrivacyManager()).open_stream(
        "microphone", on_partial=lambda t: None, on_final=lambda t: None,
        on_error=lambda code, msg: errors.append(code))
    assert stream is None
    assert errors == [asr_types.ASR_CLOUD_DISABLED]


def test_asr_with_key_and_cloud_starts_a_stream(monkeypatch):
    from malva.asr import gemini_live
    monkeypatch.setenv("CLOUD_ENABLED", "true")
    started = []
    monkeypatch.setattr(gemini_live.GeminiLiveStream, "start", lambda self: started.append(self._codes))
    stream = _service(PrivacyManager(), language="id").open_stream(
        "microphone", on_partial=lambda t: None, on_final=lambda t: None, on_error=lambda c, m: None)
    assert stream is not None
    assert started == [["id-ID"]]


def test_asr_status_shows_reason_when_blocked(monkeypatch):
    monkeypatch.setenv("CLOUD_ENABLED", "true")
    status = _service(PrivacyManager(), key="").status()
    assert status["ready"] is False and status["configured"] is False
    assert "GEMINI_API_KEY" in status["reason"]


@pytest.mark.parametrize("setting, codes", [
    ("auto", []), ("", []), ("id", ["id-ID"]), ("en", ["en-US"]), ("ja-JP", ["ja-JP"]), ("xx", []),
])
def test_language_setting_maps_to_gemini_codes(setting, codes):
    assert language_codes_for(setting) == codes


# ------------------------------------------------------------------ LLM and web honour the switch

def test_llm_makes_no_http_call_when_cloud_disabled(monkeypatch):
    from malva.ai import orchestrator as orc

    class NoHttp:
        def __init__(self, *a, **k):
            raise AssertionError("no HTTP request may be made while CLOUD_ENABLED=false")

    monkeypatch.setenv("CLOUD_ENABLED", "false")
    monkeypatch.setattr(orc.httpx, "Client", NoHttp)
    monkeypatch.setattr(orc, "CLOUDFLARE_URL", "https://api.cloudflare.com/client/v4/accounts/x/ai/v1/chat/completions")
    monkeypatch.setattr(orc, "CLOUDFLARE_API_TOKEN", "k")
    ai = orc.AIOrchestrator("s1", "assistant", db=None, privacy_manager=PrivacyManager())
    errors = []
    ai.on_error = errors.append
    ai.ask("halo")
    assert errors and "CLOUD_ENABLED" in errors[0]


def test_web_search_blocked_when_cloud_disabled(monkeypatch):
    from malva.desktop.tools import web_backend

    class NoHttp:
        def __init__(self, *a, **k):
            raise AssertionError("no HTTP request may be made while cloud is disabled")

    monkeypatch.setattr(web_backend.httpx, "Client", NoHttp)
    web_backend.set_cloud_gate(lambda: False)
    try:
        with pytest.raises(web_backend.WebError, match="CLOUD_ENABLED"):
            web_backend.web_search("berita hari ini")
    finally:
        web_backend.set_cloud_gate(lambda: False)


def test_web_search_reaches_backend_when_cloud_enabled(monkeypatch):
    from malva.desktop.tools import web_backend

    monkeypatch.setattr(web_backend, "_ddg_search", lambda q, n: [{"title": "t", "url": "https://x", "content": "c"}])
    web_backend.set_cloud_gate(lambda: True)
    try:
        out = web_backend.web_search("halo")
    finally:
        web_backend.set_cloud_gate(lambda: False)
    assert out["source"] == "duckduckgo" and out["results"]


# ------------------------------------------------------------------ approval: delete only

@pytest.mark.parametrize("tool, args, needs", [
    ("list_windows", {}, False),
    ("browser_close_tab", {"title": "Gmail"}, False),
    ("close_browser", {}, False),
    ("type_text", {"text": "halo dunia"}, False),
    ("run_command", {"command": "dir"}, False),
    ("delete_file", {"path": "C:/x.txt"}, True),
    ("run_command", {"command": "del C:/x.txt"}, True),
    ("type_text", {"text": "delete the file"}, True),
])
def test_only_destructive_calls_need_approval(tool, args, needs):
    assert gateway.requires_approval(tool, args) is needs


def test_destructive_call_without_approval_is_refused(monkeypatch):
    ran = []
    monkeypatch.setattr(gateway.DesktopGateway, "_dispatch", lambda self, t, a: ran.append(t) or {})
    gw = gateway.DesktopGateway(session_id="s1", db=FakeDB(), tools_enabled=True)
    result = gw.run("delete_file", {"path": "C:/x.txt"})
    assert result["ok"] is False and ran == []


def test_destructive_call_runs_once_approved(monkeypatch):
    ran = []
    monkeypatch.setattr(gateway.DesktopGateway, "_dispatch", lambda self, t, a: ran.append(t) or {"done": True})
    gw = gateway.DesktopGateway(session_id="s1", db=FakeDB(), tools_enabled=True)
    result = gw.run("delete_file", {"path": "C:/x.txt"}, approved=True)
    assert result["ok"] is True and ran == ["delete_file"]


def test_non_destructive_call_runs_without_approval(monkeypatch):
    ran = []
    monkeypatch.setattr(gateway.DesktopGateway, "_dispatch", lambda self, t, a: ran.append(t) or {})
    gw = gateway.DesktopGateway(session_id="s1", db=FakeDB(), tools_enabled=True)
    assert gw.run("close_browser", {})["ok"] is True
    assert ran == ["close_browser"]


@pytest.mark.parametrize("text, decision", [
    ("setuju", "approve"), ("Setuju.", "approve"), ("ya hapus", "approve"),
    ("batal", "reject"), ("Tidak jadi!", "reject"), ("saya setuju dengan rencana ini", None),
    ("hapus file itu", None), ("", None),
])
def test_voice_decision_needs_the_whole_phrase(text, decision):
    assert voice_decision(text) == decision


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


