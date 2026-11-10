"""calendar 模块的测试：日期区间、待定、全天、跨年、没装截止模块、分类配置、单独拿掉不影响其他、口令合并。

全部用临时目录里的虚构数据；运行：python3 -m unittest discover -s tests
"""
import datetime as dt
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_modules import MODULES, Base  # noqa: E402

CAL = MODULES / "calendar"
spec = importlib.util.spec_from_file_location("calendar_load", CAL / "load.py")
cal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)

HEAD = "| 日期 | 时间 | 事件 | 分类 | 地点 | 备注 |\n|---|---|---|---|---|---|\n"


class TestParsing(unittest.TestCase):
    def test_single_day_and_range(self):
        self.assertEqual(cal.parse_date("2026-11-10"), ("2026-11-10", "2026-11-10"))
        self.assertEqual(cal.parse_date("2026-12-01～12-03"), ("2026-12-01", "2026-12-03"))
        self.assertEqual(cal.parse_date("2026-12-01~2026-12-03"), ("2026-12-01", "2026-12-03"))

    def test_range_across_year(self):
        self.assertEqual(cal.parse_date("2026-12-30～01-02"), ("2026-12-30", "2027-01-02"))
        self.assertEqual(cal.parse_date("2026-12-30～2027-01-02"), ("2026-12-30", "2027-01-02"))

    def test_pending(self):
        self.assertEqual(cal.parse_date("待定"), (None, None))

    def test_bad_dates(self):
        for s in ("11-10", "2026-13-01", "2026-02-30", "下周二", "2026-12-05～2025-01-01"):
            with self.assertRaises(ValueError, msg=s):
                cal.parse_date(s)

    def test_times(self):
        self.assertEqual(cal.parse_time(""), ("", "", True))
        self.assertEqual(cal.parse_time("14:00"), ("14:00", "", False))
        self.assertEqual(cal.parse_time("9:30–11:00"), ("09:30", "11:00", False))
        self.assertEqual(cal.parse_time("18:30-21:20"), ("18:30", "21:20", False))
        with self.assertRaises(ValueError):
            cal.parse_time("下午")


class CalBase(Base):
    def setUp(self):
        super().setUp()
        shutil.copytree(CAL / "sample", self.data, dirs_exist_ok=True)
        self.config(modules=["schedule", "deadlines", "calendar"])

    def write(self, rows, name="日历/日历.md"):
        p = self.data / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# 日历\n\n" + HEAD + rows, encoding="utf-8")

    def cal(self):
        m = self.mods(self.build().collect())["calendar"]
        self.assertEqual(m["error"], "")
        return m["data"]


