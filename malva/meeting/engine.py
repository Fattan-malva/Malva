"""
malva.meeting.engine — Meeting Intelligence (Blueprint §4, §13).

Responsibilities:
- Accumulate transcript segments in real-time
- On session end (or on demand): generate summary, decisions, action items
- Persist all outputs to storage, clearly distinguished from raw transcript
- Support Cross-Meeting Memory via db queries
"""

from __future__ import annotations

import json
import uuid
from typing import Callable

from malva.ai.orchestrator import AIOrchestrator
from malva.storage.db import Database
from malva.transcript.core import TranscriptCore


class MeetingEngine:
    def __init__(self, session_id: str, ai: AIOrchestrator, db: Database,
                 transcript: TranscriptCore):
        self.session_id = session_id
        self._ai        = ai
        self._db        = db
        self._transcript = transcript
        self._on_update: Callable[[dict], None] | None = None

    def set_update_callback(self, fn: Callable[[dict], None]) -> None:
        self._on_update = fn

    # ------------------------------------------------------------------ real-time

    def on_segment(self, evt: dict) -> None:
        """Called by TranscriptCore on each new segment."""
        if self._on_update:
            self._on_update({"type": "segment", "data": evt})

    # ------------------------------------------------------------------ end-of-session analysis

    def finalize(self) -> dict:
        """
        Called when the meeting session ends.
        Returns report dict with summary, decisions, action_items.
        DOES NOT overwrite raw transcript.
        """
        transcript_text = self._transcript.get_full_text()
        if not transcript_text.strip():
            return {"summary": "", "decisions": [], "action_items": []}

        # Summary (AI-generated, stored separately from transcript)
        summary = self._ai.summarize_transcript(transcript_text, task="meeting")

        # Decisions
        decisions = self._ai.extract_decisions(transcript_text)

        # Action items
        action_items_raw = self._ai.extract_action_items(transcript_text)

        # Persist — clearly distinguished from raw transcript
        note_id = uuid.uuid4().hex
        self._db.save_meeting_notes(
            note_id=note_id,
            session_id=self.session_id,
            summary=summary,
            full_text=transcript_text,
            model_used=self._ai.mode,
        )

        for dec in decisions:
            self._db.add_decision(
                dec_id=uuid.uuid4().hex,
                session_id=self.session_id,
                text=dec,
            )

        saved_items = []
        for item in action_items_raw:
            iid = uuid.uuid4().hex
            text     = item.get("text", "")
            owner    = item.get("owner", "")
            deadline = item.get("deadline", "")
            if text:
                self._db.add_action_item(
                    item_id=iid,
                    session_id=self.session_id,
                    text=text,
                    owner=owner,
                    deadline=deadline,
                )
                saved_items.append({"id": iid, "text": text, "owner": owner, "deadline": deadline})

        report = {
            "summary":      summary,
            "decisions":    decisions,
            "action_items": saved_items,
        }

        if self._on_update:
            self._on_update({"type": "meeting_report", "data": report})

        return report

    # ------------------------------------------------------------------ cross-session memory

    def find_related_decisions(self, query: str) -> list[dict]:
        """Search decisions across all past sessions."""
        rows = self._db.find_decisions_across_sessions(query)
        return [dict(r) for r in rows]

    def get_unresolved_actions(self) -> list[dict]:
        """Return all pending action items across sessions."""
        rows = self._db.find_unresolved_action_items()
        return [dict(r) for r in rows]

