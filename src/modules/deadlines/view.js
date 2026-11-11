// 截止模块：「今天」页右栏的近期截止（挂点 today.side）
(() => {
  function side(ctx) {
    const D = ctx.data;
    const upcoming = D.items
      .map(d => ({ ...d, left: Math.round((new Date(d.date + "T00:00:00") - ctx.today0) / 864e5) }))
      .filter(d => d.left >= 0);
    const row = d => {
      const cls = d.final ? "" : d.left <= 7 ? "urgent" : d.left <= 14 ? "soon" : "";
      const tt = (k, v) => window.t(k, v);
      const flags = (d.tentative ? `<span class="flag">${tt("dl.tentative")}</span>` : "") + (d.pending ? `<span class="flag">${tt("dl.tba")}</span>` : "");
      return `<div class="dl ${cls}"><div class="days"><b class="num">${d.left === 0 ? tt("dl.today_big") : d.left}</b><small>${tt(d.left === 0 ? "dl.today_small" : "sched.days_later")}</small></div>
        <div><div class="title"><span class="course" style="--c:var(--${D.cat})">${d.course}</span>${d.title}<span class="w">${d.weight}</span></div>
        <div class="when">${d.date.slice(5)} ${d.weekday} ${d.time}${flags}</div></div></div>`;
    };
    const quizzes = upcoming.filter(d => !d.final), finals = upcoming.filter(d => d.final);
    const tt = (k, v) => window.t(k, v);
    let dh = `<div class="card-head"><h2>${tt("dl.title")}</h2><span class="meta">${D.source ? `<a href="${D.source}">${D.note || tt("dl.source")}</a>` : tt("dl.no_source")}</span></div>`;
    dh += quizzes.length ? quizzes.map(row).join("") : `<div class="empty">${tt("dl.none")}</div>`;
    if (finals.length) dh += `<div class="finals-head">${tt("dl.finals")}</div><div class="finals">${finals.map(row).join("")}</div>`;
    return dh;
  }

  NOW.register("deadlines", { slots: { "today.side": side } });
})();
