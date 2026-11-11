"""开发版工具包不能写自己仓库的账本和模板；发布版、demo、其他项目不受影响。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "src" / "core"
WORKBENCH = ROOT / "src" / "workbench" / "zh"
sys.path.insert(0, str(CORE))
import flow  # noqa: E402


class TestRefusal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.repo = self.tmp / "repo"
        self.kit = self.repo / "src"
        (self.kit / "workbench").mkdir(parents=True)
        patcher = mock.patch.object(flow, "TOOLKIT", self.kit)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_refuses_own_repo_and_template(self):
        self.assertTrue(flow.dev_write_refusal(self.repo))
        self.assertTrue(flow.dev_write_refusal(self.kit))
        self.assertTrue(flow.dev_write_refusal(self.kit / "workbench"))

    def test_allows_demo_and_other_projects(self):
        self.assertIsNone(flow.dev_write_refusal(self.repo / "demo" / "万历新政"))
        self.assertIsNone(flow.dev_write_refusal(self.tmp / "别的项目"))

    def test_published_copy_is_not_limited(self):
        (self.kit / "VERSION.txt").write_text("提交：abc\n", encoding="utf-8")
        self.assertIsNone(flow.dev_write_refusal(self.repo))

    def test_lock_refuses_before_touching_ledger(self):
        proj = flow.Project(self.repo)
        with self.assertRaises(flow.FlowError):
            with flow.locked(proj):
                self.fail("不该拿到写锁")
        self.assertFalse((self.repo / "collab").exists())


class TestCommandLine(unittest.TestCase):
    """真实入口：src/ 里的脚本对 src/workbench 写入，直接被拒，什么都不留下。"""

    def run_tool(self, script, *args):
        return subprocess.run([sys.executable, str(CORE / script), "--project", str(WORKBENCH), *args],
                              capture_output=True, text=True)

    def test_flow_refuses(self):
        r = self.run_tool("flow.py", "渲染")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("开发版工具包", r.stdout + r.stderr)
        self.assertFalse((WORKBENCH / "collab" / "internal" / "flow" / ".lock").exists())

    def test_dispatch_refuses_writes_but_not_reads(self):
        r = self.run_tool("dispatch.py", "stop", "--all")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("开发版工具包", r.stderr)
        self.assertEqual(self.run_tool("dispatch.py", "list").returncode, 0)


if __name__ == "__main__":
    unittest.main()
