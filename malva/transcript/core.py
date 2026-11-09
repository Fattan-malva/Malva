"""
malva.transcript.core — Transcript segment pipeline.

Receives ASRResult objects, assigns session-scoped sequence numbers,
persists to storage, and notifies listeners (AI orchestrator, UI).

Invariants (Blueprint §12):
- Original transcript text is NEVER overwritten by AI-generated content.
- Each segment retains its source track reference.
- Language metadata is preserved at segment level.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

from malva.asr.router import ASRResult, ASRSegment
from malva.storage.db import Database


class TranscriptCore:
    def __init__(self, session_id: str, db: Database):
        self.session_id = session_id
        self._db        = db
        self._seq       = 0
        self._lock      = threading.Lock()
        self._listeners: list[Callable[[dict], None]] = []

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        """Subscribe to new transcript events (called in background thread)."""
        self._listeners.append(fn)

    def ingest(self, result: ASRResult, track_id: str = "", source_type: str = "") -> list[dict]:
        """
        Store an ASRResult. Returns list of event dicts emitted.
        Called by the ASR pipeline after each utterance is finalized.
        """
        events: list[dict] = []
        if not result.full_text.strip():
            return events

        with self._lock:
            if result.segments:
                for seg in result.segments:
                    if not seg.text.strip():
                        continue
                    evt = self._store_segment(
                        text=seg.text,
                        language=seg.language,
                        confidence=seg.confidence,
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        track_id=track_id,
                        source_type=source_type,
                        raw=seg.to_dict(),
                    )
                    events.append(evt)
            else:
                # No segment breakdown — store as single segment
                evt = self._store_segment(
                    text=result.full_text,
                    language=result.language,
                    track_id=track_id,
                    source_type=source_type,
                )
                events.append(evt)

        for evt in events:
            for fn in self._listeners:
                try:
                    fn(evt)
                except Exception as e:
                    print(f"[transcript] listener error: {e}")

        return events

    def get_full_text(self) -> str:
        """Return full session transcript as plain text (original, never AI-modified)."""
        rows = self._db.get_segments(self.session_id)
        return "\n".join(r["text"] for r in rows)

    def get_segments_dicts(self) -> list[dict]:
        rows = self._db.get_segments(self.session_id)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ internal

    def _store_segment(self, text: str, language: str = "", confidence: float = 1.0,
                        start_ms: float = 0, end_ms: float = 0,
                        track_id: str = "", source_type: str = "",
                        raw: dict | None = None) -> dict:
        import json
        seg_id = uuid.uuid4().hex
        self._seq += 1
        self._db.add_segment(
            seg_id=seg_id,
            session_id=self.session_id,
            seq=self._seq,
            text=text,
            language=language,
            confidence=confidence,
            start_ms=start_ms,
            end_ms=end_ms,
            # Empty string would violate the audio_tracks foreign key; NULL means "no track".
            track_id=track_id or None,
            raw_json=json.dumps(raw or {}),
        )
        evt = {
            "type":       "transcript_segment",
            "seg_id":     seg_id,
            "session_id": self.session_id,
            "seq":        self._seq,
            "text":       text,
            "language":   language,
            "confidence": confidence,
            "start_ms":   start_ms,
            "end_ms":     end_ms,
            "track_id":   track_id,
            "source_type": source_type,
            "timestamp":  time.time(),
        }
        return evt

