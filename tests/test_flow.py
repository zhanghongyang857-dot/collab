"""flow.py 的测试：全部用模拟数据（内容虚构），结构覆盖试运行出现过的走法。

运行：python3 -m unittest discover -s tests
期望视图模型存在 tests/样例/；改了投影或渲染规约、确认新输出没问题后，用 UPDATE_GOLDEN=1 重新生成。
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
import flow  # noqa: E402

GOLDEN = HERE / "样例"
TZ = dt.timezone(dt.timedelta(hours=8))
ROSTER = {"成员": [{"派活名": "codex", "名称": "Codex", "别名": ["Codex"]},
                   {"派活名": "deepseek", "名称": "DeepSeek", "别名": ["DeepSeek", "dsh"]},
                   {"派活名": "claude", "名称": "Claude 命令行"}]}
PROGRESS = """# 模拟项目
目标：测试 ｜ 截止：— ｜ 状态：进行中

## ▶ 下一步
{next}

## 现状
- 模拟数据

## 待你决定
<!-- flow:待你决定 项目 视图@1 sha=da39a3ee -->
<!-- /flow -->

## 生效决议
<!-- flow:生效决议 项目 视图@1 sha=da39a3ee -->
<!-- /flow -->

## 目标
<!-- flow:目标 项目 视图@1 sha=da39a3ee -->
<!-- /flow -->

## 任务
<!-- flow:任务 项目 视图@1 sha=da39a3ee -->
<!-- /flow -->
"""
PROTOCOL = """# 协议

## 席位
### 执行
<!-- 角色：执行 -->
执行者交付前自测，结束前用 flow.py 写交付或上报。

### 确认
<!-- 角色：确认 -->
确认交付：通过、需补充或未通过，写明核查了什么。

