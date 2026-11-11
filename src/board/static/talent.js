// 人才市场（规划中）：按身份列出人才——拥有哪些技能、主要擅长什么、可由哪些命令行成员扮演。
// 数据是静态的 ~/.collab-team/人才.json（没有时显示工具包示例），打开时读一次；点技能只看有这项技能的身份。
(function () {
  const app = document.getElementById("app");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const T = (k, v) => window.t(k, v);
  const tbd = () => `<span class="tbd">${esc(T("team.tbd"))}</span>`;
  const ALL = "*";
  let data = null;
  let skill = null;

  function card(title, body, meta) {
    return `<section class="card"><div class="card-head"><h2>${title}</h2>${meta ? `<span class="meta">${meta}</span>` : ""}</div>${body}</section>`;
  }

  function render() {
    const d = data;
    const skills = [...new Set(d.items.flatMap((x) => x.skills || []))];
    const list = d.items.filter((x) => !skill || (x.skills || []).includes(skill));
    const intro = `<div class="note">${T("talent.intro")}
      ${d.sample ? T("talent.sample") : T("talent.source", {path: esc(d.source)})}
      ${T("talent.later")}</div>`;
    const filter = skills.length ? `<div class="gfilter">${[ALL].concat(skills).map((k) => `<button class="chip ${(k === ALL ? !skill : skill === k) ? "on" : ""}" data-skill="${esc(k)}">${esc(k === ALL ? T("talent.all") : k)}</button>`).join("")}</div>` : "";
    const cards = list.map((x) => {
      const by = (x.played_by || []).map((n) => `${esc(n)}${d.members.includes(n) ? ` <span class="pill ok">${esc(T("talent.on_team"))}</span>` : ""}`).join(esc(T("sep.list")));
      return `<div class="tcard">
        <div class="mh"><b>${esc(x.identity)}</b>${x.status ? `<span class="pill">${esc(x.status)}</span>` : ""}</div>
        <div class="fields"><span class="k">${esc(T("talent.k.skills"))}</span><span>${(x.skills || []).map((k) => `<button class="chip ${skill === k ? "on" : ""}" data-skill="${esc(k)}">${esc(k)}</button>`).join(" ") || tbd()}</span>
          <span class="k">${esc(T("talent.k.strengths"))}</span><span>${x.strengths ? esc(x.strengths) : tbd()}</span>
          <span class="k">${esc(T("talent.k.played_by"))}</span><span>${by || tbd()}</span></div></div>`;
    }).join("");
    app.innerHTML = card(`${esc(T("talent.page"))} <span class="pill">${esc(T("talent.planned"))}</span>`, intro + filter + `<div class="mgrid">${cards || `<div class="empty">${esc(T("talent.empty"))}</div>`}</div>`,
      esc(T("talent.meta", {n: d.items.length, k: skills.length})));
    document.getElementById("meta").textContent = d.sample ? T("talent.sample_data") : "";
  }

  app.addEventListener("click", (e) => {
    const b = e.target.closest("[data-skill]");
    if (!b) return;
    const k = b.dataset.skill;
    skill = k === ALL || skill === k ? null : k;
    render();
  });

  fetch("/api/talent", {cache: "no-store"}).then((r) => r.json()).then((d) => { data = d; render(); })
    .catch((e) => { app.innerHTML = `<div class="empty">${esc(T("talent.failed"))}${esc(e.message)}</div>`; });
})();
