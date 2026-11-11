#!/usr/bin/env bash
# 把开发仓库里已提交的 src/ 发布成本机自用的独立拷贝（不带 git，删掉开发仓库也能照常运行）
# 用法：
#   publish.sh [目标目录]        不写时依次取环境变量 COLLAB_SYSTEM、开发仓库根目录 .publish-target 文件（一行路径，不进 git）
#   publish.sh --dirty [目标]    src/ 有未提交改动时也发布（只用于临时试验，版本号标「含未提交改动」）
#   publish.sh --core <目标>     只带核心、不带模块；必须写目标，避免把本机自用的拷贝换成只有核心的
#   publish.sh --module <id> <目标>   只导出一个模块到 <目标>/<id>/（附 版本.txt），拷进 NOW/模块/ 后 init.sh module enable <id>
# 做什么：
#   1. 用 git archive 导出当前提交的 src/，写 版本.txt（提交号、分支、时间）
#   2. 原来的拷贝改名为「<目标>.上一版」，回退就把它改回来
#   3. 看板常驻已指向目标目录就重启；还没指向时提示运行 board/service.sh install
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$(python3 "$KIT/core/paths.py" sh)"  # 文件名：P_VERSION_TXT…（core/paths.py）
REPO="$(git -C "$KIT" rev-parse --show-toplevel 2>/dev/null)" || { echo "错误：$KIT 不在 git 仓库里，只能从开发仓库发布" >&2; exit 1; }
DIRTY=0; CORE=0; MODULE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dirty) DIRTY=1; shift ;;
    --core) CORE=1; shift ;;
    --module) MODULE="${2:?--module 需要模块 id}"; shift 2 ;;
    *) break ;;
  esac
done
if [ "$CORE" = 1 ] || [ -n "$MODULE" ]; then
  [ $# -ge 1 ] || { echo "错误：--core、--module 必须写目标目录" >&2; exit 1; }
  [ -z "$MODULE" ] || [ "$CORE" = 0 ] || { echo "错误：--core 和 --module 不能同时用" >&2; exit 1; }
fi
DEST="${1:-${COLLAB_SYSTEM:-}}"
if [ -z "$DEST" ] && [ -f "$REPO/.publish-target" ]; then
  DEST="$(head -n 1 "$REPO/.publish-target")"
  DEST="${DEST/#\~/$HOME}"
fi
[ -n "$DEST" ] || { echo "错误：没给目标目录。写参数、设 COLLAB_SYSTEM，或在 $REPO/.publish-target 写一行路径" >&2; exit 1; }
DEST="${DEST%/}"

if [ -n "$(git -C "$REPO" status --porcelain -- src)" ]; then
  [ "$DIRTY" = 1 ] || { echo "错误：src/ 有未提交的改动，先提交；临时试验加 --dirty" >&2; exit 1; }
fi

mkdir -p "$(dirname "$DEST")"
if [ -n "$MODULE" ]; then
  mkdir -p "$DEST"
  DEST="$DEST/$MODULE"
  [ ! -e "$DEST" ] || { echo "错误：$DEST 已存在，先删掉" >&2; exit 1; }
  [ -f "$KIT/modules/$MODULE/module.json" ] || { echo "错误：没有模块 $MODULE" >&2; exit 1; }
fi
TMP="$(mktemp -d "${DEST}.发布中.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
if [ "$DIRTY" = 1 ]; then
  (cd "$KIT" && tar -cf - --exclude build --exclude __pycache__ --exclude .DS_Store .) | tar -xf - -C "$TMP"
else
  git -C "$REPO" archive --format=tar HEAD:src | tar -xf - -C "$TMP"
fi
if [ -n "$MODULE" ]; then
  [ -d "$TMP/modules/$MODULE" ] || { echo "错误：当前提交里没有模块 $MODULE，先提交" >&2; exit 1; }
  mv "$TMP/modules/$MODULE" "$TMP.模块"
  rm -rf "$TMP"
  mv "$TMP.模块" "$TMP"
elif [ "$CORE" = 1 ]; then
  find "$TMP/modules" -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} +  # 只留约定说明 modules/README.md
fi
{
  echo "提交：$(git -C "$REPO" rev-parse --short HEAD)$([ "$DIRTY" = 1 ] && echo "（含未提交改动）")"
  echo "分支：$(git -C "$REPO" branch --show-current)"
  echo "说明：$(git -C "$REPO" log -1 --format=%s)"
  echo "发布：$(date '+%Y-%m-%d %H:%M')"
  echo "来源：$REPO/src$([ -n "$MODULE" ] && echo "/modules/$MODULE")$([ "$CORE" = 1 ] && echo "（只有核心）")"
} > "$TMP/${P_VERSION_TXT}"

if [ -n "$MODULE" ]; then
  mv "$TMP" "$DEST"
  trap - EXIT
  echo "已导出模块到 $DEST"
  sed 's/^/  /' "$DEST/${P_VERSION_TXT}"
  exit 0
fi

PREV="${DEST}.上一版"
if [ -d "$DEST" ]; then
  rm -rf "$PREV"
  mv "$DEST" "$PREV"
fi
mv "$TMP" "$DEST"
trap - EXIT
echo "已发布到 $DEST"
sed 's/^/  /' "$DEST/${P_VERSION_TXT}"
[ -d "$PREV" ] && echo "上一版：$PREV（回退：删掉 $DEST，把上一版改回原名）"

CONF="$HOME/Library/Application Support/ai-company-board/config"
if [ -f "$CONF" ] && grep -qx "SERVER=$DEST/board/server.py" "$CONF"; then
  bash "$DEST/board/service.sh" restart
else
  echo "看板常驻还没指向这里：运行 bash \"$DEST/board/service.sh\" install"
fi
