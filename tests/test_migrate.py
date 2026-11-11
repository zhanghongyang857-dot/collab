"""迁移（init.sh migrate、migrate-now，G036-T3）：旧格式样例迁成格式 3 后回放相同、链接有效、和新版直接生成的一致；
第二次运行无改动；--rollback 后逐字节恢复；--dry-run 不改文件。旧格式样例是改英文前的演示（第 2 回），由旧版 demo/build.py 生成。"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src" / "core"))
import flow  # noqa: E402
import migrate  # noqa: E402

OLD = HERE / "样例" / "旧格式" / "万历新政第2回"
INIT = ROOT / "src" / "core" / "init.sh"
ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin"}


def tree(root: Path, skip=(migrate.BACKUP,)) -> dict:
    """{相对路径: sha1}，跳过备份目录。"""
    return {f.relative_to(root).as_posix(): hashlib.sha1(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file() and not any(s in f.relative_to(root).parts for s in skip)}


def broken_links(root: Path) -> list:
    out = []
    for f in sorted((root / "collab").rglob("*.md")):
        for m in re.finditer(r"\]\(([^)\s]+)\)", f.read_text(encoding="utf-8")):
            t = m.group(1).split("#")[0]
            if t and not re.match(r"^[a-z]+:", t) and not (f.parent / unquote(t)).resolve().exists():
                out.append((f.relative_to(root).as_posix(), m.group(1)))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proj = self.tmp / "p"
        shutil.copytree(OLD, self.proj)
        self.before = tree(self.proj)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def init(self, *args):
        return subprocess.run(["bash", str(INIT), *args], capture_output=True, text=True, env=ENV)


class TestMigrate(Base):
    def test_migrate_round_trip(self):
        old_states = {f.stem: migrate.old_replay([json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()])
                      for f in (self.proj / "collab" / "内部" / "流转").glob("*.jsonl")}
        r = self.init("migrate", str(self.proj))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("逐条核对", r.stdout)
        # 回放：每个对象的状态、持有人、事件条数和 seq 和迁移前相同
        states, evs, probs = flow.replay_all(flow.Project(self.proj))
        self.assertEqual(probs, [])
        for obj, old in old_states.items():
            self.assertEqual((states[obj]["state"], states[obj]["holder"], [r["seq"] for r in evs[obj]]),
                             (old["state"], old["holder"], old["seqs"]), obj)
        self.assertTrue(all(r["v"] == 2 for rows in evs.values() for r in rows))
        # 新格式：config.json、英文目录、目标卡只用编号；检查没有错误；链接有效
        self.assertEqual(json.loads((self.proj / "collab" / "config.json").read_text())["format"], flow.FORMAT)
        names = [p.relative_to(self.proj).as_posix() for p in self.proj.rglob("*") if migrate.BACKUP not in p.parts]
        self.assertFalse([n for n in names if n.startswith(("collab/", "work/")) and re.search(r"[一-鿿]", n.split("/")[1])])
        self.assertTrue((self.proj / "collab" / "goals" / "G001.md").exists())
        self.assertTrue((self.proj / "work" / "G001").is_dir())
        self.assertEqual([x["msg"] for x in flow.check(flow.Project(self.proj)) if x["level"] == "error"], [])
        self.assertEqual(broken_links(self.proj), [])
        self.assertIn(".collab-backup/", (self.proj / ".gitignore").read_text(encoding="utf-8"))
        # 第二次运行：没有改动
        after = tree(self.proj)
        r = self.init("migrate", str(self.proj))
        self.assertEqual(r.returncode, 0)
        self.assertIn("没有改动", r.stdout)
        self.assertEqual(tree(self.proj), after)
        # 回退：逐字节恢复（备份目录本身留着）
        r = self.init("migrate", "--rollback", str(self.proj))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(tree(self.proj), self.before)

    def test_same_as_new_build(self):
        """迁移出来的事件和新版直接生成的同一回演示逐字节相同；卡片和 PROGRESS 只差模板随版本改的部分以外的地方都一样。"""
        self.assertEqual(self.init("migrate", str(self.proj)).returncode, 0)
        fresh = self.tmp / "fresh"
        r = subprocess.run([sys.executable, str(ROOT / "demo" / "build.py"), "--到", "2", "--输出", str(fresh)], capture_output=True, text=True,
                           env={**ENV, "HOME": str(self.tmp)})
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in sorted((fresh / "collab" / "internal" / "flow").glob("*.jsonl")):
            self.assertEqual((self.proj / "collab" / "internal" / "flow" / f.name).read_text(encoding="utf-8"), f.read_text(encoding="utf-8"), f.name)
        for rel in ["collab/PROGRESS.md", "collab/goals/G001.md", "collab/issues/I001-治河方略之争.md"]:
            self.assertEqual((self.proj / rel).read_text(encoding="utf-8"), (fresh / rel).read_text(encoding="utf-8"), rel)
        for f in sorted((fresh / "collab" / "tasks").glob("G*.md")):
            self.assertEqual((self.proj / "collab" / "tasks" / f.name).read_text(encoding="utf-8"), f.read_text(encoding="utf-8"), f.name)

    def test_dry_run_changes_nothing(self):
        r = self.init("migrate", str(self.proj), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("目录 collab/内部/流转/ → collab/internal/flow/", r.stdout)
        self.assertIn("文件 collab/目标/G001-黄河决口：赈灾与治河.md → collab/goals/G001.md", r.stdout)
        self.assertEqual(tree(self.proj), self.before)

    def test_refuses_while_runs_are_live_and_old_layout(self):
        runs = self.proj / "collab" / "内部" / "运行记录"
        rec = json.loads(next(runs.glob("*.json")).read_text(encoding="utf-8"))
        (runs / "live.json").write_text(json.dumps({**rec, "run": "live", "status": "运行中", "pid": __import__("os").getpid()},
                                                   ensure_ascii=False), encoding="utf-8")
        r = self.init("migrate", str(self.proj))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("还有派活在跑", r.stdout)
        (runs / "live.json").unlink()
        self.assertEqual(tree(self.proj), self.before)
        shutil.rmtree(self.proj / "collab" / "内部")
        r = self.init("migrate", str(self.proj))
        self.assertIn("init.sh tidy", r.stdout)

    def test_mismatch_aborts_without_touching(self):
        """改写后回放和改写前不一致（这里模拟改写出错：G001-T1 的最后一条事件丢了接收方）就中止，项目不动。"""
        from unittest import mock
        real = migrate.legacy.event

        def broken(row, kind=None, paths=None):
            out = real(row, kind, paths)
            if row.get("对象") == "G001-T1" and row.get("边") == "派发":
                out["to"] = "none"
            return out
        lines = []
        with mock.patch.object(migrate.legacy, "event", broken):
            code = migrate.migrate_project(self.proj, out=lines.append)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("回放不一致" in x for x in lines), lines)
        self.assertEqual(tree(self.proj), self.before)
        self.assertFalse((self.proj / migrate.BACKUP).exists())

    def test_old_ledger_is_refused_by_new_flow(self):
        p = flow.Project(self.proj)
        self.assertTrue(p.needs_migration())
        with self.assertRaises(flow.FlowError):
            flow.record(p, "G001", "progress", {"from": "lead", "note": "x"})


class TestMigrateNow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "NOW"
        (self.data / "日历").mkdir(parents=True)
        (self.data / "班子").mkdir()
        (self.data / "系统").mkdir()
        (self.data / "安排.md").write_text("# 安排\n收工时把过去的行移到 归档/YYYY-MM.md。\n", encoding="utf-8")
        (self.data / "已完成.md").write_text("# 已完成\n", encoding="utf-8")
        (self.data / "日历" / "日历.md").write_text("# 日历\n", encoding="utf-8")
        (self.data / "班子" / "班子.json").write_text('{"成员": []}', encoding="utf-8")
        (self.data / "系统" / "版本.txt").write_text("工具包不动\n", encoding="utf-8")
        (self.data / "config.json").write_text(json.dumps({"deadlines": {"file": "截止.md"}}, ensure_ascii=False), encoding="utf-8")
        (self.data / "截止.md").write_text("# 截止\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_rename_and_rollback(self):
        before = tree(self.data, (migrate.NOW_BACKUP,))
        self.assertEqual(migrate.migrate_now(self.data, out=lambda *_: None), 0)
        for rel in ("schedule.md", "done.md", "calendar/calendar.md", "team/team.json", "deadlines.md"):
            self.assertTrue((self.data / rel).exists(), rel)
        self.assertFalse((self.data / "安排.md").exists())
        self.assertEqual(json.loads((self.data / "config.json").read_text())["deadlines"]["file"], "deadlines.md")
        self.assertIn("archive/YYYY-MM.md", (self.data / "schedule.md").read_text(encoding="utf-8"))
        self.assertTrue((self.data / "系统" / "版本.txt").exists())
        after = tree(self.data, (migrate.NOW_BACKUP,))
        self.assertEqual(migrate.migrate_now(self.data, out=lambda *_: None), 0)  # 第二次没有改动
        self.assertEqual(tree(self.data, (migrate.NOW_BACKUP,)), after)
        self.assertEqual(migrate.rollback_now(self.data, out=lambda *_: None), 0)
        self.assertEqual(tree(self.data, (migrate.NOW_BACKUP,)), before)
        self.assertEqual(flow.team_file().name in ("team.json", "班子.json"), True)


if __name__ == "__main__":
    unittest.main()
