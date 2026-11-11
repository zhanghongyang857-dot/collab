#!/usr/bin/env python3
"""派活脚本：总管用它向命令行成员派活、续接、停止，并把每次派活写进项目的 collab/内部/运行记录/。

用法（在项目目录或其子目录里运行，或用 --project 指定）：
  dispatch.py start T003 执行 codex "启动语"      新会话派活（先按任务卡和目标流程检查）
  dispatch.py continue T003 执行 "追问或返工"      续接该任务该席位最近的会话
  dispatch.py stop T003-02                         停止一次派活
  dispatch.py stop --all                           停止本项目所有正在跑的派活
  dispatch.py list [--all]                         列出派活（默认只列运行中和最近 10 条）
  dispatch.py show T003-02                         显示一次派活的记录和最终回复
  dispatch.py meet I003 [--round N]                朝会（旧结构）：召集议题「与会」表里的成员开下一轮，发言原文写入议题文件
  dispatch.py meet I003 [--wake 成员 …] [--detach]  朝会（新结构，有 collab/内部/流转/）：叫醒与会者，只喂增量；
                                                   不写 --wake 时叫醒还没开过口的（第 1 轮）。发言由各自的派活写回黑板，
                                                   只有总裁的 @ 能叫醒人，同一成员同时只跑一次
  dispatch.py room --标题 … --与会 成员:视角 … --依据 "总裁原话" [--问题 …] [--开场 …]
                                                   搭会议室：建议题、写开场约定、启动检查，都就绪就直接进「讨论中」并给出地址
  dispatch.py ready I003                           对「起草」中的议题重做启动检查，就绪就进「讨论中」
  dispatch.py check [成员 …]                       启动检查：用一次最小的真实调用确认成员能启动、已登录

启动语写 "-" 时从标准输入读取。
派活前三道关，不过就不派（退出码 2）：
  1. 校验 collab/（core/check.py）没有错误；确需跳过加 --skip-check "理由"。
  2. 硬性条件：有任务卡（临时派活加 --adhoc "理由"）；卡没结束；目标已批准，零散任务有总裁批准记录。这一关不能跳过。
  3. 流程：前面的阶段都通过、席位和人选与流程表和卡头一致；确需偏离加 --override "理由"。
跳过和偏离的理由都记入运行记录，看板标为「偏离」。命令在 CLI 结束时才退出，适合总管以后台命令运行。
只用 Python 标准库。
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collab_parse  # noqa: E402  与看板共用的任务卡、目标卡解析
import check as collab_check  # noqa: E402  collab/ 校验，与 Stop hook、看板共用
import team as team_mod  # noqa: E402
import flow  # noqa: E402  新结构项目（有 collab/内部/流转/）：派发、接手、进展由本脚本经 flow.py 代写
import paths as P  # noqa: E402
from vocab import Edge as E, IssueType, Kind, RunMode, RunPhase, RunStatus, Seat, Section, State as S, Writer  # noqa: E402
TEAM_FILE = flow.team_file()
RUNS_DIR = P.INTERNAL_RUNS
HEARTBEAT_SECONDS = 5  # 事件密集时，最多每隔几秒写一次记录
ACTION_LIMIT = 100

L = flow.i18n.current  # 输出文字（派活脚本的提示）：跟着项目语言，main 里按项目设
RUNNING, DONE, FAILED, STOPPED, LOST = RunStatus.RUNNING, RunStatus.DONE, RunStatus.FAILED, RunStatus.STOPPED, RunStatus.LOST


# ---------- 启动环境：成员在什么 PATH、什么认证变量下启动 ----------

# 桌面版 Claude 会话带来的认证和会话变量：传给 Claude 成员会让它报「未登录」（I001），启动成员时一律去掉
# 桌面版带来的变量名不固定（CLAUDE_AGENT_SDK_*、CLAUDE_PREVIEW_* 等），所以 CLAUDE 开头的一律去掉，只留用户自己的配置
STRIP_PREFIXES = ("ANTHROPIC_", "CLAUDE")
KEEP_NAMES = ("CLAUDE_CONFIG_DIR",)
_LOGIN_PATH: Optional[str] = None


def _nvm_bins() -> List[str]:
    """nvm 下各 Node 版本的 bin 目录，新版本在前；不写死版本号。"""
    root = Path(os.environ.get("NVM_DIR") or "~/.nvm").expanduser() / "versions" / "node"
    if not root.is_dir():
        return []

    def key(p: Path):
        return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", p.name.lstrip("v"))]
    return [str(d / "bin") for d in sorted(root.iterdir(), key=key, reverse=True) if (d / "bin").is_dir()]


def login_path() -> str:
    """登录 shell 的 PATH（看板是开机常驻服务，自己的 PATH 只有系统目录）；取不到时用 Homebrew 和 nvm 的常见位置补。
    结果和当前进程 PATH 合并去重，登录 PATH 在前。同一进程只取一次。"""
    global _LOGIN_PATH
    if _LOGIN_PATH is not None:
        return _LOGIN_PATH
    found: List[str] = []
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        r = subprocess.run([shell, "-ilc", 'printf "\\n__PATH__%s\\n" "$PATH"'], capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL, env={k: v for k, v in os.environ.items() if k in ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "TMPDIR")})
        for line in r.stdout.splitlines():
            if line.startswith("__PATH__"):
                found = line[len("__PATH__"):].split(":")
    except (OSError, subprocess.SubprocessError):
        pass
    extra = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"] + _nvm_bins()
    parts: List[str] = []
    for d in found + os.environ.get("PATH", "").split(":") + extra:
        if d and d not in parts:
            parts.append(d)
    _LOGIN_PATH = ":".join(parts)
    return _LOGIN_PATH


def member_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """命令行成员的启动环境：登录 PATH，去掉桌面版带来的认证和会话变量（ANTHROPIC_* 和所有 CLAUDE* 开头的，只留 CLAUDE_CONFIG_DIR）；朝会和普通派活走同一处。"""
    env = {k: v for k, v in os.environ.items() if k in KEEP_NAMES or not k.startswith(STRIP_PREFIXES)}
    env["PATH"] = login_path()
    env.update(extra or {})
    return env


def which(cmd: str, env: Dict[str, str]) -> Optional[str]:
    return shutil.which(cmd, path=env.get("PATH"))


# ---------- 通用 ----------

def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def clip(text: Any, limit: int = ACTION_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def find_project(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / P.COLLAB / P.PROGRESS).exists():
            return p
    sys.exit(L.t("flow.no_project", start=start))


def runs_dir(project: Path) -> Path:
    d = project / P.COLLAB / RUNS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load_runs(project: Path) -> List[Dict[str, Any]]:
    """读出全部派活记录，按开始时间排序；标为运行中但进程已不在的，视为异常结束（只在返回值里改，不写回）。"""
    d = project / P.COLLAB / RUNS_DIR
    runs = []
    if d.exists():
        for f in d.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if r.get("status") == RUNNING and not pid_alive(r.get("pid")):
                r["status"] = LOST
            runs.append(r)
    runs.sort(key=lambda r: (r.get("started") or "", r.get("run") or ""))
    return runs


def members_source() -> Path:
    return TEAM_FILE


def load_members() -> Dict[str, Any]:
    """成员来自班子配置（班子目录见 flow.team_dir()）；没有班子配置时报错，先运行 init.sh team。"""
    if not TEAM_FILE.exists():
        sys.exit(L.t("disp.no_team", path=TEAM_FILE))
    team = team_mod.read(TEAM_FILE)
    out = {}
    for x in team.get("members", []):
        did = x.get("dispatch_name")
        if not did or not x.get("start_command"):
            continue
        out[did] = {"aliases": x.get("aliases") or [did], "parser": x.get("parser", did),
                    "start": x["start_command"], "resume": x.get("resume_command", []),
                    "available": str(x.get("available", "✓"))}
    return out


def new_run_id(rdir: Path, task: str, member: str = "", seat: str = "") -> str:
    """任务编号 + 两位序号；用 O_EXCL 抢占文件，避免同时派活时撞号。抢到后立刻写一份占位记录（运行中、本进程），
    读记录的人（看板、测试）不会读到空文件，也能马上看到「启动中」。"""
    n = 1
    for f in rdir.glob(f"{task}-*.json"):
        m = re.fullmatch(re.escape(task) + r"-(\d+)\.json", f.name)
        if m:
            n = max(n, int(m.group(1)) + 1)
    while True:
        rid = f"{task}-{n:02d}"
        try:
            fd = os.open(rdir / f"{rid}.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, (json.dumps({"run": rid, "task": task, "member": member, "seat": seat, "status": RUNNING,
                                      "pid": os.getpid(), "started": now_iso(), "phase": RunPhase.STARTING}, ensure_ascii=False) + "\n").encode("utf-8"))
            os.close(fd)
            return rid
        except FileExistsError:
            n += 1


# ---------- 各成员事件解析：每行事件 → 会话 ID / 最近动作 / 最终回复 / 错误 ----------

def _tool_brief(name: str, inp: Any) -> str:
    if isinstance(inp, dict):
        for k in ("description", "command", "file_path", "path", "pattern", "url", "query"):
            if inp.get(k):
                return f"{name}：{inp[k]}"
    return name


def parse_dsh(ev: Dict[str, Any], out: Dict[str, Any]) -> None:
    t = ev.get("type")
    if t == "session" and ev.get("sessionId"):
        out["session"] = ev["sessionId"]
    elif t == "tool_call":
        out["action"] = _tool_brief(ev.get("tool", L.t("disp.tool")), ev.get("input"))
        out["step"] = True
    elif t == "final":
        out["final"] = ev.get("text", "")
    elif t == "status" and ev.get("phase"):
        out["phase"] = ev["phase"]
    elif t in ("error", "turn_end") and (ev.get("error") or ev.get("message")):
        out["error"] = clip(ev.get("error") or ev.get("message"), 300)


def parse_codex(ev: Dict[str, Any], out: Dict[str, Any]) -> None:
    t = ev.get("type")
    item = ev.get("item") or {}
    it = item.get("type")
    if t == "thread.started" and ev.get("thread_id"):
        out["session"] = ev["thread_id"]
    elif t == "item.started" and it == "command_execution":
        out["action"] = L.t("disp.action.run") + str(item.get("command", ""))
        out["step"] = True
    elif t == "item.completed" and it == "file_change":
        paths = [c.get("path", "") for c in item.get("changes") or []]
        out["action"] = L.t("disp.action.edit") + L.join(Path(p).name for p in paths if p)
        out["step"] = True
    elif t == "item.started" and it in ("mcp_tool_call", "web_search"):
        out["action"] = _tool_brief(item.get("tool") or it, item.get("arguments") or {"query": item.get("query")})
        out["step"] = True
    elif t == "item.completed" and it == "agent_message":
        out["final"] = item.get("text", "")
    elif t == "turn.failed":
        out["error"] = clip((ev.get("error") or {}).get("message", "turn.failed"), 300)
    elif t == "error":
        out["error"] = clip(ev.get("message", "error"), 300)


def parse_claude(ev: Dict[str, Any], out: Dict[str, Any]) -> None:
    """phase：启动中 / 思考 / 调用工具 / 正在写回复；draft_reset、draft_add 是 --include-partial-messages 给的正在写的内容。"""
    t = ev.get("type")
    if ev.get("session_id") and t in ("system", "result"):
        out["session"] = ev["session_id"]
    if t == "tool_progress" and ev.get("heartbeat"):  # 工具运行时每 30 秒一次，只说明命令行活着，不说明工具有进展
        out["heartbeat"] = True
        return
    if t == "stream_event":
        e = ev.get("event") or {}
        et = e.get("type")
        if et == "message_start":
            out["phase"] = RunPhase.THINKING
            out["draft_reset"] = True
        elif et == "content_block_start":
            cb = e.get("content_block") or {}
            if cb.get("type") == "text":
                out["phase"] = RunPhase.WRITING
            elif cb.get("type") in ("tool_use", "server_tool_use"):
                out["phase"] = RunPhase.TOOL
                out["action"] = cb.get("name", L.t("disp.tool"))
            else:
                out["phase"] = RunPhase.THINKING
        elif et == "content_block_delta":
            d = e.get("delta") or {}
            if d.get("type") == "text_delta" and d.get("text"):
                out["draft_add"] = d["text"]
        return
    if t == "user":
        out["phase"] = RunPhase.THINKING
    if t == "assistant":
        for c in (ev.get("message") or {}).get("content") or []:
            if c.get("type") == "tool_use":
                out["action"] = _tool_brief(c.get("name", L.t("disp.tool")), c.get("input"))
                out["step"] = True
    elif t == "result":
        out["final"] = ev.get("result", "")
        if ev.get("is_error"):
            # 续接失败等情况 result 是空的，真正的原因在 errors 里；都没有才用 subtype
            out["error"] = clip(ev.get("result") or "；".join(str(x) for x in ev.get("errors") or []) or ev.get("subtype") or "is_error", 300)


PARSERS = {"dsh": parse_dsh, "codex": parse_codex, "claude": parse_claude}


# ---------- token 汇总：每次派活记一行（输入、缓存、输出、调用次数、最后上下文）；算错只记未知，不影响派活 ----------

def _n(v: Any) -> int:
    return v if isinstance(v, int) else 0


def usage_dsh(ev: Dict[str, Any], acc: Dict[str, Any]) -> None:
    """每次模型调用结束（status/step_end）带一次 usage，逐次相加；totalTokens 即这次调用的上下文。"""
    u = ev.get("usage") if ev.get("type") == "status" else None
    if isinstance(u, dict):
        acc["calls"] = acc.get("calls", 0) + 1
        acc["input"] = acc.get("input", 0) + _n(u.get("inputTokens")) + _n(u.get("cacheWriteTokens"))
        acc["cached"] = acc.get("cached", 0) + _n(u.get("cacheReadTokens"))
        acc["output"] = acc.get("output", 0) + _n(u.get("outputTokens"))
        acc["context"] = _n(u.get("totalTokens"))


def usage_codex(ev: Dict[str, Any], acc: Dict[str, Any]) -> None:
    """turn.completed 给的是整个会话的累计数，续接时减去上一次派活记下的累计（_base）。"""
    u = ev.get("usage") if ev.get("type") == "turn.completed" else None
    if isinstance(u, dict):
        cached = _n(u.get("cached_input_tokens"))
        cum = {"input": _n(u.get("input_tokens")) - cached, "cached": cached, "output": _n(u.get("output_tokens"))}
        base = acc.get("_base") or {}
        acc["session_cum"] = cum
        for k, v in cum.items():
            acc[k] = max(v - _n(base.get(k)), 0)


def usage_claude(ev: Dict[str, Any], acc: Dict[str, Any]) -> None:
    if ev.get("type") == "assistant":  # 运行中的实时用量：按消息 ID 取最新一次，result 到了再换成权威数字
        m = ev.get("message") or {}
        u = m.get("usage")
        if isinstance(u, dict) and m.get("id"):
            msgs = acc.setdefault("_msgs", {})
            msgs[m["id"]] = u
            acc["input"] = sum(_n(x.get("input_tokens")) + _n(x.get("cache_creation_input_tokens")) for x in msgs.values())
            acc["cached"] = sum(_n(x.get("cache_read_input_tokens")) for x in msgs.values())
            acc["output"] = sum(_n(x.get("output_tokens")) for x in msgs.values())
            acc["calls"] = len(msgs)
        return
    u = ev.get("usage") if ev.get("type") == "result" else None
    if isinstance(u, dict):
        acc["input"] = _n(u.get("input_tokens")) + _n(u.get("cache_creation_input_tokens"))
        acc["cached"] = _n(u.get("cache_read_input_tokens"))
        acc["output"] = _n(u.get("output_tokens"))
        if isinstance(ev.get("num_turns"), int):
            acc["calls"] = ev["num_turns"]
        it = (u.get("iterations") or [None])[-1]
        if isinstance(it, dict):
            acc["context"] = sum(_n(it.get(k)) for k in ("input_tokens", "cache_read_input_tokens",
                                                          "cache_creation_input_tokens", "output_tokens"))
        if isinstance(ev.get("total_cost_usd"), (int, float)):
            acc["cost_usd"] = round(ev["total_cost_usd"], 4)


USAGE = {"dsh": usage_dsh, "codex": usage_codex, "claude": usage_claude}


def finish_tokens(acc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """去掉内部字段、补总量；没有任何用量时返回 None（记为未知）。"""
    out = {k: v for k, v in acc.items() if not k.startswith("_")}
    if not any(k in out for k in ("input", "cached", "output")):
        return None
    out["total"] = out.get("input", 0) + out.get("cached", 0) + out.get("output", 0)
    return out


def fmt_tokens(t: Optional[Dict[str, Any]]) -> str:
    """「49万 · 缓存89%」；没有数据写「—」。"""
    if not t or not t.get("total"):
        return "—"
    n = t["total"]
    if L.lang == "zh":
        s = f"{n / 10000:.1f}万".replace(".0万", "万") if n >= 10000 else str(n)
    else:
        s = f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)
    return s + L.t("disp.tokens_cached", pct=round(100 * t.get('cached', 0) / n)) if t.get("cached") else s


# ---------- 启动检查：用一次真实的最小调用确认成员能启动、已登录 ----------

def check_prompt() -> str:
    return L.t("disp.check_prompt")
CHECK_SECONDS = 120


def _exe_of(argv: List[str]) -> str:
    """argv 里真正要启动的程序（跳过 env 和 KEY=VALUE）。"""
    for t in argv:
        if t == "env" or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            continue
        return t
    return ""


def check_member(key: str, cfg: Dict[str, Any], timeout: int = CHECK_SECONDS) -> Dict[str, Any]:
    """启动检查：在临时目录里用成员自己的启动命令和启动环境跑一句最小的话，收到「就绪」类回复才算通过。
    不用 claude auth status（桌面版变量没清干净时它也显示已登录，实际仍失败）。不写运行记录、不留会话。"""
    t0 = time.time()
    res: Dict[str, Any] = {"member": key, "ok": False, "error": "", "time": now_iso(), "seconds": 0}
    if not cfg.get("available", "✓").startswith("✓"):
        res["error"] = L.t("disp.check_skipped", status=cfg['available'])
        res["skipped"] = True
        return res
    env = member_env()
    with tempfile.TemporaryDirectory() as tmp:
        argv = isolate(build_argv(cfg, "start", check_prompt(), "", Path(tmp) / "last.txt"))
        if Path(_exe_of(argv)).name == "claude" and "--no-session-persistence" not in argv:
            i = argv.index(_exe_of(argv))
            argv = argv[:i + 1] + ["--no-session-persistence"] + argv[i + 1:]
        exe = _exe_of(argv)
        if exe and not which(exe, env):
            res["error"] = L.t("disp.no_command", exe=exe)
            return res
        out: Dict[str, Any] = {}
        tokens: Dict[str, Any] = {}
        usage = USAGE.get(cfg["parser"])
        try:
            r = subprocess.run(argv, cwd=tmp, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            res.update(error=L.t("disp.check_timeout", n=timeout), seconds=round(time.time() - t0, 1))
            return res
        except OSError as e:
            res.update(error=L.t("disp.cant_start", e=e), seconds=round(time.time() - t0, 1))
            return res
        for line in r.stdout.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                PARSERS[cfg["parser"]](ev, out)
                if usage:
                    try:
                        usage(ev, tokens)
                    except Exception:
                        pass
        last = Path(tmp) / "last.txt"
        if last.exists() and last.read_text(encoding="utf-8", errors="replace").strip():
            out["final"] = last.read_text(encoding="utf-8", errors="replace").strip()
    res["seconds"] = round(time.time() - t0, 1)
    tk = finish_tokens(tokens)
    if tk:
        res["tokens"] = tk.get("total")
    if r.returncode == 0 and (out.get("final") or "").strip() and not out.get("error"):
        res["ok"] = True
    else:
        res["error"] = clip(out.get("error") or (r.stderr.strip().splitlines() or [""])[-1] or out.get("final")
                            or L.t("disp.exit_no_reply", code=r.returncode), 200)
    return res


def check_members(project: Path, keys: List[str]) -> List[Dict[str, Any]]:
    """并行检查多位成员，按传入顺序返回。"""
    members = load_members()
    results: Dict[str, Dict[str, Any]] = {}

    def one(k: str) -> None:
        if k not in members:
            results[k] = {"member": k, "ok": False, "error": L.t("disp.not_in_team"), "time": now_iso(), "seconds": 0}
        else:
            results[k] = check_member(k, members[k])
    threads = [threading.Thread(target=one, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [results[k] for k in keys]


def cmd_check(a, project: Path) -> int:
    members = load_members()
    keys = [resolve_member(x, members) or x for x in a.members] or list(members)
    ok = True
    for r in check_members(project, keys):
        mark = L.t("disp.ready") if r["ok"] else (L.t("disp.skipped") if r.get("skipped") else L.t("disp.not_ready"))
        print(f"{r['member']:<14} {mark}  {L.t('disp.seconds', n=r['seconds'])}{'  ' + str(r['tokens']) + ' token' if r.get('tokens') else ''}"
              f"{'  ' + r['error'] if r['error'] else ''}")
        ok = ok and (r["ok"] or bool(r.get("skipped")))
    return 0 if ok else 1


# ---------- 运行一次派活 ----------

class Runner:
    def __init__(self, project: Path, rec: Dict[str, Any], argv: List[str], parser: str,
                 token_base: Optional[Dict[str, Any]] = None, env: Optional[Dict[str, str]] = None,
                 flow_actor: str = "", limits: Optional[Dict[str, int]] = None):
        self.project = project
        self.env = env if env is not None else member_env()
        self.flow_actor = flow_actor  # 新结构项目：结束后经 flow.py 写进展，没写结束边时代写上报
        self.rdir = runs_dir(project)
        self.rec = rec
        self.argv = argv
        self.parse = PARSERS[parser]
        self.usage = USAGE.get(parser)
        self.tokens: Dict[str, Any] = {"_base": token_base} if token_base else {}
        self.token_error = False
        self.meta = self.rdir / f"{rec['run']}.json"
        self.events = self.rdir / f"{rec['run']}.stream.jsonl"  # 命令行原始输出，和 collab/内部/流转/ 的事件区分开
        self.errfile = self.rdir / f"{rec['run']}.err"
        self.child: Optional[subprocess.Popen] = None
        self.stopping = False
        self.dirty = False
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.limits = limits or {}  # {"steps": n, "seconds": n}；到了就停掉这次运行，rec["stop_reason"] 写明原因
        self.draft = ""
        self.draft_at = 0.0
        self.draft_file = self.rdir / f"{rec['run']}.draft.txt"

    def trip(self, reason: str) -> None:
        """到运行上限：记下原因，停掉命令行进程（状态为已中断，调用方决定是否让它收尾）。"""
        if self.stopping:
            return
        self.rec["stop_reason"] = L.t("disp.limit_prefix") + reason
        self.rec["stop_limit"] = reason  # 到上限停的：收尾时用这里的原因，不解析文字
        self.stopping = True
        self.save(force=True)
        if self.child and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def watchdog(self) -> None:
        secs = self.limits.get("seconds")
        t0 = time.time()
        while not self.done.wait(2):
            if secs and time.time() - t0 > secs:
                self.trip(L.t("disp.limit_minutes", n=secs // 60) if secs % 60 == 0 else L.t("disp.limit_seconds", n=secs))
                return

    def write_draft(self, force: bool = False) -> None:
        if force or time.time() - self.draft_at >= 0.3:
            self.draft_at = time.time()
            tmp = self.draft_file.with_name(self.draft_file.name + ".tmp")
            tmp.write_text(self.draft, encoding="utf-8")
            os.replace(tmp, self.draft_file)

    def save(self, force: bool = False) -> None:
        """force 立即写；否则只标记，由 flusher 每隔 HEARTBEAT_SECONDS 写一次。"""
        with self.lock:
            if force:
                write_json(self.meta, self.rec)
                self.dirty = False
            else:
                self.dirty = True

    def flusher(self) -> None:
        while not self.done.wait(HEARTBEAT_SECONDS):
            with self.lock:
                if self.dirty:
                    write_json(self.meta, self.rec)
                    self.dirty = False

    def on_signal(self, signum, _frame) -> None:
        self.stopping = True
        if self.child and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.on_signal)
        signal.signal(signal.SIGINT, self.on_signal)
        signal.signal(signal.SIGHUP, self.on_signal)
        self.rec.update(status=RUNNING, pid=os.getpid(), started=now_iso(), phase=RunPhase.STARTING, phase_at=now_iso())
        self.save(force=True)
        print(L.t("disp.run_head", run=self.rec['run'], member=self.rec['member'], seat=L.name('seat', self.rec['seat']), task=self.rec['task'])
              + (L.t("disp.run_resume", session=self.rec['session']) if self.rec.get('session') else ""), flush=True)
        try:
            err = self.errfile.open("w", encoding="utf-8")
            self.child = subprocess.Popen(self.argv, cwd=self.project, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=err, env=self.env,
                                          start_new_session=True, text=True, encoding="utf-8",
                                          errors="replace", bufsize=1)
        except OSError as e:
            self.rec.update(status=FAILED, ended=now_iso(), error=L.t("disp.cant_start", e=e))
            self.save(force=True)
            print(self.rec["error"], file=sys.stderr)
            return 127
        self.rec["child_pid"] = self.child.pid
        self.save(force=True)
        threading.Thread(target=self.flusher, daemon=True).start()
        threading.Thread(target=self.watchdog, daemon=True).start()

        with self.events.open("a", encoding="utf-8") as log:
            for line in self.child.stdout:
                log.write(line)
                log.flush()
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                out: Dict[str, Any] = {}
                self.parse(ev, out)
                if not out.get("heartbeat"):  # 心跳不算动静，否则工具卡住时静默时间超不过心跳间隔，永远不显示疑似卡住
                    self.rec["last_at"] = now_iso()
                if self.rec.get("phase") == RunPhase.STARTING and not out.get("phase") and set(out) != {"session"}:
                    out["phase"] = RunPhase.THINKING  # 只报了会话 ID 的初始化事件还算启动中；有的成员不报阶段，有别的输出就算思考
                if out.get("session") and not self.rec.get("session"):
                    self.rec["session"] = out["session"]
                    self.save(force=True)
                    print(L.t("disp.session", session=out['session']), flush=True)
                if out.get("draft_reset"):
                    self.draft = ""
                if out.get("draft_add"):
                    self.draft += out["draft_add"]
                    self.write_draft()
                if out.get("action"):
                    self.rec["last_action"] = clip(out["action"])
                if out.get("phase") and out["phase"] != self.rec.get("phase"):
                    self.rec["phase"], self.rec["phase_at"] = out["phase"], now_iso()
                    self.save(force=True)
                if out.get("step"):
                    self.rec["steps"] = self.rec.get("steps", 0) + 1
                    if self.limits.get("steps") and self.rec["steps"] >= self.limits["steps"]:
                        self.trip(L.t("disp.limit_steps", n=self.limits['steps']))
                if "final" in out:
                    self.rec["final"] = out["final"]
                if out.get("error"):
                    self.rec["error"] = out["error"]
                if self.usage and not self.token_error:
                    try:
                        self.usage(ev, self.tokens)
                        t = finish_tokens(self.tokens)
                        if t:
                            self.rec["tokens"] = t
                    except Exception:  # 统计出错只记未知，派活照常
                        self.token_error = True
                        self.rec.pop("tokens", None)
                self.save()

        code = self.child.wait()
        self.done.set()
        err.close()
        self.draft_file.unlink(missing_ok=True)
        stderr = self.errfile.read_text(encoding="utf-8", errors="replace")
        if not stderr.strip():
            self.errfile.unlink()
        last = self.rdir / f"{self.rec['run']}.last.txt"
        if last.exists():
            text = last.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                self.rec["final"] = text
            last.unlink()
        if self.stopping:
            status = STOPPED
        elif code == 0 and not (self.rec.get("error") and not self.rec.get("final")):
            status = DONE
        else:
            status = FAILED
            if not self.rec.get("error"):
                self.rec["error"] = clip(stderr.strip().splitlines()[-1] if stderr.strip() else L.t("disp.exit_code", code=code), 300)
            elif self.rec["error"] in ("is_error", "error_during_execution") and stderr.strip():
                self.rec["error"] = clip(stderr.strip().splitlines()[-1], 300)
        self.rec.update(status=status, ended=now_iso(), exit_code=code, last_at=now_iso())
        self.rec.pop("child_pid", None)
        self.rec["phase"] = {DONE: RunPhase.DONE, FAILED: RunPhase.FAILED, STOPPED: RunPhase.STOPPED}.get(status, status)
        self.save(force=True)
        if self.flow_actor:
            try:
                done = flow.dispatch_end(flow.Project(self.project), self.rec["task"], self.flow_actor, self.rec["run"],
                                         self.rec.get("session", ""), self.rec.get("final", ""), status)
                print(L.t("disp.flow_done") + L.join(done, "sep.clause"))
            except flow.FlowError as e:
                print(L.t("disp.flow_failed", kind=e.kind, msg=e.msg), file=sys.stderr)

        print("\n" + L.t("disp.run_end", run=self.rec['run'], status=status, code=code, steps=self.rec.get('steps', 0)))
        if self.rec.get("session"):
            print(L.t("disp.session", session=self.rec['session']))
        if self.rec.get("error") and status != DONE:
            print(L.t("disp.error") + self.rec['error'])
        if self.rec.get("final"):
            print("\n" + L.t("disp.final_head") + "\n" + self.rec["final"])
        return 0 if status == DONE else (130 if status == STOPPED else 1)


def build_argv(member_cfg: Dict[str, Any], mode: str, prompt: str, session: str, last: Path) -> List[str]:
    vals = {"prompt": prompt, "session": session, "last": str(last)}
    return [re.sub(r"\{(prompt|session|last)\}", lambda m: vals[m.group(1)], a) for a in member_cfg[mode]]


def read_prompt(p: str) -> str:
    text = sys.stdin.read() if p == "-" else p
    if not text.strip():
        sys.exit(L.t("disp.empty_prompt"))
    return text


def check_gate(project: Path, skip: str) -> Optional[str]:
    """第一关：collab/ 校验没有错误。返回记入运行记录的偏离说明；不通过时退出。"""
    errs = collab_check.errors(collab_check.check(project))
    if not errs:
        return None
    if not skip:
        print(L.t("disp.check_failed"), file=sys.stderr)
        print(collab_check.fmt(errs), file=sys.stderr)
        print(L.t("disp.skip_check_hint"), file=sys.stderr)
        sys.exit(2)
    print(L.t("disp.skipping_check", n=len(errs), why=skip))
    return L.t("disp.skipped_check", n=len(errs))


def start_run(project: Path, task: str, seat: str, member: str, prompt: str,
              session: Optional[str] = None, parent: Optional[str] = None, override: str = "",
              adhoc: str = "", skip_check: str = "") -> int:
    members = load_members()
    if member not in members:
        sys.exit(L.t("disp.unknown_member", member=member, members=L.join(members), src=members_source()))
    cfg = members[member]
    if not cfg.get("available", "✓").startswith("✓"):
        print(L.t("disp.member_unavailable", member=member, status=cfg['available']), file=sys.stderr)
    if cfg.get("parser") not in PARSERS:
        sys.exit(L.t("disp.bad_parser", member=member, parser=cfg.get('parser'), parsers=L.join(PARSERS)))
    skipped = check_gate(project, skip_check)
    collab = project / P.COLLAB
    if (collab / P.INTERNAL_FLOW).is_dir():
        if adhoc:
            print(L.t("disp.no_adhoc"), file=sys.stderr)
            return 2
        return start_flow_run(project, task, seat, member, cfg, prompt, session, parent, override, skipped)
    has_card = any(t["id"] == task for t in collab_parse.load_tasks(collab))
    if not has_card and not adhoc:
        print(f"未派活：{task} 没有任务卡。先建卡（协议「记录规范 · 编号」），总裁批准后再派；"
              '临时派活（不属于任何任务）加 --adhoc "理由"。', file=sys.stderr)
        return 2
    blocks = collab_parse.dispatch_blocks(collab, task)
    if blocks:
        print(f"未派活：{task}", file=sys.stderr)
        for b in blocks:
            print(f"  - {b}", file=sys.stderr)
        print("这一关不能用 --override 跳过。", file=sys.stderr)
        return 2
    deviations = collab_parse.check_dispatch(collab, task, flow.i18n.pack("zh").name("seat", seat), member, cfg.get("aliases", [member]))  # 旧结构的卡片写中文席位
    if deviations and not override:
        print(f"未派活：{task}「{L.name('seat', seat)}」{member} 与任务卡或目标流程不符：", file=sys.stderr)
        for d in deviations:
            print(f"  - {d}", file=sys.stderr)
        print('确需偏离就加 --override "理由"，理由会记入运行记录并在看板标为偏离；'
              "改流程本身要总裁批准。", file=sys.stderr)
        return 2
    if deviations:
        print(f"按 --override 偏离流程：{override}")
    reasons = [r for r in (override if deviations else "", f"临时派活：{adhoc}" if adhoc and not has_card else "",
                           f"跳过校验：{skip_check}" if skipped else "") if r]
    if adhoc and not has_card:
        deviations = deviations + ["没有任务卡（临时派活）"]
    if skipped:
        deviations = deviations + [skipped]
    rdir = runs_dir(project)
    rid = new_run_id(rdir, task, member, seat)
    mode = "resume" if session else "start"
    argv = isolate(build_argv(cfg, mode, prompt, session or "", rdir / f"{rid}.last.txt"))
    rec = {"run": rid, "task": task, "seat": seat, "member": member, "mode": RunMode.RESUME if session else RunMode.NEW,
           "session": session or "", "continues": parent or "", "prompt": prompt, "steps": 0,
           "last_action": "", "final": "", "error": "",
           "deviations": deviations, "override": "；".join(reasons),
           "adhoc": adhoc if not has_card else ""}
    base = None
    if parent:  # Codex 的用量是会话累计，续接时要减去上一次的累计
        prev = next((r for r in load_runs(project) if r.get("run") == parent), None)
        base = ((prev or {}).get("tokens") or {}).get("session_cum")
    return Runner(project, rec, argv, cfg["parser"], token_base=base).run()


CLAUDE_ISOLATE = ["--setting-sources", "local", "--settings", '{"autoMemoryEnabled":false}']
CLAUDE_PARTIAL = "--include-partial-messages"  # 生成回复时实时输出片段（11-07 实测可用），页面据此显示正在写的内容


def isolate(argv: List[str]) -> List[str]:
    """Claude 命令行成员不带总裁的全局 CLAUDE.md、项目 hook 和自动记忆（11-01 实测 --setting-sources local 有效）；
    输出 stream-json 的再加 --include-partial-messages。"""
    if argv and Path(argv[0]).name == "claude":
        if "--setting-sources" not in argv:
            argv = argv[:1] + CLAUDE_ISOLATE + argv[1:]
        if CLAUDE_PARTIAL not in argv and "stream-json" in argv:
            argv = argv[:1] + [CLAUDE_PARTIAL] + argv[1:]
    return argv


def start_flow_run(project: Path, task: str, seat: str, member: str, cfg: Dict[str, Any], prompt: str,
                   session: Optional[str], parent: Optional[str], override: str, skipped: Optional[str]) -> int:
    """新结构项目（有 collab/内部/流转/）：顺序、人选等由 flow.py 校验；派发、接手由本脚本代写；
    启动语拼上 flow.py 的上下文包；成员用环境变量里的身份自己写交付或上报，结束后补一条进展。"""
    if flow.kind_of(task) == Kind.ISSUE:
        print(L.t("disp.is_issue", task=task), file=sys.stderr)
        return 2
    proj = flow.Project(project)
    actor = proj.actor(member) or next((proj.actor(a) for a in cfg.get("aliases", []) if proj.actor(a)), None)
    if not actor:
        print(L.t("disp.not_in_roster", member=member, roster=f"{P.COLLAB}/{P.INTERNAL_PLANS}/{P.ROSTER}"), file=sys.stderr)
        return 2
    rdir = runs_dir(project)
    rid = new_run_id(rdir, task, member, seat)
    try:
        done = flow.dispatch_begin(proj, task, seat, actor, rid, override)
    except flow.FlowError as e:
        (rdir / f"{rid}.json").unlink(missing_ok=True)  # 没派出去：收回占位记录
        print(L.t("disp.refused", task=task, kind=proj.L.t('cli.' + e.kind), msg=e.msg), file=sys.stderr)
        if e.kind == "rule":
            print(L.t("disp.override_hint"), file=sys.stderr)
        return 2
    print(L.t("disp.flow_done") + L.join(done, "sep.clause"))
    full_prompt = flow.dispatch_prompt(proj, task, actor, prompt)
    # 工位：<工作目录>/.scratch/<成员>/<任务>/，上下文包「现状」里写了这个路径；会话 cwd 仍是项目根
    st = flow.replay_all(proj)[0][task]
    (project / flow.workspace(proj, st, actor)["scratch"]).mkdir(parents=True, exist_ok=True)
    mode = "resume" if session else "start"
    argv = isolate(build_argv(cfg, mode, full_prompt, session or "", rdir / f"{rid}.last.txt"))
    deviations = [skipped] if skipped else []
    rec = {"run": rid, "task": task, "seat": seat, "member": member, "mode": RunMode.RESUME if session else RunMode.NEW,
           "session": session or "", "continues": parent or "", "prompt": full_prompt, "steps": 0,
           "last_action": "", "final": "", "error": "", "deviations": deviations,
           "override": L.join((r for r in (override, skipped) if r), "sep.clause"), "adhoc": ""}
    env = member_env({"COLLAB_ACTOR": actor, "COLLAB_RUN": rid, "COLLAB_WRITER": Writer.MEMBER, "COLLAB_FLOW": str(flow.FLOW_PY)})
    base = None
    if parent:
        prev = next((r for r in load_runs(project) if r.get("run") == parent), None)
        base = ((prev or {}).get("tokens") or {}).get("session_cum")
    return Runner(project, rec, argv, cfg["parser"], token_base=base, env=env, flow_actor=actor).run()


# ---------- 朝会（新结构）：一次叫醒一个与会者 ----------

def member_key(proj: "flow.Project", actor: str, members: Dict[str, Any]) -> Optional[str]:
    """flow 的派活名 → 班子配置里的成员键。"""
    if actor in members:
        return actor
    return next((k for k, v in members.items() if proj.actor(k) == actor or any(proj.actor(x) == actor for x in v.get("aliases", []))), None)


def issue_session(project: Path, proj: "flow.Project", issue: str, member: str) -> Optional[Dict[str, Any]]:
    """会话复用（方案 03 第 10.5 节）：挂目标的议题续接该成员在本目标里最近一个正常结束或被停止的会话（失败的不接）；
    项目级议题只续接本议题的；第三方验收的会话不续接；那个会话还在跑或已经丢失就开新的。"""
    states, _, _ = flow.replay_all(proj)
    goal = states[issue]["goal"]

    def goal_of(task: str) -> Optional[str]:
        st = states.get(task)
        return st["goal"] if st else (task.split("-T")[0] if "-T" in task else None)
    runs = [r for r in load_runs(project) if r.get("member") == member and r.get("session")]
    busy = {r["session"] for r in runs if r.get("status") == RUNNING}
    lost = {r["session"] for r in runs if r.get("session_lost")}
    cands = [r for r in runs if r.get("status") in (DONE, STOPPED) and r.get("seat") != Seat.ACCEPTANCE and r["session"] not in busy | lost
             and (r.get("task") == issue or (goal and goal_of(r.get("task", "")) == goal))]
    return cands[-1] if cands else None


DEFAULT_LIMITS = {"steps": 40, "minutes": 10}
WRAP_LIMITS = {"steps": 3, "seconds": 240}  # 收尾那一次：只许写回复，跑超了也停


def run_limits(key: str) -> Dict[str, int]:
    """每次运行的上限：班子.json 顶层「朝会运行上限」{步数, 分钟}，成员自己的「运行上限」覆盖它；缺省 40 步 10 分钟。写 0 表示不限。"""
    conf: Dict[str, Any] = dict(DEFAULT_LIMITS)
    try:
        team = team_mod.read(TEAM_FILE)
    except (OSError, ValueError):
        team = {}
    conf.update(team.get("meet_limits") or {})
    for x in team.get("members", []):
        if key in (x.get("dispatch_name"), *(x.get("aliases") or [])):
            conf.update(x.get("limits") or {})
    out = {}
    if conf.get("steps"):
        out["steps"] = int(conf["steps"])
    if conf.get("minutes"):
        out["seconds"] = int(float(conf["minutes"]) * 60)
    if conf.get("seconds"):
        out["seconds"] = int(conf["seconds"])
    return out


# 续接失败时各命令行说「会话没了」的说法；Claude 的「No conversation found」和 DeepSeek 的「session … does not exist」实测过
SESSION_LOST = re.compile(r"no conversation found|no (such )?session|session\b.*\b(not found|does not exist)|thread\b.*\bnot found|no rollout", re.I)


def wrap_prompt(reason: str, text: str = "") -> str:
    """text：总裁要求收尾时给的上下文包。被停的那次可能还没把启动语存进会话，运行中又可能有追问，所以从上次成功的「读到」补起，重复没关系。"""
    head = L.t("disp.wrap_head", reason=reason)
    return f"{head}\n{L.t('disp.wrap_answer')}\n\n{text}" if text else head


def _lock_issue(rdir: Path, issue: str, actor: str, wait: float):
    lock = open(rdir / f".meet-{issue}-{actor}.lock", "a+")
    end = time.time() + wait
    while True:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except BlockingIOError:
            if time.time() >= end:
                lock.close()
                return None
            time.sleep(0.3)


def run_issue_member(project: Path, issue: str, member: str, wrap: str = "") -> int:
    """meet-run：叫醒一个与会者跑一次。持有「议题 + 成员」锁，同一成员同时只跑一次；
    没有要它开口的（总裁没有公开点名它、已开过口）就不跑。每次运行有步数和时间上限，到上限自动让它用已有内容收尾（再续接同一会话跑一次）。
    wrap 不空：总裁要求收尾，不检查有没有点名，续接上次被停止的会话，要它立刻发言。
    结束后放锁，把回复写回黑板；只有总裁的 @ 能叫醒人，成员写的 @ 不叫醒。"""
    proj = flow.Project(project)
    members = load_members()
    actor = proj.actor(member) or member
    key = member_key(proj, actor, members)
    if not key:
        print(L.t("disp.not_woken_team", member=member), file=sys.stderr)
        return 2
    cfg = members[key]
    rdir = runs_dir(project)
    lock = _lock_issue(rdir, issue, actor, 60 if wrap else 0)
    if lock is None:
        print(L.t("disp.busy", who=L.who(actor), issue=issue))
        return 0
    try:
        try:
            st = flow.issue_begin(proj, issue, actor)
        except flow.FlowError as e:
            print(L.t("disp.not_woken") + e.msg, file=sys.stderr)
            return 2
        mine = [r for r in load_runs(project) if r.get("task") == issue and r.get("member") == key]
        # 只有成功写进黑板的运行才推进「读到」；失败、被停止的不算（I001：失败也推进，补叫不动）
        prev = [r for r in mine if "read_upto" in r and r.get("status") == DONE]
        since = prev[-1]["read_upto"] if prev else None
        seen = prev[-1].get("caught_up") or [] if prev else []
        last = mine[-1] if mine else None
        retry = bool(last and last.get("status") in (FAILED, LOST, STOPPED) and last.get("seat") == Seat.ATTENDEE)
        if not wrap and not flow.issue_needs(st, actor, since) and not retry:
            print(L.t("disp.no_mention", who=L.who(actor), issue=issue))
            return 0
        base = issue_session(project, proj, issue, key)
        session = (base or {}).get("session") or ""
        fresh = bool(prev) and prev[-1].get("session") != session  # 接的不是上次成功发言的会话（丢了）：它不记得这场会
        text, manifest = flow.context(proj, issue, actor, since=since, catch_up=retry or bool(wrap), fresh=fresh, seen=seen)
        upto, extra = manifest[-1]["read_upto"], manifest[-1]["caught_up"]
        head = L.t("disp.meet_head", issue=issue)
        if retry:
            why = (last.get("error") or last.get("status") or "").strip()
            head = L.t("disp.meet_retry", run=last['run'], why=(L.t("sep.colon") + clip(why, 100)) if why else "")
        if fresh:
            head += L.t("disp.meet_fresh")
        prompt = f"{head}\n\n{text}"
        limits = run_limits(key)
        rec = None
        note = wrap  # 记进运行记录「收尾」：总裁要求的，或到上限自动收尾的原因
        if wrap:  # 总裁要求收尾：有会话就续接被停止的，要它发言，运行中的追问一起给
            prompt, limits = wrap_prompt(wrap, text), WRAP_LIMITS
        for attempt in (0, 1):  # 第 2 次只在第 1 次到上限被停掉时：自动收尾
            rid = new_run_id(rdir, issue, key, Seat.ATTENDEE)
            mode = "resume" if session else "start"
            argv = isolate(build_argv(cfg, mode, prompt, session, rdir / f"{rid}.last.txt"))
            rec = {"run": rid, "task": issue, "seat": Seat.ATTENDEE, "member": key, "mode": RunMode.RESUME if session else RunMode.NEW,
                   "session": session, "continues": (base or {}).get("run", ""), "prompt": prompt, "steps": 0,
                   "last_action": "", "final": "", "error": "", "deviations": [], "override": "", "adhoc": ""}
            if note:
                rec["wrap"] = note
            tbase = ((base or {}).get("tokens") or {}).get("session_cum") if base else None
            code = Runner(project, rec, argv, cfg["parser"], token_base=tbase, limits=limits).run()
            reason = rec.get("stop_reason", "")
            limit = rec.get("stop_limit", "")
            if attempt == 0 and limit and not wrap:
                msg = L.t("disp.limit_wrap", who=L.who(actor), limit=limit)
                print(msg)
                try:
                    flow.record(proj, issue, E.PROGRESS, {"from": flow.LEAD, "writer": Writer.DISPATCHER, "run": rid, "note": msg})
                except flow.FlowError:
                    pass
                session = rec.get("session") or session
                base = {"run": rid, "tokens": rec.get("tokens")}
                note = reason
                if session:
                    prompt = wrap_prompt(reason)
                else:
                    prompt = L.t("disp.limit_fresh", limit=limit) + f"\n\n{text}"
                limits = WRAP_LIMITS
                continue
            break
        if rec.get("status") == FAILED and rec.get("mode") == RunMode.RESUME and SESSION_LOST.search(rec.get("error") or ""):
            # 再续接也不会好：记下来，下次开新会话（issue_session 跳过），带上全部公开发言
            rec["session_lost"] = True
            rec["error"] = clip(rec["error"] + L.t("disp.session_lost"), 300)
            write_json(rdir / f"{rid}.json", rec)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    try:
        done, wake = flow.issue_end(proj, issue, actor, rid, rec.get("session", ""), rec.get("final", ""),
                                    rec.get("status") == DONE, upto)
        print(L.t("disp.board_done") + L.join(done, "sep.clause"))
        if rec.get("status") == DONE and rec.get("final", "").strip():
            rec["read_upto"] = upto
            if extra:
                rec["caught_up"] = extra
            write_json(rdir / f"{rid}.json", rec)
    except flow.FlowError as e:
        print(L.t("disp.board_failed", kind=e.kind, msg=e.msg, run=rid), file=sys.stderr)
        return 1
    if wake:
        spawn_meet(project, issue, wake)
        print(L.t("disp.wake_next") + L.join(wake))
    return code


def stop_member(project: Path, issue: str, member: str) -> List[str]:
    """停止某成员在议题上正在跑的运行；返回停掉的派活编号。"""
    proj = flow.Project(project)
    actor = proj.actor(member) or member
    key = member_key(proj, actor, load_members()) or member
    out = []
    for r in load_runs(project):
        if r.get("task") == issue and r.get("member") == key and r.get("status") == RUNNING:
            _stop_one(project, r)
            out.append(r["run"])
    return out


def cmd_stop_member(a, project: Path) -> int:
    stopped = stop_member(project, a.issue, a.member)
    print(L.t("disp.stopped_list", runs=L.join(stopped)) if stopped else L.t("disp.nothing_running", member=a.member, issue=a.issue))
    return 0


def cmd_wrap(a, project: Path) -> int:
    """收尾：先停止这位成员当前的运行，再续接同一会话，要它用已有内容发言。
    一次收尾只算一次：另一个收尾还没结束、已经在收尾（含到上限自动收尾）、或者已经发过言没有在跑的，都不再做。"""
    proj = flow.Project(project)
    actor = proj.actor(a.member) or a.member
    key = member_key(proj, actor, load_members()) or a.member
    guard = _lock_issue(runs_dir(project), f"{a.issue}-wrap", actor, 0)
    if guard is None:
        print(L.t("disp.already_wrapping", member=a.member))
        return 0
    try:
        mine = [r for r in load_runs(project) if r.get("task") == a.issue and r.get("member") == key]
        running = [r for r in mine if r.get("status") == RUNNING]
        if any(r.get("wrap") for r in running):
            print(L.t("disp.already_wrapping", member=a.member))
            return 0
        if mine and not running and mine[-1].get("status") == DONE:
            print(L.t("disp.no_wrap_needed", member=a.member))
            return 0
        if a.page:
            flow.record(proj, a.issue, E.PROGRESS, {"from": flow.BOSS, "writer": Writer.BOARD, "note": L.t("disp.wrap_note", who=L.who(actor))})
        stopped = stop_member(project, a.issue, a.member)
        print(L.t("disp.stopped_wrap", runs=L.join(stopped) or L.t("disp.none_running"), member=a.member), flush=True)
        return run_issue_member(project, a.issue, a.member, wrap=a.reason or L.t("disp.owner_wrap"))
    finally:
        fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
        guard.close()


def spawn_meet(project: Path, issue: str, who: List[str]) -> None:
    """后台叫醒（不等）：每人一个 meet-run 进程，脱离当前进程组，看板或总管的进程退出也不影响。"""
    for w in who:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--project", str(project), "meet-run", issue, w],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def cmd_meet_flow(a, project: Path) -> int:
    check_gate(project, a.skip_check or "")
    proj = flow.Project(project)
    states, _, _ = flow.replay_all(proj)
    st = states.get(a.issue)
    if not st or st["kind"] != Kind.ISSUE:
        sys.exit(L.t("disp.not_issue", issue=a.issue))
    if st["state"] != S.DISCUSSING:
        sys.exit(L.t("disp.not_started", issue=a.issue, state=L.st(st['state'])))
    names = [x["member"] for x in st["attendees"]]
    if a.wake:
        who = []
        for w in a.wake:
            x = proj.actor(w)
            if x not in names:
                sys.exit(L.t("disp.not_attendee", who=w, issue=a.issue, names=L.join(names)))
            who.append(x)
    else:
        spoke = {r.get("from") for r in st["events"] if r.get("edge") in flow.MESSAGES}
        who = [n for n in names if n not in spoke]
        if not who:
            sys.exit(L.t("disp.all_spoken", issue=a.issue))
    if a.detach:
        spawn_meet(project, a.issue, who)
        print(L.t("disp.woken_bg", who=L.join(who)))
        return 0
    procs = [(w, subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--project", str(project), "meet-run", a.issue, w],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace")) for w in who]
    print(L.t("disp.waking", issue=a.issue, who=L.join(who)), flush=True)
    for w, p in procs:
        out = p.communicate()[0]
        print(f"\n=== {w} ===\n{out.strip()}")
    return 0


# ---------- 搭会议室：建议题、写开场约定、启动检查，通过后直接进「讨论中」 ----------

BOARD_PORT = 3100


def meet_url(project: Path, issue: str, port: Optional[int] = None) -> str:
    import hashlib
    pid = hashlib.sha1(str(project).encode("utf-8")).hexdigest()[:8]  # 与 board/server.py 的 project_id 一致
    return f"http://127.0.0.1:{port or int(os.environ.get('COLLAB_BOARD_PORT') or BOARD_PORT)}/p/{pid}/meet/{issue}"


def ready_file(project: Path, issue: str) -> Path:
    return runs_dir(project) / f"{issue}{P.READY_SUFFIX}"  # 不用 .json：避免被当成派活记录读


def fill_card(path: Path, question: str, opening: str) -> None:
    """写议题卡的「问题」，并在它后面加一节「开场约定」（软约定：总管写明这场会要什么、已知情况、资料位置）。
    命令行里写的字面 \\n 算换行（shell 的双引号不转义，总管常这样写）。"""
    question, opening = question.replace("\\n", "\n"), opening.replace("\\n", "\n")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## " + flow.heading_re(Section.QUESTION) + r"\s*\n", text, re.M)
    if not m:
        sys.exit(L.t("disp.no_section", file=path.name, section=L.heading(Section.QUESTION)))
    nxt = re.search(r"^## ", text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(text) - m.end())
    body = text[m.end():end]
    if question.strip():
        body = question.strip() + "\n\n"
    if opening.strip():
        body = body.rstrip("\n") + "\n\n## " + L.heading(Section.OPENING) + "\n" + opening.strip() + "\n\n"
    path.write_text(text[:m.end()] + body + text[end:], encoding="utf-8")


def open_room(project: Path, issue: str, port: Optional[int] = None) -> int:
    """对议题的全部与会者做启动检查，结果写进 到场 记录和一条进展；全部就绪且议题还在「起草」就记总裁的「开始」（总管代记）。"""
    proj = flow.Project(project)
    st = flow.replay_all(proj)[0].get(issue)
    if not st or st["kind"] != Kind.ISSUE:
        sys.exit(L.t("issue.not_issue", obj=issue))
    if st["state"] not in (S.DRAFT, S.DISCUSSING):
        sys.exit(L.t("disp.room_state", issue=issue, state=L.st(st['state'])))
    members = load_members()
    keys = []
    for x in st["attendees"]:
        k = member_key(proj, x["member"], members)
        keys.append(k or x["member"])
    print(L.t("disp.checking", who=L.join(keys)), flush=True)
    results = check_members(project, keys)
    ready = {"checked": now_iso(), "members": {r["member"]: r for r in results}}
    write_json(ready_file(project, issue), ready)
    bad = [r for r in results if not r["ok"]]
    for r in results:
        print(f"  {r['member']:<14} {L.t('disp.ready') if r['ok'] else L.t('disp.not_ready')}  {L.t('disp.seconds', n=r['seconds'])}{'  ' + r['error'] if r['error'] else ''}")
    summary = L.join([L.t("disp.member_ready", member=r['member']) if r['ok'] else L.t("disp.member_not_ready", member=r['member'], why=clip(r['error'], 60)) for r in results], "sep.clause")
    flow.record(proj, issue, E.PROGRESS, {"from": flow.LEAD, "writer": Writer.LEAD, "note": L.t("disp.roll_call") + summary})
    if bad:
        print("\n" + L.t("disp.room_not_ready", n=len(bad), issue=issue, state=L.st(st['state'])))
        return 1
    if st["state"] == S.DRAFT:
        flow.record(proj, issue, E.START, {"from": flow.BOSS, "writer": Writer.LEAD, "basis": L.t("disp.room_basis")})
    print("\n" + L.t("disp.room_ready", issue=issue, state=L.st("discussing"), url=meet_url(project, issue, port)))
    return 0


def cmd_room(a, project: Path) -> int:
    check_gate(project, a.skip_check or "")
    proj = flow.Project(project)
    args: Dict[str, Any] = {"from": flow.LEAD, "writer": Writer.LEAD, "title": a.title, "attendees": a.attendees, "basis": a.basis}
    if a.goal:
        args["goal"] = a.goal
    if a.type:
        args["type"] = a.type
    try:
        issue, path = flow.create(proj, Kind.ISSUE, args)
    except flow.FlowError as e:
        print(L.t("disp.issue_failed", kind=e.kind, msg=e.msg), file=sys.stderr)
        return 2
    fill_card(path, a.question or "", a.opening or "")
    print(L.t("cli.created", obj=issue, path=path.relative_to(project)))
    return open_room(project, issue, a.port)


def cmd_ready(a, project: Path) -> int:
    return open_room(project, a.issue, a.port)


# ---------- 子命令 ----------

def cmd_start(a, project: Path) -> int:
    return start_run(project, a.task, flow.value_code("seat", a.seat), a.member, read_prompt(a.prompt), override=a.override or "",
                     adhoc=a.adhoc or "", skip_check=a.skip_check or "")


def cmd_continue(a, project: Path) -> int:
    runs = load_runs(project)
    if a.run:
        base = next((r for r in runs if r.get("run") == a.run), None)
        if not base:
            sys.exit(L.t("disp.no_run", run=a.run))
    else:
        cands = [r for r in runs if r.get("task") == a.task and r.get("seat") == flow.value_code("seat", a.seat) and r.get("session")]
        if not cands:
            sys.exit(L.t("disp.no_session_seat", task=a.task, seat=L.name("seat", a.seat)))
        base = cands[-1]
    if base.get("status") == RUNNING:
        sys.exit(L.t("disp.still_running", run=base['run']))
    if not base.get("session"):
        sys.exit(L.t("disp.no_session_id", run=base['run']))
    return start_run(project, base["task"], base["seat"], base["member"], read_prompt(a.prompt),
                     session=base["session"], parent=base["run"], override=a.override or "",
                     adhoc=base.get("adhoc") or "", skip_check=a.skip_check or "")


def _stop_one(project: Path, r: Dict[str, Any]) -> str:
    meta = project / P.COLLAB / RUNS_DIR / f"{r['run']}.json"
    pid, child = r.get("pid"), r.get("child_pid")
    if pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            time.sleep(0.1)
            if not pid_alive(pid):
                break
    if child and pid_alive(child):
        try:
            os.killpg(child, signal.SIGTERM)
        except ProcessLookupError:
            pass
    cur = json.loads(meta.read_text(encoding="utf-8"))
    if cur.get("status") == RUNNING:  # 派活进程没能自己收尾，替它记上
        cur.update(status=STOPPED, ended=now_iso())
        cur.pop("child_pid", None)
        write_json(meta, cur)
    return L.t("disp.stopped_one", run=r['run'], member=r['member'], session=cur.get('session') or L.t("block.none_inline"))


def cmd_stop(a, project: Path) -> int:
    runs = load_runs(project)
    if a.all:
        targets = [r for r in runs if r.get("status") == RUNNING]
        if not targets:
            print(L.t("disp.none_running_runs"))
    else:
        if not a.run:
            sys.exit(L.t("disp.stop_which"))
        targets = [r for r in runs if r.get("run") == a.run]
        if not targets:
            sys.exit(L.t("disp.no_run", run=a.run))
        if targets[0].get("status") != RUNNING:
            print(L.t("disp.not_running", run=a.run, status=L.name("run_status", targets[0].get('status'))))
            return 0
    for r in targets:
        print(_stop_one(project, r))
    return 0


def _ago(iso: str) -> str:
    try:
        s = int((dt.datetime.now().astimezone() - dt.datetime.fromisoformat(iso)).total_seconds())
    except (TypeError, ValueError):
        return ""
    return L.t("disp.ago_s", n=s) if s < 120 else L.t("disp.ago_m", n=s // 60) if s < 7200 else L.t("disp.ago_h", n=s // 3600)


def cmd_list(a, project: Path) -> int:
    runs = load_runs(project)
    if not a.all:
        running = [r for r in runs if r.get("status") == RUNNING]
        rest = [r for r in runs if r.get("status") != RUNNING][-10:]
        runs = rest + running
    if not runs:
        print(L.t("disp.no_runs"))
        return 0
    for r in runs:
        tail = L.t("disp.latest", action=r.get('last_action') or '—', ago=_ago(r.get('last_at'))) if r.get("status") == RUNNING \
            else (L.t("disp.error") + clip(r.get('error'), 60) if r.get("status") in (FAILED, LOST) and r.get("error") else "")
        print(f"{r['run']:<10} {L.name('run_status', r.get('status', '')):<5} {L.name('seat', r.get('seat', '')):<3} {r.get('member', ''):<8} "
              f"{(r.get('started') or '')[5:16].replace('T', ' ')}  {L.t('disp.steps', n=r.get('steps', 0))}  "
              f"{fmt_tokens(r.get('tokens')):<14} {tail}")
    return 0


def cmd_show(a, project: Path) -> int:
    r = next((x for x in load_runs(project) if x.get("run") == a.run), None)
    if not r:
        sys.exit(L.t("disp.no_run", run=a.run))
    for k in ("run", "task", "seat", "member", "mode", "session", "continues", "status", "started", "ended",
              "steps", "last_action", "error", "override", "deviations"):
        if r.get(k) not in (None, ""):
            kind = {"seat": "seat", "mode": "run_mode", "status": "run_status"}.get(k)
            print(f"{k}: {L.name(kind, r[k]) if kind else r[k]}")
    tk = r.get("tokens")
    if tk:
        print(f"tokens: {fmt_tokens(tk)}" + L.t("disp.tokens_detail", input=tk.get('input', 0), cached=tk.get('cached', 0), output=tk.get('output', 0))
              + (L.t("disp.tokens_calls", n=tk['calls']) if tk.get("calls") else "")
              + (L.t("disp.tokens_context", n=tk['context']) if tk.get("context") else "")
              + (L.t("disp.tokens_cost", n=tk['cost_usd']) if tk.get("cost_usd") else "") + L.t("sep.paren_close"))
    print("\n" + L.t("disp.prompt_label") + "\n" + r.get("prompt", ""))
    if r.get("final"):
        print("\n" + L.t("disp.final_head") + "\n" + r["final"])
    return 0


def cmd_tokens(a, project: Path) -> int:
    """从各次派活的原始事件（.jsonl）补算 token；默认只补还没有的，--force 全部重算。按开始时间顺序算，续接能接上前一次的累计。"""
    members = load_members()
    rdir = runs_dir(project)
    runs = [r for r in load_runs(project) if r.get("status") != RUNNING]
    by_id = {r["run"]: r for r in runs}
    n = 0
    for r in sorted(runs, key=lambda x: (x.get("started") or "", x.get("run") or "")):
        if r.get("tokens") and not a.force:
            continue
        parser = (members.get(r.get("member")) or {}).get("parser")
        f = rdir / f"{r['run']}.stream.jsonl"
        f = f if f.exists() else rdir / f"{r['run']}.jsonl"  # 旧记录
        if parser not in USAGE or not f.exists():
            continue
        base = ((by_id.get(r.get("continues")) or {}).get("tokens") or {}).get("session_cum")
        acc: Dict[str, Any] = {"_base": base} if base else {}
        try:
            for line in f.open(encoding="utf-8", errors="replace"):
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    USAGE[parser](ev, acc)
            t = finish_tokens(acc)
        except Exception as e:
            print(L.t("disp.tokens_failed", run=r['run'], e=e), file=sys.stderr)
            continue
        if not t:
            continue
        meta = rdir / f"{r['run']}.json"
        rec = json.loads(meta.read_text(encoding="utf-8"))
        rec["tokens"] = r["tokens"] = t
        write_json(meta, rec)
        n += 1
        print(f"{r['run']:<10} {r.get('member', ''):<8} {fmt_tokens(t)}")
    print(L.t("disp.tokens_done", n=n))
    return 0


# ---------- 朝会 ----------

MEET_LIMIT = 400


def resolve_member(name: str, members: Dict[str, Any]) -> Optional[str]:
    n = name.strip().lower()
    if n in members:
        return n
    return next((k for k, v in members.items() if any(a.lower() in n for a in v.get("aliases", [k]))), None)


def _section_text(path: Path, prefix: str) -> str:
    secs = collab_parse.h2_sections(collab_parse.strip_comments(path.read_text(encoding="utf-8")))
    s = next((x for x in secs if x["title"].startswith(prefix)), None)
    return "\n".join(l for l in s["lines"] if not l.startswith(">")).strip() if s else ""


def _meet_prompt(issue: Dict[str, Any], path: Path, rnd: int, me: int) -> str:
    att = issue["attendees"]
    mine = att[me]
    others = "；".join(f"{a['member']}（{a['view'] or '未指定视角'}）" for i, a in enumerate(att) if i != me) or "无"
    if rnd == 1:
        return f"""你受邀参加朝会，议题 {issue['id']}「{issue['title']}」。当前工作目录是项目根目录，协作文件在 collab/。
