"""总裁反馈可视化：事件带依据（原话），总裁要求带来的新增任务画总裁 → 总管，退回和新增任务互相标注，
目标层总裁动作进主视图，看板批准的批注送到 PROGRESS 和待你决定、总管记进展后消失。"""
import argparse
import sys
import unittest
from pathlib import Path

from test_flow import Sim
from test_frame import FrameBase, FILL
import flow  # noqa: E402

SPEC = {"阶段": [{"序": 1, "名称": "做", "类型": "执行", "前置": [], "任务": [
    {"键": "a", "标题": "日历页", "执行": "总管", "确认": "总裁", **FILL}]}]}
QUOTE = "日历要按月份的网格"


class TestFeedback(FrameBase):
    def setUp(self):
        super().setUp()
        self.sim = Sim(self.root)
        self.g = self.approved(self.sim, SPEC)
        self.a = self.ids(self.sim, self.g)["a"]
        flow.start_self(self.sim.proj, self.a, {})
        self.sim.log(self.a, "交付", 给="总裁")

    def rows(self):
        return {r["项目序"]: r for r in self.goal(self.sim, self.g)["事件"]}

    def steps(self, tid):
        for s in self.goal(self.sim, self.g)["结构"]["阶段"]:
            for t in s["任务"]:
                if t["编号"] == tid:
                    return t["步骤"]

    def new_task(self, basis=None, **kw):
        a = {"目标": self.g, "阶段": 1, "标题": "新卡", **kw}
        if basis:
            a["依据"] = basis
        return self.sim.new("任务", **a)

    def test_basis_in_rows_and_default_is_not_quote(self):
        self.sim.log(self.a, "确认", "总裁", 结果="需补充", 依据=QUOTE, 说明="总管转述")
        rows = self.rows()
        r = next(x for x in rows.values() if x["边"] == "确认")
        self.assertEqual(r["依据"], QUOTE)
        self.assertTrue(r["原话"])
        create = next(x for x in rows.values() if x["对象"] == self.a and x["边"] == "建立")
        self.assertEqual(create["依据"], f"{self.g} 框架")
        self.assertNotIn("原话", create)
        derive = next(x for x in rows.values() if x["边"] == "交付")
        self.assertNotIn("依据", derive)

    def test_boss_request_adds_step_before_dispatch_and_lead_card_does_not(self):
        t = self.new_task(QUOTE)
        mine = self.new_task(f"{self.g} 框架", 标题="总管自己补")
        seq = [r["项目序"] for r in self.rows().values() if r["对象"] == t and r["边"] == "建立"][0]
        first = self.steps(t)[0]
        self.assertEqual((first["边"], first["发起"], first["接收"], first["项目序"]), ("要求", "总裁", "总管", seq))
        self.assertEqual(self.steps(t)[1]["边"], "派发")
        self.assertEqual(self.rows()[seq]["画"]["发起"], "总裁")
        self.assertNotIn("要求", [x["边"] for x in self.steps(mine)])
        mrow = next(r for r in self.rows().values() if r["对象"] == mine and r["边"] == "建立")
        self.assertNotIn("画", mrow)

    def test_cross_links_with_return(self):
        self.sim.log(self.a, "确认", "总裁", 结果="需补充", 依据=QUOTE, 说明="转述")
        t = self.new_task(QUOTE)
        other = self.new_task("总裁在对话里另说的话", 标题="另一张")
        rows = self.rows()
        ret = next(r for r in rows.values() if r["对象"] == self.a and r["边"] == "确认")
        mk = next(r for r in rows.values() if r["对象"] == t and r["边"] == "建立")
        self.assertEqual(ret["催生"], [{"对象": t, "项目序": mk["项目序"]}])
        self.assertEqual(mk["来自"]["项目序"], ret["项目序"])
        omk = next(r for r in rows.values() if r["对象"] == other and r["边"] == "建立")
        self.assertIn("画", omk)  # 没有对应退回也要画
        self.assertNotIn("来自", omk)

    def test_goal_level_events_inserted_by_time(self):
        s = self.sim
        s.log(self.a, "确认", "总裁", 结果="通过", 依据="确认")
        s.log(self.g, "目标验收", 给="总裁", 方案="A 通过", 建议="A")
        s.log(self.g, "打回", "总裁", 依据="先不交付", 说明="转述")
        t = self.new_task("日历要按月份的网格", 标题="后补")
        flow.start_self(s.proj, t, {})
        s.log(t, "交付", 给="总裁")
        s.log(t, "确认", "总裁", 结果="通过", 依据="确认")
        s.log(self.g, "目标验收", 给="总裁", 方案="A 通过", 建议="A")
        S = self.goal(s, self.g)["结构"]
        self.assertNotIn("反馈", S)
        evs = {r["项目序"]: r for r in self.goal(s, self.g)["事件"]}
        ck = sorted(q for q, r in evs.items() if r["对象"] == self.g and r["边"] == "目标验收")
        seqs = {"目标验收": ck[0], "打回": next(q for q, r in evs.items() if r["边"] == "打回")}
        # 验收和打回都早于新任务，插在新任务头行之前，且按时间先验收后打回
        item = next(it for st in S["阶段"] for it in st["任务"] if it["编号"] == t)
        self.assertEqual([(x["边"], x["项目序"]) for x in item["前"]], [("目标验收", seqs["目标验收"]), ("打回", seqs["打回"])])
        self.assertNotIn(seqs["打回"], S["记录"])
        self.assertEqual([(x["边"], x["项目序"]) for x in S["结尾"]][:1], [("目标验收", ck[1])])
        self.assertEqual([x["边"] for x in S["结尾"]], ["目标验收", "完成"])

    def test_pre_approval_change_in_head_and_merge_into_task(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "变更", "总裁", 依据="批准前的话", 说明="转述", 变更项="x")
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.APPROVE_BASIS.format(1))
        sim.log(g, "变更", "总裁", 依据=QUOTE, 说明="转述", 变更项="x", 框架版本=2)
        t = sim.new("任务", 目标=g, 阶段=1, 标题="新卡", 依据=QUOTE)
        S = self.goal(sim, g)["结构"]
        self.assertEqual([x["边"] for x in S["开头"]], ["变更", "批准"])
        self.assertTrue(S["开头"][0]["项目序"] < S["开头"][1]["项目序"])
        item = next(it for st in S["阶段"] for it in st["任务"] if it["编号"] == t)
        req = next(x for x in item["步骤"] if x["边"] == "要求")
        self.assertEqual(len(req["含"]), 1)
        self.assertEqual(item["前"], [])
        self.assertNotIn(req["含"][0], [x["项目序"] for st in S["阶段"] for x in st["前"]])
        row = next(r for r in self.goal(sim, g)["事件"] if r["项目序"] == req["项目序"])
        self.assertEqual(row["同改框架版"], 2)

    def test_task_cancelled_before_approval_is_hidden(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        early = sim.new("任务", 目标=g, 阶段=1, 标题="批准前就去掉")
        sim.log(early, "取消", 说明="框架改版去掉")
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.APPROVE_BASIS.format(1))
        late = sim.new("任务", 目标=g, 阶段=1, 标题="批准后建又取消")
        sim.log(late, "取消", 说明="不做了")
        gv = self.goal(sim, g)
        stage = gv["结构"]["阶段"][0]
        ids = [t["编号"] for t in stage["任务"]]
        self.assertNotIn(early, ids)
        self.assertIn(late, ids)
        view_stage = next(s for s in gv["阶段"] if s["序"] == 1)
        self.assertNotIn(early, view_stage["任务"])
        self.assertNotIn(early, view_stage["批准后新增"])
        self.assertIn(late, view_stage["批准后新增"])
        mine = {r["项目序"] for r in gv["事件"] if r["对象"] == early}
        self.assertTrue(mine and mine <= set(gv["结构"]["记录"]))
        self.assertFalse(mine & {x["项目序"] for t in stage["任务"] for x in t["步骤"] if x["项目序"]})

    def test_approval_note_delivered_then_cleared_by_progress(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.APPROVE_BASIS.format(1) + "：复用对话")
        prog = lambda: (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8")
        gv = self.goal(sim, g)
        self.assertEqual([c["说明"] for c in gv["意见"]], ["复用对话"])
        self.assertIn("总裁意见（总管处理）：复用对话", prog())
        self.assertTrue(any("复用对话" in l for l in flow.decision_lines(sim.view())))
        sim.log(g, "进展", 说明="已处理批注：复用对话")
        self.assertEqual(self.goal(sim, g)["意见"], [])
        self.assertNotIn("总裁意见（总管处理）", prog())

    def test_approval_without_note_shows_nothing(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.APPROVE_BASIS.format(1))
        self.assertEqual(self.goal(sim, g)["意见"], [])
        self.assertNotIn("总裁意见（总管处理）", (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8"))

    def test_board_approve_writes_note_basis(self):
        sys.path.insert(0, str(Path(flow.__file__).parents[1] / "board"))
        import server
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        server.goal_post({"root": str(self.root)}, g, {"action": "批准", "version": 1, "text": "注意复用"})
        self.assertEqual([c["说明"] for c in self.goal(sim, g)["意见"]], ["注意复用"])


if __name__ == "__main__":
    unittest.main()
