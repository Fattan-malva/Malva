"""
malva.asr.gemini_live — Streaming transcription with the Gemini Live API (Blueprint §9).

One GeminiLiveStream per audio source. Each stream runs its own asyncio loop in a
background thread, so the capture thread only pushes bytes and never waits on the network.

Contract, verified against the Gemini Live transcription docs:
  * API version: v1beta. The Live API (BidiGenerateContent) is not served on v1, and
    google-genai 3.x defaults to v1; connecting there fails with HTTP 404 for every model.
  * Model: gemini-3.5-transcribe-live (response_modalities=["TEXT"], so the model never
    speaks back and no audio output is billed).
  * Input: raw 16-bit PCM, 16 kHz, mono, sent as audio/pcm;rate=16000 chunks.
  * server_content.interim_input_transcription  -> live partial text (may change).
  * server_content.input_transcription          -> final text for one speech turn.
  * language_codes (BCP-47) is optional. Empty means automatic detection.
  * A streaming session lasts at most 10 minutes, so the stream reconnects before that.

Audio that arrives while a reconnect is in progress is queued, not sent live. The queue
is bounded: if the network stalls, the oldest audio is dropped and counted.
"""

from __future__ import annotations

import asyncio
import collections
import re
import threading
import time
from typing import Any, Callable

from malva.asr.types import ASR_FAILED, ASR_REJECTED

MODEL_DEFAULT             = "gemini-3.5-transcribe-live"
LIVE_API_VERSION          = "v1beta"   # BidiGenerateContent is not served on v1
INPUT_RATE                = 16000
SESSION_ROTATE_SECONDS    = 9 * 60     # API limit is 10 minutes; rotate a minute early
MAX_QUEUED_CHUNKS         = 300        # about 19 s of 64 ms chunks
MAX_CONSECUTIVE_FAILURES  = 5
DRAIN_SECONDS             = 3.0        # wait for the last final result after end-of-stream


def language_codes_for(setting: str) -> list[str]:
    """Map the app's language setting to Gemini language_codes. Empty = automatic detection."""
    raw = (setting or "").strip()
    low = raw.lower()
    if low in ("", "auto"):
        return []
    if low == "id":
        return ["id-ID"]
    if low == "en":
        return ["en-US"]
    if "-" in raw:
        return [raw]              # already BCP-47, for example "ja-JP"
    return []


_REJECT_RE = re.compile(r"HTTP (400|401|403|404)\b")


def rejection_status(error: BaseException) -> str | None:
    """HTTP status when the server refused the request for good (wrong model or key), else None.

    Retrying these never helps, so the stream stops and says why.
    """
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if isinstance(code, int) and code in (400, 401, 403, 404):
        return str(code)
    match = _REJECT_RE.search(str(error))
    return match.group(1) if match else None


def rejection_message(status: str, model: str) -> str:
    if status == "404":
        return (f"Model transkripsi '{model}' tidak ditemukan untuk key ini (HTTP 404). "
                "Periksa GEMINI_ASR_MODEL di .env.")
    if status in ("401", "403"):
        return f"Key Gemini ditolak (HTTP {status}). Periksa GEMINI_API_KEY di .env."
    return f"Permintaan transkripsi ditolak (HTTP {status}). Periksa GEMINI_API_KEY dan GEMINI_ASR_MODEL."


def _text_of(obj: Any) -> str:
    value = getattr(obj, "text", None) if obj is not None else None
    return value.strip() if isinstance(value, str) else ""


