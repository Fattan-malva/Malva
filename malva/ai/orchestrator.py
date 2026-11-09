"""
malva.ai.orchestrator — Central AI reasoning layer.

Responsibilities:
- Builds mode-specific prompts
- Maintains conversation history per session
- Calls the LLM (Ollama-compatible API, streaming)
- Parses tool calls from LLM output
- Streams text chunks to UI callback
- Injects realtime web context when needed

Modes: assistant | meeting | interview_practice | interview_notes | voice_input
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Callable, Iterator

import httpx

from malva.storage.db import Database

# Ollama cloud endpoint. Malva has no local LLM: this URL is always treated as cloud.
OLLAMA_URL   = os.getenv("OLLAMA_URL", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

_MAX_HISTORY = 10   # pairs kept per session

# ------------------------------------------------------------------ system prompts

_BASE_RULES = """
Kamu adalah Malva — private AI desktop copilot untuk Windows.
Prinsip utama:
- Jawab dalam bahasa yang sama dengan pertanyaan user (Indonesia atau Inggris).
- Jaga privasi: jangan sertakan data sensitif di luar konteks.
- Tool action selalu dalam format JSON: {"tool":"nama","args":{...}}
- Jangan campurkan teks narasi dan tool call dalam satu respons.
- Jika tidak yakin, tanya pengguna — jangan berasumsi.
"""

_PROMPTS = {
    "assistant": _BASE_RULES + """
Mode: Asisten Umum.
Kamu bisa menjawab pertanyaan, menjalankan tool desktop, browsing, dan membantu berbagai tugas.
Gunakan konteks transkrip aktif jika relevan.
""",
    "meeting": _BASE_RULES + """
Mode: Meeting Intelligence.
Tugasmu: transkripsi, ringkasan, identifikasi keputusan, dan action item dari audio meeting.
- Jangan komentari konten kecuali diminta.
- Simpan keputusan dan action item secara eksplisit.
- Format output: ringkasan paragraf singkat + daftar keputusan + daftar action item.
""",
    "interview_practice": _BASE_RULES + """
Mode: Interview Practice (latihan wawancara).
Kamu bertindak sebagai interviewer profesional.
- Ajukan pertanyaan behavioral, teknis, atau situasional sesuai konteks yang diberikan user.
- Evaluasi jawaban: struktur, relevansi, kejelasan, spesifisitas, kelengkapan.
- Berikan feedback konstruktif dan saran perbaikan.
- Di akhir sesi, hasilkan laporan: strengths, areas to improve, recommended topics.
- JANGAN pernah berpura-pura menjadi AI yang tidak transparan — kamu jelas-jelas AI.
""",
    "interview_notes": _BASE_RULES + """
Mode: Interview Notes (pencatatan wawancara).
Tugasmu: transkripsi, pengelompokan pertanyaan-jawaban, label speaker (jika tersedia),
dan pengorganisasian konten per topik.
Output: ringkasan, kutipan kunci, pertanyaan tindak lanjut, laporan yang bisa diedit.
""",
    "voice_input": _BASE_RULES + """
