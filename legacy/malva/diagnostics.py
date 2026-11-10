"""Crash and error logging for Malva.

Files (Windows: %LOCALAPPDATA%\\Malva\\logs, elsewhere: ~/.malva/logs):
  malva.log  - Python logging and everything printed by the app. Rotating, 2 MB x 3.
               Includes uncaught exceptions from the main thread and from every worker thread.
  crash.log  - faulthandler output for native crashes (access violation, abort). Python
               cannot catch those, so this file is the only record of them.

Privacy: transcripts and audio are never logged here. Log lines carry error messages
and tracebacks only.
"""

from __future__ import annotations

import faulthandler
import io
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_crash_file = None
_log_file = None
_handler: RotatingFileHandler | None = None


def log_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Malva" / "logs"
    return Path.home() / ".malva" / "logs"


class _Tee(io.TextIOBase):
    """Writes to the original stream (if any) and to the log file."""

    def __init__(self, original, sink):
        self._original = original
        self._sink = sink

    def write(self, text: str) -> int:
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        try:
            self._sink.write(text)
            self._sink.flush()
        except Exception:
            pass
        return len(text)

    def flush(self) -> None:
        for stream in (self._original, self._sink):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass


def setup(directory: Path | None = None) -> Path:
    """Start file logging, crash capture and exception hooks. Safe to call more than once."""
    global _crash_file, _log_file, _handler

    folder = directory or log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder / "malva.log"

    if _handler is None:
        _handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(_handler)
        root.setLevel(logging.WARNING)
        logging.getLogger("malva").setLevel(logging.INFO)

        _log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, _log_file)
        sys.stderr = _Tee(sys.stderr, _log_file)

        _crash_file = open(folder / "crash.log", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_crash_file, all_threads=True)

        def _excepthook(exc_type, exc, tb):
            logging.getLogger("malva.crash").error(
                "Uncaught exception", exc_info=(exc_type, exc, tb))

        def _thread_hook(args):
            name = args.thread.name if args.thread else "unknown"
            logging.getLogger("malva.crash").error(
                "Uncaught exception in thread %s", name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

        sys.excepthook = _excepthook
        threading.excepthook = _thread_hook
        logging.getLogger("malva").info("Malva started (pid %s)", os.getpid())

    return log_path


def teardown() -> None:
    """Detach handlers and hooks. Used by tests; the app never needs it."""
    global _crash_file, _log_file, _handler
    faulthandler.disable()
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
    for handle in (_crash_file, _log_file):
        if handle is not None:
            handle.close()
    _crash_file = _log_file = None
