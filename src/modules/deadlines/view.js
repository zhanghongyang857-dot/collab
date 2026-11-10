// 截止模块：「今天」页右栏的近期截止（挂点 today.side）
(() => {
  function side(ctx) {
    const D = ctx.data;
    const upcoming = D.items
      .map(d => ({ ...d, left: Math.round((new Date(d.date + "T00:00:00") - ctx.today0) / 864e5) }))
      .filter(d => d.left >= 0);
    const row = d => {
      const cls = d.final ? "" : d.left <= 7 ? "urgent" : d.left <= 14 ? "soon" : "";
      const flags = (d.tentative ? `<span class="flag">暂定</span>` : "") + (d.pending ? `<span class="flag">时间待公告</span>` : "");
      return `<div class="dl ${cls}"><div class="days"><b class="num">${d.left === 0 ? "今" : d.left}</b><small>${d.left === 0 ? "天" : "天后"}</small></div>
        <div><div class="title"><span class="course" style="--c:var(--${D.cat})">${d.course}</span>${d.title}<span class="w">${d.weight}</span></div>
        <div class="when">${d.date.slice(5)} ${d.weekday} ${d.time}${flags}</div></div></div>`;
    };
    const quizzes = upcoming.filter(d => !d.final), finals = upcoming.filter(d => d.final);
    let dh = `<div class="card-head"><h2>近期截止</h2><span class="meta">${D.source ? `<a href="${D.source}">${D.note || "截止来源"}</a>` : "未设置截止来源"}</span></div>`;
    dh += quizzes.length ? quizzes.map(row).join("") : `<div class="empty">没有未到期的截止事项</div>`;
    if (finals.length) dh += `<div class="finals-head">期末</div><div class="finals">${finals.map(row).join("")}</div>`;
    return dh;
  }

  NOW.register("deadlines", { slots: { "today.side": side } });
})();
