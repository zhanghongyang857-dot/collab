"""NOW 页按需重画（G056-T3）：/ 给外壳、页面自己拉 /api/now；live.js 订阅推送、断线重连、切回前台补拉、三态标记。

服务端部分沿用 test_board_live 的临时 NOW 数据和演示项目；live.js 的行为用 node 跑（没装 node 时跳过），
浏览器里的整页行为（改 NOW.md 后重画、保留标签和滚动、外壳变了重载）见 work/G056/G056-T3/ 的实测记录。
"""
import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import test_board_live as base

ROOT = base.ROOT
SRC = base.SRC
server = base.server
TEMPLATE = SRC / "board" / "now" / "template.html"
LIVE_JS = SRC / "board" / "static" / "live.js"
INJECT_JS = SRC / "board" / "static" / "now-inject.js"


class Shell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        cls.proj = base.demo.build(cls.tmp / "proj", 1)
        cls.data = base.make_now(cls.tmp, cls.proj / "collab" / "PROGRESS.md")
        server.ARGS = argparse.Namespace(verbose=False, port=0, now_dir=str(cls.data), project=[str(cls.proj)], no_registry=True)
        server.WATCH = server.Watcher()
        server.CACHE.clear()
        server.NOW_DEPS.clear()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

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

    def test_root_is_shell(self):
        r, body = self.req("/")
        page = body.decode("utf-8")
        self.assertEqual(r.status, 200)
        self.assertIn("let DATA = null;", page)  # 不含数据
        self.assertNotIn(str(self.proj), page)  # 任务链接的路径只在数据里
        self.assertLess(page.index("/static/live.js"), page.index("/static/now-inject.js"))
        fp = re.search(r'<meta name="board-shell" content="([0-9a-f]+)">', page).group(1)
        ra, data = self.req("/api/now")
        self.assertEqual(json.loads(data)["shell"], fp)
        self.assertEqual(ra.getheader("X-Board-Shell"), fp)

    def test_data_change_keeps_shell(self):
        r1, _ = self.req("/")
        a1, _ = self.req("/api/now")
        now_md = self.tmp / "NOW.md"
        now_md.write_text(now_md.read_text(encoding="utf-8").replace("[演示]", "[演示 T3]"), encoding="utf-8")
        server.CACHE.clear()  # 不等文件时间戳精度，直接让下次重算
        r2, b2 = self.req("/", {"If-None-Match": r1.getheader("ETag")})
        self.assertEqual((r2.status, b2), (304, b""))  # 数据变了外壳不变：页面不重载
        a2, _ = self.req("/api/now", {"If-None-Match": a1.getheader("ETag")})
        self.assertEqual(a2.status, 200)
        a3, b3 = self.req("/api/now", {"If-None-Match": a2.getheader("ETag")})
        self.assertEqual((a3.status, b3), (304, b""))

    def test_live_js_served(self):
        self.assertIn("live.js", server.STATIC_FILES)
        r, body = self.req("/static/live.js")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/javascript"))
        self.assertIn(b"window.BoardLive", body)

    def test_standalone_embeds_data(self):
        b = server.load_build()
        page = b.render(b.collect())
        self.assertRegex(page, r"let DATA = \{")
        self.assertIn("if (DATA) apply(DATA);", page)  # 内嵌数据直接画
        self.assertNotIn("/static/live.js", page)  # 不连推送
        self.assertNotIn("/static/now-inject.js", page)


class Fingerprint(unittest.TestCase):
    def test_shell_same_across_processes(self):
        """外壳指纹每个进程都一样：语言包 names 的键序来自集合，不排序时服务一重启指纹就变，各端都会整页重载。"""
        code = ("import importlib.util, os, sys\n"
                "spec = importlib.util.spec_from_file_location('b', sys.argv[1]); b = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(b); print(b.fingerprint(b.shell()))")
        env = {**os.environ, "NOW_DATA_DIR": str(SRC / "board" / "now" / "sample" / "NOW")}
        fps = {subprocess.run([sys.executable, "-c", code, str(SRC / "board" / "now" / "build.py")], capture_output=True, text=True,
                              env={**env, "PYTHONHASHSEED": str(seed)}, check=True).stdout.strip() for seed in (1, 2, 3)}
        self.assertEqual(len(fps), 1, fps)


class Source(unittest.TestCase):
    def test_no_timer_or_reload(self):
        t = TEMPLATE.read_text(encoding="utf-8")
        self.assertNotIn("setInterval(render", t)  # 去掉每 30 秒整块重画，改为每分钟保留现场重画
        self.assertIn("function refresh()", t)
        self.assertIn('"If-None-Match"', t)
        self.assertIn('cache: "no-store"', t)
        self.assertNotIn("location.reload", INJECT_JS.read_text(encoding="utf-8"))

    def test_module_js_runs_after_data(self):
        t = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("function NOW_LOAD_MODULES() {\n/*MODULE_JS*/\n}", t)


