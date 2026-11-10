#!/usr/bin/env bash
# 批红初始化脚本
# 用法：
#   init.sh new       [目标目录] [-n 项目名] [--no-now]   给项目装上工作台（AGENTS.md + collab/），并在 NOW 任务表加一行（--no-now 不加）
#   init.sh protocol  [目标目录]   用最新工作台更新 collab/协议.md（保留「本项目补充」一节）、各 _模板.md 和 PROGRESS「加载地图」
#   init.sh hook      [目标目录]   给已有项目装 Claude Code Stop hook：每轮结束校验 collab/，有错交回 Claude 修（new 会自动装）
#   init.sh now       [目录，默认 ~/Desktop]   建立 NOW 总看板（NOW.md + NOW/ 数据目录；生成代码在工具包 board/now/）
#   init.sh register  [目标目录] [-n 项目名]   把已有工作台的项目加回 NOW 任务表（状态进行中）；在「已完成」里的移回来
#   init.sh unregister [目标目录] [-m 一句话结果] [--drop]   从 NOW 任务表移到「已完成」（--drop 直接删去）；项目文件和 collab/ 不动
#   init.sh team      [班子目录]   从示例建立你的 班子.json
#   init.sh team-sync [目标目录] [--all] [--force]   按 班子.json 重新生成 collab/成员.md；--all 刷 NOW 任务表里的全部项目
#   init.sh module list | enable <id> | disable <id> | init <id> [--now-dir <NOW 数据目录>]   管理看板模块；enable、disable 会重新合并口令
#   init.sh tidy      [目标目录] [--all]   把旧位置的 collab/流转、流程、运行记录 搬进 collab/内部/；--all 处理 NOW 任务表里的全部项目
#   init.sh rules     [--now-dir <NOW 数据目录>]   把核心和已启用模块的口令合并成 NOW 数据目录下的 口令.md
# 工作台在工具包的 workbench/：协作文件全部在 collab/ 下；项目根目录只放 AGENTS.md，Claude Code 通过 .claude/CLAUDE.md 导入它。
# 班子目录：COLLAB_TEAM；没设时用工具包旁边的 班子/；都没有时 ~/.collab-team。有 班子.json 时，新项目的 成员.md 按它生成。
# 原则：除 protocol 外从不覆盖已有文件；已有 AGENTS.md / CLAUDE.md 只追加入口说明。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # core/：本脚本、team.py、check.py
KIT="$(cd "$SRC/.." && pwd)"                        # 工具包根：开发时是 src/，本机发布后是 NOW/系统/
WB="$KIT/workbench"                    # 装进项目的工作台
NOWCODE="$KIT/board/now"               # NOW 看板代码；sample/ 是 NOW 数据样板
MODE="${1:-}"; shift || true
if [ "$MODE" = module ] || [ "$MODE" = rules ]; then exec python3 "$SRC/modules.py" "$KIT" "$MODE" "$@"; fi
DEST="."; NAME=""; ALL=0; FORCE=""; NO_NOW=0; RESULT=""; DROP=0
while [ $# -gt 0 ]; do
  case "$1" in
    -n) NAME="${2:?-n 需要项目名}"; shift 2 ;;
    -m) RESULT="${2:?-m 需要一句话结果}"; shift 2 ;;
    --drop) DROP=1; shift ;;
    --all) ALL=1; shift ;;
    --force) FORCE="--force"; shift ;;
    --no-now) NO_NOW=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) DEST="$1"; shift ;;
  esac
done

