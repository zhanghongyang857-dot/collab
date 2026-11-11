#!/usr/bin/env python3
"""流转工具：任务、目标流转的唯一写入口、唯一投影和渲染。

数据：骨架（core/skeletons/*.json，项目可在 collab/内部/流程/ 覆盖）+ 事件（collab/内部/流转/<编号>.jsonl，只追加）。
投影：回放事件得到状态、持有人、阶段进度和视图模型；同样的输入得到逐字节相同的输出。
呈现：卡片、PROGRESS 的生成块和看板都只用视图模型，不读事件、不做推断。

用法（在项目目录或其子目录里运行，或用 --project 指定）：
  flow.py 建立 任务 --目标 G001 --阶段 1 --标题 "…" --依据 "…"     新建任务卡并写「建立」（别名 new）
  flow.py 建立 任务 --标题 "…" --依据 "总裁原话"                    零散任务
  flow.py 建立 目标 --类型 调研 --标题 "…" --依据 "总裁原话"          新建目标卡和工作目录 work/<目标卡名>/
  flow.py 记 <编号> <边> [--结果] [--给] [--证据 …] --说明 "…"       校验后追加一条事件（别名 log）
  flow.py 可走 <编号> [--作为 成员]                                列出当前能走的边和完整命令（别名 next）
  flow.py 上下文 <编号> --给 <成员> [--全] [--清单]                 打印成员的上下文包（别名 context）
  flow.py 渲染                                                    由视图模型重写所有生成块（别名 render）
  flow.py 检查 [--json]                                           完整性和一致性检查（别名 check）
  flow.py 导出 [--json]                                           输出视图模型（别名 export）

发起人用 --作为 指定（默认取环境变量 COLLAB_ACTOR，否则「总管」）；总管代总裁记时写 --作为 总裁 并带 --依据 原话。
只用 Python 标准库。
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths as P  # noqa: E402
from vocab import (Block, Category, Diff, DraftStage, Edge as E, Field, GoalType, IssueType, Kind, Pending,  # noqa: E402
                   Result, Role, Seat, SeatClass, Section, Skel, Speech, StageStatus, StageType, State as S, Writer, Ctx, NONE)
import i18n  # noqa: E402
import team as team_mod  # noqa: E402
TOOLKIT = HERE.parent  # 开发时是 src/，本机发布后是 NOW/系统/
SKEL_DIR = HERE / "skeletons"


def skel_file(name: str) -> str:
    """骨架在工具包里的文件名（不含 .json）：骨架名就是文件名（task、goal-dev…）。"""
    return name
FLOW_PY = Path(__file__).resolve()


def team_dir() -> Path:
    """班子目录：环境变量 COLLAB_TEAM；没有时找工具包旁边的 班子/（本机发布在 NOW/系统/，班子在 NOW/班子/）；再没有用 ~/.collab-team。"""
    env = os.environ.get("COLLAB_TEAM")
    if env:
        return Path(env).expanduser()
    for name in (P.TEAM_DIR, P.LEGACY_TEAM_DIR):  # 没跑 init.sh migrate-now 的还叫 班子/
        beside = TOOLKIT.parent / name
        if beside.is_dir():
            return beside
    return Path("~/.collab-team").expanduser()


def team_file(name: str = "") -> Path:
    """班子目录里的 team.json（name 给 talent 时是 talent.json）；没迁移的还叫 班子.json、人才.json。"""
    new, old = (P.TALENT_JSON, P.LEGACY_TALENT_JSON) if name == "talent" else (P.TEAM_JSON, P.LEGACY_TEAM_JSON)
    d = team_dir()
    return d / new if (d / new).exists() or not (d / old).exists() else d / old

EVENT_V = 2  # 事件格式版本：v2 键和代码取值都是英文；v1（中文）要先 init.sh migrate
FORMAT = 3  # 账本格式版本（collab/config.json 的 format）
VIEW = "view@3"
BOSS, LEAD = Seat.OWNER, Seat.LEAD
MANAGERS = (BOSS, LEAD)
BOSS_ALIASES = (Seat.OWNER, "总裁", "Owner", "用户", "本人")
LEAD_ALIASES = (Seat.LEAD, "总管", "Lead")
SPECIAL = (E.CHANGE, E.PROGRESS, E.CORRECTION, E.COMMENT, E.DRAFT_STAGE)
REOPEN = (E.REOPEN, E.REDRAFT)  # 终止状态唯一能走的边：通过后重开，撤下的草稿编号重拟
DRAFT_STAGES = (DraftStage.IDEA, DraftStage.DISCUSSION, DraftStage.PROPOSAL)  # 起草状态下的阶段，只由「起草阶段」事件回放得出，默认第一个
def approve_basis(version: int, note: str = "") -> str:
    """看板批准写的依据；带批注时后面接「：批注」。"""
    L = i18n.pack()
    return L.t("flow.approve_basis", version=version) + (L.t("sep.colon") + note if note else "")
RETURN_EDGES = (E.REJECT, E.RETURN)


def T(key: str, **kw: Any) -> str:
    """当前项目语言的一句提示（没有 proj.L 在手边时用）。"""
    return i18n.pack().t(key, **kw)


def is_quote(basis: Any, goal: Optional[str]) -> bool:
    """依据是不是原话：有内容，且不是框架自动写的默认依据「<目标> 框架」。"""
    b = str(basis or "").strip()
    return bool(b) and b not in {i18n.pack(x).t("flow.plan_basis", goal=goal) for x in i18n.LANGS}


def is_boss_return(r: Dict[str, Any]) -> bool:
    """总裁的退回：任务上总裁判需补充或未通过，目标上的打回、退回；要带依据。"""
    return r.get("from") == BOSS and bool(str(r.get("basis") or "").strip()) and (
        r.get("edge") in RETURN_EDGES or (r.get("edge") == E.REVIEW and r.get("result") in (Result.NEEDS_MORE, Result.FAIL)))
# 议题的消息事件：不改状态、不改持有人（方案 03 第 10 节）
MESSAGES = (E.POST, E.PASS)
# 改变持有人的边：除接手（持有人不变）、特殊事件和消息事件外都改
KEEP_HOLDER = (E.PICK_UP,) + SPECIAL + MESSAGES
ID_RE = r"(?:G\d+-T\d+|G\d+|T\d+|I\d+)"
BLOCK_RE = re.compile(r"<!-- flow:(\S+) (\S+) (\S+) sha=([0-9a-f]+) -->\n(.*?)<!-- /flow -->", re.S)
FIELD_ORDER = ["v", "seq", "project_seq", "time", "object", "skeleton", "edge", "result", "from", "to", "from_state", "to_state",
               "writer", "run", "session", "goal", "stage", "plan", "key", "title", "type", "planned_executor", "planned_reviewer", "depends_on", "attendees", "mentions", "private", "body", "evidence", "note", "basis", "options", "recommendation",
               "changes", "diff", "plan_version", "approved_plan", "diff_reason", "correct", "override"]


class FlowError(Exception):
    """kind："hard" 硬错误（不能越过）/ "rule" 规则错误（总管、总裁可带理由越过）。"""

    def __init__(self, kind: str, msg: str):
        super().__init__(msg)
        self.kind = kind
        self.msg = msg


def hard(msg: str) -> FlowError:
    return FlowError("hard", msg)


def rule(msg: str) -> FlowError:
    return FlowError("rule", msg)


# ---------- 时间、文件 ----------

def now_dt() -> dt.datetime:
    fixed = os.environ.get("FLOW_NOW")  # 测试用：固定当前时间
    if fixed:
        return dt.datetime.fromisoformat(fixed)
    return dt.datetime.now().astimezone().replace(microsecond=0)


def project_now(proj: "Project") -> dt.datetime:
    """检查用的「现在」：FLOW_NOW > 项目的 collab/内部/流程/时钟.json（演示案例用，停在剧情里的某一刻）> 真实时间。"""
    if os.environ.get("FLOW_NOW"):
        return now_dt()
    clock = proj.proc_dir / P.CLOCK
    if clock.exists():
        return dt.datetime.fromisoformat(json.loads(clock.read_text(encoding="utf-8"))["now"])
    return now_dt()


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def short_time(s: str) -> str:
    return s[5:16].replace("T", " ") if s else ""


def sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def write_if_changed(path: Path, text: str) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def cell(s: Any, limit: int = 0) -> str:
    s = " ".join(str(s or "").split()).replace("|", "／")
    return s if not limit or len(s) <= limit else s[: limit - 1] + "…"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1)


# ---------- 项目 ----------

class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.collab = self.root / P.COLLAB
        self.flow_dir = self.collab / P.INTERNAL_FLOW
        self.proc_dir = self.collab / P.INTERNAL_PLANS
        self.small = (self.collab / P.TASKS_MD).exists() and not (self.collab / P.TASKS).is_dir()
        self._skel: Dict[str, Dict[str, Any]] = {}
        self._roster: Optional[List[Dict[str, Any]]] = None
        cfg_file = self.collab / P.CONFIG
        try:
            self.config = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        except ValueError:
            self.config = {}
        self.lang = self.config.get("lang") if self.config.get("lang") in i18n.LANGS else i18n.DEFAULT
        self.L = i18n.Pack(self.lang)  # 文件用语言包的中性叫法；config.json 的 names（演示的明朝叫法）只用在看板上
        i18n.set_current(self.lang)

    def needs_migration(self) -> bool:
        """旧格式项目：没有 collab/config.json，或 format 不是当前版本。"""
        return self.config.get("format") != FORMAT

    # 骨架：项目覆盖（collab/内部/流程/<中文名>.json）优先，再找工具包 skeletons/<英文名>.json；
    # 指定版本时找 collab/内部/流程/历史/<中文名>@<版本>.json 或 skeletons/history/<英文名>@<版本>.json
    def skeleton(self, name: str, version: Optional[int] = None) -> Dict[str, Any]:
        key = f"{name}@{version}"
        if key in self._skel:
            return self._skel[key]
        cands = [self.proc_dir / f"{name}.json", SKEL_DIR / f"{skel_file(name)}.json"]
        found = None
        for c in cands:
            if c.exists():
                data = json.loads(c.read_text(encoding="utf-8"))
                if version is None or data.get("version") == version:
                    found = data
                    break
        if found is None and version is not None:
            for c in (self.proc_dir / P.HISTORY / f"{name}@{version}.json", SKEL_DIR / "history" / f"{skel_file(name)}@{version}.json"):
                if c.exists():
                    found = json.loads(c.read_text(encoding="utf-8"))
                    break
        if found is None:
            raise hard(i18n.pack().t("flow.no_skeleton", name=name + (f"@{version}" if version else "")))
        self._skel[key] = found
        return found

    def roster(self) -> List[Dict[str, Any]]:
        if self._roster is None:
            out: List[Dict[str, Any]] = []
            src = self.proc_dir / P.ROSTER
            if not src.exists():
                team = team_file()
                src = team if team.exists() else src
            if src.exists():
                data = team_mod.read(src)  # 旧文件的中文键读的时候换成英文
                for m in data.get("members", []):
                    name = m.get("dispatch_name") or m.get("name")
                    if not name:
                        continue
                    keys = {str(x).lower() for x in [name, m.get("name", "")] + list(m.get("aliases", [])) if x}
                    out.append({"dispatch_name": name, "name": m.get("name", name), "keys": keys})
            self._roster = out
        return self._roster

    def actor(self, name: Optional[str]) -> Optional[str]:
        n = (name or "").strip()
        if not n:
            return None
        if n in BOSS_ALIASES:
            return BOSS
        if n in LEAD_ALIASES:
            return LEAD
        low = n.lower()
        for m in self.roster():
            if low in m["keys"]:
                return m["dispatch_name"]
        return None

    def is_member(self, name: Optional[str]) -> bool:
        return bool(name) and any(m["dispatch_name"] == name for m in self.roster())

    # 事件
    def event_files(self) -> List[Path]:
        return sorted(self.flow_dir.glob("*.jsonl")) if self.flow_dir.is_dir() else []

    def load_events(self) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
        evs: Dict[str, List[Dict[str, Any]]] = {}
        probs: List[Dict[str, Any]] = []
        for f in self.event_files():
            obj = f.stem
            rows = []
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    probs.append(issue("error", self.rel(f), n, self.L.t("flow.bad_json_line")))
                    continue
                if row.get("v") != EVENT_V:
                    probs.append(issue("error", self.rel(f), n, self.L.t("flow.old_event_line", v=row.get('v'))))
                    continue
                rows.append(row)
            evs[obj] = rows
        return evs, probs

    def rel(self, p: Path) -> str:
        try:
            return str(p.resolve().relative_to(self.root))
        except ValueError:
            return str(p)

    # 卡片位置
    def card_files(self) -> List[Path]:
        c = self.collab
        out = []
        for single in (P.TASKS_MD, P.GOALS_MD, P.ARCHIVE_MD):
            if (c / single).exists():
                out.append(c / single)
        for d in (c / P.TASKS, c / P.GOALS, c / P.ISSUES, c / P.ARCHIVE / P.TASKS, c / P.ARCHIVE / P.GOALS, c / P.ARCHIVE / P.ISSUES):
            if d.is_dir():
                out += sorted(x for x in d.glob("*.md") if not x.name.startswith("_"))
        return out


def issue(level: str, file: str, line: Optional[int], msg: str) -> Dict[str, Any]:
    return {"level": level, "file": file, "line": line, "msg": msg}


def find_project(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / P.COLLAB).is_dir() and ((p / P.COLLAB / P.PROGRESS).exists() or (p / P.COLLAB / P.INTERNAL_FLOW).is_dir()):
            return p
    sys.exit(i18n.pack().t("flow.no_project", start=start))


def dev_write_refusal(root: Path) -> Optional[str]:
    """开发版工具包不能写自己仓库的账本和模板：账本归发布版管，试新功能用 demo/ 或临时项目。发布版带 版本.txt，不受限。"""
    if (TOOLKIT / P.VERSION_TXT).exists():
        return None
    root = root.resolve()
    if root == TOOLKIT or TOOLKIT in root.parents or root in TOOLKIT.parents:
        return i18n.pack().t("flow.dev_refusal", kit=TOOLKIT, root=root)
    return None


@contextmanager
def locked(proj: Project):
    refusal = dev_write_refusal(proj.root)
    if refusal:
        raise hard(refusal)
    if proj.needs_migration():
        raise hard(proj.L.t("flow.needs_migration", root=proj.root, config=f"{P.COLLAB}/{P.CONFIG}", format=FORMAT))

    proj.flow_dir.mkdir(parents=True, exist_ok=True)
    with open(proj.flow_dir / ".lock", "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ---------- 回放 ----------

def kind_of(obj: str) -> str:
    """对象三类：目标、任务、议题；骨架文件和种类同名。"""
    if re.fullmatch(r"G\d+", obj):
        return Kind.GOAL
    return Kind.ISSUE if re.fullmatch(r"I\d+", obj) else Kind.TASK


def blank_state(obj: str) -> Dict[str, Any]:
    return {"id": obj, "kind": kind_of(obj), "state": S.NONE, "holder": None, "title": "", "goal": None, "stage": None, "plan": None,
            "type": None, "executor": None, "reviewer": None, "last_deliverer": None, "rework_by": None, "rework_count": 0,
            "before_escalation": None, "before_pause": None, "pass_valid": False, "self_reviewed": False, "stages": [], "basis": "",
            "draft_stage": DRAFT_STAGES[0], "key": None, "planned_executor": None, "planned_reviewer": None, "depends_on": [], "plan_version": 0, "approved_plan": None, "round_changes": [], "comments": [],
            "diff_reason": "", "events": [], "voided": [], "problems": [], "skeleton": None, "attendees": []}


def replay(obj: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    st = blank_state(obj)
    voided = {r.get("correct") for r in rows if r.get("edge") == E.CORRECTION}
    st["voided"] = sorted(x for x in voided if isinstance(x, int))
    for ev in rows:
        if ev.get("seq") in voided or ev.get("edge") == E.CORRECTION:
            continue
        apply_event(st, ev)
    return st


def apply_event(st: Dict[str, Any], ev: Dict[str, Any]) -> None:
    L = i18n.pack()
    edge = ev.get("edge")
    st["events"].append(ev)
    if edge in MESSAGES:
        return
    if edge == E.PROGRESS:
        return
    if edge == E.DRAFT_STAGE:
        st["draft_stage"] = ev.get("result") or st["draft_stage"]
        return
    if edge == E.COMMENT:
        st["comments"].append(ev)
        return
    if edge == E.CHANGE:
        if ev.get("attendees") is not None:
            st["attendees"] = ev["attendees"]
        if st["kind"] == Kind.TASK:
            for k in ("stage", "key", "title", "planned_executor", "planned_reviewer", "depends_on"):
                if ev.get(k) is not None:
                    st[k] = ev[k]
            return
        if ev.get("stage") is not None:
            st["stages"] = ev["stage"]
            st["diff_reason"] = st["diff_reason"] or ev.get("note", "")  # 改阶段的变更必带说明，算登记过的差异
        if ev.get("plan_version") is not None:
            st["plan_version"] = ev["plan_version"]
            st["round_changes"] = ev.get("diff") or []
        return
    if ev.get("from_state") != st["state"]:
        st["problems"].append(L.t("flow.replay_mismatch", seq=ev.get('seq'), edge=L.ed(edge), recorded=L.st(ev.get('from_state')), replayed=L.st(st['state'])))
    prev_state, prev_holder = st["state"], st["holder"]
    st["state"] = ev.get("to_state") or st["state"]
    to = ev.get("to")
    if edge == E.PICK_UP:
        st["holder"] = ev.get("from")
    elif edge not in KEEP_HOLDER:
        st["holder"] = None if to in (None, NONE) else to
    if edge in (E.CREATE, E.REDRAFT):
        if edge == E.CREATE:
            st["skeleton"] = ev.get("skeleton")
        for k in ("goal", "stage", "plan", "key", "title", "type", "planned_executor", "planned_reviewer", "depends_on", "basis", "attendees"):
            if ev.get(k) is not None:
                st[k] = ev[k]
    elif edge in (E.DISPATCH, E.REASSIGN, E.REOPEN):
        st["executor"] = to
        if edge == E.REOPEN:
            st["pass_valid"] = False
        if to != st["rework_by"]:
            st["rework_by"], st["rework_count"] = None, 0
    elif edge == E.DELIVER:
        st["last_deliverer"] = ev.get("from")
        st["reviewer"] = to
    elif edge == E.HAND_OVER and st["state"] == S.IN_REVIEW:
        st["reviewer"] = to
    elif edge == E.REVIEW:
        res = ev.get("result")
        if res == Result.PASS:
            st["pass_valid"] = True
            st["self_reviewed"] = ev.get("from") == st["last_deliverer"]
            st["rework_by"], st["rework_count"] = None, 0
        elif res == Result.NEEDS_MORE and ev.get("from") != BOSS:
            if to == st["rework_by"]:
                st["rework_count"] += 1
            else:
                st["rework_by"], st["rework_count"] = to, 1
    elif edge == E.ESCALATE:
        st["before_escalation"] = [prev_state, prev_holder]
    elif edge == E.PAUSE:
        st["before_pause"] = [prev_state, prev_holder]
    if edge in (E.SUBMIT, E.APPROVE) and ev.get("stage") is not None:
        st["stages"] = ev["stage"]
    if edge == E.APPROVE and ev.get("approved_plan"):
        st["approved_plan"] = ev["approved_plan"]
    if edge == E.SUBMIT and (ev.get("diff_reason") or ev.get("override")):
        st["diff_reason"] = ev.get("diff_reason") or ev["override"]


def replay_all(proj: Project) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    evs, probs = proj.load_events()
    states = {obj: replay(obj, rows) for obj, rows in evs.items()}
    return states, evs, probs


def draft_stage(st: Dict[str, Any]) -> Optional[str]:
    """目标在起草（或从起草暂停）时的阶段：想法、讨论、方案；其余状态返回 None。
    已经搭过框架、又没有写过阶段事件的旧目标不显示（它们早就过了这几段）。"""
    if st["kind"] != Kind.GOAL:
        return None
    drafting = st["state"] == S.DRAFT or (st["state"] == S.PAUSED and (st["before_pause"] or [None])[0] == S.DRAFT)
    if not drafting:
        return None
    if st["plan_version"] and not any(e.get("edge") == E.DRAFT_STAGE for e in st["events"]):
        return None
    return st["draft_stage"]


def goal_dir(proj: Project, goal: str) -> Optional[Path]:
    """目标自己的目录（问题.md、方案.md 和其他文档）：collab/目标/G00x/，归档后在 collab/归档/目标/G00x/。"""
    for d in (proj.collab / P.GOALS / goal, proj.collab / P.ARCHIVE / P.GOALS / goal):
        if d.is_dir():
            return d
    return None


GOAL_DOCS = tuple(Path(x).stem for x in (P.QUESTIONS, P.DISCUSSION, P.PROPOSAL))  # 讨论.md 是 G026 之前的名字，已归档的卡还在用


def goal_files(proj: Project, goal: str) -> Dict[str, Any]:
    """目标目录里的文档（相对项目根的路径）：问题、讨论、方案，其余 Markdown 放「其他」。"""
    d = goal_dir(proj, goal)
    if not d:
        return {}
    out: Dict[str, Any] = {n: proj.rel(d / f"{n}.md") for n in GOAL_DOCS if (d / f"{n}.md").is_file()}
    others = sorted(f for f in d.glob("*.md") if f.stem not in GOAL_DOCS)
    if others:
        out["other"] = [proj.rel(f) for f in others]
    return out


def open_questions(proj: Project, goal: str) -> List[str]:
    """问题.md「待解决」一节里顶格的列表项：要总裁回答的问题。"""
    d = goal_dir(proj, goal)
    f = d / P.QUESTIONS if d else None
    if not f or not f.is_file():
        return []
    m = re.search(r"^## " + heading_re(Section.OPEN_QUESTIONS) + r"[ \t]*\n(.*?)(?=^## |\Z)", f.read_text(encoding="utf-8"), re.M | re.S)
    return [x.strip() for x in re.findall(r"^(?:\d+[.、]|[-*])\s+(.+)$", m.group(1), re.M)] if m else []


# ---------- 阶段 ----------

def obj_skeleton(proj: Project, st: Dict[str, Any]) -> Dict[str, Any]:
    """对象按它「建立」时记下的骨架版本回放和检查（如 任务@1）；骨架升级后旧对象仍按旧版本，旧版本在 历史/ 里找。"""
    name = st["kind"]
    m = re.fullmatch(r"(.+)@(\d+)", st.get("skeleton") or "")
    return proj.skeleton(name, int(m.group(2)) if m else None)


def terminal(proj: Project, st: Dict[str, Any]) -> bool:
    try:
        sk = obj_skeleton(proj, st)
    except FlowError:
        sk = proj.skeleton(st["kind"])
    return st["state"] in sk["terminal"]


def cancelled_before_approval(goal: Dict[str, Any], t: Dict[str, Any]) -> bool:
    """批准之前就取消的任务（框架改版去掉的卡）：不进阶段和时序图，也不算批准后新增；事件仍在账本和记录里。"""
    if t["state"] != S.CANCELLED:
        return False
    appr = max((e.get("project_seq") or 0 for e in goal["events"] if e.get("edge") == E.APPROVE), default=0)
    cancel = max((e.get("project_seq") or 0 for e in t["events"] if e.get("edge") == E.CANCEL), default=0)
    return bool(appr) and 0 < cancel < appr


def dropped_draft(goal: Dict[str, Any], t: Dict[str, Any]) -> bool:
    """框架草稿里去掉的卡：批准前改框架撤下的，或旧账本里批准前就取消的。不进阶段、时序图和任务表，事件只在记录里。"""
    return t["state"] == S.WITHDRAWN or cancelled_before_approval(goal, t)


def stage_table(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks = [s for s in states.values() if s["kind"] == Kind.TASK and s["goal"] == goal["id"]
             and not dropped_draft(goal, s)]
    out: Dict[int, Dict[str, Any]] = {}
    for s in sorted(goal["stages"], key=lambda x: x.get("order", 0)):
        no = s.get("order")
        ts = sorted((t for t in tasks if t["stage"] == no), key=lambda t: id_key(t["id"]))
        live = [t for t in ts if t["state"] != S.CANCELLED]
        people = list(s.get("people", []))
        for t in live:
            if t["planned_executor"] and t["planned_executor"] not in people:
                people.append(t["planned_executor"])
        pre = [p for p in s.get("depends_on", []) if p in out]
        pre_ok = all(out[p]["state"] == S.PASSED for p in pre)
        ended = ts and all(terminal(proj, t) for t in ts)
        passed = ended and any(t["state"] == S.PASSED for t in ts)
        started = any(t["state"] not in (S.PLANNED, S.APPROVED) or t["executor"] for t in ts)
        invalid = False
        if passed and pre_ok:
            status = StageStatus.PASSED
        elif passed or (ended and not passed):
            status = StageStatus.ACTIVE
            invalid = passed and not pre_ok
        elif started:
            status = StageStatus.ACTIVE
        elif pre_ok:
            status = StageStatus.READY
        else:
            status = StageStatus.NOT_STARTED
        base = {x["id"] for x in (goal["approved_plan"] or {}).get("tasks", [])} if goal["approved_plan"] else None
        out[no] = {"order": no, "name": s.get("name", ""), "type": s.get("type", ""), "people": people,
                   "depends_on": list(s.get("depends_on", [])), "parallel": bool(s.get("parallel")), "output": s.get("output", ""),
                   "pass_condition": s.get("pass_condition", ""), "state": status, "invalid": invalid,
                   "tasks": [t["id"] for t in ts],
                   "added_after_approval": [t["id"] for t in ts if base is not None and t["id"] not in base],
                   "reviewers": [t["planned_reviewer"] for t in live if t["planned_reviewer"]],
                   "needs_split": not live}
    return [out[k] for k in sorted(out)]


def structure(goal: Dict[str, Any], stages: List[Dict[str, Any]], by_task: Dict[str, Dict[str, Any]],
              rows: List[Dict[str, Any]], basis_of: Optional[Dict[str, str]] = None,
              side_seqs: List[int] = ()) -> Dict[str, Any]:
    """时序图的骨架：按「阶段 → 任务 → 派发、交付、确认」排，每一步的位置不随事件变。没发生的「计划」为真，
    发生了带项目序，呈现端按项目序取时间和说明。接手并进派发那一行；返工、上报等支线挂在所在步骤后面。"""
    def step(edge, frm, to, seq=None, more=()):
        return {"edge": edge, "from": frm, "to": to, "planned": seq is None, "project_seq": seq, "includes": list(more)}
    level: Dict[int, int] = {}
    for s in stages:
        level[s["order"]] = 1 + max([level.get(p, 0) for p in s["depends_on"]] or [0])
    by_stage = {s["order"]: s for s in stages}
    out_stages, needs_me = [], []
    basis_of = basis_of or {}
    merged: Dict[str, Any] = {}  # 要求序 → 同时改的框架版本
    for s in stages:
        items = []
        for tid in s["tasks"]:
            t = by_task[tid]
            ended = t["category"] == Category.DONE
            doer = t["executor"] or t["planned_executor"] or (s["people"] or [LEAD])[0]
            checker = t["reviewer"] or t["planned_reviewer"] or LEAD
            marks = {m["slot"]: m["project_seq"] for m in t["trunk"]}
            hidden = (E.CREATE, E.PICK_UP, E.APPROVE, E.CHANGE, E.PROGRESS, E.CORRECTION, E.COMMENT)
            branches: Dict[int, List[Dict[str, Any]]] = {}
            for b in t["branches"]:
                if b["edge"] not in hidden:
                    branches.setdefault(b["attached_to"], []).append(step(b["edge"], b.get("from"), b.get("to"), b["project_seq"]))
            steps = []
            def put(slot, edge, frm, to, more=()):
                seq = marks.get(slot)
                if seq is not None or not ended:
                    steps.append(step(edge, frm, to, seq, more))
                for x in sorted(k for k in branches if k == slot or (slot == 1 and k in (0, 2))):
                    steps.extend(branches[x])
            if t.get("request_seq") is not None and tid in s["added_after_approval"]:
                steps.append({**step(E.REQUEST, BOSS, LEAD, t["request_seq"]), "source": True})  # 总裁要求带来的新增任务：派发前先画总裁 → 总管
            put(1, E.DISPATCH, LEAD, doer, [marks[2]] if 2 in marks else [])
            put(3, E.DELIVER, doer, checker)
            put(4, E.REVIEW, checker, NONE)
            need = list(t["depends_on"]) or [x for p in s["depends_on"] if p in by_stage for x in by_stage[p]["tasks"] if by_task[x]["state"] != S.CANCELLED]
            mine = BOSS in (t["planned_executor"], t["planned_reviewer"]) and not ended
            if mine:
                needs_me.append(tid)
            items.append({"id": tid, "title": t["title"], "state": t["state"], "planned_executor": t["planned_executor"], "executor": t["executor"],
                          "planned_reviewer": t["planned_reviewer"], "needs": need, "owner_involved": BOSS in (t["planned_executor"], t["planned_reviewer"]),
                          "added_after_approval": tid in s["added_after_approval"],
                          "reassigned": bool(t["executor"] and t["planned_executor"] and t["executor"] != t["planned_executor"]), "steps": steps})
        same = [x["order"] for x in stages if level[x["order"]] == level[s["order"]] and x["order"] != s["order"]]
        out_stages.append({"order": s["order"], "name": s["name"], "type": s["type"], "state": s["state"], "invalid": s["invalid"],
                           "output": s["output"], "pass_condition": s["pass_condition"], "layer": level[s["order"]],
                           "parallel_with": same, "needs_split": s["needs_split"], "tasks": items})
    state = goal["state"]
    def last(edge):
        return next((r["project_seq"] for r in reversed(rows) if r.get("edge") == edge), None)
    used = []
    def goal_step(edge, frm, to):
        seq = last(edge)
        if seq is not None:
            used.append(seq)
        return step(edge, frm, to, seq)
    head, tail = [], []
    if state == S.DRAFT and last(E.SUBMIT) is None:
        head.append(step(E.SUBMIT, LEAD, BOSS))
    appr = goal_step(E.APPROVE, BOSS, LEAD)
    final_check = goal_step(E.REQUEST_ACCEPTANCE, LEAD, BOSS)
    tail.append(final_check)
    tail.append(goal_step(E.COMPLETE, BOSS, NONE))
    if state == S.CANCELLED:
        appr = appr if not appr["planned"] else None
        head = [x for x in head if not x["planned"]]
        tail = [x for x in tail if not x["planned"]]
    late = []
    # 目标层事件（总裁的打回、退回，带原话的变更，每一次目标验收）：按时间插回，不集中放
    added = {tid for sx in stages for tid in sx["added_after_approval"]}
    req = {by_task[tid]["request_seq"]: tid for tid in added if by_task[tid].get("request_seq") is not None}
    gev = []
    for r in rows:
        seq, e = r["project_seq"], r.get("edge")
        if is_boss_return(r) or e == E.REQUEST_ACCEPTANCE and seq != final_check["project_seq"]:
            gev.append(step(e, BOSS if e != E.REQUEST_ACCEPTANCE else LEAD, LEAD if e != E.REQUEST_ACCEPTANCE else BOSS, seq))
        elif e == E.CHANGE and is_quote(r.get("basis"), goal["id"]):
            host = next((q for q, t in req.items() if basis_of.get(t, "").strip() == r["basis"].strip()), None)
            if host is not None:  # 依据和某个新增任务的建立依据相同：并进那个任务的「要求」，不单独画
                for sx in out_stages:
                    for it in sx["tasks"]:
                        for stp in it["steps"]:
                            if stp["edge"] == E.REQUEST and stp["project_seq"] == host:
                                stp["includes"].append(seq)
                merged[str(host)] = r.get("plan_version")
                used.append(seq)
            else:
                gev.append(step(e, BOSS, LEAD, seq))
    used += [x["project_seq"] for x in gev]
    gev.sort(key=lambda x: x["project_seq"])
    # 锚点：阶段、任务各自第一条已发生事件的项目序；事件插在锚点晚于它的最早的阶段或任务之前（同点阶段在先）
    approve_seq = appr["project_seq"] if appr else None
    cand = []
    for sx in out_stages:
        tas = []
        for it in sx["tasks"]:
            sq = [x["project_seq"] for x in it["steps"] if x["project_seq"] is not None and approve_seq is not None and x["project_seq"] > approve_seq]  # 批准之前的事不算它的位置
            if sq:
                tas.append((min(sq), 1, sx["order"], it))
        if tas:
            cand.append((min(c[0] for c in tas), 0, sx["order"], sx))
            cand += tas
    cand.sort(key=lambda c: (c[0], c[1]))
    for sx in out_stages:
        sx["before"] = []
        for it in sx["tasks"]:
            it["before"] = []
    for x in gev:
        if approve_seq is None or x["project_seq"] < approve_seq:
            head.append(x)
            continue
        c = next((c for c in cand if c[0] > x["project_seq"]), None)
        if c is None:
            late.append(x)
        else:
            c[3]["before"].append(x)
    if appr:
        head.append(appr)
    record_seqs = [r["project_seq"] for r in rows if r["project_seq"] not in used and r.get("edge") not in (E.PROGRESS, E.COMMENT)]
    record_seqs = sorted(record_seqs + list(side_seqs))  # 批准前取消的任务的事件，只在记录里
    return {"record": record_seqs, "head": head, "stages": out_stages, "tail": late + tail, "owner_tasks": needs_me, "merged": merged}


def id_key(x: str) -> Tuple:
    return tuple(int(n) if n.isdigit() else n for n in re.findall(r"\d+|\D+", x))


def template_stages(proj: Project, gtype: str) -> List[Dict[str, Any]]:
    return proj.skeleton(Skel.goal_type(gtype))["stages"]


def stage_shape(stages: List[Dict[str, Any]]) -> List[Tuple]:
    return [(s.get("order"), s.get("name"), s.get("type"), tuple(s.get("depends_on", []))) for s in stages]


# ---------- 校验和组装一条事件 ----------

def seat_ok(proj: Project, cls: str, who: Optional[str], st: Dict[str, Any], actor: str) -> bool:
    if cls == SeatClass.NONE:
        return who in (None, NONE)
    if cls == SeatClass.MANAGER:
        return who in MANAGERS
    if cls in (SeatClass.LEAD, SeatClass.OWNER):
        return who == cls
    if cls == SeatClass.SELF:
        return who == actor
    if cls == SeatClass.EXECUTOR:
        return who == LEAD or proj.is_member(who)
    if cls == SeatClass.REVIEWER:
        return who in MANAGERS or proj.is_member(who)
    return False


def resolve_ref(ref: str, st: Dict[str, Any]) -> Any:
    if ref == SeatClass.STATE_BEFORE_ESCALATION:
        return (st["before_escalation"] or [None, None])[0]
    if ref == SeatClass.HOLDER_BEFORE_ESCALATION:
        return (st["before_escalation"] or [None, None])[1]
    if ref == SeatClass.STATE_BEFORE_PAUSE:
        return (st["before_pause"] or [None, None])[0]
    if ref == SeatClass.HOLDER_BEFORE_PAUSE:
        return (st["before_pause"] or [None, None])[1]
    if ref == SeatClass.LAST_DELIVERER:
        return st["last_deliverer"]
    if ref == SeatClass.UNCHANGED:
        return st["state"]
    return ref


def plan(proj: Project, states: Dict[str, Dict[str, Any]], obj: str, edge: str, a: Dict[str, Any]) -> Dict[str, Any]:
    """检查并组装一条事件（不写盘）。a：发起、给、结果、证据、说明、依据、方案、建议、变更项、阶段、越过等。
    规则错误在带「越过」且发起或写入者是总管、总裁时放行，记下理由。"""
    L = proj.L
    st = states.get(obj) or blank_state(obj)
    kind = st["kind"]
    sk = proj.skeleton(kind, None)
    actor = a.get("from")
    if not actor:
        raise hard(L.t("flow.unknown_actor"))
    if edge != E.CREATE and st["state"] == S.NONE:
        raise hard(L.t("flow.not_created", obj=obj))
    if edge == E.CREATE and st["state"] != S.NONE:
        raise hard(L.t("flow.already_created", obj=obj))
    rules: List[str] = []
    ev: Dict[str, Any] = {"object": obj, "edge": edge, "from": actor}
    if a.get("with_goal"):
        ev["with_goal"] = True
    for k in ("evidence", "note", "basis", "options", "recommendation", "changes", "diff_reason", "correct", "run", "session", "writer"):
        if a.get(k) not in (None, "", []):
            ev[k] = a[k]
    if kind == Kind.ISSUE and a.get("attendees") is not None and edge in (E.CREATE, E.CHANGE):
        ev["attendees"] = attendees(proj, a["attendees"])

    if edge in MESSAGES:
        if kind != Kind.ISSUE:
            raise hard(L.t("flow.issue_only", edge=L.ed(edge)))
        return message(proj, st, sk, ev, edge, a, rules)

    if edge in SPECIAL:
        spec = sk["special_events"].get(edge)
        if spec is None and edge == E.DRAFT_STAGE and kind == Kind.GOAL:
            spec = {"required": []}  # 项目自己覆盖的旧目标骨架没写这个事件也能用
        if spec is None:
            raise hard(L.t("flow.kind_no_event", kind=L.name('kind', kind), edge=L.ed(edge)))
        if edge == E.DRAFT_STAGE:
            if kind != Kind.GOAL:
                raise hard(L.t("flow.draft_stage_goal_only", edge=L.ed(E.DRAFT_STAGE)))
            if a.get("result") not in DRAFT_STAGES:
                raise hard(L.t("flow.need_result", edge=L.ed(E.DRAFT_STAGE), results=' / '.join(L.name('draft_stage', x) for x in DRAFT_STAGES)))
            if st["state"] != S.DRAFT:
                raise hard(L.t("flow.draft_stage_not_draft", obj=obj, state=L.st(st['state'])))
            ev["result"] = a["result"]
        missing = [k for k in spec.get("required", []) if not ev.get(k)]
        if missing:
            raise hard(L.t("flow.required", edge=L.ed(edge), fields=L.join(L.name('event_field', x) for x in missing)))
        if edge == E.CORRECTION:
            seqs = [r.get("seq") for r in st["events"]] + st["voided"]
            if ev["correct"] not in seqs:
                raise hard(L.t("flow.no_seq", obj=obj, seq=ev['correct']))
        if edge == E.COMMENT and actor != BOSS:
            raise hard(L.t("flow.comment_owner_only", edge=L.ed(E.COMMENT)))
        if edge == E.CHANGE and kind == Kind.TASK:
            for k in ("key", "title", "planned_executor", "planned_reviewer", "depends_on"):
                if a.get(k) is not None:
                    ev[k] = a[k]
            if a.get("task_stage") is not None:
                ev["stage"] = a["task_stage"]
        if edge == E.CHANGE and kind == Kind.GOAL:
            for k in ("plan_version", "diff"):
                if a.get(k) is not None:
                    ev[k] = a[k]
            need = set(spec.get("changes_need_approval", []))
            if need & set(ev.get("changes", [])) and not ev.get("basis"):
                rules.append(L.t("flow.change_needs_owner", what=L.join(sorted(need & set(ev['changes'])))))
            if a.get("stage") is not None:
                check_stage_list(a["stage"])
                ev["stage"] = plan_stages(proj, a["stage"])
        ev["from_state"] = ev["to_state"] = st["state"]
        ev["to"] = NONE
        return finish(ev, st, sk, rules, a)

    spec = sk["edges"].get(edge)
    if not spec:
        names = L.join(list(sk["edges"]) + list(SPECIAL))
        raise hard(L.t("flow.kind_no_edge", kind=L.name('kind', kind), edge=L.ed(edge), names=names))
    res = a.get("result")
    target = spec.get("to")
    recv_cls = spec.get("receiver")
    default_recv = spec.get("default_receiver")
    if "results" in spec:
        if res not in spec["results"]:
            raise hard(L.t("flow.need_result", edge=L.ed(edge), results=' / '.join(L.name('result', x) for x in spec['results'])))
        r = spec["results"][res]
        target, recv_cls, default_recv = r["to"], r["receiver"], r.get("default_receiver")
        ev["result"] = res
    elif res:
        raise hard(L.t("flow.no_result", edge=L.ed(edge)))
    missing = [k for k in spec.get("required", []) if not ev.get(k) and not (k == "evidence" and a.get("evidence"))]
    if (edge == E.ESCALATE or (edge == E.HAND_OVER and st["state"] == S.BLOCKED)) and proj.actor(a.get("to")) == BOSS:
        missing += [k for k in ("options", "recommendation") if not ev.get(k)]
    if missing:
        raise hard(L.t("flow.required", edge=L.ed(edge), fields=L.join(L.name('event_field', x) for x in missing)))

    # 从哪个状态
    if st["state"] not in spec["from"]:
        rules.append(L.t("flow.wrong_state", obj=obj, state=L.st(st['state']), edge=L.ed(edge), allowed=L.join(L.st(x) for x in spec['from'])))
    # 发起
    holder = st["holder"]
    ini = spec["initiator"]
    if ini == SeatClass.HOLDER and actor != holder:
        rules.append(L.t("flow.holder_only", edge=L.ed(edge), holder=L.who(holder) or '—', actor=L.who(actor)))
    elif ini == SeatClass.MANAGER and actor not in MANAGERS:
        rules.append(L.t("flow.managers_only", edge=L.ed(edge)))
    elif ini in MANAGERS and actor != ini:
        rules.append(L.t("flow.initiator_only", edge=L.ed(edge), who=L.name('seat_class', ini)))
    # 接收
    given = proj.actor(a["to"]) if a.get("to") else None
    if a.get("to") and not given:
        raise hard(L.t("flow.unknown_receiver", to=L.who(a['to'])))
    if recv_cls == SeatClass.STATE_SEAT:
        recv_cls = {S.IN_PROGRESS: SeatClass.EXECUTOR, S.IN_REVIEW: SeatClass.REVIEWER, S.BLOCKED: SeatClass.MANAGER}.get(st["state"], SeatClass.MANAGER)
        if not given:
            raise hard(L.t("flow.hand_over_to", edge=L.ed(E.HAND_OVER)))
    if recv_cls and recv_cls.startswith("@"):
        recv = resolve_ref(recv_cls, st)
        if given and given != recv:
            rules.append(L.t("flow.receiver_should_be", edge=L.ed(edge), expected=L.who(recv) or '—', given=L.who(given)))
        recv = given or recv
    else:
        recv = given
        if recv is None and default_recv:
            recv = resolve_ref(default_recv, st)
        if recv is None and recv_cls in (SeatClass.LEAD, SeatClass.OWNER):
            recv = recv_cls
        if recv is None and recv_cls == SeatClass.SELF:
            recv = actor
        if recv is None and recv_cls == SeatClass.NONE:
            recv = NONE
        if recv is None:
            raise hard(L.t("flow.need_to", edge=L.ed(edge), cls=L.name('seat_class', recv_cls)))
        if not seat_ok(proj, recv_cls, recv, st, actor):
            rules.append(L.t("flow.receiver_class", edge=L.ed(edge), cls=L.name('seat_class', recv_cls), given=L.who(recv)))
    ev["to"] = recv or NONE

    to_state = resolve_ref(target, st)
    if not to_state:
        raise hard(L.t("flow.no_return_state", edge=L.ed(edge)))

    # 各边的守卫
    if kind == Kind.TASK:
        task_guards(proj, states, st, edge, ev, res, rules, sk)
    elif kind == Kind.ISSUE:
        issue_guards(proj, states, st, edge, ev, a, rules, sk)
    else:
        goal_guards(proj, states, st, edge, ev, a, rules)
    if edge in (E.CREATE, E.REDRAFT):
        for k in ("goal", "stage", "key", "title", "type", "planned_executor", "planned_reviewer"):
            if a.get(k) not in (None, ""):
                ev[k] = a[k]
        if a.get("depends_on") or edge == E.REDRAFT:
            ev["depends_on"] = a.get("depends_on") or []
        if kind == Kind.TASK:  # 目标批准前建的卡在规划中；批准后补的卡直接可派，图上标「批准后新增」
            g = states.get(a.get("goal")) or {}
            to_state = S.PLANNED if g.get("state") in (S.DRAFT, S.PENDING_APPROVAL) else S.APPROVED
    if edge == E.APPROVE and kind == Kind.TASK and a.get("with_goal"):
        ev.pop("with_goal", None)
    ev["from_state"], ev["to_state"] = st["state"], to_state
    return finish(ev, st, sk, rules, a)


def finish(ev: Dict[str, Any], st: Dict[str, Any], sk: Dict[str, Any], rules: List[str], a: Dict[str, Any]) -> Dict[str, Any]:
    ev["skeleton"] = f"{sk['skeleton']}@{sk['version']}"
    if rules:
        why = a.get("override")
        if not why:
            raise rule(i18n.pack().join(rules, "sep.clause"))
        if ev["from"] not in MANAGERS and a.get("writer") != LEAD:
            raise rule(i18n.pack().t("flow.override_managers", rules=i18n.pack().join(rules, "sep.clause")))
        ev["override"] = i18n.pack().t("flow.override_note", why=why, rules=i18n.pack().join(rules, "sep.clause"))
    return ev


def attendees(proj: Project, spec: List[Any]) -> List[Dict[str, str]]:
    """与会：[{成员, 视角}]；成员必须在花名册里（总裁、总管不算与会者），不重复。"""
    L = proj.L
    out: List[Dict[str, str]] = []
    for item in spec:
        name, view_ = (item.get("member"), item.get("view", "")) if isinstance(item, dict) else (str(item).partition(":")[0], str(item).partition(":")[2])
        who = proj.actor(name)
        if not who or who in MANAGERS:
            raise hard(L.t("flow.attendee_not_in_roster", name=name))
        if any(x["member"] == who for x in out):
            raise hard(L.t("flow.attendee_twice", who=L.who(who)))
        out.append({"member": who, "view": (view_ or "").strip()})
    if not out:
        raise hard(L.t("flow.attendees_empty"))
    return out


def message(proj: Project, st: Dict[str, Any], sk: Dict[str, Any], ev: Dict[str, Any], edge: str,
            a: Dict[str, Any], rules: List[str]) -> Dict[str, Any]:
    """发言、PASS：只存事实（正文、点名、是否私下、总裁自选的类型），发言类型由投影推出。"""
    L = proj.L
    spec = sk["message_events"][edge]
    if edge == E.POST:
        if not (a.get("body") or "").strip():
            raise hard(L.t("flow.required", edge=L.ed(E.POST), fields=L.name("event_field", "body")))
        ev["body"] = a["body"]
    names = [x["member"] for x in st["attendees"]]
    if st["state"] not in spec.get("allowed_in", []):
        rules.append(L.t("flow.post_not_discussing", obj=st['id'], state=L.st(st['state']), edge=L.ed(edge)))
    if ev["from"] not in MANAGERS and ev["from"] not in names:
        rules.append(L.t("flow.not_attendee", who=L.who(ev['from']), obj=st['id'], names=L.join(names)))
    called = []
    for w in a.get("mentions") or []:
        who = proj.actor(w)
        if not who or (who not in MANAGERS and who not in names):
            raise hard(L.t("flow.bad_mention", who=w))
        if who not in called and who != ev["from"]:
            called.append(who)
    if called:
        ev["mentions"] = called
    if a.get("private"):
        ev["private"] = True
    if a.get("type") and ev["from"] == BOSS:
        ev["type"] = a["type"]
    ev["from_state"] = ev["to_state"] = st["state"]
    ev["to"] = NONE
    return finish(ev, st, sk, rules, a)


def open_reviews(states: Dict[str, Dict[str, Any]], goal: str) -> List[Dict[str, Any]]:
    """挂在目标上、还没结束的框架会审。"""
    return [s for s in sorted(states.values(), key=lambda x: id_key(x["id"]))
            if s["kind"] == Kind.ISSUE and s["goal"] == goal and s["type"] == IssueType.REVIEW_MEETING and s["state"] not in (S.RULED, S.CANCELLED, S.NONE)]


def issue_guards(proj, states, st, edge, ev, a, rules, sk):
    L = proj.L
    if edge == E.CREATE:
        itype = a.get("type") or IssueType.COUNCIL
        if itype not in sk["types"]:
            raise hard(L.t("flow.issue_type", types=' / '.join(L.name('issue_type', x) for x in sk['types'])))
        a["type"] = itype
        goal = a.get("goal")
        if goal:
            g = states.get(goal)
            if not g or g["kind"] != Kind.GOAL or g["state"] == S.NONE:
                rules.append(L.t("flow.goal_missing", goal=goal))
            elif itype == IssueType.REVIEW_MEETING and g["state"] != S.PENDING_APPROVAL:
                rules.append(L.t("flow.review_meeting_state", goal=goal, state=L.st(g['state'])))
            elif g["state"] in (S.DONE, S.CANCELLED):
                rules.append(L.t("flow.goal_closed", goal=goal, state=L.st(g['state'])))
        elif itype == IssueType.REVIEW_MEETING:
            raise hard(L.t("flow.review_meeting_goal"))


def task_guards(proj, states, st, edge, ev, res, rules, sk):
    L = proj.L
    if edge == E.CREATE:
        return
    if edge == E.APPROVE and not ev.get("with_goal"):
        raise hard(L.t("flow.task_no_approve"))
    if edge in (E.WITHDRAW, E.REDRAFT):
        g = states.get(st["goal"]) or {}
        if edge == E.WITHDRAW and (g.get("state") not in (S.DRAFT, S.PENDING_APPROVAL) or g.get("approved_plan")):
            raise hard(L.t("flow.withdraw_before_approval", obj=st['id']))
        if g.get("state") in (S.DONE, S.CANCELLED):
            raise hard(L.t("flow.no_redraft", goal=st['goal'], state=L.st(g['state'])))
        return
    if st["state"] == S.PLANNED and edge not in (E.APPROVE, E.CANCEL):
        raise hard(L.t("flow.still_planned", obj=st['id'], goal=st['goal']))
    if edge == E.DELIVER:
        for p in ev.get("evidence", []):
            path = Path(p).expanduser()
            if not path.is_absolute():
                path = proj.root / p
            if not path.exists():
                raise hard(L.t("flow.no_evidence", path=p))
    if edge == E.REVIEW:
        if ev["from"] == st["last_deliverer"] and ev["from"] != LEAD:
            rules.append(L.t("flow.reviewer_is_deliverer", who=L.who(ev['from'])))
        if res == Result.NEEDS_MORE and ev["from"] != BOSS and ev["to"] == st["rework_by"] and st["rework_count"] + 1 >= sk.get("max_rework", 3):
            rules.append(L.t("flow.rework_limit", who=L.who(ev['to']), n=st['rework_count']))
    if edge == E.HAND_OVER and st["state"] == S.IN_REVIEW and ev["to"] == st["last_deliverer"] and ev["to"] != LEAD:
        rules.append(L.t("flow.no_review_by_deliverer"))
    if edge in (E.DISPATCH, E.REASSIGN, E.REOPEN) and st["goal"]:
        g = states.get(st["goal"])
        if not g or g["state"] == S.NONE:
            rules.append(L.t("flow.goal_missing", goal=st['goal']))
            return
        if g["state"] in (S.DRAFT, S.PENDING_APPROVAL):
            raise hard(L.t("flow.dispatch_needs_approval", goal=g['id'], state=L.st(g['state'])))
        if g["state"] != S.ACTIVE:
            rules.append(L.t("flow.dispatch_needs_active", goal=g['id'], state=L.st(g['state'])))
        if edge == E.DISPATCH:
            miss = handoff_gaps(proj, st["id"])
            if miss:
                raise hard(L.t("flow.handoff_missing", obj=st['id'], fields=L.join(miss)))
        for p in st["depends_on"]:
            if (states.get(p) or {}).get("state") not in (S.PASSED, S.CANCELLED):
                rules.append(L.t("flow.dep_not_passed", obj=st['id'], dep=p))
        stage = next((s for s in stage_table(proj, g, states) if s["order"] == st["stage"]), None)
        if not stage:
            rules.append(L.t("flow.goal_no_stage", goal=g['id'], stage=st['stage']))
        else:
            if stage["state"] == StageStatus.NOT_STARTED:
                rules.append(L.t("flow.stage_deps_open", order=stage['order'], name=stage['name']))
            if stage["people"] and ev["to"] not in stage["people"]:
                rules.append(L.t("flow.stage_people", order=stage['order'], people=L.join(stage['people']), to=L.who(ev['to'])))


def goal_guards(proj, states, st, edge, ev, a, rules):
    L = proj.L
    if edge == E.CREATE:
        gtype = a.get("type") or GoalType.GENERAL
        a["type"] = gtype  # 建立目标只需标题和依据，类型默认通用
        if gtype not in proj.skeleton(Skel.GOAL)["types"]:
            raise hard(L.t("flow.goal_type", types=' / '.join(L.name('goal_type', x) for x in proj.skeleton(Skel.GOAL)['types'])))
        return
    if edge == E.SUBMIT:
        if a.get("stage") is not None:
            raise hard(L.t("flow.submit_no_stages"))
        gaps = frame_gaps(proj, st, states)
        if gaps:
            raise hard(L.t("flow.submit_gaps", gaps=L.join(gaps, "sep.clause")))
    if edge == E.APPROVE:
        if a.get("stage") is not None:
            raise hard(L.t("flow.approve_no_structure"))
        if a.get("plan_version") is not None and int(a["plan_version"]) != st["plan_version"]:
            raise hard(L.t("flow.plan_outdated", current=st['plan_version'], seen=a['plan_version']))
        gaps = frame_gaps(proj, st, states)
        if gaps:
            raise hard(L.t("flow.approve_gaps", gaps=L.join(gaps, "sep.clause")))
        stages = [dict(s) for s in st["stages"]]
        for no, who in (a.get("people") or {}).items():
            s = next((x for x in stages if x.get("order") == no), None)
            if not s:
                raise hard(L.t("flow.no_stage", no=no))
            s["people"] = who
        check_stage_list(stages)
        stages = plan_stages(proj, stages)
        ev["stage"] = stages
        ev["approved_plan"] = approved_snapshot(proj, st, states)
    if edge in (E.APPROVE, E.RETURN):
        for s in open_reviews(states, st["id"]):
            if s["state"] != S.PENDING_RULING:
                rules.append(L.t("flow.review_meeting_open", obj=s['id'], state=L.st(s['state'])))
    if edge == E.REQUEST_ACCEPTANCE:
        table = stage_table(proj, st, states)
        if not table or any(s["state"] != S.PASSED for s in table):
            left = [f"{s['order']}{L.t('sep.paren_open')}{L.name('stage_status', s['state'])}{L.t('sep.paren_close')}" for s in table if s["state"] != S.PASSED]
            rules.append(L.t("flow.stages_open", left=L.join(left) or L.t("flow.no_stages")))


def plan_stages(proj: Project, stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """整理阶段实例：人名换成花名册里的名字。任务不在阶段里存，任务卡是唯一来源。"""
    out = []
    for s in stages:
        s = {k: v for k, v in s.items() if k not in ("planned_tasks", "tasks")}
        people = []
        for w in s.get("people", []):
            x = proj.actor(w) or w
            if x not in MANAGERS and not proj.is_member(x):
                raise hard(i18n.pack().t("flow.stage_person_unknown", order=s.get('order'), who=w))
            people.append(x)
        s["people"] = people
        out.append(s)
    return out


HANDOFF_FIELDS = (Field.PURPOSE, Field.ROLE, Field.CONSTRAINTS, Field.ALTERNATIVES, Field.INPUTS, Field.DELIVERABLES,
                  Field.ACCEPTANCE, Field.AUTHORITY, Field.ESCALATE_WHEN)
HANDOFF_REQUIRED = (Field.PURPOSE, Field.DELIVERABLES, Field.ACCEPTANCE)


def field_code(name: str) -> str:
    """字段名 → 代码：中英两种写法都认，认不出原样返回。"""
    return i18n.code_of("field", name) or name


def handoff_fields(text: str) -> Dict[str, str]:
    """把任务卡「交接」一节拆成字段（键是代码）：`- 名称：内容`，名称认中英两种写法，内容可以跨行。"""
    out: Dict[str, str] = {}
    key = None
    for line in text.splitlines():
        m = re.match(r"^-\s*([^：:]{1,24}?)\s*[：:]\s*(.*)$", line)
        code = field_code(m.group(1)) if m else None
        if code in HANDOFF_FIELDS:
            key = code
            out[key] = m.group(2).strip()
        elif key and line.strip():
            out[key] = (out[key] + "\n" + line.strip()).strip()
    return out


def handoff_like(text: str) -> Dict[str, str]:
    """目标卡「要什么」的 `- 名称：内容` 拆成字段（认得的名称换成代码）。"""
    return {field_code(m.group(1)): m.group(2).strip() for m in re.finditer(r"^-\s*([^：:]{1,24}?)\s*[：:]\s*(.*)$", text, re.M)}


def handoff_text(fields: Dict[str, Any], L: Optional["i18n.Pack"] = None) -> str:
    L = L or i18n.pack()
    return "\n".join(f"- {L.kv(L.field(k), str(fields.get(k) or '').strip())}" for k in HANDOFF_FIELDS)


def handoff_gaps(proj: Project, tid: str) -> List[str]:
    got = handoff_fields(card_section(proj, tid, Section.HANDOFF))
    return [k for k in HANDOFF_REQUIRED if not got.get(k)]


def goal_tasks(states: Dict[str, Dict[str, Any]], goal: str) -> List[Dict[str, Any]]:
    return sorted((t for t in states.values() if t["kind"] == Kind.TASK and t["goal"] == goal and t["state"] not in (S.CANCELLED, S.WITHDRAWN)),
                  key=lambda t: id_key(t["id"]))


def frame_gaps(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> List[str]:
    """提交、批准前框架还缺什么：每个阶段至少一张卡，每张卡有执行人、确认人和必填内容。"""
    L = proj.L
    if not goal["stages"]:
        return [L.t("flow.gap_no_plan")]
    gaps = []
    wish = handoff_like(card_section(proj, goal["id"], Section.WANT))
    missing = [k for k in (Field.WANT, Field.CRITERIA) if not wish.get(k)]
    if missing:
        gaps.append(L.t("flow.gap_goal_fields", fields=L.join(L.field(x) for x in missing)))
    tasks = goal_tasks(states, goal["id"])
    for s in goal["stages"]:
        if not any(t["stage"] == s.get("order") for t in tasks):
            gaps.append(L.t("flow.gap_stage_empty", order=s.get('order'), name=s.get('name', '')))
    for t in tasks:
        if not t["planned_executor"] or not t["planned_reviewer"]:
            gaps.append(L.t("flow.gap_people", obj=t['id']))
        miss = handoff_gaps(proj, t["id"])
        if miss:
            gaps.append(L.t("flow.gap_handoff", obj=t['id'], fields=L.join(miss)))
    return gaps


def approved_snapshot(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {"version": goal["plan_version"], "tasks": [
        {"id": t["id"], "title": t["title"], "stage": t["stage"], "planned_executor": t["planned_executor"], "planned_reviewer": t["planned_reviewer"],
         "depends_on": t["depends_on"], "content": sha(card_section(proj, t["id"], Section.HANDOFF))} for t in goal_tasks(states, goal["id"])]}


def approved_diff(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """现在和批准版的差别。"""
    L = proj.L
    base = goal.get("approved_plan")
    if not base:
        return []
    old = {x["id"]: x for x in base["tasks"]}
    out = []
    all_tasks = sorted((t for t in states.values() if t["kind"] == Kind.TASK and t["goal"] == goal["id"]), key=lambda t: id_key(t["id"]))
    for t in all_tasks:
        tid, was = t["id"], old.get(t["id"])
        if t["state"] == S.WITHDRAWN:
            continue
        if not was:
            if t["state"] != S.CANCELLED:
                out.append({"type": Diff.ADDED, "task": tid, "note": f"{t['title']}{L.t('sep.paren_open')}{t['planned_executor'] or t['executor'] or '—'}{L.t('sep.paren_close')}"})
            continue
        if t["state"] == S.CANCELLED:
            out.append({"type": Diff.CANCELLED, "task": tid, "note": t["title"]})
            continue
        now_doer = t["executor"] or t["planned_executor"]
        if now_doer != was["planned_executor"]:
            out.append({"type": Diff.EXECUTOR_CHANGED, "task": tid, "note": f"{L.who(was['planned_executor'])} → {now_doer}"})
        if t["planned_reviewer"] != was["planned_reviewer"]:
            out.append({"type": Diff.REVIEWER_CHANGED, "task": tid, "note": f"{L.who(was['planned_reviewer'])} → {L.who(t['planned_reviewer'])}"})
        if t["depends_on"] != was["depends_on"] or t["stage"] != was["stage"]:
            out.append({"type": Diff.DEPS_CHANGED, "task": tid, "note": t["title"]})
        if sha(card_section(proj, tid, Section.HANDOFF)) != was["content"]:
            out.append({"type": Diff.CONTENT_CHANGED, "task": tid, "note": t["title"]})
    return out


def check_stage_list(stages: List[Dict[str, Any]]) -> None:
    seen = set()
    for s in stages:
        no = s.get("order")
        if not isinstance(no, int) or no in seen:
            raise hard(i18n.pack().t("flow.stage_order", no=no))
        if s.get("type") not in (StageType.WORK, StageType.RESEARCH, StageType.ACCEPTANCE):
            raise hard(i18n.pack().t("flow.stage_type", no=no, types=" / ".join(i18n.pack().name("stage_type", x) for x in ("work", "research", "acceptance"))))
        for p in s.get("depends_on", []):
            if p not in seen:
                raise hard(i18n.pack().t("flow.stage_dep_order", no=no, dep=p))
        seen.add(no)
        s.setdefault("depends_on", [])
        s.setdefault("people", [])
        s.setdefault("parallel", False)


# ---------- 写入 ----------

def record(proj: Project, obj: str, edge: str, a: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """加锁、校验、追加一条事件、重渲染。返回（事件，提醒）。"""
    L = proj.L
    with locked(proj):
        states, evs, _ = replay_all(proj)
        ev = plan(proj, states, obj, edge, a)
        append(proj, evs, obj, ev, a)
        if kind_of(obj) == Kind.GOAL and edge == E.APPROVE:  # 工作目录批准时才建，想法和讨论阶段不留空目录
            (proj.root / workdir(proj, obj)).mkdir(parents=True, exist_ok=True)
        # 框架会审随目标的批准或退回一起裁决（方案 03 第 10.3 节 B）
        if kind_of(obj) == Kind.GOAL and edge in (E.APPROVE, E.RETURN):
            states = {o: replay(o, rs) for o, rs in evs.items()}
            for s in [x for x in open_reviews(states, obj) if x["state"] == S.PENDING_RULING]:
                b = {"from": BOSS, "writer": ev.get("writer"), "basis": ev.get("basis") or ev.get("note"),
                     "note": L.t("flow.ruled_with", obj=obj, edge=L.ed(edge))}
                append(proj, evs, s["id"], plan(proj, states, s["id"], E.RULE, b), b)
        # 目标批准，它下面规划中的任务一起批准；目标取消，规划中的任务一起取消
        if kind_of(obj) == Kind.GOAL and edge in (E.APPROVE, E.CANCEL):
            states = {o: replay(o, rs) for o, rs in evs.items()}
            for t in [x for x in goal_tasks(states, obj) if x["state"] == S.PLANNED]:
                b = {"from": BOSS if edge == E.APPROVE else LEAD, "writer": ev.get("writer"), "basis": ev.get("basis") or "",
                     "note": L.t("flow.with_goal", obj=obj, edge=L.ed(edge)), "with_goal": True}
                append(proj, evs, t["id"], plan(proj, states, t["id"], edge, b), b)
        render_all(proj)
    notes = []
    st = replay(obj, evs.get(obj, []))
    if st["rework_count"] == 2:
        notes.append(L.t("flow.rework_twice_hint", who=L.who(st['rework_by'])))
    return ev, notes


def append(proj: Project, evs: Dict[str, List[Dict[str, Any]]], obj: str, ev: Dict[str, Any], a: Dict[str, Any]) -> None:
    """在已持有的锁里给事件发号、追加一行，并更新内存里的 evs。"""
    rows = evs.setdefault(obj, [])
    ev["v"] = EVENT_V
    ev["seq"] = len(rows) + 1
    ev["project_seq"] = 1 + max([r.get("project_seq", 0) for rs in evs.values() for r in rs] or [0])
    ev["time"] = iso(now_dt())
    ev.setdefault("writer", a.get("writer") or (Writer.LEAD if ev["from"] in MANAGERS else Writer.MEMBER))
    line = json.dumps({k: ev[k] for k in FIELD_ORDER if k in ev}, ensure_ascii=False)
    with open(proj.flow_dir / f"{obj}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    rows.append(ev)


# ---------- 新建卡片 ----------

def next_id(proj: Project, kind: str, goal: Optional[str]) -> str:
    states, _, _ = replay_all(proj)
    ids = set(states)
    for f in proj.card_files():
        ids |= set(re.findall(r"^#{1,2}\s*(" + ID_RE + r")\b", f.read_text(encoding="utf-8"), re.M))
    if kind in (Kind.GOAL, Kind.ISSUE):
        pre = "G" if kind == Kind.GOAL else "I"
        n = max([int(x[1:]) for x in ids if re.fullmatch(pre + r"\d+", x)] or [0]) + 1
        return f"{pre}{n:03d}"
    if goal:
        n = max([int(x.split("-T")[1]) for x in ids if re.fullmatch(re.escape(goal) + r"-T\d+", x)] or [0]) + 1
        return f"{goal}-T{n}"
    n = max([int(x[1:]) for x in ids if re.fullmatch(r"T\d+", x)] or [0]) + 1
    return f"T{n:03d}"


slug = P.slug



def block(name: str, obj: str, body: str) -> str:
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"<!-- flow:{name} {obj} {VIEW} sha={sha(body)} -->\n{body}<!-- /flow -->"


def new_card_text(kind: str, obj: str, title: str, small: bool, L: Optional["i18n.Pack"] = None) -> str:
    L = L or i18n.pack()
    h1, h2 = ("##", "###") if small else ("#", "##")
    H, F = L.heading, L.field
    if kind == Kind.ISSUE:
        return (f"# {obj} {title}\n{block(Block.HEADER, obj, '')}\n\n"
                f"## {H(Section.QUESTION)}\n- {L.kv(F(Field.DECIDE))}\n- {L.kv(F(Field.CONTEXT))}\n- {L.kv(F(Field.REFERENCES))}\n- {L.kv(F(Field.OPTIONS))}\n\n"
                f"## {H(Section.ATTENDEES)}\n{block(Block.ATTENDEES, obj, '')}\n\n"
                f"## {H(Section.TRANSCRIPT)}\n{L.t('card.transcript_note')}\n{block(Block.TRANSCRIPT, obj, '')}\n\n"
                f"## {L.t('card.summary_heading', summary=H(Section.SUMMARY))}\n- {L.kv(F(Field.CONSENSUS))}\n- {L.kv(F(Field.DISAGREEMENTS), L.t('card.disagreements_hint'))}\n- {L.kv(F(Field.RECOMMENDATION))}\n\n"
                f"## {H(Section.RULING)}\n{block(Block.RULING, obj, '')}\n")
    if kind == Kind.GOAL:
        return (f"{h1} {obj} {title}\n{block(Block.HEADER, obj, '')}\n\n"
                f"{h2} {H(Section.WANT)}\n- {L.kv(F(Field.WANT))}\n- {L.kv(F(Field.CRITERIA))}\n\n"
                f"{h2} {H(Section.STAGES)}\n{block(Block.STAGES, obj, '')}\n\n{h2} {H(Section.CHANGES)}\n{block(Block.CHANGES, obj, '')}\n\n"
                f"{h2} {H(Section.ISSUES)}\n{block(Block.ISSUES, obj, '')}\n")
    return (f"{h1} {obj} {title}\n{block(Block.HEADER, obj, '')}\n\n"
            f"{h2} {H(Section.HISTORY)}\n{L.t('card.history_note')}\n{block(Block.HISTORY, obj, '')}\n\n"
            f"{h2} {H(Section.HANDOFF)}\n" + "".join(f"- {L.kv(F(k))}\n" for k in HANDOFF_FIELDS) + f"\n{h2} {H(Section.NOTES)}\n")


def create(proj: Project, kind: str, a: Dict[str, Any]) -> Tuple[str, Path]:
    L = proj.L
    with locked(proj):
        obj = next_id(proj, kind, a.get("goal"))
        states, _, _ = replay_all(proj)
        if kind == Kind.TASK and a.get("goal"):
            g = states.get(a["goal"])
            if not g:
                raise hard(L.t("flow.goal_missing", goal=a['goal']))
            if a.get("stage") is None:
                raise hard(L.t("flow.task_needs_stage"))
            if a["stage"] not in [s.get("order") for s in g["stages"]]:
                raise hard(L.t("flow.task_stage_missing", goal=a['goal'], stage=a['stage']))
            if g["state"] in (S.DONE, S.CANCELLED):
                raise hard(L.t("flow.goal_closed_no_task", goal=a['goal'], state=L.st(g['state'])))
        if kind == Kind.TASK and not a.get("goal"):
            raise hard(L.t("flow.task_needs_goal"))
        ev = plan(proj, states, obj, E.CREATE, a)
        text = new_card_text(kind, obj, a.get("title", ""), proj.small, L)
        if kind == Kind.TASK and a.get("handoff"):
            text = set_handoff(text, a["handoff"], L)
        if kind == Kind.ISSUE:
            path = proj.collab / P.ISSUES / P.card_name(obj, a.get("title", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            write_if_changed(path, text)
        elif proj.small:
            path = proj.collab / (P.GOALS_MD if kind == Kind.GOAL else P.TASKS_MD)
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            m = re.search(r"^## " + ID_RE, old, re.M)
            new = old[: m.start()] + text + "\n" + old[m.start():] if m else old.rstrip("\n") + "\n\n" + text
            write_if_changed(path, new)
        else:
            path = (proj.collab / P.GOALS / P.goal_card(obj, a.get("title", "")) if kind == Kind.GOAL
                    else proj.collab / P.TASKS / P.card_name(obj, a.get("title", "")))
            write_if_changed(path, text)
    ev2, _ = record(proj, obj, E.CREATE, a)
    return obj, path


def heading_re(code: str) -> str:
    """一个小节的标题（中英两种写法）的正则片段。"""
    return "(?:" + "|".join(re.escape(h) for h in i18n.headings(code)) + ")"


def set_handoff(text: str, fields: Dict[str, Any], L: Optional["i18n.Pack"] = None) -> str:
    """把卡片文本里「交接」一节换成给定字段；备注和生成块不动。"""
    m = re.search(r"^(#{2,3}) " + heading_re(Section.HANDOFF) + r"\s*$", text, re.M)
    if not m:
        raise hard(i18n.pack().t("flow.no_handoff_section", section=i18n.pack().heading("handoff")))
    rest = text[m.end():]
    n = re.search(r"^#{1,%d}\s" % len(m.group(1)), rest, re.M)
    tail = rest[n.start():] if n else ""
    return text[:m.end()] + "\n" + handoff_text(fields, L) + "\n" + ("\n" + tail if tail else "")


def card_path(proj: Project, obj: str) -> Optional[Path]:
    for f in proj.card_files():
        if re.search(r"^#{1,2}\s*" + re.escape(obj) + r"(?![-\w]).*$", f.read_text(encoding="utf-8"), re.M):
            return f
    return None


FRAME_KEYS = {"阶段": "stages", "序": "order", "名称": "name", "类型": "type", "前置": "depends_on", "可并行": "parallel", "任务": "tasks",
              "人选": "people", "产出": "output", "通过条件": "pass_condition", "执行": "executor", "确认": "reviewer", "来自": "from",
              "键": "key", "标题": "title"}


def normalize_frame(spec: Dict[str, Any]) -> Dict[str, Any]:
    """框架 JSON：键认英文和中文（阶段、序、名称……，交接字段写 目的、交付物 或 purpose、deliverables），阶段类型认代码和显示名。"""
    def keys(d):
        out = {}
        for k, v in d.items():
            code = FRAME_KEYS.get(k) or (k if k in FRAME_KEYS.values() else field_code(k))
            out[code] = v
        return out
    top = keys(spec)
    stages = []
    for s in top.get("stages") or []:
        s = keys(s) if isinstance(s, dict) else s
        if isinstance(s, dict):
            if s.get("type") is not None:
                s["type"] = i18n.code_of("stage_type", s["type"]) or s["type"]
            s["tasks"] = [keys(x) if isinstance(x, dict) else x for x in s.get("tasks") or []]
        stages.append(s)
    if "stages" in top:
        top["stages"] = stages
    return top


def frame(proj: Project, goal: str, spec: Dict[str, Any], a: Dict[str, Any]) -> Dict[str, Any]:
    """搭框架、改框架：一次写好阶段和全部任务卡。可重复运行，这就是改图的方式。按「键」认任务（没写就用标题）。"""
    L = proj.L
    spec = normalize_frame(spec)
    with locked(proj):
        states, evs, _ = replay_all(proj)
        g = states.get(goal)
        if not g or g["kind"] != Kind.GOAL:
            raise hard(L.t("flow.goal_missing", goal=goal))
        if g["state"] in (S.DONE, S.CANCELLED, S.PENDING_ACCEPTANCE):
            raise hard(L.t("flow.plan_locked", goal=goal, state=L.st(g['state'])))
        raw = spec.get("stages")
        if not isinstance(raw, list) or not raw:
            raise hard(L.t("flow.plan_no_stages"))
        stages = [{k: v for k, v in s.items() if k != "tasks"} for s in raw]
        check_stage_list(stages)
        stages = plan_stages(proj, stages)
        # 校验：每个阶段至少一张卡；键不重复；前置只能写排在前面的任务
        items, seen = [], {}
        for s in raw:
            if not s.get("tasks"):
                raise hard(L.t("flow.plan_stage_empty", order=s.get('order'), name=s.get('name', '')))
            for t in s["tasks"]:
                title = str(t.get("title", "")).strip()
                if not title or not t.get("executor"):
                    raise hard(L.t("flow.plan_task_fields", order=s.get('order')))
                key = str(t.get("key") or title)
                if key in seen:
                    raise hard(L.t("flow.plan_dup_key", key=key))
                doer = proj.actor(t["executor"]) or t["executor"]
                checker = proj.actor(t.get("reviewer") or LEAD) or t.get("reviewer")
                for w in (doer, checker):
                    if w not in MANAGERS and not proj.is_member(w):
                        raise hard(L.t("flow.plan_unknown_person", title=title, who=w))
                if doer == checker and doer != LEAD:
                    raise hard(L.t("flow.plan_self_review", title=title, who=doer))
                for p in t.get("depends_on", []):
                    if str(p) not in seen:
                        raise hard(L.t("flow.plan_dep_order", title=title, dep=p))
                seen[key] = True
                items.append({"key": key, "title": title, "stage": s["order"], "planned_executor": doer, "planned_reviewer": checker,
                              "depends_on_keys": [str(p) for p in t.get("depends_on", [])], "merged_from": list(t.get("from") or []),
                              "handoff": {k: t[k] for k in HANDOFF_FIELDS if k in t}})
        live = goal_tasks(states, goal)
        existing = {(t["key"] or t["title"]): t for t in live}
        spare = sorted((t["id"] for t in states.values() if t["kind"] == Kind.TASK and t["goal"] == goal and t["state"] == S.WITHDRAWN),
                       key=id_key)  # 撤下的草稿编号，新卡先用它们，编号不断
        # 批准前框架只是草稿：按位置给编号，第 i 张卡用第 i 个编号，整版重写；多出来的旧卡撤下，不记取消
        draft = g["state"] in (S.DRAFT, S.PENDING_APPROVAL) and not g["approved_plan"]
        basis = a.get("basis") or L.t("flow.plan_basis", goal=goal)
        base = {"from": LEAD, "writer": a.get("writer") or LEAD}
        changes: List[str] = []
        ids: Dict[str, str] = {}
        def refresh(obj):
            states[obj] = replay(obj, evs[obj])
        version = g["plan_version"] + 1
        old_ref = {k: t["id"] for k, t in existing.items()}
        def origin(item):
            src = [old_ref.get(str(x), str(x)) for x in item["merged_from"]]
            return L.t("flow.merged_from", src=L.join(src)) if src else ""
        def add(item, need, tid=None):
            obj = tid or next_id(proj, Kind.TASK, goal)
            text = set_handoff(new_card_text(Kind.TASK, obj, item["title"], proj.small, L), item["handoff"], L)
            write_if_changed(proj.collab / P.TASKS / P.card_name(obj, item["title"]), text)
            b = {**base, "goal": goal, "stage": item["stage"], "key": item["key"], "title": item["title"], "basis": basis,
                 "planned_executor": item["planned_executor"], "planned_reviewer": item["planned_reviewer"], "depends_on": need}
            edge = E.REDRAFT if tid else E.CREATE
            append(proj, evs, obj, plan(proj, states, obj, edge, b), b)
            refresh(obj)
            changes.append(L.t("flow.plan_added", obj=obj, title=item['title'], executor=L.who(item['planned_executor']), reviewer=L.who(item['planned_reviewer'])) + origin(item))
            return obj
        def update(old, item, need):
            tid = old["id"]
            same = (old["key"] or old["title"]) == item["key"]
            diff, what = {}, []
            if not same:
                diff["key"] = item["key"]
            if old["title"] != item["title"]:
                diff["title"] = item["title"]
                what.append(L.t("flow.what.title"))
            if old["stage"] != item["stage"]:
                diff["task_stage"] = item["stage"]
                what.append(L.t("flow.what.stage"))
            if old["planned_executor"] != item["planned_executor"]:
                diff["planned_executor"] = item["planned_executor"]
                what.append(L.t("flow.what.executor", old=L.who(old['planned_executor']) or '—', new=L.who(item['planned_executor'])))
            if old["planned_reviewer"] != item["planned_reviewer"]:
                diff["planned_reviewer"] = item["planned_reviewer"]
                what.append(L.t("flow.what.reviewer", old=L.who(old['planned_reviewer']) or '—', new=L.who(item['planned_reviewer'])))
            if list(old["depends_on"]) != need:
                diff["depends_on"] = need
                what.append(L.t("flow.what.deps"))
            path = card_path(proj, tid)
            cur_fields = handoff_fields(card_section(proj, tid, Section.HANDOFF))
            # 同一张卡：框架文件没写的字段保留卡片原样；换成了另一张卡（批准前按位置复用编号）：整版换掉
            given = {k: str(v).strip() for k, v in item["handoff"].items()}
            merged = {**cur_fields, **given} if same else given
            if path:
                text = path.read_text(encoding="utf-8")
                if any(merged.get(k, "") != cur_fields.get(k, "") for k in HANDOFF_FIELDS):
                    text = set_handoff(text, merged, L)
                    what.append(L.t("flow.what.content"))
                if "title" in diff:  # 卡片标题跟着改；批准前文件名也跟着改
                    text = re.sub(r"^(#{1,2})\s*" + re.escape(tid) + r"(?![-\w]).*$", lambda m: f"{m.group(1)} {tid} {item['title']}",
                                  text, count=1, flags=re.M)
                write_if_changed(path, text)
                if "title" in diff and draft and not proj.small and path.parent == proj.collab / P.TASKS:
                    dest = path.with_name(P.card_name(tid, item["title"]))
                    if dest != path and not dest.exists():
                        path.rename(dest)
            if not what and not diff:
                return
            if not what:
                what.append(L.t("flow.what.key"))
            b = {**base, **diff, "note": L.t("flow.plan_version_note", version=version, what=L.join(what)), "changes": what}
            append(proj, evs, tid, plan(proj, states, tid, E.CHANGE, b), b)
            refresh(tid)
            if same:
                changes.append(L.t("flow.plan_changed", obj=tid, title=item['title'], what=L.join(what)) + origin(item))
            else:
                changes.append(L.t("flow.plan_renamed", obj=tid, title=item['title'], old=old['title']) + origin(item))
        if draft:
            for t in live:
                if t["state"] != S.PLANNED:
                    raise hard(L.t("flow.plan_started_early", obj=t['id'], state=L.st(t['state'])))
            slots = sorted([t["id"] for t in live] + spare, key=id_key)
            if len(items) < len(live):  # 合并或删减时写明张数；只加卡时逐条「新增」已经够清楚
                changes.append(L.t("flow.plan_count", old=len(live), new=len(items)))
            for i, item in enumerate(items):
                need = [ids[k] for k in item["depends_on_keys"]]
                tid = slots[i] if i < len(slots) else None
                if tid and states[tid]["state"] != S.WITHDRAWN:
                    ids[item["key"]] = tid
                    update(states[tid], item, need)
                else:
                    ids[item["key"]] = add(item, need, tid)
            for tid in slots[len(items):]:
                if states[tid]["state"] == S.WITHDRAWN:
                    continue
                b = {**base, "note": L.t("flow.plan_dropped_draft", version=version)}
                append(proj, evs, tid, plan(proj, states, tid, E.WITHDRAW, b), b)
                refresh(tid)
                path = card_path(proj, tid)
                if path and not proj.small and path.parent == proj.collab / P.TASKS:
                    path.unlink()
                changes.append(L.t("flow.plan_withdrawn", obj=tid, title=states[tid]['title']))
        else:
            for item in items:
                need = [ids[k] for k in item["depends_on_keys"]]
                old = existing.get(item["key"])
                if old:
                    ids[item["key"]] = old["id"]
                    update(old, item, need)
                else:
                    ids[item["key"]] = add(item, need, spare.pop(0) if spare else None)
            for key, old in existing.items():
                if key in seen:
                    continue
                if old["state"] not in (S.PLANNED, S.APPROVED):
                    raise hard(L.t("flow.plan_cant_drop", obj=old['id'], state=L.st(old['state'])))
                b = {**base, "note": L.t("flow.plan_dropped_task", version=version)}
                append(proj, evs, old["id"], plan(proj, states, old["id"], E.CANCEL, b), b)
                refresh(old["id"])
                changes.append(L.t("flow.plan_cancelled", obj=old['id'], title=old['title']))
        if g["stages"] and [dict(s) for s in g["stages"]] != stages:
            changes.insert(0, L.t("flow.plan_stages_changed"))
        if not changes and g["plan_version"]:
            return {"version": g["plan_version"], "changes": []}
        b = {**base, "stage": stages, "plan_version": version, "diff": changes or [L.t("flow.plan_built")],
             "note": a.get("note") or L.t("flow.plan_version", version=version), "changes": [L.t("flow.what.plan")]}
        if a.get("basis"):
            b["basis"] = a["basis"]
        append(proj, evs, goal, plan(proj, states, goal, E.CHANGE, b), b)
        render_all(proj)
        return {"version": version, "changes": b["diff"]}


def archive_goal(proj: Project, goal: str) -> List[str]:
    """目标卡移到 collab/归档/目标/，目标自己的目录（问题.md、方案.md 等）一起移。返回移了什么（相对项目根）。"""
    L = proj.L
    with locked(proj):
        states, _, _ = replay_all(proj)
        g = states.get(goal)
        if not g or g["kind"] != Kind.GOAL:
            raise hard(L.t("flow.goal_missing", goal=goal))
        if proj.small:
            raise hard(L.t("flow.archive_single"))
        card = card_path(proj, goal)
        live, arch = proj.collab / P.GOALS, proj.collab / P.ARCHIVE / P.GOALS
        moved: List[str] = []
        if card and card.parent == live:
            if g["state"] not in (S.DONE, S.CANCELLED):
                raise hard(L.t("flow.archive_not_done", goal=goal, state=L.st(g['state'])))
            arch.mkdir(parents=True, exist_ok=True)
            if (arch / card.name).exists():
                raise hard(L.t("flow.exists", path=proj.rel(arch / card.name)))
            card.rename(arch / card.name)
            moved.append(f"{proj.rel(card)} → {proj.rel(arch / card.name)}")
        elif not card or card.parent != arch:
            raise hard(L.t("flow.no_goal_card", goal=goal))
        src, dst = live / goal, arch / goal
        if src.is_dir():
            if dst.exists():
                raise hard(L.t("flow.exists_not_moved", path=proj.rel(dst)))
            src.rename(dst)
            moved.append(f"{proj.rel(src)}/ → {proj.rel(dst)}/")
        return moved


def start_self(proj: Project, obj: str, a: Dict[str, Any]) -> None:
    """总管自己执行：一条命令写派发和接手。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["kind"] != Kind.TASK:
        raise hard(proj.L.t("flow.not_task", obj=obj))
    base = {"from": LEAD, "writer": a.get("writer") or LEAD}
    record(proj, obj, E.DISPATCH, {**base, "to": LEAD, "note": a.get("note") or proj.L.t("flow.self_execute")})
    record(proj, obj, E.PICK_UP, {**base, "note": proj.L.t("flow.start_note")})