class TestLoad(CalBase):
    def test_sample(self):
        d = self.cal()
        self.assertTrue(d["exists"])
        self.assertEqual(len(d["events"]) - len([e for e in d["events"] if e["exam"]]), 5)
        self.assertEqual([e["title"] for e in d["pending"]], ["示例讲座（听说 12 月有）"])
        self.assertEqual(d["bad"], [])
        self.assertNotIn("days", d)

    def test_fields_range_allday_important_tentative(self):
        self.write("| 2026-11-10 | 18:30–21:20 | 课 | 课程 | 教室 | |\n"
                   "| 2026-11-12 | 14:00 | 宣讲会 | 求职 | 礼堂 | 大致时间 |\n"
                   "| 2026-11-14 | | **开放日** | 探索 | | |\n"
                   "| 2026-12-01～12-03 | | 会议 | 科研 | | |\n")
        ev = {e["title"]: e for e in self.cal()["events"] if not e["exam"]}
        self.assertEqual((ev["课"]["start"], ev["课"]["endTime"], ev["课"]["allDay"]), ("18:30", "21:20", False))
        self.assertEqual((ev["宣讲会"]["start"], ev["宣讲会"]["endTime"]), ("14:00", ""))
        self.assertTrue(ev["宣讲会"]["tentative"])
        self.assertFalse(ev["课"]["tentative"])
        self.assertTrue(ev["开放日"]["allDay"])
        self.assertTrue(ev["开放日"]["important"])
        self.assertEqual((ev["会议"]["date"], ev["会议"]["end"]), ("2026-12-01", "2026-12-03"))

    def test_cross_year_range_and_sorting(self):
        self.write("| 2027-01-05 | 10:00 | 晚 | | | |\n| 2026-12-30～01-02 | | 跨年 | | | |\n| 2027-01-05 | 09:00 | 早 | | | |\n")
        evs = [e for e in self.cal()["events"] if not e["exam"]]
        self.assertEqual([e["title"] for e in evs], ["跨年", "早", "晚"])
        self.assertEqual(evs[0]["end"], "2027-01-02")

    def test_pending_not_in_dated_events(self):
        self.write("| 待定 | | 讲座 | 探索 | | 日期未公布 |\n| 2026-11-10 | | 有日期 | | | |\n")
        d = self.cal()
        self.assertEqual([e["title"] for e in d["pending"]], ["讲座"])
        self.assertEqual([e["title"] for e in d["events"] if not e["exam"]], ["有日期"])

    def test_bad_rows_skipped_and_reported(self):
        self.write("| 11-10 | | 缺年份 | | | |\n| 2026-11-10 | 下午 | 时间错 | | | |\n| 2026-11-11 | | 好的 | | | |\n")
        d = self.cal()
        self.assertEqual([e["title"] for e in d["events"] if not e["exam"]], ["好的"])
        self.assertEqual(len(d["bad"]), 2)

    def test_missing_file_is_empty_state(self):
        (self.data / "日历" / "日历.md").unlink()
        d = self.cal()
        self.assertFalse(d["exists"])
        self.assertEqual(([e for e in d["events"] if not e["exam"]], d["pending"]), ([], []))

    def test_file_config(self):
        self.write("| 2026-11-10 | | 别处 | | | |\n", name="别处.md")
        self.config(calendar={"file": "别处.md"})
        d = self.cal()
        self.assertNotIn("days", d)
        self.assertEqual([e["title"] for e in d["events"] if not e["exam"]], ["别处"])

    def test_provides_events(self):
        self.module("probe", {"uses": ["calendar"]}, load="def load(ctx):\n    return {'n': len(ctx.get('events') or [])}\n")
        self.config(modules=["calendar", "probe"])
        self.assertEqual(self.mods(self.build().collect())["probe"]["data"]["n"], 5)


