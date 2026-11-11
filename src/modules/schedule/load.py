"""安排模块：读 schedule.md（旧版用 今天.md）和 month.md，给「今天」「短期」两页和「任务」页下面的本月布局。"""
import re
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "core"))
import paths as P  # noqa: E402  数据文件名
import i18n  # noqa: E402  NOW 数据的表头按代码认列

# 「短期」视图的时间段：每段从 start 起到下一段 start；可在 config.json 的 schedule.plan_slots 覆盖，hint 显示在段名下
DEFAULT_SLOTS = [{"name": "上午", "start": "00:00"}, {"name": "下午", "start": "13:00"}, {"name": "晚上", "start": "18:00"}]


def parse_today(ctx, path):
    """旧版数据：没有 schedule.md 时「今天」页读 今天.md。"""
    if not path.exists():
        return {"date": "", "weekday": "", "note": "", "slots": [], "extras": []}
    here = ctx.data_dir
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    m = re.search(r"^## (\d{2}-\d{2})（(周.)）", text, re.M)
    note = " ".join(l.lstrip("> ").strip() for l in lines if l.startswith(">"))
    _, rows = ctx.table_rows(lines)
    slots, extras = [], []
    for when, what, task in (r[:3] for r in rows):
        t = re.match(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})", when)
        if t:
            slots.append({"start": t.group(1), "end": t.group(2), "what": ctx.inline(what, here),
                          "task": task if task not in ("—", "-") else "", "cat": ctx.category(task)})
        else:
            extras.append({"label": when, "what": ctx.inline(what, here)})
    return {"date": m.group(1) if m else "", "weekday": m.group(2) if m else "",
            "note": ctx.inline(note, here), "slots": slots, "extras": extras}


def parse_plan(ctx, path, slots):
    """schedule.md：一张表，每行一件事 `| 日期 | 时段 | 事项 | 任务 |`。日期 MM-DD 或 YYYY-MM-DD；
    时段写时间（15:00–16:00）或时间段名（上午），留空为全天，`备注` 为当天说明。`**…**` 为节点，`*…*` 为虚线块。
    「今天」和「短期」两个视图都从这里取；过去的行由 archive.py 移到 archive/YYYY-MM.md。"""
    out = {"exists": path.exists(), "slots": slots, "items": []}
    if not out["exists"]:
        return out
    for r in map(i18n.cols, ctx.table_dicts(path.read_text(encoding="utf-8").splitlines())):  # 表头按代码认列
        m = re.match(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})", r.get("date", "").strip())
        what = r.get("item", "").strip()
        if not m or not what:
            continue
        when = r.get("slot", "").strip()
        if i18n.code_of("now_col", when) == "note":  # 时段写「备注」/「note」：当天说明
            when = "note"
        t = re.match(r"(\d{1,2}:\d{2})(?:\s*[–-]\s*(\d{1,2}:\d{2}))?", when)
        kind = "node" if what.startswith("**") and what.endswith("**") else \
            "light" if re.fullmatch(r"\*[^*].*\*", what) else "plain"
        what = what.strip("*") if kind != "plain" else what
        task = r.get("task", "").strip()
        out["items"].append({
            "date": f"{int(m.group(2)):02d}-{int(m.group(3)):02d}", "year": m.group(1) or "",
            "when": when, "start": t.group(1) if t else "", "end": (t.group(2) or "") if t else "",
            "what": ctx.inline(what, ctx.data_dir), "kind": kind,
            "task": task if task not in ("—", "-") else "", "cat": ctx.category(task)})
    return out


def archived_items(ctx, slots, current):
    """archive/YYYY-MM.md 里的行，年份取文件名；schedule.md 里还留着同一行时不重复。只给其他模块（provide），页面不用。"""
    seen = {(it["date"], it["when"], it["what"]) for it in current}
    out = []
    for f in sorted((ctx.data_dir / P.ARCHIVE).glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md")):
        ctx.watch(f)
        for it in parse_plan(ctx, f, slots)["items"]:
            if (it["date"], it["when"], it["what"]) not in seen:
                out.append({**it, "year": it["year"] or f.stem[:4]})
    return out


THREE_TITLES = ("本周三件事", "This week")  # month.md 里「本周三件事」一节的标题，中英文都认


def parse_month(ctx, path):
    empty = {"range": "", "intro": "", "pending": [], "cols": [], "colCats": [], "weeks": [],
             "three_title": "", "three": [], "exists": False}
    if not path.exists():
        return empty
    here = ctx.data_dir
    secs = ctx.sections(path.read_text(encoding="utf-8"))
    rng, lines = next(((t, l) for t, l in secs if t and not t.startswith(THREE_TITLES)), ("", []))
    paras = [l for l in lines if l.strip() and not l.startswith(("#", "|", "[←"))]
    head, rows = ctx.table_rows(lines) if any(l.lstrip().startswith("|") for l in lines) else ([""], [])
    weeks = []
    for r in rows:
        w = re.match(r"(第\s*\d+\s*周|Week\s*\d+)\s*(\d{2}-\d{2})[～~](\d{2}-)?(\d{2})", r[0])
        weeks.append({
            "label": w.group(1) if w else r[0],
            "start": w.group(2) if w else "",
            "end": ((w.group(3) or w.group(2)[:3]) + w.group(4)) if w else "",
            "range": r[0][w.end(1):].strip() if w else "",
            "cells": [ctx.inline(c, here) for c in r[1:]],
        })
    wt, wl = next(((t, l) for t, l in secs if t.startswith(THREE_TITLES)), ("", []))
    three = [ctx.inline(re.sub(r"^\d+\.\s*", "", l.strip()), here) for l in wl if re.match(r"\s*\d+\.", l)]
    return {"range": rng, "intro": ctx.inline(paras[0], here) if paras else "",
            "pending": [ctx.inline(p, here) for p in paras[1:]], "cols": head[1:],
            "colCats": [ctx.category(c) for c in head[1:]], "weeks": weeks,
            "three_title": wt, "three": three, "exists": True}


def load(ctx):
    here = ctx.data_dir
    plan_md, today_md, month_md = here / P.SCHEDULE, here / "今天.md", here / P.MONTH
    # plan_slots 原来写在 config.json 顶层，兼容旧配置
    slots = ctx.config.get("plan_slots") or ctx.root_config.get("plan_slots") or DEFAULT_SLOTS
    plan = parse_plan(ctx, plan_md, slots)
    ctx.provide("plan", {**plan, "items": archived_items(ctx, slots, plan["items"]) + plan["items"]})
    if not plan["exists"]:
        ctx.watch(today_md)
    return {
        "plan": plan,
        "today": parse_today(ctx, today_md) if not plan["exists"] else None,
        "month": parse_month(ctx, month_md),
        "sources": {"plan": ctx.file_url(plan_md), "today": ctx.file_url(today_md), "month": ctx.file_url(month_md)},
    }
