"""测试用：按中文写的参数（边、种类、席位、键名）换成代码再交给 flow，测试里的剧情照中文写。"""
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "core"))
import flow  # noqa: E402
from i18n import code_of  # noqa: E402

KW = {"发起": "from", "说明": "note", "依据": "basis", "方案": "options", "建议": "recommendation", "结果": "result", "给": "to",
      "证据": "evidence", "派活": "run", "会话": "session", "变更项": "changes", "阶段": "stage", "写入者": "writer", "正文": "body",
      "点名": "mentions", "私下": "private", "与会": "attendees", "类型": "type", "标题": "title", "目标": "goal", "人选": "people",
      "越过": "override", "差异理由": "diff_reason", "框架版本": "plan_version", "更正": "correct", "交接": "handoff", "键": "key",
      "拟执行": "planned_executor", "拟确认": "planned_reviewer", "前置": "depends_on", "随目标": "with_goal", "任务阶段": "task_stage",
      "差异": "diff"}
SEATS = {"总裁": "owner", "总管": "lead", "无": "none"}


def seat(x: Any) -> Any:
    return [seat(i) for i in x] if isinstance(x, list) else SEATS.get(x, x)


def code(kind: str, x: Any) -> Any:
    return (code_of(kind, x) or x) if isinstance(x, str) else x


def args(edge: str, kw: Dict[str, Any], kind: str = "") -> Dict[str, Any]:
    out = {}
    for k, v in kw.items():
        key = KW.get(k, k)
        if key == "result" and v is not None:
            v = code("draft_stage" if edge == "draft_stage" else "result", v)
        elif key == "writer":
            v = code("writer", v)
        elif key in ("to", "mentions", "from", "planned_executor", "planned_reviewer"):
            v = seat(v)
        elif key == "people" and isinstance(v, dict):
            v = {n: seat(w) for n, w in v.items()}
        elif key == "type" and isinstance(v, str):
            v = code("goal_type" if kind == "goal" else "issue_type" if kind == "issue" else "speech", v)
        elif key == "attendees" and isinstance(v, list):
            v = [{"member": seat(i.get("成员", i.get("member"))), "view": i.get("视角", i.get("view", ""))} if isinstance(i, dict) else i for i in v]
        elif key == "handoff" and isinstance(v, dict):
            v = {code("field", a): b for a, b in v.items()}
        elif key == "stage" and isinstance(v, list):
            v = [flow.normalize_frame({"stages": [s]})["stages"][0] for s in v]
        out[key] = v
    return out


def record(proj, obj: str, edge: str, a: Dict[str, Any]):
    edge = code("edge", edge)
    return flow.record(proj, obj, edge, args(edge, a, flow.kind_of(obj)))


def create(proj, kind: str, a: Dict[str, Any]):
    kind = code("kind", kind)
    return flow.create(proj, kind, args("create", a, kind))


def dispatch_begin(proj, obj, seat_name, member, run, override=""):
    return flow.dispatch_begin(proj, obj, code("seat", seat_name), member, run, override)
