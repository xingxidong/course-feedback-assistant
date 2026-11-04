from __future__ import annotations
import unittest
from unittest.mock import patch

from course_feedback import wechat_gui

class WeChatSendSafetyTests(unittest.TestCase):
    def test_error_before_send_is_normal_failure(self):
        with patch.object(wechat_gui, "_open_verified_chat", side_effect=RuntimeError("not found")):
            result = wechat_gui.send("群", "正文")
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("uncertain", False))

    def test_error_after_send_trigger_is_uncertain(self):
        with patch.object(wechat_gui, "_open_verified_chat", return_value={"bounds": [0, 0, 1000, 700]}), \
             patch.object(wechat_gui, "_write_and_verify"), \
             patch.object(wechat_gui, "_keys", side_effect=RuntimeError("post-send read failed")):
            result = wechat_gui.send("群", "正文")
        self.assertFalse(result["ok"])
        self.assertTrue(result["uncertain"])
        self.assertEqual(result["error"], "WECHAT_DELIVERY_UNCERTAIN")

if __name__ == "__main__":
    unittest.main()
