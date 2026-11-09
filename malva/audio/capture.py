"""
malva.audio.capture — Dual-track audio capture service.

Microphone and system audio are captured as ISOLATED tracks and never mixed.

Key guarantees (Blueprint §4, §8; audit P0.1–P0.3):
  * System audio is captured only from a WASAPI loopback endpoint opened via
    PyAudioWPatch. If that is unavailable, start() raises AudioDeviceError.
    It never falls back to the microphone / default input.
  * A track is only reported as active after its stream has actually opened.
    start() opens the stream synchronously before the capture thread begins.
  * Levels for the UI are real FFT band energies, tagged with their source.
  * Stereo loopback is downmixed to mono AFTER reading the real device format.
  * Pause keeps draining the stream (no stale buffers) and resets the bars.
"""

from __future__ import annotations

import io
import threading
import time
import uuid
import wave
from enum import Enum
from typing import Callable

import numpy as np

try:  # Standard PyAudio: microphone input.
    import pyaudio
except ImportError:  # pragma: no cover - only on machines without PyAudio
    pyaudio = None  # type: ignore[assignment]

try:  # PyAudioWPatch: WASAPI loopback for system audio.
    import pyaudiowpatch as pyaudio_wp
    _HAS_WPATCH = True
except ImportError:  # pragma: no cover
    pyaudio_wp = None  # type: ignore[assignment]
    _HAS_WPATCH = False

from malva.audio.analysis import SpectrumAnalyzer
from malva.audio.devices import (
    ERR_DEVICE_LOST,
    ERR_LOOPBACK_UNAVAILABLE,
    ERR_OPEN_FAILED,
    AudioDeviceError,
    DeviceInfo,
    find_default_microphone,
    find_loopback_device,
)

CHUNK        = 1024
FORMAT       = 8          # paInt16 (PortAudio constant; avoids importing pyaudio)
TARGET_RATE  = 16000

# VAD parameters (RMS on int16 scale; calibrated for laptop microphones)
SPEECH_THRESHOLD   = 45.0
SILENCE_THRESHOLD  = 25.0
SILENCE_DURATION   = 1.1     # seconds of silence that ends an utterance
MAX_RECORD_SECONDS = 30.0
PRE_BUFFER_CHUNKS  = 12      # ~0.4 s before speech onset
MIN_SPEECH_SECONDS = 0.3

LEVELS_MIN_INTERVAL = 1.0 / 25.0   # UI update cap: 25 Hz
MAX_CONSECUTIVE_READ_ERRORS = 25

# Live (partial) text: a snapshot of the utterance so far is handed to the session
# every PARTIAL_INTERVAL_SECONDS once PARTIAL_MIN_SECONDS of speech exists.
PARTIAL_INTERVAL_SECONDS = 1.0
PARTIAL_MIN_SECONDS      = 0.8
# Live text decodes only the last few seconds. Decoding the whole utterance every second
# costs more with each second of speech.
PARTIAL_WINDOW_SECONDS  = 8.0


class TrackSource(str, Enum):
    MICROPHONE   = "microphone"
    SYSTEM_AUDIO = "system_audio"


class TrackState(str, Enum):
    IDLE    = "idle"
    ACTIVE  = "active"
    PAUSED  = "paused"
    STOPPED = "stopped"
    ERROR   = "error"


