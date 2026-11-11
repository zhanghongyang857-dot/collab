#!/usr/bin/env python3
"""语言包：代码 → 给人看的文字。包在工具包的 i18n/<lang>.json（zh、en），格式见 collab/目标/G036/规格.md 第 2 节。

  t(key, **kw)          text 里的一句，按 str.format 填参数
  name(kind, code)      状态、边、席位等的显示名（kind 是 vocab 的命名空间，如 state、edge、seat）
  heading(code)         小节标题；field(code) 字段名
  code_of(kind, text)   反查：代码本身、中英两种显示名都认，认不出返回 None

缺键时退回英文包，再退回键名本身。项目可以在 collab/config.json 的 names 覆盖 names 里任一项。
只用 Python 标准库。
"""
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
I18N_DIR = HERE.parent / "i18n"
LANGS = ("zh", "en")
DEFAULT = "zh"
_cache: Dict[str, Dict[str, Any]] = {}


def raw(lang: str) -> Dict[str, Any]:
    """一种语言的整份语言包（不合并退回）。"""
    if lang not in _cache:
        f = I18N_DIR / f"{lang}.json"
        _cache[lang] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return _cache[lang]


def kind_key(ns: str) -> str:
    """vocab 命名空间名 → 语言包 names 里的键：SeatClass → seat_class。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", ns).lower()


SINGULAR_RE = re.compile(r"(?<![\d.,])1(</\w+>)? (goal|task|run|post|step|day|hour|minute|second|error|warning|question|call|row|record|issue|event|card|slot|member|item|attempt|round|file|stage|decision)s\b")

class Pack:
    """一种语言（加项目的称谓覆盖）的查询入口。"""

    def __init__(self, lang: str = DEFAULT, names: Optional[Dict[str, Dict[str, str]]] = None):
        self.lang = lang if lang in LANGS else DEFAULT
        self.overrides = names or {}

    def _get(self, group: str, key: str) -> Optional[str]:
        for lang in (self.lang, "en"):
            v = raw(lang).get(group, {}).get(key)
            if v:
                return v
        return None

    def t(self, key: str, **kw: Any) -> str:
        s = self._get("text", key)
        if s is None:
            return key
        return self._singular(s.format(**kw)) if kw else s

    def _singular(self, s: str) -> str:
        """英文「1 goals」→「1 goal」：模板里的复数写法，数量是 1 时去掉 s（{n} 代入之后才处理）。"""
        return SINGULAR_RE.sub(lambda m: "1" + (m.group(1) or "") + " " + m.group(2), s) if self.lang == "en" else s

    def join(self, items: Any, sep: str = "sep.list") -> str:
        """列表连写：中文「、」，英文 ", "；sep 可换 sep.clause（；/ ; ）。"""
        return self.t(sep).join(str(x) for x in items)

    def kv(self, name: str, value: Any = "") -> str:
        """字段行的「名：值」：中文全角冒号；英文 "Name: value"，没有值时只写 "Name:"。"""
        v = str(value or "")
        if self.lang == "zh":
            return f"{name}：{v}"
        return f"{name}: {v}" if v else f"{name}:"

    def q(self, x: Any) -> str:
        """引号：中文「x」，英文 "x"。"""
        return self.t("sep.quote_open") + str(x) + self.t("sep.quote_close")

    def name(self, kind: str, code: Any) -> str:
        if code is None or code == "":
            return "" if code is None else code
        code = str(code)
        o = self.overrides.get(kind, {}).get(code)
        if o:
            return o
        for lang in (self.lang, "en"):
            v = raw(lang).get("names", {}).get(kind, {}).get(code)
            if v:
                return v
        return code

    # 常用的几类显示名
    def st(self, code: Any) -> str:
        return self.name("state", code)

    def ed(self, code: Any) -> str:
        return self.name("edge", code)

    def who(self, code: Any) -> str:
        """发起、接收、持有人：席位代码显示席位名（owner → 总裁），成员派活名和「无」照原样或按席位类显示。"""
        if code is None or code == "":
            return ""
        s = str(code)
        v = self.overrides.get("seat", {}).get(s) or raw(self.lang).get("names", {}).get("seat", {}).get(s)
        if v:
            return v
        if s == "none":
            return self.name("seat_class", s)
        return s

    def edge_res(self, edge: Any, res: Any) -> str:
        """「确认：通过」这样的边加结果；起草阶段的结果是阶段名。"""
        if not res:
            return self.ed(edge)
        kind = "draft_stage" if edge == "draft_stage" else "result"
        return self.ed(edge) + self.t("sep.colon") + self.name(kind, res)

    def heading(self, code: str) -> str:
        return self._get("sections", code) or code

    def field(self, code: str) -> str:
        return self._get("fields", code) or code

    def text_dict(self) -> Dict[str, Any]:
        """整份语言包（本语言优先，缺的用英文补），给看板用。"""
        out: Dict[str, Any] = {"lang": self.lang}
        for group in ("names", "sections", "fields", "text"):
            en, mine = raw("en").get(group, {}), raw(self.lang).get(group, {})
            if group == "names":
                out[group] = {k: {**en.get(k, {}), **{c: v for c, v in mine.get(k, {}).items() if v},
                                  **self.overrides.get(k, {})} for k in set(en) | set(mine)}
            else:
                out[group] = {**en, **{k: v for k, v in mine.items() if v}}
        return out


def code_of(kind: str, text: Any) -> Optional[str]:
    """显示名 → 代码。kind：names 里的一类，或 section、field。代码本身、各语言的显示名都认，冒号和空白不算。"""
    if text is None:
        return None
    s = str(text).strip().rstrip("：:").strip()
    for lang in LANGS:
        pack = raw(lang)
        table = pack.get("sections" if kind == "section" else "fields" if kind == "field" else "names", {})
        table = table if kind in ("section", "field") else table.get(kind, {})
        if s in table:
            return s
        for code, v in table.items():
            if v and (v == s or v.lower() == s.lower()):
                return code
    return None


def cols(row: Dict[str, Any], kind: str = "now_col") -> Dict[str, Any]:
    """表格一行的列名换成代码（NOW 数据的表头中英两种写法都认）；认不出的列名原样。"""
    return {code_of(kind, k) or k: v for k, v in row.items()}


def heading_codes(text: str) -> Optional[str]:
    """小节标题 → 代码：先整行认，再认开头（「总结（总管）」认作 summary）。"""
    c = code_of("section", text)
    if c:
        return c
    s = str(text).strip()
    best = None
    for lang in LANGS:
        for code, v in raw(lang).get("sections", {}).items():
            if v and s.startswith(v) and (best is None or len(v) > best[1]):
                best = (code, len(v))
    return best[0] if best else None


def headings(code: str) -> list:
    """一个小节在各语言里的标题，解析时都认。"""
    out = []
    for lang in LANGS:
        v = raw(lang).get("sections", {}).get(code)
        if v and v not in out:
            out.append(v)
    return out or [code]


def names(kind: str, code: str) -> list:
    """一个代码在各语言里的显示名，解析时都认。"""
    out = []
    for lang in LANGS:
        v = raw(lang).get("names", {}).get(kind, {}).get(code)
        if v and v not in out:
            out.append(v)
    return out or [code]


def fields(code: str) -> list:
    out = []
    for lang in LANGS:
        v = raw(lang).get("fields", {}).get(code)
        if v and v not in out:
            out.append(v)
    return out or [code]


def missing_keys() -> Dict[str, list]:
    """两种语言包逐键对齐：{语言: [缺的键]}。check.py 报错、测试断言用。"""
    def flat(d, pre=""):
        out = set()
        for k, v in d.items():
            if k == "lang":
                continue
            if isinstance(v, dict):
                out |= flat(v, pre + k + ".")
            else:
                out.add(pre + k)
        return out
    keys = {lang: flat(raw(lang)) for lang in LANGS}
    every = set().union(*keys.values())
    return {lang: sorted(every - ks) for lang, ks in keys.items() if every - ks}


_default: Dict[str, Pack] = {}
_current = [os.environ.get("COLLAB_LANG") if os.environ.get("COLLAB_LANG") in LANGS else DEFAULT]


def set_current(lang: str) -> None:
    """当前项目的语言：flow.Project 载入时设，没有项目上下文的提示（回放、检查、命令行）跟着它。"""
    _current[0] = lang if lang in LANGS else DEFAULT


def pack(lang: Optional[str] = None) -> Pack:
    lang = lang or _current[0]
    if lang not in _default:
        _default[lang] = Pack(lang)
    return _default[lang]


class _Current:
    """跟着当前项目语言的 Pack（模块级的 L 用它，不在导入时定死语言）。"""

    def __getattr__(self, k: str) -> Any:
        return getattr(pack(), k)


current = _Current()


def project_lang(root: Any) -> str:
    """项目语言：<项目>/collab/config.json 的 lang；没有时 zh（旧格式项目都是中文）。"""
    try:
        v = json.loads((Path(root) / "collab" / "config.json").read_text(encoding="utf-8")).get("lang")
    except (OSError, ValueError):
        return DEFAULT
    return v if v in LANGS else DEFAULT


def main(argv: list) -> int:
    """给 shell 脚本用：i18n.py t <lang> <key> [名=值 …]，打印一句；lang 写目录时取那个项目的语言。"""
    if len(argv) >= 3 and argv[0] == "t":
        lang = argv[1] if argv[1] in LANGS else project_lang(argv[1])
        kw = dict(x.split("=", 1) for x in argv[3:] if "=" in x)
        print(pack(lang).t(argv[2], **kw))
        return 0
    if len(argv) >= 2 and argv[0] == "lang":
        print(project_lang(argv[1]))
        return 0
    print("usage: i18n.py t <zh|en|project-dir> <key> [name=value ...] | i18n.py lang <project-dir>")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
