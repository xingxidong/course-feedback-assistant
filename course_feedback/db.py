"""Local SQLite storage for the course-feedback workbench."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "course_feedback.sqlite3"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  grade TEXT NOT NULL DEFAULT '',
  chat_title TEXT NOT NULL UNIQUE,
  default_notes TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weeks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL UNIQUE,
  course_intro TEXT NOT NULL,
  topics_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week_id INTEGER NOT NULL REFERENCES weeks(id),
  student_id INTEGER NOT NULL REFERENCES students(id),
  notes TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  error TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  sent_at TEXT,
  UNIQUE(week_id, student_id)
);
CREATE TABLE IF NOT EXISTS send_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  draft_id INTEGER NOT NULL REFERENCES drafts(id),
  action TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)

def rows(sql: str, params=()) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]

def one(sql: str, params=()) -> dict | None:
    with connect() as con:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None

def upsert_student(data: dict) -> dict:
    name = str(data.get("name", "")).strip()
    chat = str(data.get("chat_title", "")).strip()
    if not name or not chat:
        raise ValueError("学生姓名和微信群名不能为空")
    grade = str(data.get("grade", "")).strip()
    notes = str(data.get("default_notes", "")).strip()
    ts = now()
    with connect() as con:
        sid = data.get("id")
        if sid:
            con.execute("UPDATE students SET name=?, grade=?, chat_title=?, default_notes=?, updated_at=? WHERE id=?",
                        (name, grade, chat, notes, ts, int(sid)))
        else:
            con.execute("INSERT INTO students(name,grade,chat_title,default_notes,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (name, grade, chat, notes, ts, ts))
        r = con.execute("SELECT * FROM students WHERE name=?", (name,)).fetchone()
        return dict(r)

def set_student_active(student_id: int, active: bool) -> None:
    with connect() as con:
        con.execute("UPDATE students SET active=?, updated_at=? WHERE id=?", (1 if active else 0, now(), student_id))

def archive_student(student_id: int) -> None:
    """Hide a student while preserving historical drafts and send logs."""
    with connect() as con:
        found = con.execute("SELECT id FROM students WHERE id=?", (student_id,)).fetchone()
        if not found:
            raise ValueError("学生不存在")
        con.execute("UPDATE students SET active=0, updated_at=? WHERE id=?", (now(), student_id))

def save_week(label: str, course_intro: str, topics: list[str]) -> int:
    label, course_intro = label.strip(), course_intro.strip()
    topics = [str(x).strip() for x in topics if str(x).strip()]
    if not label or not course_intro or not topics:
        raise ValueError("周次、课程概述和知识点不能为空")
    with connect() as con:
        con.execute("INSERT INTO weeks(label,course_intro,topics_json,created_at) VALUES(?,?,?,?) ON CONFLICT(label) DO UPDATE SET course_intro=excluded.course_intro, topics_json=excluded.topics_json",
                    (label, course_intro, json.dumps(topics, ensure_ascii=False), now()))
        return int(con.execute("SELECT id FROM weeks WHERE label=?", (label,)).fetchone()[0])

def save_draft(week_id: int, student_id: int, notes: str, content: str, content_hash: str) -> int:
    with connect() as con:
        con.execute("""INSERT INTO drafts(week_id,student_id,notes,content,content_hash,status,error,updated_at)
          VALUES(?,?,?,?,?,'draft','',?)
          ON CONFLICT(week_id,student_id) DO UPDATE SET notes=excluded.notes,content=excluded.content,
          content_hash=excluded.content_hash,status='draft',error='',updated_at=excluded.updated_at,sent_at=NULL""",
                    (week_id, student_id, notes, content, content_hash, now()))
        return int(con.execute("SELECT id FROM drafts WHERE week_id=? AND student_id=?", (week_id, student_id)).fetchone()[0])

def update_draft(draft_id: int, content: str, content_hash: str) -> None:
    if not content.strip():
        raise ValueError("反馈正文不能为空")
    with connect() as con:
        con.execute("UPDATE drafts SET content=?,content_hash=?,status='draft',error='',updated_at=?,sent_at=NULL WHERE id=?",
                    (content.strip(), content_hash, now(), draft_id))

def mark_draft(draft_id: int, status: str, error: str = "") -> None:
    sent_at = now() if status == "sent" else None
    with connect() as con:
        con.execute("UPDATE drafts SET status=?,error=?,updated_at=?,sent_at=COALESCE(?,sent_at) WHERE id=?",
                    (status, error, now(), sent_at, draft_id))

def log_action(draft_id: int, action: str, result: dict) -> None:
    with connect() as con:
        con.execute("INSERT INTO send_logs(draft_id,action,result_json,created_at) VALUES(?,?,?,?)",
                    (draft_id, action, json.dumps(result, ensure_ascii=False), now()))

def list_students() -> list[dict]:
    return rows("SELECT * FROM students WHERE active=1 ORDER BY grade, id")

def list_drafts() -> list[dict]:
    """Return only the most recently generated batch; older weeks remain in history."""
    return rows("""SELECT d.*,s.name,s.grade,s.chat_title,w.label,w.course_intro,w.topics_json
      FROM drafts d JOIN students s ON s.id=d.student_id JOIN weeks w ON w.id=d.week_id
      WHERE d.week_id=(SELECT week_id FROM drafts ORDER BY updated_at DESC,id DESC LIMIT 1)
        AND d.status!='sent'
      ORDER BY d.id""")

def get_draft(draft_id: int) -> dict | None:
    return one("""SELECT d.*,s.name,s.grade,s.chat_title,w.label,w.course_intro,w.topics_json
      FROM drafts d JOIN students s ON s.id=d.student_id JOIN weeks w ON w.id=d.week_id WHERE d.id=?""", (draft_id,))

def recent_logs(limit: int = 50) -> list[dict]:
    return rows("""SELECT l.*,s.name,s.chat_title FROM send_logs l JOIN drafts d ON d.id=l.draft_id
      JOIN students s ON s.id=d.student_id ORDER BY l.id DESC LIMIT ?""", (limit,))
