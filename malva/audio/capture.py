"""
malva.audio.capture — Dual-track audio capture service.

Captures microphone and system audio (Stereo Mix / WASAPI loopback)
as ISOLATED tracks. Never mixes them.

Features:
  - Real-time 5-band spectrum audio level callback for the UI
  - Multi-sample rate mic fallback (16000, 44100, 48000 Hz)
  - Pre-speech audio buffer so words are not clipped at start
  - Resilient VAD with configurable sensitivity
  - Non-blocking utterance delivery to ASR worker
"""

from __future__ import annotations

import io
import threading
import time
import uuid
import wave
from enum import Enum
from pathlib import Path
from typing import Callable

import numpy as np
import pyaudio

try:
    import pyaudiowpatch as pyaudio_sys
    _HAS_WPATCH = True
except ImportError:
    import pyaudio as pyaudio_sys  # type: ignore
    _HAS_WPATCH = False

CHUNK       = 1024
FORMAT      = pyaudio.paInt16
CHANNELS    = 1
TARGET_RATE = 16000

# VAD parameters (calibrated for laptop microphones)
SPEECH_THRESHOLD   = 45.0    # RMS trigger threshold (lowered from 65 for better sensitivity)
SILENCE_THRESHOLD  = 25.0    # RMS silence threshold (lowered from 35)
SILENCE_DURATION   = 1.1     # Seconds of silence to finalize utterance
MAX_RECORD_SECONDS = 30.0
PRE_BUFFER_CHUNKS  = 12      # ~0.4s pre-speech audio buffer


class TrackSource(str, Enum):
    MICROPHONE   = "microphone"
    SYSTEM_AUDIO = "system_audio"


class TrackState(str, Enum):
    IDLE     = "idle"
    ACTIVE   = "active"
    PAUSED   = "paused"
    STOPPED  = "stopped"
    ERROR    = "error"


