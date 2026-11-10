// 项目列表页：没启用 NOW 时就是首页（/），启用了 NOW 时在 /projects。数据来自 /api/projects（登记表、NOW 两张表和 --project）。
(function () {
  const app = document.getElementById("app");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function render(list) {
    document.getElementById("meta").textContent = list.length ? list.length + " 个项目" : "";
    if (!list.length) {
      app.innerHTML = '<section class="card"><div class="empty">还没有项目。给项目装上工作台：<code>init.sh new &lt;项目目录&gt;</code>，' +
        "已装过的用 <code>init.sh register &lt;项目目录&gt;</code> 登记，刷新本页就能看到。</div></section>";
      return;
    }
    const done = (p) => p.state === "已完成";
    const sorted = list.slice().sort((a, b) => done(a) - done(b));
    app.innerHTML = '<section class="card"><div class="card-head"><h2>项目看板</h2></div>' + sorted.map((p) =>
      `<a class="proj-row${done(p) ? " proj-done" : ""}" href="/p/${esc(p.id)}"><b>${esc(p.name)}</b>` +
      `<span class="meta">${esc(p.summary || (done(p) ? "已完成" : "没有进行中的目标"))}</span>` +
      `<span class="meta proj-root">${esc(p.root)}</span></a>`).join("") + "</section>";
  }

  fetch("/api/home").then((r) => r.json()).then((h) => {
    if (h.now) document.getElementById("back").hidden = false;
  }).catch(() => {});
  const load = () => fetch("/api/projects", {cache: "no-store"}).then((r) => r.json()).then(render)
    .catch(() => { app.innerHTML = '<div class="empty">读不到项目列表</div>'; });
  load();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
})();
