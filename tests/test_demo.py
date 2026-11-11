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
        pending = {n: [d["id"] for d in v["decisions"]] for n, v in self.views.items()}
        self.assertEqual(pending[3], ["G001-T2"])   # 待批内帑
        self.assertEqual(pending[4], ["G002-T2"])   # 江南阻丈，请遣钦差
        self.assertEqual(pending[7], ["G002"])      # 清丈告成待结案
        self.assertTrue(any("偏离" in x["msg"] for x in self.checks[5]))  # 陛下特许兵部先行接洽
        end = {g["id"]: g["state"] for g in self.views[8]["goals"]}
        self.assertEqual(end, {"G001": "done", "G002": "done", "G003": "done", "G004": "active", "G005": "draft", "G006": "draft"})
        stage = {g["id"]: g.get("draft_stage") for g in self.views[8]["goals"] if g["state"] == "draft"}
        self.assertEqual(stage, {"G005": "discussion", "G006": "idea"})  # 每个想法先立案，终回「想法」页有两件
        i3 = next(i for i in self.views[8]["issues"] if i["id"] == "I003")
        self.assertIn("工部", [x["member"] for x in i3["attendees"]])  # I003 陛下中途加人
        import json  # 明朝叫法写在演示项目 config.json 的 names（只用在看板上）
        self.assertEqual(json.loads((Path(self.tmp.name) / "第8回" / "collab" / "config.json").read_text(encoding="utf-8"))["names"]["seat"]["owner"], "陛下")
        self.assertTrue(all(v["loose"] is None for v in self.views.values()))  # 演示里每件差事都属于国事

    def test_relation_graph_now(self):
        """关系图的「现在」：每个未结束任务的最后一个交接切面就是「当前」那条边；终回四种情形都有：成员之间的交接、奏报受阻、转呈陛下、在办。"""
        for n, v in self.views.items():
            for t in v["tasks"]:
                cur = next((c for c in v["current"] if c["object"] == t["id"]), None)
                if cur:
                    last = t["handoffs"][-1]
                    self.assertEqual((cur["from"], cur["to"], cur["state"]), (last["from"], last["holder"], last["state"]), (n, t["id"]))
        now = {c["object"]: (c["from"], c["to"], c["state"]) for c in self.views[8]["current"]}
        self.assertEqual(now, {"G004-T2": ("户部", "翰林院", "in_review"), "G004-T3": ("兵部", "lead", "blocked"),
                               "G004-T4": ("lead", "owner", "blocked"), "G004-T5": ("lead", "都察院", "in_progress")})
        self.assertEqual([d["id"] for d in self.views[8]["decisions"]], ["G004-T4"])  # 终回停在待批红

    def test_all_edges_appear(self):
        out = Path(self.tmp.name) / "第8回"
        _, evs, _ = flow.replay_all(flow.Project(out))
        seen = {r["edge"] for rows in evs.values() for r in rows}
        proj = flow.Project(out)
        wanted = set(proj.skeleton("task")["edges"]) | set(proj.skeleton("goal")["edges"]) | set(flow.SPECIAL)
        wanted -= {"withdraw", "redraft"}  # 批准前整版重写框架才有，演示不演，由 test_frame.TestDraftRewrite 覆盖
        self.assertEqual(wanted - seen, set())


if __name__ == "__main__":
    unittest.main()


GOLDEN_EN = HERE / "样例" / "演示-en"
CJK = __import__("re").compile(r"[　-〿㐀-鿿＀-￯]")  # 汉字和中文标点（含全角｜：英文卡头用半角 |）


class TestDemoEnglish(unittest.TestCase):
    """英文万历演示（build.py --lang en）：单独一套期望文件；输出没有中文；和中文版回放出的状态序列相同。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out, cls.views, cls.checks, cls.missing = {}, {}, {}, {}
        for lang in ("zh", "en"):
            for n in range(1, len(build.STORY) + 1):
                out = build.build(Path(cls.tmp.name) / lang / f"c{n}", n, lang)
                proj = flow.Project(out)
                cls.out[lang, n] = out
                cls.views[lang, n] = flow.view(proj)
                cls.checks[lang, n] = flow.check(proj, now=flow.project_now(proj))
                cls.missing[lang, n] = list(build.MISSING)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_chapter_matches_golden(self):
        GOLDEN_EN.mkdir(parents=True, exist_ok=True)
        for n in range(1, len(build.STORY) + 1):
            path = GOLDEN_EN / f"chapter-{n}.json"
            text = flow.dumps(self.views["en", n]) + "\n"
            if os.environ.get("UPDATE_GOLDEN") or not path.exists():
                path.write_text(text, encoding="utf-8")
            with self.subTest(chapter=n):
                self.assertEqual(path.read_text(encoding="utf-8"), text, f"chapter {n} view model changed")

    def test_no_errors_and_nothing_untranslated(self):
        for n in range(1, len(build.STORY) + 1):
            with self.subTest(chapter=n):
                self.assertEqual([x["msg"] for x in self.checks["en", n] if x["level"] == "error"], [])
                self.assertEqual(self.missing["en", n], [])

    def test_no_chinese_in_output(self):
        out = self.out["en", len(build.STORY)]
        bad = []
        for f in sorted(out.rglob("*")):
            if f.is_file():
                bad += [f"{f.relative_to(out)}: {l[:80]}" for l in f.read_text(encoding="utf-8", errors="ignore").splitlines() if CJK.search(l)]
        self.assertEqual(bad, [])

    def test_same_state_sequence_as_chinese(self):
        """每一回、每个对象：事件条数、seq、边、结果、前后状态都和中文版一样；只换了文字。"""
        def seq(v):
            return {g["id"]: [(e["project_seq"], e["object"], e["edge"], e.get("result"), e.get("from_state"), e.get("to_state"), e.get("time"))
                              for e in g["events"]] for g in v["goals"] + [v["loose"]] if g}
        for n in range(1, len(build.STORY) + 1):
            zh, en = self.views["zh", n], self.views["en", n]
            with self.subTest(chapter=n):
                self.assertEqual(seq(en), seq(zh))
                self.assertEqual([(t["id"], t["state"], t["stage"]) for t in en["tasks"]], [(t["id"], t["state"], t["stage"]) for t in zh["tasks"]])
                self.assertEqual([(g["id"], g["state"]) for g in en["goals"]], [(g["id"], g["state"]) for g in zh["goals"]])
                self.assertEqual([(i["id"], i["state"], i["post_count"]) for i in en["issues"]], [(i["id"], i["state"], i["post_count"]) for i in zh["issues"]])
                self.assertEqual([d["id"] for d in en["decisions"]], [d["id"] for d in zh["decisions"]])

    def test_ming_titles_come_from_config_names(self):
        import json
        for lang, owner, lead in (("zh", "陛下", "内阁"), ("en", "the Throne", "Grand Secretariat")):
            cfg = json.loads((self.out[lang, 1] / "collab" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual((cfg["lang"], cfg["names"]["seat"]["owner"], cfg["names"]["seat"]["lead"]), (lang, owner, lead))
            self.assertEqual(self.views[lang, 1]["titles"], {})  # 不再用渲染规约的「称谓」