# ---------- 投影：视图模型 ----------

def holds(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out, cur = [], None
    for ev in rows:
        if ev.get("edge") in SPECIAL or (ev.get("edge") == E.PICK_UP):
            continue
        to = ev.get("to")
        who = None if to in (None, NONE) else to
        if cur and cur["who"] == who:
            continue
        if cur:
            cur["end_seq"], cur["end_time"] = ev["project_seq"], ev["time"]
            out.append(cur)
            cur = None
        if who:
            cur = {"who": who, "start_seq": ev["project_seq"], "start_time": ev["time"], "end_seq": None, "end_time": None}
    if cur:
        out.append(cur)
    return out


def handoffs(rows: List[Dict[str, Any]], states_sk: Dict[str, Any]) -> List[Dict[str, Any]]:
    """每条改状态的事件之后，这个对象「谁交过来、现在在谁手里、什么状态」的切面（关系图和它的回放用）。
    持有人取法和「当前」一致：接手不换持有人，交过来的人仍是上一条换持有人的事件的发起方。"""
    out, giver, holder = [], None, None
    for ev in rows:
        if ev.get("edge") in SPECIAL + MESSAGES:
            continue
        if ev.get("edge") not in KEEP_HOLDER:
            giver = ev.get("from")
            holder = None if ev.get("to") in (None, NONE) else ev.get("to")
        state = ev.get("to_state", "")
        out.append({"project_seq": ev["project_seq"], "time": ev["time"], "edge": ev["edge"], "from": giver, "holder": holder,
                    "state": state, "category": states_sk.get(state, {}).get("category", "")})
    return out


def trunk_marks(rows: List[Dict[str, Any]], passed: bool) -> Dict[int, int]:
    """主干槽位：建立、派发、接手取首次；交付取最后一次通过确认之前那次；确认取最后一次且结果为通过。返回 {项目序: 槽位}。"""
    marks: Dict[int, int] = {}
    def first(edge):
        return next((r for r in rows if r.get("edge") == edge), None)
    for slot, edge in enumerate((E.CREATE, E.DISPATCH, E.PICK_UP)):
        r = first(edge)
        if r:
            marks[r["project_seq"]] = slot
    ok = [r for r in rows if r.get("edge") == E.REVIEW and r.get("result") == Result.PASS]
    final = ok[-1] if ok and passed else None
    deliveries = [r for r in rows if r.get("edge") == E.DELIVER and (not final or r["project_seq"] < final["project_seq"])]
    if deliveries:
        marks[deliveries[-1]["project_seq"]] = 3
    if final:
        marks[final["project_seq"]] = 4
    return marks


def view(proj: Project) -> Dict[str, Any]:
    states, evs, probs = replay_all(proj)
    render_rule = proj.skeleton(Skel.RENDER)
    fixed = render_rule["fixed_participants"]
    eff = {obj: [e for e in st["events"]] for obj, st in states.items()}
    tasks, goals = [], []
    for obj in sorted(states, key=id_key):
        st = states[obj]
        if st["kind"] != Kind.TASK:
            continue
        rows = eff[obj]
        marks = trunk_marks(rows, st["state"] == S.PASSED and st["pass_valid"])
        sk = proj.skeleton(Skel.TASK)
        last_confirm = next((r for r in reversed(rows) if r.get("edge") == E.REVIEW), None)
        tasks.append({
            "id": obj, "title": st["title"], "goal": st["goal"], "stage": st["stage"], "state": st["state"],
            "category": sk["states"].get(st["state"], {}).get("category", ""), "holder": st["holder"], "executor": st["executor"],
            "reviewer": st["reviewer"], "rework_count": st["rework_count"], "self_reviewed": st["self_reviewed"],
            "key": st["key"], "planned_executor": st["planned_executor"], "planned_reviewer": st["planned_reviewer"], "depends_on": st["depends_on"],
            "content": handoff_fields(card_section(proj, obj, Section.HANDOFF)),
            "comments": [{"time": r.get("time"), "note": r.get("note", ""), "project_seq": r.get("project_seq")} for r in st["comments"]],
            "conclusion": (last_confirm or {}).get("note", ""),
            "request_seq": next((r["project_seq"] for r in rows if r.get("edge") == E.CREATE and is_quote(r.get("basis"), st["goal"])), None),
            "trunk": [{"slot": marks[r["project_seq"]], "project_seq": r["project_seq"], "edge": r["edge"]} for r in rows if r["project_seq"] in marks],
            "branches": [{"project_seq": r["project_seq"], "edge": r["edge"], "from": r.get("from"), "to": r.get("to"), "attached_to": max([s for q, s in marks.items() if q < r["project_seq"]] or [0])}
                   for r in rows if r["project_seq"] not in marks],
            "holds": holds(rows),
            "handoffs": handoffs(rows, sk["states"]),
        })
    by_task = {t["id"]: t for t in tasks}
    for obj in sorted(states, key=id_key):
        st = states[obj]
        if st["kind"] != Kind.GOAL:
            continue
        stages = stage_table(proj, st, states)
        mine = [t for t in tasks if t["goal"] == obj]
        gcls = proj.skeleton(Skel.GOAL)["states"].get(st["state"], {}).get("category", "")
        basis_of = {t["id"]: next((r.get("basis") or "" for r in eff[t["id"]] if r.get("edge") == E.CREATE), "") for t in mine}
        gone = [t["id"] for t in mine if dropped_draft(st, states[t["id"]])]
        struct = structure(st, stages, by_task, eff[obj], basis_of, [r["project_seq"] for o in gone for r in eff[o]])
        evrows = event_rows(states, [obj] + [t["id"] for t in mine], eff, by_task,
                            {x for s in stages for x in s["added_after_approval"]})
        for r in evrows:
            v = struct["merged"].get(str(r["project_seq"]))
            if r["edge"] == E.CREATE and v is not None:
                r["same_plan_version"] = v
        goals.append({"id": obj, "title": st["title"], "type": st["type"], "state": st["state"],
                      "category": gcls, "draft_stage": draft_stage(st), "files": goal_files(proj, obj), "open_questions": open_questions(proj, obj),
                      "holder": st["holder"], "workdir": workdir(proj, obj), "stages": stages,
                      "issues": [i for i in sorted(states, key=id_key) if states[i]["kind"] == Kind.ISSUE and states[i]["goal"] == obj],
                      "handoffs": handoffs(eff[obj], proj.skeleton(Skel.GOAL)["states"]),
                      "participants": participants(fixed, stages, [e for o in [obj] + [t["id"] for t in mine] for e in eff.get(o, [])]),
                      "events": evrows,
                      "structure": struct,
                      "plan_version": st["plan_version"], "round_changes": st["round_changes"], "approved_version": (st["approved_plan"] or {}).get("version"),
                      "drift": approved_diff(proj, st, states),
                      "comments": open_comments(st, states, live=gcls not in (Category.DONE, S.CANCELLED))})
    loose = [t["id"] for t in tasks if not t["goal"]]
    loose_group = None
    if loose:
        loose_group = {"id": "—", "title": T("view.loose_tasks"), "participants": participants(fixed, [], [e for o in loose for e in eff[o]]),
                       "events": event_rows(states, loose, eff, by_task)}
    current = []
    for t in tasks:
        if t["category"] == Category.DONE or not t["holds"]:
            continue
        rows = [r for r in eff[t["id"]] if r.get("edge") not in KEEP_HOLDER]
        last = rows[-1] if rows else None
        current.append({"object": t["id"], "from": (last or {}).get("from"), "to": t["holder"], "state": t["state"],
                        "category": t["category"], "project_seq": (last or {}).get("project_seq")})
    all_seq = [e.get("project_seq", 0) for rs in evs.values() for e in rs]
    return {
        "spec": VIEW, "upto": max(all_seq or [0]),
        "titles": render_rule.get("titles", {}),
        "goals": goals, "loose": loose_group, "tasks": [t for t in tasks if t["state"] != S.WITHDRAWN], "current": current,
        "issues": [issue_view(proj, states[o]) for o in sorted(states, key=id_key) if states[o]["kind"] == Kind.ISSUE],
        "decisions": decisions(proj, states, eff),
        "checks": [p for p in check(proj, now=None) if p["level"] == "error"],
    }


def approval_note(r: Dict[str, Any]) -> str:
    """看板批准时写的批注：依据是「总裁在看板批准第 N 版框架：批注」，没有批注返回空。"""
    b = str(r.get("basis") or "").strip()
    for lang in i18n.LANGS:
        L = i18n.pack(lang)
        pat = re.escape(L.t("flow.approve_basis", version="\0")).replace(re.escape("\0"), r"\d+") + re.escape(L.t("sep.colon").strip()) + r"\s*(.+)"
        m = re.fullmatch(pat, b, re.S)
        if m:
            return m.group(1).strip()
    return ""


def open_comments(goal: Dict[str, Any], states: Dict[str, Dict[str, Any]], live: bool = True) -> List[Dict[str, Any]]:
    """总裁的意见里，最近一次改框架之后提的（改框架就算处理过了）；再加上带批注的批准：
    批注在总管于目标上记一条进展（发起为总管、不是派活脚本代写）之前一直算没处理。"""
    changed = max([r.get("project_seq", 0) for r in goal["events"] if r.get("edge") == E.CHANGE and r.get("plan_version")] or [0])
    out = []
    for o in [goal] + goal_tasks(states, goal["id"]):
        out += [{"object": o["id"], "note": r.get("note", ""), "time": r.get("time"), "project_seq": r.get("project_seq")}
                for r in o["comments"] if r.get("project_seq", 0) > changed]
    if live:
        for r in goal["events"]:
            note = approval_note(r) if r.get("edge") == E.APPROVE else ""
            if not note:
                continue
            done = any(q.get("edge") == E.PROGRESS and q.get("from") == LEAD and q.get("writer") != Writer.DISPATCHER
                       and q.get("project_seq", 0) > r.get("project_seq", 0) for q in goal["events"])
            if not done:
                out.append({"object": goal["id"], "note": note, "time": r.get("time"), "project_seq": r.get("project_seq"), "kind": "批准批注"})
    return sorted(out, key=lambda x: x["project_seq"])


def speech_types(rows: List[Dict[str, Any]]) -> List[str]:
    """发言类型由投影推出（不存）：PASS；私下；总裁自选的类型，否则点了名是「提问」、没点名是「发言」；总管是「说明」；
    成员第一次开口是「立场」，被点名后再开口是「回答」（立场、私下、PASS 不算回答过点名），其余是「补充」。"""
    out, spoken, asked = [], set(), {}
    for r in rows:
        who = r.get("from")
        if r.get("edge") == E.PASS:
            kind = Speech.PASS
        elif r.get("private"):
            kind = Speech.PRIVATE
        elif who == BOSS:
            kind = r.get("type") or (Speech.QUESTION if r.get("mentions") else Speech.POST)
        elif who == LEAD:
            kind = Speech.NOTE
        elif who not in spoken:
            kind = Speech.POSITION
        else:
            kind = Speech.ANSWER if asked.get(who) else Speech.FOLLOWUP
        if who not in MANAGERS:
            spoken.add(who)
            if kind in (Speech.ANSWER, Speech.FOLLOWUP):  # 立场（第 1 轮看不到别人）、私下、PASS 都不算回答了之前的点名
                asked[who] = False
        for w in r.get("mentions", []):
            asked[w] = True
        out.append(kind)
    return out


def issue_view(proj: Project, st: Dict[str, Any]) -> Dict[str, Any]:
    """一个议题的视图：卡头、与会、总结和裁决（面板用），消息（对话页用），起止项目序（时序图里的议题框用）。"""
    sk = proj.skeleton(Skel.ISSUE)
    rows = st["events"]
    msgs = [r for r in rows if r.get("edge") in MESSAGES]
    kinds = speech_types(msgs)
    last = {e: next((r for r in reversed(rows) if r.get("edge") == e), None) for e in (E.SUMMARIZE, E.RULE)}
    seqs = [r["project_seq"] for r in rows if "project_seq" in r]
    return {
        "id": st["id"], "title": st["title"], "type": st["type"], "state": st["state"],
        "category": sk["states"].get(st["state"], {}).get("category", ""), "holder": st["holder"], "goal": st["goal"],
        "attendees": st["attendees"],
        "summary": {k: last[E.SUMMARIZE].get(k, "") for k in ("note", "options", "recommendation")} if last[E.SUMMARIZE] else None,
        "ruling": {k: last[E.RULE].get(k, "") for k in ("note", "basis")} if last[E.RULE] else None,
        "post_count": sum(1 for r in msgs if r["edge"] == E.POST),
        "start_seq": min(seqs or [0]), "end_seq": max(seqs or [0]),
        "messages": [{**{k: r[k] for k in ("project_seq", "seq", "edge", "from", "time", "body", "mentions", "private", "run", "session") if k in r},
                 "type": kind} for r, kind in zip(msgs, kinds)],
        "process": [{k: r[k] for k in ("project_seq", "seq", "edge", "from", "to", "from_state", "to_state", "time", "note", "override") if k in r}
               for r in rows if r.get("edge") not in MESSAGES],
    }


def participants(fixed: List[str], stages: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_in_rows = []
    for r in sorted(rows, key=lambda r: r.get("project_seq", 0)):
        for w in (r.get("from"), r.get("to")):
            if w and w != NONE and w not in seen_in_rows:
                seen_in_rows.append(w)
    order = list(fixed)
    for s in stages:
        for w in s["people"] + s.get("reviewers", []):
            if w not in order:
                order.append(w)
    planned = set(order)
    for w in seen_in_rows:
        if w not in order:
            order.append(w)
    return [{"name": w, "planned": w in planned, "appeared": w in seen_in_rows} for w in order]


def event_rows(states, objs, eff, by_task, unplanned=()) -> List[Dict[str, Any]]:
    out = []
    for o in objs:
        t = by_task.get(o)
        trunk = {m["project_seq"]: m["slot"] for m in (t["trunk"] if t else [])}
        goal = states[o]["id"] if states[o]["kind"] == Kind.GOAL else states[o]["goal"]
        for r in eff.get(o, []):
            row = {k: r[k] for k in ("project_seq", "object", "edge", "result", "from", "to", "from_state", "to_state", "time",
                                     "note", "basis", "evidence", "run", "session", "override", "writer") if k in r}
            if not str(row.get("basis") or "").strip():
                row.pop("basis", None)
            elif is_quote(row["basis"], goal):
                row["quote"] = True
            row["stage"] = states[o]["stage"]
            row["layer"] = Kind.GOAL if states[o]["kind"] == Kind.GOAL else Kind.TASK
            row["trunk"] = r["project_seq"] in trunk if t else False
            if o in unplanned:
                row["added_after_approval"] = True
            if t and r["project_seq"] in trunk:
                row["slot"] = trunk[r["project_seq"]]
            # 总裁的话落在总管名下的事件（总管代记的建立、变更），画成总裁 → 总管
            if row.get("quote") and ((row["edge"] == E.CREATE and o in unplanned and row["layer"] == Kind.TASK)
                                    or (row["edge"] == E.CHANGE and row["layer"] == Kind.GOAL)):
                row["draw"] = {"from": BOSS, "to": LEAD, "label": E.REQUEST if row["edge"] == E.CREATE else E.REQUEST_CHANGE}
            out.append(row)
    out.sort(key=lambda r: r["project_seq"])
    # 因果：总裁的退回和由它带来的新增任务，依据相同就互相标注
    for r in out:
        if r["edge"] == E.CREATE and r.get("draw") and r["layer"] == Kind.TASK:
            src = next((q for q in reversed(out) if q["project_seq"] < r["project_seq"] and is_boss_return(q)
                        and q["basis"].strip() == r["basis"].strip()), None)
            if src:
                r["caused_by"] = {"object": src["object"], "project_seq": src["project_seq"], "edge": src["edge"]}
                src.setdefault("caused", []).append({"object": r["object"], "project_seq": r["project_seq"]})
    return out


def decisions(proj: Project, states, eff) -> List[Dict[str, Any]]:
    """待你决定：所有持有人为总裁的未结束对象。每条取让总裁成为持有人的那条事件。"""
    out = []
    for obj in sorted(states, key=id_key):
        st = states[obj]
        if st["holder"] != BOSS or terminal(proj, st):
            continue
        # 议题只在待裁决时进收件箱（讨论中是总裁在主持）；框架会审并进所属目标的「批准框架」
        if st["kind"] == Kind.ISSUE and (st["state"] != S.PENDING_RULING or st["type"] == IssueType.REVIEW_MEETING):
            continue
        reviews = open_reviews(states, obj) if st["kind"] == Kind.GOAL and st["state"] == S.PENDING_APPROVAL else []
        if any(s["state"] != S.PENDING_RULING for s in reviews):
            continue  # 会审中，还不该批
        ev = next((r for r in reversed(eff[obj]) if r.get("to") == BOSS and r.get("edge") not in SPECIAL + MESSAGES), {})
        kind = {S.PENDING_APPROVAL: Pending.APPROVE_PLAN, S.PENDING_ACCEPTANCE: Pending.ACCEPTANCE, S.BLOCKED: Pending.BLOCKED,
                S.PENDING_RULING: Pending.RULING}.get(st["state"], st["state"])
        item = {"id": obj, "type": kind, "note": ev.get("note", ""), "options": ev.get("options", ""),
                "recommendation": ev.get("recommendation", ""), "raised_by": ev.get("from", ""), "project_seq": ev.get("project_seq")}
        if st["kind"] == Kind.GOAL and st["state"] == S.PENDING_APPROVAL:
            ts = goal_tasks(states, obj)
            item.update({"plan_version": st["plan_version"], "task_count": len(ts), "round_changes": st["round_changes"],
                         "people": sorted({t["planned_executor"] for t in ts if t["planned_executor"]}),
                         "owner_tasks": [t["id"] for t in ts if BOSS in (t["planned_executor"], t["planned_reviewer"])]})
        if reviews:
            item["reviews"] = [s["id"] for s in reviews]
        out.append(item)
    return out


# ---------- 检查 ----------

SEATS = (SeatClass.HOLDER, SeatClass.MANAGER, SeatClass.LEAD, SeatClass.OWNER, SeatClass.EXECUTOR, SeatClass.REVIEWER,
         SeatClass.SELF, SeatClass.NONE)



def check_skeletons(proj: Project) -> List[Dict[str, Any]]:
    """加载骨架时的检查：状态可达、能走到终止、终止态除「重开」外无出边、席位合法；阶段模板和渲染规约引用正确。"""
    out = []
    for lang, keys in i18n.missing_keys().items():  # 两种语言包逐键对齐
        out.append(issue("error", f"i18n/{lang}.json", None, T("check.i18n_missing", keys=i18n.pack().join(keys[:10]) + ("…" if len(keys) > 10 else ""))))
    for name in (Skel.TASK, Skel.GOAL, Skel.ISSUE):
        try:
            sk = proj.skeleton(name)
        except (FlowError, ValueError) as e:
            out.append(issue("error", f"core/skeletons/{skel_file(name)}.json", None, str(e)))
            continue
        out += check_skeleton(sk, f"core/skeletons/{skel_file(name)}.json")
    try:
        gsk = proj.skeleton(Skel.GOAL)
        for gtype in gsk.get("types", []):
            f = f"core/skeletons/{skel_file(Skel.goal_type(gtype))}.json"
            try:
                stages = [dict(x) for x in template_stages(proj, gtype)]
                check_stage_list(stages)
            except (FlowError, ValueError) as e:
                out.append(issue("error", f, None, getattr(e, "msg", str(e))))
    except (FlowError, ValueError):
        pass
    try:
        rr, tsk = proj.skeleton(Skel.RENDER), proj.skeleton(Skel.TASK)
        for w in rr.get("fixed_participants", []):
            if w not in MANAGERS:
                out.append(issue("error", "core/skeletons/render.json", None, T("check.fixed_participant", who=w)))
        for e in rr.get("trunk", []):
            if e not in tsk["edges"]:
                out.append(issue("error", "core/skeletons/render.json", None, T("check.trunk_edge", edge=e)))
    except (FlowError, ValueError):
        pass
    return out


def check_skeleton(sk: Dict[str, Any], f: str) -> List[Dict[str, Any]]:
    L = i18n.pack()
    out = []
    states, ends = set(sk["states"]), set(sk["terminal"])

    def targets(spec):
        return [r["to"] for r in spec.get("results", {}).values()] or [spec.get("to")]

    # 从初始往前走，能到哪些状态（@ 开头的「回到原状态」不算新状态）
    reach, changed = {sk["initial"]}, True
    while changed:
        changed = False
        for spec in sk["edges"].values():
            if any(x in reach for x in spec["from"]) or S.NONE in spec["from"]:
                for t in targets(spec):
                    if t and not t.startswith("@") and t not in reach:
                        reach.add(t)
                        changed = True
    for x in sorted(states - reach):
        out.append(issue("error", f, None, T("check.unreachable", state=L.st(x))))
    # 从终止往回走，哪些状态能走到终止
    back, changed = set(ends), True
    while changed:
        changed = False
        for spec in sk["edges"].values():
            if any(t in back for t in targets(spec) if t):
                for x in spec["from"]:
                    if x != S.NONE and x not in back:
                        back.add(x)
                        changed = True
    for x in sorted(states - back):
        out.append(issue("error", f, None, T("check.no_terminal", state=L.st(x))))
    for x in sorted(states - ends):
        if not any(x in spec["from"] for spec in sk["edges"].values()):
            out.append(issue("error", f, None, T("check.dead_end", state=L.st(x))))
    for e, spec in sk["edges"].items():
        for x in spec["from"]:
            if x != S.NONE and x not in states:
                out.append(issue("error", f, None, T("check.bad_from", edge=L.ed(e), state=L.st(x))))
            if x in ends and e not in REOPEN:
                out.append(issue("error", f, None, T("check.terminal_edge", state=L.st(x), reopen=L.ed(E.REOPEN), edge=L.ed(e))))
        for t in targets(spec):
            if t and not t.startswith("@") and t not in states:
                out.append(issue("error", f, None, T("check.bad_to", edge=L.ed(e), state=L.st(t))))
        seats = [spec.get("initiator"), spec.get("receiver")] + [r.get("receiver") for r in spec.get("results", {}).values()]
        for seat in seats:
            if seat and not seat.startswith("@") and seat not in SEATS:
                out.append(issue("error", f, None, T("check.bad_seat", edge=L.ed(e), seat=seat, seats=L.join(L.name('seat_class', s) for s in SEATS))))
    for e, spec in sk.get("message_events", {}).items():
        if e in sk["edges"] or e in SPECIAL:
            out.append(issue("error", f, None, T("check.message_clash", edge=L.ed(e))))
        for x in spec.get("allowed_in", []):
            if x not in states:
                out.append(issue("error", f, None, T("check.message_state", edge=L.ed(e), state=L.st(x))))
    return out


def check(proj: Project, now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
    """完整性和一致性检查。now 为 None 时不做跟时间有关的提醒（视图模型用，保证固定）。"""
    L = proj.L
    out = check_skeletons(proj)
    states, evs, probs = replay_all(proj)
    out += probs
    seen_global: Dict[int, str] = {}
    for obj in sorted(evs, key=id_key):
        f = f"{P.COLLAB}/{P.INTERNAL_FLOW}/{obj}.jsonl"
        rows = evs[obj]
        st = states[obj]
        for n, r in enumerate(rows, 1):
            if r.get("seq") != n:
                out.append(issue("error", f, n, T("check.seq", n=n, seq=r.get('seq'))))
            g = r.get("project_seq")
            if g in seen_global:
                out.append(issue("error", f, n, T("check.project_seq_dup", seq=g, other=seen_global[g])))
            elif g is not None:
                seen_global[g] = obj
            if r.get("override"):
                out.append(issue("warn", f, n, T("check.override", edge=L.ed(r.get('edge')), why=r['override'])))
        if rows and rows[0].get("edge") != E.CREATE:
            out.append(issue("error", f, 1, T("check.first_not_create", edge=L.ed(E.CREATE))))
        for p in st["problems"]:
            out.append(issue("error", f, None, p))
        try:
            sk = obj_skeleton(proj, st)
        except FlowError as e:
            out.append(issue("error", f, None, e.msg + T("check.keep_old_skeleton", path=f"{P.COLLAB}/{P.INTERNAL_PLANS}/{P.HISTORY}/")))
            continue
        ended = False
        for r in st["events"]:
            if ended and r.get("edge") not in SPECIAL + REOPEN:
                out.append(issue("error", f, None, T("check.after_terminal", seq=r.get('seq'), edge=L.ed(r.get('edge')))))
            if r.get("edge") in REOPEN:
                ended = False
            elif r.get("to_state") in sk["terminal"]:
                ended = True
        if st["state"] not in sk["terminal"] and st["state"] != S.NONE and not st["holder"]:
            out.append(issue("error", f, None, T("check.no_holder", obj=obj)))
        # 证据在交付时已验证过存在；任务结束后文件被归档或移动不算错误，只查没结束的
        for r in ([] if st["state"] in sk["terminal"] else st["events"]):
            for p in r.get("evidence", []) or []:
                path = Path(p).expanduser()
                if path.is_absolute():
                    if proj.root not in path.resolve().parents:
                        out.append(issue("warn", f, None, T("check.outside_evidence", path=p, dest=f"{P.COLLAB}/{P.OUTPUTS}/{obj}/")))
                    if not path.exists():
                        out.append(issue("error", f, None, T("flow.no_evidence", path=p)))
                elif not (proj.root / p).exists():
                    out.append(issue("error", f, None, T("flow.no_evidence", path=p)))
        if st["kind"] == Kind.TASK and st["goal"]:
            g = states.get(st["goal"])
            if not g:
                out.append(issue("error", f, None, T("flow.goal_missing", goal=st['goal'])))
            elif g["state"] in (S.DRAFT, S.PENDING_APPROVAL) and st["state"] not in (S.PLANNED, S.APPROVED, S.CANCELLED, S.WITHDRAWN):
                out.append(issue("error", f, None, T("check.dispatched_early", goal=g['id'])))
        if st["kind"] == Kind.GOAL and st["state"] in (S.ACTIVE, S.PENDING_ACCEPTANCE, S.DONE):
            table = stage_table(proj, st, states)
            for s in table:
                if not s["people"]:
                    out.append(issue("error", f, None, T("check.stage_no_people", order=s['order'])))
                if not s["tasks"] and st["state"] in (S.PENDING_ACCEPTANCE, S.DONE):
                    out.append(issue("error", f, None, T("flow.gap_stage_empty", order=s['order'], name=s['name'])))
                if s["invalid"]:
                    out.append(issue("warn", f, None, T("check.stage_invalid", order=s['order'])))
                if s["state"] == StageStatus.READY and not s["tasks"]:
                    out.append(issue("warn", f, None, T("check.stage_ready", order=s['order'], name=s['name'])))
            if st["type"]:
                try:
                    tmpl = template_stages(proj, st["type"])
                    inst = [s for s in st["stages"] if s.get("type") != StageType.ACCEPTANCE]
                    if stage_shape(inst) != stage_shape(tmpl) and not st["diff_reason"]:
                        out.append(issue("error", f, None, T("check.unregistered_diff", template=f"{L.name('kind', Kind.GOAL)}-{L.name('goal_type', st['type'])}", change=L.ed(E.CHANGE))))
                except FlowError:
                    pass
        if st["kind"] == Kind.ISSUE and st["goal"] and not (states.get(st["goal"]) or {}).get("events"):
            out.append(issue("error", f, None, T("check.issue_goal_missing", goal=st['goal'])))
        if st["kind"] == Kind.TASK:
            msg = trunk_problem(st, sk)
            if msg:
                out.append(issue("error", f, None, msg))
        if st["rework_count"] == 2:
            out.append(issue("warn", f, None, T("check.rework_twice", who=L.who(st['rework_by']))))
    for obj, st in sorted(states.items(), key=lambda kv: id_key(kv[0])):  # 目标卡归档了，它的目录要一起走
        if st["kind"] == Kind.GOAL and (proj.collab / P.GOALS / obj).is_dir():
            card = card_path(proj, obj)
            if card and card.parent == proj.collab / P.ARCHIVE / P.GOALS:
                out.append(issue("error", f"{P.COLLAB}/{P.GOALS}/{obj}", None,
                                 T("check.goal_dir_left", goals=P.GOALS, obj=obj, dest=f"{P.ARCHIVE}/{P.GOALS}/{obj}/")))
    out += check_blocks(proj)
    out += check_progress(proj, states)
    if now is not None:
        out += check_time(proj, states, now)
    return out


def trunk_problem(st: Dict[str, Any], sk: Dict[str, Any]) -> str:
    """任务要能归约成同一条主干：主干节点按 建立 → 派发 → 接手 → 交付 → 确认 的顺序出现、不跳格；已通过的五格齐全。"""
    passed = st["state"] == S.PASSED and st["pass_valid"]
    marks = trunk_marks(st["events"], passed)
    slots = [marks[q] for q in sorted(marks)]
    if slots != list(range(len(slots))):
        return T("check.trunk_reduce", obj=st['id'], slots=slots)
    if passed and len(slots) != 5:
        return T("check.trunk_short", obj=st['id'], n=len(slots))
    return ""


def check_blocks(proj: Project) -> List[Dict[str, Any]]:
    out = []
    files = proj.card_files() + [proj.collab / P.PROGRESS]
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for m in BLOCK_RE.finditer(text):
            if sha(m.group(5)) != m.group(4):
                line = text[: m.start()].count("\n") + 1
                out.append(issue("error", proj.rel(f), line, T("check.block_edited", block=f"{m.group(1)} {m.group(2)}")))
    return out


def check_progress(proj: Project, states) -> List[Dict[str, Any]]:
    L = proj.L
    out = []
    p = proj.collab / P.PROGRESS
    if not p.exists():
        return out
    text = p.read_text(encoding="utf-8")
    limit = proj.skeleton(Skel.LOADING)["target_size"]["PROGRESS"]
    size = len(text.encode("utf-8"))
    if size > limit:
        out.append(issue("warn", f"{P.COLLAB}/{P.PROGRESS}", None, T("check.progress_size", size=size, limit=limit)))
    narrative = "\n".join(section(text, Section.NEXT))  # 现状可以讲刚结束的事，只查下一步
    for obj in sorted(set(re.findall(ID_RE, narrative)), key=id_key):
        st = states.get(obj)
        if st and terminal(proj, st):
            out.append(issue("warn", f"{P.COLLAB}/{P.PROGRESS}", None, T("check.next_stale", next=i18n.pack().heading(Section.NEXT).lstrip("▶ "), obj=obj, state=L.st(st['state']))))
    # 叙述改过之后，又有目标换了状态或任务结束，「下一步」「现状」多半要更新
    f = proj.flow_dir / P.NARRATIVE
    if f.exists():
        mark = json.loads(f.read_text(encoding="utf-8"))
        if mark.get("sha") == narrative_sha(text):
            moved = sorted({st["id"] for st in states.values() for r in st["events"]
                            if r.get("project_seq", 0) > mark.get("project_seq", 0) and r.get("edge") not in SPECIAL
                            and (st["kind"] == Kind.GOAL or r.get("to_state") in (S.PASSED, S.CANCELLED))}, key=id_key)
            if moved:
                out.append(issue("warn", f"{P.COLLAB}/{P.PROGRESS}", None,
                                 T("check.narrative_stale", next=i18n.pack().heading(Section.NEXT).lstrip("▶ "), status=i18n.pack().heading(Section.STATUS), objs=i18n.pack().join(moved))))
    return out


def section(text: str, code: str) -> List[str]:
    """PROGRESS 里一节的行：标题按代码认（中英两种写法），认开头。"""
    titles = i18n.headings(code)
    out, on = [], False
    for l in text.splitlines():
        if l.startswith("## "):
            on = l[3:].strip().startswith(tuple(titles))
            continue
        if on:
            out.append(l)
    return out


def check_time(proj: Project, states, now: dt.datetime) -> List[Dict[str, Any]]:
    out = []
    active = [s for s in states.values() if s["kind"] == Kind.GOAL and s["state"] == S.ACTIVE]
    if len(active) > 3:
        out.append(issue("warn", f"{P.COLLAB}/{P.INTERNAL_FLOW}", None, T("check.too_many_goals", n=len(active))))
    for st in states.values():
        if st["kind"] != Kind.TASK or not st["events"]:
            continue
        last = st["events"][-1]
        try:
            age = (now - dt.datetime.fromisoformat(last["time"])).total_seconds() / 3600
        except (KeyError, ValueError):
            continue
        f = f"{P.COLLAB}/{P.INTERNAL_FLOW}/{st['id']}.jsonl"
        if st["state"] == S.DISPATCHED and age > 24:
            out.append(issue("warn", f, None, T("check.not_picked_up", obj=st['id'], hours=int(age))))
        if st["state"] == S.IN_PROGRESS and age > 48:
            out.append(issue("warn", f, None, T("check.quiet", obj=st['id'], hours=int(age))))
    return out


# ---------- 渲染生成块 ----------

def render_all(proj: Project) -> List[str]:
    v = view(proj)
    states, _, _ = replay_all(proj)
    changed = []
    bodies = card_bodies(proj, v, states)
    for f in proj.card_files():
        if apply_blocks(f, bodies):
            changed.append(proj.rel(f))
    p = proj.collab / P.PROGRESS
    if p.exists() and apply_blocks(p, progress_bodies(proj, v)):
        changed.append(proj.rel(p))
    if p.exists():
        note_narrative(proj, p.read_text(encoding="utf-8"), v["upto"])
    return changed


def narrative_sha(text: str) -> str:
    return sha("\n".join(section(text, Section.NEXT) + ["---"] + section(text, Section.STATUS)))


def note_narrative(proj: Project, text: str, upto: int) -> None:
    """记下「▶ 下一步」「现状」最近一次改动时项目走到了哪条事件（collab/内部/流转/.叙述.json），供「叙述过时」提醒用。"""
    f = proj.flow_dir / P.NARRATIVE
    cur = narrative_sha(text)

    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if old.get("sha") != cur:
        write_if_changed(f, json.dumps({"sha": cur, "project_seq": upto}, ensure_ascii=False) + "\n")


def apply_blocks(path: Path, bodies: Dict[Tuple[str, str], str]) -> bool:
    text = path.read_text(encoding="utf-8")

    def sub(m):
        key = (m.group(1), m.group(2))
        if key not in bodies:
            return m.group(0)
        return block(m.group(1), m.group(2), bodies[key])
    return write_if_changed(path, BLOCK_RE.sub(sub, text))


def card_bodies(proj: Project, v: Dict[str, Any], states) -> Dict[Tuple[str, str], str]:
    L = proj.L
    W = lambda x: L.who(x) if x else "—"  # noqa: E731  发起、接收、持有人；空的写 —
    out = {}
    for t in v["tasks"]:
        st = states[t["id"]]
        out[(Block.HEADER, t["id"])] = L.t("header.task", state=L.st(t["state"]), goal=t["goal"] or "—", stage=t["stage"] or "—",
                                           executor=W(t["executor"] or t["planned_executor"]),
                                           reviewer=W(t["reviewer"] or t["planned_reviewer"]), holder=W(t["holder"])) + "\n"
        rows = [L.t("block.history.head"), "|---|---|---|---|---|---|"]
        voided = set(st["voided"])
        for r in proj_rows(proj, t["id"]):
            mark = L.t("block.history.voided") if r.get("seq") in voided else ""
            edge = L.edge_res(r["edge"], r.get("result"))
            desc = r.get("note", "") or (L.t("block.basis", basis=r["basis"]) if r.get("basis") else "")
            if r.get("evidence"):
                desc += L.t("block.history.evidence") + L.join(r["evidence"])
            if r.get("override"):
                desc += L.t("sep.clause") + r["override"]
            if r.get("correct"):
                desc = L.t("block.history.voids", seq=r["correct"]) + desc
            state = f"{L.st(r.get('from_state'))} → {L.st(r.get('to_state'))}" if r.get("from_state") != r.get("to_state") else L.st(r.get("to_state", ""))
            rows.append(f"| {r['seq']} | {short_time(r.get('time', ''))} | {edge}{mark} | {L.who(r.get('from'))} → {L.who(r.get('to'))} | {state} | {cell(desc)} |")
        out[(Block.HISTORY, t["id"])] = "\n".join(rows) + "\n"
    for g in v["goals"]:
        draft = L.t("header.goal_stage", stage=L.name("draft_stage", g["draft_stage"])) if g["draft_stage"] else ""
        out[(Block.HEADER, g["id"])] = L.t("header.goal", state=L.st(g["state"]), draft=draft,
                                           type=L.name("goal_type", g["type"]) if g["type"] else "—", holder=W(g["holder"])) + "\n"
        rows = [L.t("block.stages.head"), "|---|---|---|---|---|---|---|---|"]
        for s in g["stages"]:
            st = L.name("stage_status", s["state"]) + (L.t("block.stages.invalid") if s["invalid"] else "")
            rows.append(f"| {s['order']} | {cell(s['name'])} | {L.name('stage_type', s['type'])} | {L.join(W(x) for x in s['people']) or '—'} | "
                        f"{L.join(map(str, s['depends_on'])) or '—'} | {L.t('block.yes') if s['parallel'] else L.t('block.no')} | {st} | {L.join(s['tasks']) or '—'} |")
        out[(Block.STAGES, g["id"])] = "\n".join(rows) + "\n" if g["stages"] else L.t("block.stages.empty") + "\n"
        lines = []
        for r in proj_rows(proj, g["id"]):
            if r["edge"] == E.PROGRESS:
                continue
            extra = f"{L.t('sep.paren_open')}{L.join(r['changes'])}{L.t('sep.paren_close')}" if r.get("changes") else ""
            basis = L.t("block.changes.basis", basis=r["basis"]) if r.get("basis") else ""
            edge = L.edge_res(r["edge"], r.get("result") if r["edge"] == E.DRAFT_STAGE else None)
            bar = L.t("sep.bar")
            lines.append(f"- {short_time(r.get('time', ''))}{bar}{edge}{bar}{L.who(r.get('from'))} → {L.who(r.get('to'))}{bar}{cell(r.get('note', ''))}{extra}{basis}")
        out[(Block.CHANGES, g["id"])] = "\n".join(lines) + "\n" if lines else ""
        by_issue = {i["id"]: i for i in v["issues"]}
        bar = L.t("sep.bar")
        sp = "" if L.lang == "zh" else " "
        lines = [f"- {i}{sp}{L.q(cell(by_issue[i]['title']))}"
                 + f"{L.t('sep.paren_open')}{L.name('issue_type', by_issue[i]['type'])}{L.t('sep.paren_close')}{bar}{L.st(by_issue[i]['state'])}"
                 + (f"{bar}{cell((by_issue[i]['summary'] or {}).get('note', ''), 60)}" if by_issue[i]["summary"] else "") for i in g["issues"]]
        out[(Block.ISSUES, g["id"])] = "\n".join(lines) + "\n" if lines else L.t("block.none") + "\n"
    for i in v["issues"]:
        out[(Block.HEADER, i["id"])] = L.t("header.issue", state=L.st(i["state"]), type=L.name("issue_type", i["type"]),
                                           goal=i["goal"] or "—", holder=W(i["holder"]), posts=i["post_count"]) + "\n"
        rows = [L.t("block.attendees.head"), "|---|---|"] + [f"| {a['member']} | {cell(a['view']) or '—'} |" for a in i["attendees"]]
        out[(Block.ATTENDEES, i["id"])] = "\n".join(rows) + "\n"
        rows = [L.t("block.transcript.head"), "|---|---|---|---|---|---|"]
        for m in i["messages"]:
            head = L.t("block.transcript.private") if m.get("private") else first_line(m.get("body", ""))
            rows.append(f"| {m['seq']} | {short_time(m.get('time', ''))} | {L.who(m['from'])} | {L.name('speech', m['type'])} | "
                        f"{L.join(W(x) for x in m.get('mentions', [])) or '—'} | {cell(head, 60) or '—'} |")
        out[(Block.TRANSCRIPT, i["id"])] = "\n".join(rows) + "\n" if i["messages"] else L.t("block.transcript.empty") + "\n"
        r = i["ruling"]
        out[(Block.RULING, i["id"])] = (L.t("block.ruling", note=cell(r["note"]), basis=cell(r["basis"])) if r
                                        else L.t("block.ruling.empty") + "\n")
    return out


def first_line(text: str) -> str:
    return next((l.strip().lstrip("#").strip() for l in text.splitlines() if l.strip()), "")


def proj_rows(proj: Project, obj: str) -> List[Dict[str, Any]]:
    path = proj.flow_dir / f"{obj}.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def pending_type(L: "i18n.Pack", d: Dict[str, Any]) -> str:
    """待你决定一条的类型显示名；框架会审中的批准框架写「批准框架（附会审 I002）」。"""
    name = L.name("pending", d["type"]) if d["type"] in vars(Pending).values() else L.st(d["type"])
    return L.t("block.decisions.with_reviews", type=name, reviews=L.join(d["reviews"])) if d.get("reviews") else name


def decision_lines(v: Dict[str, Any], L: Optional["i18n.Pack"] = None) -> List[str]:
    """待你决定的每一条，格式同协议：编号｜类型：要决定什么｜可选方案与代价｜总管建议｜验收意见｜提出者。"""
    L = L or i18n.pack()
    return [L.t("block.decisions.line", id=d["id"], type=pending_type(L, d), note=cell(d["note"], 120),
                options=cell(d["options"], 120) or "—", recommendation=cell(d["recommendation"], 60) or "—", by=L.who(d["raised_by"]))
            for d in v["decisions"]] + [
        L.t("block.decisions.comment", object=c["object"], note=cell(c["note"], 120)) for g in v["goals"] for c in g["comments"]]


def progress_bodies(proj: Project, v: Dict[str, Any]) -> Dict[Tuple[str, str], str]:
    L = proj.L
    W = lambda x: L.who(x) if x else "—"  # noqa: E731
    out = {}
    items = decision_lines(v, L)
    out[(Block.DECISIONS, Block.PROJECT)] = "\n".join(items) + "\n" if items else L.t("block.decisions.empty") + "\n"
    rows = [L.t("block.goals.head"), "|---|---|---|---|---|"]
    D = DraftStage
    drafts: Dict[str, List[str]] = {D.IDEA: [], D.DISCUSSION: [], D.PROPOSAL: [], D.FRAMING: []}
    for g in v["goals"]:
        if g["category"] == Category.DONE:
            continue
        if g["state"] == S.DRAFT:  # 起草中的不逐行进表，只汇总一行
            drafts[g["draft_stage"] or D.FRAMING].append(g["id"])
            continue
        done = sum(1 for s in g["stages"] if s["state"] == StageStatus.PASSED)
        gtype = L.name("goal_type", g["type"]) if g["type"] else "—"
        rows.append(f"| {g['id']} | {cell(g['title'])} | {gtype} | {L.st(g['state'])} | {done}/{len(g['stages'])} |")
    out[(Block.GOALS, Block.PROJECT)] = "\n".join(rows) + "\n"
    if any(drafts.values()):
        none = L.t("block.none_inline")
        line = L.t("block.goals.drafts", ideas=len(drafts[D.IDEA]), discussing=L.join(drafts[D.DISCUSSION]) or none,
                   proposing=L.join(drafts[D.PROPOSAL]) or none)
        if drafts[D.FRAMING]:
            line += L.t("block.goals.framing", ids=L.join(drafts[D.FRAMING]))
        out[(Block.GOALS, Block.PROJECT)] += "\n" + line + "\n"
    rows = [L.t("block.tasks.head"), "|---|---|---|---|---|---|---|---|"]
    passed, cancelled = [], []
    for t in v["tasks"]:
        if t["state"] == S.PASSED:
            passed.append(t["id"])
            continue
        if t["state"] == S.CANCELLED:
            cancelled.append(t["id"])
            continue
        rows.append(f"| {t['id']} | {cell(t['title'])} | {t['goal'] or '—'} | {W(t['executor'] or t['planned_executor'])} | {W(t['reviewer'] or t['planned_reviewer'])} | "
                    f"{L.st(t['state'])} | {W(t['holder'])} | {cell(t['conclusion'], 30) or '—'} |")
    tail = "\n" + L.t("block.tasks.done", ids=L.join(passed) or L.t("block.none_inline")) + "\n" + (
        L.t("block.tasks.cancelled", ids=L.join(cancelled)) + "\n" if cancelled else "")
    out[(Block.TASKS, Block.PROJECT)] = "\n".join(rows) + "\n" + tail
    out[(Block.ACTIVE_DECISIONS, Block.PROJECT)] = active_decisions(proj)
    return out


def active_decisions(proj: Project) -> str:
    p = proj.collab / P.DECISIONS
    if not p.exists():
        return proj.L.t("block.none") + "\n"
    text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
    lines = [f"- {m.group(1)} {m.group(2).strip()}" for m in re.finditer(r"^##\s*(D\d+)\s*[｜|][^｜|]*[｜|]\s*(.*)$", text, re.M)]
    return "\n".join(lines) + "\n" if lines else proj.L.t("block.none") + "\n"


# ---------- 可走、上下文包 ----------

def legal(proj: Project, obj: str, actor: str, blocked: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """actor 现在能走的边，附可复制的命令。每条边先按真实写入的规则试一遍（不写盘）：会被规则错误拒绝的不列，
    放进 blocked（边、结果、原因），总管、总裁要走得带 --越过。缺说明、缺证据这类要填的内容不算拒绝。"""
    L = proj.L
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st:
        return []
    sk = proj.skeleton(st["kind"])
    out = []
    en = L.lang == "en"  # 英文项目给英文写法，边和结果写代码
    base = f"python3 {FLOW_PY} --project {proj.root} {L.t('cli.cmd.log')} {obj}"
    for edge, spec in sk["edges"].items():
        if edge == E.CREATE or st["state"] not in spec["from"] or (edge == E.APPROVE and st["kind"] == Kind.TASK):
            continue
        ini = spec["initiator"]
        if (ini == SeatClass.HOLDER and actor != st["holder"]) or (ini == SeatClass.MANAGER and actor not in MANAGERS) \
                or (ini in MANAGERS and actor != ini):
            continue
        for res in list(spec.get("results", {})) or [None]:
            r = spec["results"][res] if res else spec
            recv_cls = r.get("receiver") or ""
            need_to = recv_cls in (SeatClass.EXECUTOR, SeatClass.REVIEWER, SeatClass.MANAGER, SeatClass.STATE_SEAT) and not r.get("default_receiver")
            plan_who: List[str] = []
            cmd = f"{base} {edge if en else L.ed(edge)} {L.t('cli.flag.as')} {L.who(actor)}"
            if res:
                cmd += f" {L.t('cli.flag.result')} {res if en else L.name('result', res)}"
            if need_to:
                plan_who = stage_people(proj, states, st) if edge in (E.DISPATCH, E.REASSIGN, E.REOPEN) else []
                cmd += f" {L.t('cli.flag.to')} {'|'.join(L.who(x) for x in plan_who) if plan_who else L.t('cli.ph.receiver')}"
            for k in spec.get("required", []):
                if k in ("evidence", "note", "basis", "options", "recommendation"):
                    cmd += " " + L.t("cli.req." + k)
            if edge == E.ESCALATE:
                cmd += L.t("cli.escalate_hint")
            why = dry_run_rule(proj, states, obj, edge, actor, res, plan_who)
            if why:
                if blocked is not None:
                    blocked.append({"edge": edge, "result": res, "reason": why})
                continue
            out.append({"edge": edge, "result": res, "command": cmd})
    return out


def dry_run_rule(proj: Project, states, obj: str, edge: str, actor: str, res: Optional[str], who: List[str]) -> str:
    """按真实写入试一遍这条边，返回规则错误的原因；硬错误（多半是缺 --给、--证据 这类要填的）不算。"""
    filler = {"from": actor, "note": "…", "basis": "…", "options": "…", "recommendation": "…"}
    if res:
        filler["result"] = res
    for w in who or [None]:
        a = dict(filler, **({"to": w} if w else {}))
        try:
            plan(proj, states, obj, edge, a)
            return ""
        except FlowError as e:
            if e.kind != "rule":
                return ""
            why = e.msg
    return why


def ready_stages(proj: Project, obj: str) -> List[Dict[str, Any]]:
    """目标里可以开始的阶段（前置都已通过、还没派出任务）；还没有任务卡的附建任务的命令。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["kind"] != Kind.GOAL or st["state"] != S.ACTIVE:
        return []
    base = f"python3 {FLOW_PY} --project {proj.root} {proj.L.t('cli.cmd.plan')} {obj} {proj.L.t('cli.req.file')}"
    return [{"order": s["order"], "name": s["name"], "people": s["people"], "tasks": s["tasks"], "command": "" if s["tasks"] else base}
            for s in stage_table(proj, st, states) if s["state"] == StageStatus.READY]


def stage_people(proj: Project, states, st: Dict[str, Any]) -> List[str]:
    g = states.get(st["goal"]) if st["goal"] else None
    if not g:
        return []
    stage = next((s for s in stage_table(proj, g, states) if s["order"] == st["stage"]), None)
    return stage["people"] if stage else []


ROLE_MARK = re.compile(r"<!-- (?:role:|角色：)\s*(.*?) -->")


def protocol_slice(proj: Project, roles: List[str]) -> str:
    """协议里标了这些角色的章节：`<!-- role: lead -->`，旧写法 `<!-- 角色：总管 -->` 也认。"""
    p = proj.collab / P.PROTOCOL
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^(?=#{2,3} )", text)
    out = []
    for part in parts:
        m = ROLE_MARK.search(part.split("\n", 2)[1] if part.count("\n") >= 1 else "")
        marked = {i18n.code_of("protocol_role", x) or x for x in re.split(r"[、,，\s]+", m.group(1).strip())} if m else set()
        if marked & set(roles):
            out.append(re.sub(ROLE_MARK.pattern + r"\n?", "", part).strip())
    return "\n\n".join(out)


def card_section(proj: Project, obj: str, code: str) -> str:
    """卡片里一节的正文：小节按代码认，中英两种标题都认，认开头（「总结（总管）」是 summary）。"""
    for f in proj.card_files():
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^(#{1,2})\s*" + re.escape(obj) + r"(?![-\w]).*$", text, re.M)  # G001 不能命中 G001-T1
        if not m:
            continue
        level = len(m.group(1))
        rest = text[m.end():]
        nxt = re.search(r"^#{1,%d}\s" % level, rest, re.M)
        body = rest[: nxt.start()] if nxt else rest
        sm = re.search(r"^#{%d}\s*%s.*$" % (level + 1, heading_re(code)), body, re.M)
        if not sm:
            return ""
        sub = body[sm.end():]
        sn = re.search(r"^#{1,%d}\s" % (level + 1), sub, re.M)
        return (sub[: sn.start()] if sn else sub).strip()
    return ""


WORK = P.WORK  # 交付和草稿的总目录，和 collab/ 并列


def workdir(proj: Project, goal: Optional[str]) -> str:
    """工作目录（相对项目根）：目标是 work/<目标编号>/，零散任务是 work/loose/。"""
    if not goal:
        return f"{WORK}/{P.LOOSE}"
    return P.work_dir(goal)


def workspace(proj: Project, st: Dict[str, Any], member: str) -> Dict[str, str]:
    """任务的工作区（都相对项目根）：工作目录、默认交付位置 <工作目录>/<任务>/、成员工位 <工作目录>/.scratch/<成员>/<任务>/。"""
    wd = workdir(proj, st["goal"])
    return {"workdir": wd, "delivery": f"{wd}/{st['id']}/", "scratch": f"{wd}/.scratch/{member}/{st['id']}/"}


def issue_feed(st: Dict[str, Any], member: str, since: Optional[int] = None, catch_up: bool = False, fresh: bool = False,
               seen: Iterable[int] = ()) -> Tuple[List[Dict[str, Any]], int]:
    """议题里要喂给 member 的消息和喂到的项目序。
    总管、总裁：全部（含私下）。成员都不给私下发言和自己的发言：
    - 还没开过口的（第一次发言）：叫醒它的那句话（总裁最近一条公开点名它的）和这句话之前的全部公开发言，
      这句话之后的先不给——同一句话叫醒的人互相独立；没有这样的点名（总管拉人）就给到现在为止的全部公开发言；
      catch_up（补叫、收尾：上次没跑成）再加这句话之后的公开发言，只去掉和它同一句话叫来的人的；
      喂到的项目序仍停在那句话，这些人的回答下一轮才给，已补过的由 seen 去重；
    - 开过口的：since 之后的（since 缺省取它最近一次开口的项目序），seen 里的不重复给；
    - fresh（会话丢失，新会话什么都不记得）：到现在为止的全部公开发言，包括它自己说过的。"""
    msgs = [r for r in st["events"] if r.get("edge") in MESSAGES]
    kinds = dict(zip([r["project_seq"] for r in msgs], speech_types(msgs)))
    upto = max([r["project_seq"] for r in st["events"]] or [0])
    if member in MANAGERS:
        pick = [r for r in msgs if since is None or r["project_seq"] > since]
    else:
        mine = [r["project_seq"] for r in msgs if r.get("from") == member]
        if fresh:
            pick = [r for r in msgs if not r.get("private")]
        elif not mine and since is None:
            calls = [r for r in msgs if r.get("from") == BOSS and member in r.get("mentions", []) and not r.get("private")]
            if calls:
                upto = calls[-1]["project_seq"]
            pick = [r for r in msgs if r["project_seq"] <= upto and not r.get("private")]
            if calls and catch_up:
                batch = {w for r in calls for w in r.get("mentions", [])}
                pick += [r for r in msgs if r["project_seq"] > upto and r.get("from") not in batch and not r.get("private")]
        else:
            start = since if since is not None else max(mine)
            pick = [r for r in msgs if r["project_seq"] > start and r.get("from") != member and not r.get("private") and r["project_seq"] not in seen]
    return [{**r, "type": kinds[r["project_seq"]]} for r in pick], upto


def issue_context(proj: Project, states, st: Dict[str, Any], member: str, since: Optional[int],
                  catch_up: bool = False, fresh: bool = False, seen: Iterable[int] = ()) -> Tuple[str, List[Dict[str, Any]]]:
    """与会者（或收口的总管）的上下文包：议题和身份、问题、所挂目标、新发言、记号说明、协议切片。"""
    L = proj.L
    obj = st["id"]
    spec = proj.skeleton(Skel.LOADING)["roles"][Role.ATTENDEE]
    feed, upto = issue_feed(st, member, since, catch_up, fresh, seen)
    me = next((a for a in st["attendees"] if a["member"] == member), None)
    if member not in MANAGERS and not me:
        raise hard(L.t("ctx.not_attendee", member=member, obj=obj))
    others = L.join(L.t("ctx.attendee_view", member=a['member'], view=a['view'] or L.t("ctx.no_view")) for a in st["attendees"] if a["member"] != member) or L.t("block.none_inline")
    blocks: List[Tuple[str, str, str]] = []
    if me:
        intro = L.t("ctx.issue_intro_member", obj=obj, title=st['title'], state=L.st(st['state']), member=member,
                    view=me['view'] or L.t("ctx.own_judgement"), others=others, dir=f"{P.COLLAB}/{P.ISSUES}/{obj}/{member}/")
    else:
        intro = L.t("ctx.issue_intro_lead", obj=obj, title=st['title'], state=L.st(st['state']), others=others)
    blocks.append((Ctx.ISSUE, L.t("ctx.src.replay"), intro))
    blocks.append((Ctx.QUESTION, L.t("ctx.src.issue_card", obj=obj, section=L.heading(Section.QUESTION)), card_section(proj, obj, Section.QUESTION)))
    opening = card_section(proj, obj, Section.OPENING)
    if opening:
        blocks.append((Ctx.OPENING, L.t("ctx.src.issue_card", obj=obj, section=L.heading(Section.OPENING)), opening))
    g = states.get(st["goal"]) if st["goal"] else None
    if g:
        body = f"{g['id']} {g['title']}{L.t('sep.paren_open')}{L.st(g['state'])}{L.t('sep.paren_close')}\n" + card_section(proj, g["id"], Section.WANT)
        if st["type"] == IssueType.REVIEW_MEETING:
            body += "\n\n" + L.t("ctx.submitted_plan") + "\n" + card_section(proj, g["id"], Section.STAGES)
        blocks.append((Ctx.GOAL, L.t("ctx.src.goal_card", obj=g['id']), body))
    if feed:
        lines = []
        for r in feed:
            tag = L.t("ctx.tag_asked_you") if member in r.get("mentions", []) and r.get("from") == BOSS else ""
            tag += L.t("ctx.tag_private") if r.get("private") and r["type"] != Speech.PRIVATE else ""
            text = r.get("body", "").strip() if r["edge"] == E.POST else "[PASS]"
            lines.append(f"### {L.who(r['from'])} · {L.name('speech', r['type'])}{tag}{L.t('sep.paren_open')}{short_time(r.get('time', ''))}{L.t('sep.paren_close')}\n{text}")
        blocks.append((Ctx.TRANSCRIPT, L.t("ctx.src.transcript", upto=upto), "\n\n".join(lines)))
    if me:
        blocks.append((Ctx.NOTATION, L.t("ctx.src.issue_skeleton"), L.t("ctx.notation")
                       + (L.t("ctx.first_post") if not any(r.get("from") == member for r in st["events"] if r.get("edge") in MESSAGES) else "")))
        sl = protocol_slice(proj, spec["protocol"])
        if sl:
            blocks.append((Ctx.PROTOCOL, f"{P.PROTOCOL}{L.t('sep.paren_open')}{L.join(L.name('protocol_role', x) for x in spec['protocol'])}{L.t('sep.paren_close')}", sl))
    text = "\n\n".join(f"## {L.t('context.issue_title.' + n)}\n{body.strip()}" for n, _, body in blocks if body.strip())
    manifest = [{"block": n, "source": src, "bytes": len(body.encode("utf-8"))} for n, src, body in blocks if body.strip()]
    manifest.append({"block": Ctx.READ_UPTO, "source": L.t("ctx.src.project_seq", upto=upto), "bytes": 0, "read_upto": upto, "caught_up": [r["project_seq"] for r in feed if r["project_seq"] > upto]})
    return text, manifest


def context(proj: Project, obj: str, member: str, full: bool = False, since: Optional[int] = None, catch_up: bool = False,
            fresh: bool = False, seen: Iterable[int] = ()) -> Tuple[str, List[Dict[str, Any]]]:
    """成员的上下文包和清单。角色按任务现状推出：待验收 → 确认；所在阶段类型为验收 → 第三方验收；其余 → 执行。"""
    L = proj.L
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st:
        raise hard(L.t("ctx.no_object", obj=obj))
    if st["kind"] == Kind.ISSUE:
        return issue_context(proj, states, st, member, since, catch_up, fresh, seen)
    load = proj.skeleton(Skel.LOADING)
    g = states.get(st["goal"]) if st["goal"] else None
    stage = next((s for s in stage_table(proj, g, states) if s["order"] == st["stage"]), None) if g else None
    role = Role.REVIEWER if st["state"] == S.IN_REVIEW else (Role.THIRD_PARTY if stage and stage["type"] == StageType.ACCEPTANCE else Role.EXECUTOR)
    spec = load["roles"][role]
    blocks: List[Tuple[str, str, str]] = []
    for b in spec["blocks"]:
        if b == Ctx.GOAL and g:
            plan_md = goal_files(proj, g["id"]).get(Path(P.PROPOSAL).stem)  # 只给方案路径，问题.md 不进成员上下文包
            blocks.append((b, L.t("ctx.src.goal_section", obj=g['id'], section=L.heading(Section.WANT)), f"{g['id']} {g['title']}\n" + card_section(proj, g["id"], Section.WANT)
                           + ("\n" + L.t("ctx.proposal", path=plan_md) + "\n" if plan_md else "")))
        elif b == Ctx.HANDOFF:
            blocks.append((b, L.t("ctx.src.task_section", obj=obj, section=L.heading(Section.HANDOFF)), card_section(proj, obj, Section.HANDOFF)))
        elif b == Ctx.CHANGES:
            ch = [f"- {short_time(r['time'])} {r.get('note', '')}{L.t('sep.paren_open')}{L.join(r.get('changes', []))}{L.t('sep.paren_close')}" for r in st["events"] if r.get("edge") == E.CHANGE]
            if ch:
                blocks.append((b, L.t("ctx.src.changes"), "\n".join(ch)))
        elif b == Ctx.STATUS:
            ws = workspace(proj, st, member)
            put = (L.t("ctx.put_executor", path=ws['delivery'], flag=L.t("cli.flag.evidence"))
                   if role == Role.EXECUTOR else L.t("ctx.put_reviewer", path=f"{P.COLLAB}/{P.OUTPUTS}/{obj}/"))
            blocks.append((b, L.t("ctx.src.replay"), L.t("ctx.status", obj=obj, title=st['title'], state=L.st(st['state']), holder=L.who(st['holder']) or '—',
                                                  member=member, role=L.name('role', role), workdir=ws['workdir'], put=put, scratch=ws['scratch'])))
        elif b == Ctx.UPSTREAM and stage:
            ups = []
            table = stage_table(proj, g, states)
            need = list(st["depends_on"]) or [tid for s in table if s["order"] in stage["depends_on"] for tid in s["tasks"]]
            for tid in need:
                t = states[tid]
                dl = [r for r in t["events"] if r.get("edge") == E.DELIVER]
                if dl:
                    ups.append(f"- {tid} {t['title']}{L.t('sep.colon')}{L.join(dl[-1].get('evidence', []))}")
            if ups:
                blocks.append((b, L.t("ctx.src.upstream"), "\n".join(ups)))
        elif b == Ctx.DELIVERY:
            dl = [r for r in st["events"] if r.get("edge") == E.DELIVER]
            if dl:
                blocks.append((b, L.t("ctx.src.last_delivery"), L.t("ctx.last_delivery", who=L.who(dl[-1].get('from')), note=dl[-1].get('note', ''), evidence=L.join(dl[-1].get('evidence', [])))))
        elif b == Ctx.DECISIONS:
            text = card_section(proj, obj, Section.HANDOFF) + (card_section(proj, g["id"], Section.WANT) if g else "")
            ids = sorted(set(re.findall(r"D\d+", text)), key=id_key)
            if ids:
                dec = active_decisions(proj)
                lines = [l for l in dec.splitlines() if any(l.startswith(f"- {i} ") for i in ids)]
                if lines:
                    blocks.append((b, P.DECISIONS, "\n".join(lines)))
        elif b == Ctx.PROTOCOL:
            sl = protocol_slice(proj, spec["protocol"])
            if sl:
                blocks.append((b, f"{P.PROTOCOL}{L.t('sep.paren_open')}{L.join(L.name('protocol_role', x) for x in spec['protocol'])}{L.t('sep.paren_close')}", sl))
        elif b == Ctx.MOVES:
            moves = legal(proj, obj, member)
            if moves:
                blocks.append((b, L.t("ctx.src.moves"), "\n".join(f"- {L.edge_res(m['edge'], m['result'])}{L.t('sep.colon')}`{m['command']}`" for m in moves)))
    if full:
        p = proj.collab / P.PROGRESS
        if p.exists():
            blocks.append((Ctx.PROGRESS, f"{P.COLLAB}/{P.PROGRESS}", p.read_text(encoding="utf-8")))
    text = "\n\n".join(f"## {L.t('context.title.' + n)}\n{body.strip()}" for n, _, body in blocks if body.strip())
    manifest = [{"block": n, "source": src, "bytes": len(body.encode("utf-8"))} for n, src, body in blocks if body.strip()]
    return text, manifest


# ---------- 派活脚本用 ----------

def dispatch_begin(proj: Project, obj: str, seat: str, member: str, run: str, override: str = "") -> List[str]:
    """派活前代写：执行席位写派发（或续接时的进展）和接手；确认席位在需要时转交给该成员。返回写了哪些事件。"""
    L = proj.L
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["kind"] != Kind.TASK:
        raise hard(L.t("disp.no_task", obj=obj))
    base = {"writer": Writer.DISPATCHER, "run": run, "override": override or None}
    done: List[str] = []

    def rec(edge, frm, **kw):
        ev, _ = record(proj, obj, edge, {**base, "from": frm, **kw})
        done.append(f"{L.ed(edge)} {L.who(ev['from'])} → {L.who(ev['to'])}")

    s, holder = st["state"], st["holder"]
    if s == S.PLANNED:
        raise hard(L.t("disp.still_planned", obj=obj, goal=st['goal']))
    if seat in (Seat.ACCEPTANCE, Seat.REVIEWER):
        if s != S.IN_REVIEW:
            raise hard(L.t("disp.not_in_review", obj=obj, state=L.st(s), seat=L.name("seat", seat)))
        if holder != member:
            rec(E.HAND_OVER, holder, to=member, note=L.t("disp.note.hand_over", member=member, run=run))
        else:
            rec(E.PROGRESS, member, note=L.t("disp.note.resume_review", run=run))
        return done
    if s == S.APPROVED:
        rec(E.DISPATCH, LEAD, to=member, note=L.t("disp.note.dispatch", member=member, run=run))
        rec(E.PICK_UP, member, note=L.t("disp.note.start", run=run))
    elif s in (S.DISPATCHED, S.IN_PROGRESS) and holder != member:
        if not override:
            raise rule(L.t("disp.held_by", obj=obj, holder=L.who(holder), member=member))
        rec(E.REASSIGN, LEAD, to=member, note=L.t("disp.note.reassign", member=member, why=override))
        rec(E.PICK_UP, member, note=L.t("disp.note.start", run=run))
    elif s == S.DISPATCHED:
        rec(E.PICK_UP, member, note=L.t("disp.note.start", run=run))
    elif s == S.IN_PROGRESS:
        rec(E.PROGRESS, member, note=L.t("disp.note.resume", run=run))
    else:
        raise hard(L.t("disp.cant_dispatch", obj=obj, state=L.st(s)))
    return done


def dispatch_end(proj: Project, obj: str, member: str, run: str, session: str, final: str, status: str) -> List[str]:
    """派活结束后代写：一条进展（会话、结果）；成员没写结束边（交付、确认、上报、转交）时代写上报给总管。"""
    done = []
    rows = proj_rows(proj, obj)
    mine = [r for r in rows if r.get("run") == run and r.get("from") == member and r.get("edge") in (E.DELIVER, E.REVIEW, E.ESCALATE, E.HAND_OVER)]
    record(proj, obj, E.PROGRESS, {"from": member, "writer": Writer.DISPATCHER, "run": run, "session": session or None,
                               "note": proj.L.t("disp.note.ended", run=run, status=status)})
    done.append(E.PROGRESS)
    if mine:
        return done
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if st and st["holder"] == member and not terminal(proj, st) and st["state"] != S.BLOCKED:
        record(proj, obj, E.ESCALATE, {"from": member, "to": LEAD, "writer": Writer.DISPATCHER, "run": run, "session": session or None,
                                   "note": proj.L.t("disp.note.undeclared") + cell(final, 120)})
        done.append(proj.L.t("disp.auto_escalated", edge=proj.L.ed(E.ESCALATE), lead=proj.L.who(LEAD)))
    return done


def dispatch_prompt(proj: Project, obj: str, member: str, prompt: str) -> str:
    text, _ = context(proj, obj, member)
    L = proj.L
    return f"{prompt.rstrip()}\n\n---\n{L.t('disp.prompt_head', obj=obj)}\n\n{text}\n\n{L.t('disp.prompt_tail', moves=L.t('context.title.moves'))}"


PRIVATE_RE = re.compile(r"<(私下|private)(?:\s+[^>]*)?>(.*?)</\1>", re.S | re.I)
MENTION_RE = re.compile(r"@([^\s@，。、,.:：；;！!？?()（）\[\]【】<>「」]+)")


def parse_reply(text: str) -> List[Dict[str, Any]]:
    """把成员的最后回复拆成黑板消息：<私下 …>…</私下> 各成一条私下发言；其余是一条公开发言；只有 [PASS] 是 PASS。"""
    private = [m.group(2).strip() for m in PRIVATE_RE.finditer(text or "") if m.group(2).strip()]
    public = PRIVATE_RE.sub("", text or "").strip()
    out: List[Dict[str, Any]] = []
    if public in ("[PASS]", "PASS"):
        out.append({"edge": E.PASS})
    elif public:
        out.append({"edge": E.POST, "body": public, "mentions": MENTION_RE.findall(public)})
    out += [{"edge": E.POST, "body": m, "private": True} for m in private]
    return out


def issue_begin(proj: Project, obj: str, member: str) -> Dict[str, Any]:
    """叫醒与会者前检查：议题在讨论中、member 在与会名单里。返回议题状态。"""
    L = proj.L
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["kind"] != Kind.ISSUE:
        raise hard(L.t("issue.not_issue", obj=obj))
    if st["state"] != S.DISCUSSING:
        raise hard(L.t("issue.not_discussing", obj=obj, state=L.st(st['state'])))
    if member not in [a["member"] for a in st["attendees"]]:
        raise hard(L.t("ctx.not_attendee", member=member, obj=obj))
    return st


def issue_needs(st: Dict[str, Any], member: str, since: Optional[int]) -> bool:
    """有没有要 member 开口的：还没开过口，或 since 之后总裁公开点名了它。成员的 @ 和私下的点名都不算。"""
    msgs = [r for r in st["events"] if r.get("edge") in MESSAGES]
    if not any(r.get("from") == member for r in msgs):
        return True
    start = since if since is not None else max(r["project_seq"] for r in msgs if r.get("from") == member)
    return any(r["project_seq"] > start and r.get("from") == BOSS and member in r.get("mentions", []) and not r.get("private") for r in msgs)


def issue_end(proj: Project, obj: str, member: str, run: str, session: str, final: str, ok: bool,
              upto: int) -> Tuple[List[str], List[str]]:
    """与会者那次派活结束后，由派活钩子把回复写成黑板消息（方案 03 第 10.3 节 F）。
    返回（写了什么，接着要叫醒谁）。只有总裁的 @ 能叫醒人（总裁 11-04）：成员写的 @ 当普通文字，不记点名、不叫醒；
    唯一的接着叫醒是 member 自己——它跑的时候总裁又公开点名了它。"""
    L = proj.L
    if not ok or not (final or "").strip():
        return [L.t("issue.no_reply")], []
    done, wake = [], []
    base = {"from": member, "writer": Writer.DISPATCHER, "run": run, "session": session or None}

    for m in parse_reply(final):
        ev, _ = record(proj, obj, m["edge"], {**base, "body": m.get("body"), "private": m.get("private")})
        done.append(L.ed(m['edge']) + (L.t("issue.private_mark") if m.get('private') else ""))
    st = replay(obj, proj_rows(proj, obj))
    if st["state"] == S.DISCUSSING and issue_needs(st, member, upto):
        wake.append(member)
    return done, wake


# ---------- 命令行 ----------

def env_args(a) -> Dict[str, Any]:
    out = {}
    for k in ("note", "basis", "options", "recommendation", "diff_reason", "title", "type", "goal", "body"):
        v = getattr(a, k, None)
        if v:
            out[k] = v
    if getattr(a, "stage", None) is not None:
        out["stage"] = a.stage
    if getattr(a, "attendees", None):
        out["attendees"] = a.attendees
    return out


def value_code(kind: str, x: Optional[str]) -> Optional[str]:
    """命令行参数值：代码、中英两种显示名都认；认不出原样返回，由校验报错。"""
    if x is None:
        return None
    return i18n.code_of(kind, x) or x


# 子命令：英文为准，中文写法长期保留为别名（术语表「命令行」）
COMMANDS = {"new": ["建立"], "log": ["记"], "plan": ["框架", "frame"], "start": ["开工"], "next": ["可走"], "context": ["上下文"],
            "archive": ["归档"], "render": ["渲染"], "check": ["检查"], "export": ["导出"]}
# 中文子命令和参数名长期保留为别名：解析前换成英文写法，帮助里只列英文
FLAG_ALIASES = {'--作为': '--as', '--写入者': '--writer', '--派活': '--run', '--会话': '--session', '--说明': '--note', '--依据': '--basis', '--越过': '--override', '--标题': '--title', '--目标': '--goal', '--阶段': '--stage', '--类型': '--type', '--与会': '--attendees', '--结果': '--result', '--给': '--to', '--证据': '--evidence', '--方案': '--options', '--建议': '--recommend', '--变更项': '--changes', '--更正': '--correct', '--人选': '--assignee', '--差异理由': '--diff-reason', '--正文': '--body', '--点名': '--mention', '--私下': '--private', '--文件': '--file', '--全': '--all', '--清单': '--list', '--起': '--since'}


def english_argv(argv: List[str]) -> List[str]:
    out, sub_done, i = [], False, 0
    while i < len(argv):
        x = argv[i]
        if x == "--project" and not sub_done:
            out += argv[i:i + 2]
            i += 2
            continue
        head, eq, rest = x.partition("=")
        if head in FLAG_ALIASES:
            x = FLAG_ALIASES[head] + eq + rest
        elif not sub_done and not x.startswith("-"):
            x = next((k for k, v in COMMANDS.items() if x in v and not x.isascii()), x)
            sub_done = True
        out.append(x)
        i += 1
    return out


def parse_people(spec: Optional[List[str]]) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for item in spec or []:
        for part in re.split(r"[;；]", item):
            if not part.strip():
                continue
            k, _, v = part.partition("=")
            out[int(k)] = [x.strip() for x in re.split(r"[,，、]", v) if x.strip()]
    return out


def cli_lang(argv: List[str]) -> str:
    """帮助文字的语言：--project 指的项目，或当前目录往上找到的项目；都没有时用当前默认。"""
    root: Optional[Path] = None
    for i, x in enumerate(argv):
        if x == "--project" and i + 1 < len(argv):
            root = Path(argv[i + 1]).expanduser()
        elif x.startswith("--project="):
            root = Path(x.split("=", 1)[1]).expanduser()
    if root is None:
        root = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / P.COLLAB / P.CONFIG).exists()), None)
    return i18n.project_lang(root) if root else i18n.pack().lang


def main(argv: Optional[List[str]] = None) -> int:
    HL = i18n.pack(cli_lang(list(sys.argv[1:] if argv is None else argv)))
    H = lambda k: HL.t("cli.help." + k)  # noqa: E731
    ap = argparse.ArgumentParser(description=H("flow"))
    ap.add_argument("--project", help=H("project"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def parser(name):
        return sub.add_parser(name, aliases=[x for x in COMMANDS[name] if x.isascii()])

    def actor_arg(p):
        p.add_argument("--as", dest="as_", default=os.environ.get("COLLAB_ACTOR") or LEAD)

    def common(p):
        actor_arg(p)
        p.add_argument("--writer", dest="writer", default=os.environ.get("COLLAB_WRITER"))
        p.add_argument("--run", dest="run", default=os.environ.get("COLLAB_RUN"))
        p.add_argument("--session", dest="session", default=os.environ.get("COLLAB_SESSION"))
        p.add_argument("--note", dest="note")
        p.add_argument("--basis", dest="basis")
        p.add_argument("--override", dest="override")

    p = parser("new")
    p.add_argument("kind", help=H("kind"))
    p.add_argument("--title", dest="title", required=True)
    p.add_argument("--goal", dest="goal")
    p.add_argument("--stage", dest="stage", type=int)
    p.add_argument("--type", dest="type")
    p.add_argument("--attendees", dest="attendees", nargs="*", help=H("attendees"))
    common(p)

    p = parser("log")
    p.add_argument("id")
    p.add_argument("edge")
    p.add_argument("--result", dest="result")
    p.add_argument("--to", dest="to")
    p.add_argument("--evidence", dest="evidence", nargs="*", default=[])
    p.add_argument("--options", dest="options")
    p.add_argument("--recommend", "--advice", dest="recommendation")
    p.add_argument("--changes", dest="changes", nargs="*", default=[])
    p.add_argument("--correct", "--void", dest="correct", type=int)
    p.add_argument("--assignee", "--people", dest="people", nargs="*", help=H("people"))
    p.add_argument("--diff-reason", "--why-differ", dest="diff_reason")
    p.add_argument("--body", "--text", dest="body", help=H("body"))
    p.add_argument("--mention", "--at", dest="mentions", nargs="*", default=[], help=H("mention"))
    p.add_argument("--private", dest="private", action="store_true", help=H("private"))
    p.add_argument("--type", dest="type", help=H("speech_type"))
    p.add_argument("--attendees", dest="attendees", nargs="*", help=H("new_attendees"))
    common(p)

    p = parser("plan")
    p.add_argument("id")
    p.add_argument("--file", dest="file", required=True, help=H("file"))
    common(p)

    p = parser("start")
    p.add_argument("id")
    common(p)

    p = parser("next")
    p.add_argument("id")
    actor_arg(p)

    p = parser("context")
    p.add_argument("id")
    p.add_argument("--to", "--for", dest="to", required=True)
    p.add_argument("--all", "--full", dest="all", action="store_true")
    p.add_argument("--list", "--manifest", dest="list", action="store_true")
    p.add_argument("--since", dest="since", type=int, help=H("since"))

    p = parser("archive")
    p.add_argument("id")
    common(p)

    parser("render")
    p = parser("check")
    p.add_argument("--json", action="store_true")
    p = parser("export")
    p.add_argument("--json", action="store_true")

    a = ap.parse_args(english_argv(list(sys.argv[1:] if argv is None else argv)))
    root = Path(a.project).expanduser() if a.project else find_project(Path.cwd())
    proj = Project(root)
    L = proj.L
    cmd = next((k for k, v in COMMANDS.items() if a.cmd == k or a.cmd in v), a.cmd)
    try:
        if cmd == "plan":
            spec = json.loads(Path(a.file).expanduser().read_text(encoding="utf-8"))
            res = frame(proj, a.id, spec, {"note": a.note, "basis": a.basis, "writer": a.writer})
            print(L.t("cli.plan_version", obj=a.id, version=res['version']) + ("" if res["changes"] else L.t("cli.no_change_paren")))
            for line in res["changes"]:
                print("  " + line)
            return 0
        if cmd == "archive":
            moved = archive_goal(proj, a.id)
            print("\n".join([L.t("cli.moved")] + ["  " + m for m in moved]) if moved else L.t("cli.nothing_to_move"))
            return 0
        if cmd == "start":
            start_self(proj, a.id, {"note": a.note, "writer": a.writer})
            print(L.t("cli.started", obj=a.id, lead=L.who(LEAD)))
            return 0
        if cmd in ("log", "render") and not proj.flow_dir.is_dir():  # 不能顺手建出 internal/flow/，那样旧项目会被当成新结构
            raise hard(L.t("cli.no_flow_dir", dir=f"{P.COLLAB}/{P.INTERNAL_FLOW}/"))
        if cmd in ("new", "log"):
            actor = proj.actor(a.as_)
            if not actor:
                raise hard(L.t("cli.unknown_actor", actor=a.as_))
            args = env_args(a)
            args.update({"from": actor, "writer": value_code("writer", a.writer) or (Writer.LEAD if actor in MANAGERS else Writer.MEMBER),
                         "run": a.run, "session": a.session, "override": a.override})
            if cmd == "new":
                kind = value_code("kind", a.kind)
                if kind not in (Kind.TASK, Kind.GOAL, Kind.ISSUE):
                    raise hard(L.t("cli.bad_kind", kinds=L.join(L.name('kind', k) for k in (Kind.TASK, Kind.GOAL, Kind.ISSUE)), kind=a.kind))
                if args.get("type"):
                    args["type"] = value_code("goal_type" if kind == Kind.GOAL else "issue_type", args["type"])
                obj, path = create(proj, kind, args)
                print(L.t("cli.created", obj=obj, path=proj.rel(path)))
                return 0
            edge = value_code("edge", a.edge)
            if edge == E.CREATE:
                raise hard(L.t("cli.use_new"))
            args.update({"result": value_code("draft_stage" if edge == E.DRAFT_STAGE else "result", a.result), "to": a.to,
                         "evidence": a.evidence, "options": a.options, "recommendation": a.recommendation,
                         "changes": a.changes, "correct": a.correct, "diff_reason": a.diff_reason, "mentions": a.mentions, "private": a.private})
            if args.get("type"):
                args["type"] = value_code("speech", args["type"])
            if args.get("body") == "-":
                args["body"] = sys.stdin.read()
            if a.people:
                args["people"] = parse_people(a.people)
            if args.get("people"):
                args["people"] = {k: [proj.actor(w) or w for w in v] for k, v in args["people"].items()}
            ev, notes = record(proj, a.id, edge, args)
            res = ev.get("result")
            print(L.t("cli.logged", obj=a.id, seq=ev['seq'], edge=L.edge_res(ev['edge'], res), frm=L.who(ev['from']), to=L.who(ev['to']),
                      from_state=L.st(ev['from_state']), to_state=L.st(ev['to_state'])))
            for n in notes:
                print(L.t("cli.note") + n)
            if ev.get("override"):
                print(L.t("cli.overridden") + ev["override"])
            return 0
        if cmd == "next":
            actor = proj.actor(a.as_) or a.as_
            blocked: List[Dict[str, Any]] = []
            moves = legal(proj, a.id, actor, blocked)
            ready = ready_stages(proj, a.id)
            if not moves and not ready:
                print(L.t("cli.no_moves", who=L.who(actor), obj=a.id))
            for m in moves:
                print(f"{L.edge_res(m['edge'], m['result'])}\n  {m['command']}")
            for r in ready:
                head = L.t("cli.stage_ready", order=r['order'], name=r['name'], people=L.join(L.who(x) for x in r['people']) or '—')
                print(L.t("cli.stage_dispatch", head=head, tasks=L.join(r['tasks'])) if r["tasks"] else L.t("cli.stage_create", head=head, command=r['command']))
            for b in blocked:
                print(L.t("cli.blocked_move", edge=L.edge_res(b['edge'], b['result']), reason=b['reason'])
                      + (L.t("cli.override_hint_short") if actor in MANAGERS else ""))
            return 0
        if cmd == "context":
            member = proj.actor(a.to) or a.to
            text, manifest = context(proj, a.id, member, a.all, a.since)
            if a.list:
                limit = proj.skeleton(Skel.LOADING)["target_size"]["context"]
                total = sum(m["bytes"] for m in manifest)
                for m in manifest:
                    print(f"{L.t('context.block.' + m['block']):<6} {m['bytes']:>6} {L.t('cli.bytes')}  {m['source']}")
                print(L.t("cli.total_bytes", total=total, limit=limit) + (L.t("cli.over") if total > limit else ""))
            else:
                print(text)
            return 0
        if cmd == "render":
            with locked(proj):
                changed = render_all(proj)
            print(L.t("cli.rewritten") + (L.join(changed) if changed else L.t("cli.no_change")))
            return 0
        if cmd == "check":
            items = check(proj, now=project_now(proj))
            if a.json:
                print(json.dumps(items, ensure_ascii=False, indent=1))
            else:
                for x in items:
                    print(f"{L.t('cli.level.' + x['level'])}  {x['file']}{':' + str(x['line']) if x['line'] else ''}  {x['msg']}")
                if not items:
                    print(L.t("cli.no_problems"))
            return 1 if any(x["level"] == "error" for x in items) else 0
        if cmd == "export":
            print(dumps(view(proj)))
            return 0
    except FlowError as e:
        print(f"{L.t('cli.' + e.kind)}{L.t('sep.colon')}{e.msg}", file=sys.stderr)
        if e.kind == "rule":
            print(L.t("cli.override_hint"), file=sys.stderr)
        if cmd == "log":
            actor = proj.actor(getattr(a, "as_", "")) or LEAD
            moves = legal(proj, a.id, actor) if (proj.flow_dir / f"{a.id}.jsonl").exists() else []
            if moves:
                print(L.t("cli.can_do", who=L.who(actor)), file=sys.stderr)
                for m in moves:
                    print("  " + m["command"], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
