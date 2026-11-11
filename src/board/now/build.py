#!/usr/bin/env python3
"""NOW 看板 = 核心 + 模块。核心读 NOW.md（任务、大方向）、各任务 PROGRESS.md 和 done.md，生成「任务」页；
其余标签页和小卡片由模块提供（工具包 modules/<id>/，或 NOW 数据目录下的 模块/<id>/），在 config.json 的
`modules` 里打开。没写 `modules` 时启用 schedule（今天、短期）和 deadlines（近期截止），和拆分前一样。

用法：python3 NOW/build.py
      python3 NOW/build.py --if-changed   只在源文件比看板新时生成（供 Claude Code Stop hook 调用）
      python3 build.py --now-dir <NOW 目录>  代码和数据分开放时指定数据目录（也可用环境变量 NOW_DATA_DIR）
内容只改 Markdown；分类、配色、模块和各模块的设置改 config.json；外框改 template.html，模块改 modules/<id>/。
模块约定见 modules/README.md。
"""
import datetime as dt
import html
import importlib.util
import json
import os
import re
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlsplit

CODE = Path(__file__).resolve().parent  # 本脚本和 template.html 所在目录
sys.path.insert(0, str(CODE.parent.parent / "core"))
import paths as P  # noqa: E402
from vocab import Section  # noqa: E402
import i18n  # noqa: E402
CONTRACT = 1  # 模块约定版本；module.json 的 contract 不同就不加载
DEFAULT_MODULES = ["schedule", "deadlines"]  # config.json 没写 modules 时启用


def _data_dir():
    """NOW 数据目录：--now-dir、环境变量 NOW_DATA_DIR，都没有时与代码同目录。"""
    if "--now-dir" in sys.argv[:-1]:
        return Path(sys.argv[sys.argv.index("--now-dir") + 1]).expanduser().resolve()
    env = os.environ.get("NOW_DATA_DIR")
    return Path(env).expanduser().resolve() if env else CODE


HERE = _data_dir()
CONFIG = HERE / "config.json"


def _load_config():
    """个人设置都在 config.json：分类与配色、启用的模块、各模块自己的一节。缺省时用通用分类。"""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    cfg.setdefault("categories", [])
    cfg.setdefault("rest_keywords", ["不计时", "untracked"])
    return cfg


def _path(p, default=None):
    if not p:
        return default
    p = Path(p).expanduser()
    return p if p.is_absolute() else (HERE / p).resolve()


CFG = _load_config()
NOW_MD = _path(CFG.get("now_md"), HERE.parent / "NOW.md")
DONE_MD = HERE / P.DONE
DONE_SHOW = CFG.get("done_show", 5)  # 看板上显示最近几条已完成
TEMPLATE = CODE / "template.html"
OUT = _path(CFG.get("output"), HERE / "board.html")  # 可在 config.json 用 output 指定生成位置
# 模块目录：工具包自带的，和 NOW 数据目录下 模块/ 里另装的（同 id 时后者优先）
MODULE_DIRS = [CODE.parent.parent / "modules", HERE / P.NOW_MODULES]

# 关键词 → 分类配色键（顺序即优先级）：先「不计时」，再按 config 中分类的顺序
CATEGORIES = [(k, "rest") for k in CFG["rest_keywords"]] + [
    (k, "cat-" + c["color"]) for c in CFG["categories"] for k in c.get("keywords", [c["name"]])
]
LANG = CFG.get("lang") if CFG.get("lang") in i18n.LANGS else ("zh" if CONFIG.exists() and "lang" not in CFG else "en")  # 没写 lang 的旧 NOW 是中文
L = i18n.pack(LANG)
CAT_NAMES = {"other": L.t("now.cat.other"), "rest": L.t("now.cat.rest"), **{"cat-" + c["color"]: c["name"] for c in reversed(CFG["categories"])}}


def inline(text, base):
    """Markdown 行内语法 → HTML：链接、粗体、斜体、删除线、代码。"""
    out, pos = [], 0
    for m in re.finditer(r"\[([^\]]+)\]\(<?([^)>]+)>?\)", text):
        out.append(_fmt(text[pos:m.start()]))
        href = m.group(2)
        if not re.match(r"[a-z]+:", href):
            href = "file://" + quote(str((base / href).resolve()))
        out.append(f'<a href="{html.escape(href)}">{_fmt(m.group(1))}</a>')
        pos = m.end()
    out.append(_fmt(text[pos:]))
    return "".join(out)


def _fmt(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?![*\w])", r"<em>\1</em>", t)  # 前后贴字的不算，如 3*4*5
    t = re.sub(r"~~(.+?)~~", r"<del>\1</del>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


def table_rows(lines):
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines if l.lstrip().startswith("|")]
    return rows[0], [r for r in rows[2:]]


