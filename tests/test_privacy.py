"""两个仓库稳定更新（G059）。隐私检查前移到测试：按 release/屏蔽词.txt 和 release/放行.txt 扫导出白名单（src、tests、demo）和 release/public/，
规则和 release/export.sh 一致。扫的是 git 跟踪的文件（含已 git add 未提交的）和还没 add、也没被忽略的新文件，录样本带了用户名当场就红。
公开仓库里没有 release/，自动跳过。
另有 release/sync.sh 和 src/core/publish.sh 推送部分的用例：全在临时目录里建开发仓库、裸仓库当 origin 和公开仓库，不碰真的远端和 ../collab。"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
SCOPE = ("src", "tests", "demo", "release/public")
# export.sh 不导出的生成目录（rsync --exclude），这里也不扫
SKIP = ("demo/万历新政/", "demo/站点/")


def rules(name: str) -> list:
    path = RELEASE / name
    if not path.exists():
        return []
    return [s for s in (l.strip() for l in path.read_text(encoding="utf-8").splitlines()) if s and not s.startswith("#")]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def candidates() -> dict:
    """{相对路径: [要查的内容（bytes）]}：工作区内容；已暂存且和工作区不同的，再查一份暂存区里的"""
    names = [n for n in git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *SCOPE).split("\0") if n]
    staged = {n for n in git("diff", "-z", "--cached", "--name-only", "--", *SCOPE).split("\0") if n}
    out = {}
    for n in names:
        if n.startswith(SKIP):
            continue
        blobs = []
        p = ROOT / n
        if p.is_file():
            blobs.append(p.read_bytes())
        if n in staged or not p.is_file():
            r = subprocess.run(["git", "-C", str(ROOT), "show", f":{n}"], capture_output=True)
            if r.returncode == 0:
                blobs.append(r.stdout)
        out[n] = blobs
    return out


def hits(pattern: re.Pattern, allow, files: dict) -> list:
    found = []
    for name, blobs in files.items():
        if pattern.search(name):
            found.append(f"{name}（文件名）")
        for blob in blobs:
            if b"\0" in blob[:8192]:  # 二进制，和 grep -I 一样跳过
                continue
            for i, line in enumerate(blob.decode("utf-8", "replace").splitlines(), 1):
                rest = allow.sub("", line) if allow else line
                if pattern.search(rest):
                    found.append(f"{name}:{i}: {line.strip()[:120]}")
    return sorted(set(found))


class PrivacyTest(unittest.TestCase):
    def test_no_blocked_words(self):
        words = rules("屏蔽词.txt")
        if not words:
            self.skipTest("没有 release/屏蔽词.txt（公开仓库里正常跳过）")
        pattern = re.compile("|".join(f"(?:{w})" for w in words), re.I)
        allowed = rules("放行.txt")  # 和 export.sh 的 sed 一样区分大小写
        allow = re.compile("|".join(f"(?:{w})" for w in allowed)) if allowed else None
        found = hits(pattern, allow, candidates())
        self.assertEqual(found, [], "屏蔽词命中（换成占位写法；确需公开的写进 release/放行.txt 并经总裁同意）：\n" + "\n".join(found))


SYNC = RELEASE / "sync.sh"
BLOCKED = "zqxsecretword"  # 临时仓库自己的屏蔽词，虚构


def sh(*args, cwd=None, env=None, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True, errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"{args} 失败：\n{r.stdout}\n{r.stderr}")
    return r


@unittest.skipUnless(SYNC.exists(), "没有 release/sync.sh（公开仓库里正常跳过）")
class SyncTest(unittest.TestCase):
    """临时目录：dev（开发仓库，带 src 拷贝和 release 脚本）、origin.git（私有远端）、pub.git + pub（公开仓库）"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        home = self.tmp / "home"
        home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "COLLAB_"))}
        self.env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", COLLAB_LANG="zh",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.dev = self.tmp / "dev"
        self.origin = self.tmp / "origin.git"
        self.pub = self.tmp / "pub"
        self.pubgit = self.tmp / "pub.git"
        d = self.dev
        shutil.copytree(ROOT / "src", d / "src", ignore=shutil.ignore_patterns("build", "__pycache__", ".DS_Store"))
        (d / "release" / "public").mkdir(parents=True)
        for f in ("sync.sh", "export.sh"):
            shutil.copy2(RELEASE / f, d / "release" / f)
        (d / "release" / "屏蔽词.txt").write_text(f"# 虚构\n{BLOCKED}\n", encoding="utf-8")
        (d / "release" / "放行.txt").write_text("# 无\n", encoding="utf-8")
        (d / "release" / "public" / "README.md").write_text("# 公开首页\n", encoding="utf-8")
        (d / "release" / "public" / "gitignore").write_text("__pycache__/\n", encoding="utf-8")
        (d / "tests").mkdir()
        (d / "tests" / "test_ok.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n"
                                                "    def test_ok(self):\n        pass\n", encoding="utf-8")
        (d / "demo").mkdir()
        (d / "demo" / "build.py").write_text("print('demo ok')\n", encoding="utf-8")
        (d / "collab" / "goals").mkdir(parents=True)
        (d / "collab" / "goals" / "G901.md").write_text("# G901 看板换新皮肤\n", encoding="utf-8")
        (d / "collab" / "goals" / "G902.md").write_text("# G902 只改账本\n", encoding="utf-8")
        self.git(d, "init", "-q", "-b", "main")
        self.git(d, "add", "-A")
        self.git(d, "commit", "-q", "-m", "初始")
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.origin)
        self.git(d, "remote", "add", "origin", self.origin)
        self.git(d, "push", "-q", "origin", "main")
        # 公开仓库：旧写法「跟上新版（开发仓库 <hash>）」，来源是初始提交
        self.base = self.git(d, "rev-parse", "--short", "HEAD").stdout.strip()
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.pubgit)
        self.git(self.tmp, "init", "-q", "-b", "main", self.pub)
        (self.pub / "README.md").write_text("# 公开首页\n", encoding="utf-8")
        self.git(self.pub, "add", "-A")
        self.git(self.pub, "commit", "-q", "-m", f"跟上新版（开发仓库 {self.base}）：首版")
        self.git(self.pub, "remote", "add", "origin", self.pubgit)
        self.git(self.pub, "push", "-q", "origin", "main")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def git(self, cwd, *args, check=True):
        return sh("git", "-C", cwd, *args, env=self.env, check=check)

    def commit(self, path: str, text: str, msg: str):
        p = self.dev / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self.git(self.dev, "add", "-A")
        self.git(self.dev, "commit", "-q", "-m", msg)

    def sync(self, *args):
        return sh("bash", self.dev / "release" / "sync.sh", *args, self.pub, env=self.env, check=False)

    def ref(self, repo, name="main"):
        return self.git(repo, "rev-parse", name).stdout.strip()

    def test_dry_run_stops_before_commit_then_push(self):
        self.commit("src/core/README.md", "改了说明\n", "G901-T1：看板换皮肤，说明同步")
        self.commit("collab/goals/G902.md", "# G902 只改账本\n改\n", "G902：只改账本")
        head = self.ref(self.dev, "HEAD")
        origin0, pub0, pubgit0 = self.ref(self.origin), self.ref(self.pub, "HEAD"), self.ref(self.pubgit)

        r = self.sync()
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("共 2 个提交，改了公开内容的 1 个", out)
        self.assertIn("- G901 看板换新皮肤", out)
        self.assertNotIn("G902", out.split("区间内的目标")[1])
        self.assertIn("== 提交信息 ==\n更新", out)
        self.assertIn("README 提示", out)
        self.assertIn("src/core/README.md", out)
        self.assertIn("停在提交前", out)
        # 不加 --push：哪里都没提交、没推送
        self.assertEqual((self.ref(self.origin), self.ref(self.pub, "HEAD"), self.ref(self.pubgit)), (origin0, pub0, pubgit0))
        self.assertTrue((self.pub / "src" / "core" / "README.md").exists())  # 导出到了公开仓库工作区

        r = self.sync("--push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ref(self.origin), head)
        self.assertEqual(self.ref(self.pubgit), self.ref(self.pub, "HEAD"))
        # 公开提交信息只有一行中性标题，不带目标和来源
        self.assertEqual(self.git(self.pub, "log", "-1", "--format=%B").stdout.strip(), "更新")
        # 来源记在开发仓库标签 public-synced，并推到私有仓库
        self.assertEqual(self.ref(self.dev, "public-synced^{commit}"), head)
        self.assertEqual(self.ref(self.origin, "public-synced^{commit}"), head)
        r = self.sync("--status")
        self.assertIn("已是最新", r.stdout)
        r = self.sync()
        self.assertIn("公开仓库已是最新，不用同步", r.stdout)

        # --message 可换标题；标签优先于公开仓库里的旧来源写法
        self.commit("src/core/新功能.txt", "x\n", "G901-T2：新功能")
        r = self.sync("--push", "--message", "v0.2.0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("共 1 个提交", r.stdout)
        self.assertEqual(self.git(self.pub, "log", "-1", "--format=%B").stdout.strip(), "v0.2.0")

    def test_stops_on_uncommitted_and_on_blocked_word(self):
        (self.dev / "src" / "新文件.txt").write_text("x\n", encoding="utf-8")
        r = self.sync()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("未提交", r.stderr)
        (self.dev / "src" / "新文件.txt").unlink()
        self.commit("tests/样本.txt", f"ls -l 输出 {BLOCKED}\n", "G901-T2：录样本")
        r = self.sync()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("隐私检查未通过", r.stderr)
        self.assertFalse((self.pub / "tests").exists())

    def test_stops_when_export_did_not_finish(self):
        # bash 3.2 下 export.sh 中途因 set -u 之类中止时退出码可能是 0，sync.sh 还要看它最后一行
        (self.dev / "release" / "export.sh").write_text("#!/usr/bin/env bash\necho 隐私检查通过\n", encoding="utf-8")
        self.commit("src/core/新功能.txt", "x\n", "G901-T1：新功能")
        r = self.sync()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("export.sh 没有走完", r.stderr)
        self.assertNotIn("== 提交信息 ==", r.stdout)

    def test_no_readme_hint_when_public_readme_changed(self):
        self.commit("src/core/README.md", "改了说明\n", "G901-T1：说明")
        self.commit("release/public/README.md", "# 公开首页\n新功能\n", "G901-T2：公开 README 同步")
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("README 提示", r.stdout)

    def publish(self, *args, extra=None):
        env = {**self.env, "COLLAB_PUBLIC": str(self.pub), **(extra or {})}
        return sh("bash", self.dev / "src" / "core" / "publish.sh", *args, env=env, check=False)

    def test_publish_without_switch_does_not_push(self):
        # 没有 .publish-push（别人从公开仓库拿到的 publish.sh 默认就是这样）：不推，只报多几个提交和怎么开
        self.commit("src/core/新功能.txt", "x\n", "G901-T1：新功能")
        self.commit("collab/goals/G902.md", "改\n", "G902：只改账本")
        origin0 = self.ref(self.origin)
        r = self.publish(self.tmp / "系统")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertTrue((self.tmp / "系统" / "core" / "新功能.txt").exists())
        self.assertIn("私有仓库比 origin 多 2 个提交（自动推送没开：touch", out)
        self.assertIn(".publish-push", out)
        self.assertNotIn("已推送", out)
        self.assertEqual(self.ref(self.origin), origin0)
        self.assertIn("公开仓库落后 1 个提交：G901", out)

    def test_publish_with_switch_pushes_private_and_reports_public_lag(self):
        (self.dev / ".publish-push").write_text("", encoding="utf-8")
        self.commit("src/core/新功能.txt", "x\n", "G901-T1：新功能")
        self.commit("collab/goals/G902.md", "改\n", "G902：只改账本")
        head = self.ref(self.dev, "HEAD")
        r = self.publish(self.tmp / "系统")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertTrue((self.tmp / "系统" / "core" / "新功能.txt").exists())
        self.assertIn("私有仓库：已推送 main 到 origin", out)
        self.assertEqual(self.ref(self.origin), head)
        self.assertIn("公开仓库落后 1 个提交：G901", out)
        self.assertEqual(self.ref(self.pubgit), self.ref(self.pub, "HEAD"))  # 公开仓库不动

    def test_publish_switch_names_remote(self):
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.tmp / "backup.git")
        self.git(self.dev, "remote", "add", "backup", self.tmp / "backup.git")
        (self.dev / ".publish-push").write_text("backup\n", encoding="utf-8")
        origin0 = self.ref(self.origin)
        r = self.publish(self.tmp / "系统")
        self.assertIn("私有仓库：已推送 main 到 backup", r.stdout, r.stdout + r.stderr)
        self.assertEqual(self.ref(self.tmp / "backup.git"), self.ref(self.dev, "HEAD"))
        self.assertEqual(self.ref(self.origin), origin0)

    def test_publish_core_module_dirty_do_not_push(self):
        (self.dev / ".publish-push").write_text("", encoding="utf-8")
        self.commit("src/core/新功能.txt", "x\n", "G901-T1：新功能")
        origin0 = self.ref(self.origin)
        for args in (("--core", self.tmp / "核心"), ("--module", "schedule", self.tmp / "模块"), ("--dirty", self.tmp / "试验")):
            r = self.publish(*args)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("私有仓库", r.stdout)
            self.assertNotIn("公开仓库", r.stdout)
        self.assertEqual(self.ref(self.origin), origin0)

    def test_publish_push_failure_only_warns(self):
        (self.dev / ".publish-push").write_text("", encoding="utf-8")
        self.git(self.dev, "remote", "set-url", "origin", self.tmp / "没有这个仓库.git")
        r = self.publish(self.tmp / "系统")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.tmp / "系统" / "版本.txt").exists() or any((self.tmp / "系统").iterdir()))
        self.assertIn("推送失败（发布不受影响）", r.stdout)
        self.assertIn("公开仓库：已是最新", r.stdout)


if __name__ == "__main__":
    unittest.main()
