"""新结构项目的看板摘要（G037-T3）：项目列表和 NOW 任务标题后那一行，由 flow 视图算出。"""
import importlib.util
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC / "core"))
spec = importlib.util.spec_from_file_location("board_server_summary", SRC / "board" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def goal(gid, state, stages):
    return {"id": gid, "state": state, "stages": [{"order": i + 1, "state": s} for i, s in enumerate(stages)]}


class TestFlowGoalSummary(unittest.TestCase):
    def test_formats(self):
        v = {"goals": [goal("G001", "active", ["passed", "active", "not_started"]),
                       goal("G002", "active", ["active"]),
                       goal("G003", "active", ["passed", "passed"]),
                       goal("G004", "draft", []),
                       goal("G005", "done", ["passed"]),
                       goal("G006", "pending_approval", ["not_started"])],
             "tasks": [{"id": "G002-T1", "goal": "G002", "state": "blocked"}]}
        issues = [{"id": "I001", "stage": "pending_ruling", "archived": False},
                  {"id": "I002", "stage": "pending_ruling", "archived": True},
                  {"id": "I003", "stage": "discussing", "archived": False}]
        self.assertEqual(server.flow_goal_summary(v, issues), "G001 ②/3 · G002 受阻 · G003 待批准完成 · I001 待裁决")

    def test_empty(self):
        self.assertEqual(server.flow_goal_summary({"goals": [], "tasks": []}, []), "")


if __name__ == "__main__":
    unittest.main()
