#!/usr/bin/env bash
# 批红初始化脚本
# 用法：
#   init.sh new       [目标目录] [-n 项目名] [--no-now] [--lang zh|en]   给项目装上工作台（AGENTS.md + collab/），登记到看板，打印看板网址；启用了 NOW 时再在 NOW 任务表加一行（--no-now 不加）
#   init.sh lang      zh|en [目标目录]   换项目语言：规则文档和模板换成该语言，卡片小节标题和字段名按代码改写，config.json 改 lang，再 flow render；正文不动
#   init.sh protocol  [目标目录]   用最新工作台更新 collab/protocol.md（保留「本项目补充」一节）、各 _template.md 和 PROGRESS「加载地图」
#   init.sh hook      [目标目录]   给已有项目装 Claude Code Stop hook：每轮结束校验 collab/，有错交回 Claude 修（new 会自动装）
#   init.sh open      [目标目录] [--print]   看板在运行就在浏览器打开本项目（--print 只打印网址）；没运行时提示怎么启动
#   init.sh now       <目录>   建立 NOW 总看板（可选：汇总多个项目、加日程等个人模块；NOW.md + NOW/ 数据目录；生成代码在工具包 board/now/）
#   init.sh register  [目标目录] [-n 项目名]   把已有工作台的项目登记到看板；启用了 NOW 时加回 NOW 任务表（状态进行中），在「已完成」里的移回来
#   init.sh unregister [目标目录] [-m 一句话结果] [--drop]   从看板登记表移除；启用了 NOW 时从任务表移到「已完成」（--drop 直接删去）；项目文件和 collab/ 不动
#   init.sh team      [班子目录]   从示例建立你的 team.json
#   init.sh team-sync [目标目录] [--all] [--force]   按 team.json 重新生成 collab/members.md；--all 刷登记表和 NOW 任务表里的全部项目
#   init.sh module list | enable <id> | disable <id> | init <id> [--now-dir <NOW 数据目录>]   管理看板模块；enable、disable 会重新合并口令
#   init.sh tidy      [目标目录] [--all]   把旧位置的 collab/流转、流程、运行记录 搬进 collab/内部/（之后再运行 init.sh migrate）；--all 处理登记表和 NOW 任务表里的全部项目
#   init.sh rules     [--now-dir <NOW 数据目录>]   把核心和已启用模块的口令合并成 NOW 数据目录下的 commands.md
#   init.sh migrate   [目标目录] [--dry-run] [--lang zh|en]   旧格式账本（中文目录、事件 v1）迁成格式 3；先备份到 .collab-backup/<时间>/，可重复运行
#   init.sh migrate --rollback [目标目录]   用最近一次备份恢复
#   init.sh migrate-now [NOW 数据目录] [--dry-run] [--rollback]   NOW 数据文件和班子目录改英文名（安排.md → schedule.md、班子/ → team/…）
# 工作台在工具包的 workbench/<语言>/（zh、en 两套，文件名相同）：协作文件全部在 collab/ 下；项目根目录只放 AGENTS.md，Claude Code 通过 .claude/CLAUDE.md 导入它。
# 看板登记表：工具包旁边的 projects.json（COLLAB_PROJECTS 可另指；开发版工具包不登记），只记项目目录和名字。
# NOW（可选）：NOW_PATH 指的 NOW.md；没设时找工具包旁边的 NOW（有 config.json）和本工具包装的看板常驻配置；都没有就是没启用 NOW。
# 班子目录：COLLAB_TEAM；没设时用工具包旁边的 team/（旧名 班子/）；都没有时 ~/.collab-team。有 team.json 时，新项目的 members.md 按它生成。
# 原则：除 protocol 外从不覆盖已有文件；已有 AGENTS.md / CLAUDE.md 只追加入口说明。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # core/：本脚本、team.py、check.py
KIT="$(cd "$SRC/.." && pwd)"                        # 工具包根：开发时是 src/，本机发布后是 NOW/系统/
NOWCODE="$KIT/board/now"               # NOW 看板代码；sample/ 是 NOW 数据样板
eval "$(python3 "$SRC/paths.py" sh)"    # 文件和目录名：P_COLLAB、P_PROGRESS…（core/paths.py）
MODE="${1:-}"; shift || true
NO_MODE=0; case "$MODE" in ""|-h|--help) NO_MODE=1 ;; esac  # 没写命令：用法按工具包默认语言，不跟当前目录的项目
if [ "$MODE" = module ] || [ "$MODE" = rules ]; then exec python3 "$SRC/modules.py" "$KIT" "$MODE" "$@"; fi
if [ "$MODE" = lang ]; then exec python3 "$SRC/lang.py" "$@"; fi  # 换项目语言
if [ "$MODE" = migrate ] || [ "$MODE" = migrate-now ]; then  # 迁移由 migrate.py 做：前检、备份、改写、回放核对、检查、失败回退
  _cmd=project; [ "$MODE" = migrate-now ] && _cmd=now; _args=()
  for _a in "$@"; do if [ "$_a" = --rollback ]; then _cmd="${_cmd/project/rollback}"; _cmd="${_cmd/now/now-rollback}"; else _args+=("$_a"); fi; done
  exec python3 "$SRC/migrate.py" "$_cmd" ${_args[@]+"${_args[@]}"}
