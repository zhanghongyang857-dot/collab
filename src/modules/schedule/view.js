// 安排模块：「今天」「短期」两页；挂点 header（第几周 · 主题）、status（正在做什么）、tasks.below（本月布局）
(() => {
  const { CAT, $, pad, mins, md, dayKey, fmtDur, WD } = NOW.util;
  const tt = (k, v) => window.t(k, v);  // 界面文字（变量 T 在本模块里是「今天」的数据）

  // 「今天」和「短期」都从 schedule.md 取（没有 schedule.md 时退回旧版 今天.md）
  function model(ctx) {
    const S = ctx.data, P = S.plan || { exists: false, slots: [], items: [] };
    const inDay = (it, d) => it.date === dayKey(d) && (!it.year || Number(it.year) === d.getFullYear());
    const planDay = (d) => {
      const its = P.items.filter(it => inDay(it, d));
      const what = (it) => it.kind === "node" ? `<strong>${it.what}</strong>` : it.what;
      return {
        date: dayKey(d), weekday: WD[d.getDay()], count: its.length,
        note: its.filter(it => it.when === "note").map(it => it.what).join(" "),
        slots: its.filter(it => it.start && it.end).sort((a, b) => mins(a.start) - mins(b.start)).map(it => ({ ...it, what: what(it) })),
        extras: its.filter(it => it.when !== "note" && !(it.start && it.end)).map(it => ({ label: it.when || tt("sched.all_day"), what: what(it) })),
      };
    };
    const T = P.exists ? planDay(ctx.now) : S.today;
    const isToday = T.date === dayKey(ctx.now);
    const slots = T.slots.map(s => ({ ...s, a: mins(s.start), b: mins(s.end) }));
    const curWeek = S.month.weeks.find(w => w.start && ctx.now >= md(w.start) && ctx.now < new Date(md(w.end).getTime() + 864e5));
    return { S, P, inDay, planDay, T, isToday, slots, curWeek };
  }

  function today(el, ctx) {
    const { S, P, planDay, T, isToday, slots } = model(ctx);
    const { now, nowMin } = ctx;
    const work = {};
    slots.forEach(s => { if (s.cat !== "rest") work[s.cat] = (work[s.cat] || 0) + (s.b - s.a); });
    const total = Object.values(work).reduce((x, y) => x + y, 0);

    let h = `<div class="card-head"><h2>${tt("sched.today_title")}</h2><span class="meta">${T.date} ${T.weekday} · <a href="${P.exists ? S.sources.plan : S.sources.today}">${P.exists ? "schedule.md" : "今天.md"}</a></span></div>`;
    if (P.exists && !T.count) {
      const tmr = planDay(new Date(now.getTime() + 864e5));
      h += `<div class="stale">${tt("sched.none_today")}${tt(tmr.count ? "sched.tomorrow_ready" : "sched.how_to_plan")}</div>`;
    }
    if (!isToday) h += `<div class="stale">${tt("sched.old_day", {d: T.date, w: T.weekday})}</div>`;
    if (T.note) h += `<div class="note">${T.note}</div>`;
    h += ctx.slot("today.top");
    if (total) {
      h += `<div class="alloc"><div class="alloc-bar">` +
        Object.entries(work).map(([c, m]) => `<span style="flex:${m};background:var(--${c})" title="${CAT[c]} ${fmtDur(m)}"></span>`).join("") +
        `</div><div class="legend">` +
        Object.entries(work).map(([c, m]) => `<span><i style="background:var(--${c})"></i>${CAT[c]} ${fmtDur(m)}</span>`).join("") +
        `<span style="margin-left:auto">${tt("sched.total", {t: fmtDur(total)})}</span></div></div>`;
    }
    h += `<div class="timeline">`;
    // 扩展点 schedule.timeline.lanes：别的模块给每段时间（当天分钟 a–b）画一条附加轨道，只在今天的安排上有
    const lane = (a, b, optional) => isToday ? ctx.slot("schedule.timeline.lanes", a, b, optional) : "";
    const outside = (a, b) => { const l = lane(a, b, true); return l ? `<div class="gap"><div></div><div class="rail"></div><div class="body">${tt("sched.outside")}</div>${l}</div>` : ""; };
    h += outside(0, slots.length ? slots[0].a : 1440);
    slots.forEach((s, i) => {
      if (i > 0) {
        const g = s.a - slots[i - 1].b;
        if (g >= 5) h += `<div class="gap"><div></div><div class="rail"></div><div class="body">${tt("sched.break", {t: fmtDur(g)})}</div>${lane(slots[i - 1].b, s.a)}</div>`;
      }
      const len = s.b - s.a;
      let state = "", live = "";
      if (isToday) {
        if (nowMin >= s.b) state = "past";
        else if (nowMin >= s.a) {
          state = "now";
          live = `<span class="live">${tt("sched.live", {t: fmtDur(s.b - nowMin)})}</span>`;
        }
      }
      const p = state === "now" ? Math.round((nowMin - s.a) / len * 100) : 0;
      const height = Math.max(56, Math.min(len * 0.75, 120));
      h += `<div class="slot ${s.cat === "rest" ? "rest" : ""} ${state}" style="--c:var(--${s.cat});--p:${p}%;min-height:${height}px">
        <div class="t num">${s.start}<small>${s.end}</small></div>
        <div class="rail"></div>
        <div class="body"><div class="what">${s.what}</div>
          <div class="tags">${s.task ? `<span class="pill">${s.task}</span>` : ""}<span class="dur">${fmtDur(len)}</span>${live}</div></div>
        ${lane(s.a, s.b)}
      </div>`;
    });
    if (slots.length) h += outside(slots[slots.length - 1].b, 1440);
    h += `</div>`;
    if (T.extras.length) h += `<div class="extras">${T.extras.map(e => `<div><b>${e.label}</b>${e.what}</div>`).join("")}</div>`;

    // 右栏留给其他模块（如近期截止）；没有时「今天」占满一行
    const side = ctx.slot("today.side");
    el.innerHTML = side
      ? `<div class="grid"><section class="card">${h}</section><aside class="card">${side}</aside></div>`
      : `<section class="card">${h}</section>`;
  }

  // 时钟下一行：正在做什么，或下一段什么时候开始
  function status(ctx) {
    const { T, isToday, slots } = model(ctx);
    if (!isToday) return "";
    const cur = slots.find(s => ctx.nowMin >= s.a && ctx.nowMin < s.b);
    if (cur) return `${cur.cat === "rest" ? "" : tt("sched.now_doing")}${cur.what.replace(/<[^>]+>/g, "").split(/[：；:;]/)[0]}`;
    const next = slots.find(s => s.a > ctx.nowMin);
    return next ? tt("sched.next_at", {t: next.start}) : T.slots.length ? tt("sched.day_over") : "";
  }

  function header(ctx) {
    const { S, curWeek } = model(ctx);
    return NOW.util.esc(curWeek ? `${curWeek.label} · ${curWeek.cells[0].replace(/<[^>]+>/g, "")}` : S.month.range);
  }

  // 本月布局（「短期」页下半部分）
  function month(ctx) {
    const { S, curWeek } = model(ctx);
    const M = S.month, today0 = ctx.today0;
    if (!M.exists) return "";
    const colColor = (c, i) => { const k = M.colCats[i]; return k && k !== "other" && k !== "rest" ? k : null; };
    let mh = `<div class="card-head"><h2>${tt("sched.month_title")} <span style="font-weight:400;color:var(--ink-3);font-size:14px">${M.range}</span></h2><span class="meta"><a href="${S.sources.month}">month.md</a></span></div>`;
    if (M.three_title) {
      const real = M.three.filter(x => x && !/^(待填|TBD)$/i.test(x));  // 没填的：两种语言的占位写法
      mh += `<div class="three"><b>${M.three_title}</b>${real.length ? `<ol>${real.map(x => `<li>${x}</li>`).join("")}</ol>` : `<span class="muted">${tt("sched.three_tbd")}</span>`}</div>`;
    }
    if (M.intro) mh += `<div class="intro">${M.intro}</div>`;
    if (M.weeks.length) mh += `<div class="month"><div class="colh">${tt("sched.week")}</div>` +
      M.cols.map((c, i) => { const k = colColor(c, i); return `<div class="colh">${k ? `<i style="background:var(--${k})"></i>` : ""}${c}</div>`; }).join("");
    M.weeks.forEach(w => {
      const end = w.end ? new Date(md(w.end).getTime() + 864e5) : null;
      const cls = w === curWeek ? "row-now" : end && today0 >= end ? "row-past" : "";
      mh += `<div class="wk ${cls}">${w.label}${w === curWeek ? `<span class="badge">${tt("sched.this_week")}</span>` : ""}<small class="num">${w.range}</small></div>` +
        w.cells.map((c, i) => `<div class="${cls} ${i === 0 ? "theme" : ""}" data-label="${M.cols[i]}">${c}</div>`).join("");
    });
    if (M.weeks.length) mh += `</div>`;
    if (M.pending.length) mh += M.pending.map(p => `<div class="pending">${p.replace(/^待定：/, "<b>待定：</b>")}</div>`).join("");
    return `<section class="card" style="margin-top:20px">${mh}</section>`;
  }

  // 短期：上面未来 7 天（每天一块，不显示备注和休息），下面本月布局；旧版（无 schedule.md）用 今天.md 补当天
  function plan(el, ctx) {
    const { S, P, inDay, T } = model(ctx);
    const { today0, nowMin } = ctx;
    const days = [...Array(7)].map((_, i) => new Date(today0.getTime() + i * 864e5));
    const slotIdx = (it) => {
      if (it.start) { let k = 0; P.slots.forEach((s, i) => { if (mins(it.start) >= mins(s.start)) k = i; }); return k; }
      const k = P.slots.findIndex(s => it.when && it.when.startsWith(s.name));
      return k;  // -1 = 全天
    };
    const dayItems = days.map(d => {
      const its = P.items.filter(it => inDay(it, d) && it.when !== "note" && it.cat !== "rest");
      if (P.exists || dayKey(d) !== T.date) return its;
      return T.slots.filter(s => s.cat !== "rest").map(s => ({ start: s.start, end: s.end, when: "", what: s.what, task: s.task, cat: s.cat, kind: "plain" }));
    });
    const actOf = (task) => (task.match(/（(.+)）/) || [])[1] || "";
    const item = (it, d) => {
      const t = it.start ? it.start + (it.end ? `–${it.end}` : "") : (it.when || tt("sched.all_day"));
      const act = actOf(it.task);
      const done = d.getTime() === today0.getTime() && it.end && mins(it.end) <= nowMin;
      const full = it.what.replace(/<[^>]+>/g, "").replace(/"/g, "&quot;");  // 一行放不下时悬停看全文
      return `<div class="pl-item ${it.kind || "plain"} ${done ? "done" : ""}" style="--c:var(--${it.cat === "other" ? "other" : it.cat})">` +
        `<span class="t num">${t}</span><span class="x" title="${full}">${it.what}</span><span class="a">${act && !it.what.includes(act) ? act : ""}</span></div>`;
    };
    const dayHead = (d, i) => `<div class="pl-date ${d.getDay() % 6 === 0 ? "wkend" : ""}"><span class="d num">${dayKey(d)}</span><span class="w">${WD[d.getDay()]}</span>${i === 0 ? `<span class="badge">${tt("board.today")}</span>` : ""}</div>`;
    const blank = (from, to) => `<div class="pl-blank"><span class="num">${dayKey(from)} ${WD[from.getDay()]}${to > from ? ` → ${dayKey(to)} ${WD[to.getDay()]}` : ""}</span><span>${tt("sched.not_planned")}</span></div>`;
    let ph = `<div class="card-head"><h2>${tt("sched.next7")} <span style="font-weight:400;color:var(--ink-3);font-size:14px">${dayKey(days[0])} → ${dayKey(days[6])}</span></h2><span class="meta"><a href="${S.sources.plan}">schedule.md</a></span></div>`;
    const nodes = [];
    dayItems.forEach((its, i) => its.forEach(it => { if (it.kind === "node") nodes.push({ it, d: days[i], i }); }));
    if (nodes.length) {
      ph += `<div class="pl-nodes">` + nodes.map(({ it, d, i }) =>
        `<div class="pl-node" style="--c:var(--${it.cat === "other" ? "other" : it.cat})"><div class="nw"><span class="num">${dayKey(d)}</span> ${WD[d.getDay()]}${it.when ? ` · ${it.when}` : ""}</div>` +
        `<div class="nm">${it.what}</div><div class="nl num">${i ? `${i}<small>${tt("sched.days_later")}</small>` : tt("board.today")}</div></div>`).join("") + `</div>`;
    }
    if (!dayItems.some(x => x.length)) {
      ph += `<div class="empty">${tt("sched.next7_empty")}</div>`;
    } else {
      // 每天一块；不是今天的空白日子连着的合并成一行，不占地方
      ph += `<div class="pl-days">`;
      let gapFrom = null;
      const flush = (to) => { if (gapFrom) ph += blank(gapFrom, to); gapFrom = null; };
      days.forEach((d, i) => {
        if (!dayItems[i].length && i > 0) { gapFrom = gapFrom || d; return; }
        flush(days[i - 1]);
        const its = [...dayItems[i]].sort((a, b) => slotIdx(a) - slotIdx(b) || (a.start || "").localeCompare(b.start || ""));
        ph += `<div class="pl-row ${i === 0 ? "is-today" : ""}">${dayHead(d, i)}<div class="pl-items">` +
          (its.length ? its.map(it => item(it, d)).join("") : `<div class="pl-none">${tt("sched.today_not_planned")}</div>`) + `</div></div>`;
      });
      flush(days[6]);
      ph += `</div>`;
    }
    el.innerHTML = `<section class="card">${ph}</section>${month(ctx)}`;
  }

  NOW.register("schedule", { tabs: { today, plan }, slots: { header, status } });
})();
