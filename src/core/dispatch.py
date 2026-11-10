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
import flow  # noqa: E402  新结构项目（有 collab/内部/流转/）：派发、接手、进展由本脚本经 flow.py 代写
TEAM_FILE = flow.team_dir() / "班子.json"
RUNS_DIR = "内部/运行记录"
HEARTBEAT_SECONDS = 5  # 事件密集时，最多每隔几秒写一次记录
ACTION_LIMIT = 100

RUNNING, DONE, FAILED, STOPPED, LOST = "运行中", "完成", "失败", "已中断", "异常结束"


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
        if (p / "collab" / "PROGRESS.md").exists():
            return p
    sys.exit(f"找不到 collab/PROGRESS.md：{start} 及其上级目录都不是协作项目，用 --project 指定")


def runs_dir(project: Path) -> Path:
    d = project / "collab" / RUNS_DIR
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
    d = project / "collab" / RUNS_DIR
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
        sys.exit(f"没有班子配置：{TEAM_FILE}（先运行 init.sh team 建立）")
    team = json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    out = {}
    for x in team.get("成员", []):
        did = x.get("派活名")
        if not did or not x.get("新会话命令"):
            continue
        out[did] = {"aliases": x.get("别名") or [did], "parser": x.get("事件解析", did),
                    "start": x["新会话命令"], "resume": x.get("续接命令", []),
                    "available": str(x.get("可用", "✓"))}
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
                                      "pid": os.getpid(), "started": now_iso(), "phase": "启动中"}, ensure_ascii=False) + "\n").encode("utf-8"))
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
        out["action"] = _tool_brief(ev.get("tool", "工具"), ev.get("input"))
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
        out["action"] = "运行：" + str(item.get("command", ""))
        out["step"] = True
    elif t == "item.completed" and it == "file_change":
        paths = [c.get("path", "") for c in item.get("changes") or []]
        out["action"] = "改文件：" + "、".join(Path(p).name for p in paths if p)
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
            out["phase"] = "思考"
            out["draft_reset"] = True
        elif et == "content_block_start":
            cb = e.get("content_block") or {}
            if cb.get("type") == "text":
                out["phase"] = "正在写回复"
            elif cb.get("type") in ("tool_use", "server_tool_use"):
                out["phase"] = "调用工具"
                out["action"] = cb.get("name", "工具")
            else:
                out["phase"] = "思考"
        elif et == "content_block_delta":
            d = e.get("delta") or {}
            if d.get("type") == "text_delta" and d.get("text"):
                out["draft_add"] = d["text"]
        return
    if t == "user":
        out["phase"] = "思考"
    if t == "assistant":
        for c in (ev.get("message") or {}).get("content") or []:
            if c.get("type") == "tool_use":
                out["action"] = _tool_brief(c.get("name", "工具"), c.get("input"))
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
    s = f"{n / 10000:.1f}万".replace(".0万", "万") if n >= 10000 else str(n)
    return f"{s} · 缓存{round(100 * t.get('cached', 0) / n)}%" if t.get("cached") else s


# ---------- 启动检查：用一次真实的最小调用确认成员能启动、已登录 ----------

CHECK_PROMPT = "这是启动检查。只回复两个字：就绪。不要调用任何工具，不要读写文件。"
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
        res["error"] = f"班子配置里状态是「{cfg['available']}」，没有检查"
        res["skipped"] = True
        return res
    env = member_env()
    with tempfile.TemporaryDirectory() as tmp:
        argv = isolate(build_argv(cfg, "start", CHECK_PROMPT, "", Path(tmp) / "last.txt"))
        if Path(_exe_of(argv)).name == "claude" and "--no-session-persistence" not in argv:
            i = argv.index(_exe_of(argv))
            argv = argv[:i + 1] + ["--no-session-persistence"] + argv[i + 1:]
        exe = _exe_of(argv)
        if exe and not which(exe, env):
            res["error"] = f"找不到命令 {exe}（启动环境的 PATH 里没有）"
            return res
        out: Dict[str, Any] = {}
        tokens: Dict[str, Any] = {}
        usage = USAGE.get(cfg["parser"])
        try:
            r = subprocess.run(argv, cwd=tmp, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            res.update(error=f"{timeout} 秒内没有回复", seconds=round(time.time() - t0, 1))
            return res
        except OSError as e:
            res.update(error=f"无法启动：{e}", seconds=round(time.time() - t0, 1))
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
                            or f"退出码 {r.returncode}，没有回复", 200)
    return res


