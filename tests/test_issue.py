"""议题（朝会）的测试：骨架 core/skeletons/issue.json 和 flow.py 的写入、回放、检查（方案 03 第 10 节）。

全部用模拟数据；运行：python3 -m unittest discover -s tests
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE))
import flow  # noqa: E402
import zh  # noqa: E402
from test_flow import Base, Sim  # noqa: E402

WHO = ["codex:从实现成本看", "deepseek:从风险看"]


def say(sim: Sim, obj: str, who: str, text: str = "", edge: str = "发言", **kw):
    sim.tick(3)
    args = {"发起": who, "写入者": "看板" if who == "总裁" else ("总管" if who == "总管" else "成员"), **kw}
    if edge == "发言":
        args["body"] = text or f"{who} 的模拟发言"
    ev, _ = zh.record(sim.proj, obj, edge, args)
    return ev


def meeting(sim: Sim, **kw) -> str:
    return sim.new("议题", 标题="缓存方案", 与会=list(WHO), 依据="总裁：开个朝会定缓存方案", **kw)


def state(sim: Sim, obj: str):
    states, _, _ = flow.replay_all(sim.proj)
    return states[obj]


class TestIssueSkeleton(Base):
    def test_skeleton_loads_clean(self):
        sim = Sim(self.root)
        self.assertEqual(flow.check_skeletons(sim.proj), [])

    def test_broken_message_state_is_reported(self):
        sim = Sim(self.root)
        sk = json.loads((flow.SKEL_DIR / "issue.json").read_text(encoding="utf-8"))
        sk["message_events"]["post"]["allowed_in"] = ["开会中"]
        (sim.root / "collab" / "internal" / "plans" / "issue.json").write_text(json.dumps(sk, ensure_ascii=False), encoding="utf-8")
        msgs = [x["msg"] for x in flow.check_skeletons(flow.Project(sim.root))]
        self.assertTrue(any("开会中" in m for m in msgs), msgs)


class TestProjectMeeting(Base):
    def test_full_meeting(self):
        sim = Sim(self.root)
        i = meeting(sim)
        self.assertEqual(i, "I001")
        st = state(sim, i)
        self.assertEqual((st["state"], st["holder"], st["type"]), ("draft", "lead", "council"))
        self.assertEqual([x["member"] for x in st["attendees"]], ["codex", "deepseek"])
        self.assertTrue((sim.root / "collab" / "issues" / "I001-缓存方案.md").exists())

        sim.log(i, "开始", "总裁", 写入者="看板")
        self.assertEqual(state(sim, i)["holder"], "owner")
        self.assertEqual(sim.view()["decisions"], [], "讨论中是总裁在主持，不进待你决定")
        say(sim, i, "codex", "主张本地缓存")
        say(sim, i, "deepseek", "主张不缓存")
        say(sim, i, "总裁", "你说说风险", 点名=["deepseek"], 类型="提问")
        say(sim, i, "deepseek", "风险在一致性，@codex 你怎么保证", 点名=["codex"])
        ev = say(sim, i, "codex", edge="PASS")
        self.assertNotIn("正文", ev)
        say(sim, i, "deepseek", "只给总裁：codex 低估了工期", 私下=True)
        st = state(sim, i)
        self.assertEqual((st["state"], st["holder"]), ("discussing", "owner"), "发言不改状态和持有人")
        rows = [e for e in st["events"] if e["edge"] == "post"]
        self.assertEqual(rows[2].get("type"), "提问")
        self.assertTrue(rows[-1].get("private"))

        sim.log(i, "结束讨论", "总裁", 写入者="看板")
        self.assertEqual(state(sim, i)["holder"], "lead")
        sim.log(i, "总结", 说明="共识：先不缓存；分歧：工期", 方案="A 不缓存；B 本地缓存", 建议="A")
        dec = sim.view()["decisions"]
        self.assertEqual([(d["id"], d["type"]) for d in dec], [(i, "ruling")])
        sim.log(i, "裁决", "总裁", 依据="总裁：按 A", 说明="不缓存，三个月后复查")
        self.assertEqual(state(sim, i)["state"], "ruled")
        self.assertEqual(sim.view()["decisions"], [])
        self.assertEqual(self.errors(sim.check()), [])

    def test_rules(self):
        sim = Sim(self.root)
        i = meeting(sim)
        with self.assertRaises(flow.FlowError) as e:
            say(sim, i, "codex", "抢跑")
        self.assertEqual(e.exception.kind, "rule")
        self.assertIn("只有讨论中", e.exception.msg)
        with self.assertRaises(flow.FlowError) as e:
            sim.log(i, "开始")
        self.assertIn("只能由总裁发起", e.exception.msg)
        sim.log(i, "开始", "总裁")
        with self.assertRaises(flow.FlowError) as e:
            say(sim, i, "claude", "我也说两句")
        self.assertIn("不在 I001 的与会名单里", e.exception.msg)
        with self.assertRaises(flow.FlowError) as e:
            say(sim, i, "codex", "@claude", 点名=["claude"])
        self.assertEqual(e.exception.kind, "hard")
        with self.assertRaises(flow.FlowError) as e:
            zh.record(sim.proj, i, "发言", {"发起": "codex", "正文": "  "})
        self.assertIn("正文", e.exception.msg)
        with self.assertRaises(flow.FlowError) as e:
            sim.log(i, "总结", 说明="…", 方案="…", 建议="…")
        self.assertIn("现在是「讨论中」", e.exception.msg)
        t = sim.new("任务", 标题="零散")
        with self.assertRaises(flow.FlowError) as e:
            say(sim, t, "总管", "任务上不能发言")
        self.assertIn("只用于议题", e.exception.msg)
        with self.assertRaises(flow.FlowError):
            sim.new("议题", 标题="没人", 与会=[], 依据="总裁：开会")
        with self.assertRaises(flow.FlowError) as e:
            sim.new("议题", 标题="总裁与会", 与会=["总裁"], 依据="总裁：开会")
        self.assertIn("不在花名册", e.exception.msg)

    def test_only_boss_mentions_wake(self):
        sim = Sim(self.root)
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        say(sim, i, "codex", "立场 @deepseek 你看呢", 点名=["deepseek"])
        self.assertTrue(flow.issue_needs(state(sim, i), "deepseek", None), "没开过口的总要叫")
        say(sim, i, "codex", "我先说了")
        say(sim, i, "deepseek", "我也说了")
        st = state(sim, i)
        self.assertFalse(flow.issue_needs(st, "codex", 0), "成员 @ 成员不算")
        say(sim, i, "总裁", "悄悄话 @codex", 点名=["codex"], 私下=True)
        self.assertFalse(flow.issue_needs(state(sim, i), "codex", 0), "私下点名不叫醒")
        say(sim, i, "总裁", "@codex 公开问你", 点名=["codex"])
        self.assertTrue(flow.issue_needs(state(sim, i), "codex", 0))

    def test_continue_discussion(self):
        sim = Sim(self.root)
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        sim.log(i, "结束讨论", "总裁")
        sim.log(i, "继续讨论", "总裁", 说明="还没问清")
        say(sim, i, "codex", "补充")
        sim.log(i, "结束讨论", "总裁")
        sim.log(i, "总结", 说明="…", 方案="A；B", 建议="A")
        sim.log(i, "继续讨论", "总裁")
        self.assertEqual(state(sim, i)["state"], "discussing")
        sim.log(i, "取消", "总裁", 说明="不议了")
        self.assertEqual(self.errors(sim.check()), [])
        with self.assertRaises(flow.FlowError):
            say(sim, i, "codex", "取消之后")


class TestFrameworkReview(Base):
    def draft_goal(self, sim):
        g = sim.new("目标", 类型="调研", 标题="框架对比")
        sim.log(g, "提交", 说明="按调研模板两阶段")
        return g

    def test_review_merges_into_approval(self):
        sim = Sim(self.root)
        g = self.draft_goal(sim)
        i = sim.new("议题", 标题="框架会审", 目标=g, 类型="会审", 与会=list(WHO), 依据="总裁：要会审")
        self.assertEqual([d["id"] for d in sim.view()["decisions"]], [], "会审中不该批")
        sim.log(i, "开始", "总裁")
        say(sim, i, "codex", "支持，风险是检索面太窄")
        say(sim, i, "deepseek", "反对，要加验收阶段")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(g, "批准", "总裁", 依据="总裁：批", 人选={1: ["codex"], 2: ["deepseek"]})
        self.assertIn("会审 I001 还没收口", e.exception.msg)
        sim.log(i, "结束讨论", "总裁")
        sim.log(i, "总结", 说明="共识：加验收", 方案="A 加第三方验收；B 不加", 建议="A")
        dec = sim.view()["decisions"]
        self.assertEqual([(d["id"], d["type"]) for d in dec], [(g, "approve_plan")])
        self.assertEqual(dec[0]["reviews"], ["I001"])
        self.assertIn("批准框架（附会审 I001）", "\n".join(flow.decision_lines(sim.view())))
        self.assertEqual(dec[0]["reviews"], [i])
        sim.log(g, "批准", "总裁", 依据="总裁：按会审加验收", 人选={1: ["codex"], 2: ["deepseek"]}, 第三方验收="claude")
        st = state(sim, i)
        self.assertEqual(st["state"], "ruled")
        last = st["events"][-1]
        self.assertEqual((last["edge"], last["basis"], last["note"]), ("rule", "总裁：按会审加验收", f"随 {g}「批准」裁决"))
        self.assertEqual(sim.view()["decisions"], [])
        self.assertEqual(self.errors(sim.check()), [])

    def test_review_needs_pending_goal(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="调研", 标题="框架对比")
        with self.assertRaises(flow.FlowError) as e:
            sim.new("议题", 标题="会审", 目标=g, 类型="会审", 与会=list(WHO), 依据="总裁：会审")
        self.assertIn("待批准", e.exception.msg)
        with self.assertRaises(flow.FlowError) as e:
            sim.new("议题", 标题="会审", 类型="会审", 与会=list(WHO), 依据="总裁：会审")
        self.assertIn("--目标", e.exception.msg)
        i = sim.new("议题", 标题="挂目标的朝会", 目标=g, 与会=list(WHO), 依据="总裁：先聊聊")
        self.assertEqual(state(sim, i)["goal"], g)

    def test_return_also_closes_review(self):
        sim = Sim(self.root)
        g = self.draft_goal(sim)
        i = sim.new("议题", 标题="框架会审", 目标=g, 类型="会审", 与会=list(WHO), 依据="总裁：要会审")
        sim.log(i, "开始", "总裁")
        sim.log(i, "结束讨论", "总裁")
        sim.log(i, "总结", 说明="都反对", 方案="A 退回重写；B 照批", 建议="A")
        sim.log(g, "退回", "总裁", 说明="按会审意见重写")
        self.assertEqual(state(sim, i)["state"], "ruled")
        self.assertEqual(state(sim, g)["state"], "draft")
        self.assertEqual(self.errors(sim.check()), [])


class TestIssueProjection(Base):
    def full(self, sim):
        i = meeting(sim)
        card = sim.root / "collab" / "issues" / f"{i}-缓存方案.md"
        card.write_text(card.read_text(encoding="utf-8").replace("- 要决定什么：", "- 要决定什么：要不要加本地缓存"),
                        encoding="utf-8")
        sim.log(i, "开始", "总裁")
        say(sim, i, "codex", "## 立场\n主张本地缓存")
        say(sim, i, "deepseek", "主张不缓存")
        say(sim, i, "总裁", "@deepseek 风险在哪", 点名=["deepseek"])
        say(sim, i, "deepseek", "一致性，@codex 怎么保证", 点名=["codex"])
        say(sim, i, "codex", "版本号失效")
        say(sim, i, "deepseek", "codex 低估了工期", 私下=True)
        say(sim, i, "codex", edge="PASS")
        sim.log(i, "结束讨论", "总裁")
        sim.log(i, "总结", 说明="共识：可以缓存但要失效机制", 方案="A 缓存 + 版本号；B 不缓存", 建议="A")
        return i

    def test_view_and_golden(self):
        sim = Sim(self.root)
        i = self.full(sim)
        v = sim.view()
        iv = v["issues"][0]
        self.assertEqual([m["type"] for m in iv["messages"]], ["position", "position", "question", "answer", "answer", "private", "pass"])
        self.assertEqual(iv["summary"]["recommendation"], "A")
        self.assertIsNone(iv["ruling"])
        self.assertEqual(iv["post_count"], 6)
        self.assertLess(iv["start_seq"], iv["end_seq"])
        self.golden("朝会", v)
        self.assertEqual(flow.dumps(sim.view()), flow.dumps(v), "同样输入两次输出相同")

    def test_cards_render(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="调研", 标题="框架对比")
        sim.log(g, "提交", 说明="两阶段")
        r = sim.new("议题", 标题="框架会审", 目标=g, 类型="会审", 与会=list(WHO), 依据="总裁：会审")
        i = self.full(sim)
        card = (sim.root / "collab" / "issues" / f"{i}-缓存方案.md").read_text(encoding="utf-8")
        self.assertIn("状态：待裁决 ｜ 类型：朝会 ｜ 目标：— ｜ 持有人：总裁 ｜ 发言：6", card)
        self.assertIn("| codex | 从实现成本看 |", card)
        self.assertIn("| deepseek | 回答 | codex | 一致性，@codex 怎么保证 |", card)
        self.assertIn("（只给总裁和总管）", card)
        self.assertNotIn("低估了工期", card, "私下发言的正文不进卡片索引")
        self.assertIn("| 立场 | — | 立场 |", card, "首行去掉标题记号")
        sim.log(i, "裁决", "总裁", 依据="总裁：按 A", 说明="缓存加版本号")
        card = (sim.root / "collab" / "issues" / f"{i}-缓存方案.md").read_text(encoding="utf-8")
        self.assertIn("- 决定：缓存加版本号\n- 依据：总裁：按 A", card)
        gcard = next((sim.root / "collab" / "goals").glob(f"{g}.md")).read_text(encoding="utf-8")
        self.assertIn(f"- {r}「框架会审」（会审）｜起草", gcard)
        self.assertEqual(self.errors(sim.check()), [])

    def test_context_feed(self):
        sim = Sim(self.root)
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        text, _ = flow.context(sim.proj, i, "codex")
        self.assertIn("视角：从实现成本看", text)
        self.assertIn("第一次发言", text)
        self.assertNotIn("## 新发言", text)
        say(sim, i, "deepseek", "主张不缓存")
        say(sim, i, "总裁", "@codex 你先说", 点名=["codex"])
        text, man = flow.context(sim.proj, i, "codex")
        self.assertIn("主张不缓存", text, "叫醒它的那句话之前的公开发言都给")
        self.assertIn("你先说", text)
        self.assertIn("点名问你", text)
        upto = man[-1]["read_upto"]
        say(sim, i, "codex", "主张缓存")
        say(sim, i, "deepseek", "工期内幕", 私下=True)
        say(sim, i, "deepseek", "回应 codex", 点名=["codex"])
        text, man = flow.context(sim.proj, i, "codex")
        self.assertIn("回应 codex", text)
        self.assertNotIn("主张缓存", text, "不喂自己的发言")
        self.assertNotIn("工期内幕", text)
        text, _ = flow.context(sim.proj, i, "codex", since=upto)
        self.assertNotIn("你先说", text, "since 之后的才喂")
        lead, _ = flow.context(sim.proj, i, "lead")
        for s in ("主张不缓存", "主张缓存", "工期内幕", "回应 codex"):
            self.assertIn(s, lead)
        with self.assertRaises(flow.FlowError):
            flow.context(sim.proj, i, "claude")


class TestIssueCli(Base):
    def run_cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = flow.main(["--project", str(self.root), *argv])
        finally:
            sys.stdin = old
        return code, out.getvalue(), err.getvalue()

    def test_cli_new_speak_check(self):
        sim = Sim(self.root)
        sim.tick()
        code, out, err = self.run_cli("建立", "议题", "--标题", "缓存方案", "--与会", "codex:实现", "DeepSeek",
                                      "--依据", "总裁：开会")
        self.assertEqual(code, 0, err)
        self.assertIn("I001", out)
        self.assertEqual(self.run_cli("记", "I001", "开始", "--作为", "总裁")[0], 0)
        code, out, err = self.run_cli("记", "I001", "发言", "--作为", "codex", "--正文", "-", "--点名", "deepseek",
                                      stdin="## 立场\n本地缓存\n")
        self.assertEqual(code, 0, err)
        ev = state(sim, "I001")["events"][-1]
        self.assertEqual((ev["body"], ev["mentions"]), ("## 立场\n本地缓存\n", ["deepseek"]))
        self.assertEqual(self.run_cli("记", "I001", "PASS", "--作为", "dsh")[0], 0)
        code, out, err = self.run_cli("检查")
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()
