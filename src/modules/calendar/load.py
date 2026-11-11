"""日历模块：读 calendar/calendar.md 的事件表，给「日历」页的月网格和日期待定栏。

装了截止模块时，把它解析的考核项（ctx.get("deadlines")）合并进来，只记一份；没装就只显示日历文件里的事件。
分类取自 config.json 的 calendar.categories（[{name, keywords, color, note}]）：
- 配了：日历文件的分类列按 name 精确匹配，不在列表里（含空）算"未分类"（灰色）；
  calendar.major_category 指定的那一类同时收考核项，考核项不再单独标记；没指定时考核项按名字对 keywords 匹配并保留"考核"标记。
- 没配：沿用核心的分类和颜色，说明栏按实际出现的分类显示。
"""
import datetime as dt
import re
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "core"))
import paths as P  # noqa: E402  数据文件名
import i18n  # noqa: E402  NOW 数据的表头按代码认列

DEFAULT_FILE = P.CALENDAR
DEFAULT_TENTATIVE = ["大致", "待公告", "暂定", "待定", "approx", "to be announced", "tentative", "tbc", "tbd"]  # 备注含这些词时显示为虚线框


UNCAT = "未分类"


def make_category(ctx):
    """返回 文字 → (颜色键, 分类键) 的函数。
    配了 categories：按 name 精确匹配，分类键是 name，没命中是 ("other", "")；没配：沿用核心分类，分类键就是颜色键。"""
    cats = [c for c in ctx.config.get("categories") or [] if c.get("name")]
    by_name = {c["name"]: ("cat-" + c.get("color", "gray"), c["name"]) for c in cats}

    def cat(text):
        if cats:
            return by_name.get(text.strip(), ("other", ""))
        key = ctx.category(text)
        return key, key
    return cat


def make_exam_category(ctx, cat):
    """考核项的分类：配了 major_category 且在列表里就归入它；否则按名字匹配 keywords；没配分类时用核心分类，配了却没命中算未分类。"""
    cfg = ctx.config
    cats = [c for c in cfg.get("categories") or [] if c.get("name")]
    major = cfg.get("major_category") or ""
    if major and any(c["name"] == major for c in cats):
        return (lambda text: cat(major)), major
    kws = [(c.get("keywords") or [c["name"]], "cat-" + c.get("color", "gray"), c["name"]) for c in cats]

    def exam_cat(text):
        for ks, color, name in kws:
            if any(k in text for k in ks):
                return color, name
        return cat(text) if not cats else ("other", "")
    return exam_cat, ""


def parse_date(cell):
    """日期单元 → (开始, 结束)，都是 ISO 字符串；`待定` → (None, None)；写错 → 抛 ValueError。
    结束可以省略年份；结束的月日早于开始时算到下一年（跨年）。"""
    s = cell.strip().replace("~", "～")
    if s in ("待定", "TBD", "tbd"):
        return None, None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s*～\s*(?:(\d{4})-)?(\d{1,2})-(\d{1,2}))?", s)
    if not m:
        raise ValueError(f"日期看不懂：{cell}")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    start = dt.date(y, mo, d)
    if not m.group(5):
        return start.isoformat(), start.isoformat()
    ey = int(m.group(4)) if m.group(4) else y
    end = dt.date(ey, int(m.group(5)), int(m.group(6)))
    if not m.group(4) and end < start:
        end = end.replace(year=y + 1)
    if end < start:
        raise ValueError(f"结束早于开始：{cell}")
    return start.isoformat(), end.isoformat()


def parse_time(cell):
    """时间单元 → (开始, 结束, 全天)。空为全天；只认 HH:MM 和 HH:MM–HH:MM。"""
    s = cell.strip()
    if not s:
        return "", "", True
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*[–—-]\s*(\d{1,2}):(\d{2}))?", s)
    if not m:
        raise ValueError(f"时间看不懂：{cell}")
    end = f"{int(m.group(3)):02d}:{m.group(4)}" if m.group(3) else ""
    return f"{int(m.group(1)):02d}:{m.group(2)}", end, False


