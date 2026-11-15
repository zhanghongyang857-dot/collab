"""项目、朝会、班子、人才页改为推送更新（G056-T4）：收到本页的块变化才拉数据，自带 If-None-Match，留 60 秒保底；
静态导出和归档页不连推送、不轮询。

服务端部分沿用 test_board_live 的临时 NOW 数据和演示项目；BoardLive.getJSON / pages 用 node 跑（没装 node 时跳过），
浏览器里的整页行为（改账本后 3 秒内更新、保留选中和滚动、空闲时只有心跳和保底）见 work/G056/G056-T4/ 的实测记录。
"""
import argparse
import http.client
import json
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
STATIC = SRC / "board" / "static"
LIVE_JS = STATIC / "live.js"
PAGES = ("project", "meet", "team", "talent")


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        cls.proj = base.demo.build(cls.tmp / "proj", 5)
        cls.data = base.make_now(cls.tmp, cls.proj / "collab" / "PROGRESS.md")
        server.ARGS = argparse.Namespace(verbose=False, port=0, now_dir=str(cls.data), project=[str(cls.proj)], no_registry=True)
        server.WATCH = server.Watcher()
        server.CACHE.clear()
        server.NOW_DEPS.clear()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.pid = next(p["id"] for p in server.discover() if Path(p["root"]) == cls.proj)
        server.WATCH.scan()  # 先记一轮版本号

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

    def test_project_version_and_304(self):
        ver = str(server.WATCH.versions.get("p:" + self.pid))
        self.assertTrue(ver and ver != "None")
        r, body = self.req(f"/api/p/{self.pid}")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("X-Board-Version"), ver)  # 页面交给 live.seen：推送来同一版本不再拉
        r2, b2 = self.req(f"/api/p/{self.pid}", {"If-None-Match": r.getheader("ETag")})
        self.assertEqual((r2.status, b2), (304, b""))
        self.assertEqual(r2.getheader("X-Board-Version"), ver)

    def test_meet_version_and_304(self):
        r, body = self.req(f"/api/p/{self.pid}/meet/I001")
        self.assertEqual(r.status, 200, body[:200])
        self.assertEqual(r.getheader("X-Board-Version"), str(server.WATCH.versions.get("p:" + self.pid)))
        r2, b2 = self.req(f"/api/p/{self.pid}/meet/I001", {"If-None-Match": r.getheader("ETag")})
        self.assertEqual((r2.status, b2), (304, b""))

    def test_talent_version(self):
        r, _ = self.req("/api/talent")
        self.assertEqual(r.getheader("X-Board-Version"), str(server.WATCH.versions.get("team", "")))

    def test_team_and_talent_304(self):
        for path in ("/api/team", "/api/talent"):
            r, _ = self.req(path)
            self.assertEqual(r.status, 200, path)
            r2, b2 = self.req(path, {"If-None-Match": r.getheader("ETag")})
            self.assertEqual((r2.status, b2), (304, b""), path)

    def test_pages_load_live_js_first(self):
        for name, path in (("project", f"/p/{self.pid}"), ("project", f"/p/{self.pid}/archive"), ("meet", f"/p/{self.pid}/meet/I001"),
                           ("team", "/team"), ("talent", "/talent")):
            r, body = self.req(path)
            page = body.decode("utf-8")
            self.assertEqual(r.status, 200, path)
            self.assertLess(page.index('src="/static/live.js"'), page.index(f'src="/static/{name}.js"'), path)


class Source(unittest.TestCase):
    def read(self, name):
        return (STATIC / name).read_text(encoding="utf-8")

    def test_no_fixed_polling(self):
        p = self.read("project.js")
        self.assertNotIn("}, 5000);", p)
        self.assertIn('BoardLive.pages({watch: ["p:" + id, "r:" + id], load})', p)  # 账本即时；运行类服务端最多 10 秒推一次（G056-T9）
        self.assertIn("if (!ARCHIVE && !SITE && window.BoardLive)", p)  # 归档页、静态导出：加载一次，不连推送
        t = self.read("team.js")
        self.assertNotIn("}, 30000);", t)
        self.assertIn('k === "team" || k.startsWith("p:") || k.startsWith("r:")', t)
        m = self.read("meet.js")
        self.assertNotIn("2900", m)  # 没人在跑时不再每 3 秒拉
        self.assertNotIn("running() && Date.now() - last >= 900", m)  # 有人在跑时不再每秒拉（G056-T9），流式输出走 r:<项目> 推送
        self.assertIn('BoardLive.pages({watch: ["p:" + pid, "r:" + pid], load})', m)
        self.assertIn("if (SITE || !window.BoardLive) { load(); return; }", m)
        self.assertIn('BoardLive.pages({watch: ["team"]', self.read("talent.js"))

    def test_data_requests_carry_etag(self):
        for name in ("project.js", "meet.js", "team.js", "talent.js"):
            self.assertIn("BoardLive.getJSON(", self.read(name), name)
        live = self.read("live.js")
        self.assertIn('"If-None-Match"', live)
        self.assertIn('cache: "no-store"', live)


