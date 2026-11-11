"""init.sh module、init.sh rules 和 publish.sh --core、--module 的测试。全部用临时目录里的虚构数据。"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INIT = SRC / "core" / "init.sh"
PUBLISH = SRC / "core" / "publish.sh"


def write_module(base, mid, requires=(), contract=1, rules="", files=(), sample=None):
    d = base / mid
    d.mkdir(parents=True)
    meta = {"id": mid, "name": mid + "名", "version": 2, "contract": contract, "tabs": [{"id": mid, "title": mid}],
            "slots": [], "files": list(files), "requires": list(requires), "uses": [], "provides": []}
    (d / "module.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "load.py").write_text("def load(ctx):\n    return {}\n", encoding="utf-8")
    if rules:
        (d / "commands.md").write_text(rules, encoding="utf-8")
    for rel, text in (sample or {}).items():
        f = d / "sample" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "NOW"
        self.data.mkdir()
        (self.data / "config.json").write_text('{"now_md": "../NOW.md", "categories": []}', encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def cli(self, *args, ok=True):
        r = subprocess.run(["bash", str(INIT), *args, "--now-dir", str(self.data)], capture_output=True, text=True, env={**os.environ, "COLLAB_LANG": "zh"})
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def modules(self):
        return json.loads((self.data / "config.json").read_text(encoding="utf-8")).get("modules")

    def rules(self):
        return (self.data / "commands.md").read_text(encoding="utf-8")


class TestModuleCommand(Base):
    def test_list_defaults_and_states(self):
        write_module(self.data / "modules", "needs", requires=["nothing"])
        write_module(self.data / "modules", "future", contract=9)
        write_module(self.data / "modules", "plain")
        lines = {l.split("\t")[0]: l for l in self.cli("module", "list").stdout.splitlines()}
        self.assertIn("已启用", lines["schedule"])
        self.assertIn("已启用", lines["deadlines"])
        self.assertIn("未启用（缺依赖 nothing）", lines["needs"])
        self.assertIn("约定版本 9 不对", lines["future"])
        self.assertTrue(lines["plain"].endswith("未启用"))
        self.assertIn("plain名", lines["plain"])

    def test_link_module_with_only_module_json(self):
        d = self.data / "modules" / "ext"
        d.mkdir(parents=True)
        (d / "module.json").write_text(json.dumps({"id": "ext", "name": "外部", "version": 1, "contract": 1,
                                                   "tabs": [{"id": "ext", "title": "外部", "url": "http://127.0.0.1:3200/"}]}), encoding="utf-8")
        self.cli("module", "enable", "ext")
        self.assertIn("ext", self.modules())
        line = [l for l in self.cli("module", "list").stdout.splitlines() if l.startswith("ext")][0]
        self.assertIn("已启用", line)
        self.cli("module", "disable", "ext")
        self.assertNotIn("ext", self.modules())

    def test_enable_writes_config_and_is_idempotent(self):
        write_module(self.data / "modules", "cal")
        self.assertIsNone(self.modules())
        self.cli("module", "enable", "cal")
        self.assertEqual(self.modules(), ["schedule", "deadlines", "cal"])  # 默认模块变成显式的，顺序不变
        self.assertIn("已经启用", self.cli("module", "enable", "cal").stdout)
        self.assertEqual(self.modules(), ["schedule", "deadlines", "cal"])

    def test_enable_refuses_missing_requirement_and_unknown(self):
        write_module(self.data / "modules", "needs", requires=["nothing"])
        r = self.cli("module", "enable", "needs", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("缺依赖 nothing", r.stderr)
        self.assertNotEqual(self.cli("module", "enable", "nope", ok=False).returncode, 0)
        self.assertIsNone(self.modules())

    def test_enable_creates_only_listed_missing_files(self):
        write_module(self.data / "modules", "cal", files=["calendar/calendar.md", "已有.md"],
                     sample={"calendar/calendar.md": "样例", "已有.md": "样例", "别的.md": "样例"})
        (self.data / "已有.md").write_text("我的数据", encoding="utf-8")
        self.cli("module", "enable", "cal")
        self.assertEqual((self.data / "calendar" / "calendar.md").read_text(encoding="utf-8"), "样例")
        self.assertEqual((self.data / "已有.md").read_text(encoding="utf-8"), "我的数据")
        self.assertFalse((self.data / "别的.md").exists())

    def test_disable_keeps_data_and_warns_dependents(self):
        write_module(self.data / "modules", "base", files=["b.md"], sample={"b.md": "样例"})
        write_module(self.data / "modules", "top", requires=["base"])
        self.cli("module", "enable", "base")
        self.cli("module", "enable", "top")
        out = self.cli("module", "disable", "base").stdout
        self.assertIn("top 依赖 base", out)
        self.assertNotIn("base", self.modules())
        self.assertTrue((self.data / "b.md").exists())

    def test_contract_matches_build_py(self):
        build = (SRC / "board" / "now" / "build.py").read_text(encoding="utf-8")
        mods = (SRC / "core" / "modules.py").read_text(encoding="utf-8")
        pat = r"^(CONTRACT|DEFAULT_MODULES) = (.+?)(?:  #.*)?$"
        self.assertEqual(re.findall(pat, build, re.M), re.findall(pat, mods, re.M))


class TestRules(Base):
    def test_module_rules_follow_enable_and_disable(self):
        write_module(self.data / "modules", "cal", rules="说明不进合并\n\n## 记事件\n\n写进日历。\n\n## 收工 / 先停这\n\n日历这一步。\n")
        self.cli("rules")
        self.assertNotIn("记事件", self.rules())
        self.cli("module", "enable", "cal")
        self.assertIn("## 记事件", self.rules())
        self.assertNotIn("说明不进合并", self.rules())
        self.cli("module", "disable", "cal")
        self.assertNotIn("记事件", self.rules())
        self.assertNotIn("日历这一步", self.rules())

    def test_old_module_rules_file_name_still_read(self):
        write_module(self.data / "modules", "shop")
        (self.data / "modules" / "shop" / "口令.md").write_text("## 想买 …\n\n登记到清单。\n", encoding="utf-8")
        self.cli("module", "enable", "shop")
        self.assertIn("## 想买 …", self.rules())

    def test_same_command_is_joined_in_module_order(self):
        self.cli("rules")
        body = self.rules().split("## 收工 / 先停这", 1)[1].split("\n## ", 1)[0]
        self.assertLess(body.index("写今天的日志"), body.index("archive.py"))
        self.assertEqual(self.rules().count("## 收工 / 先停这"), 1)

    def test_core_only_has_no_schedule_step(self):
        (self.data / "config.json").write_text('{"modules": []}', encoding="utf-8")
        self.cli("rules")
        text = self.rules()
        self.assertIn("## 任务完成", text)
        self.assertNotIn("排明天", text)
        self.assertNotIn("archive.py", text)

    def test_placeholders_are_filled(self):
        self.cli("rules")
        text = self.rules()
        self.assertNotIn("{{", text)
        self.assertIn(str(self.tmp / "NOW.md").replace(str(Path.home()), "~"), text)
        self.assertIn(str(SRC / "modules" / "schedule" / "archive.py").replace(str(Path.home()), "~"), text)

    def test_shipped_rules_have_no_personal_paths(self):
        files = [*SRC.glob("core/commands.*.md"), *SRC.glob("modules/*/commands.*.md")]
        self.assertGreaterEqual(len(files), 8)
        for f in files:
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"/Users/\w|~/Documents/|_dataset|\d\d_Notes", str(f))

    def test_init_now_generates_rules(self):
        dest = self.tmp / "fresh"
        env = {**os.environ, "COLLAB_TEAM": str(self.tmp / "no-team"), "COLLAB_LANG": "zh"}
        r = subprocess.run(["bash", str(INIT), "now", str(dest)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("## 排明天", (dest / "NOW" / "commands.md").read_text(encoding="utf-8"))


@unittest.skipIf(subprocess.run(["git", "-C", str(ROOT), "rev-parse"], capture_output=True).returncode, "不在 git 仓库里")
class TestPublish(unittest.TestCase):
    """用 --dirty 发布工作区，这样测试不依赖改动已经提交。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def publish(self, *args):
        return subprocess.run(["bash", str(PUBLISH), "--dirty", *args], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.tmp), "COLLAB_LANG": "zh"})

    def test_core_needs_explicit_target(self):
        r = self.publish("--core")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("必须写目标", r.stderr)
        self.assertFalse((self.tmp / "Documents").exists())

    def test_core_runs_and_takes_a_module(self):
        kit = self.tmp / "NOW" / "系统"
        r = self.publish("--core", str(kit))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in (kit / "modules").iterdir()), ["README.en.md", "README.md"])
        self.assertIn("只有核心", (kit / "VERSION.txt").read_text(encoding="utf-8"))
        # 只有核心的工具包：建 NOW、看板只有「任务」、没有缺模块的提示
        home = self.tmp / "desk"
        r = subprocess.run(["bash", str(kit / "core" / "init.sh"), "now", str(home)], capture_output=True, text=True, env={**os.environ, "COLLAB_LANG": "zh"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        html = (home / "NOW" / "board.html").read_text(encoding="utf-8")
        self.assertIn('"notes": []', html)  # 没有缺模块的提示（页面自带语言包，不能再按文字找）
        self.assertNotIn("## 排明天", (home / "NOW" / "commands.md").read_text(encoding="utf-8"))
        # 单独导出的模块拷进来，enable 后出现
        out = self.tmp / "out"
        r = self.publish("--module", "schedule", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / "schedule" / "VERSION.txt").exists())
        shutil.copytree(out / "schedule", home / "NOW" / "modules" / "schedule")
        r = subprocess.run(["bash", str(kit / "core" / "init.sh"), "module", "enable", "schedule", "--now-dir", str(home / "NOW")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("## 排明天", (home / "NOW" / "commands.md").read_text(encoding="utf-8"))
        self.assertTrue((home / "NOW" / "schedule.md").exists())
        r = subprocess.run(["python3", str(kit / "board" / "now" / "build.py"), "--now-dir", str(home / "NOW")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('"title": "今天"', (home / "NOW" / "board.html").read_text(encoding="utf-8"))

    def test_module_refuses_existing_and_unknown(self):
        out = self.tmp / "out"
        (out / "schedule").mkdir(parents=True)
        self.assertNotEqual(self.publish("--module", "schedule", str(out)).returncode, 0)
        self.assertNotEqual(self.publish("--module", "nope", str(out)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
