//! Kontrak event dari core ke UI. Sumber kebenaran tunggal di sisi Rust.
//! Urutan dan isi harus sama dengan `EVENT_TYPES` di Python (dicek oleh contract_parity.sh).

pub const EVENT_TYPES: &[&str] = &[
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
];

pub fn is_known_event(name: &str) -> bool {
    EVENT_TYPES.contains(&name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_has_no_duplicates() {
        let mut sorted = EVENT_TYPES.to_vec();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), EVENT_TYPES.len());
    }

    #[test]
    fn known_and_unknown_events() {
        assert!(is_known_event("transcript_partial"));
        assert!(!is_known_event("transcript"));
    }
}