class TestCategories(CalBase):
    def test_configured_categories_match_name_exactly(self):
        self.write("| 2026-11-10 | | 甲 | 生活 | | |\n| 2026-11-10 | | 乙 | 求职 | | |\n| 2026-11-10 | | 丙 | 没配的 | | |\n"
                   "| 2026-11-10 | | 丁 | | | |\n| 2026-11-10 | | 戊 | 求 | | |\n")
        self.config(calendar={"categories": [{"name": "生活", "keywords": ["生活"], "color": "gray", "note": "私人"},
                                              {"name": "求职", "color": "pink"}]})
        d = self.cal()
        ev = {e["title"]: (e["cat"], e["catKey"]) for e in d["events"] if not e["exam"]}
        self.assertEqual(ev, {"甲": ("cat-gray", "生活"), "乙": ("cat-pink", "求职"), "丙": ("other", ""),
                              "丁": ("other", ""), "戊": ("other", "")})
        self.assertTrue(d["configured"])
        self.assertEqual([(l["key"], l["name"], l["note"], l["cat"]) for l in d["legend"]],
                         [("生活", "生活", "私人", "cat-gray"), ("求职", "求职", "", "cat-pink"), ("", "未分类", d["legend"][2]["note"], "other")])

    def test_uncategorized_row_only_when_present(self):
        self.write("| 2026-11-10 | | 甲 | 生活 | | |\n")
        self.config(modules=["calendar"], calendar={"categories": [{"name": "生活", "color": "gray"}]})
        self.assertEqual([l["key"] for l in self.cal()["legend"]], ["生活"])

    def test_uncategorized_pending_also_listed(self):
        self.write("| 待定 | | 甲 | 乱写 | | |\n")
        self.config(calendar={"categories": [{"name": "生活", "color": "gray"}]})
        d = self.cal()
        self.assertEqual(d["pending"][0]["catKey"], "")
        self.assertEqual([l["name"] for l in d["legend"]], ["生活", "未分类"])

    def test_no_categories_configured_legend_from_actual(self):
        self.write("| 2026-11-10 | | 甲 | 探索 | | |\n| 2026-11-11 | | 乙 | 探索 | | |\n| 2026-11-12 | | 丙 | 学习 | | |\n")
        d = self.cal()
        self.assertFalse(d["configured"])
        self.assertEqual(d["major"], "")
        self.assertTrue(all(l["note"] == "" for l in d["legend"]))
        keys = {l["key"] for l in d["legend"]}
        self.assertEqual(keys, {e["catKey"] for e in d["events"]} | {e["catKey"] for e in d["pending"]})
        self.assertTrue(all(e["catKey"] == e["cat"] for e in d["events"]))  # 筛选键就是颜色键

    def test_filter_data_each_event_has_legend_key(self):
        self.write("| 2026-11-10 | | 甲 | 生活 | | |\n| 2026-11-10 | | 乙 | 乱写 | | |\n")
        self.config(calendar={"categories": [{"name": "生活", "color": "gray"}]})
        d = self.cal()
        keys = {l["key"] for l in d["legend"]}
        for e in d["events"] + d["pending"]:
            self.assertIn(e["catKey"], keys)

    def test_falls_back_to_core_categories(self):
        self.write("| 2026-11-10 | | 甲 | 探索 | | |\n")
        self.assertEqual([e["cat"] for e in self.cal()["events"] if not e["exam"]], ["cat-purple"])  # 样例核心分类：探索=紫

    def test_no_personal_category_names_in_code(self):
        code = "\n".join((CAL / f).read_text(encoding="utf-8") for f in ("load.py", "view.js"))
        for name in ("课程", "科研与项目", "求职", "生活", "重大事项", "学习与科研", "职业", "探索"):
            self.assertNotIn(name, code)


