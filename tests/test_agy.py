"""G058：Antigravity 命令行 agy 的事件解析、token 统计、推理档位和续接丢会话。夹具是 tests/样例/agy/ 里录的真实输出。"""
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE))
import dispatch  # noqa: E402
from test_wake import Room  # noqa: E402

SAMPLES = HERE / "样例" / "agy"
FAKE_AGY = HERE / "fake_agy.py"
L = dispatch.L


def events(name):
    return [json.loads(x) for x in (SAMPLES / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def replay(name):
    """按 Runner 的方式逐行解析：返回每行的 out 和累计的用量。"""
    outs, acc = [], {}
    for ev in events(name):
        out = {}
        dispatch.parse_agy(ev, out)
        dispatch.usage_agy(ev, acc)
        outs.append(out)
    return outs, dispatch.finish_tokens(acc)


class TestParseAgy(unittest.TestCase):
    def test_start_with_tools(self):
        outs, _ = replay("start-tools.jsonl")
        sid = "153a1875-1297-4c1f-8c5e-49b4698d1ff3"
        self.assertEqual(outs[0], {"session": sid}, "init 只给会话 ID（派活脚本据此仍算启动中）")
        self.assertEqual([o["action"] for o in outs if o.get("step")],
                         ["write_file：/tmp/agy-rec/out.txt",
                          L.t("disp.action.run") + "ls"])
        self.assertIn("tool", [o.get("phase") for o in outs])
        self.assertEqual(outs[-1]["final"], "完成（已创建 [out.txt](file:///tmp/agy-rec/out.txt) 并确认存在）。")
        self.assertFalse(any(o.get("error") for o in outs))

    def test_draft_collects_text_deltas(self):
        outs, _ = replay("resume-effort.jsonl")
        draft = ""
        for o in outs:
            if o.get("draft_reset"):
                draft = ""
            draft += o.get("draft_add", "")
            if o.get("draft_add"):
                self.assertEqual(o["phase"], "writing")
        self.assertEqual(draft, "", "回复写完（DONE）就清空正在写的内容")
        written = "".join(o.get("draft_add", "") for o in outs)
        self.assertEqual(written, "`out.txt`（[out.txt](file:///tmp/agy-rec/out.txt)）里写的是 `ok`（无末尾换行符）。")

    def test_errors(self):
        outs, _ = replay("effort-conflict.jsonl")
        self.assertIn("conflicts with --effort=high", outs[-1]["error"])
        self.assertEqual(outs[-1]["final"], "")
        self.assertNotIn("session", outs[-1], "出错时 conversation_id 是空的")
        outs, _ = replay("effort-unsupported.jsonl")
        self.assertIn('has no "xhigh" effort', outs[-1]["error"])
        outs, _ = replay("denied.jsonl")
        self.assertIn("write_file", outs[-1]["error"], "status 是 SUCCESS 但没有回复、工具被拒：要报出来")
        outs, _ = replay("lost.jsonl")
        self.assertFalse(any(o.get("error") for o in outs), "丢会话时 agy 不报错，由 Runner 比对会话 ID")

    def test_usage_sums_steps_not_session_total(self):
        _, t = replay("start-read.jsonl")
        res = events("start-read.jsonl")[-1]["result"]["usage"]
        self.assertEqual((t["input"], t["cached"], t["output"], t["calls"]), (10873, 6642, 60, 2))
        self.assertEqual((t["input"], t["cached"], t["output"]),
                         (res["input_tokens"], res["cache_read_tokens"], res["output_tokens"]), "第一次派活：按步相加 = result 的累计")
        self.assertEqual(t["context"], 2177 + 6642 + 29)
        _, t = replay("resume.jsonl")
        self.assertEqual((t["input"], t["cached"], t["output"], t["calls"]), (2287, 6770, 7, 1), "续接只算这一次，不含前一次")
        self.assertEqual(events("resume.jsonl")[-1]["result"]["usage"]["input_tokens"], 13160, "result 是会话累计")
        _, t = replay("effort-conflict.jsonl")
        self.assertIsNone(t, "没调用模型：用量记为未知")


class TestEffort(unittest.TestCase):
    cfg = {"parser": "agy", "start": ["agy", "-p", "{prompt}", "--model", "gemini-4-argon"],
           "resume": ["agy", "-p", "{prompt}", "--conversation", "{session}", "--model", "gemini-4-argon"]}

    def test_flag_added_after_program(self):
        a = dispatch.build_argv(self.cfg, "start", "hi", "", Path("/x"), "high")
        self.assertEqual(a, ["agy", "--effort", "high", "-p", "hi", "--model", "gemini-4-argon"])
        a = dispatch.build_argv(self.cfg, "resume", "hi", "s1", Path("/x"), "low")
        self.assertEqual(a[:3], ["agy", "--effort", "low"])
        self.assertIn("s1", a)
        self.assertEqual(dispatch.build_argv(self.cfg, "start", "hi", "", Path("/x")), ["agy", "-p", "hi", "--model", "gemini-4-argon"],
                         "不指定就不传，走 agy 默认")

    def test_existing_flag_replaced_and_env_prefix(self):
        cfg = dict(self.cfg, start=["env", "A=1", "agy", "--effort", "low", "-p", "{prompt}"])
        self.assertEqual(dispatch.build_argv(cfg, "start", "hi", "", Path("/x"), "max"),
                         ["env", "A=1", "agy", "--effort", "max", "-p", "hi"])

    def test_other_members_refuse(self):
        with self.assertRaises(SystemExit):
            dispatch.build_argv({"parser": "claude", "start": ["claude", "-p", "{prompt}"]}, "start", "hi", "", Path("/x"), "high")


class TestRunnerAgy(unittest.TestCase):
    """真的跑 Runner：命令行用 cat 回放录下的输出。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):  # Runner.run 会换掉信号处理
            self.addCleanup(signal.signal, s, signal.getsignal(s))

    def run_sample(self, name, session="", exit_code=0):
        rec = {"run": "G001-T1-01", "task": "G001-T1", "seat": "execute", "member": "agy-x",
               "mode": dispatch.RunMode.RESUME if session else dispatch.RunMode.NEW, "session": session, "steps": 0,
               "last_action": "", "final": "", "error": ""}
        argv = ["sh", "-c", f'cat "$0"; exit {exit_code}', str(SAMPLES / name)]
        code = dispatch.Runner(self.project, rec, argv, "agy", env=dict(os.environ)).run()
        rdir = dispatch.runs_dir(self.project)
        self.assertFalse((rdir / "G001-T1-01.draft.txt").exists())
        return code, json.loads((rdir / "G001-T1-01.json").read_text(encoding="utf-8"))

    def test_start_run(self):
        code, r = self.run_sample("start-tools.jsonl")
        self.assertEqual((code, r["status"], r["phase"]), (0, "done", "done"))
        self.assertEqual(r["session"], "153a1875-1297-4c1f-8c5e-49b4698d1ff3")
        self.assertEqual(r["steps"], 2)
        self.assertEqual(r["last_action"], L.t("disp.action.run") + "ls")
        self.assertTrue(r["final"].startswith("完成"))
        self.assertEqual((r["tokens"]["input"], r["tokens"]["cached"], r["tokens"]["output"], r["tokens"]["calls"]),
                         (8710 + 2175 + 2373, 6656 + 6782, 41 + 42 + 29, 3))

    def test_resume_same_session(self):
        sid = "153a1875-1297-4c1f-8c5e-49b4698d1ff3"
        code, r = self.run_sample("resume-effort.jsonl", session=sid)
        self.assertEqual((code, r["status"], r["session"]), (0, "done", sid))
        self.assertNotIn("session_replaced", r)
        self.assertEqual(r["tokens"]["input"], 10167 + 2209)

    def test_resume_lost_session_switches_to_new_one(self):
        old = "00000000-0000-0000-0000-000000000000"
        code, r = self.run_sample("lost.jsonl", session=old)
        self.assertEqual(r["status"], "done", "agy 照常回复了，算完成，但要提示")
        self.assertEqual(r["session"], "1a053019-d7d1-4c60-9564-026b884f9808", "之后续接接新会话")
        self.assertEqual(r["session_replaced"], old)
        self.assertIn(old, r["error"])
        self.assertNotIn("session_lost", r, "session_lost 会让朝会跳过这个（新）会话")

    def test_failed_run(self):
        code, r = self.run_sample("effort-conflict.jsonl", exit_code=1)
        self.assertEqual((code, r["status"]), (1, "failed"))
        self.assertIn("conflicts with --effort=high", r["error"])
        self.assertEqual(r["session"], "")

    def test_check_member(self):
        cfg = {"parser": "agy", "available": "✓", "start": ["cat", str(SAMPLES / "start-read.jsonl")]}
        res = dispatch.check_member("agy-x", cfg, timeout=10)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["tokens"], 10873 + 6642 + 60)
        cfg["start"] = ["cat", str(SAMPLES / "effort-unsupported.jsonl")]
        res = dispatch.check_member("agy-x", cfg, timeout=10)
        self.assertFalse(res["ok"])
        self.assertIn("xhigh", res["error"])


class TestDispatchCli(Room):
    """派活命令行：--effort 传到 agy 的参数里；不支持的成员在派出去之前就拒。"""

    def setUp(self):
        super().setUp()
        team = json.loads((self.root / "team" / "team.json").read_text(encoding="utf-8"))
        team["成员"].append({"派活名": "agy-x", "可用": "✓", "事件解析": "agy",
                           "新会话命令": [str(FAKE_AGY), "-p", "{prompt}", "--model", "gemini-4-argon"],
                           "续接命令": [str(FAKE_AGY), "-p", "{prompt}", "--conversation", "{session}", "--model", "gemini-4-argon"]})
        (self.root / "team" / "team.json").write_text(json.dumps(team, ensure_ascii=False), encoding="utf-8")
        roster = self.root / "p" / "collab" / "internal" / "plans" / "roster.json"
        r = json.loads(roster.read_text(encoding="utf-8"))
        r["成员"].append({"派活名": "agy-x", "名称": "Agy X"})
        roster.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def task(self, member):
        g = self.sim.new("目标", 类型="调研", 标题="agy")
        self.sim.log(g, "提交", 说明="一阶段")
        self.sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: [member]})
        os.environ.pop("FLOW_NOW", None)
        return self.sim.new("任务", 目标=g, 阶段=1, 标题="试")

    def argvs(self):
        f = self.env_dir / "agy.argv"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []

    def test_effort_reaches_agy(self):
        self.assertTrue(os.access(FAKE_AGY, os.X_OK), "fake_agy.py 要能直接执行")
        t = self.task("agy-x")
        r = self.dispatch("start", t, "执行", "agy-x", "开工", "--effort", "high")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.argvs()[-1][:2], ["--effort", "high"])
        run = self.runs("agy-x")[-1]
        self.assertEqual((run["status"], run["effort"], run["steps"]), ("done", "high", 2))
        self.assertEqual(run["session"], "153a1875-1297-4c1f-8c5e-49b4698d1ff3")

    def test_effort_refused_for_other_members(self):
        t = self.task("codex")
        r = self.dispatch("start", t, "执行", "codex", "开工", "--effort", "high")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("agy", r.stderr)
        self.assertEqual(self.runs(), [], "拒绝时不留运行记录")

    def test_bad_effort_value(self):
        t = self.task("agy-x")
        r = self.dispatch("start", t, "执行", "agy-x", "开工", "--effort", "huge")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.argvs(), [])


if __name__ == "__main__":
    unittest.main()
