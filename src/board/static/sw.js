// 看板的 Service Worker（G056-T5）：服务端从根路径 /sw.js 提供（作用域覆盖全站），并把下面的 __SHELL__ 换成当前外壳指纹。
// 发布了新代码 → 指纹变 → sw.js 内容变 → 浏览器装新版：skipWaiting + clients.claim 立即接管，删掉旧外壳缓存。
//   外壳（页面 HTML、/static/、manifest、图标）：先用本地缓存，后台再拉一次更新缓存（缓存名带指纹）
//   数据（GET /api/…）：先走网络，成功就存一份；失败回退最近一次缓存，响应头 X-Board-Cache: offline、X-Board-Cached-At 标出是缓存
//   不经 SW：写操作（POST 等）、/api/events（推送长连接）、/api/versions（判断在不在线就靠它失败）、别的站点
const SHELL = "__SHELL__";
const SHELL_CACHE = "board-shell-" + SHELL;
const DATA_CACHE = "board-data";
const PRECACHE = ["/", "/projects", "/team", "/talent", "/manifest.webmanifest",
  "/static/board.css", "/static/vocab.js", "/static/i18n.js", "/static/live.js", "/static/pwa.js",
  "/static/now-inject.css", "/static/now-inject.js", "/static/project.js",
  "/static/meet.js", "/static/team.js", "/static/talent.js", "/static/projects.js",
  "/static/icon-180.png", "/static/icon-192.png"];
const BYPASS = ["/api/events", "/api/versions", "/sw.js"];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  // 预存外壳：绕过 HTTP 缓存拿新的；个别失败（如没启用 NOW 时 / 是项目列表）不影响安装
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => Promise.all(PRECACHE.map((u) =>
    fetch(u, {cache: "reload"}).then((r) => (r.ok ? c.put(u, r) : null)).catch(() => null)))));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("board-shell-") && k !== SHELL_CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;  // 写操作直接走网络，不缓存
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || BYPASS.includes(url.pathname)) return;
  if (url.pathname.startsWith("/api/")) e.respondWith(data(req, url));
  else e.respondWith(shell(e, req, url));
});

// 外壳：缓存优先，后台更新（服务端回 no-cache + ETag，浏览器会去问，没变就是 304）。缓存键是路径加查询串，不看请求头
function shell(e, req, url) {
  const key = url.pathname + url.search;
  return caches.open(SHELL_CACHE).then((c) => c.match(key, {ignoreVary: true}).then((hit) => {
    const net = fetch(req).then((r) => {
      if (r.ok && r.type === "basic") c.put(key, r.clone()).catch(() => {});
      return r;
    });
    if (hit) {
      e.waitUntil(net.catch(() => {}));
      return hit;
    }
    return net.catch(() => (req.mode === "navigate" ? offlinePage() : Response.error()));
  }));
}

// 数据：网络优先。成功的 200 存一份（附上存的时间）；304 原样交给页面（页面手里就是这一版）。
// 回退的缓存保留 ETag：连上后页面带它去问，没变就是 304，页面上的缓存数据就是最新的
function data(req, url) {
  const key = url.pathname + url.search;
  return fetch(req).then((r) => {
    if (r.status === 200 && r.type === "basic") {
      const copy = r.clone();
      copy.blob().then((body) => {
        const h = new Headers(copy.headers);
        h.set("X-Board-Cached-At", new Date().toISOString());
        return caches.open(DATA_CACHE).then((c) => c.put(key, new Response(body, {status: 200, headers: h})));
      }).catch(() => {});
    }
    return r;
  }, () => caches.open(DATA_CACHE).then((c) => c.match(key, {ignoreVary: true})).then((hit) => {
    if (!hit) return new Response(JSON.stringify({error: "offline"}), {status: 503, headers: {"Content-Type": "application/json", "X-Board-Cache": "miss"}});
    const h = new Headers(hit.headers);
    h.set("X-Board-Cache", "offline");
    return hit.blob().then((body) => new Response(body, {status: 200, headers: h}));
  }));
}

function offlinePage() {
  return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<title>Offline</title><body style="font:15px -apple-system,sans-serif;padding:40px;color:#555">'
    + "离线：这一页还没有缓存，连上 Mac 后再打开。<br>Offline: this page isn't cached yet; open it again once the Mac is reachable."
    + '<p><a href="/">← NOW</a></p></body>', {status: 503, headers: {"Content-Type": "text/html; charset=utf-8"}});
}
