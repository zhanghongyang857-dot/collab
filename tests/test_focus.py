"""对照模块（src/modules/focus）的测试：期望值按 sample/ 的虚构数据手算，today 取 2026-03-04（周三）。"""
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "src" / "modules"
BUILD = ROOT / "src" / "board" / "now" / "build.py"
SAMPLE = MODULES / "focus" / "sample"

spec = importlib.util.spec_from_file_location("focus_load_test", MODULES / "focus" / "load.py")
focus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focus)

TODAY = dt.date(2026, 3, 4)
NOW = dt.datetime(2026, 3, 4, 15, 0)
CFG = {"folder_map": {"学期课程": "学习"}, "budgets": {"工作": ">=25", "项目": "25-30", "学习": "<=30", "杂务": "<=5"}}
COLORS = {"工作": "cat-blue", "项目": "cat-green", "学习": "cat-orange"}


def category(text):
    if "不计时" in text:
        return "rest"
    return next((c for k, c in COLORS.items() if k in text), "other")


def item(date, when, task, year="2026"):
    t = re.match(r"(\d{1,2}:\d{2})(?:–(\d{1,2}:\d{2}))?", when)
    return {"date": date, "year": year, "when": when, "start": t.group(1) if t else "", "end": (t.group(2) or "") if t else "",
            "what": "事", "kind": "plain", "task": task, "cat": category(task)}


def record(activity, folder, start, end):
    return {"activity": activity, "folder": folder, "start": f"2026-03-{start}:00+08:00", "end": f"2026-03-{end}:00+08:00"}


def run(items, records, active=None, cfg=CFG, today=TODAY, now=NOW):
    export = {"format": focus.FORMAT, "version": 1, "generated_at": "2026-03-04T14:59:00+08:00", "records": records, "active": active}
    return focus.compute(export, items, cfg, today, now, category)


def rows(summary):
    return {r["activity"]: (r["plan"], r["actual"]) for r in summary["rows"]}


class TestPieces(unittest.TestCase):
    def test_split_task(self):
        self.assertEqual(focus.split_task("课程（EE1）"), ("课程", "EE1"))
        self.assertEqual(focus.split_task("项目"), ("项目", "项目"))

    def test_parse_budget(self):
        self.assertEqual(focus.parse_budget(">=25"), (25, None))
        self.assertEqual(focus.parse_budget("≤30"), (None, 30))
        self.assertEqual(focus.parse_budget("25-30"), (25, 30))
        self.assertEqual(focus.parse_budget("随便"), (None, None))

    def test_split_days_across_midnight(self):
        a, b = dt.datetime(2026, 3, 2, 23, 30), dt.datetime(2026, 3, 4, 0, 10)
        parts = focus.split_days(a, b)
        self.assertEqual([(p[0].day, (p[2] - p[1]).total_seconds() / 60) for p in parts], [(2, 30), (3, 1440), (4, 10)])

    def test_year_is_nearest_to_today(self):
        it = item("12-30", "09:00–10:00", "工作（周报）", year="")
        self.assertEqual(focus.resolve_date(it, dt.date(2026, 1, 2)), dt.date(2025, 12, 30))