class TestDeadlines(CalBase):
    def setUp(self):
        super().setUp()
        d = dt.date.today() + dt.timedelta(days=3)
        self.day = d.isoformat()
        (self.data / "截止.md").write_text(
            f"## EE0001 示例课\n- **期中（30%）**：**{self.day}（周X）14:00–16:00**\n"
            f"- **作业（10%）**：**{self.day}（周X）23:59 暂定**\n", encoding="utf-8")
        self.config(deadlines={"file": "截止.md", "category": "学习", "groups": ["EE0001"]})

    def test_exams_merged_once_and_marked(self):
        self.write(f"| {self.day} | 10:00 | 讲座 | 探索 | | |\n")
        evs = self.cal()["events"]
        exams = [e for e in evs if e["exam"]]
        self.assertEqual([e["title"] for e in exams], ["EE0001 · 期中（30%）", "EE0001 · 作业（10%）"])
        self.assertEqual(exams[0]["timeText"], "14:00–16:00")
        self.assertTrue(exams[1]["tentative"])
        self.assertEqual([e["title"] for e in evs if not e["exam"]], ["讲座"])
        self.assertEqual(evs[0]["title"], "讲座")  # 同一天按开始时间排：10:00 在 14:00 前

    def test_exam_category_uses_calendar_categories(self):
        self.config(deadlines={"file": "截止.md", "groups": ["EE0001"]},
                    calendar={"categories": [{"name": "课程", "keywords": ["EE0001"], "color": "red"}]})
        self.assertEqual({e["cat"] for e in self.cal()["events"] if e["exam"]}, {"cat-red"})

    def test_major_category_merges_exams(self):
        self.write(f"| {self.day} | 10:00 | 面试 | 要事 | | |\n| {self.day} | 11:00 | 讲座 | 学 | | |\n")
        self.config(deadlines={"file": "截止.md", "groups": ["EE0001"]},
                    calendar={"categories": [{"name": "要事", "color": "red", "note": "不能错过"},
                                             {"name": "学", "color": "blue"}], "major_category": "要事"})
        d = self.cal()
        self.assertEqual(d["major"], "要事")
        self.assertEqual({(e["cat"], e["catKey"], e["source"]) for e in d["events"] if e["exam"]}, {("cat-red", "要事", "考核安排")})
        self.assertEqual([(e["title"], e["cat"], e["source"]) for e in d["events"] if not e["exam"] and e["catKey"] == "要事"],
                         [("面试", "cat-red", "日历")])
        self.assertEqual(len([e for e in d["events"] if e["catKey"] == "要事"]), 3)  # 1 日历 + 2 考核，各一次
        self.assertEqual(len([e for e in d["events"] if e["exam"]]), 2)

    def test_major_category_exams_not_in_calendar_provide(self):
        self.config(calendar={"categories": [{"name": "要事", "color": "red"}], "major_category": "要事"},
                    deadlines={"file": "截止.md", "groups": ["EE0001"]})
        self.module("probe", {"uses": ["calendar"]}, load="def load(ctx):\n    return {'n': len(ctx.get('events') or [])}\n")
        self.config(modules=["deadlines", "calendar", "probe"])
        self.assertEqual(self.mods(self.build().collect())["probe"]["data"]["n"], 5)

    def test_major_category_not_in_list_keeps_exam_mark_behaviour(self):
        self.config(deadlines={"file": "截止.md", "groups": ["EE0001"]},
                    calendar={"categories": [{"name": "课程", "keywords": ["EE0001"], "color": "red"}], "major_category": "没有这类"})
        d = self.cal()
        self.assertEqual(d["major"], "")
        self.assertEqual({e["cat"] for e in d["events"] if e["exam"]}, {"cat-red"})

    def test_exams_without_categories_keep_mark(self):
        d = self.cal()
        self.assertEqual(d["major"], "")
        self.assertTrue(all(e["exam"] for e in d["events"] if e["source"] == "考核安排"))

    def test_exam_not_written_to_calendar_provide(self):
        self.module("probe", {"uses": ["calendar"]}, load="def load(ctx):\n    return {'n': len(ctx.get('events') or [])}\n")
        self.config(modules=["deadlines", "calendar", "probe"])
        self.assertEqual(self.mods(self.build().collect())["probe"]["data"]["n"], 5)

    def test_without_deadlines_module(self):
        self.config(modules=["calendar"])
        d = self.cal()
        self.assertFalse(d["hasDeadlines"])
        self.assertEqual([e for e in d["events"] if e["exam"]], [])
        self.assertEqual(len(d["events"]), 5)

    def test_deadlines_enabled_but_no_source(self):
        self.config(deadlines={})
        d = self.cal()
        self.assertTrue(d["hasDeadlines"])
        self.assertEqual([e for e in d["events"] if e["exam"]], [])


class TestIsolation(CalBase):
    def test_removing_calendar_leaves_others_unchanged(self):
        with_cal = self.build().collect()
        self.config(modules=["schedule", "deadlines"])
        without = self.build().collect()
        a, b = self.mods(with_cal), self.mods(without)
        self.assertNotIn("calendar", b)
        for mid in ("schedule", "deadlines"):
            self.assertEqual(a[mid]["data"], b[mid]["data"])
            self.assertEqual(a[mid]["error"], "")
        self.assertEqual(without["notes"], [])
        self.assertEqual(with_cal["now"], without["now"])

    def test_calendar_error_only_affects_itself(self):
        (self.data / "日历" / "日历.md").write_bytes(b"\xff\xfe\x00bad")
        data = self.build().collect()
        m = self.mods(data)
        self.assertNotEqual(m["calendar"]["error"], "")
        self.assertEqual(m["schedule"]["error"], "")
        self.assertEqual(m["deadlines"]["error"], "")

    def test_calendar_does_not_touch_schedule_data(self):
        s1 = self.mods(self.build().collect())["schedule"]["data"]["plan"]["items"]
        self.write("| 2026-11-10 | 09:00 | 事件 | | | |\n")
        s2 = self.mods(self.build().collect())["schedule"]["data"]["plan"]["items"]
        self.assertEqual(s1, s2)

    def test_page_renders_with_calendar_tab(self):
        mod = self.build()
        page = mod.render(mod.collect())
        self.assertIn('NOW.register("calendar"', page)
        self.assertNotIn("/*MODULE_JS*/", page)


