"""
malva.asr.types — Result types for speech recognition (Blueprint §9).

Recognition runs in the cloud (Gemini Live transcription). These types are the
hand-off between the recognizer and the transcript store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Reasons a transcription could not start. The session shows them to the user.
ASR_NOT_CONFIGURED = "asr-not-configured"   # GEMINI_API_KEY is empty
ASR_CLOUD_DISABLED = "asr-cloud-disabled"   # CLOUD_ENABLED=false
ASR_FAILED         = "asr-failed"           # connection or API error (retried)
ASR_REJECTED       = "asr-rejected"         # server refused the request (not retried)


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
    language:    str                   # BCP-47 primary language, or "und"
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
