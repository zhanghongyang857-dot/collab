"""G015 第二轮：搭会议室、加人和前情、@ 规则。假成员，不调用模型。"""
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE.parent / "src" / "board"))
sys.path.insert(0, str(HERE))
import flow  # noqa: E402
from test_issue import meeting, say, state  # noqa: E402
from test_wake import Room  # noqa: E402


class TestFeed(Room):
    def test_first_speech_sees_public_before_the_call_only(self):
        sim = self.sim
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        say(sim, i, "codex", "codex 的公开立场")
        say(sim, i, "codex", "codex 的私下话", 私下=True)
        say(sim, i, "总裁", "@deepseek @claude 这句话叫两个人", 点名=["deepseek"])
        say(sim, i, "codex", "叫醒之后 codex 又说了一句")
        text, man = flow.context(sim.proj, i, "deepseek")
        self.assertIn("codex 的公开立场", text, "之前的公开发言都能看到")
        self.assertIn("这句话叫两个人", text)
        self.assertNotIn("codex 的私下话", text, "私下发言看不到")
        self.assertNotIn("叫醒之后 codex 又说了一句", text, "同一句话叫醒的人互相独立，之后的不给")
        call_seq = [e for e in state(sim, i)["事件"] if "这句话叫两个人" in e.get("正文", "")][0]["项目序"]
        self.assertEqual(man[-1]["读到"], call_seq, "读到停在叫醒它的那句话，之后的下次补")
        later, _ = flow.context(sim.proj, i, "deepseek", since=call_seq)
        self.assertIn("叫醒之后 codex 又说了一句", later)

    def test_joined_without_call_sees_all_public(self):
        sim = self.sim
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        say(sim, i, "codex", "公开A")
        say(sim, i, "codex", "私下B内容", 私下=True)
        text, _ = flow.context(sim.proj, i, "deepseek")
        self.assertIn("公开A", text)
        self.assertNotIn("私下B内容", text)


class TestRoom(Room):
    def room(self, *extra):
        os.environ.pop("FLOW_NOW", None)
        return self.dispatch("room", "--标题", "缓存方案", "--依据", "总裁：开个会", "--与会", "codex:实现", "deepseek:风险",
                             "--问题", "- 要决定什么：要不要缓存", "--开场", "只想听利弊；资料在 docs/，可以看，不必须看。", *extra)

    def test_room_opens_directly_and_failure_blocks(self):
        (self.fail_dir / "deepseek").write_text("x")
        r = self.room()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("deepseek", r.stdout)
        self.assertIn("没有开会", r.stdout)
        st = state(self.sim, "I001")
        self.assertEqual(st["状态"], "起草", "有人没就绪不进讨论中")
        ready = json.loads((self.runs_dir / "I001.到场.txt").read_text(encoding="utf-8"))
        self.assertTrue(ready["members"]["codex"]["ok"])
        self.assertFalse(ready["members"]["deepseek"]["ok"])
        self.assertIn("Not logged in", ready["members"]["deepseek"]["error"])
        (self.fail_dir / "deepseek").unlink()
        os.environ.pop("FLOW_NOW", None)
        r = self.dispatch("ready", "I001", "--port", "3199")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state(self.sim, "I001")["状态"], "讨论中")
        self.assertRegex(r.stdout, r"http://127\.0\.0\.1:3199/p/[0-9a-f]{8}/meet/I001")
        self.assertEqual(self.runs(), [], "启动检查不留运行记录，也没人开口")
        self.assertEqual(self.msgs("I001"), [])

    def test_opening_agreement_reaches_members(self):
        r = self.room()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = state(self.sim, "I001")
        self.assertEqual((st["状态"], st["持有人"]), ("讨论中", "总裁"))
        text, _ = flow.context(self.sim.proj, "I001", "codex")
        self.assertIn("## 开场约定", text)
        self.assertIn("只想听利弊", text)
        self.assertIn("要不要缓存", text)
        self.assertIn("不会叫醒任何人", text, "告诉成员 @ 不叫人")


class TestAddAttendee(Room):
    def test_add_member_midway(self):
        import server  # noqa: E402
        sim = self.sim
        i = meeting(sim)
        sim.log(i, "开始", "总裁")
        os.environ["COLLAB_TEAM"] = self.env["COLLAB_TEAM"]
        self.addCleanup(os.environ.pop, "COLLAB_TEAM", None)
        os.environ.pop("FLOW_NOW", None)
        say(sim, i, "codex", "公开立场")
        say(sim, i, "codex", "机密内幕XYZ", 私下=True)
        proj = flow.Project(self.root / "p")
        pool = {m["name"]: m for m in server.team_pool(proj)}
        self.assertTrue(pool["codex"]["ok"])
        with self.assertRaises(flow.FlowError):
            server.add_attendees(proj, i, ["codex"], "")  # 已在名单里
        with self.assertRaises(flow.FlowError):
            server.add_attendees(proj, i, ["不存在"], "")
        # 名单外的可用成员：用另一个班子成员 claude（花名册里有，班子配置里没写时按可用算）
        res = server.add_attendees(proj, i, ["claude"], "旁观")
        self.assertEqual(res["added"], ["claude"])
        self.assertEqual([a["成员"] for a in state(sim, i)["与会"]], ["codex", "deepseek", "claude"])
        text, _ = flow.context(proj, i, "claude")
        self.assertIn("公开立场", text, "中途加入的人看得到之前的公开发言")
        self.assertNotIn("机密内幕XYZ", text, "看不到私下发言")


if __name__ == "__main__":
    unittest.main()
