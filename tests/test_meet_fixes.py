"""G015-T10：第三方验收（G015-T9）报告的问题的回归测试。假成员，不调用模型；真实成员的复现见 work/G015-朝会优化/G015-T10/复现/。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE.parent / "src" / "board"))
sys.path.insert(0, str(HERE))
import dispatch  # noqa: E402
import flow  # noqa: E402
from test_issue import say, state  # noqa: E402
from test_runctl import Ctl  # noqa: E402
from test_wake import DISPATCH  # noqa: E402

BOTH = ["codex", "deepseek"]


def feed_of(prompt):
    return prompt.split("## 新发言")[1].split("## 怎么发言")[0] if "## 新发言" in prompt else ""


class Fix(Ctl):
    def speak(self, i, member="codex"):
        return [m["正文"] for m in self.msgs(i) if m["发起"] == member]

    def live(self, member="codex"):
        return self.wait(lambda: next((r for r in self.runs(member) if r["status"] == "运行中" and r.get("session")), None))

    def public(self, i, text):
        say(self.sim, i, "总裁", text)
        os.environ.pop("FLOW_NOW", None)


class TestWrapKeepsFollowUp(Fix):
    """P1：运行中追问后收尾，追问不丢，也不答错题。"""

    def test_follow_up_goes_into_wrap_and_is_not_lost(self):
        i = self.start()
        self.ask(i, "第一问 [[卡]]")
        p = self.spawn(i)
        self.live()
        self.ask(i, "追问：丁香对应 7，7+8 等于几？")
        r = self.dispatch("wrap", i, "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p.wait(timeout=20)
        wrapped = self.runs("codex")[-1]
        self.assertEqual((wrapped["status"], wrapped["mode"]), ("完成", "续接"))
        self.assertIn("不要再调用任何工具", wrapped["prompt"])
        self.assertIn("丁香", feed_of(wrapped["prompt"]))
        self.assertIn("第一问", feed_of(wrapped["prompt"]), "被停的那次可能还没存进会话，从上次成功的读到补起")
        self.ask(i, "第二问")
        self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual(self.runs("codex")[-1]["status"], "完成")
        self.assertNotIn("丁香", feed_of(self.runs("codex")[-1]["prompt"]), "收尾已经给过，不再重复")

    def test_wrap_right_after_start_answers_the_new_question(self):
        i = self.start()
        self.ask(i, "第一题 2+2")
        self.dispatch("meet", i, "--wake", "codex")
        session = self.runs("codex")[-1]["session"]
        self.ask(i, "第二题 3+3 [[慢启动]]")
        p = self.spawn(i)
        self.wait(lambda: self.runs("codex")[-1]["status"] == "运行中" and "第二题" in self.runs("codex")[-1].get("prompt", ""))
        r = self.dispatch("wrap", i, "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p.wait(timeout=20)
        w = self.runs("codex")[-1]
        self.assertEqual((w["status"], w["session"]), ("完成", session))
        self.assertIn("第二题", feed_of(w["prompt"]))
        self.assertNotIn("第一题", feed_of(w["prompt"]))

    def test_wrap_of_first_speech_without_session_gets_context(self):
        i = self.start()
        self.ask(i, "第一问 [[慢启动]]")
        p = self.spawn(i)
        self.wait(lambda: self.runs("codex") and self.runs("codex")[-1]["status"] == "运行中" and self.runs("codex")[-1].get("pid"))
        self.ask(i, "追问：丁香")
        r = self.dispatch("wrap", i, "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p.wait(timeout=20)
        w = self.runs("codex")[-1]
        self.assertEqual(w["status"], "完成")
        for word in ("第一问", "丁香"):
            self.assertIn(word, feed_of(w["prompt"]))

    def test_follow_up_during_auto_wrap_wakes_again(self):
        self.team(**{"朝会运行上限": {"步数": 2, "分钟": 10}})
        i = self.start()
        self.ask(i, "查一查 [[工具 6]]")
        p = self.spawn(i)
        self.live()
        self.ask(i, "追问：丁香对应 7")
        p.wait(timeout=30)
        self.wait(lambda: len(self.runs("codex")) >= 3 and self.runs("codex")[-1]["status"] == "完成")
        rs = self.runs("codex")
        self.assertEqual([x["status"] for x in rs], ["已中断", "完成", "完成"])
        self.assertIn("丁香", feed_of(rs[2]["prompt"]))


class TestDoubleWrap(Fix):
    def test_two_wraps_at_once_give_one_message_and_one_note(self):
        i = self.start()
        self.ask(i, "想 [[卡]] [[慢收尾]]")
        p = self.spawn(i)
        self.live()
        cmd = [sys.executable, str(DISPATCH), "--project", str(self.root / "p"), "wrap", i, "codex", "--page"]
        ws = [subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for _ in range(2)]
        outs = [w.communicate(timeout=30)[0] for w in ws]
        p.wait(timeout=20)
        self.assertEqual(len(self.speak(i)), 1, outs)
        self.assertEqual([x["status"] for x in self.runs("codex")], ["已中断", "完成"])
        notes = [e for e in state(self.sim, i)["事件"] if e["边"] == "进展" and "收尾" in e.get("说明", "")]
        self.assertEqual(len(notes), 1)

    def test_wrap_while_wrapping_and_after_speaking_does_nothing(self):
        i = self.start()
        self.ask(i, "想 [[卡]] [[慢收尾]]")
        p = self.spawn(i)
        self.live()
        first = subprocess.Popen([sys.executable, str(DISPATCH), "--project", str(self.root / "p"), "wrap", i, "codex"],
                                 env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.wait(lambda: self.runs("codex")[-1].get("收尾") and self.runs("codex")[-1]["status"] == "运行中")
        self.assertIn("已经在收尾", self.dispatch("wrap", i, "codex").stdout)
        first.communicate(timeout=30)
        p.wait(timeout=20)
        self.assertIn("不用收尾", self.dispatch("wrap", i, "codex").stdout)
        self.assertEqual(len(self.speak(i)), 1)


class TestFirstSpeechRedeliver(Fix):
    """P2：首次发言失败后补叫，收到之后的公开发言，看不到同批成员的回答。"""

    def failed_batch(self, i):
        (self.fail_dir / "codex").touch()
        say(self.sim, i, "总裁", "@codex @deepseek 暗号甲是松", 点名=BOTH)
        os.environ.pop("FLOW_NOW", None)
        self.dispatch("meet", i, "--wake", "codex", "deepseek")
        self.assertEqual(self.runs("codex")[-1]["status"], "失败")
        self.assertTrue(self.speak(i, "deepseek"))
        (self.fail_dir / "codex").unlink()

    def test_redeliver_catches_up_but_stays_independent(self):
        i = self.start()
        self.failed_batch(i)
        self.public(i, "补充：暗号乙是竹")
        self.dispatch("meet", i, "--wake", "codex")
        run = self.runs("codex")[-1]
        feed = feed_of(run["prompt"])
        self.assertEqual(run["status"], "完成")
        self.assertIn("暗号甲", feed)
        self.assertIn("暗号乙", feed)
        self.assertNotIn("### deepseek", feed, "同一句话叫来的人的回答看不到")
        self.assertTrue(run["补到"], "喂到的项目序停在那句话，补过的单独记")
        self.ask(i, "下一问")
        self.dispatch("meet", i, "--wake", "codex")
        feed = feed_of(self.runs("codex")[-1]["prompt"])
        self.assertIn("### deepseek", feed, "下一轮收到同批的回答")
        self.assertNotIn("暗号乙", feed, "补过的不重复")
        self.assertIn("下一问", feed)

    def test_feed_rules(self):
        i = self.start()
        say(self.sim, i, "总裁", "@codex @deepseek 第一句", 点名=BOTH)
        say(self.sim, i, "总裁", "@codex 再说一遍", 点名=["codex"])
        say(self.sim, i, "deepseek", "同批的回答")
        say(self.sim, i, "总裁", "公开补充")
        say(self.sim, i, "总裁", "私下补充", 私下=True)
        say(self.sim, i, "总管", "总管公开说明")
        st = state(self.sim, i)
        os.environ.pop("FLOW_NOW", None)
        body = lambda f: [r["正文"] for r in f[0]]
        plain = flow.issue_feed(st, "codex")
        self.assertEqual(body(plain), ["@codex @deepseek 第一句", "@codex 再说一遍"])
        caught = flow.issue_feed(st, "codex", catch_up=True)
        self.assertEqual(body(caught), ["@codex @deepseek 第一句", "@codex 再说一遍", "公开补充", "总管公开说明"],
                         "前一句同批的 deepseek 也算同批；私下不给")
        self.assertEqual(caught[1], plain[1], "喂到的项目序不变，同批的回答留到下一轮")


class TestSessionLost(Fix):
    """P3：真实失败原因显示出来；会话丢失后补叫开新会话。"""

    def test_error_comes_from_errors_field(self):
        out = {}
        dispatch.parse_claude({"type": "result", "is_error": True, "subtype": "error_during_execution", "result": "",
                               "errors": ["No conversation found with session ID: x"]}, out)
        self.assertEqual(out["error"], "No conversation found with session ID: x")
        out = {}
        dispatch.parse_claude({"type": "result", "is_error": True, "subtype": "error_max_turns"}, out)
        self.assertEqual(out["error"], "error_max_turns")

    def test_stderr_used_when_event_has_no_reason(self):
        i = self.start()
        self.ask(i, "[[无原因失败]]")
        self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual(self.runs("codex")[-1]["error"], "真正的原因在 stderr")

    def test_lost_session_recovers_on_redeliver(self):
        i = self.start()
        self.ask(i, "暗号甲是松")
        self.dispatch("meet", i, "--wake", "codex")
        old = self.runs("codex")[-1]["session"]
        said = self.speak(i)[0]
        (self.fail_dir / f"{old}.lost").touch()
        self.ask(i, "暗号甲是什么")
        self.dispatch("meet", i, "--wake", "codex")
        failed = self.runs("codex")[-1]
        self.assertEqual((failed["status"], failed["session"]), ("失败", old))
        self.assertIn("No conversation found", failed["error"])
        self.assertTrue(failed["会话丢失"])
        import server
        self.assertIn("No conversation found", server.run_view(failed, self.root / "p")["error"])
        self.public(i, "补充：暗号乙是竹")
        self.dispatch("meet", i, "--wake", "codex")
        new = self.runs("codex")[-1]
        self.assertEqual((new["status"], new["mode"]), ("完成", "新会话"))
        self.assertNotEqual(new["session"], old)
        feed = feed_of(new["prompt"])
        for word in ("暗号甲是松", "暗号甲是什么", "暗号乙是竹", said):
            self.assertIn(word, feed, "新会话要带上全部公开发言，包括它自己说过的")
        self.assertIn("新会话", new["prompt"].split("\n")[0])
        (self.fail_dir / f"{old}.lost").unlink()  # 文件回来了也不再接旧会话
        self.ask(i, "下一问")
        self.dispatch("meet", i, "--wake", "codex")
        next_ = self.runs("codex")[-1]
        self.assertEqual((next_["status"], next_["session"]), ("完成", new["session"]))
        self.assertNotIn("暗号甲是松", feed_of(next_["prompt"]))

    def test_other_failures_keep_the_session(self):
        i = self.start()
        self.ask(i, "第一问")
        self.dispatch("meet", i, "--wake", "codex")
        old = self.runs("codex")[-1]["session"]
        (self.fail_dir / "codex").touch()
        self.ask(i, "第二问")
        self.dispatch("meet", i, "--wake", "codex")
        self.assertNotIn("会话丢失", self.runs("codex")[-1])
        (self.fail_dir / "codex").unlink()
        self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual((self.runs("codex")[-1]["mode"], self.runs("codex")[-1]["session"]), ("续接", old))

    def test_wrap_after_lost_session_starts_new(self):
        i = self.start()
        self.ask(i, "第一问")
        self.dispatch("meet", i, "--wake", "codex")
        old = self.runs("codex")[-1]["session"]
        (self.fail_dir / f"{old}.lost").touch()
        self.ask(i, "第二问")
        self.dispatch("meet", i, "--wake", "codex")
        r = self.dispatch("wrap", i, "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        w = self.runs("codex")[-1]
        self.assertEqual((w["status"], w["mode"]), ("完成", "新会话"))
        self.assertIn("第一问", feed_of(w["prompt"]))


class TestStates(Fix):
    def view(self, member="codex"):
        import server
        return server.run_view(self.runs(member)[-1], self.root / "p")

    def test_heartbeat_does_not_count_as_activity(self):
        """P4：工具不输出、命令行照发心跳，静默时间照涨，到阈值显示疑似卡住。"""
        import server
        self.addCleanup(setattr, server, "STALL_SECONDS", server.STALL_SECONDS)
        server.STALL_SECONDS = 2
        i = self.start()
        self.ask(i, "跑工具 [[心跳]]")
        p = self.spawn(i)
        self.wait(lambda: self.runs("codex") and self.runs("codex")[-1].get("phase") == "调用工具")
        v = self.wait(lambda: self.view()["state"] == "疑似卡住" and self.view(), timeout=5)
        self.assertEqual(v["phase"], "调用工具", "页面据此写「工具 N 秒没有新输出」")
        self.assertGreaterEqual(v["quiet"], 2)
        p.wait(timeout=20)

    def test_starting_shown_until_first_real_output(self):
        i = self.start()
        self.ask(i, "想 [[慢启动]]")
        p = self.spawn(i)
        self.wait(lambda: self.runs("codex") and self.runs("codex")[-1].get("phase") == "启动中" and "想" in self.runs("codex")[-1].get("prompt", ""))
        v = self.view()
        self.assertEqual(v["state"], "启动中", "进程还没输出")
        self.assertFalse(self.runs("codex")[-1].get("last_at"))
        self.wait(lambda: self.runs("codex")[-1].get("session"))
        self.assertEqual(self.view()["state"], "启动中", "只报了会话 ID 的初始化事件还算启动中")
        p.wait(timeout=20)
        self.assertEqual(self.runs("codex")[-1]["phase"], "完成")

    def test_member_without_phases_moves_to_thinking(self):
        i = self.start()
        self.ask(i, "想 [[无阶段]]")
        p = self.spawn(i)
        self.wait(lambda: self.runs("codex") and self.runs("codex")[-1].get("phase") == "思考")
        self.assertEqual(self.view()["state"], "思考")
        p.wait(timeout=20)

    def test_old_record_without_phase_still_labelled(self):
        import server
        self.assertEqual(server.run_state({"status": "运行中", "started": dispatch.now_iso()}), "启动中")
        self.assertEqual(server.run_state({"status": "运行中", "started": dispatch.now_iso(), "last_at": dispatch.now_iso()}), "思考")


class TestSmallFixes(unittest.TestCase):
    def test_literal_newline_in_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "I001.md"
            card.write_text("# 卡\n\n## 问题\n模板\n\n## 发言\n", encoding="utf-8")
            dispatch.fill_card(card, r"第一行\n第二行", r"约定一\n约定二")
            text = card.read_text(encoding="utf-8")
        self.assertIn("第一行\n第二行", text)
        self.assertIn("约定一\n约定二", text)
        self.assertNotIn("\\n", text)

    def test_protocol_has_no_member_wake_notation(self):
        text = (HERE.parent / "src" / "workbench" / "collab" / "协议.md").read_text(encoding="utf-8")
        self.assertNotIn("要谁接着回答写", text)
        self.assertNotIn("看不到别人的观点", text)


if __name__ == "__main__":
    unittest.main()