### 总管
<!-- 角色：总管 -->
总管的规则，成员看不到。
"""


class Sim:
    """在临时目录里搭一个项目，按固定的模拟时间写事件。"""

    def __init__(self, root: Path, small: bool = False, next_line: str = "派活"):
        self.root = root
        c = root / "collab"
        for d in ("内部/流程", "产出") + (() if small else ("任务", "目标")):
            (c / d).mkdir(parents=True, exist_ok=True)
        if small:
            (c / "任务.md").write_text("# 任务\n\n<!-- 新卡加在最上方 -->\n", encoding="utf-8")
            (c / "目标.md").write_text("# 目标\n", encoding="utf-8")
        (c / "内部" / "流程" / "花名册.json").write_text(json.dumps(ROSTER, ensure_ascii=False), encoding="utf-8")
        (c / "PROGRESS.md").write_text(PROGRESS.format(next=next_line), encoding="utf-8")
        (c / "协议.md").write_text(PROTOCOL, encoding="utf-8")
        (c / "决议.md").write_text("# 决议\n\n## D001｜2026-10-30｜验收默认由 Codex 做\n- 理由：模拟\n", encoding="utf-8")
        self.proj = flow.Project(root)
        self.t = dt.datetime(2026, 11, 1, 9, 0, tzinfo=TZ)
        self.misc = None
        self.spares = {}

    def tick(self, minutes: int = 7) -> None:
        self.t += dt.timedelta(minutes=minutes)
        os.environ["FLOW_NOW"] = self.t.isoformat()

    FILL = {"目的": "模拟", "交付物": "模拟交付", "验收标准": "模拟通过"}

    def new(self, kind: str, **kw) -> str:
        """建立对象。任务要归属目标：没写目标时挂到一个已批准的「杂项」目标上；
        目标提交时占位的任务卡，先按阶段顺序给后面建的任务用（标题改成新的）。"""
        self.tick()
        if kind == "任务":
            if not kw.get("目标"):
                kw["目标"], kw["阶段"] = self.misc_goal(), 1
            spare = self.spares.get((kw["目标"], kw["阶段"]))
            if spare:
                tid = spare.pop(0)
                flow.record(self.proj, tid, "变更", {"发起": "总管", "写入者": "总管", "标题": kw.get("标题"), "说明": "定标题", "变更项": ["标题"]})
                return tid
            kw.setdefault("交接", self.FILL)
        args = {"发起": "总管", "写入者": "总管", "依据": "总裁：模拟", **kw}
        obj, path = flow.create(self.proj, kind, args)
        if kind == "目标":
            text = path.read_text(encoding="utf-8").replace("- 要什么：\n", "- 要什么：模拟\n").replace("- 成功标准：\n", "- 成功标准：模拟\n")
            path.write_text(text, encoding="utf-8")
        return obj

    def misc_goal(self) -> str:
        if not self.misc:
            self.misc = self.new("目标", 类型="通用", 标题="杂项")
            flow.frame(self.proj, self.misc, {"阶段": [{"序": 1, "名称": "杂项", "类型": "执行", "前置": [], "人选": ["总管", "codex", "deepseek", "claude"],
                       "任务": [{"键": "占位", "标题": "占位", "执行": "总管", **self.FILL}]}]}, {})
            self.log(self.misc, "提交", 说明="杂项", 建议="批准")
            self.log(self.misc, "批准", "总裁", 依据="总裁：模拟")
            states, _, _ = flow.replay_all(self.proj)
        return self.misc

    def frame_template(self, g: str, stages=None) -> None:
        """旧测试的「提交」：按阶段（默认类型模板）搭框架，每个阶段一张占位卡。"""
        states, _, _ = flow.replay_all(self.proj)
        raw = stages or [dict(x) for x in flow.template_stages(self.proj, states[g]["类型"])]
        spec = {"阶段": [{**x, "人选": ["总管", "codex", "deepseek", "claude"], "任务": [{"键": f"占位{x['序']}", "标题": f"占位{x['序']}", "执行": "总管", **self.FILL}]} for x in raw]}
        flow.frame(self.proj, g, spec, {})
        states, _, _ = flow.replay_all(self.proj)
        for t in flow.goal_tasks(states, g):
            self.spares.setdefault((g, t["阶段"]), []).append(t["编号"])

    def log(self, obj: str, edge: str, actor: str = "总管", **kw):
        self.tick()
        args = {"发起": actor, "写入者": "总管" if actor in flow.MANAGERS else "成员", **kw}
        if edge == "提交":
            states, _, _ = flow.replay_all(self.proj)
            if not flow.goal_tasks(states, obj):
                self.frame_template(obj, args.pop("阶段", None))
            args.setdefault("建议", "批准")
        if edge == "交付" and "证据" not in kw:
            p = self.root / "collab" / "产出" / obj / "交付.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"{obj} 的模拟交付 {self.t}\n", encoding="utf-8")
            args["证据"] = [f"collab/产出/{obj}/交付.md"]
        args.setdefault("说明", f"{edge}（模拟）")
        ev, _ = flow.record(self.proj, obj, edge, args)
        return ev

    def deliver_pass(self, obj: str, who: str, reworks: int = 0, reviewer: str = "总管") -> None:
        self.log(obj, "接手", who)
        for _ in range(reworks):
            self.log(obj, "交付", who, 给=reviewer)
            self.log(obj, "确认", reviewer, 结果="需补充")
        self.log(obj, "交付", who, 给=reviewer)
        self.log(obj, "确认", reviewer, 结果="通过")

    def view(self):
        return flow.view(self.proj)

    def check(self, now=None):
        return flow.check(self.proj, now=now)


def research_goal(sim: Sim, reworks=(1, 0, 0)) -> str:
    g = sim.new("目标", 类型="调研", 标题="框架对比")
    sim.log(g, "提交", 说明="按调研模板两阶段")
    sim.log(g, "批准", "总裁", 依据="总裁：按草稿批准", 人选={1: ["codex", "deepseek"], 2: ["deepseek"]})
    t1 = sim.new("任务", 目标=g, 阶段=1, 标题="检索 A")
    t2 = sim.new("任务", 目标=g, 阶段=1, 标题="检索 B")
    t3 = sim.new("任务", 目标=g, 阶段=2, 标题="综合成文")
    sim.log(t1, "派发", 给="codex")
    sim.log(t2, "派发", 给="deepseek")
    sim.deliver_pass(t1, "codex", reworks[0])
    sim.deliver_pass(t2, "deepseek", reworks[1])
    sim.log(t3, "派发", 给="deepseek")
    sim.deliver_pass(t3, "deepseek", reworks[2], reviewer="codex")
    sim.log(g, "目标验收", 说明="成功标准逐条达成", 方案="A 确认完成；B 打回补充", 建议="A")
    sim.log(g, "完成", "总裁", 依据="总裁：可以")
    return g


def trunk_signature(view, goal_id):
    """同类目标的主干形状：每个阶段里每个任务的主干槽位序列。"""
    g = next(x for x in view["目标"] if x["编号"] == goal_id)
    by = {t["编号"]: t for t in view["任务"]}
    return [(s["序"], [tuple(m["槽位"] for m in by[tid]["主干"]) for tid in s["任务"]]) for s in g["阶段"]]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.environ.pop, "FLOW_NOW", None)

    def golden(self, name: str, view) -> None:
        path = GOLDEN / f"{name}.json"
        text = flow.dumps(view) + "\n"
        if os.environ.get("UPDATE_GOLDEN") or not path.exists():
            path.write_text(text, encoding="utf-8")
        self.assertEqual(path.read_text(encoding="utf-8"), text, f"视图模型和 {path.name} 不一致")

    def errors(self, items):
        return [x["msg"] for x in items if x["level"] == "error"]


class TestResearchGoal(Base):
    def test_full_goal_and_golden(self):
        sim = Sim(self.root)
        g = research_goal(sim)
        v = sim.view()
        goal = v["目标"][0]
        self.assertEqual(goal["状态"], "完成")
        self.assertEqual([s["状态"] for s in goal["阶段"]], ["通过", "通过"])
        self.assertEqual([p["名"] for p in goal["参与者"]], ["总裁", "总管", "codex", "deepseek"])
        self.assertEqual(self.errors(sim.check()), [])
        self.golden("调研目标", v)

    def test_stage_order_is_enforced(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="调研", 标题="框架对比")
        sim.log(g, "提交")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"]})
        sim.new("任务", 目标=g, 阶段=1, 标题="检索")
        t2 = sim.new("任务", 目标=g, 阶段=2, 标题="综合")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(t2, "派发", 给="deepseek")
        self.assertEqual(e.exception.kind, "规则错误")
        self.assertIn("前置还没通过", e.exception.msg)
        with self.assertRaises(flow.FlowError) as e:
            sim.log(f"{g}-T1", "派发", 给="deepseek")
        self.assertIn("人选", e.exception.msg)
        ev = sim.log(t2, "派发", 给="deepseek", 越过="总裁同意先并行起草")
        self.assertIn("越过", ev)
        self.assertTrue(any("偏离" in x["msg"] for x in sim.check()))

    def test_same_type_goals_share_trunk_shape(self):
        a = Sim(self.root / "a")
        b = Sim(self.root / "b")
        ga = research_goal(a, reworks=(1, 0, 0))
        gb = research_goal(b, reworks=(0, 2, 1))
        self.assertEqual(trunk_signature(a.view(), ga), trunk_signature(b.view(), gb))
        tb = next(t for t in b.view()["任务"] if t["编号"] == f"{gb}-T2")
        self.assertEqual(len(tb["支线"]), 4)

    def test_goal_acceptance_needs_all_stages(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="通用", 标题="小事")
        sim.log(g, "提交")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"]})
        with self.assertRaises(flow.FlowError) as e:
            sim.log(g, "目标验收", 方案="A", 建议="A")
        self.assertIn("阶段还没全部通过", e.exception.msg)


class TestTransferAndBlocked(Base):
    """T003 那种：受阻交总管、再转总裁；改方案后重派；总管初验后转给 Codex 确认。"""

    def build(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="看板常驻", 依据="总裁：让 DeepSeek 改")
        sim.log(t, "派发", 给="deepseek")
        sim.log(t, "接手", "deepseek")
        sim.log(t, "上报", "deepseek", 说明="沙箱不能写 ~/Library")
        sim.log(t, "转交", 给="总裁", 说明="总管试装仍被隐私保护拦截", 方案="A 登录项小应用；B 完全磁盘访问", 建议="A")
        return sim, t

    def test_decision_appears_and_clears(self):
        sim, t = self.build()
        v = sim.view()
        self.assertEqual([d["编号"] for d in v["待你决定"]], [t])
        self.assertEqual(v["待你决定"][0]["建议"], "A")
        text = (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8")
        self.assertIn(f"- {t}｜受阻：", text)
        sim.log(t, "解除", "总裁", 依据="总裁：选 A")
        self.assertEqual(sim.view()["待你决定"], [])
        st = next(x for x in sim.view()["任务"] if x["编号"] == t)
        self.assertEqual((st["状态"], st["持有人"]), ("执行中", "deepseek"))

    def test_options_required_when_escalating_to_boss(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(t, "上报", 给="总裁", 说明="要授权")
        self.assertEqual(e.exception.kind, "硬错误")

    def test_change_then_handover_to_reviewer(self):
        sim, t = self.build()
        sim.log(t, "解除", "总裁", 依据="总裁：选 A")
        sim.log(t, "变更", 变更项=["交付物"], 说明="改用方案 B：登录项小应用")
        sim.log(t, "交付", "deepseek")
        sim.log(t, "转交", 给="codex", 说明="总管代装验证后转独立确认")
        sim.log(t, "确认", "codex", 结果="需补充", 给="总管", 说明="补在线证据")
        sim.log(t, "交付", "总管", 给="codex")
        with self.assertRaises(flow.FlowError):
            sim.log(t, "转交", "deepseek", 给="claude", 说明="不是持有人不能转交")
        sim.log(t, "确认", "codex", 结果="通过", 说明="复核通过")
        v = sim.view()
        task = next(x for x in v["任务"] if x["编号"] == t)
        self.assertEqual(task["状态"], "通过")
        self.assertEqual([m["边"] for m in task["主干"]], ["建立", "派发", "接手", "交付", "确认"])
        self.assertEqual(self.errors(sim.check()), [])
        ctx, manifest = flow.context(sim.proj, t, "codex")
        self.assertIn("改用方案 B", ctx)
        self.golden("转交与受阻", v)


class TestBossIteration(Base):
    """T002 那种：总裁直接派、直接确认，来回改多次；总裁判的需补充不计返工。"""

    def test_boss_reworks_not_counted(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="班子设计文档", 发起="总裁", 依据="总裁：整理方案")
        sim.log(t, "派发", "总裁", 给="codex")
        sim.log(t, "接手", "codex")
        for _ in range(4):
            sim.log(t, "交付", "codex", 给="总裁")
            sim.log(t, "确认", "总裁", 结果="需补充", 说明="按反馈再改")
        sim.log(t, "交付", "codex", 给="总裁")
        sim.log(t, "确认", "总裁", 结果="通过", 说明="可以")
        task = next(x for x in sim.view()["任务"] if x["编号"] == t)
        self.assertEqual((task["状态"], task["返工次"]), ("通过", 0))
        self.golden("总裁直接迭代", sim.view())


class TestReworkCap(Base):
    def test_third_rework_to_same_person_is_blocked(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="deepseek")
        sim.log(t, "接手", "deepseek")
        for _ in range(2):
            sim.log(t, "交付", "deepseek")
            sim.log(t, "确认", 结果="需补充")
        self.assertTrue(any("连续返工 2 次" in x["msg"] for x in sim.check()))
        sim.log(t, "交付", "deepseek")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(t, "确认", 结果="需补充")
        self.assertIn("上限", e.exception.msg)
        sim.log(t, "确认", 结果="未通过", 说明="换人")
        sim.log(t, "改派", 给="codex", 说明="升档")
        self.assertEqual(next(x for x in sim.view()["任务"] if x["编号"] == t)["返工次"], 0)


class TestReopenRollback(Base):
    def test_reopen_invalidates_later_stages(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="开发", 标题="功能")
        sim.log(g, "提交")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"], 3: ["codex"]})
        ids = [sim.new("任务", 目标=g, 阶段=n, 标题=f"阶段{n}") for n in (1, 2, 3)]
        for tid, who in zip(ids, ("codex", "deepseek", "codex")):
            sim.log(tid, "派发", 给=who)
            sim.deliver_pass(tid, who)
        sim.log(ids[0], "重开", 给="codex", 说明="方案有漏洞")
        stages = sim.view()["目标"][0]["阶段"]
        self.assertEqual([s["状态"] for s in stages], ["进行中", "进行中", "进行中"])
        self.assertEqual([s["失效"] for s in stages], [False, True, True])
        with self.assertRaises(flow.FlowError):
            sim.log(g, "目标验收", 方案="A", 建议="A")


class TestPauseCorrectTamper(Base):
    def test_pause_resume(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        sim.log(t, "暂停", 说明="优先级调整")
        self.assertEqual(next(x for x in sim.view()["任务"] if x["编号"] == t)["类别"], "待办")
        sim.log(t, "恢复")
        task = next(x for x in sim.view()["任务"] if x["编号"] == t)
        self.assertEqual((task["状态"], task["持有人"]), ("执行中", "codex"))

    def test_correction_and_replay_mismatch(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "进展", 说明="记错的进展")
        sim.log(t, "更正", 更正=2, 说明="记错了")
        self.assertEqual(self.errors(sim.check()), [])
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        sim.log(t, "更正", 更正=4, 说明="作废派发，接手就对不上了")
        self.assertTrue(any("回放得到" in m for m in self.errors(sim.check())))

    def test_tampered_block_is_reported_and_restored(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        card = next((self.root / "collab" / "任务").glob(f"{t}-*.md"))
        text = card.read_text(encoding="utf-8")
        card.write_text(text.replace("状态：已批准", "状态：通过"), encoding="utf-8")
        self.assertTrue(any("被改动过" in m for m in self.errors(sim.check())))
        flow.render_all(sim.proj)
        self.assertEqual(self.errors(sim.check()), [])
        self.assertIn("状态：已批准", card.read_text(encoding="utf-8"))

    def test_stale_narrative_warning(self):
        sim = Sim(self.root, next_line="等 G001-T2 交付")
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "取消", 说明="不做了")
        self.assertTrue(any("「下一步」还在说 G001-T2" in x["msg"] for x in sim.check()))


class TestHardErrors(Base):
    def test_hard_errors(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        for edge, kw in (("跳过", {}), ("派发", {"给": "陌生人"})):
            with self.assertRaises(flow.FlowError) as e:
                sim.log(t, edge, **kw)
            self.assertEqual(e.exception.kind, "硬错误")
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(t, "交付", "codex", 证据=["collab/产出/没有.md"])
        self.assertEqual(e.exception.kind, "硬错误")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(t, "交付", "codex", 证据=["collab/产出/没有.md"], 越过="硬错误不能越过")
        self.assertEqual(e.exception.kind, "硬错误")

    def test_member_cannot_override(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        with self.assertRaises(flow.FlowError) as e:
            sim.log(t, "接手", "deepseek", 越过="我来")
        self.assertIn("只有总管、总裁能越过", e.exception.msg)

    def test_outside_evidence_warns(self):
        sim = Sim(self.root / "p")
        outside = self.root / "外部日志.txt"
        outside.write_text("log", encoding="utf-8")
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        sim.log(t, "交付", "codex", 证据=[str(outside)])
        self.assertTrue(any("项目外的证据" in x["msg"] for x in sim.check()))


class TestEvidenceAfterEnd(Base):
    def test_missing_evidence_only_matters_before_end(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        sim.log(t, "交付", "codex")
        evidence = self.root / "collab" / "产出" / t / "交付.md"
        moved = evidence.with_name("已归档.md")
        evidence.rename(moved)
        self.assertTrue(any("证据不存在" in m for m in self.errors(sim.check())))  # 待验收：要报
        moved.rename(evidence)
        sim.log(t, "确认", 结果="通过")
        evidence.rename(moved)
        self.assertFalse(any("证据" in x["msg"] for x in sim.check()))  # 已结束：文件移走不报
        sim.log(t, "重开", 给="codex", 说明="再做一次")
        self.assertTrue(any("证据不存在" in m for m in self.errors(sim.check())))  # 重开后又要报


class TestDeterminismAndLayout(Base):
    def test_same_input_same_bytes(self):
        a, b = Sim(self.root / "a"), Sim(self.root / "b")
        research_goal(a)
        research_goal(b)
        self.assertEqual(flow.dumps(a.view()), flow.dumps(a.view()))
        self.assertEqual(flow.dumps(a.view()), flow.dumps(b.view()))

    def test_planned_participants_listed_before_appearing(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="调研", 标题="x")
        sim.log(g, "提交")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"]})
        t = sim.new("任务", 目标=g, 阶段=1, 标题="检索")
        sim.log(t, "派发", 给="codex")
        sim.log(t, "接手", "codex")
        sim.log(t, "转交", "codex", 给="claude", 说明="计划外的人接手")
        ps = sim.view()["目标"][0]["参与者"]
        self.assertEqual([(p["名"], p["计划内"], p["出场"]) for p in ps],
                         [("总裁", True, True), ("总管", True, True), ("codex", True, True),
                          ("deepseek", True, False), ("claude", False, True)])

    def test_global_order_and_current_edges(self):
        sim = Sim(self.root)
        t1 = sim.new("任务", 标题="a", 依据="总裁：做")
        t2 = sim.new("任务", 标题="b", 依据="总裁：做")
        sim.log(t1, "派发", 给="codex")
        sim.log(t2, "派发", 给="deepseek")
        v = sim.view()
        seqs = [e["项目序"] for e in v["目标"][0]["事件"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))
        self.assertEqual([(c["对象"], c["发起"], c["接收"]) for c in v["当前"] if c["对象"] in (t1, t2)],
                         [(t1, "总管", "codex"), (t2, "总管", "deepseek")])


class TestSmallAndContext(Base):
    def test_context_has_role_slice_and_commands(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        ctx, manifest = flow.context(sim.proj, t, "codex")
        self.assertIn("执行者交付前自测", ctx)
        self.assertNotIn("总管的规则", ctx)
        self.assertIn("记 " + t + " 接手 --作为 codex", ctx)
        self.assertTrue(all(m["字节"] > 0 for m in manifest))
        sim.log(t, "接手", "codex")
        sim.log(t, "交付", "codex", 给="deepseek")
        ctx, _ = flow.context(sim.proj, t, "deepseek")
        self.assertIn("确认交付", ctx)
        self.assertIn("要确认的交付", ctx)

    def test_cli_round_trip(self):
        sim = Sim(self.root)
        os.environ["FLOW_NOW"] = "2026-11-01T10:00:00+08:00"
        base = ["--project", str(self.root)]
        self.assertEqual(flow.main(base + ["new", "task", "--title", "没有目标", "--basis", "总裁：做"]), 2)
        self.assertEqual(flow.main(base + ["new", "goal", "--title", "命令行", "--type", "通用", "--basis", "总裁：做"]), 0)
        f = self.root / "框架.json"
        f.write_text(json.dumps({"阶段": [{"序": 1, "名称": "做", "类型": "执行", "前置": [], "任务": [
            {"键": "a", "标题": "命令行", "执行": "Codex", "目的": "x", "交付物": "y", "验收标准": "z"}]}]}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(flow.main(base + ["frame", "G001", "--file", str(f)]), 0)
        self.assertEqual(flow.main(base + ["log", "G001", "提交", "--note", "n", "--advice", "批"]), 2)  # 目标卡没写
        card = next((self.root / "collab" / "目标").glob("G001-*.md"))
        card.write_text(card.read_text(encoding="utf-8").replace("- 要什么：\n", "- 要什么：x\n").replace("- 成功标准：\n", "- 成功标准：y\n"), encoding="utf-8")
        self.assertEqual(flow.main(base + ["log", "G001-T1", "派发", "--to", "Codex"]), 2)
        self.assertEqual(flow.main(base + ["log", "G001", "提交", "--note", "n", "--advice", "批"]), 0)
        self.assertEqual(flow.main(base + ["log", "G001", "批准", "--as", "总裁", "--basis", "总裁：批"]), 0)
        self.assertEqual(flow.main(base + ["log", "G001-T1", "派发", "--to", "Codex"]), 0)
        self.assertEqual(flow.main(base + ["log", "G001-T1", "交付", "--as", "codex"]), 2)
        self.assertEqual(flow.main(base + ["log", "G001-T1", "建立"]), 2)


class TestCheckGaps(Base):
    """方案 01 第 2.6、2.9、2.10 节里第一轮没做全的几项。"""

    def approved_research(self, sim):
        g = sim.new("目标", 类型="调研", 标题="框架对比")
        sim.log(g, "提交")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"]})
        return g

    def test_next_hides_rejected_edges_and_lists_ready_stages(self):
        sim = Sim(self.root)
        g = self.approved_research(sim)
        self.assertEqual([r["序"] for r in flow.ready_stages(sim.proj, g)], [1])
        t2 = sim.new("任务", 目标=g, 阶段=2, 标题="综合")
        blocked = []
        moves = [m["边"] for m in flow.legal(sim.proj, t2, "总管", blocked)]
        self.assertNotIn("派发", moves)
        self.assertIn("前置还没通过", next(b["原因"] for b in blocked if b["边"] == "派发"))
        blocked = []
        flow.legal(sim.proj, g, "总管", blocked)
        self.assertIn("目标验收", [b["边"] for b in blocked])
        t1 = sim.new("任务", 目标=g, 阶段=1, 标题="检索")
        self.assertEqual([(r["序"], r["任务"], r["命令"]) for r in flow.ready_stages(sim.proj, g)], [(1, [t1], "")])
        sim.log(t1, "派发", 给="codex")
        self.assertEqual(flow.ready_stages(sim.proj, g), [])

    def test_skeleton_load_checks(self):
        sim = Sim(self.root)
        sk = json.loads(json.dumps(sim.proj.skeleton("任务")))
        self.assertEqual(flow.check_skeleton(sk, "任务.json"), [])
        sk["边"]["取消"]["从"].append("通过")                      # 终止态多了出边
        sk["边"]["派发"]["接收"] = "外人"                          # 席位不认识
        sk["状态"]["孤岛"] = {"类别": "进行"}                       # 到不了、也走不到终止
        msgs = " ".join(x["msg"] for x in flow.check_skeleton(sk, "任务.json"))
        for want in ("只能走「重开」", "席位「外人」", "「孤岛」从初始到不了", "「孤岛」走不到终止"):
            self.assertIn(want, msgs)

    def test_trunk_must_reduce(self):
        sim = Sim(self.root)
        rows = [{"seq": 1, "项目序": 1, "边": "建立", "后状态": "已批准", "前状态": "无", "接收": "总管"},
                {"seq": 2, "项目序": 2, "边": "派发", "后状态": "已交接", "前状态": "已批准", "接收": "codex"},
                {"seq": 3, "项目序": 3, "边": "交付", "后状态": "待验收", "前状态": "执行中", "接收": "总管", "发起": "codex"},
                {"seq": 4, "项目序": 4, "边": "确认", "结果": "通过", "后状态": "通过", "前状态": "待验收", "接收": "无", "发起": "总管"}]
        st = flow.replay("T009", rows)
        self.assertIn("归约不成主干", flow.trunk_problem(st, sim.proj.skeleton("任务")))
        t = sim.new("任务", 标题="正常", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        sim.deliver_pass(t, "codex", 1)
        states, _, _ = flow.replay_all(sim.proj)
        self.assertEqual(flow.trunk_problem(states[t], sim.proj.skeleton("任务")), "")

    def test_narrative_not_updated_after_progress(self):
        sim = Sim(self.root, next_line="派活")
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        p = self.root / "collab" / "PROGRESS.md"
        p.write_text(p.read_text(encoding="utf-8").replace("派活", "派 G001-T2"), encoding="utf-8")
        with flow.locked(sim.proj):
            flow.render_all(sim.proj)
        sim.log(t, "派发", 给="codex")
        self.assertFalse(any("没更新" in x["msg"] for x in sim.check()))
        sim.deliver_pass(t, "codex")
        self.assertTrue(any("G001-T2 有进展后没更新" in x["msg"] for x in sim.check()))
        p = self.root / "collab" / "PROGRESS.md"
        p.write_text(p.read_text(encoding="utf-8").replace("派 G001-T2", "选下一件事"), encoding="utf-8")
        flow.render_all(sim.proj)
        self.assertFalse(any("没更新" in x["msg"] for x in sim.check()))

    def test_old_skeleton_version_is_found_in_history(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x", 依据="总裁：做")
        sim.log(t, "派发", 给="codex")
        f = self.root / "collab" / "内部" / "流转" / f"{t}.jsonl"
        f.write_text(f.read_text(encoding="utf-8").replace('"骨架": "任务@2"', '"骨架": "任务@7"'), encoding="utf-8")
        self.assertTrue(any("任务@7" in m for m in self.errors(sim.check())))
        old = dict(sim.proj.skeleton("任务"), 版本=7)
        hist = self.root / "collab" / "内部" / "流程" / "历史"
        hist.mkdir()
        (hist / "任务@7.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        sim.proj = flow.Project(self.root)
        self.assertEqual(self.errors(sim.check()), [])
        states, _, _ = flow.replay_all(sim.proj)
        self.assertEqual(flow.obj_skeleton(sim.proj, states[t])["版本"], 7)


class TestWorkdir(Base):
    def test_goal_workdir_follows_card_name(self):
        sim = Sim(self.root)
        g = sim.new("目标", 类型="调研", 标题="框架对比")
        self.assertFalse((self.root / "work" / f"{g}-框架对比").exists())  # 建立时不建工作目录
        sim.log(g, "提交", 说明="两阶段")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"]})
        self.assertTrue((self.root / "work" / f"{g}-框架对比").is_dir())  # 批准时才建
        t = sim.new("任务", 目标=g, 阶段=1, 标题="检索")
        sim.log(t, "派发", 给="codex")
        text, _ = flow.context(sim.proj, t, "codex")
        self.assertIn(f"交付默认放 `work/{g}-框架对比/{t}/`", text)
        self.assertIn(f"工位 `work/{g}-框架对比/.scratch/codex/{t}/`", text)
        self.assertEqual(next(x for x in sim.view()["目标"] if x["编号"] == g)["工作目录"], f"work/{g}-框架对比")
        sim.log(t, "接手", "codex")
        sim.log(t, "交付", "codex", 给="总管")
        text, _ = flow.context(sim.proj, t, "总管")
        self.assertIn(f"`collab/产出/{t}/`", text)


class TestDraftStage(Base):
    """G012：想法、讨论、方案三个起草阶段，由事件回放得出。"""

    def progress(self, sim):
        return (self.root / "collab" / "PROGRESS.md").read_text(encoding="utf-8")

    def test_create_with_title_and_basis_only(self):
        sim = Sim(self.root)
        sim.tick()
        g, path = flow.create(sim.proj, "目标", {"发起": "总管", "写入者": "总管", "标题": "随手一想", "依据": "总裁：记个想法"})
        st = flow.replay_all(sim.proj)[0][g]
        self.assertEqual((st["状态"], st["类型"], st["起草阶段"]), ("起草", "通用", "想法"))
        self.assertIn("状态：起草 ｜ 阶段：想法 ｜ 类型：通用", path.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "work").exists() and any((self.root / "work").iterdir()))

    def test_stage_events_and_header(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="想一想")
        sim.log(g, "起草阶段", 结果="讨论")
        self.assertIn("阶段：讨论", flow.card_path(sim.proj, g).read_text(encoding="utf-8"))
        sim.log(g, "起草阶段", 结果="方案")
        self.assertEqual(sim.view()["目标"][0]["起草阶段"], "方案")
        with self.assertRaises(flow.FlowError):
            sim.log(g, "起草阶段", 结果="执行")
        with self.assertRaises(flow.FlowError):
            sim.log(g, "起草阶段")
        sim.log(g, "起草阶段", 结果="想法")  # 可以退回前一段
        self.assertEqual(sim.view()["目标"][0]["起草阶段"], "想法")
        sim.log(g, "提交", 说明="小事直接搭框架")  # 不经过讨论和方案也能提交
        with self.assertRaises(flow.FlowError):  # 离开起草后阶段没有意义
            sim.log(g, "起草阶段", 结果="讨论")
        self.assertNotIn("｜ 阶段：", flow.card_path(sim.proj, g).read_text(encoding="utf-8"))
        self.assertIsNone(sim.view()["目标"][0]["起草阶段"])
        self.assertEqual(self.errors(sim.check()), [])

    def test_task_cannot_use_stage_event(self):
        sim = Sim(self.root)
        t = sim.new("任务", 标题="x")
        with self.assertRaises(flow.FlowError):
            sim.log(t, "起草阶段", 结果="讨论")

    def test_old_goal_without_stage_event_unchanged(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="旧卡")
        sim.log(g, "提交", 说明="框架已搭")
        sim.log(g, "退回", "总裁", 说明="再改")  # 回到起草，但框架早已搭过
        st = flow.replay_all(sim.proj)[0][g]
        self.assertEqual(st["状态"], "起草")
        self.assertIsNone(flow.draft_stage(st))
        self.assertNotIn("阶段：", flow.card_path(sim.proj, g).read_text(encoding="utf-8").split("## ")[0])
        self.assertEqual(len([e for e in st["事件"] if e["边"] == "起草阶段"]), 0)

    def test_pause_works_on_draft(self):
        """暂停能用于起草中的目标：暂停、恢复都合法，阶段保持，暂停时不能改阶段，取消也行。"""
        sim = Sim(self.root)
        g = sim.new("目标", 标题="先放一放")
        sim.log(g, "起草阶段", 结果="讨论")
        sim.log(g, "暂停", 说明="暂时先不开发")
        st = flow.replay_all(sim.proj)[0][g]
        self.assertEqual((st["状态"], st["持有人"]), ("暂停", "总管"))
        self.assertEqual(flow.draft_stage(st), "讨论")
        self.assertIn("状态：暂停 ｜ 阶段：讨论", flow.card_path(sim.proj, g).read_text(encoding="utf-8"))
        self.assertEqual(self.errors(sim.check()), [])
        with self.assertRaises(flow.FlowError):
            sim.log(g, "起草阶段", 结果="方案")
        sim.log(g, "恢复")
        st = flow.replay_all(sim.proj)[0][g]
        self.assertEqual((st["状态"], flow.draft_stage(st)), ("起草", "讨论"))
        sim.log(g, "暂停", 说明="再放")
        sim.log(g, "取消", 说明="不做了")
        self.assertEqual(flow.replay_all(sim.proj)[0][g]["状态"], "取消")
        self.assertEqual(self.errors(sim.check()), [])

    def test_progress_one_line_summary(self):
        sim = Sim(self.root)
        a = sim.new("目标", 标题="想法甲")
        b = sim.new("目标", 标题="想法乙")
        c = sim.new("目标", 标题="讨论中的")
        d = sim.new("目标", 标题="方案中的")
        e = sim.new("目标", 标题="已提交的")
        sim.log(c, "起草阶段", 结果="讨论")
        sim.log(d, "起草阶段", 结果="方案")
        sim.log(e, "提交", 说明="小事")
        text = self.progress(sim)
        self.assertIn(f"起草中：想法 2 个｜讨论中 {c}｜方案中 {d}", text)
        for g in (a, b, c, d):
            self.assertNotIn(f"| {g} |", text)
        self.assertIn(f"| {e} | 已提交的", text)
        self.assertEqual(self.errors(sim.check()), [])

    def test_context_gives_plan_path_not_discussion(self):
        sim = Sim(self.root)
        g = research_goal(sim)
        gdir = self.root / "collab" / "目标" / g
        gdir.mkdir()
        (gdir / "问题.md").write_text("# 问题\n机密的问题内容\n", encoding="utf-8")
        t = flow.goal_tasks(flow.replay_all(sim.proj)[0], g)[0]["编号"]
        text, _ = flow.context(sim.proj, t, "codex")
        self.assertNotIn("方案（", text)  # 还没有方案.md
        (gdir / "方案.md").write_text("# 方案\n", encoding="utf-8")
        text, _ = flow.context(sim.proj, t, "codex")
        self.assertIn(f"`collab/目标/{g}/方案.md`", text)
        self.assertIn("开工前先读", text)
        self.assertNotIn("问题.md", text)
        self.assertNotIn("机密的问题内容", text)
        self.assertEqual(sim.view()["目标"][0]["文件"], {"问题": f"collab/目标/{g}/问题.md", "方案": f"collab/目标/{g}/方案.md"})

    def test_new_card_has_only_want_and_criteria(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="新卡")
        text = flow.card_path(sim.proj, g).read_text(encoding="utf-8")
        self.assertIn("- 要什么：", text)
        self.assertIn("- 成功标准：", text)
        for gone in ("硬约束", "可替换的做法", "优先：", "依赖：", "截止："):
            self.assertNotIn(gone, text)

    def test_open_questions_and_other_docs(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="有问题的")
        gdir = self.root / "collab" / "目标" / g
        gdir.mkdir()
        self.assertEqual(sim.view()["目标"][0]["待解决"], [])
        (gdir / "问题.md").write_text("# 问题\n\n## 待解决\n1. 做成独立应用吗？\n   - 建议：独立应用\n- 要不要提示？\n\n## 已解决\n- 接口要补吗？→ 不用\n", encoding="utf-8")
        (gdir / "调研.md").write_text("# 调研\n", encoding="utf-8")
        v = sim.view()["目标"][0]
        self.assertEqual(v["待解决"], ["做成独立应用吗？", "要不要提示？"])
        self.assertEqual(v["文件"], {"问题": f"collab/目标/{g}/问题.md", "其他": [f"collab/目标/{g}/调研.md"]})

    def test_old_discussion_file_still_listed(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="旧卡")
        gdir = self.root / "collab" / "目标" / g
        gdir.mkdir()
        (gdir / "讨论.md").write_text("# 讨论\n## 待解决\n- 不算数\n", encoding="utf-8")
        v = sim.view()["目标"][0]
        self.assertEqual(v["文件"], {"讨论": f"collab/目标/{g}/讨论.md"})
        self.assertEqual(v["待解决"], [])

    def test_archive_moves_directory_with_card(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="归档的")
        gdir = self.root / "collab" / "目标" / g
        gdir.mkdir()
        (gdir / "方案.md").write_text("# 方案\n", encoding="utf-8")
        with self.assertRaises(flow.FlowError):  # 没结束不能归档
            flow.archive_goal(sim.proj, g)
        sim.log(g, "取消", 说明="不做了")
        # 手工只移卡片：检查报出遗漏
        card = flow.card_path(sim.proj, g)
        arch = self.root / "collab" / "归档" / "目标"
        arch.mkdir(parents=True)
        card.rename(arch / card.name)
        self.assertTrue(any("flow.py 归档" in m for m in self.errors(sim.check())))
        moved = flow.archive_goal(sim.proj, g)
        self.assertEqual(len(moved), 1)
        self.assertFalse(gdir.exists())
        self.assertEqual(self.errors(sim.check()), [])
        self.assertEqual(sim.view()["目标"][0]["文件"], {"方案": f"collab/归档/目标/{g}/方案.md"})

    def test_board_data_has_ideas_and_archived_links(self):
        sys.path.insert(0, str(Path(flow.__file__).parents[1] / "board"))
        import server
        sim = Sim(self.root)
        a = sim.new("目标", 标题="想法甲")
        b = sim.new("目标", 标题="方案乙")
        sim.log(b, "起草阶段", 结果="方案")
        bdir = self.root / "collab" / "目标" / b
        bdir.mkdir()
        (bdir / "方案.md").write_text("# 方案\n", encoding="utf-8")
        _, goals, _ = server.flow_cards(self.root / "collab", self.root)
        by = {g["id"]: g for g in goals}
        self.assertEqual((by[a]["idea"], by[a]["files"]), ("想法", {}))
        self.assertEqual((by[b]["idea"], by[b]["files"]), ("方案", {"方案": f"collab/目标/{b}/方案.md"}))
        sim.log(b, "取消", 说明="不做了")
        flow.archive_goal(sim.proj, b)
        _, goals, _ = server.flow_cards(self.root / "collab", self.root)
        done = next(g for g in goals if g["id"] == b)
        self.assertIsNone(done["idea"])
        self.assertTrue(done["archived"])
        self.assertEqual(done["files"], {"方案": f"collab/归档/目标/{b}/方案.md"})  # 归档后链接指向新位置，文件在

    def test_archive_cli_moves_both(self):
        sim = Sim(self.root)
        g = sim.new("目标", 标题="命令归档")
        gdir = self.root / "collab" / "目标" / g
        gdir.mkdir()
        (gdir / "讨论.md").write_text("# 讨论\n", encoding="utf-8")
        sim.log(g, "取消", 说明="不做了")
        self.assertEqual(flow.main(["--project", str(self.root), "归档", g]), 0)
        self.assertTrue((self.root / "collab" / "归档" / "目标" / g / "讨论.md").is_file())
        self.assertTrue(any((self.root / "collab" / "归档" / "目标").glob(f"{g}-*.md")))
        self.assertEqual(self.errors(sim.check()), [])


if __name__ == "__main__":
    unittest.main()