# live.js 在 node 里跑：假的 EventSource、fetch、document、计时器（手动推进）
HARNESS = r"""
const fs = require("fs");
let now = 0, timers = [], tid = 0;
const flush = () => new Promise((r) => setImmediate(r));  // 跑完排队的 Promise 回调
global.setTimeout = (f, ms) => { const id = ++tid; timers.push({id, at: now + (ms || 0), f}); return id; };
global.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
async function advance(ms) {
  const end = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > end) break;
    timers.shift(); now = t.at; t.f();
    await flush();
  }
  now = end;
  await flush();
}
const docL = {}, winL = {};
global.document = { visibilityState: "visible", addEventListener: (e, f) => { (docL[e] = docL[e] || []).push(f); } };
global.window = { addEventListener: (e, f) => { (winL[e] = winL[e] || []).push(f); },
  t: (k, v) => k + (v ? JSON.stringify(v) : "") };
Object.defineProperty(globalThis, "navigator", {value: {onLine: true}, configurable: true});
const store = {};
global.sessionStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
let reloads = 0;
global.location = { reload: () => { reloads++; } };
const sources = [];
global.EventSource = class { constructor(url) { this.url = url; this.l = {}; this.closed = false; sources.push(this); }
  addEventListener(e, f) { this.l[e] = f; } close() { this.closed = true; }
  push(v) { this.l.change({data: JSON.stringify(v)}); } };
let fetches = [], versionsOk = true, versions = {};
global.fetch = (url) => { fetches.push(url);
  return versionsOk ? Promise.resolve({ok: true, json: () => Promise.resolve({versions})}) : Promise.reject(new Error("down")); };
eval(fs.readFileSync(process.argv[2], "utf8"));
const BL = window.BoardLive;
const log = [];
const out = {};
(async () => {
  const live = BL.start({ watch: ["now"], shell: "s1",
    onChange: (keys, v) => log.push(["change", keys, v.now]), onResume: () => log.push(["resume"]) });
  const states = [];
  live.onState((s) => states.push(s));
  out.connecting = live.state;
  const es = sources[0];
  es.push({now: 5, "p:x": 1, shell: "s1"});           // 第一条：now 和本页不同 → 回调；p:x 不关心
  es.push({now: 5, "p:x": 2, shell: "s1"});           // now 没变 → 不回调
  live.seen("now", 7);
  es.push({now: 7, shell: "s1"});                      // 页面已拉到 7 → 不回调
  es.push({now: 8, shell: "s1"});                      // 变了 → 回调
  out.afterPush = JSON.parse(JSON.stringify(log)); out.state = live.state;
  es.push({now: 8, shell: "s2"});                      // 外壳变了 → 重载一次
  es.push({now: 8, shell: "s2"});
  out.reloads = reloads;
  // 断线：退回拉 /api/versions；Mac 在时仍是实时，版本号变了照常回调
  log.length = 0; versions = {now: 9, shell: "s1"};
  es.onerror();
  await advance(10);
  out.pollFetches = fetches.filter((u) => u === "/api/versions").length;
  out.afterPoll = JSON.parse(JSON.stringify(log)); out.pollState = live.state;
  // Mac 不在：两次失败后标离线，文字带上次连上的时间
  versionsOk = false;
  await advance(2000);  // 再拉一次失败（fails=1 → 连接中）
  await advance(1000);  // 1 秒后重连推送
  sources[sources.length - 1].onerror();  // 又失败 → fails=2
  await advance(10);
  out.offline = live.state;
  out.label = BL.label(live.state, new Date(2026, 10, 14, 9, 5));
  // 恢复：重连上推送，第一条就追上
  versionsOk = true;
  await advance(3000);
  const es2 = sources[sources.length - 1];
  log.length = 0;
  es2.push({now: 10, shell: "s1"});
  out.recovered = live.state; out.afterRecover = JSON.parse(JSON.stringify(log));
  // 切回前台：重连并回调 onResume
  const n = sources.length; log.length = 0;
  docL.visibilitychange.forEach((f) => f());
  out.resumeNewSource = sources.length === n + 1; out.afterResume = JSON.parse(JSON.stringify(log));
  // 前台 5 分钟兜底
  log.length = 0; sources[sources.length - 1].push({now: 10, shell: "s1"});
  await advance(300000);
  out.fallback = log.filter((x) => x[0] === "resume").length;
  out.states = states;
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


@unittest.skipUnless(shutil.which("node"), "没装 node")
class LiveJs(unittest.TestCase):
    def test_live_js(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "harness.js"
            h.write_text(HARNESS, encoding="utf-8")
            r = subprocess.run(["node", str(h), str(LIVE_JS)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["connecting"], "connecting")
        self.assertEqual(out["afterPush"], [["change", ["now"], 5], ["change", ["now"], 8]])
        self.assertEqual(out["state"], "live")
        self.assertEqual(out["reloads"], 1)  # 同一个新外壳只重载一次
        self.assertEqual(out["pollFetches"], 1)
        self.assertEqual(out["afterPoll"], [["change", ["now"], 9]])
        self.assertEqual(out["pollState"], "live")
        self.assertEqual(out["offline"], "offline")
        self.assertEqual(out["label"], 'board.live.offline_since{"t":"09:05"}')
        self.assertEqual(out["recovered"], "live")
        self.assertEqual(out["afterRecover"], [["change", ["now"], 10]])
        self.assertTrue(out["resumeNewSource"])
        self.assertEqual(out["afterResume"], [["resume"]])
        self.assertEqual(out["fallback"], 1)
        self.assertEqual(out["states"][:3], ["connecting", "live", "connecting"])
        self.assertIn("offline", out["states"])


if __name__ == "__main__":
    unittest.main()
