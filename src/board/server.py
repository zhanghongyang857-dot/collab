#!/usr/bin/env python3
"""看板网页服务：各项目的御前看板页，和可选的 NOW 页（复用模板里的 build.py 读 NOW 数据目录，生成到临时文件）。

用法：python3 board/server.py [--port 3100] [--now-dir <NOW 数据目录>] [--project 目录 ...]
项目来自工具包旁的登记表 projects.json（init.sh new / register 写）、NOW 任务表和已完成表、--project，按根目录去重。
页面：首页（/：启用了 NOW 是 NOW 页，没有时是项目列表）、项目列表（/projects）、御前看板（/p/<项目>）、朝会（/p/<项目>/meet/<议题>）、班子（/team）、人才市场（/talent）。
只读，加只能追加经过校验的黑板事件：不直接写 NOW、各项目 collab/ 或运行记录；动作只有两个——
/api/open 用系统默认应用打开本机文件；/api/p/<项目>/meet/<议题> 由总裁在朝会页发言、开始、结束、裁决，
经 flow.py 同一套检查写一条事件，带 @ 的发言和「开始」在后台用 dispatch.py meet 叫醒相关成员。
只用 Python 标准库，只监听 127.0.0.1。其他设备经 `tailscale serve` 代理访问（service.sh remote on），
这类请求算「远程」：页面照常读写，但 /api/open 拒绝（打开的是 Mac 上的文件），页面也不显示打开按钮。
"""
import argparse
import contextlib
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "core"))
import collab_parse  # noqa: E402  与派活脚本共用的任务卡、目标卡解析
import check as collab_check  # noqa: E402  collab/ 校验，与派活脚本、Stop hook 共用
import flow  # noqa: E402  新结构项目（有 collab/内部/流转/）的投影：状态、阶段和视图模型都从这里来
import registry  # noqa: E402  项目登记表和 NOW 位置，与 init.sh 共用
import paths as P  # noqa: E402
import vocab  # noqa: E402
import team as team_mod  # noqa: E402  班子配置：键换成英文读
from vocab import Edge as E, MeetAction, RunPhase, RunStatus, Section, State as S, StageStatus, Writer  # noqa: E402

STATIC = HERE / "static"
STATIC_FILES = {"board.css": "text/css", "project.js": "text/javascript", "project.html": "text/html",
                "meet.html": "text/html", "meet.js": "text/javascript",
                "now-inject.css": "text/css", "now-inject.js": "text/javascript", "live.js": "text/javascript",
                "team.html": "text/html", "team.js": "text/javascript",
                "talent.html": "text/html", "talent.js": "text/javascript",
                "projects.html": "text/html", "projects.js": "text/javascript", "i18n.js": "text/javascript",
                "pwa.js": "text/javascript", "sw.js": "text/javascript",  # sw.js 从根路径 /sw.js 提供，见 sw_js()
                "icon-180.png": "image/png", "icon-192.png": "image/png", "icon-512.png": "image/png"}
TEAM_DIR = flow.team_dir()
BOARD_LANG = registry.kit_lang(HERE.parent)  # 看板默认语言：COLLAB_LANG → NOW config.json 的 lang → en；页面里还要看 ?lang、本机选择和项目语言
TALENT_EXAMPLE = HERE.parent / "core" / "team-example" / P.TALENT_JSON
RUNS_DIR = P.INTERNAL_RUNS
OPEN_SUFFIXES = {".md", ".html", ".txt", ".json", ".jsonl", ".py", ".pdf", ".csv", ".png", ".jpg"}
BUILD_LOCK = threading.Lock()
DISPATCH_PY = HERE.parent / "core" / "dispatch.py"
MEET_ACTIONS = (E.POST, E.START, E.END_DISCUSSION, E.CONTINUE_DISCUSSION, E.RULE, E.CANCEL,
                MeetAction.REDELIVER, MeetAction.ADD, MeetAction.STOP, MeetAction.WRAP)
STALL_SECONDS = 90  # 运行中这么久没有实际输出（工具心跳不算），页面标「疑似卡住」
GOAL_ACTIONS = (E.APPROVE, E.RETURN, E.COMMENT)
BUILD_PY = HERE / "now" / "build.py"  # NOW 看板代码，template.html 在同目录

ARGS: argparse.Namespace


def default_now_dir() -> str:
    """本机发布在 NOW/系统/ 时，NOW 数据目录就是它的上一级（有 config.json 即是，不要求装了哪个模块）；
    其次 NOW_PATH、本工具包装的常驻配置（见 core/registry.py）；都没有时为空，即没启用 NOW。"""
    found = registry.now_data_dir(flow.TOOLKIT)
    return str(found) if found else ""


def now_enabled() -> bool:
    """启用了 NOW：给了 NOW 数据目录，且其中有 config.json 或上一级有 NOW.md。"""
    if not ARGS.now_dir:
        return False
    d = Path(ARGS.now_dir).expanduser()
    return (d / "config.json").exists() or (d.parent / "NOW.md").exists()


# ---------- NOW：重新加载 build.py 生成；按文件指纹缓存，依赖的文件没变不重算 ----------

def load_build():
    # build.py 在导入时按 NOW_DATA_DIR 定数据目录；代码用工具包里模板那份，NOW 目录只放数据
    if ARGS.now_dir:
        os.environ["NOW_DATA_DIR"] = str(Path(ARGS.now_dir).expanduser())
    else:  # 没启用 NOW：build.py 退回它自己的目录，那里没有 NOW 数据，只借用解析函数
        os.environ.pop("NOW_DATA_DIR", None)
    path = BUILD_PY
    spec = importlib.util.spec_from_file_location("now_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PWA_HEAD = ('<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/static/icon-180.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
            '<meta name="theme-color" content="#f6f5f2" media="(prefers-color-scheme: light)">'
            '<meta name="theme-color" content="#141415" media="(prefers-color-scheme: dark)">')  # 主屏 app（G056-T5）；static/*.html 里写在文件中
NOW_INJECT = (PWA_HEAD + '<link rel="stylesheet" href="/static/now-inject.css"><script src="/static/vocab.js" defer></script>'
              '<script src="/static/live.js" defer></script><script src="/static/pwa.js" defer></script>'
              '<script src="/static/now-inject.js" defer></script>')  # NOW 页自带语言包和 i18n.js


def now_html() -> str:
    """/ 的 NOW 页：外壳（不含数据），注入 now-inject 和外壳指纹；页面自己拉 /api/now 再画，之后靠推送只换数据重画。"""
    return now_bundle()["html"].decode("utf-8")


def now_bundle() -> Dict[str, Any]:
    """NOW 页和 /api/now 的数据一次算出，按依赖文件的指纹缓存：{html, json, tag, shell}。"""
    deps_before = list(NOW_DEPS)
    sig = now_sig(deps_before)
    hit = CACHE.get("now")
    if hit and hit[0] == sig and time.time() - hit[1] < CACHE_TTL:
        return hit[2]
    with key_lock("now"):  # 同时来的请求只算一次：后到的等前一个算完，再看一遍缓存
        deps_before = list(NOW_DEPS)
        sig = now_sig(deps_before)
        hit = CACHE.get("now")
        if hit and hit[0] == sig and time.time() - hit[1] < CACHE_TTL:
            return hit[2]
        return _now_bundle(deps_before, sig)


def _now_bundle(deps_before: List[Path], sig: str) -> Dict[str, Any]:
    t0 = time.time()
    with BUILD_LOCK:
        mod = load_build()
        deps: List[Path] = []
        d = mod.collect(deps)
        payload = mod.data(d)
        deps += mod.shell_sources()
        page = mod.shell(d["modules"])
        shell = shell_fingerprint(page)
    payload["shell"] = shell  # 外壳指纹按服务端实际给的外壳算（含 static/），和 /api/events 的 shell 一致
    body, tag = encode(payload, "built")
    inject = f'<meta name="board-shell" content="{shell}">' + NOW_INJECT  # 页面据此判断 /api/now 和推送里的外壳是不是自己这版
    out = {"html": page.replace("</head>", inject + "</head>", 1).encode("utf-8"), "json": body, "tag": tag, "shell": shell}
    NOW_DEPS[:] = deps
    # 依赖清单变了（第一次算、任务表里加了任务）就按新清单记指纹；算之前先取的指纹保证算的过程中文件又变了时下次重算
    CACHE["now"] = (sig if deps == deps_before else now_sig(deps), t0, out)
    return out


