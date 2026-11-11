#!/usr/bin/env python3
"""旧格式（账本格式 2 及以前：中文目录、中文键和取值、事件 v1）→ 新格式的对照表和转换函数。

迁移（migrate.py、init.sh migrate）用它改写事件、骨架、框架、运行记录；表是冻结的，不跟着语言包变。
文件和目录的旧名 → 新名在 paths.LEGACY。只用 Python 标准库。
"""
import copy
from typing import Any, Dict, List, Optional

# 取值：{类: {旧中文: 新代码}}
VALUES: Dict[str, Dict[str, str]] = {
 "kind": {
  "目标": "goal",
  "任务": "task",
  "议题": "issue"
 },
 "seat": {
  "总裁": "owner",
  "总管": "lead",
  "执行": "executor",
  "确认": "reviewer",
  "验收": "acceptance",
  "与会": "attendee"
 },
 "seat_class": {
  "持有人": "holder",
  "管理": "manager",
  "总管": "lead",
  "总裁": "owner",
  "执行人": "executor",
  "确认人": "reviewer",
  "自己": "self",
  "无": "none",
  "@该状态席位": "@state_seat",
  "@上报前持有人": "@holder_before_escalation",
  "@暂停前持有人": "@holder_before_pause",
  "@上报前状态": "@state_before_escalation",
  "@暂停前状态": "@state_before_pause",
  "@上次交付人": "@last_deliverer",
  "@不变": "@unchanged"
 },
 "state": {
  "无": "none",
  "规划中": "planned",
  "已批准": "approved",
  "已交接": "dispatched",
  "执行中": "in_progress",
  "待验收": "in_review",
  "受阻": "blocked",
  "暂停": "paused",
  "未通过": "failed",
  "通过": "passed",
  "取消": "cancelled",
  "撤下": "withdrawn",
  "起草": "draft",
  "待批准": "pending_approval",
  "进行中": "active",
  "待确认": "pending_acceptance",
  "完成": "done",
  "讨论中": "discussing",
  "收口中": "closing",
  "待裁决": "pending_ruling",
  "已裁决": "ruled"
 },
 "edge": {
  "建立": "create",
  "批准": "approve",
  "派发": "dispatch",
  "接手": "pick_up",
  "交付": "deliver",
  "确认": "review",
  "转交": "hand_over",
  "上报": "escalate",
  "解除": "unblock",
  "改派": "reassign",
  "暂停": "pause",
  "恢复": "resume",
  "重开": "reopen",
  "取消": "cancel",
  "撤下": "withdraw",
  "重拟": "redraft",
  "提交": "submit",
  "退回": "return",
  "目标验收": "request_acceptance",
  "完成": "complete",
  "打回": "reject",
  "开始": "start",
  "结束讨论": "end_discussion",
  "继续讨论": "continue_discussion",
  "总结": "summarize",
  "裁决": "rule",
  "变更": "change",
  "进展": "progress",
  "更正": "correction",
  "意见": "comment",
  "起草阶段": "draft_stage",
  "发言": "post",
  "PASS": "pass",
  "要求": "request",
  "要求变更": "request_change"
 },
 "result": {
  "通过": "pass",
  "需补充": "needs_more",
  "未通过": "fail"
 },
 "category": {
  "待办": "todo",
  "进行": "doing",
  "评审": "review",
  "完成": "done"
 },
 "draft_stage": {
  "想法": "idea",
  "讨论": "discussion",
  "方案": "proposal",
  "搭框架": "framing"
 },
 "goal_type": {
  "通用": "general",
  "调研": "research",
  "开发": "dev"
 },
 "issue_type": {
  "朝会": "council",
  "会审": "review_meeting"
 },
 "stage_type": {
  "执行": "work",
  "调研": "research",
  "验收": "acceptance"
 },
 "stage_status": {
  "通过": "passed",
  "进行中": "active",
  "可开始": "ready",
  "未开始": "not_started"
 },
 "speech": {
  "立场": "position",
  "发言": "post",
  "提问": "question",
  "说明": "note",
  "回答": "answer",
  "补充": "followup",
  "私下": "private",
  "PASS": "pass"
 },
 "writer": {
  "总管": "lead",
  "成员": "member",
  "派活脚本": "dispatcher",
  "看板": "board"
 },
 "role": {
  "总管": "lead",
  "执行": "executor",
  "确认": "reviewer",
  "第三方验收": "third_party",
  "与会": "attendee"
 },
 "run_status": {
  "运行中": "running",
  "完成": "done",
  "失败": "failed",
  "已中断": "stopped",
  "异常结束": "lost"
 },
 "run_mode": {
  "新会话": "new",
  "续接": "resume"
 },
 "run_phase": {
  "启动中": "starting",
  "思考": "thinking",
  "调用工具": "tool",
  "正在写回复": "writing",
  "疑似卡住": "stalled",
  "完成": "done",
  "失败": "failed",
  "已停止": "stopped"
 },
 "protocol_role": {
  "总管": "lead",
  "执行": "executor",
  "确认": "reviewer",
  "验收": "acceptance",
  "与会": "attendee"
 },
 "ctx": {
  "目标": "goal",
  "交接": "handoff",
  "变更": "changes",
  "状态": "status",
  "上游交付": "upstream",
  "交付": "delivery",
  "决议": "decisions",
  "协议": "protocol",
  "可走": "moves",
  "PROGRESS": "progress",
  "议题": "issue",
  "问题": "question",
  "开场约定": "opening",
  "发言": "transcript",
  "记号": "notation",
  "读到": "read_upto"
 }
}

