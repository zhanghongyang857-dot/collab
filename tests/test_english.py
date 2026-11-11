"""G036-T6 英文内容：英文语言包齐全、英文工作台从装到验收没有中文、中英两套模板对齐、换语言往返还原、班子配置的中文键照认。全部用临时目录。"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC / "core"))
import i18n  # noqa: E402
import paths  # noqa: E402
import team  # noqa: E402

CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")  # 汉字和中文标点（含全角｜：英文卡头用半角 |）
CLEAR = ("COLLAB_ACTOR", "COLLAB_RUN", "COLLAB_WRITER", "COLLAB_FLOW", "COLLAB_SESSION", "COLLAB_PROJECT", "COLLAB_LANG", "NOW_PATH", "NOW_DATA_DIR")


def cjk_lines(*roots):
    out = []
    for r in roots:
        files = [r] if r.is_file() else sorted(x for x in r.rglob("*") if x.is_file())
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            out += [f"{f}: {l}" for l in text.splitlines() if CJK.search(l)]
    return out


class TestPack(unittest.TestCase):
    def test_english_text_complete(self):
        en = i18n.raw("en")
        empty = [k for k, v in en["text"].items() if not v]
        self.assertEqual(empty, [])
        self.assertEqual(i18n.missing_keys(), {})
        self.assertEqual([k for k, v in en["text"].items() if CJK.search(v) and "commands.zh.md" not in v], [])

    def test_helpers(self):
        zh, en = i18n.pack("zh"), i18n.pack("en")
        self.assertEqual((zh.join(["a", "b"]), en.join(["a", "b"])), ("a、b", "a, b"))
        self.assertEqual((zh.kv("目的"), en.kv("Purpose"), en.kv("Purpose", "x")), ("目的：", "Purpose:", "Purpose: x"))
        self.assertEqual(en.edge_res("review", "pass"), "Review: Pass")

    def test_slug(self):
        self.assertEqual(paths.slug("Report format"), "Report-format")
        self.assertEqual(paths.slug("河工 方略"), "河工方略")


class TestWorkbench(unittest.TestCase):
    def test_two_sets_same_files(self):
        def files(lang):
            base = SRC / "workbench" / lang
            return sorted(str(x.relative_to(base)) for x in base.rglob("*") if x.is_file())
        self.assertEqual(files("zh"), files("en"))
        self.assertEqual(cjk_lines(SRC / "workbench" / "en"), [])
        for rel in ("collab/PROGRESS.md", "collab/log.md", "collab/decisions.md", "collab/lessons.md", "collab/archive/decisions.md",
                    "collab/members.md", "AGENTS.md"):  # init.sh lang 逐行对照这些文件，两种语言行数要一样
            a = (SRC / "workbench" / "zh" / rel).read_text(encoding="utf-8").splitlines()
            b = (SRC / "workbench" / "en" / rel).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(a), len(b), rel)

    def test_commands_both_languages(self):
        for base in [SRC / "core", *[p.parent for p in SRC.glob("modules/*/commands.zh.md")]]:
            zh = re.findall(r"(?m)^## ", (base / "commands.zh.md").read_text(encoding="utf-8"))
            en = (base / "commands.en.md").read_text(encoding="utf-8")
            self.assertEqual(len(zh), len(re.findall(r"(?m)^## ", en)), base)
            self.assertEqual(cjk_lines(base / "commands.en.md"), [])


class TestEnglishProject(unittest.TestCase):
    """英文工作台从装到验收：命令行输出和项目里的文件都没有中文（正文也用英文写）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.env = {k: v for k, v in os.environ.items() if k not in CLEAR}
        cls.env.update(HOME=str(cls.tmp / "home"), COLLAB_TEAM=str(cls.tmp / "team"), FLOW_NOW="2026-11-10T10:00:00+08:00")
        cls.proj = cls.tmp / "p"
        cls.out = []
        init = SRC / "core" / "init.sh"
        cls.sh("bash", init, "team", cls.tmp / "team", "--lang", "en")
        cls.sh("bash", init, "new", cls.proj, "-n", "Demo", "--no-now")  # 不写 --lang：默认英文
        cls.sh("bash", init, "team-sync", cls.proj)
        g = cls.flow("new", "goal", "--title", "Weekly report", "--basis", "Owner: build it")
        card = cls.proj / "collab" / "goals" / "G001.md"
        card.write_text(card.read_text(encoding="utf-8").replace("- What we want:", "- What we want: A one-page weekly report.")
                        .replace("- Success criteria:", "- Success criteria: ① it runs"), encoding="utf-8")
        plan = cls.tmp / "plan.json"
        plan.write_text(json.dumps({"stages": [{"order": 1, "name": "Build", "type": "work", "tasks": [
            {"key": "s", "title": "Write the script", "executor": "codex", "reviewer": "lead", "purpose": "Report",
             "deliverables": "report.py", "acceptance": "It runs"}]}]}), encoding="utf-8")
        cls.flow("plan", "G001", "--file", plan)
        cls.flow("log", "G001", "submit", "--note", "Ready", "--recommend", "Approve")
        cls.flow("log", "G001", "approve", "--as", "owner", "--basis", "Owner: go")
        cls.flow("log", "G001-T1", "deliver", "--as", "codex", "--evidence", "x", "--note", "refused")
        cls.flow("log", "G001-T1", "dispatch", "--to", "codex", "--note", "Over to codex")
        cls.flow("log", "G001-T1", "pick_up", "--as", "codex", "--note", "Starting")
        cls.flow("context", "G001-T1", "--to", "codex")
        cls.flow("context", "G001-T1", "--to", "codex", "--list")
        (cls.proj / "report.py").write_text("print(1)\n", encoding="utf-8")
        cls.flow("log", "G001-T1", "deliver", "--as", "codex", "--evidence", "report.py", "--note", "Done")
        cls.flow("log", "G001-T1", "review", "--result", "pass", "--note", "Checked")
        cls.flow("new", "issue", "--title", "Format", "--attendees", "codex:implementation", "--basis", "Owner: discuss")
        cls.flow("next", "G001")
        cls.flow("render")
        cls.flow("check")
        cls.flow("--help")
        cls.sh("python3", SRC / "core" / "dispatch.py", "--project", cls.proj, "list")
        cls.sh("bash", init, "--help")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    @classmethod
    def sh(cls, *cmd):
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=cls.env)
        cls.out.append(r.stdout + r.stderr)
        return r

    @classmethod
    def flow(cls, *args):
        return cls.sh("python3", SRC / "core" / "flow.py", "--project", cls.proj, *args)

    def test_config_is_english(self):
        self.assertEqual(json.loads((self.proj / "collab" / "config.json").read_text())["lang"], "en")

    def test_no_chinese_in_output(self):
        text = "\n".join(self.out)
        self.assertIn("Logged: G001-T1", text)
        self.assertIn("Your next moves", text)
        self.assertIn("hard error: Evidence not found", text)
        self.assertEqual([l for l in text.splitlines() if CJK.search(l)], [])

    def test_no_chinese_in_files(self):
        self.assertEqual(cjk_lines(self.proj, self.tmp / "team"), [])
        self.assertTrue((self.proj / "collab" / "issues" / "I001-Format.md").exists())
        head = next(l for l in (self.proj / "collab" / "tasks" / "G001-T1-Write-the-script.md").read_text(encoding="utf-8").splitlines() if l.startswith("Status:"))
        self.assertTrue(head.startswith("Status: Passed | Goal: G001"), head)


