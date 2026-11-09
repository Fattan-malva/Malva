"""
malva.asr.router — ASR Model Router (Blueprint §9).

Supports:
  - faster-whisper (local, CPU/GPU)
  - Google STT via SpeechRecognition (cloud fallback)

Features:
  - Non-blocking startup (does not hang the UI on first launch)
  - Cache inspection for HuggingFace models
  - Background asynchronous model downloading and hot-reloading
  - Dynamic auto-language detection per-segment
"""

from __future__ import annotations

import io
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ------------------------------------------------------------------ data types

@dataclass
class ASRSegment:
    text:       str
    language:   str
    start_ms:   float = 0.0
    end_ms:     float = 0.0
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": self.confidence,
        }


@dataclass
class ASRResult:
    full_text:   str
    language:    str                   # dominant detected language
    segments:    list[ASRSegment] = field(default_factory=list)
    model_used:  str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "full_text": self.full_text,
            "language": self.language,
            "segments": [s.to_dict() for s in self.segments],
            "model_used": self.model_used,
            "duration_ms": self.duration_ms,
        }


# Sentinel values for ASRResult.model_used when no transcript was produced.
# The session reads these to tell the user what is missing.
LOCAL_MODEL_REQUIRED = "local-model-required"
LOCAL_FAILED         = "local-failed"

# ------------------------------------------------------------------ model metadata

AVAILABLE_MODELS = {
    "tiny":   {"name": "Whisper Tiny",   "size_mb": 75,   "desc": "Paling cepat, hemat RAM"},
    "base":   {"name": "Whisper Base",   "size_mb": 145,  "desc": "Cepat dan ringan"},
    "small":  {"name": "Whisper Small",  "size_mb": 480,  "desc": "Akurat & seimbang (Rekomendasi)", "recommended": True},
    "medium": {"name": "Whisper Medium", "size_mb": 1500, "desc": "Presisi tinggi (lebih berat di CPU)"},
}


def get_hf_cache_dir() -> Path:
    """Return HuggingFace hub cache directory."""
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_model_cached(model_size: str) -> bool:
    """Check if model files exist in HuggingFace cache."""
    cache_dir = get_hf_cache_dir()
    repo_folder = cache_dir / f"models--Systran--faster-whisper-{model_size}"
    if not repo_folder.exists():
        return False
    # Check for model.bin in snapshots
    snapshots_dir = repo_folder / "snapshots"
    if snapshots_dir.exists():
        for snap in snapshots_dir.iterdir():
            if snap.is_dir() and (snap / "model.bin").exists():
                return True
    return False


# ------------------------------------------------------------------ router

