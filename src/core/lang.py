#!/usr/bin/env python3
"""换项目语言（init.sh lang）：规则文档和模板换成目标语言，卡片的小节标题和字段名按代码改写，config.json 改 lang，再 flow render。
正文（卡片内容、日志、决议、发言、依据）不动；生成块由 flow render 按新语言重写。

用法：lang.py zh|en [项目目录]
只用 Python 标准库。
"""
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flow  # noqa: E402
import i18n  # noqa: E402
import paths as P  # noqa: E402
import team as team_mod  # noqa: E402
from vocab import Section  # noqa: E402

WB = HERE.parent / "workbench"
# 整份换成目标语言模板的文件（协议保留「本项目补充」一节）
REPLACE = [P.PROTOCOL, f"{P.GOALS}/{P.TEMPLATE}", f"{P.TASKS}/{P.TEMPLATE}", f"{P.ISSUES}/{P.TEMPLATE}"]
# 模板固定行逐行对照的文件：两种语言的模板行数相同，项目里和源语言模板某行完全一样的那行换成目标语言的同一行
LINEWISE = [P.PROGRESS, P.LOG, P.LESSONS, P.DECISIONS, f"{P.ARCHIVE}/{P.DECISIONS}", P.MEMBERS]
CARD_TEXT = ("card.history_note", "card.transcript_note", "card.disagreements_hint")
EXTRA = re.compile(r"(?ms)^## (?:\d+\. )?(?:本项目补充|Project notes)\s*\n.*\Z")


def line_map(rel: str, src: str, dst: str) -> Dict[str, str]:
    a = (WB / src / rel).read_text(encoding="utf-8").splitlines()
    b = (WB / dst / rel).read_text(encoding="utf-8").splitlines()
    if len(a) != len(b):
        return {}
    return {x: y for x, y in zip(a, b) if x != y and x.strip() and "{{" not in x}


def retitle(text: str, lang: str) -> str:
    """卡片的 ## / ### 小节标题和「- 字段：」行换成目标语言；认不出的原样。"""
    L = i18n.pack(lang)

    def head(m):
        title = m.group(2).strip()
        code = i18n.code_of("section", title)
        if code:
            return m.group(1) + L.heading(code)
        code = i18n.heading_codes(title)
        if code == Section.SUMMARY:  # 「总结（总管）」
            return m.group(1) + L.t("card.summary_heading", summary=L.heading(code))
        return m.group(0)

    text = re.sub(r"(?m)^(#{2,3} )(.+)$", head, text)

    def field(m):
        code = i18n.code_of("field", m.group(2))
        return m.group(1) + L.kv(L.field(code), m.group(3).strip()) if code else m.group(0)

    return re.sub(r"(?m)^(- )([^：:\n]{1,24}?)\s*[：:][ \t]*(.*)$", field, text)


META = {"zh": ("目标：", " ｜ 截止：", " ｜ 状态：", " ｜ 建立于 "), "en": ("Goal: ", " | Due: ", " | Status: ", " | Started ")}


def meta_line(text: str, lang: str) -> str:
    """PROGRESS 标题下那行「目标：… ｜ 截止：… ｜ 状态：… ｜ 建立于 …」换成目标语言，值不动（状态名按代码换）。"""
    for frm in i18n.LANGS:
        a = META[frm]
        bar = lambda s: re.escape(s.replace("｜", "|")).replace("\\|", "[｜|]")  # noqa: E731  卡头分隔符中文全角｜、英文半角 |，两种都认
        pat = re.compile("(?m)^" + bar(a[0]) + "(.*?)" + bar(a[1]) + "(.*?)" + bar(a[2]) + "(.*?)" + bar(a[3]) + "(.*)$")
        m = pat.search(text)
        if m:
            b = META[lang]
            state = i18n.code_of("state", m.group(3))
            st = i18n.pack(lang).st(state) if state else m.group(3)
            return text[:m.start()] + b[0] + m.group(1) + b[1] + m.group(2) + b[2] + st + b[3] + m.group(4) + text[m.end():]
    return text