case "$MODE" in new|protocol|hook|now|team|team-sync|register|unregister|tidy) ;; *) sed -n '2,17p' "$0"; exit 1 ;; esac
if [ "$MODE" = now ]; then [ "$DEST" != "." ] || DEST="$HOME/Desktop"; fi
if [ -n "${COLLAB_TEAM:-}" ]; then TEAM_DIR="$COLLAB_TEAM"; elif [ -d "$KIT/../班子" ]; then TEAM_DIR="$(cd "$KIT/../班子" && pwd)"; else TEAM_DIR="$HOME/.collab-team"; fi
TEAM_FILE="$TEAM_DIR/班子.json"
if [ "$MODE" = team ]; then
  [ "$DEST" != "." ] || DEST="$TEAM_DIR"
  python3 "$SRC/team.py" init "$DEST"; exit $?
fi
if [ "$MODE" = team-sync ]; then
  [ -f "$TEAM_FILE" ] || { echo "没有班子配置：${TEAM_FILE}（先运行 init.sh team）"; exit 1; }
  if [ "$ALL" = 1 ]; then
    NOW_FILE="${NOW_PATH:-$HOME/Desktop/NOW.md}"
    rc=0
    while IFS= read -r proj; do
      python3 "$SRC/team.py" render "$TEAM_FILE" "$proj/collab/成员.md" $FORCE || rc=1
    done < <(python3 "$SRC/team.py" projects "$NOW_FILE")
    exit $rc
  fi
  DEST="$(cd "$DEST" && pwd)"
  [ -e "$DEST/collab/PROGRESS.md" ] || { echo "未找到 collab/PROGRESS.md：$DEST"; exit 1; }
  python3 "$SRC/team.py" render "$TEAM_FILE" "$DEST/collab/成员.md" $FORCE; exit $?
fi
if [ "$MODE" = tidy ] && [ "$ALL" = 1 ]; then
  rc=0
  while IFS= read -r proj; do bash "$0" tidy "$proj" || rc=1; done < <(python3 "$SRC/team.py" projects "${NOW_PATH:-$HOME/Desktop/NOW.md}")
  exit $rc
fi
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
[ -n "$NAME" ] || NAME="$(basename "$DEST")"
NOW_FILE="${NOW_PATH:-$HOME/Desktop/NOW.md}"
# PROGRESS.md 在 collab/ 下，NOW 链接相对 collab/ 计算
NOW_REL="$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$NOW_FILE" "$DEST/collab")"
TODAY="$(date +%Y-%m-%d)"

created=(); skipped=(); appended=(); notes=()

# 复制单个文件；.md 做占位符替换
copy_one() {  # $1 源文件  $2 目标文件
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then skipped+=("${dst#$DEST/}"); return; fi
  mkdir -p "$(dirname "$dst")"
  if [ "${src##*.}" = "md" ]; then
    python3 - "$src" "$dst" "$NAME" "$NOW_REL" "$TODAY" <<'PY'
import sys, datetime as dt
src, dst, name, now, today = sys.argv[1:]
wd = "一二三四五六日"
d0 = dt.date.today(); d1 = d0 + dt.timedelta(days=14)
t = open(src, encoding="utf-8").read()
for k, v in {"项目名": name, "NOW路径": now, "日期": today, "今天": d0.strftime("%m-%d"),
             "周几": "周" + wd[d0.weekday()], "示例日期": d1.isoformat(), "示例周几": "周" + wd[d1.weekday()]}.items():
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

# NOW 任务表加一行，链接到本项目 collab/PROGRESS.md；已有链接或找不到 NOW 时跳过；在「已完成」里的移回来
now_row() {
  [ "$NO_NOW" = 0 ] || return 0
  if [ ! -f "$NOW_FILE" ]; then
    notes+=("没找到 NOW：${NOW_FILE}，未加进 NOW 任务表（用 NOW_PATH 指明，或加 --no-now）"); return 0
  fi
  case "$(python3 "$SRC/now_rows.py" register "$NOW_FILE" "$DEST/collab/PROGRESS.md" "$NAME")" in
    added) appended+=("NOW 任务表（${NOW_FILE}；分类、等级待填）") ;;
    restored) appended+=("NOW 任务表（从「已完成」移回，状态进行中；等级待填）") ;;
    exists) skipped+=("NOW 任务表（已有本项目）") ;;
    *) notes+=("$NOW_FILE 里没找到「## 任务」表，未加行") ;;
  esac
}

