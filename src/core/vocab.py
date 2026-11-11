#!/usr/bin/env python3
"""标识的唯一来源：对象种类、席位、席位类、状态、边、结果、类别、类型、小节和生成块的代码。

取值都是英文代码，只有一套：代码里比较、存储、下发给看板的都是这里的常量，不写字面量；
给人看的文字由语言包 src/i18n/<lang>.json 按代码查（i18n.py），取值和命名空间一一对应。
看板 JS 用 server 下发的同一份（as_dict()，见 board/static/vocab.js）。
名字对照见 collab/目标/G036/术语表.md。只用 Python 标准库。
"""
from typing import Dict


class Kind:  # 对象种类，骨架文件和种类同名
    GOAL = "goal"
    TASK = "task"
    ISSUE = "issue"


class Seat:  # 席位
    OWNER = "owner"
    LEAD = "lead"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    ACCEPTANCE = "acceptance"  # 派活席位「验收」，和「确认」同义
    ATTENDEE = "attendee"


class SeatClass:  # 骨架里发起、接收用的席位类；@ 开头的由回放推出
    HOLDER = "holder"
    MANAGER = "manager"
    LEAD = Seat.LEAD
    OWNER = Seat.OWNER
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    SELF = "self"
    NONE = "none"
    STATE_SEAT = "@state_seat"
    HOLDER_BEFORE_ESCALATION = "@holder_before_escalation"
    HOLDER_BEFORE_PAUSE = "@holder_before_pause"
    STATE_BEFORE_ESCALATION = "@state_before_escalation"
    STATE_BEFORE_PAUSE = "@state_before_pause"
    LAST_DELIVERER = "@last_deliverer"
    UNCHANGED = "@unchanged"


NONE = SeatClass.NONE  # 接收方「无」，也是还没建立的对象的状态


class State:  # 任务、目标、议题的状态
    NONE = NONE
    # 任务
    PLANNED = "planned"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    PAUSED = "paused"
    FAILED = "failed"
    PASSED = "passed"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"
    # 目标
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    PENDING_ACCEPTANCE = "pending_acceptance"
    DONE = "done"
    # 议题
    DISCUSSING = "discussing"
    CLOSING = "closing"
    PENDING_RULING = "pending_ruling"
    RULED = "ruled"


class Edge:  # 流转动作
    CREATE = "create"
    APPROVE = "approve"
    DISPATCH = "dispatch"
    PICK_UP = "pick_up"
    DELIVER = "deliver"
    REVIEW = "review"
    HAND_OVER = "hand_over"
    ESCALATE = "escalate"
    UNBLOCK = "unblock"
    REASSIGN = "reassign"
    PAUSE = "pause"
    RESUME = "resume"
    REOPEN = "reopen"
    CANCEL = "cancel"
    WITHDRAW = "withdraw"
    REDRAFT = "redraft"
    # 目标
    SUBMIT = "submit"
    RETURN = "return"
    REQUEST_ACCEPTANCE = "request_acceptance"
    COMPLETE = "complete"
    REJECT = "reject"
    # 议题
    START = "start"
    END_DISCUSSION = "end_discussion"
    CONTINUE_DISCUSSION = "continue_discussion"
    SUMMARIZE = "summarize"
    RULE = "rule"
    # 特殊事件
    CHANGE = "change"
    PROGRESS = "progress"
    CORRECTION = "correction"
    COMMENT = "comment"
    DRAFT_STAGE = "draft_stage"
    # 消息事件
    POST = "post"
    PASS = "pass"
    # 时序图里的虚拟步骤：总裁的要求带来新增任务
    REQUEST = "request"
    REQUEST_CHANGE = "request_change"


class Result:  # 确认结果
    PASS = "pass"
    NEEDS_MORE = "needs_more"
    FAIL = "fail"


class Category:  # 状态类别
    TODO = "todo"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"


class DraftStage:  # 目标起草时的阶段
    IDEA = "idea"
    DISCUSSION = "discussion"
    PROPOSAL = "proposal"
    FRAMING = "framing"  # 起草中、阶段事件之外：已在搭框架


class GoalType:
    GENERAL = "general"
    RESEARCH = "research"
    DEV = "dev"


class IssueType:
    COUNCIL = "council"
    REVIEW_MEETING = "review_meeting"


class StageType:  # 目标阶段的类型
    WORK = "work"
    RESEARCH = "research"
    ACCEPTANCE = "acceptance"


class StageStatus:  # 阶段进度，由下属任务推出
    PASSED = State.PASSED
    ACTIVE = State.ACTIVE
    READY = "ready"
    NOT_STARTED = "not_started"


class Speech:  # 发言类型，由投影推出
    POSITION = "position"
    POST = "post"
    QUESTION = "question"
    NOTE = "note"
    ANSWER = "answer"
    FOLLOWUP = "followup"
    PRIVATE = "private"
    PASS = "pass"


class Pending:  # 待你决定的类型
    APPROVE_PLAN = "approve_plan"
    ACCEPTANCE = "acceptance"
    BLOCKED = "blocked"
    RULING = "ruling"


class Diff:  # 现在和批准版的差别
    ADDED = "added"
    CANCELLED = "cancelled"
    EXECUTOR_CHANGED = "executor_changed"
    REVIEWER_CHANGED = "reviewer_changed"
    DEPS_CHANGED = "deps_changed"
    CONTENT_CHANGED = "content_changed"