fi
DEST="."; DEST_SET=0; NAME=""; ALL=0; FORCE=""; NO_NOW=0; RESULT=""; DROP=0; PRINT=""; LANG_SET=""; HELP=0
while [ $# -gt 0 ]; do
  case "$1" in
    -n) NAME="${2:?-n needs a project name}"; shift 2 ;;
    -m) RESULT="${2:?-m needs a one-line result}"; shift 2 ;;
    --drop) DROP=1; shift ;;
    --all) ALL=1; shift ;;
    --force) FORCE="--force"; shift ;;
    --no-now) NO_NOW=1; shift ;;
    --print) PRINT="--print"; shift ;;
    --lang) LANG_SET="${2:?--lang needs zh or en}"; shift 2 ;;
    -h|--help) HELP=1; shift ;;
    *) DEST="$1"; DEST_SET=1; shift ;;
  esac
done

# 语言：new 用 --lang，再 COLLAB_LANG、NOW config.json 的 lang，都没有用 en；其他命令跟着项目 collab/config.json
KIT_LANG="$(python3 "$SRC/registry.py" lang "$KIT")"
if [ "$MODE" = new ] || [ "$MODE" = now ] || [ "$MODE" = team ]; then LANG_USE="${LANG_SET:-$KIT_LANG}"
elif [ "$NO_MODE" = 0 ] && [ -e "$DEST/${P_COLLAB}/${P_CONFIG}" ]; then LANG_USE="$(python3 "$SRC/i18n.py" lang "$DEST")"
else LANG_USE="${LANG_SET:-$KIT_LANG}"; fi
case "$LANG_USE" in zh|en) ;; *) echo "--lang: zh | en"; exit 1 ;; esac
t() { python3 "$SRC/i18n.py" t "$LANG_USE" "$@"; }  # 一句提示（语言包 init.*）
usage() { if [ "$LANG_USE" = zh ]; then sed -n '2,25p' "$0"; else t init.usage; fi; }
WB="$KIT/workbench/$LANG_USE"          # 装进项目的工作台（按语言）
if [ "$HELP" = 1 ]; then usage; exit 0; fi

