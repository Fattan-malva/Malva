// Kontrak event core -> UI. Harus sama dengan native/core/src/events.rs dan EVENT_TYPES di Python.
// Dicek oleh native/tests/contract_parity.sh.

export const EVENT_TYPES = [
  "session_started",
  "session_ended",
  "source_state",
  "capture_error",
  "state_change",
  "transcript_segment",
  "audio_levels",
  "ai_start",
  "ai_chunk",
  "ai_end",
  "ai_error",
  "action_proposed",
  "action_result",
  "voice_input_text",
  "focus_mode",
  "sleep_mode",
  "interview_question",
  "interview_answer_draft",
  "interview_feedback",
  "interview_report",
  "meeting_report",
  "transcript_partial",
  "asr_error",
  "report_error",
  "notice",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export const SESSION_STATES = [
  "idle",
  "listening",
  "processing",
  "paused",
  "sleeping",
  "error",
] as const;

export type SessionState = (typeof SESSION_STATES)[number];

export const MODES = [
  "assistant",
  "meeting",
  "interview_practice",
  "interview_notes",
  "voice_input",
] as const;

export type Mode = (typeof MODES)[number];

/** Hanya kontrak yang sudah dipastikan. Payload lain ditambahkan saat PoC berjalan. */
export interface CoreEvent<T extends EventType = EventType> {
  type: T;
  payload?: Record<string, unknown>;
}

/** Tidak ada audio mentah di sini. UI hanya menerima status, teks, dan level. */
export type IsKnownEvent = (name: string) => name is EventType;
export const isKnownEvent: IsKnownEvent = (name): name is EventType =>
  (EVENT_TYPES as readonly string[]).includes(name);
