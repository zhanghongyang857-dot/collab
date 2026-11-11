#!/usr/bin/env python3
"""NOW 里项目的注册和注销：只改 NOW.md「任务」表和 NOW/done.md，项目文件和 collab/ 原样不动。

用法（一般由 init.sh 调用）：
  now_rows.py register   <NOW.md> <PROGRESS.md> <项目名>            加进「任务」表（状态进行中）；在「已完成」里的移回来，保留分类
  now_rows.py unregister <NOW.md> <PROGRESS.md> [--result 一句话] [--drop]   从「任务」表移到「已完成」（补完成日期和结果）；--drop 直接删去
输出一个词给 init.sh：added / restored / exists / moved / dropped / missing / notable。只用 Python 标准库。
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths as P  # noqa: E402
import i18n  # noqa: E402

LINK = re.compile(r"\]\(<?([^)>]+)>?\)")
TASK_COL = "|".join(re.escape(x) for x in i18n.names("now_col", "task"))  # 「任务」列：中英两种表头都认
HEAD = re.compile(r"(?m)^\|[ \t]*(?:%s)[ \t]*\|.*\n\|[-| :]+\|[ \t]*\n" % TASK_COL)
SECTION = "now_projects"  # NOW.md 的「## 任务」一节（英文 ## Projects）


def table_end(text: str, sec_title: Optional[str]) -> Optional[int]:
    """表头（含分隔行）之后的位置；sec_title 给出时只在该二级标题之后找。"""
    start = 0
    if sec_title:
        titles = i18n.headings(sec_title) if i18n.code_of("section", sec_title) == sec_title else [sec_title]
        sec = re.search(r"(?m)^## (?:%s)\s*$" % "|".join(map(re.escape, titles)), text)
        if not sec:
            return None
        start = sec.end()
    m = HEAD.search(text, start)
    return m.end() if m else None


def find_row(text: str, base: Path, prog: Path, start: int) -> Optional[Tuple[int, int, List[str]]]:
    """表里链接到 prog 的那一行：(行首, 行尾含换行, 各格)。"""
    pos = start
    for line in text[start:].splitlines(keepends=True):
        if not line.startswith("|"):
            break
        for m in LINK.finditer(line):
            if os.path.normpath(base / m.group(1)) == os.path.normpath(prog):
                return pos, pos + len(line), [c.strip() for c in line.strip().strip("|").split("|")]
        pos += len(line)
    return None


def label_of(cell: str) -> str:
    """「[名称](<路径>)」里的名称。"""
    return LINK.split(cell)[0].lstrip("[")


def now_pack(now: Path) -> "i18n.Pack":
    """NOW 的语言：NOW/config.json 的 lang；没写的旧 NOW 是中文。"""
    try:
        lang = json.loads((now.parent / "NOW" / "config.json").read_text(encoding="utf-8")).get("lang") or "zh"
    except (OSError, ValueError):
        lang = "zh"
    return i18n.pack(lang if lang in i18n.LANGS else "zh")


def done_head(now: Path) -> str:
    L = now_pack(now)
    return "| " + " | ".join(L.name("now_col", c) for c in ("task", "category", "done_on", "result")) + " |\n|---|---|---|---|\n"


def register(now: Path, prog: Path, name: str) -> str:
    text = now.read_text(encoding="utf-8")
    end = table_end(text, SECTION)
    if end is None:
        return "notable"
    if find_row(text, now.parent, prog, end):
        return "exists"
    cat, how = "", "added"
    done = now.parent / "NOW" / P.DONE
    if done.exists():
        dt_text = done.read_text(encoding="utf-8")
        dend = table_end(dt_text, None)
        hit = find_row(dt_text, done.parent, prog, dend) if dend is not None else None
        if hit:
            a, b, cells = hit
            cat, how, name = (cells[1] if len(cells) > 1 else ""), "restored", label_of(cells[0])
            done.write_text(dt_text[:a] + dt_text[b:], encoding="utf-8")
    row = "| [%s](<%s>) | %s |  | %s |\n" % (name, os.path.relpath(prog, now.parent), cat, now_pack(now).st("active"))
    now.write_text(text[:end] + row + text[end:], encoding="utf-8")
    return how


def unregister(now: Path, prog: Path, result: str, drop: bool) -> str:
    text = now.read_text(encoding="utf-8")
    end = table_end(text, SECTION)
    hit = find_row(text, now.parent, prog, end) if end is not None else None
    if not hit:
        return "missing"
    a, b, cells = hit
    now.write_text(text[:a] + text[b:], encoding="utf-8")
    if drop:
        return "dropped"
    done = now.parent / "NOW" / P.DONE
    if not done.exists():
        done.parent.mkdir(parents=True, exist_ok=True)
        done.write_text("# " + now_pack(now).t("now.done_title") + "\n\n" + done_head(now), encoding="utf-8")
    dt_text = done.read_text(encoding="utf-8")
    dend = table_end(dt_text, None)
    if dend is None:
        dt_text = dt_text.rstrip("\n") + "\n\n" + done_head(now)
        dend = len(dt_text)
    row = "| [%s](<%s>) | %s | %s | %s |\n" % (label_of(cells[0]), os.path.relpath(prog, done.parent),
                                             cells[1] if len(cells) > 1 else "", dt.date.today().isoformat(), result)
    done.write_text(dt_text[:dend] + row + dt_text[dend:], encoding="utf-8")
    return "moved"


def main(argv: List[str]) -> int:
    if len(argv) >= 4 and argv[0] == "register":
        print(register(Path(argv[1]), Path(argv[2]).resolve(), argv[3]))
        return 0
    if len(argv) >= 3 and argv[0] == "unregister":
        rest = argv[3:]
        result = rest[rest.index("--result") + 1] if "--result" in rest[:-1] else ""
        print(unregister(Path(argv[1]), Path(argv[2]).resolve(), result, "--drop" in rest))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
