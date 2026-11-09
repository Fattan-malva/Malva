"""
malva.shell.policy — Sleep / Focus decisions as pure functions (Blueprint §7).

Kept free of threads, windows and audio so the rules are unit-testable.

Rules:
  * Focus is an app-level preference. It survives mode switches and only
    changes when the user toggles it. It never changes the session state
    (paused / sleeping / error stay as they are).
  * Auto-sleep only applies to the Assistant profile, only after the
    configured idle time, and only when the user has not been active
    (no speech utterance and no typed text). Protected profiles
    (Meeting, Interview, Voice Input) never auto-sleep.
  * Focus always blocks auto-sleep.
  * Manual Sleep is always allowed; the caller must warn when a protected
    capture would be paused.
"""

from __future__ import annotations

PROTECTED_MODES = frozenset({"meeting", "interview_practice", "interview_notes", "voice_input"})


def should_auto_sleep(
    *,
    mode: str,
    idle_seconds: float,
    threshold_seconds: float,
    focus_on: bool,
    sleeping: bool,
    paused: bool,
) -> bool:
    """Return True only when automatic sleep is allowed right now."""
    if threshold_seconds <= 0:
        return False          # 0 disables auto-sleep
    if focus_on or sleeping or paused:
        return False
    if mode in PROTECTED_MODES:
        return False
    return idle_seconds >= threshold_seconds


def protected_capture_warning(mode: str) -> str:
    """Message shown before a manual Sleep that will pause live capture."""
    if mode in PROTECTED_MODES:
        return "Sesi ini sedang merekam. Tidur akan menjeda perekaman audio."
    return "Malva akan berhenti mendengarkan sampai dibangunkan."


def parse_sleep_seconds(raw: str | None, default: float = 60.0) -> float:
    """SLEEP_AFTER_SECONDS parsing: invalid or negative values fall back safely."""
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value != value:  # NaN
        return default
    return max(0.0, value)


# ------------------------------------------------------------------ voice approval

APPROVE_PHRASES = frozenset({"setuju", "ya hapus", "iya hapus", "hapus saja", "lanjutkan hapus", "setuju hapus"})
REJECT_PHRASES = frozenset({"batal", "tolak", "jangan", "tidak jadi", "batalkan"})
VOICE_APPROVAL_WINDOW_SECONDS = 120.0


def normalize_utterance(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in (text or "").lower())
    return " ".join(cleaned.split())


def voice_decision(text: str) -> str | None:
    """'approve' or 'reject' when the whole utterance is exactly one decision phrase, else None.

    Only a complete phrase counts. A sentence that merely contains the word does not.
    """
    phrase = normalize_utterance(text)
    if phrase in APPROVE_PHRASES:
        return "approve"
    if phrase in REJECT_PHRASES:
        return "reject"
    return None
