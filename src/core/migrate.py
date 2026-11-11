#!/usr/bin/env python3
"""迁移：旧格式账本（中文目录、中文键、事件 v1）→ 格式 3（英文目录和代码，事件 v2，collab/config.json）。由 init.sh 调用。

  migrate.py project <项目目录> [--dry-run] [--lang zh|en]     迁移一个项目
  migrate.py rollback <项目目录>                                用最近一次备份恢复
  migrate.py now <NOW 数据目录> [--dry-run]                      NOW 数据文件和班子目录改名（安排.md → schedule.md、班子/ → team/…）
  migrate.py now-rollback <NOW 数据目录>

做法（规格 §9）：已是格式 3 就跳过；先在临时目录里整份改好、回放核对、跑检查，都通过才动项目：
备份 collab/、work/、AGENTS.md、.claude/、.gitignore 到 <项目>/.collab-backup/<时间>/（.gitignore 加这一行），再换上改好的。
回放核对：每个对象每条事件之后的状态和持有人、事件条数和 seq 改写前后都相同，不同就中止。可重复运行，流转历史一条不丢。
对照表在 paths.LEGACY、legacy.py。只用 Python 标准库。
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flow  # noqa: E402
import i18n  # noqa: E402
import team as team_mod  # noqa: E402
import legacy  # noqa: E402
import paths as P  # noqa: E402

BACKUP = ".collab-backup"
BACKED = (P.COLLAB, P.WORK, "AGENTS.md", ".claude", ".gitignore")  # 备份和回退的范围
NOW_BACKUP = ".now-backup"
OLD_COLLAB_MARK = ("内部", "流转")  # 旧格式新结构项目的标志：collab/内部/流转/


class MigrateError(Exception):
    pass


# ---------- 旧格式的独立回放：只用旧事件本身推状态和持有人，用来核对改写 ----------

KEEP_HOLDER_OLD = {"接手", "变更", "进展", "更正", "意见", "起草阶段", "发言", "PASS"}


def old_replay(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """旧事件（v1）回放出的最终状态、持有人、事件条数：作废的不算，特殊事件和消息不改状态。"""
    voided = {r.get("更正") for r in rows if r.get("边") == "更正"}
    state, holder = "无", None
    for r in rows:
        if r.get("seq") in voided or r.get("边") == "更正":
            continue
        if r.get("边") in KEEP_HOLDER_OLD - {"接手"}:
            continue
        state = r.get("后状态") or state
        if r.get("边") == "接手":
            holder = r.get("发起")
        else:
            to = r.get("接收")
            holder = None if to in (None, "无") else to
    return {"state": legacy.v("state", state), "holder": legacy.who(holder), "count": len(rows), "seqs": [r.get("seq") for r in rows]}


def old_trajectory(rows: List[Dict[str, Any]]) -> List[Tuple[Any, Any]]:
    """每条事件之后的（状态，持有人）：逐条核对用。"""
    out = []
    for k in range(1, len(rows) + 1):
        s = old_replay(rows[:k])
        out.append((s["state"], s["holder"]))
    return out


# ---------- 改名 ----------

def goal_card_renames(collab: Path) -> Dict[str, str]:
    """目标卡 G036-标题.md → G036.md（目标/ 和 归档/目标/ 下）；返回 {旧编号前缀: 新名}，并给工作目录用。"""
    out = {}
    for d in (collab / "目标", collab / "归档" / "目标"):
        if d.is_dir():
            for f in sorted(d.glob("G*.md")):
                m = re.fullmatch(r"(G\d+)-(?!T\d).*\.md", f.name)
                if m:
                    out[f.name] = f"{m.group(1)}.md"
    return out


TOP = {"目标": P.GOALS, "任务": P.TASKS, "议题": P.ISSUES, "归档": P.ARCHIVE, "产出": P.OUTPUTS, "内部": P.INTERNAL}
UNDER_ARCHIVE = {"目标": P.GOALS, "任务": P.TASKS, "议题": P.ISSUES}
UNDER_INTERNAL = {"流程": "plans", "流转": "flow", "运行记录": "runs"}


def rel_rename(rel: str) -> str:
    """collab/ 下一个相对路径的新名：目录按旧名表换，目标卡去掉标题，骨架覆盖换英文名，文件名按旧名表换。"""
    parts = rel.split("/")
    out = list(parts)
    if parts[0] in TOP:
        out[0] = TOP[parts[0]]
        if len(parts) > 2 and parts[0] == "归档" and parts[1] in UNDER_ARCHIVE:
            out[1] = UNDER_ARCHIVE[parts[1]]
        if len(parts) > 2 and parts[0] == "内部" and parts[1] in UNDER_INTERNAL:
            out[1] = UNDER_INTERNAL[parts[1]]
            if parts[1] == "流程" and len(parts) > 3 and parts[2] == "历史":
                out[2] = P.HISTORY
    if not ledger_file(rel):  # 归档里的别的文档（旧项目快照等）：只换外层的 归档/，里面原样
        return "/".join(out)
    name = parts[-1]
    goal_dir = out[:-1] in ([P.GOALS], [P.ARCHIVE, P.GOALS])
    m = re.fullmatch(r"(G\d+)-(?!T\d).*\.md", name)
    if m and goal_dir:
        name = f"{m.group(1)}.md"
    elif name.endswith(P.LEGACY_READY_SUFFIX):
        name = name[: -len(P.LEGACY_READY_SUFFIX)] + P.READY_SUFFIX
    elif parts[:2] == ["内部", "流程"] and name.endswith(".json"):
        base, at, ver = name[:-5].partition("@")
        if base in P.LEGACY_SKELETONS:
            name = P.LEGACY_SKELETONS[base] + at + ver + ".json"
        else:
            name = legacy.FILES.get(name, name.replace("框架", "plan"))
    else:
        name = legacy.FILES.get(name, name)
    out[-1] = name
    return "/".join(out)


def work_rename(rel: str) -> str:
    """work/ 下的相对路径：G036-标题/ → G036/。"""
    return re.sub(r"^(G\d+)-[^/]+", r"\1", rel)


def path_rewriter(goal_cards: Dict[str, str]):
    """事件 evidence 和正文里的路径：collab/… 按表换，work/G036-标题/ → work/G036/。"""
    def fix(p: str) -> str:
        if p.startswith(P.COLLAB + "/"):
            return P.COLLAB + "/" + rel_rename(p[len(P.COLLAB) + 1:])
        if p.startswith(P.WORK + "/"):
            return P.WORK + "/" + work_rename(p[len(P.WORK) + 1:])
        return legacy.path(p)
    return fix


# ---------- 内容改写 ----------

def convert_json(rel_new: str, text: str) -> str:
    """internal/ 下的 JSON：运行记录、时钟、叙述标记、骨架覆盖、框架文件、花名册（键换英文，同班子配置）。"""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    name = rel_new.rsplit("/", 1)[-1]
    if rel_new.startswith(P.INTERNAL_RUNS + "/"):
        return json.dumps(legacy.run_record(data), ensure_ascii=False, indent=1 if text.startswith("{\n ") else 2) + "\n"
    if name == P.CLOCK:
        return json.dumps({{"现在": "now", "回目": "chapter", "说明": "note"}.get(k, k): v for k, v in data.items()}, ensure_ascii=False) + "\n"
    if name == P.NARRATIVE:
        return json.dumps({{"项目序": "project_seq"}.get(k, k): v for k, v in data.items()}, ensure_ascii=False) + "\n"
    if name == P.ROSTER:
        return json.dumps(team_mod.english(json.loads(legacy.paths_in_text(text))), ensure_ascii=False, indent=1) + "\n"
    if rel_new.startswith(P.INTERNAL_PLANS + "/") and (("骨架" in data or "规约" in data or "加载" in data) or "/history/" in rel_new):
        return json.dumps(legacy.skeleton(data), ensure_ascii=False, indent=1) + "\n"
    if rel_new.startswith(P.INTERNAL_PLANS + "/"):
        return json.dumps(legacy.frame_file(data), ensure_ascii=False, indent=1) + "\n"
    return text


def convert_markdown(text: str, lang: str, fix) -> str:
    """Markdown：路径和生成块标记换新写法（迁成英文的，之后再按 init.sh lang 换语言）。"""
    text = legacy.markdown(text)
    text = re.sub(r"\bwork/(G\d+)-[^/\s)`\]」，。；]+", r"work/\1", text)
    return text


# ---------- 一个项目 ----------

def is_new(root: Path) -> bool:
    cfg = root / P.COLLAB / P.CONFIG
    try:
        return json.loads(cfg.read_text(encoding="utf-8")).get("format") == flow.FORMAT
    except (OSError, ValueError):
        return False


def is_old(root: Path) -> bool:
    return (root / P.COLLAB / Path(*OLD_COLLAB_MARK)).is_dir()


def running_runs(root: Path) -> List[str]:
    """旧运行记录里还在跑的派活（status 运行中且进程还在）。"""
    out = []
    d = root / P.COLLAB / "内部" / "运行记录"
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("status") == "运行中" and r.get("pid"):
            try:
                os.kill(int(r["pid"]), 0)
                out.append(r.get("run") or f.stem)
            except (ProcessLookupError, ValueError):
                pass
            except PermissionError:
                out.append(r.get("run") or f.stem)
    return out


def plan_project(root: Path, lang: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """{旧相对路径（相对项目根）: 新相对路径}，collab/ 和 work/ 下的全部文件；第二个是目标卡改名。"""
    collab = root / P.COLLAB
    moves: Dict[str, str] = {}
    for f in sorted(collab.rglob("*")):
        if f.is_file():
            rel = f.relative_to(collab).as_posix()
            moves[f"{P.COLLAB}/{rel}"] = f"{P.COLLAB}/{rel_rename(rel)}"
    work = root / P.WORK
    for f in sorted(work.rglob("*")) if work.is_dir() else []:
        if f.is_file():
            rel = f.relative_to(work).as_posix()
            moves[f"{P.WORK}/{rel}"] = f"{P.WORK}/{work_rename(rel)}"
    seen: Dict[str, str] = {}
    for a, b in moves.items():
        if b in seen:
            raise MigrateError(f"改名后重名：{seen[b]} 和 {a} 都会变成 {b}")
        seen[b] = a
    return moves, goal_card_renames(collab)


def ledger_file(rel: str) -> bool:
    """collab/ 下的账本文件（改写路径和块标记）：归档/ 里只算目标、任务、议题和决议，别的归档文档（旧项目快照等）原样留着。"""
    parts = rel.split("/")
    return parts[0] != "归档" or len(parts) > 1 and parts[1] in ("目标", "任务", "议题", "决议.md")


def build_staged(root: Path, stage: Path, lang: str) -> Dict[str, Any]:
    """在 stage（空目录）里放好改好的 collab/、work/；返回统计。原项目不动。"""
    moves, cards = plan_project(root, lang)
    fix = path_rewriter(cards)
    stats = {"files": 0, "renamed": 0, "events": 0, "objects": 0}
    old_states: Dict[str, Dict[str, Any]] = {}
    for a, b in moves.items():
        src, dst = root / a, stage / b
        dst.parent.mkdir(parents=True, exist_ok=True)
        stats["files"] += 1
        stats["renamed"] += a != b
        if src.suffix == ".jsonl" and b.startswith(f"{P.COLLAB}/{P.INTERNAL_FLOW}/"):
            obj = src.stem
            kind = flow.kind_of(obj)
            lines = [l for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
            rows = [json.loads(l) for l in lines]
            old_states[obj] = {**old_replay(rows), "trajectory": old_trajectory(rows)}
            new = [legacy.event(r, kind, fix) for r in rows]
            stats["events"] += len(new)
            stats["objects"] += 1
            dst.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new), encoding="utf-8")
        elif src.suffix == ".md" and b.startswith(P.COLLAB + "/") and ledger_file(a[len(P.COLLAB) + 1:]):
            dst.write_text(convert_markdown(src.read_text(encoding="utf-8"), lang, fix), encoding="utf-8")
        elif src.suffix == ".json" and b.startswith(f"{P.COLLAB}/{P.INTERNAL}/"):
            dst.write_text(convert_json(b[len(P.COLLAB) + 1:], src.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
    for d in (stage / P.COLLAB / P.INTERNAL_FLOW, stage / P.COLLAB / P.INTERNAL_PLANS, stage / P.COLLAB / P.INTERNAL_RUNS):
        d.mkdir(parents=True, exist_ok=True)
    (stage / P.COLLAB / P.CONFIG).write_text(json.dumps({"format": flow.FORMAT, "lang": lang}) + "\n", encoding="utf-8")
    stats["old_states"] = old_states
    stats["moves"] = moves
    return stats


def verify(stage: Path, old_states: Dict[str, Dict[str, Any]]) -> List[str]:
    """改写后的回放和改写前逐个对象比：状态、持有人、事件条数、seq。"""
    states, evs, probs = flow.replay_all(flow.Project(stage))
    out = [p["msg"] for p in probs]
    for obj, old in sorted(old_states.items()):
        st = states.get(obj)
        if not st:
            out.append(f"{obj}：改写后回放不出来")
            continue
        rows = evs.get(obj, [])
        if (st["state"], st["holder"], len(rows), [r.get("seq") for r in rows]) != (old["state"], old["holder"], old["count"], old["seqs"]):
            out.append(f"{obj}：改写前 {old['state']} / {old['holder']} / {old['count']} 条，改写后 {st['state']} / {st['holder']} / {len(rows)} 条")
            continue
        for k, want in enumerate(old.get("trajectory", []), 1):
            got = flow.replay(obj, rows[:k])
            if (got["state"], got["holder"]) != want:
                out.append(f"{obj} 第 {k} 条事件之后：改写前 {want[0]} / {want[1]}，改写后 {got['state']} / {got['holder']}")
                break
    return out


def stage_check(stage: Path) -> List[str]:
    """改好的项目上跑 flow 渲染和检查（在临时目录里，不受开发版写保护影响）；返回错误。"""
    proj = flow.Project(stage)
    flow.render_all(proj)
    return [f"{x['file']}：{x['msg']}" for x in flow.check(proj, now=None) if x["level"] == "error"]


def git_dirty(root: Path) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def backup(root: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = root / BACKUP / stamp
    n = 1
    while dest.exists():
        n += 1
        dest = root / BACKUP / f"{stamp}-{n}"
    dest.mkdir(parents=True)
    for name in BACKED:
        src = root / name
        if src.is_dir():
            shutil.copytree(src, dest / name, symlinks=True)
        elif src.exists():
            shutil.copy2(src, dest / name)
    (dest / "MANIFEST.json").write_text(json.dumps({"at": stamp, "had": [n for n in BACKED if (root / n).exists()]},
                                                   ensure_ascii=False) + "\n", encoding="utf-8")
    gi = root / ".gitignore"
    line = BACKUP + "/"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if line not in text.splitlines():
        gi.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "# 迁移前的备份（init.sh migrate），不进 git\n" + line + "\n",
                      encoding="utf-8")
    return dest


def latest_backup(root: Path, name: str = BACKUP) -> Optional[Path]:
    d = root / name
    cands = sorted(x for x in d.iterdir() if x.is_dir() and not x.name.endswith(".restored")) if d.is_dir() else []
    return cands[-1] if cands else None


def restore(root: Path, bk: Path) -> List[str]:
    """把备份里的 collab/、work/、AGENTS.md、.claude/、.gitignore 原样放回（项目里这几样先删掉）。"""
    had = json.loads((bk / "MANIFEST.json").read_text(encoding="utf-8"))["had"]
    for name in BACKED:
        cur = root / name
        if cur.is_dir() and not cur.is_symlink():
            shutil.rmtree(cur)
        elif cur.exists() or cur.is_symlink():
            cur.unlink()
        if name in had:
            src = bk / name
            if src.is_dir():
                shutil.copytree(src, cur, symlinks=True)
            else:
                shutil.copy2(src, cur)
    return had


def migrate_project(root: Path, dry_run: bool = False, lang: str = "zh", out=print) -> int:
    root = root.resolve()
    M = i18n.pack(lang if lang in i18n.LANGS else "zh").t  # 提示用目标语言
    if not (root / P.COLLAB).is_dir():
        out(M("migrate.not_project", root=root))
        return 1
    if is_new(root):
        out(M("migrate.already_new", cfg=f"{P.COLLAB}/{P.CONFIG}", fmt=flow.FORMAT, root=root))
        return 0
    if not is_old(root):
        out(M("migrate.not_old", root=root))
        return 1
    if lang not in i18n.LANGS:
        out(M("migrate.bad_lang"))
        return 1
    busy = running_runs(root)
    if busy:
        out(M("migrate.busy", runs=M("migrate.sep_list").join(busy)))
        return 1
    if git_dirty(root):
        out(M("migrate.dirty"))
    with tempfile.TemporaryDirectory(prefix="collab-migrate-") as tmp:
        stage = Path(tmp) / "p"
        stage.mkdir()
        try:
            stats = build_staged(root, stage, "zh")  # 先按中文迁，迁成英文的再用 init.sh lang 的做法换语言
        except (MigrateError, ValueError) as e:
            out(M("migrate.aborted", why=e))
            return 1
        moves = stats["moves"]
        renamed = [(a, b) for a, b in moves.items() if a != b]
        if dry_run:
            out(M("migrate.dry_head", root=root))
            out(M("migrate.dry_counts", files=stats["files"], renamed=len(renamed), events=stats["events"], objects=stats["objects"]))
            dirs = sorted({(a.rsplit('/', 1)[0], b.rsplit('/', 1)[0]) for a, b in renamed if a.rsplit('/', 1)[0] != b.rsplit('/', 1)[0]})
            for a, b in dirs:
                out(M("migrate.dir_line", a=a, b=b))
            for a, b in renamed:
                if a.rsplit("/", 1)[-1] != b.rsplit("/", 1)[-1]:
                    out(M("migrate.file_line", a=a, b=b))
            out(M("migrate.dry_new", cfg=f"{P.COLLAB}/{P.CONFIG}", fmt=flow.FORMAT, lang=lang, backup=BACKUP))
        bad = verify(stage, stats["old_states"])
        if bad:
            out(M("migrate.replay_mismatch"))
            for x in bad[:20]:
                out("  " + x)
            return 1
        errs = stage_check(stage)
        if errs:
            out(M("migrate.check_failed"))
            for x in errs[:20]:
                out("  " + x)
            return 1
        if dry_run:
            out(M("migrate.dry_ok", objects=stats["objects"]))
            return 0
        bk = backup(root)
        try:
            for name in (P.COLLAB, P.WORK):
                if (root / name).exists():
                    shutil.rmtree(root / name)
                if (stage / name).exists():
                    shutil.copytree(stage / name, root / name, symlinks=True)
            if lang != "zh":
                import lang as lang_mod  # noqa: E402  换项目语言（init.sh lang）：模板、协议、PROGRESS、卡片小节标题
                if lang_mod.switch(root, lang, out=lambda *_: None):
                    raise MigrateError(f"switch to {lang}")
            proj = flow.Project(root)
            errs = [x["msg"] for x in flow.check(proj, now=None) if x["level"] == "error"]
            if errs:
                raise MigrateError("；".join(errs[:5]))
        except Exception as e:  # 有错就退回备份
            restore(root, bk)
            out(M("migrate.failed", why=e))
            return 1
    out(M("migrate.done", root=root))
    out(M("migrate.done_counts", files=stats["files"], renamed=len(renamed), events=stats["events"], objects=stats["objects"]))
    out(M("migrate.done_backup", backup=bk.relative_to(root), root=root))
    return 0


def rollback_project(root: Path, out=print, lang: str = "") -> int:
    root = root.resolve()
    M = i18n.pack(lang or i18n.project_lang(root)).t  # 迁移后的项目按它的语言，没有就中文
    bk = latest_backup(root)
    if not bk:
        out(M("migrate.no_backup", dir=BACKUP, root=root))
        return 1
    restore(root, bk)
    shutil.move(str(bk), str(bk.with_name(bk.name + ".restored")))  # 用过的备份留着、改名，下次回退取更早的
    out(M("migrate.restored", backup=bk.relative_to(root), root=root))
    return 0


# ---------- NOW 数据目录 ----------

NOW_FILES = [("安排.md", P.SCHEDULE), ("本月布局.md", P.MONTH), ("已完成.md", P.DONE), ("截止.md", P.DEADLINES), ("口令.md", P.COMMANDS), ("看板.html", "board.html"),
             ("日历/日历.md", "日历/" + Path(P.CALENDAR).name), ("日历", P.CALENDAR_DIR), ("归档", P.ARCHIVE), ("模块", P.NOW_MODULES),
             ("班子/班子.json", P.LEGACY_TEAM_DIR + "/" + P.TEAM_JSON), ("班子/人才.json", P.LEGACY_TEAM_DIR + "/" + P.TALENT_JSON),
             ("班子", P.TEAM_DIR)]
NOW_SKIP = ("系统", NOW_BACKUP)  # 工具包和备份本身不动


def migrate_now(data: Path, dry_run: bool = False, out=print, lang: str = "zh") -> int:
    """NOW 数据文件和班子目录改名，config.json 里写的文件名、Markdown 里提到的文件名一起改。
    先把数据目录里除工具包（系统/）外的全部内容备份到 .now-backup/<时间>/，回退时原样放回。"""
    data = data.resolve()
    M = i18n.pack(lang).t
    todo = [(a, b) for a, b in NOW_FILES if (data / a).exists() and not (data / b).exists()]
    cfg = data / "config.json"
    cfg_text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    new_cfg = cfg_text
    for a, b in (("截止.md", P.DEADLINES), ("日历/日历.md", P.CALENDAR), ("看板.html", "board.html")):
        new_cfg = new_cfg.replace(f'"{a}"', f'"{b}"')
    team_files = [d / f for d in (data / P.TEAM_DIR, data / P.LEGACY_TEAM_DIR) for f in (P.TEAM_JSON, P.TALENT_JSON, P.LEGACY_TEAM_JSON, P.LEGACY_TALENT_JSON)]
    rekey = [f for f in team_files if f.is_file() and team_keys_old(f)]  # 班子配置的中文键
    if not todo and new_cfg == cfg_text and not rekey:
        out(M("migrate.now_same", root=data))
        return 0
    if dry_run:
        out(M("migrate.dry_head", root=data))
        for a, b in todo:
            out(f"  {a} → {b}")
        if new_cfg != cfg_text:
            out(M("migrate.now_cfg"))
        for f in rekey:
            out(M("migrate.now_rekey", file=f.relative_to(data)))
        return 0
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bk = data / NOW_BACKUP / stamp
    bk.mkdir(parents=True)
    had = []
    for x in sorted(data.iterdir()):
        if x.name in NOW_SKIP:
            continue
        (shutil.copytree if x.is_dir() and not x.is_symlink() else shutil.copy2)(x, bk / x.name)
        had.append(x.name)
    (bk / "MANIFEST.json").write_text(json.dumps({"had": had, "renamed": todo}, ensure_ascii=False) + "\n", encoding="utf-8")
    for a, b in todo:
        if (data / a).exists() and not (data / b).exists():
            (data / b).parent.mkdir(parents=True, exist_ok=True)
            (data / a).rename(data / b)
    if new_cfg != cfg_text:
        cfg.write_text(new_cfg, encoding="utf-8")
    for d in (data / P.TEAM_DIR, data / P.LEGACY_TEAM_DIR):  # 班子配置和人才库：键换英文，值不动
        for f in (d / P.TEAM_JSON, d / P.TALENT_JSON):
            if f.is_file() and team_keys_old(f):
                raw = f.read_text(encoding="utf-8")
                f.write_text(json.dumps(team_mod.english(json.loads(raw)), ensure_ascii=False, indent=2 if raw.startswith("{\n  ") else 1) + "\n", encoding="utf-8")
    for f in sorted(data.rglob("*.md")):
        if any(s in f.relative_to(data).parts for s in NOW_SKIP):
            continue
        t = f.read_text(encoding="utf-8")
        n = legacy.paths_in_text(t).replace("日历/calendar.md", P.CALENDAR)
        if n != t:
            f.write_text(n, encoding="utf-8")
    out(M("migrate.now_done", root=data, n=len(todo), backup=bk.relative_to(data)))
    return 0


def team_keys_old(f: Path) -> bool:
    """班子配置、人才库里还有中文键。"""
    try:
        return team_mod.english(json.loads(f.read_text(encoding="utf-8"))) != json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return False


def rollback_now(data: Path, out=print, lang: str = "zh") -> int:
    data = data.resolve()
    M = i18n.pack(lang).t
    bk = latest_backup(data, NOW_BACKUP)
    if not bk:
        out(M("migrate.no_backup", dir=NOW_BACKUP, root=data))
        return 1
    had = json.loads((bk / "MANIFEST.json").read_text(encoding="utf-8"))["had"]
    for x in sorted(data.iterdir()):
        if x.name in NOW_SKIP:
            continue
        shutil.rmtree(x) if x.is_dir() and not x.is_symlink() else x.unlink()
    for name in had:
        (shutil.copytree if (bk / name).is_dir() else shutil.copy2)(bk / name, data / name)
    shutil.move(str(bk), str(bk.with_name(bk.name + ".restored")))
    out(M("migrate.restored", backup=bk.relative_to(data), root=data))
    return 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in ("project", "rollback", "now", "now-rollback"):
        print(__doc__.split("\n\n")[1])
        return 2
    cmd, rest = argv[0], argv[1:]
    dry = "--dry-run" in rest
    lang = rest[rest.index("--lang") + 1] if "--lang" in rest and rest.index("--lang") + 1 < len(rest) else "zh"
    pos = [x for i, x in enumerate(rest) if not x.startswith("--") and (i == 0 or rest[i - 1] != "--lang")]
    target = Path(pos[0] if pos else ".").expanduser()
    if lang not in i18n.LANGS:
        lang = "zh"
    explicit = "--lang" in rest
    if cmd == "project":
        return migrate_project(target, dry, lang)
    if cmd == "rollback":
        return rollback_project(target, lang=lang if explicit else "")
    if cmd == "now":
        return migrate_now(target, dry, lang=lang)
    return rollback_now(target, lang=lang)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