class AudioTrack:
    """One isolated audio source (microphone OR system audio)."""

    def __init__(
        self,
        source: TrackSource,
        session_id: str,
        on_utterance: Callable[[bytes, "AudioTrack"], None],
        on_levels: Callable[["TrackSource", list[float]], None] | None = None,
        on_error: Callable[["TrackSource", str, str], None] | None = None,
        device_index: int | None = None,
        on_partial: Callable[[bytes, "AudioTrack"], None] | None = None,
    ):
        self.track_id     = uuid.uuid4().hex
        self.source       = source
        self.session_id   = session_id
        self.device_index = device_index
        self.device_name  = ""
        self.sample_rate  = TARGET_RATE
        self.channels     = 1
        self.state        = TrackState.IDLE
        self.error_code   = ""
        self.error_message = ""
        self.started_at: float | None = None

        self._on_utterance = on_utterance
        self._on_levels    = on_levels
        self._on_error     = on_error
        self._on_partial  = on_partial
        self._thread: threading.Thread | None = None
        self._stop_evt     = threading.Event()
        self._pa           = None
        self._stream       = None
        self._lock         = threading.Lock()

    # ------------------------------------------------------------------ control

    @property
    def is_active(self) -> bool:
        return self.state == TrackState.ACTIVE

    @property
    def is_running(self) -> bool:
        return self.state in (TrackState.ACTIVE, TrackState.PAUSED)

    def start(self) -> None:
        """Open the device, then start the capture thread. Raises AudioDeviceError."""
        with self._lock:
            if self.is_running:
                return
            self._open_device()           # raises before any state change
            self._stop_evt.clear()
            self.state = TrackState.ACTIVE
            self.started_at = time.time()
            self._thread = threading.Thread(
                target=self._capture_loop, daemon=True, name=f"track-{self.source.value}",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=3.0)
        self._close_device()
        if self.state != TrackState.ERROR:
            self.state = TrackState.STOPPED

    def pause(self) -> None:
        if self.state == TrackState.ACTIVE:
            self.state = TrackState.PAUSED

    def resume(self) -> None:
        if self.state == TrackState.PAUSED:
            self.state = TrackState.ACTIVE

    # ------------------------------------------------------------------ device

    def _open_device(self) -> None:
        if self.source == TrackSource.MICROPHONE:
            if pyaudio is None:
                raise AudioDeviceError(ERR_OPEN_FAILED, "PyAudio belum terpasang; mikrofon tidak bisa dibuka.")
            pa = pyaudio.PyAudio()
            try:
                if self.device_index is None:
                    dev = find_default_microphone(pa)
                else:
                    dev = DeviceInfo.from_pa(pa.get_device_info_by_index(self.device_index))
                stream, rate, channels = _open_input_stream(pa, dev)
            except Exception:
                pa.terminate()
                raise
        else:
            if not _HAS_WPATCH:
                raise AudioDeviceError(
                    ERR_LOOPBACK_UNAVAILABLE,
                    "PyAudioWPatch belum terpasang; audio sistem tidak bisa direkam.",
                )
            pa = pyaudio_wp.PyAudio()
            try:
                dev = find_loopback_device(pa)
                stream, rate, channels = _open_input_stream(pa, dev)
            except Exception:
                pa.terminate()
                raise

        self._pa, self._stream = pa, stream
        self.sample_rate, self.channels = rate, channels
        self.device_name = dev.name
        self.device_index = dev.index
        self.error_code = ""
        self.error_message = ""

    def _close_device(self) -> None:
        with self._lock:
            stream, pa = self._stream, self._pa
            self._stream, self._pa = None, None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------ capture loop

    def _capture_loop(self) -> None:
        analyzer = SpectrumAnalyzer(sample_rate=self.sample_rate)
        last_levels_at = 0.0
        was_paused = False
        pre_buffer: list[bytes] = []
        frames: list[bytes] = []
        speech_started = False
        above_count = 0
        silence_count = 0
        silence_needed = max(1, int(SILENCE_DURATION * self.sample_rate / CHUNK))
        min_frames = max(1, int(MIN_SPEECH_SECONDS * self.sample_rate / CHUNK))
        record_start = 0.0
        read_errors = 0
        last_partial_at = 0.0

        try:
            while not self._stop_evt.is_set():
                stream = self._stream
                if stream is None:
                    break

                try:
                    raw = stream.read(CHUNK, exception_on_overflow=False)
                    read_errors = 0
                except Exception as e:
                    read_errors += 1
                    if read_errors >= MAX_CONSECUTIVE_READ_ERRORS:
                        self._fail(ERR_DEVICE_LOST, f"Perangkat '{self.device_name}' terputus: {e}")
                        break
                    time.sleep(0.02)
                    continue

                if self.state == TrackState.PAUSED:
                    if not was_paused:
                        was_paused = True
                        pre_buffer.clear()
                        frames.clear()
                        speech_started = False
                        self._emit_levels(analyzer.reset(), force=True)
                    continue
                was_paused = False

                mono = _to_mono_int16(raw, self.channels)
                if mono.size == 0:
                    continue
                rms = float(np.sqrt(np.mean(mono ** 2)))

                now = time.time()
                if self._on_levels and now - last_levels_at >= LEVELS_MIN_INTERVAL:
                    last_levels_at = now
                    self._emit_levels(analyzer.process(mono))

                mono_bytes = mono.astype(np.int16).tobytes()

                if not speech_started:
                    pre_buffer.append(mono_bytes)
                    if len(pre_buffer) > PRE_BUFFER_CHUNKS:
                        pre_buffer.pop(0)
                    if rms > SPEECH_THRESHOLD:
                        above_count += 1
                        if above_count >= 2:
                            speech_started = True
                            frames = list(pre_buffer)
                            pre_buffer.clear()
                            record_start = time.time()
                            last_partial_at = record_start
                            above_count = 0
                            silence_count = 0
                    else:
                        above_count = 0
                    continue

                frames.append(mono_bytes)
                if self._on_partial is not None:
                    now_p = time.time()
                    if (now_p - last_partial_at >= PARTIAL_INTERVAL_SECONDS
                            and len(frames) * CHUNK >= PARTIAL_MIN_SECONDS * self.sample_rate):
                        last_partial_at = now_p
                        self._emit_partial(frames)
                elapsed = time.time() - record_start
                if rms < SILENCE_THRESHOLD:
                    silence_count += 1
                else:
                    silence_count = 0

                if silence_count >= silence_needed or elapsed >= MAX_RECORD_SECONDS:
                    if len(frames) >= min_frames:
                        wav_bytes = self._frames_to_wav(frames, self.sample_rate)
                        threading.Thread(
                            target=self._on_utterance, args=(wav_bytes, self), daemon=True,
                        ).start()
                    frames = []
                    speech_started = False
                    silence_count = 0
        finally:
            self._close_device()

    def _emit_partial(self, frames: list[bytes]) -> None:
        """Hand a snapshot of the speech so far to the session. Never raises into the capture loop."""
        try:
            window = max(1, int(PARTIAL_WINDOW_SECONDS * self.sample_rate / CHUNK))
            wav = self._frames_to_wav(list(frames[-window:]), self.sample_rate)
            self._on_partial(wav, self)
        except Exception as e:
            print(f"[audio] partial hand-off failed: {e}")

    def _emit_levels(self, levels: list[float], force: bool = False) -> None:
        if self._on_levels:
            try:
                self._on_levels(self.source, levels)
            except Exception as e:
                print(f"[audio/{self.source.value}] levels callback error: {e}")

    def _fail(self, code: str, message: str) -> None:
        self.state = TrackState.ERROR
        self.error_code = code
        self.error_message = message
        print(f"[audio/{self.source.value}] {code}: {message}")
        if self._on_error:
            try:
                self._on_error(self.source, code, message)
            except Exception as e:
                print(f"[audio/{self.source.value}] error callback failed: {e}")

    # ------------------------------------------------------------------ encoding

    @staticmethod
    def _frames_to_wav(frames: list[bytes], sample_rate: int) -> bytes:
        """Mono int16 PCM → WAV (resampled to 16 kHz when scipy is available)."""
        raw_pcm = b"".join(frames)
        if sample_rate != TARGET_RATE:
            try:
                import scipy.signal as sg
                arr = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
                raw_pcm = sg.resample_poly(arr, TARGET_RATE, sample_rate).astype(np.int16).tobytes()
                sample_rate = TARGET_RATE
            except Exception:
                pass
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_pcm)
        return buf.getvalue()