def category(task):
    for key, cat in CATEGORIES:
        if key in task:
            return cat
    return "other"


def sections(text):
    """按 `## ` 标题切分，返回 [(标题, 行列表)]；标题前的内容标题为空串。"""
    out, title, buf = [], "", []
    for line in text.splitlines():
        if line.startswith("## "):
            out.append((title, buf))
            title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out.append((title, buf))
    return out


def find_section(secs, prefix):
    """按标题开头找一节；prefix 是小节代码（next、status…）时中英两种标题都认。"""
    prefixes = tuple(i18n.headings(prefix)) if i18n.code_of("section", prefix) == prefix else (prefix,)
    for title, lines in secs:
        if title.startswith(prefixes):
            return title, lines
    return "", []


def link_parts(cell, base):
    """表格单元里的 [名称](路径) → (名称, 绝对路径或 None)。"""
    m = re.search(r"\[([^\]]+)\]\(<?([^)>]+)>?\)", cell)
    if not m:
        return cell, None
    return m.group(1), (base / m.group(2)).resolve()


def table_dicts(lines):
    if not any(l.lstrip().startswith("|") for l in lines):
        return []
    head, rows = table_rows(lines)
    return [dict(zip(head, r)) for r in rows]


def placeholder(t):
    t = re.sub(r"（[^（）]*）$", "", t.strip())  # 去掉结尾的来源注记，如“待填（日历）”
    return not t or (t.startswith("<") and t.endswith(">")) or t in ("待填", "…")


def file_url(path):
    return "file://" + quote(str(path)) if path else ""


def parse_progress(path):
    """从任务的 PROGRESS.md 读取：目标、截止、状态、▶ 下一步、卡点数、最近日志日期。"""
    if not path or not path.exists():
        return {"missing": True}
    text = path.read_text(encoding="utf-8")
    base = path.parent
    info = {"missing": False, "href": "file://" + quote(str(path))}
    for code, keys in (("goal", ("目标：", "Goal:")), ("due", ("截止：", "Due:")), ("status", ("状态：", "Status:"))):  # PROGRESS 标题下那行，中英两种写法
        m = re.search("(?:" + "|".join(map(re.escape, keys)) + r")\s*([^｜\n]*)", text)
        v = m.group(1).strip() if m else ""
        info[code] = "" if placeholder(v) else v
    secs = sections(text)
    _, nl = find_section(secs, Section.NEXT)
    nxt = " ".join(l.strip() for l in nl if l.strip() and not placeholder(l))
    info["next"] = inline(nxt, base) if nxt else ""
    _, bl = find_section(secs, Section.BLOCKERS)
    info["blockers"] = sum(1 for l in bl if l.strip().startswith("- ") and not placeholder(l.strip()[2:]))
    log = log_lines(path, secs)
    m = next((re.match(r"^### (\d{4}-\d{2}-\d{2})", l) for l in log if l.startswith("### ")), None)
    info["last"] = m.group(1) if m else ""
    info["activity"] = log_activity(log)
    return info


def log_lines(path, secs):
    """日志行：优先同目录的 日志.md（v3），否则 PROGRESS.md 的「日志」一节（v1/v2）。"""
    f = path.parent / P.LOG
    if f.exists():
        return f.read_text(encoding="utf-8").splitlines()
    return find_section(secs, "日志")[1]


def log_activity(lines):
    """日志中每个 `### YYYY-MM-DD` 下的条目数 → {日期: 条数}，用于近 14 天活跃度格子。"""
    act, day = {}, None
    for l in lines:
        m = re.match(r"^### (\d{4}-\d{2}-\d{2})", l)
        if m:
            day = m.group(1)
            act.setdefault(day, 0)
        elif day and l.lstrip().startswith("- "):
            act[day] += 1
    return act


def parse_now():
    if not NOW_MD.exists():
        return {"tasks": [], "dirTitle": "", "dirs": []}
    secs = sections(NOW_MD.read_text(encoding="utf-8"))
    base = NOW_MD.parent
    tasks = []
    for r in map(i18n.cols, table_dicts(find_section(secs, "now_projects")[1])):  # 表头按代码认列
        name, path = link_parts(r.get("task", ""), base)
        cat = r.get("category", "")
        st = r.get("state", "")
        tasks.append({"name": name, "cat": category(cat), "catName": cat, "level": r.get("level", ""),
                      "state": i18n.code_of("state", st) or st, **parse_progress(path)})
    dt_title, dl = find_section(secs, "directions")
    dirs = [{"name": r.get("direction", ""), "goal": inline(r.get("six_month", ""), base),
             "milestones": inline(r.get("milestones", ""), base), "share": r.get("share", ""),
             "cat": category(r.get("direction", ""))} for r in map(i18n.cols, table_dicts(dl))]
    return {"tasks": tasks, "dirTitle": dt_title, "dirs": dirs}


