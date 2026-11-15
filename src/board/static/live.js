// 推送订阅（G056）：各页共用。订阅 /api/events（SSE），本页关心的块版本号变了就回调；断线按指数退避重连，
// 推送不通（连接上限、代理攒着不发）时退回每 2 秒拉 /api/versions；切回前台重连并回调 onResume 让页面补拉；
// 在前台时每 5 分钟也回调一次 onResume（有的数据在监视清单以外）。状态三态：live 实时 / connecting 连接中 / offline 离线。
//
// 用法：const live = BoardLive.start({
//   watch: ["now"] 或 (key) => key.startsWith("p:"),  // 关心哪些块
//   onChange: (keys, versions) => …,                    // 关心的块版本号变了（按「不等」判断）
//   onResume: () => …,                                  // 切回前台、5 分钟兜底：页面自己带 If-None-Match 补拉一次
//   onShell: (fp) => …,                                 // 外壳指纹变了（发布了新代码）；不给时整页重载一次
//   shell: "ab12…",                                     // 本页外壳指纹，不知道时不给（以第一次收到的为准）
// });
// live.seen("now", 版本号)：页面自己拉到数据时记下版本号，推送来的版本号相同就不再回调
// live.onState((state, lastOk) => …)；live.state、live.lastOk（最近一次连上 Mac 的时间）；BoardLive.label(state, lastOk) 给出界面文字
// BoardLive.getJSON(url)：自己记 ETag、带 If-None-Match 拉 JSON，不靠浏览器 HTTP 缓存；没变回 {changed: false, version, runVersion}，
//   变了回 {changed: true, data, version, runVersion}（version 是响应头 X-Board-Version，项目的账本块 p:<项目>；
//   runVersion 是 X-Board-Run-Version，运行块 r:<项目>；都可交给 live.seen）
// BoardLive.pages(opts)：项目、朝会、班子、人才页的共用接法——推送来本页的块才 load()，前台时另有保底轮询（默认 60 秒）；
//   拉到的版本号比推送来的旧（服务端运行类最多 10 秒重算一次，期间回上次结果）时，过 10 秒再拉一次
// 离线（G056-T5）：Service Worker 断线时回退上次数据，响应头带 X-Board-Cache: offline 和 X-Board-Cached-At；
//   BoardLive.noteResponse(r) 看到它就把各订阅标成离线、「截至」取缓存的时间（刚打开、还没连上过时也有时间）。getJSON 自己调；
//   状态每次变化另发 window 事件 board:live（detail: {state, lastOk}），pwa.js 据此把写操作置灰
(function () {
  const POLL_MS = 2000;       // 推送不通时拉版本号的间隔
  const RESUME_MS = 300000;   // 前台兜底补拉
  const FIRST_MS = 5000;      // 连上后这么久没收到第一条，当作代理攒着不发
  const MAX_BACKOFF = 30000;
  const SHELL_KEY = "board.shell-reload";

  function reloadOnce(fp) {
    // 防止外壳指纹算法对不上时反复重载：同一个指纹 60 秒内只重载一次
    let last = null;
    try { last = JSON.parse(sessionStorage.getItem(SHELL_KEY) || "null"); } catch (e) { last = null; }
    if (last && last.fp === fp && Date.now() - last.at < 60000) return false;
    try { sessionStorage.setItem(SHELL_KEY, JSON.stringify({fp, at: Date.now()})); } catch (e) { /* 无痕模式 */ }
    if (window.BoardPWA) window.BoardPWA.reload(); else location.reload();  // 有 SW 时先让它换上新外壳，不然重载拿到的还是缓存的旧代码
    return true;
  }

  function start(opts) {
    opts = opts || {};
    const want = typeof opts.watch === "function" ? opts.watch : (k) => (opts.watch || []).includes(k);
    const known = {};             // 块 → 本页已有的版本号
    let shell = opts.shell || null;
    let es = null, firstTimer = null, retryTimer = null, pollTimer = null, resumeTimer = null;
    let fails = 0, sseOk = false, stopped = false, cachedOff = false;  // cachedOff：拿到过 SW 回退的缓存，重试期间一直标离线
    const listeners = [];
    const api = {state: "connecting", lastOk: null};

    function setState(s, force) {
      if (s === "live") { api.lastOk = new Date(); cachedOff = false; }
      if (s === api.state && s !== "live" && !force) return;
      const changed = s !== api.state || force;
      api.state = s;
      if (!changed) return;
      listeners.forEach((f) => { try { f(s, api.lastOk); } catch (e) { console.error(e); } });
      if (typeof CustomEvent === "function" && window.dispatchEvent) window.dispatchEvent(new CustomEvent("board:live", {detail: {state: s, lastOk: api.lastOk}}));
    }

    function handle(versions) {
      setState("live");
      if (versions.shell != null && versions.shell !== "") {
        if (shell == null) shell = versions.shell;
        else if (versions.shell !== shell) {
          if (opts.onShell) opts.onShell(versions.shell); else reloadOnce(versions.shell);
          return;
        }
      }
      const keys = Object.keys(versions).filter((k) => k !== "shell" && want(k) && String(versions[k]) !== String(known[k]));
      if (!keys.length) return;
      keys.forEach((k) => { known[k] = versions[k]; });
      if (opts.onChange) opts.onChange(keys, versions);
    }

    function close() {
      clearTimeout(firstTimer);
      if (es) { es.onerror = es.onopen = null; es.close(); es = null; }
      sseOk = false;
    }

    function connect() {
      close();
      clearTimeout(retryTimer);
      if (stopped || typeof EventSource === "undefined") { poll(); return; }
      if (api.state !== "live" && !(cachedOff && api.state === "offline")) setState("connecting");
      const src = new EventSource("/api/events");
      es = src;
      firstTimer = setTimeout(() => { if (es === src && !sseOk) fail(); }, FIRST_MS);
      src.addEventListener("change", (e) => {
        if (es !== src) return;
        let v;
        try { v = JSON.parse(e.data); } catch (err) { return; }
        if (!sseOk) { sseOk = true; fails = 0; clearTimeout(firstTimer); stopPoll(); }
        handle(v);
      });
      src.onerror = () => { if (es === src) fail(); };
    }

    function fail() {
      close();
      fails += 1;
      poll();  // 推送断了：先拉一次版本号，Mac 在就每 2 秒拉，直到推送重新连上
      retryTimer = setTimeout(connect, Math.min(MAX_BACKOFF, 1000 * 2 ** Math.min(fails - 1, 5)));
    }

    function stopPoll() { clearTimeout(pollTimer); pollTimer = null; }

    function poll() {
      stopPoll();
      if (stopped || sseOk) return;
      fetch("/api/versions", {cache: "no-store"})
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then((d) => { if (!sseOk) handle(d.versions || {}); })
        .catch(() => { if (!sseOk) setState(fails >= 2 || navigator.onLine === false || cachedOff ? "offline" : "connecting"); })
        .finally(() => {
          if (!stopped && !sseOk && document.visibilityState !== "hidden") pollTimer = setTimeout(poll, POLL_MS);
        });
    }

    function armResume() {
      clearTimeout(resumeTimer);
      if (!stopped && document.visibilityState !== "hidden") resumeTimer = setTimeout(() => { resume(false); }, RESUME_MS);
    }

    function resume(reconnect) {
      if (stopped) return;
      if (reconnect) { fails = 0; connect(); }
      if (opts.onResume) opts.onResume();
      armResume();
    }

    // 切回前台：iOS 在后台会掐断连接，重连并补拉一次；转到后台时停掉短轮询和兜底计时
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") resume(true);
      else { stopPoll(); clearTimeout(resumeTimer); }
    });
    window.addEventListener("pageshow", (e) => { if (e.persisted) resume(true); });  // 从往返缓存回来
    window.addEventListener("online", () => { if (!sseOk) { fails = 0; connect(); } });
    window.addEventListener("offline", () => setState("offline"));

    // 拿到的是 SW 回退的缓存：没连上就标离线，「截至」不早于缓存的时间
    api.cached = (at) => {
      if (at && !isNaN(at) && (!api.lastOk || at > api.lastOk)) api.lastOk = at;
      if (api.state !== "live") { cachedOff = true; setState("offline", true); }
    };
    instances.push(api);
    api.seen = (key, version) => { if (version != null && version !== "") known[key] = version; };
    api.onState = (f) => { listeners.push(f); f(api.state, api.lastOk); };
    api.refreshNow = () => resume(true);
    api.stop = () => { stopped = true; close(); stopPoll(); clearTimeout(retryTimer); clearTimeout(resumeTimer); };
    if (!cachedAt && window.BOARD_CACHED_AT) {  // NOW 页的 refresh() 在 live.js 载入前就拿到了缓存，先记在这里
      const at = new Date(window.BOARD_CACHED_AT);
      if (!isNaN(at)) cachedAt = at;
    }
    if (cachedAt) api.cached(cachedAt);
    connect();
    armResume();
    return api;
  }

  const instances = [];  // start() 开的订阅：noteResponse 要通知它们
  let cachedAt = null;   // 最近一次从 SW 缓存拿到的数据是什么时候存的（订阅还没开时先记着）
  function noteResponse(r) {
    if (!r || !r.headers || r.headers.get("X-Board-Cache") !== "offline") return false;
    const at = new Date(r.headers.get("X-Board-Cached-At") || "");
    if (!isNaN(at) && (!cachedAt || at > cachedAt)) cachedAt = at;
    instances.forEach((api) => api.cached(at));
    return true;
  }

  const etags = {};  // 地址 → 上次拿到的 ETag
  async function getJSON(url) {
    const headers = etags[url] ? {"If-None-Match": etags[url]} : {};
    const r = await fetch(url, {cache: "no-store", headers});
    noteResponse(r);
    const version = r.headers.get("X-Board-Version"), runVersion = r.headers.get("X-Board-Run-Version");
    if (r.status === 304) return {changed: false, version, runVersion};
    const data = await r.json();
    const tag = r.headers.get("ETag");
    if (r.ok && tag) etags[url] = tag; else delete etags[url];
    return {changed: true, data, version, runVersion};
  }

  // 页面接法：opts = {watch, load, every}。load() 自己用 getJSON 拉；同一时间只跑一次，跑的时候又来了变化就跑完再补一次——
  // 推送来的版本号如果这次 load 已经 seen 过（打开页面时推送首条常和第一次拉数据撞在一起），就不补。
  // 保底轮询只在前台跑（every 默认 60 秒）；切回前台、5 分钟兜底由 live.js 回调 load。
  const LAG_MS = 10000;  // 拉到的比推送来的旧：服务端运行类最多 10 秒重算一次，过这么久再拉
  function pages(opts) {
    let running = null, again = null, got = {}, lagTimer = null;
    const pushed = {};  // 块 → 推送来的最新版本号
    const run = (pending) => {
      if (running) {
        if (again !== true) again = pending ? {...(again || {}), ...pending} : true;
        return running;
      }
      got = {};
      running = Promise.resolve().then(opts.load).catch((e) => console.error(e)).finally(() => {
        running = null;
        const a = again;
        again = null;
        if (a && (a === true || Object.keys(a).some((k) => got[k] !== String(a[k])))) { run(); return; }
        const behind = Object.keys(pushed).some((k) => got[k] != null && Number(got[k]) < Number(pushed[k]));
        if (behind && !lagTimer) lagTimer = setTimeout(() => { lagTimer = null; run(); }, LAG_MS);
      });
      return running;
    };
    const live = start({watch: opts.watch, onResume: () => run(),
      onChange: (keys, versions) => { keys.forEach((k) => { pushed[k] = versions[k]; }); run(Object.fromEntries(keys.map((k) => [k, versions[k]]))); }});
    const seen = live.seen;
    live.seen = (key, version) => { if (version != null && version !== "") got[key] = String(version); seen(key, version); };
    setInterval(() => { if (document.visibilityState === "visible") run(); }, opts.every || 60000);
    live.load = () => run();
    // 页面右上角的 tick：连着时显示页面给的文字，断了时前面加「连接中 / 离线 · 截至 HH:MM」
    let tick = "";
    const paint = () => {
      const el = document.getElementById("tick");
      if (el) el.textContent = live.state === "live" ? tick : label(live.state, live.lastOk) + (tick ? " · " + tick : "");
    };
    live.tick = (text) => { tick = text; paint(); };
    live.onState(paint);
    return live;
  }

  function label(state, lastOk) {
    const t = window.t || ((k) => k);
    if (state === "live") return t("board.live.live");
    if (state === "offline") {
      const p = (n) => String(n).padStart(2, "0");
      return lastOk ? t("board.live.offline_since", {t: `${p(lastOk.getHours())}:${p(lastOk.getMinutes())}`}) : t("board.live.offline");
    }
    return t("board.live.connecting");
  }

  window.BoardLive = {start, label, reloadOnce, getJSON, pages, noteResponse};
})();