class TestMetrics(unittest.TestCase):
    def test_specific_plan_is_not_absorbed_by_same_category(self):
        """总量对、科目错：计划 EE2 160，实际全给 EE1，完成度要低、EE2 显示 0。"""
        s = run([item("03-04", "09:00–10:40", "学习（EE1）"), item("03-04", "11:00–13:40", "学习（EE2）")],
                [record("EE1", "学习", "04T09:00", "04T13:20")])["today"]
        self.assertEqual(rows(s), {"EE1": (100, 260), "EE2": (160, 0)})
        self.assertEqual((s["planMin"], s["actualMin"]), (260, 260))
        self.assertEqual(s["completion"], 38)  # 100 / 260
        self.assertEqual(s["unplannedMin"], 160)
        self.assertEqual(s["missing"], [{"activity": "EE2", "min": 160}])
        self.assertEqual(s["rows"][0]["activity"], "EE2")  # 偏差一样大时，没做的排前面

    def test_category_only_plan_takes_unnamed_activities_of_that_category(self):
        s = run([item("03-04", "09:00–10:00", "项目"), item("03-04", "10:00–11:00", "学习（数学）")],
                [record("代码", "项目", "04T09:00", "04T09:40"), record("数学", "学习", "04T10:00", "04T10:30"),
                 record("英语", "学习", "04T11:00", "04T11:20")])["today"]
        self.assertEqual(rows(s), {"项目": (60, 40), "数学": (60, 30), "英语": (0, 20)})
        self.assertEqual(s["completion"], 58)  # (40 + 30) / 120
        self.assertEqual(s["unplannedMin"], 20)

    def test_rest_notes_and_unquantified_lines(self):
        s = run([item("03-04", "备注", "—"), item("03-04", "10:00–10:10", "不计时"), item("03-04", "下午", "学习（论文）"),
                 item("03-04", "19:00", "工作（会议）"), item("03-04", "", "工作（全天）"), item("03-04", "09:00–10:00", "工作（周报）")], [])["today"]
        self.assertEqual(s["planMin"], 60)
        self.assertEqual(s["unquant"], 2)
        self.assertEqual(s["completion"], 0)

    def test_no_plan_has_no_completion(self):
        s = run([], [record("代码", "项目", "04T09:00", "04T09:30")])["today"]
        self.assertIsNone(s["completion"])
        self.assertEqual(s["unplannedMin"], 30)
        self.assertEqual(s["firstFocus"], "09:00")

    def test_active_runs_until_now_and_is_marked(self):
        d = run([], [], active={"activity": "代码", "folder": "项目", "start": "2026-03-04T14:30:00+08:00"})
        self.assertEqual(d["today"]["actualMin"], 30)
        self.assertTrue(d["todaySegs"][0]["live"])
        self.assertEqual(d["active"], {"activity": "代码", "start": "14:30"})
        self.assertFalse(d["stale"])

    def test_stale_only_without_active(self):
        late = dt.datetime(2026, 3, 4, 18, 0)
        self.assertTrue(run([], [], now=late)["stale"])
        fresh = dt.datetime(2026, 3, 4, 15, 2)  # 计时中、导出刚更新过
        self.assertFalse(run([], [], active={"activity": "x", "start": "2026-03-04T14:00:00+08:00"}, now=fresh)["stale"])

    def test_unknown_folder_and_no_folder(self):
        w = run([], [record("甲", "别的", "04T09:00", "04T09:30"), {"activity": "乙", "start": "2026-03-04T10:00:00+08:00", "end": "2026-03-04T10:30:00+08:00"}])["week"]
        by = {r["name"]: r for r in w["rows"]}
        self.assertEqual((by["别的"]["min"], by["别的"]["state"]), (30, "none"))
        self.assertEqual(by[focus.NO_FOLDER]["min"], 30)

    def test_week_start_sunday(self):
        self.assertEqual(run([], [])["week"]["start"], "2026-03-02")
        self.assertEqual(run([], [], cfg={"week_start": "sun"})["week"]["start"], "2026-03-01")

    def test_records_before_the_week_do_not_count(self):
        w = run([], [record("代码", "项目", "01T09:00", "01T10:00")])["week"]
        self.assertEqual(w["totalMin"], 0)
        self.assertTrue(all(r["state"] == "none" for r in w["rows"]))


