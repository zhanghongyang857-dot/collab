#!/usr/bin/env python3
"""把 schedule.md 里日期早于今天的行移到 archive/YYYY-MM.md（按月一个文件，表格格式与 schedule.md 相同）。

用法：python3 archive.py --now-dir <NOW 目录>   （也可用环境变量 NOW_DATA_DIR；都没有时与本脚本同目录）
      加 --dry-run 只列出要移的行，不改文件
      加 --before YYYY-MM-DD 把这天之前的行归档（默认今天）
同一行已在归档里时不重复写；归档内按日期排序，同一天保持原顺序。「收工」时运行。
"""
import datetime as dt
import os
import re
import sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "core"))
import paths as P  # noqa: E402  数据文件名

HEAD = "| 日期 | 时段 | 事项 | 任务 |"
SEP = "|---|---|---|---|"


def _data_dir():
    if "--now-dir" in sys.argv[:-1]:
        return Path(sys.argv[sys.argv.index("--now-dir") + 1]).expanduser().resolve()
    env = os.environ.get("NOW_DATA_DIR")
    return Path(env).expanduser().resolve() if env else Path(__file__).resolve().parent


def row_date(line, today):
    """表格行的日期；MM-DD 不写年份时取离今天最近的那一年（12 月写 01-03 算下一年）。"""
    cell = line.strip().strip("|").split("|")[0].strip()
    m = re.match(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})$", cell)
    if not m:
        return None
    mo, d = int(m.group(2)), int(m.group(3))
    cands = []
    for y in ([int(m.group(1))] if m.group(1) else [today.year - 1, today.year, today.year + 1]):
        try:
            cands.append(dt.date(y, mo, d))
        except ValueError:  # 02-29 在平年不存在；02-30 哪年都不存在，当作不是日期行
            pass
    return min(cands, key=lambda x: abs((x - today).days)) if cands else None


def main():
    here = _data_dir()
    plan = here / P.SCHEDULE
    if not plan.exists():
        sys.exit(f"未找到 {plan}")
    today = dt.date.today()
    if "--before" in sys.argv[:-1]:
        today = dt.date.fromisoformat(sys.argv[sys.argv.index("--before") + 1])
    dry = "--dry-run" in sys.argv

    lines = plan.read_text(encoding="utf-8").splitlines()
    keep, moved = [], {}  # moved: "YYYY-MM" → [(date, 行)]
    for line in lines:
        d = row_date(line, today) if line.lstrip().startswith("|") else None
        if d and d < today:
            moved.setdefault(f"{d:%Y-%m}", []).append((d, line.strip()))
        else:
            keep.append(line)
    if not moved:
        print("没有需要归档的行")
        return

    for month, rows in sorted(moved.items()):
        f = here / P.ARCHIVE / f"{month}.md"
        old = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
        have = [(row_date(l, today), l.strip()) for l in old if l.lstrip().startswith("|") and row_date(l, today)]
        seen = {l for _, l in have}
        new = [(d, l) for d, l in rows if l not in seen]
        print(f"{'将移' if dry else '已移'} {len(rows)} 行 → 归档/{month}.md" + (f"（{len(rows) - len(new)} 行已在归档里）" if len(new) < len(rows) else ""))
        if dry:
            continue
        allrows = sorted(have + new, key=lambda x: x[0])  # 稳定排序：同一天保持原顺序
        f.parent.mkdir(exist_ok=True)
        f.write_text(f"# 安排归档 {month}\n[← 安排](../schedule.md)\n\n{HEAD}\n{SEP}\n"
                     + "\n".join(l for _, l in allrows) + "\n", encoding="utf-8")
    if not dry:
        plan.write_text("\n".join(keep) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
