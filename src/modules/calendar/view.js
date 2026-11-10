// 日历模块：「日历」页，按月的网格（周一开头）和日期待定栏；只读
(() => {
  const { esc, pad } = NOW.util;
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const HEAD = ["一", "二", "三", "四", "五", "六", "日"];
  const MAX = 3;
  let filter = null;  // 说明栏里选中的分类键；翻月和自动刷新都保留
  let view = null;  // 正在看的月份 {y, m}；页面每 30 秒重画一次，月份留在这里不跳回本月

  function when(e) {
    if (e.timeText !== undefined) return e.timeText || "全天";
    return e.allDay ? "全天" : e.start + (e.endTime ? "–" + e.endTime : "");
  }

  function cls(e) {
    return `${e.tentative ? " tent" : ""}${e.important ? " imp" : ""}${e.allDay ? " all" : ""}`;
  }

  // 配了 major_category 时考核项和同类事件一样显示，不再单独标记
  let showMark = true;
  const mark = e => e.exam && showMark ? `<span class="cal-exam">考核</span>` : "";

  function pill(e) {
    const t = e.start || "";
    return `<div class="cal-pill${cls(e)}" style="--c:var(--${e.cat})" title="${esc(e.title)}"><span class="cal-dot"></span>${t ? `<span class="cal-pt">${t}</span>` : ""}${mark(e)}<span class="cal-pn">${esc(e.title)}</span></div>`;
  }

  function detail(e) {
    const span = e.end && e.end !== e.date ? `<span class="cal-span">${e.date.slice(5)}～${e.end.slice(5)}</span>` : "";
    const meta = [e.place, e.note, showMark ? "" : "来源：" + e.source].filter(Boolean).map(esc).join(" · ");
    return `<div class="cal-ev${cls(e)}" style="--c:var(--${e.cat})">
      <div class="cal-t">${esc(when(e))}</div>
      <div class="cal-b"><div class="cal-title">${mark(e)}${esc(e.title)}${span}</div>
      ${meta ? `<div class="cal-meta">${meta}</div>` : ""}</div></div>`;
  }

  function closeModal() { const m = document.getElementById("cal-modal"); if (m) m.remove(); document.removeEventListener("keydown", onKey); }
  function onKey(ev) { if (ev.key === "Escape") closeModal(); }
  function openModal(k, evs) {
    closeModal();
    const d = new Date(k + "T00:00:00");
    const m = document.createElement("div");
    m.id = "cal-modal"; m.className = "cal-modal";
    m.innerHTML = `<div class="cal-dlg" role="dialog" aria-modal="true"><div class="cal-dlg-head"><b>${d.getMonth() + 1} 月 ${d.getDate()} 日 周${HEAD[(d.getDay() + 6) % 7]}</b><span class="meta">${evs.length} 项</span><button class="cal-btn" data-x>关闭</button></div>
      <div class="cal-list">${evs.length ? evs.map(detail).join("") : `<div class="empty">这天没有事件</div>`}</div></div>`;
    m.addEventListener("click", ev => { if (ev.target === m || ev.target.hasAttribute("data-x")) closeModal(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(m);
  }

  function calendar(el, ctx) {
    const D = ctx.data;
    const t0 = ctx.today0, todayK = iso(t0);
    if (!view) view = { y: t0.getFullYear(), m: t0.getMonth() };
    const first = new Date(view.y, view.m, 1);
    const lead = (first.getDay() + 6) % 7;
    const nDays = new Date(view.y, view.m + 1, 0).getDate();
    const weeks = Math.ceil((lead + nDays) / 7);
    showMark = !D.major;
    if (filter !== null && !D.legend.some(l => l.key === filter)) filter = null;
    const shown = e => filter === null || e.catKey === filter;
    const byDay = k => D.events.filter(e => shown(e) && e.date <= k && k <= (e.end || e.date));
    // 当前月的条数：多天事件算一次，只算和这个月有重叠的事件；不受筛选影响
    const m0 = iso(first), m1 = iso(new Date(view.y, view.m, nDays));
    const count = key => D.events.filter(e => e.catKey === key && e.date <= m1 && m0 <= (e.end || e.date)).length;
    const side = `<aside class="cal-side" aria-label="分类说明">${D.legend.map(l => `<button type="button" class="cal-leg${filter === l.key ? " on" : ""}" data-key="${esc(l.key)}" aria-pressed="${filter === l.key}" style="--c:var(--${l.cat})" title="${esc(l.note)}">
      <span class="cal-sw"></span><span class="cal-lg-b"><span class="cal-lg-n">${esc(l.name)}</span>${l.note ? `<span class="cal-lg-note">${esc(l.note)}</span>` : ""}</span><span class="cal-lg-c">${count(l.key)}</span></button>`).join("")}</aside>`;
    const pend = D.pending.filter(shown);
    let cells = "";
    for (let i = 0; i < weeks * 7; i++) {
      const d = new Date(view.y, view.m, 1 - lead + i), k = iso(d);
      const out = d.getMonth() !== view.m, wk = i % 7 >= 5;
      const evs = byDay(k), more = evs.length - MAX;
      cells += `<div class="cal-cell${out ? " out" : ""}${wk ? " wk" : ""}${k === todayK ? " today" : ""}" data-k="${k}">
        <div class="cal-num"><span>${d.getDate()}</span></div>
        ${evs.slice(0, MAX).map(pill).join("")}${more > 0 ? `<div class="cal-more" data-more>还有 ${more} 项</div>` : ""}</div>`;
    }
    const src = D.exists ? `<a href="${D.source}">日历.md</a>` : "还没有日历文件";
    let h = `<section class="card"><div class="card-head cal-head"><h2>${view.y} 年 ${view.m + 1} 月</h2>
      <span class="cal-nav"><button class="cal-btn" data-go="-1" aria-label="上一月">‹ 上一月</button><button class="cal-btn" data-go="0">今天</button><button class="cal-btn" data-go="1" aria-label="下一月">下一月 ›</button></span>
      <span class="meta">${src}${D.hasDeadlines ? " ｜ 含考核" : ""}</span></div>
      <div class="cal-wrap"><div class="cal-grid"><div class="cal-wd">${HEAD.map((w, i) => `<div${i > 4 ? ` class="wk"` : ""}>${w}</div>`).join("")}</div>
      <div class="cal-body" style="--rows:${weeks}">${cells}</div></div>${side}</div></section>`;
    h += `<section class="card" style="margin-top:20px"><div class="card-head"><h2>日期待定</h2><span class="meta">${pend.length} 条</span></div>`;
    h += pend.length ? `<div class="cal-list">${pend.map(detail).join("")}</div>` : `<div class="empty">没有日期待定的事件</div>`;
    h += `</section>`;
    if (D.bad.length) h += `<div class="note" style="margin-top:12px">有 ${D.bad.length} 行没读懂，已跳过：${D.bad.map(esc).join("；")}</div>`;
    el.innerHTML = h;
    el.querySelectorAll("[data-go]").forEach(b => b.onclick = () => {
      const n = +b.dataset.go;
      view = n === 0 ? { y: t0.getFullYear(), m: t0.getMonth() } : (d => ({ y: d.getFullYear(), m: d.getMonth() }))(new Date(view.y, view.m + n, 1));
      calendar(el, ctx);
    });
    el.querySelectorAll(".cal-leg").forEach(b => b.onclick = () => {
      filter = filter === b.dataset.key ? null : b.dataset.key;
      calendar(el, ctx);
    });
    el.querySelectorAll(".cal-cell").forEach(c => c.onclick = () => openModal(c.dataset.k, byDay(c.dataset.k)));
  }

  NOW.register("calendar", { tabs: { calendar } });
})();