# ------------------------------------------------------------------ helpers

def _open_input_stream(pa, dev: DeviceInfo):
    """Open an input stream on `dev`, trying the device's own rate first."""
    rates: list[int] = []
    for r in (int(dev.default_sample_rate or 0), TARGET_RATE, 44100, 48000):
        if r and r not in rates:
            rates.append(r)
    channel_options: list[int] = [1]
    if dev.max_input_channels >= 2:
        channel_options = [min(dev.max_input_channels, 2), 1]

    last_error: Exception | None = None
    for ch in channel_options:
        for rate in rates:
            try:
                stream = pa.open(
                    format=FORMAT,
                    channels=ch,
                    rate=rate,
                    input=True,
                    input_device_index=dev.index,
                    frames_per_buffer=CHUNK,
                )
                return stream, rate, ch
            except Exception as e:
                last_error = e
    raise AudioDeviceError(
        ERR_OPEN_FAILED,
        f"Tidak bisa membuka '{dev.name}' (device {dev.index}): {last_error}",
    )


def _to_mono_int16(raw: bytes, channels: int) -> np.ndarray:
    arr = np.frombuffer(raw, dtype=np.int16)
    if channels > 1 and arr.size >= channels:
        arr = arr[: arr.size - (arr.size % channels)].reshape(-1, channels)
        arr = arr.astype(np.float32).mean(axis=1)
    else:
        arr = arr.astype(np.float32)
    return arr


