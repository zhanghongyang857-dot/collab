"""看板静态导出（src/board/export_static.py）：拿演示第五回导出，页面、数据、文件都在，链接是相对的，没有本机路径。"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "board"))
sys.path.insert(0, str(ROOT / "demo"))
import build  # noqa: E402
import export_static  # noqa: E402


class TestExportStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        proj = build.build(Path(cls.tmp.name) / "演示", 5)
        cls.out = Path(cls.tmp.name) / "站"
        cls.r = export_static.export(proj, cls.out, "15730301", team=ROOT / "demo",
                                     extra={"chapter": 5, "home": "../"}, extra_js=["demo-bar.js"])
        cls.proj = proj

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_pages_and_data(self):
        o = self.out
        for rel in ("p/15730301/index.html", "p/15730301/archive/index.html", "team/index.html",
                    "api/p/15730301.json", "api/p/15730301/archive.json", "api/team.json", "static/project.js", "static/board.css"):
            self.assertTrue((o / rel).exists(), rel)
        self.assertEqual(self.r["issues"], ["I001", "I002", "I003"])
        for i in self.r["issues"]:
            d = json.loads((o / f"api/p/15730301/meet/{i}.json").read_text(encoding="utf-8"))
            self.assertEqual(d["issue"]["id"], i)
            self.assertEqual(d["project"]["name"], "万历新政")  # 不用临时目录名
        d = json.loads((o / "api/p/15730301.json").read_text(encoding="utf-8"))
        self.assertEqual(d["id"], "15730301")
        self.assertTrue(d["view"]["goals"])

    def test_pages_are_relative_and_static(self):
        page = (self.out / "p/15730301/meet/I003/index.html").read_text(encoding="utf-8")
        conf = json.loads(re.search(r"window\.BOARD_STATIC = (\{.*?\});", page).group(1))
        self.assertEqual((conf["base"], conf["issue"], conf["chapter"]), ("../../../..", "I003", 5))
        self.assertIn('href="../../../../static/board.css"', page)
        self.assertIn('src="../../../../static/demo-bar.js"', page)
        self.assertIn('class="static"', page)
        self.assertNotIn('"/static/', page)
        proj = (self.out / "p/15730301/index.html").read_text(encoding="utf-8")
        self.assertIn('href="../../team/"', proj)
        self.assertIn('href="../../../"', proj)  # 「← NOW」去 home
        self.assertNotIn("/talent", proj)

    def test_file_links_point_into_export(self):
        text = (self.out / "api/p/15730301.json").read_text(encoding="utf-8")
        self.assertNotIn("file://", text)
        links = set(re.findall(r"\{\{FILES\}\}(/[^\"\\\\]+?\.html)", text))
        self.assertTrue(links)
        for l in links:
            from urllib.parse import unquote
            self.assertTrue((self.out / "files" / unquote(l).lstrip("/")).exists(), l)

    def test_no_local_paths(self):
        leaks = (str(self.proj), str(ROOT), str(Path.home()))
        for f in self.out.rglob("*"):
            if f.suffix in (".json", ".html"):
                t = f.read_text(encoding="utf-8")
                self.assertFalse(any(x in t for x in leaks), f)


if __name__ == "__main__":
    unittest.main()
