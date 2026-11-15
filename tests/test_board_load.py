"""看板降负载（G056-T9）：项目块拆成账本 p:<项目> 和运行 r:<项目> 两类版本；运行类最多 RUN_MIN 秒推一次、重算一次；
/api/projects、/api/meetings 等按依赖文件指纹缓存，同一块的并发请求只算一次；NOW 页摘要最多 60 秒拉一次、不看运行类；
根路径的触屏图标。

服务端部分沿用 test_board_live 的临时 NOW 数据和演示项目；前端（live.js、now-inject.js）用 node 跑（没装 node 时跳过）。
有成员运行时看板进程的 CPU、请求量修前修后对比见 work/G056/G056-T9/实测记录.md。
"""
import argparse
import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import test_board_live as base

server = base.server
STATIC = base.SRC / "board" / "static"


class Load(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        cls.proj = base.demo.build(cls.tmp / "proj", 5)
        cls.collab = cls.proj / "collab"
        cls.runs = cls.collab / "internal" / "runs"
        cls.runs.mkdir(parents=True, exist_ok=True)
        cls.data = base.make_now(cls.tmp, cls.collab / "PROGRESS.md")
        server.ARGS = argparse.Namespace(verbose=False, port=0, now_dir=str(cls.data), project=[str(cls.proj)], no_registry=True)
        server.WATCH = server.Watcher()
        server.CACHE.clear()
        server.NOW_DEPS.clear()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.p = next(p for p in server.discover() if Path(p["root"]) == cls.proj)
        cls.pid = cls.p["id"]
        server.WATCH.scan()

    @classmethod
    def tearDownClass(cls):
        server.WATCH.stop()
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp)

    def req(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    n = 0

    def write_run(self):
        """假成员写一次运行流（只动 internal/runs/）。"""
        Load.n += 1
        with (self.runs / "G900-T1-01.stream.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"n": Load.n}) + "\n")

    def touch_ledger(self):
        with (self.collab / "PROGRESS.md").open("a", encoding="utf-8") as f:
            f.write("\n")

    # ---------- 指纹 ----------

    def test_ledger_and_run_sigs(self):
        l0, r0 = server.ledger_sig(self.p), server.run_sig(self.p)
        self.write_run()
        self.assertEqual(server.ledger_sig(self.p), l0)  # 运行流变了，账本指纹不变
        r1 = server.run_sig(self.p)
        self.assertNotEqual(r1, r0)
        self.touch_ledger()
        self.assertNotEqual(server.ledger_sig(self.p), l0)
        self.assertEqual(server.run_sig(self.p), r1)

    # ---------- 监视线程：运行类最多 RUN_MIN 秒加一次版本号 ----------

    def test_run_versions_throttled(self):
        w = server.WATCH
        w.scan()
        k, pk = "r:" + self.pid, "p:" + self.pid
        self.write_run()
        w.run_bumped[k] = 0  # 上次加版本号是很久以前：这次马上加
        self.assertIn(k, w.scan())
        v1 = w.versions[k]
        self.write_run()
        self.assertNotIn(k, w.scan())  # 不到 RUN_MIN 秒：压着
        self.assertEqual(w.versions[k], v1)
        p0 = w.versions.get(pk)
        self.touch_ledger()
        got = w.scan()
        self.assertIn(pk, got)  # 账本照旧马上推（PROGRESS.md 也在 NOW 的依赖里，now 也会变）
        self.assertNotIn(k, got)
        self.assertNotEqual(w.versions[pk], p0)
        w.run_bumped[k] -= server.RUN_MIN  # 到点：压着的那次变化补上
        self.assertIn(k, w.scan())
        self.assertNotEqual(w.versions[k], v1)
        self.assertEqual(w.scan(), [])

    # ---------- memo：运行类只变时最多 RUN_MIN 秒重算一次；账本变了马上算；并发合并 ----------

    def test_memo_run_throttle(self):
        calls = []
        sig = {"l": "a", "r": "1"}
        key = "test:memo"
        server.CACHE.pop(key, None)
        server.WATCH.versions["r:test"] = 5
        f = lambda: (sig["l"], sig["r"])  # noqa: E731
        comp = lambda: calls.append(1) or len(calls)  # noqa: E731
        self.assertEqual(server.memo(key, f, comp, "r:test"), (1, "5"))
        sig["r"] = "2"
        server.WATCH.versions["r:test"] = 6
        self.assertEqual(server.memo(key, f, comp, "r:test"), (1, "5"))  # 只有运行变了、不到 10 秒：上次结果和它的版本号
        server.CACHE[key]["t"] -= server.RUN_MIN
        self.assertEqual(server.memo(key, f, comp, "r:test"), (2, "6"))
        sig["l"] = "b"
        self.assertEqual(server.memo(key, f, comp, "r:test")[0], 3)  # 账本变了马上算
        self.assertEqual(server.memo(key, f, comp, "r:test"), (3, "6"))
        server.CACHE[key]["t"] -= server.CACHE_TTL
        self.assertEqual(server.memo(key, f, comp, "r:test")[0], 4)  # 指纹没变也最多 CACHE_TTL 秒重算一次
        server.WATCH.versions.pop("r:test", None)

    def test_memo_coalesces(self):
        calls = []
        key = "test:together"
        server.CACHE.pop(key, None)

        def slow():
            calls.append(1)
            time.sleep(0.3)
            return "x"
        got = []
        ts = [threading.Thread(target=lambda: got.append(server.memo(key, lambda: ("l", "r"), slow)[0])) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(calls), 1)  # 六个并发请求只算一次
        self.assertEqual(got, ["x"] * 6)

    # ---------- 接口：按指纹缓存、304、命中耗时 ----------

    def test_projects_meetings_cached(self):
        counts = {"discover": 0, "meetings": 0}
        orig_d, orig_m = server.discover, server.meetings

        def d():
            counts["discover"] += 1
            return orig_d()

        def m():
            counts["meetings"] += 1
            return orig_m()
        server.discover, server.meetings = d, m
        server.CACHE.pop("projects", None)
        server.CACHE.pop("meetings", None)
        try:
            for path in ("/api/projects", "/api/meetings"):
                r, _ = self.req(path)
                self.assertEqual(r.status, 200)
                tag = r.getheader("ETag")
                n = dict(counts)
                ms = []
                for _ in range(5):
                    t0 = time.perf_counter()
                    r2, b2 = self.req(path, {"If-None-Match": tag})
                    ms.append((time.perf_counter() - t0) * 1000)
                    self.assertEqual((r2.status, b2), (304, b""))
                self.assertEqual(counts, n, path)  # 命中：不重算
                self.assertLess(sorted(ms)[2], 20, f"{path} 命中耗时 {ms}")
            n = dict(counts)
            self.write_run()
            self.req("/api/projects")
            self.req("/api/meetings")
            self.assertEqual(counts, n)  # 只有运行记录变了、不到 10 秒：用上次结果
            self.touch_ledger()
            self.req("/api/projects")
            self.req("/api/meetings")
            self.assertEqual(counts["meetings"], n["meetings"] + 1)  # 账本变了马上重算
            self.assertGreaterEqual(counts["discover"], n["discover"] + 1)
        finally:
            server.discover, server.meetings = orig_d, orig_m

    def test_project_run_version_header(self):
        r, _ = self.req(f"/api/p/{self.pid}")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("X-Board-Run-Version"), str(server.WATCH.versions.get("r:" + self.pid, "")))
        r, _ = self.req(f"/api/p/{self.pid}/meet/I001")
        self.assertEqual(r.status, 200)
        self.assertIsNotNone(r.getheader("X-Board-Run-Version"))

    def test_project_run_only_change_reuses(self):
        calls = []
        orig = server.project_data
        server.project_data = lambda p: calls.append(1) or orig(p)
        server.CACHE.pop("p:" + self.pid, None)
        try:
            r1, _ = self.req(f"/api/p/{self.pid}")
            self.write_run()
            r2, _ = self.req(f"/api/p/{self.pid}", {"If-None-Match": r1.getheader("ETag")})
            self.assertEqual(r2.status, 304)  # 不到 10 秒：上次结果
            self.assertEqual(len(calls), 1)
            server.CACHE["p:" + self.pid]["t"] -= server.RUN_MIN
            self.req(f"/api/p/{self.pid}")
            self.assertEqual(len(calls), 2)
        finally:
            server.project_data = orig

    # ---------- 根路径图标 ----------

    def test_root_icons(self):
        icon = (STATIC / "icon-180.png").read_bytes()
        for path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
                     "/apple-touch-icon-152x152.png", "/apple-touch-icon-167x167-precomposed.png"):
            r, body = self.req(path)
            self.assertEqual((r.status, r.getheader("Content-Type"), body), (200, "image/png", icon), path)
        r, body = self.req("/favicon.ico")
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))


