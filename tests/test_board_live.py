"""看板数据分离与推送（G056-T2）：build.py 的 shell()/data()、/api/now、按文件指纹缓存、监视线程和 /api/events（SSE）。

全部用临时目录：样例 NOW 数据加一个探针模块（load.py 每跑一次记一笔），演示案例第 1 回作项目。
"""
import argparse
import http.client
import importlib.util
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


server = _load("board_server_live", SRC / "board" / "server.py")
sys.path.insert(0, str(ROOT / "demo"))  # 演示案例的 build.py 要导入同目录的 story_en
demo = _load("demo_build_live", ROOT / "demo" / "build.py")

PROBE_LOAD = '''from pathlib import Path


def load(ctx):
    f = ctx.data_dir / "probe-ran.txt"
    f.write_text(f.read_text() + "x" if f.exists() else "x")
    return {"n": 1}
'''


def make_now(tmp: Path, progress: Path) -> Path:
    """样例 NOW 数据目录，只启用探针模块；任务表链接演示项目的 PROGRESS.md。"""
    data = tmp / "NOW"
    shutil.copytree(SRC / "board" / "now" / "sample" / "NOW", data)
    cfg = json.loads((data / "config.json").read_text(encoding="utf-8"))
    cfg["modules"] = ["probe"]
    (data / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    m = data / "modules" / "probe"
    m.mkdir(parents=True)
    (m / "module.json").write_text(json.dumps({"name": "probe", "contract": 1, "tabs": [], "files": []}), encoding="utf-8")
    (m / "load.py").write_text(PROBE_LOAD, encoding="utf-8")
    (m / "view.js").write_text("// probe\n", encoding="utf-8")
    (tmp / "NOW.md").write_text(
        "# NOW\n\n## 任务\n\n| 任务 | 分类 | 等级 | 状态 |\n|---|---|---|---|\n"
        f"| [演示]({progress}) | 项目 | A | 进行中 |\n", encoding="utf-8")
    return data


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        cls.proj = demo.build(cls.tmp / "proj", 1)
        cls.progress = cls.proj / "collab" / "PROGRESS.md"
        cls.data = make_now(cls.tmp, cls.progress)
        cls.marker = cls.data / "probe-ran.txt"
        server.ARGS = argparse.Namespace(verbose=False, port=0, now_dir=str(cls.data), project=[str(cls.proj)], no_registry=True)
        server.WATCH = server.Watcher()
        server.CACHE.clear()
        server.NOW_DEPS.clear()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.pid = server.project_id(cls.proj.resolve())

    @classmethod
    def tearDownClass(cls):
        server.WATCH.stop()
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp)

    def req(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def runs(self):
        return len(self.marker.read_text()) if self.marker.exists() else 0

    def touch(self, f: Path, line: str) -> None:
        with f.open("a", encoding="utf-8") as fh:
            fh.write(line)

    # ---------- build.py ----------

    def test_shell_and_data(self):
        b = server.load_build()
        before = self.runs()
        sh = b.shell()
        self.assertEqual(self.runs(), before)  # 外壳不执行 load.py
        self.assertIn("let DATA = null;", sh)
        self.assertIn("// probe", sh)  # 模块 js 在外壳里
        deps = []
        d = b.collect(deps)
        self.assertEqual(self.runs(), before + 1)
        self.assertIn(self.progress, deps)
        payload = b.data(d)
        self.assertTrue(all("css" not in m and "js" not in m for m in payload["modules"]))
        self.assertEqual(payload["shell"], b.fingerprint(sh))
        self.assertEqual(payload["modules"][0]["data"], {"n": 1})
        # 独立页面 = 外壳 + 内嵌数据，和拆分前一样
        page = b.render(d)
        blob = json.dumps({k: v for k, v in payload.items() if k != "shell"}, ensure_ascii=False).replace("</", "<\\/")
        self.assertEqual(page, sh.replace("let DATA = null;", "let DATA = " + blob + ";"))
        self.assertTrue(set(b.shell_sources()) >= {b.TEMPLATE, b.CONFIG, self.data / "modules" / "probe" / "view.js"})

    # ---------- 缓存和 304 ----------

    def test_root_304_and_cached(self):
        r1, b1 = self.req("/")
        self.assertEqual(r1.status, 200)
        self.assertIn(b"now-inject.js", b1)
        n = self.runs()
        r2, b2 = self.req("/", {"If-None-Match": r1.getheader("ETag")})
        self.assertEqual((r2.status, b2), (304, b""))
        self.assertEqual(self.runs(), n)  # 依赖没变不重算

    def test_api_now(self):
        r, body = self.req("/api/now")
        self.assertEqual(r.status, 200)
        d = json.loads(body)
        self.assertEqual(d["shell"], r.getheader("X-Board-Shell"))
        self.assertTrue(all("js" not in m for m in d["modules"]))
        self.assertEqual(d["now"]["tasks"][0]["name"], "演示")
        n = self.runs()
        r2, b2 = self.req("/api/now", {"If-None-Match": r.getheader("ETag")})
        self.assertEqual((r2.status, b2), (304, b""))
        self.assertEqual(self.runs(), n)
        # 改了依赖（任务的 PROGRESS.md）就重算
        self.touch(self.progress, "\n")
        r3, _ = self.req("/api/now", {"If-None-Match": r.getheader("ETag")})
        self.assertEqual(self.runs(), n + 1)
        self.assertIn(r3.status, (200, 304))

    def test_cache_ttl(self):
        self.req("/api/now")
        n = self.runs()
        sig, t0, out = server.CACHE["now"]
        server.CACHE["now"] = (sig, t0 - server.CACHE_TTL - 1, out)  # 到期：依赖以外的数据（如专注计时）也要过一阵重算
        self.req("/api/now")
        self.assertEqual(self.runs(), n + 1)

    def test_project_cache(self):
        calls = []
        orig = server.project_data
        server.project_data = lambda p: calls.append(1) or orig(p)
        try:
            r1, b1 = self.req(f"/api/p/{self.pid}")
            self.assertEqual(r1.status, 200)
            r2, _ = self.req(f"/api/p/{self.pid}", {"If-None-Match": r1.getheader("ETag")})
            self.assertEqual(r2.status, 304)
            self.assertEqual(len(calls), 1)  # 账本没变不重算
            self.touch(self.progress, "\n")
            self.req(f"/api/p/{self.pid}")
            self.assertEqual(len(calls), 2)
        finally:
            server.project_data = orig

    # ---------- 指纹 ----------

    def test_tree_sig(self):
        d = self.tmp / "tree"
        (d / "a").mkdir(parents=True)
        (d / "a" / "x.md").write_text("1")
        s0 = server.tree_sig(d)
        self.assertEqual(server.tree_sig(d), s0)
        (d / "a" / "y.md").write_text("2")
        s1 = server.tree_sig(d)
        self.assertNotEqual(s1, s0)
        (d / "a" / "y.md").unlink()
        self.assertNotEqual(server.tree_sig(d), s1)

    # ---------- 监视线程和 SSE ----------

    def sse(self, timeout=8):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        s.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        return s, s.makefile("rb")

    def next_event(self, f, deadline):
        """读到下一条 event: change 或心跳注释，返回 (类型, 数据)。"""
        lines = []
        while time.monotonic() < deadline:
            line = f.readline()
            if not line:
                return None, None
            line = line.decode("utf-8").rstrip("\r\n")
            if line == "":
                if lines:
                    if lines[0].startswith(":"):
                        return "ping", None
                    if lines[0] == "event: change":
                        return "change", json.loads(lines[1][len("data: "):])
                lines = []
                continue
            lines.append(line)
        return None, None

    def test_events_push(self):
        server.WATCH.start()
        s, f = self.sse()
        try:
            head = []
            while True:
                line = f.readline()
                head.append(line)
                if line in (b"\r\n", b"\n"):
                    break
            self.assertIn(b"text/event-stream", b"".join(head))
            kind, v0 = self.next_event(f, time.monotonic() + 5)
            self.assertEqual(kind, "change")
            self.assertIn("now", v0)
            self.assertIn("shell", v0)
            self.discover_wait()
            for target, key in ((self.data.parent / "NOW.md", "now"), (self.progress, "p:" + self.pid)):
                _, cur = server.WATCH.snapshot()
                n = self.runs()
                t0 = time.monotonic()
                self.touch(target, "\n<!-- t2 -->\n")
                got = None
                while time.monotonic() - t0 < 3:
                    kind, v = self.next_event(f, t0 + 3)
                    if kind == "change" and v.get(key) != cur.get(key):
                        got = time.monotonic() - t0
                        break
                self.assertIsNotNone(got, key)
                self.assertLess(got, 2.0, key)  # 验收：改了 2 秒内推出新版本号
                self.assertEqual(self.runs(), n)  # 监视线程不执行模块的 load.py
        finally:
            s.close()

    def discover_wait(self):
        deadline = time.monotonic() + 5
        while "p:" + self.pid not in server.WATCH.snapshot()[1] and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIn("p:" + self.pid, server.WATCH.snapshot()[1])

    def test_heartbeat_and_limit(self):
        server.WATCH.start()
        hb, cap = server.HEARTBEAT, server.SSE_MAX
        server.HEARTBEAT, server.SSE_MAX = 0.5, server.SSE_OPEN[0] + 1  # 别的用例留下的连接要到下次写心跳才发现断开
        s, f = self.sse()
        try:
            kinds = []
            deadline = time.monotonic() + 4
            while "ping" not in kinds and None not in kinds:
                kinds.append(self.next_event(f, deadline)[0])
            self.assertIn("ping", kinds)
            r, _ = self.req("/api/events")  # 超过上限
            self.assertEqual(r.status, 503)
        finally:
            s.close()
            deadline = time.monotonic() + 3  # 断开后名额要还回来（下一次写心跳时发现断开）
            while server.SSE_OPEN[0] >= server.SSE_MAX and time.monotonic() < deadline:
                time.sleep(0.1)
            server.HEARTBEAT, server.SSE_MAX = hb, cap
        self.assertLess(server.SSE_OPEN[0], server.SSE_MAX)

    def test_versions_and_round(self):
        server.WATCH.start()
        r, body = self.req("/api/versions")
        d = json.loads(body)
        self.assertIn("now", d["versions"])
        self.assertLess(server.WATCH.round_ms, server.SLOW_ROUND_MS)  # 单轮 stat < 20ms
        server.WATCH.scan()  # 先收下前面用例改的文件
        seq, _ = server.WATCH.snapshot()
        self.assertEqual(server.WATCH.scan(), [])  # 没变化时什么都不推
        self.assertEqual(server.WATCH.snapshot()[0], seq)


if __name__ == "__main__":
    unittest.main()
