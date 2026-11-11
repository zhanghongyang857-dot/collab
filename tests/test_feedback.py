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
        return {r["project_seq"]: r for r in self.goal(self.sim, self.g)["events"]}

    def steps(self, tid):
        for s in self.goal(self.sim, self.g)["structure"]["stages"]:
            for t in s["tasks"]:
                if t["id"] == tid:
                    return t["steps"]

    def new_task(self, basis=None, **kw):
        a = {"目标": self.g, "阶段": 1, "标题": "新卡", **kw}
        if basis:
            a["basis"] = basis
        return self.sim.new("任务", **a)

    def test_basis_in_rows_and_default_is_not_quote(self):
        self.sim.log(self.a, "确认", "总裁", 结果="需补充", 依据=QUOTE, 说明="总管转述")
        rows = self.rows()
        r = next(x for x in rows.values() if x["edge"] == "review")
        self.assertEqual(r["basis"], QUOTE)
        self.assertTrue(r["quote"])
        create = next(x for x in rows.values() if x["object"] == self.a and x["edge"] == "create")
        self.assertEqual(create["basis"], f"{self.g} 框架")
        self.assertNotIn("原话", create)
        derive = next(x for x in rows.values() if x["edge"] == "deliver")
        self.assertNotIn("依据", derive)

    def test_boss_request_adds_step_before_dispatch_and_lead_card_does_not(self):
        t = self.new_task(QUOTE)
        mine = self.new_task(f"{self.g} 框架", 标题="总管自己补")
        seq = [r["project_seq"] for r in self.rows().values() if r["object"] == t and r["edge"] == "create"][0]
        first = self.steps(t)[0]
        self.assertEqual((first["edge"], first["from"], first["to"], first["project_seq"]), ("request", "owner", "lead", seq))
        self.assertEqual(self.steps(t)[1]["edge"], "dispatch")
        self.assertEqual(self.rows()[seq]["draw"]["from"], "owner")
        self.assertNotIn("request", [x["edge"] for x in self.steps(mine)])
        mrow = next(r for r in self.rows().values() if r["object"] == mine and r["edge"] == "create")
        self.assertNotIn("draw", mrow)

    def test_cross_links_with_return(self):
        self.sim.log(self.a, "确认", "总裁", 结果="需补充", 依据=QUOTE, 说明="转述")
        t = self.new_task(QUOTE)
        other = self.new_task("总裁在对话里另说的话", 标题="另一张")
        rows = self.rows()
        ret = next(r for r in rows.values() if r["object"] == self.a and r["edge"] == "review")
        mk = next(r for r in rows.values() if r["object"] == t and r["edge"] == "create")
        self.assertEqual(ret["caused"], [{"object": t, "project_seq": mk["project_seq"]}])
        self.assertEqual(mk["caused_by"]["project_seq"], ret["project_seq"])
        omk = next(r for r in rows.values() if r["object"] == other and r["edge"] == "create")
        self.assertIn("draw", omk)  # 没有对应退回也要画
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
        S = self.goal(s, self.g)["structure"]
        self.assertNotIn("反馈", S)
        evs = {r["project_seq"]: r for r in self.goal(s, self.g)["events"]}
        ck = sorted(q for q, r in evs.items() if r["object"] == self.g and r["edge"] == "request_acceptance")
        seqs = {"request_acceptance": ck[0], "reject": next(q for q, r in evs.items() if r["edge"] == "reject")}
        # 验收和打回都早于新任务，插在新任务头行之前，且按时间先验收后打回
        item = next(it for st in S["stages"] for it in st["tasks"] if it["id"] == t)
        self.assertEqual([(x["edge"], x["project_seq"]) for x in item["before"]], [("request_acceptance", seqs["request_acceptance"]), ("reject", seqs["reject"])])
        self.assertNotIn(seqs["reject"], S["record"])
        self.assertEqual([(x["edge"], x["project_seq"]) for x in S["tail"]][:1], [("request_acceptance", ck[1])])
        self.assertEqual([x["edge"] for x in S["tail"]], ["request_acceptance", "complete"])

    def test_pre_approval_change_in_head_and_merge_into_task(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "变更", "总裁", 依据="批准前的话", 说明="转述", 变更项="x")
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.approve_basis(1))
        sim.log(g, "变更", "总裁", 依据=QUOTE, 说明="转述", 变更项="x", 框架版本=2)
        t = sim.new("任务", 目标=g, 阶段=1, 标题="新卡", 依据=QUOTE)
        S = self.goal(sim, g)["structure"]
        self.assertEqual([x["edge"] for x in S["head"]], ["change", "approve"])
        self.assertTrue(S["head"][0]["project_seq"] < S["head"][1]["project_seq"])
        item = next(it for st in S["stages"] for it in st["tasks"] if it["id"] == t)
        req = next(x for x in item["steps"] if x["edge"] == "request")
        self.assertEqual(len(req["includes"]), 1)
        self.assertEqual(item["before"], [])
        self.assertNotIn(req["includes"][0], [x["project_seq"] for st in S["stages"] for x in st["before"]])
        row = next(r for r in self.goal(sim, g)["events"] if r["project_seq"] == req["project_seq"])
        self.assertEqual(row["same_plan_version"], 2)

    def test_task_cancelled_before_approval_is_hidden(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        early = sim.new("任务", 目标=g, 阶段=1, 标题="批准前就去掉")
        sim.log(early, "取消", 说明="框架改版去掉")
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.approve_basis(1))
        late = sim.new("任务", 目标=g, 阶段=1, 标题="批准后建又取消")
        sim.log(late, "取消", 说明="不做了")
        gv = self.goal(sim, g)
        stage = gv["structure"]["stages"][0]
        ids = [t["id"] for t in stage["tasks"]]
        self.assertNotIn(early, ids)
        self.assertIn(late, ids)
        view_stage = next(s for s in gv["stages"] if s["order"] == 1)
        self.assertNotIn(early, view_stage["tasks"])
        self.assertNotIn(early, view_stage["added_after_approval"])
        self.assertIn(late, view_stage["added_after_approval"])
        mine = {r["project_seq"] for r in gv["events"] if r["object"] == early}
        self.assertTrue(mine and mine <= set(gv["structure"]["record"]))
        self.assertFalse(mine & {x["project_seq"] for t in stage["tasks"] for x in t["steps"] if x["project_seq"]})

    def test_approval_note_delivered_then_cleared_by_progress(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.approve_basis(1, "复用对话"))
        prog = lambda: (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8")
        gv = self.goal(sim, g)
        self.assertEqual([c["note"] for c in gv["comments"]], ["复用对话"])
        self.assertIn("总裁意见（总管处理）：复用对话", prog())
        self.assertTrue(any("复用对话" in l for l in flow.decision_lines(sim.view())))
        sim.log(g, "进展", 说明="已处理批注：复用对话")
        self.assertEqual(self.goal(sim, g)["comments"], [])
        self.assertNotIn("总裁意见（总管处理）", prog())

    def test_approval_without_note_shows_nothing(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 框架版本=1, 依据=flow.approve_basis(1))
        self.assertEqual(self.goal(sim, g)["comments"], [])
        self.assertNotIn("总裁意见（总管处理）", (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8"))

    def test_board_approve_writes_note_basis(self):
        sys.path.insert(0, str(Path(flow.__file__).parents[1] / "board"))
        import server
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        server.goal_post({"root": str(self.root)}, g, {"action": "approve", "version": 1, "text": "注意复用"})
        self.assertEqual([c["note"] for c in self.goal(sim, g)["comments"]], ["注意复用"])


if __name__ == "__main__":
    unittest.main()
