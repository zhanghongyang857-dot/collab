"""G015 第一轮：叫得到、接得上。启动环境（PATH、认证变量）、失败不推进「读到」、补叫带上错过的发言、启动检查。

用假成员 fake_member.py，不调用模型；运行：python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src" / "core"))
sys.path.insert(0, str(HERE))
import dispatch  # noqa: E402
import flow  # noqa: E402
from test_flow import Base, Sim  # noqa: E402
from test_issue import meeting, say, state  # noqa: E402

DISPATCH = HERE.parent / "src" / "core" / "dispatch.py"
FAKE = HERE / "fake_member.py"


class TestMemberEnv(unittest.TestCase):
    def setUp(self):
        dispatch._LOGIN_PATH = None
        self.addCleanup(setattr, dispatch, "_LOGIN_PATH", None)

    def test_strips_desktop_variables(self):
        dirty = {"PATH": "/usr/bin:/bin", "HOME": "/h", "ANTHROPIC_AUTH_TOKEN": "x", "ANTHROPIC_BASE_URL": "y",
                 "CLAUDE_CODE_ENTRYPOINT": "z", "CLAUDE_CODE_SSE_PORT": "1", "CLAUDECODE": "1", "CLAUDE_PID": "2",
                 "CLAUDE_AGENT_SDK_VERSION": "x", "CLAUDE_AGENT_SDK_MCP_NO_PREFIX": "1", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR": "1",
                 "CLAUDE_CONFIG_DIR": "/keep", "COLLAB_TEAM": "/t"}
        with mock.patch.dict(os.environ, dirty, clear=True), mock.patch.object(dispatch, "login_path", return_value="/a:/b"):
            env = dispatch.member_env({"COLLAB_ACTOR": "codex"})
        self.assertEqual([k for k in env if k.startswith(("ANTHROPIC", "CLAUDE")) and k != "CLAUDE_CONFIG_DIR"], [], "真实桌面版变量名也要清掉")
        self.assertEqual((env["CLAUDE_CONFIG_DIR"], env["COLLAB_TEAM"], env["COLLAB_ACTOR"], env["PATH"]), ("/keep", "/t", "codex", "/a:/b"))

    def test_path_adds_homebrew_and_newest_nvm(self):
        with tempfile.TemporaryDirectory() as tmp:
            for v in ("v9.11.2", "v24.15.0", "v20.1.0"):
                (Path(tmp) / "versions" / "node" / v / "bin").mkdir(parents=True)
            fake_shell = Path(tmp) / "sh"
            fake_shell.write_text("#!/bin/sh\nexit 1\n")
            fake_shell.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "NVM_DIR": tmp, "SHELL": str(fake_shell)}):
                parts = dispatch.login_path().split(":")
        self.assertEqual(parts[:2], ["/usr/bin", "/bin"])
        nvm = [p for p in parts if "versions/node" in p]
        self.assertEqual([Path(p).parent.name for p in nvm], ["v24.15.0", "v20.1.0", "v9.11.2"], "不写死版本，新版本在前")
        self.assertIn("/opt/homebrew/bin", parts)

    def test_login_shell_path_comes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            sh = Path(tmp) / "sh"
            sh.write_text('#!/bin/sh\nprintf "noise\\n__PATH__/login/bin:/usr/bin\\n"\n')
            sh.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "SHELL": str(sh), "NVM_DIR": tmp}):
                parts = dispatch.login_path().split(":")
        self.assertEqual(parts[:3], ["/login/bin", "/usr/bin", "/bin"])

    def test_minimal_launchd_path_still_finds_commands(self):
        """看板服务的 PATH 只有系统目录：启动环境里仍要找得到 claude、dsh（本机有才测）。"""
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}):
            env = dispatch.member_env()
        for cmd in ("claude", "dsh"):
            real = subprocess.run(["bash", "-lc", f"command -v {cmd}"], capture_output=True, text=True).stdout.strip()
            if real:
                self.assertTrue(dispatch.which(cmd, env), f"{cmd} 在登录环境里有，启动环境却找不到")


class Room(Base):
    """临时项目 + 假成员班子；子类里 self.sim 是模拟时钟。"""

    def setUp(self):
        super().setUp()
        team = self.root / "team"
        team.mkdir()
        cmd = lambda name: {"派活名": name, "可用": "✓", "事件解析": "claude",
                            "新会话命令": [sys.executable, str(FAKE), name, "{prompt}"],
                            "续接命令": [sys.executable, str(FAKE), name, "{prompt}", "--resume", "{session}"]}
        (team / "班子.json").write_text(json.dumps({"成员": [cmd("codex"), cmd("deepseek")]}, ensure_ascii=False), encoding="utf-8")
        self.fail_dir = self.root / "fail"
        self.fail_dir.mkdir()
        self.env_dir = self.root / "envs"
        self.env_dir.mkdir()
        self.env = dict(os.environ, COLLAB_TEAM=str(team), FAKE_FAIL_DIR=str(self.fail_dir), FAKE_ENV_DIR=str(self.env_dir),
                        ANTHROPIC_AUTH_TOKEN="bad-token", CLAUDE_CODE_ENTRYPOINT="desktop", CLAUDECODE="1",
                        CLAUDE_AGENT_SDK_VERSION="x", CLAUDE_PREVIEW_CLASSIFIER_FLOOR="1")
        for k in ("FLOW_NOW", "COLLAB_ACTOR", "COLLAB_RUN", "COLLAB_WRITER", "COLLAB_FLOW"):
            self.env.pop(k, None)
        self.sim = Sim(self.root / "p")
        self.runs_dir = self.root / "p" / "collab" / "内部" / "运行记录"

    def dispatch(self, *args):
        return subprocess.run([sys.executable, str(DISPATCH), "--project", str(self.root / "p"), *args],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def runs(self, member=None):
        rs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(self.runs_dir.glob("*.json"))]
        return [r for r in rs if member in (None, r["member"])]

    def msgs(self, obj):
        return [e for e in state(self.sim, obj)["事件"] if e["边"] in flow.MESSAGES]


class TestFailureAndRedeliver(Room):
    def test_failed_run_does_not_advance_read_and_redeliver_brings_missed(self):
        sim = self.sim
        i = meeting(sim)
        sim.log(i, "开始", "总裁", 写入者="看板")
        os.environ.pop("FLOW_NOW", None)
        say(sim, i, "总裁", "@codex 先说立场", 点名=["codex"])
        os.environ.pop("FLOW_NOW", None)
        self.assertEqual(self.dispatch("meet", i, "--wake", "codex").returncode, 0)
        first = self.runs("codex")
        self.assertEqual([r["status"] for r in first], ["完成"])
        self.assertIn("读到", first[0])
        # codex 再被点名，但这次叫不到（未登录）
        os.environ.pop("FLOW_NOW", None)
        q2 = say(sim, i, "总裁", "@codex 追问一个细节", 点名=["codex"])
        (self.fail_dir / "codex").write_text("x")
        os.environ.pop("FLOW_NOW", None)
        self.dispatch("meet", i, "--wake", "codex")
        failed = self.runs("codex")[-1]
        self.assertEqual(failed["status"], "失败")
        self.assertIn("Not logged in", failed["error"])
        self.assertNotIn("读到", failed, "失败的运行不推进读到")
        self.assertEqual(len([m for m in self.msgs(i) if m["发起"] == "codex"]), 1, "失败不写发言")
        # 失败期间别人又说了话
        os.environ.pop("FLOW_NOW", None)
        say(sim, i, "deepseek", "我补充一点：缓存要考虑失效")
        # 补叫：登录恢复后再叫，能收到追问和错过的发言
        (self.fail_dir / "codex").unlink()
        os.environ.pop("FLOW_NOW", None)
        r = self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        again = self.runs("codex")[-1]
        self.assertEqual(again["status"], "完成", again.get("error"))
        self.assertIn("追问一个细节", again["prompt"])
        self.assertIn("缓存要考虑失效", again["prompt"], "错过的发言要补上")
        self.assertIn("上次叫你", again["prompt"])
        self.assertGreater(again["读到"], first[0]["读到"])
        self.assertEqual(again["session"], first[0]["session"], "失败的运行不当作可续接的会话，仍接上次成功的那个")
        self.assertEqual(len([m for m in self.msgs(i) if m["发起"] == "codex"]), 2)

    def test_old_failed_run_with_read_mark_is_ignored(self):
        """I001 留下的旧记录：失败的运行也带了「读到」，现在不再当作已读。"""
        sim = self.sim
        i = meeting(sim)
        sim.log(i, "开始", "总裁", 写入者="看板")
        os.environ.pop("FLOW_NOW", None)
        say(sim, i, "总裁", "@codex 说", 点名=["codex"])
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        old = {"run": f"{i}-01", "task": i, "seat": "与会", "member": "codex", "status": "失败", "session": "", "读到": 999,
               "started": "2026-11-01T09:00:00+08:00", "error": "Not logged in"}
        (self.runs_dir / f"{i}-01.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        r = self.dispatch("meet", i, "--wake", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([x["status"] for x in self.runs("codex")], ["失败", "完成"])

    def test_dirty_environment_is_cleaned_for_members(self):
        sim = self.sim
        i = meeting(sim)
        sim.log(i, "开始", "总裁", 写入者="看板")
        os.environ.pop("FLOW_NOW", None)
        say(sim, i, "总裁", "@codex 说", 点名=["codex"])
        self.assertEqual(self.dispatch("meet", i, "--wake", "codex").returncode, 0)
        got = json.loads((self.env_dir / "codex.env").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual([k for k in got if k.startswith(("ANTHROPIC", "CLAUDE")) and k != "CLAUDE_CONFIG_DIR"], [], "桌面版的认证变量不能传给成员")

    def test_task_dispatch_also_cleans_environment(self):
        sim = self.sim
        g = sim.new("目标", 类型="调研", 标题="环境")
        sim.log(g, "提交", 说明="两阶段")
        sim.log(g, "批准", "总裁", 依据="总裁：批准", 人选={1: ["codex"], 2: ["deepseek"]})
        t = sim.new("任务", 目标=g, 阶段=1, 标题="检索")
        os.environ.pop("FLOW_NOW", None)
        r = self.dispatch("start", t, "执行", "codex", "开工")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads((self.env_dir / "codex.env").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual([k for k in got if k.startswith(("ANTHROPIC", "CLAUDE")) and k != "CLAUDE_CONFIG_DIR"], [])


class TestCheckMember(Room):
    def test_check_ok_and_failure(self):
        r = self.dispatch("check", "codex", "deepseek")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("就绪", r.stdout)
        (self.fail_dir / "deepseek").write_text("x")
        r = self.dispatch("check", "codex", "deepseek")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Not logged in", r.stdout)
        self.assertEqual(self.runs(), [], "启动检查不写运行记录")

    def test_missing_command_is_reported(self):
        cfg = {"parser": "claude", "available": "✓", "start": ["no-such-cli-xyz", "{prompt}"]}
        res = dispatch.check_member("x", cfg, timeout=5)
        self.assertFalse(res["ok"])
        self.assertIn("找不到命令 no-such-cli-xyz", res["error"])

    def test_unavailable_member_is_skipped(self):
        res = dispatch.check_member("x", {"parser": "claude", "available": "✗（不用了）", "start": ["x"]})
        self.assertTrue(res["skipped"])


if __name__ == "__main__":
    unittest.main()
