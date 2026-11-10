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
    return {"编号": gid, "状态": state, "阶段": [{"序": i + 1, "状态": s} for i, s in enumerate(stages)]}


class TestFlowGoalSummary(unittest.TestCase):
    def test_formats(self):
        v = {"目标": [goal("G001", "进行中", ["通过", "进行中", "未开始"]),
                      goal("G002", "进行中", ["进行中"]),
                      goal("G003", "进行中", ["通过", "通过"]),
                      goal("G004", "起草", []),
                      goal("G005", "完成", ["通过"]),
                      goal("G006", "待批准", ["未开始"])],
             "任务": [{"编号": "G002-T1", "目标": "G002", "状态": "受阻"}]}
        issues = [{"id": "I001", "stage": "待裁决", "archived": False},
                  {"id": "I002", "stage": "待裁决", "archived": True},
                  {"id": "I003", "stage": "讨论中", "archived": False}]
        self.assertEqual(server.flow_goal_summary(v, issues), "G001 ②/3 · G002 受阻 · G003 待批准完成 · I001 待裁决")

    def test_empty(self):
        self.assertEqual(server.flow_goal_summary({"目标": [], "任务": []}, []), "")


if __name__ == "__main__":
    unittest.main()