class AudioEngine:
    """
    Owns the named tracks for one session and enforces source invariants
    (Blueprint §4): Voice Input may never receive system audio.
    """

    def __init__(
        self,
        session_id: str,
        mode: str,
        on_utterance: Callable[[bytes, TrackSource, str], None],
        on_levels: Callable[[TrackSource, list[float]], None] | None = None,
        on_error: Callable[[TrackSource, str, str], None] | None = None,
        db=None,
        on_partial: Callable[[bytes, TrackSource, str], None] | None = None,
    ):
        self.session_id    = session_id
        self.mode          = mode
        self._on_utterance = on_utterance
        self._on_partial   = on_partial
        self._on_levels    = on_levels
        self._on_error     = on_error
        self._db           = db
        self._tracks: dict[TrackSource, AudioTrack] = {}
        self._lock = threading.Lock()

    def set_levels_callback(self, fn) -> None:
        self._on_levels = fn
        for track in self._tracks.values():
            track._on_levels = fn

    def start_microphone(self, device_index: int | None = None) -> AudioTrack:
        return self._start_track(TrackSource.MICROPHONE, device_index)

    def start_system_audio(self, device_index: int | None = None) -> AudioTrack:
        if self.mode == "voice_input":
            raise ValueError("Voice Input tidak boleh menerima audio sistem (Blueprint §4).")
        return self._start_track(TrackSource.SYSTEM_AUDIO, device_index)

    def stop_all(self) -> None:
        with self._lock:
            tracks = list(self._tracks.values())
            self._tracks.clear()
        for track in tracks:
            track.stop()

    def stop_track(self, source: TrackSource) -> None:
        with self._lock:
            track = self._tracks.pop(source, None)
        if track:
            track.stop()

    def pause_all(self) -> None:
        for t in list(self._tracks.values()):
            t.pause()

    def resume_all(self) -> None:
        for t in list(self._tracks.values()):
            t.resume()

    @property
    def active_sources(self) -> list[TrackSource]:
        """Sources whose stream is open (active or paused). Errored tracks are excluded."""
        return [src for src, t in list(self._tracks.items()) if t.is_running]

    def source_states(self) -> dict[str, str]:
        return {src.value: t.state.value for src, t in list(self._tracks.items())}

    def get_track(self, source: TrackSource) -> AudioTrack | None:
        return self._tracks.get(source)

    def _start_track(self, source: TrackSource, device_index: int | None) -> AudioTrack:
        with self._lock:
            existing = self._tracks.get(source)
            if existing is not None and existing.is_running:
                return existing  # never create a duplicate stream

        def on_track_utterance(wav_bytes: bytes, track: AudioTrack) -> None:
            self._on_utterance(wav_bytes, track.source, self.session_id)

        def on_track_partial(wav_bytes: bytes, track: AudioTrack) -> None:
            if self._on_partial is not None:
                self._on_partial(wav_bytes, track.source, self.session_id)

        track = AudioTrack(
            source=source,
            session_id=self.session_id,
            on_utterance=on_track_utterance,
            on_levels=self._on_levels,
            on_error=self._on_error,
            device_index=device_index,
            on_partial=on_track_partial,
        )
        track.start()  # raises AudioDeviceError; nothing registered on failure

        if self._db:
            try:
                self._db.create_audio_track(
                    track_id=track.track_id,
                    session_id=self.session_id,
                    source_type=source.value,
                    device_name=track.device_name or "Unknown",
                    sample_rate=track.sample_rate,
                    channels=1,
                )
            except Exception as e:
                print(f"[audio] Failed to register track: {e}")

        with self._lock:
            old = self._tracks.get(source)
            self._tracks[source] = track
        if old is not None and old is not track:
            old.stop()
        return track
