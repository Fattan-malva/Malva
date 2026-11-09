"""Canonical event contract (audit P0.4): every event the backend emits is listed in
session.EVENT_TYPES, every listed event is emitted somewhere, and app.py dispatches it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _canonical() -> set[str]:
    from malva.shell import session
    return set(session.EVENT_TYPES)


def _emitted() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "malva").rglob("*.py"):
        found |= set(re.findall(r'"type":\s*"(\w+)"', path.read_text(encoding="utf-8")))
    return found


def test_every_emitted_event_is_canonical():
    assert _emitted() - _canonical() == set()


def test_every_canonical_event_is_emitted():
    assert _canonical() - _emitted() == set()


def test_every_canonical_event_is_dispatched_in_app():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    missing = sorted(e for e in _canonical() if f'"{e}"' not in app)
    assert not missing, f"app.py has no handler for: {missing}"