case "$MODE" in new|open|protocol|hook|now|team|team-sync|register|unregister|tidy) ;; *) usage; exit 1 ;; esac
if [ "$MODE" = now ] && [ "$DEST_SET" = 0 ]; then t init.now_needs_dir; exit 1; fi
NOW_FILE="$(python3 "$SRC/registry.py" now-md "$KIT")"  # 空 = 没启用 NOW
if [ "$MODE" = open ]; then
  DEST="$(cd "$DEST" && pwd)"
  [ -e "$DEST/${P_COLLAB}/${P_PROGRESS}" ] || { t init.no_progress_new dest="$DEST"; exit 1; }
  exec python3 "$SRC/registry.py" open "$KIT" "$DEST" $PRINT
fi
if [ -n "${COLLAB_TEAM:-}" ]; then TEAM_DIR="$COLLAB_TEAM"; elif [ -d "$KIT/../${P_TEAM_DIR}" ]; then TEAM_DIR="$(cd "$KIT/../${P_TEAM_DIR}" && pwd)"; elif [ -d "$KIT/../${P_LEGACY_TEAM_DIR}" ]; then TEAM_DIR="$(cd "$KIT/../${P_LEGACY_TEAM_DIR}" && pwd)"; else TEAM_DIR="$HOME/.collab-team"; fi
TEAM_FILE="$TEAM_DIR/${P_TEAM_JSON}"; [ -f "$TEAM_FILE" ] || [ ! -f "$TEAM_DIR/${P_LEGACY_TEAM_JSON}" ] || TEAM_FILE="$TEAM_DIR/${P_LEGACY_TEAM_JSON}"  # 没迁移的班子目录还叫 班子.json
if [ "$MODE" = team ]; then
  [ "$DEST" != "." ] || DEST="$TEAM_DIR"
  python3 "$SRC/team.py" init "$DEST" --lang "$LANG_USE"; exit $?
fi
if [ "$MODE" = team-sync ]; then
  [ -f "$TEAM_FILE" ] || { t init.no_team path="$TEAM_FILE"; exit 1; }
  if [ "$ALL" = 1 ]; then
    rc=0
    while IFS= read -r proj; do
      python3 "$SRC/team.py" render "$TEAM_FILE" "$proj/${P_COLLAB}/${P_MEMBERS}" $FORCE || rc=1
    done < <(python3 "$SRC/registry.py" roots "$KIT")
    exit $rc
  fi
  DEST="$(cd "$DEST" && pwd)"
  [ -e "$DEST/${P_COLLAB}/${P_PROGRESS}" ] || { t init.no_progress dest="$DEST"; exit 1; }
  python3 "$SRC/team.py" render "$TEAM_FILE" "$DEST/${P_COLLAB}/${P_MEMBERS}" $FORCE; exit $?
fi
if [ "$MODE" = tidy ] && [ "$ALL" = 1 ]; then
  rc=0
  while IFS= read -r proj; do bash "$0" tidy "$proj" || rc=1; done < <(python3 "$SRC/registry.py" roots "$KIT")
  exit $rc
fi
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
[ -n "$NAME" ] || NAME="$(basename "$DEST")"
# PROGRESS.md 在 collab/ 下，NOW 链接相对 collab/ 计算；没启用 NOW 时 PROGRESS 不放「← NOW」这一行
NOW_REL=""
[ -z "$NOW_FILE" ] || NOW_REL="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$NOW_FILE" "$DEST/${P_COLLAB}")"
TODAY="$(date +%Y-%m-%d)"

created=(); skipped=(); appended=(); notes=()