def parse_events(ctx, path, cat):
    """日历文件 → (有日期的事件, 日期待定的事件, 没法解析的行)。"""
    tent_kw = ctx.config.get("tentative_keywords") or DEFAULT_TENTATIVE
    dated, pending, bad = [], [], []
    for r in ctx.table_dicts(path.read_text(encoding="utf-8").splitlines()):
        r = i18n.cols(r)  # 表头按代码认列，中英两种写法都认
        title = r.get("event", "").strip()
        if not title or not r.get("date", "").strip():
            continue
        try:
            start, end = parse_date(r["date"])
            t0, t1, allday = parse_time(r.get("time", ""))
        except ValueError as e:
            bad.append(f"{e}（{title}）")
            continue
        important = len(title) > 4 and title.startswith("**") and title.endswith("**")
        title = title.strip("*").strip() if important else title
        note = r.get("note", "").strip()
        kind = r.get("category", "").strip()
        ev = {"date": start or "", "end": end or "", "start": t0, "endTime": t1, "allDay": allday,
              "title": title, "important": important, "place": r.get("place", "").strip(), "note": note,
              "category": kind, "cat": cat(kind)[0], "catKey": cat(kind)[1], "tentative": any(k in note for k in tent_kw),
              "exam": False, "source": "calendar"}
        (dated if start else pending).append(ev)
    dated.sort(key=lambda e: (e["date"], e["start"]))
    return dated, pending, bad


def exam_events(items, cat):
    """截止模块提供的考核项 → 日历事件；时间文字原样显示，能认出开始时间的用来排序。"""
    out = []
    for it in items or []:
        m = re.search(r"(\d{1,2}):(\d{2})", it.get("time", ""))
        text = it.get("time", "").strip()
        out.append({"date": it["date"], "end": it["date"], "start": f"{int(m.group(1)):02d}:{m.group(2)}" if m else "",
                    "endTime": "", "allDay": not text, "timeText": text,
                    "title": f"{it['course']} · {it['title']}" + (f"（{it['weight']}）" if it.get("weight") else ""),
                    "important": bool(it.get("final")), "place": "", "note": "",
                    "category": it["course"], "cat": cat(it["course"])[0], "catKey": cat(it["course"])[1],
                    "tentative": bool(it.get("tentative") or it.get("pending")), "exam": True, "source": "deadlines"})
    return out


def legend(ctx, events):
    """说明栏的行 [{key, name, note, cat}]：配了分类按配置顺序（有未分类事件时末尾加一行）；没配按实际出现的分类，没有 note。"""
    cats = [c for c in ctx.config.get("categories") or [] if c.get("name")]
    if cats:
        rows = [{"key": c["name"], "name": c["name"], "note": c.get("note", ""), "cat": "cat-" + c.get("color", "gray")}
                for c in cats]
        if any(e["catKey"] == "" for e in events):
            rows.append({"key": "", "name": UNCAT, "note": "分类不在配置列表里（或没写）", "cat": "other"})
        return rows
    rows, seen = [], set()
    for e in events:
        if e["catKey"] not in seen:
            seen.add(e["catKey"])
            rows.append({"key": e["catKey"], "name": e["category"] or UNCAT, "note": "", "cat": e["cat"]})
    return rows


def load(ctx):
    cfg = ctx.config
    path = ctx.path(cfg.get("file") or DEFAULT_FILE)
    ctx.watch(path)
    cat = make_category(ctx)
    exists = path.exists()
    dated, pending, bad = parse_events(ctx, path, cat) if exists else ([], [], [])
    ctx.provide("events", dated)
    deadlines = ctx.get("deadlines")
    exam_cat, major = make_exam_category(ctx, cat)
    exams = exam_events(deadlines, exam_cat) if deadlines else []
    events = sorted(dated + exams, key=lambda e: (e["date"], e["start"]))
    return {"exists": exists, "events": events, "pending": pending,
            "bad": bad, "hasDeadlines": deadlines is not None, "major": major,
            "configured": any(c.get("name") for c in cfg.get("categories") or []),
            "legend": legend(ctx, events + pending), "source": ctx.file_url(path)}