def now_sig(deps: List[Path]) -> str:
    return stat_sig(deps) + dt.date.today().isoformat()  # 模块按「今天」算，过了零点要重算


# ---------- 按文件指纹缓存、监视线程和推送（G056）----------

CACHE_TTL = 60  # 秒：有的模块数据来自依赖清单以外（如专注 app 的计时），指纹没变也最多这么久重算一次
RUN_MIN = 10  # 秒（G056-T9）：只有运行记录变了时，同一块最多这么久重算一次、推送一次；成员在跑时运行流每秒都在写
CACHE: Dict[str, Any] = {}  # 键 → 结果：now 是 (指纹, 算好的时间, 结果)；其余（memo）是 {sigs, t, out, ver}
LOCKS: Dict[str, threading.Lock] = {}  # 每块一把锁：同一块的并发请求合并为一次计算
LOCKS_GUARD = threading.Lock()
DISCOVER_DEPS: List[Path] = []  # discover() 读的 NOW 任务表、已完成表、登记表：项目列表按它们和各项目账本缓存
NOW_DEPS: List[Path] = []  # 上次生成 NOW 数据时的依赖文件（build.py 的 sources 和 shell_sources），监视线程只 stat 它
KNOWN: Dict[str, Dict[str, Any]] = {}  # discover() 见过的项目：/api/p/<id> 不必每次重新发现，监视线程按它看各项目的账本
SSE_MAX = 16  # /api/events 同时连接数上限：每个连接占一个线程，自用设备个位数
SSE_LOCK = threading.Lock()
SSE_OPEN = [0]
HEARTBEAT = 15  # 秒：SSE 心跳，防 iOS 和代理掐断空闲连接
SLOW_ROUND_MS = 20  # 单轮 stat 超过它就降到 2 秒一轮


def stat_sig(paths) -> str:
    """一组文件的指纹：路径 + 修改时间 + 大小；不存在的文件也记一笔（删掉、新建都算变化）。"""
    h = hashlib.sha1()
    for f in paths:
        try:
            st = os.stat(f)
            h.update(f"{f}\0{st.st_mtime_ns}\0{st.st_size}\n".encode("utf-8", "surrogateescape"))
        except OSError:
            h.update(f"{f}\0-\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def tree_sig(root: Path, skip: Optional[Path] = None) -> str:
    """目录下全部文件和子目录的指纹（项目账本 collab/：卡片、流转日志、运行记录、配置都在里面）；skip 给出的子目录整个不看。"""
    h = hashlib.sha1()
    stack = [str(root)]
    skip_s = str(skip) if skip else None
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            h.update(f"{cur}\0-\n".encode("utf-8", "surrogateescape"))
            continue
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if e.path == skip_s:
                continue
            h.update(f"{e.path}\0{st.st_mtime_ns}\0{st.st_size}\n".encode("utf-8", "surrogateescape"))
            if e.is_dir(follow_symlinks=False):
                stack.append(e.path)
    return h.hexdigest()


# 项目分两类版本（G056-T9）：账本（flow 事件、卡片、PROGRESS、决议、计划……）变了马上推、马上重算；
# 运行（collab/internal/runs/ 下的运行流、运行记录、启动检查）成员在跑时每秒都变，推送和重算都最多 RUN_MIN 秒一次，NOW 页不看它
def ledger_sig(p: Dict[str, Any]) -> str:
    """账本指纹：collab/ 整棵树去掉 internal/runs/，加班子配置（成员名、座位）。"""
    collab = Path(p["progress"]).parent
    return tree_sig(collab, skip=collab / RUNS_DIR) + stat_sig([flow.team_file()])


def run_sig(p: Dict[str, Any]) -> str:
    """运行指纹：collab/internal/runs/ 整棵树。"""
    return tree_sig(Path(p["progress"]).parent / RUNS_DIR)


def project_sig(p: Dict[str, Any]) -> str:
    """项目数据的指纹：账本加运行。"""
    return ledger_sig(p) + run_sig(p)


def project_sigs(p: Dict[str, Any]) -> Callable[[], tuple]:
    return lambda: (ledger_sig(p), run_sig(p))


def all_sigs() -> tuple:
    """跨项目的数据（项目列表、朝会入口、班子页）的指纹：NOW 任务表、已完成表、登记表，加见过的各项目的账本 / 运行。"""
    ps = [KNOWN[k] for k in sorted(KNOWN)]
    return (stat_sig(DISCOVER_DEPS + [flow.team_file()]) + "".join(ledger_sig(p) for p in ps),
            "".join(run_sig(p) for p in ps))


def key_lock(key: str) -> threading.Lock:
    with LOCKS_GUARD:
        return LOCKS.setdefault(key, threading.Lock())


def memo(key: str, sig_fn: Callable[[], tuple], compute: Callable[[], Any], run_key: str = "") -> tuple:
    """按依赖文件指纹缓存一块数据，返回 (结果, 运行版本号)。sig_fn() 给 (账本指纹, 运行指纹)：
    都没变：直接用，最多 CACHE_TTL 秒重算一次（有的数据来自清单以外，如成员进程还在不在）；
    只有运行指纹变了：距上次算不到 RUN_MIN 秒就用上次结果；账本变了：马上重算。
    同一块同时来的请求只算一次，其余等它算完用同一份。运行版本号是结果对应的 run_key（r:<项目>）版本：
    用上次结果时给上次算时的版本，页面看到它比推送来的旧，过一阵再拉。"""
    def usable(h: Optional[Dict[str, Any]], sigs: tuple) -> bool:
        if not h:
            return False
        age = time.time() - h["t"]
        return age < CACHE_TTL if h["sigs"] == sigs else (h["sigs"][0] == sigs[0] and age < RUN_MIN)

    sigs = sig_fn()
    h = CACHE.get(key)
    if not usable(h, sigs):
        with key_lock(key):
            sigs = sig_fn()
            h = CACHE.get(key)
            if not usable(h, sigs):
                first = h is None
                ver = WATCH.versions.get(run_key, "") if run_key else ""  # 先取版本号再算：取到旧的只会让页面多拉一次
                t0 = time.time()
                out = compute()
                # 第一次算时依赖清单（见过的项目、任务表）才刚知道，按算完的清单重记指纹，免得下一次又算一遍
                h = {"sigs": sig_fn() if first else sigs, "t": t0, "out": out, "ver": ver}
                CACHE[key] = h
    if not run_key:
        return h["out"], ""
    return h["out"], str(WATCH.versions.get(run_key, "") if h["sigs"][1] == sigs[1] else h["ver"])


def projects() -> List[Dict[str, Any]]:
    """discover() 按指纹缓存：项目列表（/api/projects、朝会入口、班子页都用它）。"""
    return memo("projects", all_sigs, discover)[0]


def encode(data: Any, *volatile: str) -> tuple:
    """JSON 正文和算 ETag 用的内容（去掉每次都变的键，如 generated、built）。"""
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    keys = [k for k in volatile if isinstance(data, dict) and k in data]
    tag = json.dumps({k: v for k, v in data.items() if k not in keys}, ensure_ascii=False).encode("utf-8") if keys else None
    return body, tag


def project_cached(p: Dict[str, Any], archive: bool = False) -> tuple:
    """/api/p/<id> 的 (正文, ETag 内容, 运行版本号)：账本没变时不重算（现算一次约 0.27s），只有运行记录变了时最多 RUN_MIN 秒一次。"""
    (body, tag), ver = memo(("a:" if archive else "p:") + p["id"], project_sigs(p),
                            lambda: encode(archive_data(p) if archive else project_data(p), "generated"), "r:" + p["id"])
    return body, tag, ver


def find_project(pid: str) -> Optional[Dict[str, Any]]:
    """按 id 找项目：先看 discover() 见过的（账本还在就直接用），没有再重新发现一遍。"""
    p = KNOWN.get(pid)
    if p and Path(p["progress"]).exists():
        return p
    return next((x for x in projects() if x["id"] == pid), None)


def static_paths() -> List[Path]:
    return [STATIC / f for f in sorted(STATIC_FILES)] + [HERE.parent / "core" / "vocab.py"]


def shell_fingerprint(shell_html: str = "") -> str:
    """外壳指纹：NOW 外壳（模板、模块 css/js、语言包）加 static/ 下的页面文件和 vocab.js；变了各端整页重载一次。"""
    h = hashlib.sha1(shell_html.encode("utf-8") + NOW_INJECT.encode("utf-8") + vocab_js().encode("utf-8"))
    for f in static_paths():
        with contextlib.suppress(OSError):
            h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes())
    return h.hexdigest()[:16]


