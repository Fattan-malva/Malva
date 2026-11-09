"""Crash and error logging (malva/diagnostics.py)."""
import logging
import sys
import threading

import pytest

from malva import diagnostics


@pytest.fixture
def clean_diag():
    saved = (sys.stdout, sys.stderr, sys.excepthook, threading.excepthook)
    yield
    diagnostics.teardown()
    sys.stdout, sys.stderr, sys.excepthook, threading.excepthook = saved


def _flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_setup_creates_log_and_crash_files(tmp_path, clean_diag):
    path = diagnostics.setup(tmp_path)
    assert path == tmp_path / "malva.log"
    assert path.exists()
    assert (tmp_path / "crash.log").exists()


def test_logged_messages_and_prints_reach_the_file(tmp_path, clean_diag):
    diagnostics.setup(tmp_path)
    logging.getLogger("malva.test").warning("marker-warning-123")
    print("marker-print-456")
    _flush()
    text = (tmp_path / "malva.log").read_text(encoding="utf-8")
    assert "marker-warning-123" in text
    assert "marker-print-456" in text


def test_exception_in_worker_thread_is_logged(tmp_path, clean_diag):
    diagnostics.setup(tmp_path)

    def boom():
        raise ValueError("boom-789")

    worker = threading.Thread(target=boom, name="malva-test-worker")
    worker.start()
    worker.join()
    _flush()
    text = (tmp_path / "malva.log").read_text(encoding="utf-8")
    assert "Uncaught exception in thread malva-test-worker" in text
    assert "boom-789" in text


def test_setup_is_idempotent(tmp_path, clean_diag):
    diagnostics.setup(tmp_path)
    count = len(logging.getLogger().handlers)
    diagnostics.setup(tmp_path)
    assert len(logging.getLogger().handlers) == count
