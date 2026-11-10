#!/usr/bin/env python3
"""看板网页服务：NOW 页（复用模板里的 build.py 读 NOW 数据目录，生成到临时文件）和各项目的御前看板页。

用法：python3 board/server.py [--port 3100] [--now-dir ~/Collab/NOW] [--project 目录 ...]
页面：NOW（/）、御前看板（/p/<项目>）、朝会（/p/<项目>/meet/<议题>）、班子（/team）、人才市场（/talent）。
只读，加只能追加经过校验的黑板事件：不直接写 NOW、各项目 collab/ 或运行记录；动作只有两个——
/api/open 用系统默认应用打开本机文件；/api/p/<项目>/meet/<议题> 由总裁在朝会页发言、开始、结束、裁决，
经 flow.py 同一套检查写一条事件，带 @ 的发言和「开始」在后台用 dispatch.py meet 叫醒相关成员。
只用 Python 标准库，只监听 127.0.0.1。
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "core"))
import collab_parse  # noqa: E402  与派活脚本共用的任务卡、目标卡解析
import check as collab_check  # noqa: E402  collab/ 校验，与派活脚本、Stop hook 共用
import flow  # noqa: E402  新结构项目（有 collab/内部/流转/）的投影：状态、阶段和视图模型都从这里来
STATIC = HERE / "static"
STATIC_FILES = {"board.css": "text/css", "project.js": "text/javascript", "project.html": "text/html",
                "meet.html": "text/html", "meet.js": "text/javascript",
                "now-inject.css": "text/css", "now-inject.js": "text/javascript",
                "team.html": "text/html", "team.js": "text/javascript",
                "talent.html": "text/html", "talent.js": "text/javascript"}
TEAM_DIR = flow.team_dir()
TALENT_EXAMPLE = HERE.parent / "core" / "team-example" / "人才.json"
RUNS_DIR = "内部/运行记录"
OPEN_SUFFIXES = {".md", ".html", ".txt", ".json", ".jsonl", ".py", ".pdf", ".csv", ".png", ".jpg"}
BUILD_LOCK = threading.Lock()
DISPATCH_PY = HERE.parent / "core" / "dispatch.py"
MEET_ACTIONS = ("发言", "开始", "结束讨论", "继续讨论", "裁决", "取消", "补叫", "加人", "停止", "收尾")
STALL_SECONDS = 90  # 运行中这么久没有实际输出（工具心跳不算），页面标「疑似卡住」
GOAL_ACTIONS = ("批准", "退回", "意见")
BUILD_PY = HERE / "now" / "build.py"  # NOW 看板代码，template.html 在同目录

ARGS: argparse.Namespace


def default_now_dir() -> str:
    """本机发布在 NOW/系统/ 时，NOW 数据目录就是它的上一级（有 config.json 即是，不要求装了哪个模块）；
    开发时没有就用 ~/Collab/NOW。"""
    beside = flow.TOOLKIT.parent
    return str(beside) if (beside / "config.json").exists() else "~/Collab/NOW"


# ---------- NOW：每次请求重新加载 build.py，让它把看板生成到临时文件 ----------

def load_build():
    # build.py 在导入时按 NOW_DATA_DIR 定数据目录；代码用工具包里模板那份，NOW 目录只放数据
    os.environ["NOW_DATA_DIR"] = str(Path(ARGS.now_dir).expanduser())
    path = BUILD_PY
    spec = importlib.util.spec_from_file_location("now_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def now_html() -> str:
    with BUILD_LOCK, tempfile.TemporaryDirectory() as tmp:
        mod = load_build()
        mod.OUT = Path(tmp) / "看板.html"
        argv = sys.argv
        sys.argv = ["build.py"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                mod.main()
        finally:
            sys.argv = argv
        page = mod.OUT.read_text(encoding="utf-8")
    inject = '<link rel="stylesheet" href="/static/now-inject.css"><script src="/static/now-inject.js" defer></script>'
    return page.replace("</head>", inject + "</head>", 1)


# ---------- 项目发现：NOW 任务表和已完成表里链接的 collab/PROGRESS.md，加上 --project ----------

def project_id(root: Path) -> str:
    return hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]


def discover() -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    def add(progress: Optional[Path], name: str, source: str, state: str = "") -> None:
        if not progress or progress.name != "PROGRESS.md" or progress.parent.name != "collab" or not progress.exists():
            return
        root = progress.parent.parent
        pid = project_id(root)
        if pid not in found:
            try:
                flowed = (progress.parent / "内部" / "流转").is_dir()
                issues = flow_issue_rows(root) if flowed else collab_parse.load_issues(progress.parent)
                summary = collab_parse.goal_summary(collab_parse.load_goals(progress.parent), issues)
            except Exception:
                summary = ""
            found[pid] = {"id": pid, "name": name or root.name, "root": str(root), "progress": str(progress),
                          "source": source, "state": state, "summary": summary}

    try:
        mod = load_build()
        for md, src in ((mod.NOW_MD, "now"), (mod.DONE_MD, "done")):
            if md.exists():
                for r in mod.table_dicts(md.read_text(encoding="utf-8").splitlines()):
                    name, path = mod.link_parts(r.get("任务", ""), md.parent)
                    add(path, name, src, r.get("状态", "") if src == "now" else "已完成")
    except Exception as e:  # NOW 坏了也不影响 --project 指定的项目
        print(f"读取 NOW 失败：{e}", file=sys.stderr)
    for p in ARGS.project or []:
        root = Path(p).expanduser().resolve()
        add(root / "collab" / "PROGRESS.md", "", "extra")
    return list(found.values())


# ---------- 项目数据 ----------

def is_placeholder(t: str) -> bool:
    t = t.strip()
    return not t or (t.startswith("<") and t.endswith(">")) or t in ("待填", "…", "无")


def kv_line(line: str) -> Dict[str, str]:
    return collab_parse.kv_line(line)


def html_task(mod, t: Dict[str, Any], base: Path) -> Dict[str, Any]:
    out = dict(t)
    out["flow"] = [{k: mod.inline(v, base) for k, v in r.items()} for r in t["flow"]]
    out["fields"] = [{"k": f["k"], "v": mod.inline(f["v"], base)} for f in t["fields"]]
    return out


def html_goal(mod, g: Dict[str, Any], by_id: Dict[str, Any], base: Path) -> Dict[str, Any]:
    out = dict(g)
    out["fields"] = [{"k": f["k"], "v": mod.inline(f["v"], base)} for f in g["fields"]]
    stages = []
    for s in g["stages"]:
        st = dict(s)
        for k in ("output", "cond"):
            st[k] = mod.inline(s[k], base)
        st["taskInfo"] = [{"id": i, "title": by_id[i]["title"], "state": by_id[i]["state"], "cls": by_id[i]["cls"],
                           "exec": by_id[i]["head"].get("执行", ""), "archived": by_id[i]["archived"],
                           "flow": by_id[i]["flow"]}
                          for i in s["tasks"] if i in by_id]
        stages.append(st)
    out["stages"] = stages
    return out


def html_issue(mod, i: Dict[str, Any], base: Path) -> Dict[str, Any]:
    out = dict(i)
    for k in ("question", "summary", "ruling"):
        out[k] = [{"k": f["k"], "v": mod.inline(f["v"], base)} for f in i[k]]
    return out


def pid_alive(pid: Any) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError):
        return True
    return True


def parse_runs(collab: Path) -> List[Dict[str, Any]]:
    # 演示案例停在剧情里的某一刻（有时钟）：运行记录按原样显示，不按进程是否还在改成异常结束
    frozen = project_clock(collab) is not None
    d = collab / RUNS_DIR
    runs = []
    if not d.exists():
        return runs
    for f in d.glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("status") == "运行中" and not frozen and not pid_alive(r.get("pid")):
            r["status"] = "异常结束"
        r.pop("pid", None)
        r.pop("child_pid", None)
        runs.append(r)
    runs.sort(key=lambda r: (r.get("started") or "", r.get("run") or ""))
    return runs


TASK_CLS = {"通过": "pass", "取消": "pass", "受阻": "block", "未通过": "block", "待验收": "review", "执行中": "doing"}
STAGE_STATUS = {"可开始": "未开始"}


def flow_cards(collab: Path, root: Path) -> tuple:
    """新结构项目：任务和目标的状态、持有人、阶段一律取自 flow.py 的视图模型，卡片只提供标题和手写字段。
    返回与 collab_parse 相同形状的 (tasks, goals, view)，看板其余部分不用区分新旧。"""
    proj = flow.Project(root)
    v = flow.view(proj)
    old = {t["id"]: t for t in collab_parse.load_tasks(collab)}
    old_goals = {g["id"]: g for g in collab_parse.load_goals(collab, list(old.values()))}
    tasks = []
    for tv in v["任务"]:
        t = dict(old.get(tv["编号"]) or {"id": tv["编号"], "title": tv["标题"], "fields": [], "file": "", "archived": False})
        t.update({"title": t.get("title") or tv["标题"], "state": tv["状态"], "holder": tv["持有人"] or "",
                  "goal": tv["目标"] or "", "stage": tv["阶段"], "cls": TASK_CLS.get(tv["状态"], "todo"),
                  "head": {"状态": tv["状态"], "执行": tv["执行"] or "", "验收": tv["确认"] or "", "目标": tv["目标"] or "—"}})
        t["flow"] = [{"日期": flow.short_time(r.get("时间", "")), "状态": r.get("后状态", ""),
                      "经办人": r.get("发起", ""), "接手人": r.get("接收", ""),
                      "说明": (r["边"] + ("：" + r["结果"] if r.get("结果") else "") + " · " + r.get("说明", "")).strip(" ·")}
                     for r in flow.proj_rows(proj, tv["编号"])]
        tasks.append(t)
    goals = []
    for gv in v["目标"]:
        g = dict(old_goals.get(gv["编号"]) or {"id": gv["编号"], "fields": [], "file": "", "archived": False, "head": {}})
        head = dict(g.get("head") or {})
        head["状态"] = gv["状态"]
        head["工作目录"] = gv["工作目录"]
        g.update({"title": g.get("title") or gv["标题"], "state": gv["状态"], "head": head, "archived": g.get("archived", False),
                  "idea": gv["起草阶段"], "files": gv["文件"], "questions": gv["待解决"]})  # 起草阶段：想法/讨论/方案，不在起草是 None；文件：讨论、方案的路径（归档后在归档/目标/下）
        g["stages"] = [{"no": s["序"], "seat": s["名称"], "who": "、".join(s["人选"]), "output": s["产出"], "cond": s["通过条件"],
                        "tasks": s["任务"], "missing": [], "status": STAGE_STATUS.get(s["状态"], s["状态"])} for s in gv["阶段"]]
        cur = next((s for s in g["stages"] if s["status"] != "通过"), None)
        g["current"] = cur["no"] if cur else None
        goals.append(g)
    return tasks, goals, v


def issue_archived(root: Path) -> set:
    d = root / "collab" / "归档" / "议题"
    return {re.match(r"I\d+", f.name).group(0) for f in d.glob("I*.md")} if d.is_dir() else set()


def flow_issue_rows(root: Path, view: Optional[Dict[str, Any]] = None, runs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """新结构项目的议题面板：只放结论（状态、所属目标、与会、总结、裁决）和谁在思考；发言在对话页。"""
    v = view or flow.view(flow.Project(root))
    arch = issue_archived(root)
    live = [r for r in (runs if runs is not None else parse_runs(root / "collab")) if r.get("status") == "运行中"]
    out = []
    for i in v["议题"]:
        last = i["消息"][-1] if i["消息"] else None
        out.append({"id": i["编号"], "title": i["标题"], "stage": i["状态"], "flow": True, "archived": i["编号"] in arch,
                    "type": i["类型"], "goal": i["目标"] or "", "holder": i["持有人"] or "",
                    "attendees": i["与会"], "summary": i["总结"], "ruling": i["裁决"], "count": i["发言数"],
                    "last": {"who": last["发起"], "time": last.get("时间", ""), "private": bool(last.get("私下")),
                             "text": "" if last.get("私下") else flow.first_line(last.get("正文", "") or "[PASS]")} if last else None,
                    "thinking": sorted({r["member"] for r in live if r.get("task") == i["编号"]})})
    return out


def meet_data(p: Dict[str, Any], iid: str) -> Optional[Dict[str, Any]]:
    """朝会页：这个议题的全部消息（总裁能看私下），与会、谁在思考；左栏是本项目的议题列表。"""
    root = Path(p["root"])
    v = flow.view(flow.Project(root))
    issue = next((i for i in v["议题"] if i["编号"] == iid), None)
    if not issue:
        return None
    runs = parse_runs(root / "collab")
    goal = next((g for g in v["目标"] if g["编号"] == issue["目标"]), None)
    return {"project": {"id": p["id"], "name": p["name"]}, "issue": issue,
            "goal": {"id": goal["编号"], "title": goal["标题"], "state": goal["状态"]} if goal else None,
            "rooms": flow_issue_rows(root, v, runs),
            "thinking": sorted({r["member"] for r in runs if r.get("status") == "运行中" and r.get("task") == iid}),
            "runs": [run_view(r, root) for r in runs if r.get("task") == iid],
            "pool": team_pool(flow.Project(root)),
            "ready": read_ready(root, iid),
            "称谓": v.get("称谓", {}),
            "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds")}


def read_ready(root: Path, iid: str) -> Dict[str, Any]:
    """总管搭会议室时的启动检查结果（dispatch.py room / ready 写的 <议题>.到场.txt）。"""
    f = root / "collab" / RUNS_DIR / f"{iid}.到场.txt"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def goal_post(p: Dict[str, Any], gid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """总裁在项目页对框架的动作：批准、退回、提意见。写一条事件（flow.record，和命令行同一套检查）。"""
    act = body.get("action")
    if act not in GOAL_ACTIONS:
        raise flow.hard(f"不认识的动作「{act}」")
    proj = flow.Project(Path(p["root"]))
    text = (body.get("text") or "").strip()
    a: Dict[str, Any] = {"发起": flow.BOSS, "写入者": "看板"}
    obj = gid
    if act == "批准":
        if body.get("version") is None:
            raise flow.hard("批准要带看到的框架版本")
        a.update(框架版本=int(body["version"]), 依据=flow.APPROVE_BASIS.format(int(body["version"])) + (f"：{text}" if text else ""))
    else:
        if not text:
            raise flow.hard("要写意见")
        a["说明"] = text
    if act == "意见" and body.get("task"):
        obj = str(body["task"])
        states, _, _ = flow.replay_all(proj)
        if (states.get(obj) or {}).get("目标") != gid:
            raise flow.hard(f"{obj} 不是 {gid} 的任务")
    ev, _ = flow.record(proj, obj, act, a)
    return {"ok": True, "seq": ev.get("seq")}


def meet_post(p: Dict[str, Any], iid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """总裁在朝会页的动作：写一条事件（flow.record，和命令行同一套检查），再按需后台叫醒成员。"""
    act = body.get("action")
    if act not in MEET_ACTIONS:
        raise flow.hard(f"不认识的动作「{act}」")
    root = Path(p["root"])
    proj = flow.Project(root)
    text = (body.get("text") or "").strip()
    a: Dict[str, Any] = {"发起": flow.BOSS, "写入者": "看板"}
    if act == "发言":
        states, _, _ = flow.replay_all(proj)
        st = states.get(iid) or {}
        allowed = {flow.LEAD} | {x["成员"] for x in st.get("与会", [])}
        called = []
        for w in flow.MENTION_RE.findall(text):
            x = proj.actor(w)
            if x in allowed and x not in called:
                called.append(x)
        a.update(正文=text, 点名=called, 私下=bool(body.get("private")), 类型=body.get("type") or None)
    elif act == "补叫":
        return redeliver(proj, iid, str(body.get("member") or ""))
    elif act == "加人":
        return add_attendees(proj, iid, body.get("members") or [], str(body.get("view") or ""))
    elif act in ("停止", "收尾"):
        return stop_or_wrap(proj, iid, act, str(body.get("member") or ""))
    elif act == "裁决":
        a.update(依据="总裁：" + text, 说明=text)
    elif act in ("继续讨论", "取消"):
        a.update(说明=text or ("总裁在朝会页继续讨论" if act == "继续讨论" else ""))
    ev, _ = flow.record(proj, iid, act, a)
    note = ""
    if act == "发言":
        members = [w for w in ev.get("点名", []) if w not in flow.MANAGERS]
        if members and not ev.get("私下"):
            note = wake_members(root, iid, members)
    return {"ok": True, "seq": ev["项目序"], "note": note}


def wake_members(root: Path, iid: str, members: List[str]) -> str:
    """后台叫醒（dispatch.py meet --wake --detach）；返回给页面的一句话，失败时以「没能叫醒」开头。"""
    r = subprocess.run([sys.executable, str(DISPATCH_PY), "--project", str(root), "meet", iid, "--wake", *members, "--detach"],
                       capture_output=True, text=True, timeout=60)
    msg = (r.stdout.strip() or r.stderr.strip()).splitlines()[-1:] or [""]
    return msg[0] if r.returncode == 0 else "没能叫醒：" + (r.stderr.strip() or r.stdout.strip())[-300:]


def redeliver(proj: "flow.Project", iid: str, member: str) -> Dict[str, Any]:
    """补叫：叫醒上次没跑成的成员，带上它错过的发言（派活脚本按上一次成功的「读到」补）。留一条进展事件做记录。"""
    st = (flow.replay_all(proj)[0]).get(iid) or {}
    who = proj.actor(member)
    if not who or who not in [x["成员"] for x in st.get("与会", [])]:
        raise flow.hard(f"{member or '（没写成员）'} 不在 {iid} 的与会名单里")
    if st.get("状态") != "讨论中":
        raise flow.hard(f"{iid} 现在是「{st.get('状态')}」，讨论中才能补叫")
    ev, _ = flow.record(proj, iid, "进展", {"发起": flow.BOSS, "写入者": "看板", "说明": f"总裁在朝会页补叫 {who}"})
    return {"ok": True, "seq": ev["项目序"], "note": wake_members(proj.root, iid, [who])}


def _secs(iso: Any) -> Optional[float]:
    try:
        return (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return None


def run_state(r: Dict[str, Any]) -> str:
    """页面上的状态：启动中 / 思考 / 调用工具 / 正在写回复 / 疑似卡住 / 失败 / 已停止 / 完成。"""
    st = r.get("status")
    if st == "运行中":
        quiet = _secs(r.get("last_at") or r.get("started"))
        if quiet is not None and quiet > STALL_SECONDS:
            return "疑似卡住"
        ph = r.get("phase")
        return ph if ph in ("启动中", "思考", "调用工具", "正在写回复") else ("思考" if r.get("last_at") else "启动中")  # 旧记录没有阶段
    return {"完成": "完成", "失败": "失败", "异常结束": "失败", "已中断": "已停止"}.get(st, st or "")


def run_view(r: Dict[str, Any], root: Path) -> Dict[str, Any]:
    out = {k: r.get(k) for k in ("run", "member", "seat", "status", "started", "ended", "error", "tokens", "steps",
                                 "last_action", "last_at", "phase", "stop_reason", "收尾")}
    out["state"] = run_state(r)
    started = _secs(r.get("started"))
    ended = _secs(r.get("ended")) if r.get("ended") else None
    out["elapsed"] = int(started - (ended or 0)) if started is not None else None
    out["quiet"] = int(_secs(r.get("last_at") or r.get("started")) or 0) if r.get("status") == "运行中" else None
    if r.get("status") == "运行中":
        try:
            out["draft"] = (root / "collab" / RUNS_DIR / f"{r['run']}.draft.txt").read_text(encoding="utf-8")[-6000:]
        except OSError:
            out["draft"] = ""
    return out


def stop_or_wrap(proj: "flow.Project", iid: str, act: str, member: str) -> Dict[str, Any]:
    """停止：停掉这位成员正在跑的运行，会话保留。收尾：先停止，再续接同一会话，要它用已有内容发言（后台进行）。"""
    st = (flow.replay_all(proj)[0]).get(iid) or {}
    who = proj.actor(member)
    if not who or who not in [x["成员"] for x in st.get("与会", [])]:
        raise flow.hard(f"{member or '（没写成员）'} 不在 {iid} 的与会名单里")
    if st.get("状态") != "讨论中":
        raise flow.hard(f"{iid} 现在是「{st.get('状态')}」，讨论中才能{act}")
    base = [sys.executable, str(DISPATCH_PY), "--project", str(proj.root)]
    if act == "停止":
        ev, _ = flow.record(proj, iid, "进展", {"发起": flow.BOSS, "写入者": "看板", "说明": f"总裁在朝会页停止了{who}"})
        r = subprocess.run(base + ["stop-member", iid, who], capture_output=True, text=True, timeout=60)
        lines = (r.stdout.strip() or r.stderr.strip()).splitlines()
        return {"ok": True, "seq": ev["项目序"], "note": lines[-1] if lines else ""}
    # 进展由 wrap 自己记：连点两次时第二次什么都不做，也不多记一条
    subprocess.Popen(base + ["wrap", iid, who, "--reason", "总裁在页面上点了收尾", "--page"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True, "note": f"已让 {who} 收尾"}


def team_pool(proj: "flow.Project") -> List[Dict[str, Any]]:
    """可以拉进会议室的成员：花名册里、班子配置里「可用」为 ✓ 的命令行成员（有启动命令的）。"""
    team = flow.team_dir() / "班子.json"
    cfg = {}
    if team.exists():
        try:
            cfg = {m.get("派活名"): m for m in json.loads(team.read_text(encoding="utf-8")).get("成员", [])}
        except (OSError, ValueError):
            cfg = {}
    out = []
    for m in proj.roster():
        c = cfg.get(m["派活名"])
        if c is not None and not c.get("新会话命令"):
            continue
        avail = str((c or {}).get("可用", "✓"))
        out.append({"name": m["派活名"], "title": m["名称"], "ok": avail.startswith("✓"), "note": "" if avail.startswith("✓") else avail,
                    "model": (c or {}).get("型号", "")})
    return out


def add_attendees(proj: "flow.Project", iid: str, members: List[Any], view_: str) -> Dict[str, Any]:
    """加人：把名单外的可用成员加进与会（记一条「变更」）。他不会被叫醒；总裁 @ 他时，他第一次发言能看到那句话之前的全部公开发言。"""
    st = (flow.replay_all(proj)[0]).get(iid) or {}
    if st.get("状态") not in ("起草", "讨论中", "收口中", "待裁决"):
        raise flow.hard(f"{iid} 现在是「{st.get('状态')}」，不能加人")
    pool = {m["name"]: m for m in team_pool(proj)}
    have = [x["成员"] for x in st.get("与会", [])]
    add = []
    for name in members:
        who = proj.actor(str(name))
        if not who or who not in pool:
            raise flow.hard(f"「{name}」不在班子里")
        if not pool[who]["ok"]:
            raise flow.hard(f"{who} 现在不可用：{pool[who]['note']}")
        if who in have or who in add:
            raise flow.hard(f"{who} 已经在会议室里")
        add.append(who)
    if not add:
        raise flow.hard("没有选成员")
    new = [{"成员": x["成员"], "视角": x["视角"]} for x in st["与会"]] + [{"成员": w, "视角": view_.strip()} for w in add]
    ev, _ = flow.record(proj, iid, "变更", {"发起": flow.BOSS, "写入者": "看板", "与会": new, "变更项": ["与会"],
                                            "说明": f"总裁在朝会页加人：{'、'.join(add)}"})
    return {"ok": True, "seq": ev["项目序"], "added": add}


def meetings() -> List[Dict[str, Any]]:
    """NOW 的朝会入口：各新结构项目里进行中和待裁决的议题，只读聚合。"""
    out = []
    for p in discover():
        root = Path(p["root"])
        if not (root / "collab" / "内部" / "流转").is_dir():
            continue
        try:
            rows = flow_issue_rows(root)
        except Exception:
            continue
        for i in rows:
            if i["stage"] in ("讨论中", "收口中", "待裁决") and not i["archived"]:
                out.append({"project": p["name"], "pid": p["id"], **{k: i[k] for k in ("id", "title", "stage", "type", "goal", "thinking")}})
    return out


def project_clock(collab: Path) -> Optional[str]:
    """演示案例停在剧情里的某一刻（collab/内部/流程/时钟.json）；看板上的「多久前」「已持有」按它算，没有就用真实时间。"""
    f = collab / "内部" / "流程" / "时钟.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))["现在"] if f.exists() else None
    except (OSError, ValueError, KeyError):
        return None


def project_data(p: Dict[str, Any]) -> Dict[str, Any]:
    mod = load_build()
    progress = Path(p["progress"])
    collab = progress.parent
    text = collab_parse.strip_comments(progress.read_text(encoding="utf-8"))
    secs = mod.sections(text)
    name = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), p["name"])
    meta_line = next((l for l in text.splitlines() if l.startswith("目标：")), "")

    def bullets(prefix: str) -> List[str]:
        _, ls = mod.find_section(secs, prefix)
        return [mod.inline(l.strip()[2:], collab) for l in ls
                if l.strip().startswith("- ") and not is_placeholder(l.strip()[2:])]

    def plain(prefix: str) -> List[str]:
        _, ls = mod.find_section(secs, prefix)
        out = []
        for l in ls:
            s = l.strip()
            if not s or s.startswith(("|", ">")) or is_placeholder(s):
                continue
            out.append(mod.inline(s[2:] if s.startswith("- ") else s, collab))
        return out

    view = None
    if (collab / "内部" / "流转").is_dir():
        tasks, goals, view = flow_cards(collab, Path(p["root"]))
    else:
        tasks = collab_parse.load_tasks(collab)
        goals = collab_parse.load_goals(collab, tasks)
    by_id = {t["id"]: t for t in tasks}
    _, task_lines = mod.find_section(secs, "任务")
    done_line = next((l for l in task_lines if l.startswith("已完成")), "")
    decisions = [mod.inline(re.sub(r"^\s*-\s*", "", l.strip()), collab) for t in ("决议", "生效决议")
                 for l in mod.find_section(secs, t)[1] if re.match(r"\s*-?\s*D\d+", l)]
    runs = parse_runs(collab)
    issues = flow_issue_rows(Path(p["root"]), view, runs) if view else collab_parse.load_issues(collab)
    archived = sum(1 for t in tasks if t["archived"])
    try:
        checked = collab_check.check(Path(p["root"]))
    except Exception as e:  # 校验器出错不影响看板
        checked = [{"level": "warn", "file": "", "line": None, "msg": f"校验器出错：{e}"}]
    return {
        "id": p["id"], "name": name, "root": p["root"],
        "progressHref": "file://" + quote(str(progress)),
        "meta": {k: v for k, v in kv_line(meta_line).items()},
        "next": " ".join(plain("▶ 下一步")),
        "status": bullets("现状"),
        "pending": [mod.inline(l[2:], collab) for l in flow.decision_lines(view)] if view else plain("卡点"),
        "decisions": decisions,
        "doneLine": mod.inline(done_line, collab),
        "archived": archived,
        "archivedCount": {"goals": sum(1 for g in goals if g["archived"]), "tasks": archived,
                          "issues": sum(1 for i in issues if i["archived"])},
        "cards": [html_task(mod, t, collab) for t in tasks if not t["archived"]],
        "goals": [html_goal(mod, g, by_id, collab) for g in goals if not g["archived"]],
        "issues": [i if i.get("flow") else html_issue(mod, i, collab) for i in issues if not i["archived"]],
        "runs": runs,
        "check": checked,
        "view": view,
        "clock": project_clock(collab),
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def archive_data(p: Dict[str, Any]) -> Dict[str, Any]:
    """归档页：只有归档的目标、任务、议题和它们的派活记录；打开时加载一次，不轮询。"""
    mod = load_build()
    progress = Path(p["progress"])
    collab = progress.parent
    text = collab_parse.strip_comments(progress.read_text(encoding="utf-8"))
    name = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), p["name"])
    view = None
    runs = parse_runs(collab)
    if (collab / "内部" / "流转").is_dir():  # 新结构：和项目页一样取自 flow.py 的视图模型，只读
        tasks, goals, view = flow_cards(collab, Path(p["root"]))
        issues = [i for i in flow_issue_rows(Path(p["root"]), view, runs) if i["archived"]]
    else:
        tasks = collab_parse.load_tasks(collab)
        goals = collab_parse.load_goals(collab, tasks)
        issues = [i for i in collab_parse.load_issues(collab) if i["archived"]]
    by_id = {t["id"]: t for t in tasks}
    cards = [t for t in tasks if t["archived"]]
    ids = {t["id"] for t in cards} | {i["id"] for i in issues}
    return {
        "id": p["id"], "name": name, "root": p["root"], "archive": True,
        "progressHref": "file://" + quote(str(progress)),
        "meta": {}, "pending": [], "decisions": [],
        "cards": [html_task(mod, t, collab) for t in cards],
        "goals": [html_goal(mod, g, by_id, collab) for g in goals if g["archived"]],
        "issues": [i if i.get("flow") else html_issue(mod, i, collab) for i in issues],
        "runs": [r for r in runs if r.get("task") in ids],
        "view": view,
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


# ---------- 班子页：班子.json 里的每个成员 + 各项目现算的现状和用量 ----------

def team_data() -> Dict[str, Any]:
    src = TEAM_DIR / "班子.json"
    team = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    members = [{k: v for k, v in m.items() if k not in ("新会话命令", "续接命令", "事件解析")} for m in team.get("成员", [])]
    names = {m.get("派活名") for m in members}
    stats = {n: {"runs": 0, "total": 0, "cached": 0, "last": "", "running": [], "holding": []} for n in names}
    for p in discover():
        collab = Path(p["progress"]).parent
        for r in parse_runs(collab):
            st = stats.get(r.get("member"))
            if not st:
                continue
            st["runs"] += 1
            tk = r.get("tokens") or {}
            st["total"] += tk.get("total") or 0
            st["cached"] += tk.get("cached") or 0
            st["last"] = max(st["last"], r.get("started") or "")
            if r.get("status") == "运行中":
                st["running"].append({"project": p["name"], "pid": p["id"], "run": r.get("run"), "started": r.get("started")})
        if (collab / "内部" / "流转").is_dir():
            try:
                v = flow.view(flow.Project(Path(p["root"])))
            except Exception:
                continue
            titles = {t["编号"]: t["标题"] for t in v["任务"]}
            for c in v["当前"]:
                st = stats.get(c.get("接收"))
                if st:
                    st["holding"].append({"project": p["name"], "pid": p["id"], "task": c["对象"],
                                          "title": titles.get(c["对象"], ""), "state": c["状态"]})
    return {
        "source": str(src), "exists": src.exists(),
        "members": members, "stats": stats,
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def talent_data() -> Dict[str, Any]:
    """人才市场：读静态的 ~/.collab-team/人才.json，没有时用工具包示例；附上班子成员名，标出谁已在班子里。"""
    src = TEAM_DIR / "人才.json"
    sample = not src.exists()
    if sample:
        src = TALENT_EXAMPLE
    talent = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    team_file = TEAM_DIR / "班子.json"
    team = json.loads(team_file.read_text(encoding="utf-8")) if team_file.exists() else {}
    return {"sample": sample, "source": str(src), "note": talent.get("说明", ""), "items": talent.get("人才", []),
            "members": [m.get("名称") for m in team.get("成员", [])]}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "board/1"

    def log_message(self, fmt, *args):
        if ARGS.verbose:
            super().log_message(fmt, *args)

    def send(self, code: int, body: bytes, ctype: str, csp: bool = True) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp:
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def json(self, data: Any, code: int = 200) -> None:
        self.send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path in ("/", "/now"):
                return self.send(200, now_html().encode("utf-8"), "text/html", csp=False)
            if path == "/api/projects":
                return self.json(discover())
            if path == "/api/team":
                return self.json(team_data())
            if path == "/team":
                return self.send(200, (STATIC / "team.html").read_bytes(), "text/html")
            if path == "/api/talent":
                return self.json(talent_data())
            if path == "/talent":
                return self.send(200, (STATIC / "talent.html").read_bytes(), "text/html")
            if path == "/api/meetings":
                return self.json(meetings())
            m = re.fullmatch(r"/api/p/([0-9a-f]{8})/meet/(I\d+)", path)
            if m:
                p = next((x for x in discover() if x["id"] == m.group(1)), None)
                data = meet_data(p, m.group(2)) if p and (Path(p["root"]) / "collab" / "内部" / "流转").is_dir() else None
                return self.json(data) if data else self.json({"error": "找不到这个议题"}, 404)
            if re.fullmatch(r"/p/[0-9a-f]{8}/meet/I\d+", path):
                return self.send(200, (STATIC / "meet.html").read_bytes(), "text/html")
            m = re.fullmatch(r"/api/p/([0-9a-f]{8})(/archive)?", path)
            if m:
                p = next((x for x in discover() if x["id"] == m.group(1)), None)
                if not p:
                    return self.json({"error": "找不到项目"}, 404)
                return self.json(archive_data(p) if m.group(2) else project_data(p))
            if re.fullmatch(r"/p/[0-9a-f]{8}(/archive)?", path):
                return self.send(200, (STATIC / "project.html").read_bytes(), "text/html")
            m = re.fullmatch(r"/static/([\w.-]+)", path)
            if m and m.group(1) in STATIC_FILES:
                return self.send(200, (STATIC / m.group(1)).read_bytes(), STATIC_FILES[m.group(1)])
            self.send(404, "找不到页面".encode("utf-8"), "text/plain")
        except Exception as e:
            self.send(500, f"出错：{e}".encode("utf-8"), "text/plain")

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if self.headers.get("X-Board") != "1":
            return self.send(403, b"forbidden", "text/plain")
        m = re.fullmatch(r"/api/p/([0-9a-f]{8})/meet/(I\d+)", path)
        if m:
            return self.meet_write(m.group(1), m.group(2))
        m = re.fullmatch(r"/api/p/([0-9a-f]{8})/goal/(G\d+)", path)
        if m:
            return self.meet_write(m.group(1), m.group(2), goal_post)
        if path != "/api/open":
            return self.send(403, b"forbidden", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            target = Path(json.loads(self.rfile.read(n) or b"{}").get("path", "")).expanduser()
        except (ValueError, TypeError):
            return self.json({"error": "参数错误"}, 400)
        home = Path.home().resolve()
        try:
            target = target.resolve()
        except OSError:
            return self.json({"error": "路径无效"}, 400)
        ok = target.exists() and home in target.parents and (target.is_dir() or target.suffix.lower() in OPEN_SUFFIXES)
        if not ok:
            return self.json({"error": f"不允许打开：{target}"}, 400)
        subprocess.Popen(["open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.json({"ok": True})


    def meet_write(self, pid: str, iid: str, handler=None):
        """受限写入口：只接受朝会的黑板事件和总裁对框架的动作，经 flow.record 校验；不合法的原样返回错误。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return self.json({"error": "参数错误"}, 400)
        p = next((x for x in discover() if x["id"] == pid), None)
        if not p or not (Path(p["root"]) / "collab" / "内部" / "流转").is_dir():
            return self.json({"error": "找不到项目"}, 404)
        try:
            return self.json((handler or meet_post)(p, iid, body))
        except flow.FlowError as e:
            return self.json({"error": e.msg, "kind": e.kind}, 400)
        except Exception as e:
            return self.json({"error": f"出错：{e}"}, 500)


def main() -> None:
    global ARGS
    ap = argparse.ArgumentParser(description="NOW 与御前看板网页服务")
    ap.add_argument("--port", type=int, default=3100)
    ap.add_argument("--now-dir", default=os.environ.get("COLLAB_NOW_DIR") or default_now_dir())
    ap.add_argument("--project", action="append", help="额外显示的项目目录（含 collab/PROGRESS.md），可重复")
    ap.add_argument("--verbose", action="store_true")
    ARGS = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    print(f"看板：http://127.0.0.1:{ARGS.port}  （Ctrl+C 停止）", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
