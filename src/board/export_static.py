#!/usr/bin/env python3
"""把一个项目的御前看板导出成静态网站：不用起服务，放到 GitHub Pages 或任意静态文件服务器上就能看（只读）。

用法：python3 board/export_static.py --project <项目目录> --out <输出目录> [--id 15730301] [--team <班子目录>]
导出：
  <out>/p/<id>/                 项目页（同本机看板 /p/<id>）
  <out>/p/<id>/archive/         归档页
  <out>/p/<id>/meet/<议题>/     各议题的朝会页
  <out>/team/                   班子页（有班子.json 时）
  <out>/api/...json             上面各页要的数据，和本机服务的 /api 同一份（server.py 里的同一套函数现算）
  <out>/files/...html           collab/ 和 work/ 下的文本文件，转成只读网页；看板里的文件链接指向它们
  <out>/static/                 页面的 CSS、JS
页面里写 window.BOARD_STATIC（项目、页面、到导出根的相对路径），前端据此读 JSON、改链接、隐藏写入口、不轮询。
数据里的本机绝对路径一律换掉；导出后再扫一遍，还有项目根或家目录路径就报错。只用 Python 标准库。
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PAGES = ("board.css", "project.js", "meet.js", "team.js")
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".csv", ".py"}


def _server(project: Path, team: Optional[Path]):
    """按导出要求准备 server.py：只看这一个项目，NOW 用一个空目录，班子目录按参数。"""
    if team:
        os.environ["COLLAB_TEAM"] = str(team)
    sys.path.insert(0, str(HERE))
    import server  # noqa: E402  导入时按 COLLAB_TEAM 定班子目录
    server.ARGS = argparse.Namespace(project=[str(project)], now_dir=tempfile.mkdtemp(prefix="now-"), verbose=False,
                                     no_registry=True)
    return server


def _plain(text: str, root: Path, team: Path) -> str:
    """换掉剩下的本机路径：项目根 → 空（相对项目根），班子目录 → 「班子目录」。"""
    return text.replace(str(root), "").replace(str(team), "<班子目录>")  # 项目可能就在班子目录里，先换项目根


def _scrub(obj: Any, root: Path, team: Path) -> str:
    """数据转成 JSON 文本，换掉本机路径：文件链接 → {{FILES}}/…html（前端换成导出里的 files/），其余见 _plain。"""
    text = json.dumps(obj, ensure_ascii=False)
    for r in (quote(str(root)), str(root)):
        text = re.sub(r"file://" + re.escape(r) + r'(/[^"\\\s)<>]*)', lambda m: "{{FILES}}" + m.group(1) + ".html", text)
    return _plain(text, root, team)


def _page(name: str, depth: int, conf: Dict[str, Any], extra_js: List[str]) -> str:
    """拿 static/ 里的页面，改成相对路径并写入静态配置。depth 是页面目录离导出根几层。"""
    base = "/".join([".."] * depth) or "."
    conf = {**conf, "base": base}
    page = (STATIC / name).read_text(encoding="utf-8")
    page = page.replace('href="/static/', f'href="{base}/static/').replace('src="/static/', f'src="{base}/static/')
    page = page.replace('<html lang="zh-CN">', '<html lang="zh-CN" class="static">', 1)
    page = re.sub(r'\s*<a class="toplink" href="/talent">人才市场</a>', "", page)
    page = page.replace('href="/team"', f'href="{base}/team/"')
    page = page.replace('href="/"', f'href="{base}/{conf.get("home", "")}"')  # 「← NOW」：home 是相对导出根的去处
    inject = f"<script>window.BOARD_STATIC = {json.dumps(conf, ensure_ascii=False)};</script>\n"
    inject += "".join(f'<script src="{base}/static/{js}" defer></script>\n' for js in extra_js)
    return page.replace("<script ", inject + "<script ", 1)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _files(root: Path, out: Path, team: Path) -> int:
    """collab/ 和 work/ 下的文本文件转成只读网页（<pre>），看板里点文件链接看它。"""
    n = 0
    for top in ("collab", "work"):
        for f in sorted((root / top).rglob("*")) if (root / top).is_dir() else []:
            if not f.is_file() or f.suffix not in TEXT_SUFFIXES or "运行记录" in f.parts:
                continue
            rel = f.relative_to(root).as_posix()
            body = html.escape(_plain(f.read_text(encoding="utf-8", errors="replace"), root, team))
            _write(out / "files" / (rel + ".html"),
                   f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                   f'<title>{html.escape(f.name)}</title><style>body{{margin:0;padding:24px 16px;font:14px/1.7 -apple-system,"PingFang SC",sans-serif;'
                   f'background:#fafaf8;color:#2c2c2a}}pre{{white-space:pre-wrap;word-break:break-word;max-width:860px;margin:0 auto;font:inherit}}'
                   f'h1{{font-size:13px;color:#888;max-width:860px;margin:0 auto 16px}}</style></head>'
                   f'<body><h1>{html.escape(rel)}（只读）</h1><pre>{body}</pre></body></html>\n')
            n += 1
    return n


def export(project: Path, out: Path, pid: str = "15730301", team: Optional[Path] = None,
           extra: Optional[Dict[str, Any]] = None, extra_js: Optional[List[str]] = None) -> Dict[str, Any]:
    """导出一个项目。extra 并进页面的 BOARD_STATIC（如演示的回目），extra_js 是另放进 static/ 的脚本名（调用方自己拷）。"""
    project, out = project.resolve(), out.resolve()
    srv = _server(project, team)
    p = next((x for x in srv.discover() if Path(x["root"]) == project), None)
    if not p:
        raise SystemExit(f"{project} 不是项目（找不到 collab/PROGRESS.md）")
    title = next((l[2:].strip() for l in Path(p["progress"]).read_text(encoding="utf-8").splitlines() if l.startswith("# ")), "")
    p = {**p, "id": pid, "name": p["name"] if p["source"] != "extra" else title or p["name"]}  # 不在 NOW 里的项目用 PROGRESS 标题，不用目录名
    conf = {"project": pid, **(extra or {})}
    js = extra_js or []
    out.mkdir(parents=True, exist_ok=True)
    (out / "static").mkdir(exist_ok=True)
    for f in PAGES:
        shutil.copy2(STATIC / f, out / "static" / f)

    _write(out / "api" / "p" / f"{pid}.json", _scrub(srv.project_data(p), project, srv.TEAM_DIR))
    _write(out / "api" / "p" / pid / "archive.json", _scrub(srv.archive_data(p), project, srv.TEAM_DIR))
    _write(out / "p" / pid / "index.html", _page("project.html", 2, conf, js))
    _write(out / "p" / pid / "archive" / "index.html", _page("project.html", 3, {**conf, "archive": True}, js))
    issues = []
    if (project / "collab" / "内部" / "流转").is_dir():
        view = srv.flow.view(srv.flow.Project(project))
        for i in view["议题"]:
            data = srv.meet_data(p, i["编号"])
            if data:
                issues.append(i["编号"])
                _write(out / "api" / "p" / pid / "meet" / f"{i['编号']}.json", _scrub(data, project, srv.TEAM_DIR))
                _write(out / "p" / pid / "meet" / i["编号"] / "index.html", _page("meet.html", 4, {**conf, "issue": i["编号"]}, js))
    team_doc = srv.team_data()
    if team_doc.get("exists"):
        for st in team_doc["stats"].values():
            for x in st["running"] + st["holding"]:
                x["pid"] = pid
        _write(out / "api" / "team.json", _scrub(team_doc, project, srv.TEAM_DIR))
        _write(out / "team" / "index.html", _page("team.html", 1, {**conf, "page": "team"}, js))
    files = _files(project, out, srv.TEAM_DIR)

    leaks = [str(project), str(Path.home())]
    bad = [f.relative_to(out).as_posix() for f in out.rglob("*") if f.is_file() and f.suffix in (".json", ".html")
           and any(s in f.read_text(encoding="utf-8", errors="ignore") for s in leaks)]
    if bad:
        raise SystemExit("导出里还有本机路径：" + "、".join(bad[:10]))
    return {"out": str(out), "project": pid, "issues": issues, "team": bool(team_doc.get("exists")), "files": files}


def main() -> int:
    ap = argparse.ArgumentParser(description="把项目看板导出成静态网站（只读）")
    ap.add_argument("--project", required=True, help="项目目录（含 collab/PROGRESS.md）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--id", default="15730301", help="导出里的项目编号（8 位十六进制）")
    ap.add_argument("--team", help="班子目录（含 班子.json），不给就按 COLLAB_TEAM 或工具包默认")
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{8}", a.id):
        sys.exit("--id 要是 8 位十六进制")
    r = export(Path(a.project), Path(a.out), a.id, Path(a.team).resolve() if a.team else None)
    print(f"已导出：{r['out']}，项目页 p/{r['project']}/，议题 {len(r['issues'])} 个，文件 {r['files']} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
