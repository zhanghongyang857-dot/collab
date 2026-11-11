#!/usr/bin/env python3
"""班子配置：一份 班子.json 描述你的成员（应用、型号、档位、唤醒命令），生成各项目的 collab/成员.md。

用法（一般由 init.sh 调用）：
  team.py init   <班子目录>                         没有 班子.json 时从示例复制一份
  team.py render <班子.json> <成员.md> [--force]     生成成员.md；保留原文件中「## 本项目补充」一节
  team.py projects <NOW.md>                         列出 NOW「任务」表里有 collab/ 的项目目录
只用 Python 标准库。
"""
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n  # noqa: E402
import paths as P  # noqa: E402

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "team-example" / P.TEAM_JSON
MARK = "<!-- collab-team:"


# 班子配置（team.json、talent.json）和项目花名册（roster.json）的键：英文为准；旧文件的中文键读的时候换掉，init.sh migrate-now 改写文件
TEAM_KEYS = {
    "成员": "members", "派活名": "dispatch_name", "名称": "name", "应用": "app", "常坐席位": "usual_seat", "型号": "model",
    "能力档": "tier", "相对成本": "cost", "擅长": "strengths", "不适合": "weaknesses", "可用": "available", "职能": "duty",
    "唤醒": "wake", "续接": "resume", "权限": "permissions", "回看": "history", "备注": "notes", "别名": "aliases",
    "事件解析": "parser", "新会话命令": "start_command", "续接命令": "resume_command", "运行上限": "limits",
    "朝会运行上限": "meet_limits", "步数": "steps", "分钟": "minutes", "秒数": "seconds", "总裁": "owner", "总管": "lead",
    "派活脚本": "dispatcher", "_说明": "_note", "说明": "note", "人才": "talent", "身份": "identity", "技能": "skills",
    "可由": "played_by", "状态": "status",
}


