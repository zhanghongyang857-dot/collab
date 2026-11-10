// NOW 页增强：有 collab/ 的任务标题改去项目看板，旁边留「文档」按钮打开 PROGRESS.md；file:// 链接交给本机服务用默认应用打开；定时整页刷新拿最新内容。
(function () {
  let byProgress = {};

  function openFile(href) {
    const path = decodeURIComponent(href.replace(/^file:\/\//, ""));
    fetch("/api/open", {method: "POST", headers: {"Content-Type": "application/json", "X-Board": "1"},
      body: JSON.stringify({path})});
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest('a[href^="file://"]');
    if (!a) return;
    e.preventDefault();
    openFile(a.getAttribute("href"));
  });

  // 有 collab/ 的任务：标题改去项目看板，后面跟摘要和一个小的「文档」按钮打开 PROGRESS.md
  function addChips() {
    document.querySelectorAll('a[href^="file://"]').forEach((a) => {
      if (a.dataset.bd) return;
      a.dataset.bd = "1";
      const href = a.getAttribute("href");
      const p = byProgress[decodeURIComponent(href.replace(/^file:\/\//, ""))];
      if (!p) return;
      a.href = "/p/" + p.id;
      a.title = "打开项目看板";
      if (p.summary) {
        const sum = document.createElement("a");
        sum.className = "bd-chip" + (/受阻/.test(p.summary) ? " bd-warn" : "");
        sum.href = "/p/" + p.id;
        sum.textContent = p.summary;
        a.after(sum);
      }
      const doc = document.createElement("a");
      doc.className = "bd-chip bd-doc";
      doc.dataset.bd = "1";
      doc.href = href;
      doc.title = "用默认应用打开 PROGRESS.md";
      doc.textContent = "文档";
      (a.nextElementSibling && a.nextElementSibling.classList.contains("bd-chip") ? a.nextElementSibling : a).after(doc);
    });
  }

  fetch("/api/projects").then((r) => r.json()).then((list) => {
    list.forEach((p) => { byProgress[p.progress] = p; });
    addChips();
    new MutationObserver(addChips).observe(document.body, {childList: true, subtree: true});
  });

  const live = document.createElement("div");
  live.className = "bd-live";
  live.innerHTML = '本地服务 · 回到此页时自动刷新 · <a href="/team">班子</a> · <a href="/talent">人才市场</a>';
  document.body.appendChild(live);
  // 朝会入口：跨项目只读聚合（方案 03 第 7 节），没有进行中或待裁决的议题就不显示
  fetch("/api/meetings").then((r) => r.json()).then((list) => {
    if (!list.length) return;
    const box = document.createElement("div");
    box.className = "bd-meet";
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
    box.innerHTML = `<b>朝会 ${list.length}</b>` + list.map((m) =>
      `<a href="/p/${m.pid}/meet/${esc(m.id)}">${esc(m.project)} · ${esc(m.id)} ${esc(m.title)} · <span class="${m.stage === "待裁决" ? "bd-w" : ""}">${esc(m.stage)}</span>${m.thinking.length ? " · " + esc(m.thinking.join("、")) + " 运行中" : ""}</a>`).join("");
    document.body.appendChild(box);
  }).catch(() => {});
  const loaded = Date.now();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - loaded > 30000) location.reload();
  });
})();