# ---------- 前端：node 里跑，计时器和 Date.now 手动推进 ----------

TIMERS = r"""
let now = 0, timers = [], tid = 0;
const flush = () => new Promise((r) => setImmediate(r));
const add = (f, ms, every) => { const id = ++tid; timers.push({id, at: now + (ms || 0), f, every}); return id; };
global.setTimeout = (f, ms) => add(f, ms, 0);
global.setInterval = (f, ms) => add(f, ms, ms);
global.clearTimeout = global.clearInterval = (id) => { timers = timers.filter((t) => t.id !== id); };
Date.now = () => now;
async function advance(ms, each) {
  const end = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > end) break;
    timers.shift(); now = t.at;
    if (t.every) timers.push({...t, at: now + t.every});
    t.f();
    await flush();
  }
  now = end;
  await flush();
}
"""

# now-inject.js：摘要和朝会入口最多 60 秒拉一次，切回前台也受限，后台到点不拉；不看 r:
NOW_INJECT = TIMERS + r"""
const fs = require("fs");
const el = () => ({className: "", dataset: {}, innerHTML: "", textContent: "", remove() {}, after() {},
  querySelector: () => ({dataset: {}, textContent: ""}), appendChild() {}});
const docL = {};
global.document = {visibilityState: "visible", addEventListener: (e, f) => { (docL[e] = docL[e] || []).push(f); },
  querySelectorAll: () => [], querySelector: () => null, createElement: el, body: el()};
global.MutationObserver = class { observe() {} };
global.V = {State: {PENDING_RULING: "x"}}; global.N = () => "";
const calls = [];
let opts = null;
global.window = {t: (k) => k, I18n_summary: () => "", I18n_blocked: () => false, BOARD_REMOTE: false,
  BoardLive: {getJSON: (u) => { calls.push([now, u]); return Promise.resolve({changed: false}); },
              start: (o) => { opts = o; return {onState() {}}; }, label: () => ""}};
eval(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
(async () => {
  await flush();
  out.initial = calls.length;
  out.watch = ["now", "p:abc", "r:abc", "team"].map((k) => opts.watch(k));
  opts.onChange(["p:abc"], {"p:abc": 1});  // 推送首条：只记版本号
  // 成员在跑、账本也每秒在变：130 秒里只在 60、120 秒各拉一次
  for (let i = 0; i < 130; i++) { opts.onChange(["p:abc"], {"p:abc": i + 2}); await advance(1000); }
  out.at130 = calls.map((c) => c[0] / 1000);
  // 切回前台：也受同一限流（上次在 120 秒，到 180 秒才拉）
  calls.length = 0;
  opts.onResume();
  await flush();
  out.resumeNow = calls.length;
  // 到后台：180 秒到点也不拉；200 秒切回前台时补拉
  document.visibilityState = "hidden";
  await advance(60000);
  out.hidden = calls.length;
  document.visibilityState = "visible";
  opts.onResume();
  await flush();
  out.back = calls.map((c) => c[0] / 1000);
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""

# live.js pages()：拉到的运行版本号比推送来的旧（服务端 10 秒内回上次结果）时，10 秒后再拉一次，追上就停
PAGES_LAG = TIMERS + r"""
const fs = require("fs");
global.document = {visibilityState: "visible", addEventListener: () => {}, getElementById: () => null};
global.window = {addEventListener: () => {}, t: (k) => k};
Object.defineProperty(globalThis, "navigator", {value: {onLine: true}, configurable: true});
global.sessionStorage = {getItem: () => null, setItem: () => {}};
global.location = {reload: () => {}};
const sources = [];
global.EventSource = class { constructor() { this.l = {}; sources.push(this); } addEventListener(e, f) { this.l[e] = f; } close() {}
  push(v) { this.l.change({data: JSON.stringify(v)}); } };