class AudioTrack:
    """Single isolated audio source track (mic OR system audio)."""

    def __init__(
        self,
        source: TrackSource,
        session_id: str,
        on_utterance: Callable[[bytes, "AudioTrack"], None],
        on_levels: Callable[[list[float]], None] | None = None,
        device_index: int | None = None,
        device_name: str = "",
    ):
        self.track_id     = uuid.uuid4().hex
        self.source       = source
        self.session_id   = session_id
        self.device_index = device_index
        self.device_name  = device_name
        self.state        = TrackState.IDLE
        self.started_at: float | None = None
        self._on_utterance = on_utterance
        self._on_levels   = on_levels
        self._thread: threading.Thread | None = None
        self._stop_evt    = threading.Event()
        self._pa: pyaudio.PyAudio | None = None

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        if self.state == TrackState.ACTIVE:
            return
        self._stop_evt.clear()
        self.state = TrackState.ACTIVE
        self.started_at = time.time()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name=f"track-{self.source.value}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        self.state = TrackState.STOPPED
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def pause(self) -> None:
        self.state = TrackState.PAUSED

    def resume(self) -> None:
        if self.state == TrackState.PAUSED:
            self.state = TrackState.ACTIVE

    @property
    def is_active(self) -> bool:
        return self.state == TrackState.ACTIVE

    # ------------------------------------------------------------------ capture loop

    def _open_stream(self, pa: pyaudio.PyAudio, dev_idx: int | None):
        """Try opening at 16000, 44100, 48000 Hz for maximum device compatibility."""
        rates_to_try = (TARGET_RATE, 44100, 48000)
        for rate in rates_to_try:
            try:
                stream = pa.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=rate,
                    input=True,
                    input_device_index=dev_idx,
                    frames_per_buffer=CHUNK,
                )
                return stream, rate
            except Exception:
                continue
        return None, TARGET_RATE

    def _capture_loop(self) -> None:
        self._pa = pyaudio.PyAudio()
        dev_idx = self._resolve_device_index()
        stream, actual_rate = self._open_stream(self._pa, dev_idx)

        if stream is None:
            self.state = TrackState.ERROR
            print(f"[audio/{self.source.value}] Gagal membuka stream mic pada device {dev_idx}")
            if self._pa:
                self._pa.terminate()
            return

        frames: list[bytes] = []
        pre_buffer: list[bytes] = []
        speech_started = False
        above_count = 0
        silence_count = 0
        silence_needed = int(SILENCE_DURATION * actual_rate / CHUNK)
        min_frames = int(0.3 * actual_rate / CHUNK)
        chunk_idx = 0
        record_start = 0.0

        try:
            while not self._stop_evt.is_set():
                if self.state == TrackState.PAUSED:
                    time.sleep(0.08)
                    continue

                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except Exception:
                    continue

                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0
                chunk_idx += 1
                
                # Debug: print RMS every 50 chunks to monitor audio levels
                if chunk_idx % 50 == 0:
                    print(f"[audio/{self.source.value}] RMS: {rms:.1f}")

                # Send 5-bar spectrum levels to UI (both mic and system audio)
                if self._on_levels:
                    if len(arr) >= 64:
                        # FFT-based frequency bands (5 bands: sub, low, mid, high, ultra)
                        fft = np.fft.rfft(arr * np.hanning(len(arr)))
                        magnitudes = np.abs(fft)
                        band_size = len(magnitudes) // 5
                        levels = []
                        for i in range(5):
                            start = i * band_size
                            end = (i + 1) * band_size if i < 4 else len(magnitudes)
                            band = magnitudes[start:end]
                            if len(band) == 0:
                                levels.append(6.0)
                                continue
                            avg = float(np.mean(band))
                            lvl = min(32.0, 6.0 + np.sqrt(avg) * 2.2)
                            levels.append(round(lvl, 1))
                    else:
                        # Fallback to RMS slices
                        seg = max(1, len(arr) // 5)
                        levels = []
                        for i in range(5):
                            ch = arr[i * seg:(i + 1) * seg]
                            if len(ch) == 0:
                                levels.append(6.0)
                                continue
                            r = float(np.sqrt(np.mean(ch ** 2)))
                            lvl = min(32.0, 6.0 + np.sqrt(r) * 2.2)
                            levels.append(round(lvl, 1))
                    self._on_levels(levels)

                # VAD State Machine
                if not speech_started:
                    pre_buffer.append(data)
                    if len(pre_buffer) > PRE_BUFFER_CHUNKS:
                        pre_buffer.pop(0)

                    if rms > SPEECH_THRESHOLD:
                        above_count += 1
                        if above_count >= 2:
                            speech_started = True
                            frames = list(pre_buffer)
                            pre_buffer.clear()
                            record_start = time.time()
                            above_count = 0
                            silence_count = 0
                            print(f"[audio/{self.source.value}] Speech detected! RMS: {rms:.1f}")
                    else:
                        above_count = 0
                else:
                    frames.append(data)
                    elapsed = time.time() - record_start

                    if rms < SILENCE_THRESHOLD:
                        silence_count += 1
                        if silence_count >= silence_needed or elapsed >= MAX_RECORD_SECONDS:
                            if len(frames) >= min_frames:
                                print(f"[audio/{self.source.value}] Utterance complete: {elapsed:.1f}s, {len(frames)} frames")
                                wav_bytes = self._frames_to_wav(frames, actual_rate)
                                threading.Thread(
                                    target=self._on_utterance,
                                    args=(wav_bytes, self),
                                    daemon=True,
                                ).start()
                            frames.clear()
                            speech_started = False
                            silence_count = 0
                    else:
                        silence_count = 0
                        if elapsed >= MAX_RECORD_SECONDS:
                            if len(frames) >= min_frames:
                                wav_bytes = self._frames_to_wav(frames, actual_rate)
                                threading.Thread(
                                    target=self._on_utterance,
                                    args=(wav_bytes, self),
                                    daemon=True,
                                ).start()
                            frames.clear()
                            speech_started = False
                            silence_count = 0
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            if self._pa:
                try:
                    self._pa.terminate()
                except Exception:
                    pass

    def _resolve_device_index(self) -> int | None:
        if self.device_index is not None:
            return self.device_index
        if self.source == TrackSource.SYSTEM_AUDIO:
            return self._find_system_audio_device()
        return None  # Default input for microphone

    def _find_system_audio_device(self) -> int | None:
        """Find WASAPI loopback device via pyaudiowpatch."""
        if not _HAS_WPATCH:
            print(f"[audio/{self.source.value}] pyaudiowpatch not available")
            return None
            
        try:
            import pyaudiowpatch as pa_wp
            pa_local = pa_wp.PyAudio()
            try:
                # Get default output device for loopback
                default_output = pa_local.get_default_output_device_info()
                loopback_info = pa_local.get_loopback_device_info(default_output["index"])
                self.device_name = loopback_info["name"]
                device_idx = loopback_info["index"]
                pa_local.terminate()
                print(f"[audio/{self.source.value}] Found WASAPI loopback: {self.device_name} (device {device_idx})")
                return device_idx
            except Exception as e:
                print(f"[audio/{self.source.value}] get_loopback_device_info failed: {e}")
                pa_local.terminate()
                
                # Fallback to legacy name search
                pa_legacy = pyaudio.PyAudio()
                count = pa_legacy.get_device_count()
                print(f"[audio/{self.source.value}] Searching {count} devices for Stereo Mix/Loopback...")
                for i in range(count):
                    try:
                        info = pa_legacy.get_device_info_by_index(i)
                        name: str = info.get("name", "").lower()
                        max_in = info.get("maxInputChannels", 0)
                        if max_in > 0 and ("stereo mix" in name or "loopback" in name):
                            self.device_name = info.get("name", "Stereo Mix")
                            pa_legacy.terminate()
                            print(f"[audio/{self.source.value}] Found via name search: {self.device_name} (device {i})")
                            return i
                    except Exception:
                        continue
                pa_legacy.terminate()
                print(f"[audio/{self.source.value}] No system audio device found")
                return None
        except Exception as e:
            print(f"[audio/{self.source.value}] System audio detection error: {e}")
            return None

    def _frames_to_wav(self, frames: list[bytes], sample_rate: int) -> bytes:
        """Convert raw PCM frames to WAV bytes (resampled to 16 kHz if necessary)."""
        raw_pcm = b"".join(frames)
        if sample_rate != TARGET_RATE:
            try:
                import scipy.signal as sg
                arr = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
                resampled = sg.resample_poly(arr, TARGET_RATE, sample_rate).astype(np.int16)
                raw_pcm = resampled.tobytes()
                sample_rate = TARGET_RATE
            except Exception:
                pass

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_pcm)
        return buf.getvalue()


