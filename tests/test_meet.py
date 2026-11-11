"""朝会派活的测试（方案 03 第 3 步）：回复拆分、写回黑板、接力和排队，以及用假成员跑通一场朝会。

假成员 fake_member.py 照 Claude 命令行的输出格式回复，不调用模型；运行：python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE))
import flow  # noqa: E402
from test_flow import Base, Sim  # noqa: E402
from test_issue import WHO, meeting, say, state  # noqa: E402

DISPATCH = HERE.parent / "src" / "core" / "dispatch.py"
FAKE = HERE / "fake_member.py"


class TestReply(unittest.TestCase):
    def test_parse(self):
        out = flow.parse_reply("我主张 A。@deepseek 你看呢？\n<私下 总裁>codex 低估了工期</私下>")
        self.assertEqual(out, [{"edge": "post", "body": "我主张 A。@deepseek 你看呢？", "mentions": ["deepseek"]},
                               {"edge": "post", "body": "codex 低估了工期", "private": True}])
        self.assertEqual(flow.parse_reply(" [PASS] "), [{"edge": "pass"}])
        self.assertEqual(flow.parse_reply("<私下>只有这句</私下>"), [{"edge": "post", "body": "只有这句", "private": True}])
        self.assertEqual(flow.parse_reply(""), [])


class TestIssueEnd(Base):
    def test_write_back_and_wake(self):
        sim = Sim(self.root)
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        sim.tick()
        done, wake = flow.issue_end(sim.proj, i, "codex", "I001-01", "s1", "主张缓存 @DeepSeek @总裁 @某人", True, 2)
        self.assertEqual(wake, [], "成员写的 @ 不叫醒任何人")
        ev = state(sim, i)["events"][-1]
        self.assertEqual((ev["from"], ev.get("mentions"), ev["run"], ev["session"], ev["writer"]),
                         ("codex", None, "I001-01", "s1", "dispatcher"))
        self.assertIn("@DeepSeek", ev["body"], "@ 留在正文里当普通文字")
        self.assertEqual(flow.issue_end(sim.proj, i, "deepseek", "I001-02", "", "", False, 2), (["没有回复，不写发言"], []))

    def test_queue_rewakes_self(self):
        sim = Sim(self.root)
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        upto = state(sim, i)["events"][-1]["project_seq"]
        say(sim, i, "deepseek", "立场")
        say(sim, i, "总裁", "@codex 你呢", 点名=["codex"])  # codex 跑的时候总裁又点名了它
        sim.tick()
        _, wake = flow.issue_end(sim.proj, i, "codex", "I001-01", "", "立场", True, upto)
        self.assertEqual(wake, ["codex"])

    def test_ended_discussion_rejects(self):
        sim = Sim(self.root)
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        sim.log(i, "结束讨论", "总裁")
        with self.assertRaises(flow.FlowError):
            flow.issue_end(sim.proj, i, "codex", "I001-01", "", "晚到的发言", True, 0)


class TestMeetEndToEnd(Base):
    def setUp(self):
        super().setUp()
        team = self.root / "team"
        team.mkdir()
        cmd = lambda name: {"派活名": name, "可用": "✓", "事件解析": "claude",
                            "新会话命令": [sys.executable, str(FAKE), name, "{prompt}"],
                            "续接命令": [sys.executable, str(FAKE), name, "{prompt}", "--resume", "{session}"]}
        (team / "team.json").write_text(json.dumps({"成员": [cmd("codex"), cmd("deepseek")]}, ensure_ascii=False), encoding="utf-8")
        self.env = dict(os.environ, COLLAB_TEAM=str(team))
        self.env.pop("FLOW_NOW", None)

    def dispatch(self, *args):
        return subprocess.run([sys.executable, str(DISPATCH), "--project", str(self.root / "p"), *args],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def wait_messages(self, sim, obj, n, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            msgs = [e for e in state(sim, obj)["events"] if e["edge"] in flow.MESSAGES]
            runs = [json.loads(f.read_text(encoding="utf-8")) for f in (self.root / "p" / "collab" / "internal" / "runs").glob("*.json")]
            if len(msgs) >= n and not any(r.get("status") == "running" for r in runs):
                time.sleep(1.5)  # 等可能的后续接力
                return [e for e in state(sim, obj)["events"] if e["edge"] in flow.MESSAGES], runs
            time.sleep(0.3)
        self.fail(f"{timeout} 秒内没等到 {n} 条消息")

    def test_task_dispatch_makes_workstation(self):
        sim = Sim(self.root / "p")
        g = sim.new("目标", 类型="调研", 标题="工位")
        sim.log(g, "提交", 说明="两阶段")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"]})
        t = sim.new("任务", 目标=g, 阶段=1, 标题="检索")
        r = self.dispatch("start", t, "执行", "codex", "开工")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / "p" / "work" / g / ".scratch" / "codex" / t).is_dir())
        run = json.loads(next((self.root / "p" / "collab" / "internal" / "runs").glob(f"{t}-*.json")).read_text(encoding="utf-8"))
        self.assertIn(f"工位 `work/{g}/.scratch/codex/{t}/`", run["prompt"])

    def test_meeting_runs_through(self):
        sim = Sim(self.root / "p")
        i = meeting(sim)
        os.environ.pop("FLOW_NOW", None)
        r = self.dispatch("meet", i)
        self.assertNotEqual(r.returncode, 0, "没开始讨论不能叫醒")
        sim.log(i, "开始", "总裁", 写入者="board")
        os.environ.pop("FLOW_NOW", None)
        r = self.dispatch("meet", i)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        msgs, runs = self.wait_messages(sim, i, 3)
        got = sorted((m["from"], m["edge"], m.get("body", ""), bool(m.get("private"))) for m in msgs)
        self.assertEqual(got, sorted([
            ("codex", "post", "主张本地缓存。@deepseek 你怎么看风险？", False),
            ("deepseek", "post", "主张不缓存。", False),
            ("deepseek", "post", "codex 低估了工期", True)]))
        self.assertEqual(len(runs), 2, "codex 在发言里 @ deepseek 没有叫醒任何人")
        # 总裁 @ 它们，才有第二次
        sim.tick()
        os.environ.pop("FLOW_NOW", None)
        say(sim, i, "总裁", "@codex @deepseek 各补一句", 点名=["codex", "deepseek"])
        os.environ.pop("FLOW_NOW", None)
        r = self.dispatch("meet", i, "--wake", "codex", "deepseek")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        msgs, runs = self.wait_messages(sim, i, 5)
        self.assertEqual(len(runs), 4, [r["run"] for r in runs])
        by = {}
        for run in sorted(runs, key=lambda x: x["run"]):
            by.setdefault(run["member"], []).append(run)
        for who, rs in by.items():
            self.assertEqual([x["mode"] for x in rs], ["new", "resume"], who)
            self.assertEqual(rs[1]["session"], rs[0]["session"], "同一议题续接自己的会话")
            self.assertLess(rs[0]["read_upto"], rs[1]["read_upto"])
            self.assertNotIn("主张", rs[0]["prompt"].split("## 新发言")[-1] if "## 新发言" in rs[0]["prompt"] else "",
                             "第 1 轮看不到别人的立场")
        self.assertNotIn("低估了工期", by["codex"][1]["prompt"], "私下发言不喂给其他成员")
        v = flow.view(flow.Project(self.root / "p"))
        self.assertEqual([m["type"] for m in v["issues"][0]["messages"] if m["from"] == "codex"], ["position", "answer"])
        r = self.dispatch("meet", i)
        self.assertNotEqual(r.returncode, 0, "都开过口后不写 --wake 不叫醒")
        r = self.dispatch("meet", i, "--wake", "codex")
        self.assertIn("没有新的点名", r.stdout, "没人点名就不调用成员")
        r = self.dispatch("start", i, "与会", "codex", "x")
        self.assertIn("用 dispatch.py meet", r.stderr)


if __name__ == "__main__":
    unittest.main()