Mode: Voice Input.
Konversi ucapan user menjadi teks. Jangan tambahkan interpretasi, komentar, atau aksi.
Kembalikan hanya teks transkripsi yang bersih.
""",
}


def get_system_prompt(mode: str, extra_context: str = "") -> str:
    base = _PROMPTS.get(mode, _PROMPTS["assistant"])
    if extra_context:
        return base + f"\n\n--- Konteks tambahan ---\n{extra_context}\n"
    return base


# ------------------------------------------------------------------ orchestrator

class AIOrchestrator:
    def __init__(self, session_id: str, mode: str, db: Database, privacy_manager = None):
        self.session_id = session_id
        self.mode       = mode
        self._db        = db
        self._privacy   = privacy_manager
        self._history: list[dict] = []
        self.on_error: Callable[[str], None] | None = None
        self._running   = True
        self._headers   = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            self._headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    # ------------------------------------------------------------------ public

    def stop(self) -> None:
        self._running = False

    def resume(self) -> None:
        self._running = True

    def ask(
        self,
        user_text: str,
        on_chunk: Callable[[str], None] | None = None,
        extra_context: str = "",
    ) -> tuple[str, dict | None]:
        """
        Send user_text to LLM. Streams text chunks via on_chunk.
        Returns (full_response_text, tool_action_or_None).
        History is updated after each call.
        """
        messages = self._build_messages(user_text, extra_context)
        full_text, action = self._llm_round(messages, on_chunk)
        # Update history with original text — not AI tool calls
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": full_text})
        # Keep history bounded
        if len(self._history) > _MAX_HISTORY * 2:
            self._history = self._history[-(_MAX_HISTORY * 2):]
        return full_text, action

    def summarize_transcript(self, transcript: str, task: str = "meeting") -> str:
        """
        Standalone summarization call (no history update).
        Returns full summary string.
        """
        prompt = {
            "meeting": "Buat ringkasan meeting berikut. Sertakan: ringkasan eksekutif, keputusan utama, dan action item (siapa, apa, kapan jika disebutkan).",
            "interview_practice": "Evaluasi sesi latihan wawancara berikut. Sertakan: kekuatan jawaban, area perbaikan, dan rekomendasi topik latihan berikutnya.",
            "interview_notes": "Buat ringkasan wawancara berikut. Sertakan: topik utama, pertanyaan kunci, jawaban penting, dan pertanyaan tindak lanjut.",
        }.get(task, "Buat ringkasan dari transkrip berikut.")
        messages = [
            {"role": "system", "content": get_system_prompt(self.mode)},
            {"role": "user",   "content": f"{prompt}\n\nTRANSKRIP:\n{transcript}"},
        ]
        result, _ = self._llm_round(messages, on_chunk=None)
        return result

    def extract_action_items(self, transcript: str) -> list[dict]:
        """Extract action items from transcript. Returns list of {text, owner, deadline}."""
        messages = [
            {"role": "system", "content": get_system_prompt(self.mode)},
            {"role": "user", "content": (
                "Dari transkrip berikut, ekstrak semua action item. "
                "Format respons HANYA sebagai JSON array:\n"
                '[{"text":"...", "owner":"...", "deadline":"..."}]\n'
                "Jika tidak ada action item, kembalikan array kosong [].\n\n"
                f"TRANSKRIP:\n{transcript}"
            )},
        ]
        raw, _ = self._llm_round(messages, on_chunk=None)
        try:
            # Find JSON array in response
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass
        return []

    def extract_decisions(self, transcript: str) -> list[str]:
        """Extract decisions from transcript. Returns list of decision strings."""
        messages = [
            {"role": "system", "content": get_system_prompt(self.mode)},
            {"role": "user", "content": (
                "Dari transkrip berikut, ekstrak semua keputusan yang dibuat. "
                "Format respons HANYA sebagai JSON array of strings:\n"
                '["Keputusan 1", "Keputusan 2"]\n'
                "Jika tidak ada keputusan, kembalikan [].\n\n"
                f"TRANSKRIP:\n{transcript}"
            )},
        ]
        raw, _ = self._llm_round(messages, on_chunk=None)
        try:
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------ policy

    def _endpoint_allowed(self) -> bool:
        """Every LLM request goes through here. The LLM is Ollama cloud only; fail closed."""
        if not OLLAMA_URL.strip():
            self._report_error("AI belum diatur. Isi OLLAMA_URL di file .env (endpoint Ollama cloud).")
            return False
        if self._privacy is None or not self._privacy.allows_llm():
            self._report_error(
                "AI memakai Ollama cloud. Aktifkan 'Izinkan cloud' di tab Setelan untuk memakainya."
            )
            return False
        return True

    def _report_error(self, message: str) -> None:
        print(f"[ai] {message}")
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass

    # ------------------------------------------------------------------ LLM internals

    def _build_messages(self, user_text: str, extra_context: str = "") -> list[dict]:
        # Cross-Meeting Memory (Blueprint §13.1)
        if self.mode == "meeting" and any(k in user_text.lower() for k in ("keputusan", "decision", "action", "tugas", "sebelumnya", "kemarin", "lalu")):
            past_decisions = self._db.find_decisions_across_sessions(user_text[:30])
            if past_decisions:
                dec_text = "\n".join(f"- [{d['title'] or 'Sesi Lalu'}] {d['text']}" for d in past_decisions[:5])
                extra_context += f"\nMemori Keputusan Sesi Sebelumnya:\n{dec_text}\n"

        msgs = [{"role": "system", "content": get_system_prompt(self.mode, extra_context)}]
        msgs.extend(self._history[-(_MAX_HISTORY * 2):])
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def _llm_round(
        self,
        messages: list[dict],
        on_chunk: Callable[[str], None] | None,
    ) -> tuple[str, dict | None]:
        """Stream LLM response. Returns (emitted_text, action_or_None)."""
        if not self._endpoint_allowed():
            return "", None

        emitted:  list[str] = []
        buffered  = ""
        mode_     = None   # "text" | "action"

        def emit(chunk: str) -> None:
            if chunk:
                emitted.append(chunk)
                if on_chunk:
                    on_chunk(chunk)

        def classify() -> None:
            nonlocal buffered, mode_
            stripped = buffered.lstrip()
            if not stripped:
                return
            if stripped.startswith("```"):
                if "\n" in stripped:
                    first, rest = stripped.split("\n", 1)
                    info = first[3:].strip().lower()
                    if info in ("", "json") and rest.lstrip().startswith("{"):
                        mode_ = "action"
                    else:
                        mode_ = "text"
                        emit(buffered)
                        buffered = ""
                elif len(stripped) > 16:
                    mode_ = "text"
                    emit(buffered)
                    buffered = ""
            elif stripped.startswith("{"):
                mode_ = "action"
            else:
                mode_ = "text"
                emit(buffered)
                buffered = ""

        headers = {**self._headers, "Accept": "text/event-stream"}
        got_any = False

        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream(
                    "POST", OLLAMA_URL, headers=headers,
                    json={"model": OLLAMA_MODEL, "messages": messages, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    for raw_line in resp.iter_lines():
                        if not self._running:
                            break
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj   = json.loads(payload)
                            delta = obj["choices"][0]["delta"].get("content")
                        except Exception:
                            continue
                        if not delta:
                            continue
                        got_any = True
                        if mode_ is None:
                            buffered += delta
                            classify()
                        elif mode_ == "text":
                            emit(delta)
                        else:
                            buffered += delta
        except Exception as e:
            print(f"[ai/stream] {e}")

        if got_any:
            if mode_ == "action":
                action = self._parse_action(buffered)
                if action:
                    return "".join(emitted), action
                emit(buffered)
            elif mode_ is None and buffered:
                action = self._parse_action(buffered)
                if action:
                    return "".join(emitted), action
                emit(buffered)
            return "".join(emitted), None

        # Fallback non-streaming
        return self._fallback_request(messages, on_chunk)

    def _fallback_request(
        self,
        messages: list[dict],
        on_chunk: Callable[[str], None] | None,
    ) -> tuple[str, dict | None]:
        if not self._endpoint_allowed():
            return "", None
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    OLLAMA_URL, headers=self._headers,
                    json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                action  = self._parse_action(content)
                if action:
                    return "", action
                if on_chunk:
                    on_chunk(content)
                return content, None
        except Exception as e:
            print(f"[ai/fallback] {e}")
            return "", None

    @staticmethod
    def _parse_action(text: str) -> dict | None:
        raw = (text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw).strip()
        try:
            obj, _ = json.JSONDecoder().raw_decode(raw)
        except Exception:
            return None
        name = obj.get("tool") if isinstance(obj, dict) else None
        if isinstance(name, str):
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name.strip())
        if isinstance(name, str) and name:
            args = obj.get("args")
            return {"tool": name, "args": args if isinstance(args, dict) else {}}
        return None

