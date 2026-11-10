"""对照模块：读专注记录的导出文件和安排模块提供的计划，算每天的完成度和本周分类占比。

导出格式见 README.md；compute() 不碰文件，方便测试。所有时间按导出里写的本地时间算，不换时区。
"""
import datetime as dt
import json
import re

FORMAT, VERSION = "work-rhythm.focus", 1
STALE_MINUTES = 120  # 导出超过这么久没更新、又没有正在计时的，提示来源可能没在运行
DAYS = 7
ACTIVE_FRESH = 5  # 计时中导出每分钟更新；超过这么久（分钟）没更新，说明计时已经断了（崩溃、断电、关了导出）
NO_FOLDER = "未分类"


def norm(name):
    """活动名比较时不管空格和大小写：`AI 工具探索` 和 `AI工具探索` 是同一个。"""
    return re.sub(r"\s+", "", name).casefold()


def resolve_date(item, today):
    """计划行的日期；没写年份时取离今天最近的那一年。日期不存在（如 02-30）时返回 None。"""
    month, day = map(int, item["date"].split("-"))
    if item.get("year"):
        try:
            return dt.date(int(item["year"]), month, day)
        except ValueError:
            return None
    cands = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            cands.append(dt.date(y, month, day))
        except ValueError:  # 02-29
            pass
    return min(cands, key=lambda x: abs((x - today).days)) if cands else None


def split_task(task):
    """`分类（活动）` → (分类, 活动)；没有括号时活动就是分类本身。"""
    m = re.match(r"\s*([^（(]*?)\s*[（(](.+)[）)]\s*$", task)
    return (m.group(1), m.group(2)) if m else (task.strip(), task.strip())


def plan_minutes(item):
    """定量计划行的分钟数；只写时间段名或只写开始时间的返回 None。"""
    if not (item.get("start") and item.get("end")):
        return None
    h1, m1 = map(int, item["start"].split(":"))
    h2, m2 = map(int, item["end"].split(":"))
    return (h2 * 60 + m2 - h1 * 60 - m1) % 1440  # 23:30–00:30 跨午夜也算对


def plans_by_day(items, today, category):
    """{日期: {"rows": {规范化的活动名: {name, cat, catName, min}}, "unquant": 条数}}。不计时、备注、全天行都不算。"""
    days = {}
    for it in items:
        if it.get("when") == "备注" or it.get("cat") == "rest" or not it.get("task") or not it.get("when"):
            continue
        date = resolve_date(it, today)
        if date is None:
            continue
        day = days.setdefault(date, {"rows": {}, "unquant": 0})
        minutes = plan_minutes(it)
        if minutes is None:
            day["unquant"] += 1
            continue
        cat_name, activity = split_task(it["task"])
        row = day["rows"].setdefault(norm(activity), {"name": activity, "cat": category(it["task"]), "catName": cat_name, "min": 0})
        row["min"] += minutes
    return days


def parse_time(s):
    """带时区的本地时间 → 钟面时间；不是合法时间时返回 None。"""
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except (AttributeError, TypeError, ValueError):
        return None


def split_days(start, end):
    """一段时间按本地日期切开：[(日期, 开始, 结束)]。"""
    out = []
    while start.date() < end.date():
        midnight = dt.datetime.combine(start.date() + dt.timedelta(days=1), dt.time())
        out.append((start.date(), start, midnight))
        start = midnight
    if end > start:
        out.append((start.date(), start, end))
    return out


