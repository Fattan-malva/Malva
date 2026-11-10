"""
malva.interview.engine — Interview Mode (Blueprint §6).

Two distinct sub-modes with SEPARATE prompt sets, session config, output, and logic:
  - interview_practice : AI acts as interviewer, evaluates answers, gives feedback
  - interview_notes    : Records and organizes questions/answers from real interviews

IMPORTANT (Blueprint §6 invariant):
  "Live assistance during real interviews must respect the organizer's rules.
   Do not design the product to disguise prohibited assistance."
"""

from __future__ import annotations

import json
import uuid
from typing import Callable

from malva.ai.orchestrator import AIOrchestrator
from malva.storage.db import Database
from malva.transcript.core import TranscriptCore


# ------------------------------------------------------------------ Practice Engine

class PracticeSession:
    """State for a single Interview Practice session."""
    def __init__(self):
        self.questions_asked: list[str] = []
        self.answers_given:   list[dict] = []  # {question, answer, feedback}
        self.topic:           str = "general"
        self.interview_type:  str = "behavioral"  # behavioral|technical|coding|situational


class InterviewEngine:
    """
    Handles both Interview Practice and Interview Notes sub-modes.
    Sub-mode is determined by the session mode string.
    """

    def __init__(self, session_id: str, mode: str,
                 ai: AIOrchestrator, db: Database, transcript: TranscriptCore):
        assert mode in ("interview_practice", "interview_notes"), \
            f"InterviewEngine requires mode interview_practice or interview_notes, got: {mode}"
        self.session_id  = session_id
        self.mode        = mode
        self._ai         = ai
        self._db         = db
        self._transcript = transcript
        self._on_update: Callable[[dict], None] | None = None
        # Practice-specific state
        self._practice   = PracticeSession()
        # Notes-specific state
        self._qa_pairs:  list[dict] = []  # {question, answer, timestamp}

    def set_update_callback(self, fn: Callable[[dict], None]) -> None:
        self._on_update = fn

    # ------------------------------------------------------------------ Practice sub-mode

    def set_interview_context(self, topic: str = "general",
                               interview_type: str = "behavioral") -> None:
        """Configure the practice session before starting."""
        self._practice.topic          = topic
        self._practice.interview_type = interview_type

    def get_next_question(self, on_chunk: Callable[[str], None] | None = None) -> str:
        """AI generates and asks the next interview question."""
        context = (
            f"Topik: {self._practice.topic}. "
            f"Tipe: {self._practice.interview_type}. "
            f"Pertanyaan sudah ditanyakan: {len(self._practice.questions_asked)}. "
        )
        if self._practice.questions_asked:
            context += f"Pertanyaan terakhir: '{self._practice.questions_asked[-1]}'. "
        prompt = (
            f"{context}\n"
            "Ajukan SATU pertanyaan wawancara berikutnya yang relevan. "
            "Hanya pertanyaannya saja, tanpa penjelasan tambahan."
        )
        question, _ = self._ai.ask(prompt, on_chunk=on_chunk)
        question = (question or "").strip()
        if not question:
            return ""  # AI unavailable: do not record an empty question
        self._practice.questions_asked.append(question)
        if self._on_update:
            self._on_update({"type": "interview_question", "data": {"question": question}})
        return question

    def evaluate_answer(self, answer: str,
                         on_chunk: Callable[[str], None] | None = None) -> str:
        """Evaluate the user's answer and provide feedback."""
        if not self._practice.questions_asked:
            return "Belum ada pertanyaan yang diajukan."
        last_q = self._practice.questions_asked[-1]
        prompt = (
            f"Pertanyaan yang diajukan: '{last_q}'\n"
            f"Jawaban kandidat: '{answer}'\n\n"
            "Evaluasi jawaban ini berdasarkan:\n"
            "1. Struktur (apakah ada kerangka yang jelas, mis. STAR)\n"
            "2. Relevansi dengan pertanyaan\n"
            "3. Kejelasan dan kekonkretan\n"
            "4. Kelengkapan\n\n"
            "Berikan feedback konstruktif dan saran perbaikan spesifik."
        )
        feedback, _ = self._ai.ask(prompt, on_chunk=on_chunk)
        self._practice.answers_given.append({
            "question": last_q,
            "answer":   answer,
            "feedback": feedback,
        })
        if self._on_update:
            self._on_update({"type": "interview_feedback", "data": {
                "question": last_q, "answer": answer, "feedback": feedback
            }})
        return feedback

    def finalize_practice(self) -> dict:
        """Generate end-of-session practice report."""
        if not self._practice.answers_given:
            return {"report_type": "practice", "summary": "Tidak ada sesi yang direkam."}

        qa_summary = "\n".join(
            f"Q: {qa['question']}\nA: {qa['answer']}\nFeedback: {qa['feedback']}"
            for qa in self._practice.answers_given
        )
        prompt = (
            "Berdasarkan sesi latihan wawancara berikut, buat laporan akhir yang mencakup:\n"
            "1. Kekuatan kandidat\n"
            "2. Area yang perlu dikembangkan\n"
            "3. Rekomendasi topik latihan ke depan\n"
            "4. Penilaian keseluruhan (skala 1-10 dengan justifikasi)\n\n"
            f"SESI:\n{qa_summary}"
        )
        report_text, _ = self._ai.ask(prompt)
        report = {
            "report_type":    "practice",
            "topic":          self._practice.topic,
            "interview_type": self._practice.interview_type,
            "questions_count": len(self._practice.questions_asked),
            "answers_count":   len(self._practice.answers_given),
            "qa_pairs":        self._practice.answers_given,
            "report":          report_text,
        }
        self._db.save_interview_report(
            rep_id=uuid.uuid4().hex,
            session_id=self.session_id,
            report_type="practice",
            content_json=json.dumps(report, ensure_ascii=False),
        )
        if self._on_update:
            self._on_update({"type": "interview_report", "data": report})
        return report

    # ------------------------------------------------------------------ Notes sub-mode

    def on_segment(self, evt: dict) -> None:
        """Called on new transcript segment in interview_notes mode."""
        if self.mode != "interview_notes":
            return
        text = evt.get("text", "").strip()
        if not text:
            return
        # Simple heuristic: segments ending with "?" are likely questions
        is_question = text.endswith("?")
        if is_question and self._qa_pairs:
            # Assign to current open answer slot if any
            self._qa_pairs.append({"question": text, "answer": "", "timestamp": evt.get("timestamp", 0)})
        elif is_question:
            self._qa_pairs.append({"question": text, "answer": "", "timestamp": evt.get("timestamp", 0)})
        else:
            # Append as answer to last question
            if self._qa_pairs and self._qa_pairs[-1]["answer"] == "":
                self._qa_pairs[-1]["answer"] = text
            elif self._qa_pairs:
                self._qa_pairs[-1]["answer"] += " " + text
            else:
                self._qa_pairs.append({"question": "", "answer": text, "timestamp": evt.get("timestamp", 0)})

        if self._on_update:
            self._on_update({"type": "transcript_segment", "data": evt})

    def finalize_notes(self) -> dict:
        """Generate interview notes report."""
        transcript_text = self._transcript.get_full_text()
        if not transcript_text.strip():
            return {"report_type": "notes", "summary": "Tidak ada transkrip."}

        summary    = self._ai.summarize_transcript(transcript_text, task="interview_notes")
        if not summary.strip():
            summary = "(Ringkasan AI tidak tersedia. AI memakai Cloudflare Workers AI: atur CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN dan pastikan CLOUD_ENABLED tidak false.)"
        follow_ups = self._generate_follow_ups(transcript_text)

        report = {
            "report_type":   "notes",
            "transcript":    transcript_text,
            "qa_pairs":      self._qa_pairs,
            "summary":       summary,
            "follow_up_questions": follow_ups,
        }
        self._db.save_interview_report(
            rep_id=uuid.uuid4().hex,
            session_id=self.session_id,
            report_type="notes",
            content_json=json.dumps(report, ensure_ascii=False),
        )
        if self._on_update:
            self._on_update({"type": "interview_report", "data": report})
        return report

    def _generate_follow_ups(self, transcript: str) -> list[str]:
        prompt = (
            "Dari transkrip wawancara ini, buat 3-5 pertanyaan tindak lanjut yang relevan. "
            "Format: JSON array of strings.\n\n"
            f"TRANSKRIP:\n{transcript}"
        )
        raw, _ = self._ai.ask(prompt)
        try:
            import re
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass
        return []