let runVer = "5", n = 0;
global.fetch = (url, o) => { n++; const h = {get: (k) => ({"X-Board-Version": "1", "X-Board-Run-Version": runVer, ETag: 'W/"' + runVer + '"'}[k] ?? null)};
  return Promise.resolve({status: 200, ok: true, headers: h, json: () => Promise.resolve({})}); };
eval(fs.readFileSync(process.argv[2], "utf8"));
const BL = window.BoardLive;
const out = {};
(async () => {
  const loads = [];
  const live = BL.pages({watch: ["p:x", "r:x"], load: () => { loads.push(now); return BL.getJSON("/api/p/x").then((r) => { live.seen("p:x", r.version); live.seen("r:x", r.runVersion); }); }});
  await live.load();
  sources[0].push({"p:x": "1", "r:x": "5", shell: "s"});
  await flush();
  out.first = loads.length;  // 首条推送和拉到的一样：不再拉
  sources[0].push({"p:x": "1", "r:x": "6", shell: "s"});  // 运行类变了；服务端还在 10 秒内，回上次结果（5）
  await flush(); await flush();
  out.afterPush = loads.length;
  runVer = "6";
  await advance(10000);
  out.afterLag = loads.length;  // 10 秒后补拉，拿到 6
  await advance(30000);
  out.settled = loads.length;  // 追上了：不再拉
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


def node(script, target):
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "harness.js"
        h.write_text(script, encoding="utf-8")
        r = subprocess.run(["node", str(h), str(target)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "没装 node")
class Front(unittest.TestCase):
    def test_now_summaries_throttled(self):
        out = node(NOW_INJECT, STATIC / "now-inject.js")
        self.assertEqual(out["initial"], 2)  # 打开时摘要和朝会入口各拉一次
        self.assertEqual(out["watch"], [True, True, False, False])  # NOW 页不看运行类 r:
        self.assertEqual(out["at130"], [0, 0, 60, 60, 120, 120])
        self.assertEqual(out["resumeNow"], 0)
        self.assertEqual(out["hidden"], 0)
        self.assertEqual(out["back"], [190, 190])

    def test_pages_catch_up_after_stale(self):
        out = node(PAGES_LAG, STATIC / "live.js")
        self.assertEqual(out, {"first": 1, "afterPush": 2, "afterLag": 3, "settled": 3})


# 中 / EN 切换（补充要求⑨）：页脚的小文字链接，触屏不显示，不用写死的白底；浏览器里的截图和逐项检查见 work/G056/G056-T9/语言切换_检查.json
I18N_SWITCH = TIMERS + r"""
const fs = require("fs");
const made = [];
const mk = (tag) => { const e = {tagName: tag.toUpperCase(), className: "", dataset: {}, children: [], l: {},
  appendChild(c) { this.children.push(c); c.parentElement = this; }, addEventListener(k, f) { this.l[k] = f; }}; made.push(e); return e; };
const body = mk("body");
const nowFoot = mk("footer");
const docEl = {lang: ""};
let page = process.argv[3];
global.document = {readyState: "complete", body, documentElement: docEl, addEventListener() {}, createElement: mk,
  getElementById: (id) => made.find((e) => e.id === id) || null,
  querySelector: (q) => (q === ".wrap > footer" && page === "now" ? nowFoot : null), querySelectorAll: () => []};
const store = {};
global.localStorage = {getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; }};
let replaced = null;
global.location = {href: "http://127.0.0.1/?lang=zh", search: "", replace: (u) => { replaced = u; }};
global.window = {I18N_PACKS: {zh: {text: {}}, en: {text: {}}}, BOARD_LANG: "zh"};
eval(fs.readFileSync(process.argv[2], "utf8"));
const sw = document.getElementById("langsw");
sw.l.click({preventDefault() {}});
console.log(JSON.stringify({tag: sw.tagName, text: sw.textContent, to: sw.dataset.lang, parent: sw.parentElement.className || sw.parentElement.tagName,
  inNowFooter: sw.parentElement === nowFoot, stored: Object.values(store), replaced}));
process.exit(0);
"""


class LangSwitch(unittest.TestCase):
    def test_css_footer_and_touch(self):
        css = (STATIC / "board.css").read_text(encoding="utf-8")
        tpl = (base.SRC / "board" / "now" / "template.html").read_text(encoding="utf-8")
        inject = (STATIC / "now-inject.css").read_text(encoding="utf-8")
        self.assertNotIn("langsw", inject)  # 不再浮在右上角（原来 position:fixed 加写死的白底）
        self.assertIn("@media (pointer: coarse) { .langfoot, .langsw { display: none; } }", css)
        self.assertIn("@media (pointer: coarse) { .langsw { display: none; } }", tpl)
        for text in (css, tpl):
            rules = [l for l in text.splitlines() if ".langsw" in l or ".langfoot" in l]
            self.assertTrue(rules)
            for l in rules:
                self.assertNotIn("position: fixed", l)
                self.assertNotIn("background", l)  # 不给背景色：深色模式下不出白块

    @unittest.skipUnless(shutil.which("node"), "没装 node")
    def test_switch_link(self):
        for page, parent in (("now", "FOOTER"), ("project", "langfoot")):
            with tempfile.TemporaryDirectory() as d:
                h = Path(d) / "harness.js"
                h.write_text(I18N_SWITCH, encoding="utf-8")
                r = subprocess.run(["node", str(h), str(STATIC / "i18n.js"), page], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual((out["tag"], out["text"], out["to"]), ("A", "English", "en"), page)  # 中文页面上只写「English」
            self.assertEqual(out["parent"], parent, page)
            self.assertEqual(out["inNowFooter"], page == "now")
            self.assertEqual(out["stored"], ["en"])  # 读者的选择照旧记下，下次打开仍按它
            self.assertNotIn("lang=", out["replaced"])


if __name__ == "__main__":
    unittest.main()
