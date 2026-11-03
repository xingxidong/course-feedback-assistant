from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from course_feedback import generator

class GeneratorTests(unittest.TestCase):
    def test_feedback_structure(self):
        text = generator.deterministic_generate("皓轩", "本节课主要预习动量与磁场相关知识", ["动量守恒", "人船模型", "磁聚焦"], "听课认真，物理思维好，成绩有进步，但不够稳定")
        self.assertIn("课程内容：", text)
        self.assertIn("课堂表现：", text)
        self.assertIn("皓轩", text)
        self.assertIn("动量守恒", text)
        self.assertNotIn("笨", text)
    def test_negative_words_are_reframed(self):
        text = generator.deterministic_generate("小朱", "复习期中考试内容", ["电场", "电流", "闭合电路欧姆定律"], "有点笨，坐不住，不去思考，不背公式，作业完成不好")
        self.assertNotIn("笨", text)
        self.assertIn("专注", text)
        self.assertIn("公式", text)
    def test_hash_stable(self):
        self.assertEqual(generator.content_hash("abc"), generator.content_hash("abc"))
        self.assertNotEqual(generator.content_hash("abc"), generator.content_hash("abd"))

if __name__ == "__main__": unittest.main()
