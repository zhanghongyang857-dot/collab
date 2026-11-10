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
TOOLKIT = HERE.parent  # 开发时是 src/，本机发布后是 NOW/系统/
SKEL_DIR = HERE / "skeletons"
# 骨架名（事件和项目覆盖里用的中文名）→ 工具包里的文件名
SKEL_FILES = {"任务": "task", "目标": "goal", "目标-通用": "goal-general", "目标-调研": "goal-research",
              "目标-开发": "goal-dev", "议题": "issue", "加载": "loading", "渲染": "render"}


def skel_file(name: str) -> str:
    """骨架在工具包里的文件名（不含 .json）；没登记的名字原样用。"""
    return SKEL_FILES.get(name, name)
FLOW_PY = Path(__file__).resolve()


def team_dir() -> Path:
    """班子目录：环境变量 COLLAB_TEAM；没有时找工具包旁边的 班子/（本机发布在 NOW/系统/，班子在 NOW/班子/）；再没有用 ~/.collab-team。"""
    env = os.environ.get("COLLAB_TEAM")
    if env:
        return Path(env).expanduser()
    beside = TOOLKIT.parent / "班子"
    return beside if beside.is_dir() else Path("~/.collab-team").expanduser()

EVENT_V = 1
VIEW = "视图@2"
BOSS, LEAD = "总裁", "总管"
MANAGERS = (BOSS, LEAD)
BOSS_ALIASES = ("总裁", "用户", "本人")
SPECIAL = ("变更", "进展", "更正", "意见", "起草阶段")
DRAFT_STAGES = ("想法", "讨论", "方案")  # 起草状态下的阶段，只由「起草阶段」事件回放得出，默认第一个
APPROVE_BASIS = "总裁在看板批准第 {} 版框架"  # 看板批准写的依据；带批注时后面接「：批注」
RETURN_EDGES = ("打回", "退回")


def is_quote(basis: Any, goal: Optional[str]) -> bool:
    """依据是不是原话：有内容，且不是框架自动写的默认依据「<目标> 框架」。"""
    b = str(basis or "").strip()
    return bool(b) and b != f"{goal} 框架"


def is_boss_return(r: Dict[str, Any]) -> bool:
    """总裁的退回：任务上总裁判需补充或未通过，目标上的打回、退回；要带依据。"""
    return r.get("发起") == BOSS and bool(str(r.get("依据") or "").strip()) and (
        r.get("边") in RETURN_EDGES or (r.get("边") == "确认" and r.get("结果") in ("需补充", "未通过")))
# 议题的消息事件：不改状态、不改持有人（方案 03 第 10 节）
MESSAGES = ("发言", "PASS")
# 改变持有人的边：除接手（持有人不变）、特殊事件和消息事件外都改
KEEP_HOLDER = ("接手",) + SPECIAL + MESSAGES
ID_RE = r"(?:G\d+-T\d+|G\d+|T\d+|I\d+)"
BLOCK_RE = re.compile(r"<!-- flow:(\S+) (\S+) (\S+) sha=([0-9a-f]+) -->\n(.*?)<!-- /flow -->", re.S)
FIELD_ORDER = ["v", "seq", "项目序", "时间", "对象", "骨架", "边", "结果", "发起", "接收", "前状态", "后状态",
               "写入者", "派活", "会话", "目标", "阶段", "计划", "键", "标题", "类型", "拟执行", "拟确认", "前置", "与会", "点名", "私下", "正文", "证据", "说明", "依据", "方案", "建议",
               "变更项", "差异", "框架版本", "批准版", "差异理由", "更正", "越过"]


class FlowError(Exception):
    """kind：硬错误（不能越过）/ 规则错误（总管、总裁可带理由越过）。"""

    def __init__(self, kind: str, msg: str):
        super().__init__(msg)
        self.kind = kind
        self.msg = msg


def hard(msg: str) -> FlowError:
    return FlowError("硬错误", msg)


def rule(msg: str) -> FlowError:
    return FlowError("规则错误", msg)


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
    clock = proj.proc_dir / "时钟.json"
    if clock.exists():
        return dt.datetime.fromisoformat(json.loads(clock.read_text(encoding="utf-8"))["现在"])
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
        self.collab = self.root / "collab"
        self.flow_dir = self.collab / "内部" / "流转"
        self.proc_dir = self.collab / "内部" / "流程"
        self.small = (self.collab / "任务.md").exists() and not (self.collab / "任务").is_dir()
        self._skel: Dict[str, Dict[str, Any]] = {}
        self._roster: Optional[List[Dict[str, Any]]] = None

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
                if version is None or data.get("版本") == version:
                    found = data
                    break
        if found is None and version is not None:
            for c in (self.proc_dir / "历史" / f"{name}@{version}.json", SKEL_DIR / "history" / f"{skel_file(name)}@{version}.json"):
                if c.exists():
                    found = json.loads(c.read_text(encoding="utf-8"))
                    break
        if found is None:
            raise hard(f"找不到骨架 {name}" + (f"@{version}" if version else ""))
        self._skel[key] = found
        return found

    def roster(self) -> List[Dict[str, Any]]:
        if self._roster is None:
            out: List[Dict[str, Any]] = []
            src = self.proc_dir / "花名册.json"
            if not src.exists():
                team = team_dir() / "班子.json"
                src = team if team.exists() else src
            if src.exists():
                data = json.loads(src.read_text(encoding="utf-8"))
                for m in data.get("成员", []):
                    name = m.get("派活名") or m.get("名称")
                    if not name:
                        continue
                    keys = {str(x).lower() for x in [name, m.get("名称", "")] + list(m.get("别名", [])) if x}
                    out.append({"派活名": name, "名称": m.get("名称", name), "keys": keys})
            self._roster = out
        return self._roster

    def actor(self, name: Optional[str]) -> Optional[str]:
        n = (name or "").strip()
        if not n:
            return None
        if n in BOSS_ALIASES:
            return BOSS
        if n == LEAD:
            return LEAD
        low = n.lower()
        for m in self.roster():
            if low in m["keys"]:
                return m["派活名"]
        return None

    def is_member(self, name: Optional[str]) -> bool:
        return bool(name) and any(m["派活名"] == name for m in self.roster())

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
                    rows.append(json.loads(line))
                except ValueError:
                    probs.append(issue("error", self.rel(f), n, "这一行不是合法 JSON"))
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
        for single in ("任务.md", "目标.md", "归档.md"):
            if (c / single).exists():
                out.append(c / single)
        for d in (c / "任务", c / "目标", c / "议题", c / "归档" / "任务", c / "归档" / "目标", c / "归档" / "议题"):
            if d.is_dir():
                out += sorted(x for x in d.glob("*.md") if not x.name.startswith("_"))
        return out


def issue(level: str, file: str, line: Optional[int], msg: str) -> Dict[str, Any]:
    return {"level": level, "file": file, "line": line, "msg": msg}


def find_project(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "collab").is_dir() and ((p / "collab" / "PROGRESS.md").exists() or (p / "collab" / "内部" / "流转").is_dir()):
            return p
    sys.exit(f"找不到 collab/：{start} 及其上级目录都不是协作项目，用 --project 指定")


def dev_write_refusal(root: Path) -> Optional[str]:
    """开发版工具包不能写自己仓库的账本和模板：账本归发布版管，试新功能用 demo/ 或临时项目。发布版带 版本.txt，不受限。"""
    if (TOOLKIT / "版本.txt").exists():
        return None
    root = root.resolve()
    if root == TOOLKIT or TOOLKIT in root.parents or root in TOOLKIT.parents:
        return f"开发版工具包（{TOOLKIT}）不能写 {root}：账本用发布版 NOW/系统/ 的命令操作，试新功能用 demo/ 或临时项目"
    return None


@contextmanager
def locked(proj: Project):
    refusal = dev_write_refusal(proj.root)
    if refusal:
        raise hard(refusal)
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
        return "目标"
    return "议题" if re.fullmatch(r"I\d+", obj) else "任务"


def blank_state(obj: str) -> Dict[str, Any]:
    return {"编号": obj, "种类": kind_of(obj), "状态": "无", "持有人": None, "标题": "", "目标": None, "阶段": None, "计划": None,
            "类型": None, "执行": None, "确认": None, "上次交付人": None, "返工人": None, "返工次": 0,
            "上报前": None, "暂停前": None, "通过有效": False, "自确认": False, "阶段实例": [], "依据": "",
            "起草阶段": DRAFT_STAGES[0], "键": None, "拟执行": None, "拟确认": None, "前置": [], "框架版本": 0, "批准版": None, "本轮改动": [], "意见": [],
            "差异理由": "", "事件": [], "作废": [], "问题": [], "骨架": None, "与会": []}


