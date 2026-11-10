"""看图批准：规划时建真实任务卡，改框架、批准版、差别；规划中不能开工；总管没有执行中的任务不能改文件。"""
import argparse
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from test_flow import Base, Sim
import flow  # noqa: E402

CHECK = Path(flow.__file__).with_name("check.py")
FILL = {"目的": "把模块做出来", "交付物": "模块和测试", "验收标准": "测试通过", "硬约束": "不动真实数据"}
SPEC = {"阶段": [
    {"序": 1, "名称": "开发", "类型": "执行", "前置": [], "任务": [
        {"键": "mod", "标题": "写模块", "执行": "codex", **FILL},
        {"键": "doc", "标题": "写文档", "执行": "deepseek", "确认": "codex", **FILL}]},
    {"序": 2, "名称": "接入", "类型": "执行", "前置": [], "任务": [
        {"键": "hook", "标题": "接入看板", "执行": "codex", **FILL}]},
    {"序": 3, "名称": "上线", "类型": "执行", "前置": [1, 2], "任务": [
        {"键": "ship", "标题": "发布", "执行": "总管", "确认": "总裁", "前置": ["mod", "hook"], **FILL}]},
]}


class FrameBase(Base):
    def goal(self, sim, g):
        return next(x for x in sim.view()["目标"] if x["编号"] == g)

    def framed(self, sim, spec=SPEC):
        g = sim.new("目标", 类型="开发", 标题="做工具")
        flow.frame(sim.proj, g, spec, {})
        return g

    def approved(self, sim, spec=SPEC):
        g = self.framed(sim, spec)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 依据="总裁：批准")
        return g

    def ids(self, sim, g):
        return {t["键"]: t["编号"] for t in sim.view()["任务"] if t["目标"] == g}


