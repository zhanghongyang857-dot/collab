#!/usr/bin/env python3
"""文件和目录名的唯一来源：项目 collab/ 下的目录和文件、班子配置、NOW 数据文件。名字只有一套英文。

Python 里 `import paths` 后用常量；shell 脚本用 `eval "$(python3 paths.py sh)"` 取同名变量（P_COLLAB…）。
目录名都相对 collab/（INTERNAL_FLOW 是 "internal/flow"，拼路径时用 collab_dir / INTERNAL_FLOW）。
旧名（中文）→ 新名的对照在 LEGACY、LEGACY_NOW，迁移用。名字对照见 collab/目标/G036/术语表.md。只用 Python 标准库。
"""
import re
import sys
from typing import Dict

COLLAB = "collab"
PROGRESS = "PROGRESS.md"
CONFIG = "config.json"  # collab/config.json：账本格式版本、项目语言、称谓覆盖
WORK = "work"  # 交付和草稿的总目录，和 collab/ 并列
LOOSE = "loose"  # 零散任务的工作目录 work/loose/

# collab/ 下的目录
GOALS = "goals"
TASKS = "tasks"
ISSUES = "issues"
ARCHIVE = "archive"
OUTPUTS = "outputs"
INTERNAL = "internal"
INTERNAL_PLANS = INTERNAL + "/plans"
INTERNAL_FLOW = INTERNAL + "/flow"
INTERNAL_RUNS = INTERNAL + "/runs"
HISTORY = "history"  # INTERNAL_PLANS 里旧版本骨架的子目录

# collab/ 下的文件
PROTOCOL = "protocol.md"
MEMBERS = "members.md"
DECISIONS = "decisions.md"
LOG = "log.md"
LESSONS = "lessons.md"
COMMANDS = "commands.md"
TEMPLATE = "_template.md"
# 单文件版小项目：卡片都在一个文件里
TASKS_MD = "tasks.md"
GOALS_MD = "goals.md"
ARCHIVE_MD = "archive.md"
# 目标目录 collab/goals/G00x/ 里的文档
PROPOSAL = "proposal.md"
QUESTIONS = "questions.md"
DISCUSSION = "discussion.md"  # G026 之前的名字，已归档的卡还在用
# INTERNAL_PLANS 里的文件
ROSTER = "roster.json"
CLOCK = "clock.json"  # 演示案例停在剧情里的某一刻
RENDER_OVERRIDE = "render.json"
# INTERNAL_RUNS 里议题的启动检查结果：<议题>.ready.txt
READY_SUFFIX = ".ready.txt"
LEGACY_READY_SUFFIX = ".到场.txt"
# INTERNAL_FLOW 里的文件
NARRATIVE = ".narrative.json"

# 班子
TEAM_DIR = "team"  # 本机发布时在 NOW/team/
TEAM_JSON = "team.json"
TALENT_JSON = "talent.json"

# 工具包
VERSION_TXT = "VERSION.txt"  # 发布版带它
BOARD_APP = "Board.app"  # 看板启动器（board/build_app.sh、service.sh）

# NOW 数据文件
SCHEDULE = "schedule.md"
MONTH = "month.md"
DONE = "done.md"
CALENDAR_DIR = "calendar"
CALENDAR = CALENDAR_DIR + "/calendar.md"
DEADLINES = "deadlines.md"
NOW_MODULES = "modules"  # NOW 数据目录里自带的模块


def slug(title: str) -> str:
    if title.strip() and title.isascii():  # 英文标题：单词之间用连字符，长一点
        s = re.sub(r"[\\/:*?\"<>|]+", "", title)
        s = re.sub(r"\s+", "-", s.strip())
        return s[:40].rstrip("-") or "untitled"
    s = re.sub(r"[\\/:*?\"<>|\s]+", "", title)
    return s[:24] or "未命名"