def parse_done():
    if not DONE_MD.exists():
        return {"total": 0, "items": []}
    lines = DONE_MD.read_text(encoding="utf-8").splitlines()
    items = []
    for r in map(i18n.cols, table_dicts(lines)):
        name, path = link_parts(r.get("task", ""), DONE_MD.parent)
        items.append({"name": name, "href": "file://" + quote(str(path)) if path else "",
                      "cat": category(r.get("category", "")), "date": r.get("done_on", ""),
                      "result": inline(r.get("result", ""), DONE_MD.parent)})
    return {"total": len(items), "items": items[:DONE_SHOW]}


# ---------- 模块 ----------

def find_modules():
    """所有可用模块 {id: 目录}：按 MODULE_DIRS 顺序扫描，后面的同 id 覆盖前面的。"""
    found = {}
    for base in MODULE_DIRS:
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if (d / "module.json").is_file():
                    found[d.name] = d
    return found


def enabled_modules():
    mods = CFG.get("modules")
    # 没写 modules：默认模块里装了的才启用（只发布核心时看板就是「任务」页，不提示缺模块）
    return [m for m in DEFAULT_MODULES if m in find_modules()] if mods is None else list(mods)


def _import(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def valid_tab_url(url):
    """链接标签只接受带主机名的 http、https 地址，挡掉 javascript: 之类。"""
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def load_modules():
    """按 config 的 modules 加载：读 module.json，查约定版本和硬依赖，调用 load.py 的 load(ctx)。
    返回 (模块列表, 页脚提示, 要监视的文件)。一个模块出错只影响它自己。"""
    avail, wanted = find_modules(), enabled_modules()
    metas, notes, watch = {}, [], []
    for mid in wanted:
        d = avail.get(mid)
        if not d:
            notes.append(L.t("now.note.no_module", mid=mid))
            continue
        try:
            meta = json.loads((d / "module.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            notes.append(L.t("now.note.bad_meta", mid=mid, e=e))
            continue
        if meta.get("contract") != CONTRACT:
            notes.append(L.t("now.note.contract", mid=mid, v=meta.get('contract'), want=CONTRACT))
            continue
        metas[mid] = (d, meta)
    # 硬依赖：缺了就不加载（反复剔除，直到稳定）
    changed = True
    while changed:
        changed = False
        for mid, (_, meta) in list(metas.items()):
            miss = [r for r in meta.get("requires", []) if r not in metas]
            if miss:
                notes.append(L.t("now.note.needs", mid=mid, deps=L.join(miss)))
                del metas[mid]
                changed = True
    # 加载顺序：依赖（requires、uses）在前；同层保持 config 里的顺序
    order, seen = [], set()

    def visit(mid, stack=()):
        if mid in seen or mid not in metas or mid in stack:
            return
        for dep in metas[mid][1].get("requires", []) + metas[mid][1].get("uses", []):
            visit(dep, stack + (mid,))
        seen.add(mid)
        order.append(mid)

    for mid in metas:
        visit(mid)
    provided, results = {}, {}
    for mid in order:
        d, meta = metas[mid]
        files = [HERE / f for f in meta.get("files", [])]
        watch += files + [p for p in d.iterdir() if p.is_file()]
        ctx = SimpleNamespace(
            id=mid, dir=d, data_dir=HERE, config=CFG.get(mid) or {}, root_config=CFG,
            today=dt.date.today(), category=category, cat_names=CAT_NAMES,
            inline=inline, fmt=_fmt, table_rows=table_rows, table_dicts=table_dicts,
            sections=sections, find_section=find_section, link_parts=link_parts, path=_path, file_url=file_url,
            get=lambda name: provided.get(name),
            provide=lambda name, value, _m=meta: provided.__setitem__(name, value) if name in _m.get("provides", []) else None,
            watch=watch.append)
        tabs = []
        for tab in meta.get("tabs", []):
            if "url" in tab and not valid_tab_url(tab["url"]):
                notes.append(L.t("now.note.bad_url", mid=meta.get('name', mid), tab=tab.get('title', tab.get('id'))))
                continue
            tabs.append(tab)
        entry = {"id": mid, "name": meta.get("name", mid), "tabs": tabs,
                 "slots": meta.get("slots", []), "data": None, "error": "", "css": "", "js": ""}
        try:
            if (d / "load.py").is_file():  # 只有链接标签的模块可以没有 load.py
                entry["data"] = _import(d / "load.py", f"now_module_{mid}").load(ctx)
        except Exception as e:  # noqa: BLE001 — 模块出错只影响它自己
            tb = traceback.extract_tb(e.__traceback__)[-1]
            entry["error"] = f"{type(e).__name__}: {e}（{Path(tb.filename).name} 第 {tb.lineno} 行）"
            notes.append(L.t("now.note.error", mid=entry['name'], e=entry['error']))
        for kind in ("css", "js"):
            f = d / f"view.{kind}"
            entry[kind] = f.read_text(encoding="utf-8") if f.exists() else ""
        results[mid] = entry
    # 页面上按 config 的顺序排
    return [results[m] for m in wanted if m in results], notes, watch


def sources(watch=()):
    """看板依赖的全部文件：核心 Markdown、模板、本脚本、任务与已完成里链接的 PROGRESS.md，加上各模块的文件。"""
    files = [NOW_MD, DONE_MD, CONFIG, TEMPLATE, Path(__file__).resolve(), *watch]
    for md, base in ((NOW_MD, NOW_MD.parent), (DONE_MD, DONE_MD.parent)):
        if md.exists():
            for r in table_dicts(md.read_text(encoding="utf-8").splitlines()):
                _, path = link_parts(i18n.cols(r).get("task", ""), base)
                if path:
                    files += [path, path.parent / P.LOG]
    return [f for f in files if f and f.exists()]


def up_to_date():
    if not OUT.exists():
        return False
    built = OUT.stat().st_mtime
    _, _, watch = load_modules()
    return all(f.stat().st_mtime <= built for f in sources(watch))


def tab_sequence(modules, order):
    """标签页 id 的显示顺序（链接标签不在内，它们总排在最后）。

    默认是「任务」加各内嵌模块的标签，按 modules 顺序；config.json 的 tab_order 列出的标签，
    按给定顺序重新占据它们原来所在的那些位置，没列出的位置不动。不存在、重复的 id 忽略。"""
    ids = ["tasks"] + [t["id"] for m in modules for t in m["tabs"] if not t.get("url")]
    listed = [i for i in dict.fromkeys(order if isinstance(order, list) else []) if i in ids]
    picked, queue = set(listed), iter(listed)
    return [next(queue) if i in picked else i for i in ids]


def collect():
    """生成页面所需的全部数据；模块的 css、js 单独返回，由 render() 内联进模板。"""
    modules, notes, _ = load_modules()
    if "tab_order" in CFG and not isinstance(CFG["tab_order"], list):
        notes.append(L.t("now.note.tab_order"))
    return {
        "tabOrder": tab_sequence(modules, CFG.get("tab_order")),
        "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "now": parse_now(),
        "done": parse_done(),
        "catNames": CAT_NAMES,
        "lang": LANG,
        "buildCmd": ("python3 " + str(Path(__file__).resolve())
                     + ("" if HERE == CODE else f" --now-dir {HERE}")).replace(str(Path.home()), "~"),
        "sources": {"now": file_url(NOW_MD), "done": file_url(DONE_MD)},
        "modules": modules,
        "notes": notes,
    }


def render(data):
    mods = data["modules"]
    css = "\n".join(f"/* 模块 {m['id']} */\n{m['css']}" for m in mods if m["css"])
    js = "\n".join(f"// 模块 {m['id']}\ntry {{\n{m['js']}\n}} catch (e) {{ NOW.fail({json.dumps(m['id'])}, e); }}"
                   for m in mods if m["js"])
    page_data = {**data, "modules": [{k: v for k, v in m.items() if k not in ("css", "js")} for m in mods]}
    blob = json.dumps(page_data, ensure_ascii=False).replace("</", "<\\/")
    packs = {x: i18n.pack(x).text_dict() for x in i18n.LANGS}  # 页面自带两种语言包和 i18n.js：直接打开文件也能切换
    i18n_js = ("window.I18N_PACKS = " + json.dumps(packs, ensure_ascii=False) + ";\nwindow.BOARD_LANG = " + json.dumps(LANG) + ";\n"
               + (CODE.parent / "static" / "i18n.js").read_text(encoding="utf-8")).replace("</", "<\\/")
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("/*I18N_JS*/", i18n_js)
            .replace("/*MODULE_CSS*/", css.replace("</style", "<\\/style"))
            .replace("/*MODULE_JS*/", js.replace("</script", "<\\/script"))
            .replace("/*DATA*/null", blob))


def main():
    if "--if-changed" in sys.argv and up_to_date():
        return
    OUT.write_text(render(collect()), encoding="utf-8")
    print(L.t("team.generated", path=OUT))


if __name__ == "__main__":
    main()