class TestAuditFixes(unittest.TestCase):
    """11-04 审核发现的问题。"""

    def test_activity_names_ignore_spaces_and_case(self):
        s = run([item("03-04", "09:00–10:00", "探索（AI 工具探索）")], [record("AI工具探索", "探索", "04T09:00", "04T10:00")])["today"]
        self.assertEqual(s["rows"][0]["activity"], "AI 工具探索")
        self.assertEqual((s["completion"], s["unplannedMin"]), (100, 0))
        s = run([item("03-04", "09:00–10:00", "探索(Abc)")], [record("abc", "探索", "04T09:00", "04T10:00")])["today"]
        self.assertEqual(s["completion"], 100)

    def test_dead_active_stops_at_last_export(self):
        """App 崩溃后 active 还留在文件里：不能一直涨，要提示。"""
        d = run([], [], active={"activity": "代码", "folder": "项目", "start": "2026-03-04T14:30:00+08:00"},
                today=dt.date(2026, 3, 7), now=dt.datetime(2026, 3, 7, 12, 0))  # 导出停在 03-04 14:59，三天后再看
        by = {x["date"]: x for x in d["days"]}
        self.assertEqual(by["2026-03-04"]["actualMin"], 29)
        self.assertEqual(by["2026-03-05"]["actualMin"], 0)
        self.assertEqual(d["today"]["actualMin"], 0)
        self.assertTrue(d["stale"])
        self.assertIsNone(d["active"])

    def test_active_within_refresh_window_stays_live(self):
        d = run([], [], active={"activity": "代码", "folder": "项目", "start": "2026-03-04T14:30:00+08:00"},
                now=dt.datetime(2026, 3, 4, 15, 3))
        self.assertEqual(d["today"]["actualMin"], 33)
        self.assertTrue(d["todaySegs"][0]["live"])
        self.assertFalse(d["stale"])

    def test_unplanned_activity_named_like_its_folder(self):
        s = run([item("03-04", "09:00–10:00", "工作（周报）")],
                [record("杂务", "杂务", "04T10:00", "04T10:10"), record("邮件", "杂务", "04T11:00", "04T11:10")])["today"]
        self.assertEqual(rows(s), {"周报": (60, 0), "杂务": (0, 10), "邮件": (0, 10)})

    def test_one_bad_item_only_loses_itself(self):
        good = record("代码", "项目", "04T09:00", "04T09:30")
        d = run([item("02-30", "09:00–10:00", "工作（周报）"), item("03-04", "11:00–12:00", "工作（周报）")],
                [good, {"activity": "缺结束", "start": "2026-03-04T10:00:00+08:00"}, {"start": None, "end": "x"}, "不是对象"])
        self.assertEqual(d["skipped"], 3)
        self.assertEqual((d["today"]["planMin"], d["today"]["actualMin"]), (60, 30))
        export = {"format": focus.FORMAT, "version": 1, "generated_at": "乱写", "records": [good], "active": None}
        d = focus.compute(export, [], CFG, TODAY, NOW, category)
        self.assertEqual((d["generatedAt"], d["today"]["actualMin"]), ("", 30))

    def test_first_focus_ignores_segment_from_previous_day(self):
        d = run([], [record("代码", "项目", "03T23:30", "04T00:30"), record("代码", "项目", "04T11:00", "04T11:10")])
        self.assertEqual(d["today"]["firstFocus"], "11:00")

    def test_plan_row_across_midnight(self):
        self.assertEqual(focus.plan_minutes({"start": "23:30", "end": "00:30"}), 60)