# .gitignore 加一行 .scratch/（成员工位草稿，不进 git）；已有就跳过
gitignore_add() {
  local g="$DEST/.gitignore"
  if [ -f "$g" ] && grep -qxF '.scratch/' "$g"; then return 0; fi
  if [ -f "$g" ]; then printf '\n# 成员工位：草稿和中间笔记，不进 git\n.scratch/\n' >> "$g"; appended+=(".gitignore（.scratch/）")
  else printf '# 成员工位：草稿和中间笔记，不进 git\n.scratch/\n' > "$g"; created+=(".gitignore（.scratch/）")
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
    added) created+=(".claude/settings.json（Stop hook：每轮结束校验 collab/；PreToolUse：没有执行中的任务不能改文件）") ;;
    updated) appended+=(".claude/settings.json（hook 已更新）") ;;
    exists) skipped+=(".claude/settings.json 的 Stop hook") ;;
    *) notes+=(".claude/settings.json 不是合法 JSON，没装 Stop hook，请手动修好后运行 init.sh hook") ;;
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
    if [ -e "$DEST/collab/PROGRESS.md" ]; then
      echo "已存在 collab/PROGRESS.md，未做任何改动：$DEST"; exit 1
    fi
    copy_tree "$WB"; pointer "$WB"
    if [ -f "$TEAM_FILE" ] && printf '%s\n' "${created[@]}" | grep -qx 'collab/成员.md'; then
      rm "$DEST/collab/成员.md"
      python3 "$SRC/team.py" render "$TEAM_FILE" "$DEST/collab/成员.md" >/dev/null
      kept=(); for c in "${created[@]}"; do [ "$c" = "collab/成员.md" ] || kept+=("$c"); done
      created=("${kept[@]}" "collab/成员.md（按班子 $TEAM_FILE 生成）")
    fi
    hook_install
    gitignore_add
    now_row ;;
  register)
    [ -e "$DEST/collab/PROGRESS.md" ] || { echo "未找到 collab/PROGRESS.md：$DEST（新项目用 init.sh new）"; exit 1; }
    NO_NOW=0; now_row ;;
  unregister)
    [ -f "$NOW_FILE" ] || { echo "没找到 NOW：${NOW_FILE}（用 NOW_PATH 指明）"; exit 1; }
    args=(unregister "$NOW_FILE" "$DEST/collab/PROGRESS.md" --result "$RESULT"); [ "$DROP" = 0 ] || args+=(--drop)
    case "$(python3 "$SRC/now_rows.py" "${args[@]}")" in
      moved) appended+=("NOW/已完成.md（从任务表移来，完成于今天）") ;;
      dropped) notes+=("已从 NOW 任务表删去") ;;
      *) notes+=("NOW 任务表里没有本项目，未改动") ;;
    esac ;;
  tidy)
    [ -e "$DEST/collab/PROGRESS.md" ] || { echo "未找到 collab/PROGRESS.md：$DEST"; exit 1; }
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
    [ -e "$DEST/collab/PROGRESS.md" ] || { echo "未找到 collab/PROGRESS.md：$DEST"; exit 1; }
    hook_install ;;
  protocol)
    [ -e "$DEST/collab/协议.md" ] || { echo "未找到 collab/协议.md：$DEST"; exit 1; }
    [ -d "$DEST/collab/内部/流转" ] || { echo "这是旧结构项目（没有 collab/内部/流转/），新协议按 flow.py 写流转，不适用；本轮不迁移旧项目，未改动：$DEST"; exit 1; }
    # 用新模板覆盖，但保留项目自己的「本项目补充」一节（旧协议没有这一节时用模板里的空节）
    python3 - "$WB/collab" "$DEST/collab" <<'PY'