你的视角：{mine['view'] or '未指定，按你的专业判断'}。其他与会者：{others}。第 1 轮各自独立发言，你看不到他们的观点。
可以打开下面列出的参考资料；不要修改任何文件。

## 问题
{_section_text(path, '问题')}

请用中文回答，不超过 {MEET_LIMIT} 字，按以下结构：
- 结论：你主张的做法（一句话）
- 理由：最重要的 2–3 条依据
- 风险与代价：
- 还需要的信息：（没有就写「无」）"""
    prev = next((r for r in issue["rounds"] if r["no"] == rnd - 1), {"speeches": []})
    speeches = "\n\n".join(f"### {s['who']}\n{s['text']}" for s in prev["speeches"])
    return f"""朝会 {issue['id']}「{issue['title']}」第 {rnd} 轮。你的视角仍是：{mine['view'] or '未指定'}。
下面是第 {rnd - 1} 轮全部发言（含你自己的）：

{speeches}

请回应分歧：同意哪些、不同意哪些及理由，是否修改你的结论。不要修改任何文件。中文，不超过 {MEET_LIMIT} 字，按以下结构：
- 结论（是否修改）：
- 回应：
- 仍存在的分歧：（没有就写「无」）"""


def _write_round(path: Path, rnd: int, blocks: List[str], state: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = next((i for i, l in enumerate(lines) if l.startswith("## ") and collab_parse.ROUND_RE.match(l[3:].strip())
                and int(collab_parse.ROUND_RE.match(l[3:].strip()).group(1)) == rnd), None)
    if idx is None:  # 没有这一轮的标题：插在「总结」前（或文末）
        at = next((i for i, l in enumerate(lines) if l.startswith("## 总结")), len(lines))
        lines[at:at] = [f"## 第{rnd}轮", ""]
        idx = at
    end = next((i for i in range(idx + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > idx + 1 and not lines[end - 1].strip():
        end -= 1
    body = []
    for b in blocks:
        body += ["", *b.splitlines()]
    lines[end:end] = body + [""]
    text = "\n".join(lines) + "\n"
    text = re.sub(r"(?m)^(状态：)[^｜|\n]*", lambda m: m.group(1) + state + " ", text, count=1)
    path.write_text(text, encoding="utf-8")


def cmd_meet(a, project: Path) -> int:
    if (project / P.COLLAB / P.INTERNAL_FLOW / f"{a.issue}.jsonl").exists():
        return cmd_meet_flow(a, project)
    if a.wake or a.detach:
        sys.exit("--wake、--detach 只用于新结构项目（有 collab/内部/流转/）的议题")
    check_gate(project, a.skip_check or "")
    collab = project / P.COLLAB
    path = collab_parse.find_issue(collab, a.issue)
    if not path:
        sys.exit(f"找不到议题 {a.issue}（collab/议题/{a.issue}-*.md）")
    issue = collab_parse.parse_issue(path)
    if issue["stage"] in ("待裁决", "已裁决"):
        sys.exit(f"{a.issue} 已{issue['stage']}，不再开会")
    if not issue["attendees"]:
        sys.exit(f"{a.issue} 的「与会」表还没有成员")
    rnd = a.round or issue["roundsDone"] + 1
    if rnd > issue["maxRounds"]:
        sys.exit(f"{a.issue} 已开 {issue['roundsDone']} 轮，到了上限 {issue['maxRounds']} 轮；请写总结")
    if rnd != issue["roundsDone"] + 1:
        sys.exit(f"{a.issue} 已完成 {issue['roundsDone']} 轮，下一轮应是第 {issue['roundsDone'] + 1} 轮")
    members = load_members()
    resolved = []
    for at in issue["attendees"]:
        m = resolve_member(at["member"], members)
        if not m:
            sys.exit(f"与会成员「{at['member']}」不在 {members_source()} 里")
        resolved.append(m)

    started = now_iso()
    procs = []
    print(f"朝会 {a.issue} 第 {rnd} 轮：{'、'.join(resolved)}，并行进行", flush=True)
    for i, m in enumerate(resolved):
        seat = f"朝会{i + 1}"
        base = [sys.executable, str(Path(__file__).resolve()), "--project", str(project)]
        argv = base + (["start", a.issue, seat, m, "-"] if rnd == 1 else ["continue", a.issue, seat, "-"])
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
        p.stdin.write(_meet_prompt(issue, path, rnd, i))
        p.stdin.close()
        procs.append((i, m, seat, p))

    stopping = {"v": False}

    def forward(signum, _frame):
        stopping["v"] = True
        for *_, p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
    for sg in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sg, forward)

    outputs = {}
    for i, m, seat, p in procs:
        outputs[i] = p.stdout.read()
        p.wait()
    if stopping["v"]:
        print("朝会被停止，本轮发言未写入议题文件；用 meet 重新开这一轮前先确认各会话状态", file=sys.stderr)
        return 130

    runs = load_runs(project)
    blocks, report = [], []
    for i, m, seat, p in procs:
        r = next((x for x in reversed(runs) if x.get("task") == a.issue and x.get("seat") == seat
                  and (x.get("started") or "") >= started), None)
        view = issue["attendees"][i]["view"]
        head = f"### {m}{' · ' + view if view else ''} · {r['run'] if r else '无记录'}"
        if r and r.get("status") == DONE and r.get("final"):
            text = re.sub(r"(?m)^(#+)", lambda mm: "\\" + mm.group(1), r["final"].strip())
            blocks.append(head + "\n\n" + text)
            report.append(f"{m}：已发言（{r['run']}）")
        else:
            why = (r or {}).get("error") or (r or {}).get("status") or outputs.get(i, "").strip()[-200:]
            blocks.append(head + "\n\n（未发言：" + clip(why, 200) + "）")
            report.append(f"{m}：未发言（{clip(why, 80)}）")
    _write_round(path, rnd, blocks, f"第{rnd}轮完成")
    print("\n".join(report))
    print(f"\n第 {rnd} 轮发言已写入 {path.relative_to(project)}")
    if rnd < issue["maxRounds"]:
        print("下一步：总管读发言，仍有实质分歧就 meet 开下一轮，否则写「总结」。")
    else:
        print("下一步：已到轮数上限，总管写「总结」（共识、争议、建议），并在「待你决定」加一行。")
    for b in blocks:
        print("\n" + b)
    return 0


FLAG_ALIASES = {**flow.FLAG_ALIASES, "--问题": "--question", "--开场": "--opening"}


def english_flags(argv: List[str]) -> List[str]:
    """中文参数名（--标题、--与会…）换成英文写法，`--名=值` 的写法也认。"""
    out = []
    for x in argv:
        head, eq, rest = x.partition("=")
        out.append(FLAG_ALIASES[head] + eq + rest if head in FLAG_ALIASES else x)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    flow.i18n.set_current(flow.cli_lang(list(sys.argv[1:] if argv is None else argv)))
    H = lambda k: L.t("disp.help." + k)  # noqa: E731
    ap = argparse.ArgumentParser(prog="dispatch.py", description=H("dispatch"))
    ap.add_argument("--project", help=H("h01"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start", help=H("h02"))
    p.add_argument("task"); p.add_argument("seat"); p.add_argument("member"); p.add_argument("prompt")
    p.add_argument("--override", help=H("h03"))
    p.add_argument("--adhoc", help=H("h04"))
    p.add_argument("--skip-check", help=H("h05"))
    p = sub.add_parser("continue", help=H("h06"))
    p.add_argument("task"); p.add_argument("seat"); p.add_argument("prompt")
    p.add_argument("--run", help=H("h07"))
    p.add_argument("--override", help=H("h08"))
    p.add_argument("--skip-check", help=H("h09"))
    p = sub.add_parser("stop", help=H("h10"))
    p.add_argument("run", nargs="?"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("list", help=H("h11"))
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("show", help=H("h12"))
    p.add_argument("run")
    p = sub.add_parser("tokens", help=H("h13"))
    p.add_argument("--force", action="store_true", help=H("h14"))
    p = sub.add_parser("meet", help=H("h15"))
    p.add_argument("issue"); p.add_argument("--round", type=int, help=H("h16"))
    p.add_argument("--wake", nargs="*", help=H("h17"))
    p.add_argument("--detach", action="store_true", help=H("h18"))
    p.add_argument("--skip-check", help=H("h19"))
    p = sub.add_parser("check", help=H("h20"))
    p.add_argument("members", nargs="*", help=H("h21"))
    p = sub.add_parser("room", help=H("h22"))
    p.add_argument("--title", dest="title", required=True); p.add_argument("--basis", dest="basis", required=True, help=H("h23"))
    p.add_argument("--attendees", dest="attendees", nargs="+", required=True, help=H("h24"))
    p.add_argument("--question", dest="question", help=H("h25"))
    p.add_argument("--opening", dest="opening", help=H("h26"))
    p.add_argument("--goal", dest="goal"); p.add_argument("--type", dest="type", choices=[IssueType.COUNCIL, IssueType.REVIEW_MEETING])

    p.add_argument("--port", type=int, help=H("h27"))
    p.add_argument("--skip-check", help=H("h28"))
    p = sub.add_parser("ready", help=H("h29"))
    p.add_argument("issue"); p.add_argument("--port", type=int)
    p = sub.add_parser("stop-member", help=H("h30"))
    p.add_argument("issue"); p.add_argument("member")
    p = sub.add_parser("wrap", help=H("h31"))
    p.add_argument("issue"); p.add_argument("member"); p.add_argument("--reason", help=H("h32"))
    p.add_argument("--page", action="store_true", help=H("h33"))
    p = sub.add_parser("meet-run", help=H("h34"))
    p.add_argument("issue"); p.add_argument("member")
    a = ap.parse_args(english_flags(sys.argv[1:] if argv is None else argv))  # 中文参数名保留为别名，解析前换成英文写法，帮助里只列英文
    project = Path(a.project).expanduser().resolve() if a.project else find_project(Path.cwd())
    flow.i18n.set_current(flow.i18n.project_lang(project))
    if not (project / P.COLLAB / P.PROGRESS).exists():
        sys.exit(L.t("disp.no_progress", project=project))
    refusal = flow.dev_write_refusal(project) if a.cmd not in ("list", "show") else None
    if refusal:
        sys.exit(refusal)
    return {"start": cmd_start, "continue": cmd_continue, "stop": cmd_stop,
            "list": cmd_list, "show": cmd_show, "meet": cmd_meet, "tokens": cmd_tokens, "check": cmd_check, "wrap": cmd_wrap, "stop-member": cmd_stop_member, "room": cmd_room, "ready": cmd_ready,
            "meet-run": lambda a, pr: run_issue_member(pr, a.issue, a.member)}[a.cmd](a, project)


if __name__ == "__main__":
    sys.exit(main())
