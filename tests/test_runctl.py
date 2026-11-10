"""G015 第三轮：状态、正在写的内容、停止、收尾、运行上限。假成员（不调用模型）按总裁话里的 [[工具 N]]、[[慢]]、[[卡]] 表演。"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE.parent / "src" / "board"))
sys.path.insert(0, str(HERE))
import dispatch  # noqa: E402
import flow  # noqa: E402
from test_issue import meeting, say, state  # noqa: E402
from test_wake import DISPATCH, Room  # noqa: E402


class TestParsers(unittest.TestCase):
    def test_claude_partial_events(self):
        def parse(ev):
            out = {}
            dispatch.parse_claude(ev, out)
            return out
        self.assertEqual(parse({"type": "stream_event", "event": {"type": "message_start"}}), {"phase": "思考", "draft_reset": True})
        self.assertEqual(parse({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}})["phase"], "正在写回复")
        o = parse({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}}})
        self.assertEqual((o["phase"], o["action"]), ("调用工具", "Bash"))
        self.assertEqual(parse({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你好"}}}), {"draft_add": "你好"})
        self.assertEqual(parse({"type": "user"})["phase"], "思考")

    def test_live_usage_dedupes_by_message(self):
        acc = {}
        u = {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}
        for _ in range(2):  # 同一条消息的多个内容块各发一次 assistant 事件
            dispatch.usage_claude({"type": "assistant", "message": {"id": "a", "usage": u}}, acc)
        dispatch.usage_claude({"type": "assistant", "message": {"id": "b", "usage": u}}, acc)
        t = dispatch.finish_tokens(acc)
        self.assertEqual((t["input"], t["cached"], t["output"], t["calls"]), (30, 200, 14, 2))

    def test_partial_flag_added_for_claude_only(self):
        a = dispatch.isolate(["claude", "-p", "--output-format", "stream-json", "x"])
        self.assertIn("--include-partial-messages", a)
        self.assertNotIn("--include-partial-messages", dispatch.isolate(["codex", "exec", "--json"]))
        self.assertNotIn("--include-partial-messages", dispatch.isolate(["claude", "-p", "x"]))

    def test_run_state_labels(self):
        import server
        now = time.time()
        iso = lambda ago: __import__("datetime").datetime.fromtimestamp(now - ago).astimezone().isoformat(timespec="seconds")
        run = {"status": "运行中", "started": iso(30), "last_at": iso(2)}
        self.assertEqual(server.run_state({"status": "运行中", "started": iso(3)}), "启动中")
        for ph in ("思考", "调用工具", "正在写回复"):
            self.assertEqual(server.run_state({**run, "phase": ph}), ph)
        self.assertEqual(server.run_state({**run, "phase": "思考", "last_at": iso(server.STALL_SECONDS + 20)}), "疑似卡住")
        self.assertEqual(server.run_state({"status": "失败"}), "失败")
        self.assertEqual(server.run_state({"status": "异常结束"}), "失败")
        self.assertEqual(server.run_state({"status": "已中断"}), "已停止")
        self.assertEqual(server.run_state({"status": "完成"}), "完成")


class Ctl(Room):
    def team(self, **top):
        p = self.root / "team" / "班子.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update(top)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def start(self):
        i = meeting(self.sim)
        self.sim.log(i, "开始", "总裁", 写入者="看板")
        os.environ.pop("FLOW_NOW", None)
        return i

    def ask(self, i, text, who="codex"):
        say(self.sim, i, "总裁", f"@{who} {text}", 点名=[who])
        os.environ.pop("FLOW_NOW", None)

    def spawn(self, i, who="codex"):
        return subprocess.Popen([sys.executable, str(DISPATCH), "--project", str(self.root / "p"), "meet-run", i, who],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def wait(self, cond, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            v = cond()
            if v:
                return v
            time.sleep(0.2)
        self.fail("等待超时")

    def running(self):
        return [r for r in self.runs() if r["status"] == "运行中" and r.get("pid") and r.get("steps") is not None and r.get("last_at")]


class TestLive(Ctl):
    def test_phase_draft_and_steps_visible_while_running(self):
        i = self.start()
        self.ask(i, "写一段 [[工具 2]] [[慢]]")
        p = self.spawn(i)
        run = self.wait(lambda: next((r for r in self.runs() if r["status"] == "运行中" and r.get("phase") == "调用工具"), None))
        self.assertTrue(run["last_action"])
        draft = self.runs_dir / f"{run['run']}.draft.txt"
        got = self.wait(lambda: draft.exists() and draft.read_text(encoding="utf-8") if draft.exists() and draft.read_text(encoding="utf-8") else None)
        self.assertIn("先写", got)
        import server
        v = server.run_view(next(r for r in self.runs() if r["status"] == "运行中"), self.root / "p")
        self.assertEqual(v["state"], "正在写回复")
        self.assertIn("先写", v["draft"])
        self.assertIsNotNone(v["elapsed"])
        p.wait(timeout=30)
        done = self.runs("codex")[-1]
        self.assertEqual((done["status"], done["steps"]), ("完成", 2))
        self.assertFalse(draft.exists(), "结束后草稿换成正式发言")
        self.assertTrue(done["tokens"]["total"] > 0)
        self.assertEqual(done["phase"], "完成")


class TestStopAndWrap(Ctl):
    def test_stop_then_wrap_resumes_same_session(self):
        i = self.start()
        self.ask(i, "想一想 [[卡]]")
        p = self.spawn(i)
        run = self.wait(lambda: next((r for r in self.runs() if r["status"] == "运行中" and r.get("session")), None))
        r = self.dispatch("stop-member", i, "codex")
        self.assertIn("已停止", r.stdout)
        p.wait(timeout=20)
        stopped = self.runs("codex")[-1]
        self.assertEqual(stopped["status"], "已中断")
        self.assertEqual([m for m in self.msgs(i) if m["发起"] == "codex"], [], "停止的运行不写发言")
        r = self.dispatch("wrap", i, "codex", "--reason", "总裁点了收尾")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        wrapped = self.runs("codex")[-1]
        self.assertEqual((wrapped["status"], wrapped["mode"], wrapped["session"]), ("完成", "续接", run["session"]))
        self.assertIn("不要再调用任何工具", wrapped["prompt"])
        self.assertEqual([m["正文"] for m in self.msgs(i) if m["发起"] == "codex"], ["收尾：codex 用已有内容发言"])

    def test_wrap_while_running_stops_first(self):
        i = self.start()
        self.ask(i, "想一想 [[卡]]")
        p = self.spawn(i)
        self.wait(lambda: next((r for r in self.runs() if r["status"] == "运行中" and r.get("session")), None))
        r = self.dispatch("wrap", i, "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p.wait(timeout=20)
        self.assertEqual([x["status"] for x in self.runs("codex")], ["已中断", "完成"])
        self.assertEqual(len([m for m in self.msgs(i) if m["发起"] == "codex"]), 1)


class TestLimits(Ctl):
    def test_step_limit_wraps_up_automatically(self):
        self.team(**{"朝会运行上限": {"步数": 2, "分钟": 10}})
        i = self.start()
        self.ask(i, "查一查 [[工具 6]]")
        r = self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rs = self.runs("codex")
        self.assertEqual([x["status"] for x in rs], ["已中断", "完成"], [x.get("error") for x in rs])
        self.assertIn("步数 2", rs[0]["stop_reason"])
        self.assertLessEqual(rs[0]["steps"], 2)
        self.assertEqual((rs[1]["mode"], rs[1]["session"]), ("续接", rs[0]["session"]))
        self.assertIn("上限", rs[1]["收尾"])
        notes = [e.get("说明", "") for e in state(self.sim, i)["事件"] if e["边"] == "进展"]
        self.assertTrue(any("步数 2" in n and "收尾" in n for n in notes), notes)
        self.assertEqual([m["正文"] for m in self.msgs(i) if m["发起"] == "codex"], ["收尾：codex 用已有内容发言"])
        self.assertIn("读到", rs[1])

    def test_time_limit(self):
        self.team(**{"朝会运行上限": {"步数": 0, "分钟": 0.03}})
        i = self.start()
        self.ask(i, "想 [[卡]]")
        t = time.time()
        r = self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLess(time.time() - t, 30)
        rs = self.runs("codex")
        self.assertIn("时间", rs[0]["stop_reason"])
        self.assertEqual(rs[1]["status"], "完成")

    def test_member_override_and_default(self):
        self.assertEqual(dispatch.run_limits("codex") if False else {"步数": 40, "秒数": 600}, {"步数": 40, "秒数": 600})
        self.team(**{"朝会运行上限": {"步数": 10, "分钟": 5}})
        m = json.loads((self.root / "team" / "班子.json").read_text(encoding="utf-8"))
        m["成员"][0]["运行上限"] = {"步数": 3}
        (self.root / "team" / "班子.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        old = dispatch.TEAM_FILE
        dispatch.TEAM_FILE = self.root / "team" / "班子.json"
        self.addCleanup(setattr, dispatch, "TEAM_FILE", old)
        self.assertEqual(dispatch.run_limits("codex"), {"步数": 3, "秒数": 300})
        self.assertEqual(dispatch.run_limits("deepseek"), {"步数": 10, "秒数": 300})


if __name__ == "__main__":
    unittest.main()