import re, sys
from pathlib import Path
wb, col = Path(sys.argv[1]), Path(sys.argv[2])
src, dst = wb / "协议.md", col / "协议.md"
new, old = src.read_text(encoding="utf-8"), dst.read_text(encoding="utf-8")
pat = re.compile(r"(?ms)^## (?:\d+\. )?本项目补充\s*\n.*\Z")
m = pat.search(old)
if m:
    body = m.group(0).split("\n", 1)[1]
    new = pat.sub(lambda n: n.group(0).split("\n", 1)[0] + "\n" + body, new)
dst.write_text(new, encoding="utf-8")
# 参考模板整份换新（工具不读，只给人看）
for tpl in sorted(wb.glob("*/_模板.md")):
    out = col / tpl.relative_to(wb)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(tpl.read_bytes())
# PROGRESS 只换「加载地图」这个模板固定块，其余内容不动
block = re.compile(r"(?ms)^## 加载地图[ \t]*\n.*?(?=^## |\Z)")
prog = col / "PROGRESS.md"
fresh = block.search((wb / "PROGRESS.md").read_text(encoding="utf-8"))
text = prog.read_text(encoding="utf-8") if prog.exists() else ""
if fresh and block.search(text):
    prog.write_text(block.sub(lambda _: fresh.group(0), text, count=1), encoding="utf-8")
PY
    created+=("collab/协议.md（已更新，保留「本项目补充」）、_模板.md、PROGRESS「加载地图」") ;;
  now)
    copy_tree "$NOWCODE/sample"
    # 默认启用的模块（安排、截止）各自的样例数据放进 NOW/
    for _m in schedule deadlines; do
      [ -d "$KIT/modules/$_m/sample" ] || continue  # 只发布核心时没有模块
      while IFS= read -r -d '' f; do copy_one "$f" "$DEST/NOW/${f#$KIT/modules/$_m/sample/}"; done \
        < <(find "$KIT/modules/$_m/sample" -type f -print0 | sort -z)
    done
    python3 - "$DEST/NOW.md" "$NOWCODE/build.py" "$DEST/NOW" <<'PY'
import os, sys
p, build, data = sys.argv[1:]
home = os.path.expanduser("~")
short = lambda x: "~" + x[len(home):] if x.startswith(home + "/") else x
t = open(p, encoding="utf-8").read()
cmd = "python3 %s --now-dir %s" % (short(build), short(data))
open(p, "w", encoding="utf-8").write(t.replace("`python3 NOW/build.py`", "`%s`" % cmd))
PY
    python3 "$NOWCODE/build.py" --now-dir "$DEST/NOW" >/dev/null && created+=("NOW/看板.html（已生成）")
    python3 "$SRC/modules.py" "$KIT" rules --now-dir "$DEST/NOW" >/dev/null && created+=("NOW/口令.md（已合并）") ;;
esac

echo "目标：${DEST}（${MODE}）"
[ ${#created[@]}  -eq 0 ] || printf '  新建  %s\n' "${created[@]}"
[ ${#appended[@]} -eq 0 ] || printf '  追加  %s\n' "${appended[@]}"
[ ${#skipped[@]}  -eq 0 ] || printf '  跳过（已存在）  %s\n' "${skipped[@]}"
[ ${#notes[@]}    -eq 0 ] || printf '  注意  %s\n' "${notes[@]}"

if [ "$MODE" = now ]; then cat <<MSG

下一步：
  1. 改 NOW/config.json 里的分类（和 NOW.md 大方向的方向名对应）与截止来源
  2. 启动看板服务看效果：python3 $KIT/board/server.py --now-dir $DEST/NOW，打开 http://127.0.0.1:3100（开机常驻见 board/README.md）
  3. 之后建项目用 NOW_PATH=$DEST/NOW.md $SRC/init.sh new，项目会自动加进 NOW 任务表
MSG
fi
