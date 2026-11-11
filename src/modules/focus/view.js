// 对照模块：「对照」页（不进标签栏，从「今天」状态行的链接进入）；挂点 today.top（计划 / 已做 / 完成度 / 链接）、schedule.timeline.lanes（时间轴上的实际轨道）
(() => {
  const { CAT, esc } = NOW.util;
  const tt = (k, v) => window.t(k, v);
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
    const parts = [tt("focus.planned", {t: hm(T.planMin)}), tt("focus.done", {t: hm(T.actualMin + liveExtra(ctx))})];
    if (T.completion !== null) parts.push(tt("focus.completion", {n: T.completion}));
    if (T.unquant) parts.push(tt("focus.unquant", {n: T.unquant}));
    parts.push(`<a href="#focus">${esc(tt("now.tab.focus"))} →</a>`);
    return `<div class="fc-top num">${parts.join(" · ")}</div>`;
  }

  // 安排模块每画一段时间轴就问一次：这段时间（当天分钟 a–b）的实际轨道。optional 时这段没有记录就不画
  function lane(ctx, a, b, optional) {
    const D = ctx.data;
    if (D.status !== "ok" || b <= a || !isCurrent(ctx)) return "";
    const segs = D.todaySegs.map(s => ({ ...s, b: s.live ? s.b + liveExtra(ctx) : s.b })).filter(s => s.a < b && s.b > a);
    if (optional && !segs.length) return "";
    const pos = (t) => (Math.min(b, Math.max(a, t)) - a) / (b - a) * 100;
    return `<div class="fc-lane" title="${esc(tt("focus.actual"))}">${segs.map(s =>
      `<i class="${s.live ? "live" : ""}" style="top:${pos(s.a)}%;height:${Math.max(pos(s.b) - pos(s.a), 3)}%;--c:${catVar(s.cat)}" title="${esc(s.activity)} ${hm(s.b - s.a)}"></i>`).join("")}</div>`;
  }

  function bar(segs, extra, scale) {
    const part = (s) => `<span style="flex:0 0 ${s.min / scale * 100}%;background:${catVar(s.cat)}" title="${esc(CAT[s.cat] || "")} ${hm(s.min)}"></span>`;
    return `<div class="fc-bar">${segs.map(part).join("")}${extra ? `<span class="off" style="flex:0 0 ${extra / scale * 100}%" title="${esc(tt("focus.unplanned", {t: hm(extra)}))}"></span>` : ""}</div>`;
  }

  function dayRow(d, scale) {
    const worst = d.rows[0];
    const gap = worst && worst.diff ? esc(tt("focus.gap", {a: worst.activity, p: worst.plan, r: worst.actual})) : "";
    const table = d.rows.length ? `<table class="fc-table"><thead><tr>${["activity", "plan", "actual", "diff"].map((k) => `<th>${esc(tt("focus.th." + k))}</th>`).join("")}</tr></thead><tbody>` +
      d.rows.map(r => `<tr><td><i style="background:${catVar(r.cat)}"></i>${esc(r.activity)}</td><td class="num">${r.plan}</td><td class="num">${r.actual}</td><td class="num ${r.diff < 0 ? "neg" : ""}">${r.diff > 0 ? "+" : ""}${r.diff}</td></tr>`).join("") +
      `</tbody></table>` : `<div class="empty">${esc(tt("focus.day_empty"))}</div>`;
    const extras = [d.firstFocus ? tt("focus.first", {t: d.firstFocus}) : "", d.unquant ? tt("focus.unquant_plan", {n: d.unquant}) : ""].filter(Boolean).join(" · ");
    return `<details class="fc-day" data-day="${d.date}" ${openDays.has(d.date) ? "open" : ""}>
      <summary>
        <span class="d num">${d.date.slice(5)}<small>${esc(NOW.util.WD[d.weekday_n ?? 0])}</small></span>
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
      <span class="v num">${Math.round(r.pct)}%${r.budget ? `<small>${esc(tt("focus.budget", {b: r.budget.replace(">=", "≥").replace("<=", "≤")}))}</small>` : ""}</span>
    </div>`;
  }

  function tab(el, ctx) {
    const D = ctx.data;
    const back = `<a class="fc-back" href="#today">← ${esc(tt("now.tab.today"))}</a>`;
    if (D.status !== "ok") {
      el.innerHTML = `${back}<section class="card"><div class="card-head"><h2>${esc(tt("now.tab.focus"))}</h2></div><div class="empty">${esc(tt("focus.msg." + D.status, D.vars || {}))}</div></section>`;
      return;
    }
    const scale = Math.max(60, ...D.days.flatMap(d => [d.planMin, d.actualMin]));
    let h = `${back}<section class="card"><div class="card-head"><h2>${esc(tt("focus.last7"))} <span style="font-weight:400;color:var(--ink-3);font-size:14px">${esc(tt("focus.last7_hint"))}</span></h2></div>`;
    h += D.days.map(d => dayRow(d, scale)).join("") + `</section>`;

    const W = D.week, offs = W.rows.filter(r => r.state === "under" || r.state === "over");
    const budgetScale = Math.max(50, ...W.rows.flatMap(r => [r.pct, r.high ?? 0, r.low ?? 0]));
    h += `<section class="card" style="margin-top:20px"><div class="card-head"><h2>${esc(tt("focus.week_share"))} <span style="font-weight:400;color:var(--ink-3);font-size:14px">${W.start.slice(5)} → ${W.end.slice(5)}</span></h2><span class="meta num">${esc(tt("focus.total", {t: hm(W.totalMin)}))}</span></div>`;
    h += W.rows.length ? W.rows.map(r => budgetRow(r, budgetScale)).join("") : `<div class="empty">${esc(tt("focus.week_empty"))}</div>`;
    if (offs.length) h += `<div class="fc-verdict">${offs.map(r => esc(tt("focus.verdict", {name: r.name, pct: Math.round(r.pct), b: r.budget.replace(">=", "≥").replace("<=", "≤")}))).join(esc(tt("sep.clause")))}</div>`;
    h += `</section>`;

    const notes = [esc(tt("focus.n.generated", {t: D.generatedAt}))];
    if (D.active) notes.push(esc(tt("focus.n.active", {a: D.active.activity, t: D.active.start})));
    if (D.today.unquant) notes.push(esc(tt("focus.n.unquant", {n: D.today.unquant})));
    if (D.skipped) notes.push(esc(tt("focus.n.skipped", {n: D.skipped})));
    h += `<section class="card fc-notes" style="margin-top:20px">${D.stale ? `<div class="stale">${esc(tt("focus.n.stale", {t: hm(D.ageMin)}))}</div>` : ""}${notes.join(" · ")}</section>`;
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
