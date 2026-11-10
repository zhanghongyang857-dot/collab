"""各命令行「会话没了」的报错都要判定为会话丢失，补叫才会开新会话（G015 复验 L1）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "core"))
import dispatch


class TestSessionLost(unittest.TestCase):
    def test_real_messages(self):
        for text in ("No conversation found with session ID: abc",
                     'session "00000000-0000-4000-8000-000000000000" does not exist; omit --session-id to start a new one'):
            self.assertTrue(dispatch.SESSION_LOST.search(text), text)

    def test_other_errors_are_not_lost(self):
        for text in ("Not logged in · Please run /login", "file does not exist: a.txt", "退出码 1"):
            self.assertFalse(dispatch.SESSION_LOST.search(text), text)


if __name__ == "__main__":
    unittest.main()
