"""主屏 app 和离线（G056-T5）：/manifest.webmanifest、图标、根路径 /sw.js、各页头部标签、离线标记和写操作置灰。

服务端部分沿用 test_board_live 的临时 NOW 数据和演示项目；sw.js、live.js、pwa.js 的行为用 node 跑（没装 node 时跳过），
浏览器里的整页行为（停服务后重开显示上次数据、恢复后转实时、改外壳后只重载一次）见 work/G056/G056-T5/ 的实测记录。
"""
import argparse
import http.client
import json
import shutil
import struct
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
sys.path.insert(0, str(SRC / "board"))
import export_static  # noqa: E402

HEAD_TAGS = ('<link rel="manifest" href="/manifest.webmanifest">', '<link rel="apple-touch-icon" href="/static/icon-180.png">',
             '<meta name="apple-mobile-web-app-capable" content="yes">', "viewport-fit=cover", '<script src="/static/pwa.js" defer></script>')


def png_size(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


class Server(unittest.TestCase):
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
        cls.pid = server.project_id(cls.proj)

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

    def test_sw_at_root_with_shell(self):
        _, page = self.req("/")
        fp = page.decode("utf-8").split('<meta name="board-shell" content="')[1].split('"')[0]
        r, body = self.req("/sw.js")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/javascript"))
        self.assertIn(f'const SHELL = "{fp}";'.encode(), body)  # 缓存名带的指纹和页面、推送里的是同一个
        self.assertNotIn(b'"__SHELL__"', body)
        self.assertEqual(r.getheader("Cache-Control"), "no-cache")  # 每次都来问，发布后马上拿到新版

    def test_sw_changes_with_shell(self):
        _, a = self.req("/sw.js")
        old = server.WATCH.versions["shell"]
        try:
            server.WATCH.versions["shell"] = "feedfacefeedface"  # 发布了新代码：监视线程算出新指纹
            _, b = self.req("/sw.js")
        finally:
            server.WATCH.versions["shell"] = old
        self.assertNotEqual(a, b)
        self.assertIn(b'"feedfacefeedface"', b)

    def test_manifest(self):
        r, body = self.req("/manifest.webmanifest")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("application/manifest+json"))
        m = json.loads(body)
        self.assertEqual((m["display"], m["start_url"], m["scope"]), ("standalone", "/", "/"))
        self.assertTrue(m["name"] and m["short_name"] and m["theme_color"])
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        for i in m["icons"]:
            ri, data = self.req(i["src"])
            self.assertEqual((ri.status, ri.getheader("Content-Type")), (200, "image/png"))
            self.assertEqual("%dx%d" % png_size(data), i["sizes"])

    def test_touch_icon_180(self):
        r, data = self.req("/static/icon-180.png")
        self.assertEqual(r.status, 200)
        self.assertEqual(png_size(data), (180, 180))

    def test_pages_have_head_tags(self):
        for path in ("/", f"/p/{self.pid}", f"/p/{self.pid}/meet/I001", "/team", "/talent", "/projects"):
            r, body = self.req(path)
            page = body.decode("utf-8")
            self.assertEqual(r.status, 200, path)
            head = page.split("</head>")[0]
            for tag in HEAD_TAGS:
                self.assertIn(tag, head, (path, tag))

    def test_static_files_registered(self):
        for f in ("pwa.js", "sw.js", "icon-180.png", "icon-192.png", "icon-512.png"):
            self.assertIn(f, server.STATIC_FILES)
            self.assertTrue((STATIC / f).exists(), f)
        r, _ = self.req("/static/pwa.js")
        self.assertEqual(r.status, 200)


class Source(unittest.TestCase):
    def test_static_export_has_no_sw(self):
        for name in ("project.html", "meet.html", "team.html", "talent.html"):
            page = export_static._page(name, 2, {"project": "x"}, [])
            self.assertNotIn("pwa.js", page, name)
            self.assertNotIn('rel="manifest"', page, name)
            self.assertNotIn("apple-touch-icon", page, name)

    def test_standalone_now_has_no_sw(self):
        b = server.load_build()
        page = b.render(b.collect())
        self.assertNotIn("pwa.js", page)
        self.assertNotIn("manifest.webmanifest", page)

    def test_write_ops_check_offline(self):
        self.assertIn("BoardPWA.offline()", (STATIC / "project.js").read_text(encoding="utf-8"))
        self.assertIn("BoardPWA.offline()", (STATIC / "meet.js").read_text(encoding="utf-8"))
        css = (STATIC / "board.css").read_text(encoding="utf-8")
        self.assertIn("html.board-offline [data-goalact]", css)
        self.assertIn("html.board-offline .composer button", css)


