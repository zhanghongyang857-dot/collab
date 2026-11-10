"""演示案例「万历新政」的回归测试：每一回都重新生成，视图模型和期望文件逐字节比对，并且不能有检查错误。

期望文件在 tests/样例/演示/第N回.json；改了剧情或流转规则、确认新输出没问题后，用 UPDATE_GOLDEN=1 重新生成。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # 仓库根
sys.path.insert(0, str(ROOT / "src" / "core"))
sys.path.insert(0, str(ROOT / "demo"))
import flow  # noqa: E402
import build  # noqa: E402

GOLDEN = HERE / "样例" / "演示"


class TestDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.views, cls.checks = {}, {}
        for n in range(1, len(build.STORY) + 1):
            out = build.build(Path(cls.tmp.name) / f"第{n}回", n)
            proj = flow.Project(out)
            cls.views[n] = flow.view(proj)
            cls.checks[n] = flow.check(proj, now=flow.project_now(proj))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_chapter_matches_golden(self):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for n, v in self.views.items():
            path = GOLDEN / f"第{n}回.json"
            text = flow.dumps(v) + "\n"
            if os.environ.get("UPDATE_GOLDEN") or not path.exists():
                path.write_text(text, encoding="utf-8")
            with self.subTest(回=n):
                self.assertEqual(path.read_text(encoding="utf-8"), text, f"第{n}回的视图模型变了")

    def test_no_errors_in_any_chapter(self):
        for n, items in self.checks.items():
            with self.subTest(回=n):
                self.assertEqual([x["msg"] for x in items if x["level"] == "error"], [])

    def test_story_beats(self):
        pending = {n: [d["编号"] for d in v["待你决定"]] for n, v in self.views.items()}
        self.assertEqual(pending[3], ["G001-T2"])   # 待批内帑
        self.assertEqual(pending[4], ["G002-T2"])   # 江南阻丈，请遣钦差
        self.assertEqual(pending[7], ["G002"])      # 清丈告成待结案
        self.assertTrue(any("偏离" in x["msg"] for x in self.checks[5]))  # 陛下特许兵部先行接洽
        end = {g["编号"]: g["状态"] for g in self.views[8]["目标"]}
        self.assertEqual(end, {"G001": "完成", "G002": "完成", "G003": "完成", "G004": "进行中", "G005": "起草", "G006": "起草"})
        stage = {g["编号"]: g.get("起草阶段") for g in self.views[8]["目标"] if g["状态"] == "起草"}
        self.assertEqual(stage, {"G005": "讨论", "G006": "想法"})  # 每个想法先立案，终回「想法」页有两件
        i3 = next(i for i in self.views[8]["议题"] if i["编号"] == "I003")
        self.assertIn("工部", [x["成员"] for x in i3["与会"]])  # I003 陛下中途加人
        self.assertEqual(self.views[8]["称谓"]["总裁"], "陛下")
        self.assertTrue(all(v["零散"] is None for v in self.views.values()))  # 演示里每件差事都属于国事

    def test_relation_graph_now(self):
        """关系图的「现在」：每个未结束任务的最后一个交接切面就是「当前」那条边；终回四种情形都有：成员之间的交接、奏报受阻、转呈陛下、在办。"""
        for n, v in self.views.items():
            for t in v["任务"]:
                cur = next((c for c in v["当前"] if c["对象"] == t["编号"]), None)
                if cur:
                    last = t["交接"][-1]
                    self.assertEqual((cur["发起"], cur["接收"], cur["状态"]), (last["发起"], last["持有人"], last["状态"]), (n, t["编号"]))
        now = {c["对象"]: (c["发起"], c["接收"], c["状态"]) for c in self.views[8]["当前"]}
        self.assertEqual(now, {"G004-T2": ("户部", "翰林院", "待验收"), "G004-T3": ("兵部", "总管", "受阻"),
                               "G004-T4": ("总管", "总裁", "受阻"), "G004-T5": ("总管", "都察院", "执行中")})
        self.assertEqual([d["编号"] for d in self.views[8]["待你决定"]], ["G004-T4"])  # 终回停在待批红

    def test_all_edges_appear(self):
        out = Path(self.tmp.name) / "第8回"
        _, evs, _ = flow.replay_all(flow.Project(out))
        seen = {r["边"] for rows in evs.values() for r in rows}
        proj = flow.Project(out)
        wanted = set(proj.skeleton("任务")["边"]) | set(proj.skeleton("目标")["边"]) | set(flow.SPECIAL)
        self.assertEqual(wanted - seen, set())


if __name__ == "__main__":
    unittest.main()
