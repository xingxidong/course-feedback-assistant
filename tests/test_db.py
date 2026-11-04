from __future__ import annotations
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from course_feedback import db

class DatabaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        self.patch = patch.object(db, "DB_PATH", self.db_path)
        self.patch.start()
        db.init_db()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_group_can_be_filled_later(self):
        student = db.upsert_student({"name": "测试学生", "grade": "高二", "chat_title": "", "default_notes": "认真"})
        self.assertEqual(student["chat_title"], "待填写：测试学生")
        self.assertEqual(len(db.list_students()), 1)

    def test_archive_and_reactivate_same_student(self):
        student = db.upsert_student({"name": "测试学生", "grade": "高二", "chat_title": "", "default_notes": "认真"})
        db.archive_student(student["id"])
        self.assertEqual(db.list_students(), [])
        restored = db.upsert_student({"name": "测试学生", "grade": "高三", "chat_title": "新群", "default_notes": "进步"})
        self.assertEqual(restored["id"], student["id"])
        self.assertEqual(restored["active"], 1)
        self.assertEqual(restored["chat_title"], "新群")

    def test_batch_replaces_unselected_and_is_explicit(self):
        a = db.upsert_student({"name": "甲", "grade": "高二", "chat_title": "甲群", "default_notes": ""})
        b = db.upsert_student({"name": "乙", "grade": "高二", "chat_title": "乙群", "default_notes": ""})
        make = lambda student, text: {"student_id": student["id"], "notes": "", "content": text, "content_hash": text}
        db.save_batch("第一周", "课程", ["知识点"], [make(a, "甲1"), make(b, "乙1")])
        self.assertEqual({x["name"] for x in db.list_drafts()}, {"甲", "乙"})
        db.save_batch("第一周", "课程", ["知识点"], [make(a, "甲2")])
        self.assertEqual([x["name"] for x in db.list_drafts()], ["甲"])
        db.save_batch("第二周", "新课程", ["新知识"], [make(b, "乙2")])
        old = db.one("SELECT id FROM drafts WHERE week_id=(SELECT id FROM weeks WHERE label='第一周') AND student_id=?", (a["id"],))
        db.update_draft(old["id"], "修改旧草稿", "hash")
        self.assertEqual([x["name"] for x in db.list_drafts()], ["乙"])

    def test_send_claim_is_atomic_and_sent_cannot_be_edited(self):
        student = db.upsert_student({"name": "甲", "grade": "高二", "chat_title": "甲群", "default_notes": ""})
        ids = db.save_batch("第一周", "课程", ["知识点"], [{"student_id": student["id"], "notes": "", "content": "正文", "content_hash": "h"}])
        draft_id = ids[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: db.claim_send(draft_id), range(2)))
        self.assertEqual(sorted(claims), [False, True])
        self.assertFalse(db.claim_send(draft_id))
        db.mark_draft(draft_id, "sent")
        with self.assertRaises(ValueError):
            db.update_draft(draft_id, "再次修改", "h2")
        with self.assertRaises(ValueError):
            db.save_batch("第一周", "课程更新", ["新知识点"], [{"student_id": student["id"], "notes": "", "content": "新正文", "content_hash": "h3"}])
        self.assertEqual(db.get_draft(draft_id)["status"], "sent")

    def test_inactive_student_cannot_be_claimed(self):
        student = db.upsert_student({"name": "甲", "grade": "高二", "chat_title": "甲群", "default_notes": ""})
        ids = db.save_batch("第一周", "课程", ["知识点"], [{"student_id": student["id"], "notes": "", "content": "正文", "content_hash": "h"}])
        db.archive_student(student["id"])
        self.assertFalse(db.claim_send(ids[0]))

if __name__ == "__main__":
    unittest.main()
