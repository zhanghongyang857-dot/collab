// 御前看板：每 5 秒拉一次项目数据并重绘；展开状态保留。
// /p/<id>/archive 是归档页：只看归档的目标、任务、议题，打开时加载一次，不轮询。
// 服务端给的 *Html 字段（来自 Markdown，已转义）用 innerHTML，其余一律转义。
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
  const fileHref = (abs) => (SITE ? SITE.base + "/files" + encodeURI(abs) + ".html" : "file://" + encodeURI(abs));
  const [, id, archiveSeg] = SITE ? [null, SITE.project, SITE.archive ? "/archive" : ""] : location.pathname.match(/^\/p\/([0-9a-f]+)(\/archive)?/) || [];
  const ARCHIVE = !!archiveSeg;
  const app = document.getElementById("app");
  const COLS = [
    {name: "待开始", match: (s) => /^(规划中|已交接|已批准|暂停)/.test(s)},
    {name: "执行中", match: (s) => s.startsWith("执行中")},
    {name: "待验收", match: (s) => s.startsWith("待验收")},
    {name: "需处理", match: (s) => /^(需补充|未通过|受阻)/.test(s)},
    {name: "通过", match: (s) => s.startsWith("通过")},
  ];
  const STALE_MIN = 10;
  let openTask = ARCHIVE ? (location.hash.match(/^#((?:G\d+-)?T\d+)$/) || [])[1] || null : null;
  let openGoal = null;
  let openCard = null;  // 时序图下面展开的任务卡
  const openRecord = new Set();  // 展开了「筹备和记录」的目标
  const drafts = {};  // 正在写的意见：自动刷新不能冲掉
  let apprMsg = "";
  let openIssue = null;
  // 选中的目标：只在「目标」总览里选，泳道、任务、派活记录都跟着它；不选时任务和记录看全部，泳道展开排第一的目标
  let selGoal = (location.hash.match(/^#(G\d+)$/) || [])[1] || null;
  const openSpeech = new Set();
  const CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩";
  const circ = (n) => CIRCLED[n - 1] || String(n);
  const openRuns = new Set();
  let data = null;
  let lastSig = "";

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const strip = (h) => String(h || "").replace(/<[^>]+>/g, "");
  // 「已运行」「无动作」按项目时钟算：演示案例停在剧情里的某一刻（接口带 clock），否则是真实时间
  const secs = (iso) => (iso ? Math.max(0, ((data && data.clock ? new Date(data.clock).getTime() : Date.now()) - new Date(iso).getTime()) / 1000) : null);
  function dur(s) {
    if (s == null) return "—";
    s = Math.round(s);
    if (s < 60) return s + " 秒";
    if (s < 3600) return Math.floor(s / 60) + " 分" + (s % 60 ? " " + (s % 60) + " 秒" : "");
    return Math.floor(s / 3600) + " 小时 " + Math.floor((s % 3600) / 60) + " 分";
  }
  function tok(t) {
    if (!t || !t.total) return "—";
    const n = t.total, s = n >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, "") + "万" : String(n);
    return t.cached ? `${s} · 缓存${Math.round((100 * t.cached) / n)}%` : s;
  }
  function tokDetail(t) {
    if (!t || !t.total) return "token 未知";
    const parts = [`token ${tok(t)}`, `输入 ${t.input || 0}`, `缓存 ${t.cached || 0}`, `输出 ${t.output || 0}`];
    if (t.calls) parts.push(`调用 ${t.calls} 次`);
    if (t.context) parts.push(`最后上下文 ${t.context}`);
    if (t.cost_usd) parts.push(`约 ${t.cost_usd} 美元`);
    return parts.join(" · ");
  }
  function sumTok(runs) {
    const s = {total: 0, cached: 0};
    runs.forEach((r) => { if (r.tokens) { s.total += r.tokens.total || 0; s.cached += r.tokens.cached || 0; } });
    return s;
  }
  const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
  function statusPill(s) {
    const cls = s === "运行中" ? "run" : s === "完成" || s.startsWith("通过") ? "ok"
      : /失败|异常|未通过/.test(s) ? "bad" : /中断|需补充|受阻/.test(s) ? "warn" : "";
    return `<span class="pill ${cls}">${s === "运行中" ? '<span class="dot"></span>' : ""}${esc(s)}</span>`;
  }

  function card(title, body, opts = {}) {
    return `<section class="card ${opts.cls || ""}"><div class="card-head"><h2>${title}</h2>${opts.meta ? `<span class="meta">${opts.meta}</span>` : ""}</div>${body}</section>`;
  }

  // 「待你决定」一条的约定格式：编号｜要决定什么｜可选方案与代价｜总管建议｜验收意见｜提出者；不合格式的原样显示
  function pendingCard(html) {
    const f = html.split("｜").map((x) => x.trim());
    if (f.length < 4) return `<div class="pend raw">${html}</div>`;
    let [id, what, opts, sug, chk, by] = f;
    const sample = /^（示例）/.test(strip(id));
    id = id.replace(/^（示例）\s*/, "");
    const pick = (strip(sug).match(/[A-Z]/) || [])[0];
    const list = opts.split(/[；;]\s*(?=[A-Z][\s　])/).map((o) => {
      const m = strip(o).match(/^([A-Z])[\s　]/);
      const on = m && m[1] === pick;
      return `<li class="${on ? "pick" : ""}">${o}${on ? ' <span class="sug">总管建议</span>' : ""}</li>`;
    }).join("");
    const plainId = strip(id).trim();
    const link = /^(G\d+-)?T\d+$/.test(plainId) && data.cards.some((t) => t.id === plainId) ? ` data-task="${esc(plainId)}"`
      : /^G\d+$/.test(plainId) ? ` data-goal="${esc(plainId)}"` : /^I\d+$/.test(plainId) ? ` data-issue="${esc(plainId)}"` : "";
    const extra = pick ? "" : `<div class="note">${sug}</div>`;
    const km = strip(what).match(/^(受阻|批准[^：:]*|目标验收|裁决|返工|授权|总裁意见[^：:]*)[：:]\s*/);
    const kind = km ? km[1] : "";
    if (km) what = what.replace(/^[^：:]*[：:]\s*/, "");
    const kcls = /受阻/.test(kind) ? "bad" : /返工/.test(kind) ? "warn" : "run";
    const check = chk && !/^[—\-\s]*$/.test(strip(chk)) ? `<div class="note">验收意见：${chk}</div>` : "";
    return `<div class="pend ${kind ? "k-" + kcls : ""}"><div class="ph"><span class="tid ${link ? "tlink" : ""}"${link}>${id}</span>${kind ? `<span class="pill ${kcls}">${esc(kind)}</span>` : ""}${sample ? '<span class="pill">示例</span>' : ""}<span class="pw">${what}</span>${by ? `<span class="meta">提出：${by}</span>` : ""}</div>
      <ul class="popts">${list}</ul>${extra}${check}</div>`;
  }

  // 校验结果（core/check.py）：错误会挡住派活和 Claude 的每轮结束，提醒只显示
  function renderCheck(d) {
    const items = d.check || [];
    if (!items.length) return "";
    const errs = items.filter((x) => x.level === "error"), warns = items.filter((x) => x.level !== "error");
    const li = (x) => `<li class="${x.level === "error" ? "e" : "w"}"><span class="loc">${esc(x.file)}${x.line ? ":" + x.line : ""}</span>${esc(x.msg)}</li>`;
    const title = errs.length ? `校验：${errs.length} 个错误${warns.length ? `，${warns.length} 个提醒` : ""}` : `校验：${warns.length} 个提醒`;
    if (!errs.length) return `<details class="checkline"><summary>${title}</summary><ul class="checks">${warns.map(li).join("")}</ul></details>`;
    const note = '<div class="note">有错误时派活脚本不派活，Claude 每轮结束会被要求先改好。</div>';
    return card(title, `<ul class="checks">${errs.concat(warns).map(li).join("")}</ul>${note}`, {cls: errs.length ? "check-bad" : "alert"});
  }

  function renderPending(d) {
    const body = d.pending.length ? d.pending.map(pendingCard).join("") : `<div class="empty small">没有需要你拍板的事</div>`;
    return card("待你决定", body, {cls: "pending", meta: d.pending.length ? d.pending.length + " 项" : ""});
  }

  // 「现在」：先说等谁做什么，再是下一步，现状只露 3 行
  function renderNow(d) {
    const goals = activeGoals(d);
    let b = goals.length ? goals.map((g) => `<div class="nowbig"><span class="tid">${esc(g.id)}</span>${nowLine(d, g)}</div>`).join("") : "";
    b += `<h4>▶ 下一步</h4>${d.next ? `<div>${d.next}</div>` : `<div class="empty">未填写</div>`}`;
    if (d.status.length) {
      const li = (x) => `<li>${x}</li>`;
      b += `<h4>现状</h4><ul class="plain">${d.status.slice(0, 3).map(li).join("")}</ul>`;
      if (d.status.length > 3) b += `<details class="more"><summary>其余 ${d.status.length - 3} 条</summary><ul class="plain">${d.status.slice(3).map(li).join("")}</ul></details>`;
    }
    return card("现在", b, {cls: "now"});
  }

  // 顶部摘要：目标、任务各状态数、在跑的派活、token 合计
  function renderStrip(d) {
    const goals = d.goals.filter((g) => !/^(完成|取消)/.test(g.state));
    const counts = COLS.map((c) => [c.name, d.cards.filter((t) => c.match(t.state || "")).length]).filter(([, n]) => n);
    const running = d.runs.filter((r) => r.status === "运行中").length;
    const total = sumTok(d.runs);
    const items = [
      `<span class="si"><b>${goals.length}</b> 个目标在推进</span>`,
      `<span class="si">待你决定 <b>${d.pending.length}</b></span>`,
      `<span class="si">任务 ${counts.length ? counts.map(([k, n]) => `${k} <b>${n}</b>`).join(" · ") : "<b>0</b>"}</span>`,
      running ? `<span class="si live"><span class="dot"></span><b>${running}</b> 个派活在跑</span>` : `<span class="si">没有派活在跑</span>`,
      `<span class="si">派活 <b>${d.runs.length}</b> 次 · token <b>${tok(total).split(" ·")[0]}</b></span>`,
    ];
    return `<div class="strip">${items.join("")}</div>`;
  }

  function daysLeft(due) {
    const m = String(due || "").match(/(\d{4}-)?(\d{1,2})-(\d{1,2})/);
    if (!m) return "";
    const now = new Date();
    const y = m[1] ? +m[1].slice(0, 4) : now.getFullYear();
    const d = new Date(y, +m[2] - 1, +m[3]);
    const n = Math.ceil((d - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
    return n < 0 ? `已过 ${-n} 天` : n === 0 ? "今天截止" : `还剩 ${n} 天`;
  }


  function goalRuns(d, g) {
    const ids = new Set(g.stages.flatMap((s) => s.tasks));
    return d.runs.filter((r) => ids.has(r.task));
  }

  // ---------- 多目标：总览一行一个，按「待你决定 > 受阻 > 进行中 > 待批准 > 暂停」再按优先排；只展开一个目标的泳道 ----------
  const SORT = (g) => (g.alert.pend ? 0 : g.alert.block ? 1 : /^进行中/.test(g.state) ? 2 : /^待批准/.test(g.state) ? 3 : 4);
  function goalTasks(d, g) { return new Set(g.stages.flatMap((s) => s.tasks)); }
  function goalInfo(d, g) {
    const ids = goalTasks(d, g);
    const pend = d.pending.filter((h) => { const k = strip(h.split("｜")[0]).replace(/^（示例）\s*/, "").trim(); return k === g.id || ids.has(k); }).length;
    const block = g.stages.some((s) => s.status === "受阻");
    const dep = (g.head["依赖"] || "").match(/G\d+/g) || [];
    const waiting = dep.filter((x) => { const o = d.goals.find((q) => q.id === x); return o && !/^完成/.test(o.state); });
    const prio = parseInt(g.head["优先"], 10);
    return {...g, alert: {pend, block}, waiting, prio: isNaN(prio) ? 99 : prio, runs: goalRuns(d, g)};
  }
  // 想法：还在起草、有阶段（想法、讨论、方案）的目标，不进目标列表，单独一页按阶段分组
  const IDEA_STAGES = ["想法", "讨论", "方案"];
  const ideaGoals = (d) => d.goals.filter((g) => g.idea && !/^(完成|取消)/.test(g.state));
  function activeGoals(d) {
    return d.goals.filter((g) => !/^(完成|取消)/.test(g.state) && !g.idea).map((g) => goalInfo(d, g))
      .sort((a, b) => SORT(a) - SORT(b) || a.prio - b.prio || a.id.localeCompare(b.id));
  }
  function stageDots(g) {
    const cls = {"通过": "ok", "受阻": "bad", "返工": "warn", "待验收": "now", "进行中": "now"};
    const done = g.stages.filter((s) => s.status === "通过").length;
    return `<span class="dots">${g.stages.map((s) => `<i class="${cls[s.status] || ""}" title="阶段 ${s.no} ${esc(s.seat)}：${esc(s.status)}"></i>`).join("")}</span><span class="dn">${done}/${g.stages.length}</span>`;
  }

  // ---------- 选择器：每个目标一个，另有零散任务（有才显示）、议题、决议；主区一次只呈现选中的一个 ----------
  let pick = ARCHIVE ? null : decodeURIComponent((location.hash.match(/^#(.+)$/) || [])[1] || "") || null;
  let goalTab = "tasks";
  function allGoals(d) {
    const done = d.goals.filter((g) => /^(完成|取消)/.test(g.state)).map((g) => goalInfo(d, g))
      .sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}));
    return activeGoals(d).concat(done);
  }
  const hasLoose = (d) => (d.view ? !!d.view.零散 : d.cards.some((t) => !t.goal));
  function pickKeys(d) {
    return allGoals(d).map((g) => g.id).concat(ideaGoals(d).length ? ["ideas"] : [], hasLoose(d) ? ["loose"] : [], d.issues.length ? ["issues"] : [], ["dec"]);
  }
  function curPick(d) {
    const keys = pickKeys(d);
    return keys.includes(pick) ? pick : keys[0];
  }
  function renderPicker(d, cur) {
    const goals = allGoals(d);
    const btn = (key, inner, cls = "") => `<button class="pk ${cls} ${cur === key ? "on" : ""}" data-pick="${esc(key)}">${inner}</button>`;
    const gb = goals.map((g) => {
      const done = /^(完成|取消)/.test(g.state);
      const alerts = (g.alert.pend ? `<span class="pill run">待你决定 ${g.alert.pend}</span>` : "") + (g.alert.block ? '<span class="pill bad">受阻</span>' : "");
      return btn(g.id, `<span class="tid">${esc(g.id)}</span><span class="pt">${esc(g.title)}</span>${statusPill(g.state || "—")}${alerts}`, done ? "done" : "");
    }).join("");
    const waitIssue = d.issues.filter((i) => i.stage === "待裁决").length;
    const other = [
      ideaGoals(d).length ? btn("ideas", `想法 <span class="n">${ideaGoals(d).length}</span>`) : "",
      hasLoose(d) ? btn("loose", `零散任务 <span class="n">${d.cards.filter((t) => !t.goal).length}</span>`) : "",
      d.issues.length ? btn("issues", `议题（朝会） <span class="n">${d.issues.length}</span>${waitIssue ? `<span class="pill warn">待裁决 ${waitIssue}</span>` : ""}`) : "",
      btn("dec", `决议 <span class="n">${d.decisions.length}</span>`),
    ].join("");
    return `<nav class="picker"><div class="pkg"><span class="pkh">目标</span>${gb || '<span class="empty">还没有目标</span>'}</div><div class="pkg"><span class="pkh">其他</span>${other}</div></nav>`;
  }


  // ---------- 目标主页：要干什么、现在、主干；只用视图模型和卡片里已有的数据 ----------
  const mainTab = {}, openSteps = new Set();
  const fieldOf = (g, k) => { const f = (g.fields || []).find((x) => x.k === k); return f ? f.v : ""; };
  const plain = (h) => String(h || "").replace(/<[^>]+>/g, "").replace(/&quot;/g, '"').replace(/&amp;/g, "&");
  const firstSentence = (s, n = 64) => { const x = String(s || "").split(/[。；\n]/)[0]; return x.length > n ? x.slice(0, n) + "…" : x; };
  const criteria = (g) => plain(fieldOf(g, "成功标准")).split(/(?=[①②③④⑤⑥⑦⑧⑨⑩])/).map((x) => x.trim()).filter(Boolean);
  const goalTasksV = (d, gid) => d.view.任务.filter((t) => t.目标 === gid && t.状态 !== "取消").slice()
    .sort((a, b) => (a.阶段 - b.阶段) || a.编号.localeCompare(b.编号, undefined, {numeric: true}));
  const deliverNote = (d, id) => {
    const c = d.cards.find((x) => x.id === id);
    const r = c && (c.flow || []).filter((f) => f.说明.startsWith("交付")).pop();
    return r ? r.说明.replace(/^交付\s*·\s*/, "") : "";
  };
  const DOING = /执行中|待验收|已交接|受阻|暂停/;
  const whoName = (x) => x === "总裁" ? "你" : (x || "—");
  function nowCells(d, g) {
    const ts = goalTasksV(d, g.id);
    const doing = ts.filter((t) => DOING.test(t.状态));
    const next = ts.find((t) => /已批准|规划中/.test(t.状态));
    const mine = ts.filter((t) => t.持有人 === "总裁");
    const cell = (cls, lab, main, sub) => `<div class="ncell ${cls}"><div class="nlab">${lab}</div><b>${main}</b><span class="nsub">${sub}</span></div>`;
    const a = doing.length ? cell("doing", "正在做", esc(doing.map((t) => t.标题).join("、")), esc(doing.map((t) => `${whoName(t.持有人)} · ${t.状态}`).join("、")))
      : cell("", "正在做", "没有在跑的任务", "");
    const b = cell("", "接下来", next ? esc(next.标题) : "没有未开始的任务", next ? esc(whoName(next.拟执行 || next.执行)) : "");
    const decide = g.alert.pend || mine.length, qs = g.questions || [];
    const c = decide || qs.length
      ? cell("need", "需要你", esc([decide ? `${decide} 件事要你决定` : "", qs.length ? `回答 ${qs.length} 个问题` : ""].filter(Boolean).join("，")),
        esc(qs.length ? firstSentence(plain(qs[0]), 40) : "见上方「待你决定」"))
      : cell("", "需要你", "现在不用", "");
    return `<div class="ncells">${a}${b}${c}</div>`;
  }
  function trunk(d, g) {
    const ts = goalTasksV(d, g.id);
    const lastAppr = Math.max(0, ...g.vg.事件.filter((e) => e.边 === "批准").map((e) => e.项目序));
    const fbs = g.vg.事件.filter((e) => e.依据 && e.项目序 > lastAppr && (/打回|退回/.test(e.边) || e.边 === "变更"))
      .filter((e, i, a) => a.findIndex((x) => x.依据 === e.依据) === i);  // 同一句原话可能记了几条事件，只显示一次
    const fbFor = {}, tail = [];
    fbs.forEach((e) => {
      let best = null, gap = 6;
      ts.forEach((t) => { if (t.要求序 != null && Math.abs(t.要求序 - e.项目序) < gap) { best = t.编号; gap = Math.abs(t.要求序 - e.项目序); } });
      if (best) (fbFor[best] = fbFor[best] || []).push(e); else tail.push(e);
    });
    const fbRow = (e) => `<li class="tfb"><span class="tfl">${/打回|退回/.test(e.边) ? "你打回" : "你的要求"} ${esc(e.时间.slice(5, 16).replace("T", " "))}</span> “${esc(e.依据)}”<div class="nsub">${esc(e.说明)}</div></li>`;
    const rows = [];
    let stage = null;
    ts.forEach((t) => {
      const s = g.vg.阶段.find((x) => x.序 === t.阶段);
      (fbFor[t.编号] || []).forEach((e) => rows.push(fbRow(e)));
      if (t.阶段 !== stage) { stage = t.阶段; rows.push(`<li class="tstage">阶段 ${stage} · ${esc(s ? s.名称 : "")}</li>`); }
      const st = t.状态 === "通过" ? "done" : DOING.test(t.状态) ? "doing" : "todo";
      const c = t.内容 || {};
      const note = st === "done" ? firstSentence(deliverNote(d, t.编号) || t.结论) : firstSentence(c.目的);
      const k = (a, b) => b ? `<span class="k">${a}</span><span>${esc(b)}</span>` : "";
      rows.push(`<li class="tstep ${st}"><span class="tdot"></span><details data-step="${esc(t.编号)}" ${openSteps.has(t.编号) ? "open" : ""}><summary>
        <div class="ttl"><span>${esc(t.标题)}</span>${st === "doing" ? statusPill(t.状态) : t.返工次 ? `<span class="pill warn">返工 ${t.返工次}</span>` : ""}<span class="twho">${esc(whoName(t.执行 || t.拟执行))} · ${esc(whoName(t.确认 || t.拟确认))}确认</span></div>
        <div class="tres">${esc(note)}</div></summary>
        <div class="fields tmore">${k("任务", t.编号)}${k("目的", c.目的)}${k("交付物", c.交付物)}${k("验收标准", c.验收标准)}${k("结论", t.结论)}</div>
        <span class="tlink" data-task="${esc(t.编号)}">打开任务卡</span></details></li>`);
    });
    tail.forEach((e) => rows.push(fbRow(e)));
    return `<ol class="trunk">${rows.join("")}</ol>`;
  }
  function goalMain(d, g) {
    const vg = d.view.目标.find((x) => x.编号 === g.id);
    const gg = {...g, vg};
    const cr = criteria(g), want = plain(fieldOf(g, "要什么"));
    const tab = mainTab[g.id] || (/^待批准/.test(g.state) ? "flow" : "trunk");
    const tb = (k, n) => `<button class="gt ${tab === k ? "on" : ""}" data-maintab="${esc(g.id)}:${k}">${n}</button>`;
    const inner = tab === "trunk" ? trunk(d, gg)
      : tab === "flow" ? `<div class="gfh"><span class="tlink gdet" data-gdet="${esc(g.id)}">${openGoal === g.id ? "收起框架" : "看框架和偏离"}</span></div>${openGoal === g.id ? renderGoalDetail(g, goalRuns(d, g).filter((r) => r.override)) : ""}` + (ARCHIVE ? "" : renderApproval(d, g.id)) + renderSeq(d, g.id) + renderRel(d, g.id) + goalIssues(d, g.id)
      : renderLower(d, (gx) => gx === g.id);
    const side = `<aside class="gside"><div class="sh">成功标准 ${cr.length ? `· ${cr.length} 条` : ""}</div>${cr.length ? `<ul class="crit">${cr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : '<div class="empty">还没写</div>'}
      <div class="sh" style="margin-top:14px">文档</div>${goalFiles(d, g) || '<div class="nsub">还没有文档</div>'}</aside>`;
    return `<p class="gwant">${want ? esc(want) : '<span class="nsub">这张卡还没写要干什么</span>'}</p>${/^(完成|取消)/.test(g.state) ? "" : nowCells(d, g)}
      <div class="gcols"><div class="gleft"><div class="gtabs">${tb("trunk", "主干")}${tb("flow", "流程图")}${tb("low", "任务和派活")}</div>${inner}</div>${side}</div>`;
  }
  // 选中一个目标：卡头一行现状，时序图（旧项目是泳道），下面是它的任务和派活
  function renderGoalPane(d, gid) {
    const g = allGoals(d).find((x) => x.id === gid);
    const done = /^(完成|取消)/.test(g.state);
    let body = d.view ? goalMain(d, g) : `<div class="note">旧结构项目</div>`;
    const meta = `${stageDots(g)}${g.runs.length ? ` · 派活 ${g.runs.length} · ${tok(sumTok(g.runs)).split(" ·")[0]}` : ""}`;
    return card(`<span class="tid">${esc(g.id)}</span> ${esc(g.title)} ${statusPill(g.state || "—")}`, body, {meta, cls: "pane"});
  }
  // 框架的批准面板：看完图就能批准、提意见、退回；批准绑定看到的那一版
  const draftBox = (key, ph) => `<textarea class="adraft" data-draft="${esc(key)}" rows="2" placeholder="${esc(ph)}">${esc(drafts[key] || "")}</textarea>`;
  function commentList(list) {
    return (list || []).length ? `<ul class="plain acomm">${list.map((c) => `<li><span class="tid">${esc(c.对象 || "")}</span> ${esc(c.说明)} <span class="meta">${esc(hm(c.时间))}</span></li>`).join("")}</ul>` : "";
  }
  function renderApproval(d, gid) {
    const g = seqGroup(d, gid);
    if (!g || ARCHIVE) return "";
    const state = g.状态;
    const open = (g.意见 || []).length ? `<div class="alabel">你提的意见和批准批注（总管处理后消失）</div>${commentList(g.意见)}` : "";
    if (state === "起草") {
      const dv = g.框架版本 ? `总管在搭框架（第 ${g.框架版本} 版），提交后你来批准。` : "总管还没有搭框架。";
      return `<div class="appr draft"><div class="ah">${dv}</div>${open}</div>`;
    }
    if (state !== "待批准") return open ? `<div class="appr">${open}</div>` : "";
    const dec = (d.view.待你决定 || []).find((x) => x.编号 === gid) || {};
    const short = (x) => x.replace(/^G\d+-/, "");
    const stat = [`${dec.任务数 || 0} 张任务卡`, (dec.人选 || []).length ? `执行：${dec.人选.join("、")}` : "",
      (dec.介入 || []).length ? `<b class="me">要你确认：${dec.介入.map(short).join("、")}</b>` : "不需要你中途确认"].filter(Boolean).join(" · ");
    const changed = (g.本轮改动 || []).length && g.框架版本 > 1 ? `<div class="alabel">这一版改了什么</div><ul class="plain achg">${g.本轮改动.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    return `<div class="appr"><div class="ah"><span class="pill run">等你批准</span> <b>框架第 ${g.框架版本 || 0} 版</b> · ${stat}</div>
      ${dec.说明 ? `<div class="adesc">${esc(dec.说明)}</div>` : ""}${dec.建议 ? `<div class="adesc"><span class="meta">总管建议</span> ${esc(dec.建议)}</div>` : ""}
      ${changed}${open}${draftBox("goal:" + gid, "对整体的意见；针对某个任务的，点开下面的任务卡写")}
      <div class="aacts"><button class="act primary" type="button" data-goalact="批准" data-goalid="${esc(gid)}" data-version="${g.框架版本 || 0}">批准这一版</button>
      <button class="act" type="button" data-goalact="意见" data-goalid="${esc(gid)}" data-key="goal:${esc(gid)}">提意见</button>
      <button class="act" type="button" data-goalact="退回" data-goalid="${esc(gid)}" data-key="goal:${esc(gid)}">退回</button>
      ${apprMsg ? `<span class="aerr">${esc(apprMsg)}</span>` : ""}</div></div>`;
  }
  // 时序图下面的任务卡：内容来自卡片「交接」，可以针对这个任务提意见
  function renderTaskCard(d, g, tid) {
    const t = d.view.任务.find((x) => x.编号 === tid);
    if (!t) return "";
    const order = ["目的", "硬约束", "输入", "交付物", "验收标准", "授权", "上报条件", "身份", "可替换的做法"];
    const c = t.内容 || {};
    const rows = order.filter((k) => c[k]).map((k) => `<span class="k">${esc(k)}</span><span>${esc(c[k]).replace(/\n/g, "<br>")}</span>`).join("");
    const who = `${esc(t.拟执行 || t.执行 || "—")} 执行${t.执行 && t.拟执行 && t.执行 !== t.拟执行 ? `（实际 ${esc(t.执行)}）` : ""} · ${esc(t.确认 || t.拟确认 || "总管")} 确认`;
    const live = !ARCHIVE && !/^(完成|取消)/.test(g.状态 || "");
    const key = "task:" + tid;
    const said = (t.意见 || []).length ? `<div class="alabel">你提的意见</div>${commentList(t.意见.map((x) => ({...x, 对象: ""})))}` : "";
    return `<div class="ldet tcard"><div><b>${esc(tid)} ${esc(t.标题)}</b> ${statusPill(t.状态)} <span class="meta">${who}</span></div>
      ${rows ? `<div class="fields">${rows}</div>` : `<div class="note">这张卡还没写内容</div>`}${said}
      ${live ? `${draftBox(key, "对这个任务的意见")}<div class="aacts"><button class="act" type="button" data-goalact="意见" data-goalid="${esc(g.编号)}" data-tid="${esc(tid)}" data-key="${esc(key)}">提意见</button>${apprMsg ? `<span class="aerr">${esc(apprMsg)}</span>` : ""}</div>` : ""}</div>`;
  }
  // 目标面板里挂着的议题：一行一个，点进朝会页
  function goalIssues(d, gid) {
    const list = d.issues.filter((i) => i.flow && i.goal === gid);
    if (!list.length) return "";
    return `<div class="gissues"><span class="meta">议题</span>${list.map((i) => `<a class="girow" href="${U(`/p/${esc(id)}/meet/${esc(i.id)}`)}"><span class="tid">${esc(i.id)}</span> ${esc(i.title)} ${issuePill(i.thinking.length ? "讨论中" : i.stage)}<span class="meta">${esc(i.type)}${i.summary ? " · " + esc(i.summary.说明) : ""}</span></a>`).join("")}</div>`;
  }
  // 目标目录里的文档：点开用本机程序打开；归档后文件在 归档/目标/ 下，路径由视图模型给
  function goalFiles(d, g) {
    const f = g.files || {};
    const paths = ["方案", "问题", "讨论"].filter((k) => f[k]).map((k) => f[k]).concat(f["其他"] || []);
    const links = paths.map((p) => `<a href="${esc(fileHref(`${d.root}/${p}`))}">${esc(p.split("/").pop())}</a>`);
    return links.length ? `<span class="gfiles">${links.join(" · ")}</span>` : "";
  }
  function renderIdeasPane(d) {
    const list = ideaGoals(d);
    const groups = IDEA_STAGES.map((st) => {
      const rows = list.filter((g) => g.idea === st).sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}));
      const body = rows.length ? rows.map((g) => `<div class="girow"><span class="tid">${esc(g.id)}</span> <span class="igt"><b>${esc(g.title)}</b> ${g.state === "起草" ? "" : statusPill(g.state)}${(g.questions || []).length ? `<span class="pill warn">要你回答 ${g.questions.length} 个问题</span>` : ""}<span class="psub">${esc(plain(fieldOf(g, "要什么"))) || "还没写要干什么"}</span></span>
        ${goalFiles(d, g) || '<span class="meta">还没有文档</span>'}</div>`).join("") : '<div class="empty">无</div>';
      return `<div class="gissues"><span class="meta">${st} ${rows.length}</span>${body}</div>`;
    }).join("");
    return card("想法", groups, {meta: "起草中的目标，按阶段分组；点文档打开文件", cls: "pane"});
  }
  function renderLoosePane(d) {
    const body = (d.view && d.view.零散 ? renderRel(d, "—") + renderSeq(d, "—") : "") + renderLower(d, (gx) => gx === "none");
    return card("零散任务", body, {meta: "不属于目标的任务", cls: "pane"});
  }
  function renderDecPane(d) {
    const body = d.decisions.length ? `<ul class="plain">${d.decisions.map((x) => `<li>${x}</li>`).join("")}</ul>` : `<div class="empty">暂无</div>`;
    return card("生效决议", body, {cls: "pane"});
  }
  // 主区下半：任务和派活两个标签页，只列属于当前选中项的
  function renderLower(d, inScope) {
    const cards = d.cards.filter((t) => inScope(t.goal || "none"));
    const runs = d.runs.filter((r) => inScope(goalOfTask(d, r.task)))
      .sort((a, b) => String(b.started || "").localeCompare(String(a.started || "")));
    const tabs = [["tasks", `任务 ${cards.length}`], ["runs", `派活记录 ${runs.length}`]]
      .map(([k, t]) => `<button class="tab ${goalTab === k ? "on" : ""}" data-gtab="${k}">${t}</button>`).join("");
    const body = goalTab === "runs" ? (runs.length ? runsTable(runs, true) : `<div class="empty">没有派活记录</div>`) : taskList(d, cards);
    return `<div class="lower"><div class="card-head"><h2><span class="tabs">${tabs}</span></h2>${goalTab === "runs" && runs.length ? '<span class="meta">点一行看启动语和回复</span>' : ""}</div>${body}</div>`;
  }

  // ---------- 泳道流程：按席位分道（总裁 / 总管 / 执行 / 验收），执行按并行任务分子道，从上到下是时间 ----------
  let openNode = null;
  const LEAD = /^(claude|总管)/i, BOSS = /^(总裁|用户|本人)/;
  function laneOf(row, verifier) {
    const who = strip(row["经办人"] || "").trim();
    if (BOSS.test(who)) return "boss";
    if (LEAD.test(who)) return "lead";
    return /^(通过|需补充|未通过)/.test(strip(row["状态"] || "")) && verifier ? "check" : "exec";
  }
  function nodeCls(state, last) {
    if (/^(受阻|需补充|未通过)/.test(state)) return "bad";
    if (last && !/^通过/.test(state)) return "now";
    return "ok";
  }
  function goalLanes(d, g) {
    const nodes = [], edges = [], used = new Set();
    const put = (lane, sub, row) => { while (used.has(lane + sub + ":" + row)) row++; used.add(lane + sub + ":" + row); return row; };
    const add = (n) => { n.i = nodes.length; nodes.push(n); return n.i; };
    const approved = !g.state.startsWith("待批准");
    let row = 0;
    const draft = add({lane: "lead", sub: 0, row: put("lead", 0, row++), label: "起草框架", cls: "ok", info: `总管起草 ${g.id} 的目标和流程`});
    const appr = add({lane: "boss", sub: 0, row: put("boss", 0, row++), label: approved ? "批准框架" : "待批准", cls: approved ? "ok" : "now",
      info: approved ? `总裁批准 ${g.id}：${strip(g.head["依据"] || "")}` : "等总裁批准框架，批准前不派发"});
    edges.push([draft, appr]);
    let ends = [appr], maxSub = 1, hasCheck = false;
    const runsOf = (id) => d.runs.filter((r) => r.task === id);
    g.stages.forEach((s) => {
      const tasks = s.taskInfo;
      const start = row, newEnds = [];
      if (!tasks.length) {
        const lane = /验收/.test(s.seat) && !LEAD.test(s.who) && !/总管/.test(s.who) ? "check" : /汇报|总管/.test(s.seat + s.who) ? "lead" : "exec";
        if (lane === "check") hasCheck = true;
        const prevDone = g.stages.filter((x) => x.no < s.no).every((x) => x.status === "通过");
        const n = add({lane, sub: 0, row: put(lane, 0, start), label: `${circ(s.no)} ${s.seat}`, cls: s.status === "通过" ? "ok" : prevDone && approved ? "now" : "todo", stage: s,
          info: `阶段 ${circ(s.no)}「${s.seat}」· ${s.who || "—"}：${strip(s.output)}（还没有任务）`});
        ends.forEach((e) => edges.push([e, n]));
        ends = [n]; row = nodes[n].row + 1; return;
      }
      maxSub = Math.max(maxSub, tasks.length);
      tasks.forEach((t, k) => {
        const flow = t.flow || [];
        const verifier = !!strip(flow.map((r) => r["经办人"]).join(""));
        let r0 = start, prev = null;
        const rows = flow.length ? flow : [{"状态": t.state, "经办人": t.exec, "说明": ""}];
        rows.forEach((fr, idx) => {
          const st = strip(fr["状态"] || "");
          const lane = laneOf(fr, verifier);
          if (lane === "check") hasCheck = true;
          const sub = lane === "exec" ? k : 0;
          const rr = put(lane, sub, r0);
          const descKey = Object.keys(fr).find((x) => x.startsWith("说明")) || "说明";
          const n = add({lane, sub, row: rr, label: `${t.id.replace(/^G\d+-/, "")} ${st.replace(/：.*/, "")}`.slice(0, 14), cls: nodeCls(st, idx === rows.length - 1), last: idx === rows.length - 1,
            task: t.id, holder: strip(fr["接手人"] || ""), state: st, info: `${strip(fr["日期"] || "")} ${t.id} · ${strip(fr["经办人"] || "")} → ${strip(fr["接手人"] || "")} · ${st}：${strip(fr[descKey] || "")}`});
          if (prev === null) ends.forEach((e) => edges.push([e, n])); else edges.push([prev, n]);
          prev = n; r0 = rr + 1;
        });
        newEnds.push(prev);
        row = Math.max(row, r0);
      });
      ends = newEnds;
    });
    return {nodes, edges, maxSub, hasCheck, rows: Math.max(...nodes.map((n) => n.row)) + 1, runsOf};
  }
  function nowLine(d, g) {
    if (d.view) return nowLineView(d, g);
    const wait = ((g.head["依赖"] || "").match(/G\d+/g) || []).filter((x) => { const o = d.goals.find((q) => q.id === x); return o && !/^完成/.test(o.state); });
    if (g.state.startsWith("暂停")) return "已暂停";
    if (g.state.startsWith("待批准")) return `等<b>总裁</b>批准框架${wait.length ? `，且等 ${wait.map(esc).join("、")} 完成` : "（批准前不派发）"}`;
    if (wait.length) return `等 <b>${wait.map(esc).join("、")}</b> 完成后才能派发`;
    const cur = goalLanes(d, g).nodes.filter((n) => n.cls === "now" || (n.last && n.cls === "bad"));
    if (!cur.length) return "各阶段都已完成，等<b>总裁</b>批准目标完成";
    return cur.map((n) => {
      if (n.stage) return `等<b>${esc(n.stage.who || "总管")}</b>做阶段 ${circ(n.stage.no)}「${esc(n.stage.seat)}」（还没派任务）`;
      const who = esc(n.holder || "—"), id = esc(n.task);
      const act = /^受阻/.test(n.state) ? `处理 ${id} 的阻塞` : /^需补充/.test(n.state) ? `返工 ${id}`
        : /^待验收/.test(n.state) ? `验收 ${id}` : /^(已交接|执行中)/.test(n.state) ? `执行 ${id}` : `推进 ${id}`;
      const live = d.runs.filter((r) => r.task === n.task && r.status === "运行中").pop();
      return `等<b>${who}</b>${act}${live ? ` · <span class="dot"></span>${esc(live.member)} 已运行 ${dur(secs(live.started))}` : ""}`;
    }).join("；");
  }

  function renderLanes(d, g) {
    const L = goalLanes(d, g), RH = 34, TOP = 40, NH = 24, LEFT = 8;
    const cols = [{lane: "boss", name: "总裁", w: 120}, {lane: "lead", name: "总管", w: 130}];
    for (let k = 0; k < L.maxSub; k++) cols.push({lane: "exec", sub: k, name: k ? "" : "执行", w: 170});
    if (L.hasCheck) cols.push({lane: "check", name: "验收（第三方）", w: 150});
    // 泳道按页面宽度铺开（最多放大到 2 倍），节点宽度不跟着变
    const need = cols.reduce((a, c) => a + c.w, 0), avail = (app.clientWidth || 1000) - 56 - LEFT;
    const k = Math.min(2, Math.max(1, avail / need));
    cols.forEach((c) => { c.nw = c.w - 14; c.w = Math.floor(c.w * k); });
    let x = LEFT; cols.forEach((c) => { c.x = x; x += c.w; });
    const W = x + 8, H = TOP + RH * L.rows + 8;
    const col = (n) => cols.find((c) => c.lane === n.lane && (n.lane !== "exec" || c.sub === n.sub)) || cols[1];
    const cx = (n) => col(n).x + col(n).w / 2, cy = (n) => TOP + RH * n.row + RH / 2;
    let s = `<svg class="lanes" viewBox="0 0 ${W} ${H}" style="max-width:${W}px"><defs><marker id="la" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5"/></marker></defs>`;
    const groups = [];
    cols.forEach((c) => { if (c.name || c.lane !== "exec") groups.push({...c, w2: c.lane === "exec" ? c.w * L.maxSub : c.w}); });
    groups.forEach((c, i) => { s += `<rect x="${c.x + 3}" y="4" width="${c.w2 - 6}" height="${H - 8}" rx="8" class="ln"/><text x="${c.x + c.w2 / 2}" y="22" class="lnh">${esc(c.name)}</text><line x1="${c.x + 8}" y1="36" x2="${c.x + c.w2 - 8}" y2="36" class="lhl"/>${i > 0 ? `<line x1="${c.x}" y1="8" x2="${c.x}" y2="${H - 8}" class="lsep"/>` : ""}`; });
    for (let k = 1; k < L.maxSub; k++) { const c = cols.find((q) => q.lane === "exec" && q.sub === k); s += `<line x1="${c.x}" y1="34" x2="${c.x}" y2="${H - 8}" class="lsub"/>`; }
    L.edges.forEach(([a, b], k) => {
      const A = L.nodes[a], B = L.nodes[b], x1 = cx(A), y1 = cy(A) + NH / 2, x2 = cx(B), y2 = cy(B) - NH / 2 - 2, ym = y2 - 6 - (k % 2) * 3;
      s += `<path d="${x1 === x2 ? `M${x1} ${y1}L${x2} ${y2}` : `M${x1} ${y1}L${x1} ${ym}L${x2} ${ym}L${x2} ${y2}`}" class="le ${B.cls === "todo" ? "todo" : ""}" marker-end="url(#la)"/>`;
    });
    L.nodes.forEach((n) => {
      const w = col(n).nw;
      s += `<g class="lnode ${n.cls} ${openNode === g.id + ":" + n.i ? "sel" : ""}" data-lnode="${esc(g.id + ":" + n.i)}"><rect x="${cx(n) - w / 2}" y="${cy(n) - NH / 2}" width="${w}" height="${NH}" rx="6"/><text x="${cx(n)}" y="${cy(n)}">${esc(n.label)}</text></g>`;
    });
    s += "</svg>";
    let det = `<div class="note">点格子看这一步的说明、用时和 token</div>`;
    if (openNode && openNode.startsWith(g.id + ":")) {
      const n = L.nodes[+openNode.split(":")[1]];
      if (n) {
        det = `<div class="ldet">${esc(n.info)}`;
        const rs = n.task ? L.runsOf(n.task) : [];
        if (rs.length) det += `<div class="meta" style="margin-top:6px">${n.task} 的派活：${rs.map((r) => `${esc(r.run)} ${esc(r.member)} ${dur(r.ended ? (new Date(r.ended) - new Date(r.started)) / 1000 : secs(r.started))} · ${tok(r.tokens)}`).join("；")}</div>`;
        det += "</div>";
      }
    }
    return `<div class="lanewrap">${s}</div>${det}`;
  }

  // ---------- 时序图（新结构项目）：只画 flow.py 的视图模型，不读事件、不推断、不自行排序 ----------
  // 生命线顺序、主干和支线、持有期都由视图模型给定；从上到下按项目序每条事件一格，长间隔画成折断
  let openSeq = null;
  let hiTask = null;
  const openStages = new Set();
  const TASK_COLORS = ["var(--accent)", "var(--green)", "var(--amber)", "#8e5bd9", "#d9568e", "#3aa0c8"];
  const seqGroup = (d, gid) => (gid === "—" ? d.view.零散 : d.view.目标.find((x) => x.编号 === gid));
  function gapText(ms) {
    const h = ms / 3600e3;
    return h >= 48 ? `⋯ ${Math.round(h / 24)} 天` : `⋯ ${Math.round(h)} 小时`;
  }
  function renderSeq(d, gid) {
    const g = seqGroup(d, gid);
    if (!g) return "";
    const tasks = d.view.任务.filter((t) => (gid === "—" ? !t.目标 : t.目标 === gid));
    const color = {};
    tasks.forEach((t, i) => { color[t.编号] = TASK_COLORS[i % TASK_COLORS.length]; });
    const stages = g.阶段 || [];
    const folded = new Set(ARCHIVE ? [] : stages.filter((s) => s.状态 === "通过" && !openStages.has(gid + ":" + s.序)).map((s) => s.序));  // 归档页要看全过程，不折叠
    const rows = [], seenFold = new Set();
    let prevT = null;
    // 挂在这个目标上的议题：在它开始的位置插一行折叠框，点开去朝会页（发言不画进时序图）
    const issues = gid === "—" ? [] : (d.view.议题 || []).filter((i) => i.目标 === gid).slice().sort((a, b) => a.起序 - b.起序);
    const flushIssues = (upto) => { while (issues.length && issues[0].起序 < upto) rows.push({issue: issues.shift()}); };
    const S = g.结构;
    const short = (x) => x.replace(/^G\d+-/, "");
    if (S) {
      // 结构为主：按「阶段 → 任务 → 派发、交付、确认」排，每一步的位置不变；发生了就地变实线加时间
      const evBy = {};
      g.事件.forEach((e) => { evBy[e.项目序] = e; });
      if (S.记录.length) rows.push({rec: S.记录.length, open: openRecord.has(gid)});
      if (openRecord.has(gid)) S.记录.forEach((q) => { if (evBy[q]) rows.push({e: evBy[q]}); });
      flushIssues(Infinity);
      const stepRow = (x, t, no) => {
        const tid = t ? t.编号 : null;
        if (x.计划) rows.push({p: {...x, 层: t ? "任务" : "目标", 阶段: no, 对象: tid, 标题: t ? t.标题 : ""}, stage: no, task: tid});
        else if (evBy[x.项目序]) rows.push({e: evBy[x.项目序], also: x.含 || [], stage: no, task: tid});
      };
      S.开头.forEach((x) => stepRow(x, null, null));
      S.阶段.forEach((st) => {
        (st.前 || []).forEach((x) => stepRow(x, null, null));  // 目标层事件：插在紧随其后的阶段之前
        if (folded.has(st.序)) {
          st.任务.forEach((t) => (t.前 || []).forEach((x) => stepRow(x, null, null)));  // 折叠的阶段不吞掉这些事件
          rows.push({fold: stages.find((x) => x.序 === st.序), n: g.事件.filter((x) => x.层 === "任务" && x.阶段 === st.序 && !S.记录.includes(x.项目序)).length});
          return;
        }
        rows.push({shead: st, stage: st.序});
        if (st.待拆) rows.push({p: {边: "待拆", 阶段: st.序, 名称: st.名称, 人选: []}, stage: st.序});
        st.任务.forEach((t) => {
          (t.前 || []).forEach((x) => stepRow(x, null, null));
          rows.push({head: t, stage: st.序, task: t.编号});
          t.步骤.forEach((x) => stepRow(x, t, st.序));
        });
      });
      S.结尾.forEach((x) => stepRow(x, null, null));
    } else g.事件.forEach((e) => {
      flushIssues(e.项目序);
      const t = new Date(e.时间).getTime();
      if (prevT != null && t - prevT > 6 * 3600e3) {
        const last = rows[rows.length - 1];
        if (last && last.gap) last.gap += t - prevT; else rows.push({gap: t - prevT});  // 折叠掉的行之间的间隔合成一处
      }
      prevT = t;
      const st = e.层 === "任务" ? e.阶段 : null;
      if (st != null && folded.has(st)) {
        if (!seenFold.has(st)) {
          seenFold.add(st);
          rows.push({fold: stages.find((s) => s.序 === st), n: g.事件.filter((x) => x.层 === "任务" && x.阶段 === st).length});
        }
        return;
      }
      rows.push({e});
    });
    flushIssues(Infinity);
    const hiDeps = new Set();
    if (S && hiTask) S.阶段.forEach((st) => st.任务.forEach((t) => { if (t.编号 === hiTask) t.需要.forEach((x) => hiDeps.add(x)); }));
    const dimFor = (tid) => (hiTask && tid !== hiTask && !hiDeps.has(tid) ? "dim" : "");
    const P = g.参与者, TIMEW = S ? 84 : 62, TOP = 44, RH = 30, GH = 18, FH = 26;
    const avail = (app.clientWidth || 1000) - 56 - TIMEW;
    const CW = Math.max(110, Math.min(190, avail / Math.max(1, P.length)));
    const W = TIMEW + CW * P.length + 8;
    const col = {};
    P.forEach((p, i) => { col[p.名] = TIMEW + CW * i + CW / 2; });
    let y = TOP + 6;
    rows.forEach((r) => { const h = r.gap ? GH : (r.fold || r.issue || r.rec || r.lab || r.shead || r.head || (r.p && r.p.边 === "待拆")) ? FH : RH; r.y = y + h / 2; y += h; });
    const H = y + 10;
    const rowOf = {};
    rows.forEach((r) => { if (r.e) { rowOf[r.e.项目序] = r; (r.also || []).forEach((q) => { rowOf[q] = r; }); } });
    let s = `<svg class="seq" viewBox="0 0 ${W} ${H}" style="max-width:${W}px"><defs><marker id="sa" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5"/></marker></defs>`;
    // 阶段框：圈出该阶段任务事件所在的行
    stages.forEach((st) => {
      if (folded.has(st.序)) return;
      // 建卡往往一次建齐，框只圈派发之后的事件，否则并行和先后阶段的框会叠在一起
      const ys = rows.filter((r) => (S ? r.stage === st.序 : (r.e && r.e.层 === "任务" && r.e.阶段 === st.序 && r.e.边 !== "建立") || (r.p && r.p.阶段 === st.序))).map((r) => r.y);
      if (!ys.length) return;
      const y1 = Math.min(...ys) - (S ? FH / 2 : RH / 2 - 2), y2 = Math.max(...ys) + RH / 2 - 2;
      s += `<rect x="${TIMEW - 4}" y="${y1}" width="${W - TIMEW}" height="${y2 - y1}" rx="6" class="sbox"/>`;
      if (!S) s += `<text x="${W - 8}" y="${y1 + 11}" class="slab">阶段 ${circ(st.序)} ${esc(st.名称)} · ${esc(st.状态)}${st.失效 ? "（失效）" : ""}</text>`;
    });
    // 生命线和表头
    P.forEach((p) => {
      const x = col[p.名];
      s += `<line x1="${x}" y1="${TOP}" x2="${x}" y2="${H - 6}" class="life ${p.出场 ? "" : "off"}"/>`;
      s += `<rect x="${x - CW / 2 + 8}" y="6" width="${CW - 16}" height="26" rx="7" class="phead ${p.出场 ? "" : "off"} ${p.计划内 ? "" : "extra"}"/><text x="${x}" y="19" class="pname">${esc(p.名)}${p.出场 ? "" : "（未出场）"}</text>`;
    });
    // 持有期：生命线上的粗条
    tasks.forEach((t, k) => {
      (t.持有期 || []).forEach((h) => {
        const firstPlan = rows.find((r) => r.p);
        const lastMine = rows.filter((r) => r.task === t.编号 && r.e).pop();
        const a = rowOf[h.起序], b = h.止序 != null ? rowOf[h.止序] : {y: S ? (lastMine ? lastMine.y + RH / 2 : a ? a.y : 0) : firstPlan ? firstPlan.y - RH / 2 : H - 8};  // 还在手里的画到实际事件的末尾
        if (!a || !b || col[h.人] == null) return;
        const off = ((k % 3) - 1) * 7;
        s += `<rect x="${col[h.人] - 3 + off}" y="${a.y}" width="6" height="${Math.max(4, b.y - a.y)}" rx="3" class="hold ${hiTask && hiTask !== t.编号 ? "dim" : ""}" style="fill:${color[t.编号]}"/>`;
      });
    });
    // 行：箭头、折叠的阶段、折断
    rows.forEach((r) => {
      if (r.gap) { s += `<text x="${TIMEW + (W - TIMEW) / 2}" y="${r.y}" class="gap">${gapText(r.gap)}</text>`; return; }
      if (r.rec) {
        s += `<g class="fold" data-record="${esc(gid)}"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">筹备和记录 · ${r.rec} 条事件（${r.open ? "点开收起" : "点开查看"}）</text></g>`;
        return;
      }
      if (r.lab) { s += `<text x="${TIMEW + 6}" y="${r.y}" class="shd">${esc(r.lab)}</text>`; return; }
      if (r.shead) {
        const st = r.shead;
        const par = st.并行.length ? ` · 和 ${st.并行.map(circ).join("、")} 同时进行` : "";
        s += `<text x="${TIMEW + 6}" y="${r.y}" class="shd">阶段 ${circ(st.序)} ${esc(st.名称)}<tspan class="shm"> · ${esc(st.状态)}${st.失效 ? "（失效）" : ""}${par}</tspan></text>`;
        return;
      }
      if (r.head) {
        const t = r.head, on = openCard === t.编号;
        const doer = t.执行 || t.拟执行 || "—";
        const swap = t.换人 ? `（原计划 ${t.拟执行}）` : "";
        const real = tasks.find((x) => x.编号 === t.编号) || {};
        const need = t.需要.length ? ` · 需要 ${t.需要.map(short).join("、")} 的产出` : "";
        const tag = (t.总裁介入 ? `<tspan class="thme"> · 要你确认</tspan>` : "") + (t.批准后新增 ? `<tspan class="thme"> · 批准后新增</tspan>` : "");
        s += `<g class="thead ${on ? "on" : ""} ${dimFor(t.编号)}" data-taskcard="${esc(t.编号)}"><rect x="${TIMEW + 2}" y="${r.y - FH / 2 + 2}" width="${W - TIMEW - 12}" height="${FH - 4}" rx="5"/><text x="${TIMEW + 10}" y="${r.y}" class="tht">${esc(short(t.编号))} ${esc(t.标题)}<tspan class="thm"> · ${esc(doer)}${esc(swap)} 做，${esc(real.确认 || t.拟确认 || "总管")} 确认 · ${esc(t.状态)}${esc(need)}</tspan>${tag}</text><title>点开看任务卡</title></g>`;
        return;
      }
      if (r.issue) {
        const i = r.issue, who = i.与会.map((a) => a.成员).join("、");
        s += `<a href="${U(`/p/${esc(id)}/meet/${esc(i.编号)}`)}" class="iss"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">${i.类型 === "会审" ? "框架会审" : "朝会"} ${esc(i.编号)} ${esc(i.标题)} · ${esc(who)} · ${i.发言数} 条 · ${esc(i.状态)}（点开看对话）</text></a>`;
        return;
      }
      if (r.fold) {
        s += `<g class="fold" data-fold="${esc(gid + ":" + r.fold.序)}"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">阶段 ${circ(r.fold.序)} ${esc(r.fold.名称)} 已通过 · ${r.n} 条事件（点开展开）</text></g>`;
        return;
      }
      if (r.p) {
        const p = r.p;
        if (p.边 === "待拆") {
          s += `<g class="planbox"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">阶段 ${circ(p.阶段)} ${esc(p.名称)} · 还没拆任务${p.人选.length ? " · 人选 " + esc(p.人选.join("、")) : ""}</text></g>`;
          return;
        }
        const px1 = col[p.发起], px2 = p.接收 && p.接收 !== "无" && col[p.接收] != null ? col[p.接收] : px1;
        if (px1 == null) return;
        const pid = p.对象 || "";
        const pdim = hiTask ? dimFor(pid) : "";
        const plabel = p.边;
        s += `<g class="ev plan ${pdim} ${pid ? "clickable" : ""}" ${pid ? `data-taskcard="${esc(pid)}"` : ""}><text x="${TIMEW - 8}" y="${r.y}" class="tm">计划</text><title>计划：${esc(p.发起)} → ${esc(p.接收 === "无" ? p.发起 : p.接收)} · ${esc(p.标题 || g.标题)}</title>`;
        if (px1 === px2) {
          s += `<path d="M${px1} ${r.y - 6}h18v12h-14" class="arw" marker-end="url(#sa)"/><text x="${px1 + 24}" y="${r.y}" class="elab l">${esc(plabel)}</text>`;
        } else {
          const dir = px2 > px1 ? 1 : -1;
          s += `<line x1="${px1}" y1="${r.y + 4}" x2="${px2 - dir * 4}" y2="${r.y + 4}" class="arw" marker-end="url(#sa)"/><text x="${(px1 + px2) / 2}" y="${r.y - 5}" class="elab">${esc(plabel)}</text>`;
        }
        s += "</g>";
        return;
      }
      const e = r.e, dr = e.画 || {}, from = dr.发起 || e.发起, to = dr.接收 || e.接收;  // 总裁的话由总管代记的事件，按总裁 → 总管画
      const x1 = col[from], x2 = to && to !== "无" && col[to] != null ? col[to] : x1;
      if (x1 == null) return;
      const task = e.层 === "任务", cls = !task ? "gl" : e.主干 ? "tr" : "br";
      const dim = hiTask ? dimFor(e.对象) : "";
      const sel = openSeq === e.项目序 ? "sel" : "";
      const stroke = task ? color[e.对象] : "var(--ink-2)";
      const label = `${task && !S ? e.对象.replace(/^G\d+-/, "") + " " : ""}${task && S && !r.stage ? e.对象.replace(/^G\d+-/, "") + " " : ""}${dr.标签 || e.边}${e.结果 ? "：" + e.结果 : ""}`;
      s += `<g class="ev ${cls} ${dim} ${sel}" data-seq="${e.项目序}" style="--c:${stroke}">`;
      s += `<text x="${TIMEW - 8}" y="${r.y}" class="tm">${esc(S ? hm(e.时间) : hm(e.时间).slice(6))}</text>`;
      if (x1 === x2) {
        s += `<path d="M${x1} ${r.y - 6}h18v12h-14" class="arw" marker-end="url(#sa)"/>`;
        s += `<text x="${x1 + 24}" y="${r.y}" class="elab l">${esc(label)}</text>`;
      } else {
        const inset = cls === "br" ? 8 : 0, dir = x2 > x1 ? 1 : -1;
        s += `<line x1="${x1 + dir * inset}" y1="${r.y + 4}" x2="${x2 - dir * (4 + inset)}" y2="${r.y + 4}" class="arw" marker-end="url(#sa)"/>`;
        s += `<text x="${(x1 + x2) / 2}" y="${r.y - 5}" class="elab">${esc(label)}</text>`;
      }
      s += `<rect x="${Math.min(x1, x2) - 6}" y="${r.y - RH / 2}" width="${Math.abs(x2 - x1) + 30}" height="${RH}" class="hit"/>`;
      // 因果标注：退回 ↔ 因此新增的任务，点标注跳到对方
      const xr = (e.催生 || []).length ? {t: "因此新增 " + e.催生.map((c) => short(c.对象)).join("、"), q: e.催生[0].项目序}
        : e.来自 ? {t: "来自 " + short(e.来自.对象) + " 的" + (e.来自.边 === "确认" ? "退回" : e.来自.边), q: e.来自.项目序} : null;
      if (xr) s += `<text x="${Math.max(x1, x2) + (x1 === x2 ? 30 + label.length * 11 : 12)}" y="${r.y + 4}" class="xref" data-goseq="${xr.q}">${esc(xr.t)}</text>`;
      s += "</g>";
    });
    s += "</svg>";
    // 一键展开 / 折叠所有已通过的阶段
    const passed = ARCHIVE ? [] : stages.filter((x) => x.状态 === "通过");
    const foldAll = passed.length ? `<span class="tlink foldall" data-foldall="${esc(gid)}" data-open="${folded.size ? 1 : 0}">${folded.size ? "全部展开" : "全部折叠"}</span>` : "";
    const planNote = S ? `<span class="meta">灰色是计划，发生后就地变成带时间的实线；虚线是返工、转交、上报等支线。点任务行看任务卡，点实线看这一步。</span>` : "";
    const legend = S ? `<div class="seqlegend">${planNote}${foldAll}</div>` : `<div class="seqlegend">${tasks.map((t) => `<span class="lg ${hiTask === t.编号 ? "on" : ""}" data-hitask="${esc(t.编号)}"><i style="background:${color[t.编号]}"></i>${esc(t.编号)} ${esc(t.标题)} · ${esc(t.状态)}${t.返工次 ? ` · 返工 ${t.返工次}` : ""}</span>`).join("")}<span class="meta">实线是主干，虚线是返工、转交、上报等支线；点任务只看它</span>${foldAll}</div>`;
    const diffs = g.差别 || [];
    const diffBox = diffs.length ? `<div class="appr diff"><div class="alabel">和批准版（第 ${g.批准版本} 版）的差别</div><ul class="plain achg">${diffs.map((x) => `<li><b>${esc(x.类型)}</b> <span class="tid">${esc(short(x.任务))}</span> ${esc(x.说明)}</li>`).join("")}</ul></div>` : "";
    let det = "";
    const ev = g.事件.find((x) => x.项目序 === openSeq);
    if (ev) {
      const run = ev.派活 ? d.runs.find((r) => r.run === ev.派活) : null;
      det = `<div class="ldet"><b>${esc(ev.对象)} ${esc(ev.边)}${ev.结果 ? "：" + esc(ev.结果) : ""}</b> · ${esc((ev.画 || {}).发起 || ev.发起)} → ${esc((ev.画 || {}).接收 || ev.接收)} · ${esc(ev.前状态)} → ${esc(ev.后状态)} · ${esc(hm(ev.时间))} · 项目序 ${ev.项目序}`
        + (ev.依据 ? `<div class="${ev.原话 ? "quote" : "meta"}"><span class="meta">${ev.原话 ? "原话" : "依据（框架自动写）"}</span> ${esc(ev.依据)}</div>` : "")
        + (ev.说明 ? `<div>${ev.依据 && ev.原话 ? `<span class="meta">${ev.发起 === "总管" || ev.写入者 === "总管" ? "总管转述" : "说明"}</span> ` : ""}${esc(ev.说明)}</div>` : "")
        + (ev.同改框架版 ? `<div class="meta">同时改了框架第 ${esc(ev.同改框架版)} 版</div>` : "")
        + ((ev.催生 || []).length ? `<div class="meta">${ev.催生.map((c) => `<span class="xref" data-goseq="${c.项目序}">因此新增 ${esc(c.对象)}</span>`).join("、")}</div>` : "")
        + (ev.来自 ? `<div class="meta"><span class="xref" data-goseq="${ev.来自.项目序}">来自 ${esc(ev.来自.对象)} 的${ev.来自.边 === "确认" ? "退回" : esc(ev.来自.边)}</span></div>` : "")
        + (ev.证据 && ev.证据.length ? `<div class="meta">证据：${ev.证据.map((x) => fileLink(x, d.root)).join("、")}</div>` : "")
        + (ev.越过 ? `<div class="meta">偏离：${esc(ev.越过)}</div>` : "")
        + (ev.会话 ? `<div class="meta">会话：${esc(ev.会话)}</div>` : "")
        + (run ? `<div class="meta">派活 ${esc(run.run)} ${esc(run.member)} · ${dur(run.ended ? (new Date(run.ended) - new Date(run.started)) / 1000 : secs(run.started))} · ${tok(run.tokens)}</div>` : "")
        + "</div>";
    }
    const cardBox = S && openCard && tasks.some((t) => t.编号 === openCard) ? renderTaskCard(d, g, openCard) : "";
    return `${legend}${diffBox}<div class="lanewrap">${s}</div>${cardBox}${det}`;
  }
  // 证据路径 → 点开就用本机程序打开的链接；相对路径按项目根算
  function fileLink(p, root) {
    const abs = /^(\/|~)/.test(p) ? p : `${root}/${p.replace(/^\.\//, "")}`;
    return `<a href="${esc(fileHref(abs))}">${esc(p)}</a>`;
  }
  // ---------- 关系图（新结构项目）：时序图的当前切面，只画视图模型 ----------
  // 每个未结束的对象一条边：交过来的人 → 现在的持有人，取自视图模型的「交接」切面；人的位置固定，只变边和颜色。
  // 游标：在时序图上选中一步时，关系图回放到那一刻（取 项目序 ≤ 游标 的最后一个切面）；否则是现在。
  const relCls = (s) => (/^(受阻|未通过)/.test(s) ? "bad" : s === "待验收" ? "rv" : /^(执行中|已交接|进行中)/.test(s) ? "go" : "idle");
  const nowMs = (d) => (d.clock ? new Date(d.clock).getTime() : Date.now());
  function ago(ms) {
    const m = Math.max(0, Math.round(ms / 60e3));
    if (m < 1) return "刚刚";
    if (m < 60) return m + " 分钟";
    if (m < 48 * 60) return Math.round(m / 60) + " 小时";
    return Math.round(m / 1440) + " 天";
  }
  function relCursor(g) {
    return openSeq != null && g.事件.some((e) => e.项目序 === openSeq) ? openSeq : null;
  }
  function renderRel(d, gid) {
    const g = seqGroup(d, gid);
    if (!g || !g.事件.length) return "";
    const cur = relCursor(g);
    const upto = (list) => (cur == null ? list : list.filter((x) => x.项目序 <= cur));
    const lastOf = (list) => { const l = upto(list || []); return l[l.length - 1]; };
    const tNow = cur == null ? nowMs(d) : new Date(g.事件.find((e) => e.项目序 === cur).时间).getTime();
    const stages = g.阶段 || [];
    const tasks = d.view.任务.filter((t) => (gid === "—" ? !t.目标 : t.目标 === gid));
    const tIndex = {};
    tasks.forEach((t, i) => { tIndex[t.编号] = i; });
    // 端口：派出去过、还没结束的任务；现在视图里再加上所在阶段已轮到、还没派的任务（灰）；目标本身在总裁手里时也占一个
    const ports = [];
    if (gid !== "—") {
      const gs = lastOf(g.交接);
      if (gs && gs.持有人 === "总裁" && gs.类别 !== "完成") ports.push({id: gid, label: `${gid} ${gs.状态}`, snap: gs, goal: true});
    }
    tasks.forEach((t) => {
      const snap = lastOf(t.交接);
      if (!snap || snap.类别 === "完成") return;
      const sent = upto(t.交接).some((x) => x.边 === "派发");
      const st = stages.find((x) => x.序 === t.阶段);
      if (!sent && gid !== "—") return;  // 还没派的任务在下面按计划画
      if (!sent && !(cur == null && st && /^(可开始|进行中)$/.test(st.状态))) return;
      // 拿到手的时刻：持有人最后一次换成现在这个人
      const hs = upto(t.交接);
      let since = snap;
      for (let k = hs.length - 1; k >= 0 && hs[k].持有人 === snap.持有人; k--) since = hs[k];
      ports.push({id: t.编号, label: `${t.编号.replace(/^G\d+-/, "")} ${sent ? snap.状态 : "待派发"}`, snap, t, since, sent});
    });
    // 计划：还没走到的任务和没拆的阶段是灰色端口，连到计划的成员；回放时只看当时的实际情况
    if (gid !== "—" && cur == null && !/^(完成|取消)/.test(g.状态 || "")) {
      stages.forEach((st) => {
        tasks.filter((t) => t.阶段 === st.序 && t.类别 !== "完成" && !ports.some((q) => q.id === t.编号)).forEach((t) => {
          const doer = t.执行 || t.拟执行 || (st.人选 || [])[0] || "总管";
          ports.push({id: t.编号, plan: true, label: `${t.编号.replace(/^G\d+-/, "")} ${t.标题}`, title: `${t.标题}：${doer} 做，${t.拟确认 || "总管"} 确认（${t.状态}）`,
            snap: {持有人: doer, 发起: "总管", 状态: "计划"}});
        });
        if (st.待拆) ports.push({id: "阶段:" + st.序, plan: true, label: `${st.序} ${st.名称} · 待拆`, title: `阶段 ${st.序}「${st.名称}」还没拆任务`,
          snap: {持有人: st.人选[0] || "总管", 发起: "总管", 状态: "计划"}});
      });
    }
    const members = g.参与者.filter((p) => p.名 !== "总裁" && p.名 !== "总管");
    if (!ports.length) {
      const done = /^(完成|取消)/.test(g.状态 || "");
      return `<div class="relwrap relempty"><span class="meta">关系图（${cur == null ? "现在" : "回放"}）</span>${done && cur == null ? "这件事已经结案，没有在办的差事。" : "这一刻没有在办的差事。"}点下面时序图的任一步，可以回放当时谁手里拿着什么。${cur != null ? ` <span class="tlink" data-relnow="1">回到现在</span>` : ""}</div>`;
    }
    // 布局：总裁在左、总管居中（每个端口一行）、成员在右（按参与者顺序固定位置）
    const avail = Math.max(640, Math.min(1100, (app.clientWidth || 1000) - 56));
    const TOP = 34, PH = 34, MH = 50, MG = 10, BW = 130, LW = 200, MW = 210, ARC = 36;
    const BX = 8, MX = avail - MW - ARC, LX = Math.round(BX + BW + (MX - BX - BW - LW) / 2);
    const portY = (i) => TOP + 40 + PH * i + PH / 2;
    const memY = (i) => TOP + (MH + MG) * i + MH / 2;
    const leadH = 40 + PH * ports.length + 8;
    const bodyH = Math.max(leadH, (MH + MG) * members.length - MG, 60);
    const W = avail, H = TOP + bodyH + 12;
    const boss = {x: BX, y: TOP, h: 52};
    const memAt = {};
    members.forEach((p, i) => { memAt[p.名] = i; });
    const held = {};
    const planned = {};
    ports.forEach((p) => {
      const h = p.snap.持有人, box = p.plan ? planned : held;
      if (h && memAt[h] != null) (box[h] = box[h] || []).push(p);
    });
    const bossN = ports.filter((p) => p.snap.持有人 === "总裁").length;
    const curStages = [...new Set(ports.filter((p) => p.t).map((p) => p.t.阶段))].map((n) => stages.find((x) => x.序 === n)).filter(Boolean);
    const dimP = (p) => (hiTask && hiTask !== p.id ? "dim" : "");
    let s = `<svg class="rel" viewBox="0 0 ${W} ${H}" style="max-width:${W}px"><defs><marker id="ra" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5"/></marker></defs>`;
    s += `<text x="${BX + BW / 2}" y="16" class="rh">总裁</text><text x="${LX + LW / 2}" y="16" class="rh">总管${curStages.length ? " · " + curStages.map((x) => `阶段 ${circ(x.序)} ${esc(x.名称)}`).join("、") : ""}</text><text x="${MX + MW / 2}" y="16" class="rh">成员</text>`;
    // 边（先画，压在卡片下面）
    const curve = (x1, y1, x2, y2) => { const mx = (x1 + x2) / 2; return `M${x1} ${y1}C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`; };
    ports.forEach((p, i) => {
      const py = portY(i), h = p.snap.持有人, from = p.snap.发起, cls = relCls(p.snap.状态), dim = dimP(p);
      const edge = (d0, back) => { s += `<path d="${d0}" class="re ${cls} ${p.plan ? "plan" : ""} ${back ? "back" : ""} ${dim}" data-rtask="${esc(p.id)}" marker-end="url(#ra)"/>`; };
      if (h === "总裁") edge(curve(LX - 2, py, BX + BW + 4, boss.y + boss.h / 2), false);
      else if (h === "总管" && from === "总裁") edge(curve(BX + BW + 2, boss.y + boss.h / 2, LX - 4, py), true);
      else if (h === "总管" && memAt[from] != null) edge(curve(MX - 2, memY(memAt[from]), LX + LW + 4, py), true);
      else if (memAt[h] != null && memAt[from] != null && from !== h) {
        // 成员之间的交接：卡片右侧的弧线；端口和持有人之间只画一条细的归属线
        const y1 = memY(memAt[from]), y2 = memY(memAt[h]), xr = MX + MW;
        s += `<path d="M${LX + LW} ${py}L${MX} ${y2}" class="re own ${dim}"/>`;
        edge(`M${xr + 2} ${y1}C${xr + ARC} ${y1} ${xr + ARC} ${y2} ${xr + 4} ${y2}`, false);
      } else if (memAt[h] != null) edge(curve(LX + LW + 2, py, MX - 4, memY(memAt[h])), false);
    });
    // 总裁
    s += `<g class="rcard ${bossN ? "bad" : "idle"}"><rect x="${BX}" y="${boss.y}" width="${BW}" height="${boss.h}" rx="8"/><text x="${BX + BW / 2}" y="${boss.y + 19}" class="rn">总裁</text><text x="${BX + BW / 2}" y="${boss.y + 37}" class="rs">${bossN ? `待你决定 ${bossN}` : "无待决"}</text></g>`;
    // 总管和端口
    s += `<rect x="${LX}" y="${TOP}" width="${LW}" height="${leadH}" rx="8" class="rlead"/><text x="${LX + LW / 2}" y="${TOP + 20}" class="rn">总管</text>`;
    ports.forEach((p, i) => {
      const py = portY(i), cls = p.sent === false ? "idle" : relCls(p.snap.状态);
      const short = p.label.length > 15 ? p.label.slice(0, 14) + "…" : p.label;
      s += `<g class="rport ${cls} ${p.plan ? "plan" : ""} ${dimP(p)} ${hiTask === p.id ? "on" : ""}" data-rtask="${esc(p.id)}"><rect x="${LX + 12}" y="${py - 13}" width="${LW - 24}" height="26" rx="5"/><text x="${LX + LW / 2}" y="${py}" class="rs">${esc(short)}</text><title>${esc(p.title || (p.t ? p.t.标题 : g.标题))}</title></g>`;
    });
    // 成员卡片
    members.forEach((p, i) => {
      const y = memY(i) - MH / 2, mine = held[p.名] || [];
      const worst = mine.some((q) => relCls(q.snap.状态) === "bad") ? "bad" : mine.some((q) => relCls(q.snap.状态) === "rv") ? "rv" : mine.length ? "go" : "idle";
      const line = mine.length ? mine.map((q) => {
        const live = cur == null ? d.runs.filter((r) => r.task === q.id && r.status === "运行中").pop() : null;
        const t = live ? `已运行 ${dur(secs(live.started))}` : `已持有 ${ago(tNow - new Date(q.since.时间).getTime())}`;
        return `${q.id.replace(/^G\d+-/, "")} · ${t}`;
      }).join("；") : planned[p.名] ? `计划 ${planned[p.名].length} 项` : p.出场 ? "空闲" : "未出场";
      const dim = hiTask && !ports.some((q) => q.id === hiTask && (q.snap.持有人 === p.名 || q.snap.发起 === p.名)) ? "dim" : "";
      s += `<g class="rcard ${worst} ${dim} ${p.计划内 ? "" : "extra"}" ${mine.length ? `data-rtask="${esc(mine[0].id)}"` : ""}><rect x="${MX}" y="${y}" width="${MW}" height="${MH}" rx="8"/><text x="${MX + MW / 2}" y="${y + 18}" class="rn">${esc(p.名)}</text><text x="${MX + MW / 2}" y="${y + 35}" class="rs">${esc(line)}</text></g>`;
    });
    s += "</svg>";
    // 最近事件栏：时序图到游标为止的最后一行
    // 进展、变更、更正不是交接，不进事件栏
    const le = lastOf(g.事件.filter((e) => !["进展", "变更", "更正"].includes(e.边)));
    const to = le && le.接收 && le.接收 !== "无" && le.接收 !== le.发起 ? ` → ${esc(le.接收)}` : "";
    const bar = le ? `<b>最近交接</b>：${esc(le.发起)}${to} · ${esc(le.边)}${le.结果 ? "：" + esc(le.结果) : ""} · ${esc(le.对象)}${le.说明 ? " · " + esc(le.说明.length > 48 ? le.说明.slice(0, 48) + "…" : le.说明) : ""} · ${cur == null ? ago(tNow - new Date(le.时间).getTime()) + "前" : esc(hm(le.时间))}` : "";
    const mode = cur == null ? `<span class="meta">关系图 · 现在</span>` : `<span class="pill warn">回放到 ${esc(hm(g.事件.find((e) => e.项目序 === cur).时间))} · 项目序 ${cur}</span> <span class="tlink" data-relnow="1">回到现在</span>`;
    return `<div class="relwrap"><div class="relhead">${mode}<span class="meta">实线 = 派出去，虚线 = 交回来；绿 = 在办，黄 = 待确认，红 = 受阻或未通过，灰 = 计划、待派或暂停 · 点任务看它的时序，点时序图上的箭头回放到那一刻</span></div>${s}<div class="relbar">${bar}</div></div>`;
  }
  function nowLineView(d, g) {
    if (g.state === "起草") return "等<b>总管</b>搭好框架并提交";
    if (g.state === "待批准") return "等<b>总裁</b>看图批准（批准前不开工）";
    if (g.state === "待确认") return "等<b>总裁</b>确认目标完成";
    if (g.state === "暂停") return "已暂停";
    const ids = new Set(g.stages.flatMap((s) => s.tasks));
    const ACT = {"已批准": "派发", "已交接": "接手", "执行中": "执行", "待验收": "确认", "受阻": "处理阻塞", "未通过": "决定改派或取消", "暂停": "恢复"};
    const gv0 = seqGroup(d, g.id);
    const waiting = new Set((gv0 ? gv0.阶段 : []).filter((s) => s.状态 === "未开始").flatMap((s) => s.任务));
    // 已建好、但所在阶段还没轮到的差事不算「现在」
    const parts = d.view.当前.filter((c) => ids.has(c.对象) && !(c.状态 === "已批准" && waiting.has(c.对象))).map((c) => {
      const live = d.runs.filter((r) => r.task === c.对象 && r.status === "运行中").pop();
      return `等<b>${esc(c.接收 || "—")}</b>${ACT[c.状态] || "推进"} ${esc(c.对象)}${live ? ` · <span class="dot"></span>${esc(live.member)} 已运行 ${dur(secs(live.started))}` : ""}`;
    });
    const gv = seqGroup(d, g.id);
    (gv ? gv.阶段 : []).filter((s) => s.状态 === "可开始" && !s.任务.length)
      .forEach((s) => parts.push(`等<b>总管</b>为阶段 ${circ(s.序)}「${esc(s.名称)}」建任务`));
    return parts.join("；") || "各阶段都已通过，等<b>总管</b>做目标验收";
  }
  function renderGoalDetail(g, devs) {
    let b = `<div class="detail gdetail">`;
    const gtasks = new Set(g.stages.flatMap((s) => s.tasks));
    const gruns = (data.runs || []).filter((r) => gtasks.has(r.task));
    if (gruns.length) b += `<div class="meta">派活 ${gruns.length} 次 · 合计 ${tok(sumTok(gruns))}</div>`;
    const head = Object.entries(g.head).filter(([k]) => !["状态", "截止"].includes(k)).map(([k, v]) => ({k, v: esc(v)}));
    const fields = head.concat(g.fields);
    if (fields.length) b += `<div class="fields">${fields.map((f) => `<span class="k">${esc(f.k)}</span><span>${f.v}</span>`).join("")}</div>`;
    b += `<h4>流程</h4><div class="scroll"><table><thead><tr><th>阶段</th><th>席位</th><th>人选</th><th>产出</th><th>通过条件</th><th>子任务</th><th>状态</th></tr></thead><tbody>${g.stages.map((s) => `<tr>
      <td>${circ(s.no)}</td><td>${esc(s.seat)}</td><td>${esc(s.who)}</td><td>${s.output}</td><td>${s.cond}</td>
      <td>${s.taskInfo.map((t) => t.archived && !ARCHIVE ? `<a class="tlink" href="${U(`/p/${esc(id)}/archive#${esc(t.id)}`)}">${esc(t.id)} ${statusPill(t.state || "—")}</a>`
        : `<span class="tlink" data-task="${esc(t.id)}">${esc(t.id)} ${statusPill(t.state || "—")}</span>`).join(" ") || "—"}${s.missing.length ? ` <span class="pill bad">找不到 ${esc(s.missing.join("、"))}</span>` : ""}</td>
      <td>${statusPill(s.status)}</td></tr>`).join("")}</tbody></table></div>`;
    if (devs.length) b += `<h4>偏离记录</h4><ul class="plain">${devs.map((r) => `<li><b>${esc(r.run)}</b> ${esc(r.member)} 坐「${esc(r.seat)}」：${esc(r.override)}<div class="note">${(r.deviations || []).map(esc).join("；")}</div></li>`).join("")}</ul>`;
    return b + "</div>";
  }

  const ISSUE_CLS = {"待裁决": "warn", "已裁决": "ok", "开放": "", "讨论中": "run", "收口中": "warn", "起草": "", "取消": ""};

  function renderIssues(d) {
    const list = d.issues.slice().sort((a, b) => (a.stage === "已裁决") - (b.stage === "已裁决"));
    if (!list.length) return "";
    const body = list.map((i) => {
      if (i.flow) return flowIssueCard(i);
      const live = d.runs.filter((r) => r.task === i.id && r.status === "运行中");
      const chips = Array.from({length: i.maxRounds}, (_, k) => {
        const n = k + 1;
        const done = n <= i.roundsDone;
        const running = !done && n === i.roundsDone + 1 && live.length;
        return `<span class="stage ${done ? "ok" : running ? "run cur" : ""}">第${n}轮 ${done ? "✓" : running ? "●" : ""}</span>`;
      }).join('<span class="arrow">→</span>') + `<span class="arrow">→</span><span class="stage ${i.summary.length ? "ok" : ""}">总结 ${i.summary.length ? "✓" : ""}</span><span class="arrow">→</span><span class="stage ${i.ruling.length ? "ok" : i.stage === "待裁决" ? "warn cur" : ""}">裁决 ${i.ruling.length ? "✓" : ""}</span>`;
      const who = i.attendees.map((a) => `${esc(a.member)}${a.view ? "（" + esc(a.view) + "）" : ""}`).join("、");
      const stage = live.length ? `第${i.roundsDone + 1}轮进行中` : i.stage;
      let h = `<div class="goal ${openIssue === i.id ? "open" : ""}" data-issue="${esc(i.id)}">
        <div class="ghead"><span class="tid">${esc(i.id)}</span><span class="tt">${esc(i.title)}</span> ${issuePill(stage)}
          ${stage === "待裁决" ? '<span class="meta">等你裁决</span>' : ""}</div>
        <div class="pipe">${chips}</div>
        <div class="note">与会：${who || "—"}${live.length ? ` · <span class="dot"></span>${live.length} 人发言中` : ""}</div></div>`;
      if (openIssue === i.id) h += renderIssueDetail(i);
      return h;
    }).join("");
    return card("议题（朝会）", body, {meta: list.some((i) => i.flow) ? "这里只放结论；对话在朝会页" : "点议题看发言、总结和裁决"});
  }

  // 新结构议题：只放结论（状态、所属目标、与会、总结、裁决）和谁在思考，发言在朝会页
  function flowIssueCard(i) {
    const who = i.attendees.map((a) => `${esc(a.成员)}${a.视角 ? "（" + esc(a.视角) + "）" : ""}`).join("、");
    const think = i.thinking.length ? ` · <span class="dot"></span>${esc(i.thinking.join("、"))} 运行中` : "";
    const last = i.last ? ` · 最近：${esc(i.last.who)} ${esc(hm(i.last.time))}${i.last.private ? "（私下）" : i.last.text ? "：" + esc(i.last.text.slice(0, 40)) : ""}` : "";
    let concl = "";
    if (i.summary) concl += `<div class="fields"><span class="k">总结</span><span>${esc(i.summary.说明)}</span><span class="k">方案</span><span>${esc(i.summary.方案)}</span><span class="k">总管建议</span><span>${esc(i.summary.建议)}</span></div>`;
    if (i.ruling) concl += `<div class="fields"><span class="k">裁决</span><span>${esc(i.ruling.说明)}</span></div>`;
    if (!concl) concl = `<div class="empty">${i.stage === "收口中" ? "讨论已结束，等总管收口" : "还没有结论"}</div>`;
    return `<div class="goal fissue">
      <div class="ghead"><span class="tid">${esc(i.id)}</span><span class="tt">${esc(i.title)}</span> ${issuePill(i.stage)}
        <span class="pill">${esc(i.type)}</span>${i.goal ? ` <span class="tlink" data-goal="${esc(i.goal)}">${esc(i.goal)}</span>` : ' <span class="meta">项目级</span>'}
        ${i.stage === "待裁决" ? '<span class="meta">等你裁决</span>' : ""}<a class="tlink golink" href="${U(`/p/${esc(id)}/meet/${esc(i.id)}`)}">进入朝会 →</a></div>
      <div class="note">与会：${who || "—"} · 发言 ${i.count}${last}${think}</div>${concl}</div>`;
  }

  function issuePill(s) {
    const cls = /进行中/.test(s) ? "run" : ISSUE_CLS[s] ?? "";
    return `<span class="pill ${cls}">${/进行中/.test(s) ? '<span class="dot"></span>' : ""}${esc(s)}</span>`;
  }

  function fieldGrid(list) {
    return list.length ? `<div class="fields">${list.map((f) => `<span class="k">${esc(f.k)}</span><span>${f.v}</span>`).join("")}</div>` : `<div class="empty">未填写</div>`;
  }

  function renderIssueDetail(i) {
    let b = `<div class="detail gdetail"><h4>问题</h4>${fieldGrid(i.question)}`;
    i.rounds.filter((r) => r.speeches.length).forEach((r) => {
      b += `<h4>第 ${r.no} 轮</h4>${r.speeches.map((s, k) => `<details class="speech" data-sp="${esc(i.id + "-" + r.no + "-" + k)}" ${openSpeech.has(i.id + "-" + r.no + "-" + k) ? "open" : ""}><summary>${esc(s.who)}</summary><pre class="out">${esc(s.text)}</pre></details>`).join("")}`;
    });
    b += `<h4>总结（总管）</h4>${fieldGrid(i.summary)}<h4>裁决（总裁）</h4>${fieldGrid(i.ruling)}`;
    return b + "</div>";
  }

  function renderRunning(d) {
    const running = d.runs.filter((r) => r.status === "运行中");
    if (!running.length) return "";
    const rows = running.map((r) => {
      const idle = secs(r.last_at);
      const stale = idle != null && idle > STALE_MIN * 60;
      return `<tr><td class="num">${esc(r.run)}</td><td>${esc(r.seat)}</td><td>${esc(r.member)}</td>
        <td class="num">${dur(secs(r.started))}</td><td class="num">${esc(r.steps || 0)}</td>
        <td>${esc(r.last_action || "—")}</td>
        <td class="num ${stale ? "stale" : ""}">${idle == null ? "—" : dur(idle) + " 前"}${stale ? " · 疑似卡住" : ""}</td></tr>`;
    }).join("");
    return card("正在运行", `<div class="scroll"><table><thead><tr><th>派活</th><th>席位</th><th>成员</th><th>已运行</th><th>步数</th><th>最近动作</th><th>上次动作</th></tr></thead><tbody>${rows}</tbody></table></div>`,
      {meta: `${running.length} 个 · 超过 ${STALE_MIN} 分钟无动作标红`});
  }

  // 目标筛选：任务看卡头「目标」，派活看它所属任务的目标
  function goalOfTask(d, id) { const t = d.cards.find((x) => x.id === id); return t && t.goal ? t.goal : "none"; }

  function who(t) {
    const parts = [];
    if (t.head["执行"] || t.head["验收"]) parts.push(`${esc(t.head["执行"] || "—")} → ${esc(t.head["验收"] || "—")}`);
    if (t.holder) parts.push(`现在在 ${esc(t.holder)}`);
    return parts.join(" · ");
  }

  function taskList(d, list) {
    const runsBy = {};
    d.runs.forEach((r) => { (runsBy[r.task] = runsBy[r.task] || []).push(r); });
    const cols = COLS.map((c) => ({...c, cards: []}));
    const other = {name: "其他", cards: []};
    list.forEach((t) => { (cols.find((c) => c.match(t.state || "")) || other).cards.push(t); });
    if (other.cards.length) cols.push(other);
    // 只列有任务的状态组，一行一个任务；点开在该行下面看详情
    const html = cols.filter((c) => c.cards.length).map((c) => `<div class="tgroup"><h3>${c.name}<span class="n">${c.cards.length}</span></h3>${c.cards.map((t) => {
      const rs = runsBy[t.id] || [];
      const live = rs.some((r) => r.status === "运行中");
      const lastRow = t.flow[t.flow.length - 1] || {};
      const last = strip(lastRow[Object.keys(lastRow).find((k) => k.startsWith("说明"))] || "");
      const row = `<div class="trow task ${openTask === t.id ? "open" : ""}" data-task="${esc(t.id)}">
        <span class="tid">${esc(t.id)}</span><span class="tt">${esc(t.title)}</span>
        ${t.goal && !t.id.startsWith(t.goal + "-") ? `<span class="gtag">${esc(t.goal)}${t.stage ? " · " + circ(t.stage) : ""}</span>` : ""}${rs.some((r) => r.override) ? '<span class="pill warn">偏离</span>' : ""}
        <span class="tw">${who(t)}</span>
        ${statusPill(t.state || "—")}
        <span class="tn">${live ? '<span class="dot"></span>' : ""}${rs.length ? `派活 ${rs.length}` : ""}</span>
        ${last ? `<div class="note">${esc(last)}</div>` : ""}
      </div>`;
      return row + (openTask === t.id ? renderTaskDetail(t, rs) : "");
    }).join("")}</div>`).join("");
    return html ? `<div class="tlist">${html}</div>` : `<div class="empty">这里没有任务</div>`;
  }

  function renderTaskDetail(t, runs) {
    let b = `<div class="detail"><h4>${esc(t.id)} ${esc(t.title)} ${statusPill(t.state || "—")}</h4>`;
    const head = Object.entries(t.head).filter(([k]) => k !== "状态");
    const fields = head.map(([k, v]) => ({k, v: esc(v)})).concat(t.fields);
    if (fields.length) b += `<div class="fields">${fields.map((f) => `<span class="k">${esc(f.k)}</span><span>${f.v}</span>`).join("")}</div>`;
    if (t.flow.length) {
      const keys = Object.keys(t.flow[0]);
      b += `<h4>流转</h4><div class="scroll"><table><thead><tr>${keys.map((k) => `<th>${esc(k.replace(/（.*）/, ""))}</th>`).join("")}</tr></thead><tbody>${t.flow.map((r) => `<tr>${keys.map((k) => `<td>${r[k] || ""}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    if (runs.length) b += `<h4>派活记录</h4>${runsTable(runs.slice().reverse(), false)}`;
    return b + "</div>";
  }

  // 派活记录按开始日期分组（新的在上），组头写当天次数、合计用时和 token
  const WEEK = "日一二三四五六";
  function dayLabel(day) {
    const [y, m, dd] = day.split("-").map(Number), dt = new Date(y, m - 1, dd);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const diff = Math.round((today - dt) / 86400000);
    return `${diff === 0 ? "今天 · " : diff === 1 ? "昨天 · " : ""}${day.slice(5)}（周${WEEK[dt.getDay()]}）`;
  }
  const tookOf = (r) => (r.ended ? (new Date(r.ended) - new Date(r.started)) / 1000 : secs(r.started));
  function runsTable(runs, showTask) {
    runs = runs.slice().sort((a, b) => String(b.started || "").localeCompare(String(a.started || "")));
    const cols = showTask ? 8 : 7;
    let lastDay = null;
    const rows = runs.map((r) => {
      const day = (r.started || "").slice(0, 10);
      let head = "";
      if (day !== lastDay) {
        lastDay = day;
        const same = runs.filter((x) => (x.started || "").slice(0, 10) === day);
        head = `<tr class="dayrow"><td colspan="${cols}"><b>${day ? dayLabel(day) : "时间未知"}</b><span>${same.length} 次 · 合计用时 ${dur(same.reduce((a, x) => a + (tookOf(x) || 0), 0))} · token ${tok(sumTok(same)).split(" ·")[0]}</span></td></tr>`;
      }
      return head + runRow(r, showTask, cols);
    }).join("");
    return `<div class="scroll"><table class="runs"><thead><tr><th>派活</th>${showTask ? "<th>任务</th>" : ""}<th>席位 · 成员</th><th>状态</th><th>开始</th><th>用时</th><th>token</th><th>结果</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function runRow(r, showTask, cols) {
    {
      const took = tookOf(r);
      const summary = r.status === "完成" ? r.final : r.error || r.final;
      const open = openRuns.has(r.run);
      const plain = (summary || "").replace(/[*#`>|]+/g, " ").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/\s+/g, " ").trim();
      let tr = `<tr class="click" data-run="${esc(r.run)}"><td class="num">${esc(r.run)}</td>${showTask ? `<td>${esc(r.task)}</td>` : ""}
        <td>${esc(r.seat)} · ${esc(r.member)}<div class="sub2">${r.mode === "续接" ? "续接" : "新会话"}</div></td><td>${statusPill(r.status || "")}${r.override ? ' <span class="pill warn">偏离</span>' : ""}</td>
        <td class="num">${(r.started || "").slice(11, 16) || "—"}</td><td class="num">${dur(took)}<div class="sub2">${esc(r.steps || 0)} 步</div></td><td class="num">${tok(r.tokens)}</td>
        <td><div class="clip">${esc(plain)}</div></td></tr>`;
      if (open) {
        tr += `<tr><td colspan="${cols}">
          <div class="meta">会话 ${esc(r.session || "—")}${r.continues ? ` · 续接自 ${esc(r.continues)}` : ""}${r.ended ? ` · 结束于 ${hm(r.ended)}` : ""}</div>
          <div class="meta" style="margin-top:6px">${esc(tokDetail(r.tokens))}</div>
          ${r.override ? `<div class="meta" style="margin-top:6px">偏离理由：${esc(r.override)}；${(r.deviations || []).map(esc).join("；")}</div>` : ""}
          <div class="meta" style="margin-top:6px">启动语</div><pre class="out">${esc(r.prompt)}</pre>
          ${r.final ? `<div class="meta">最终回复</div><pre class="out">${esc(r.final)}</pre>` : ""}
          ${r.error ? `<div class="meta">错误</div><pre class="out">${esc(r.error)}</pre>` : ""}
        </td></tr>`;
      }
      return tr;
    }
  }

  // ---------- 归档页 ----------
  function doneDate(x) {
    const row = (x.flow || []).filter((r) => /^(通过|完成)/.test(strip(r["状态"] || ""))).pop();
    return row ? strip(row["日期"] || "") : "";
  }
  function renderArchiveGoals(d) {
    if (!d.goals.length) return card("归档目标", '<div class="empty">没有归档的目标</div>');
    const goals = d.goals.slice().sort((a, b) => b.id.localeCompare(a.id, undefined, {numeric: true}));
    const focus = goals.find((g) => g.id === selGoal) || goals[0];
    const rows = goals.map((g) => {
      const runs = goalRuns(d, g);
      return `<div class="grow ${g.id === selGoal ? "on" : g.id === focus.id ? "auto" : ""}" data-goal="${esc(g.id)}">
        <div class="gname"><span class="tid">${esc(g.id)}</span><span class="tt">${esc(g.title)}</span>${statusPill(g.state || "—")}</div>
        <div class="gprog">${stageDots(g)}</div>
        <div class="gnow">${g.head["批准"] ? "批准：" + esc(g.head["批准"]) : ""}</div>
        <div class="galert"></div>
        <div class="gcost">${runs.length ? `派活 ${runs.length} · ${tok(sumTok(runs)).split(" ·")[0]}` : "未派活"}</div>
      </div>`;
    }).join("");
    const body = `<div class="glist">${rows}</div><div class="gfocus"><div class="gfh"><b>${esc(focus.id)} ${esc(focus.title)}</b><span class="meta">${d.view ? "时序图" : "流程泳道"} · 已归档</span>
</div>
      ${d.view ? goalMain(d, focus) : renderLanes(d, focus)}</div>`;
    return card("归档目标", body, {meta: `${goals.length} 个 · 点一行看它的流程`});
  }
  function renderArchiveTasks(d) {
    if (!d.cards.length) return card("归档任务", '<div class="empty">没有归档的任务</div>');
    const runsBy = {};
    d.runs.forEach((r) => { (runsBy[r.task] = runsBy[r.task] || []).push(r); });
    const groups = {};
    d.cards.forEach((t) => { const k = t.goal || ""; (groups[k] = groups[k] || []).push(t); });
    const keys = Object.keys(groups).sort((a, b) => (a === "") - (b === "") || b.localeCompare(a, undefined, {numeric: true}));
    const html = keys.map((k) => {
      const g = d.goals.find((x) => x.id === k);
      const title = k ? `${esc(k)}${g ? " " + esc(g.title) : ""}` : "零散任务";
      return `<div class="tgroup"><h3>${title}<span class="n">${groups[k].length}</span></h3>${groups[k].map((t) => {
        const rs = runsBy[t.id] || [];
        const dd = doneDate(t);
        return `<div class="trow task ${openTask === t.id ? "open" : ""}" data-task="${esc(t.id)}">
          <span class="tid">${esc(t.id)}</span><span class="tt">${esc(t.title)}</span>
          <span class="tw">${esc(t.head["执行"] || "—")} → ${esc(t.head["验收"] || "—")}${dd ? ` · ${esc(dd)} 通过` : ""}</span>${statusPill(t.state || "—")}
          <span class="tn">${rs.length ? `派活 ${rs.length}` : ""}</span></div>` + (openTask === t.id ? renderTaskDetail(t, rs) : "");
      }).join("")}</div>`;
    }).join("");
    return card("归档任务", `<div class="tlist">${html}</div>`, {meta: `${d.cards.length} 张 · 点一行看流转和派活记录`});
  }
  function renderArchive(d) {
    const n = d.goals.length + d.cards.length + d.issues.length;
    const body = n ? `${renderArchiveGoals(d)}${renderIssues(d)}${renderArchiveTasks(d)}` : '<div class="empty">这个项目还没有归档的目标、任务或议题</div>';
    return `<div class="strip"><span class="si">归档目标 <b>${d.goals.length}</b></span><span class="si">任务 <b>${d.cards.length}</b></span><span class="si">议题 <b>${d.issues.length}</b></span><span class="si">派活 <b>${d.runs.length}</b> 次 · token <b>${tok(sumTok(d.runs)).split(" ·")[0]}</b></span></div>${body}`;
  }

  function render() {
    const d = data;
    document.title = d.name + (ARCHIVE ? " · 归档" : " · 御前看板");
    document.getElementById("name").textContent = d.name + (ARCHIVE ? " · 归档" : "");
    const m = d.meta;
    const ac = d.archivedCount || {};
    const an = (ac.goals || 0) + (ac.tasks || 0) + (ac.issues || 0);
    const alink = !ARCHIVE && an ? `<a href="${U(`/p/${esc(id)}/archive`)}">已归档 ${[ac.goals && ac.goals + " 个目标", ac.tasks && ac.tasks + " 张任务", ac.issues && ac.issues + " 个议题"].filter(Boolean).join("、")} →</a>` : "";
    document.getElementById("meta").innerHTML = [m["状态"], m["截止"] && "截止 " + m["截止"], `<a href="${esc(d.progressHref)}">PROGRESS.md</a>`, alink]
      .filter(Boolean).map((x) => (x.startsWith("<a") ? x : esc(x))).join(" · ");
    if (ARCHIVE) { app.classList.add("archive"); app.innerHTML = renderArchive(d); return; }
    const cur = curPick(d);
    const pane = cur === "ideas" ? renderIdeasPane(d) : cur === "loose" ? renderLoosePane(d) : cur === "issues" ? renderIssues(d) : cur === "dec" ? renderDecPane(d) : renderGoalPane(d, cur);
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.draft : null;
    app.innerHTML = `${renderStrip(d)}${renderCheck(d)}<div class="row">${renderPending(d)}${renderNow(d)}</div>${renderRunning(d)}${renderPicker(d, cur)}${pane}`;
    if (d.view && d.view.称谓) { applyTitles(app, d.view.称谓); applyTitles(document.getElementById("meta"), d.view.称谓); }
    if (focused) {
      const box = [...app.querySelectorAll("textarea[data-draft]")].find((x) => x.dataset.draft === focused);
      if (box) { box.focus(); box.selectionStart = box.selectionEnd = box.value.length; }
    }
  }

  // 称谓：视图模型可带一套显示名（如演示案例的明朝叫法），只换页面上的文字，不碰属性和数据
  function applyTitles(root, titles) {
    const keys = Object.keys(titles || {}).filter((k) => titles[k] && titles[k] !== k).sort((x, y) => y.length - x.length);
    if (!keys.length) return;
    const re = new RegExp(keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => { if (re.test(n.nodeValue)) { re.lastIndex = 0; n.nodeValue = n.nodeValue.replace(re, (m) => titles[m]); } re.lastIndex = 0; });
  }

  async function load() {
    try {
      const j = await getJSON("/api/p/" + id + (ARCHIVE ? "/archive" : ""));
      if (j.error) throw new Error(j.error);
      const sig = JSON.stringify({...j, generated: 0});
      const live = j.runs.some((x) => x.status === "运行中");
      data = j;
      if (sig !== lastSig || live) render();
      lastSig = sig;
      const now = new Date().toLocaleTimeString("zh-CN", {hour12: false});
      document.getElementById("tick").textContent = SITE ? "静态演示 · 只读" : ARCHIVE ? "打开时加载 · " + now + " · 刷新页面重新读取" : "每 5 秒刷新 · " + now;
    } catch (e) {
      document.getElementById("tick").textContent = "刷新失败：" + e.message;
    }
  }

  function selectGoal(id) {
    selGoal = id;
    history.replaceState(null, "", id ? "#" + id : location.pathname);
    render();
  }
  // 主页：切换主区呈现哪一个（目标编号、loose、issues、dec）
  function choose(key, scroll) {
    if (pick !== key) { openSeq = null; hiTask = null; }
    pick = key;
    history.replaceState(null, "", "#" + encodeURIComponent(key));
    render();
    if (scroll) document.querySelector(".picker")?.scrollIntoView({behavior: "smooth", block: "start"});
  }

  app.addEventListener("input", (e) => {
    const k = e.target.dataset && e.target.dataset.draft;
    if (k) drafts[k] = e.target.value;
  });
  // 批准、退回、提意见：和朝会页一样走受限写入口，不合法的把错误显示出来
  // 点因果标注：展开对方所在的折叠，选中它并滚过去
  function goSeq(n) {
    const gid = ARCHIVE ? selGoal || data.goals.map((x) => x.id).sort((x, y) => y.localeCompare(x, undefined, {numeric: true}))[0]
      : curPick(data) === "loose" ? "—" : curPick(data);
    const g = seqGroup(data, gid);
    const ev = g && g.事件.find((x) => x.项目序 === n);
    if (!ev) return;
    if (ev.层 === "任务" && ev.阶段 != null) openStages.add(gid + ":" + ev.阶段);
    if ((g.结构 && g.结构.记录 || []).includes(n)) openRecord.add(gid);
    if (hiTask) hiTask = null;
    openSeq = n;
    render();
    document.querySelector(`.seq .ev[data-seq="${n}"]`)?.scrollIntoView({behavior: "smooth", block: "center"});
  }
  async function goalAct(btn) {
    const act = btn.dataset.goalact, key = btn.dataset.key;
    const body = {action: act, text: key ? (drafts[key] || "").trim() : (drafts["goal:" + btn.dataset.goalid] || "").trim()};
    if (btn.dataset.version != null) body.version = +btn.dataset.version;
    if (btn.dataset.tid) body.task = btn.dataset.tid;
    if (SITE) { apprMsg = "静态演示只读：批红要在本机看板上做"; render(); return; }
    if (act !== "批准" && !body.text) { apprMsg = "先写意见"; render(); return; }
    btn.disabled = true;
    try {
      const r = await fetch(`/api/p/${id}/goal/${btn.dataset.goalid}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Board": "1"}, body: JSON.stringify(body)});
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      apprMsg = "";
      if (key) delete drafts[key]; else delete drafts["goal:" + btn.dataset.goalid];
      lastSig = "";
      await load();
    } catch (err) {
      apprMsg = err.message;
      render();
    }
  }

  app.addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="file://"]');
    if (a) {
      e.preventDefault();
      fetch("/api/open", {method: "POST", headers: {"Content-Type": "application/json", "X-Board": "1"},
        body: JSON.stringify({path: decodeURIComponent(a.getAttribute("href").slice(7))})});
      return;
    }
    if (e.target.closest("a")) return;
    if (e.target.closest("textarea")) return;
    const ga = e.target.closest("[data-goalact]");
    if (ga) { goalAct(ga); return; }
    const rc = e.target.closest("[data-record]");
    if (rc) { openRecord.has(rc.dataset.record) ? openRecord.delete(rc.dataset.record) : openRecord.add(rc.dataset.record); render(); return; }
    const tc = e.target.closest("[data-taskcard]");
    if (tc) {
      const tid = tc.dataset.taskcard;
      openCard = openCard === tid ? null : tid;
      hiTask = openCard;
      render();
      document.querySelector(".tcard")?.scrollIntoView({behavior: "smooth", block: "nearest"});
      return;
    }
    if (e.target.closest("[data-relnow]")) { openSeq = null; render(); return; }
    const rk = e.target.closest("[data-rtask]");
    if (rk) {
      // 点关系图上的任务：时序图只看它，并滚到它到游标为止的最新一步
      const tid = rk.dataset.rtask;
      hiTask = hiTask === tid ? null : tid;
      render();
      if (hiTask) {
        const seqs = [...document.querySelectorAll(".seq .ev[data-seq]")].filter((x) => !x.classList.contains("dim"));
        const g = seqGroup(data, curPick(data) === "loose" ? "—" : curPick(data));
        const c = g ? relCursor(g) : null;
        const pickEl = seqs.filter((x) => c == null || +x.dataset.seq <= c).pop();
        pickEl?.scrollIntoView({behavior: "smooth", block: "center"});
      }
      return;
    }
    const hs = e.target.closest("[data-hitask]");
    if (hs) { hiTask = hiTask === hs.dataset.hitask ? null : hs.dataset.hitask; render(); return; }
    const gx = e.target.closest("[data-goseq]");
    if (gx) { goSeq(+gx.dataset.goseq); return; }
    const sq = e.target.closest("[data-seq]");
    if (sq) { const n = +sq.dataset.seq; openSeq = openSeq === n ? null : n; render(); return; }
    const fa = e.target.closest("[data-foldall]");
    if (fa) {
      const g = seqGroup(data, fa.dataset.foldall);
      (g ? g.阶段 || [] : []).filter((x) => x.状态 === "通过").forEach((x) => {
        const k = fa.dataset.foldall + ":" + x.序;
        fa.dataset.open === "1" ? openStages.add(k) : openStages.delete(k);
      });
      render(); return;
    }
    const fd = e.target.closest("[data-fold]");
    if (fd) { openStages.has(fd.dataset.fold) ? openStages.delete(fd.dataset.fold) : openStages.add(fd.dataset.fold); render(); return; }
    const pk = e.target.closest("[data-pick]");
    if (pk) { choose(pk.dataset.pick); return; }
    const tb = e.target.closest("[data-gtab]");
    if (tb) { goalTab = tb.dataset.gtab; render(); return; }
    const gt = e.target.closest("[data-maintab]");
    if (gt) { const [gid, k] = gt.dataset.maintab.split(":"); mainTab[gid] = k; render(); return; }
    const gd = e.target.closest("[data-gdet]");
    if (gd) { openGoal = openGoal === gd.dataset.gdet ? null : gd.dataset.gdet; render(); return; }
    const t = e.target.closest("[data-task]");
    if (t) {
      if (!t.dataset.task) return;
      const fromGoal = t.classList.contains("tlink");
      openTask = fromGoal ? t.dataset.task : (openTask === t.dataset.task ? null : t.dataset.task);
      if (fromGoal && !ARCHIVE) { goalTab = "tasks"; pick = goalOfTask(data, t.dataset.task) === "none" ? "loose" : goalOfTask(data, t.dataset.task); }
      if (fromGoal) mainTab[goalOfTask(data, t.dataset.task)] = "low";  // 任务详情在「任务和派活」标签里
      render();
      if (fromGoal) document.querySelector(".task.open")?.scrollIntoView({behavior: "smooth", block: "center"});
      return;
    }
    if (e.target.closest("details")) return;
    const ln = e.target.closest("[data-lnode]");
    if (ln) { openNode = openNode === ln.dataset.lnode ? null : ln.dataset.lnode; render(); return; }
    const iss = e.target.closest("[data-issue]");
    if (iss) {
      if (!ARCHIVE && curPick(data) !== "issues") { openIssue = iss.dataset.issue; choose("issues", true); return; }
      openIssue = openIssue === iss.dataset.issue ? null : iss.dataset.issue; render(); return;
    }
    const g = e.target.closest("[data-goal]");
    if (g) {
      // 总览行点击切换选中；「待你决定」里的目标编号只负责选中并跳到泳道
      if (!ARCHIVE) { choose(g.dataset.goal, true); return; }
      const row = g.classList.contains("grow");
      selectGoal(row && selGoal === g.dataset.goal ? null : g.dataset.goal);
      if (!row) document.querySelector(".gfocus")?.scrollIntoView({behavior: "smooth", block: "start"});
      return;
    }
    const r = e.target.closest("[data-run]");
    if (r && !window.getSelection().toString()) {
      openRuns.has(r.dataset.run) ? openRuns.delete(r.dataset.run) : openRuns.add(r.dataset.run);
      render();
    }
  });
  document.getElementById("meta").addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="file://"]');
    if (!a) return;
    e.preventDefault();
    fetch("/api/open", {method: "POST", headers: {"Content-Type": "application/json", "X-Board": "1"},
      body: JSON.stringify({path: decodeURIComponent(a.getAttribute("href").slice(7))})});
  });

  app.addEventListener("toggle", (e) => {
    const sp = e.target.dataset && e.target.dataset.sp;
    if (sp) e.target.open ? openSpeech.add(sp) : openSpeech.delete(sp);
    const stp = e.target.dataset && e.target.dataset.step;
    if (stp) e.target.open ? openSteps.add(stp) : openSteps.delete(stp);
  }, true);

  let rt = null;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => data && render(), 200); });

  if (ARCHIVE) {
    const back = document.querySelector(".back");
    back.href = U("/p/" + id);
    back.textContent = "← 项目看板";
  }
  load().then(() => { if (ARCHIVE && openTask) document.querySelector(".task.open")?.scrollIntoView({block: "center"}); });
  if (!ARCHIVE && !SITE) setInterval(() => { if (document.visibilityState === "visible") load(); }, 5000);
})();