def actual_segments(export, folder_map, category, active_end, live):
    """导出记录 → 按日切开的段，加上 active 那段（到 active_end）；文件夹按 folder_map 换成分类名。
    返回 (段, 跳过的坏记录条数)；一条记录坏了只丢它自己。"""
    segs, skipped = [], 0
    records = export.get("records")
    items = [(r, False) for r in records] if isinstance(records, list) else []
    active = export.get("active")
    if isinstance(active, dict):
        items.append((active, True))
    for rec, is_active in items:
        if not isinstance(rec, dict):
            skipped += 1
            continue
        t0, t1 = parse_time(rec.get("start")), active_end if is_active else parse_time(rec.get("end"))
        if t0 is None or t1 is None:
            skipped += 1
            continue
        folder = rec.get("folder") or NO_FOLDER
        cat_name = folder_map.get(folder, folder)
        for i, (day, a, b) in enumerate(split_days(t0, t1)):
            segs.append({"day": day, "start": a, "end": b, "minutes": (b - a).total_seconds() / 60, "activity": rec.get("activity") or "?",
                         "catName": cat_name, "cat": category(cat_name), "live": is_active and live, "continued": i > 0})
    return segs, skipped


def group_cats(pairs):
    """[(颜色键, 分钟)] → 按颜色键合并，保持首次出现的顺序。"""
    out = {}
    for cat, minutes in pairs:
        if minutes > 0:
            out[cat] = out.get(cat, 0) + minutes
    return [{"cat": c, "min": round(m)} for c, m in out.items()]


def day_summary(day, plan, segs):
    """一天的指标。先按活动名对；只写了分类的计划行，再收同分类里没被计划点名的活动；其余算计划外。"""
    plan_rows = plan["rows"] if plan else {}
    actual = {}
    for s in segs:
        a = actual.setdefault(norm(s["activity"]), {"name": s["activity"], "min": 0, "cat": s["cat"], "catName": s["catName"]})
        a["min"] += s["minutes"]
    rows = {key: {"activity": p["name"], "cat": p["cat"], "plan": p["min"], "actual": 0.0} for key, p in plan_rows.items()}
    for key, a in actual.items():
        if key in plan_rows:
            rows[key]["actual"] += a["min"]
    for key, a in actual.items():
        if key in plan_rows:
            continue
        # 分类行：计划写的是分类本身（活动名 = 分类名）
        host = norm(a["catName"])
        if host in plan_rows and norm(plan_rows[host]["catName"]) == host:
            rows[host]["actual"] += a["min"]
        else:
            rows[key] = {"activity": a["name"], "cat": a["cat"], "plan": 0, "actual": a["min"]}
    plan_total = sum(r["plan"] for r in rows.values())
    actual_total = sum(r["actual"] for r in rows.values())
    matched = sum(min(r["plan"], r["actual"]) for r in rows.values())
    table = sorted(({**r, "actual": round(r["actual"]), "diff": round(r["actual"] - r["plan"])} for r in rows.values()),
                   key=lambda r: (-abs(r["diff"]), r["diff"]))  # 偏差最大的在前；一样大时没做的在前
    first = min((s["start"] for s in segs if not s["continued"]), default=None)  # 前一天跨过来的不算首次专注
    return {
        "date": day.isoformat(),
        "weekday": "一二三四五六日"[day.weekday()],
        "planMin": plan_total,
        "actualMin": round(actual_total),
        "completion": round(matched / plan_total * 100) if plan_total else None,
        "missing": [{"activity": r["activity"], "min": r["plan"] - r["actual"]} for r in table if r["actual"] < r["plan"]],
        "unplannedMin": round(sum(max(0, r["actual"] - r["plan"]) for r in rows.values())),
        "firstFocus": first.strftime("%H:%M") if first else "",
        "unquant": plan["unquant"] if plan else 0,
        "planSegs": group_cats((r["cat"], r["plan"]) for r in rows.values()),
        "actualSegs": group_cats((r["cat"], min(r["plan"], r["actual"])) for r in rows.values()),
        "rows": table,
    }