# 复制单个文件；.md 做占位符替换
copy_one() {  # $1 源文件  $2 目标文件
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then skipped+=("${dst#$DEST/}"); return; fi
  mkdir -p "$(dirname "$dst")"
  if [ "${src##*.}" = "md" ]; then
    python3 - "$src" "$dst" "$NAME" "$NOW_REL" "$TODAY" <<'PY'
import re, sys, datetime as dt
src, dst, name, now, today = sys.argv[1:]
wd, wd_en = "一二三四五六日", ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
d0 = dt.date.today(); d1 = d0 + dt.timedelta(days=14)
t = open(src, encoding="utf-8").read()
if not now:
    t = re.sub(r"(?m)^\[← NOW\]\(\{\{(?:NOW路径|now_path)\}\}\)\n\n?", "", t)
for k, v in {"项目名": name, "NOW路径": now, "日期": today, "今天": d0.strftime("%m-%d"),
             "周几": "周" + wd[d0.weekday()], "示例日期": d1.isoformat(), "示例周几": "周" + wd[d1.weekday()],
             "project": name, "now_path": now, "date": today, "today": d0.strftime("%m-%d"),
             "weekday": wd_en[d0.weekday()], "sample_date": d1.isoformat(), "sample_weekday": wd_en[d1.weekday()]}.items():
    t = t.replace("{{" + k + "}}", v)
open(dst, "w", encoding="utf-8").write(t)
PY
  else
    cp "$src" "$dst"
  fi
  created+=("${dst#$DEST/}")
}

# 复制整个目录（跳过入口说明文件，由 pointer 单独处理）
copy_tree() {  # $1 源目录  $2 只复制该子路径（可空）
  local base="$1" sub="${2:-}"
  while IFS= read -r -d '' f; do
    local rel="${f#$base/}"
    case "$rel" in AGENTS.md|.claude/CLAUDE.md) continue ;; esac
    copy_one "$f" "$DEST/$rel"
  done < <(find "$base/$sub" -type f -print0 | sort -z)
}

# 看板登记表加上本项目；开发版工具包没有登记表时只提示
REGISTERED=0; IN_NOW=0
reg_add() {
  case "$(python3 "$SRC/registry.py" add "$KIT" "$DEST" "$NAME")" in
    added) REGISTERED=1; appended+=("$(t init.reg_added path="$(dirname "$KIT")/projects.json")") ;;
    exists) REGISTERED=1; skipped+=("$(t init.reg_exists)") ;;
    *) notes+=("$(t init.reg_dev)") ;;
  esac
}

# NOW 任务表加一行，链接到本项目 collab/PROGRESS.md；已有链接或没启用 NOW 时跳过；在「已完成」里的移回来
now_row() {
  [ "$NO_NOW" = 0 ] || return 0
  if [ -z "$NOW_FILE" ]; then
    [ "$REGISTERED" = 0 ] || notes+=("$(t init.now_off)"); return 0
  fi
  if [ ! -f "$NOW_FILE" ]; then
    notes+=("$(t init.now_missing path="$NOW_FILE")"); return 0
  fi
  case "$(python3 "$SRC/now_rows.py" register "$NOW_FILE" "$DEST/${P_COLLAB}/${P_PROGRESS}" "$NAME")" in
    added) IN_NOW=1; appended+=("$(t init.now_added path="$NOW_FILE")") ;;
    restored) IN_NOW=1; appended+=("$(t init.now_restored)") ;;
    exists) IN_NOW=1; skipped+=("$(t init.now_exists)") ;;
    *) notes+=("$(t init.now_no_table path="$NOW_FILE")") ;;
  esac
}

# .gitignore 加一行 .scratch/（成员工位草稿，不进 git）；已有就跳过
gitignore_add() {
  local g="$DEST/.gitignore"
  if [ -f "$g" ] && grep -qxF '.scratch/' "$g"; then return 0; fi
  local c; c="$(t init.gitignore_comment)"
  if [ -f "$g" ]; then printf '\n# %s\n.scratch/\n' "$c" >> "$g"; appended+=("$(t init.gitignore)")
  else printf '# %s\n.scratch/\n' "$c" > "$g"; created+=("$(t init.gitignore)")
  fi
}

