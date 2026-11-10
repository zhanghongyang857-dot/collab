// 人才市场（规划中）：按身份列出人才——拥有哪些技能、主要擅长什么、可由哪些命令行成员扮演。
// 数据是静态的 ~/.collab-team/人才.json（没有时显示工具包示例），打开时读一次；点技能只看有这项技能的身份。
(function () {
  const app = document.getElementById("app");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const tbd = '<span class="tbd">待填</span>';
  let data = null;
  let skill = null;

  function card(title, body, meta) {
    return `<section class="card"><div class="card-head"><h2>${title}</h2>${meta ? `<span class="meta">${meta}</span>` : ""}</div>${body}</section>`;
  }

  function render() {
    const d = data;
    const skills = [...new Set(d.items.flatMap((x) => x.技能 || []))];
    const list = d.items.filter((x) => !skill || (x.技能 || []).includes(skill));
    const intro = `<div class="note">按<b>身份</b>找人：每个身份记拥有哪些技能、主要擅长什么、可由哪些命令行成员扮演。班子页看的是现在实际在用的成员，这里看的是能力本身。
      ${d.sample ? `现在显示的是示例数据（工具包 <code>core/team-example/人才.json</code>）；有了自己的人才库，放到班子目录的 <code>人才.json</code> 就会显示它。` : `数据来自 <code>${esc(d.source)}</code>。`}
      身份怎么划分、技能怎么描述、和班子怎么衔接，后续再定（方案 05）。</div>`;
    const filter = skills.length ? `<div class="gfilter">${["全部"].concat(skills).map((k) => `<button class="chip ${(k === "全部" ? !skill : skill === k) ? "on" : ""}" data-skill="${esc(k)}">${esc(k)}</button>`).join("")}</div>` : "";
    const cards = list.map((x) => {
      const by = (x.可由 || []).map((n) => `${esc(n)}${d.members.includes(n) ? ' <span class="pill ok">在班子</span>' : ""}`).join("、");
      return `<div class="tcard">
        <div class="mh"><b>${esc(x.身份)}</b>${x.状态 ? `<span class="pill">${esc(x.状态)}</span>` : ""}</div>
        <div class="fields"><span class="k">技能</span><span>${(x.技能 || []).map((k) => `<button class="chip ${skill === k ? "on" : ""}" data-skill="${esc(k)}">${esc(k)}</button>`).join(" ") || tbd}</span>
          <span class="k">擅长</span><span>${x.擅长 ? esc(x.擅长) : tbd}</span>
          <span class="k">可由</span><span>${by || tbd}</span></div></div>`;
    }).join("");
    app.innerHTML = card("人才市场 <span class=\"pill\">规划中</span>", intro + filter + `<div class="mgrid">${cards || '<div class="empty">还没有人才条目</div>'}</div>`,
      `${d.items.length} 个身份 · ${skills.length} 项技能`);
    document.getElementById("meta").textContent = d.sample ? "示例数据" : "";
  }

  app.addEventListener("click", (e) => {
    const b = e.target.closest("[data-skill]");
    if (!b) return;
    const k = b.dataset.skill;
    skill = k === "全部" || skill === k ? null : k;
    render();
  });

  fetch("/api/talent", {cache: "no-store"}).then((r) => r.json()).then((d) => { data = d; render(); })
    .catch((e) => { app.innerHTML = `<div class="empty">读取失败：${esc(e.message)}</div>`; });
})();