class Writer:  # 事件的写入者
    LEAD = Seat.LEAD
    MEMBER = "member"
    DISPATCHER = "dispatcher"
    BOARD = "board"


class Role:  # 上下文包的角色（loading.json「角色」）
    LEAD = Seat.LEAD
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    THIRD_PARTY = "third_party"
    ATTENDEE = "attendee"


class Skel:  # 骨架名
    TASK = Kind.TASK
    GOAL = Kind.GOAL
    ISSUE = Kind.ISSUE
    LOADING = "loading"
    RENDER = "render"

    @staticmethod
    def goal_type(gtype: str) -> str:
        return f"goal-{gtype}"


class RunStatus:  # 派活记录的状态
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"
    LOST = "lost"


class RunMode:  # 派活记录的方式
    NEW = "new"
    RESUME = "resume"


class RunPhase:  # 运行中的阶段；结束后是结果
    STARTING = "starting"
    THINKING = "thinking"
    TOOL = "tool"
    WRITING = "writing"
    STALLED = "stalled"  # 看板推出：运行中太久没有实际输出
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


class MeetAction:  # 朝会页上不是边的动作
    REDELIVER = "redeliver"
    ADD = "add"
    STOP = "stop"
    WRAP = "wrap"


class Block:  # 生成块的代码
    HEADER = "header"
    HISTORY = "history"
    STAGES = "stages"
    CHANGES = "changes"
    ISSUES = "issues"
    ATTENDEES = "attendees"
    TRANSCRIPT = "transcript"
    RULING = "ruling"
    DECISIONS = "decisions"
    GOALS = "goals"
    TASKS = "tasks"
    ACTIVE_DECISIONS = "active_decisions"
    PROJECT = "project"  # PROGRESS 里生成块的对象


class Ctx:  # 上下文包里的块（loading.json「角色」的「块」）
    GOAL = "goal"
    HANDOFF = "handoff"
    CHANGES = "changes"
    STATUS = "status"
    UPSTREAM = "upstream"
    DELIVERY = "delivery"
    DECISIONS = "decisions"
    PROTOCOL = "protocol"
    MOVES = "moves"
    PROGRESS = "progress"
    ISSUE = "issue"
    QUESTION = "question"
    OPENING = "opening"
    TRANSCRIPT = "transcript"
    NOTATION = "notation"
    READ_UPTO = "read_upto"  # 清单最后一行：议题喂到的项目序


class Section:  # 卡片和 PROGRESS 的小节标题
    WANT = "want"
    CRITERIA = "criteria"
    STAGES = "stages"
    CHANGES = "changes"
    ISSUES = "issues"
    HISTORY = "history"
    HANDOFF = "handoff"
    NOTES = "notes"
    QUESTION = "question"
    ATTENDEES = "attendees"
    TRANSCRIPT = "transcript"
    SUMMARY = "summary"
    RULING = "ruling"
    OPENING = "opening"
    NEXT = "next"
    STATUS = "status"
    BLOCKERS = "blockers"
    DECISIONS = "decisions"
    ACTIVE_DECISIONS = "active_decisions"
    GOALS = "goals"
    TASKS = "tasks"
    LOADING_MAP = "loading_map"
    OPEN_QUESTIONS = "open_questions"  # 目标的 问题.md 里要总裁回答的一节
    NOW_PROJECTS = "now_projects"  # NOW.md 的项目表（中文标题「任务」）
    DIRECTIONS = "directions"  # NOW.md 的大方向
    WEEK_THREE = "week_three"  # month.md 的本周三件事


class Field:  # 交接和目标卡「要什么」的字段
    PURPOSE = "purpose"
    ROLE = "role"
    CONSTRAINTS = "constraints"
    ALTERNATIVES = "alternatives"
    INPUTS = "inputs"
    DELIVERABLES = "deliverables"
    ACCEPTANCE = "acceptance"
    AUTHORITY = "authority"
    ESCALATE_WHEN = "escalate_when"
    WANT = Section.WANT
    CRITERIA = Section.CRITERIA
    # 议题卡「问题」「总结」
    DECIDE = "decide"
    CONTEXT = "context"
    REFERENCES = "references"
    OPTIONS = "options"
    CONSENSUS = "consensus"
    DISAGREEMENTS = "disagreements"
    RECOMMENDATION = "recommendation"


NAMESPACES = (Kind, Seat, SeatClass, State, Edge, Result, Category, DraftStage, GoalType, IssueType, StageType,
              StageStatus, Speech, Pending, Diff, Writer, Role, RunStatus, RunMode, RunPhase, MeetAction, Block, Ctx, Section, Field)


def as_dict() -> Dict[str, Dict[str, str]]:
    """全部常量：{命名空间: {名字: 取值}}，看板 JS 用。"""
    return {ns.__name__: {k: v for k, v in vars(ns).items() if k.isupper() and isinstance(v, str)} for ns in NAMESPACES}


def as_js() -> str:
    """board/static/vocab.js 的内容：window.V = {...}。"""
    import json
    return "window.V = " + json.dumps(as_dict(), ensure_ascii=False, sort_keys=True) + ";\n"