# .claude/settings.json 里加 Stop hook：每轮结束运行 core/check.py --hook；已有同一条时不重复加
CHECK_PY="$KIT/core/check.py"
hook_install() {
  local r
  r="$(python3 - "$DEST/.claude/settings.json" "$CHECK_PY" <<'PY'
import json, os, sys
path, check = sys.argv[1:]
cmd = "python3 '%s' --hook" % check
cfg = {}
if os.path.exists(path):
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except ValueError:
        print("bad"); sys.exit()
def add_pretool():
    """PreToolUse：总管没有执行中的任务就不能改项目文件；已有同一条时只更新路径。"""
    pre_cmd = "python3 '%s' --pretool" % check
    pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
    found = False
    for grp in pre:
        for h in grp.get("hooks", []):
            if "check.py" in h.get("command", "") and "--pretool" in h.get("command", ""):
                h["command"] = pre_cmd
                found = True
    if not found:
        pre.append({"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [{"type": "command", "command": pre_cmd, "timeout": 15}]})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
stop = cfg.setdefault("hooks", {}).setdefault("Stop", [])
for grp in stop:
    for h in grp.get("hooks", []):
        if "check.py" in h.get("command", "") and "--hook" in h.get("command", ""):
            same = h["command"] == cmd
            h["command"] = cmd
            had = any("--pretool" in x.get("command", "") for g in cfg["hooks"].get("PreToolUse", []) for x in g.get("hooks", []))
            add_pretool()
            print("exists" if same and had else "updated"); sys.exit()
stop.append({"hooks": [{"type": "command", "command": cmd, "timeout": 30}]})
add_pretool()
print("added")
PY
)"
  case "$r" in
    added) created+=("$(t init.hook_added)") ;;
    updated) appended+=("$(t init.hook_updated)") ;;
    exists) skipped+=("$(t init.hook_exists)") ;;
    *) notes+=("$(t init.hook_bad)") ;;
  esac
}

# AGENTS.md：不存在则创建，存在则追加。
# Claude Code：根目录已有 CLAUDE.md 就在其中导入 @AGENTS.md，否则用 .claude/CLAUDE.md，保持根目录干净。
pointer() {  # $1 工作台目录
  local a="$DEST/AGENTS.md" c="$DEST/CLAUDE.md" hc="$DEST/.claude/CLAUDE.md"
  if [ ! -e "$a" ]; then cp "$1/AGENTS.md" "$a"; created+=("AGENTS.md")
  elif ! grep -q 'collab-templates:pointer' "$a"; then printf '\n' >> "$a"; cat "$1/AGENTS.md" >> "$a"; appended+=("AGENTS.md")
  fi
  if [ -e "$c" ]; then
    grep -qx '@AGENTS.md' "$c" || { printf '\n@AGENTS.md\n' >> "$c"; appended+=("CLAUDE.md"); }
  elif [ ! -e "$hc" ]; then mkdir -p "$DEST/.claude"; cp "$1/.claude/CLAUDE.md" "$hc"; created+=(".claude/CLAUDE.md")
  elif ! grep -qx '@../AGENTS.md' "$hc"; then printf '\n@../AGENTS.md\n' >> "$hc"; appended+=(".claude/CLAUDE.md")
  fi
}

