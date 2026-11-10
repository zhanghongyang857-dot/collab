"""collab/内部/ 的位置：新项目直接在这里，旧项目用 init.sh tidy 搬过来。全部用临时目录。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "core" / "init.sh"
sys.path.insert(0, str(ROOT / "src" / "core"))
import check  # noqa: E402
import flow  # noqa: E402

NAMES = ("流转", "流程", "运行记录")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proj = self.tmp / "p"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def init(self, *args):
        return subprocess.run(["bash", str(INIT), *args], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.tmp), "COLLAB_TEAM": str(self.tmp / "无")})

    def new(self):
        r = self.init("new", str(self.proj), "--no-now")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.proj / "collab"


class TestNewProject(Base):
    def test_new_project_uses_internal_folder(self):
        c = self.new()
        for n in NAMES:
            self.assertTrue((c / "内部" / n).is_dir(), n)
            self.assertFalse((c / n).exists(), n)

    def test_flow_writes_under_internal(self):
        c = self.new()
        p = flow.Project(self.proj)
        self.assertEqual(p.flow_dir, (c / "内部" / "流转").resolve())
        self.assertEqual(p.proc_dir, (c / "内部" / "流程").resolve())


class TestOldProjectStaysOld(Base):
    def test_flow_does_not_turn_old_project_into_new_structure(self):
        c = self.new()
        shutil.rmtree(c / "内部")
        for args in (["渲染"], ["记", "T001", "进展", "--说明", "x"]):
            r = subprocess.run([sys.executable, str(ROOT / "src" / "core" / "flow.py"), "--project", str(self.proj), *args], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertFalse((c / "内部" / "流转").exists(), args)


class TestTidy(Base):
    def old_layout(self):
        c = self.new()
        shutil.rmtree(c / "内部")
        for n in NAMES:
            (c / n).mkdir()
            (c / n / "x.json").write_text(n, encoding="utf-8")
        return c

    def test_moves_old_folders_and_keeps_content(self):
        c = self.old_layout()
        r = self.init("tidy", str(self.proj))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in NAMES:
            self.assertFalse((c / n).exists())
            self.assertEqual((c / "内部" / n / "x.json").read_text(encoding="utf-8"), n)

    def test_second_run_changes_nothing(self):
        c = self.old_layout()
        self.init("tidy", str(self.proj))
        r = self.init("tidy", str(self.proj))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((c / "内部" / "流转" / "x.json").exists())

    def test_empty_template_folder_does_not_block(self):
        c = self.new()  # 模板的 内部/运行记录 只有 .gitkeep
        (c / "运行记录").mkdir()
        (c / "运行记录" / "x.json").write_text("旧", encoding="utf-8")
        self.init("tidy", str(self.proj))
        self.assertEqual((c / "内部" / "运行记录" / "x.json").read_text(encoding="utf-8"), "旧")

    def test_refuses_to_overwrite_when_both_have_content(self):
        c = self.new()
        (c / "运行记录").mkdir()
        (c / "运行记录" / "old.json").write_text("旧", encoding="utf-8")
        (c / "内部" / "运行记录" / "new.json").write_text("新", encoding="utf-8")
        r = self.init("tidy", str(self.proj))
        self.assertIn("手动合并", r.stdout)
        self.assertTrue((c / "运行记录" / "old.json").exists())
        self.assertTrue((c / "内部" / "运行记录" / "new.json").exists())

    def test_old_project_gets_a_warning_and_tidy_clears_it(self):
        self.old_layout()
        text = " ".join(str(i) for i in check.check(self.proj))
        self.assertIn("旧位置", text)
        self.init("tidy", str(self.proj))
        text = " ".join(str(i) for i in check.check(self.proj))
        self.assertNotIn("旧位置", text)


if __name__ == "__main__":
    unittest.main()