# sw.js 在 node 里跑：假的 self、caches，fetch 可切换在线 / 离线；Request、Response、Headers 用 node 自带的
SW_HARNESS = r"""
const fs = require("fs");
const L = {};
const stores = {};
let online = true, fetched = [];
const keyOf = (k) => new URL(typeof k === "string" ? k : k.url, "http://h/").pathname + new URL(typeof k === "string" ? k : k.url, "http://h/").search;
class Cache { constructor() { this.m = new Map(); }
  async put(k, r) { this.m.set(keyOf(k), r); } async match(k) { const r = this.m.get(keyOf(k)); return r ? r.clone() : undefined; } }
global.caches = { open: async (n) => (stores[n] = stores[n] || new Cache()), keys: async () => Object.keys(stores),
  delete: async (n) => delete stores[n] };
let claimed = 0, skipped = 0;
global.self = { location: {origin: "http://h"}, addEventListener: (e, f) => { L[e] = f; },
  skipWaiting: () => { skipped++; }, clients: { claim: async () => { claimed++; } } };
let n = 0;
global.fetch = async (req, init) => {
  const url = typeof req === "string" ? req : req.url;
  fetched.push(url);
  if (!online) throw new TypeError("Failed to fetch");
  n++;
  const p = new URL(url, "http://h/").pathname;
  const ct = p.startsWith("/api/") ? "application/json" : "text/html";
  const r = new Response(p.startsWith("/api/") ? JSON.stringify({n, p}) : `<html>${p} v${n}</html>`,
    {status: 200, headers: {"Content-Type": ct, "ETag": 'W/"' + n + '"', "X-Board-Version": String(n)}});
  Object.defineProperty(r, "type", {value: "basic"});
  return r;
};
eval(fs.readFileSync(process.argv[2], "utf8").replace('"__SHELL__"', '"fp1"'));
const flush = () => new Promise((r) => setTimeout(r, 20));
function fire(req) {
  let res = "passthrough";
  const waits = [];
  L.fetch({request: req, respondWith: (p) => { res = p; }, waitUntil: (p) => waits.push(p)});
  return {res, waits};
}
const R = (path, opts) => new Request("http://h" + path, opts);
const out = {};
(async () => {
  stores["board-shell-old"] = new Cache();
  let w = [];
  L.install({waitUntil: (p) => w.push(p)}); await Promise.all(w);
  out.skipped = skipped;
  out.precached = stores["board-shell-fp1"].m.has("/") && stores["board-shell-fp1"].m.has("/static/live.js");
  w = []; L.activate({waitUntil: (p) => w.push(p)}); await Promise.all(w);
  out.claimed = claimed; out.oldGone = !("board-shell-old" in stores) && ("board-shell-fp1" in stores);
  // 不经 SW：POST、推送、版本号、别的站点
  out.post = fire(new Request("http://h/api/p/1/goal/G1", {method: "POST", body: "{}"})).res;
  out.events = fire(R("/api/events")).res;
  out.versions = fire(R("/api/versions")).res;
  out.other = fire(new Request("http://other/x.js")).res;
  // 数据：在线时走网络并存一份
  let a = await fire(R("/api/now")).res;
  out.dataOnline = [a.status, a.headers.get("X-Board-Cache"), (await a.json()).p];
  await flush();
  const stored = stores["board-data"] && stores["board-data"].m.get("/api/now");
  out.dataStored = !!stored && !!stored.headers.get("X-Board-Cached-At");
  // 外壳：缓存优先（先给缓存的预存版），后台更新缓存
  fetched = [];
  const s1 = await fire(R("/")).res;
  out.shellFromCache = (await s1.text()).includes("<html>/ v");
  await flush();
  out.shellRevalidated = fetched.includes("http://h/");
  // 离线：数据回退缓存、带标记；外壳照样有；没缓存过的数据 503
  online = false;
  const b = await fire(R("/api/now")).res;
  out.dataOffline = [b.status, b.headers.get("X-Board-Cache"), !!b.headers.get("X-Board-Cached-At"), !!b.headers.get("ETag"), (await b.json()).p];
  const s2 = await fire(R("/team")).res;
  out.shellOffline = s2.status;
  const c = await fire(R("/api/p/abc")).res;
  out.missOffline = [c.status, c.headers.get("X-Board-Cache")];
  const nav = await fire({method: "GET", url: "http://h/p/deadbeef", mode: "navigate"}).res;  // node 造不出 navigate 请求
  const sub = await fire(R("/static/nope.js")).res;
  out.subMiss = sub.type;
  out.navMiss = nav.status;
  console.log(JSON.stringify(out));
})();
"""

