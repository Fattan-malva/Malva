"""
Gemini Live transcription stream, tested with a fake SDK client (no network, no google-genai).

The message shapes mirror the documented ones: server_content.interim_input_transcription
(partial) and server_content.input_transcription (final), audio sent as audio/pcm;rate=16000.
"""

import asyncio
import threading
import time
from types import SimpleNamespace

from malva.asr.gemini_live import GeminiLiveStream, language_codes_for


class FakeTypes:
    @staticmethod
    def AudioTranscriptionConfig(**kwargs):
        return SimpleNamespace(**kwargs)

    @staticmethod
    def LiveConnectConfig(**kwargs):
        return SimpleNamespace(**kwargs)

    @staticmethod
    def Blob(data, mime_type):
        return SimpleNamespace(data=data, mime_type=mime_type)


def _msg(interim=None, final=None):
    content = SimpleNamespace(
        interim_input_transcription=SimpleNamespace(text=interim) if interim else None,
        input_transcription=SimpleNamespace(text=final) if final else None,
    )
    return SimpleNamespace(server_content=content)


class FakeSession:
    def __init__(self, messages):
        self._messages = messages
        self.sent = []
        self.ended = False

    async def send_realtime_input(self, audio=None, audio_stream_end=None):
        if audio is not None:
            self.sent.append(audio)
        if audio_stream_end:
            self.ended = True

    async def receive(self):
        for message in self._messages:
            yield message
        await asyncio.sleep(60)  # the server keeps the socket open until we close it


class _Connection:
    def __init__(self, session, config_log):
        self._session = session
        self._config_log = config_log

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class FakeClient:
    def __init__(self, session):
        self.session = session
        self.configs = []
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=self._connect))

    def _connect(self, model, config):
        self.configs.append((model, config))
        return _Connection(self.session, None)


def _wait(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_partial_and_final_text_are_delivered_and_audio_is_sent():
    partial, final, errors = [], [], []
    session = FakeSession([_msg(interim="sedang"), _msg(final="halo dunia")])
    client = FakeClient(session)
    stream = GeminiLiveStream(
        "microphone", api_key="k", model="gemini-3.5-transcribe-live",
        language_codes=["id-ID"], on_partial=partial.append, on_final=final.append,
        on_error=lambda code, msg: errors.append((code, msg)),
        client_factory=lambda: client, types_module=FakeTypes,
    )
    stream.start()
    stream.push(b"\x01\x00" * 512)
    assert _wait(lambda: final and session.sent), "final text and audio should arrive"
    stream.close()

    assert partial == ["sedang"]
    assert final == ["halo dunia"]
    assert errors == []
    model, config = client.configs[0]
    assert model == "gemini-3.5-transcribe-live"
    assert config.response_modalities == ["TEXT"]
    assert config.input_audio_transcription.language_codes == ["id-ID"]
    blob = session.sent[0]
    assert blob.mime_type == "audio/pcm;rate=16000"
    assert len(blob.data) == 1024


def test_automatic_language_sends_no_language_codes():
    session = FakeSession([])
    client = FakeClient(session)
    stream = GeminiLiveStream(
        "microphone", api_key="k", model="m", language_codes=[],
        on_partial=lambda t: None, on_final=lambda t: None, on_error=lambda c, m: None,
        client_factory=lambda: client, types_module=FakeTypes,
    )
    stream.start()
    assert _wait(lambda: client.configs)
    stream.close()
    _, config = client.configs[0]
    assert not hasattr(config.input_audio_transcription, "language_codes")  # absent: auto-detect


def test_push_after_close_is_ignored_and_queue_is_bounded():
    stream = GeminiLiveStream(
        "microphone", api_key="k", model="m", language_codes=[],
        on_partial=lambda t: None, on_final=lambda t: None, on_error=lambda c, m: None,
        client_factory=lambda: FakeClient(FakeSession([])), types_module=FakeTypes,
    )
    for _ in range(400):  # more than the queue can hold
        stream.push(b"\x00\x00")
    assert stream.dropped_chunks == 400 - 300
    stream.close()
    before = stream.dropped_chunks
    stream.push(b"\x00\x00")
    assert stream.dropped_chunks == before


def test_connection_failure_is_reported_not_raised():
    errors = []

    def broken():
        raise RuntimeError("tidak ada jaringan")

    stream = GeminiLiveStream(
        "microphone", api_key="k", model="m", language_codes=[],
        on_partial=lambda t: None, on_final=lambda t: None,
        on_error=lambda code, msg: errors.append((code, msg)),
        client_factory=broken, types_module=FakeTypes,
    )
    stream.start()
    assert _wait(lambda: errors)
    stream.close()
    assert errors[0][0] == "asr-failed" and "tidak ada jaringan" in errors[0][1]


def test_language_codes_mapping_for_settings():
    assert language_codes_for("id") == ["id-ID"]
    assert language_codes_for("auto") == []
