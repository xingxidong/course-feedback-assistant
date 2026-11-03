#!/usr/bin/env python3
"""Local-only course-feedback workbench."""
from __future__ import annotations

import json
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from course_feedback import db, generator, wechat

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
HOST, PORT = "127.0.0.1", 8765

class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message

class Handler(BaseHTTPRequestHandler):
    server_version = "CourseFeedback/1.0"

    def log_message(self, fmt, *args):
        (ROOT / "logs").mkdir(exist_ok=True)
        with (ROOT / "logs" / "server.log").open("a", encoding="utf-8") as f:
            f.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000: raise ApiError(413, "请求内容过大")
        try: return json.loads(self.rfile.read(length) or b"{}")
        except Exception: raise ApiError(400, "JSON格式错误")

    def _file(self, path: Path):
        if not path.is_file(): raise ApiError(404, "页面不存在")
        raw = path.read_bytes(); ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/": return self._file(STATIC / "index.html")
            if path.startswith("/static/"):
                target = (STATIC / path.removeprefix("/static/")).resolve()
                if STATIC.resolve() not in target.parents: raise ApiError(403, "禁止访问")
                return self._file(target)
            if path == "/api/state":
                return self._json({"ok": True, "students": db.list_students(), "drafts": db.list_drafts(), "logs": db.recent_logs(), "wechat": wechat.status()})
            raise ApiError(404, "接口不存在")
        except ApiError as e: self._json({"ok": False, "error": e.message}, e.status)
        except Exception as e: self._json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
        try:
            path, body = urlparse(self.path).path, self._body()
            if path == "/api/students":
                try: student = db.upsert_student(body)
                except Exception as e: raise ApiError(400, str(e))
                return self._json({"ok": True, "student": student})
            m = re.fullmatch(r"/api/students/(\d+)/active", path)
            if m:
                db.set_student_active(int(m.group(1)), bool(body.get("active")))
                return self._json({"ok": True})
            if path == "/api/generate":
                label = str(body.get("label", "")).strip()
                intro = str(body.get("course_intro", "")).strip()
                topics = body.get("topics", [])
                if isinstance(topics, str): topics = [x.strip() for x in topics.splitlines() if x.strip()]
                try: week_id = db.save_week(label, intro, topics)
                except Exception as e: raise ApiError(400, str(e))
                selected = {int(x) for x in body.get("student_ids", [])}
                notes_by_id = {int(k): str(v) for k, v in body.get("student_notes", {}).items()}
                students = [s for s in db.list_students() if s["active"] and (not selected or s["id"] in selected)]
                if not students: raise ApiError(400, "没有选中学生")
                ids = []
                for s in students:
                    notes = notes_by_id.get(s["id"], "").strip() or s["default_notes"]
                    content = generator.generate(s["name"], intro, topics, notes)
                    ids.append(db.save_draft(week_id, s["id"], notes, content, generator.content_hash(content)))
                return self._json({"ok": True, "draft_ids": ids, "count": len(ids)})
            m = re.fullmatch(r"/api/drafts/(\d+)", path)
            if m:
                draft_id = int(m.group(1)); content = str(body.get("content", "")).strip()
                try: db.update_draft(draft_id, content, generator.content_hash(content))
                except Exception as e: raise ApiError(400, str(e))
                return self._json({"ok": True})
            m = re.fullmatch(r"/api/drafts/(\d+)/(prepare|send)", path)
            if m:
                draft_id, action = int(m.group(1)), m.group(2)
                draft = db.get_draft(draft_id)
                if not draft: raise ApiError(404, "草稿不存在")
                if action == "send" and body.get("confirmation") != "确认发送": raise ApiError(400, "缺少发送确认")
                if action == "send" and draft["status"] == "sent" and not body.get("force"): raise ApiError(409, "该反馈已经发送；如需重发必须明确选择强制重发")
                result = wechat.prepare(draft["chat_title"], draft["content"]) if action == "prepare" else wechat.send(draft["chat_title"], draft["content"])
                db.log_action(draft_id, action, result)
                db.mark_draft(draft_id, "prepared" if action == "prepare" and result.get("ok") else "sent" if action == "send" and result.get("ok") else "error", "" if result.get("ok") else result.get("detail") or result.get("error", "失败"))
                return self._json(result, 200 if result.get("ok") else 502)
            if path == "/api/send-batch":
                if body.get("confirmation") != "确认发送": raise ApiError(400, "必须输入“确认发送”")
                ids = [int(x) for x in body.get("draft_ids", [])]
                if not ids: raise ApiError(400, "没有选中草稿")
                results = []
                for draft_id in ids:
                    draft = db.get_draft(draft_id)
                    if not draft:
                        results.append({"id": draft_id, "ok": False, "error": "草稿不存在"}); continue
                    if draft["status"] == "sent":
                        results.append({"id": draft_id, "name": draft["name"], "ok": False, "error": "已发送，已跳过"}); continue
                    result = wechat.send(draft["chat_title"], draft["content"])
                    db.log_action(draft_id, "send", result)
                    db.mark_draft(draft_id, "sent" if result.get("ok") else "error", "" if result.get("ok") else result.get("detail") or result.get("error", "失败"))
                    results.append({"id": draft_id, "name": draft["name"], **result})
                    time.sleep(2)
                return self._json({"ok": all(x.get("ok") for x in results), "results": results})
            raise ApiError(404, "接口不存在")
        except ApiError as e: self._json({"ok": False, "error": e.message}, e.status)
        except Exception as e: self._json({"ok": False, "error": str(e)}, 500)

if __name__ == "__main__":
    db.init_db()
    print(f"课程反馈工作台：http://{HOST}:{PORT}")
    print("仅监听本机，不会暴露到局域网。按 Control+C 停止。")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
