"""语言包（src/i18n/）：两种语言逐键对齐；代码、中英显示名都能反查代码；中文命令行写法和英文等价（G036-T3）。"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE))
import flow  # noqa: E402
import i18n  # noqa: E402
import vocab  # noqa: E402
from test_flow import Base, Sim  # noqa: E402


class TestPacks(unittest.TestCase):
    def test_keys_aligned(self):
        self.assertEqual(i18n.missing_keys(), {})

    def test_every_code_has_a_name(self):
        zh = i18n.raw("zh")["names"]
        for ns in ("State", "Edge", "Seat", "Result", "Category", "StageStatus", "Speech", "RunStatus", "RunPhase"):
            kind = i18n.kind_key(ns)
            for code in vocab.as_dict()[ns].values():
                self.assertIn(code, zh[kind], (kind, code))
        self.assertEqual(set(i18n.raw("zh")["sections"]), set(vocab.as_dict()["Section"].values()))

    def test_code_of_both_languages(self):
        self.assertEqual(i18n.code_of("edge", "交付"), "deliver")
        self.assertEqual(i18n.code_of("edge", "Deliver"), "deliver")
        self.assertEqual(i18n.code_of("edge", "deliver"), "deliver")
        self.assertEqual(i18n.code_of("result", "通过"), "pass")
        self.assertEqual(i18n.code_of("state", "通过"), "passed")
        self.assertEqual(i18n.code_of("section", "交接"), "handoff")
        self.assertEqual(i18n.code_of("section", "Handoff"), "handoff")
        self.assertEqual(i18n.heading_codes("总结（总管）"), "summary")
        self.assertIsNone(i18n.code_of("edge", "不存在"))

    def test_zh_text_unchanged(self):
        L = i18n.pack("zh")
        self.assertEqual(L.st("in_progress"), "执行中")
        self.assertEqual(L.edge_res("review", "needs_more"), "确认：需补充")
        self.assertEqual(L.who("owner"), "总裁")
        self.assertEqual(L.t("block.decisions.empty"), "（没有需要你拍板的事）")


class TestCliAliases(Base):
    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = flow.main(["--project", str(self.root), *args])
        return code, out.getvalue()

    def test_chinese_and_english_commands_are_the_same(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="甲", 依据="总裁：做")
        code, zh = self.run_cli("记", t, "派发", "--给", "codex", "--作为", "总管", "--说明", "派")
        self.assertEqual(code, 0)
        self.assertIn("「派发」总管 → codex，已批准 → 已交接", zh)
        code, en = self.run_cli("log", t, "pick_up", "--as", "codex", "--note", "接")
        self.assertEqual(code, 0)
        self.assertIn("「接手」codex → codex，已交接 → 执行中", en)
        code, _ = self.run_cli("log", t, "Escalate", "--as", "codex", "--note", "卡住")
        self.assertEqual(code, 0)
        rows = [json.loads(l) for l in (self.root / "collab" / "internal" / "flow" / f"{t}.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["edge"] for r in rows][-3:], ["dispatch", "pick_up", "escalate"])
        self.assertTrue(all(r["v"] == 2 for r in rows))

    def test_old_format_refused(self):
        sim = Sim(self.root)
        (self.root / "collab" / "config.json").unlink()
        sim.proj = flow.Project(self.root)
        with self.assertRaises(flow.FlowError) as e:
            sim.new("目标", 标题="x")
        self.assertIn("init.sh migrate", e.exception.msg)


if __name__ == "__main__":
    unittest.main()