class TestPlanning(FrameBase):
    def test_tasks_are_real_cards_before_approval(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        v = sim.view()
        tasks = [t for t in v["任务"] if t["目标"] == g]
        self.assertEqual([t["状态"] for t in tasks], ["规划中"] * 4)
        self.assertEqual(tasks[0]["内容"]["目的"], "把模块做出来")
        self.assertTrue(list((self.root / "collab" / "任务").glob(f"{g}-T1-*.md")))
        self.assertEqual(self.errors(sim.check()), [])

    def test_task_must_belong_to_goal(self):
        sim = Sim(self.root)
        with self.assertRaises(flow.FlowError) as e:
            flow.create(sim.proj, "任务", {"发起": "总管", "标题": "x", "依据": "总裁：做"})
        self.assertIn("必须归属目标", e.exception.msg)

    def test_submit_needs_complete_frame(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="开发", 标题="空的")
        with self.assertRaises(flow.FlowError) as e:
            flow.record(sim.proj, g, "提交", {"发起": "总管", "说明": "x", "建议": "y"})
        self.assertIn("框架", e.exception.msg)
        bad = {"阶段": [{"序": 1, "名称": "做", "类型": "执行", "前置": [], "任务": [{"标题": "缺内容", "执行": "codex"}]}]}
        flow.frame(sim.proj, g, bad, {})
        with self.assertRaises(flow.FlowError) as e:
            flow.record(sim.proj, g, "提交", {"发起": "总管", "说明": "x", "建议": "y"})
        self.assertIn("交接缺", e.exception.msg)
        with self.assertRaises(flow.FlowError):
            flow.record(sim.proj, g, "提交", {"发起": "总管", "说明": "x"})  # 必须写建议

    def test_frame_rejects_empty_stage_and_forward_dependency(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="开发", 标题="x")
        with self.assertRaises(flow.FlowError):
            flow.frame(sim.proj, g, {"阶段": [{"序": 1, "名称": "空", "类型": "执行", "前置": []}]}, {})
        with self.assertRaises(flow.FlowError):
            flow.frame(sim.proj, g, {"阶段": [{"序": 1, "名称": "a", "类型": "执行", "前置": [], "任务": [
                {"键": "a", "标题": "a", "执行": "codex", "前置": ["b"]}, {"键": "b", "标题": "b", "执行": "codex"}]}]}, {})

    def test_planned_task_cannot_start_even_with_override(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        t = self.ids(sim, g)["mod"]
        with self.assertRaises(flow.FlowError) as e:
            flow.record(sim.proj, t, "派发", {"发起": "总管", "给": "codex", "越过": "赶时间"})
        self.assertEqual(e.exception.kind, "硬错误")
        with self.assertRaises(flow.FlowError) as e:
            flow.record(sim.proj, t, "批准", {"发起": "总裁", "依据": "总裁：批"})
        self.assertIn("没有单独的批准", e.exception.msg)

    def test_rerun_frame_records_what_changed(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        self.assertEqual(self.goal(sim, g)["框架版本"], 1)
        ids = self.ids(sim, g)
        spec = json.loads(json.dumps(SPEC, ensure_ascii=False))
        spec["阶段"][0]["任务"][0]["执行"] = "deepseek"
        spec["阶段"][0]["任务"][0]["确认"] = "codex"
        spec["阶段"][0]["任务"][1]["标题"] = "写说明"
        del spec["阶段"][1]["任务"][0]
        spec["阶段"][1]["任务"].append({"键": "new", "标题": "新接入", "执行": "codex", **FILL})
        spec["阶段"][2]["任务"][0]["前置"] = ["mod", "new"]
        res = flow.frame(sim.proj, g, spec, {})
        self.assertEqual(res["版本"], 2)
        text = "\n".join(res["改动"])
        self.assertIn("执行 codex → deepseek", text)
        self.assertIn("标题", text)
        self.assertIn(f"取消 {ids['hook']}", text)
        self.assertIn("新增", text)
        self.assertEqual(self.goal(sim, g)["本轮改动"], res["改动"])
        now = {t["键"]: t for t in sim.view()["任务"] if t["目标"] == g and t["状态"] != "取消"}
        self.assertEqual(now["doc"]["编号"], ids["doc"])  # 改标题还是同一张卡
        self.assertEqual(now["doc"]["标题"], "写说明")
        self.assertEqual(now["ship"]["前置"], [ids["mod"], now["new"]["编号"]])
        self.assertEqual(flow.frame(sim.proj, g, spec, {})["改动"], [])
        self.assertEqual(self.errors(sim.check()), [])

    def test_frame_keeps_card_fields_it_does_not_mention(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        spec = json.loads(json.dumps(SPEC, ensure_ascii=False))
        del spec["阶段"][0]["任务"][0]["硬约束"]
        flow.frame(sim.proj, g, spec, {})
        t = next(x for x in sim.view()["任务"] if x["键"] == "mod")
        self.assertEqual(t["内容"]["硬约束"], "不动真实数据")


class TestApproval(FrameBase):
    def test_approval_moves_all_tasks_and_snapshots(self):
        sim = Sim(self.root)
        g = self.approved(sim)
        tasks = [t for t in sim.view()["任务"] if t["目标"] == g]
        self.assertEqual({t["状态"] for t in tasks}, {"已批准"})
        v = self.goal(sim, g)
        self.assertEqual(v["批准版本"], 1)
        self.assertEqual(v["差别"], [])
        self.assertEqual(self.errors(sim.check()), [])

    def test_approval_binds_version(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        spec = json.loads(json.dumps(SPEC, ensure_ascii=False))
        spec["阶段"][0]["任务"][0]["标题"] = "改了"
        flow.frame(sim.proj, g, spec, {})  # 待批准时可以直接改
        flow.record(sim.proj, g, "提交", {"发起": "总管", "说明": "改过了", "建议": "批这版"})  # 待批准时可以刷新说明和建议
        self.assertEqual(sim.view()["待你决定"][0]["建议"], "批这版")
        with self.assertRaises(flow.FlowError) as e:
            flow.record(sim.proj, g, "批准", {"发起": "总裁", "依据": "总裁：批", "框架版本": 1})
        self.assertIn("刷新", e.exception.msg)
        flow.record(sim.proj, g, "批准", {"发起": "总裁", "依据": "总裁：批", "框架版本": 2})

    def test_comment_only_boss_and_cleared_by_frame(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        t = self.ids(sim, g)["mod"]
        with self.assertRaises(flow.FlowError):
            flow.record(sim.proj, t, "意见", {"发起": "总管", "说明": "x"})
        flow.record(sim.proj, t, "意见", {"发起": "总裁", "说明": "这个拆细一点", "写入者": "看板"})
        self.assertEqual([c["说明"] for c in self.goal(sim, g)["意见"]], ["这个拆细一点"])
        self.assertIn("这个拆细一点", (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8"))
        spec = json.loads(json.dumps(SPEC, ensure_ascii=False))
        spec["阶段"][0]["任务"][0]["标题"] = "拆细了"
        flow.frame(sim.proj, g, spec, {})
        self.assertEqual(self.goal(sim, g)["意见"], [])

    def test_diff_against_approved(self):
        sim = Sim(self.root)
        g = self.approved(sim)
        spec = json.loads(json.dumps(SPEC, ensure_ascii=False))
        spec["阶段"][0]["任务"][0]["执行"] = "deepseek"
        spec["阶段"][0]["任务"][0]["确认"] = "codex"
        spec["阶段"][0]["任务"].append({"键": "extra", "标题": "补一个", "执行": "codex", **FILL})
        spec["阶段"][1]["任务"][0]["目的"] = "换个目的"
        flow.frame(sim.proj, g, spec, {})
        kinds = {(d["类型"], d["说明"].split("（")[0]) for d in self.goal(sim, g)["差别"]}
        self.assertIn(("换人", "codex → deepseek"), kinds)
        self.assertIn(("新增", "补一个"), kinds)
        self.assertIn(("内容改了", "接入看板"), kinds)
        extra = next(t for t in sim.view()["任务"] if t["键"] == "extra")
        self.assertEqual(extra["状态"], "已批准")  # 批准后补的任务不用再批

    def test_cancel_goal_cancels_planned_tasks(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        sim.log(g, "取消", 说明="不做了")
        self.assertEqual({t["状态"] for t in sim.view()["任务"] if t["目标"] == g}, {"取消"})

    def test_cannot_delete_started_task(self):
        sim = Sim(self.root)
        g = self.approved(sim)
        sim.log(self.ids(sim, g)["mod"], "派发", 给="codex")
        spec = json.loads(json.dumps(SPEC, ensure_ascii=False))
        del spec["阶段"][0]["任务"][0]
        spec["阶段"][2]["任务"][0]["前置"] = ["hook"]
        with self.assertRaises(flow.FlowError) as e:
            flow.frame(sim.proj, g, spec, {})
        self.assertIn("已经开工", e.exception.msg)


class TestExecution(FrameBase):
    def test_dependency_blocks_dispatch(self):
        sim = Sim(self.root)
        spec = {"阶段": [{"序": 1, "名称": "做", "类型": "执行", "前置": [], "任务": [
            {"键": "a", "标题": "a", "执行": "codex", **FILL},
            {"键": "b", "标题": "b", "执行": "codex", "前置": ["a"], **FILL}]}]}
        g = self.approved(sim, spec)
        ids = self.ids(sim, g)
        with self.assertRaises(flow.FlowError) as e:
            sim.log(ids["b"], "派发", 给="codex")
        self.assertIn("还没通过", e.exception.msg)
        sim.log(ids["a"], "派发", 给="codex")
        sim.deliver_pass(ids["a"], "codex")
        sim.log(ids["b"], "派发", 给="codex")

    def test_empty_handoff_cannot_dispatch(self):
        sim = Sim(self.root)
        g = self.approved(sim)
        obj, _ = flow.create(sim.proj, "任务", {"发起": "总管", "目标": g, "阶段": 1, "标题": "新补的", "依据": "总管：补"})
        with self.assertRaises(flow.FlowError) as e:
            sim.log(obj, "派发", 给="codex")
        self.assertIn("交接缺", e.exception.msg)

    def test_context_has_goal_constraints(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        card = next((self.root / "collab" / "目标").glob(f"{g}-*.md"))
        card.write_text(card.read_text(encoding="utf-8").replace("- 成功标准：", "- 硬约束：绝不卸载\n- 成功标准：", 1), encoding="utf-8")  # 旧卡的写法
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 依据="总裁：批准")
        t = self.ids(sim, g)["mod"]
        text, _ = flow.context(sim.proj, t, "codex")
        self.assertIn("绝不卸载", text)
        self.assertIn("不动真实数据", text)

    def test_start_self(self):
        sim = Sim(self.root)
        g = self.approved(sim)
        spec_task = self.ids(sim, g)["ship"]
        ids = self.ids(sim, g)
        for key, who in (("mod", "codex"), ("doc", "deepseek"), ("hook", "codex")):
            sim.log(ids[key], "派发", 给=who)
            sim.deliver_pass(ids[key], who, reviewer="codex" if key == "doc" else "总管")
        flow.start_self(sim.proj, spec_task, {})
        st = next(t for t in sim.view()["任务"] if t["编号"] == spec_task)
        self.assertEqual((st["状态"], st["持有人"]), ("执行中", "总管"))

    def test_structure_positions_stay_and_light_up(self):
        sim = Sim(self.root)
        g = self.framed(sim)
        s0 = self.goal(sim, g)["结构"]
        self.assertEqual([x["边"] for x in s0["开头"]], ["提交", "批准"])
        self.assertEqual([x["并行"] for x in s0["阶段"]], [[2], [1], []])
        ship = s0["阶段"][2]["任务"][0]
        self.assertTrue(ship["总裁介入"])
        self.assertEqual([x["边"] for x in ship["步骤"]], ["派发", "交付", "确认"])
        self.assertTrue(all(x["计划"] for x in ship["步骤"]))
        self.assertEqual(len(s0["阶段"][1]["任务"]), 1)
        sim.log(g, "提交", 说明="框架", 建议="批准")
        sim.log(g, "批准", "总裁", 依据="总裁：批准")
        t = self.ids(sim, g)["mod"]
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        sim.log(t, "交付", "codex", 给="总管")
        sim.log(t, "确认", 结果="需补充")
        s1 = self.goal(sim, g)["结构"]
        steps = s1["阶段"][0]["任务"][0]["步骤"]
        self.assertFalse(s1["开头"][0]["计划"])  # 批准已发生
        self.assertEqual(steps[0]["边"], "派发")
        self.assertFalse(steps[0]["计划"])
        self.assertTrue(steps[0]["含"])  # 接手并进派发
        self.assertEqual(steps[-1]["边"], "确认")

    def test_cancelled_task_has_no_planned_steps(self):
        sim = Sim(self.root)
        g = self.approved(sim)
        t = self.ids(sim, g)["mod"]
        sim.log(t, "取消", 说明="不要了")
        task = next(x for x in self.goal(sim, g)["结构"]["阶段"][0]["任务"] if x["编号"] == t)
        self.assertFalse(any(x["计划"] for x in task["步骤"]))


class TestArchivePage(FrameBase):
    def test_archive_data_uses_view(self):
        sys.path.insert(0, str(Path(flow.__file__).parents[1] / "board"))
        import server
        server.ARGS = argparse.Namespace(now_dir=str(self.root), project=[])
        sim = Sim(self.root)
        spec = {"阶段": [{"序": 1, "名称": "做", "类型": "执行", "前置": [], "任务": [
            {"键": "a", "标题": "一张卡", "执行": "总管", "确认": "总裁", **FILL}]}]}
        g = self.approved(sim, spec)
        t = self.ids(sim, g)["a"]
        flow.start_self(sim.proj, t, {})
        sim.log(t, "交付", 给="总裁")
        sim.log(t, "确认", "总裁", 结果="通过")
        sim.log(g, "目标验收", 方案="A", 建议="A")
        sim.log(g, "完成", "总裁", 依据="总裁：可以")
        c = self.root / "collab"
        for sub, pat in (("任务", f"{t}-*.md"), ("目标", f"{g}-*.md")):
            (c / "归档" / sub).mkdir(parents=True, exist_ok=True)
            f = next((c / sub).glob(pat))
            f.rename(c / "归档" / sub / f.name)
        d = server.archive_data({"id": "x", "name": "x", "root": str(self.root), "progress": str(c / "PROGRESS.md")})
        self.assertEqual([x["id"] for x in d["goals"]], [g])
        self.assertEqual(d["goals"][0]["stages"][0]["status"], "通过")
        self.assertEqual(d["cards"][0]["head"]["验收"], "总裁")
        v = next(x for x in d["view"]["目标"] if x["编号"] == g)
        steps = v["结构"]["阶段"][0]["任务"][0]["步骤"]
        self.assertFalse(any(x["计划"] for x in steps))
        self.assertEqual([x["边"] for x in v["结构"]["结尾"]], ["目标验收", "完成"])


class TestPretoolHook(FrameBase):
    def run_hook(self, path, env=None):
        e = {k: v for k, v in os.environ.items() if k != "COLLAB_ACTOR"}
        e.update(env or {})
        data = {"tool_name": "Edit", "tool_input": {"file_path": str(path)}, "cwd": str(self.root)}
        r = subprocess.run([sys.executable, str(CHECK), "--pretool"], input=json.dumps(data), text=True, capture_output=True, env=e)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else "allow"

    def test_blocks_until_lead_is_working(self):
        sim = Sim(self.root)
        (self.root / "src").mkdir()
        (self.root / "collab" / "内部" / "流转").mkdir(parents=True, exist_ok=True)
        target = self.root / "src" / "a.py"
        self.assertEqual(self.run_hook(target), "deny")
        self.assertEqual(self.run_hook(self.root / "collab" / "PROGRESS.md"), "allow")
        self.assertEqual(self.run_hook(target, {"COLLAB_ACTOR": "codex"}), "allow")
        self.assertEqual(self.run_hook(Path("/tmp/别的项目/a.py")), "allow")
        spec = {"阶段": [{"序": 1, "名称": "做", "类型": "执行", "前置": [], "任务": [
            {"键": "a", "标题": "a", "执行": "总管", "确认": "总裁", **FILL}]}]}
        g = self.framed(sim, spec)
        t = self.ids(sim, g)["a"]
        self.assertEqual(self.run_hook(target), "deny")  # 规划中也不行
        sim.log(g, "提交", 说明="一张卡", 建议="批准")
        sim.log(g, "批准", "总裁", 依据="总裁：批")
        self.assertEqual(self.run_hook(target), "deny")  # 批准了没开工也不行
        flow.start_self(sim.proj, t, {})
        self.assertEqual(self.run_hook(target), "allow")
        sim.log(t, "交付", 给="总裁")
        self.assertEqual(self.run_hook(target), "deny")  # 交付后就结束了

    def test_broken_project_does_not_block(self):
        self.assertEqual(self.run_hook(self.root / "a.py"), "allow")


if __name__ == "__main__":
    unittest.main()
