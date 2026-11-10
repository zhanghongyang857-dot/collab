#!/usr/bin/env python3
"""把演示案例「万历新政」做成静态网站：八回各生成一次、各导出一份只读看板，加一个回目录首页。

用法：python3 demo/site.py [--输出 目录]（默认 demo/站点，不进版本库）
公开仓库的 GitHub Actions 用它生成 GitHub Pages；本机看：python3 -m http.server -d demo/站点 8000
目录：index.html（首页：故事和回目）、chN/（第 N 回，chN/ 自己跳到项目页）、chN/p/15730301/（项目看板）……
只用 Python 标准库。
"""
import argparse
import html
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src" / "board"))
import build  # noqa: E402
import export_static  # noqa: E402

PID = "15730301"  # 万历元年三月初一，演示开场那天
# 每回：一句话看什么，和点进去先落在哪（相对项目页）
GUIDE = [
    ("内阁立案、进呈、陛下批红；赈灾诏四易其稿；廷议定治河方略", "#G001"),
    ("框架会审：都察院坚持加独立核验，改变了框架", "meet/I002/"),
    ("工部缺银，「待批红」里第一次出现奏本，等你朱批", "#G001"),
    ("陛下准拨内帑，奏本自动消失；江南豪强阻丈，又一道奏本", "#G002"),
    ("开海被留中退回；兵部逾制先行；和战之议中途加人、私下进言", "meet/I003/"),
    ("都察院巡按验收，河工告成结案；开海恢复", "#G001"),
    ("鱼鳞册造假：清丈重开，后续节次自动失效；户部返工到上限，改委工部", "#G002"),
    ("三件结案，开海五路并行；两件新想法先立案，停在「想法」页", "#G004"),
]


def chapters_meta(issues_by_ch):
    return [{"title": build.CHAPTERS[i].replace("　", " ").replace("终 回", "终回"), "see": GUIDE[i][0], "issues": issues_by_ch[i]}
            for i in range(len(build.CHAPTERS))]


def landing(meta) -> str:
    rows = "".join(
        f'<li><a href="ch{i + 1}/p/{PID}/{GUIDE[i][1]}"><span class="no">{html.escape(m["title"].split(" ")[0])}</span>'
        f'<span class="tt">{html.escape(" ".join(m["title"].split(" ")[1:]))}</span>'
        f'<span class="see">{html.escape(m["see"])}</span></a></li>' for i, m in enumerate(meta))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>万历新政 · 批红演示</title>
<style>
:root {{ --bg:#f7f3ec; --card:#fffdf9; --ink:#2a2420; --ink2:#6b625a; --line:#e7dfd3; --red:#9c2a24; --red-soft:#f6e6e1; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#17130f; --card:#211c17; --ink:#f1eae1; --ink2:#b3a899; --line:#3a3128; --red:#e0756b; --red-soft:#3a201c; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.75 -apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans SC",sans-serif; }}
main {{ max-width:860px; margin:0 auto; padding:56px 16px 72px; }}
.seal {{ display:inline-block; border:2px solid var(--red); color:var(--red); padding:2px 10px; border-radius:4px; font-size:13px; letter-spacing:.2em; }}
h1 {{ font-size:40px; line-height:1.25; margin:18px 0 8px; letter-spacing:.04em; }}
.lead {{ font-size:18px; color:var(--ink2); margin:0 0 28px; }}
.cast {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin:24px 0 36px; }}
.cast div {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; font-size:14px; }}
.cast b {{ display:block; font-size:15px; }}
.cast span {{ color:var(--ink2); }}
h2 {{ font-size:15px; letter-spacing:.2em; color:var(--red); margin:40px 0 12px; }}
ol {{ list-style:none; padding:0; margin:0; border-top:1px solid var(--line); }}
ol a {{ display:grid; grid-template-columns:5.5em 1fr; gap:2px 14px; padding:14px 6px; border-bottom:1px solid var(--line); color:inherit; text-decoration:none; }}
ol a:hover {{ background:var(--red-soft); }}
.no {{ color:var(--red); font-weight:600; grid-row:span 2; }}
.tt {{ font-weight:600; }}
.see {{ color:var(--ink2); font-size:14px; }}
.note {{ font-size:14px; color:var(--ink2); margin-top:36px; }}
.note a {{ color:var(--red); }}
</style>
</head>
<body>
<main>
<span class="seal">批红 · 演示</span>
<h1>万历新政</h1>
<p class="lead">万历元年，黄河在徐州决口，清丈、北边、开海三件大事接踵而来。你是皇帝，只管朱笔批红；内阁票拟统筹，六部和都察院分头办差、互相核验。<br>这是批红的演示项目：每一回都是同一个项目停在剧情里的某一刻，看板和真实使用时一模一样。</p>
<div class="cast">
<div><b>陛下（你）</b><span>总裁：定目标、批红、裁决</span></div>
<div><b>内阁</b><span>总管：票拟、搭框架、派活、验收</span></div>
<div><b>工部 · 兵部</b><span>成员：Codex 扮演</span></div>
<div><b>户部</b><span>成员：DeepSeek 扮演</span></div>
<div><b>都察院 · 翰林院</b><span>成员：Claude 命令行扮演</span></div>
</div>
<h2>回目</h2>
<ol>{rows}</ol>
<p class="note">全部是虚拟数据：没有真的派活，也没有调用模型。事件按剧情写进去，走的是工具包真实的流转规则和检查。网页只读，批红、发言要在本机看板上做。<br>
看板上的明朝叫法只是换了显示：待你决定 → 待批红，目标 → 国事，任务 → 差事，阶段 → 节次。</p>
</main>
</body>
</html>
"""


def make(out: Path) -> Path:
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    issues_by_ch, dirs = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(1, len(build.STORY) + 1):
            proj = build.build(Path(tmp) / f"第{n}回", n)
            dirs.append(proj)
        # 先导出一遍拿到每回有哪些议题，回目条要用；再按完整的回目信息重写页面
        for rnd in (1, 2):
            meta = chapters_meta(issues_by_ch) if rnd == 2 else None
            for n, proj in enumerate(dirs, 1):
                ch = out / f"ch{n}"
                if ch.exists():
                    shutil.rmtree(ch)
                extra = {"chapter": n, "chapters": meta, "home": "../"} if meta else {"home": "../"}
                r = export_static.export(proj, ch, PID, team=HERE, extra=extra, extra_js=["demo-bar.js"] if meta else [])
                shutil.copy2(HERE / "demo-bar.js", ch / "static" / "demo-bar.js")
                (ch / "index.html").write_text(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=p/{PID}/">'
                                               f'<a href="p/{PID}/">进入看板</a>\n', encoding="utf-8")
                if rnd == 1:
                    issues_by_ch.append(r["issues"])
    (out / "index.html").write_text(landing(chapters_meta(issues_by_ch)), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成演示案例的静态网站（八回 + 回目录）")
    ap.add_argument("--输出", dest="out", default=str(HERE / "站点"))
    a = ap.parse_args()
    out = make(Path(a.out))
    print(f"已生成：{out}（八回）。本机看：python3 -m http.server -d {out} 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