class TestSampleThroughLoader(unittest.TestCase):
    """用样例跑一遍真的加载器：schedule 提供计划（含归档），focus 读导出。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "NOW"
        shutil.copytree(SAMPLE, self.data)
        (self.data / "config.json").write_text(json.dumps({
            "categories": [{"name": n, "keywords": [n], "color": c.split("-")[1]} for n, c in COLORS.items()],
            "modules": ["schedule", "focus"],
            "focus": {"file": "export/focus-v1.json", **CFG},
        }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self):
        os.environ["NOW_DATA_DIR"] = str(self.data)
        try:
            s = importlib.util.spec_from_file_location("now_build_focus_test", BUILD)
            mod = importlib.util.module_from_spec(s)
            s.loader.exec_module(mod)
        finally:
            del os.environ["NOW_DATA_DIR"]
        return mod

    def focus_data(self):
        return {m["id"]: m for m in self.build().collect()["modules"]}.get("focus")

    def sample_compute(self):
        """load() 用真实的今天，这里取 schedule 提供的计划，按样例的今天重算。"""
        mod = self.build()
        s = importlib.util.spec_from_file_location("schedule_load_test", MODULES / "schedule" / "load.py")
        schedule = importlib.util.module_from_spec(s)
        s.loader.exec_module(schedule)
        provided = {}
        ctx = SimpleNamespace(data_dir=self.data, config={}, root_config={}, category=mod.category, inline=mod.inline,
                              table_rows=mod.table_rows, table_dicts=mod.table_dicts, sections=mod.sections,
                              find_section=mod.find_section, file_url=mod.file_url,
                              provide=provided.__setitem__, watch=lambda p: None)
        schedule.load(ctx)
        export = json.loads((SAMPLE / "export" / "focus-v1.json").read_text(encoding="utf-8"))
        return focus.compute(export, provided["plan"]["items"], CFG, TODAY, NOW, mod.category)

    def test_sample_today(self):
        d = self.sample_compute()
        t = d["today"]
        self.assertEqual(rows(t), {"周报": (60, 30), "数学": (90, 0), "项目": (60, 40), "英语": (0, 120)})
        self.assertEqual((t["planMin"], t["actualMin"]), (210, 190))
        self.assertEqual(t["completion"], 33)  # (30 + 0 + 40) / 210
        self.assertEqual(t["unplannedMin"], 120)
        self.assertEqual(t["unquant"], 2)
        self.assertEqual(t["firstFocus"], "09:05")

    def test_sample_archive_and_midnight(self):
        d = self.sample_compute()
        by = {x["date"]: x for x in d["days"]}
        y = by["2026-03-03"]  # 计划在 归档/，有一段是前一天 23:30 跨过来的
        self.assertEqual(rows(y), {"数学": (60, 60), "代码": (0, 30)})
        self.assertEqual(y["completion"], 100)
        self.assertEqual(by["2026-03-02"]["actualMin"], 30)
        self.assertEqual(len(d["days"]), 7)
        self.assertEqual(d["days"][0]["date"], "2026-03-04")

    def test_sample_week(self):
        w = self.sample_compute()["week"]
        by = {r["name"]: r for r in w["rows"]}
        self.assertEqual(w["totalMin"], 310)  # 代码 30 + 30（跨午夜）+ 40，数学 60，周报 30，英语 120
        self.assertEqual((by["工作"]["min"], by["项目"]["min"], by["学习"]["min"]), (30, 100, 180))
        self.assertEqual((by["工作"]["pct"], by["项目"]["pct"], by["学习"]["pct"]), (9.7, 32.3, 58.1))
        self.assertEqual((by["工作"]["state"], by["项目"]["state"], by["学习"]["state"]), ("under", "over", "over"))
        self.assertEqual(by["杂务"]["min"], 0)
        self.assertEqual(by["杂务"]["state"], "ok")

    def test_loaded_for_real(self):
        m = self.focus_data()
        self.assertEqual((m["error"], m["data"]["status"]), ("", "ok"))
        self.assertEqual([t["id"] for t in m["tabs"]], ["focus"])

    def test_page_is_link_from_today_not_a_tab(self):
        m = self.focus_data()
        self.assertTrue(m["tabs"][0]["hidden"])
        mod = self.build()
        page = mod.render(mod.collect())
        self.assertIn('href="#focus"', page)     # 「今天」状态行进入
        self.assertIn('href="#today"', page)     # 明细页返回
        self.assertIn("TABS.filter(t => !t.hidden)", page)  # 标签栏跳过隐藏页

    def test_off_when_no_section_and_missing_or_bad_file(self):
        cfg = json.loads((self.data / "config.json").read_text(encoding="utf-8"))
        del cfg["focus"]
        (self.data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.focus_data()["data"]["status"], "off")
        cfg["focus"] = {"file": "export/没有.json"}
        (self.data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.focus_data()["data"]["status"], "missing")
        (self.data / "export" / "坏.json").write_text("{", encoding="utf-8")
        cfg["focus"] = {"file": "export/坏.json"}
        (self.data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.focus_data()["data"]["status"], "bad")
        (self.data / "export" / "坏.json").write_text('{"format": "别的", "version": 1}', encoding="utf-8")
        self.assertEqual(self.focus_data()["data"]["status"], "bad")
        (self.data / "export" / "坏.json").write_text('[1, 2]', encoding="utf-8")
        self.assertEqual(self.focus_data()["data"]["status"], "bad")

    def test_needs_schedule(self):
        cfg = json.loads((self.data / "config.json").read_text(encoding="utf-8"))
        cfg["modules"] = ["focus"]
        (self.data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        data = self.build().collect()
        self.assertEqual(data["modules"], [])
        self.assertTrue(any("focus 需要 schedule" in n for n in data["notes"]))

    def test_page_without_focus_has_no_lane_code_or_css(self):
        cfg = json.loads((self.data / "config.json").read_text(encoding="utf-8"))
        cfg["modules"] = ["schedule"]
        (self.data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        mod = self.build()
        page = mod.render(mod.collect())
        self.assertNotIn("fc-lane", page)
        self.assertNotIn('"title": "对照"', page)


class TestScheduleProvidesArchive(unittest.TestCase):
    def test_page_data_stays_without_archive_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "NOW"
            shutil.copytree(SAMPLE, data)
            # 归档里也有一行还留在 安排.md 里的：不重复
            with open(data / "归档" / "2026-03.md", "a", encoding="utf-8") as f:
                f.write("| 03-04 | 09:00–10:00 | 写周报 | 工作（周报） |\n")
            (data / "config.json").write_text('{"modules": ["schedule"]}', encoding="utf-8")
            os.environ["NOW_DATA_DIR"] = str(data)
            try:
                s = importlib.util.spec_from_file_location("now_build_arch_test", BUILD)
                mod = importlib.util.module_from_spec(s)
                s.loader.exec_module(mod)
            finally:
                del os.environ["NOW_DATA_DIR"]
            plan = mod.collect()["modules"][0]["data"]["plan"]
            self.assertEqual(len(plan["items"]), 7)  # 页面只有 安排.md 的行
            self.assertFalse(any(it["date"] == "03-03" for it in plan["items"]))


if __name__ == "__main__":
    unittest.main()