# live.js：SW 回退的缓存 → 标离线、「截至」取缓存时间；连上推送 → 实时；外壳变了先交给 BoardPWA
LIVE_HARNESS = r"""
const fs = require("fs");
global.setTimeout = () => 0; global.clearTimeout = () => {}; global.setInterval = () => 0;
const winL = {}, events = [];
global.document = { visibilityState: "visible", addEventListener: () => {} };
class CE { constructor(type, init) { this.type = type; this.detail = init.detail; } }
global.CustomEvent = CE;
global.window = { addEventListener: (e, f) => { (winL[e] = winL[e] || []).push(f); },
  dispatchEvent: (e) => { events.push([e.type, e.detail.state]); }, t: (k, v) => k + (v ? JSON.stringify(v) : "") };
Object.defineProperty(globalThis, "navigator", {value: {onLine: true}, configurable: true});
const store = {};
global.sessionStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
let reloads = 0, pwaReloads = 0;
global.location = { reload: () => { reloads++; } };
const sources = [];
global.EventSource = class { constructor() { this.l = {}; sources.push(this); } addEventListener(e, f) { this.l[e] = f; } close() {}
  push(v) { this.l.change({data: JSON.stringify(v)}); } };
const hdr = (h) => ({ get: (k) => (k in h ? h[k] : null) });
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({x: 1}),
  headers: hdr({"X-Board-Cache": "offline", "X-Board-Cached-At": new Date(2026, 10, 14, 8, 7).toISOString(), "ETag": 'W/"1"'}) });
eval(fs.readFileSync(process.argv[2], "utf8"));
const BL = window.BoardLive;
const out = {};
(async () => {
  // NOW 页的 refresh() 在 live.js 之前拿到缓存：记在 BOARD_CACHED_AT，start() 时用上
  window.BOARD_CACHED_AT = new Date(2026, 10, 14, 7, 30).toISOString();
  const live = BL.start({watch: ["now"], shell: "s1"});
  out.early = [live.state, BL.label(live.state, live.lastOk)];
  const r = await BL.getJSON("/api/p/x");  // SW 回退的缓存：时间更新到 08:07
  out.got = r.changed;
  out.cached = [live.state, BL.label(live.state, live.lastOk)];
  out.plain = BL.noteResponse({headers: hdr({})});  // 网络来的不算
  sources[0].push({now: 3, shell: "s1"});
  out.live = live.state;
  out.events = events;
  window.BoardPWA = { reload: () => { pwaReloads++; } };
  sources[0].push({now: 3, shell: "s2"});
  out.reloads = [reloads, pwaReloads];
  console.log(JSON.stringify(out));
})();
"""

