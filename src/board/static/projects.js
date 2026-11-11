// 项目列表页：没启用 NOW 时就是首页（/），启用了 NOW 时在 /projects。数据来自 /api/projects（登记表、NOW 两张表和 --project）。
(function () {
  const app = document.getElementById("app");
  const T = (k, v) => window.t(k, v);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function render(list) {
    document.getElementById("meta").textContent = list.length ? T("proj.count", {n: list.length}) : "";
    if (!list.length) {
      app.innerHTML = `<section class="card"><div class="empty">${T("proj.empty")}</div></section>`;
      return;
    }
    const done = (p) => p.state === "done";
    const sorted = list.slice().sort((a, b) => done(a) - done(b));
    app.innerHTML = `<section class="card"><div class="card-head"><h2>${esc(T("board.project_board"))}</h2></div>` + sorted.map((p) =>
      `<a class="proj-row${done(p) ? " proj-done" : ""}" href="/p/${esc(p.id)}"><b>${esc(p.name)}</b>` +
      `<span class="meta">${esc(window.I18n_summary(p) || (done(p) ? N("state", "done") : T("proj.no_goals")))}</span>` +
      `<span class="meta proj-root">${esc(p.root)}</span></a>`).join("") + "</section>";
  }

  fetch("/api/home").then((r) => r.json()).then((h) => {
    if (h.now) document.getElementById("back").hidden = false;
  }).catch(() => {});
  const load = () => fetch("/api/projects", {cache: "no-store"}).then((r) => r.json()).then(render)
    .catch(() => { app.innerHTML = `<div class="empty">${esc(T("proj.load_failed"))}</div>`; });
  load();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
})();