def replay(obj: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    st = blank_state(obj)
    voided = {r.get("更正") for r in rows if r.get("边") == "更正"}
    st["作废"] = sorted(x for x in voided if isinstance(x, int))
    for ev in rows:
        if ev.get("seq") in voided or ev.get("边") == "更正":
            continue
        apply_event(st, ev)
    return st


def apply_event(st: Dict[str, Any], ev: Dict[str, Any]) -> None:
    edge = ev.get("边")
    st["事件"].append(ev)
    if edge in MESSAGES:
        return
    if edge == "进展":
        return
    if edge == "起草阶段":
        st["起草阶段"] = ev.get("结果") or st["起草阶段"]
        return
    if edge == "意见":
        st["意见"].append(ev)
        return
    if edge == "变更":
        if ev.get("与会") is not None:
            st["与会"] = ev["与会"]
        if st["种类"] == "任务":
            for k in ("阶段", "标题", "拟执行", "拟确认", "前置"):
                if ev.get(k) is not None:
                    st[k] = ev[k]
            return
        if ev.get("阶段") is not None:
            st["阶段实例"] = ev["阶段"]
            st["差异理由"] = st["差异理由"] or ev.get("说明", "")  # 改阶段的变更必带说明，算登记过的差异
        if ev.get("框架版本") is not None:
            st["框架版本"] = ev["框架版本"]
            st["本轮改动"] = ev.get("差异") or []
        return
    if ev.get("前状态") != st["状态"]:
        st["问题"].append(f"seq {ev.get('seq')}「{edge}」记的前状态是「{ev.get('前状态')}」，回放得到「{st['状态']}」")
    prev_state, prev_holder = st["状态"], st["持有人"]
    st["状态"] = ev.get("后状态") or st["状态"]
    to = ev.get("接收")
    if edge == "接手":
        st["持有人"] = ev.get("发起")
    elif edge not in KEEP_HOLDER:
        st["持有人"] = None if to in (None, "无") else to
    if edge == "建立":
        st["骨架"] = ev.get("骨架")
        for k in ("目标", "阶段", "计划", "键", "标题", "类型", "拟执行", "拟确认", "前置", "依据", "与会"):
            if ev.get(k) is not None:
                st[k] = ev[k]
    elif edge in ("派发", "改派", "重开"):
        st["执行"] = to
        if edge == "重开":
            st["通过有效"] = False
        if to != st["返工人"]:
            st["返工人"], st["返工次"] = None, 0
    elif edge == "交付":
        st["上次交付人"] = ev.get("发起")
        st["确认"] = to
    elif edge == "转交" and st["状态"] == "待验收":
        st["确认"] = to
    elif edge == "确认":
        res = ev.get("结果")
        if res == "通过":
            st["通过有效"] = True
            st["自确认"] = ev.get("发起") == st["上次交付人"]
            st["返工人"], st["返工次"] = None, 0
        elif res == "需补充" and ev.get("发起") != BOSS:
            if to == st["返工人"]:
                st["返工次"] += 1
            else:
                st["返工人"], st["返工次"] = to, 1
    elif edge == "上报":
        st["上报前"] = [prev_state, prev_holder]
    elif edge == "暂停":
        st["暂停前"] = [prev_state, prev_holder]
    if edge in ("提交", "批准") and ev.get("阶段") is not None:
        st["阶段实例"] = ev["阶段"]
    if edge == "批准" and ev.get("批准版"):
        st["批准版"] = ev["批准版"]
    if edge == "提交" and (ev.get("差异理由") or ev.get("越过")):
        st["差异理由"] = ev.get("差异理由") or ev["越过"]


def replay_all(proj: Project) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    evs, probs = proj.load_events()
    states = {obj: replay(obj, rows) for obj, rows in evs.items()}
    return states, evs, probs


def draft_stage(st: Dict[str, Any]) -> Optional[str]:
    """目标在起草（或从起草暂停）时的阶段：想法、讨论、方案；其余状态返回 None。
    已经搭过框架、又没有写过阶段事件的旧目标不显示（它们早就过了这几段）。"""
    if st["种类"] != "目标":
        return None
    drafting = st["状态"] == "起草" or (st["状态"] == "暂停" and (st["暂停前"] or [None])[0] == "起草")
    if not drafting:
        return None
    if st["框架版本"] and not any(e.get("边") == "起草阶段" for e in st["事件"]):
        return None
    return st["起草阶段"]


def goal_dir(proj: Project, goal: str) -> Optional[Path]:
    """目标自己的目录（问题.md、方案.md 和其他文档）：collab/目标/G00x/，归档后在 collab/归档/目标/G00x/。"""
    for d in (proj.collab / "目标" / goal, proj.collab / "归档" / "目标" / goal):
        if d.is_dir():
            return d
    return None


GOAL_DOCS = ("问题", "讨论", "方案")  # 讨论.md 是 G026 之前的名字，已归档的卡还在用


def goal_files(proj: Project, goal: str) -> Dict[str, Any]:
    """目标目录里的文档（相对项目根的路径）：问题、讨论、方案，其余 Markdown 放「其他」。"""
    d = goal_dir(proj, goal)
    if not d:
        return {}
    out: Dict[str, Any] = {n: proj.rel(d / f"{n}.md") for n in GOAL_DOCS if (d / f"{n}.md").is_file()}
    others = sorted(f for f in d.glob("*.md") if f.stem not in GOAL_DOCS)
    if others:
        out["其他"] = [proj.rel(f) for f in others]
    return out


def open_questions(proj: Project, goal: str) -> List[str]:
    """问题.md「待解决」一节里顶格的列表项：要总裁回答的问题。"""
    d = goal_dir(proj, goal)
    f = d / "问题.md" if d else None
    if not f or not f.is_file():
        return []
    m = re.search(r"^## 待解决[ \t]*\n(.*?)(?=^## |\Z)", f.read_text(encoding="utf-8"), re.M | re.S)
    return [x.strip() for x in re.findall(r"^(?:\d+[.、]|[-*])\s+(.+)$", m.group(1), re.M)] if m else []


# ---------- 阶段 ----------

def obj_skeleton(proj: Project, st: Dict[str, Any]) -> Dict[str, Any]:
    """对象按它「建立」时记下的骨架版本回放和检查（如 任务@1）；骨架升级后旧对象仍按旧版本，旧版本在 历史/ 里找。"""
    name = st["种类"]
    m = re.fullmatch(r"(.+)@(\d+)", st.get("骨架") or "")
    return proj.skeleton(name, int(m.group(2)) if m else None)


def terminal(proj: Project, st: Dict[str, Any]) -> bool:
    try:
        sk = obj_skeleton(proj, st)
    except FlowError:
        sk = proj.skeleton(st["种类"])
    return st["状态"] in sk["终止"]


def cancelled_before_approval(goal: Dict[str, Any], t: Dict[str, Any]) -> bool:
    """批准之前就取消的任务（框架改版去掉的卡）：不进阶段和时序图，也不算批准后新增；事件仍在账本和记录里。"""
    if t["状态"] != "取消":
        return False
    appr = max((e.get("项目序") or 0 for e in goal["事件"] if e.get("边") == "批准"), default=0)
    cancel = max((e.get("项目序") or 0 for e in t["事件"] if e.get("边") == "取消"), default=0)
    return bool(appr) and 0 < cancel < appr


def stage_table(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks = [s for s in states.values() if s["种类"] == "任务" and s["目标"] == goal["编号"]
             and not cancelled_before_approval(goal, s)]
    out: Dict[int, Dict[str, Any]] = {}
    for s in sorted(goal["阶段实例"], key=lambda x: x.get("序", 0)):
        no = s.get("序")
        ts = sorted((t for t in tasks if t["阶段"] == no), key=lambda t: id_key(t["编号"]))
        live = [t for t in ts if t["状态"] != "取消"]
        people = list(s.get("人选", []))
        for t in live:
            if t["拟执行"] and t["拟执行"] not in people:
                people.append(t["拟执行"])
        pre = [p for p in s.get("前置", []) if p in out]
        pre_ok = all(out[p]["状态"] == "通过" for p in pre)
        ended = ts and all(terminal(proj, t) for t in ts)
        passed = ended and any(t["状态"] == "通过" for t in ts)
        started = any(t["状态"] not in ("规划中", "已批准") or t["执行"] for t in ts)
        invalid = False
        if passed and pre_ok:
            status = "通过"
        elif passed or (ended and not passed):
            status = "进行中"
            invalid = passed and not pre_ok
        elif started:
            status = "进行中"
        elif pre_ok:
            status = "可开始"
        else:
            status = "未开始"
        base = {x["编号"] for x in (goal["批准版"] or {}).get("任务", [])} if goal["批准版"] else None
        out[no] = {"序": no, "名称": s.get("名称", ""), "类型": s.get("类型", ""), "人选": people,
                   "前置": list(s.get("前置", [])), "可并行": bool(s.get("可并行")), "产出": s.get("产出", ""),
                   "通过条件": s.get("通过条件", ""), "状态": status, "失效": invalid,
                   "任务": [t["编号"] for t in ts],
                   "批准后新增": [t["编号"] for t in ts if base is not None and t["编号"] not in base],
                   "确认人": [t["拟确认"] for t in live if t["拟确认"]],
                   "待拆": not live}
    return [out[k] for k in sorted(out)]


def structure(goal: Dict[str, Any], stages: List[Dict[str, Any]], by_task: Dict[str, Dict[str, Any]],
              rows: List[Dict[str, Any]], basis_of: Optional[Dict[str, str]] = None,
              side_seqs: List[int] = ()) -> Dict[str, Any]:
    """时序图的骨架：按「阶段 → 任务 → 派发、交付、确认」排，每一步的位置不随事件变。没发生的「计划」为真，
    发生了带项目序，呈现端按项目序取时间和说明。接手并进派发那一行；返工、上报等支线挂在所在步骤后面。"""
    def step(edge, frm, to, seq=None, more=()):
        return {"边": edge, "发起": frm, "接收": to, "计划": seq is None, "项目序": seq, "含": list(more)}
    level: Dict[int, int] = {}
    for s in stages:
        level[s["序"]] = 1 + max([level.get(p, 0) for p in s["前置"]] or [0])
    by_stage = {s["序"]: s for s in stages}
    out_stages, needs_me = [], []
    basis_of = basis_of or {}
    merged: Dict[str, Any] = {}  # 要求序 → 同时改的框架版本
    for s in stages:
        items = []
        for tid in s["任务"]:
            t = by_task[tid]
            ended = t["类别"] == "完成"
            doer = t["执行"] or t["拟执行"] or (s["人选"] or [LEAD])[0]
            checker = t["确认"] or t["拟确认"] or LEAD
            marks = {m["槽位"]: m["项目序"] for m in t["主干"]}
            hidden = ("建立", "接手", "批准", "变更", "进展", "更正", "意见")
            branches: Dict[int, List[Dict[str, Any]]] = {}
            for b in t["支线"]:
                if b["边"] not in hidden:
                    branches.setdefault(b["挂在"], []).append(step(b["边"], b.get("发起"), b.get("接收"), b["项目序"]))
            steps = []
            def put(slot, edge, frm, to, more=()):
                seq = marks.get(slot)
                if seq is not None or not ended:
                    steps.append(step(edge, frm, to, seq, more))
                for x in sorted(k for k in branches if k == slot or (slot == 1 and k in (0, 2))):
                    steps.extend(branches[x])
            if t.get("要求序") is not None and tid in s["批准后新增"]:
                steps.append({**step("要求", BOSS, LEAD, t["要求序"]), "来源": True})  # 总裁要求带来的新增任务：派发前先画总裁 → 总管
            put(1, "派发", LEAD, doer, [marks[2]] if 2 in marks else [])
            put(3, "交付", doer, checker)
            put(4, "确认", checker, "无")
            need = list(t["前置"]) or [x for p in s["前置"] if p in by_stage for x in by_stage[p]["任务"] if by_task[x]["状态"] != "取消"]
            mine = BOSS in (t["拟执行"], t["拟确认"]) and not ended
            if mine:
                needs_me.append(tid)
            items.append({"编号": tid, "标题": t["标题"], "状态": t["状态"], "拟执行": t["拟执行"], "执行": t["执行"],
                          "拟确认": t["拟确认"], "需要": need, "总裁介入": BOSS in (t["拟执行"], t["拟确认"]),
                          "批准后新增": tid in s["批准后新增"],
                          "换人": bool(t["执行"] and t["拟执行"] and t["执行"] != t["拟执行"]), "步骤": steps})
        same = [x["序"] for x in stages if level[x["序"]] == level[s["序"]] and x["序"] != s["序"]]
        out_stages.append({"序": s["序"], "名称": s["名称"], "类型": s["类型"], "状态": s["状态"], "失效": s["失效"],
                           "产出": s["产出"], "通过条件": s["通过条件"], "层": level[s["序"]],
                           "并行": same, "待拆": s["待拆"], "任务": items})
    state = goal["状态"]
    def last(edge):
        return next((r["项目序"] for r in reversed(rows) if r.get("边") == edge), None)
    used = []
    def goal_step(edge, frm, to):
        seq = last(edge)
        if seq is not None:
            used.append(seq)
        return step(edge, frm, to, seq)
    head, tail = [], []
    if state == "起草" and last("提交") is None:
        head.append(step("提交", LEAD, BOSS))
    appr = goal_step("批准", BOSS, LEAD)
    final_check = goal_step("目标验收", LEAD, BOSS)
    tail.append(final_check)
    tail.append(goal_step("完成", BOSS, "无"))
    if state == "取消":
        appr = appr if not appr["计划"] else None
        head = [x for x in head if not x["计划"]]
        tail = [x for x in tail if not x["计划"]]
    late = []
    # 目标层事件（总裁的打回、退回，带原话的变更，每一次目标验收）：按时间插回，不集中放
    added = {tid for sx in stages for tid in sx["批准后新增"]}
    req = {by_task[tid]["要求序"]: tid for tid in added if by_task[tid].get("要求序") is not None}
    gev = []
    for r in rows:
        seq, e = r["项目序"], r.get("边")
        if is_boss_return(r) or e == "目标验收" and seq != final_check["项目序"]:
            gev.append(step(e, BOSS if e != "目标验收" else LEAD, LEAD if e != "目标验收" else BOSS, seq))
        elif e == "变更" and is_quote(r.get("依据"), goal["编号"]):
            host = next((q for q, t in req.items() if basis_of.get(t, "").strip() == r["依据"].strip()), None)
            if host is not None:  # 依据和某个新增任务的建立依据相同：并进那个任务的「要求」，不单独画
                for sx in out_stages:
                    for it in sx["任务"]:
                        for stp in it["步骤"]:
                            if stp["边"] == "要求" and stp["项目序"] == host:
                                stp["含"].append(seq)
                merged[str(host)] = r.get("框架版本")
                used.append(seq)
            else:
                gev.append(step(e, BOSS, LEAD, seq))
    used += [x["项目序"] for x in gev]
    gev.sort(key=lambda x: x["项目序"])
    # 锚点：阶段、任务各自第一条已发生事件的项目序；事件插在锚点晚于它的最早的阶段或任务之前（同点阶段在先）
    approve_seq = appr["项目序"] if appr else None
    cand = []
    for sx in out_stages:
        tas = []
        for it in sx["任务"]:
            sq = [x["项目序"] for x in it["步骤"] if x["项目序"] is not None and approve_seq is not None and x["项目序"] > approve_seq]  # 批准之前的事不算它的位置
            if sq:
                tas.append((min(sq), 1, sx["序"], it))
        if tas:
            cand.append((min(c[0] for c in tas), 0, sx["序"], sx))
            cand += tas
    cand.sort(key=lambda c: (c[0], c[1]))
    for sx in out_stages:
        sx["前"] = []
        for it in sx["任务"]:
            it["前"] = []
    for x in gev:
        if approve_seq is None or x["项目序"] < approve_seq:
            head.append(x)
            continue
        c = next((c for c in cand if c[0] > x["项目序"]), None)
        if c is None:
            late.append(x)
        else:
            c[3]["前"].append(x)
    if appr:
        head.append(appr)
    record_seqs = [r["项目序"] for r in rows if r["项目序"] not in used and r.get("边") not in ("进展", "意见")]
    record_seqs = sorted(record_seqs + list(side_seqs))  # 批准前取消的任务的事件，只在记录里
    return {"记录": record_seqs, "开头": head, "阶段": out_stages, "结尾": late + tail, "介入": needs_me, "合并": merged}


def id_key(x: str) -> Tuple:
    return tuple(int(n) if n.isdigit() else n for n in re.findall(r"\d+|\D+", x))


def template_stages(proj: Project, gtype: str) -> List[Dict[str, Any]]:
    return proj.skeleton(f"目标-{gtype}")["阶段"]


def stage_shape(stages: List[Dict[str, Any]]) -> List[Tuple]:
    return [(s.get("序"), s.get("名称"), s.get("类型"), tuple(s.get("前置", []))) for s in stages]


# ---------- 校验和组装一条事件 ----------

def seat_ok(proj: Project, cls: str, who: Optional[str], st: Dict[str, Any], actor: str) -> bool:
    if cls == "无":
        return who in (None, "无")
    if cls == "管理":
        return who in MANAGERS
    if cls in (LEAD, BOSS):
        return who == cls
    if cls == "自己":
        return who == actor
    if cls == "执行人":
        return who == LEAD or proj.is_member(who)
    if cls == "确认人":
        return who in MANAGERS or proj.is_member(who)
    return False


def resolve_ref(ref: str, st: Dict[str, Any]) -> Any:
    if ref == "@上报前状态":
        return (st["上报前"] or [None, None])[0]
    if ref == "@上报前持有人":
        return (st["上报前"] or [None, None])[1]
    if ref == "@暂停前状态":
        return (st["暂停前"] or [None, None])[0]
    if ref == "@暂停前持有人":
        return (st["暂停前"] or [None, None])[1]
    if ref == "@上次交付人":
        return st["上次交付人"]
    if ref == "@不变":
        return st["状态"]
    return ref


def plan(proj: Project, states: Dict[str, Dict[str, Any]], obj: str, edge: str, a: Dict[str, Any]) -> Dict[str, Any]:
    """检查并组装一条事件（不写盘）。a：发起、给、结果、证据、说明、依据、方案、建议、变更项、阶段、越过等。
    规则错误在带「越过」且发起或写入者是总管、总裁时放行，记下理由。"""
    st = states.get(obj) or blank_state(obj)
    kind = st["种类"]
    sk = proj.skeleton(kind, None)
    actor = a.get("发起")
    if not actor:
        raise hard("发起人不认识：用 --作为 写总管、总裁或花名册里的派活名")
    if edge != "建立" and st["状态"] == "无":
        raise hard(f"{obj} 还没有「建立」事件；先用 `flow.py 建立` 新建")
    if edge == "建立" and st["状态"] != "无":
        raise hard(f"{obj} 已经建立过")
    rules: List[str] = []
    ev: Dict[str, Any] = {"对象": obj, "边": edge, "发起": actor}
    if a.get("随目标"):
        ev["随目标"] = True
    for k in ("证据", "说明", "依据", "方案", "建议", "变更项", "差异理由", "更正", "派活", "会话", "写入者"):
        if a.get(k) not in (None, "", []):
            ev[k] = a[k]
    if kind == "议题" and a.get("与会") is not None and edge in ("建立", "变更"):
        ev["与会"] = attendees(proj, a["与会"])

    if edge in MESSAGES:
        if kind != "议题":
            raise hard(f"「{edge}」只用于议题")
        return message(proj, st, sk, ev, edge, a, rules)

    if edge in SPECIAL:
        spec = sk["特殊事件"].get(edge)
        if spec is None and edge == "起草阶段" and kind == "目标":
            spec = {"必填": []}  # 项目自己覆盖的旧目标骨架没写这个事件也能用
        if spec is None:
            raise hard(f"{kind}没有「{edge}」")
        if edge == "起草阶段":
            if kind != "目标":
                raise hard("「起草阶段」只用于目标")
            if a.get("结果") not in DRAFT_STAGES:
                raise hard(f"「起草阶段」要写 --结果：{' / '.join(DRAFT_STAGES)}")
            if st["状态"] != "起草":
                raise hard(f"{obj} 现在是「{st['状态']}」，想法、讨论、方案只在起草状态下有意义")
            ev["结果"] = a["结果"]
        missing = [k for k in spec.get("必填", []) if not ev.get(k)]
        if missing:
            raise hard(f"「{edge}」必填：{'、'.join(missing)}")
        if edge == "更正":
            seqs = [r.get("seq") for r in st["事件"]] + st["作废"]
            if ev["更正"] not in seqs:
                raise hard(f"{obj} 没有 seq {ev['更正']}")
        if edge == "意见" and actor != BOSS:
            raise hard("「意见」只有总裁能提")
        if edge == "变更" and kind == "任务":
            for k in ("标题", "拟执行", "拟确认", "前置"):
                if a.get(k) is not None:
                    ev[k] = a[k]
            if a.get("任务阶段") is not None:
                ev["阶段"] = a["任务阶段"]
        if edge == "变更" and kind == "目标":
            for k in ("框架版本", "差异"):
                if a.get(k) is not None:
                    ev[k] = a[k]
            need = set(spec.get("要批准的变更项", []))
            if need & set(ev.get("变更项", [])) and not ev.get("依据"):
                rules.append(f"改{'、'.join(sorted(need & set(ev['变更项'])))}要总裁批准：带 --依据 总裁原话")
            if a.get("阶段") is not None:
                check_stage_list(a["阶段"])
                ev["阶段"] = plan_stages(proj, a["阶段"])
        ev["前状态"] = ev["后状态"] = st["状态"]
        ev["接收"] = "无"
        return finish(ev, st, sk, rules, a)

    spec = sk["边"].get(edge)
    if not spec:
        names = "、".join(list(sk["边"]) + list(SPECIAL))
        raise hard(f"{kind}没有「{edge}」这条边；可用：{names}")
    res = a.get("结果")
    target = spec.get("到")
    recv_cls = spec.get("接收")
    default_recv = spec.get("默认接收")
    if "结果" in spec:
        if res not in spec["结果"]:
            raise hard(f"「{edge}」要写 --结果：{' / '.join(spec['结果'])}")
        r = spec["结果"][res]
        target, recv_cls, default_recv = r["到"], r["接收"], r.get("默认接收")
        ev["结果"] = res
    elif res:
        raise hard(f"「{edge}」没有结果")
    missing = [k for k in spec.get("必填", []) if not ev.get(k) and not (k == "证据" and a.get("证据"))]
    if (edge == "上报" or (edge == "转交" and st["状态"] == "受阻")) and proj.actor(a.get("给")) == BOSS:
        missing += [k for k in ("方案", "建议") if not ev.get(k)]
    if missing:
        raise hard(f"「{edge}」必填：{'、'.join(missing)}")

    # 从哪个状态
    if st["状态"] not in spec["从"]:
        rules.append(f"{obj} 现在是「{st['状态']}」，不能走「{edge}」（只能从 {'、'.join(spec['从'])}）")
    # 发起
    holder = st["持有人"]
    ini = spec["发起"]
    if ini == "持有人" and actor != holder:
        rules.append(f"「{edge}」要由持有人发起，现在持有人是 {holder or '—'}，发起的是 {actor}")
    elif ini == "管理" and actor not in MANAGERS:
        rules.append(f"「{edge}」只能由总管或总裁发起")
    elif ini in MANAGERS and actor != ini:
        rules.append(f"「{edge}」只能由{ini}发起")
    # 接收
    given = proj.actor(a["给"]) if a.get("给") else None
    if a.get("给") and not given:
        raise hard(f"接收方「{a['给']}」不是总管、总裁，也不在花名册里")
    if recv_cls == "@该状态席位":
        recv_cls = {"执行中": "执行人", "待验收": "确认人", "受阻": "管理"}.get(st["状态"], "管理")
        if not given:
            raise hard("「转交」要用 --给 写转给谁")
    if recv_cls and recv_cls.startswith("@"):
        recv = resolve_ref(recv_cls, st)
        if given and given != recv:
            rules.append(f"「{edge}」的接收方应是 {recv or '—'}，写的是 {given}；要换人用改派")
        recv = given or recv
    else:
        recv = given
        if recv is None and default_recv:
            recv = resolve_ref(default_recv, st)
        if recv is None and recv_cls in (LEAD, BOSS):
            recv = recv_cls
        if recv is None and recv_cls == "自己":
            recv = actor
        if recv is None and recv_cls == "无":
            recv = "无"
        if recv is None:
            raise hard(f"「{edge}」要用 --给 写接收方（{recv_cls}）")
        if not seat_ok(proj, recv_cls, recv, st, actor):
            rules.append(f"「{edge}」的接收方要是{recv_cls}，写的是 {recv}")
    ev["接收"] = recv or "无"
    to_state = resolve_ref(target, st)
    if not to_state:
        raise hard(f"回放里找不到「{edge}」要回到的状态")

    # 各边的守卫
    if kind == "任务":
        task_guards(proj, states, st, edge, ev, res, rules, sk)
    elif kind == "议题":
        issue_guards(proj, states, st, edge, ev, a, rules, sk)
    else:
        goal_guards(proj, states, st, edge, ev, a, rules)
    if edge == "建立":
        for k in ("目标", "阶段", "键", "标题", "类型", "拟执行", "拟确认"):
            if a.get(k) not in (None, ""):
                ev[k] = a[k]
        if a.get("前置"):
            ev["前置"] = a["前置"]
        if kind == "任务":  # 目标批准前建的卡在规划中；批准后补的卡直接可派，图上标「批准后新增」
            g = states.get(a.get("目标")) or {}
            to_state = "规划中" if g.get("状态") in ("起草", "待批准") else "已批准"
    if edge == "批准" and kind == "任务" and a.get("随目标"):
        ev.pop("随目标", None)
    ev["前状态"], ev["后状态"] = st["状态"], to_state
    return finish(ev, st, sk, rules, a)


def finish(ev: Dict[str, Any], st: Dict[str, Any], sk: Dict[str, Any], rules: List[str], a: Dict[str, Any]) -> Dict[str, Any]:
    ev["骨架"] = f"{sk['骨架']}@{sk['版本']}"
    if rules:
        why = a.get("越过")
        if not why:
            raise rule("；".join(rules))
        if ev["发起"] not in MANAGERS and a.get("写入者") != LEAD:
            raise rule("；".join(rules) + "。只有总管、总裁能越过")
        ev["越过"] = why + "（越过：" + "；".join(rules) + "）"
    return ev


def attendees(proj: Project, spec: List[Any]) -> List[Dict[str, str]]:
    """与会：[{成员, 视角}]；成员必须在花名册里（总裁、总管不算与会者），不重复。"""
    out: List[Dict[str, str]] = []
    for item in spec:
        name, view_ = (item.get("成员"), item.get("视角", "")) if isinstance(item, dict) else (str(item).partition(":")[0], str(item).partition(":")[2])
        who = proj.actor(name)
        if not who or who in MANAGERS:
            raise hard(f"与会者「{name}」不在花名册里")
        if any(x["成员"] == who for x in out):
            raise hard(f"与会者 {who} 写了两次")
        out.append({"成员": who, "视角": (view_ or "").strip()})
    if not out:
        raise hard("与会至少要有一位成员")
    return out


def message(proj: Project, st: Dict[str, Any], sk: Dict[str, Any], ev: Dict[str, Any], edge: str,
            a: Dict[str, Any], rules: List[str]) -> Dict[str, Any]:
    """发言、PASS：只存事实（正文、点名、是否私下、总裁自选的类型），发言类型由投影推出。"""
    spec = sk["消息事件"][edge]
    if edge == "发言":
        if not (a.get("正文") or "").strip():
            raise hard("「发言」必填：正文")
        ev["正文"] = a["正文"]
    names = [x["成员"] for x in st["与会"]]
    if st["状态"] not in spec.get("可在", []):
        rules.append(f"{st['编号']} 现在是「{st['状态']}」，只有讨论中能{edge}")
    if ev["发起"] not in MANAGERS and ev["发起"] not in names:
        rules.append(f"{ev['发起']} 不在 {st['编号']} 的与会名单里（{'、'.join(names)}）")
    called = []
    for w in a.get("点名") or []:
        who = proj.actor(w)
        if not who or (who not in MANAGERS and who not in names):
            raise hard(f"点名的「{w}」不是总裁、总管或与会者")
        if who not in called and who != ev["发起"]:
            called.append(who)
    if called:
        ev["点名"] = called
    if a.get("私下"):
        ev["私下"] = True
    if a.get("类型") and ev["发起"] == BOSS:
        ev["类型"] = a["类型"]
    ev["前状态"] = ev["后状态"] = st["状态"]
    ev["接收"] = "无"
    return finish(ev, st, sk, rules, a)


def open_reviews(states: Dict[str, Dict[str, Any]], goal: str) -> List[Dict[str, Any]]:
    """挂在目标上、还没结束的框架会审。"""
    return [s for s in sorted(states.values(), key=lambda x: id_key(x["编号"]))
            if s["种类"] == "议题" and s["目标"] == goal and s["类型"] == "会审" and s["状态"] not in ("已裁决", "取消", "无")]


def issue_guards(proj, states, st, edge, ev, a, rules, sk):
    if edge == "建立":
        itype = a.get("类型") or "朝会"
        if itype not in sk["类型"]:
            raise hard(f"议题类型要是：{' / '.join(sk['类型'])}")
        a["类型"] = itype
        goal = a.get("目标")
        if goal:
            g = states.get(goal)
            if not g or g["种类"] != "目标" or g["状态"] == "无":
                rules.append(f"目标 {goal} 没有建立")
            elif itype == "会审" and g["状态"] != "待批准":
                rules.append(f"框架会审要在目标待批准时开，{goal} 现在是「{g['状态']}」")
            elif g["状态"] in ("完成", "取消"):
                rules.append(f"目标 {goal} 已{g['状态']}")
        elif itype == "会审":
            raise hard("框架会审要用 --目标 写挂在哪个目标上")


def task_guards(proj, states, st, edge, ev, res, rules, sk):
    if edge == "建立":
        return
    if edge == "批准" and not ev.get("随目标"):
        raise hard("任务没有单独的批准：批准目标时，它下面的任务一起批准")
    if st["状态"] == "规划中" and edge not in ("批准", "取消"):
        raise hard(f"{st['编号']} 还在规划中：目标 {st['目标']} 批准后才能开工，这一步不能越过")
    if edge == "交付":
        for p in ev.get("证据", []):
            path = Path(p).expanduser()
            if not path.is_absolute():
                path = proj.root / p
            if not path.exists():
                raise hard(f"证据不存在：{p}")
    if edge == "确认":
        if ev["发起"] == st["上次交付人"] and ev["发起"] != LEAD:
            rules.append(f"确认人不能是上次交付人（{ev['发起']}）")
        if res == "需补充" and ev["发起"] != BOSS and ev["接收"] == st["返工人"] and st["返工次"] + 1 >= sk.get("返工上限", 3):
            rules.append(f"{ev['接收']} 已连续返工 {st['返工次']} 次，到上限后只能改派、转交或上报")
    if edge == "转交" and st["状态"] == "待验收" and ev["接收"] == st["上次交付人"] and ev["接收"] != LEAD:
        rules.append("不能转给上次交付人确认")
    if edge in ("派发", "改派", "重开") and st["目标"]:
        g = states.get(st["目标"])
        if not g or g["状态"] == "无":
            rules.append(f"所属目标 {st['目标']} 没有建立")
            return
        if g["状态"] in ("起草", "待批准"):
            raise hard(f"目标 {g['编号']} 是「{g['状态']}」，批准后才能派发，这一步不能越过")
        if g["状态"] != "进行中":
            rules.append(f"目标 {g['编号']} 是「{g['状态']}」，进行中才能派发")
        if edge == "派发":
            miss = handoff_gaps(proj, st["编号"])
            if miss:
                raise hard(f"{st['编号']} 的交接缺 {'、'.join(miss)}：写好任务卡再派发")
        for p in st["前置"]:
            if (states.get(p) or {}).get("状态") not in ("通过", "取消"):
                rules.append(f"{st['编号']} 依赖的 {p} 还没通过")
        stage = next((s for s in stage_table(proj, g, states) if s["序"] == st["阶段"]), None)
        if not stage:
            rules.append(f"目标 {g['编号']} 的阶段实例里没有阶段 {st['阶段']}")
        else:
            if stage["状态"] == "未开始":
                rules.append(f"阶段 {stage['序']}「{stage['名称']}」的前置还没通过")
            if stage["人选"] and ev["接收"] not in stage["人选"]:
                rules.append(f"阶段 {stage['序']} 的人选是 {'、'.join(stage['人选'])}，派的是 {ev['接收']}")


def goal_guards(proj, states, st, edge, ev, a, rules):
    if edge == "建立":
        gtype = a.get("类型") or "通用"
        a["类型"] = gtype  # 建立目标只需标题和依据，类型默认通用
        if gtype not in proj.skeleton("目标")["类型"]:
            raise hard(f"目标类型要是：{' / '.join(proj.skeleton('目标')['类型'])}")
        return
    if edge == "提交":
        if a.get("阶段") is not None:
            raise hard("阶段和任务用 `flow.py 框架` 写，提交不再带阶段")
        gaps = frame_gaps(proj, st, states)
        if gaps:
            raise hard("框架还没搭好，不能提交：" + "；".join(gaps))
    if edge == "批准":
        if a.get("阶段") is not None:
            raise hard("批准不改结构：要改先用 `flow.py 框架`")
        if a.get("框架版本") is not None and int(a["框架版本"]) != st["框架版本"]:
            raise hard(f"框架已更新到第 {st['框架版本']} 版，你看到的是第 {a['框架版本']} 版：刷新后再批准")
        gaps = frame_gaps(proj, st, states)
        if gaps:
            raise hard("框架不完整，不能批准：" + "；".join(gaps))
        stages = [dict(s) for s in st["阶段实例"]]
        for no, who in (a.get("人选") or {}).items():
            s = next((x for x in stages if x.get("序") == no), None)
            if not s:
                raise hard(f"没有阶段 {no}")
            s["人选"] = who
        check_stage_list(stages)
        stages = plan_stages(proj, stages)
        ev["阶段"] = stages
        ev["批准版"] = approved_snapshot(proj, st, states)
    if edge in ("批准", "退回"):
        for s in open_reviews(states, st["编号"]):
            if s["状态"] != "待裁决":
                rules.append(f"会审 {s['编号']} 还没收口（现在是「{s['状态']}」）")
    if edge == "目标验收":
        table = stage_table(proj, st, states)
        if not table or any(s["状态"] != "通过" for s in table):
            left = [f"{s['序']}（{s['状态']}）" for s in table if s["状态"] != "通过"]
            rules.append("阶段还没全部通过：" + ("、".join(left) or "没有阶段"))


def plan_stages(proj: Project, stages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """整理阶段实例：人名换成花名册里的名字。任务不在阶段里存，任务卡是唯一来源。"""
    out = []
    for s in stages:
        s = {k: v for k, v in s.items() if k not in ("计划任务", "任务")}
        people = []
        for w in s.get("人选", []):
            x = proj.actor(w) or w
            if x not in MANAGERS and not proj.is_member(x):
                raise hard(f"阶段 {s.get('序')} 的人选 {w} 不在花名册里")
            people.append(x)
        s["人选"] = people
        out.append(s)
    return out


HANDOFF_FIELDS = ("目的", "身份", "硬约束", "可替换的做法", "输入", "交付物", "验收标准", "授权", "上报条件")
HANDOFF_REQUIRED = ("目的", "交付物", "验收标准")


def handoff_fields(text: str) -> Dict[str, str]:
    """把任务卡「交接」一节拆成字段：`- 名称：内容`，内容可以跨行。"""
    out: Dict[str, str] = {}
    key = None
    for line in text.splitlines():
        m = re.match(r"^-\s*([^：:]{1,12})[：:]\s*(.*)$", line)
        if m and m.group(1) in HANDOFF_FIELDS:
            key = m.group(1)
            out[key] = m.group(2).strip()
        elif key and line.strip():
            out[key] = (out[key] + "\n" + line.strip()).strip()
    return out


def handoff_like(text: str) -> Dict[str, str]:
    """目标卡「要什么」的 `- 名称：内容` 拆成字段。"""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^-\s*([^：:]{1,12})[：:]\s*(.*)$", text, re.M)}


def handoff_text(fields: Dict[str, Any]) -> str:
    return "\n".join(f"- {k}：{str(fields.get(k) or '').strip()}" for k in HANDOFF_FIELDS)


def handoff_gaps(proj: Project, tid: str) -> List[str]:
    got = handoff_fields(card_section(proj, tid, "交接"))
    return [k for k in HANDOFF_REQUIRED if not got.get(k)]


def goal_tasks(states: Dict[str, Dict[str, Any]], goal: str) -> List[Dict[str, Any]]:
    return sorted((t for t in states.values() if t["种类"] == "任务" and t["目标"] == goal and t["状态"] != "取消"),
                  key=lambda t: id_key(t["编号"]))


def frame_gaps(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> List[str]:
    """提交、批准前框架还缺什么：每个阶段至少一张卡，每张卡有执行人、确认人和必填内容。"""
    if not goal["阶段实例"]:
        return ["还没有阶段和任务：先运行 flow.py 框架"]
    gaps = []
    wish = handoff_like(card_section(proj, goal["编号"], "要什么"))
    missing = [k for k in ("要什么", "成功标准") if not wish.get(k)]
    if missing:
        gaps.append(f"目标卡缺 {'、'.join(missing)}")
    tasks = goal_tasks(states, goal["编号"])
    for s in goal["阶段实例"]:
        if not any(t["阶段"] == s.get("序") for t in tasks):
            gaps.append(f"阶段 {s.get('序')}「{s.get('名称', '')}」没有任务卡")
    for t in tasks:
        if not t["拟执行"] or not t["拟确认"]:
            gaps.append(f"{t['编号']} 没写执行人或确认人")
        miss = handoff_gaps(proj, t["编号"])
        if miss:
            gaps.append(f"{t['编号']} 交接缺 {'、'.join(miss)}")
    return gaps


def approved_snapshot(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {"版本": goal["框架版本"], "任务": [
        {"编号": t["编号"], "标题": t["标题"], "阶段": t["阶段"], "拟执行": t["拟执行"], "拟确认": t["拟确认"],
         "前置": t["前置"], "内容": sha(card_section(proj, t["编号"], "交接"))} for t in goal_tasks(states, goal["编号"])]}


def approved_diff(proj: Project, goal: Dict[str, Any], states: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """现在和批准版的差别。"""
    base = goal.get("批准版")
    if not base:
        return []
    old = {x["编号"]: x for x in base["任务"]}
    out = []
    all_tasks = sorted((t for t in states.values() if t["种类"] == "任务" and t["目标"] == goal["编号"]), key=lambda t: id_key(t["编号"]))
    for t in all_tasks:
        tid, was = t["编号"], old.get(t["编号"])
        if not was:
            if t["状态"] != "取消":
                out.append({"类型": "新增", "任务": tid, "说明": f"{t['标题']}（{t['拟执行'] or t['执行'] or '—'}）"})
            continue
        if t["状态"] == "取消":
            out.append({"类型": "取消", "任务": tid, "说明": t["标题"]})
            continue
        now_doer = t["执行"] or t["拟执行"]
        if now_doer != was["拟执行"]:
            out.append({"类型": "换人", "任务": tid, "说明": f"{was['拟执行']} → {now_doer}"})
        if t["拟确认"] != was["拟确认"]:
            out.append({"类型": "换确认人", "任务": tid, "说明": f"{was['拟确认']} → {t['拟确认']}"})
        if t["前置"] != was["前置"] or t["阶段"] != was["阶段"]:
            out.append({"类型": "依赖改了", "任务": tid, "说明": t["标题"]})
        if sha(card_section(proj, tid, "交接")) != was["内容"]:
            out.append({"类型": "内容改了", "任务": tid, "说明": t["标题"]})
    return out


def check_stage_list(stages: List[Dict[str, Any]]) -> None:
    seen = set()
    for s in stages:
        no = s.get("序")
        if not isinstance(no, int) or no in seen:
            raise hard(f"阶段的「序」要是不重复的整数：{no}")
        if s.get("类型") not in ("执行", "调研", "验收"):
            raise hard(f"阶段 {no} 的类型要是 执行 / 调研 / 验收")
        for p in s.get("前置", []):
            if p not in seen:
                raise hard(f"阶段 {no} 的前置 {p} 要是排在它前面的阶段")
        seen.add(no)
        s.setdefault("前置", [])
        s.setdefault("人选", [])
        s.setdefault("可并行", False)


# ---------- 写入 ----------

def record(proj: Project, obj: str, edge: str, a: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """加锁、校验、追加一条事件、重渲染。返回（事件，提醒）。"""
    with locked(proj):
        states, evs, _ = replay_all(proj)
        ev = plan(proj, states, obj, edge, a)
        append(proj, evs, obj, ev, a)
        if kind_of(obj) == "目标" and edge == "批准":  # 工作目录批准时才建，想法和讨论阶段不留空目录
            (proj.root / workdir(proj, obj)).mkdir(parents=True, exist_ok=True)
        # 框架会审随目标的批准或退回一起裁决（方案 03 第 10.3 节 B）
        if kind_of(obj) == "目标" and edge in ("批准", "退回"):
            states = {o: replay(o, rs) for o, rs in evs.items()}
            for s in [x for x in open_reviews(states, obj) if x["状态"] == "待裁决"]:
                b = {"发起": BOSS, "写入者": ev.get("写入者"), "依据": ev.get("依据") or ev.get("说明"),
                     "说明": f"随 {obj}「{edge}」裁决"}
                append(proj, evs, s["编号"], plan(proj, states, s["编号"], "裁决", b), b)
        # 目标批准，它下面规划中的任务一起批准；目标取消，规划中的任务一起取消
        if kind_of(obj) == "目标" and edge in ("批准", "取消"):
            states = {o: replay(o, rs) for o, rs in evs.items()}
            for t in [x for x in goal_tasks(states, obj) if x["状态"] == "规划中"]:
                b = {"发起": BOSS if edge == "批准" else LEAD, "写入者": ev.get("写入者"), "依据": ev.get("依据") or "",
                     "说明": f"随 {obj}「{edge}」", "随目标": True}
                append(proj, evs, t["编号"], plan(proj, states, t["编号"], edge, b), b)
        render_all(proj)
    notes = []
    st = replay(obj, evs.get(obj, []))
    if st["返工次"] == 2:
        notes.append(f"{st['返工人']} 已连续返工 2 次：建议升档改派（协议「连续两次返工升一档」）")
    return ev, notes


def append(proj: Project, evs: Dict[str, List[Dict[str, Any]]], obj: str, ev: Dict[str, Any], a: Dict[str, Any]) -> None:
    """在已持有的锁里给事件发号、追加一行，并更新内存里的 evs。"""
    rows = evs.setdefault(obj, [])
    ev["v"] = EVENT_V
    ev["seq"] = len(rows) + 1
    ev["项目序"] = 1 + max([r.get("项目序", 0) for rs in evs.values() for r in rs] or [0])
    ev["时间"] = iso(now_dt())
    ev.setdefault("写入者", a.get("写入者") or (LEAD if ev["发起"] in MANAGERS else "成员"))
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
    if kind in ("目标", "议题"):
        pre = "G" if kind == "目标" else "I"
        n = max([int(x[1:]) for x in ids if re.fullmatch(pre + r"\d+", x)] or [0]) + 1
        return f"{pre}{n:03d}"
    if goal:
        n = max([int(x.split("-T")[1]) for x in ids if re.fullmatch(re.escape(goal) + r"-T\d+", x)] or [0]) + 1
        return f"{goal}-T{n}"
    n = max([int(x[1:]) for x in ids if re.fullmatch(r"T\d+", x)] or [0]) + 1
    return f"T{n:03d}"


def slug(title: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "", title)
    return s[:24] or "未命名"


def block(name: str, obj: str, body: str) -> str:
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"<!-- flow:{name} {obj} {VIEW} sha={sha(body)} -->\n{body}<!-- /flow -->"


def new_card_text(kind: str, obj: str, title: str, small: bool) -> str:
    h1, h2 = ("##", "###") if small else ("#", "##")
    if kind == "议题":
        return (f"# {obj} {title}\n{block('卡头', obj, '')}\n\n"
                f"## 问题\n- 要决定什么：\n- 背景与约束：\n- 参考资料：\n- 已知选项：\n\n"
                f"## 与会\n{block('与会', obj, '')}\n\n"
                f"## 发言\n<!-- 由 flow.py 生成的索引，全文在朝会页面或 `flow.py 上下文` -->\n{block('发言', obj, '')}\n\n"
                f"## 总结（总管）\n- 共识：\n- 分歧：<各方立场、依据、代价>\n- 建议：\n\n"
                f"## 裁决\n{block('裁决', obj, '')}\n")
    if kind == "目标":
        return (f"{h1} {obj} {title}\n{block('卡头', obj, '')}\n\n"
                f"{h2} 要什么\n- 要什么：\n- 成功标准：\n\n"
                f"{h2} 流程\n{block('流程', obj, '')}\n\n{h2} 变更\n{block('变更', obj, '')}\n\n"
                f"{h2} 议题\n{block('议题', obj, '')}\n")
    return (f"{h1} {obj} {title}\n{block('卡头', obj, '')}\n\n"
            f"{h2} 流转\n<!-- 由 flow.py 生成，用 `flow.py 记` 写入，不要手改 -->\n{block('流转', obj, '')}\n\n"
            f"{h2} 交接\n- 目的：\n- 身份：\n- 硬约束：\n- 可替换的做法：\n- 输入：\n- 交付物：\n- 验收标准：\n"
            f"- 授权：\n- 上报条件：\n\n{h2} 备注\n")


def create(proj: Project, kind: str, a: Dict[str, Any]) -> Tuple[str, Path]:
    with locked(proj):
        obj = next_id(proj, kind, a.get("目标"))
        states, _, _ = replay_all(proj)
        if kind == "任务" and a.get("目标"):
            g = states.get(a["目标"])
            if not g:
                raise hard(f"目标 {a['目标']} 没有建立")
            if a.get("阶段") is None:
                raise hard("属于目标的任务要写 --阶段")
            if a["阶段"] not in [s.get("序") for s in g["阶段实例"]]:
                raise hard(f"目标 {a['目标']} 没有阶段 {a['阶段']}（先运行 flow.py 框架）")
            if g["状态"] in ("完成", "取消"):
                raise hard(f"目标 {a['目标']} 已{g['状态']}，不能再建任务")
        if kind == "任务" and not a.get("目标"):
            raise hard("任务必须归属目标：用 --目标 G00x；没有合适的目标就先建一个，一件小事就是一个目标加一张卡")
        ev = plan(proj, states, obj, "建立", a)
        text = new_card_text(kind, obj, a.get("标题", ""), proj.small)
        if kind == "任务" and a.get("交接"):
            text = set_handoff(text, a["交接"])
        if kind == "议题":
            path = proj.collab / "议题" / f"{obj}-{slug(a.get('标题', ''))}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            write_if_changed(path, text)
        elif proj.small:
            path = proj.collab / ("目标.md" if kind == "目标" else "任务.md")
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            m = re.search(r"^## " + ID_RE, old, re.M)
            new = old[: m.start()] + text + "\n" + old[m.start():] if m else old.rstrip("\n") + "\n\n" + text
            write_if_changed(path, new)
        else:
            path = proj.collab / ("目标" if kind == "目标" else "任务") / f"{obj}-{slug(a.get('标题', ''))}.md"
            write_if_changed(path, text)
    ev2, _ = record(proj, obj, "建立", a)
    return obj, path


def set_handoff(text: str, fields: Dict[str, Any]) -> str:
    """把卡片文本里「交接」一节换成给定字段；备注和生成块不动。"""
    m = re.search(r"^(#{2,3}) 交接\s*$", text, re.M)
    if not m:
        raise hard("任务卡里没有「交接」一节")
    rest = text[m.end():]
    n = re.search(r"^#{1,%d}\s" % len(m.group(1)), rest, re.M)
    tail = rest[n.start():] if n else ""
    return text[:m.end()] + "\n" + handoff_text(fields) + "\n" + ("\n" + tail if tail else "")


def card_path(proj: Project, obj: str) -> Optional[Path]:
    for f in proj.card_files():
        if re.search(r"^#{1,2}\s*" + re.escape(obj) + r"(?![-\w]).*$", f.read_text(encoding="utf-8"), re.M):
            return f
    return None


def frame(proj: Project, goal: str, spec: Dict[str, Any], a: Dict[str, Any]) -> Dict[str, Any]:
    """搭框架、改框架：一次写好阶段和全部任务卡。可重复运行，这就是改图的方式。按「键」认任务（没写就用标题）。"""
    with locked(proj):
        states, evs, _ = replay_all(proj)
        g = states.get(goal)
        if not g or g["种类"] != "目标":
            raise hard(f"目标 {goal} 没有建立")
        if g["状态"] in ("完成", "取消", "待确认"):
            raise hard(f"目标 {goal} 是「{g['状态']}」，不能改框架")
        raw = spec.get("阶段")
        if not isinstance(raw, list) or not raw:
            raise hard("框架文件要有「阶段」列表")
        stages = [{k: v for k, v in s.items() if k != "任务"} for s in raw]
        check_stage_list(stages)
        stages = plan_stages(proj, stages)
        # 校验：每个阶段至少一张卡；键不重复；前置只能写排在前面的任务
        items, seen = [], {}
        for s in raw:
            if not s.get("任务"):
                raise hard(f"阶段 {s.get('序')}「{s.get('名称', '')}」没有任务：想不清的也先建一张粗略的卡，写明什么时候细化")
            for t in s["任务"]:
                title = str(t.get("标题", "")).strip()
                if not title or not t.get("执行"):
                    raise hard(f"阶段 {s.get('序')} 的任务要写 标题、执行")
                key = str(t.get("键") or title)
                if key in seen:
                    raise hard(f"任务的键「{key}」重复")
                doer = proj.actor(t["执行"]) or t["执行"]
                checker = proj.actor(t.get("确认") or LEAD) or t.get("确认")
                for w in (doer, checker):
                    if w not in MANAGERS and not proj.is_member(w):
                        raise hard(f"任务「{title}」的 {w} 不在花名册里")
                if doer == checker and doer != LEAD:
                    raise hard(f"任务「{title}」的确认人不能是执行人（{doer}）")
                for p in t.get("前置", []):
                    if str(p) not in seen:
                        raise hard(f"任务「{title}」的前置「{p}」要写排在它前面的任务的键")
                seen[key] = True
                items.append({"键": key, "标题": title, "阶段": s["序"], "拟执行": doer, "拟确认": checker,
                              "前置键": [str(p) for p in t.get("前置", [])],
                              "交接": {k: t[k] for k in HANDOFF_FIELDS if k in t}})
        existing = {(t["键"] or t["标题"]): t for t in goal_tasks(states, goal)}
        basis = a.get("依据") or f"{goal} 框架"
        base = {"发起": LEAD, "写入者": a.get("写入者") or LEAD}
        changes: List[str] = []
        ids: Dict[str, str] = {}
        def refresh(obj):
            states[obj] = replay(obj, evs[obj])
        version = g["框架版本"] + 1
        for item in items:
            need = [ids[k] for k in item["前置键"]]
            old = existing.get(item["键"])
            if not old:
                obj = next_id(proj, "任务", goal)
                ids[item["键"]] = obj
                text = set_handoff(new_card_text("任务", obj, item["标题"], proj.small), item["交接"])
                path = proj.collab / "任务" / f"{obj}-{slug(item['标题'])}.md"
                write_if_changed(path, text)
                b = {**base, "目标": goal, "阶段": item["阶段"], "键": item["键"], "标题": item["标题"], "依据": basis,
                     "拟执行": item["拟执行"], "拟确认": item["拟确认"], "前置": need}
                ev = plan(proj, states, obj, "建立", b)
                append(proj, evs, obj, ev, b)
                refresh(obj)
                changes.append(f"新增 {obj} {item['标题']}（{item['拟执行']} 做，{item['拟确认']} 确认）")
                continue
            tid = old["编号"]
            ids[item["键"]] = tid
            diff, what = {}, []
            if old["标题"] != item["标题"]:
                diff["标题"] = item["标题"]
                what.append("标题")
            if old["阶段"] != item["阶段"]:
                diff["任务阶段"] = item["阶段"]
                what.append("阶段")
            if old["拟执行"] != item["拟执行"]:
                diff["拟执行"] = item["拟执行"]
                what.append(f"执行 {old['拟执行'] or '—'} → {item['拟执行']}")
            if old["拟确认"] != item["拟确认"]:
                diff["拟确认"] = item["拟确认"]
                what.append(f"确认 {old['拟确认'] or '—'} → {item['拟确认']}")
            if list(old["前置"]) != need:
                diff["前置"] = need
                what.append("依赖")
            path = card_path(proj, tid)
            cur_fields = handoff_fields(card_section(proj, tid, "交接"))
            merged = {**cur_fields, **{k: str(v).strip() for k, v in item["交接"].items()}}  # 框架文件没写的字段保留卡片原样
            if path and any(merged.get(k, "") != cur_fields.get(k, "") for k in HANDOFF_FIELDS):
                path.write_text(set_handoff(path.read_text(encoding="utf-8"), merged), encoding="utf-8")
                what.append("内容")
            if what:
                b = {**base, **diff, "说明": "框架第 %d 版：%s" % (version, "、".join(what)), "变更项": what}
                append(proj, evs, tid, plan(proj, states, tid, "变更", b), b)
                refresh(tid)
                changes.append(f"改 {tid} {item['标题']}：{'、'.join(what)}")
        for key, old in existing.items():
            if key in seen:
                continue
            if old["状态"] not in ("规划中", "已批准"):
                raise hard(f"{old['编号']} 已经开工（{old['状态']}），不能从框架里删；要停先走取消")
            b = {**base, "说明": f"框架第 {version} 版去掉了这个任务"}
            append(proj, evs, old["编号"], plan(proj, states, old["编号"], "取消", b), b)
            refresh(old["编号"])
            changes.append(f"取消 {old['编号']} {old['标题']}")
        if g["阶段实例"] and [dict(s) for s in g["阶段实例"]] != stages:
            changes.insert(0, "调整了阶段")
        if not changes and g["框架版本"]:
            return {"版本": g["框架版本"], "改动": []}
        b = {**base, "阶段": stages, "框架版本": version, "差异": changes or ["搭好框架"],
             "说明": a.get("说明") or f"框架第 {version} 版", "变更项": ["框架"]}
        if a.get("依据"):
            b["依据"] = a["依据"]
        append(proj, evs, goal, plan(proj, states, goal, "变更", b), b)
        render_all(proj)
        return {"版本": version, "改动": b["差异"]}


def archive_goal(proj: Project, goal: str) -> List[str]:
    """目标卡移到 collab/归档/目标/，目标自己的目录（问题.md、方案.md 等）一起移。返回移了什么（相对项目根）。"""
    with locked(proj):
        states, _, _ = replay_all(proj)
        g = states.get(goal)
        if not g or g["种类"] != "目标":
            raise hard(f"目标 {goal} 没有建立")
        if proj.small:
            raise hard("单文件版项目的目标在 目标.md 里，没有目标目录可移")
        card = card_path(proj, goal)
        live, arch = proj.collab / "目标", proj.collab / "归档" / "目标"
        moved: List[str] = []
        if card and card.parent == live:
            if g["状态"] not in ("完成", "取消"):
                raise hard(f"目标 {goal} 是「{g['状态']}」，完成或取消后才能归档")
            arch.mkdir(parents=True, exist_ok=True)
            if (arch / card.name).exists():
                raise hard(f"{proj.rel(arch / card.name)} 已存在")
            card.rename(arch / card.name)
            moved.append(f"{proj.rel(card)} → {proj.rel(arch / card.name)}")
        elif not card or card.parent != arch:
            raise hard(f"找不到目标 {goal} 的卡片")
        src, dst = live / goal, arch / goal
        if src.is_dir():
            if dst.exists():
                raise hard(f"{proj.rel(dst)} 已存在，目录没有移")
            src.rename(dst)
            moved.append(f"{proj.rel(src)}/ → {proj.rel(dst)}/")
        return moved


def start_self(proj: Project, obj: str, a: Dict[str, Any]) -> None:
    """总管自己执行：一条命令写派发和接手。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["种类"] != "任务":
        raise hard(f"{obj} 不是任务")
    base = {"发起": LEAD, "写入者": a.get("写入者") or LEAD}
    record(proj, obj, "派发", {**base, "给": LEAD, "说明": a.get("说明") or "总管自己执行"})
    record(proj, obj, "接手", {**base, "说明": "开工"})


# ---------- 投影：视图模型 ----------

def holds(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out, cur = [], None
    for ev in rows:
        if ev.get("边") in SPECIAL or (ev.get("边") == "接手"):
            continue
        to = ev.get("接收")
        who = None if to in (None, "无") else to
        if cur and cur["人"] == who:
            continue
        if cur:
            cur["止序"], cur["止时"] = ev["项目序"], ev["时间"]
            out.append(cur)
            cur = None
        if who:
            cur = {"人": who, "起序": ev["项目序"], "起时": ev["时间"], "止序": None, "止时": None}
    if cur:
        out.append(cur)
    return out


def handoffs(rows: List[Dict[str, Any]], states_sk: Dict[str, Any]) -> List[Dict[str, Any]]:
    """每条改状态的事件之后，这个对象「谁交过来、现在在谁手里、什么状态」的切面（关系图和它的回放用）。
    持有人取法和「当前」一致：接手不换持有人，交过来的人仍是上一条换持有人的事件的发起方。"""
    out, giver, holder = [], None, None
    for ev in rows:
        if ev.get("边") in SPECIAL + MESSAGES:
            continue
        if ev.get("边") not in KEEP_HOLDER:
            giver = ev.get("发起")
            holder = None if ev.get("接收") in (None, "无") else ev.get("接收")
        state = ev.get("后状态", "")
        out.append({"项目序": ev["项目序"], "时间": ev["时间"], "边": ev["边"], "发起": giver, "持有人": holder,
                    "状态": state, "类别": states_sk.get(state, {}).get("类别", "")})
    return out


def trunk_marks(rows: List[Dict[str, Any]], passed: bool) -> Dict[int, int]:
    """主干槽位：建立、派发、接手取首次；交付取最后一次通过确认之前那次；确认取最后一次且结果为通过。返回 {项目序: 槽位}。"""
    marks: Dict[int, int] = {}
    def first(edge):
        return next((r for r in rows if r.get("边") == edge), None)
    for slot, edge in enumerate(("建立", "派发", "接手")):
        r = first(edge)
        if r:
            marks[r["项目序"]] = slot
    ok = [r for r in rows if r.get("边") == "确认" and r.get("结果") == "通过"]
    final = ok[-1] if ok and passed else None
    deliveries = [r for r in rows if r.get("边") == "交付" and (not final or r["项目序"] < final["项目序"])]
    if deliveries:
        marks[deliveries[-1]["项目序"]] = 3
    if final:
        marks[final["项目序"]] = 4
    return marks


def view(proj: Project) -> Dict[str, Any]:
    states, evs, probs = replay_all(proj)
    render_rule = proj.skeleton("渲染")
    fixed = render_rule["固定参与者"]
    eff = {obj: [e for e in st["事件"]] for obj, st in states.items()}
    tasks, goals = [], []
    for obj in sorted(states, key=id_key):
        st = states[obj]
        if st["种类"] != "任务":
            continue
        rows = eff[obj]
        marks = trunk_marks(rows, st["状态"] == "通过" and st["通过有效"])
        sk = proj.skeleton("任务")
        last_confirm = next((r for r in reversed(rows) if r.get("边") == "确认"), None)
        tasks.append({
            "编号": obj, "标题": st["标题"], "目标": st["目标"], "阶段": st["阶段"], "状态": st["状态"],
            "类别": sk["状态"].get(st["状态"], {}).get("类别", ""), "持有人": st["持有人"], "执行": st["执行"],
            "确认": st["确认"], "返工次": st["返工次"], "自确认": st["自确认"],
            "键": st["键"], "拟执行": st["拟执行"], "拟确认": st["拟确认"], "前置": st["前置"],
            "内容": handoff_fields(card_section(proj, obj, "交接")),
            "意见": [{"时间": r.get("时间"), "说明": r.get("说明", ""), "项目序": r.get("项目序")} for r in st["意见"]],
            "结论": (last_confirm or {}).get("说明", ""),
            "要求序": next((r["项目序"] for r in rows if r.get("边") == "建立" and is_quote(r.get("依据"), st["目标"])), None),
            "主干": [{"槽位": marks[r["项目序"]], "项目序": r["项目序"], "边": r["边"]} for r in rows if r["项目序"] in marks],
            "支线": [{"项目序": r["项目序"], "边": r["边"], "发起": r.get("发起"), "接收": r.get("接收"), "挂在": max([s for q, s in marks.items() if q < r["项目序"]] or [0])}
                   for r in rows if r["项目序"] not in marks],
            "持有期": holds(rows),
            "交接": handoffs(rows, sk["状态"]),
        })
    by_task = {t["编号"]: t for t in tasks}
    for obj in sorted(states, key=id_key):
        st = states[obj]
        if st["种类"] != "目标":
            continue
        stages = stage_table(proj, st, states)
        mine = [t for t in tasks if t["目标"] == obj]
        gcls = proj.skeleton("目标")["状态"].get(st["状态"], {}).get("类别", "")
        basis_of = {t["编号"]: next((r.get("依据") or "" for r in eff[t["编号"]] if r.get("边") == "建立"), "") for t in mine}
        gone = [t["编号"] for t in mine if cancelled_before_approval(st, states[t["编号"]])]
        S = structure(st, stages, by_task, eff[obj], basis_of, [r["项目序"] for o in gone for r in eff[o]])
        evrows = event_rows(states, [obj] + [t["编号"] for t in mine], eff, by_task,
                            {x for s in stages for x in s["批准后新增"]})
        for r in evrows:
            v = S["合并"].get(str(r["项目序"]))
            if r["边"] == "建立" and v is not None:
                r["同改框架版"] = v
        goals.append({"编号": obj, "标题": st["标题"], "类型": st["类型"], "状态": st["状态"],
                      "类别": gcls, "起草阶段": draft_stage(st), "文件": goal_files(proj, obj), "待解决": open_questions(proj, obj),
                      "持有人": st["持有人"], "工作目录": workdir(proj, obj), "阶段": stages,
                      "议题": [i for i in sorted(states, key=id_key) if states[i]["种类"] == "议题" and states[i]["目标"] == obj],
                      "交接": handoffs(eff[obj], proj.skeleton("目标")["状态"]),
                      "参与者": participants(fixed, stages, [e for o in [obj] + [t["编号"] for t in mine] for e in eff.get(o, [])]),
                      "事件": evrows,
                      "结构": S,
                      "框架版本": st["框架版本"], "本轮改动": st["本轮改动"], "批准版本": (st["批准版"] or {}).get("版本"),
                      "差别": approved_diff(proj, st, states),
                      "意见": open_comments(st, states, live=gcls not in ("完成", "取消"))})
    loose = [t["编号"] for t in tasks if not t["目标"]]
    loose_group = None
    if loose:
        loose_group = {"编号": "—", "标题": "零散任务", "参与者": participants(fixed, [], [e for o in loose for e in eff[o]]),
                       "事件": event_rows(states, loose, eff, by_task)}
    current = []
    for t in tasks:
        if t["类别"] == "完成" or not t["持有期"]:
            continue
        rows = [r for r in eff[t["编号"]] if r.get("边") not in KEEP_HOLDER]
        last = rows[-1] if rows else None
        current.append({"对象": t["编号"], "发起": (last or {}).get("发起"), "接收": t["持有人"], "状态": t["状态"],
                        "类别": t["类别"], "项目序": (last or {}).get("项目序")})
    all_seq = [e.get("项目序", 0) for rs in evs.values() for e in rs]
    return {
        "规约": VIEW, "截至": max(all_seq or [0]),
        "称谓": render_rule.get("称谓", {}),
        "目标": goals, "零散": loose_group, "任务": tasks, "当前": current,
        "议题": [issue_view(proj, states[o]) for o in sorted(states, key=id_key) if states[o]["种类"] == "议题"],
        "待你决定": decisions(proj, states, eff),
        "检查": [p for p in check(proj, now=None) if p["level"] == "error"],
    }


def approval_note(r: Dict[str, Any]) -> str:
    """看板批准时写的批注：依据是「总裁在看板批准第 N 版框架：批注」，没有批注返回空。"""
    m = re.fullmatch(r"总裁在看板批准第 \d+ 版框架：(.+)", str(r.get("依据") or "").strip(), re.S)
    return m.group(1).strip() if m else ""


def open_comments(goal: Dict[str, Any], states: Dict[str, Dict[str, Any]], live: bool = True) -> List[Dict[str, Any]]:
    """总裁的意见里，最近一次改框架之后提的（改框架就算处理过了）；再加上带批注的批准：
    批注在总管于目标上记一条进展（发起为总管、不是派活脚本代写）之前一直算没处理。"""
    changed = max([r.get("项目序", 0) for r in goal["事件"] if r.get("边") == "变更" and r.get("框架版本")] or [0])
    out = []
    for o in [goal] + goal_tasks(states, goal["编号"]):
        out += [{"对象": o["编号"], "说明": r.get("说明", ""), "时间": r.get("时间"), "项目序": r.get("项目序")}
                for r in o["意见"] if r.get("项目序", 0) > changed]
    if live:
        for r in goal["事件"]:
            note = approval_note(r) if r.get("边") == "批准" else ""
            if not note:
                continue
            done = any(q.get("边") == "进展" and q.get("发起") == LEAD and q.get("写入者") != "派活脚本"
                       and q.get("项目序", 0) > r.get("项目序", 0) for q in goal["事件"])
            if not done:
                out.append({"对象": goal["编号"], "说明": note, "时间": r.get("时间"), "项目序": r.get("项目序"), "类": "批准批注"})
    return sorted(out, key=lambda x: x["项目序"])


def speech_types(rows: List[Dict[str, Any]]) -> List[str]:
    """发言类型由投影推出（不存）：PASS；私下；总裁自选的类型，否则点了名是「提问」、没点名是「发言」；总管是「说明」；
    成员第一次开口是「立场」，被点名后再开口是「回答」（立场、私下、PASS 不算回答过点名），其余是「补充」。"""
    out, spoken, asked = [], set(), {}
    for r in rows:
        who = r.get("发起")
        if r.get("边") == "PASS":
            kind = "PASS"
        elif r.get("私下"):
            kind = "私下"
        elif who == BOSS:
            kind = r.get("类型") or ("提问" if r.get("点名") else "发言")
        elif who == LEAD:
            kind = "说明"
        elif who not in spoken:
            kind = "立场"
        else:
            kind = "回答" if asked.get(who) else "补充"
        if who not in MANAGERS:
            spoken.add(who)
            if kind in ("回答", "补充"):  # 立场（第 1 轮看不到别人）、私下、PASS 都不算回答了之前的点名
                asked[who] = False
        for w in r.get("点名", []):
            asked[w] = True
        out.append(kind)
    return out


def issue_view(proj: Project, st: Dict[str, Any]) -> Dict[str, Any]:
    """一个议题的视图：卡头、与会、总结和裁决（面板用），消息（对话页用），起止项目序（时序图里的议题框用）。"""
    sk = proj.skeleton("议题")
    rows = st["事件"]
    msgs = [r for r in rows if r.get("边") in MESSAGES]
    kinds = speech_types(msgs)
    last = {e: next((r for r in reversed(rows) if r.get("边") == e), None) for e in ("总结", "裁决")}
    seqs = [r["项目序"] for r in rows if "项目序" in r]
    return {
        "编号": st["编号"], "标题": st["标题"], "类型": st["类型"], "状态": st["状态"],
        "类别": sk["状态"].get(st["状态"], {}).get("类别", ""), "持有人": st["持有人"], "目标": st["目标"],
        "与会": st["与会"],
        "总结": {k: last["总结"].get(k, "") for k in ("说明", "方案", "建议")} if last["总结"] else None,
        "裁决": {k: last["裁决"].get(k, "") for k in ("说明", "依据")} if last["裁决"] else None,
        "发言数": sum(1 for r in msgs if r["边"] == "发言"),
        "起序": min(seqs or [0]), "止序": max(seqs or [0]),
        "消息": [{**{k: r[k] for k in ("项目序", "seq", "边", "发起", "时间", "正文", "点名", "私下", "派活", "会话") if k in r},
                 "类型": kind} for r, kind in zip(msgs, kinds)],
        "过程": [{k: r[k] for k in ("项目序", "seq", "边", "发起", "接收", "前状态", "后状态", "时间", "说明", "越过") if k in r}
               for r in rows if r.get("边") not in MESSAGES],
    }


def participants(fixed: List[str], stages: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_in_rows = []
    for r in sorted(rows, key=lambda r: r.get("项目序", 0)):
        for w in (r.get("发起"), r.get("接收")):
            if w and w != "无" and w not in seen_in_rows:
                seen_in_rows.append(w)
    order = list(fixed)
    for s in stages:
        for w in s["人选"] + s.get("确认人", []):
            if w not in order:
                order.append(w)
    planned = set(order)
    for w in seen_in_rows:
        if w not in order:
            order.append(w)
    return [{"名": w, "计划内": w in planned, "出场": w in seen_in_rows} for w in order]


def event_rows(states, objs, eff, by_task, unplanned=()) -> List[Dict[str, Any]]:
    out = []
    for o in objs:
        t = by_task.get(o)
        trunk = {m["项目序"]: m["槽位"] for m in (t["主干"] if t else [])}
        goal = states[o]["编号"] if states[o]["种类"] == "目标" else states[o]["目标"]
        for r in eff.get(o, []):
            row = {k: r[k] for k in ("项目序", "对象", "边", "结果", "发起", "接收", "前状态", "后状态", "时间",
                                     "说明", "依据", "证据", "派活", "会话", "越过", "写入者") if k in r}
            if not str(row.get("依据") or "").strip():
                row.pop("依据", None)
            elif is_quote(row["依据"], goal):
                row["原话"] = True
            row["阶段"] = states[o]["阶段"]
            row["层"] = "目标" if states[o]["种类"] == "目标" else "任务"
            row["主干"] = r["项目序"] in trunk if t else False
            if o in unplanned:
                row["批准后新增"] = True
            if t and r["项目序"] in trunk:
                row["槽位"] = trunk[r["项目序"]]
            # 总裁的话落在总管名下的事件（总管代记的建立、变更），画成总裁 → 总管
            if row.get("原话") and ((row["边"] == "建立" and o in unplanned and row["层"] == "任务")
                                    or (row["边"] == "变更" and row["层"] == "目标")):
                row["画"] = {"发起": BOSS, "接收": LEAD, "标签": "要求" if row["边"] == "建立" else "要求变更"}
            out.append(row)
    out.sort(key=lambda r: r["项目序"])
    # 因果：总裁的退回和由它带来的新增任务，依据相同就互相标注
    for r in out:
        if r["边"] == "建立" and r.get("画") and r["层"] == "任务":
            src = next((q for q in reversed(out) if q["项目序"] < r["项目序"] and is_boss_return(q)
                        and q["依据"].strip() == r["依据"].strip()), None)
            if src:
                r["来自"] = {"对象": src["对象"], "项目序": src["项目序"], "边": src["边"]}
                src.setdefault("催生", []).append({"对象": r["对象"], "项目序": r["项目序"]})
    return out


def decisions(proj: Project, states, eff) -> List[Dict[str, Any]]:
    """待你决定：所有持有人为总裁的未结束对象。每条取让总裁成为持有人的那条事件。"""
    out = []
    for obj in sorted(states, key=id_key):
        st = states[obj]
        if st["持有人"] != BOSS or terminal(proj, st):
            continue
        # 议题只在待裁决时进收件箱（讨论中是总裁在主持）；框架会审并进所属目标的「批准框架」
        if st["种类"] == "议题" and (st["状态"] != "待裁决" or st["类型"] == "会审"):
            continue
        reviews = open_reviews(states, obj) if st["种类"] == "目标" and st["状态"] == "待批准" else []
        if any(s["状态"] != "待裁决" for s in reviews):
            continue  # 会审中，还不该批
        ev = next((r for r in reversed(eff[obj]) if r.get("接收") == BOSS and r.get("边") not in SPECIAL + MESSAGES), {})
        kind = {"待批准": "批准框架", "待确认": "目标验收", "受阻": "受阻", "待裁决": "裁决"}.get(st["状态"], st["状态"])
        item = {"编号": obj, "类型": kind, "说明": ev.get("说明", ""), "方案": ev.get("方案", ""),
                "建议": ev.get("建议", ""), "提出者": ev.get("发起", ""), "项目序": ev.get("项目序")}
        if st["种类"] == "目标" and st["状态"] == "待批准":
            ts = goal_tasks(states, obj)
            item.update({"框架版本": st["框架版本"], "任务数": len(ts), "本轮改动": st["本轮改动"],
                         "人选": sorted({t["拟执行"] for t in ts if t["拟执行"]}),
                         "介入": [t["编号"] for t in ts if BOSS in (t["拟执行"], t["拟确认"])]})
        if reviews:
            item["类型"] = f"批准框架（附会审 {'、'.join(s['编号'] for s in reviews)}）"
            item["会审"] = [s["编号"] for s in reviews]
        out.append(item)
    return out


# ---------- 检查 ----------

SEATS = ("持有人", "管理", LEAD, BOSS, "执行人", "确认人", "自己", "无")


def check_skeletons(proj: Project) -> List[Dict[str, Any]]:
    """加载骨架时的检查：状态可达、能走到终止、终止态除「重开」外无出边、席位合法；阶段模板和渲染规约引用正确。"""
    out = []
    for name in ("任务", "目标", "议题"):
        try:
            sk = proj.skeleton(name)
        except (FlowError, ValueError) as e:
            out.append(issue("error", f"core/skeletons/{skel_file(name)}.json", None, str(e)))
            continue
        out += check_skeleton(sk, f"core/skeletons/{skel_file(name)}.json")
    try:
        gsk = proj.skeleton("目标")
        for gtype in gsk.get("类型", []):
            f = f"core/skeletons/{skel_file('目标-' + gtype)}.json"
            try:
                stages = [dict(x) for x in template_stages(proj, gtype)]
                check_stage_list(stages)
            except (FlowError, ValueError) as e:
                out.append(issue("error", f, None, getattr(e, "msg", str(e))))
    except (FlowError, ValueError):
        pass
    try:
        rr, tsk = proj.skeleton("渲染"), proj.skeleton("任务")
        for w in rr.get("固定参与者", []):
            if w not in MANAGERS:
                out.append(issue("error", "core/skeletons/render.json", None, f"固定参与者「{w}」不是总裁或总管"))
        for e in rr.get("主干", []):
            if e not in tsk["边"]:
                out.append(issue("error", "core/skeletons/render.json", None, f"主干里的「{e}」不是任务骨架的边"))
    except (FlowError, ValueError):
        pass
    return out


def check_skeleton(sk: Dict[str, Any], f: str) -> List[Dict[str, Any]]:
    out = []
    states, ends = set(sk["状态"]), set(sk["终止"])

    def targets(spec):
        return [r["到"] for r in spec.get("结果", {}).values()] or [spec.get("到")]

    # 从初始往前走，能到哪些状态（@ 开头的「回到原状态」不算新状态）
    reach, changed = {sk["初始"]}, True
    while changed:
        changed = False
        for spec in sk["边"].values():
            if any(x in reach for x in spec["从"]) or "无" in spec["从"]:
                for t in targets(spec):
                    if t and not t.startswith("@") and t not in reach:
                        reach.add(t)
                        changed = True
    for x in sorted(states - reach):
        out.append(issue("error", f, None, f"状态「{x}」从初始到不了"))
    # 从终止往回走，哪些状态能走到终止
    back, changed = set(ends), True
    while changed:
        changed = False
        for spec in sk["边"].values():
            if any(t in back for t in targets(spec) if t):
                for x in spec["从"]:
                    if x != "无" and x not in back:
                        back.add(x)
                        changed = True
    for x in sorted(states - back):
        out.append(issue("error", f, None, f"状态「{x}」走不到终止"))
    for x in sorted(states - ends):
        if not any(x in spec["从"] for spec in sk["边"].values()):
            out.append(issue("error", f, None, f"非终止状态「{x}」没有出边"))
    for e, spec in sk["边"].items():
        for x in spec["从"]:
            if x != "无" and x not in states:
                out.append(issue("error", f, None, f"边「{e}」的起点「{x}」不是状态"))
            if x in ends and e != "重开":
                out.append(issue("error", f, None, f"终止状态「{x}」只能走「重开」，不能走「{e}」"))
        for t in targets(spec):
            if t and not t.startswith("@") and t not in states:
                out.append(issue("error", f, None, f"边「{e}」的终点「{t}」不是状态"))
        seats = [spec.get("发起"), spec.get("接收")] + [r.get("接收") for r in spec.get("结果", {}).values()]
        for seat in seats:
            if seat and not seat.startswith("@") and seat not in SEATS:
                out.append(issue("error", f, None, f"边「{e}」的席位「{seat}」不认识（可用：{'、'.join(SEATS)}）"))
    for e, spec in sk.get("消息事件", {}).items():
        if e in sk["边"] or e in SPECIAL:
            out.append(issue("error", f, None, f"消息事件「{e}」和边或特殊事件重名"))
        for x in spec.get("可在", []):
            if x not in states:
                out.append(issue("error", f, None, f"消息事件「{e}」的「可在」里「{x}」不是状态"))
    return out


def check(proj: Project, now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
    """完整性和一致性检查。now 为 None 时不做跟时间有关的提醒（视图模型用，保证固定）。"""
    out = check_skeletons(proj)
    states, evs, probs = replay_all(proj)
    out += probs
    seen_global: Dict[int, str] = {}
    for obj in sorted(evs, key=id_key):
        f = f"collab/内部/流转/{obj}.jsonl"
        rows = evs[obj]
        st = states[obj]
        for n, r in enumerate(rows, 1):
            if r.get("seq") != n:
                out.append(issue("error", f, n, f"seq 应为 {n}，写的是 {r.get('seq')}"))
            g = r.get("项目序")
            if g in seen_global:
                out.append(issue("error", f, n, f"项目序 {g} 和 {seen_global[g]} 重复"))
            elif g is not None:
                seen_global[g] = obj
            if r.get("越过"):
                out.append(issue("warn", f, n, f"偏离：「{r.get('边')}」{r['越过']}"))
        if rows and rows[0].get("边") != "建立":
            out.append(issue("error", f, 1, "第 1 条事件不是「建立」"))
        for p in st["问题"]:
            out.append(issue("error", f, None, p))
        try:
            sk = obj_skeleton(proj, st)
        except FlowError as e:
            out.append(issue("error", f, None, e.msg + "：旧版本骨架要留在 core/skeletons/history/ 或 collab/内部/流程/历史/"))
            continue
        ended = False
        for r in st["事件"]:
            if ended and r.get("边") not in SPECIAL + ("重开",):
                out.append(issue("error", f, None, f"终止后还有事件 seq {r.get('seq')}「{r.get('边')}」"))
            if r.get("边") == "重开":
                ended = False
            elif r.get("后状态") in sk["终止"]:
                ended = True
        if st["状态"] not in sk["终止"] and st["状态"] != "无" and not st["持有人"]:
            out.append(issue("error", f, None, f"{obj} 未结束却没有持有人"))
        # 证据在交付时已验证过存在；任务结束后文件被归档或移动不算错误，只查没结束的
        for r in ([] if st["状态"] in sk["终止"] else st["事件"]):
            for p in r.get("证据", []) or []:
                path = Path(p).expanduser()
                if path.is_absolute():
                    if proj.root not in path.resolve().parents:
                        out.append(issue("warn", f, None, f"项目外的证据可能会变：{p}；需要留证就复制到 collab/产出/{obj}/"))
                    if not path.exists():
                        out.append(issue("error", f, None, f"证据不存在：{p}"))
                elif not (proj.root / p).exists():
                    out.append(issue("error", f, None, f"证据不存在：{p}"))
        if st["种类"] == "任务" and st["目标"]:
            g = states.get(st["目标"])
            if not g:
                out.append(issue("error", f, None, f"所属目标 {st['目标']} 没有建立"))
            elif g["状态"] in ("起草", "待批准") and st["状态"] not in ("规划中", "已批准", "取消"):
                out.append(issue("error", f, None, f"目标 {g['编号']} 还没批准，任务已经派出"))
        if st["种类"] == "目标" and st["状态"] in ("进行中", "待确认", "完成"):
            table = stage_table(proj, st, states)
            for s in table:
                if not s["人选"]:
                    out.append(issue("error", f, None, f"阶段 {s['序']} 没有人选"))
                if not s["任务"] and st["状态"] in ("待确认", "完成"):
                    out.append(issue("error", f, None, f"阶段 {s['序']}「{s['名称']}」没有任务卡"))
                if s["失效"]:
                    out.append(issue("warn", f, None, f"阶段 {s['序']} 的通过已失效：前置阶段回退，要重开它的任务"))
                if s["状态"] == "可开始" and not s["任务"]:
                    out.append(issue("warn", f, None, f"阶段 {s['序']}「{s['名称']}」可以开始了，还没有任务"))
            if st["类型"]:
                try:
                    tmpl = template_stages(proj, st["类型"])
                    inst = [s for s in st["阶段实例"] if s.get("类型") != "验收"]
                    if stage_shape(inst) != stage_shape(tmpl) and not st["差异理由"]:
                        out.append(issue("error", f, None, f"未登记偏差：阶段和「目标-{st['类型']}」模板不同，提交时没写差异理由，也没有改阶段的「变更」"))
                except FlowError:
                    pass
        if st["种类"] == "议题" and st["目标"] and not (states.get(st["目标"]) or {}).get("事件"):
            out.append(issue("error", f, None, f"所挂目标 {st['目标']} 没有建立"))
        if st["种类"] == "任务":
            msg = trunk_problem(st, sk)
            if msg:
                out.append(issue("error", f, None, msg))
        if st["返工次"] == 2:
            out.append(issue("warn", f, None, f"{st['返工人']} 已连续返工 2 次，建议升档改派"))
    for obj, st in sorted(states.items(), key=lambda kv: id_key(kv[0])):  # 目标卡归档了，它的目录要一起走
        if st["种类"] == "目标" and (proj.collab / "目标" / obj).is_dir():
            card = card_path(proj, obj)
            if card and card.parent == proj.collab / "归档" / "目标":
                out.append(issue("error", f"collab/目标/{obj}", None,
                                 f"目标卡已归档，目录还留在 目标/：运行 flow.py 归档 {obj} 一起移到 归档/目标/{obj}/"))
    out += check_blocks(proj)
    out += check_progress(proj, states)
    if now is not None:
        out += check_time(proj, states, now)
    return out


def trunk_problem(st: Dict[str, Any], sk: Dict[str, Any]) -> str:
    """任务要能归约成同一条主干：主干节点按 建立 → 派发 → 接手 → 交付 → 确认 的顺序出现、不跳格；已通过的五格齐全。"""
    passed = st["状态"] == "通过" and st["通过有效"]
    marks = trunk_marks(st["事件"], passed)
    slots = [marks[q] for q in sorted(marks)]
    if slots != list(range(len(slots))):
        return f"{st['编号']} 归约不成主干：主干节点顺序是 {slots}"
    if passed and len(slots) != 5:
        return f"{st['编号']} 已通过，但主干只有 {len(slots)} 格"
    return ""


def check_blocks(proj: Project) -> List[Dict[str, Any]]:
    out = []
    files = proj.card_files() + [proj.collab / "PROGRESS.md"]
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for m in BLOCK_RE.finditer(text):
            if sha(m.group(5)) != m.group(4):
                line = text[: m.start()].count("\n") + 1
                out.append(issue("error", proj.rel(f), line, f"生成块「{m.group(1)} {m.group(2)}」被改动过；用 `flow.py 渲染` 重写，内容改动请走 `flow.py 记`"))
    return out


def check_progress(proj: Project, states) -> List[Dict[str, Any]]:
    out = []
    p = proj.collab / "PROGRESS.md"
    if not p.exists():
        return out
    text = p.read_text(encoding="utf-8")
    limit = proj.skeleton("加载")["目标大小"]["PROGRESS"]
    size = len(text.encode("utf-8"))
    if size > limit:
        out.append(issue("warn", "collab/PROGRESS.md", None, f"PROGRESS 有 {size} 字节，超过目标 {limit}"))
    narrative = "\n".join(section(text, "▶ 下一步"))  # 现状可以讲刚结束的事，只查下一步
    for obj in sorted(set(re.findall(ID_RE, narrative)), key=id_key):
        st = states.get(obj)
        if st and terminal(proj, st):
            out.append(issue("warn", "collab/PROGRESS.md", None, f"「下一步」还在说 {obj}，它已经{st['状态']}了"))
    # 叙述改过之后，又有目标换了状态或任务结束，「下一步」「现状」多半要更新
    f = proj.flow_dir / ".叙述.json"
    if f.exists():
        mark = json.loads(f.read_text(encoding="utf-8"))
        if mark.get("sha") == narrative_sha(text):
            moved = sorted({st["编号"] for st in states.values() for r in st["事件"]
                            if r.get("项目序", 0) > mark.get("项目序", 0) and r.get("边") not in SPECIAL
                            and (st["种类"] == "目标" or r.get("后状态") in ("通过", "取消"))}, key=id_key)
            if moved:
                out.append(issue("warn", "collab/PROGRESS.md", None,
                                 f"「下一步」「现状」在 {'、'.join(moved)} 有进展后没更新"))
    return out


def section(text: str, title: str) -> List[str]:
    out, on = [], False
    for l in text.splitlines():
        if l.startswith("## "):
            on = l[3:].strip().startswith(title)
            continue
        if on:
            out.append(l)
    return out


def check_time(proj: Project, states, now: dt.datetime) -> List[Dict[str, Any]]:
    out = []
    active = [s for s in states.values() if s["种类"] == "目标" and s["状态"] == "进行中"]
    if len(active) > 3:
        out.append(issue("warn", "collab/内部/流转", None, f"同时进行中的目标有 {len(active)} 个，超过 3 个"))
    for st in states.values():
        if st["种类"] != "任务" or not st["事件"]:
            continue
        last = st["事件"][-1]
        try:
            age = (now - dt.datetime.fromisoformat(last["时间"])).total_seconds() / 3600
        except (KeyError, ValueError):
            continue
        f = f"collab/内部/流转/{st['编号']}.jsonl"
        if st["状态"] == "已交接" and age > 24:
            out.append(issue("warn", f, None, f"{st['编号']} 派发后 {int(age)} 小时没人接手"))
        if st["状态"] == "执行中" and age > 48:
            out.append(issue("warn", f, None, f"{st['编号']} 执行中，{int(age)} 小时没有新事件"))
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
    p = proj.collab / "PROGRESS.md"
    if p.exists() and apply_blocks(p, progress_bodies(proj, v)):
        changed.append(proj.rel(p))
    if p.exists():
        note_narrative(proj, p.read_text(encoding="utf-8"), v["截至"])
    return changed


def narrative_sha(text: str) -> str:
    return sha("\n".join(section(text, "▶ 下一步") + ["---"] + section(text, "现状")))


def note_narrative(proj: Project, text: str, upto: int) -> None:
    """记下「▶ 下一步」「现状」最近一次改动时项目走到了哪条事件（collab/内部/流转/.叙述.json），供「叙述过时」提醒用。"""
    f = proj.flow_dir / ".叙述.json"
    cur = narrative_sha(text)
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if old.get("sha") != cur:
        write_if_changed(f, json.dumps({"sha": cur, "项目序": upto}, ensure_ascii=False) + "\n")


def apply_blocks(path: Path, bodies: Dict[Tuple[str, str], str]) -> bool:
    text = path.read_text(encoding="utf-8")

    def sub(m):
        key = (m.group(1), m.group(2))
        if key not in bodies:
            return m.group(0)
        return block(m.group(1), m.group(2), bodies[key])
    return write_if_changed(path, BLOCK_RE.sub(sub, text))


def card_bodies(proj: Project, v: Dict[str, Any], states) -> Dict[Tuple[str, str], str]:
    out = {}
    for t in v["任务"]:
        st = states[t["编号"]]
        out[("卡头", t["编号"])] = (f"状态：{t['状态']} ｜ 目标：{t['目标'] or '—'} ｜ 阶段：{t['阶段'] or '—'} ｜ "
                                   f"执行：{t['执行'] or t['拟执行'] or '—'} ｜ 确认：{t['确认'] or t['拟确认'] or '—'} ｜ 持有人：{t['持有人'] or '—'}\n")
        rows = ["| 序 | 时间 | 边 | 发起 → 接收 | 状态 | 说明 |", "|---|---|---|---|---|---|"]
        voided = set(st["作废"])
        for r in proj_rows(proj, t["编号"]):
            mark = "（已作废）" if r.get("seq") in voided else ""
            edge = r["边"] + (f"：{r['结果']}" if r.get("结果") else "")
            desc = r.get("说明", "") or (f"依据：{r['依据']}" if r.get("依据") else "")
            if r.get("证据"):
                desc += "；证据：" + "、".join(r["证据"])
            if r.get("越过"):
                desc += "；" + r["越过"]
            if r.get("更正"):
                desc = f"作废 seq {r['更正']}：" + desc
            state = f"{r.get('前状态')} → {r.get('后状态')}" if r.get("前状态") != r.get("后状态") else r.get("后状态", "")
            rows.append(f"| {r['seq']} | {short_time(r.get('时间', ''))} | {edge}{mark} | {r.get('发起')} → {r.get('接收')} | {state} | {cell(desc)} |")
        out[("流转", t["编号"])] = "\n".join(rows) + "\n"
    for g in v["目标"]:
        out[("卡头", g["编号"])] = f"状态：{g['状态']} ｜ " + (f"阶段：{g['起草阶段']} ｜ " if g["起草阶段"] else "") + f"类型：{g['类型'] or '—'} ｜ 持有人：{g['持有人'] or '—'}\n"
        rows = ["| 阶段 | 名称 | 类型 | 人选 | 前置 | 可并行 | 状态 | 子任务 |", "|---|---|---|---|---|---|---|---|"]
        for s in g["阶段"]:
            st = s["状态"] + ("（失效）" if s["失效"] else "")
            rows.append(f"| {s['序']} | {cell(s['名称'])} | {s['类型']} | {'、'.join(s['人选']) or '—'} | "
                        f"{'、'.join(map(str, s['前置'])) or '—'} | {'是' if s['可并行'] else '否'} | {st} | {'、'.join(s['任务']) or '—'} |")
        out[("流程", g["编号"])] = "\n".join(rows) + "\n" if g["阶段"] else "（提交框架后生成）\n"
        lines = []
        for r in proj_rows(proj, g["编号"]):
            if r["边"] == "进展":
                continue
            extra = f"（{'、'.join(r['变更项'])}）" if r.get("变更项") else ""
            basis = f"；依据：{r['依据']}" if r.get("依据") else ""
            edge = r["边"] + (f"：{r['结果']}" if r["边"] == "起草阶段" and r.get("结果") else "")
            lines.append(f"- {short_time(r.get('时间', ''))}｜{edge}｜{r.get('发起')} → {r.get('接收')}｜{cell(r.get('说明', ''))}{extra}{basis}")
        out[("变更", g["编号"])] = "\n".join(lines) + "\n" if lines else ""
        by_issue = {i["编号"]: i for i in v["议题"]}
        lines = [f"- {i}「{cell(by_issue[i]['标题'])}」（{by_issue[i]['类型']}）｜{by_issue[i]['状态']}"
                 + (f"｜{cell((by_issue[i]['总结'] or {}).get('说明', ''), 60)}" if by_issue[i]["总结"] else "") for i in g["议题"]]
        out[("议题", g["编号"])] = "\n".join(lines) + "\n" if lines else "（无）\n"
    for i in v["议题"]:
        out[("卡头", i["编号"])] = (f"状态：{i['状态']} ｜ 类型：{i['类型']} ｜ 目标：{i['目标'] or '—'} ｜ "
                                   f"持有人：{i['持有人'] or '—'} ｜ 发言：{i['发言数']}\n")
        rows = ["| 成员 | 视角 |", "|---|---|"] + [f"| {a['成员']} | {cell(a['视角']) or '—'} |" for a in i["与会"]]
        out[("与会", i["编号"])] = "\n".join(rows) + "\n"
        rows = ["| 序 | 时间 | 谁 | 类型 | 点名 | 首行 |", "|---|---|---|---|---|---|"]
        for m in i["消息"]:
            head = "（只给总裁和总管）" if m.get("私下") else first_line(m.get("正文", ""))
            rows.append(f"| {m['seq']} | {short_time(m.get('时间', ''))} | {m['发起']} | {m['类型']} | "
                        f"{'、'.join(m.get('点名', [])) or '—'} | {cell(head, 60) or '—'} |")
        out[("发言", i["编号"])] = "\n".join(rows) + "\n" if i["消息"] else "（还没有发言）\n"
        r = i["裁决"]
        out[("裁决", i["编号"])] = (f"- 决定：{cell(r['说明'])}\n- 依据：{cell(r['依据'])}\n" if r
                                   else "（未裁决）\n")
    return out


def first_line(text: str) -> str:
    return next((l.strip().lstrip("#").strip() for l in text.splitlines() if l.strip()), "")


def proj_rows(proj: Project, obj: str) -> List[Dict[str, Any]]:
    path = proj.flow_dir / f"{obj}.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def decision_lines(v: Dict[str, Any]) -> List[str]:
    """待你决定的每一条，格式同协议：编号｜类型：要决定什么｜可选方案与代价｜总管建议｜验收意见｜提出者。"""
    return [f"- {d['编号']}｜{d['类型']}：{cell(d['说明'], 120)}｜{cell(d['方案'], 120) or '—'}｜"
            f"总管建议：{cell(d['建议'], 60) or '—'}｜—｜{d['提出者']}" for d in v["待你决定"]] + [
        f"- {c['对象']}｜总裁意见（总管处理）：{cell(c['说明'], 120)}｜—｜总管建议：—｜—｜总裁" for g in v["目标"] for c in g["意见"]]


def progress_bodies(proj: Project, v: Dict[str, Any]) -> Dict[Tuple[str, str], str]:
    out = {}
    items = decision_lines(v)
    out[("待你决定", "项目")] = "\n".join(items) + "\n" if items else "（没有需要你拍板的事）\n"
    rows = ["| 编号 | 目标 | 类型 | 状态 | 进度 |", "|---|---|---|---|---|"]
    drafts: Dict[str, List[str]] = {"想法": [], "讨论": [], "方案": [], "搭框架": []}
    for g in v["目标"]:
        if g["类别"] == "完成":
            continue
        if g["状态"] == "起草":  # 起草中的不逐行进表，只汇总一行
            drafts[g["起草阶段"] or "搭框架"].append(g["编号"])
            continue
        done = sum(1 for s in g["阶段"] if s["状态"] == "通过")
        rows.append(f"| {g['编号']} | {cell(g['标题'])} | {g['类型'] or '—'} | {g['状态']} | {done}/{len(g['阶段'])} |")
    out[("目标", "项目")] = "\n".join(rows) + "\n"
    if any(drafts.values()):
        line = f"起草中：想法 {len(drafts['想法'])} 个｜讨论中 {'、'.join(drafts['讨论']) or '无'}｜方案中 {'、'.join(drafts['方案']) or '无'}"
        if drafts["搭框架"]:
            line += f"｜搭框架中 {'、'.join(drafts['搭框架'])}"
        out[("目标", "项目")] += "\n" + line + "\n"
    rows = ["| 编号 | 事项 | 目标 | 执行 | 确认 | 状态 | 持有人 | 结论 |", "|---|---|---|---|---|---|---|---|"]
    passed, cancelled = [], []
    for t in v["任务"]:
        if t["状态"] == "通过":
            passed.append(t["编号"])
            continue
        if t["状态"] == "取消":
            cancelled.append(t["编号"])
            continue
        rows.append(f"| {t['编号']} | {cell(t['标题'])} | {t['目标'] or '—'} | {t['执行'] or t['拟执行'] or '—'} | {t['确认'] or t['拟确认'] or '—'} | "
                    f"{t['状态']} | {t['持有人'] or '—'} | {cell(t['结论'], 30) or '—'} |")
    tail = f"\n已完成：{'、'.join(passed) or '无'}\n" + (f"已取消：{'、'.join(cancelled)}\n" if cancelled else "")
    out[("任务", "项目")] = "\n".join(rows) + "\n" + tail
    out[("生效决议", "项目")] = active_decisions(proj)
    return out


def active_decisions(proj: Project) -> str:
    p = proj.collab / "决议.md"
    if not p.exists():
        return "（无）\n"
    text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8"), flags=re.S)
    lines = [f"- {m.group(1)} {m.group(2).strip()}" for m in re.finditer(r"^##\s*(D\d+)｜[^｜]*｜(.*)$", text, re.M)]
    return "\n".join(lines) + "\n" if lines else "（无）\n"


# ---------- 可走、上下文包 ----------

def legal(proj: Project, obj: str, actor: str, blocked: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """actor 现在能走的边，附可复制的命令。每条边先按真实写入的规则试一遍（不写盘）：会被规则错误拒绝的不列，
    放进 blocked（边、结果、原因），总管、总裁要走得带 --越过。缺说明、缺证据这类要填的内容不算拒绝。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st:
        return []
    sk = proj.skeleton(st["种类"])
    out = []
    base = f"python3 {FLOW_PY} --project {proj.root} 记 {obj}"
    for edge, spec in sk["边"].items():
        if edge == "建立" or st["状态"] not in spec["从"] or (edge == "批准" and st["种类"] == "任务"):
            continue
        ini = spec["发起"]
        if (ini == "持有人" and actor != st["持有人"]) or (ini == "管理" and actor not in MANAGERS) \
                or (ini in MANAGERS and actor != ini):
            continue
        for res in list(spec.get("结果", {})) or [None]:
            r = spec["结果"][res] if res else spec
            recv_cls = r.get("接收") or ""
            need_to = recv_cls in ("执行人", "确认人", "管理", "@该状态席位") and not r.get("默认接收")
            plan_who: List[str] = []
            cmd = f"{base} {edge} --作为 {actor}"
            if res:
                cmd += f" --结果 {res}"
            if need_to:
                plan_who = stage_people(proj, states, st) if edge in ("派发", "改派", "重开") else []
                cmd += f" --给 {'|'.join(plan_who) if plan_who else '<接收方>'}"
            for k in spec.get("必填", []):
                cmd += {"证据": " --证据 <路径>", "说明": ' --说明 "<做了什么>"', "依据": ' --依据 "<总裁原话>"',
                        "方案": ' --方案 "<A …；B …>"', "建议": ' --建议 "<A>"'}.get(k, "")
            if edge == "上报":
                cmd += '  （给总裁时加 --给 总裁 --方案 "<A …；B …>" --建议 "<A>"）'
            why = dry_run_rule(proj, states, obj, edge, actor, res, plan_who)
            if why:
                if blocked is not None:
                    blocked.append({"边": edge, "结果": res, "原因": why})
                continue
            out.append({"边": edge, "结果": res, "命令": cmd})
    return out


def dry_run_rule(proj: Project, states, obj: str, edge: str, actor: str, res: Optional[str], who: List[str]) -> str:
    """按真实写入试一遍这条边，返回规则错误的原因；硬错误（多半是缺 --给、--证据 这类要填的）不算。"""
    filler = {"发起": actor, "说明": "…", "依据": "…", "方案": "…", "建议": "…"}
    if res:
        filler["结果"] = res
    for w in who or [None]:
        a = dict(filler, **({"给": w} if w else {}))
        try:
            plan(proj, states, obj, edge, a)
            return ""
        except FlowError as e:
            if e.kind != "规则错误":
                return ""
            why = e.msg
    return why


def ready_stages(proj: Project, obj: str) -> List[Dict[str, Any]]:
    """目标里可以开始的阶段（前置都已通过、还没派出任务）；还没有任务卡的附建任务的命令。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["种类"] != "目标" or st["状态"] != "进行中":
        return []
    base = f"python3 {FLOW_PY} --project {proj.root} 框架 {obj} --文件 <框架.json>"
    return [{"序": s["序"], "名称": s["名称"], "人选": s["人选"], "任务": s["任务"], "命令": "" if s["任务"] else base}
            for s in stage_table(proj, st, states) if s["状态"] == "可开始"]


def stage_people(proj: Project, states, st: Dict[str, Any]) -> List[str]:
    g = states.get(st["目标"]) if st["目标"] else None
    if not g:
        return []
    stage = next((s for s in stage_table(proj, g, states) if s["序"] == st["阶段"]), None)
    return stage["人选"] if stage else []


def protocol_slice(proj: Project, roles: List[str]) -> str:
    p = proj.collab / "协议.md"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^(?=#{2,3} )", text)
    out = []
    for part in parts:
        m = re.search(r"<!-- 角色：(.*?) -->", part.split("\n", 2)[1] if part.count("\n") >= 1 else "")
        if m and set(re.split(r"[、,，\s]+", m.group(1).strip())) & set(roles):
            out.append(re.sub(r"<!-- 角色：.*? -->\n?", "", part).strip())
    return "\n\n".join(out)


def card_section(proj: Project, obj: str, title: str) -> str:
    for f in proj.card_files():
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^(#{1,2})\s*" + re.escape(obj) + r"(?![-\w]).*$", text, re.M)  # G001 不能命中 G001-T1
        if not m:
            continue
        level = len(m.group(1))
        rest = text[m.end():]
        nxt = re.search(r"^#{1,%d}\s" % level, rest, re.M)
        body = rest[: nxt.start()] if nxt else rest
        sm = re.search(r"^#{%d}\s*%s.*$" % (level + 1, re.escape(title)), body, re.M)
        if not sm:
            return ""
        sub = body[sm.end():]
        sn = re.search(r"^#{1,%d}\s" % (level + 1), sub, re.M)
        return (sub[: sn.start()] if sn else sub).strip()
    return ""


WORK = "work"  # 交付和草稿的总目录，和 collab/ 并列


def workdir(proj: Project, goal: Optional[str]) -> str:
    """工作目录（相对项目根）：目标是 work/<目标卡文件名>/（文件名在建立时定，改标题不变），零散任务是 work/loose/。"""
    if not goal:
        return f"{WORK}/loose"
    for d in (proj.collab / "目标", proj.collab / "归档" / "目标"):
        hit = sorted(d.glob(f"{goal}-*.md")) if d.is_dir() else []
        if hit:
            return f"{WORK}/{hit[0].stem}"
    return f"{WORK}/{goal}"


def workspace(proj: Project, st: Dict[str, Any], member: str) -> Dict[str, str]:
    """任务的工作区（都相对项目根）：工作目录、默认交付位置 <工作目录>/<任务>/、成员工位 <工作目录>/.scratch/<成员>/<任务>/。"""
    wd = workdir(proj, st["目标"])
    return {"工作目录": wd, "交付": f"{wd}/{st['编号']}/", "工位": f"{wd}/.scratch/{member}/{st['编号']}/"}


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
    msgs = [r for r in st["事件"] if r.get("边") in MESSAGES]
    kinds = dict(zip([r["项目序"] for r in msgs], speech_types(msgs)))
    upto = max([r["项目序"] for r in st["事件"]] or [0])
    if member in MANAGERS:
        pick = [r for r in msgs if since is None or r["项目序"] > since]
    else:
        mine = [r["项目序"] for r in msgs if r.get("发起") == member]
        if fresh:
            pick = [r for r in msgs if not r.get("私下")]
        elif not mine and since is None:
            calls = [r for r in msgs if r.get("发起") == BOSS and member in r.get("点名", []) and not r.get("私下")]
            if calls:
                upto = calls[-1]["项目序"]
            pick = [r for r in msgs if r["项目序"] <= upto and not r.get("私下")]
            if calls and catch_up:
                batch = {w for r in calls for w in r.get("点名", [])}
                pick += [r for r in msgs if r["项目序"] > upto and r.get("发起") not in batch and not r.get("私下")]
        else:
            start = since if since is not None else max(mine)
            pick = [r for r in msgs if r["项目序"] > start and r.get("发起") != member and not r.get("私下") and r["项目序"] not in seen]
    return [{**r, "类型": kinds[r["项目序"]]} for r in pick], upto


def issue_context(proj: Project, states, st: Dict[str, Any], member: str, since: Optional[int],
                  catch_up: bool = False, fresh: bool = False, seen: Iterable[int] = ()) -> Tuple[str, List[Dict[str, Any]]]:
    """与会者（或收口的总管）的上下文包：议题和身份、问题、所挂目标、新发言、记号说明、协议切片。"""
    obj = st["编号"]
    spec = proj.skeleton("加载")["角色"]["与会"]
    feed, upto = issue_feed(st, member, since, catch_up, fresh, seen)
    me = next((a for a in st["与会"] if a["成员"] == member), None)
    if member not in MANAGERS and not me:
        raise hard(f"{member} 不在 {obj} 的与会名单里")
    others = "、".join(f"{a['成员']}（{a['视角'] or '未指定视角'}）" for a in st["与会"] if a["成员"] != member) or "无"
    blocks: List[Tuple[str, str, str]] = []
    if me:
        intro = (f"朝会 {obj}「{st['标题']}」现在是「{st['状态']}」。你是 {member}，视角：{me['视角'] or '按你的专业判断'}。"
                 f"其他与会者：{others}。长材料写到 collab/议题/{obj}/{member}/，发言里贴链接。")
    else:
        intro = f"朝会 {obj}「{st['标题']}」现在是「{st['状态']}」，与会：{others}。下面是全部发言（含私下），供收口写总结。"
    blocks.append(("议题", "回放", intro))
    blocks.append(("问题", f"议题卡 {obj}「问题」", card_section(proj, obj, "问题")))
    opening = card_section(proj, obj, "开场约定")
    if opening:
        blocks.append(("开场约定", f"议题卡 {obj}「开场约定」", opening))
    g = states.get(st["目标"]) if st["目标"] else None
    if g:
        body = f"{g['编号']} {g['标题']}（{g['状态']}）\n" + card_section(proj, g["编号"], "要什么")
        if st["类型"] == "会审":
            body += "\n\n提交的框架：\n" + card_section(proj, g["编号"], "流程")
        blocks.append(("目标", f"目标卡 {g['编号']}", body))
    if feed:
        lines = []
        for r in feed:
            tag = "；点名问你" if member in r.get("点名", []) and r.get("发起") == BOSS else ""
            tag += "；私下" if r.get("私下") and r["类型"] != "私下" else ""
            text = r.get("正文", "").strip() if r["边"] == "发言" else "[PASS]"
            lines.append(f"### {r['发起']} · {r['类型']}{tag}（{short_time(r.get('时间', ''))}）\n{text}")
        blocks.append(("发言", f"I00x 发言，喂到项目序 {upto}", "\n\n".join(lines)))
    if me:
        blocks.append(("记号", "议题骨架", "直接用 Markdown 写你的发言作为最后的回复，系统会把它记到黑板上，你不用跑命令、不要改任何文件。\n"
                       "- 只有总裁能叫人：你写的 @ 只是普通文字，不会叫醒任何人；想听谁的意见，写给总裁（如「建议问一下 XX」）；\n"
                       "- 只给总裁和总管看的写 <私下 总裁>…</私下>；\n- 没有要补充的只回 [PASS]。\n黑板放结论和要点，详细材料写到工作区再贴链接。"
                       + ("\n这是你第一次发言：先看「新发言」里已有的公开发言和叫你的那句话，再独立给出你的判断；和你同一句话叫来的人，他们的回答你看不到。" if not any(r.get("发起") == member for r in st["事件"] if r.get("边") in MESSAGES) else "")))
        sl = protocol_slice(proj, spec["协议"])
        if sl:
            blocks.append(("协议", f"协议.md（{'、'.join(spec['协议'])}）", sl))
    titles = {"议题": "现状", "问题": "问题", "开场约定": "开场约定（软约定：资料可以看，不是必须看；不限制你的读写）", "目标": "所挂目标", "发言": "新发言", "记号": "怎么发言", "协议": "规则"}
    text = "\n\n".join(f"## {titles.get(n, n)}\n{body.strip()}" for n, _, body in blocks if body.strip())
    manifest = [{"块": n, "来源": src, "字节": len(body.encode("utf-8"))} for n, src, body in blocks if body.strip()]
    manifest.append({"块": "读到", "来源": f"项目序 {upto}", "字节": 0, "读到": upto, "补到": [r["项目序"] for r in feed if r["项目序"] > upto]})
    return text, manifest


def context(proj: Project, obj: str, member: str, full: bool = False, since: Optional[int] = None, catch_up: bool = False,
            fresh: bool = False, seen: Iterable[int] = ()) -> Tuple[str, List[Dict[str, Any]]]:
    """成员的上下文包和清单。角色按任务现状推出：待验收 → 确认；所在阶段类型为验收 → 第三方验收；其余 → 执行。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st:
        raise hard(f"没有 {obj}")
    if st["种类"] == "议题":
        return issue_context(proj, states, st, member, since, catch_up, fresh, seen)
    load = proj.skeleton("加载")
    g = states.get(st["目标"]) if st["目标"] else None
    stage = next((s for s in stage_table(proj, g, states) if s["序"] == st["阶段"]), None) if g else None
    role = "确认" if st["状态"] == "待验收" else ("第三方验收" if stage and stage["类型"] == "验收" else "执行")
    spec = load["角色"][role]
    blocks: List[Tuple[str, str, str]] = []
    for b in spec["块"]:
        if b == "目标" and g:
            plan_md = goal_files(proj, g["编号"]).get("方案")  # 只给方案路径，问题.md 不进成员上下文包
            blocks.append((b, f"目标卡 {g['编号']}「要什么」", f"{g['编号']} {g['标题']}\n" + card_section(proj, g["编号"], "要什么")
                           + (f"\n方案（开工前先读，硬约束写在里面）：`{plan_md}`\n" if plan_md else "")))
        elif b == "交接":
            blocks.append((b, f"任务卡 {obj}「交接」", card_section(proj, obj, "交接")))
        elif b == "变更":
            ch = [f"- {short_time(r['时间'])} {r.get('说明', '')}（{'、'.join(r.get('变更项', []))}）" for r in st["事件"] if r.get("边") == "变更"]
            if ch:
                blocks.append((b, "任务的变更事件", "\n".join(ch)))
        elif b == "状态":
            ws = workspace(proj, st, member)
            put = (f"交付默认放 `{ws['交付']}`，或项目里本来该放的位置（代码进 src/ 等），`--证据` 写相对项目根的路径。"
                   if role == "执行" else f"验收结论等管理性产出放 `collab/产出/{obj}/`。")
            blocks.append((b, "回放", f"{obj}「{st['标题']}」现在是「{st['状态']}」，持有人 {st['持有人'] or '—'}；你是 {member}，这次的角色是「{role}」。"
                           "流转只用下面的命令写，不要改卡里的生成块和 PROGRESS。\n"
                           f"工作目录 `{ws['工作目录']}`（相对项目根）。{put}"
                           f"草稿和中间笔记放你的工位 `{ws['工位']}`，只写自己的；工位不是证据，验收只看交付。"))
        elif b == "上游交付" and stage:
            ups = []
            table = stage_table(proj, g, states)
            need = list(st["前置"]) or [tid for s in table if s["序"] in stage["前置"] for tid in s["任务"]]
            for tid in need:
                t = states[tid]
                dl = [r for r in t["事件"] if r.get("边") == "交付"]
                if dl:
                    ups.append(f"- {tid} {t['标题']}：{'、'.join(dl[-1].get('证据', []))}")
            if ups:
                blocks.append((b, "前置阶段的交付", "\n".join(ups)))
        elif b == "交付":
            dl = [r for r in st["事件"] if r.get("边") == "交付"]
            if dl:
                blocks.append((b, "最近一次交付", f"{dl[-1].get('发起')}：{dl[-1].get('说明', '')}\n证据：{'、'.join(dl[-1].get('证据', []))}"))
        elif b == "决议":
            text = card_section(proj, obj, "交接") + (card_section(proj, g["编号"], "要什么") if g else "")
            ids = sorted(set(re.findall(r"D\d+", text)), key=id_key)
            if ids:
                dec = active_decisions(proj)
                lines = [l for l in dec.splitlines() if any(l.startswith(f"- {i} ") for i in ids)]
                if lines:
                    blocks.append((b, "决议.md", "\n".join(lines)))
        elif b == "协议":
            sl = protocol_slice(proj, spec["协议"])
            if sl:
                blocks.append((b, f"协议.md（{'、'.join(spec['协议'])}）", sl))
        elif b == "可走":
            moves = legal(proj, obj, member)
            if moves:
                blocks.append((b, "flow.py 可走", "\n".join(f"- {m['边']}{'：' + m['结果'] if m['结果'] else ''}：`{m['命令']}`" for m in moves)))
    if full:
        p = proj.collab / "PROGRESS.md"
        if p.exists():
            blocks.append(("PROGRESS", "collab/PROGRESS.md", p.read_text(encoding="utf-8")))
    titles = {"目标": "目标", "交接": "交接", "变更": "卡片改过", "状态": "现状", "上游交付": "上游交付物", "交付": "要确认的交付",
              "决议": "相关决议", "协议": "规则", "可走": "你能走的边", "PROGRESS": "PROGRESS"}
    text = "\n\n".join(f"## {titles.get(n, n)}\n{body.strip()}" for n, _, body in blocks if body.strip())
    manifest = [{"块": n, "来源": src, "字节": len(body.encode("utf-8"))} for n, src, body in blocks if body.strip()]
    return text, manifest


# ---------- 派活脚本用 ----------

def dispatch_begin(proj: Project, obj: str, seat: str, member: str, run: str, override: str = "") -> List[str]:
    """派活前代写：执行席位写派发（或续接时的进展）和接手；确认席位在需要时转交给该成员。返回写了哪些事件。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["种类"] != "任务":
        raise hard(f"{obj} 没有建立：先用 flow.py 建立任务")
    base = {"写入者": "派活脚本", "派活": run, "越过": override or None}
    done: List[str] = []

    def rec(edge, **kw):
        ev, _ = record(proj, obj, edge, {**base, **kw})
        done.append(f"{edge} {ev['发起']} → {ev['接收']}")

    s, holder = st["状态"], st["持有人"]
    if s == "规划中":
        raise hard(f"{obj} 还在规划中：目标 {st['目标']} 批准后才能派活，这一步不能越过")
    if seat in ("验收", "确认"):
        if s != "待验收":
            raise hard(f"{obj} 现在是「{s}」，不在待验收，不能派{seat}")
        if holder != member:
            rec("转交", 发起=holder, 给=member, 说明=f"派活脚本：转给 {member} 确认（{run}）")
        else:
            rec("进展", 发起=member, 说明=f"续接确认（{run}）")
        return done
    if s == "已批准":
        rec("派发", 发起=LEAD, 给=member, 说明=f"派活脚本：派给 {member}（{run}）")
        rec("接手", 发起=member, 说明=f"开工（{run}）")
    elif s in ("已交接", "执行中") and holder != member:
        if not override:
            raise rule(f"{obj} 现在在 {holder} 手里；要换成 {member} 加 --override \"理由\"，会记成改派")
        rec("改派", 发起=LEAD, 给=member, 说明=f"派活脚本改派给 {member}：{override}")
        rec("接手", 发起=member, 说明=f"开工（{run}）")
    elif s == "已交接":
        rec("接手", 发起=member, 说明=f"开工（{run}）")
    elif s == "执行中":
        rec("进展", 发起=member, 说明=f"续接（{run}）")
    else:
        raise hard(f"{obj} 现在是「{s}」，不能派执行：先解除、恢复或重开")
    return done


def dispatch_end(proj: Project, obj: str, member: str, run: str, session: str, final: str, status: str) -> List[str]:
    """派活结束后代写：一条进展（会话、结果）；成员没写结束边（交付、确认、上报、转交）时代写上报给总管。"""
    done = []
    rows = proj_rows(proj, obj)
    mine = [r for r in rows if r.get("派活") == run and r.get("发起") == member and r.get("边") in ("交付", "确认", "上报", "转交")]
    record(proj, obj, "进展", {"发起": member, "写入者": "派活脚本", "派活": run, "会话": session or None,
                               "说明": f"{run} 结束：{status}"})
    done.append("进展")
    if mine:
        return done
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if st and st["持有人"] == member and not terminal(proj, st) and st["状态"] != "受阻":
        record(proj, obj, "上报", {"发起": member, "给": LEAD, "写入者": "派活脚本", "派活": run, "会话": session or None,
                                   "说明": "未声明结果（派活脚本代写）：" + cell(final, 120)})
        done.append("上报 → 总管（成员没写结束边）")
    return done


def dispatch_prompt(proj: Project, obj: str, member: str, prompt: str) -> str:
    text, _ = context(proj, obj, member)
    return (f"{prompt.rstrip()}\n\n---\n以下是 flow.py 给你的 {obj} 上下文包，按它工作，不必再读 PROGRESS 和整份协议。\n\n{text}\n\n"
            f"结束前必须用「你能走的边」里的命令写一条交付、确认或上报（环境变量已设好你的身份和派活编号）；"
            f"不要改卡片里的生成块和 PROGRESS。")


PRIVATE_RE = re.compile(r"<私下(?:\s+[^>]*)?>(.*?)</私下>", re.S)
MENTION_RE = re.compile(r"@([^\s@，。、,.:：；;！!？?()（）\[\]【】<>「」]+)")


def parse_reply(text: str) -> List[Dict[str, Any]]:
    """把成员的最后回复拆成黑板消息：<私下 …>…</私下> 各成一条私下发言；其余是一条公开发言；只有 [PASS] 是 PASS。"""
    private = [m.strip() for m in PRIVATE_RE.findall(text or "") if m.strip()]
    public = PRIVATE_RE.sub("", text or "").strip()
    out: List[Dict[str, Any]] = []
    if public in ("[PASS]", "PASS"):
        out.append({"边": "PASS"})
    elif public:
        out.append({"边": "发言", "正文": public, "点名": MENTION_RE.findall(public)})
    out += [{"边": "发言", "正文": m, "私下": True} for m in private]
    return out


def issue_begin(proj: Project, obj: str, member: str) -> Dict[str, Any]:
    """叫醒与会者前检查：议题在讨论中、member 在与会名单里。返回议题状态。"""
    states, _, _ = replay_all(proj)
    st = states.get(obj)
    if not st or st["种类"] != "议题":
        raise hard(f"{obj} 不是已建立的议题")
    if st["状态"] != "讨论中":
        raise hard(f"{obj} 现在是「{st['状态']}」，讨论中才能叫醒与会者")
    if member not in [a["成员"] for a in st["与会"]]:
        raise hard(f"{member} 不在 {obj} 的与会名单里")
    return st


def issue_needs(st: Dict[str, Any], member: str, since: Optional[int]) -> bool:
    """有没有要 member 开口的：还没开过口，或 since 之后总裁公开点名了它。成员的 @ 和私下的点名都不算。"""
    msgs = [r for r in st["事件"] if r.get("边") in MESSAGES]
    if not any(r.get("发起") == member for r in msgs):
        return True
    start = since if since is not None else max(r["项目序"] for r in msgs if r.get("发起") == member)
    return any(r["项目序"] > start and r.get("发起") == BOSS and member in r.get("点名", []) and not r.get("私下") for r in msgs)


def issue_end(proj: Project, obj: str, member: str, run: str, session: str, final: str, ok: bool,
              upto: int) -> Tuple[List[str], List[str]]:
    """与会者那次派活结束后，由派活钩子把回复写成黑板消息（方案 03 第 10.3 节 F）。
    返回（写了什么，接着要叫醒谁）。只有总裁的 @ 能叫醒人（总裁 11-04）：成员写的 @ 当普通文字，不记点名、不叫醒；
    唯一的接着叫醒是 member 自己——它跑的时候总裁又公开点名了它。"""
    if not ok or not (final or "").strip():
        return ["没有回复，不写发言"], []
    done, wake = [], []
    base = {"发起": member, "写入者": "派活脚本", "派活": run, "会话": session or None}
    for m in parse_reply(final):
        ev, _ = record(proj, obj, m["边"], {**base, "正文": m.get("正文"), "私下": m.get("私下")})
        done.append(f"{m['边']}{'（私下）' if m.get('私下') else ''}")
    st = replay(obj, proj_rows(proj, obj))
    if st["状态"] == "讨论中" and issue_needs(st, member, upto):
        wake.append(member)
    return done, wake


# ---------- 命令行 ----------

def env_args(a) -> Dict[str, Any]:
    out = {}
    for k in ("说明", "依据", "方案", "建议", "差异理由", "标题", "类型", "目标", "正文"):
        v = getattr(a, k, None)
        if v:
            out[k] = v
    if getattr(a, "阶段", None) is not None:
        out["阶段"] = a.阶段
    if getattr(a, "与会", None):
        out["与会"] = a.与会
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="流转工具：唯一写入口、唯一投影")
    ap.add_argument("--project", help="项目目录（默认从当前目录向上找 collab/）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--作为", "--as", dest="作为", default=os.environ.get("COLLAB_ACTOR") or LEAD)
        p.add_argument("--写入者", "--writer", dest="写入者", default=os.environ.get("COLLAB_WRITER"))
        p.add_argument("--派活", "--run", dest="派活", default=os.environ.get("COLLAB_RUN"))
        p.add_argument("--会话", "--session", dest="会话", default=os.environ.get("COLLAB_SESSION"))
        p.add_argument("--说明", "--note", dest="说明")
        p.add_argument("--依据", "--basis", dest="依据")
        p.add_argument("--越过", "--override", dest="越过")

    p = sub.add_parser("建立", aliases=["new"])
    p.add_argument("种类", choices=["任务", "目标", "议题", "task", "goal", "issue"])
    p.add_argument("--标题", "--title", dest="标题", required=True)
    p.add_argument("--目标", "--goal", dest="目标")
    p.add_argument("--阶段", "--stage", dest="阶段", type=int)
    p.add_argument("--类型", "--type", dest="类型")
    p.add_argument("--与会", "--attendees", dest="与会", nargs="*", help="议题的与会者，如 codex:从实现成本看 deepseek")
    common(p)

    p = sub.add_parser("记", aliases=["log"])
    p.add_argument("编号")
    p.add_argument("边")
    p.add_argument("--结果", "--result", dest="结果")
    p.add_argument("--给", "--to", dest="给")
    p.add_argument("--证据", "--evidence", dest="证据", nargs="*", default=[])
    p.add_argument("--方案", "--options", dest="方案")
    p.add_argument("--建议", "--advice", dest="建议")
    p.add_argument("--变更项", "--changes", dest="变更项", nargs="*", default=[])
    p.add_argument("--更正", "--void", dest="更正", type=int)
    p.add_argument("--人选", "--people", dest="人选", nargs="*", help="批准时的阶段人选，如 1=deepseek 2=codex,claude")
    p.add_argument("--差异理由", "--why-differ", dest="差异理由")
    p.add_argument("--正文", "--text", dest="正文", help="议题发言的正文（Markdown）；- 表示从标准输入读")
    p.add_argument("--点名", "--at", dest="点名", nargs="*", default=[], help="发言 @ 了谁")
    p.add_argument("--私下", "--private", dest="私下", action="store_true", help="只给总裁和总管看")
    p.add_argument("--类型", "--type", dest="类型", help="总裁发言时自选的类型")
    p.add_argument("--与会", "--attendees", dest="与会", nargs="*", help="议题「变更」时的新与会名单")
    common(p)

    p = sub.add_parser("框架", aliases=["frame"])
    p.add_argument("编号")
    p.add_argument("--文件", "--file", dest="文件", required=True, help="框架 JSON：阶段和每个阶段的任务；可重复运行，这就是改图的方式")
    common(p)

    p = sub.add_parser("开工", aliases=["start"])
    p.add_argument("编号")
    common(p)

    p = sub.add_parser("可走", aliases=["next"])
    p.add_argument("编号")
    p.add_argument("--作为", "--as", dest="作为", default=os.environ.get("COLLAB_ACTOR") or LEAD)

    p = sub.add_parser("上下文", aliases=["context"])
    p.add_argument("编号")
    p.add_argument("--给", "--for", dest="给", required=True)
    p.add_argument("--全", "--full", dest="全", action="store_true")
    p.add_argument("--清单", "--manifest", dest="清单", action="store_true")
    p.add_argument("--起", "--since", dest="起", type=int, help="议题：只给这个项目序之后的发言（派活脚本传已读位置）")

    p = sub.add_parser("归档", aliases=["archive"])
    p.add_argument("编号")
    common(p)

    sub.add_parser("渲染", aliases=["render"])
    p = sub.add_parser("检查", aliases=["check"])
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("导出", aliases=["export"])
    p.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    root = Path(a.project).expanduser() if a.project else find_project(Path.cwd())
    proj = Project(root)
    cmd = {"new": "建立", "log": "记", "frame": "框架", "start": "开工", "next": "可走", "context": "上下文", "render": "渲染", "check": "检查",
           "export": "导出", "archive": "归档"}.get(a.cmd, a.cmd)
    try:
        if cmd == "框架":
            spec = json.loads(Path(a.文件).expanduser().read_text(encoding="utf-8"))
            res = frame(proj, a.编号, spec, {"说明": a.说明, "依据": a.依据, "写入者": a.写入者})
            print(f"{a.编号} 框架第 {res['版本']} 版" + ("（没有变化）" if not res["改动"] else ""))
            for line in res["改动"]:
                print("  " + line)
            return 0
        if cmd == "归档":
            moved = archive_goal(proj, a.编号)
            print("\n".join(["已移："] + ["  " + m for m in moved]) if moved else "没有要移的")
            return 0
        if cmd == "开工":
            start_self(proj, a.编号, {"说明": a.说明, "写入者": a.写入者})
            print(f"已开工：{a.编号} 由总管执行")
            return 0
        if cmd in ("记", "渲染") and not proj.flow_dir.is_dir():  # 不能顺手建出 内部/流转/，那样旧项目会被当成新结构
            raise hard("这个项目没有 collab/内部/流转/：旧结构项目不走 flow.py；流转还在 collab/流转/ 的先运行 init.sh tidy")
        if cmd in ("建立", "记"):
            actor = proj.actor(a.作为)
            if not actor:
                raise hard(f"发起人「{a.作为}」不是总管、总裁，也不在花名册里")
            args = env_args(a)
            args.update({"发起": actor, "写入者": a.写入者 or (LEAD if actor in MANAGERS else "成员"),
                         "派活": a.派活, "会话": a.会话, "越过": a.越过})
            if cmd == "建立":
                kind = {"task": "任务", "goal": "目标", "issue": "议题"}.get(a.种类, a.种类)
                obj, path = create(proj, kind, args)
                print(f"已建立 {obj}：{proj.rel(path)}")
                return 0
            if a.边 == "建立":
                raise hard("新建用 `flow.py 建立 任务|目标|议题`，它会同时生成卡片")
            args.update({"结果": a.结果, "给": a.给, "证据": a.证据, "方案": a.方案, "建议": a.建议,
                         "变更项": a.变更项, "更正": a.更正, "差异理由": a.差异理由, "点名": a.点名, "私下": a.私下})
            if args.get("正文") == "-":
                args["正文"] = sys.stdin.read()
            if a.人选:
                args["人选"] = parse_people(a.人选)
            if args.get("人选"):
                args["人选"] = {k: [proj.actor(w) or w for w in v] for k, v in args["人选"].items()}
            ev, notes = record(proj, a.编号, a.边, args)
            print(f"已记：{a.编号} seq {ev['seq']}「{ev['边']}{'：' + ev['结果'] if ev.get('结果') else ''}」"
                  f"{ev['发起']} → {ev['接收']}，{ev['前状态']} → {ev['后状态']}")
            for n in notes:
                print("提醒：" + n)
            if ev.get("越过"):
                print("已越过，看板标为偏离：" + ev["越过"])
            return 0
        if cmd == "可走":
            actor = proj.actor(a.作为) or a.作为
            blocked: List[Dict[str, Any]] = []
            moves = legal(proj, a.编号, actor, blocked)
            ready = ready_stages(proj, a.编号)
            if not moves and not ready:
                print(f"{actor} 现在在 {a.编号} 上没有能走的边")
            for m in moves:
                print(f"{m['边']}{'：' + m['结果'] if m['结果'] else ''}\n  {m['命令']}")
            for r in ready:
                head = f"阶段 {r['序']}「{r['名称']}」可以开始（人选 {'、'.join(r['人选']) or '—'}）"
                print(f"{head}，派发已建的 {'、'.join(r['任务'])}" if r["任务"] else f"{head}，建任务：\n  {r['命令']}")
            for b in blocked:
                print(f"不能走：{b['边']}{'：' + b['结果'] if b['结果'] else ''} —— {b['原因']}"
                      + ("（总管、总裁确需这样做，加 --越过 \"理由\"）" if actor in MANAGERS else ""))
            return 0
        if cmd == "上下文":
            member = proj.actor(a.给) or a.给
            text, manifest = context(proj, a.编号, member, a.全, a.起)
            if a.清单:
                limit = proj.skeleton("加载")["目标大小"]["上下文包"]
                total = sum(m["字节"] for m in manifest)
                for m in manifest:
                    print(f"{m['块']:<6} {m['字节']:>6} 字节  {m['来源']}")
                print(f"合计 {total} 字节（目标 {limit}）" + ("，超出" if total > limit else ""))
            else:
                print(text)
            return 0
        if cmd == "渲染":
            with locked(proj):
                changed = render_all(proj)
            print("已重写：" + ("、".join(changed) if changed else "无变化"))
            return 0
        if cmd == "检查":
            items = check(proj, now=project_now(proj))
            if a.json:
                print(json.dumps(items, ensure_ascii=False, indent=1))
            else:
                for x in items:
                    print(f"{'错误' if x['level'] == 'error' else '提醒'}  {x['file']}{':' + str(x['line']) if x['line'] else ''}  {x['msg']}")
                if not items:
                    print("没有问题")
            return 1 if any(x["level"] == "error" for x in items) else 0
        if cmd == "导出":
            print(dumps(view(proj)))
            return 0
    except FlowError as e:
        print(f"{e.kind}：{e.msg}", file=sys.stderr)
        if e.kind == "规则错误":
            print("总管或总裁确需这样做，加 --越过 \"理由\"；看板会标为偏离。", file=sys.stderr)
        if cmd == "记":
            actor = proj.actor(getattr(a, "作为", "")) or LEAD
            moves = legal(proj, a.编号, actor) if (proj.flow_dir / f"{a.编号}.jsonl").exists() else []
            if moves:
                print(f"{actor} 现在能走的：", file=sys.stderr)
                for m in moves:
                    print("  " + m["命令"], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