class AudioEngine:
    """
    Manages multiple named AudioTracks for a session.
    Enforces audio-source invariants from Blueprint §4 and §8.
    """

    def __init__(
        self,
        session_id: str,
        mode: str,
        on_utterance: Callable[[bytes, TrackSource, str], None],
        on_levels: Callable[[list[float]], None] | None = None,
        db = None,
    ):
        self.session_id    = session_id
        self.mode          = mode
        self._on_utterance = on_utterance
        self._on_levels    = on_levels
        self._db           = db
        self._tracks: dict[TrackSource, AudioTrack] = {}

    def set_levels_callback(self, fn: Callable[[list[float]], None] | None) -> None:
        self._on_levels = fn
        for track in self._tracks.values():
            track._on_levels = fn

    def start_microphone(self, device_index: int | None = None) -> AudioTrack:
        return self._start_track(TrackSource.MICROPHONE, device_index)

    def start_system_audio(self, device_index: int | None = None) -> AudioTrack:
        if self.mode == "voice_input":
            raise ValueError("Voice Input mode must not receive system audio (Blueprint §4).")
        return self._start_track(TrackSource.SYSTEM_AUDIO, device_index)

    def stop_all(self) -> None:
        for track in list(self._tracks.values()):
            track.stop()
        self._tracks.clear()

    def stop_track(self, source: TrackSource) -> None:
        t = self._tracks.pop(source, None)
        if t:
            t.stop()

    def pause_all(self) -> None:
        for t in self._tracks.values():
            t.pause()

    def resume_all(self) -> None:
        for t in self._tracks.values():
            t.resume()

    @property
    def active_sources(self) -> list[TrackSource]:
        return [src for src, t in self._tracks.items() if t.is_active]

    def get_track(self, source: TrackSource) -> AudioTrack | None:
        return self._tracks.get(source)

    def _start_track(self, source: TrackSource, device_index: int | None) -> AudioTrack:
        if source in self._tracks:
            self._tracks[source].stop()

        def on_track_utterance(wav_bytes: bytes, track: AudioTrack) -> None:
            self._on_utterance(wav_bytes, track.source, self.session_id)

        track = AudioTrack(
            source=source,
            session_id=self.session_id,
            on_utterance=on_track_utterance,
            on_levels=self._on_levels,
            device_index=device_index,
        )
        # Register before capture starts; an utterance can finish on another thread.
        if self._db:
            try:
                self._db.create_audio_track(
                    track_id=track.track_id,
                    session_id=self.session_id,
                    source_type=source.value,
                    device_name=track.device_name or "Unknown",
                    sample_rate=16000,
                    channels=1,
                )
            except Exception as e:
                print(f"[audio] Failed to register track: {e}")
        self._tracks[source] = track
        track.start()
        return track