# 事件的键
EVENT_KEYS: Dict[str, str] = {
 "项目序": "project_seq",
 "时间": "time",
 "对象": "object",
 "骨架": "skeleton",
 "边": "edge",
 "发起": "from",
 "接收": "to",
 "前状态": "from_state",
 "后状态": "to_state",
 "写入者": "writer",
 "标题": "title",
 "类型": "type",
 "依据": "basis",
 "阶段": "stage",
 "说明": "note",
 "变更项": "changes",
 "差异": "diff",
 "差异理由": "diff_reason",
 "框架版本": "plan_version",
 "批准版": "approved_plan",
 "方案": "options",
 "建议": "recommendation",
 "目标": "goal",
 "键": "key",
 "拟执行": "planned_executor",
 "拟确认": "planned_reviewer",
 "派活": "run",
 "会话": "session",
 "证据": "evidence",
 "结果": "result",
 "前置": "depends_on",
 "与会": "attendees",
 "点名": "mentions",
 "正文": "body",
 "私下": "private",
 "计划": "plan",
 "更正": "correct",
 "越过": "override",
 "随目标": "with_goal"
}

# 骨架、加载清单、渲染规约的键
SKEL_KEYS: Dict[str, str] = {
 "骨架": "skeleton",
 "版本": "version",
 "说明": "description",
 "初始": "initial",
 "终止": "terminal",
 "返工上限": "max_rework",
 "状态": "states",
 "边": "edges",
 "从": "from",
 "到": "to",
 "发起": "initiator",
 "接收": "receiver",
 "默认接收": "default_receiver",
 "必填": "required",
 "可在": "allowed_in",
 "类别": "category",
 "持有": "holder",
 "特殊事件": "special_events",
 "消息事件": "message_events",
 "类型": "types",
 "结果": "results",
 "要批准的变更项": "changes_need_approval",
 "阶段": "stages",
 "序": "order",
 "名称": "name",
 "可并行": "parallel",
 "前置": "depends_on",
 "加载": "loading",
 "目标大小": "target_size",
 "上下文包": "context",
 "角色": "roles",
 "L1文件": "l1_files",
 "块": "blocks",
 "协议": "protocol",
 "规约": "spec",
 "固定参与者": "fixed_participants",
 "主干": "trunk",
 "称谓": "titles",
 "称谓说明": "titles_note",
 "主干取法": "trunk_rule"
}

# 框架文件（collab/内部/流程/ 里的框架 JSON）的键；交接字段名见 FIELDS
FRAME_KEYS: Dict[str, str] = {
 "阶段": "stages",
 "序": "order",
 "名称": "name",
 "类型": "type",
 "前置": "depends_on",
 "可并行": "parallel",
 "任务": "tasks",
 "执行": "executor",
 "确认": "reviewer",
 "来自": "from",
 "人选": "people",
 "产出": "output",
 "通过条件": "pass_condition",
 "键": "key",
 "标题": "title"
}

