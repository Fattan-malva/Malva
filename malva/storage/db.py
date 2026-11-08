"""
malva.storage.db — SQLite database engine for Malva.

Tables (all created on first run):
  sessions            — assistant, meeting, interview sessions
  audio_tracks        — audio source and track metadata
  transcript_segments — text, timestamps, language, speaker
  speakers            — session-local speaker identities
  meeting_notes       — summaries and notes
  decisions           — extracted decisions
  action_items        — tasks, owners, deadlines, status
  interview_reports   — practice and notes reports
  model_registry      — ASR model and runtime configuration
  app_settings        — user preferences (key-value)
  tool_audit_logs     — desktop tool requests and outcomes
"""

import sqlite3
import threading
import time
from pathlib import Path

_LOCAL = threading.local()
_DB_PATH: Path | None = None


def init(db_path: str | Path) -> None:
    """Call once at startup before any other storage call."""
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _connect()
    _create_tables()


def _connect() -> sqlite3.Connection:
    if getattr(_LOCAL, "conn", None) is None:
        assert _DB_PATH is not None, "storage.db.init() not called"
        conn = sqlite3.connect(
            str(_DB_PATH),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _LOCAL.conn = conn
    return _LOCAL.conn


def get_db() -> "Database":
    return Database(_connect())


def _create_tables() -> None:
    conn = _connect()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        mode        TEXT NOT NULL,          -- assistant|meeting|interview_practice|interview_notes|voice_input
        title       TEXT,
        started_at  REAL NOT NULL,          -- epoch seconds
        ended_at    REAL,
        status      TEXT DEFAULT 'active',  -- active|paused|ended
        metadata    TEXT DEFAULT '{}'       -- JSON
    );

    CREATE TABLE IF NOT EXISTS audio_tracks (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        source_type TEXT NOT NULL,          -- microphone|system_audio
        device_name TEXT,
        device_id   TEXT,
        sample_rate INTEGER,
        channels    INTEGER,
        fmt         TEXT,
        started_at  REAL,
        ended_at    REAL,
        track_state TEXT DEFAULT 'active',
        metadata    TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS transcript_segments (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        track_id    TEXT REFERENCES audio_tracks(id),
        seq         INTEGER NOT NULL,
        text        TEXT NOT NULL,
        language    TEXT,
        confidence  REAL,
        speaker_id  TEXT,
        start_ms    REAL,
        end_ms      REAL,
        is_final    INTEGER DEFAULT 1,      -- 0=partial, 1=final
        created_at  REAL NOT NULL,
        raw_json    TEXT                    -- full model segment JSON
    );

    CREATE TABLE IF NOT EXISTS speakers (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        label       TEXT,
        metadata    TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS meeting_notes (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        summary     TEXT,
        full_text   TEXT,
        created_at  REAL NOT NULL,
        model_used  TEXT
    );

    CREATE TABLE IF NOT EXISTS decisions (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        text        TEXT NOT NULL,
        segment_ids TEXT,                   -- JSON array of transcript_segment ids
        created_at  REAL NOT NULL,
        confirmed   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS action_items (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        text        TEXT NOT NULL,
        owner       TEXT,
        deadline    TEXT,
        status      TEXT DEFAULT 'pending', -- pending|done|cancelled
        segment_ids TEXT,
        created_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS interview_reports (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        report_type TEXT NOT NULL,          -- practice|notes
        content     TEXT NOT NULL,          -- JSON report
        created_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS model_registry (
        id          TEXT PRIMARY KEY,
        engine      TEXT NOT NULL,          -- faster_whisper|qwen3_asr|google_stt
        model_size  TEXT,
        model_path  TEXT,
        device      TEXT DEFAULT 'cpu',
        language    TEXT DEFAULT 'auto',
        is_active   INTEGER DEFAULT 0,
        metadata    TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS app_settings (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  REAL
    );

    CREATE TABLE IF NOT EXISTS tool_audit_logs (
        id          TEXT PRIMARY KEY,
        session_id  TEXT,
        tool_name   TEXT NOT NULL,
        args_json   TEXT,
        risk_level  TEXT,
        approved    INTEGER,
        outcome     TEXT,
        error       TEXT,
        created_at  REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_seg_session ON transcript_segments(session_id);
    CREATE INDEX IF NOT EXISTS idx_seg_seq     ON transcript_segments(session_id, seq);
    CREATE INDEX IF NOT EXISTS idx_track_sess  ON audio_tracks(session_id);
    CREATE INDEX IF NOT EXISTS idx_dec_sess    ON decisions(session_id);
    CREATE INDEX IF NOT EXISTS idx_ai_sess     ON action_items(session_id);
    CREATE INDEX IF NOT EXISTS idx_audit_sess  ON tool_audit_logs(session_id);
    """)
    conn.commit()


class Database:
    """Thin wrapper providing typed helpers around a sqlite3 connection."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ------------------------------------------------------------------ sessions

    def create_session(self, session_id: str, mode: str, title: str = "") -> None:
        self._conn.execute(
            "INSERT INTO sessions(id, mode, title, started_at) VALUES (?,?,?,?)",
            (session_id, mode, title, time.time()),
        )
        self._conn.commit()

    def end_session(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at=?, status='ended' WHERE id=?",
            (time.time(), session_id),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()

    def list_sessions(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # ------------------------------------------------------------------ audio tracks

    def create_audio_track(self, track_id: str, session_id: str, source_type: str,
                           device_name: str = "", sample_rate: int = 16000,
                           channels: int = 1) -> None:
        self._conn.execute(
            """INSERT INTO audio_tracks
               (id, session_id, source_type, device_name, sample_rate, channels, started_at)
               VALUES (?,?,?,?,?,?,?)""",
            (track_id, session_id, source_type, device_name, sample_rate, channels, time.time()),
        )
        self._conn.commit()

    def end_audio_track(self, track_id: str) -> None:
        self._conn.execute(
            "UPDATE audio_tracks SET ended_at=?, track_state='ended' WHERE id=?",
            (time.time(), track_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ transcript segments

    def add_segment(self, seg_id: str, session_id: str, seq: int, text: str,
                    language: str = "", confidence: float = 1.0,
                    start_ms: float = 0, end_ms: float = 0,
                    track_id: str = "", speaker_id: str = "",
                    raw_json: str = "") -> None:
        """Store a finalized transcript segment. Never overwrite raw text with AI output."""
        self._conn.execute(
            """INSERT OR IGNORE INTO transcript_segments
               (id, session_id, track_id, seq, text, language, confidence,
                speaker_id, start_ms, end_ms, is_final, created_at, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
            (seg_id, session_id, track_id, seq, text, language, confidence,
             speaker_id, start_ms, end_ms, time.time(), raw_json),
        )
        self._conn.commit()

    def get_segments(self, session_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM transcript_segments WHERE session_id=? ORDER BY seq",
            (session_id,),
        ).fetchall()

    def search_segments(self, query: str, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM transcript_segments WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()

    # ------------------------------------------------------------------ settings

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO app_settings(key, value, updated_at) VALUES(?,?,?)",
            (key, value, time.time()),
        )
        self._conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    # ------------------------------------------------------------------ action items

    def add_action_item(self, item_id: str, session_id: str, text: str,
                        owner: str = "", deadline: str = "",
                        segment_ids: str = "[]") -> None:
        self._conn.execute(
            """INSERT INTO action_items
               (id, session_id, text, owner, deadline, segment_ids, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (item_id, session_id, text, owner, deadline, segment_ids, time.time()),
        )
        self._conn.commit()

    def get_action_items(self, session_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM action_items WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()

    def update_action_item_status(self, item_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE action_items SET status=? WHERE id=?", (status, item_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------ decisions

    def add_decision(self, dec_id: str, session_id: str, text: str,
                     segment_ids: str = "[]") -> None:
        self._conn.execute(
            "INSERT INTO decisions(id, session_id, text, segment_ids, created_at) VALUES(?,?,?,?,?)",
            (dec_id, session_id, text, segment_ids, time.time()),
        )
        self._conn.commit()

    def get_decisions(self, session_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM decisions WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()

    # ------------------------------------------------------------------ cross-session memory

    def find_decisions_across_sessions(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT d.*, s.mode, s.title, s.started_at as sess_started
               FROM decisions d JOIN sessions s ON d.session_id=s.id
               WHERE d.text LIKE ? ORDER BY d.created_at DESC LIMIT ?""",
            (f"%{query}%", limit),
        ).fetchall()

    def find_unresolved_action_items(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT a.*, s.title as sess_title, s.started_at as sess_started
               FROM action_items a JOIN sessions s ON a.session_id=s.id
               WHERE a.status='pending' ORDER BY a.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    # ------------------------------------------------------------------ audit log

    def log_tool_action(self, log_id: str, session_id: str, tool_name: str,
                        args_json: str, risk_level: str, approved: bool,
                        outcome: str = "", error: str = "") -> None:
        self._conn.execute(
            """INSERT INTO tool_audit_logs
               (id, session_id, tool_name, args_json, risk_level, approved, outcome, error, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (log_id, session_id, tool_name, args_json, risk_level,
             1 if approved else 0, outcome, error, time.time()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ interview reports

    def save_interview_report(self, rep_id: str, session_id: str,
                              report_type: str, content_json: str) -> None:
        self._conn.execute(
            """INSERT INTO interview_reports(id, session_id, report_type, content, created_at)
               VALUES (?,?,?,?,?)""",
            (rep_id, session_id, report_type, content_json, time.time()),
        )
        self._conn.commit()

    def get_interview_reports(self, session_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM interview_reports WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()

    # ------------------------------------------------------------------ meeting notes

    def save_meeting_notes(self, note_id: str, session_id: str,
                           summary: str, full_text: str, model_used: str = "") -> None:
        self._conn.execute(
            """INSERT INTO meeting_notes(id, session_id, summary, full_text, created_at, model_used)
               VALUES (?,?,?,?,?,?)""",
            (note_id, session_id, summary, full_text, time.time(), model_used),
        )
        self._conn.commit()

    def get_meeting_notes(self, session_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM meeting_notes WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()

    # ------------------------------------------------------------------ raw execute

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

