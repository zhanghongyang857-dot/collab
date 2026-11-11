// 日历模块：「日历」页，按月的网格（周一开头）和日期待定栏；只读
(() => {
  const { esc, pad } = NOW.util;
  const tt = (k, v) => window.t(k, v);
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const HEAD = [1, 2, 3, 4, 5, 6, 0].map((i) => tt("cal.wd." + i));  // 周一开头
  const MAX = 3;
  let filter = null;  // 说明栏里选中的分类键；翻月和自动刷新都保留
  let view = null;  // 正在看的月份 {y, m}；页面每 30 秒重画一次，月份留在这里不跳回本月

  function when(e) {
    if (e.timeText !== undefined) return e.timeText || tt("sched.all_day");
    return e.allDay ? tt("sched.all_day") : e.start + (e.endTime ? "–" + e.endTime : "");
  }

  function cls(e) {
    return `${e.tentative ? " tent" : ""}${e.important ? " imp" : ""}${e.allDay ? " all" : ""}`;
  }

  // 配了 major_category 时考核项和同类事件一样显示，不再单独标记
  let showMark = true;
  const mark = e => e.exam && showMark ? `<span class="cal-exam">${tt("cal.exam")}</span>` : "";

  function pill(e) {
    const t = e.start || "";
    return `<div class="cal-pill${cls(e)}" style="--c:var(--${e.cat})" title="${esc(e.title)}"><span class="cal-dot"></span>${t ? `<span class="cal-pt">${t}</span>` : ""}${mark(e)}<span class="cal-pn">${esc(e.title)}</span></div>`;
  }

  function detail(e) {
    const span = e.end && e.end !== e.date ? `<span class="cal-span">${e.date.slice(5)}～${e.end.slice(5)}</span>` : "";
    const meta = [e.place, e.note, showMark ? "" : tt("cal.source", {s: tt("cal.src." + e.source)})].filter(Boolean).map(esc).join(" · ");
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
    m.innerHTML = `<div class="cal-dlg" role="dialog" aria-modal="true"><div class="cal-dlg-head"><b>${esc(tt("now.title_date", {m: d.getMonth() + 1, d: d.getDate(), wd: NOW.util.WD[d.getDay()], mon: tt("now.mon." + d.getMonth())}))}</b><span class="meta">${esc(tt("board.n_items", {n: evs.length}))}</span><button class="cal-btn" data-x>${esc(tt("cal.close"))}</button></div>
      <div class="cal-list">${evs.length ? evs.map(detail).join("") : `<div class="empty">${esc(tt("cal.no_events"))}</div>`}</div></div>`;
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
    const side = `<aside class="cal-side" aria-label="${esc(tt("cal.legend"))}">${D.legend.map(l => `<button type="button" class="cal-leg${filter === l.key ? " on" : ""}" data-key="${esc(l.key)}" aria-pressed="${filter === l.key}" style="--c:var(--${l.cat})" title="${esc(l.note)}">
      <span class="cal-sw"></span><span class="cal-lg-b"><span class="cal-lg-n">${esc(l.name)}</span>${l.note ? `<span class="cal-lg-note">${esc(l.note)}</span>` : ""}</span><span class="cal-lg-c">${count(l.key)}</span></button>`).join("")}</aside>`;
    const pend = D.pending.filter(shown);
    let cells = "";
    for (let i = 0; i < weeks * 7; i++) {
      const d = new Date(view.y, view.m, 1 - lead + i), k = iso(d);
      const out = d.getMonth() !== view.m, wk = i % 7 >= 5;
      const evs = byDay(k), more = evs.length - MAX;
      cells += `<div class="cal-cell${out ? " out" : ""}${wk ? " wk" : ""}${k === todayK ? " today" : ""}" data-k="${k}">
        <div class="cal-num"><span>${d.getDate()}</span></div>
        ${evs.slice(0, MAX).map(pill).join("")}${more > 0 ? `<div class="cal-more" data-more>${esc(tt("cal.more", {n: more}))}</div>` : ""}</div>`;
    }
    const src = D.exists ? `<a href="${D.source}">calendar.md</a>` : esc(tt("cal.no_file"));
    let h = `<section class="card"><div class="card-head cal-head"><h2>${esc(tt("cal.month", {y: view.y, m: view.m + 1, mon: tt("now.mon." + view.m)}))}</h2>
      <span class="cal-nav"><button class="cal-btn" data-go="-1" aria-label="${esc(tt("cal.prev"))}">‹ ${esc(tt("cal.prev"))}</button><button class="cal-btn" data-go="0">${esc(tt("board.today"))}</button><button class="cal-btn" data-go="1" aria-label="${esc(tt("cal.next"))}">${esc(tt("cal.next"))} ›</button></span>
      <span class="meta">${src}${D.hasDeadlines ? esc(tt("cal.with_exams")) : ""}</span></div>
      <div class="cal-wrap"><div class="cal-grid"><div class="cal-wd">${HEAD.map((w, i) => `<div${i > 4 ? ` class="wk"` : ""}>${w}</div>`).join("")}</div>
      <div class="cal-body" style="--rows:${weeks}">${cells}</div></div>${side}</div></section>`;
    h += `<section class="card" style="margin-top:20px"><div class="card-head"><h2>${esc(tt("cal.tbd_title"))}</h2><span class="meta">${esc(tt("board.n_lines", {n: pend.length}))}</span></div>`;
    h += pend.length ? `<div class="cal-list">${pend.map(detail).join("")}</div>` : `<div class="empty">${esc(tt("cal.no_tbd"))}</div>`;
    h += `</section>`;
    if (D.bad.length) h += `<div class="note" style="margin-top:12px">${esc(tt("cal.bad", {n: D.bad.length}))}${D.bad.map(esc).join(esc(tt("sep.clause")))}</div>`;
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