class Export(unittest.TestCase):
    def test_static_pages_have_no_live_js(self):
        sys.path.insert(0, str(SRC / "board"))
        import export_static  # noqa: E402
        with tempfile.TemporaryDirectory() as d:
            proj = base.demo.build(Path(d) / "演示", 5)
            out = Path(d) / "站"
            export_static.export(proj, out, "15730301", team=ROOT / "demo")
            pages = list(out.rglob("index.html"))
            self.assertTrue(pages)
            for f in pages:
                self.assertNotIn("live.js", f.read_text(encoding="utf-8"), f)
            self.assertFalse((out / "static" / "live.js").exists())


# BoardLive.getJSON / pages 在 node 里跑：假的 fetch、EventSource、document、计时器（手动推进）
HARNESS = r"""
const fs = require("fs");
let now = 0, timers = [], tid = 0;
const flush = () => new Promise((r) => setImmediate(r));
const add = (f, ms, every) => { const id = ++tid; timers.push({id, at: now + (ms || 0), f, every}); return id; };
global.setTimeout = (f, ms) => add(f, ms, 0);
global.setInterval = (f, ms) => add(f, ms, ms);
global.clearTimeout = global.clearInterval = (id) => { timers = timers.filter((t) => t.id !== id); };
async function advance(ms) {
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
const docL = {};
const tickEl = {textContent: ""};
global.document = { visibilityState: "visible", addEventListener: (e, f) => { (docL[e] = docL[e] || []).push(f); },
  getElementById: (id) => (id === "tick" ? tickEl : null) };
global.window = { addEventListener: () => {}, t: (k, v) => k + (v ? JSON.stringify(v) : "") };
Object.defineProperty(globalThis, "navigator", {value: {onLine: true}, configurable: true});
global.sessionStorage = { getItem: () => null, setItem: () => {} };
global.location = { reload: () => {} };
const sources = [];
global.EventSource = class { constructor(url) { this.url = url; this.l = {}; sources.push(this); }
  addEventListener(e, f) { this.l[e] = f; } close() {}
  push(v) { this.l.change({data: JSON.stringify(v)}); } };
// 假的 /api/p/x：ETag 跟着内容走，带上 If-None-Match 且相同就 304
let body = {n: 1}, ver = "7";
const calls = [];
let down = false;
global.fetch = (url, opts) => {
  if (down) return Promise.reject(new Error("down"));
  const inm = ((opts || {}).headers || {})["If-None-Match"] || null;
  calls.push([url, inm, (opts || {}).cache]);
  const tag = 'W/"' + body.n + '"';
  const h = {get: (k) => ({ETag: tag, "X-Board-Version": ver}[k] ?? null)};
  if (inm === tag) return Promise.resolve({status: 304, ok: false, headers: h});
  return Promise.resolve({status: 200, ok: true, headers: h, json: () => Promise.resolve(JSON.parse(JSON.stringify(body)))});
};
eval(fs.readFileSync(process.argv[2], "utf8"));
const BL = window.BoardLive;
const out = {};
(async () => {
  // getJSON：第一次 200 记下 ETag；第二次自带 If-None-Match，回 304；内容变了回 200
  const a = await BL.getJSON("/api/p/x");
  const b = await BL.getJSON("/api/p/x");
  body = {n: 2};
  const c = await BL.getJSON("/api/p/x");
  out.get = [a.changed, a.version, b.changed, b.version, c.changed, c.data.n];
  out.getCalls = calls.map((x) => x.slice(1));
  // pages：推送来本页的块才 load；版本号已 seen 的不 load；load 跑着时又来变化，跑完补一次；60 秒保底，后台时不跑
  calls.length = 0;
  const loads = [];
  let release = null;
  const load = () => { loads.push(now); return BL.getJSON("/api/p/x").then((r) => { if (r.version) live.seen("p:x", r.version); }); };
  const live = BL.pages({watch: ["p:x"], load});
  await live.load();
  out.firstLoad = loads.length;
  const es = sources[0];
  es.push({"p:x": "7", "p:y": 1, team: 1, shell: "s"});  // 和已拉到的一样 / 不关心的块 → 不 load
  await flush();
  out.afterSame = loads.length;
  ver = "8"; body = {n: 3};
  es.push({"p:x": "8", shell: "s"});                     // 变了 → load 一次
  await flush(); await flush();
  out.afterChange = loads.length;
  out.lastStatus = calls.length;
  // 并发合并：连来三次变化，只多跑一次
  const slow = BL.pages({watch: ["team"], load: () => { loads.push("t"); return new Promise((r) => { release = r; }); }});
  slow.load(); slow.load(); slow.load();
  await flush();
  release(); await flush(); await flush();
  release(); await flush(); await flush();
  out.coalesced = loads.filter((x) => x === "t").length;
  // 打开时推送首条和第一次拉数据撞在一起：版本号就是这次拉到的 → 不补；比拉到的新 → 补一次
  const race = (pushed) => new Promise(async (done) => {
    let n = 0, rel = null;
    const inst = BL.pages({watch: ["p:r"], load: () => { n++; return new Promise((r) => { rel = r; }).then(() => inst.seen("p:r", "5")); }});
    inst.load(); await flush();
    sources[sources.length - 1].push({"p:r": pushed, shell: "s"});  // 第一次 load 还没回来
    rel(); await flush(); await flush();
    if (rel && n > 1) { rel(); await flush(); await flush(); }
    inst.stop(); done(n);
  });
  out.raceSame = await race("5");
  out.raceNewer = await race("6");
  // 空闲 130 秒：只在 60、120 秒各保底一次（自带 If-None-Match，回 304）
  calls.length = 0; loads.length = 0;
  await advance(130000);
  out.idleLoads = loads.filter((x) => x !== "t").length;
  const pc = calls.filter((x) => x[0] === "/api/p/x");  // 另一个实例没推送，会退回拉 /api/versions，不算
  out.idle304 = pc.length === 2 && pc.every((x) => x[1] !== null);
  // 到后台：保底不跑
  document.visibilityState = "hidden";
  docL.visibilitychange.forEach((f) => f());
  loads.length = 0;
  await advance(130000);
  out.hiddenLoads = loads.filter((x) => x !== "t").length;
  // tick：连着时只显示页面文字，断了前面加状态
  live.tick("推送更新 · 10:00");
  out.tickLive = tickEl.textContent;
  down = true;
  sources[0].onerror();
  await flush(); await flush();
  out.tickDown = tickEl.textContent;
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


@unittest.skipUnless(shutil.which("node"), "没装 node")
class LiveJsPages(unittest.TestCase):
    def test_get_json_and_pages(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "harness.js"
            h.write_text(HARNESS, encoding="utf-8")
            r = subprocess.run(["node", str(h), str(LIVE_JS)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["get"], [True, "7", False, "7", True, 2])
        self.assertEqual(out["getCalls"], [[None, "no-store"], ['W/"1"', "no-store"], ['W/"1"', "no-store"]])
        self.assertEqual(out["firstLoad"], 1)
        self.assertEqual(out["afterSame"], 1)  # 版本号已 seen、别的块变了：不拉
        self.assertEqual(out["afterChange"], 2)
        self.assertEqual(out["raceSame"], 1)  # 打开时推送首条撞上第一次拉数据：版本号已拿到，不再拉
        self.assertEqual(out["raceNewer"], 2)
        self.assertEqual(out["coalesced"], 2)  # 三次 load 合并成「跑一次 + 补一次」
        self.assertEqual(out["idleLoads"], 2)  # 60、120 秒各一次保底
        self.assertTrue(out["idle304"])
        self.assertEqual(out["hiddenLoads"], 0)
        self.assertEqual(out["tickLive"], "推送更新 · 10:00")
        self.assertTrue(out["tickDown"].endswith(" · 推送更新 · 10:00"), out["tickDown"])
        self.assertTrue(out["tickDown"].startswith("board.live.connecting"), out["tickDown"])


if __name__ == "__main__":
    unittest.main()
