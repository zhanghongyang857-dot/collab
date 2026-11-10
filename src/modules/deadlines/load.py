"""截止模块：读 config.json 里 deadlines.file 指定的截止文件，给「今天」页右栏的近期截止。

截止文件格式：`## 分组 …` 下的 `- **事项（权重）**：… **YYYY-MM-DD（周X）时间**…`。
写「暂定」「待公告」会显示对应标记，事项名含 final_keyword（默认「期末」）的单独列出。
"""
import re


def parse(ctx, path):
    cfg = ctx.config
    groups = cfg.get("groups") or []  # 只显示这些分组（标题第一个词）；为空则全部显示
    final_kw = cfg.get("final_keyword", "期末")
    items, course = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            course = line[3:].split()[0] if line[3:].strip() else None
            continue
        if not course or (groups and course not in groups) or not line.startswith("- **"):
            continue
        d = re.search(r"\*\*(\d{4}-\d{2}-\d{2})（(周.)）([^*]*)\*\*", line)
        name = re.match(r"- \*\*(.+?)\*\*", line).group(1)
        if not d:
            continue
        w = re.search(r"（(\d+%)）", name)
        title = re.sub(r"（\d+%）", "", name)
        items.append({"date": d.group(1), "weekday": d.group(2), "time": d.group(3).strip(),
                      "course": course, "title": title, "weight": w.group(1) if w else "",
                      "final": final_kw in title,
                      "tentative": "暂定" in line, "pending": "待公告" in line})
    items.sort(key=lambda x: x["date"])
    return items


def load(ctx):
    cfg = ctx.config
    path = ctx.path(cfg.get("file"))
    if path:
        ctx.watch(path)
    items = parse(ctx, path) if path and path.exists() else []
    ctx.provide("deadlines", items)
    return {
        "items": items,
        "note": cfg.get("note", ""),
        "cat": ctx.category(cfg["category"]) if cfg.get("category") else "other",
        "source": ctx.file_url(path) if path else "",
    }
