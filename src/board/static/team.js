// 班子页：只展示个体——每个成员一张名片（头像、在忙还是空闲、擅长、能力档和用量、席位、手上的活，档案收起）。人才在单独的人才市场页（/talent）。
// 数据来自 /api/team：班子.json 原样给出，现状和用量由服务端从各项目运行记录和 flow.py 视图模型现算。每 30 秒刷新。
(function () {
  // 静态演示（board/export_static.py 导出、放到 GitHub Pages 等处）：window.BOARD_STATIC 给出项目、页面和到导出根的相对路径；
  // 这时数据读导出好的 JSON，链接改成相对路径，只读、不轮询。本机服务下没有它，行为不变。
  const SITE = window.BOARD_STATIC || null;
  const U = (p) => { if (!SITE) return p; const [a, h] = p.split("#"); return SITE.base + a + "/" + (h ? "#" + h : ""); };
  const getJSON = async (p) => {
    if (!SITE) return (await fetch(p, {cache: "no-store"})).json();
    const t = await (await fetch(SITE.base + p + ".json")).text();
    return JSON.parse(t.split("{{FILES}}").join(SITE.base + "/files"));
  };
  const app = document.getElementById("app");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const T = (k, v) => window.t(k, v);
  const blank = (s) => !s || /^(待填|TBD|—|-)$/i.test(String(s).trim());  // 班子配置里没填的：两种语言的示例写法
  const val = (s) => (blank(s) ? `<span class="tbd">${esc(T("team.tbd"))}</span>` : esc(s));
  const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
  function card(title, body, meta) {
    return `<section class="card"><div class="card-head"><h2>${title}</h2>${meta ? `<span class="meta">${meta}</span>` : ""}</div>${body}</section>`;
  }

  // 席位：任务的执行、确认，阶段的第三方验收，朝会与会；按 常坐席位 和 职能 推出
  // 常坐席位、职能是班子配置里手写的文字，中英两种写法都认
  const SEATS = [
    [() => N("seat", V.Seat.EXECUTOR), (m) => /执行|executor/i.test(m.usual_seat || "")],
    [() => N("seat", V.Seat.REVIEWER), (m) => /验收|确认|review/i.test(m.usual_seat || "")],
    [() => N("role", V.Role.THIRD_PARTY), (m) => /验收|review/i.test(m.usual_seat || "")],
    [() => N("seat", V.Seat.ATTENDEE), (m) => /与会|朝会|attend|meeting/i.test(m.duty || "")],
  ];
  const big = (n) => (!n ? "—" : I18n.lang() !== "zh" ? (n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n))
    : n >= 1e8 ? (n / 1e8).toFixed(2).replace(/\.?0+$/, "") + " 亿" : n >= 1e4 ? Math.round(n / 1e4) + " 万" : String(n));
  const tierCls = (t) => (/^A/.test(t) ? "a" : /^B/.test(t) ? "b" : /^C/.test(t) ? "c" : "");
  const openFiles = new Set();  // 展开了「档案」的成员，30 秒重绘时保留

  // 头像：名字里的大写字母（Codex Astra → CA，DeepSeek → DS），没有就取首字；颜色按应用区分
  function initials(name) {
    const caps = (String(name).match(/[A-Z]/g) || []).slice(0, 2).join("");
    return caps || String(name).trim().slice(0, 1);
  }
  const HUES = [222, 160, 28, 280, 340, 195];
  const VENDOR = [[/codex/i, 160], [/deepseek/i, 215], [/claude/i, 25]];
  function hue(app) {
    const v = VENDOR.find(([re]) => re.test(app || ""));
    if (v) return v[1];
    const k = String(app || "").split(/\s/)[0];
    let h = 0;
    for (const c of k) h = (h * 31 + c.charCodeAt(0)) % 997;
    return HUES[h % HUES.length];
  }

  // 一人一张卡：像名片——头像、名字、在忙还是空闲；擅长一句；三个数字；能坐的席位；手上的活；档案收起来
  function person(d, m) {
    const st = d.stats[m.dispatch_name] || {};
    const running = st.running || [], holding = st.holding || [];
    const busy = running.length ? "run" : holding.length ? "hold" : "";
    const status = !(m.available === "✓") ? `<span class="pstat off">${esc(m.available || T("team.unavailable"))}</span>`
      : running.length ? `<span class="pstat run"><span class="dot"></span>${esc(T("team.running"))}</span>`
      : holding.length ? `<span class="pstat hold">${esc(T("team.holding", {n: holding.length}))}</span>` : `<span class="pstat">${esc(T("board.rel.idle"))}</span>`;
    const seats = SEATS.filter(([, f]) => f(m)).map(([x]) => `<span class="seat">${esc(x())}</span>`).join("");
    const now = running.map((r) => `<li><span class="dot"></span><a href="${U(`/p/${esc(r.pid)}`)}">${esc(r.project)}</a> · ${esc(r.run)} · ${esc(T("team.started", {t: hm(r.started)}))}</li>`)
      .concat(holding.map((h) => `<li><a href="${U(`/p/${esc(h.pid)}`)}">${esc(h.project)}</a> · ${esc(h.task)} ${esc(h.title)} · ${esc(N("state", h.state))}</li>`)).join("");
    const H = hue(m.app);
    return `<article class="person ${busy}" id="m-${esc(m.dispatch_name)}" style="--h:${H}">
      <header class="ph">
        <div class="avatar">${esc(initials(m.name))}</div>
        <div class="pid"><div class="pname">${esc(m.name)}</div><div class="psub">${esc(m.app || "")} · <code>${esc(m.dispatch_name)}</code></div></div>
        ${status}
      </header>
      <div class="pgood">${blank(m.strengths) ? `<span class="tbd">${esc(T("team.strengths_tbd"))}</span>` : esc(m.strengths)}</div>
      <div class="pnums">
        <div><b class="tier ${tierCls(m.tier)}">${blank(m.tier) ? esc(T("team.tbd")) : esc(m.tier)}</b><span>${esc(T("team.tier"))}</span></div>
        <div><b>${st.runs || 0}</b><span>${esc(T("team.runs"))}</span></div>
        <div title="${st.total && st.cached ? esc(T("board.tok.cached", {pct: Math.round((100 * st.cached) / st.total)})) : ""}"><b>${big(st.total)}</b><span>token</span></div>
      </div>
      <div class="pseats">${seats}</div>
      <div class="pnow">${now ? `<ul class="plain">${now}</ul>` : `<span class="tbd">${esc(T("team.idle_hands"))}${st.last ? ` · ${esc(T("team.last_run", {t: hm(st.last)}))}` : ""}</span>`}</div>
      <details class="pfile" data-file="${esc(m.dispatch_name)}" ${openFiles.has(m.dispatch_name) ? "open" : ""}><summary>${esc(T("team.file"))}</summary>
        <div class="fields">
          <span class="k">${esc(T("team.k.model"))}</span><span>${val(m.model)}</span>
          <span class="k">${esc(T("team.k.cost"))}</span><span>${val(m.cost)}</span>
          <span class="k">${esc(T("team.k.weaknesses"))}</span><span>${val(m.weaknesses)}</span>
          <span class="k">${esc(T("team.field.duty"))}</span><span>${val(m.duty)}</span>
        </div>
      </details>
    </article>`;
  }

  function renderMembers(d) {
    return `<div class="pintro meta">${esc(T("team.page_intro", {n: d.members.length}))}</div>
      <div class="people">${d.members.map((m) => person(d, m)).join("")}</div>`;
  }

  app.addEventListener("toggle", (e) => {
    const k = e.target.dataset && e.target.dataset.file;
    if (k) e.target.open ? openFiles.add(k) : openFiles.delete(k);
  }, true);

  async function load() {
    try {
      const d = await getJSON("/api/team");
      if (!d.exists) {
        app.innerHTML = card(esc(T("team.page")), `<div class="empty">${esc(T("team.missing", {path: d.source}))}</div>`);
      } else {
        app.innerHTML = renderMembers(d);
      }
      document.getElementById("meta").textContent = d.exists ? T("team.count", {n: d.members.length}) : "";
      document.getElementById("tick").textContent = T(SITE ? "team.tick.static" : "team.tick.live") + new Date().toLocaleTimeString(I18n.lang() === "zh" ? "zh-CN" : "en-GB", {hour12: false});
    } catch (e) {
      document.getElementById("tick").textContent = T("board.tick.failed") + e.message;
    }
  }
  load();
  if (!SITE) setInterval(() => { if (document.visibilityState === "visible") load(); }, 30000);
})();
