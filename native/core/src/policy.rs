//! Aturan Sleep / Focus dan persetujuan suara sebagai fungsi murni.
//! Setara dengan `malva/shell/policy.py`.

pub const PROTECTED_MODES: &[&str] = &[
    "meeting",
    "interview_practice",
    "interview_notes",
    "voice_input",
];

pub const APPROVE_PHRASES: &[&str] = &[
    "setuju",
    "ya hapus",
    "iya hapus",
    "hapus saja",
    "lanjutkan hapus",
    "setuju hapus",
];

pub const REJECT_PHRASES: &[&str] = &["batal", "tolak", "jangan", "tidak jadi", "batalkan"];

pub const VOICE_APPROVAL_WINDOW_SECONDS: f64 = 120.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceDecision {
    Approve,
    Reject,
}

pub fn is_protected_mode(mode: &str) -> bool {
    PROTECTED_MODES.contains(&mode)
}

/// Auto-sleep hanya untuk profil non-protected, setelah idle, dan tidak saat Focus/tidur/jeda.
/// `threshold_seconds <= 0` menonaktifkan auto-sleep.
pub fn should_auto_sleep(
    mode: &str,
    idle_seconds: f64,
    threshold_seconds: f64,
    focus_on: bool,
    sleeping: bool,
    paused: bool,
) -> bool {
    if threshold_seconds <= 0.0 {
        return false;
    }
    if focus_on || sleeping || paused {
        return false;
    }
    if is_protected_mode(mode) {
        return false;
    }
    idle_seconds >= threshold_seconds
}

/// Pesan sebelum tidur manual yang akan menjeda perekaman.
pub fn protected_capture_warning(mode: &str) -> &'static str {
    if is_protected_mode(mode) {
        "Sesi ini sedang merekam. Tidur akan menjeda perekaman audio."
    } else {
        "Malva akan berhenti mendengarkan sampai dibangunkan."
    }
}

/// Parsing SLEEP_AFTER_SECONDS. Kosong, tidak valid, atau NaN memakai default. Nilai negatif jadi 0.
pub fn parse_sleep_seconds(raw: Option<&str>, default: f64) -> f64 {
    let Some(raw) = raw else { return default };
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return default;
    }
    match trimmed.parse::<f64>() {
        Ok(v) if v.is_nan() => default,
        Ok(v) => v.max(0.0),
        Err(_) => default,
    }
}

/// Huruf dan angka saja, huruf kecil, spasi tunggal. Tanda baca menjadi spasi.
pub fn normalize_utterance(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() || c.is_whitespace() { c } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// Hanya frasa penuh yang berlaku. Kalimat yang sekadar memuat kata itu tidak.
pub fn voice_decision(text: &str) -> Option<VoiceDecision> {
    let phrase = normalize_utterance(text);
    if APPROVE_PHRASES.contains(&phrase.as_str()) {
        Some(VoiceDecision::Approve)
    } else if REJECT_PHRASES.contains(&phrase.as_str()) {
        Some(VoiceDecision::Reject)
    } else {
        None
    }
}

/// Bagian nama tool dari `requires_approval` di Python. Pola teks (`safety.is_destructive`)
/// belum dipindah; itu keputusan terpisah (lihat native/README.md).
pub fn tool_name_requires_approval(tool_name: &str) -> bool {
    tool_name.to_lowercase().contains("delete")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn auto_sleep_rules() {
        assert!(should_auto_sleep("assistant", 60.0, 60.0, false, false, false));
        assert!(!should_auto_sleep("assistant", 59.9, 60.0, false, false, false));
        assert!(!should_auto_sleep("assistant", 999.0, 0.0, false, false, false));
        assert!(!should_auto_sleep("assistant", 999.0, 60.0, true, false, false));
        assert!(!should_auto_sleep("assistant", 999.0, 60.0, false, true, false));
        assert!(!should_auto_sleep("assistant", 999.0, 60.0, false, false, true));
        for mode in PROTECTED_MODES {
            assert!(!should_auto_sleep(mode, 999.0, 60.0, false, false, false));
        }
    }

    #[test]
    fn sleep_warning_text() {
        assert!(protected_capture_warning("meeting").starts_with("Sesi ini"));
        assert!(protected_capture_warning("assistant").starts_with("Malva akan"));
    }

    #[test]
    fn parse_sleep_seconds_cases() {
        assert_eq!(parse_sleep_seconds(None, 60.0), 60.0);
        assert_eq!(parse_sleep_seconds(Some("  "), 60.0), 60.0);
        assert_eq!(parse_sleep_seconds(Some("abc"), 60.0), 60.0);
        assert_eq!(parse_sleep_seconds(Some("NaN"), 60.0), 60.0);
        assert_eq!(parse_sleep_seconds(Some("-5"), 60.0), 0.0);
        assert_eq!(parse_sleep_seconds(Some("30"), 60.0), 30.0);
        assert_eq!(parse_sleep_seconds(Some("0"), 60.0), 0.0);
    }

    #[test]
    fn voice_decision_requires_whole_phrase() {
        assert_eq!(voice_decision("Setuju!"), Some(VoiceDecision::Approve));
        assert_eq!(voice_decision("  ya   hapus. "), Some(VoiceDecision::Approve));
        assert_eq!(voice_decision("batal"), Some(VoiceDecision::Reject));
        assert_eq!(voice_decision("saya setuju dengan itu"), None);
        assert_eq!(voice_decision("jangan hapus file itu"), None);
        assert_eq!(voice_decision(""), None);
    }

    #[test]
    fn delete_tools_need_approval() {
        assert!(tool_name_requires_approval("delete_file"));
        assert!(tool_name_requires_approval("Delete_Folder"));
        assert!(!tool_name_requires_approval("close_tab"));
    }
}
