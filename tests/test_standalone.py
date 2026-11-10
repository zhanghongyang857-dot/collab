"""只装工作台就能看项目看板（G037）：没有 NOW、没有班子的临时 HOME 里走完 发布核心 → init.sh new → 启动看板；
另有启用了 NOW 时首页、项目发现、任务表登记都不变的用例。全部用临时目录里的虚构数据。"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PUBLISH = SRC / "core" / "publish.sh"
sys.path.insert(0, str(SRC / "core"))
import registry  # noqa: E402

CLEAR = ("NOW_PATH", "NOW_DATA_DIR", "COLLAB_NOW_DIR", "COLLAB_PROJECTS", "COLLAB_TEAM", "BOARD_PORT", "BOARD_NOW_DIR",
         "COLLAB_SYSTEM")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.port = free_port()
        self.env = {k: v for k, v in os.environ.items() if k not in CLEAR}
        self.env.update(HOME=str(self.home), BOARD_PORT=str(self.port))
        self.srv = None

    def tearDown(self):
        if self.srv:
            self.srv.terminate()
            self.srv.wait(5)
            self.srv.stderr.close()
        shutil.rmtree(self.tmp)

    def run_(self, *cmd, env=None):
        return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env or self.env)

    def publish_core(self, dest: Path) -> Path:
        r = self.run_("bash", PUBLISH, "--dirty", "--core", dest)  # --dirty：测试不依赖改动已经提交
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return dest

    def serve(self, kit: Path, *args):
        self.srv = subprocess.Popen(["python3", str(kit / "board" / "server.py"), "--port", str(self.port), *map(str, args)],
                                    env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                self.get("/api/home")
                return
            except OSError:
                time.sleep(0.1)
        self.fail("看板没有起来：" + self.srv.stderr.read().decode())

    def get(self, path: str):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=10) as r:
            body = r.read().decode("utf-8")
        return json.loads(body) if path.startswith("/api/") else body


@unittest.skipIf(subprocess.run(["git", "-C", str(ROOT), "rev-parse"], capture_output=True).returncode, "不在 git 仓库里")
class TestWithoutNow(Base):
    def test_quickstart_three_steps(self):
        # 1. 发布核心
        kit = self.publish_core(self.home / "批红" / "系统")
        init = kit / "core" / "init.sh"
        # 2. 给项目装工作台：没有 NOW、没有班子，也不用 --no-now
        proj = self.home / "项目" / "示例"
        r = self.run_("bash", init, "new", proj, "-n", "示例")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NOW 未启用，项目已登记", r.stdout)
        url = "http://127.0.0.1:%d/p/%s" % (self.port, registry.project_id(proj))
        self.assertIn(url, r.stdout)
        reg = json.loads((self.home / "批红" / "projects.json").read_text(encoding="utf-8"))
        self.assertEqual(reg, {"projects": [{"name": "示例", "root": str(proj)}]})
        self.assertNotIn("← NOW", (proj / "collab" / "PROGRESS.md").read_text(encoding="utf-8"))
        self.assertFalse((self.home / "Desktop").exists())
        # 看板没运行时 open 给出启动提示
        r = self.run_("bash", init, "open", proj, "--print")
        self.assertEqual(r.returncode, 1)
        self.assertIn(url, r.stdout)
        self.assertIn("看板没在运行", r.stdout)
        # 3. 开看板：首页是项目列表，项目页 API 正常
        self.serve(kit)
        self.assertEqual(self.get("/api/home"), {"now": False})
        self.assertIn("/static/projects.js", self.get("/"))
        self.assertIn("/static/projects.js", self.get("/projects"))
        self.assertIn("/static/projects.js", self.get("/now"))
        listed = self.get("/api/projects")
        self.assertEqual([(p["name"], p["root"], p["source"]) for p in listed], [("示例", str(proj), "registry")])
        pid = listed[0]["id"]
        self.assertIn("/static/project.js", self.get("/p/" + pid))
        data = self.get("/api/p/" + pid)
        self.assertEqual((data["id"], data["root"]), (pid, str(proj)))
        self.assertIn("view", data)
        self.assertFalse([c for c in data["check"] if c["level"] == "error"], data["check"])
        self.assertIn("/api/projects", self.get("/static/projects.js"))
        r = self.run_("bash", init, "open", proj, "--print")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, url), r.stdout + r.stderr)
        # 注销后从列表消失，再登记回来
        r = self.run_("bash", init, "unregister", proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("已从看板登记表移除", r.stdout)
        self.assertEqual(self.get("/api/projects"), [])
        r = self.run_("bash", init, "register", proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.get("/api/projects")), 1)

    def test_no_now_defaults(self):
        kit = self.publish_core(self.home / "批红" / "系统")
        init = kit / "core" / "init.sh"
        r = self.run_("bash", init, "now")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("要写目录", r.stdout)
        r = self.run_("bash", init, "module", "list")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("没启用 NOW", r.stderr)
        self.assertFalse((self.home / "Desktop").exists())


class TestRegistry(Base):
    def test_dev_kit_does_not_register(self):
        kit = self.tmp / "src"
        kit.mkdir()
        os.environ.pop("COLLAB_PROJECTS", None)
        self.assertIsNone(registry.path(kit))
        self.assertEqual(registry.add(kit, self.tmp, "x"), "off")
        (kit / "版本.txt").write_text("提交：x\n", encoding="utf-8")
        self.assertEqual(registry.path(kit), self.tmp / "projects.json")

    def test_add_remove_dedupe(self):
        kit = self.tmp / "系统"
        kit.mkdir()
        (kit / "版本.txt").write_text("提交：x\n", encoding="utf-8")
        proj = self.tmp / "p"
        self.assertEqual(registry.add(kit, proj, "甲"), "added")
        self.assertEqual(registry.add(kit, proj / ".." / "p", "乙"), "exists")
        self.assertEqual(registry.load(registry.path(kit)), [{"name": "甲", "root": str(proj)}])
        self.assertEqual(registry.remove(kit, proj), "removed")
        self.assertEqual(registry.remove(kit, proj), "missing")

    def test_service_config_of_other_kit_is_ignored(self):
        """开发版工具包不会用发布版常驻配置里的 NOW，免得测试写进真的 NOW 任务表。"""
        now = self.tmp / "NOW"
        now.mkdir()
        (now / "config.json").write_text("{}", encoding="utf-8")
        conf = self.home / "Library" / "Application Support" / "ai-company-board" / "config"
        conf.parent.mkdir(parents=True)
        conf.write_text("ROOT=%s\nNOW_DIR=%s\nPORT=3999\n" % (self.tmp / "别的", now), encoding="utf-8")
        code = "import sys; sys.path.insert(0, %r); import registry; from pathlib import Path; print(registry.now_md(Path(%r)) or '')"
        r = self.run_("python3", "-c", code % (str(SRC / "core"), str(self.tmp / "src")))
        self.assertEqual(r.stdout.strip(), "")
        conf.write_text("ROOT=%s\nNOW_DIR=%s\n" % (self.tmp / "src", now), encoding="utf-8")
        r = self.run_("python3", "-c", code % (str(SRC / "core"), str(self.tmp / "src")))
        self.assertEqual(r.stdout.strip(), str(self.tmp / "NOW.md"))


@unittest.skipIf(subprocess.run(["git", "-C", str(ROOT), "rev-parse"], capture_output=True).returncode, "不在 git 仓库里")
class TestWithNow(Base):
    def make_now(self, init: Path, where: Path):
        r = self.run_("bash", init, "now", where)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_now_path_unchanged(self):
        """开发版工具包 + NOW_PATH：和改前一样加进 NOW 任务表，/ 是 NOW 页，项目从 NOW 表发现。"""
        init = SRC / "core" / "init.sh"
        desk = self.tmp / "desk"
        self.make_now(init, desk)
        proj = self.tmp / "proj"
        env = {**self.env, "NOW_PATH": str(desk / "NOW.md")}
        r = self.run_("bash", init, "new", proj, "-n", "甲", env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NOW 任务表", r.stdout)
        self.assertIn("开发版工具包不登记项目", r.stdout)
        self.assertIn("| [甲](<../proj/collab/PROGRESS.md>) |", (desk / "NOW.md").read_text(encoding="utf-8"))
        self.assertIn("[← NOW](../../desk/NOW.md)", (proj / "collab" / "PROGRESS.md").read_text(encoding="utf-8"))
        self.serve(SRC, "--now-dir", desk / "NOW")
        self.assertEqual(self.get("/api/home"), {"now": True})
        self.assertIn("/static/now-inject.js", self.get("/"))
        self.assertIn("/static/now-inject.js", self.get("/now"))
        self.assertIn("/static/projects.js", self.get("/projects"))
        listed = self.get("/api/projects")
        self.assertEqual([(p["name"], p["source"], p["state"]) for p in listed], [("甲", "now", "进行中")])
        self.assertEqual(self.get("/api/p/" + listed[0]["id"])["root"], str(proj))
        # unregister 照旧移到「已完成」，项目仍能从已完成表找到
        r = self.run_("bash", init, "unregister", proj, "-m", "做完了", env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("已完成", (desk / "NOW" / "已完成.md").read_text(encoding="utf-8"))
        self.assertEqual([p["source"] for p in self.get("/api/projects")], ["done"])

    def test_kit_beside_now(self):
        """本机用法：工具包发布在 NOW/系统/，不设 NOW_PATH 也找到 NOW；登记表和 NOW 表都有的项目只列一次。"""
        base = self.home / "Notes"
        kit = self.publish_core(base / "NOW" / "系统")
        init = kit / "core" / "init.sh"
        self.make_now(init, base)
        cfg = json.loads((base / "NOW" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("now_md", "../NOW.md"), "../NOW.md")
        proj = self.home / "proj"
        r = self.run_("bash", init, "new", proj, "-n", "乙")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("NOW 未启用", r.stdout)
        self.assertIn("| [乙](<../proj/collab/PROGRESS.md>) |", (base / "NOW.md").read_text(encoding="utf-8"))
        self.assertTrue((base / "NOW" / "projects.json").exists())
        self.serve(kit)  # 不给 --now-dir：工具包旁边的 NOW
        self.assertIn("/static/now-inject.js", self.get("/"))
        listed = self.get("/api/projects")
        self.assertEqual([(p["name"], p["source"]) for p in listed], [("乙", "now")])
        r = self.run_("bash", init, "open", proj, "--print")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