class ASRRouter:
    """
    Routes audio to the best available ASR model.
    Falls back to Google STT when faster-whisper is unavailable or loading.
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "auto",
        auto_load: bool = True,
        privacy_manager = None,
    ):
        self.model_size    = model_size
        self.device        = device
        self.compute_type  = compute_type
        self.language      = language   # "auto" or BCP-47
        self._privacy      = privacy_manager
        self._model        = None
        self._model_name   = ""
        self._load_error   = ""
        self._is_loading   = False
        self._lock         = threading.Lock()
        self._status_callback: Callable[[dict], None] | None = None

        if auto_load:
            # If model is already cached, load in background so startup remains instant
            if is_model_cached(self.model_size):
                threading.Thread(target=self._load_worker, args=(self.model_size,), daemon=True).start()
            else:
                self._load_error = "Model belum diunduh (tersedia di Pengaturan)"

    def set_status_callback(self, cb: Callable[[dict], None]) -> None:
        self._status_callback = cb

    def _notify_status(self, status: str, message: str = "") -> None:
        if self._status_callback:
            try:
                self._status_callback({
                    "status": status,
                    "message": message,
                    "model": self.model_size,
                    "info": self.model_info,
                })
            except Exception:
                pass

    # ------------------------------------------------------------------ background load / download

    def load_model_async(self, model_size: str) -> None:
        """Download (if needed) and load model in background thread."""
        with self._lock:
            if self._is_loading:
                return
            self._is_loading = True
            self.model_size = model_size

        threading.Thread(target=self._load_worker, args=(model_size,), daemon=True).start()

    def _load_worker(self, model_size: str) -> None:
        self._notify_status("loading", f"Memuat model {model_size}…")
        try:
            from faster_whisper import WhisperModel  # type: ignore

            cached = is_model_cached(model_size)
            if not cached:
                self._notify_status("downloading", f"Mengunduh model {model_size} dari Hugging Face…")

            # Load model
            model = WhisperModel(
                model_size,
                device=self.device,
                compute_type=self.compute_type,
            )

            with self._lock:
                self._model = model
                self.model_size = model_size
                self._model_name = f"faster-whisper/{model_size}"
                self._load_error = ""
                self._is_loading = False

            print(f"[asr] loaded {self._model_name} on {self.device}")
            self._notify_status("ready", f"Model {model_size} siap digunakan (Lokal)")
        except Exception as e:
            with self._lock:
                self._model = None
                self._load_error = str(e)
                self._is_loading = False
            print(f"[asr] faster-whisper error: {e}")
            self._notify_status("error", f"Gagal memuat {model_size}: {e}")

    def reload(self, model_size: str | None = None, device: str | None = None,
               compute_type: str | None = None) -> None:
        """Hot-swap the model."""
        if device:
            self.device = device
        if compute_type:
            self.compute_type = compute_type
        target_size = model_size or self.model_size
        self.load_model_async(target_size)

    @property
    def is_local(self) -> bool:
        return self._model is not None

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    @property
    def model_info(self) -> dict:
        if self._model_name:
            default_label = self._model_name
        elif self._is_loading:
            default_label = "Sedang memuat…"
        elif self._cloud_allowed():
            default_label = "Cloud (Google STT, diizinkan)"
        else:
            default_label = "Belum ada model lokal"
        return {
            "model": default_label,
            "cloud_allowed": self._cloud_allowed(),
            "model_size": self.model_size,
            "device": self.device,
            "language_setting": self.language,
            "is_local": self.is_local,
            "is_loading": self._is_loading,
            "load_error": self._load_error,
        }

    def get_models_catalog(self) -> list[dict]:
        """Return catalog of models with local cache status."""
        catalog = []
        for size, info in AVAILABLE_MODELS.items():
            cached = is_model_cached(size)
            active = (self._model is not None and self.model_size == size)
            catalog.append({
                "id": size,
                "name": info["name"],
                "size_mb": info["size_mb"],
                "desc": info["desc"],
                "recommended": info.get("recommended", False),
                "is_cached": cached,
                "is_active": active,
                "is_loading": (self._is_loading and self.model_size == size),
            })
        return catalog

    # ------------------------------------------------------------------ transcribe

    def transcribe(self, wav_bytes: bytes) -> ASRResult:
        """Transcribe WAV audio. Uses faster-whisper if loaded, else Google STT."""
        t0 = time.time()
        with self._lock:
            local_model = self._model

        if local_model is not None:
            result = self._transcribe_local(local_model, wav_bytes)
        else:
            if self._cloud_allowed():
                result = self._transcribe_cloud(wav_bytes)
            else:
                # Local-first: never upload audio without explicit user opt-in.
                result = ASRResult(full_text="", language="und", model_used=LOCAL_MODEL_REQUIRED)

        result.duration_ms = (time.time() - t0) * 1000
        return result

    def _cloud_allowed(self) -> bool:
        """Fail closed: without a privacy manager, cloud speech is never used."""
        return bool(self._privacy is not None and self._privacy.allows_cloud_asr())

    def _transcribe_local(self, model, wav_bytes: bytes) -> ASRResult:
        """faster-whisper transcription with per-segment language detection."""
        audio_np = self._wav_to_float32(wav_bytes)
        if audio_np is None or audio_np.size == 0:
            return ASRResult(full_text="", language=self.language, model_used=self._model_name)

        lang = None if self.language == "auto" else self.language
        try:
            segments_iter, info = model.transcribe(
                audio_np,
                language=lang,
                vad_filter=True,
                word_timestamps=False,
                without_timestamps=False,
            )
            segments: list[ASRSegment] = []
            for seg in segments_iter:
                seg_lang = getattr(seg, "language", None) or info.language or "und"
                segments.append(ASRSegment(
                    text=seg.text.strip(),
                    language=seg_lang,
                    start_ms=seg.start * 1000,
                    end_ms=seg.end * 1000,
                    confidence=getattr(seg, "avg_logprob", 0.0),
                ))
            full_text = " ".join(s.text for s in segments)
            dominant = info.language if segments else "und"
            return ASRResult(
                full_text=full_text,
                language=dominant,
                segments=segments,
                model_used=self._model_name,
            )
        except Exception as e:
            print(f"[asr/local] error: {e}")
            if not self._cloud_allowed():
                return ASRResult(full_text="", language="und", model_used=LOCAL_FAILED)
            return self._transcribe_cloud(wav_bytes)

    def _transcribe_cloud(self, wav_bytes: bytes) -> ASRResult:
        """Google STT cloud fallback via SpeechRecognition."""
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as src:
                audio = r.record(src)
            lang_code = "id-ID" if self.language in ("auto", "id") else self.language
            try:
                text = r.recognize_google(audio, language=lang_code)
            except Exception:
                text = r.recognize_google(audio)
            if not text:
                return ASRResult(full_text="", language="und", model_used="cloud/google-stt")
            detected_lang = "id" if lang_code.startswith("id") else "en"
            return ASRResult(
                full_text=text,
                language=detected_lang,
                segments=[ASRSegment(text=text, language=detected_lang)],
                model_used="cloud/google-stt",
            )
        except Exception as e:
            print(f"[asr/cloud] error: {e}")
            return ASRResult(full_text="", language="und", model_used="cloud/google-stt")

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _wav_to_float32(wav_bytes: bytes):
        try:
            import wave
            import numpy as np
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                n_frames   = wf.getnframes()
                raw        = wf.readframes(n_frames)
                n_channels = wf.getnchannels()
                sampwidth  = wf.getsampwidth()
                framerate  = wf.getframerate()

            dtype = np.int16 if sampwidth == 2 else np.int8
            arr   = np.frombuffer(raw, dtype=dtype).astype(np.float32)
            if n_channels > 1:
                arr = arr.reshape(-1, n_channels).mean(axis=1)
            arr /= (32768.0 if sampwidth == 2 else 128.0)
            if framerate != 16000:
                import scipy.signal as sg
                arr = sg.resample_poly(arr, 16000, framerate).astype(np.float32)
            return arr
        except Exception as e:
            print(f"[asr] wav decode error: {e}")
            return None
