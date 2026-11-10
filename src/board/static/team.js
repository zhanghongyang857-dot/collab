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
  const blank = (s) => !s || /^(待填|—|-)$/.test(String(s).trim());
  const val = (s) => (blank(s) ? '<span class="tbd">待填</span>' : esc(s));
  const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
  function card(title, body, meta) {
    return `<section class="card"><div class="card-head"><h2>${title}</h2>${meta ? `<span class="meta">${meta}</span>` : ""}</div>${body}</section>`;
  }

  // 席位：任务的执行、确认，阶段的第三方验收，朝会与会；按 常坐席位 和 职能 推出
  const SEATS = [
    ["执行", (m) => /执行/.test(m.常坐席位 || "")],
    ["确认", (m) => /验收|确认/.test(m.常坐席位 || "")],
    ["第三方验收", (m) => /验收/.test(m.常坐席位 || "")],
    ["与会", (m) => /与会|朝会/.test(m.职能 || "")],
  ];
  const big = (n) => (!n ? "—" : n >= 1e8 ? (n / 1e8).toFixed(2).replace(/\.?0+$/, "") + " 亿" : n >= 1e4 ? Math.round(n / 1e4) + " 万" : String(n));
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
    const st = d.stats[m.派活名] || {};
    const running = st.running || [], holding = st.holding || [];
    const busy = running.length ? "run" : holding.length ? "hold" : "";
    const status = !(m.可用 === "✓") ? `<span class="pstat off">${esc(m.可用 || "不可用")}</span>`
      : running.length ? '<span class="pstat run"><span class="dot"></span>在跑</span>'
      : holding.length ? `<span class="pstat hold">手里 ${holding.length} 件</span>` : '<span class="pstat">空闲</span>';
    const seats = SEATS.filter(([, f]) => f(m)).map(([x]) => `<span class="seat">${x}</span>`).join("");
    const now = running.map((r) => `<li><span class="dot"></span><a href="${U(`/p/${esc(r.pid)}`)}">${esc(r.project)}</a> · ${esc(r.run)} · ${hm(r.started)} 开始</li>`)
      .concat(holding.map((h) => `<li><a href="${U(`/p/${esc(h.pid)}`)}">${esc(h.project)}</a> · ${esc(h.task)} ${esc(h.title)} · ${esc(h.state)}</li>`)).join("");
    const H = hue(m.应用);
    return `<article class="person ${busy}" id="m-${esc(m.派活名)}" style="--h:${H}">
      <header class="ph">
        <div class="avatar">${esc(initials(m.名称))}</div>
        <div class="pid"><div class="pname">${esc(m.名称)}</div><div class="psub">${esc(m.应用 || "")} · <code>${esc(m.派活名)}</code></div></div>
        ${status}
      </header>
      <div class="pgood">${blank(m.擅长) ? '<span class="tbd">擅长待填</span>' : esc(m.擅长)}</div>
      <div class="pnums">
        <div><b class="tier ${tierCls(m.能力档)}">${blank(m.能力档) ? "待定" : esc(m.能力档)}</b><span>能力档</span></div>
        <div><b>${st.runs || 0}</b><span>派活次数</span></div>
        <div title="${st.total && st.cached ? `缓存 ${Math.round((100 * st.cached) / st.total)}%` : ""}"><b>${big(st.total)}</b><span>token</span></div>
      </div>
      <div class="pseats">${seats}</div>
      <div class="pnow">${now ? `<ul class="plain">${now}</ul>` : `<span class="tbd">手上没有活${st.last ? ` · 最近一次派活 ${hm(st.last)}` : ""}</span>`}</div>
      <details class="pfile" data-file="${esc(m.派活名)}" ${openFiles.has(m.派活名) ? "open" : ""}><summary>档案</summary>
        <div class="fields">
          <span class="k">型号</span><span>${val(m.型号)}</span>
          <span class="k">相对成本</span><span>${val(m.相对成本)}</span>
          <span class="k">不适合</span><span>${val(m.不适合)}</span>
          <span class="k">职能</span><span>${val(m.职能)}</span>
        </div>
      </details>
    </article>`;
  }

  function renderMembers(d) {
    return `<div class="pintro meta">${d.members.length} 名成员 · 档案来自 班子.json；手上的活和用量从各项目的运行记录和流转现算</div>
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
        app.innerHTML = card("班子", `<div class="empty">找不到班子配置：${esc(d.source)}。班子.json 是成员的唯一来源，见工具包 core/team-example/班子.json，用 init.sh team 建立。</div>`);
      } else {
        app.innerHTML = renderMembers(d);
      }
      document.getElementById("meta").textContent = d.exists ? `${d.members.length} 名成员` : "";
      document.getElementById("tick").textContent = (SITE ? "静态演示 · 只读 · " : "每 30 秒刷新 · ") + new Date().toLocaleTimeString("zh-CN", {hour12: false});
    } catch (e) {
      document.getElementById("tick").textContent = "刷新失败：" + e.message;
    }
  }
  load();
  if (!SITE) setInterval(() => { if (document.visibilityState === "visible") load(); }, 30000);
})();