class Watcher:
    """监视线程（服务里只有一个）：每秒 stat 一遍各块的依赖文件，指纹变了就把这块的版本号加一，唤醒 /api/events 的连接。
    块：now（NOW 数据的依赖清单）、shell（外壳，值是外壳指纹）、team（班子和人才配置）、p:<项目>（账本：collab/ 去掉 internal/runs/，
    朝会的黑板也在里面）、r:<项目>（运行：internal/runs/；成员在跑时每秒都变，距上次加版本号不到 RUN_MIN 秒就先压着，到点再加）。
    只 stat 缓存好的清单，不执行模块的 load.py；单轮超过 SLOW_ROUND_MS 就降到 2 秒一轮。
    版本号取 max(上一版 + 1, 当前秒数)：服务重启后也只增不减，前端按「不等」判断即可。"""

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.scan_lock = threading.Lock()  # 后台一轮和 /api/events 首次连上时的一轮不同时跑
        self.versions: Dict[str, Any] = {}
        self.sigs: Dict[str, str] = {}
        self.seq = 0  # 每次有块变化加一，SSE 连接据此判断要不要推
        self.round_ms = 0.0
        self.interval = 1.0
        self.run_bumped: Dict[str, float] = {}  # r:<项目> → 上次加版本号的时间：运行类最多 RUN_MIN 秒推一次
        self.now_static: List[Path] = []  # 不执行 load.py 也知道的 NOW 依赖（NOW.md、各任务 PROGRESS、模块声明的 files）
        self.shell_static: List[Path] = []  # 外壳依赖（build.py 的 shell_sources）
        self.stopped = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        with self.cond:
            if self.thread:
                return
            self.thread = threading.Thread(target=self.run, name="board-watch", daemon=True)
        self.scan()
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        with self.cond:
            self.cond.notify_all()

    def run(self) -> None:
        with contextlib.suppress(Exception):
            discover()  # 先认识一遍项目，监视线程才知道看哪些账本
        while not self.stopped.wait(self.interval):
            try:
                self.scan()
            except Exception as e:  # 监视出错不影响页面，下一轮再试
                if ARGS.verbose:
                    print(f"watch: {e}", file=sys.stderr)

    def refresh_now_static(self) -> None:
        """NOW.md、done.md 变了时重列静态依赖（任务表里可能加了任务）：只解析 Markdown 和 module.json，不执行 load.py。"""
        with BUILD_LOCK:
            mod = load_build()
            self.now_static = mod.sources(mod.load_modules(run=False)[2])

    def blocks(self) -> Dict[str, Callable[[], str]]:
        out: Dict[str, Callable[[], str]] = {"shell": lambda: stat_sig(static_paths() + self.shell_static),
                                             "team": lambda: stat_sig([flow.team_file(), flow.team_file("talent")])}
        if now_enabled():
            out["now"] = lambda: now_sig(sorted(set(self.now_static) | set(NOW_DEPS)))
        for pid, p in list(KNOWN.items()):
            out["p:" + pid] = lambda p=p: ledger_sig(p)
            out["r:" + pid] = lambda p=p: run_sig(p)
        return out

    def scan(self) -> List[str]:
        """一轮：stat 各块，返回变了的块。"""
        with self.scan_lock:
            return self._scan()

    def _scan(self) -> List[str]:
        t0 = time.perf_counter()
        sigs = {k: f() for k, f in self.blocks().items()}
        self.round_ms = (time.perf_counter() - t0) * 1000
        self.interval = 2.0 if self.round_ms > SLOW_ROUND_MS else 1.0
        changed = [k for k, s in sigs.items() if self.sigs.get(k) != s]
        now = time.time()
        held = {k for k in changed if k.startswith("r:") and k in self.sigs and now - self.run_bumped.get(k, 0) < RUN_MIN}
        changed = [k for k in changed if k not in held]
        if not changed:
            return []
        if "now" in changed or ("shell" in changed and now_enabled()):
            self.refresh_now_static()
            with BUILD_LOCK:
                self.shell_static = load_build().shell_sources() if now_enabled() else []
            sigs = {k: f() for k, f in self.blocks().items()}  # 按新清单重记指纹，免得下一轮又算一次变化
        for k in held:  # 压着的运行类不记新指纹：到点后下一轮还算「变了」，那时再加版本号
            sigs[k] = self.sigs[k]
        values = {}
        for k in changed:
            if k == "shell":
                with BUILD_LOCK:
                    values[k] = shell_fingerprint(load_build().shell() if now_enabled() else "")
            else:
                values[k] = max(int(self.versions.get(k) or 0) + 1, int(time.time()))
                if k.startswith("r:"):
                    self.run_bumped[k] = now
        with self.cond:
            self.sigs.update(sigs)
            if any(self.versions.get(k) != v for k, v in values.items()):
                self.versions.update(values)
                self.seq += 1
                self.cond.notify_all()
        return changed

    def snapshot(self) -> tuple:
        with self.cond:
            return self.seq, dict(self.versions)


WATCH = Watcher()


# ---------- 主屏 app（G056-T5）：manifest 和根路径的 Service Worker ----------

ROOT_ICON = re.compile(r"/apple-touch-icon(-\d+x\d+)?(-precomposed)?\.png")


def sw_js() -> bytes:
    """/sw.js：static/sw.js 填上当前外壳指纹（和 /api/events 的 shell 同一个值）。发布了新代码指纹就变，
    sw.js 内容跟着变，浏览器装新版、换新的外壳缓存。"""
    WATCH.start()
    shell = str(WATCH.versions.get("shell") or "")
    return (STATIC / "sw.js").read_text(encoding="utf-8").replace('"__SHELL__"', json.dumps(shell), 1).encode("utf-8")


def manifest() -> bytes:
    """/manifest.webmanifest：加到主屏后全屏打开 /，名字按看板默认语言。"""
    M = flow.i18n.pack(BOARD_LANG).t
    icons = [{"src": f"/static/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any"} for n in (192, 512)]
    icons.append({"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"})  # 图案在中间 60% 内
    return json.dumps({"name": M("board.app.name"), "short_name": M("board.app.short"), "lang": BOARD_LANG,
                       "start_url": "/", "scope": "/", "display": "standalone",
                       "background_color": "#f6f5f2", "theme_color": "#f6f5f2", "icons": icons},
                      ensure_ascii=False, indent=1).encode("utf-8")


# ---------- 项目发现：NOW 任务表和已完成表里链接的 collab/PROGRESS.md、登记表，加上 --project ----------

def project_id(root: Path) -> str:
    return registry.project_id(root)