case "$MODE" in
  new)
    if [ -e "$DEST/${P_COLLAB}/${P_PROGRESS}" ]; then
      t init.exists dest="$DEST"; exit 1
    fi
    copy_tree "$WB"; pointer "$WB"
    printf '{"format": 3, "lang": "%s"}\n' "$LANG_USE" > "$DEST/${P_COLLAB}/${P_CONFIG}"  # 账本格式版本和项目语言
    if [ -f "$TEAM_FILE" ] && printf '%s\n' "${created[@]}" | grep -qx "${P_COLLAB}/${P_MEMBERS}"; then
      rm "$DEST/${P_COLLAB}/${P_MEMBERS}"
      python3 "$SRC/team.py" render "$TEAM_FILE" "$DEST/${P_COLLAB}/${P_MEMBERS}" >/dev/null
      kept=(); for c in "${created[@]}"; do [ "$c" = "${P_COLLAB}/${P_MEMBERS}" ] || kept+=("$c"); done
      created=("${kept[@]}" "$(t init.members_from_team path="${P_COLLAB}/${P_MEMBERS}" team="$TEAM_FILE")")
    fi
    hook_install
    gitignore_add
    reg_add
    now_row ;;
  register)
    [ -e "$DEST/${P_COLLAB}/${P_PROGRESS}" ] || { t init.no_progress_register dest="$DEST"; exit 1; }
    reg_add
    NO_NOW=0; now_row ;;
  unregister)
    case "$(python3 "$SRC/registry.py" remove "$KIT" "$DEST")" in
      removed) notes+=("$(t init.unreg_removed)") ;;
      missing) notes+=("$(t init.unreg_missing)") ;;
    esac
    if [ -n "$NOW_FILE" ] && [ -f "$NOW_FILE" ]; then
      args=(unregister "$NOW_FILE" "$DEST/${P_COLLAB}/${P_PROGRESS}" --result "$RESULT"); [ "$DROP" = 0 ] || args+=(--drop)
      case "$(python3 "$SRC/now_rows.py" "${args[@]}")" in
        moved) appended+=("$(t init.now_moved)") ;;
        dropped) notes+=("$(t init.now_dropped)") ;;
        *) notes+=("$(t init.now_not_listed)") ;;
      esac
    elif [ -n "$NOW_FILE" ]; then notes+=("$(t init.now_missing_unchanged path="$NOW_FILE")")
    fi ;;
  tidy)
    [ -e "$DEST/${P_COLLAB}/${P_PROGRESS}" ] || { t init.no_progress dest="$DEST"; exit 1; }
    for _d in 流转 流程 运行记录; do
      _old="$DEST/collab/$_d"; _new="$DEST/collab/内部/$_d"
      [ -d "$_old" ] || continue
      if [ -d "$_new" ] && [ -n "$(find "$_new" -mindepth 1 -not -name .gitkeep -not -name .lock -print -quit)" ]; then
        notes+=("collab/$_d 和 collab/内部/$_d 都有内容，没动，请手动合并"); continue
      fi
      mkdir -p "$DEST/collab/内部"; rm -rf "$_new"; mv "$_old" "$_new"
      appended+=("collab/内部/$_d（从 collab/$_d 搬来）")
    done ;;
  hook)
    [ -e "$DEST/${P_COLLAB}/${P_PROGRESS}" ] || { t init.no_progress dest="$DEST"; exit 1; }
    hook_install ;;
  protocol)
    [ -e "$DEST/${P_COLLAB}/${P_PROTOCOL}" ] || { t init.no_protocol path="${P_COLLAB}/${P_PROTOCOL}" dest="$DEST"; exit 1; }
    [ -d "$DEST/${P_COLLAB}/${P_INTERNAL_FLOW}" ] || { t init.old_structure dest="$DEST"; exit 1; }
    # 用新模板覆盖，但保留项目自己的「本项目补充」一节（旧协议没有这一节时用模板里的空节）
    python3 - "$WB/${P_COLLAB}" "$DEST/${P_COLLAB}" "$SRC" <<'PY'
import re, sys
from pathlib import Path
wb, col = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, sys.argv[3])
import paths as P
from vocab import Section
src, dst = wb / P.PROTOCOL, col / P.PROTOCOL
new, old = src.read_text(encoding="utf-8"), dst.read_text(encoding="utf-8")
pat = re.compile(r"(?ms)^## (?:\d+\. )?(?:本项目补充|Project notes)\s*\n.*\Z")
m = pat.search(old)
if m:
    body = m.group(0).split("\n", 1)[1]
    new = pat.sub(lambda n: n.group(0).split("\n", 1)[0] + "\n" + body, new)
