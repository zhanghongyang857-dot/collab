"""NOW 看板模块化的测试：核心加载器（src/board/now/build.py）和自带的 schedule、deadlines 模块。

全部用临时目录里的虚构数据；运行：python3 -m unittest discover -s tests
"""
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "src" / "board" / "now" / "build.py"
MODULES = ROOT / "src" / "modules"
CORE_SAMPLE = ROOT / "src" / "board" / "now" / "sample"

NOW_MD = """# NOW

## 任务

| 任务 | 分类 | 等级 | 状态 |
|---|---|---|---|
| 示例任务 | 工作 | A | 进行中 |

## 大方向

| 方向 | 半年后想要的结果 | 关键节点 | 占比 |
|---|---|---|---|
| 工作 | 做成一件事 | 月底 | 50% |
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "NOW"
        shutil.copytree(CORE_SAMPLE / "NOW", self.data)
        (self.tmp / "NOW.md").write_text(NOW_MD, encoding="utf-8")
        for mid in ("schedule", "deadlines"):
            shutil.copytree(MODULES / mid / "sample", self.data, dirs_exist_ok=True)
        # 样例里的占位符本由 init.sh 填，这里按今天填上
        d0 = dt.date.today()
        d1 = d0 + dt.timedelta(days=14)
        for f, subs in (("安排.md", {"| MM-DD |": f"| {d0:%m-%d} |"}),
                        ("截止.md", {"{{示例日期}}": d1.isoformat(), "{{示例周几}}": "周" + "一二三四五六日"[d1.weekday()]})):
            p = self.data / f
            t = p.read_text(encoding="utf-8")
            for k, v in subs.items():
                t = t.replace(k, v)
            p.write_text(t, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def config(self, **kw):
        f = self.data / "config.json"
        cfg = json.loads(f.read_text(encoding="utf-8"))
        cfg.update(kw)
        f.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def build(self):
        """按当前数据目录重新导入 build.py（它在导入时读配置）。"""
        os.environ["NOW_DATA_DIR"] = str(self.data)
        try:
            spec = importlib.util.spec_from_file_location("now_build_test", BUILD)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            del os.environ["NOW_DATA_DIR"]
        return mod

    def module(self, mid, meta=None, load="def load(ctx):\n    return {'ok': True}\n", js="", where="模块"):
        d = self.data / where / mid
        d.mkdir(parents=True)
        meta = {"id": mid, "name": mid, "version": 1, "contract": 1, "tabs": [], "slots": [],
                "files": [], "requires": [], "uses": [], "provides": [], **(meta or {})}
        (d / "module.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "load.py").write_text(load, encoding="utf-8")
        if js:
            (d / "view.js").write_text(js, encoding="utf-8")
        return d

    def mods(self, data):
        return {m["id"]: m for m in data["modules"]}


class TestLoader(Base):
    def test_default_modules_when_config_has_none(self):
        data = self.build().collect()
        self.assertEqual([m["id"] for m in data["modules"]], ["schedule", "deadlines"])
        self.assertEqual(data["notes"], [])
        tabs = [t["id"] for m in data["modules"] for t in m["tabs"]]
        self.assertEqual(tabs, ["today", "plan"])

    def test_core_only(self):
        self.config(modules=[])
        mod = self.build()
        data = mod.collect()
        self.assertEqual(data["modules"], [])
        self.assertEqual(data["now"]["tasks"][0]["name"], "示例任务")
        page = mod.render(data)
        for mark in ("/*DATA*/", "/*MODULE_CSS*/", "/*MODULE_JS*/"):
            self.assertNotIn(mark, page)

    def link_module(self, mid, url):
        """只有 module.json 的链接模块。"""
        d = self.data / "模块" / mid
        d.mkdir(parents=True)
        (d / "module.json").write_text(json.dumps({"id": mid, "name": mid, "version": 1, "contract": 1,
                                                   "tabs": [{"id": mid, "title": "外部", "url": url}]}), encoding="utf-8")

    def test_link_module_needs_only_module_json(self):
        self.link_module("ext", "http://127.0.0.1:3200/")
        self.config(modules=["schedule", "ext"])
        mod = self.build()
        data = mod.collect()
        self.assertEqual(data["notes"], [])
        m = self.mods(data)["ext"]
        self.assertEqual(m["error"], "")
        self.assertEqual(m["tabs"][0]["url"], "http://127.0.0.1:3200/")
        self.assertEqual(self.mods(data)["schedule"]["error"], "")
        self.assertIn("http://127.0.0.1:3200/", mod.render(data))

    def test_link_tab_has_no_arrow_and_sits_after_separator(self):
        self.link_module("ext", "http://127.0.0.1:3200/")
        self.config(modules=["schedule", "ext"])
        mod = self.build()
        page = mod.render(mod.collect())
        self.assertNotIn("↗", page)
        self.assertIn('class="tab-sep"', page)

    def test_link_rejects_other_schemes(self):
        for i, url in enumerate(("javascript:alert(1)", "file:///etc/passwd", "http://", "/相对", 5)):
            self.link_module(f"bad{i}", url)
        self.config(modules=[f"bad{i}" for i in range(5)])
        data = self.build().collect()
        self.assertEqual([t for m in data["modules"] for t in m["tabs"]], [])
        self.assertEqual(len(data["notes"]), 5)
        self.assertIn("只支持 http、https", data["notes"][0])

    def test_inline_module_with_load_py_still_loads(self):
        self.module("inline", meta={"tabs": [{"id": "inline", "title": "内嵌"}]})
        self.config(modules=["inline"])
        data = self.build().collect()
        self.assertEqual(self.mods(data)["inline"]["data"], {"ok": True})
        self.assertNotIn("url", self.mods(data)["inline"]["tabs"][0])

    def test_core_without_any_data_files(self):
        """只有 config.json：NOW.md、已完成.md 都没有也能生成。"""
        for f in self.data.iterdir():
            if f.name != "config.json":
                f.unlink() if f.is_file() else shutil.rmtree(f)
        (self.tmp / "NOW.md").unlink()
        self.config(modules=[])
        data = self.build().collect()
        self.assertEqual(data["now"]["tasks"], [])

    def test_order_follows_config(self):
        self.config(modules=["deadlines", "schedule"])
        data = self.build().collect()
        self.assertEqual([m["id"] for m in data["modules"]], ["deadlines", "schedule"])

    def _tab_modules(self):
        """schedule（今天、短期）后面接一个内嵌模块 cal（日历）和一个链接模块 lnk。"""
        self.module("cal", {"tabs": [{"id": "cal", "title": "日历"}]})
        self.module("lnk", {"tabs": [{"id": "lnk", "title": "外链", "url": "http://127.0.0.1:3200/"}]})

    def test_tab_order_default_follows_modules(self):
        self._tab_modules()
        self.config(modules=["schedule", "cal", "lnk"])
        data = self.build().collect()
        self.assertEqual(data["tabOrder"], ["tasks", "today", "plan", "cal"])  # 链接标签不在内，页面上排最后

    def test_tab_order_reorders_listed_tabs_in_their_slots(self):
        self._tab_modules()
        self.config(modules=["schedule", "cal", "lnk"], tab_order=["today", "cal", "plan"])
        data = self.build().collect()
        self.assertEqual(data["tabOrder"], ["tasks", "today", "cal", "plan"])
        # 只列一部分：列出的在它们原来的位置里换序，「任务」等没列出的不动
        self.config(tab_order=["cal", "today"])
        self.assertEqual(self.build().collect()["tabOrder"], ["tasks", "cal", "plan", "today"])

    def test_tab_order_ignores_unknown_duplicate_and_bad_values(self):
        self._tab_modules()
        self.config(modules=["schedule", "cal", "lnk"], tab_order=["nope", "lnk", "cal", "cal", "today"])
        data = self.build().collect()
        self.assertEqual(data["tabOrder"], ["tasks", "cal", "plan", "today"])
        self.config(tab_order="today")
        data = self.build().collect()
        self.assertEqual(data["tabOrder"], ["tasks", "today", "plan", "cal"])
        self.assertTrue(any("tab_order" in n for n in data["notes"]))

    def test_unknown_module_is_noted(self):
        self.config(modules=["schedule", "nope"])
        data = self.build().collect()
        self.assertEqual(list(self.mods(data)), ["schedule"])
        self.assertTrue(any("nope" in n for n in data["notes"]))

    def test_missing_requirement_skips_module(self):
        self.module("needs", {"requires": ["schedule"]})
        self.module("chain", {"requires": ["needs"]})
        self.config(modules=["deadlines", "needs", "chain"])
        data = self.build().collect()
        self.assertEqual(list(self.mods(data)), ["deadlines"])
        self.assertEqual(sum("未加载" in n for n in data["notes"]), 2)

    def test_contract_mismatch_not_loaded(self):
        self.module("future", {"contract": 2})
        self.config(modules=["future"])
        data = self.build().collect()
        self.assertEqual(data["modules"], [])
        self.assertTrue(any("约定版本" in n for n in data["notes"]))

    def test_error_only_affects_that_module(self):
        self.module("bad", load="def load(ctx):\n    raise ValueError('坏了')\n")
        self.config(modules=["schedule", "bad", "deadlines"])
        data = self.build().collect()
        m = self.mods(data)
        self.assertIn("坏了", m["bad"]["error"])
        self.assertIsNone(m["bad"]["data"])
        self.assertEqual(m["schedule"]["error"], "")
        self.assertTrue(m["deadlines"]["data"]["items"])

    def test_data_dir_module_overrides_toolkit(self):
        self.module("deadlines", {"name": "我的截止"}, load="def load(ctx):\n    return {'mine': True}\n")
        self.config(modules=["deadlines"])
        m = self.mods(self.build().collect())["deadlines"]
        self.assertEqual((m["name"], m["data"]), ("我的截止", {"mine": True}))

    def test_uses_gets_provided_data_and_skips_when_absent(self):
        load = "def load(ctx):\n    d = ctx.get('deadlines')\n    return {'n': None if d is None else len(d)}\n"
        self.module("cal", {"uses": ["deadlines"]}, load=load)
        # 写在依赖前面也先加载依赖
        self.config(modules=["cal", "deadlines"])
        self.assertEqual(self.mods(self.build().collect())["cal"]["data"], {"n": 1})
        self.config(modules=["cal"])
        self.assertEqual(self.mods(self.build().collect())["cal"]["data"], {"n": None})

    def test_provide_needs_declaration(self):
        self.module("p", load="def load(ctx):\n    ctx.provide('x', 1)\n    return {}\n")
        self.module("q", {"uses": ["p"]}, load="def load(ctx):\n    return {'x': ctx.get('x')}\n")
        self.config(modules=["p", "q"])
        self.assertEqual(self.mods(self.build().collect())["q"]["data"], {"x": None})

    def test_module_config_section(self):
        self.module("c", load="def load(ctx):\n    return ctx.config\n")
        self.config(modules=["c"], c={"k": 1})
        self.assertEqual(self.mods(self.build().collect())["c"]["data"], {"k": 1})

    def test_module_js_is_wrapped(self):
        self.module("j", js="NOW.register('j', {});")
        self.config(modules=["j"])
        mod = self.build()
        page = mod.render(mod.collect())
        self.assertIn("NOW.register('j', {});", page)
        self.assertIn('NOW.fail("j", e)', page)
        self.assertNotIn('"js":', page.split("const DATA = ", 1)[1].split(";\n", 1)[0])

    def test_watch_includes_module_files(self):
        mod = self.build()
        _, _, watch = mod.load_modules()
        names = {p.name for p in mod.sources(watch)}
        self.assertTrue({"安排.md", "本月布局.md", "截止.md", "load.py", "view.js"} <= names)


class TestBuiltinModules(Base):
    def test_schedule_sample(self):
        s = self.mods(self.build().collect())["schedule"]["data"]
        self.assertTrue(s["plan"]["exists"])
        self.assertEqual(len(s["plan"]["items"]), 6)
        self.assertEqual(s["month"]["cols"], ["主题", "工作", "学习", "项目"])
        self.assertEqual(len(s["month"]["weeks"]), 4)
        self.assertIsNone(s["today"])

    def test_plan_page_is_a_list_not_a_grid(self):
        mod = self.build()
        page = mod.render(mod.collect())
        self.assertIn("pl-days", page)
        self.assertNotIn("pl-grid", page)

    def test_month_moved_to_short_term_page(self):
        data = self.build().collect()
        s = self.mods(data)["schedule"]
        self.assertEqual([t["title"] for t in s["tabs"]], ["今天", "短期"])
        self.assertEqual([t["id"] for t in s["tabs"]], ["today", "plan"])
        self.assertNotIn("tasks.below", s["slots"])

    def test_inline_single_star_is_emphasis_but_not_multiplication(self):
        mod = self.build()
        self.assertEqual(mod.inline("*可选*；周复盘", self.data), "<em>可选</em>；周复盘")
        self.assertEqual(mod.inline("**节点**", self.data), "<strong>节点</strong>")
        self.assertEqual(mod.inline("算 3*4*5", self.data), "算 3*4*5")

    def test_schedule_plan_slots_old_and_new_place(self):
        slots = [{"name": "白天", "start": "00:00"}]
        self.config(plan_slots=slots)
        self.assertEqual(self.mods(self.build().collect())["schedule"]["data"]["plan"]["slots"], slots)
        new = [{"name": "全天段", "start": "00:00"}]
        self.config(schedule={"plan_slots": new})
        self.assertEqual(self.mods(self.build().collect())["schedule"]["data"]["plan"]["slots"], new)

    def test_schedule_without_files(self):
        (self.data / "安排.md").unlink()
        (self.data / "本月布局.md").unlink()
        s = self.mods(self.build().collect())["schedule"]
        self.assertEqual(s["error"], "")
        self.assertFalse(s["data"]["plan"]["exists"])
        self.assertFalse(s["data"]["month"]["exists"])

    def test_deadlines_sample_and_missing_source(self):
        d = self.mods(self.build().collect())["deadlines"]["data"]
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["cat"], "cat-orange")
        self.config(deadlines={})
        d = self.mods(self.build().collect())["deadlines"]["data"]
        self.assertEqual((d["items"], d["source"]), ([], ""))


class TestArchiveShim(Base):
    def test_old_path_still_runs(self):
        old = ROOT / "src" / "board" / "now" / "archive.py"
        r = subprocess.run([sys.executable, str(old), "--now-dir", str(self.data), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("没有需要归档的行", r.stdout)


if __name__ == "__main__":
    unittest.main()