class TestMonthView(CalBase):
    def test_multiday_event_covers_each_day_once_in_data(self):
        self.write("| 2026-12-01～12-03 | | 会议 | | | |\n")
        d = self.cal()
        evs = [e for e in d["events"] if e["title"] == "会议"]
        self.assertEqual((len(evs), evs[0]["date"], evs[0]["end"]), (1, "2026-12-01", "2026-12-03"))  # 页面按日期范围铺到每一天

    def test_no_days_config_or_list_view_left(self):
        self.config(calendar={"days": 7})
        self.assertNotIn("days", self.cal())
        js = (CAL / "view.js").read_text(encoding="utf-8")
        for word in ("D.days", "接下来"):
            self.assertNotIn(word, js)
        for word in ("上一月", "下一月", "今天", "还有", "考核", "cal-more", "cal-grid", "cal-side", "cal-leg"):
            self.assertIn(word, js)
        css = (CAL / "view.css").read_text(encoding="utf-8")
        self.assertIn("max-width: 760px", css)
        self.assertIn("max-width: 900px", css)

    def test_yellow_in_both_palettes(self):
        t = (MODULES.parent / "board" / "now" / "template.html").read_text(encoding="utf-8")
        self.assertEqual(t.count("--cat-yellow:"), 2)


class TestRules(unittest.TestCase):
    def test_rules_text(self):
        t = (CAL / "口令.md").read_text(encoding="utf-8")
        self.assertIn("## 记事件", t)
        self.assertIn("## 排明天", t)
        self.assertIn("不自造新类", t)
        self.assertIn("重大事项", t)  # 口令里只引用配置项 major_category 的叫法

    def test_merged_after_core_and_before_or_after_schedule_by_modules_order(self):
        import tempfile
        sys.path.insert(0, str(MODULES.parent / "core"))
        import modules as km  # noqa: E402
        for order, first in ((["calendar", "schedule"], "日历"), (["schedule", "calendar"], "archive")):
            tmp = Path(tempfile.mkdtemp())
            try:
                (tmp / "config.json").write_text(json.dumps({"modules": order}), encoding="utf-8")
                text = km.merged_rules(MODULES.parent, tmp, {"modules": order})
                body = text.split("## 排明天", 1)[1].split("\n## ", 1)[0]
                self.assertEqual(text.count("## 排明天"), 1)
                self.assertIn("日历/日历.md", body)
                if first == "日历":
                    self.assertLess(body.index("日历/日历.md"), body.index("写明天的行（每行"))
                else:
                    self.assertLess(body.index("写明天的行（每行"), body.index("日历/日历.md"))
            finally:
                shutil.rmtree(tmp)


class TestCli(unittest.TestCase):
    def test_enable_generates_sample_and_rules(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            data = tmp / "NOW"
            data.mkdir()
            (data / "config.json").write_text('{"now_md": "../NOW.md", "categories": []}', encoding="utf-8")
            init = MODULES.parent / "core" / "init.sh"
            r = subprocess.run(["bash", str(init), "module", "enable", "calendar", "--now-dir", str(data)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((data / "日历" / "日历.md").exists())
            self.assertIn("## 记事件", (data / "口令.md").read_text(encoding="utf-8"))
            self.assertIn("calendar", json.loads((data / "config.json").read_text(encoding="utf-8"))["modules"])
            r = subprocess.run(["bash", str(init), "module", "disable", "calendar", "--now-dir", str(data)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((data / "日历" / "日历.md").exists())
            self.assertNotIn("记事件", (data / "口令.md").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