FIELDS: Dict[str, str] = {
 "目的": "purpose",
 "身份": "role",
 "硬约束": "constraints",
 "可替换的做法": "alternatives",
 "输入": "inputs",
 "交付物": "deliverables",
 "验收标准": "acceptance",
 "授权": "authority",
 "上报条件": "escalate_when",
 "要什么": "want",
 "成功标准": "criteria",
 "要决定什么": "decide",
 "背景与约束": "context",
 "参考资料": "references",
 "已知选项": "options",
 "共识": "consensus",
 "分歧": "disagreements",
 "建议": "recommendation"
}

# 生成块名
BLOCKS: Dict[str, str] = {
 "卡头": "header",
 "流转": "history",
 "流程": "stages",
 "变更": "changes",
 "议题": "issues",
 "与会": "attendees",
 "发言": "transcript",
 "裁决": "ruling",
 "待你决定": "decisions",
 "目标": "goals",
 "任务": "tasks",
 "生效决议": "active_decisions",
 "项目": "project"
}

SKEL_NAMES = {"任务": "task", "目标": "goal", "议题": "issue", "目标-通用": "goal-general", "目标-调研": "goal-research",
              "目标-开发": "goal-dev", "加载": "loading", "渲染": "render"}
STAGE_KEYS = {"序": "order", "名称": "name", "类型": "type", "可并行": "parallel", "前置": "depends_on", "人选": "people",
              "产出": "output", "通过条件": "pass_condition", "任务": "tasks", "计划任务": "planned_tasks"}
SNAPSHOT_KEYS = {"版本": "version", "任务": "tasks", "编号": "id", "标题": "title", "阶段": "stage", "拟执行": "planned_executor",
                 "拟确认": "planned_reviewer", "前置": "depends_on", "内容": "content"}
SEATS = {"总裁": "owner", "总管": "lead", "无": "none"}


def v(kind: str, x: Any) -> Any:
    """一个取值：认得的换成代码，认不出原样（成员派活名、自由文字）。"""
    if isinstance(x, str):
        return VALUES.get(kind, {}).get(x, x)
    return x


def who(x: Any) -> Any:
    if isinstance(x, list):
        return [who(i) for i in x]
    return SEATS.get(x, x) if isinstance(x, str) else x


def stage(s: Any) -> Any:
    """阶段实例（事件里的「阶段」列表、框架、骨架阶段模板）。"""
    if not isinstance(s, dict):
        return s
    out = {}
    for k, x in s.items():
        key = STAGE_KEYS.get(k, k)
        if key == "type":
            x = v("stage_type", x)
        elif key == "people":
            x = who(x)
        out[key] = x
    return out


def skel_name(x: Any) -> Any:
    """骨架名，可带版本：任务@2 → task@2。"""
    if not isinstance(x, str):
        return x
    name, at, ver = x.partition("@")
    return SKEL_NAMES.get(name, name) + at + ver


def event(row: Dict[str, Any], kind: Optional[str] = None, paths=None) -> Dict[str, Any]:
    """一行 v1 事件 → v2。kind：对象种类（goal、task、issue），决定「类型」按目标类型还是议题类型改。
    paths：证据路径改写函数（相对项目根的旧路径 → 新路径），不给就不改。键的顺序不变。"""
    if row.get("v") == 2:
        return dict(row)
    edge = v("edge", row.get("边"))
    out: Dict[str, Any] = {}
    for k, x in row.items():
        key = EVENT_KEYS.get(k, k)
        if key == "v":
            x = 2
        elif key == "edge":
            x = edge
        elif key in ("from_state", "to_state"):
            x = v("state", x)
        elif key in ("from", "to", "planned_executor", "planned_reviewer", "mentions"):
            x = who(x)
        elif key == "result":
            x = v("draft_stage" if edge == "draft_stage" else "result", x)
        elif key == "writer":
            x = v("writer", x)
        elif key == "skeleton":
            x = skel_name(x)
        elif key == "type":
            x = v("goal_type" if kind == "goal" else "issue_type" if edge in ("create", None) else "speech", x) if kind != "task" else x
        elif key == "stage" and isinstance(x, list):
            x = [stage(s) for s in x]
        elif key == "approved_plan" and isinstance(x, dict):
            x = {SNAPSHOT_KEYS.get(a, a): ([{SNAPSHOT_KEYS.get(b, b): (who(c) if b in ("拟执行", "拟确认") else c) for b, c in t.items()}
                                            for t in y] if a == "任务" else y) for a, y in x.items()}
        elif key == "attendees" and isinstance(x, list):
            x = [{{"成员": "member", "视角": "view"}.get(a, a): (who(b) if a == "成员" else b) for a, b in i.items()}
                 if isinstance(i, dict) else i for i in x]
        elif key == "evidence" and paths and isinstance(x, list):
            x = [paths(p) for p in x]
        out[key] = x
    return out