def check_members(project: Path, keys: List[str]) -> List[Dict[str, Any]]:
    """并行检查多位成员，按传入顺序返回。"""
    members = load_members()
    results: Dict[str, Dict[str, Any]] = {}

    def one(k: str) -> None:
        if k not in members:
            results[k] = {"member": k, "ok": False, "error": "不在班子配置里", "time": now_iso(), "seconds": 0}
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
        mark = "就绪" if r["ok"] else ("跳过" if r.get("skipped") else "未就绪")
        print(f"{r['member']:<14} {mark}  {r['seconds']}秒{'  ' + str(r['tokens']) + ' token' if r.get('tokens') else ''}"
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
        self.limits = limits or {}  # {"步数": n, "秒数": n}；到了就停掉这次运行，rec["stop_reason"] 写明原因
        self.draft = ""
        self.draft_at = 0.0
        self.draft_file = self.rdir / f"{rec['run']}.draft.txt"

    def trip(self, reason: str) -> None:
        """到运行上限：记下原因，停掉命令行进程（状态为已中断，调用方决定是否让它收尾）。"""
        if self.stopping:
            return
        self.rec["stop_reason"] = "上限：" + reason
        self.stopping = True
        self.save(force=True)
        if self.child and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def watchdog(self) -> None:
        secs = self.limits.get("秒数")
        t0 = time.time()
        while not self.done.wait(2):
            if secs and time.time() - t0 > secs:
                self.trip(f"时间 {secs // 60 if secs % 60 == 0 else secs} {'分钟' if secs % 60 == 0 else '秒'}")
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
        self.rec.update(status=RUNNING, pid=os.getpid(), started=now_iso(), phase="启动中", phase_at=now_iso())
        self.save(force=True)
        print(f"派活 {self.rec['run']}：{self.rec['member']} 坐「{self.rec['seat']}」，任务 {self.rec['task']}"
              f"{'，续接 ' + self.rec['session'] if self.rec.get('session') else ''}", flush=True)
        try:
            err = self.errfile.open("w", encoding="utf-8")
            self.child = subprocess.Popen(self.argv, cwd=self.project, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=err, env=self.env,
                                          start_new_session=True, text=True, encoding="utf-8",
                                          errors="replace", bufsize=1)
        except OSError as e:
            self.rec.update(status=FAILED, ended=now_iso(), error=f"无法启动：{e}")
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
                if self.rec.get("phase") == "启动中" and not out.get("phase") and set(out) != {"session"}:
                    out["phase"] = "思考"  # 只报了会话 ID 的初始化事件还算启动中；有的成员不报阶段，有别的输出就算思考
                if out.get("session") and not self.rec.get("session"):
                    self.rec["session"] = out["session"]
                    self.save(force=True)
                    print(f"会话 {out['session']}", flush=True)
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
                    if self.limits.get("步数") and self.rec["steps"] >= self.limits["步数"]:
                        self.trip(f"步数 {self.limits['步数']}")
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
                self.rec["error"] = clip(stderr.strip().splitlines()[-1] if stderr.strip() else f"退出码 {code}", 300)
            elif self.rec["error"] in ("is_error", "error_during_execution") and stderr.strip():
                self.rec["error"] = clip(stderr.strip().splitlines()[-1], 300)
        self.rec.update(status=status, ended=now_iso(), exit_code=code, last_at=now_iso())
        self.rec.pop("child_pid", None)
        self.rec["phase"] = {DONE: "完成", FAILED: "失败", STOPPED: "已停止"}.get(status, status)
        self.save(force=True)
        if self.flow_actor:
            try:
                done = flow.dispatch_end(flow.Project(self.project), self.rec["task"], self.flow_actor, self.rec["run"],
                                         self.rec.get("session", ""), self.rec.get("final", ""), status)
                print("流转：" + "；".join(done))
            except flow.FlowError as e:
                print(f"流转没写成（{e.kind}）：{e.msg}", file=sys.stderr)

        print(f"\n{self.rec['run']} {status}（退出码 {code}，{self.rec.get('steps', 0)} 步）")
        if self.rec.get("session"):
            print(f"会话 {self.rec['session']}")
        if self.rec.get("error") and status != DONE:
            print(f"错误：{self.rec['error']}")
        if self.rec.get("final"):
            print("\n--- 最终回复 ---\n" + self.rec["final"])
        return 0 if status == DONE else (130 if status == STOPPED else 1)


def build_argv(member_cfg: Dict[str, Any], mode: str, prompt: str, session: str, last: Path) -> List[str]:
    vals = {"prompt": prompt, "session": session, "last": str(last)}
    return [re.sub(r"\{(prompt|session|last)\}", lambda m: vals[m.group(1)], a) for a in member_cfg[mode]]


def read_prompt(p: str) -> str:
    text = sys.stdin.read() if p == "-" else p
    if not text.strip():
        sys.exit("启动语为空")
    return text


def check_gate(project: Path, skip: str) -> Optional[str]:
    """第一关：collab/ 校验没有错误。返回记入运行记录的偏离说明；不通过时退出。"""
    errs = collab_check.errors(collab_check.check(project))
    if not errs:
        return None
    if not skip:
        print("未派活：collab/ 校验没通过，先按协议改好：", file=sys.stderr)
        print(collab_check.fmt(errs), file=sys.stderr)
        print('确定是校验器误报才加 --skip-check "理由"（记入运行记录，看板标为偏离）。', file=sys.stderr)
        sys.exit(2)
    print(f"按 --skip-check 跳过校验（{len(errs)} 个错误）：{skip}")
    return f"跳过校验（{len(errs)} 个错误）"


def start_run(project: Path, task: str, seat: str, member: str, prompt: str,
              session: Optional[str] = None, parent: Optional[str] = None, override: str = "",
              adhoc: str = "", skip_check: str = "") -> int:
    members = load_members()
    if member not in members:
        sys.exit(f"未知成员 {member}，可用：{'、'.join(members)}（在 {members_source()} 配置）")
    cfg = members[member]
    if not cfg.get("available", "✓").startswith("✓"):
        print(f"提醒：班子配置里 {member} 的状态是「{cfg['available']}」，可能会失败", file=sys.stderr)
    if cfg.get("parser") not in PARSERS:
        sys.exit(f"{member} 的事件解析「{cfg.get('parser')}」不认识，可用：{'、'.join(PARSERS)}")
    skipped = check_gate(project, skip_check)
    collab = project / "collab"
    if (collab / "内部" / "流转").is_dir():
        if adhoc:
            print("未派活：不再有临时派活，任务必须归属目标并经总裁批准。", file=sys.stderr)
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
    deviations = collab_parse.check_dispatch(collab, task, seat, member, cfg.get("aliases", [member]))
    if deviations and not override:
        print(f"未派活：{task}「{seat}」{member} 与任务卡或目标流程不符：", file=sys.stderr)
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
    rec = {"run": rid, "task": task, "seat": seat, "member": member, "mode": "续接" if session else "新会话",
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
    if flow.kind_of(task) == "议题":
        print(f"未派活：{task} 是议题，用 dispatch.py meet {task} [--wake 成员]", file=sys.stderr)
        return 2
    proj = flow.Project(project)
    actor = proj.actor(member) or next((proj.actor(a) for a in cfg.get("aliases", []) if proj.actor(a)), None)
    if not actor:
        print(f"未派活：{member} 不在 collab/内部/流程/花名册.json 里（运行 init.sh team-sync 重新生成）", file=sys.stderr)
        return 2
    rdir = runs_dir(project)
    rid = new_run_id(rdir, task, member, seat)
    try:
        done = flow.dispatch_begin(proj, task, seat, actor, rid, override)
    except flow.FlowError as e:
        (rdir / f"{rid}.json").unlink(missing_ok=True)  # 没派出去：收回占位记录
        print(f"未派活：{task}（{e.kind}）{e.msg}", file=sys.stderr)
        if e.kind == "规则错误":
            print('确需偏离就加 --override "理由"，记入事件和运行记录，看板标为偏离。', file=sys.stderr)
        return 2
    print("流转：" + "；".join(done))
    full_prompt = flow.dispatch_prompt(proj, task, actor, prompt)
    # 工位：<工作目录>/.scratch/<成员>/<任务>/，上下文包「现状」里写了这个路径；会话 cwd 仍是项目根
    st = flow.replay_all(proj)[0][task]
    (project / flow.workspace(proj, st, actor)["工位"]).mkdir(parents=True, exist_ok=True)
    mode = "resume" if session else "start"
    argv = isolate(build_argv(cfg, mode, full_prompt, session or "", rdir / f"{rid}.last.txt"))
    deviations = [skipped] if skipped else []
    rec = {"run": rid, "task": task, "seat": seat, "member": member, "mode": "续接" if session else "新会话",
           "session": session or "", "continues": parent or "", "prompt": full_prompt, "steps": 0,
           "last_action": "", "final": "", "error": "", "deviations": deviations,
           "override": "；".join(r for r in (override, f"跳过校验：{skipped}" if skipped else "") if r), "adhoc": ""}
    env = member_env({"COLLAB_ACTOR": actor, "COLLAB_RUN": rid, "COLLAB_WRITER": "成员", "COLLAB_FLOW": str(flow.FLOW_PY)})
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
    goal = states[issue]["目标"]

    def goal_of(task: str) -> Optional[str]:
        st = states.get(task)
        return st["目标"] if st else (task.split("-T")[0] if "-T" in task else None)
    runs = [r for r in load_runs(project) if r.get("member") == member and r.get("session")]
    busy = {r["session"] for r in runs if r.get("status") == RUNNING}
    lost = {r["session"] for r in runs if r.get("会话丢失")}
    cands = [r for r in runs if r.get("status") in (DONE, STOPPED) and r.get("seat") != "验收" and r["session"] not in busy | lost
             and (r.get("task") == issue or (goal and goal_of(r.get("task", "")) == goal))]
    return cands[-1] if cands else None


DEFAULT_LIMITS = {"步数": 40, "分钟": 10}
WRAP_LIMITS = {"步数": 3, "秒数": 240}  # 收尾那一次：只许写回复，跑超了也停


def run_limits(key: str) -> Dict[str, int]:
    """每次运行的上限：班子.json 顶层「朝会运行上限」{步数, 分钟}，成员自己的「运行上限」覆盖它；缺省 40 步 10 分钟。写 0 表示不限。"""
    conf: Dict[str, Any] = dict(DEFAULT_LIMITS)
    try:
        team = json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        team = {}
    conf.update(team.get("朝会运行上限") or {})
    for x in team.get("成员", []):
        if key in (x.get("派活名"), *(x.get("别名") or [])):
            conf.update(x.get("运行上限") or {})
    out = {}
    if conf.get("步数"):
        out["步数"] = int(conf["步数"])
    if conf.get("分钟"):
        out["秒数"] = int(float(conf["分钟"]) * 60)
    if conf.get("秒数"):
        out["秒数"] = int(conf["秒数"])
    return out


# 续接失败时各命令行说「会话没了」的说法；Claude 的「No conversation found」和 DeepSeek 的「session … does not exist」实测过
SESSION_LOST = re.compile(r"no conversation found|no (such )?session|session\b.*\b(not found|does not exist)|thread\b.*\bnot found|no rollout", re.I)


def wrap_prompt(reason: str, text: str = "") -> str:
    """text：总裁要求收尾时给的上下文包。被停的那次可能还没把启动语存进会话，运行中又可能有追问，所以从上次成功的「读到」补起，重复没关系。"""
    head = (f"你这次运行被停下来了（{reason}）。现在请不要再调用任何工具、不要再查资料，立刻用你已经查到和想到的内容给出发言："
            f"先给结论，再说依据；哪些没来得及查就直说。直接写发言，作为最后的回复。")
    return f"{head}\n总裁在下面「新发言」里的问题都要回答，有前后不同的以最新的为准。\n\n{text}" if text else head


def _lock_issue(rdir: Path, issue: str, actor: str, wait: float):
    lock = open(rdir / f".朝会-{issue}-{actor}.lock", "a+")
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
        print(f"未叫醒：{member} 不在班子配置里", file=sys.stderr)
        return 2
    cfg = members[key]
    rdir = runs_dir(project)
    lock = _lock_issue(rdir, issue, actor, 60 if wrap else 0)
    if lock is None:
        print(f"{actor} 正在 {issue} 上跑，跑完会接着看新消息")
        return 0
    try:
        try:
            st = flow.issue_begin(proj, issue, actor)
        except flow.FlowError as e:
            print(f"未叫醒：{e.msg}", file=sys.stderr)
            return 2
        mine = [r for r in load_runs(project) if r.get("task") == issue and r.get("member") == key]
        # 只有成功写进黑板的运行才推进「读到」；失败、被停止的不算（I001：失败也推进，补叫不动）
        prev = [r for r in mine if "读到" in r and r.get("status") == DONE]
        since = prev[-1]["读到"] if prev else None
        seen = prev[-1].get("补到") or [] if prev else []
        last = mine[-1] if mine else None
        retry = bool(last and last.get("status") in (FAILED, LOST, STOPPED) and last.get("seat") == "与会")
        if not wrap and not flow.issue_needs(st, actor, since) and not retry:
            print(f"{actor} 在 {issue} 上没有新的点名，不叫醒")
            return 0
        base = issue_session(project, proj, issue, key)
        session = (base or {}).get("session") or ""
        fresh = bool(prev) and prev[-1].get("session") != session  # 接的不是上次成功发言的会话（丢了）：它不记得这场会
        text, manifest = flow.context(proj, issue, actor, since=since, catch_up=retry or bool(wrap), fresh=fresh, seen=seen)
        upto, extra = manifest[-1]["读到"], manifest[-1]["补到"]
        head = f"你受邀参加朝会 {issue}。下面是 flow.py 给你的上下文包，按它发言；当前工作目录是项目根目录。"
        if retry:
            why = (last.get("error") or last.get("status") or "").strip()
            head = (f"上次叫你（{last['run']}）没有成功{'：' + clip(why, 100) if why else ''}，所以你错过了一些内容，下面「新发言」里已经补上。"
                    f"现在重新叫你，请按上下文包发言。当前工作目录是项目根目录。")
        if fresh:
            head += "这是一个新会话，你之前在这场会说过什么这里没有记录；下面「新发言」是到现在的全部公开发言，包括你自己说过的。"
        prompt = f"{head}\n\n{text}"
        limits = run_limits(key)
        rec = None
        note = wrap  # 记进运行记录「收尾」：总裁要求的，或到上限自动收尾的原因
        if wrap:  # 总裁要求收尾：有会话就续接被停止的，要它发言，运行中的追问一起给
            prompt, limits = wrap_prompt(wrap, text), WRAP_LIMITS
        for attempt in (0, 1):  # 第 2 次只在第 1 次到上限被停掉时：自动收尾
            rid = new_run_id(rdir, issue, key, "与会")
            mode = "resume" if session else "start"
            argv = isolate(build_argv(cfg, mode, prompt, session, rdir / f"{rid}.last.txt"))
            rec = {"run": rid, "task": issue, "seat": "与会", "member": key, "mode": "续接" if session else "新会话",
                   "session": session, "continues": (base or {}).get("run", ""), "prompt": prompt, "steps": 0,
                   "last_action": "", "final": "", "error": "", "deviations": [], "override": "", "adhoc": ""}
            if note:
                rec["收尾"] = note
            tbase = ((base or {}).get("tokens") or {}).get("session_cum") if base else None
            code = Runner(project, rec, argv, cfg["parser"], token_base=tbase, limits=limits).run()
            reason = rec.get("stop_reason", "")
            if attempt == 0 and reason.startswith("上限") and not wrap:
                msg = f"{actor} 的运行到了上限（{reason[3:]}），已停下，自动让它用已有内容收尾"
                print(msg)
                try:
                    flow.record(proj, issue, "进展", {"发起": flow.LEAD, "写入者": "派活脚本", "派活": rid, "说明": msg})
                except flow.FlowError:
                    pass
                session = rec.get("session") or session
                base = {"run": rid, "tokens": rec.get("tokens")}
                note = reason
                if session:
                    prompt = wrap_prompt(reason)
                else:
                    prompt = f"你的上一次运行到了上限（{reason[3:]}）被停下，请不要再调用工具，用下面的材料直接发言。\n\n{text}"
                limits = WRAP_LIMITS
                continue
            break
        if rec.get("status") == FAILED and rec.get("mode") == "续接" and SESSION_LOST.search(rec.get("error") or ""):
            # 再续接也不会好：记下来，下次开新会话（issue_session 跳过），带上全部公开发言
            rec["会话丢失"] = True
            rec["error"] = clip(rec["error"] + "（这个会话已经找不到了；补叫会开新会话，带上全部公开发言）", 300)
            write_json(rdir / f"{rid}.json", rec)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    try:
        done, wake = flow.issue_end(proj, issue, actor, rid, rec.get("session", ""), rec.get("final", ""),
                                    rec.get("status") == DONE, upto)
        print("黑板：" + "；".join(done))
        if rec.get("status") == DONE and rec.get("final", "").strip():
            rec["读到"] = upto
            if extra:
                rec["补到"] = extra
            write_json(rdir / f"{rid}.json", rec)
    except flow.FlowError as e:
        print(f"发言没写进黑板（{e.kind}）：{e.msg}；原文留在运行记录 {rid}", file=sys.stderr)
        return 1
    if wake:
        spawn_meet(project, issue, wake)
        print("接着叫醒：" + "、".join(wake))
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
    print(f"已停止：{'、'.join(stopped)}" if stopped else f"{a.member} 在 {a.issue} 上没有正在跑的运行")
    return 0


def cmd_wrap(a, project: Path) -> int:
    """收尾：先停止这位成员当前的运行，再续接同一会话，要它用已有内容发言。
    一次收尾只算一次：另一个收尾还没结束、已经在收尾（含到上限自动收尾）、或者已经发过言没有在跑的，都不再做。"""
    proj = flow.Project(project)
    actor = proj.actor(a.member) or a.member
    key = member_key(proj, actor, load_members()) or a.member
    guard = _lock_issue(runs_dir(project), f"{a.issue}-收尾", actor, 0)
    if guard is None:
        print(f"{a.member} 已经在收尾了")
        return 0
    try:
        mine = [r for r in load_runs(project) if r.get("task") == a.issue and r.get("member") == key]
        running = [r for r in mine if r.get("status") == RUNNING]
        if any(r.get("收尾") for r in running):
            print(f"{a.member} 已经在收尾了")
            return 0
        if mine and not running and mine[-1].get("status") == DONE:
            print(f"{a.member} 没有正在跑的运行，不用收尾")
            return 0
        if a.page:
            flow.record(proj, a.issue, "进展", {"发起": flow.BOSS, "写入者": "看板", "说明": f"总裁在朝会页让 {actor} 用已有内容收尾：先停止当前运行再续接发言"})
        stopped = stop_member(project, a.issue, a.member)
        print(f"已停止：{'、'.join(stopped) or '（当前没有在跑的）'}；让 {a.member} 收尾", flush=True)
        return run_issue_member(project, a.issue, a.member, wrap=a.reason or "总裁要求收尾")
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
    if not st or st["种类"] != "议题":
        sys.exit(f"{a.issue} 不是已建立的议题（flow.py 建立 议题）")
    if st["状态"] != "讨论中":
        sys.exit(f"{a.issue} 现在是「{st['状态']}」；总裁开始讨论后才能叫醒与会者")
    names = [x["成员"] for x in st["与会"]]
    if a.wake:
        who = []
        for w in a.wake:
            x = proj.actor(w)
            if x not in names:
                sys.exit(f"「{w}」不在 {a.issue} 的与会名单里（{'、'.join(names)}）")
            who.append(x)
    else:
        spoke = {r.get("发起") for r in st["事件"] if r.get("边") in flow.MESSAGES}
        who = [n for n in names if n not in spoke]
        if not who:
            sys.exit(f"{a.issue} 的与会者都开过口了；要叫谁用 --wake 写，或在发言里 @ 他")
    if a.detach:
        spawn_meet(project, a.issue, who)
        print(f"已在后台叫醒：{'、'.join(who)}（进度看 dispatch.py list 或看板）")
        return 0
    procs = [(w, subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--project", str(project), "meet-run", a.issue, w],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace")) for w in who]
    print(f"朝会 {a.issue}：叫醒 {'、'.join(who)}，并行进行", flush=True)
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
    return runs_dir(project) / f"{issue}.到场.txt"  # 不用 .json：避免被当成派活记录读


def fill_card(path: Path, question: str, opening: str) -> None:
    """写议题卡的「问题」，并在它后面加一节「开场约定」（软约定：总管写明这场会要什么、已知情况、资料位置）。
    命令行里写的字面 \\n 算换行（shell 的双引号不转义，总管常这样写）。"""
    question, opening = question.replace("\\n", "\n"), opening.replace("\\n", "\n")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## 问题\s*\n", text, re.M)
    if not m:
        sys.exit(f"{path.name} 里没有「问题」一节")
    nxt = re.search(r"^## ", text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(text) - m.end())
    body = text[m.end():end]
    if question.strip():
        body = question.strip() + "\n\n"
    if opening.strip():
        body = body.rstrip("\n") + "\n\n## 开场约定\n" + opening.strip() + "\n\n"
    path.write_text(text[:m.end()] + body + text[end:], encoding="utf-8")


def open_room(project: Path, issue: str, port: Optional[int] = None) -> int:
    """对议题的全部与会者做启动检查，结果写进 到场 记录和一条进展；全部就绪且议题还在「起草」就记总裁的「开始」（总管代记）。"""
    proj = flow.Project(project)
    st = flow.replay_all(proj)[0].get(issue)
    if not st or st["种类"] != "议题":
        sys.exit(f"{issue} 不是已建立的议题")
    if st["状态"] not in ("起草", "讨论中"):
        sys.exit(f"{issue} 现在是「{st['状态']}」，不能搭会议室")
    members = load_members()
    keys = []
    for x in st["与会"]:
        k = member_key(proj, x["成员"], members)
        keys.append(k or x["成员"])
    print(f"启动检查：{'、'.join(keys)}（每人一次最小的真实调用）", flush=True)
    results = check_members(project, keys)
    ready = {"checked": now_iso(), "members": {r["member"]: r for r in results}}
    write_json(ready_file(project, issue), ready)
    bad = [r for r in results if not r["ok"]]
    for r in results:
        print(f"  {r['member']:<14} {'就绪' if r['ok'] else '未就绪'}  {r['seconds']}秒{'  ' + r['error'] if r['error'] else ''}")
    summary = "；".join(f"{r['member']}{'就绪' if r['ok'] else '未就绪（' + clip(r['error'], 60) + '）'}" for r in results)
    flow.record(proj, issue, "进展", {"发起": flow.LEAD, "写入者": "总管", "说明": "到场检查：" + summary})
    if bad:
        print(f"\n没有开会：{len(bad)} 位没就绪，{issue} 仍是「{st['状态']}」。处理后运行 dispatch.py ready {issue} 重新检查。")
        return 1
    if st["状态"] == "起草":
        flow.record(proj, issue, "开始", {"发起": flow.BOSS, "写入者": "总管", "依据": "总裁：开会（总管搭好会议室，成员已就绪）"})
    print(f"\n会议室已就绪，{issue} 在「讨论中」，成员等总裁 @ 再开口。\n地址：{meet_url(project, issue, port)}")
    return 0


def cmd_room(a, project: Path) -> int:
    check_gate(project, a.skip_check or "")
    proj = flow.Project(project)
    args: Dict[str, Any] = {"发起": flow.LEAD, "写入者": "总管", "标题": a.标题, "与会": a.与会, "依据": a.依据}
    if a.目标:
        args["目标"] = a.目标
    if a.类型:
        args["类型"] = a.类型
    try:
        issue, path = flow.create(proj, "议题", args)
    except flow.FlowError as e:
        print(f"没能建议题（{e.kind}）：{e.msg}", file=sys.stderr)
        return 2
    fill_card(path, a.问题 or "", a.开场 or "")
    print(f"已建立 {issue}：{path.relative_to(project)}")
    return open_room(project, issue, a.port)


def cmd_ready(a, project: Path) -> int:
    return open_room(project, a.issue, a.port)


# ---------- 子命令 ----------

def cmd_start(a, project: Path) -> int:
    return start_run(project, a.task, a.seat, a.member, read_prompt(a.prompt), override=a.override or "",
                     adhoc=a.adhoc or "", skip_check=a.skip_check or "")


def cmd_continue(a, project: Path) -> int:
    runs = load_runs(project)
    if a.run:
        base = next((r for r in runs if r.get("run") == a.run), None)
        if not base:
            sys.exit(f"找不到派活 {a.run}")
    else:
        cands = [r for r in runs if r.get("task") == a.task and r.get("seat") == a.seat and r.get("session")]
        if not cands:
            sys.exit(f"{a.task} 的「{a.seat}」席位还没有可续接的会话，先用 start 派活")
        base = cands[-1]
    if base.get("status") == RUNNING:
        sys.exit(f"{base['run']} 还在运行，先等它结束或 stop 它")
    if not base.get("session"):
        sys.exit(f"{base['run']} 没有记录会话 ID，无法续接")
    return start_run(project, base["task"], base["seat"], base["member"], read_prompt(a.prompt),
                     session=base["session"], parent=base["run"], override=a.override or "",
                     adhoc=base.get("adhoc") or "", skip_check=a.skip_check or "")


def _stop_one(project: Path, r: Dict[str, Any]) -> str:
    meta = project / "collab" / RUNS_DIR / f"{r['run']}.json"
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
    return f"{r['run']} 已停止（{r['member']}，会话 {cur.get('session') or '无'}，可用 continue 续接）"


def cmd_stop(a, project: Path) -> int:
    runs = load_runs(project)
    if a.all:
        targets = [r for r in runs if r.get("status") == RUNNING]
        if not targets:
            print("没有正在运行的派活")
    else:
        if not a.run:
            sys.exit("指定要停的派活编号，或用 --all")
        targets = [r for r in runs if r.get("run") == a.run]
        if not targets:
            sys.exit(f"找不到派活 {a.run}")
        if targets[0].get("status") != RUNNING:
            print(f"{a.run} 当前状态是 {targets[0].get('status')}，不需要停")
            return 0
    for r in targets:
        print(_stop_one(project, r))
    return 0


def _ago(iso: str) -> str:
    try:
        s = int((dt.datetime.now().astimezone() - dt.datetime.fromisoformat(iso)).total_seconds())
    except (TypeError, ValueError):
        return ""
    return f"{s}秒前" if s < 120 else f"{s // 60}分钟前" if s < 7200 else f"{s // 3600}小时前"


def cmd_list(a, project: Path) -> int:
    runs = load_runs(project)
    if not a.all:
        running = [r for r in runs if r.get("status") == RUNNING]
        rest = [r for r in runs if r.get("status") != RUNNING][-10:]
        runs = rest + running
    if not runs:
        print("还没有派活记录")
        return 0
    for r in runs:
        tail = f"最近：{r.get('last_action') or '—'}（{_ago(r.get('last_at'))}）" if r.get("status") == RUNNING \
            else (f"错误：{clip(r.get('error'), 60)}" if r.get("status") in (FAILED, LOST) and r.get("error") else "")
        print(f"{r['run']:<10} {r.get('status', ''):<5} {r.get('seat', ''):<3} {r.get('member', ''):<8} "
              f"{(r.get('started') or '')[5:16].replace('T', ' ')}  {r.get('steps', 0)}步  "
              f"{fmt_tokens(r.get('tokens')):<14} {tail}")
    return 0


def cmd_show(a, project: Path) -> int:
    r = next((x for x in load_runs(project) if x.get("run") == a.run), None)
    if not r:
        sys.exit(f"找不到派活 {a.run}")
    for k in ("run", "task", "seat", "member", "mode", "session", "continues", "status", "started", "ended",
              "steps", "last_action", "error", "override", "deviations"):
        if r.get(k) not in (None, ""):
            print(f"{k}: {r[k]}")
    tk = r.get("tokens")
    if tk:
        print(f"tokens: {fmt_tokens(tk)}（输入 {tk.get('input', 0)}，缓存 {tk.get('cached', 0)}，输出 {tk.get('output', 0)}"
              + (f"，调用 {tk['calls']} 次" if tk.get("calls") else "")
              + (f"，最后上下文 {tk['context']}" if tk.get("context") else "")
              + (f"，约 {tk['cost_usd']} 美元" if tk.get("cost_usd") else "") + "）")
    print("\n--- 启动语 ---\n" + r.get("prompt", ""))
    if r.get("final"):
        print("\n--- 最终回复 ---\n" + r["final"])
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
            print(f"{r['run']}：算不出（{e}），跳过", file=sys.stderr)
            continue
        if not t:
            continue
        meta = rdir / f"{r['run']}.json"
        rec = json.loads(meta.read_text(encoding="utf-8"))
        rec["tokens"] = r["tokens"] = t
        write_json(meta, rec)
        n += 1
        print(f"{r['run']:<10} {r.get('member', ''):<8} {fmt_tokens(t)}")
    print(f"补算 {n} 条")
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
    text = re.sub(r"(?m)^(状态：)[^｜\n]*", lambda m: m.group(1) + state + " ", text, count=1)
    path.write_text(text, encoding="utf-8")


def cmd_meet(a, project: Path) -> int:
    if (project / "collab" / "内部" / "流转" / f"{a.issue}.jsonl").exists():
        return cmd_meet_flow(a, project)
    if a.wake or a.detach:
        sys.exit("--wake、--detach 只用于新结构项目（有 collab/内部/流转/）的议题")
    check_gate(project, a.skip_check or "")
    collab = project / "collab"
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="dispatch.py", description="向命令行成员派活并记录")
    ap.add_argument("--project", help="项目目录（默认从当前目录向上找 collab/PROGRESS.md）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start", help="新会话派活")
    p.add_argument("task"); p.add_argument("seat"); p.add_argument("member"); p.add_argument("prompt")
    p.add_argument("--override", help="与任务卡或目标流程不符时仍要派，写明理由")
    p.add_argument("--adhoc", help="只用于旧结构项目；新结构不再有临时派活")
    p.add_argument("--skip-check", help="collab/ 校验有错仍要派（只用于校验器误报），写明理由")
    p = sub.add_parser("continue", help="续接最近的会话")
    p.add_argument("task"); p.add_argument("seat"); p.add_argument("prompt")
    p.add_argument("--run", help="续接指定派活的会话，而不是该席位最近的一次")
    p.add_argument("--override", help="与任务卡或目标流程不符时仍要续接，写明理由")
    p.add_argument("--skip-check", help="collab/ 校验有错仍要续接（只用于校验器误报），写明理由")
    p = sub.add_parser("stop", help="停止派活")
    p.add_argument("run", nargs="?"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("list", help="列出派活")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("show", help="显示一次派活")
    p.add_argument("run")
    p = sub.add_parser("tokens", help="从原始事件补算各次派活的 token")
    p.add_argument("--force", action="store_true", help="已有的也重算")
    p = sub.add_parser("meet", help="朝会：叫醒与会者（旧结构：开下一轮）")
    p.add_argument("issue"); p.add_argument("--round", type=int, help="旧结构：指定轮次（只能是下一轮）")
    p.add_argument("--wake", nargs="*", help="新结构：叫醒这几位与会者；不写时叫醒还没开过口的")
    p.add_argument("--detach", action="store_true", help="新结构：后台叫醒，不等结果（看板用）")
    p.add_argument("--skip-check", help="collab/ 校验有错仍要开会（只用于校验器误报），写明理由")
    p = sub.add_parser("check", help="启动检查：用一次最小的真实调用确认成员能启动、已登录（不写运行记录）")
    p.add_argument("members", nargs="*", help="成员；不写时检查班子里全部")
    p = sub.add_parser("room", help="搭会议室：建议题、写开场约定、启动检查，就绪就进讨论中并给出地址")
    p.add_argument("--标题", required=True); p.add_argument("--依据", required=True, help="总裁的原话")
    p.add_argument("--与会", nargs="+", required=True, help="成员:视角，如 claude-sonnet:从实现看")
    p.add_argument("--问题", help="写进议题卡「问题」一节的内容（不写就保留模板）")
    p.add_argument("--开场", help="开场约定：这场会要什么、已知情况、资料位置（软约定，成员可以看、不是必须看）")
    p.add_argument("--目标"); p.add_argument("--类型", choices=["朝会", "会审"])
    p.add_argument("--port", type=int, help="看板端口（默认 3100 或环境变量 COLLAB_BOARD_PORT）")
    p.add_argument("--skip-check", help="collab/ 校验有错仍要建（只用于校验器误报），写明理由")
    p = sub.add_parser("ready", help="对起草中的议题重做启动检查，就绪就进讨论中")
    p.add_argument("issue"); p.add_argument("--port", type=int)
    p = sub.add_parser("stop-member", help="停止某成员在议题上正在跑的运行")
    p.add_argument("issue"); p.add_argument("member")
    p = sub.add_parser("wrap", help="收尾：停掉成员当前的运行，续接同一会话要它用已有内容发言")
    p.add_argument("issue"); p.add_argument("member"); p.add_argument("--reason", help="写进收尾提示的原因")
    p.add_argument("--page", action="store_true", help="（内部）看板发起的：真的收尾时记一条进展")
    p = sub.add_parser("meet-run", help="（内部）叫醒一位与会者跑一次，由 meet 调用")
    p.add_argument("issue"); p.add_argument("member")
    a = ap.parse_args(argv)
    project = Path(a.project).expanduser().resolve() if a.project else find_project(Path.cwd())
    if not (project / "collab" / "PROGRESS.md").exists():
        sys.exit(f"{project} 下没有 collab/PROGRESS.md")
    refusal = flow.dev_write_refusal(project) if a.cmd not in ("list", "show") else None
    if refusal:
        sys.exit(refusal)
    return {"start": cmd_start, "continue": cmd_continue, "stop": cmd_stop,
            "list": cmd_list, "show": cmd_show, "meet": cmd_meet, "tokens": cmd_tokens, "check": cmd_check, "wrap": cmd_wrap, "stop-member": cmd_stop_member, "room": cmd_room, "ready": cmd_ready,
            "meet-run": lambda a, pr: run_issue_member(pr, a.issue, a.member)}[a.cmd](a, project)


if __name__ == "__main__":
    sys.exit(main())
