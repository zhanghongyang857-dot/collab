#!/usr/bin/env python3
"""看板模块管理和口令合并，由 init.sh module / init.sh rules 调用。

用法：modules.py <工具包目录> module list
      modules.py <工具包目录> module enable|disable|init <id>
      modules.py <工具包目录> rules
都可以加 --now-dir <NOW 数据目录>；没写时依次看环境变量 NOW_DATA_DIR、工具包旁边的 config.json、NOW_PATH、~/Desktop/NOW。

enable 把模块加进 config.json 的 modules，缺的数据文件从 sample/ 生成（只生成 module.json 的 files 列出的），再合并口令；
disable 只从 modules 去掉、再合并口令，数据文件不动。
口令：core/口令.md 和已启用模块的 口令.md 合并成 NOW 数据目录下的 口令.md；同名口令（## 标题）按核心、模块顺序拼起来。
"""
import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

CONTRACT = 1  # 和 board/now/build.py 的 CONTRACT 一致
DEFAULT_MODULES = ["schedule", "deadlines"]  # 和 board/now/build.py 一致：config.json 没写 modules 时启用


def data_dir(kit, explicit):
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.environ.get("NOW_DATA_DIR"):
        return Path(os.environ["NOW_DATA_DIR"]).expanduser().resolve()
    if (kit.parent / "config.json").exists():  # 工具包发布在 NOW/系统/ 时
        return kit.parent.resolve()
    if os.environ.get("NOW_PATH"):
        return Path(os.environ["NOW_PATH"]).expanduser().resolve().parent / "NOW"
    return Path.home() / "Desktop" / "NOW"


def read_config(data):
    f = data / "config.json"
    if not f.exists():
        sys.exit(f"没有找到 {f}：用 --now-dir 指明 NOW 数据目录，或先运行 init.sh now")
    return json.loads(f.read_text(encoding="utf-8"))