def skeleton(d: Any, ctx: str = "") -> Any:
    """骨架、加载清单、渲染规约：键和取值都换成代码；说明（自由文字）不动。"""
    if isinstance(d, list):
        return [skeleton(x, ctx) for x in d]
    if not isinstance(d, dict):
        return d
    out: Dict[str, Any] = {}
    for k, x in d.items():
        key = SKEL_KEYS.get(k, k)
        if ctx == "states":  # 状态表：键是状态
            out[v("state", k)] = {SKEL_KEYS.get(a, a): (v("category", b) if a == "类别" else v("seat_class", b) if a == "持有" else b)
                                   for a, b in x.items()}
            continue
        if ctx in ("edges", "special_events", "message_events"):  # 边表：键是边
            out[v("edge", k)] = skeleton(x, "edge")
            continue
        if ctx == "results":
            out[v("result", k)] = skeleton(x, "edge")
            continue
        if ctx == "roles":
            out[v("role", k)] = skeleton(x, "role")
            continue
        if ctx == "trunk_rule":
            out[v("edge", k)] = x
            continue
        if key in ("states", "edges", "special_events", "message_events", "results", "roles", "trunk_rule") and isinstance(x, dict):
            out[key] = skeleton(x, key)
        elif key == "skeleton":
            out[key] = skel_name(x)
        elif key in ("initial",):
            out[key] = v("state", x)
        elif key in ("terminal", "from", "allowed_in"):
            out[key] = [v("state", s) for s in x] if isinstance(x, list) else v("state", x)
        elif key == "to" and ctx == "edge":
            out[key] = v("seat_class", x) if str(x).startswith("@") else v("state", x)
        elif key in ("initiator", "receiver", "default_receiver"):
            out[key] = v("seat_class", x)
        elif key == "required":
            out[key] = [EVENT_KEYS.get(s, s) for s in x]
        elif key == "types":
            out[key] = [v("goal_type", s) if s in VALUES["goal_type"] else v("issue_type", s) for s in x]
        elif key == "stages" and isinstance(x, list):
            out[key] = [stage(s) for s in x]
        elif key == "blocks":
            out[key] = [v("ctx", s) for s in x]
        elif key == "protocol" and ctx == "role":
            out[key] = [v("protocol_role", s) for s in x]
        elif key == "fixed_participants":
            out[key] = who(x)
        elif key == "trunk":
            out[key] = [v("edge", s) for s in x]
        elif key == "target_size":
            out[key] = {SKEL_KEYS.get(a, a): b for a, b in x.items()}
        elif key == "spec" and x == "视图":
            out[key] = "view"
        elif key == "loading" and x == "加载清单":
            out[key] = "loading"
        else:
            out[key] = x
    return out


def frame_file(d: Any) -> Any:
    """框架 JSON：键换英文，交接字段名换代码，阶段类型和人员换代码。"""
    if isinstance(d, list):
        return [frame_file(x) for x in d]
    if not isinstance(d, dict):
        return d
    out = {}
    for k, x in d.items():
        key = FRAME_KEYS.get(k) or FIELDS.get(k) or k
        if key == "type":
            x = v("stage_type", x)
        elif key in ("executor", "reviewer"):
            x = who(x)
        elif key == "people":
            x = who(x)
        elif isinstance(x, (dict, list)):
            x = frame_file(x)
        out[key] = x
    return out


def run_record(r: Dict[str, Any]) -> Dict[str, Any]:
    """运行记录 internal/runs/*.json：键已是英文（收尾、会话丢失、读到、补到除外）；mode、seat、status、phase 换代码。"""
    keys = {"收尾": "wrap", "会话丢失": "session_lost", "读到": "read_upto", "补到": "caught_up"}
    out = {}
    for k, x in r.items():
        key = keys.get(k, k)
        if key == "mode":
            x = v("run_mode", x)
        elif key == "seat":
            x = {"执行": "executor", "验收": "acceptance", "确认": "reviewer", "与会": "attendee"}.get(x, x)
        elif key == "status":
            x = v("run_status", x)
        elif key == "phase":
            x = v("run_phase", x)
        out[key] = x
    return out