def parse_budget(text):
    """">=25"、"<=30"、"25-30" → (下限, 上限)；认不出来时都是 None。"""
    s = str(text).replace("≥", ">=").replace("≤", "<=").replace("–", "-").replace("%", "").strip()
    m = re.fullmatch(r"(>=|<=)\s*(\d+(?:\.\d+)?)", s)
    if m:
        v = float(m.group(2))
        return (v, None) if m.group(1) == ">=" else (None, v)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", s)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def week_summary(segs, budgets, today, week_start, category):
    offset = (today.weekday() + 1) % 7 if week_start == "sun" else today.weekday()
    start = today - dt.timedelta(days=offset)
    totals = {}
    for s in segs:
        if start <= s["day"] <= today:
            totals[s["catName"]] = totals.get(s["catName"], 0) + s["minutes"]
    total = sum(totals.values())
    rows = []
    for name in [*budgets, *(n for n in sorted(totals, key=lambda n: -totals[n]) if n not in budgets)]:
        minutes = totals.get(name, 0)
        pct = minutes / total * 100 if total else 0
        low, high = parse_budget(budgets[name]) if name in budgets else (None, None)
        state = "none"
        if total and (low is not None or high is not None):
            state = "under" if low is not None and pct < low else "over" if high is not None and pct > high else "ok"
        rows.append({"name": name, "cat": category(name), "min": round(minutes), "pct": round(pct, 1),
                     "low": low, "high": high, "budget": str(budgets.get(name, "")), "state": state})
    return {"start": start.isoformat(), "end": today.isoformat(), "totalMin": round(total), "rows": rows}


def compute(export, items, cfg, today, now, category):
    """由导出和计划算出页面要的全部数字；export 已核对过 format、version。"""
    generated = parse_time(export.get("generated_at"))
    age = (now - generated).total_seconds() / 60 if generated else None
    active = export.get("active") if isinstance(export.get("active"), dict) else None
    # 导出很久没更新却还写着在计时：计时已经断了，那段只算到最后一次导出
    dead = bool(active and (age is None or age > ACTIVE_FRESH))
    segs, skipped = actual_segments(export, cfg.get("folder_map") or {}, category, generated if dead else now, not dead)
    live_start = parse_time(active.get("start")) if active and not dead else None
    plans = plans_by_day(items, today, category)
    by_day = {}
    for s in segs:
        by_day.setdefault(s["day"], []).append(s)
    days = [today - dt.timedelta(days=i) for i in range(DAYS)]
    summaries = [day_summary(d, plans.get(d), by_day.get(d, [])) for d in days]
    return {
        "status": "ok",
        "generatedAt": generated.strftime("%m-%d %H:%M") if generated else "",
        "ageMin": round(age) if age is not None else None,
        "stale": dead or bool(age is not None and age > STALE_MINUTES and not active),
        "active": {"activity": active.get("activity") or "?", "start": live_start.strftime("%H:%M")} if live_start else None,
        "skipped": skipped,
        "today": summaries[0],
        "todaySegs": [{"a": s["start"].hour * 60 + s["start"].minute + s["start"].second / 60,
                       "b": (s["end"] - dt.datetime.combine(today, dt.time())).total_seconds() / 60,
                       "cat": s["cat"], "activity": s["activity"], "live": s["live"]}
                      for s in by_day.get(today, [])],
        "days": summaries,
        "week": week_summary(segs, cfg.get("budgets") or {}, today, cfg.get("week_start", "mon"), category),
    }


def load(ctx):
    cfg = ctx.config
    if not cfg.get("file"):
        return {"status": "off", "message": "还没有配置：在 config.json 加一节 focus，写明导出文件 file，见模块 README。"}
    path = ctx.path(cfg["file"])
    ctx.watch(path)
    if not path.exists():
        return {"status": "missing", "message": f"还没有读到导出文件 {path}：确认专注应用已开启导出，并计时一段。"}
    try:
        export = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return {"status": "bad", "message": f"导出文件读不了：{e}"}
    if not isinstance(export, dict):
        return {"status": "bad", "message": "导出文件读不了：内容不是一个 JSON 对象。"}
    if export.get("format") != FORMAT or export.get("version") != VERSION:
        return {"status": "bad", "message": f"导出文件格式是 {export.get('format')} v{export.get('version')}，本模块只认 {FORMAT} v{VERSION}。"}
    plan = ctx.get("plan") or {"items": []}
    return compute(export, plan["items"], cfg, ctx.today, dt.datetime.now(), ctx.category)