def card_name(obj: str, title: str) -> str:
    """任务卡、议题卡的文件名（不含目录）：编号-标题.md。"""
    return f"{obj}-{slug(title)}.md"


def goal_card(obj: str, title: str = "") -> str:
    """目标卡的文件名：只用编号（G036.md），标题只写在卡内。"""
    return f"{obj}.md"


def work_dir(goal: str) -> str:
    """目标的工作目录（相对项目根）：work/G036/。"""
    return f"{WORK}/{goal}"


# 旧名 → 新名（相对 collab/；目录在前，文件在后，按长到短改）。目标卡 G036-标题.md → G036.md、
# work/G036-标题/ → work/G036/ 不在表里，由迁移按编号改。
LEGACY: Dict[str, str] = {
    "内部/流程/历史": INTERNAL_PLANS + "/" + HISTORY,
    "内部/流程/花名册.json": INTERNAL_PLANS + "/" + ROSTER,
    "内部/流程/时钟.json": INTERNAL_PLANS + "/" + CLOCK,
    "内部/流程/渲染.json": INTERNAL_PLANS + "/" + RENDER_OVERRIDE,
    "内部/流转/.叙述.json": INTERNAL_FLOW + "/" + NARRATIVE,
    "内部/流程": INTERNAL_PLANS,
    "内部/流转": INTERNAL_FLOW,
    "内部/运行记录": INTERNAL_RUNS,
    "内部": INTERNAL,
    "归档/目标": ARCHIVE + "/" + GOALS,
    "归档/任务": ARCHIVE + "/" + TASKS,
    "归档/议题": ARCHIVE + "/" + ISSUES,
    "归档/决议.md": ARCHIVE + "/" + DECISIONS,
    "目标": GOALS,
    "任务": TASKS,
    "议题": ISSUES,
    "归档": ARCHIVE,
    "产出": OUTPUTS,
    "协议.md": PROTOCOL,
    "成员.md": MEMBERS,
    "决议.md": DECISIONS,
    "日志.md": LOG,
    "经验.md": LESSONS,
    "口令.md": COMMANDS,
    "_模板.md": TEMPLATE,
    "任务.md": TASKS_MD,
    "目标.md": GOALS_MD,
    "归档.md": ARCHIVE_MD,
    "方案.md": PROPOSAL,
    "问题.md": QUESTIONS,
    "讨论.md": DISCUSSION,
}
# 内部的骨架覆盖（collab/内部/流程/<中文骨架名>.json）→ 新骨架名
LEGACY_SKELETONS = {"任务": "task", "目标": "goal", "议题": "issue", "目标-通用": "goal-general", "目标-调研": "goal-research",
                    "目标-开发": "goal-dev", "加载": "loading", "渲染": "render"}
# NOW 数据目录、班子目录、工具包里的旧名
LEGACY_NOW: Dict[str, str] = {
    "安排.md": SCHEDULE, "本月布局.md": MONTH, "已完成.md": DONE, "日历/日历.md": CALENDAR, "日历": CALENDAR_DIR,
    "截止.md": DEADLINES, "模块": NOW_MODULES, "班子": TEAM_DIR, "班子.json": TEAM_JSON, "人才.json": TALENT_JSON,
    "口令.md": COMMANDS, "归档": ARCHIVE, "版本.txt": VERSION_TXT,
}
LEGACY_TEAM_DIR = "班子"
LEGACY_TEAM_JSON = "班子.json"
LEGACY_TALENT_JSON = "人才.json"


def as_dict() -> Dict[str, str]:
    return {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str)}


def as_sh() -> str:
    """shell 变量赋值，一行一个：P_COLLAB='collab'。"""
    return "".join(f"P_{k}='{v}'\n" for k, v in sorted(as_dict().items()))


if __name__ == "__main__":
    if sys.argv[1:] == ["sh"]:
        sys.stdout.write(as_sh())
    else:
        sys.exit("用法：python3 paths.py sh")