def switch(root: Path, lang: str, out=print) -> int:
    root = root.resolve()
    if lang not in i18n.LANGS:
        out("usage: init.sh lang zh|en [dir]")
        return 1
    proj = flow.Project(root)
    if not (root / P.COLLAB / P.CONFIG).exists() or proj.needs_migration():
        out(i18n.pack(lang).t("lang.needs_migration", root=root))
        return 1
    T = i18n.pack(lang).t
    src = proj.lang
    if src == lang:
        out(T("lang.same", root=root, lang=lang))
        return 0
    col = root / P.COLLAB
    changed: List[str] = []
    for rel in REPLACE:
        f, tpl = col / rel, WB / lang / P.COLLAB / rel
        if not tpl.exists():
            continue
        new = tpl.read_text(encoding="utf-8")
        if rel == P.PROTOCOL and f.exists():  # 保留项目自己的「本项目补充」，标题换成目标语言
            m = EXTRA.search(f.read_text(encoding="utf-8"))
            m0 = EXTRA.search((WB / src / P.COLLAB / rel).read_text(encoding="utf-8"))
            if m and m0 and m.group(0).split("\n", 1)[-1].strip() == m0.group(0).split("\n", 1)[-1].strip():
                m = None  # 还是模板里的空节：用目标语言的
            if m:
                body = m.group(0).split("\n", 1)[1] if "\n" in m.group(0) else ""
                new = EXTRA.sub(lambda n: n.group(0).split("\n", 1)[0] + "\n" + body, new)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(new, encoding="utf-8")
        changed.append(f"{P.COLLAB}/{rel}")
    for rel in LINEWISE:
        f = col / rel
        if not f.exists():
            continue
        mp = line_map(f"{P.COLLAB}/{rel}", src, lang)
        text = f.read_text(encoding="utf-8")
        new = "\n".join(mp.get(x, x) for x in text.split("\n"))
        if rel == P.PROGRESS:
            new = retitle(meta_line(new, lang), lang)
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed.append(f"{P.COLLAB}/{rel}")
    agents = root / "AGENTS.md"
    if agents.exists():  # 入口说明块换成目标语言
        a, b = (WB / src / "AGENTS.md").read_text(encoding="utf-8"), (WB / lang / "AGENTS.md").read_text(encoding="utf-8")
        t = agents.read_text(encoding="utf-8")
        if a in t:
            agents.write_text(t.replace(a, b), encoding="utf-8")
            changed.append("AGENTS.md")
    fixed = [(i18n.pack(src).t(k), i18n.pack(lang).t(k)) for k in CARD_TEXT]
    for f in proj.card_files():
        t = f.read_text(encoding="utf-8")
        n = retitle(t, lang)
        for a, b in fixed:  # 卡片模板里的固定注释和占位提示
            n = n.replace(a, b)
        if n != t:
            f.write_text(n, encoding="utf-8")
            changed.append(proj.rel(f))
    cfg = json.loads((col / P.CONFIG).read_text(encoding="utf-8"))
    cfg["lang"] = lang
    (col / P.CONFIG).write_text(json.dumps(cfg, ensure_ascii=False) + "\n", encoding="utf-8")
    changed.append(f"{P.COLLAB}/{P.CONFIG}")
    members = col / P.MEMBERS
    team = flow.team_file()
    if members.exists() and team_mod.MARK in members.read_text(encoding="utf-8") and team.exists():
        team_mod.cmd_render(team, members, False)
    proj = flow.Project(root)
    with flow.locked(proj):
        rendered = flow.render_all(proj)
    out(T("lang.done", root=root, lang=lang, n=len(changed), rendered=len(rendered)))
    for x in changed:
        out("  " + x)
    errs = [x for x in flow.check(proj, now=None) if x["level"] == "error"]
    for x in errs:
        out(f"  {T('cli.level.error')}  {x['file']}  {x['msg']}")
    return 1 if errs else 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in i18n.LANGS:
        print(__doc__.strip())
        return 1
    return switch(Path(argv[1] if len(argv) > 1 else ".").expanduser(), argv[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
