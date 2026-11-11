#!/usr/bin/env python3
"""看板模块管理和口令合并，由 init.sh module / init.sh rules 调用。

用法：modules.py <工具包目录> module list
      modules.py <工具包目录> module enable|disable|init <id>
      modules.py <工具包目录> rules
都可以加 --now-dir <NOW 数据目录>；没写时依次看环境变量 NOW_DATA_DIR、工具包旁边的 config.json、NOW_PATH、本工具包装的看板常驻配置（core/registry.py）。

enable 把模块加进 config.json 的 modules，缺的数据文件从 sample/ 生成（只生成 module.json 的 files 列出的），再合并口令；
disable 只从 modules 去掉、再合并口令，数据文件不动。
口令：core/commands.md 和已启用模块的 commands.md 合并成 NOW 数据目录下的 commands.md；同名口令（## 标题）按核心、模块顺序拼起来。
"""
import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n  # noqa: E402
import paths as P  # noqa: E402
import registry  # noqa: E402  NOW 位置和 init.sh、看板服务同一套规则

CONTRACT = 1  # 和 board/now/build.py 的 CONTRACT 一致
L = i18n.current  # 提示跟着 NOW 的语言（read_config 里设）
DEFAULT_MODULES = ["schedule", "deadlines"]  # 和 board/now/build.py 一致：config.json 没写 modules 时启用


def data_dir(kit, explicit):
    if explicit:
        return Path(explicit).expanduser().resolve()
    found = registry.now_data_dir(kit)
    if not found:
        sys.exit(L.t("mod.no_now"))
    return found


def read_config(data):
    f = data / "config.json"
    if not f.exists():
        sys.exit(L.t("mod.no_config", path=f))
    cfg = json.loads(f.read_text(encoding="utf-8"))
    i18n.set_current(now_lang(cfg))
    return cfg


def write_config(data, cfg):
    (data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_modules(kit, data):
    """所有可用模块 {id: (目录, module.json)}；同 id 时 NOW 数据目录下 模块/ 里的优先。"""
    found = {}
    for base in (kit / "modules", data / P.NOW_MODULES):
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
        return L.t("mod.broken", e=meta['broken'])
    if meta.get("contract") != CONTRACT:
        return L.t("mod.contract", v=meta.get('contract'), want=CONTRACT)
    miss = [r for r in meta.get("requires", []) if r not in on]
    return L.t("mod.missing_deps", deps=L.join(miss)) if miss else ""


def cmd_list(kit, data):
    cfg = read_config(data)
    avail = find_modules(kit, data)
    on = enabled(cfg, avail)
    for mid, (_, meta) in sorted(avail.items(), key=lambda x: (x[0] not in on, on.index(x[0]) if x[0] in on else 0, x[0])):
        state = L.t("mod.on") if mid in on else L.t("mod.off")
        why = problem(meta, on)
        print(f"{mid}\t{meta.get('name', mid)}\tv{meta.get('version', '?')}\t{state}{L.t('sep.paren_open') + why + L.t('sep.paren_close') if why else ''}")
    for mid in on:
        if mid not in avail:
            print(f"{mid}\t?\t?\t{L.t('mod.on_missing')}")


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
        sys.exit(L.t("mod.unknown", mid=mid, avail=L.join(sorted(avail)) or L.t("block.none_inline")))


def cmd_enable(kit, data, mid):
    cfg = read_config(data)
    avail = find_modules(kit, data)
    need(mid, avail)
    on = enabled(cfg, avail)
    why = problem(avail[mid][1], on)
    if why:
        sys.exit(L.t("mod.cant_enable", mid=mid, why=why))
    made = start_files(kit, data, mid, avail)
    if mid in on:
        print(L.t("mod.already_on", mid=mid))
    else:
        cfg["modules"] = on + [mid]
        write_config(data, cfg)
        print(L.t("mod.enabled", mid=mid))
    for rel in made:
        print("  " + L.t("mod.sample", path=rel))
    rules(kit, data)


def cmd_disable(kit, data, mid):
    cfg = read_config(data)
    avail = find_modules(kit, data)
    on = enabled(cfg, avail)
    if mid not in on:
        print(L.t("mod.not_on", mid=mid))
        return
    cfg["modules"] = [m for m in on if m != mid]
    write_config(data, cfg)
    print(L.t("mod.disabled", mid=mid))
    for other in cfg["modules"]:
        if other in avail and mid in avail[other][1].get("requires", []):
            print("  " + L.t("mod.dependent", other=other, mid=mid))
    rules(kit, data)


def cmd_init(kit, data, mid):
    avail = find_modules(kit, data)
    need(mid, avail)
    made = start_files(kit, data, mid, avail)
    print("\n".join(L.t("mod.sample", path=r) for r in made) or L.t("mod.no_files", mid=mid))


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


def now_lang(cfg) -> str:
    """NOW 的语言：环境变量 COLLAB_LANG，再 NOW config.json 的 lang，都没有用 en（同 registry.kit_lang）。"""
    v = os.environ.get("COLLAB_LANG") or cfg.get("lang") or "en"
    return v if v in i18n.LANGS else "en"


def merged_rules(kit, data, cfg):
    avail = find_modules(kit, data)
    on = enabled(cfg, avail)
    now_md = Path(cfg.get("now_md") or "../NOW.md").expanduser()
    now_md = now_md if now_md.is_absolute() else (data / now_md).resolve()
    lang = now_lang(cfg)
    L = i18n.pack(lang)

    def rules_file(base: Path) -> Path:
        """口令按语言放：commands.<lang>.md，没有这种语言时用另一种，再用 commands.md；工具包外的旧模块还叫 口令.md。"""
        for name in (f"commands.{lang}.md", *(f"commands.{x}.md" for x in i18n.LANGS if x != lang), P.COMMANDS, "口令.md"):
            if (base / name).exists():
                return base / name
        return base / P.COMMANDS
    sources = [(L.t("rules.core"), kit / "core", rules_file(kit / "core"))]
    sources += [(avail[m][1].get("name", m), avail[m][0], rules_file(avail[m][0])) for m in on
                if m in avail and not problem(avail[m][1], on)]
    order, bodies, used = [], {}, []
    for label, base, f in sources:
        if not f.exists():
            continue
        used.append(label)
        text = f.read_text(encoding="utf-8")
        for k, v in {"NOW目录": data, "NOW文件": now_md, "工具包": kit, "模块目录": base,
                     "now_dir": data, "now_file": now_md, "toolkit": kit, "module_dir": base}.items():
            text = text.replace("{{" + k + "}}", short(v))
        for name, body in split_rules(text):
            if name not in bodies:
                order.append(name)
                bodies[name] = []
            bodies[name].append(body)
    head = L.t("rules.head", used=L.join(used), lang=lang) + "\n\n"
    return head + "\n\n".join(f"## {n}\n\n" + "\n".join(bodies[n]) for n in order) + "\n"


def rules(kit, data):
    cfg = read_config(data)
    (data / P.COMMANDS).write_text(merged_rules(kit, data, cfg), encoding="utf-8")
    print(L.t("mod.rules_merged", path=short(data / P.COMMANDS)))


def main(argv):
    explicit = None
    if "--now-dir" in argv:
        i = argv.index("--now-dir")
        if i + 1 >= len(argv):
            sys.exit("--now-dir needs a directory")
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
        sys.exit(L.t("mod.usage"))


if __name__ == "__main__":
    main(sys.argv[1:])
