"""init.sh protocol：协议、模板、PROGRESS 加载地图一起更新，别的内容不动。全部用临时目录。"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "core" / "init.sh"
WB = ROOT / "src" / "workbench" / "zh" / "collab"
MAP = re.compile(r"(?ms)^## 加载地图[ \t]*\n.*?(?=^## |\Z)")


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proj = self.tmp / "p"
        self.assertEqual(self.init("new", str(self.proj), "--no-now").returncode, 0)
        self.col = self.proj / "collab"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def init(self, *args):
        return subprocess.run(["bash", str(INIT), *args], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.tmp), "COLLAB_TEAM": str(self.tmp / "无"), "COLLAB_LANG": "zh"})

    def age(self):
        """把项目改成落后于工作台的样子，并写入项目自己的内容。"""
        for tpl in WB.glob("*/_template.md"):
            (self.col / tpl.relative_to(WB)).write_text("旧模板\n", encoding="utf-8")
        p = self.col / "protocol.md"
        p.write_text(p.read_text(encoding="utf-8").replace("## 1. 总则", "## 1. 旧总则")
                     .rstrip("\n") + "\n- 项目自己的规矩\n", encoding="utf-8")
        q = self.col / "PROGRESS.md"
        t = q.read_text(encoding="utf-8")
        t = MAP.sub("## 加载地图\n旧地图\n", t).replace("## ▶ 下一步\n", "## ▶ 下一步\n项目自己的下一步\n", 1)
        q.write_text(t, encoding="utf-8")

    def test_updates_all_and_keeps_project_content(self):
        self.age()
        r = self.init("protocol", str(self.proj))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for tpl in WB.glob("*/_template.md"):
            self.assertEqual((self.col / tpl.relative_to(WB)).read_bytes(), tpl.read_bytes(), tpl)
        got = (self.col / "PROGRESS.md").read_text(encoding="utf-8")
        self.assertEqual(MAP.search(got).group(0), MAP.search((WB / "PROGRESS.md").read_text(encoding="utf-8")).group(0))
        self.assertIn("项目自己的下一步", got)
        self.assertNotIn("旧地图", got)
        proto = (self.col / "protocol.md").read_text(encoding="utf-8")
        self.assertIn("## 1. 总则", proto)
        self.assertIn("项目自己的规矩", proto)

    def test_progress_without_map_is_left_alone(self):
        q = self.col / "PROGRESS.md"
        t = MAP.sub("", q.read_text(encoding="utf-8"))
        q.write_text(t, encoding="utf-8")
        self.assertEqual(self.init("protocol", str(self.proj)).returncode, 0)
        self.assertEqual(q.read_text(encoding="utf-8"), t)

    def test_rerun_changes_nothing(self):
        self.assertEqual(self.init("protocol", str(self.proj)).returncode, 0)
        first = {f: f.read_bytes() for f in self.col.rglob("*.md")}
        self.assertEqual(self.init("protocol", str(self.proj)).returncode, 0)
        self.assertEqual({f: f.read_bytes() for f in self.col.rglob("*.md")}, first)


if __name__ == "__main__":
    unittest.main()