def english(obj):
    """键换成英文（值不动）；已经是英文的原样。"""
    if isinstance(obj, dict):
        return {TEAM_KEYS.get(k, k): english(v) if isinstance(v, (dict, list)) and k not in ("新会话命令", "续接命令", "start_command", "resume_command") else v
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [english(x) for x in obj]
    return obj


def read(path: Path) -> dict:
    """读班子配置、人才库或花名册，键换成英文。"""
    return english(json.loads(path.read_text(encoding="utf-8")))


def load(path: Path) -> dict:
    data = read(path)
    data.setdefault("members", [])
    return data


def render(team: dict, src: Path, lang: str = i18n.DEFAULT) -> str:
    L = i18n.pack(lang)
    T = L.t
    tbd = T("team.tbd")

    def cell(v) -> str:
        return str(v or tbd).replace("|", "／").replace("\n", " ")

    def kv(k: str, v) -> str:
        return "- " + L.kv(T("team.field." + k), v)

    p = team.get("owner", {})
    m = team.get("lead", {})
    members = team["members"]
    disp = team.get("dispatcher", "")
    if disp.startswith("<"):
        disp = ""
    extra = T("team.extra_heading")
    lines = [
        f"{MARK} " + T("team.mark", src=src, date=dt.date.today().isoformat(), team=P.TEAM_JSON, extra=extra) + " -->",
        "# " + T("team.title"), "", T("team.intro"), "",
    ]
    if disp:
        lines += [T("team.dispatcher", path=disp, runs=P.INTERNAL_RUNS + "/"), ""]
    lines += [T("team.head_members"), "|---|---|---|", T("team.owner_row")]
    if m:
        lines.append(f"| {cell(m.get('name'))} | {cell(m.get('app'))} | {L.name('seat', 'lead')} |")
    for x in members:
        lines.append(f"| {cell(x.get('name'))} | {cell(x.get('app'))} | {cell(x.get('usual_seat'))} |")
    lines += ["", "## " + T("team.capability"), "", T("team.capability_intro"), "",
              T("team.head_capability"), "|---|---|---|---|---|---|---|---|"]
    for x in members:
        lines.append("| " + " | ".join([cell(x.get("name")), f"`{x['dispatch_name']}`" if x.get("dispatch_name") else "—",
                                         cell(x.get("model")), cell(x.get("tier")), cell(x.get("cost")),
                                         cell(x.get("strengths")), cell(x.get("weaknesses")), cell(x.get("available"))]) + " |")
    lines += ["", "## " + L.name("seat", "owner"),
              kv("duty", p.get("duty") or T("team.owner_duty")),
              kv("wake", p.get("wake") or T("team.owner_wake"))]
    if m:
        lines += ["", f"## {m.get('name') or L.name('seat', 'lead')}"]
        for k in ("duty", "wake", "resume", "permissions", "history"):
            if m.get(k):
                lines.append(kv(k, m[k]))
    for x in members:
        name, did = x.get("name", "?"), x.get("dispatch_name", "")
        lines += ["", f"## {name}", kv("duty", x.get("duty") or tbd)]
        if did and disp:
            lines += [kv("wake", T("team.wake_dispatch", did=did)), kv("resume", T("team.resume_dispatch"))]
        else:
            lines += [kv("wake", x.get("wake") or tbd), kv("resume", x.get("resume") or tbd)]
        for k in ("permissions", "history", "notes"):
            if x.get(k):
                lines.append(kv(k, x[k]))
        if x.get("available") and not str(x["available"]).startswith("✓"):
            lines.append(kv("status", x["available"]))
    return "\n".join(lines) + "\n"


def cmd_render(team_file: Path, out: Path, force: bool) -> int:
    team = load(team_file)
    lang = i18n.project_lang(out.parent.parent)  # out 是 <项目>/collab/members.md
    T = i18n.pack(lang).t
    extra = ""
    if out.exists():
        old = out.read_text(encoding="utf-8")
        if MARK not in old and not force:
            print(T("team.not_generated", out=out, extra=T("team.extra_heading")), file=sys.stderr)
            return 3
        if MARK not in old:
            shutil.copy2(out, out.with_name(out.name + ".bak"))
        i = -1
        for lg in i18n.LANGS:  # 「本项目补充」一节：两种语言的标题都认
            i = old.find("\n## " + i18n.pack(lg).t("team.extra_heading"))
            if i >= 0:
                break
        if i >= 0:
            extra = old[i:].rstrip() + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(team, team_file, lang) + extra, encoding="utf-8")
    print(T("team.generated", path=out))
    roster = out.parent / P.INTERNAL_PLANS / P.ROSTER  # flow.py 唯一的成员来源：项目自带，不依赖全局班子配置
    roster.parent.mkdir(parents=True, exist_ok=True)
    keep = ("dispatch_name", "name", "aliases", "app", "usual_seat", "tier")
    data = {"note": T("team.roster_note", src=team_file, team=P.TEAM_JSON),
            "members": [{k: x[k] for k in keep if x.get(k)} for x in team["members"] if x.get("dispatch_name")]}
    roster.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(T("team.generated", path=roster))
    return 0


def cmd_init(team_dir: Path, lang: str = "") -> int:
    lang = lang if lang in i18n.LANGS else i18n.pack().lang
    T = i18n.pack(lang).t
    f = team_dir / P.TEAM_JSON
    if f.exists():
        print(T("team.exists", path=f))
        return 0
    team_dir.mkdir(parents=True, exist_ok=True)
    src = HERE / "team-example" / lang / P.TEAM_JSON
    shutil.copy2(src if src.exists() else EXAMPLE, f)
    print(T("team.created", path=f))
    return 0


def cmd_projects(now_md: Path) -> int:
    if not now_md.exists():
        print(f"找不到 {now_md}", file=sys.stderr)
        return 1
    text = now_md.read_text(encoding="utf-8")
    sec = re.search(r"(?ms)^## (?:%s)\s*\n(.*?)(?=^## |\Z)" % "|".join(map(re.escape, i18n.headings("now_projects"))), text)
    for m in re.finditer(r"\]\(<?([^)>]+?collab/PROGRESS\.md)>?\)", sec.group(1) if sec else ""):
        p = (now_md.parent / m.group(1)).resolve()
        if p.exists():
            print(p.parent.parent)
    return 0


def main(argv) -> int:
    if len(argv) >= 2 and argv[0] == "init":
        return cmd_init(Path(argv[1]).expanduser(), argv[3] if argv[2:3] == ["--lang"] and len(argv) > 3 else "")
    if len(argv) >= 3 and argv[0] == "render":
        return cmd_render(Path(argv[1]).expanduser(), Path(argv[2]).expanduser(), "--force" in argv[3:])
    if len(argv) >= 2 and argv[0] == "projects":
        return cmd_projects(Path(argv[1]).expanduser())
    print(__doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