dst.write_text(new, encoding="utf-8")
# 参考模板整份换新（工具不读，只给人看）
for tpl in sorted(wb.glob("*/" + P.TEMPLATE)):
    out = col / tpl.relative_to(wb)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(tpl.read_bytes())
# PROGRESS 只换「加载地图」这个模板固定块，其余内容不动
from i18n import headings
block = re.compile(r"(?ms)^## (?:" + "|".join(re.escape(h) for h in headings(Section.LOADING_MAP)) + r")[ \t]*\n.*?(?=^## |\Z)")
prog = col / P.PROGRESS
fresh = block.search((wb / P.PROGRESS).read_text(encoding="utf-8"))
text = prog.read_text(encoding="utf-8") if prog.exists() else ""
if fresh and block.search(text):
    prog.write_text(block.sub(lambda _: fresh.group(0), text, count=1), encoding="utf-8")
PY
    created+=("$(t init.protocol_updated protocol="${P_COLLAB}/${P_PROTOCOL}" template="${P_TEMPLATE}")") ;;
  now)
    copy_tree "$NOWCODE/sample"
    # 默认启用的模块（安排、截止）各自的样例数据放进 NOW/
    for _m in schedule deadlines; do
      [ -d "$KIT/modules/$_m/sample" ] || continue  # 只发布核心时没有模块
      while IFS= read -r -d '' f; do copy_one "$f" "$DEST/NOW/${f#$KIT/modules/$_m/sample/}"; done \
        < <(find "$KIT/modules/$_m/sample" -type f -print0 | sort -z)
    done
    python3 - "$DEST/NOW.md" "$NOWCODE/build.py" "$DEST/NOW" "$LANG_USE" <<'PY'
import json, os, sys
p, build, data, lang = sys.argv[1:]
cf = os.path.join(data, "config.json")  # NOW 的语言：口令、看板默认用它，新项目也默认用它
if os.path.exists(cf):
    raw = open(cf, encoding="utf-8").read()
    if "lang" not in json.loads(raw) and raw.startswith("{\n"):
        open(cf, "w", encoding="utf-8").write('{\n  "lang": "%s",\n' % lang + raw[2:])
home = os.path.expanduser("~")
short = lambda x: "~" + x[len(home):] if x.startswith(home + "/") else x
t = open(p, encoding="utf-8").read()
cmd = "python3 %s --now-dir %s" % (short(build), short(data))
open(p, "w", encoding="utf-8").write(t.replace("`python3 NOW/build.py`", "`%s`" % cmd))
PY
    python3 "$NOWCODE/build.py" --now-dir "$DEST/NOW" >/dev/null && created+=("$(t init.now_board)")
    python3 "$SRC/modules.py" "$KIT" rules --now-dir "$DEST/NOW" >/dev/null && created+=("$(t init.now_rules)") ;;
esac

t init.target dest="$DEST" mode="$MODE"
L_NEW="$(t init.created)"; L_APP="$(t init.appended)"; L_SKIP="$(t init.skipped)"; L_NOTE="$(t init.notes)"
[ ${#created[@]}  -eq 0 ] || printf "  $L_NEW  %s\n" "${created[@]}"
[ ${#appended[@]} -eq 0 ] || printf "  $L_APP  %s\n" "${appended[@]}"
[ ${#skipped[@]}  -eq 0 ] || printf "  $L_SKIP  %s\n" "${skipped[@]}"
[ ${#notes[@]}    -eq 0 ] || printf "  $L_NOTE  %s\n" "${notes[@]}"

if [ "$MODE" = new ] || [ "$MODE" = register ]; then
  if [ "$REGISTERED" = 1 ] || [ "$IN_NOW" = 1 ]; then
    t init.board_url url="$(python3 "$SRC/registry.py" url "$KIT" "$DEST")" kit="$KIT" src="$SRC" dest="$DEST"
  fi
fi

if [ "$MODE" = now ]; then echo; t init.now_next kit="$KIT" dest="$DEST" src="$SRC"; fi