# pwa.js：安全上下文才注册；静态导出不注册；离线时 <html> 加 board-offline，有写操作的页才提示
PWA_HARNESS = r"""
const fs = require("fs");
const [file, secure, isStatic, hasSW] = process.argv.slice(2);
const cls = new Set(), regs = [], winL = {}, body = [];
const el = () => ({ hidden: false, textContent: "", dataset: {} });
global.document = { documentElement: { classList: { toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)), contains: (c) => cls.has(c) } },
  body: { appendChild: (x) => body.push(x) }, head: { appendChild: () => {} }, createElement: el,
  querySelector: (s) => (s.includes("#composer") ? {} : null), addEventListener: () => {}, activeElement: null };
global.location = { pathname: "/team", reload: () => {} };  // 页面上有 #composer（见 querySelector），按元素认出有写操作
global.window = { isSecureContext: secure === "1", t: (k) => k, addEventListener: (e, f) => { (winL[e] = winL[e] || []).push(f); } };
if (isStatic === "1") window.BOARD_STATIC = {base: "."};
const nav = {};
if (hasSW === "1") nav.serviceWorker = { controller: null, addEventListener: () => {},
  register: (u, o) => { regs.push([u, o.scope]); return Promise.resolve({update: () => Promise.resolve()}); } };
Object.defineProperty(globalThis, "navigator", {value: nav, configurable: true});
let err = null;
try {
  eval(fs.readFileSync(file, "utf8"));
  (winL["board:live"] || []).forEach((f) => f({detail: {state: "offline"}}));
} catch (e) { err = String(e); }
const off = { cls: cls.has("board-offline"), api: window.BoardPWA.offline(), tip: body.length ? [body[0].textContent, body[0].hidden] : null };
(winL["board:live"] || []).forEach((f) => f({detail: {state: "live"}}));
console.log(JSON.stringify({err, regs, off, back: cls.has("board-offline"), tipHidden: body.length ? body[0].hidden : null}));
"""


@unittest.skipUnless(shutil.which("node"), "没装 node")
class Node(unittest.TestCase):
    def run_node(self, harness, *args):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "harness.js"
            h.write_text(harness, encoding="utf-8")
            r = subprocess.run(["node", str(h), *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_sw(self):
        out = self.run_node(SW_HARNESS, STATIC / "sw.js")
        self.assertEqual(out["skipped"], 1)  # skipWaiting：新版装好立刻接管
        self.assertTrue(out["precached"])
        self.assertEqual(out["claimed"], 1)
        self.assertTrue(out["oldGone"])  # 旧指纹的外壳缓存删掉
        for k in ("post", "events", "versions", "other"):
            self.assertEqual(out[k], "passthrough", k)
        self.assertEqual(out["dataOnline"], [200, None, "/api/now"])
        self.assertTrue(out["dataStored"])
        self.assertTrue(out["shellFromCache"])
        self.assertTrue(out["shellRevalidated"])
        self.assertEqual(out["dataOffline"], [200, "offline", True, True, "/api/now"])
        self.assertEqual(out["shellOffline"], 200)
        self.assertEqual(out["missOffline"], [503, "miss"])
        self.assertEqual(out["navMiss"], 503)  # 没缓存过的页面：给一页离线说明
        self.assertEqual(out["subMiss"], "error")  # 没缓存过的脚本：网络错误

    def test_live_offline_marker(self):
        out = self.run_node(LIVE_HARNESS, STATIC / "live.js")
        self.assertEqual(out["early"], ["offline", 'board.live.offline_since{"t":"07:30"}'])
        self.assertTrue(out["got"])
        self.assertEqual(out["cached"], ["offline", 'board.live.offline_since{"t":"08:07"}'])
        self.assertFalse(out["plain"])
        self.assertEqual(out["live"], "live")
        self.assertEqual(out["events"][0], ["board:live", "offline"])
        self.assertEqual(out["events"][-1], ["board:live", "live"])
        self.assertEqual(out["reloads"], [0, 1])  # 有 BoardPWA 时交给它（先换上新 SW 再重载）

    def test_pwa_register(self):
        js = STATIC / "pwa.js"
        out = self.run_node(PWA_HARNESS, js, 1, 0, 1)
        self.assertIsNone(out["err"])
        self.assertEqual(out["regs"], [["/sw.js", "/"]])
        self.assertEqual(out["off"], {"cls": True, "api": True, "tip": ["board.live.offline_write", False]})
        self.assertFalse(out["back"])
        self.assertTrue(out["tipHidden"])
        for secure, static, has in ((0, 0, 1), (0, 0, 0), (1, 1, 1)):  # http（非 localhost）、没有 SW、静态导出：不注册、不报错
            out = self.run_node(PWA_HARNESS, js, secure, static, has)
            self.assertIsNone(out["err"], (secure, static, has))
            self.assertEqual(out["regs"], [], (secure, static, has))


if __name__ == "__main__":
    unittest.main()
