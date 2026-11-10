// 对照模块：「对照」页（不进标签栏，从「今天」状态行的链接进入）；挂点 today.top（计划 / 已做 / 完成度 / 链接）、schedule.timeline.lanes（时间轴上的实际轨道）
(() => {
  const { CAT, esc } = NOW.util;
  const hm = (m) => { m = Math.round(m); return m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? String(m % 60).padStart(2, "0") : ""}` : `${m}m`; };
  const catVar = (c) => `var(--${c === "rest" ? "other" : c})`;
  const openDays = new Set();  // 展开的日期；页面每 30 秒重画，要记住

  // 页面只在打开时读一次数据，每 30 秒重画。进行中的那段从生成起最多再往前走几分钟，
  // 否则计时停了、页面没重新打开，数字会一直涨；再打开就是新数据
  const LIVE_CAP = 5;
  const built = new Date(DATA.built.replace(" ", "T"));
  const liveExtra = (ctx) => ctx.data.active ? Math.min(LIVE_CAP, Math.max(0, (ctx.now - built) / 6e4)) : 0;
  const isCurrent = (ctx) => ctx.data.today.date === `${ctx.now.getFullYear()}-${NOW.util.pad(ctx.now.getMonth() + 1)}-${NOW.util.pad(ctx.now.getDate())}`;

  function top(ctx) {
    const D = ctx.data;
    if (D.status !== "ok" || !isCurrent(ctx)) return "";  // 页面开过午夜：这是昨天的数据
    const T = D.today;
    const parts = [`计划 ${hm(T.planMin)}`, `已做 ${hm(T.actualMin + liveExtra(ctx))}`];
    if (T.completion !== null) parts.push(`完成 ${T.completion}%`);
    if (T.unquant) parts.push(`${T.unquant} 条未定量`);
    parts.push(`<a href="#focus">对照 →</a>`);
    return `<div class="fc-top num">${parts.join(" · ")}</div>`;
  }

  // 安排模块每画一段时间轴就问一次：这段时间（当天分钟 a–b）的实际轨道。optional 时这段没有记录就不画
  function lane(ctx, a, b, optional) {
    const D = ctx.data;
    if (D.status !== "ok" || b <= a || !isCurrent(ctx)) return "";
    const segs = D.todaySegs.map(s => ({ ...s, b: s.live ? s.b + liveExtra(ctx) : s.b })).filter(s => s.a < b && s.b > a);
    if (optional && !segs.length) return "";
    const pos = (t) => (Math.min(b, Math.max(a, t)) - a) / (b - a) * 100;
    return `<div class="fc-lane" title="实际">${segs.map(s =>
      `<i class="${s.live ? "live" : ""}" style="top:${pos(s.a)}%;height:${Math.max(pos(s.b) - pos(s.a), 3)}%;--c:${catVar(s.cat)}" title="${esc(s.activity)} ${hm(s.b - s.a)}"></i>`).join("")}</div>`;
  }

  function bar(segs, extra, scale) {
    const part = (s) => `<span style="flex:0 0 ${s.min / scale * 100}%;background:${catVar(s.cat)}" title="${esc(CAT[s.cat] || "")} ${hm(s.min)}"></span>`;
    return `<div class="fc-bar">${segs.map(part).join("")}${extra ? `<span class="off" style="flex:0 0 ${extra / scale * 100}%" title="计划外 ${hm(extra)}"></span>` : ""}</div>`;
  }

  function dayRow(d, scale) {
    const worst = d.rows[0];
    const gap = worst && worst.diff ? `${esc(worst.activity)} 计划 ${worst.plan}，实际 ${worst.actual}` : "";
    const table = d.rows.length ? `<table class="fc-table"><thead><tr><th>活动</th><th>计划</th><th>实际</th><th>差</th></tr></thead><tbody>` +
      d.rows.map(r => `<tr><td><i style="background:${catVar(r.cat)}"></i>${esc(r.activity)}</td><td class="num">${r.plan}</td><td class="num">${r.actual}</td><td class="num ${r.diff < 0 ? "neg" : ""}">${r.diff > 0 ? "+" : ""}${r.diff}</td></tr>`).join("") +
      `</tbody></table>` : `<div class="empty">这天没有定量计划，也没有记录</div>`;
    const extras = [d.firstFocus ? `首次专注 ${d.firstFocus}` : "", d.unquant ? `${d.unquant} 条未定量计划` : ""].filter(Boolean).join(" · ");
    return `<details class="fc-day" data-day="${d.date}" ${openDays.has(d.date) ? "open" : ""}>
      <summary>
        <span class="d num">${d.date.slice(5)}<small>周${d.weekday}</small></span>
        <span class="bars">${bar(d.planSegs, 0, scale)}${bar(d.actualSegs, d.unplannedMin, scale)}</span>
        <span class="res"><b class="num">${d.completion === null ? "—" : d.completion + "%"}</b><small class="num">${hm(d.planMin)} → ${hm(d.actualMin)}</small><small>${gap}</small></span>
      </summary>
      ${table}${extras ? `<div class="fc-extra">${extras}</div>` : ""}
    </details>`;
  }

  function budgetRow(r, scale) {
    const left = (r.low ?? 0) / scale * 100, right = (r.high ?? scale) / scale * 100;
    const band = r.low !== null || r.high !== null ? `<i class="band" style="left:${left}%;width:${right - left}%"></i>` : "";
    return `<div class="fc-budget ${r.state === "under" || r.state === "over" ? "off" : ""}">
      <span class="n"><i style="background:${catVar(r.cat)}"></i>${esc(r.name)}</span>
      <span class="track">${band}<i class="val" style="width:${Math.min(r.pct, scale) / scale * 100}%;--c:${catVar(r.cat)}"></i></span>
      <span class="v num">${Math.round(r.pct)}%${r.budget ? `<small>预算 ${esc(r.budget.replace(">=", "≥").replace("<=", "≤"))}</small>` : ""}</span>
    </div>`;
  }

  function tab(el, ctx) {
    const D = ctx.data;
    const back = `<a class="fc-back" href="#today">← 今天</a>`;
    if (D.status !== "ok") {
      el.innerHTML = `${back}<section class="card"><div class="card-head"><h2>对照</h2></div><div class="empty">${esc(D.message)}</div></section>`;
      return;
    }
    const scale = Math.max(60, ...D.days.flatMap(d => [d.planMin, d.actualMin]));
    let h = `${back}<section class="card"><div class="card-head"><h2>近 7 天 <span style="font-weight:400;color:var(--ink-3);font-size:14px">上面一根计划，下面一根实际；点开看明细</span></h2></div>`;
    h += D.days.map(d => dayRow(d, scale)).join("") + `</section>`;

    const W = D.week, offs = W.rows.filter(r => r.state === "under" || r.state === "over");
    const budgetScale = Math.max(50, ...W.rows.flatMap(r => [r.pct, r.high ?? 0, r.low ?? 0]));
    h += `<section class="card" style="margin-top:20px"><div class="card-head"><h2>本周分类占比 <span style="font-weight:400;color:var(--ink-3);font-size:14px">${W.start.slice(5)} → ${W.end.slice(5)}</span></h2><span class="meta num">合计 ${hm(W.totalMin)}</span></div>`;
    h += W.rows.length ? W.rows.map(r => budgetRow(r, budgetScale)).join("") : `<div class="empty">本周还没有记录，也没有配置预算</div>`;
    if (offs.length) h += `<div class="fc-verdict">${offs.map(r => `${esc(r.name)} ${Math.round(r.pct)}%，预算 ${esc(r.budget.replace(">=", "≥").replace("<=", "≤"))}`).join("；")}</div>`;
    h += `</section>`;

    const notes = [`导出生成于 ${D.generatedAt}`];
    if (D.active) notes.push(`正在计时：${esc(D.active.activity)}（${D.active.start} 起）`);
    if (D.today.unquant) notes.push(`今天有 ${D.today.unquant} 条未定量计划，没算进完成度`);
    if (D.skipped) notes.push(`${D.skipped} 条记录格式不对，没算`);
    h += `<section class="card fc-notes" style="margin-top:20px">${D.stale ? `<div class="stale">导出已经 ${hm(D.ageMin)} 没更新：专注应用可能没在运行。</div>` : ""}${notes.join(" · ")}</section>`;
    el.innerHTML = h;
    if (!el.dataset.fcBound) {
      el.dataset.fcBound = "1";
      el.addEventListener("toggle", (e) => {
        const day = e.target.dataset && e.target.dataset.day;
        if (day) { e.target.open ? openDays.add(day) : openDays.delete(day); }
      }, true);
    }
  }

  NOW.register("focus", { tabs: { focus: tab }, slots: { "today.top": top, "schedule.timeline.lanes": lane } });
})();
