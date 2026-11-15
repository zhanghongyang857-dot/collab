// NOW 页增强：有 collab/ 的任务标题改去项目看板，旁边留「文档」按钮打开 PROGRESS.md；file:// 链接交给本机服务用默认应用打开；
// 订阅推送（live.js）：NOW 数据变了只拉数据重画（NOW.refresh），项目账本变了更新摘要和朝会入口（最多每 60 秒一次）；右下角标出实时 / 连接中 / 离线。
// 不看项目的运行块 r:<项目>：成员在跑时运行流每秒都在写，NOW 页不因它发任何请求（G056-T9）。
(function () {
  let byProgress = {};

  function openFile(href) {
    window.boardOpenFile(decodeURIComponent(href.replace(/^file:\/\//, "")));
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest('a[href^="file://"]');
    if (!a) return;
    e.preventDefault();
    openFile(a.getAttribute("href"));
  });

  // 有 collab/ 的任务：标题改去项目看板，后面跟摘要和一个小的「文档」按钮打开 PROGRESS.md
  // 原来的 file:// 地址记在 data-bd-src：项目摘要更新时清掉重挂；NOW 重画后的新链接由 MutationObserver 挂上
  function addChips() {
    document.querySelectorAll('a[href^="file://"]:not([data-bd]), a[data-bd-src]:not([data-bd])').forEach((a) => {
      a.dataset.bd = "1";
      const href = a.dataset.bdSrc || a.getAttribute("href");
      const p = byProgress[decodeURIComponent(href.replace(/^file:\/\//, ""))];
      if (!p) return;
      a.dataset.bdSrc = href;
      a.href = "/p/" + p.id;
      a.title = window.t("now.open_board");
      const text = window.I18n_summary(p);
      if (text) {
        const sum = document.createElement("a");
        sum.className = "bd-chip" + (window.I18n_blocked(p) ? " bd-warn" : "");
        sum.href = "/p/" + p.id;
        sum.textContent = text;
        a.after(sum);
      }
      if (window.BOARD_REMOTE) return;  // 远程设备打不开 Mac 上的文件，不放「文档」按钮
      const doc = document.createElement("a");
      doc.className = "bd-chip bd-doc";
      doc.dataset.bd = "1";
      doc.href = href;
      doc.title = window.t("now.open_doc");
      doc.textContent = window.t("board.docs");
      (a.nextElementSibling && a.nextElementSibling.classList.contains("bd-chip") ? a.nextElementSibling : a).after(doc);
    });
  }

  // 带 If-None-Match 拉（live.js 的 getJSON 自己记 ETag），没变回 null
  const getJSON = (url) => (window.BoardLive ? window.BoardLive.getJSON(url).then((r) => (r.changed ? r.data : null))
    : fetch(url, {cache: "no-store"}).then((r) => r.json()));

  let observing = false;
  function loadProjects() {
    return getJSON("/api/projects").then((list) => {
      if (!list) return;
      byProgress = {};
      list.forEach((p) => { byProgress[p.progress] = p; });
      document.querySelectorAll(".bd-chip").forEach((x) => x.remove());
      document.querySelectorAll("a[data-bd-src]").forEach((a) => { delete a.dataset.bd; });
      addChips();
      if (!observing) { observing = true; new MutationObserver(addChips).observe(document.body, {childList: true, subtree: true}); }
    }).catch(() => {});
  }
  loadProjects();

  const badge = document.createElement("div");
  badge.className = "bd-live";
  badge.innerHTML = `<span class="bd-state"></span> · ${window.t(window.BOARD_REMOTE ? "now.live_remote" : "now.live")} · <a href="/team">${window.t("team.page")}</a> · <a href="/talent">${window.t("talent.page")}</a>`;
  document.body.appendChild(badge);
  // 朝会入口：跨项目只读聚合（方案 03 第 7 节），没有进行中或待裁决的议题就不显示；项目账本变了重拉
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  function loadMeetings() {
    return getJSON("/api/meetings").then((list) => {
      if (!list) return;
      let box = document.querySelector(".bd-meet");
      if (!list.length) { if (box) box.remove(); return; }
      if (!box) {
        box = document.createElement("div");
        box.className = "bd-meet";
        document.body.appendChild(box);
      }
      box.innerHTML = `<b>${esc(window.t("board.seq.meeting"))} ${list.length}</b>` + list.map((m) =>
        `<a href="/p/${m.pid}/meet/${esc(m.id)}">${esc(m.project)} · ${esc(m.id)} ${esc(m.title)} · <span class="${m.stage === V.State.PENDING_RULING ? "bd-w" : ""}">${esc(N("state", m.stage))}</span>${m.thinking.length ? " · " + esc(window.t("board.issue.thinking", {who: m.thinking.join(window.t("sep.list"))})) : ""}</a>`).join("");
    }).catch(() => {});
  }
  loadMeetings();

  // 摘要和朝会入口最多每 60 秒拉一次：期间的多次变化合并成到点时的一次；切回前台的补拉也走这里。在后台时到点不拉，记着切回前台再拉
  const SUMMARY_MS = 60000;
  let lastSum = Date.now(), sumTimer = null;  // 上面刚拉过
  function summaries() {
    if (sumTimer) return;
    const wait = lastSum + SUMMARY_MS - Date.now();
    if (wait > 0) { sumTimer = setTimeout(() => { sumTimer = null; if (document.visibilityState !== "hidden") summaries(); }, wait); return; }
    lastSum = Date.now();
    loadProjects();
    loadMeetings();
  }

  // 推送：now 变了只拉 /api/now 重画（NOW.refresh 自己带 If-None-Match，版本号和已有的相同就不拉）；
  // 项目账本变了更新摘要小标签和朝会入口（summaries 限流）；切回前台、5 分钟兜底都补拉一次（没变就是 304）
  const NOWP = typeof NOW !== "undefined" ? NOW : {};  // 模板里的 const NOW 是全局词法变量，不在 window 上
  const pull = () => NOWP.refresh && NOWP.refresh().catch(() => {});
  if (window.BoardLive) {
    let first = true;  // 第一条推送只是记下各块版本号：摘要和朝会入口刚在上面拉过
    const live = window.BoardLive.start({
      watch: (k) => k === "now" || k.startsWith("p:"),
      shell: NOWP.shell || undefined,
      onChange: (keys, v) => {
        const seed = first;
        first = false;
        if (keys.includes("now") && String(v.now) !== String((NOWP.sync || {}).version)) pull();
        if (!seed && keys.some((k) => k.startsWith("p:"))) summaries();
      },
      onResume: () => { pull(); summaries(); },
    });
    const state = badge.querySelector(".bd-state");
    live.onState((s, at) => { state.dataset.s = s; state.textContent = window.BoardLive.label(s, at); });
    window.boardLive = live;
  }
})();