class TestSwitchAndTeam(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: v for k, v in os.environ.items() if k not in CLEAR}
        self.env.update(HOME=str(self.tmp), COLLAB_TEAM=str(self.tmp / "team"), FLOW_NOW="2026-11-10T10:00:00+08:00")
        (self.tmp / "team").mkdir()
        shutil.copy(SRC / "core" / "team-example" / "en" / "team.json", self.tmp / "team" / "team.json")  # 班子的内容用英文，换语言后只剩卡片正文是中文

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_(self, *cmd):
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_switch_round_trip(self):
        p = self.tmp / "p"
        self.run_("bash", SRC / "core" / "init.sh", "new", p, "--no-now", "--lang", "zh")
        self.run_("python3", SRC / "core" / "flow.py", "--project", p, "建立", "目标", "--标题", "示例", "--依据", "总裁：做")
        self.run_("python3", SRC / "core" / "flow.py", "--project", p, "建立", "议题", "--标题", "格式", "--与会", "codex", "--依据", "总裁：聊")
        before = {f: f.read_text(encoding="utf-8") for f in (p / "collab").rglob("*.md")}
        self.run_("bash", SRC / "core" / "init.sh", "lang", "en", p)
        goal = (p / "collab" / "goals" / "G001.md").read_text(encoding="utf-8")
        self.assertIn("## What we want\n- What we want:\n- Success criteria:", goal)
        self.assertIn("Status: Draft | Stage: Idea | Type: General | Holder: Lead", goal)
        self.assertIn("## Summary (Lead)", (p / "collab" / "issues" / "I001-格式.md").read_text(encoding="utf-8"))
        rest = [l for l in cjk_lines(p / "collab", p / "AGENTS.md") if "示例" not in l and "格式" not in l and "总裁：" not in l]
        self.assertEqual(rest, [])
        self.run_("bash", SRC / "core" / "init.sh", "lang", "zh", p)
        after = {f: f.read_text(encoding="utf-8") for f in (p / "collab").rglob("*.md")}
        self.assertEqual(after, before)

    def test_old_team_keys_still_read(self):
        old = {"总管": {"名称": "Claude"}, "成员": [{"名称": "Codex", "派活名": "codex", "别名": ["cx"], "新会话命令": ["true", "{prompt}"],
                                                    "运行上限": {"步数": 3}}]}
        f = self.tmp / "team.json"
        f.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        data = team.read(f)
        self.assertEqual(data["lead"]["name"], "Claude")
        self.assertEqual(data["members"][0]["start_command"], ["true", "{prompt}"])
        self.assertEqual(data["members"][0]["limits"], {"steps": 3})
        import dispatch
        saved = dispatch.TEAM_FILE
        dispatch.TEAM_FILE = f
        try:
            self.assertEqual(dispatch.load_members()["codex"]["aliases"], ["cx"])
            self.assertEqual(dispatch.run_limits("codex"), {"steps": 3, "seconds": 600})
        finally:
            dispatch.TEAM_FILE = saved

    def test_migrate_now_rekeys_team(self):
        now = self.tmp / "NOW"
        (now / "班子").mkdir(parents=True)
        (now / "config.json").write_text('{"now_md": "../NOW.md"}', encoding="utf-8")
        old = {"成员": [{"名称": "Codex", "派活名": "codex", "新会话命令": ["true"]}]}
        (now / "班子" / "班子.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        (now / "班子" / "人才.json").write_text(json.dumps({"人才": [{"身份": "x", "技能": ["a"]}]}, ensure_ascii=False), encoding="utf-8")
        self.run_("bash", SRC / "core" / "init.sh", "migrate-now", now)
        self.assertEqual(json.loads((now / "team" / "team.json").read_text(encoding="utf-8")),
                         {"members": [{"name": "Codex", "dispatch_name": "codex", "start_command": ["true"]}]})
        self.assertEqual(json.loads((now / "team" / "talent.json").read_text(encoding="utf-8")), {"talent": [{"identity": "x", "skills": ["a"]}]})
        self.assertIn("没有改动", self.run_("bash", SRC / "core" / "init.sh", "migrate-now", now))
        self.run_("bash", SRC / "core" / "init.sh", "migrate-now", now, "--rollback")
        self.assertEqual(json.loads((now / "班子" / "班子.json").read_text(encoding="utf-8")), old)

    def test_chinese_aliases_still_work(self):
        import flow
        self.assertEqual(flow.english_argv(["--project", "x", "记", "G001", "交付", "--作为", "codex", "--证据=a"]),
                         ["--project", "x", "log", "G001", "交付", "--as", "codex", "--evidence=a"])


class TestTrialFixes(unittest.TestCase):
    """G036-T9 试用中修的问题：卡头半角分隔、单数、英文迁移、dispatch 帮助无中文参数名。"""

    def test_card_head_bars(self):
        import collab_parse
        self.assertEqual(collab_parse.kv_line("状态：进行中 ｜ 执行：工部"), {"状态": "进行中", "执行": "工部"})
        self.assertEqual(collab_parse.kv_line("Status: Active | Executor: Works"), {"Status": "Active", "Executor": "Works"})
        self.assertEqual(collab_parse.kv_line("Status: Active ｜ Executor: Works"), {"Status": "Active", "Executor": "Works"})

    def test_english_header_uses_ascii_bar(self):
        en = i18n.pack("en")
        head = en.t("header.task", state="Passed", goal="G001", stage="1", executor="a", reviewer="b", holder="—")
        self.assertIn(" | ", head)
        self.assertNotIn("｜", head)

    def test_meta_line_reads_both_bars(self):
        import lang
        old = "目标：x ｜ 截止：y ｜ 状态：进行中 ｜ 建立于 2026-01-01"
        self.assertEqual(lang.meta_line(old, "en"), "Goal: x | Due: y | Status: Active | Started 2026-01-01")
        self.assertEqual(lang.meta_line("Goal: x ｜ Due: y ｜ Status: Active ｜ Started 2026-01-01", "zh"), old)
        self.assertEqual(lang.meta_line("Goal: x | Due: y | Status: Active | Started 2026-01-01", "zh"), old)

    def test_singular(self):
        en = i18n.pack("en")
        self.assertEqual(en.t("board.strip.goals", n=1), "1 goal in progress")
        self.assertEqual(en.t("board.strip.goals", n=2), "2 goals in progress")
        self.assertEqual(en.t("board.strip.goals", n=11), "11 goals in progress")
        self.assertEqual(i18n.pack("zh").t("board.strip.goals", n=1), "1 个目标在推进")

    def test_dispatch_help_has_no_chinese_flags(self):
        r = subprocess.run([sys.executable, str(SRC / "core" / "dispatch.py"), "room", "--help"], capture_output=True, text=True,
                           env={**os.environ, "COLLAB_LANG": "en"})
        self.assertEqual([l for l in (r.stdout + r.stderr).splitlines() if re.search(r"--[^\x00-\x7f]", l)], [])
        import dispatch
        self.assertEqual(dispatch.english_flags(["room", "--标题", "x", "--与会=a:b", "--开场", "y", "--title", "z"]),
                         ["room", "--title", "x", "--attendees=a:b", "--opening", "y", "--title", "z"])

    def test_migrate_to_english(self):
        old = ROOT / "tests" / "样例" / "旧格式" / "万历新政第2回"
        tmp = Path(tempfile.mkdtemp())
        try:
            p = tmp / "p"
            shutil.copytree(old, p)
            env = {k: v for k, v in os.environ.items() if k not in CLEAR}
            r = subprocess.run(["bash", str(SRC / "core" / "init.sh"), "migrate", str(p), "--lang", "en"], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Migrated", r.stdout)
            self.assertEqual([l for l in r.stdout.splitlines() if CJK.search(l)], [])
            self.assertEqual(json.loads((p / "collab" / "config.json").read_text())["lang"], "en")
            progress = (p / "collab" / "PROGRESS.md").read_text(encoding="utf-8")
            self.assertIn("| Status: Active | Started ", progress)
            self.assertIn("Loading map", progress)
            head = (p / "collab" / "goals" / "G001.md").read_text(encoding="utf-8").splitlines()[2]
            self.assertTrue(head.startswith("Status: Active | Type: "), head)
            r = subprocess.run(["bash", str(SRC / "core" / "init.sh"), "migrate", "--rollback", str(p)], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((p / "collab" / "任务").is_dir())
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