# ---------- Markdown 里的路径、生成块标记、角色标记 ----------
import re  # noqa: E402

SEGMENTS = {"内部": "internal", "归档": "archive", "目标": "goals", "任务": "tasks", "议题": "issues", "产出": "outputs",
            "运行记录": "runs", "历史": "history"}
UNDER_INTERNAL = {"流程": "plans", "流转": "flow", "运行记录": "runs"}
FILES = {"协议.md": "protocol.md", "成员.md": "members.md", "决议.md": "decisions.md", "日志.md": "log.md", "经验.md": "lessons.md",
         "口令.md": "commands.md", "_模板.md": "_template.md", "方案.md": "proposal.md", "问题.md": "questions.md", "讨论.md": "discussion.md",
         "花名册.json": "roster.json", "时钟.json": "clock.json", "渲染.json": "render.json", ".叙述.json": ".narrative.json",
         "班子.json": "team.json", "人才.json": "talent.json", "安排.md": "schedule.md", "本月布局.md": "month.md", "已完成.md": "done.md",
         "截止.md": "deadlines.md", "日历.md": "calendar.md", "目标.md": "goals.md", "任务.md": "tasks.md", "归档.md": "archive.md"}
GOAL_CARD = re.compile(r"\b(G\d+)-(?!T\d)[^/\s)`\]」，。；]*?\.md\b")
WORK_DIR = re.compile(r"\bwork/(G\d+)-[^/\s)`\]」，。；]+")


def path(p: str) -> str:
    """一条路径（相对项目根或 collab/，可带 ./、../、#锚点）：各段按旧名 → 新名改，目标卡和工作目录去掉标题。"""
    p = WORK_DIR.sub(r"work/\1", p)
    p = GOAL_CARD.sub(r"\1.md", p)
    parts = p.split("/")
    out = []
    for n, seg in enumerate(parts):
        prev = parts[n - 1] if n else ""
        if prev == "内部" and seg in UNDER_INTERNAL:
            out.append(UNDER_INTERNAL[seg])
        elif seg in SEGMENTS:
            out.append(SEGMENTS[seg])
        elif seg in ("日历",) and (n + 1 < len(parts)):
            out.append("calendar")
        else:
            base, hash_, anchor = seg.partition("#")
            out.append(FILES.get(base, base) + hash_ + anchor)
    return "/".join(out)


PATHLIKE = re.compile(r"(?:(?:\.{1,2}/)*(?:collab|work|内部|归档|目标|任务|议题|产出)/[^\s`)\]」（「，。；、|]*|"
                      r"[^\s`(\[「/]*?(?:" + "|".join(re.escape(k) for k in sorted(FILES, key=len, reverse=True)) + r"))")


def paths_in_text(text: str) -> str:
    """正文里的路径：Markdown 链接目标、反引号里的路径、以 collab/、work/、内部/… 开头的路径、旧文件名。"""
    text = re.sub(r"\]\(([^)\s]+)\)", lambda m: "](" + path(m.group(1)) + ")", text)
    text = PATHLIKE.sub(lambda m: path(m.group(0)), text)
    text = re.sub(r"`(流转|流程|运行记录)/", lambda m: "`" + UNDER_INTERNAL[m.group(1)] + "/", text)  # 「internal/ 里的 `流转/`」
    return text


MARK = re.compile(r"<!-- flow:(\S+) (\S+) (\S+) sha=([0-9a-f…]+) -->")
ROLE = re.compile(r"<!-- 角色：(.*?) -->")


def markers(text: str) -> str:
    """生成块标记换代码（flow:待你决定 项目 视图@1 → flow:decisions project view@3，sha 只算正文，不变）；
    协议的角色标记 <!-- 角色：总管 --> → <!-- role: lead -->。"""
    def block(m):
        name = BLOCKS.get(m.group(1), m.group(1))
        obj = BLOCKS.get(m.group(2), m.group(2)) if m.group(2) == "项目" else m.group(2)
        return f"<!-- flow:{name} {obj} view@3 sha={m.group(4)} -->"
    text = MARK.sub(block, text)
    def role(m):
        roles = [VALUES["protocol_role"].get(x, x) for x in re.split(r"[、,，\s]+", m.group(1).strip()) if x]
        return "<!-- role: " + ", ".join(roles) + " -->"
    return ROLE.sub(role, text)


def markdown(text: str) -> str:
    return markers(paths_in_text(text))