def write_config(data, cfg):
    (data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_modules(kit, data):
    """所有可用模块 {id: (目录, module.json)}；同 id 时 NOW 数据目录下 模块/ 里的优先。"""
    found = {}
    for base in (kit / "modules", data / "模块"):
        if base.is_dir():
            for d in sorted(base.iterdir()):
                f = d / "module.json"
                if f.is_file():
                    try:
                        found[d.name] = (d, json.loads(f.read_text(encoding="utf-8")))
                    except ValueError as e:
                        found[d.name] = (d, {"id": d.name, "broken": str(e)})
    return found


def enabled(cfg, avail):
    mods = cfg.get("modules")
    return [m for m in DEFAULT_MODULES if m in avail] if mods is None else list(mods)


def problem(meta, on):
    """这个模块为什么加载不了；能加载时返回空串。on 是已启用的模块 id。"""
    if meta.get("broken"):
        return f"module.json 读不了：{meta['broken']}"
    if meta.get("contract") != CONTRACT:
        return f"约定版本 {meta.get('contract')} 不对，本看板是 {CONTRACT}"
    miss = [r for r in meta.get("requires", []) if r not in on]
    return f"缺依赖 {'、'.join(miss)}" if miss else ""


def cmd_list(kit, data):
    cfg = read_config(data)
    avail = find_modules(kit, data)
    on = enabled(cfg, avail)
    for mid, (_, meta) in sorted(avail.items(), key=lambda x: (x[0] not in on, on.index(x[0]) if x[0] in on else 0, x[0])):
        state = "已启用" if mid in on else "未启用"
        why = problem(meta, on)
        print(f"{mid}\t{meta.get('name', mid)}\tv{meta.get('version', '?')}\t{state}{'（' + why + '）' if why else ''}")
    for mid in on:
        if mid not in avail:
            print(f"{mid}\t?\t?\t已启用（没找到模块目录）")


def start_files(kit, data, mid, avail):
    """缺的数据文件从 sample/ 生成，只生成 files 列出的；返回生成了哪些。"""
    d, meta = avail[mid]
    made = []
    for rel in meta.get("files", []):
        src, dst = d / "sample" / rel, data / rel
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            made.append(rel)
    return made


def need(mid, avail):
    if mid not in avail:
        sys.exit(f"没有模块 {mid}（可用：{'、'.join(sorted(avail)) or '无'}）")


def cmd_enable(kit, data, mid):
    cfg = read_config(data)
    avail = find_modules(kit, data)
    need(mid, avail)
    on = enabled(cfg, avail)
    why = problem(avail[mid][1], on)
    if why:
        sys.exit(f"不能启用 {mid}：{why}")
    made = start_files(kit, data, mid, avail)
    if mid in on:
        print(f"{mid} 已经启用")
    else:
        cfg["modules"] = on + [mid]
        write_config(data, cfg)
        print(f"已启用 {mid}，刷新看板就出现")
    for rel in made:
        print(f"  新建 {rel}（样例，改成自己的）")
    rules(kit, data)


def cmd_disable(kit, data, mid):
    cfg = read_config(data)
    avail = find_modules(kit, data)
    on = enabled(cfg, avail)
    if mid not in on:
        print(f"{mid} 没有启用")
        return
    cfg["modules"] = [m for m in on if m != mid]
    write_config(data, cfg)
    print(f"已停用 {mid}，数据文件没动")
    for other in cfg["modules"]:
        if other in avail and mid in avail[other][1].get("requires", []):
            print(f"  注意：{other} 依赖 {mid}，之后不会加载")
    rules(kit, data)


def cmd_init(kit, data, mid):
    avail = find_modules(kit, data)
    need(mid, avail)
    made = start_files(kit, data, mid, avail)
    print("\n".join(f"新建 {r}（样例，改成自己的）" for r in made) or f"{mid} 不需要新建数据文件")


def short(p):
    s, home = str(p), str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s


def split_rules(text):
    """按 `## 口令名` 切分，返回 [(口令名, 正文)]；第一个 ## 之前的说明不要。"""
    out, name, buf = [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if name:
                out.append((name, "\n".join(buf).strip()))
            name, buf = line[3:].strip(), []
        elif name:
            buf.append(line)
    if name:
        out.append((name, "\n".join(buf).strip()))
    return out


def merged_rules(kit, data, cfg):
    avail = find_modules(kit, data)
    on = enabled(cfg, avail)
    now_md = Path(cfg.get("now_md") or "../NOW.md").expanduser()
    now_md = now_md if now_md.is_absolute() else (data / now_md).resolve()
    sources = [("核心", kit / "core", kit / "core" / "口令.md")]
    sources += [(avail[m][1].get("name", m), avail[m][0], avail[m][0] / "口令.md") for m in on
                if m in avail and not problem(avail[m][1], on)]
    order, bodies, used = [], {}, []
    for label, base, f in sources:
        if not f.exists():
            continue
        used.append(label)
        text = f.read_text(encoding="utf-8")
        for k, v in {"NOW目录": data, "NOW文件": now_md, "工具包": kit, "模块目录": base}.items():
            text = text.replace("{{" + k + "}}", short(v))
        for name, body in split_rules(text):
            if name not in bodies:
                order.append(name)
                bodies[name] = []
            bodies[name].append(body)
    head = ("# 口令\n\n"
            f"由 `init.sh rules` 按已启用的模块合并生成（{'、'.join(used)}），不要手改；"
            "要改就改工具包里的 `core/口令.md` 或模块的 `口令.md`，发布后重新运行 `init.sh rules`。\n\n")
    return head + "\n\n".join(f"## {n}\n\n" + "\n".join(bodies[n]) for n in order) + "\n"


def rules(kit, data):
    cfg = read_config(data)
    (data / "口令.md").write_text(merged_rules(kit, data, cfg), encoding="utf-8")
    print(f"已合并口令：{short(data / '口令.md')}")


def main(argv):
    explicit = None
    if "--now-dir" in argv:
        i = argv.index("--now-dir")
        if i + 1 >= len(argv):
            sys.exit("--now-dir 需要目录")
        explicit = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) < 2:
        sys.exit(__doc__)
    kit, mode, rest = Path(argv[0]).resolve(), argv[1], argv[2:]
    data = data_dir(kit, explicit)
    if mode == "rules":
        rules(kit, data)
    elif mode == "module" and rest[:1] == ["list"]:
        cmd_list(kit, data)
    elif mode == "module" and len(rest) == 2 and rest[0] in ("enable", "disable", "init"):
        {"enable": cmd_enable, "disable": cmd_disable, "init": cmd_init}[rest[0]](kit, data, rest[1])
    else:
        sys.exit("用法：init.sh module list | enable <id> | disable <id> | init <id>；init.sh rules")


if __name__ == "__main__":
    main(sys.argv[1:])