class GeminiLiveStream:
    """Streams one audio source to Gemini and reports partial and final text."""

    def __init__(
        self,
        label: str,
        *,
        api_key: str,
        model: str,
        language_codes: list[str],
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
        on_error: Callable[[str, str], None],
        client_factory: Callable[[], Any] | None = None,
        types_module: Any | None = None,
        rotate_seconds: float = SESSION_ROTATE_SECONDS,
    ):
        self._label        = label
        self._api_key      = api_key
        self._model        = model
        self._codes        = list(language_codes)
        self._on_partial   = on_partial
        self._on_final     = on_final
        self._on_error     = on_error
        self._client_factory = client_factory
        self._types_module = types_module
        self._rotate       = rotate_seconds
        self._queue: collections.deque[bytes] = collections.deque(maxlen=MAX_QUEUED_CHUNKS)
        self._lock         = threading.Lock()
        self._closing      = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped_chunks = 0

    # ------------------------------------------------------------------ thread-safe API

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name=f"gemini-asr-{self._label}", daemon=True)
        self._thread.start()

    def push(self, pcm: bytes) -> None:
        """Called from the capture thread. Never blocks."""
        if not pcm or self._closing.is_set():
            return
        with self._lock:
            if len(self._queue) == self._queue.maxlen:
                self.dropped_chunks += 1
            self._queue.append(pcm)

    def close(self) -> None:
        self._closing.set()

    @property
    def closed(self) -> bool:
        return self._closing.is_set()

    # ------------------------------------------------------------------ worker thread

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as e:  # pragma: no cover - asyncio.run itself failed
            self._report_error(f"Transkripsi berhenti: {e}")
        finally:
            self._closing.set()

    def _pop(self) -> bytes | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

    async def _run(self) -> None:
        failures = 0
        while not self._closing.is_set():
            try:
                client = self._make_client()
                async with client.aio.live.connect(model=self._model, config=self._config()) as session:
                    failures = 0
                    await self._pump(session)
            except Exception as e:
                if self._closing.is_set():
                    break
                status = rejection_status(e)
                if status is not None:
                    self._safe(lambda m: self._on_error(ASR_REJECTED, m), rejection_message(status, self._model))
                    break
                failures += 1
                self._report_error(f"Koneksi transkripsi cloud gagal ({failures}/{MAX_CONSECUTIVE_FAILURES}): {e}")
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    break
                await asyncio.sleep(min(2 ** failures, 15))

    async def _pump(self, session: Any) -> None:
        """Send queued audio and receive results until the rotation deadline or close."""
        deadline = time.monotonic() + self._rotate

        async def send() -> None:
            while not self._closing.is_set() and time.monotonic() < deadline:
                chunk = self._pop()
                if chunk is None:
                    await asyncio.sleep(0.01)
                    continue
                await session.send_realtime_input(audio=self._blob(chunk))

        async def receive() -> None:
            async for message in session.receive():
                self._handle(message)

        send_task = asyncio.ensure_future(send())
        recv_task = asyncio.ensure_future(receive())
        try:
            done, _ = await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
            if send_task in done:
                send_task.result()  # re-raise a send failure so the caller reconnects
                if not self._closing.is_set():
                    await self._end_of_stream(session)
                    try:
                        await asyncio.wait_for(recv_task, timeout=DRAIN_SECONDS)
                    except asyncio.TimeoutError:
                        pass
                return
            send_task.cancel()
            recv_task.result()  # the server ended the stream; raising makes _run reconnect
            raise RuntimeError("server closed the transcription stream")
        finally:
            for task in (send_task, recv_task):
                if not task.done():
                    task.cancel()

    async def _end_of_stream(self, session: Any) -> None:
        try:
            await session.send_realtime_input(audio_stream_end=True)
        except Exception:
            pass  # the session is being rotated anyway

    def _handle(self, message: Any) -> None:
        content = getattr(message, "server_content", None)
        if content is None:
            return
        interim = _text_of(getattr(content, "interim_input_transcription", None))
        if interim:
            self._safe(self._on_partial, interim)
        final = _text_of(getattr(content, "input_transcription", None))
        if final:
            self._safe(self._on_final, final)

    # ------------------------------------------------------------------ SDK adapters

    def _types(self) -> Any:
        if self._types_module is not None:
            return self._types_module
        from google.genai import types  # imported lazily so tests run without the SDK
        return types

    def _make_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        from google import genai
        # google-genai 3.x defaults to v1, which has no Live API endpoint: the WebSocket
        # handshake is rejected with HTTP 404 even when the model and key are valid.
        return genai.Client(
            api_key=self._api_key,
            http_options=self._types().HttpOptions(api_version=LIVE_API_VERSION),
        )

    def _config(self) -> Any:
        t = self._types()
        transcription = (t.AudioTranscriptionConfig(language_codes=self._codes)
                         if self._codes else t.AudioTranscriptionConfig())
        return t.LiveConnectConfig(response_modalities=["TEXT"], input_audio_transcription=transcription)

    def _blob(self, chunk: bytes) -> Any:
        return self._types().Blob(data=chunk, mime_type=f"audio/pcm;rate={INPUT_RATE}")

    # ------------------------------------------------------------------ reporting

    def _report_error(self, message: str) -> None:
        self._safe(lambda m: self._on_error(ASR_FAILED, m), message)

    @staticmethod
    def _safe(fn: Callable[[str], None], text: str) -> None:
        try:
            fn(text)
        except Exception as e:
            print(f"[asr] callback error: {e}")
