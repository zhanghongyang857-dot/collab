// 主屏 app 和离线（G056-T5）：各页共用。
// ① 注册根路径的 /sw.js（外壳缓存优先、数据网络优先，断线时回退上次数据，见 sw.js）。只在安全上下文（HTTPS、localhost）注册；
//    http 访问 Tailscale IP 时浏览器没有 Service Worker，这里什么都不做、不报错，其余照常；静态导出（BOARD_STATIC）不注册。
// ② 发布了新代码：新 sw.js 装好接管（controllerchange）后整页重载一次拿新代码；live.js 发现外壳指纹变了时先叫 SW 去更新再重载。
// ③ 离线时（live.js 的状态是 offline）给 <html> 加 board-offline：批准、发言这些写操作置灰（board.css），并在底部提示。
(function () {
  const sw = !window.BOARD_STATIC && window.isSecureContext && "serviceWorker" in navigator;
  let reg = null, reloading = false;

  function typing() {
    const a = document.activeElement;
    return !!a && (a.tagName === "TEXTAREA" || a.tagName === "INPUT") && !!a.value;
  }
  function reloadNow() {
    if (reloading) return;
    if (typing()) {  // 正在写发言、意见：失焦后再重载，别把草稿冲掉
      document.addEventListener("focusout", () => setTimeout(reloadNow, 0), {once: true});
      return;
    }
    reloading = true;
    location.reload();
  }

  if (sw) {
    const had = !!navigator.serviceWorker.controller;  // 第一次装上时也会 controllerchange，那时不用重载
    navigator.serviceWorker.addEventListener("controllerchange", () => { if (had) reloadNow(); });
    navigator.serviceWorker.register("/sw.js", {scope: "/"}).then((r) => { reg = r; }).catch(() => {});
    // 切回前台时顺便问一次有没有新版 sw.js（没变就是 304）
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && reg) reg.update().catch(() => {});
    });
  }

  // live.js 发现外壳指纹变了时调用：有 SW 时先让它更新，新版接管后由 controllerchange 重载；没有新版（或更新失败）4 秒后照样重载
  function reload() {
    if (!sw || !navigator.serviceWorker.controller) { reloadNow(); return; }
    const later = setTimeout(reloadNow, 4000);
    (reg ? reg.update() : navigator.serviceWorker.getRegistration().then((r) => r && r.update()))
      .then(() => {
        const r = reg || {};
        if (!r.installing && !r.waiting) { clearTimeout(later); reloadNow(); }
      })
      .catch(() => { clearTimeout(later); reloadNow(); });
  }

  // 离线：写操作置灰并提示
  let tip = null;
  function offline(on) {
    document.documentElement.classList.toggle("board-offline", on);
    if (on && !tip && document.body) {
      tip = document.createElement("div");
      tip.className = "bd-offline-tip";
      tip.dataset.i18n = "board.live.offline_write";  // 页面换成项目语言时 i18n.js 跟着换字
      document.body.appendChild(tip);
    }
    if (tip) {
      tip.textContent = window.t ? window.t("board.live.offline_write") : "Offline";
      // 有写操作的页（项目页的批红和意见、朝会页的发言）才提示；按钮可能还没画出来（卡片没展开），所以按页面认
      tip.hidden = !on || !(/^\/p\/[0-9a-f]{8}(\/meet\/I\d+)?$/.test(location.pathname) || document.querySelector("[data-goalact], #composer"));
    }
  }
  window.addEventListener("board:live", (e) => offline(e.detail.state === "offline"));

  // 加到主屏时的名字（iOS 读这个；manifest 里也有）
  const title = document.createElement("meta");
  title.name = "apple-mobile-web-app-title";
  title.content = window.t ? window.t("board.app.name") : "Board";
  document.head.appendChild(title);

  window.BoardPWA = {active: () => sw && !!navigator.serviceWorker.controller, reload, offline: () => document.documentElement.classList.contains("board-offline")};
})();