def flow_goal_alerts(v: Dict[str, Any], issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """新结构项目的摘要，给看板按语言拼：[{id, kind: stage|blocked|await_complete|pending_ruling, no, of}]。"""
    out = []
    blocked = {t["goal"] for t in v["tasks"] if t["state"] == S.BLOCKED}
    for g in v["goals"]:
        if g["state"] != S.ACTIVE or not g["stages"]:
            continue
        cur = next((s for s in g["stages"] if s["state"] != StageStatus.PASSED), None)
        if g["id"] in blocked or (cur and cur["state"] == S.BLOCKED):
            out.append({"id": g["id"], "kind": "blocked"})
        elif cur:
            out.append({"id": g["id"], "kind": "stage", "no": cur.get("order") or g["stages"].index(cur) + 1, "of": len(g["stages"])})
        else:
            out.append({"id": g["id"], "kind": "await_complete"})
    out += [{"id": i["id"], "kind": "pending_ruling"} for i in issues if i["stage"] == S.PENDING_RULING and not i["archived"]]
    return out


def flow_goal_summary(v: Dict[str, Any], issues: List[Dict[str, Any]], L: Optional[Any] = None) -> str:
    """新结构项目的一行摘要，格式同 collab_parse.goal_summary：「G001 ②/5 · G002 受阻 · I003 待裁决」（按项目语言）。"""
    L = L or flow.i18n.pack()
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    text = {"blocked": lambda a: f"{a['id']} {L.st(S.BLOCKED)}",
            "stage": lambda a: f"{a['id']} {circled[a['no'] - 1] if 0 < a['no'] <= len(circled) else a['no']}/{a['of']}",
            "await_complete": lambda a: f"{a['id']} {L.t('srv.await_complete')}",
            "pending_ruling": lambda a: f"{a['id']} {L.st(S.PENDING_RULING)}"}
    return " · ".join(text[a["kind"]](a) for a in flow_goal_alerts(v, issues))


def discover() -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    def add(progress: Optional[Path], name: str, source: str, state: str = "") -> None:
        if not progress or progress.name != P.PROGRESS or progress.parent.name != P.COLLAB or not progress.exists():
            return
        root = progress.parent.parent
        pid = project_id(root)
        if pid not in found:
            try:
                flowed = (progress.parent / P.INTERNAL_FLOW).is_dir()
                if flowed:
                    fp = flow.Project(root)
                    v = flow.view(fp)
                    rows = flow_issue_rows(root, v)
                    summary, alerts = flow_goal_summary(v, rows, fp.L), flow_goal_alerts(v, rows)
                else:
                    summary, alerts = collab_parse.goal_summary(collab_parse.load_goals(progress.parent), collab_parse.load_issues(progress.parent)), None
            except Exception:
                summary, alerts = "", None
            found[pid] = {"id": pid, "name": name or root.name, "root": str(root), "progress": str(progress),
                          "source": source, "state": state, "summary": summary, "alerts": alerts}

    deps: List[Path] = []
    if ARGS.now_dir:
        deps.append(Path(ARGS.now_dir).expanduser() / "config.json")  # 任务表在哪由它定
        try:
            mod = load_build()
            deps += [mod.NOW_MD, mod.DONE_MD]
            for md, src in ((mod.NOW_MD, "now"), (mod.DONE_MD, "done")):
                if md.exists():
                    for r in map(flow.i18n.cols, mod.table_dicts(md.read_text(encoding="utf-8").splitlines())):  # NOW 表头按代码认列
                        name, path = mod.link_parts(r.get("task", ""), md.parent)
                        add(path, name, src, (flow.i18n.code_of("state", r.get("state", "")) or r.get("state", "")) if src == "now" else "done")
        except Exception as e:  # NOW 坏了也不影响登记表和 --project 指定的项目
            print(flow.i18n.pack(registry.kit_lang(flow.TOOLKIT)).t("server.now_failed", e=e), file=sys.stderr)
    if not getattr(ARGS, "no_registry", False):
        reg = registry.path(flow.TOOLKIT)
        if reg:
            deps.append(reg)
        for r in registry.load(reg):
            add(Path(r["root"]) / P.COLLAB / P.PROGRESS, r.get("name", ""), "registry")
    for p in ARGS.project or []:
        root = Path(p).expanduser().resolve()
        add(root / P.COLLAB / P.PROGRESS, "", "extra")
    KNOWN.update(found)
    DISCOVER_DEPS[:] = deps
    return list(found.values())


# ---------- 项目数据 ----------

def is_placeholder(t: str) -> bool:
    t = t.strip()
    return not t or (t.startswith("<") and t.endswith(">")) or t in ("待填", "…", "无")


def kv_line(line: str) -> Dict[str, str]:
    return collab_parse.kv_line(line)


def html_task(mod, t: Dict[str, Any], base: Path) -> Dict[str, Any]:
    out = dict(t)
    out["head"] = head_codes(t.get("head"))
    out["flow"] = [{k: mod.inline(v, base) if k in ("note", "time") else v for k, v in flow_row_codes(r).items()} for r in t["flow"]]
    out["fields"] = field_codes([{"k": f["k"], "v": mod.inline(f["v"], base)} for f in t["fields"]])
    return out


def html_goal(mod, g: Dict[str, Any], by_id: Dict[str, Any], base: Path) -> Dict[str, Any]:
    out = dict(g)
    out["head"] = head_codes(g.get("head"))
    out["fields"] = field_codes([{"k": f["k"], "v": mod.inline(f["v"], base)} for f in g["fields"]])
    stages = []
    for s in g["stages"]:
        st = dict(s)
        for k in ("output", "cond"):
            st[k] = mod.inline(s[k], base)
        st["taskInfo"] = [{"id": i, "title": by_id[i]["title"], "state": by_id[i]["state"], "cls": by_id[i]["cls"],
                           "exec": head_codes(by_id[i]["head"]).get("executor", ""), "archived": by_id[i]["archived"],
                           "flow": [flow_row_codes(r) for r in by_id[i]["flow"]]}
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
        if r.get("status") == RunStatus.RUNNING and not frozen and not pid_alive(r.get("pid")):
            r["status"] = RunStatus.LOST
        r.pop("pid", None)
        r.pop("child_pid", None)
        runs.append(r)
    runs.sort(key=lambda r: (r.get("started") or "", r.get("run") or ""))
    return runs


# 卡头、流转表的列给看板时换成代码（旧结构卡片手写的中文列名、英文卡片的列名都认），看板按语言显示列名
HEAD_CODES = {"状态": "state", "Status": "state", "执行": "executor", "Executor": "executor", "验收": "reviewer", "确认": "reviewer",
              "Reviewer": "reviewer", "目标": "goal", "Goal": "goal", "阶段": "stage", "Stage": "stage", "持有人": "holder", "Holder": "holder",
              "类型": "type", "Type": "type", "优先": "priority", "Priority": "priority", "依赖": "depends_on", "Depends on": "depends_on",
              "截止": "due", "Due": "due", "批准": "approval", "依据": "basis", "工作目录": "workdir"}
FLOW_CODES = {"日期": "time", "状态": "state", "经办人": "from", "接手人": "to", "说明": "note"}
META_CODES = {"目标": "goal", "Goal": "goal", "截止": "due", "Due": "due", "状态": "status", "Status": "status"}


def head_codes(head: Dict[str, Any]) -> Dict[str, Any]:
    return {HEAD_CODES.get(k, k): v for k, v in (head or {}).items()}


def flow_row_codes(r: Dict[str, Any]) -> Dict[str, Any]:
    """旧结构流转表的一行：列名换代码（「说明（…）」也算说明），状态认得的换代码。"""
    out = {}
    for k, v in r.items():
        c = FLOW_CODES.get(k) or ("note" if k.startswith("说明") else k)
        out[c] = v
    st = re.sub(r"[（(：:].*$", "", str(out.get("state", ""))).strip()
    code = flow.i18n.code_of("state", st) or flow.i18n.code_of("result", st)
    if code:
        out["state"] = code
    return out


def field_codes(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{**f, "code": flow.i18n.code_of("field", f["k"]) or ""} for f in fields]


def meta_codes(text: str) -> Dict[str, str]:
    """PROGRESS 标题下那行「目标：… ｜ 截止：… ｜ 状态：… ｜ 建立于 …」（英文 Goal: … ｜ Due: … ｜ Status: … ｜ Started …）。"""
    line = next((l for l in text.splitlines() if l.startswith(("目标：", "Goal:"))), "")
    out = {}
    for part in re.split(r"[｜|]", line):
        k, sep, v = part.replace("：", ":", 1).partition(":")
        if sep and k.strip() in META_CODES:
            out[META_CODES[k.strip()]] = v.strip()
    if out.get("status"):
        out["status"] = flow.i18n.code_of("state", out["status"]) or out["status"]
    return out


TASK_CLS = {S.PASSED: "pass", S.CANCELLED: "pass", S.BLOCKED: "block", S.FAILED: "block", S.IN_REVIEW: "review", S.IN_PROGRESS: "doing"}
STAGE_STATUS = {StageStatus.READY: StageStatus.NOT_STARTED}


def flow_cards(collab: Path, root: Path) -> tuple:
    """新结构项目：任务和目标的状态、持有人、阶段一律取自 flow.py 的视图模型，卡片只提供标题和手写字段。
    返回与 collab_parse 相同形状的 (tasks, goals, view)，看板其余部分不用区分新旧。"""
    proj = flow.Project(root)
    L = proj.L
    v = flow.view(proj)
    old = {t["id"]: t for t in collab_parse.load_tasks(collab)}
    old_goals = {g["id"]: g for g in collab_parse.load_goals(collab, list(old.values()))}
    tasks = []
    for tv in v["tasks"]:
        t = dict(old.get(tv["id"]) or {"id": tv["id"], "title": tv["title"], "fields": [], "file": "", "archived": False})
        # head、flow 和旧结构的卡片同形：键是代码，值是代码或原文，看板按语言显示
        t.update({"title": t.get("title") or tv["title"], "state": tv["state"], "holder": tv["holder"] or "",
                  "goal": tv["goal"] or "", "stage": tv["stage"], "cls": TASK_CLS.get(tv["state"], "todo"),
                  "head": {"state": tv["state"], "executor": tv["executor"] or "", "reviewer": tv["reviewer"] or "", "goal": tv["goal"] or "—"}})
        t["flow"] = [{"time": flow.short_time(r.get("time", "")), "state": r.get("to_state", ""), "from": r.get("from", ""), "to": r.get("to", ""),
                      "note": r.get("note", ""), "edge": r["edge"], "result": r.get("result") or ""}
                     for r in flow.proj_rows(proj, tv["id"])]
        tasks.append(t)
    goals = []
    for gv in v["goals"]:
        g = dict(old_goals.get(gv["id"]) or {"id": gv["id"], "fields": [], "file": "", "archived": False, "head": {}})
        head = head_codes(g.get("head") or {})
        head["state"] = gv["state"]
        head["workdir"] = gv["workdir"]
        g.update({"title": g.get("title") or gv["title"], "state": gv["state"], "head": head, "archived": g.get("archived", False),
                  "idea": gv["draft_stage"], "files": gv["files"], "questions": gv["open_questions"]})  # 起草阶段：想法/讨论/方案，不在起草是 None；文件：讨论、方案的路径（归档后在归档/目标/下）
        g["stages"] = [{"no": s["order"], "seat": s["name"], "who": s["people"], "output": s["output"], "cond": s["pass_condition"],
                        "tasks": s["tasks"], "missing": [], "status": STAGE_STATUS.get(s["state"], s["state"])} for s in gv["stages"]]
        cur = next((s for s in g["stages"] if s["status"] != StageStatus.PASSED), None)
        g["current"] = cur["no"] if cur else None
        goals.append(g)
    return tasks, goals, v


def issue_archived(root: Path) -> set:
    d = root / P.COLLAB / P.ARCHIVE / P.ISSUES
    return {re.match(r"I\d+", f.name).group(0) for f in d.glob("I*.md")} if d.is_dir() else set()


def flow_issue_rows(root: Path, view: Optional[Dict[str, Any]] = None, runs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """新结构项目的议题面板：只放结论（状态、所属目标、与会、总结、裁决）和谁在思考；发言在对话页。"""
    v = view or flow.view(flow.Project(root))
    arch = issue_archived(root)
    live = [r for r in (runs if runs is not None else parse_runs(root / P.COLLAB)) if r.get("status") == RunStatus.RUNNING]
    out = []
    for i in v["issues"]:
        last = i["messages"][-1] if i["messages"] else None
        out.append({"id": i["id"], "title": i["title"], "stage": i["state"], "flow": True, "archived": i["id"] in arch,
                    "type": i["type"], "goal": i["goal"] or "", "holder": i["holder"] or "",
                    "attendees": i["attendees"], "summary": i["summary"], "ruling": i["ruling"], "count": i["post_count"],
                    "last": {"who": last["from"], "time": last.get("time", ""), "private": bool(last.get("private")),
                             "text": "" if last.get("private") else flow.first_line(last.get("body", "") or "[PASS]")} if last else None,
                    "thinking": sorted({r["member"] for r in live if r.get("task") == i["id"]})})
    return out


def meet_data(p: Dict[str, Any], iid: str) -> Optional[Dict[str, Any]]:
    """朝会页：这个议题的全部消息（总裁能看私下），与会、谁在思考；左栏是本项目的议题列表。"""
    root = Path(p["root"])
    v = flow.view(flow.Project(root))
    issue = next((i for i in v["issues"] if i["id"] == iid), None)
    if not issue:
        return None
    runs = parse_runs(root / P.COLLAB)
    goal = next((g for g in v["goals"] if g["id"] == issue["goal"]), None)
    return {"project": {"id": p["id"], "name": p["name"]}, "issue": issue,
            "goal": {"id": goal["id"], "title": goal["title"], "state": goal["state"]} if goal else None,
            "rooms": flow_issue_rows(root, v, runs),
            "thinking": sorted({r["member"] for r in runs if r.get("status") == RunStatus.RUNNING and r.get("task") == iid}),
            "runs": [run_view(r, root) for r in runs if r.get("task") == iid],
            "pool": team_pool(flow.Project(root)),
            "ready": read_ready(root, iid),
            "titles": v.get("titles", {}),
            "lang": flow.i18n.project_lang(root), "names": project_names(root),
            "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds")}


def read_ready(root: Path, iid: str) -> Dict[str, Any]:
    """总管搭会议室时的启动检查结果（dispatch.py room / ready 写的 <议题>.ready.txt）。"""
    f = root / P.COLLAB / RUNS_DIR / f"{iid}{P.READY_SUFFIX}"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def goal_post(p: Dict[str, Any], gid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """总裁在项目页对框架的动作：批准、退回、提意见。写一条事件（flow.record，和命令行同一套检查）。"""
    act = body.get("action")
    if act not in GOAL_ACTIONS:
        raise flow.hard(flow.T("srv.bad_action", act=act))
    proj = flow.Project(Path(p["root"]))
    text = (body.get("text") or "").strip()
    a: Dict[str, Any] = {"from": flow.BOSS, "writer": Writer.BOARD}
    obj = gid
    if act == E.APPROVE:
        if body.get("version") is None:
            raise flow.hard(flow.T("srv.need_version"))
        a.update(plan_version=int(body["version"]), basis=flow.approve_basis(int(body["version"]), text))
    else:
        if not text:
            raise flow.hard(flow.T("srv.need_text"))
        a["note"] = text
    if act == E.COMMENT and body.get("task"):
        obj = str(body["task"])
        states, _, _ = flow.replay_all(proj)
        if (states.get(obj) or {}).get("goal") != gid:
            raise flow.hard(flow.T("srv.not_goal_task", obj=obj, goal=gid))
    ev, _ = flow.record(proj, obj, act, a)
    return {"ok": True, "seq": ev.get("seq")}


def meet_post(p: Dict[str, Any], iid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """总裁在朝会页的动作：写一条事件（flow.record，和命令行同一套检查），再按需后台叫醒成员。"""
    act = body.get("action")
    if act not in MEET_ACTIONS:
        raise flow.hard(flow.T("srv.bad_action", act=act))
    root = Path(p["root"])
    proj = flow.Project(root)
    text = (body.get("text") or "").strip()
    a: Dict[str, Any] = {"from": flow.BOSS, "writer": Writer.BOARD}
    if act == E.POST:
        states, _, _ = flow.replay_all(proj)
        st = states.get(iid) or {}
        allowed = {flow.LEAD} | {x["member"] for x in st.get("attendees", [])}
        called = []
        for w in flow.MENTION_RE.findall(text):
            x = proj.actor(w)
            if x in allowed and x not in called:
                called.append(x)
        a.update(body=text, mentions=called, private=bool(body.get("private")), type=body.get("type") or None)
    elif act == MeetAction.REDELIVER:
        return redeliver(proj, iid, str(body.get("member") or ""))
    elif act == MeetAction.ADD:
        return add_attendees(proj, iid, body.get("members") or [], str(body.get("view") or ""))
    elif act in (MeetAction.STOP, MeetAction.WRAP):
        return stop_or_wrap(proj, iid, act, str(body.get("member") or ""))
    elif act == E.RULE:
        a.update(basis=flow.T("srv.owner_said", text=text), note=text)
    elif act in (E.CONTINUE_DISCUSSION, E.CANCEL):
        a.update(note=text or (flow.T("srv.continue_note") if act == E.CONTINUE_DISCUSSION else ""))
    ev, _ = flow.record(proj, iid, act, a)
    note, failed = "", False
    if act == E.POST:
        members = [w for w in ev.get("mentions", []) if w not in flow.MANAGERS]
        if members and not ev.get("private"):
            note, failed = wake_members(root, iid, members)
    return {"ok": True, "seq": ev["project_seq"], "note": note, "failed": failed}


def wake_members(root: Path, iid: str, members: List[str]) -> tuple:
    """后台叫醒（dispatch.py meet --wake --detach）；返回（给页面的一句话，是否失败）。"""
    r = subprocess.run([sys.executable, str(DISPATCH_PY), "--project", str(root), "meet", iid, "--wake", *members, "--detach"],
                       capture_output=True, text=True, timeout=60)
    msg = (r.stdout.strip() or r.stderr.strip()).splitlines()[-1:] or [""]
    if r.returncode == 0:
        return msg[0], False
    return flow.i18n.pack(flow.i18n.project_lang(root)).t("meet.wake_failed") + (r.stderr.strip() or r.stdout.strip())[-300:], True


def redeliver(proj: "flow.Project", iid: str, member: str) -> Dict[str, Any]:
    """补叫：叫醒上次没跑成的成员，带上它错过的发言（派活脚本按上一次成功的「读到」补）。留一条进展事件做记录。"""
    st = (flow.replay_all(proj)[0]).get(iid) or {}
    who = proj.actor(member)
    if not who or who not in [x["member"] for x in st.get("attendees", [])]:
        raise flow.hard(flow.T("ctx.not_attendee", member=member or "—", obj=iid))
    if st.get("state") != S.DISCUSSING:
        raise flow.hard(flow.T("srv.redeliver_state", obj=iid, state=flow.i18n.pack().st(st.get('state'))))
    ev, _ = flow.record(proj, iid, E.PROGRESS, {"from": flow.BOSS, "writer": Writer.BOARD, "note": flow.T("srv.redeliver_note", who=who)})
    note, failed = wake_members(proj.root, iid, [who])
    return {"ok": True, "seq": ev["project_seq"], "note": note, "failed": failed}


def _secs(iso: Any) -> Optional[float]:
    try:
        return (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return None


def run_state(r: Dict[str, Any]) -> str:
    """页面上的状态：启动中 / 思考 / 调用工具 / 正在写回复 / 疑似卡住 / 失败 / 已停止 / 完成。"""
    st = r.get("status")
    if st == RunStatus.RUNNING:
        quiet = _secs(r.get("last_at") or r.get("started"))
        if quiet is not None and quiet > STALL_SECONDS:
            return RunPhase.STALLED
        ph = r.get("phase")
        return ph if ph in (RunPhase.STARTING, RunPhase.THINKING, RunPhase.TOOL, RunPhase.WRITING) else (
            RunPhase.THINKING if r.get("last_at") else RunPhase.STARTING)  # 旧记录没有阶段
    return {RunStatus.DONE: RunPhase.DONE, RunStatus.FAILED: RunPhase.FAILED, RunStatus.LOST: RunPhase.FAILED,
            RunStatus.STOPPED: RunPhase.STOPPED}.get(st, st or "")


def run_view(r: Dict[str, Any], root: Path) -> Dict[str, Any]:
    out = {k: r.get(k) for k in ("run", "member", "seat", "status", "started", "ended", "error", "tokens", "steps",
                                 "last_action", "last_at", "phase", "stop_reason", "收尾")}
    out["state"] = run_state(r)
    started = _secs(r.get("started"))
    ended = _secs(r.get("ended")) if r.get("ended") else None
    out["elapsed"] = int(started - (ended or 0)) if started is not None else None
    out["quiet"] = int(_secs(r.get("last_at") or r.get("started")) or 0) if r.get("status") == RunStatus.RUNNING else None
    if r.get("status") == RunStatus.RUNNING:
        try:
            out["draft"] = (root / P.COLLAB / RUNS_DIR / f"{r['run']}.draft.txt").read_text(encoding="utf-8")[-6000:]
        except OSError:
            out["draft"] = ""
    return out


def stop_or_wrap(proj: "flow.Project", iid: str, act: str, member: str) -> Dict[str, Any]:
    """停止：停掉这位成员正在跑的运行，会话保留。收尾：先停止，再续接同一会话，要它用已有内容发言（后台进行）。"""
    st = (flow.replay_all(proj)[0]).get(iid) or {}
    who = proj.actor(member)
    if not who or who not in [x["member"] for x in st.get("attendees", [])]:
        raise flow.hard(flow.T("ctx.not_attendee", member=member or "—", obj=iid))
    if st.get("state") != S.DISCUSSING:
        raise flow.hard(flow.T("srv.action_state", obj=iid, state=flow.i18n.pack().st(st.get('state')), act=flow.i18n.pack().name("meet_action", act)))
    base = [sys.executable, str(DISPATCH_PY), "--project", str(proj.root)]
    if act == MeetAction.STOP:
        ev, _ = flow.record(proj, iid, E.PROGRESS, {"from": flow.BOSS, "writer": Writer.BOARD, "note": flow.T("srv.stop_note", who=who)})
        r = subprocess.run(base + ["stop-member", iid, who], capture_output=True, text=True, timeout=60)
        lines = (r.stdout.strip() or r.stderr.strip()).splitlines()
        return {"ok": True, "seq": ev["project_seq"], "note": lines[-1] if lines else ""}
    # 进展由 wrap 自己记：连点两次时第二次什么都不做，也不多记一条
    subprocess.Popen(base + ["wrap", iid, who, "--reason", flow.T("srv.wrap_reason"), "--page"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True, "note": flow.T("srv.wrap_note", who=who)}


def team_pool(proj: "flow.Project") -> List[Dict[str, Any]]:
    """可以拉进会议室的成员：花名册里、班子配置里「可用」为 ✓ 的命令行成员（有启动命令的）。"""
    team = flow.team_file()
    cfg = {}
    if team.exists():
        try:
            cfg = {m.get("dispatch_name"): m for m in team_mod.read(team).get("members", [])}  # 旧的中文键读的时候换成英文
        except (OSError, ValueError):
            cfg = {}
    out = []
    for m in proj.roster():
        c = cfg.get(m["dispatch_name"])
        if c is not None and not c.get("start_command"):
            continue
        avail = str((c or {}).get("available", "✓"))
        out.append({"name": m["dispatch_name"], "title": m["name"], "ok": avail.startswith("✓"), "note": "" if avail.startswith("✓") else avail,
                    "model": (c or {}).get("model", "")})
    return out


def add_attendees(proj: "flow.Project", iid: str, members: List[Any], view_: str) -> Dict[str, Any]:
    """加人：把名单外的可用成员加进与会（记一条「变更」）。他不会被叫醒；总裁 @ 他时，他第一次发言能看到那句话之前的全部公开发言。"""
    st = (flow.replay_all(proj)[0]).get(iid) or {}
    if st.get("state") not in (S.DRAFT, S.DISCUSSING, S.CLOSING, S.PENDING_RULING):
        raise flow.hard(flow.T("srv.add_state", obj=iid, state=flow.i18n.pack().st(st.get('state'))))
    pool = {m["name"]: m for m in team_pool(proj)}
    have = [x["member"] for x in st.get("attendees", [])]
    add = []
    for name in members:
        who = proj.actor(str(name))
        if not who or who not in pool:
            raise flow.hard(flow.T("srv.not_in_team", name=name))
        if not pool[who]["ok"]:
            raise flow.hard(flow.T("srv.unavailable", who=who, why=pool[who]['note']))
        if who in have or who in add:
            raise flow.hard(flow.T("srv.already_in", who=who))
        add.append(who)
    if not add:
        raise flow.hard(flow.T("srv.no_member"))
    new = [{"member": x["member"], "view": x["view"]} for x in st["attendees"]] + [{"member": w, "view": view_.strip()} for w in add]
    ev, _ = flow.record(proj, iid, E.CHANGE, {"from": flow.BOSS, "writer": Writer.BOARD, "attendees": new, "changes": [flow.i18n.pack().name("event_field", "attendees")],
                                            "note": flow.T("srv.add_note", who=flow.i18n.pack().join(add))})
    return {"ok": True, "seq": ev["project_seq"], "added": add}


def meetings() -> List[Dict[str, Any]]:
    """NOW 的朝会入口：各新结构项目里进行中和待裁决的议题，只读聚合。"""
    out = []
    for p in projects():
        root = Path(p["root"])
        if not (root / P.COLLAB / P.INTERNAL_FLOW).is_dir():
            continue
        try:
            rows = flow_issue_rows(root)
        except Exception:
            continue
        for i in rows:
            if i["stage"] in (S.DISCUSSING, S.CLOSING, S.PENDING_RULING) and not i["archived"]:
                out.append({"project": p["name"], "pid": p["id"], **{k: i[k] for k in ("id", "title", "stage", "type", "goal", "thinking")}})
    return out


def project_clock(collab: Path) -> Optional[str]:
    """演示案例停在剧情里的某一刻（collab/内部/流程/时钟.json）；看板上的「多久前」「已持有」按它算，没有就用真实时间。"""
    f = collab / P.INTERNAL_PLANS / P.CLOCK

    try:
        return json.loads(f.read_text(encoding="utf-8"))["now"] if f.exists() else None
    except (OSError, ValueError, KeyError):
        return None


def project_data(p: Dict[str, Any]) -> Dict[str, Any]:
    mod = load_build()
    progress = Path(p["progress"])
    collab = progress.parent
    text = collab_parse.strip_comments(progress.read_text(encoding="utf-8"))
    secs = mod.sections(text)
    name = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), p["name"])

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
    if (collab / P.INTERNAL_FLOW).is_dir():
        tasks, goals, view = flow_cards(collab, Path(p["root"]))
    else:
        tasks = collab_parse.load_tasks(collab)
        goals = collab_parse.load_goals(collab, tasks)
    by_id = {t["id"]: t for t in tasks}
    _, task_lines = mod.find_section(secs, Section.TASKS)
    done_line = next((l for l in task_lines if l.startswith(("已完成", "Done:"))), "")
    decisions = [mod.inline(re.sub(r"^\s*-\s*", "", l.strip()), collab) for t in ("决议", Section.ACTIVE_DECISIONS)
                 for l in mod.find_section(secs, t)[1] if re.match(r"\s*-?\s*D\d+", l)]
    runs = parse_runs(collab)
    issues = flow_issue_rows(Path(p["root"]), view, runs) if view else collab_parse.load_issues(collab)
    archived = sum(1 for t in tasks if t["archived"])
    try:
        checked = collab_check.check(Path(p["root"]))
    except Exception as e:  # 校验器出错不影响看板
        checked = [{"level": "warn", "file": "", "line": None, "msg": flow.T("srv.checker_failed", e=e)}]
    return {
        "id": p["id"], "name": name, "root": p["root"],
        "progressHref": "file://" + quote(str(progress)),
        "meta": meta_codes(text),
        "lang": flow.i18n.project_lang(p["root"]),
        "names": project_names(Path(p["root"])),
        "pendingItems": pending_items(view) if view else None,
        "next": " ".join(plain(Section.NEXT)),
        "status": bullets(Section.STATUS),
        "pending": [mod.inline(l[2:], collab) for l in flow.decision_lines(view)] if view else plain(Section.BLOCKERS),
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


def project_names(root: Path) -> Dict[str, Any]:
    """项目 collab/config.json 的 names（和 sections、text）：覆盖看板上的显示名（演示用它换明朝叫法）。"""
    try:
        cfg = json.loads((root / P.COLLAB / P.CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: cfg[k] for k in ("names", "sections", "text") if cfg.get(k)}


def pending_items(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """「待你决定」给看板的结构化一份：类型、说明、方案、建议、提出者都是代码或原文，看板按语言拼。"""
    out = [{"id": d["id"], "type": d["type"], "note": d.get("note", ""), "options": d.get("options", ""),
            "recommendation": d.get("recommendation", ""), "by": d.get("raised_by", ""), "reviews": d.get("reviews", [])}
           for d in view["decisions"]]
    out += [{"id": c["object"], "type": "comment", "note": c["note"], "options": "", "recommendation": "", "by": "owner", "reviews": []}
            for g in view["goals"] for c in g["comments"]]
    return out


def archive_data(p: Dict[str, Any]) -> Dict[str, Any]:
    """归档页：只有归档的目标、任务、议题和它们的派活记录；打开时加载一次，不轮询。"""
    mod = load_build()
    progress = Path(p["progress"])
    collab = progress.parent
    text = collab_parse.strip_comments(progress.read_text(encoding="utf-8"))
    name = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), p["name"])
    view = None
    runs = parse_runs(collab)
    if (collab / P.INTERNAL_FLOW).is_dir():  # 新结构：和项目页一样取自 flow.py 的视图模型，只读
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
        "lang": flow.i18n.project_lang(p["root"]), "names": project_names(Path(p["root"])),
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
    src = flow.team_file()
    team = team_mod.read(src) if src.exists() else {}
    members = [{k: v for k, v in m.items() if k not in ("start_command", "resume_command", "parser")} for m in team.get("members", [])]
    names = {m.get("dispatch_name") for m in members}
    stats = {n: {"runs": 0, "total": 0, "cached": 0, "last": "", "running": [], "holding": []} for n in names}
    for p in projects():
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
            if r.get("status") == RunStatus.RUNNING:
                st["running"].append({"project": p["name"], "pid": p["id"], "run": r.get("run"), "started": r.get("started")})
        if (collab / P.INTERNAL_FLOW).is_dir():
            try:
                v = flow.view(flow.Project(Path(p["root"])))
            except Exception:
                continue
            titles = {t["id"]: t["title"] for t in v["tasks"]}
            for c in v["current"]:
                st = stats.get(c.get("to"))
                if st:
                    st["holding"].append({"project": p["name"], "pid": p["id"], "task": c["object"],
                                          "title": titles.get(c["object"], ""), "state": c["state"]})
    return {
        "source": str(src), "exists": src.exists(),
        "members": members, "stats": stats,
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def talent_data() -> Dict[str, Any]:
    """人才市场：读静态的 ~/.collab-team/人才.json，没有时用工具包示例；附上班子成员名，标出谁已在班子里。"""
    src = flow.team_file("talent")
    sample = not src.exists()
    if sample:
        src = TALENT_EXAMPLE
    talent = team_mod.read(src) if src.exists() else {}
    team_file = flow.team_file()
    team = team_mod.read(team_file) if team_file.exists() else {}
    return {"sample": sample, "source": str(src), "note": talent.get("note", ""), "items": talent.get("talent", []),
            "members": [m.get("name") for m in team.get("members", [])]}


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
PROXY_HEADERS = ("Tailscale-User-Login", "X-Forwarded-For", "X-Forwarded-Host", "Forwarded")


def is_remote(headers, client_ip: str = "127.0.0.1") -> bool:
    """请求是否来自本机以外：不是回环地址、带代理头（tailscale serve 会加），或 Host 不是本机名。"""
    if client_ip not in ("127.0.0.1", "::1"):
        return True
    if any(headers.get(h) for h in PROXY_HEADERS):
        return True
    host = (headers.get("Host") or "").strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return bool(host) and host not in LOCAL_HOSTS


def vocab_js(lang: str = "", remote: bool = False) -> str:
    """board/static/vocab.js：window.V（标识）、window.I18N_PACKS（两种语言包）、window.BOARD_LANG（默认语言）；
    选哪种语言、t()、中 / EN 切换在 i18n.js。window.I18N 先给默认语言，没加载 i18n.js 的页面也能用 N()。"""
    lang = lang if lang in flow.i18n.LANGS else BOARD_LANG
    packs = {x: flow.i18n.Pack(x).text_dict() for x in flow.i18n.LANGS}
    return (vocab.as_js() + "window.I18N_PACKS = window.I18N_PACKS || " + json.dumps(packs, ensure_ascii=False, sort_keys=True) + ";\n"
            f"window.BOARD_LANG = window.BOARD_LANG || {json.dumps(lang)};\n"
            f"window.BOARD_REMOTE = {json.dumps(bool(remote))};\n"
            "window.I18N = window.I18N || window.I18N_PACKS[window.BOARD_LANG];\n"
            "window.N = (kind, code) => (code == null ? \"\" : ((window.I18N.names[kind] || {})[code] || code));\n"
            "window.WHO = (x) => (x ? ((window.I18N.names.seat || {})[x] || (x === \"none\" ? window.I18N.names.seat_class.none : x)) : \"\");\n")


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "board/1"

    def log_message(self, fmt, *args):
        if ARGS.verbose:
            super().log_message(fmt, *args)

    def send(self, code: int, body: bytes, ctype: str, csp: bool = True, tag_src: Optional[bytes] = None,
             extra: Optional[Dict[str, str]] = None) -> None:
        """写响应。200 带弱 ETag（默认按 body 算，JSON 去掉 generated 再算）：内容没变时回 304，不重传；
        Cache-Control 用 no-cache，浏览器每次都来问，内容变了立刻拿到新的。客户端支持 gzip 时压缩大的文本响应。"""
        etag = None
        if code == 200 and self.command == "GET":
            etag = 'W/"' + hashlib.sha1(body if tag_src is None else tag_src).hexdigest()[:20] + '"'
            if etag in [x.strip() for x in (self.headers.get("If-None-Match") or "").split(",")]:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Vary", "Accept-Encoding")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                return
        gz = (len(body) > 1024 and ctype.startswith(("text", "application/json"))
              and "gzip" in (self.headers.get("Accept-Encoding") or ""))
        if gz:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if etag else "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if etag:
            self.send_header("ETag", etag)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp:
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def remote(self) -> bool:
        return is_remote(self.headers, self.client_address[0] if self.client_address else "")

    def json(self, data: Any, code: int = 200, extra: Optional[Dict[str, str]] = None) -> None:
        body, tag = encode(data, "generated")  # 生成时间每次都变，不算进 ETag
        self.send(code, body, "application/json", tag_src=tag, extra=extra)

    def events(self) -> None:
        """/api/events（SSE）：连上先推一次全部版本号，之后哪块变了就推 event: change（内容仍是全部版本号，漏收也能追上）；
        每 HEARTBEAT 秒一行注释作心跳。不压缩，每条立即写出；超过 SSE_MAX 个连接回 503，前端退回短轮询 /api/versions。"""
        with SSE_LOCK:
            if SSE_OPEN[0] >= SSE_MAX:
                return self.send(503, b"too many event streams", "text/plain")
            SSE_OPEN[0] += 1
        try:
            WATCH.start()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")  # 让中间的代理不要攒着
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            sent, last = -1, time.monotonic()
            while not WATCH.stopped.is_set():
                with WATCH.cond:
                    if WATCH.seq == sent:
                        WATCH.cond.wait(max(0.0, HEARTBEAT - (time.monotonic() - last)))
                    seq, versions = WATCH.seq, dict(WATCH.versions)
                if seq != sent:
                    sent = seq
                    self.wfile.write(b"event: change\ndata: " + json.dumps(versions, ensure_ascii=False).encode("utf-8") + b"\n\n")
                elif time.monotonic() - last >= HEARTBEAT:
                    self.wfile.write(b": ping\n\n")
                else:
                    continue
                self.wfile.flush()
                last = time.monotonic()
        except OSError:  # 设备断开（BrokenPipe、ConnectionReset）
            pass
        finally:
            with SSE_LOCK:
                SSE_OPEN[0] -= 1

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path in ("/", "/now") and now_enabled():
                return self.send(200, now_bundle()["html"], "text/html", csp=False)
            if path == "/api/now":  # NOW 数据（不含模块 css、js），带外壳指纹；ETag 不算生成时间
                if not now_enabled():
                    return self.json({"error": "NOW not enabled"}, 404)
                b = now_bundle()
                return self.send(200, b["json"], "application/json", tag_src=b["tag"],
                                 extra={"X-Board-Shell": b["shell"], "X-Board-Version": str(WATCH.versions.get("now", ""))})
            if path == "/api/events":
                return self.events()
            if path == "/sw.js":  # 作用域要覆盖全站，所以放根路径
                return self.send(200, sw_js(), "text/javascript")
            if path == "/manifest.webmanifest":
                return self.send(200, manifest(), "application/manifest+json")
            if ROOT_ICON.fullmatch(path):  # iOS 加到主屏、打开主屏 app 时不管页面写了什么，都会去根路径找这几个图标
                return self.send(200, (STATIC / "icon-180.png").read_bytes(), "image/png")
            if path == "/favicon.ico":
                return self.send(200, (STATIC / "icon-192.png").read_bytes(), "image/png")
            if path == "/api/versions":  # 推送不通时的短轮询：各块版本号，几十字节
                WATCH.start()
                seq, versions = WATCH.snapshot()
                return self.json({"versions": versions, "roundMs": round(WATCH.round_ms, 2), "interval": WATCH.interval})
            if path in ("/", "/now", "/projects"):
                return self.send(200, (STATIC / "projects.html").read_bytes(), "text/html")
            if path == "/api/home":
                return self.json({"now": now_enabled()})
            if path == "/api/projects":  # 按 NOW 任务表、登记表和各项目账本的指纹缓存；只有运行记录变了时最多 RUN_MIN 秒重算一次
                return self.json(projects())
            if path == "/api/team":
                return self.json(memo("team", all_sigs, team_data)[0])
            if path == "/team":
                return self.send(200, (STATIC / "team.html").read_bytes(), "text/html")
            if path == "/api/talent":  # 人才页看块 team（班子.json、人才.json）：版本号交给 live.seen
                return self.json(talent_data(), extra={"X-Board-Version": str(WATCH.versions.get("team", ""))})
            if path == "/talent":
                return self.send(200, (STATIC / "talent.html").read_bytes(), "text/html")
            if path == "/api/meetings":
                return self.json(memo("meetings", all_sigs, meetings)[0])
            m = re.fullmatch(r"/api/p/([0-9a-f]{8})/meet/(I\d+)", path)
            if m:
                ver = str(WATCH.versions.get("p:" + m.group(1), ""))  # 先取版本号再算数据：取到旧的只会让页面多拉一次
                p = find_project(m.group(1))
                data, rver = None, ""
                if p and (Path(p["root"]) / P.COLLAB / P.INTERNAL_FLOW).is_dir():
                    data, rver = memo(f"m:{p['id']}:{m.group(2)}", project_sigs(p), lambda: meet_data(p, m.group(2)), "r:" + p["id"])
                return (self.json(data, extra={"X-Board-Version": ver, "X-Board-Run-Version": rver}) if data
                        else self.json({"error": "找不到这个议题"}, 404))
            if re.fullmatch(r"/p/[0-9a-f]{8}/meet/I\d+", path):
                return self.send(200, (STATIC / "meet.html").read_bytes(), "text/html")
            m = re.fullmatch(r"/api/p/([0-9a-f]{8})(/archive)?", path)
            if m:
                p = find_project(m.group(1))
                if not p:
                    return self.json({"error": "找不到项目"}, 404)
                ver = str(WATCH.versions.get("p:" + p["id"], ""))  # 页面交给 live.seen，推送来同一版本就不再拉
                body, tag, rver = project_cached(p, bool(m.group(2)))
                return self.send(200, body, "application/json", tag_src=tag, extra={"X-Board-Version": ver, "X-Board-Run-Version": rver})
            if re.fullmatch(r"/p/[0-9a-f]{8}(/archive)?", path):
                return self.send(200, (STATIC / "project.html").read_bytes(), "text/html")
            if path == "/static/vocab.js":  # 页面共用的标识（core/vocab.py）和语言包（i18n/<lang>.json）
                return self.send(200, vocab_js(remote=self.remote()).encode("utf-8"), "text/javascript")
            if path == "/api/i18n":  # 一种语言的整份语言包：?lang=zh|en
                lang = (parse_qs(urlparse(self.path).query).get("lang") or [BOARD_LANG])[0]
                return self.json(flow.i18n.Pack(lang if lang in flow.i18n.LANGS else BOARD_LANG).text_dict())
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
        if self.remote():  # 远程设备上点「打开」会在 Mac 上弹窗，没有意义也不安全
            return self.json({"error": "remote"}, 403)
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
        p = find_project(pid)
        if not p or not (Path(p["root"]) / P.COLLAB / P.INTERNAL_FLOW).is_dir():
            return self.json({"error": "找不到项目"}, 404)
        try:
            return self.json((handler or meet_post)(p, iid, body))
        except flow.FlowError as e:
            return self.json({"error": e.msg, "kind": e.kind}, 400)
        except Exception as e:
            return self.json({"error": f"出错：{e}"}, 500)


def main() -> None:
    global ARGS
    M = flow.i18n.pack(registry.kit_lang(flow.TOOLKIT)).t  # 命令行提示用工具包的默认语言
    ap = argparse.ArgumentParser(description=M("server.description"))
    ap.add_argument("--port", type=int, default=3100)
    ap.add_argument("--now-dir", default=os.environ.get("COLLAB_NOW_DIR") or default_now_dir(),
                    help=M("server.help.now_dir"))
    ap.add_argument("--project", action="append", help=M("server.help.project"))
    ap.add_argument("--verbose", action="store_true")
    ARGS = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    WATCH.start()
    print(M("server.started", port=ARGS.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
