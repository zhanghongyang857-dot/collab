#!/usr/bin/env python3
"""项目登记表和 NOW 位置：看板不搭 NOW 也能找到项目。

登记表 projects.json 放在工具包旁边（本机发布在 NOW/系统/ 时是 NOW/projects.json），只记项目根目录和名字；
环境变量 COLLAB_PROJECTS 可另指位置。开发版工具包（src/，没有 版本.txt）不登记，免得写进开发仓库。
NOW 只认环境变量 NOW_PATH、工具包旁边的 NOW（有 config.json）、看板常驻已安装的配置；都没有就是没启用 NOW。

用法（一般由 init.sh 调用）：
  registry.py add    <工具包> <项目目录> <名字>   登记；输出 added / exists / off（没有登记表）
  registry.py remove <工具包> <项目目录>          移除；输出 removed / missing / off
  registry.py now-md <工具包>                     NOW.md 的位置，没启用 NOW 时输出空行
  registry.py roots  <工具包>                     登记表和 NOW 任务表里的全部项目目录，每行一个
  registry.py url    <工具包> <项目目录>          本项目的看板网址
  registry.py open   <工具包> <项目目录> [--print]  看板在运行就用浏览器打开（--print 只打印），没运行时提示怎么启动
只用 Python 标准库。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

SERVICE_CONFIG = Path("~/Library/Application Support/ai-company-board/config").expanduser()


def path(kit: Path) -> Optional[Path]:
    """登记表位置；开发版工具包且没设 COLLAB_PROJECTS 时为 None（不登记）。"""
    env = os.environ.get("COLLAB_PROJECTS")
    if env:
        return Path(env).expanduser()
    return kit.parent / "projects.json" if (kit / "版本.txt").exists() else None


def load(reg: Optional[Path]) -> List[Dict[str, str]]:
    if not reg or not reg.exists():
        return []
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
    except ValueError:
        return []
    items = data.get("projects", []) if isinstance(data, dict) else []
    return [p for p in items if isinstance(p, dict) and p.get("root")]


def save(reg: Path, items: List[Dict[str, str]]) -> None:
    reg.parent.mkdir(parents=True, exist_ok=True)
    tmp = reg.with_name(reg.name + ".tmp")
    tmp.write_text(json.dumps({"projects": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(reg)


def add(kit: Path, root: Path, name: str) -> str:
    reg = path(kit)
    if not reg:
        return "off"
    items, root_s = load(reg), str(root.resolve())
    if any(p["root"] == root_s for p in items):
        return "exists"
    save(reg, items + [{"name": name or root.name, "root": root_s}])
    return "added"


def remove(kit: Path, root: Path) -> str:
    reg = path(kit)
    if not reg:
        return "off"
    items, root_s = load(reg), str(root.resolve())
    kept = [p for p in items if p["root"] != root_s]
    if len(kept) == len(items):
        return "missing"
    save(reg, kept)
    return "removed"


def service_value(key: str) -> str:
    """看板常驻已安装配置里的一项（board/service.sh 写的 KEY=值）。"""
    try:
        for line in SERVICE_CONFIG.read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line[len(key) + 1:].strip()
    except OSError:
        pass
    return ""


def now_data_dir(kit: Path) -> Optional[Path]:
    """NOW 数据目录：NOW_DATA_DIR、工具包旁边有 config.json 的目录、NOW_PATH 旁的 NOW/、本工具包装的常驻配置里的 NOW_DIR。"""
    if os.environ.get("NOW_DATA_DIR"):
        return Path(os.environ["NOW_DATA_DIR"]).expanduser().resolve()
    if (kit.parent / "config.json").exists():  # 工具包发布在 NOW/系统/ 时
        return kit.parent.resolve()
    if os.environ.get("NOW_PATH"):
        return Path(os.environ["NOW_PATH"]).expanduser().resolve().parent / "NOW"
    conf = service_value("NOW_DIR")  # 只认本工具包装的常驻，开发版不会写到发布版的 NOW
    if conf and service_value("ROOT") == str(kit.resolve()) and (Path(conf) / "config.json").exists():
        return Path(conf)
    return None


def now_md(kit: Path) -> Optional[Path]:
    """NOW.md：NOW_PATH；否则按 NOW 数据目录的 config.json（now_md，缺省是数据目录上一级的 NOW.md）。"""
    if os.environ.get("NOW_PATH"):
        return Path(os.environ["NOW_PATH"]).expanduser()
    data = now_data_dir(kit)
    if not data or not (data / "config.json").exists():
        return None
    try:
        rel = json.loads((data / "config.json").read_text(encoding="utf-8")).get("now_md")
    except ValueError:
        rel = None
    p = Path(rel).expanduser() if rel else data.parent / "NOW.md"
    return p if p.is_absolute() else (data / p).resolve()


def now_roots(md: Optional[Path]) -> List[Path]:
    """NOW.md「任务」表里有 collab/ 的项目目录。"""
    if not md or not md.exists():
        return []
    sec = re.search(r"(?ms)^## 任务\s*\n(.*?)(?=^## |\Z)", md.read_text(encoding="utf-8"))
    out = []
    for m in re.finditer(r"\]\(<?([^)>]+?collab/PROGRESS\.md)>?\)", sec.group(1) if sec else ""):
        p = (md.parent / m.group(1)).resolve()
        if p.exists():
            out.append(p.parent.parent)
    return out


def roots(kit: Path) -> List[Path]:
    seen, out = set(), []
    for r in [Path(p["root"]) for p in load(path(kit))] + now_roots(now_md(kit)):
        if str(r) not in seen and (r / "collab" / "PROGRESS.md").exists():
            seen.add(str(r))
            out.append(r)
    return out


def project_id(root: Path) -> str:
    """看板网址里的项目编号：根目录路径的哈希（和 board/server.py 一致）。"""
    return hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]


def port() -> str:
    return os.environ.get("BOARD_PORT") or service_value("PORT") or "3100"


def url(root: Path) -> str:
    return "http://127.0.0.1:%s/p/%s" % (port(), project_id(root.resolve()))


def open_board(kit: Path, root: Path, only_print: bool) -> int:
    link = url(root)
    print(link)
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s/api/projects" % port(), timeout=2) as r:
            listed = any(p.get("root") == str(root.resolve()) for p in json.loads(r.read().decode("utf-8")))
    except (OSError, ValueError):
        print("看板没在运行：前台运行 python3 %s --port %s，或常驻 bash %s install"
              % (kit / "board" / "server.py", port(), kit / "board" / "service.sh"))
        return 1
    if not listed:
        print("看板里还没有这个项目：先运行 %s register %s" % (kit / "core" / "init.sh", root))
        return 1
    if not only_print and shutil.which("open"):
        subprocess.run(["open", link], check=False)
    return 0


def main(argv: List[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "add" and len(rest) >= 3:
        print(add(Path(rest[0]), Path(rest[1]), rest[2]))
    elif cmd == "remove" and len(rest) >= 2:
        print(remove(Path(rest[0]), Path(rest[1])))
    elif cmd == "now-md" and rest:
        print(now_md(Path(rest[0])) or "")
    elif cmd == "roots" and rest:
        for r in roots(Path(rest[0])):
            print(r)
    elif cmd == "url" and len(rest) >= 2:
        print(url(Path(rest[1])))
    elif cmd == "open" and len(rest) >= 2:
        return open_board(Path(rest[0]), Path(rest[1]), "--print" in rest[2:])
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
