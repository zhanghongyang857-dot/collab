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
  const T = (k, v) => window.t(k, v);  // 界面文字（i18n.js）；局部变量常叫 t（任务），所以用 T
  const ST = V.State, RS = V.RunStatus;
  const isIn = (s, ...xs) => xs.some((x) => String(s || "").startsWith(x));  // 状态是不是其中之一（旧结构的状态可能带注记，按开头认）
  const COLS = [
    {key: "todo", match: (s) => isIn(s, ST.PLANNED, ST.DISPATCHED, ST.APPROVED, ST.PAUSED)},
    {key: "doing", match: (s) => isIn(s, ST.IN_PROGRESS)},
    {key: "review", match: (s) => isIn(s, ST.IN_REVIEW)},
    {key: "attention", match: (s) => isIn(s, V.Result.NEEDS_MORE, ST.FAILED, ST.BLOCKED)},
    {key: "passed", match: (s) => isIn(s, ST.PASSED)},
  ].map((c) => ({...c, get name() { return T("board.col." + c.key); }}));
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
    if (s < 60) return T("board.dur.s", {s});
    if (s < 3600) return s % 60 ? T("board.dur.ms", {m: Math.floor(s / 60), s: s % 60}) : T("board.dur.m", {m: Math.floor(s / 60)});
    return T("board.dur.hm", {h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60)});
  }
  function tok(t) {
    if (!t || !t.total) return "—";
    const n = t.total;
    const s = I18n.lang() === "zh" ? (n >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, "") + "万" : String(n))
      : (n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n));
    return t.cached ? `${s} · ${window.t("board.tok.cached", {pct: Math.round((100 * t.cached) / n)})}` : s;
  }
  function tokDetail(t) {
    if (!t || !t.total) return T("board.tok.unknown");
    const parts = [`token ${tok(t)}`, T("board.tok.input", {n: t.input || 0}), T("board.tok.cache", {n: t.cached || 0}), T("board.tok.output", {n: t.output || 0})];
    if (t.calls) parts.push(T("board.tok.calls", {n: t.calls}));
    if (t.context) parts.push(T("board.tok.context", {n: t.context}));
    if (t.cost_usd) parts.push(T("board.tok.cost", {n: t.cost_usd}));
    return parts.join(" · ");
  }
  function sumTok(runs) {
    const s = {total: 0, cached: 0};
    runs.forEach((r) => { if (r.tokens) { s.total += r.tokens.total || 0; s.cached += r.tokens.cached || 0; } });
    return s;
  }
  const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "—");
  const NS = (s) => ((I18N.names.state || {})[s] || (I18N.names.stage_status || {})[s] || s);  // 状态（含阶段进度）的显示名
  const NE = (e) => N("edge", e), NR = (r) => N("result", r);
  function statusPill(s, kind = "state") {  // s 是状态代码、派活状态代码，或旧结构卡片上写的文字（旧卡片没有代码，只能按原文认）
    const run = kind === "run_status";
    const cls = run ? ({[RS.RUNNING]: "run", [RS.DONE]: "ok", [RS.FAILED]: "bad", [RS.LOST]: "bad", [RS.STOPPED]: "warn"}[s] || "")
      : [ST.DONE, ST.PASSED].includes(s) || isIn(s, "通过") ? "ok" : s === ST.FAILED || /失败|异常|未通过/.test(s) ? "bad"
      : [ST.BLOCKED, V.Result.NEEDS_MORE].includes(s) || /中断|需补充|受阻/.test(s) ? "warn" : "";
    return `<span class="pill ${cls}">${run && s === RS.RUNNING ? '<span class="dot"></span>' : ""}${esc(run ? N(kind, s) : NS(s))}</span>`;
  }

  function card(title, body, opts = {}) {
    return `<section class="card ${opts.cls || ""}"><div class="card-head"><h2>${title}</h2>${opts.meta ? `<span class="meta">${opts.meta}</span>` : ""}</div>${body}</section>`;
  }

  // 新结构项目：「待你决定」用视图模型给的结构化条目（类型是代码），按语言拼
  function pendingItem(it) {
    const kcls = it.type === V.Pending.BLOCKED ? "bad" : "run";
    const kind = it.type === "comment" ? T("board.pend.comment") : N("pending", it.type) + (it.reviews && it.reviews.length ? T("board.pend.with_reviews", {ids: it.reviews.join(", ")}) : "");
    const pick = (String(it.recommendation || "").match(/[A-Z]/) || [])[0];
    const opts = String(it.options || "").split(/[；;]\s*(?=[A-Z][\s　])/).filter((o) => o.trim()).map((o) => {
      const m = o.match(/^\s*([A-Z])[\s　]/);
      const on = m && m[1] === pick;
      return `<li class="${on ? "pick" : ""}">${esc(o)}${on ? ` <span class="sug">${esc(T("board.pend.recommended"))}</span>` : ""}</li>`;
    }).join("");
    const link = /^(G\d+-)?T\d+$/.test(it.id) && data.cards.some((x) => x.id === it.id) ? ` data-task="${esc(it.id)}"`
      : /^G\d+$/.test(it.id) ? ` data-goal="${esc(it.id)}"` : /^I\d+$/.test(it.id) ? ` data-issue="${esc(it.id)}"` : "";
    const extra = !pick && it.recommendation ? `<div class="note">${esc(T("board.pend.lead_recommends"))} ${esc(it.recommendation)}</div>` : "";
    return `<div class="pend k-${kcls}"><div class="ph"><span class="tid ${link ? "tlink" : ""}"${link}>${esc(it.id)}</span><span class="pill ${kcls}">${esc(kind)}</span><span class="pw">${esc(it.note)}</span>${it.by ? `<span class="meta">${esc(T("board.pend.by", {who: WHO(it.by)}))}</span>` : ""}</div>
      <ul class="popts">${opts}</ul>${extra}</div>`;
  }
  // 旧结构项目：「待你决定」是 PROGRESS 里手写的一行，约定格式：编号｜要决定什么｜可选方案与代价｜总管建议｜验收意见｜提出者；不合格式的原样显示
  function pendingCard(html) {
    const f = html.split(/[｜|]/).map((x) => x.trim());
    if (f.length < 4) return `<div class="pend raw">${html}</div>`;
    let [id, what, opts, sug, chk, by] = f;
    const sample = /^（示例）/.test(strip(id));
    id = id.replace(/^（示例）\s*/, "");
    const pick = (strip(sug).match(/[A-Z]/) || [])[0];
    const list = opts.split(/[；;]\s*(?=[A-Z][\s　])/).map((o) => {
      const m = strip(o).match(/^([A-Z])[\s　]/);
      const on = m && m[1] === pick;
      return `<li class="${on ? "pick" : ""}">${o}${on ? ` <span class="sug">${esc(T("board.pend.recommended"))}</span>` : ""}</li>`;
    }).join("");
    const plainId = strip(id).trim();
    const link = /^(G\d+-)?T\d+$/.test(plainId) && data.cards.some((t) => t.id === plainId) ? ` data-task="${esc(plainId)}"`
      : /^G\d+$/.test(plainId) ? ` data-goal="${esc(plainId)}"` : /^I\d+$/.test(plainId) ? ` data-issue="${esc(plainId)}"` : "";
    const extra = pick ? "" : `<div class="note">${sug}</div>`;
    const km = strip(what).match(/^(受阻|批准[^：:]*|目标验收|裁决|返工|授权|总裁意见[^：:]*)[：:]\s*/);
    const kind = km ? km[1] : "";
    if (km) what = what.replace(/^[^：:]*[：:]\s*/, "");
    const kcls = /受阻/.test(kind) ? "bad" : /返工/.test(kind) ? "warn" : "run";
    const check = chk && !/^[—\-\s]*$/.test(strip(chk)) ? `<div class="note">${esc(T("board.pend.review_note"))}${chk}</div>` : "";
    return `<div class="pend ${kind ? "k-" + kcls : ""}"><div class="ph"><span class="tid ${link ? "tlink" : ""}"${link}>${id}</span>${kind ? `<span class="pill ${kcls}">${esc(kind)}</span>` : ""}${sample ? `<span class="pill">${esc(T("board.pend.sample"))}</span>` : ""}<span class="pw">${what}</span>${by ? `<span class="meta">${esc(T("board.pend.by", {who: ""}))}${by}</span>` : ""}</div>
      <ul class="popts">${list}</ul>${extra}${check}</div>`;
  }

  // 校验结果（core/check.py）：错误会挡住派活和 Claude 的每轮结束，提醒只显示
  function renderCheck(d) {
    const items = d.check || [];
    if (!items.length) return "";
    const errs = items.filter((x) => x.level === "error"), warns = items.filter((x) => x.level !== "error");
    const li = (x) => `<li class="${x.level === "error" ? "e" : "w"}"><span class="loc">${esc(x.file)}${x.line ? ":" + x.line : ""}</span>${esc(x.msg)}</li>`;
    const title = errs.length ? (warns.length ? T("board.check.errs_warns", {e: errs.length, w: warns.length}) : T("board.check.errs", {e: errs.length})) : T("board.check.warns", {w: warns.length});
    if (!errs.length) return `<details class="checkline"><summary>${title}</summary><ul class="checks">${warns.map(li).join("")}</ul></details>`;
    const note = `<div class="note">${esc(T("board.check.note"))}</div>`;
    return card(title, `<ul class="checks">${errs.concat(warns).map(li).join("")}</ul>${note}`, {cls: errs.length ? "check-bad" : "alert"});
  }

  function renderPending(d) {
    const items = d.pendingItems;
    const n = items ? items.length : d.pending.length;
    const body = n ? (items ? items.map(pendingItem) : d.pending.map(pendingCard)).join("") : `<div class="empty small">${esc(T("board.pend.empty"))}</div>`;
    return card(esc(I18N.sections.decisions), body, {cls: "pending", meta: n ? T("board.n_items", {n}) : ""});
  }

  // 「现在」：先说等谁做什么，再是下一步，现状只露 3 行
  function renderNow(d) {
    const goals = activeGoals(d);
    let b = goals.length ? goals.map((g) => `<div class="nowbig"><span class="tid">${esc(g.id)}</span>${nowLine(d, g)}</div>`).join("") : "";
    b += `<h4>${esc(I18N.sections.next)}</h4>${d.next ? `<div>${d.next}</div>` : `<div class="empty">${esc(T("board.not_filled"))}</div>`}`;
    if (d.status.length) {
      const li = (x) => `<li>${x}</li>`;
      b += `<h4>${esc(I18N.sections.status)}</h4><ul class="plain">${d.status.slice(0, 3).map(li).join("")}</ul>`;
      if (d.status.length > 3) b += `<details class="more"><summary>${esc(T("board.more_lines", {n: d.status.length - 3}))}</summary><ul class="plain">${d.status.slice(3).map(li).join("")}</ul></details>`;
    }
    return card(esc(T("board.now")), b, {cls: "now"});
  }

  // 顶部摘要：目标、任务各状态数、在跑的派活、token 合计
  function renderStrip(d) {
    const goals = d.goals.filter((g) => !isIn(g.state, ST.DONE, ST.CANCELLED));
    const counts = COLS.map((c) => [c.name, d.cards.filter((t) => c.match(t.state || "")).length]).filter(([, n]) => n);
    const running = d.runs.filter((r) => r.status === V.RunStatus.RUNNING).length;
    const total = sumTok(d.runs);
    const npend = d.pendingItems ? d.pendingItems.length : d.pending.length;
    const items = [
      `<span class="si">${T("board.strip.goals", {n: `<b>${goals.length}</b>`})}</span>`,
      `<span class="si">${esc(I18N.sections.decisions)} <b>${npend}</b></span>`,
      `<span class="si">${esc(T("board.strip.tasks"))} ${counts.length ? counts.map(([k, n]) => `${esc(k)} <b>${n}</b>`).join(" · ") : "<b>0</b>"}</span>`,
      running ? `<span class="si live"><span class="dot"></span>${T("board.strip.running", {n: `<b>${running}</b>`})}</span>` : `<span class="si">${esc(T("board.strip.none_running"))}</span>`,
      `<span class="si">${T("board.strip.runs", {n: `<b>${d.runs.length}</b>`})} · token <b>${tok(total).split(" ·")[0]}</b></span>`,
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
    return n < 0 ? T("board.due.over", {n: -n}) : n === 0 ? T("board.due.today") : T("board.due.left", {n});
  }


  function goalRuns(d, g) {
    const ids = new Set(g.stages.flatMap((s) => s.tasks));
    return d.runs.filter((r) => ids.has(r.task));
  }

  // ---------- 多目标：总览一行一个，按「待你决定 > 受阻 > 进行中 > 待批准 > 暂停」再按优先排；只展开一个目标的泳道 ----------
  const SORT = (g) => (g.alert.pend ? 0 : g.alert.block ? 1 : isIn(g.state, ST.ACTIVE) ? 2 : isIn(g.state, ST.PENDING_APPROVAL) ? 3 : 4);
  function goalTasks(d, g) { return new Set(g.stages.flatMap((s) => s.tasks)); }
  function goalInfo(d, g) {
    const ids = goalTasks(d, g);
    const pend = d.pendingItems ? d.pendingItems.filter((x) => x.id === g.id || ids.has(x.id)).length
      : d.pending.filter((h) => { const k = strip(h.split(/[｜|]/)[0]).replace(/^（示例）\s*/, "").trim(); return k === g.id || ids.has(k); }).length;
    const block = g.stages.some((s) => s.status === ST.BLOCKED);
    const dep = (g.head.depends_on || "").match(/G\d+/g) || [];
    const waiting = dep.filter((x) => { const o = d.goals.find((q) => q.id === x); return o && !isIn(o.state, ST.DONE); });
    const prio = parseInt(g.head.priority, 10);
    return {...g, alert: {pend, block}, waiting, prio: isNaN(prio) ? 99 : prio, runs: goalRuns(d, g)};
  }
  // 想法：还在起草、有阶段（想法、讨论、方案）的目标，不进目标列表，单独一页按阶段分组
  const IDEA_STAGES = [V.DraftStage.IDEA, V.DraftStage.DISCUSSION, V.DraftStage.PROPOSAL];
  const ideaGoals = (d) => d.goals.filter((g) => g.idea && !isIn(g.state, ST.DONE, ST.CANCELLED));
  function activeGoals(d) {
    return d.goals.filter((g) => !isIn(g.state, ST.DONE, ST.CANCELLED) && !g.idea).map((g) => goalInfo(d, g))
      .sort((a, b) => SORT(a) - SORT(b) || a.prio - b.prio || a.id.localeCompare(b.id));
  }
  function stageDots(g) {
    const cls = {[V.StageStatus.PASSED]: "ok", [V.StageStatus.ACTIVE]: "now", [ST.BLOCKED]: "bad", [ST.IN_REVIEW]: "now", [ST.PASSED]: "ok"};
    const done = g.stages.filter((s) => s.status === V.StageStatus.PASSED).length;
    return `<span class="dots">${g.stages.map((s) => `<i class="${cls[s.status] || ""}" title="${esc(T("board.stage_dot", {no: s.no, name: s.seat, state: NS(s.status)}))}"></i>`).join("")}</span><span class="dn">${done}/${g.stages.length}</span>`;
  }

  // ---------- 选择器：每个目标一个，另有零散任务（有才显示）、议题、决议；主区一次只呈现选中的一个 ----------
  let pick = ARCHIVE ? null : decodeURIComponent((location.hash.match(/^#(.+)$/) || [])[1] || "") || null;
  let goalTab = "tasks";
  function allGoals(d) {
    const done = d.goals.filter((g) => isIn(g.state, ST.DONE, ST.CANCELLED)).map((g) => goalInfo(d, g))
      .sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}));
    return activeGoals(d).concat(done);
  }
  const hasLoose = (d) => (d.view ? !!d.view.loose : d.cards.some((t) => !t.goal));
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
      const done = isIn(g.state, ST.DONE, ST.CANCELLED);

      const alerts = (g.alert.pend ? `<span class="pill run">${esc(I18N.sections.decisions)} ${g.alert.pend}</span>` : "") + (g.alert.block ? `<span class="pill bad">${esc(NS(ST.BLOCKED))}</span>` : "");
      return btn(g.id, `<span class="tid">${esc(g.id)}</span><span class="pt">${esc(g.title)}</span>${statusPill(g.state || "—")}${alerts}`, done ? "done" : "");
    }).join("");
    const waitIssue = d.issues.filter((i) => i.stage === V.State.PENDING_RULING).length;
    const other = [
      ideaGoals(d).length ? btn("ideas", `${esc(T("board.pick.ideas"))} <span class="n">${ideaGoals(d).length}</span>`) : "",
      hasLoose(d) ? btn("loose", `${esc(T("board.pick.loose"))} <span class="n">${d.cards.filter((x) => !x.goal).length}</span>`) : "",
      d.issues.length ? btn("issues", `${esc(T("board.pick.issues"))} <span class="n">${d.issues.length}</span>${waitIssue ? `<span class="pill warn">${esc(NS(ST.PENDING_RULING))} ${waitIssue}</span>` : ""}`) : "",
      btn("dec", `${esc(T("board.pick.decisions"))} <span class="n">${d.decisions.length}</span>`),
    ].join("");
    return `<nav class="picker"><div class="pkg"><span class="pkh">${esc(T("board.pick.goals"))}</span>${gb || `<span class="empty">${esc(T("board.pick.no_goals"))}</span>`}</div><div class="pkg"><span class="pkh">${esc(T("board.pick.other"))}</span>${other}</div></nav>`;
  }


  // ---------- 目标主页：要干什么、现在、主干；只用视图模型和卡片里已有的数据 ----------
  const mainTab = {}, openSteps = new Set();
  // 卡头、流转表：服务端给代码，这里按语言显示
  function headLabel(k) { const s = T("board.head." + k); return s === "board.head." + k ? k : s; }
  function headValue(k, v) { return ["executor", "reviewer", "holder"].includes(k) ? WHO(v) || "—" : k === "state" ? NS(v) : v; }
  function flowNote(r, html) {  // 流转一行的说明：边（加结果）· 说明；note 已由服务端转成 HTML
    const e = r.edge ? NE(r.edge) + (r.result ? T("sep.colon") + NR(r.result) : "") : "";
    return [html ? esc(e) : e, html ? r.note || "" : strip(r.note || "")].filter(Boolean).join(" · ");
  }
  const fieldOf = (g, code) => { const f = (g.fields || []).find((x) => x.code === code); return f ? f.v : ""; };  // 字段按代码找：中英两种写法的卡片都认
  const plain = (h) => String(h || "").replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#(?:x27|39);/g, "'").replace(/&amp;/g, "&");
  const firstSentence = (s, n = 64) => { const x = String(s || "").split(/[。；\n]/)[0]; return x.length > n ? x.slice(0, n) + "…" : x; };
  const criteria = (g) => plain(fieldOf(g, "criteria")).split(/(?=[①②③④⑤⑥⑦⑧⑨⑩])/).map((x) => x.trim()).filter(Boolean);
  const goalTasksV = (d, gid) => d.view.tasks.filter((t) => t.goal === gid && t.state !== V.State.CANCELLED).slice()
    .sort((a, b) => (a.stage - b.stage) || a.id.localeCompare(b.id, undefined, {numeric: true}));
  const deliverNote = (d, id) => {
    const c = d.cards.find((x) => x.id === id);
    const r = c && (c.flow || []).filter((f) => f.edge === V.Edge.DELIVER).pop();
    return r ? r.note || "" : "";
  };
  const DOING = {test: (s) => [ST.IN_PROGRESS, ST.IN_REVIEW, ST.DISPATCHED, ST.BLOCKED, ST.PAUSED].includes(s)};
  const whoName = (x) => x === V.Seat.OWNER ? T("board.you") : (x ? WHO(x) : "—");
  function nowCells(d, g) {
    const ts = goalTasksV(d, g.id);
    const doing = ts.filter((t) => DOING.test(t.state));
    const next = ts.find((t) => [ST.APPROVED, ST.PLANNED].includes(t.state));
    const mine = ts.filter((t) => t.holder === V.Seat.OWNER);
    const cell = (cls, lab, main, sub) => `<div class="ncell ${cls}"><div class="nlab">${lab}</div><b>${main}</b><span class="nsub">${sub}</span></div>`;
    const a = doing.length ? cell("doing", esc(T("board.cell.doing")), esc(doing.map((x) => x.title).join(T("sep.list"))), esc(doing.map((x) => `${whoName(x.holder)} · ${NS(x.state)}`).join(T("sep.list"))))
      : cell("", esc(T("board.cell.doing")), esc(T("board.cell.nothing_running")), "");
    const b = cell("", esc(T("board.cell.next")), next ? esc(next.title) : esc(T("board.cell.nothing_next")), next ? esc(whoName(next.planned_executor || next.executor)) : "");
    const decide = g.alert.pend || mine.length, qs = g.questions || [];
    const c = decide || qs.length
      ? cell("need", esc(T("board.cell.need")), esc([decide ? T("board.cell.decide", {n: decide}) : "", qs.length ? T("board.cell.questions", {n: qs.length}) : ""].filter(Boolean).join(T("board.comma"))),
        esc(qs.length ? firstSentence(plain(qs[0]), 40) : T("board.cell.see_above", {s: I18N.sections.decisions})))
      : cell("", esc(T("board.cell.need")), esc(T("board.cell.not_now")), "");
    return `<div class="ncells">${a}${b}${c}</div>`;
  }
  function trunk(d, g) {
    const ts = goalTasksV(d, g.id);
    const lastAppr = Math.max(0, ...g.vg.events.filter((e) => e.edge === V.Edge.APPROVE).map((e) => e.project_seq));
    const fbs = g.vg.events.filter((e) => e.basis && e.project_seq > lastAppr && ([V.Edge.REJECT, V.Edge.RETURN].includes(e.edge) || e.edge === V.Edge.CHANGE))
      .filter((e, i, a) => a.findIndex((x) => x.basis === e.basis) === i);  // 同一句原话可能记了几条事件，只显示一次
    const fbFor = {}, tail = [];
    fbs.forEach((e) => {
      let best = null, gap = 6;
      ts.forEach((t) => { if (t.request_seq != null && Math.abs(t.request_seq - e.project_seq) < gap) { best = t.id; gap = Math.abs(t.request_seq - e.project_seq); } });
      if (best) (fbFor[best] = fbFor[best] || []).push(e); else tail.push(e);
    });
    const fbRow = (e) => `<li class="tfb"><span class="tfl">${esc([V.Edge.REJECT, V.Edge.RETURN].includes(e.edge) ? T("board.trunk.you_returned") : T("board.trunk.you_asked"))} ${esc(e.time.slice(5, 16).replace("T", " "))}</span> “${esc(e.basis)}”<div class="nsub">${esc(e.note)}</div></li>`;
    const rows = [];
    let stage = null;
    ts.forEach((t) => {
      const s = g.vg.stages.find((x) => x.order === t.stage);
      (fbFor[t.id] || []).forEach((e) => rows.push(fbRow(e)));
      if (t.stage !== stage) { stage = t.stage; rows.push(`<li class="tstage">${esc(T("board.stage_n", {n: stage}))} · ${esc(s ? s.name : "")}</li>`); }
      const st = t.state === V.State.PASSED ? "done" : DOING.test(t.state) ? "doing" : "todo";
      const c = t.content || {};
      const note = st === "done" ? firstSentence(deliverNote(d, t.id) || t.conclusion) : firstSentence(c.purpose);
      const k = (a, b) => b ? `<span class="k">${a}</span><span>${esc(b)}</span>` : "";
      rows.push(`<li class="tstep ${st}"><span class="tdot"></span><details data-step="${esc(t.id)}" ${openSteps.has(t.id) ? "open" : ""}><summary>
        <div class="ttl"><span>${esc(t.title)}</span>${st === "doing" ? statusPill(t.state) : t.rework_count ? `<span class="pill warn">${esc(T("board.rework_n", {n: t.rework_count}))}</span>` : ""}<span class="twho">${esc(whoName(t.executor || t.planned_executor))} · ${esc(T("board.reviews", {who: whoName(t.reviewer || t.planned_reviewer)}))}</span></div>
        <div class="tres">${esc(note)}</div></summary>
        <div class="fields tmore">${k(esc(N("kind", V.Kind.TASK)), t.id)}${k(I18N.fields.purpose, c.purpose)}${k(I18N.fields.deliverables, c.deliverables)}${k(I18N.fields.acceptance, c.acceptance)}${k(esc(T("board.conclusion")), t.conclusion)}</div>
        <span class="tlink" data-task="${esc(t.id)}">${esc(T("board.open_card"))}</span></details></li>`);
    });
    tail.forEach((e) => rows.push(fbRow(e)));
    return `<ol class="trunk">${rows.join("")}</ol>`;
  }
  function goalMain(d, g) {
    const vg = d.view.goals.find((x) => x.id === g.id);
    const gg = {...g, vg};
    const cr = criteria(g), want = plain(fieldOf(g, "want"));
    const tab = mainTab[g.id] || "flow";  // 选中目标默认看流程图（G047）
    const tb = (k, n) => `<button class="gt ${tab === k ? "on" : ""}" data-maintab="${esc(g.id)}:${k}">${n}</button>`;
    const inner = tab === "trunk" ? trunk(d, gg)
      : tab === "flow" ? `<div class="gfh"><span class="tlink gdet" data-gdet="${esc(g.id)}">${esc(openGoal === g.id ? T("board.plan_hide") : T("board.plan_show"))}</span></div>${openGoal === g.id ? renderGoalDetail(g, goalRuns(d, g).filter((r) => r.override)) : ""}` + (ARCHIVE ? "" : renderApproval(d, g.id)) + renderRel(d, g.id) + renderSeq(d, g.id) + goalIssues(d, g.id)
      : renderLower(d, (gx) => gx === g.id);
    const side = `<aside class="gside"><div class="sh">${esc(I18N.fields.criteria)} ${cr.length ? `· ${esc(T("board.n_lines", {n: cr.length}))}` : ""}</div>${cr.length ? `<ul class="crit">${cr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<div class="empty">${esc(T("board.not_written"))}</div>`}
      <div class="sh" style="margin-top:14px">${esc(T("board.docs"))}</div>${goalFiles(d, g) || `<div class="nsub">${esc(T("board.no_docs"))}</div>`}</aside>`;
    return `<p class="gwant">${want ? esc(want) : `<span class="nsub">${esc(T("board.no_want"))}</span>`}</p>${isIn(g.state, ST.DONE, ST.CANCELLED) ? "" : nowCells(d, g)}
      <div class="gcols"><div class="gleft"><div class="gtabs">${tb("trunk", esc(T("board.tab.trunk")))}${tb("flow", esc(T("board.tab.flow")))}${tb("low", esc(T("board.tab.low")))}</div>${inner}</div>${side}</div>`;
  }
  // 选中一个目标：卡头一行现状，时序图（旧项目是泳道），下面是它的任务和派活
  function renderGoalPane(d, gid) {
    const g = allGoals(d).find((x) => x.id === gid);
    const done = isIn(g.state, ST.DONE, ST.CANCELLED);
    let body = d.view ? goalMain(d, g) : `<div class="note">${esc(T("board.old_structure"))}</div>`;
    const meta = `${stageDots(g)}${g.runs.length ? ` · ${esc(T("board.runs_n", {n: g.runs.length}))} · ${tok(sumTok(g.runs)).split(" ·")[0]}` : ""}`;
    return card(`<span class="tid">${esc(g.id)}</span> ${esc(g.title)} ${statusPill(g.state || "—")}`, body, {meta, cls: "pane"});
  }
  // 框架的批准面板：看完图就能批准、提意见、退回；批准绑定看到的那一版
  const draftBox = (key, ph) => `<textarea class="adraft" data-draft="${esc(key)}" rows="2" placeholder="${esc(ph)}">${esc(drafts[key] || "")}</textarea>`;
  function commentList(list) {
    return (list || []).length ? `<ul class="plain acomm">${list.map((c) => `<li><span class="tid">${esc(c.object || "")}</span> ${esc(c.note)} <span class="meta">${esc(hm(c.time))}</span></li>`).join("")}</ul>` : "";
  }
  function renderApproval(d, gid) {
    const g = seqGroup(d, gid);
    if (!g || ARCHIVE) return "";
    const state = g.state;
    const open = (g.comments || []).length ? `<div class="alabel">${esc(T("board.appr.comments"))}</div>${commentList(g.comments)}` : "";
    if (state === V.State.DRAFT) {
      const dv = esc(g.plan_version ? T("board.appr.drafting", {v: g.plan_version}) : T("board.appr.no_plan"));
      return `<div class="appr draft"><div class="ah">${dv}</div>${open}</div>`;
    }
    if (state !== V.State.PENDING_APPROVAL) return open ? `<div class="appr">${open}</div>` : "";
    const dec = (d.view.decisions || []).find((x) => x.id === gid) || {};
    const short = (x) => x.replace(/^G\d+-/, "");
    const stat = [esc(T("board.appr.cards", {n: dec.task_count || 0})), (dec.people || []).length ? esc(T("board.appr.executors", {who: dec.people.map(WHO).join(T("sep.list"))})) : "",
      (dec.owner_tasks || []).length ? `<b class="me">${esc(T("board.appr.owner_tasks", {ids: dec.owner_tasks.map(short).join(T("sep.list"))}))}</b>` : esc(T("board.appr.no_owner_tasks"))].filter(Boolean).join(" · ");
    const changed = (g.round_changes || []).length && g.plan_version > 1 ? `<div class="alabel">${esc(T("board.appr.changed"))}</div><ul class="plain achg">${g.round_changes.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    return `<div class="appr"><div class="ah"><span class="pill run">${esc(T("board.appr.waiting"))}</span> <b>${esc(T("board.appr.version", {v: g.plan_version || 0}))}</b> · ${stat}</div>
      ${dec.note ? `<div class="adesc">${esc(dec.note)}</div>` : ""}${dec.recommendation ? `<div class="adesc"><span class="meta">${esc(T("board.pend.recommended"))}</span> ${esc(dec.recommendation)}</div>` : ""}
      ${changed}${open}${draftBox("goal:" + gid, T("board.appr.placeholder"))}
      <div class="aacts"><button class="act primary" type="button" data-goalact="approve" data-goalid="${esc(gid)}" data-version="${g.plan_version || 0}">${esc(T("board.appr.approve"))}</button>
      <button class="act" type="button" data-goalact="comment" data-goalid="${esc(gid)}" data-key="goal:${esc(gid)}">${esc(T("board.appr.comment"))}</button>
      <button class="act" type="button" data-goalact="return" data-goalid="${esc(gid)}" data-key="goal:${esc(gid)}">${esc(T("board.appr.return"))}</button>
      ${apprMsg ? `<span class="aerr">${esc(apprMsg)}</span>` : ""}</div></div>`;
  }
  // 时序图下面的任务卡：内容来自卡片「交接」，可以针对这个任务提意见
  function renderTaskCard(d, g, tid) {
    const t = d.view.tasks.find((x) => x.id === tid);
    if (!t) return "";
    const order = ["purpose", "constraints", "inputs", "deliverables", "acceptance", "authority", "escalate_when", "role", "alternatives"];
    const c = t.content || {};
    const rows = order.filter((k) => c[k]).map((k) => `<span class="k">${esc(I18N.fields[k] || k)}</span><span>${esc(c[k]).replace(/\n/g, "<br>")}</span>`).join("");
    const who = esc(T("board.card.does", {who: WHO(t.planned_executor || t.executor) || "—"})) + (t.executor && t.planned_executor && t.executor !== t.planned_executor ? esc(T("board.card.actual", {who: WHO(t.executor)})) : "") + " · " + esc(T("board.reviews", {who: WHO(t.reviewer || t.planned_reviewer || V.Seat.LEAD)}));
    const live = !ARCHIVE && !isIn(g.state, ST.DONE, ST.CANCELLED);
    const key = "task:" + tid;
    const said = (t.comments || []).length ? `<div class="alabel">${esc(T("board.card.your_comments"))}</div>${commentList(t.comments.map((x) => ({...x, object: ""})))}` : "";
    return `<div class="ldet tcard"><div><b>${esc(tid)} ${esc(t.title)}</b> ${statusPill(t.state)} <span class="meta">${who}</span></div>
      ${rows ? `<div class="fields">${rows}</div>` : `<div class="note">${esc(T("board.card.empty"))}</div>`}${said}
      ${live ? `${draftBox(key, T("board.card.placeholder"))}<div class="aacts"><button class="act" type="button" data-goalact="comment" data-goalid="${esc(g.id)}" data-tid="${esc(tid)}" data-key="${esc(key)}">${esc(T("board.appr.comment"))}</button>${apprMsg ? `<span class="aerr">${esc(apprMsg)}</span>` : ""}</div>` : ""}</div>`;
  }
  // 目标面板里挂着的议题：一行一个，点进朝会页
  function goalIssues(d, gid) {
    const list = d.issues.filter((i) => i.flow && i.goal === gid);
    if (!list.length) return "";
    return `<div class="gissues"><span class="meta">${esc(I18N.sections.issues)}</span>${list.map((i) => `<a class="girow" href="${U(`/p/${esc(id)}/meet/${esc(i.id)}`)}"><span class="tid">${esc(i.id)}</span> ${esc(i.title)} ${issuePill(i.thinking.length ? ST.DISCUSSING : i.stage)}<span class="meta">${esc(N("issue_type", i.type))}${i.summary ? " · " + esc(i.summary.note) : ""}</span></a>`).join("")}</div>`;
  }
  // 目标目录里的文档：点开用本机程序打开；归档后文件在 归档/目标/ 下，路径由视图模型给
  function goalFiles(d, g) {
    const f = g.files || {};
    const paths = ["proposal", "questions", "discussion"].filter((k) => f[k]).map((k) => f[k]).concat(f.other || []);
    const links = paths.map((p) => `<a href="${esc(fileHref(`${d.root}/${p}`))}">${esc(p.split("/").pop())}</a>`);
    return links.length ? `<span class="gfiles">${links.join(" · ")}</span>` : "";
  }
  function renderIdeasPane(d) {
    const list = ideaGoals(d);
    const groups = IDEA_STAGES.map((st) => {
      const rows = list.filter((g) => g.idea === st).sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}));
      const body = rows.length ? rows.map((g) => `<div class="girow"><span class="tid">${esc(g.id)}</span> <span class="igt"><b>${esc(g.title)}</b> ${g.state === V.State.DRAFT ? "" : statusPill(g.state)}${(g.questions || []).length ? `<span class="pill warn">${esc(T("board.ideas.questions", {n: g.questions.length}))}</span>` : ""}<span class="psub">${esc(plain(fieldOf(g, "want"))) || esc(T("board.no_want"))}</span></span>
        ${goalFiles(d, g) || `<span class="meta">${esc(T("board.no_docs"))}</span>`}</div>`).join("") : `<div class="empty">${esc(T("block.none_inline"))}</div>`;
      return `<div class="gissues"><span class="meta">${esc(N("draft_stage", st))} ${rows.length}</span>${body}</div>`;
    }).join("");
    return card(esc(T("board.pick.ideas")), groups, {meta: esc(T("board.ideas.meta")), cls: "pane"});
  }
  function renderLoosePane(d) {
    const body = (d.view && d.view.loose ? renderRel(d, "—") + renderSeq(d, "—") : "") + renderLower(d, (gx) => gx === "none");
    return card(esc(T("board.pick.loose")), body, {meta: esc(T("board.loose.meta")), cls: "pane"});
  }
  function renderDecPane(d) {
    const body = d.decisions.length ? `<ul class="plain">${d.decisions.map((x) => `<li>${x}</li>`).join("")}</ul>` : `<div class="empty">${esc(T("board.none_yet"))}</div>`;
    return card(esc(I18N.sections.active_decisions), body, {cls: "pane"});
  }
  // 主区下半：任务和派活两个标签页，只列属于当前选中项的
  function renderLower(d, inScope) {
    const cards = d.cards.filter((t) => inScope(t.goal || "none"));
    const runs = d.runs.filter((r) => inScope(goalOfTask(d, r.task)))
      .sort((a, b) => String(b.started || "").localeCompare(String(a.started || "")));
    const tabs = [["tasks", esc(T("board.tab.tasks", {n: cards.length}))], ["runs", esc(T("board.tab.runs", {n: runs.length}))]]
      .map(([k, t]) => `<button class="tab ${goalTab === k ? "on" : ""}" data-gtab="${k}">${t}</button>`).join("");
    const body = goalTab === "runs" ? (runs.length ? runsTable(runs, true) : `<div class="empty">${esc(T("board.no_runs"))}</div>`) : taskList(d, cards);
    return `<div class="lower"><div class="card-head"><h2><span class="tabs">${tabs}</span></h2>${goalTab === "runs" && runs.length ? `<span class="meta">${esc(T("board.runs_hint"))}</span>` : ""}</div>${body}</div>`;
  }

  // ---------- 泳道流程：按席位分道（总裁 / 总管 / 执行 / 验收），执行按并行任务分子道，从上到下是时间 ----------
  let openNode = null;
  // 旧结构项目（没有事件、卡片手写流转表）：经办人是手写的名字，只能按原文认总裁和总管
  const LEAD = /^(claude|总管|lead)/i, BOSS = /^(总裁|用户|本人|owner)/i;
  const whoText = (w) => (Array.isArray(w) ? w.map(WHO).join(T("sep.list")) : w || "");  // 阶段人选：新结构是代码列表，旧结构是原文
  function laneOf(row, verifier) {
    const who = strip(row.from || "").trim();
    if (BOSS.test(who)) return "boss";
    if (LEAD.test(who)) return "lead";
    return ([ST.PASSED, ST.FAILED, V.Result.PASS, V.Result.NEEDS_MORE, V.Result.FAIL].includes(row.state)) && verifier ? "check" : "exec";
  }
  function nodeCls(state, last) {
    if (isIn(state, ST.BLOCKED, V.Result.NEEDS_MORE, ST.FAILED)) return "bad";
    if (last && !isIn(state, ST.PASSED)) return "now";
    return "ok";
  }
  function goalLanes(d, g) {
    const nodes = [], edges = [], used = new Set();
    const put = (lane, sub, row) => { while (used.has(lane + sub + ":" + row)) row++; used.add(lane + sub + ":" + row); return row; };
    const add = (n) => { n.i = nodes.length; nodes.push(n); return n.i; };
    const approved = !isIn(g.state, ST.PENDING_APPROVAL);
    let row = 0;
    const draft = add({lane: "lead", sub: 0, row: put("lead", 0, row++), label: T("board.lane.draft"), cls: "ok", info: T("board.lane.draft_info", {id: g.id})});
    const appr = add({lane: "boss", sub: 0, row: put("boss", 0, row++), label: approved ? N("pending", V.Pending.APPROVE_PLAN) : NS(ST.PENDING_APPROVAL), cls: approved ? "ok" : "now",
      info: approved ? T("board.lane.approved_info", {id: g.id, basis: strip(g.head.basis || "")}) : T("board.lane.wait_info")});
    edges.push([draft, appr]);
    let ends = [appr], maxSub = 1, hasCheck = false;
    const runsOf = (id) => d.runs.filter((r) => r.task === id);
    g.stages.forEach((s) => {
      const tasks = s.taskInfo;
      const start = row, newEnds = [];
      if (!tasks.length) {
        const lane = /验收|review/i.test(s.seat) && !LEAD.test(whoText(s.who)) ? "check" : /汇报|report/i.test(s.seat) || LEAD.test(whoText(s.who)) ? "lead" : "exec";
        if (lane === "check") hasCheck = true;
        const prevDone = g.stages.filter((x) => x.no < s.no).every((x) => x.status === V.StageStatus.PASSED);
        const n = add({lane, sub: 0, row: put(lane, 0, start), label: `${circ(s.no)} ${s.seat}`, cls: s.status === V.StageStatus.PASSED ? "ok" : prevDone && approved ? "now" : "todo", stage: s,
          info: T("board.lane.stage_info", {no: circ(s.no), name: s.seat, who: whoText(s.who) || "—", output: strip(s.output)})});
        ends.forEach((e) => edges.push([e, n]));
        ends = [n]; row = nodes[n].row + 1; return;
      }
      maxSub = Math.max(maxSub, tasks.length);
      tasks.forEach((t, k) => {
        const flow = t.flow || [];
        const verifier = !!strip(flow.map((r) => r.from || "").join(""));
        let r0 = start, prev = null;
        const rows = flow.length ? flow : [{state: t.state, from: t.exec, note: ""}];
        rows.forEach((fr, idx) => {
          const st = NS(strip(fr.state || ""));
          const lane = laneOf(fr, verifier);
          if (lane === "check") hasCheck = true;
          const sub = lane === "exec" ? k : 0;
          const rr = put(lane, sub, r0);
          const n = add({lane, sub, row: rr, label: `${t.id.replace(/^G\d+-/, "")} ${st.replace(/[：:].*/, "")}`.slice(0, 14), cls: nodeCls(fr.state, idx === rows.length - 1), last: idx === rows.length - 1,
            task: t.id, holder: strip(fr.to || ""), state: fr.state, info: `${strip(fr.time || "")} ${t.id} · ${WHO(strip(fr.from || ""))} → ${WHO(strip(fr.to || ""))} · ${st}${T("sep.colon")}${strip(fr.note || "")}`});
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
    const wait = ((g.head.depends_on || "").match(/G\d+/g) || []).filter((x) => { const o = d.goals.find((q) => q.id === x); return o && !isIn(o.state, ST.DONE); });
    const B = (x) => `<b>${esc(x)}</b>`;
    if (isIn(g.state, ST.PAUSED)) return esc(T("board.nl.paused"));
    if (isIn(g.state, ST.PENDING_APPROVAL)) return T("board.nl.wait_owner_plan", {who: B(WHO(V.Seat.OWNER))}) + esc(wait.length ? T("board.nl.and_wait", {ids: wait.join(T("sep.list"))}) : T("board.nl.no_dispatch"));
    if (wait.length) return T("board.nl.wait_deps", {ids: B(wait.join(T("sep.list")))});
    const cur = goalLanes(d, g).nodes.filter((n) => n.cls === "now" || (n.last && n.cls === "bad"));
    if (!cur.length) return T("board.nl.all_done_owner", {who: B(WHO(V.Seat.OWNER))});
    return cur.map((n) => {
      if (n.stage) return T("board.nl.stage_no_task", {who: B(whoText(n.stage.who) || WHO(V.Seat.LEAD)), no: circ(n.stage.no), name: esc(n.stage.seat)});
      const who = B(WHO(n.holder) || "—"), id = esc(n.task);
      const act = isIn(n.state, ST.BLOCKED) ? "blocked" : isIn(n.state, V.Result.NEEDS_MORE) ? "rework"
        : isIn(n.state, ST.IN_REVIEW) ? "review" : isIn(n.state, ST.DISPATCHED, ST.IN_PROGRESS) ? "work" : "push";
      const live = d.runs.filter((r) => r.task === n.task && r.status === V.RunStatus.RUNNING).pop();
      return T("board.nl.wait_" + act, {who, id}) + (live ? ` · <span class="dot"></span>${esc(T("board.ran_for", {who: live.member, t: dur(secs(live.started))}))}` : "");
    }).join(T("sep.clause"));
  }

  function renderLanes(d, g) {
    const L = goalLanes(d, g), RH = 34, TOP = 40, NH = 24, LEFT = 8;
    const cols = [{lane: "boss", name: WHO(V.Seat.OWNER), w: 120}, {lane: "lead", name: WHO(V.Seat.LEAD), w: 130}];
    for (let k = 0; k < L.maxSub; k++) cols.push({lane: "exec", sub: k, name: k ? "" : N("seat", V.Seat.EXECUTOR), w: 170});
    if (L.hasCheck) cols.push({lane: "check", name: N("role", V.Role.THIRD_PARTY), w: 150});
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
    let det = `<div class="note">${esc(T("board.lane.hint"))}</div>`;
    if (openNode && openNode.startsWith(g.id + ":")) {
      const n = L.nodes[+openNode.split(":")[1]];
      if (n) {
        det = `<div class="ldet">${esc(n.info)}`;
        const rs = n.task ? L.runsOf(n.task) : [];
        if (rs.length) det += `<div class="meta" style="margin-top:6px">${esc(T("board.lane.runs_of", {id: n.task}))}${rs.map((r) => `${esc(r.run)} ${esc(r.member)} ${dur(r.ended ? (new Date(r.ended) - new Date(r.started)) / 1000 : secs(r.started))} · ${tok(r.tokens)}`).join("；")}</div>`;
        det += "</div>";
      }
    }
    return `<div class="lanewrap">${s}</div>${det}`;
  }

  // ---------- 时序图（新结构项目）：只画 flow.py 的视图模型，不读事件、不推断、不自行排序 ----------
  // 生命线顺序、主干和支线、持有期都由视图模型给定；从上到下按项目序每条事件一格，长间隔画成折断
  let openSeq = null;
  let hiTask = null;
  const closedStages = new Set();  // 已通过的阶段默认展开，这里记手动折叠的（G047）
  const TASK_COLORS = ["var(--accent)", "var(--green)", "var(--amber)", "#8e5bd9", "#d9568e", "#3aa0c8"];
  const seqGroup = (d, gid) => (gid === "—" ? d.view.loose : d.view.goals.find((x) => x.id === gid));
  function gapText(ms) {
    const h = ms / 3600e3;
    return h >= 48 ? `⋯ ${T("board.gap.days", {n: Math.round(h / 24)})}` : `⋯ ${T("board.gap.hours", {n: Math.round(h)})}`;
  }
  function renderSeq(d, gid) {
    const g = seqGroup(d, gid);
    if (!g) return "";
    const tasks = d.view.tasks.filter((t) => (gid === "—" ? !t.goal : t.goal === gid));
    const color = {};
    tasks.forEach((t, i) => { color[t.id] = TASK_COLORS[i % TASK_COLORS.length]; });
    const stages = g.stages || [];
    const folded = new Set(ARCHIVE ? [] : stages.filter((s) => s.state === V.State.PASSED && closedStages.has(gid + ":" + s.order)).map((s) => s.order));  // 归档页要看全过程，不折叠
    const rows = [], seenFold = new Set();
    let prevT = null;
    // 挂在这个目标上的议题：在它开始的位置插一行折叠框，点开去朝会页（发言不画进时序图）
    const issues = gid === "—" ? [] : (d.view.issues || []).filter((i) => i.goal === gid).slice().sort((a, b) => a.start_seq - b.start_seq);
    const flushIssues = (upto) => { while (issues.length && issues[0].start_seq < upto) rows.push({issue: issues.shift()}); };
    const S = g.structure;
    const short = (x) => x.replace(/^G\d+-/, "");
    if (S) {
      // 结构为主：按「阶段 → 任务 → 派发、交付、确认」排，每一步的位置不变；发生了就地变实线加时间
      const evBy = {};
      g.events.forEach((e) => { evBy[e.project_seq] = e; });
      if (S.record.length) rows.push({rec: S.record.length, open: openRecord.has(gid)});
      if (openRecord.has(gid)) S.record.forEach((q) => { if (evBy[q]) rows.push({e: evBy[q]}); });
      flushIssues(Infinity);
      const stepRow = (x, t, no) => {
        const tid = t ? t.id : null;
        if (x.planned) rows.push({p: {...x, layer: t ? V.Kind.TASK : V.Kind.GOAL, stage: no, object: tid, title: t ? t.title : ""}, stage: no, task: tid});
        else if (evBy[x.project_seq]) rows.push({e: evBy[x.project_seq], also: x.includes || [], stage: no, task: tid});
      };
      S.head.forEach((x) => stepRow(x, null, null));
      S.stages.forEach((st) => {
        (st.before || []).forEach((x) => stepRow(x, null, null));  // 目标层事件：插在紧随其后的阶段之前
        if (folded.has(st.order)) {
          st.tasks.forEach((t) => (t.before || []).forEach((x) => stepRow(x, null, null)));  // 折叠的阶段不吞掉这些事件
          rows.push({fold: stages.find((x) => x.order === st.order), n: g.events.filter((x) => x.layer === V.Kind.TASK && x.stage === st.order && !S.record.includes(x.project_seq)).length});
          return;
        }
        rows.push({shead: st, stage: st.order});
        if (st.needs_split) rows.push({p: {edge: "needs_split", stage: st.order, name: st.name, people: []}, stage: st.order});
        st.tasks.forEach((t) => {
          (t.before || []).forEach((x) => stepRow(x, null, null));
          rows.push({head: t, stage: st.order, task: t.id});
          t.steps.forEach((x) => stepRow(x, t, st.order));
        });
      });
      S.tail.forEach((x) => stepRow(x, null, null));
    } else g.events.forEach((e) => {
      flushIssues(e.project_seq);
      const t = new Date(e.time).getTime();
      if (prevT != null && t - prevT > 6 * 3600e3) {
        const last = rows[rows.length - 1];
        if (last && last.gap) last.gap += t - prevT; else rows.push({gap: t - prevT});  // 折叠掉的行之间的间隔合成一处
      }
      prevT = t;
      const st = e.layer === V.Kind.TASK ? e.stage : null;
      if (st != null && folded.has(st)) {
        if (!seenFold.has(st)) {
          seenFold.add(st);
          rows.push({fold: stages.find((s) => s.order === st), n: g.events.filter((x) => x.layer === V.Kind.TASK && x.stage === st).length});
        }
        return;
      }
      rows.push({e});
    });
    flushIssues(Infinity);
    const hiDeps = new Set();
    if (S && hiTask) S.stages.forEach((st) => st.tasks.forEach((t) => { if (t.id === hiTask) t.needs.forEach((x) => hiDeps.add(x)); }));
    const dimFor = (tid) => (hiTask && tid !== hiTask && !hiDeps.has(tid) ? "dim" : "");
    const P = g.participants, TIMEW = S ? 84 : 62, TOP = 44, RH = 30, GH = 18, FH = 26;
    const avail = (app.clientWidth || 1000) - 56 - TIMEW;
    const CW = Math.max(110, Math.min(190, avail / Math.max(1, P.length)));
    const W = TIMEW + CW * P.length + 8;
    const col = {};
    P.forEach((p, i) => { col[p.name] = TIMEW + CW * i + CW / 2; });
    let y = TOP + 6;
    rows.forEach((r) => { const h = r.gap ? GH : (r.fold || r.issue || r.rec || r.lab || r.shead || r.head || (r.p && r.p.edge === "needs_split")) ? FH : RH; r.y = y + h / 2; y += h; });
    const H = y + 10;
    const rowOf = {};
    rows.forEach((r) => { if (r.e) { rowOf[r.e.project_seq] = r; (r.also || []).forEach((q) => { rowOf[q] = r; }); } });
    let s = `<svg class="seq" viewBox="0 0 ${W} ${H}" style="max-width:${W}px"><defs><marker id="sa" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5"/></marker></defs>`;
    // 阶段框：圈出该阶段任务事件所在的行
    stages.forEach((st) => {
      if (folded.has(st.order)) return;
      // 建卡往往一次建齐，框只圈派发之后的事件，否则并行和先后阶段的框会叠在一起
      const ys = rows.filter((r) => (S ? r.stage === st.order : (r.e && r.e.layer === V.Kind.TASK && r.e.stage === st.order && r.e.edge !== V.Edge.CREATE) || (r.p && r.p.stage === st.order))).map((r) => r.y);
      if (!ys.length) return;
      const y1 = Math.min(...ys) - (S ? FH / 2 : RH / 2 - 2), y2 = Math.max(...ys) + RH / 2 - 2;
      s += `<rect x="${TIMEW - 4}" y="${y1}" width="${W - TIMEW}" height="${y2 - y1}" rx="6" class="sbox"/>`;
      if (!S) s += `<text x="${W - 8}" y="${y1 + 11}" class="slab">${esc(T("board.stage_n", {n: circ(st.order)}))} ${esc(st.name)} · ${esc(NS(st.state))}${st.invalid ? esc(T("block.stages.invalid")) : ""}</text>`;
    });
    // 生命线和表头
    P.forEach((p) => {
      const x = col[p.name];
      s += `<line x1="${x}" y1="${TOP}" x2="${x}" y2="${H - 6}" class="life ${p.appeared ? "" : "off"}"/>`;
      s += `<rect x="${x - CW / 2 + 8}" y="6" width="${CW - 16}" height="26" rx="7" class="phead ${p.appeared ? "" : "off"} ${p.planned ? "" : "extra"}"/><text x="${x}" y="19" class="pname">${esc(WHO(p.name))}${p.appeared ? "" : esc(T("board.seq.absent"))}</text>`;
    });
    // 持有期：生命线上的粗条
    tasks.forEach((t, k) => {
      (t.holds || []).forEach((h) => {
        const firstPlan = rows.find((r) => r.p);
        const lastMine = rows.filter((r) => r.task === t.id && r.e).pop();
        const a = rowOf[h.start_seq], b = h.end_seq != null ? rowOf[h.end_seq] : {y: S ? (lastMine ? lastMine.y + RH / 2 : a ? a.y : 0) : firstPlan ? firstPlan.y - RH / 2 : H - 8};  // 还在手里的画到实际事件的末尾
        if (!a || !b || col[h.who] == null) return;
        const off = ((k % 3) - 1) * 7;
        s += `<rect x="${col[h.who] - 3 + off}" y="${a.y}" width="6" height="${Math.max(4, b.y - a.y)}" rx="3" class="hold ${hiTask && hiTask !== t.id ? "dim" : ""}" style="fill:${color[t.id]}"/>`;
      });
    });
    // 行：箭头、折叠的阶段、折断
    rows.forEach((r) => {
      if (r.gap) { s += `<text x="${TIMEW + (W - TIMEW) / 2}" y="${r.y}" class="gap">${gapText(r.gap)}</text>`; return; }
      if (r.rec) {
        s += `<g class="fold" data-record="${esc(gid)}"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">${esc(T(r.open ? "board.seq.record_open" : "board.seq.record", {n: r.rec}))}</text></g>`;
        return;
      }
      if (r.lab) { s += `<text x="${TIMEW + 6}" y="${r.y}" class="shd">${esc(r.lab)}</text>`; return; }
      if (r.shead) {
        const st = r.shead;
        const par = st.parallel_with.length ? ` · ${T("board.seq.parallel", {ids: st.parallel_with.map(circ).join(T("sep.list"))})}` : "";
        const canFold = !ARCHIVE && st.state === V.State.PASSED;  // 已通过的阶段点标题收起
        const txt = `<text x="${TIMEW + 6}" y="${r.y}" class="shd">${esc(T("board.stage_n", {n: circ(st.order)}))} ${esc(st.name)}<tspan class="shm"> · ${esc(NS(st.state))}${st.invalid ? esc(T("block.stages.invalid")) : ""}${esc(par)}${canFold ? esc(T("board.seq.fold_stage")) : ""}</tspan></text>`;
        s += canFold ? `<g class="shfold" data-fold="${esc(gid + ":" + st.order)}">${txt}</g>` : txt;
        return;
      }
      if (r.head) {
        const t = r.head, on = openCard === t.id;
        const doer = WHO(t.executor || t.planned_executor) || "—";
        const swap = t.reassigned ? T("board.seq.planned_was", {who: WHO(t.planned_executor)}) : "";
        const real = tasks.find((x) => x.id === t.id) || {};
        const need = t.needs.length ? ` · ${T("board.seq.needs", {ids: t.needs.map(short).join(T("sep.list"))})}` : "";
        const tag = (t.owner_involved ? `<tspan class="thme"> · ${esc(T("board.seq.owner_reviews"))}</tspan>` : "") + (t.added_after_approval ? `<tspan class="thme"> · ${esc(T("board.seq.added_after"))}</tspan>` : "");
        s += `<g class="thead ${on ? "on" : ""} ${dimFor(t.id)}" data-taskcard="${esc(t.id)}"><rect x="${TIMEW + 2}" y="${r.y - FH / 2 + 2}" width="${W - TIMEW - 12}" height="${FH - 4}" rx="5"/><text x="${TIMEW + 10}" y="${r.y}" class="tht">${esc(short(t.id))} ${esc(t.title)}<tspan class="thm"> · ${esc(T("board.seq.who", {doer: doer + swap, reviewer: WHO(real.reviewer || t.planned_reviewer || V.Seat.LEAD)}))} · ${esc(NS(t.state))}${esc(need)}</tspan>${tag}</text><title>${esc(T("board.seq.open_card"))}</title></g>`;
        return;
      }
      if (r.issue) {
        const i = r.issue, who = i.attendees.map((a) => a.member).join(T("sep.list"));
        s += `<a href="${U(`/p/${esc(id)}/meet/${esc(i.id)}`)}" class="iss"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">${esc(T(i.type === V.IssueType.REVIEW_MEETING ? "board.seq.review_meeting" : "board.seq.meeting"))} ${esc(i.id)} ${esc(i.title)} · ${esc(who)} · ${esc(T("board.seq.posts", {n: i.post_count}))} · ${esc(NS(i.state))}${esc(T("board.seq.open_chat"))}</text></a>`;
        return;
      }
      if (r.fold) {
        s += `<g class="fold" data-fold="${esc(gid + ":" + r.fold.order)}"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">${esc(T("board.seq.folded", {no: circ(r.fold.order), name: r.fold.name, n: r.n}))}</text></g>`;
        return;
      }
      if (r.p) {
        const p = r.p;
        if (p.edge === "needs_split") {
          s += `<g class="planbox"><rect x="${TIMEW}" y="${r.y - FH / 2 + 3}" width="${W - TIMEW - 8}" height="${FH - 6}" rx="6"/><text x="${TIMEW + 10}" y="${r.y}">${esc(T("board.stage_n", {n: circ(p.stage)}))} ${esc(p.name)} · ${esc(T("board.seq.not_split"))}${p.people.length ? " · " + esc(T("board.seq.people", {who: p.people.join(T("sep.list"))})) : ""}</text></g>`;
          return;
        }
        const px1 = col[p.from], px2 = p.to && p.to !== V.SeatClass.NONE && col[p.to] != null ? col[p.to] : px1;
        if (px1 == null) return;
        const pid = p.object || "";
        const pdim = hiTask ? dimFor(pid) : "";
        const plabel = NE(p.edge);
        s += `<g class="ev plan ${pdim} ${pid ? "clickable" : ""}" ${pid ? `data-taskcard="${esc(pid)}"` : ""}><text x="${TIMEW - 8}" y="${r.y}" class="tm">${esc(T("board.seq.plan"))}</text><title>${esc(T("board.seq.plan_title", {from: WHO(p.from), to: WHO(p.to === V.SeatClass.NONE ? p.from : p.to), title: p.title || g.title}))}</title>`;
        if (px1 === px2) {
          s += `<path d="M${px1} ${r.y - 6}h18v12h-14" class="arw" marker-end="url(#sa)"/><text x="${px1 + 24}" y="${r.y}" class="elab l">${esc(plabel)}</text>`;
        } else {
          const dir = px2 > px1 ? 1 : -1;
          s += `<line x1="${px1}" y1="${r.y + 4}" x2="${px2 - dir * 4}" y2="${r.y + 4}" class="arw" marker-end="url(#sa)"/><text x="${(px1 + px2) / 2}" y="${r.y - 5}" class="elab">${esc(plabel)}</text>`;
        }
        s += "</g>";
        return;
      }
      const e = r.e, dr = e.draw || {}, from = dr.from || e.from, to = dr.to || e.to;  // 总裁的话由总管代记的事件，按总裁 → 总管画
      const x1 = col[from], x2 = to && to !== V.SeatClass.NONE && col[to] != null ? col[to] : x1;
      if (x1 == null) return;
      const task = e.layer === V.Kind.TASK, cls = !task ? "gl" : e.trunk ? "tr" : "br";
      const dim = hiTask ? dimFor(e.object) : "";
      const sel = openSeq === e.project_seq ? "sel" : "";
      const stroke = task ? color[e.object] : "var(--ink-2)";
      const label = `${task && !S ? e.object.replace(/^G\d+-/, "") + " " : ""}${task && S && !r.stage ? e.object.replace(/^G\d+-/, "") + " " : ""}${NE(dr.label || e.edge)}${e.result ? T("sep.colon") + NR(e.result) : ""}`;
      s += `<g class="ev ${cls} ${dim} ${sel}" data-seq="${e.project_seq}" style="--c:${stroke}">`;
      s += `<text x="${TIMEW - 8}" y="${r.y}" class="tm">${esc(S ? hm(e.time) : hm(e.time).slice(6))}</text>`;
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
      const xr = (e.caused || []).length ? {t: T("board.seq.caused", {ids: e.caused.map((c) => short(c.object)).join(T("sep.list"))}), q: e.caused[0].project_seq}
        : e.caused_by ? {t: T("board.seq.caused_by", {id: short(e.caused_by.object), edge: e.caused_by.edge === V.Edge.REVIEW ? T("board.seq.sent_back") : NE(e.caused_by.edge)}), q: e.caused_by.project_seq} : null;
      if (xr) s += `<text x="${Math.max(x1, x2) + (x1 === x2 ? 30 + label.length * 11 : 12)}" y="${r.y + 4}" class="xref" data-goseq="${xr.q}">${esc(xr.t)}</text>`;
      s += "</g>";
    });
    s += "</svg>";
    // 一键展开 / 折叠所有已通过的阶段
    const passed = ARCHIVE ? [] : stages.filter((x) => x.state === V.State.PASSED);
    const foldAll = passed.length ? `<span class="tlink foldall" data-foldall="${esc(gid)}" data-open="${folded.size ? 1 : 0}">${esc(T(folded.size ? "board.seq.expand_all" : "board.seq.fold_all"))}</span>` : "";
    const planNote = S ? `<span class="meta">${esc(T("board.seq.legend"))}</span>` : "";
    const legend = S ? `<div class="seqlegend">${planNote}${foldAll}</div>` : `<div class="seqlegend">${tasks.map((t) => `<span class="lg ${hiTask === t.id ? "on" : ""}" data-hitask="${esc(t.id)}"><i style="background:${color[t.id]}"></i>${esc(t.id)} ${esc(t.title)} · ${esc(NS(t.state))}${t.rework_count ? ` · ${esc(T("board.rework_n", {n: t.rework_count}))}` : ""}</span>`).join("")}<span class="meta">${esc(T("board.seq.legend_old"))}</span>${foldAll}</div>`;
    const diffs = g.drift || [];
    const diffBox = diffs.length ? `<div class="appr diff"><div class="alabel">${esc(T("board.seq.diff", {v: g.approved_version}))}</div><ul class="plain achg">${diffs.map((x) => `<li><b>${esc(N("diff", x.type))}</b> <span class="tid">${esc(short(x.task))}</span> ${esc(x.note)}</li>`).join("")}</ul></div>` : "";
    let det = "";
    const ev = g.events.find((x) => x.project_seq === openSeq);
    if (ev) {
      const run = ev.run ? d.runs.find((r) => r.run === ev.run) : null;
      det = `<div class="ldet"><b>${esc(ev.object)} ${esc(NE(ev.edge))}${ev.result ? esc(T("sep.colon") + NR(ev.result)) : ""}</b> · ${esc(WHO((ev.draw || {}).from || ev.from))} → ${esc(WHO((ev.draw || {}).to || ev.to))} · ${esc(NS(ev.from_state))} → ${esc(NS(ev.to_state))} · ${esc(hm(ev.time))} · ${esc(T("board.seq.project_seq", {n: ev.project_seq}))}`
        + (ev.basis ? `<div class="${ev.quote ? "quote" : "meta"}"><span class="meta">${esc(T(ev.quote ? "board.seq.quote" : "board.seq.auto_basis"))}</span> ${esc(ev.basis)}</div>` : "")
        + (ev.note ? `<div>${ev.basis && ev.quote ? `<span class="meta">${esc(T(ev.from === V.Seat.LEAD || ev.writer === V.Seat.LEAD ? "board.seq.lead_says" : "board.seq.note"))}</span> ` : ""}${esc(ev.note)}</div>` : "")
        + (ev.same_plan_version ? `<div class="meta">${esc(T("board.seq.same_plan", {v: ev.same_plan_version}))}</div>` : "")
        + ((ev.caused || []).length ? `<div class="meta">${ev.caused.map((c) => `<span class="xref" data-goseq="${c.project_seq}">${esc(T("board.seq.caused", {ids: c.object}))}</span>`).join(T("sep.list"))}</div>` : "")
        + (ev.caused_by ? `<div class="meta"><span class="xref" data-goseq="${ev.caused_by.project_seq}">${esc(T("board.seq.caused_by", {id: ev.caused_by.object, edge: ev.caused_by.edge === V.Edge.REVIEW ? T("board.seq.sent_back") : NE(ev.caused_by.edge)}))}</span></div>` : "")
        + (ev.evidence && ev.evidence.length ? `<div class="meta">${esc(T("board.seq.evidence"))}${ev.evidence.map((x) => fileLink(x, d.root)).join(T("sep.list"))}</div>` : "")
        + (ev.override ? `<div class="meta">${esc(T("board.seq.override"))}${esc(ev.override)}</div>` : "")
        + (ev.session ? `<div class="meta">${esc(T("board.seq.session"))}${esc(ev.session)}</div>` : "")
        + (run ? `<div class="meta">${esc(T("board.seq.run"))} ${esc(run.run)} ${esc(run.member)} · ${dur(run.ended ? (new Date(run.ended) - new Date(run.started)) / 1000 : secs(run.started))} · ${tok(run.tokens)}</div>` : "")
        + "</div>";
    }
    const cardBox = S && openCard && tasks.some((t) => t.id === openCard) ? renderTaskCard(d, g, openCard) : "";
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
  const relCls = (s) => (isIn(s, ST.BLOCKED, ST.FAILED) ? "bad" : s === ST.IN_REVIEW ? "rv" : isIn(s, ST.IN_PROGRESS, ST.DISPATCHED, ST.ACTIVE) ? "go" : "idle");
  const nowMs = (d) => (d.clock ? new Date(d.clock).getTime() : Date.now());
  function ago(ms) {
    const m = Math.max(0, Math.round(ms / 60e3));
    if (m < 1) return T("board.ago.now");
    if (m < 60) return T("board.ago.m", {n: m});
    if (m < 48 * 60) return T("board.ago.h", {n: Math.round(m / 60)});
    return T("board.ago.d", {n: Math.round(m / 1440)});
  }
  function relCursor(g) {
    return openSeq != null && g.events.some((e) => e.project_seq === openSeq) ? openSeq : null;
  }
  function renderRel(d, gid) {
    const g = seqGroup(d, gid);
    if (!g || !g.events.length) return "";
    const cur = relCursor(g);
    const upto = (list) => (cur == null ? list : list.filter((x) => x.project_seq <= cur));
    const lastOf = (list) => { const l = upto(list || []); return l[l.length - 1]; };
    const tNow = cur == null ? nowMs(d) : new Date(g.events.find((e) => e.project_seq === cur).time).getTime();
    const stages = g.stages || [];
    const tasks = d.view.tasks.filter((t) => (gid === "—" ? !t.goal : t.goal === gid));
    const tIndex = {};
    tasks.forEach((t, i) => { tIndex[t.id] = i; });
    // 端口：派出去过、还没结束的任务；现在视图里再加上所在阶段已轮到、还没派的任务（灰）；目标本身在总裁手里时也占一个
    const ports = [];
    if (gid !== "—") {
      const gs = lastOf(g.handoffs);
      if (gs && gs.holder === V.Seat.OWNER && gs.category !== V.Category.DONE) ports.push({id: gid, label: `${gid} ${NS(gs.state)}`, snap: gs, goal: true});
    }
    tasks.forEach((t) => {
      const snap = lastOf(t.handoffs);
      if (!snap || snap.category === V.Category.DONE) return;
      const sent = upto(t.handoffs).some((x) => x.edge === V.Edge.DISPATCH);
      const st = stages.find((x) => x.order === t.stage);
      if (!sent && gid !== "—") return;  // 还没派的任务在下面按计划画
      if (!sent && !(cur == null && st && [V.StageStatus.READY, V.StageStatus.ACTIVE].includes(st.state))) return;
      // 拿到手的时刻：持有人最后一次换成现在这个人
      const hs = upto(t.handoffs);
      let since = snap;
      for (let k = hs.length - 1; k >= 0 && hs[k].holder === snap.holder; k--) since = hs[k];
      ports.push({id: t.id, label: `${t.id.replace(/^G\d+-/, "")} ${sent ? NS(snap.state) : T("board.rel.to_dispatch")}`, snap, t, since, sent});
    });
    // 计划：还没走到的任务和没拆的阶段是灰色端口，连到计划的成员；回放时只看当时的实际情况
    if (gid !== "—" && cur == null && !isIn(g.state, ST.DONE, ST.CANCELLED)) {
      stages.forEach((st) => {
        tasks.filter((t) => t.stage === st.order && t.category !== V.Category.DONE && !ports.some((q) => q.id === t.id)).forEach((t) => {
          const doer = t.executor || t.planned_executor || (st.people || [])[0] || V.Seat.LEAD;
          ports.push({id: t.id, plan: true, label: `${t.id.replace(/^G\d+-/, "")} ${t.title}`, title: `${t.title}${T("sep.colon")}${T("board.seq.who", {doer: WHO(doer), reviewer: WHO(t.planned_reviewer || V.Seat.LEAD)})}${T("sep.paren_open")}${NS(t.state)}${T("sep.paren_close")}`,
            snap: {holder: doer, from: V.Seat.LEAD, state: "plan"}});
        });
        if (st.needs_split) ports.push({id: "stage:" + st.order, plan: true, label: `${st.order} ${st.name} · ${T("board.rel.to_split")}`, title: T("board.rel.stage_not_split", {no: st.order, name: st.name}),
          snap: {holder: st.people[0] || V.Seat.LEAD, from: V.Seat.LEAD, state: "plan"}});
      });
    }
    const members = g.participants.filter((p) => p.name !== V.Seat.OWNER && p.name !== V.Seat.LEAD);
    if (!ports.length) {
      const done = isIn(g.state, ST.DONE, ST.CANCELLED);
      return `<div class="relwrap relempty"><span class="meta">${esc(T(cur == null ? "board.rel.title_now" : "board.rel.title_replay"))}</span>${esc(T(done && cur == null ? "board.rel.empty_done" : "board.rel.empty"))}${esc(T("board.rel.empty_hint"))}${cur != null ? ` <span class="tlink" data-relnow="1">${esc(T("board.rel.back_now"))}</span>` : ""}</div>`;
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
    members.forEach((p, i) => { memAt[p.name] = i; });
    const held = {};
    const planned = {};
    ports.forEach((p) => {
      const h = p.snap.holder, box = p.plan ? planned : held;
      if (h && memAt[h] != null) (box[h] = box[h] || []).push(p);
    });
    const bossN = ports.filter((p) => p.snap.holder === V.Seat.OWNER).length;
    const curStages = [...new Set(ports.filter((p) => p.t).map((p) => p.t.stage))].map((n) => stages.find((x) => x.order === n)).filter(Boolean);
    const dimP = (p) => (hiTask && hiTask !== p.id ? "dim" : "");
    let s = `<svg class="rel" viewBox="0 0 ${W} ${H}" style="max-width:${W}px"><defs><marker id="ra" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5"/></marker></defs>`;
    s += `<text x="${BX + BW / 2}" y="16" class="rh">${esc(WHO(V.Seat.OWNER))}</text><text x="${LX + LW / 2}" y="16" class="rh">${esc(WHO(V.Seat.LEAD))}${curStages.length ? " · " + curStages.map((x) => `${esc(T("board.stage_n", {n: circ(x.order)}))} ${esc(x.name)}`).join(T("sep.list")) : ""}</text><text x="${MX + MW / 2}" y="16" class="rh">${esc(T("board.rel.members"))}</text>`;
    // 边（先画，压在卡片下面）
    const curve = (x1, y1, x2, y2) => { const mx = (x1 + x2) / 2; return `M${x1} ${y1}C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`; };
    ports.forEach((p, i) => {
      const py = portY(i), h = p.snap.holder, from = p.snap.from, cls = relCls(p.snap.state), dim = dimP(p);
      const edge = (d0, back) => { s += `<path d="${d0}" class="re ${cls} ${p.plan ? "plan" : ""} ${back ? "back" : ""} ${dim}" data-rtask="${esc(p.id)}" marker-end="url(#ra)"/>`; };
      if (h === V.Seat.OWNER) edge(curve(LX - 2, py, BX + BW + 4, boss.y + boss.h / 2), false);
      else if (h === V.Seat.LEAD && from === V.Seat.OWNER) edge(curve(BX + BW + 2, boss.y + boss.h / 2, LX - 4, py), true);
      else if (h === V.Seat.LEAD && memAt[from] != null) edge(curve(MX - 2, memY(memAt[from]), LX + LW + 4, py), true);
      else if (memAt[h] != null && memAt[from] != null && from !== h) {
        // 成员之间的交接：卡片右侧的弧线；端口和持有人之间只画一条细的归属线
        const y1 = memY(memAt[from]), y2 = memY(memAt[h]), xr = MX + MW;
        s += `<path d="M${LX + LW} ${py}L${MX} ${y2}" class="re own ${dim}"/>`;
        edge(`M${xr + 2} ${y1}C${xr + ARC} ${y1} ${xr + ARC} ${y2} ${xr + 4} ${y2}`, false);
      } else if (memAt[h] != null) edge(curve(LX + LW + 2, py, MX - 4, memY(memAt[h])), false);
    });
    // 总裁
    s += `<g class="rcard ${bossN ? "bad" : "idle"}"><rect x="${BX}" y="${boss.y}" width="${BW}" height="${boss.h}" rx="8"/><text x="${BX + BW / 2}" y="${boss.y + 19}" class="rn">${esc(WHO(V.Seat.OWNER))}</text><text x="${BX + BW / 2}" y="${boss.y + 37}" class="rs">${esc(bossN ? `${I18N.sections.decisions} ${bossN}` : T("board.rel.nothing_pending"))}</text></g>`;
    // 总管和端口
    s += `<rect x="${LX}" y="${TOP}" width="${LW}" height="${leadH}" rx="8" class="rlead"/><text x="${LX + LW / 2}" y="${TOP + 20}" class="rn">${esc(WHO(V.Seat.LEAD))}</text>`;
    ports.forEach((p, i) => {
      const py = portY(i), cls = p.sent === false ? "idle" : relCls(p.snap.state);
      const short = p.label.length > 15 ? p.label.slice(0, 14) + "…" : p.label;
      s += `<g class="rport ${cls} ${p.plan ? "plan" : ""} ${dimP(p)} ${hiTask === p.id ? "on" : ""}" data-rtask="${esc(p.id)}"><rect x="${LX + 12}" y="${py - 13}" width="${LW - 24}" height="26" rx="5"/><text x="${LX + LW / 2}" y="${py}" class="rs">${esc(short)}</text><title>${esc(p.title || (p.t ? p.t.title : g.title))}</title></g>`;
    });
    // 成员卡片
    members.forEach((p, i) => {
      const y = memY(i) - MH / 2, mine = held[p.name] || [];
      const worst = mine.some((q) => relCls(q.snap.state) === "bad") ? "bad" : mine.some((q) => relCls(q.snap.state) === "rv") ? "rv" : mine.length ? "go" : "idle";
      const line = mine.length ? mine.map((q) => {
        const live = cur == null ? d.runs.filter((r) => r.task === q.id && r.status === V.RunStatus.RUNNING).pop() : null;
        const t = live ? T("board.rel.running_for", {t: dur(secs(live.started))}) : T("board.rel.held_for", {t: ago(tNow - new Date(q.since.time).getTime())});
        return `${q.id.replace(/^G\d+-/, "")} · ${t}`;
      }).join(T("sep.clause")) : planned[p.name] ? T("board.rel.planned_n", {n: planned[p.name].length}) : p.appeared ? T("board.rel.idle") : T("board.rel.absent");
      const dim = hiTask && !ports.some((q) => q.id === hiTask && (q.snap.holder === p.name || q.snap.from === p.name)) ? "dim" : "";
      s += `<g class="rcard ${worst} ${dim} ${p.planned ? "" : "extra"}" ${mine.length ? `data-rtask="${esc(mine[0].id)}"` : ""}><rect x="${MX}" y="${y}" width="${MW}" height="${MH}" rx="8"/><text x="${MX + MW / 2}" y="${y + 18}" class="rn">${esc(p.name)}</text><text x="${MX + MW / 2}" y="${y + 35}" class="rs">${esc(line)}</text></g>`;
    });
    s += "</svg>";
    // 最近事件栏：时序图到游标为止的最后一行
    // 进展、变更、更正不是交接，不进事件栏
    const le = lastOf(g.events.filter((e) => ![V.Edge.PROGRESS, V.Edge.CHANGE, V.Edge.CORRECTION].includes(e.edge)));
    const to = le && le.to && le.to !== V.SeatClass.NONE && le.to !== le.from ? ` → ${esc(WHO(le.to))}` : "";
    const bar = le ? `<b>${esc(T("board.rel.last"))}</b>${esc(T("sep.colon"))}${esc(WHO(le.from))}${to} · ${esc(NE(le.edge))}${le.result ? esc(T("sep.colon") + NR(le.result)) : ""} · ${esc(le.object)}${le.note ? " · " + esc(le.note.length > 48 ? le.note.slice(0, 48) + "…" : le.note) : ""} · ${cur == null ? esc(T("board.rel.ago", {t: ago(tNow - new Date(le.time).getTime())})) : esc(hm(le.time))}` : "";
    const mode = cur == null ? `<span class="meta">${esc(T("board.rel.mode_now"))}</span>` : `<span class="pill warn">${esc(T("board.rel.mode_replay", {t: hm(g.events.find((e) => e.project_seq === cur).time), n: cur}))}</span> <span class="tlink" data-relnow="1">${esc(T("board.rel.back_now"))}</span>`;
    return `<div class="relwrap"><div class="relhead">${mode}<span class="meta">${esc(T("board.rel.legend"))}</span></div>${s}<div class="relbar">${bar}</div></div>`;
  }
  function nowLineView(d, g) {
    const B = (x) => `<b>${esc(x)}</b>`;
    if (g.state === V.State.DRAFT) return T("board.nl.wait_plan", {who: B(WHO(V.Seat.LEAD))});
    if (g.state === V.State.PENDING_APPROVAL) return T("board.nl.wait_approve", {who: B(WHO(V.Seat.OWNER))});
    if (g.state === V.State.PENDING_ACCEPTANCE) return T("board.nl.wait_accept", {who: B(WHO(V.Seat.OWNER))});
    if (g.state === V.State.PAUSED) return esc(T("board.nl.paused"));
    const ids = new Set(g.stages.flatMap((s) => s.tasks));
    const ACT = {[ST.APPROVED]: "dispatch", [ST.DISPATCHED]: "pick_up", [ST.IN_PROGRESS]: "work", [ST.IN_REVIEW]: "review", [ST.BLOCKED]: "unblock", [ST.FAILED]: "decide", [ST.PAUSED]: "resume"};
    const gv0 = seqGroup(d, g.id);
    const waiting = new Set((gv0 ? gv0.stages : []).filter((s) => s.state === V.StageStatus.NOT_STARTED).flatMap((s) => s.tasks));
    // 已建好、但所在阶段还没轮到的差事不算「现在」
    const parts = d.view.current.filter((c) => ids.has(c.object) && !(c.state === V.State.APPROVED && waiting.has(c.object))).map((c) => {
      const live = d.runs.filter((r) => r.task === c.object && r.status === V.RunStatus.RUNNING).pop();
      return T("board.act." + (ACT[c.state] || "push"), {who: B(WHO(c.to) || "—"), id: esc(c.object)}) + (live ? ` · <span class="dot"></span>${esc(T("board.ran_for", {who: live.member, t: dur(secs(live.started))}))}` : "");
    });
    const gv = seqGroup(d, g.id);
    (gv ? gv.stages : []).filter((s) => s.state === V.StageStatus.READY && !s.tasks.length)
      .forEach((s) => parts.push(T("board.nl.stage_create", {who: B(WHO(V.Seat.LEAD)), no: circ(s.order), name: esc(s.name)})));
    return parts.join(T("sep.clause")) || T("board.nl.all_passed", {who: B(WHO(V.Seat.LEAD))});
  }
  function renderGoalDetail(g, devs) {
    let b = `<div class="detail gdetail">`;
    const gtasks = new Set(g.stages.flatMap((s) => s.tasks));
    const gruns = (data.runs || []).filter((r) => gtasks.has(r.task));
    if (gruns.length) b += `<div class="meta">${esc(T("board.runs_total", {n: gruns.length, tok: tok(sumTok(gruns))}))}</div>`;
    const head = Object.entries(g.head).filter(([k]) => !["state", "due"].includes(k)).map(([k, v]) => ({k: headLabel(k), v: esc(headValue(k, v))}));
    const fields = head.concat(g.fields);
    if (fields.length) b += `<div class="fields">${fields.map((f) => `<span class="k">${esc(f.k)}</span><span>${f.v}</span>`).join("")}</div>`;
    b += `<h4>${esc(I18N.sections.stages)}</h4><div class="scroll"><table><thead><tr>${["stage", "name", "people", "output", "condition", "tasks", "status"].map((k) => `<th>${esc(T("board.stages." + k))}</th>`).join("")}</tr></thead><tbody>${g.stages.map((s) => `<tr>
      <td>${circ(s.no)}</td><td>${esc(s.seat)}</td><td>${esc(whoText(s.who))}</td><td>${s.output}</td><td>${s.cond}</td>
      <td>${s.taskInfo.map((t) => t.archived && !ARCHIVE ? `<a class="tlink" href="${U(`/p/${esc(id)}/archive#${esc(t.id)}`)}">${esc(t.id)} ${statusPill(t.state || "—")}</a>`
        : `<span class="tlink" data-task="${esc(t.id)}">${esc(t.id)} ${statusPill(t.state || "—")}</span>`).join(" ") || "—"}${s.missing.length ? ` <span class="pill bad">${esc(T("board.not_found", {ids: s.missing.join(T("sep.list"))}))}</span>` : ""}</td>
      <td>${statusPill(s.status)}</td></tr>`).join("")}</tbody></table></div>`;
    if (devs.length) b += `<h4>${esc(T("board.devs"))}</h4><ul class="plain">${devs.map((r) => `<li><b>${esc(r.run)}</b> ${esc(T("board.dev_line", {who: r.member, seat: N("seat", r.seat)}))}${esc(r.override)}<div class="note">${(r.deviations || []).map(esc).join(esc(T("sep.clause")))}</div></li>`).join("")}</ul>`;
    return b + "</div>";
  }

  const ISSUE_CLS = {[ST.PENDING_RULING]: "warn", [ST.RULED]: "ok", "开放": "", [ST.DISCUSSING]: "run", [ST.CLOSING]: "warn", [ST.DRAFT]: "", [ST.CANCELLED]: ""};


  function renderIssues(d) {
    const list = d.issues.slice().sort((a, b) => (a.stage === V.State.RULED) - (b.stage === V.State.RULED));
    if (!list.length) return "";
    const body = list.map((i) => {
      if (i.flow) return flowIssueCard(i);
      const live = d.runs.filter((r) => r.task === i.id && r.status === V.RunStatus.RUNNING);
      const chips = Array.from({length: i.maxRounds}, (_, k) => {
        const n = k + 1;
        const done = n <= i.roundsDone;
        const running = !done && n === i.roundsDone + 1 && live.length;
        return `<span class="stage ${done ? "ok" : running ? "run cur" : ""}">${esc(T("board.round", {n}))} ${done ? "✓" : running ? "●" : ""}</span>`;
      }).join('<span class="arrow">→</span>') + `<span class="arrow">→</span><span class="stage ${i.summary.length ? "ok" : ""}">${esc(I18N.sections.summary)} ${i.summary.length ? "✓" : ""}</span><span class="arrow">→</span><span class="stage ${i.ruling.length ? "ok" : i.stage === V.State.PENDING_RULING ? "warn cur" : ""}">${esc(I18N.sections.ruling)} ${i.ruling.length ? "✓" : ""}</span>`;
      const who = i.attendees.map((a) => `${esc(a.member)}${a.view ? esc(T("sep.paren_open") + a.view + T("sep.paren_close")) : ""}`).join(esc(T("sep.list")));
      const stage = live.length ? "round_running" : i.stage;
      let h = `<div class="goal ${openIssue === i.id ? "open" : ""}" data-issue="${esc(i.id)}">
        <div class="ghead"><span class="tid">${esc(i.id)}</span><span class="tt">${esc(i.title)}</span> ${issuePill(stage, i.roundsDone + 1)}
          ${stage === V.State.PENDING_RULING ? `<span class="meta">${esc(T("board.issue.your_ruling"))}</span>` : ""}</div>
        <div class="pipe">${chips}</div>
        <div class="note">${esc(T("board.issue.attendees"))}${who || "—"}${live.length ? ` · <span class="dot"></span>${esc(T("board.issue.speaking", {n: live.length}))}` : ""}</div></div>`;
      if (openIssue === i.id) h += renderIssueDetail(i);
      return h;
    }).join("");
    return card(esc(T("board.pick.issues")), body, {meta: esc(T(list.some((i) => i.flow) ? "board.issue.meta_flow" : "board.issue.meta_old"))});
  }

  // 新结构议题：只放结论（状态、所属目标、与会、总结、裁决）和谁在思考，发言在朝会页
  function flowIssueCard(i) {
    const who = i.attendees.map((a) => `${esc(a.member)}${a.view ? esc(T("sep.paren_open") + a.view + T("sep.paren_close")) : ""}`).join(esc(T("sep.list")));
    const think = i.thinking.length ? ` · <span class="dot"></span>${esc(T("board.issue.thinking", {who: i.thinking.join(T("sep.list"))}))}` : "";
    const last = i.last ? ` · ${esc(T("board.issue.latest"))}${esc(WHO(i.last.who))} ${esc(hm(i.last.time))}${i.last.private ? esc(T("issue.private_mark")) : i.last.text ? esc(T("sep.colon") + i.last.text.slice(0, 40)) : ""}` : "";
    let concl = "";
    if (i.summary) concl += `<div class="fields"><span class="k">${esc(I18N.sections.summary)}</span><span>${esc(i.summary.note)}</span><span class="k">${esc(N("event_field", "options"))}</span><span>${esc(i.summary.options)}</span><span class="k">${esc(T("board.pend.recommended"))}</span><span>${esc(i.summary.recommendation)}</span></div>`;
    if (i.ruling) concl += `<div class="fields"><span class="k">${esc(I18N.sections.ruling)}</span><span>${esc(i.ruling.note)}</span></div>`;
    if (!concl) concl = `<div class="empty">${esc(T(i.stage === V.State.CLOSING ? "board.issue.closing" : "board.issue.no_conclusion"))}</div>`;
    return `<div class="goal fissue">
      <div class="ghead"><span class="tid">${esc(i.id)}</span><span class="tt">${esc(i.title)}</span> ${issuePill(i.stage)}
        <span class="pill">${esc(N("issue_type", i.type))}</span>${i.goal ? ` <span class="tlink" data-goal="${esc(i.goal)}">${esc(i.goal)}</span>` : ` <span class="meta">${esc(T("board.issue.project_level"))}</span>`}
        ${i.stage === V.State.PENDING_RULING ? `<span class="meta">${esc(T("board.issue.your_ruling"))}</span>` : ""}<a class="tlink golink" href="${U(`/p/${esc(id)}/meet/${esc(i.id)}`)}">${esc(T("board.issue.enter"))} →</a></div>
      <div class="note">${esc(T("board.issue.attendees"))}${who || "—"} · ${esc(T("board.issue.posts", {n: i.count}))}${last}${think}</div>${concl}</div>`;
  }

  function issuePill(s, round) {  // 旧结构议题的状态是卡片原文；round_running 是第几轮正在开
    const run = s === "round_running";
    const cls = run ? "run" : ISSUE_CLS[s] ?? "";
    return `<span class="pill ${cls}">${run ? '<span class="dot"></span>' : ""}${esc(run ? T("board.round_running", {n: round}) : NS(s))}</span>`;
  }

  function fieldGrid(list) {
    return list.length ? `<div class="fields">${list.map((f) => `<span class="k">${esc(f.code ? I18N.fields[f.code] || f.k : f.k)}</span><span>${f.v}</span>`).join("")}</div>` : `<div class="empty">${esc(T("board.not_filled"))}</div>`;
  }

  function renderIssueDetail(i) {
    let b = `<div class="detail gdetail"><h4>${esc(I18N.sections.question)}</h4>${fieldGrid(i.question)}`;
    i.rounds.filter((r) => r.speeches.length).forEach((r) => {
      b += `<h4>${esc(T("board.round", {n: r.no}))}</h4>${r.speeches.map((s, k) => `<details class="speech" data-sp="${esc(i.id + "-" + r.no + "-" + k)}" ${openSpeech.has(i.id + "-" + r.no + "-" + k) ? "open" : ""}><summary>${esc(s.who)}</summary><pre class="out">${esc(s.text)}</pre></details>`).join("")}`;
    });
    b += `<h4>${esc(T("card.summary_heading", {summary: I18N.sections.summary}))}</h4>${fieldGrid(i.summary)}<h4>${esc(I18N.sections.ruling)}${esc(T("sep.paren_open") + WHO(V.Seat.OWNER) + T("sep.paren_close"))}</h4>${fieldGrid(i.ruling)}`;
    return b + "</div>";
  }

  function renderRunning(d) {
    const running = d.runs.filter((r) => r.status === V.RunStatus.RUNNING);
    if (!running.length) return "";
    const rows = running.map((r) => {
      const idle = secs(r.last_at);
      const stale = idle != null && idle > STALE_MIN * 60;
      return `<tr><td class="num">${esc(r.run)}</td><td>${esc(N("seat", r.seat))}</td><td>${esc(r.member)}</td>
        <td class="num">${dur(secs(r.started))}</td><td class="num">${esc(r.steps || 0)}</td>
        <td>${esc(r.last_action || "—")}</td>
        <td class="num ${stale ? "stale" : ""}">${idle == null ? "—" : esc(T("board.rel.ago", {t: dur(idle)}))}${stale ? " · " + esc(N("run_phase", V.RunPhase.STALLED)) : ""}</td></tr>`;
    }).join("");
    return card(esc(T("board.running.title")), `<div class="scroll"><table><thead><tr>${["run", "seat", "member", "elapsed", "steps", "action", "since"].map((k) => `<th>${esc(T("board.running." + k))}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`,
      {meta: esc(T("board.running.meta", {n: running.length, m: STALE_MIN}))});
  }

  // 目标筛选：任务看卡头「目标」，派活看它所属任务的目标
  function goalOfTask(d, id) { const t = d.cards.find((x) => x.id === id); return t && t.goal ? t.goal : "none"; }

  function who(t) {
    const parts = [];
    if (t.head.executor || t.head.reviewer) parts.push(`${esc(WHO(t.head.executor) || "—")} → ${esc(WHO(t.head.reviewer) || "—")}`);
    if (t.holder) parts.push(esc(T("board.held_by", {who: WHO(t.holder)})));
    return parts.join(" · ");
  }

  function taskList(d, list) {
    const runsBy = {};
    d.runs.forEach((r) => { (runsBy[r.task] = runsBy[r.task] || []).push(r); });
    const cols = COLS.map((c) => ({...c, cards: []}));
    const other = {name: T("board.col.other"), cards: []};
    list.forEach((t) => { (cols.find((c) => c.match(t.state || "")) || other).cards.push(t); });
    if (other.cards.length) cols.push(other);
    // 只列有任务的状态组，一行一个任务；点开在该行下面看详情
    const html = cols.filter((c) => c.cards.length).map((c) => `<div class="tgroup"><h3>${c.name}<span class="n">${c.cards.length}</span></h3>${c.cards.map((t) => {
      const rs = runsBy[t.id] || [];
      const live = rs.some((r) => r.status === V.RunStatus.RUNNING);
      const lastRow = t.flow[t.flow.length - 1] || {};
      const last = strip(flowNote(lastRow));
      const row = `<div class="trow task ${openTask === t.id ? "open" : ""}" data-task="${esc(t.id)}">
        <span class="tid">${esc(t.id)}</span><span class="tt">${esc(t.title)}</span>
        ${t.goal && !t.id.startsWith(t.goal + "-") ? `<span class="gtag">${esc(t.goal)}${t.stage ? " · " + circ(t.stage) : ""}</span>` : ""}${rs.some((r) => r.override) ? `<span class="pill warn">${esc(T("board.deviation"))}</span>` : ""}
        <span class="tw">${who(t)}</span>
        ${statusPill(t.state || "—")}
        <span class="tn">${live ? '<span class="dot"></span>' : ""}${rs.length ? esc(T("board.runs_n", {n: rs.length})) : ""}</span>
        ${last ? `<div class="note">${esc(last)}</div>` : ""}
      </div>`;
      return row + (openTask === t.id ? renderTaskDetail(t, rs) : "");
    }).join("")}</div>`).join("");
    return html ? `<div class="tlist">${html}</div>` : `<div class="empty">${esc(T("board.no_tasks"))}</div>`;
  }

  function renderTaskDetail(t, runs) {
    let b = `<div class="detail"><h4>${esc(t.id)} ${esc(t.title)} ${statusPill(t.state || "—")}</h4>`;
    const head = Object.entries(t.head).filter(([k]) => k !== "state");
    const fields = head.map(([k, v]) => ({k: headLabel(k), v: esc(headValue(k, v))})).concat(t.fields.map((f) => ({...f, k: f.code ? I18N.fields[f.code] || f.k : f.k})));
    if (fields.length) b += `<div class="fields">${fields.map((f) => `<span class="k">${esc(f.k)}</span><span>${f.v}</span>`).join("")}</div>`;
    if (t.flow.length) {
      const keys = ["time", "state", "from", "to", "note"];
      const cellOf = (r, k) => k === "state" ? esc(NS(r.state)) : k === "from" || k === "to" ? esc(WHO(strip(r[k] || ""))) : k === "note" ? flowNote(r, true) : r[k] || "";
      b += `<h4>${esc(I18N.sections.history)}</h4><div class="scroll"><table><thead><tr>${keys.map((k) => `<th>${esc(T("board.flow." + k))}</th>`).join("")}</tr></thead><tbody>${t.flow.map((r) => `<tr>${keys.map((k) => `<td>${cellOf(r, k)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    if (runs.length) b += `<h4>${esc(T("board.runs_title"))}</h4>${runsTable(runs.slice().reverse(), false)}`;
    return b + "</div>";
  }

  // 派活记录按开始日期分组（新的在上），组头写当天次数、合计用时和 token
  function dayLabel(day) {
    const [y, m, dd] = day.split("-").map(Number), dt = new Date(y, m - 1, dd);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const diff = Math.round((today - dt) / 86400000);
    return `${diff === 0 ? T("board.today") + " · " : diff === 1 ? T("board.yesterday") + " · " : ""}${day.slice(5)}${T("board.weekday_paren", {d: T("board.weekday." + dt.getDay())})}`;
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
        head = `<tr class="dayrow"><td colspan="${cols}"><b>${esc(day ? dayLabel(day) : T("board.time_unknown"))}</b><span>${esc(T("board.day_total", {n: same.length, t: dur(same.reduce((a, x) => a + (tookOf(x) || 0), 0))}))} · token ${tok(sumTok(same)).split(" ·")[0]}</span></td></tr>`;
      }
      return head + runRow(r, showTask, cols);
    }).join("");
    const th = (k) => `<th>${esc(T("board.runs." + k))}</th>`;
    return `<div class="scroll"><table class="runs"><thead><tr>${th("run")}${showTask ? th("task") : ""}${th("who")}${th("status")}${th("start")}${th("took")}<th>token</th>${th("result")}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }
  function runRow(r, showTask, cols) {
    {
      const took = tookOf(r);
      const summary = r.status === V.RunStatus.DONE ? r.final : r.error || r.final;
      const open = openRuns.has(r.run);
      const plain = (summary || "").replace(/[*#`>|]+/g, " ").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/\s+/g, " ").trim();
      let tr = `<tr class="click" data-run="${esc(r.run)}"><td class="num">${esc(r.run)}</td>${showTask ? `<td>${esc(r.task)}</td>` : ""}
        <td>${esc(N("seat", r.seat))} · ${esc(r.member)}<div class="sub2">${esc(N("run_mode", r.mode === V.RunMode.RESUME ? V.RunMode.RESUME : V.RunMode.NEW))}</div></td><td>${statusPill(r.status || "", "run_status")}${r.override ? ` <span class="pill warn">${esc(T("board.deviation"))}</span>` : ""}</td>
        <td class="num">${(r.started || "").slice(11, 16) || "—"}</td><td class="num">${dur(took)}<div class="sub2">${esc(T("board.steps_n", {n: r.steps || 0}))}</div></td><td class="num">${tok(r.tokens)}</td>
        <td><div class="clip">${esc(plain)}</div></td></tr>`;
      if (open) {
        tr += `<tr><td colspan="${cols}">
          <div class="meta">${esc(T("board.runs.session", {s: r.session || "—"}))}${r.continues ? ` · ${esc(T("board.runs.continues", {run: r.continues}))}` : ""}${r.ended ? ` · ${esc(T("board.runs.ended", {t: hm(r.ended)}))}` : ""}</div>
          <div class="meta" style="margin-top:6px">${esc(tokDetail(r.tokens))}</div>
          ${r.override ? `<div class="meta" style="margin-top:6px">${esc(T("board.runs.why"))}${esc(r.override)}${esc(T("sep.clause"))}${(r.deviations || []).map(esc).join(esc(T("sep.clause")))}</div>` : ""}
          <div class="meta" style="margin-top:6px">${esc(T("board.runs.brief"))}</div><pre class="out">${esc(r.prompt)}</pre>
          ${r.final ? `<div class="meta">${esc(T("board.runs.final"))}</div><pre class="out">${esc(r.final)}</pre>` : ""}
          ${r.error ? `<div class="meta">${esc(T("board.runs.error"))}</div><pre class="out">${esc(r.error)}</pre>` : ""}
        </td></tr>`;
      }
      return tr;
    }
  }

  // ---------- 归档页 ----------
  function doneDate(x) {
    const row = (x.flow || []).filter((r) => [ST.PASSED, ST.DONE].includes(r.state)).pop();
    return row ? strip(row.time || "") : "";
  }
  function renderArchiveGoals(d) {
    if (!d.goals.length) return card(esc(T("board.arch.goals")), `<div class="empty">${esc(T("board.arch.no_goals"))}</div>`);
    const goals = d.goals.slice().sort((a, b) => b.id.localeCompare(a.id, undefined, {numeric: true}));
    const focus = goals.find((g) => g.id === selGoal) || goals[0];
    const rows = goals.map((g) => {
      const runs = goalRuns(d, g);
      return `<div class="grow ${g.id === selGoal ? "on" : g.id === focus.id ? "auto" : ""}" data-goal="${esc(g.id)}">
        <div class="gname"><span class="tid">${esc(g.id)}</span><span class="tt">${esc(g.title)}</span>${statusPill(g.state || "—")}</div>
        <div class="gprog">${stageDots(g)}</div>
        <div class="gnow">${g.head.approval ? esc(NE(V.Edge.APPROVE) + T("sep.colon") + g.head.approval) : ""}</div>
        <div class="galert"></div>
        <div class="gcost">${runs.length ? `${esc(T("board.runs_n", {n: runs.length}))} · ${tok(sumTok(runs)).split(" ·")[0]}` : esc(T("board.arch.no_runs"))}</div>
      </div>`;
    }).join("");
    const body = `<div class="glist">${rows}</div><div class="gfocus"><div class="gfh"><b>${esc(focus.id)} ${esc(focus.title)}</b><span class="meta">${esc(T(d.view ? "board.arch.seq" : "board.arch.lanes"))} · ${esc(T("board.arch.archived"))}</span>
</div>
      ${d.view ? goalMain(d, focus) : renderLanes(d, focus)}</div>`;
    return card(esc(T("board.arch.goals")), body, {meta: esc(T("board.arch.goals_meta", {n: goals.length}))});
  }
  function renderArchiveTasks(d) {
    if (!d.cards.length) return card(esc(T("board.arch.tasks")), `<div class="empty">${esc(T("board.arch.no_tasks"))}</div>`);
    const runsBy = {};
    d.runs.forEach((r) => { (runsBy[r.task] = runsBy[r.task] || []).push(r); });
    const groups = {};
    d.cards.forEach((t) => { const k = t.goal || ""; (groups[k] = groups[k] || []).push(t); });
    const keys = Object.keys(groups).sort((a, b) => (a === "") - (b === "") || b.localeCompare(a, undefined, {numeric: true}));
    const html = keys.map((k) => {
      const g = d.goals.find((x) => x.id === k);
      const title = k ? `${esc(k)}${g ? " " + esc(g.title) : ""}` : esc(T("board.pick.loose"));
      return `<div class="tgroup"><h3>${title}<span class="n">${groups[k].length}</span></h3>${groups[k].map((t) => {
        const rs = runsBy[t.id] || [];
        const dd = doneDate(t);
        return `<div class="trow task ${openTask === t.id ? "open" : ""}" data-task="${esc(t.id)}">
          <span class="tid">${esc(t.id)}</span><span class="tt">${esc(t.title)}</span>
          <span class="tw">${esc(WHO(t.head.executor) || "—")} → ${esc(WHO(t.head.reviewer) || "—")}${dd ? ` · ${esc(T("board.arch.passed_on", {d: dd}))}` : ""}</span>${statusPill(t.state || "—")}
          <span class="tn">${rs.length ? esc(T("board.runs_n", {n: rs.length})) : ""}</span></div>` + (openTask === t.id ? renderTaskDetail(t, rs) : "");
      }).join("")}</div>`;
    }).join("");
    return card(esc(T("board.arch.tasks")), `<div class="tlist">${html}</div>`, {meta: esc(T("board.arch.tasks_meta", {n: d.cards.length}))});
  }
  function renderArchive(d) {
    const n = d.goals.length + d.cards.length + d.issues.length;
    const body = n ? `${renderArchiveGoals(d)}${renderIssues(d)}${renderArchiveTasks(d)}` : `<div class="empty">${esc(T("board.arch.empty"))}</div>`;
    return `<div class="strip"><span class="si">${esc(T("board.arch.goals"))} <b>${d.goals.length}</b></span><span class="si">${esc(N("kind", V.Kind.TASK))} <b>${d.cards.length}</b></span><span class="si">${esc(N("kind", V.Kind.ISSUE))} <b>${d.issues.length}</b></span><span class="si">${T("board.strip.runs", {n: `<b>${d.runs.length}</b>`})} · token <b>${tok(sumTok(d.runs)).split(" ·")[0]}</b></span></div>${body}`;
  }

  function render() {
    const d = data;
    document.title = d.name + " · " + T(ARCHIVE ? "board.archive" : "board.title");
    document.getElementById("name").textContent = d.name + (ARCHIVE ? " · " + T("board.archive") : "");
    const m = d.meta;
    const ac = d.archivedCount || {};
    const an = (ac.goals || 0) + (ac.tasks || 0) + (ac.issues || 0);
    const alink = !ARCHIVE && an ? `<a href="${U(`/p/${esc(id)}/archive`)}">${esc(T("board.archived", {what: [ac.goals && T("board.archived.goals", {n: ac.goals}), ac.tasks && T("board.archived.tasks", {n: ac.tasks}), ac.issues && T("board.archived.issues", {n: ac.issues})].filter(Boolean).join(T("sep.list"))}))} →</a>` : "";
    document.getElementById("meta").innerHTML = [m.status && NS(m.status), m.due && T("board.due", {d: m.due}), `<a href="${esc(d.progressHref)}">PROGRESS.md</a>`, alink]
      .filter(Boolean).map((x) => (x.startsWith("<a") ? x : esc(x))).join(" · ");
    if (ARCHIVE) { app.classList.add("archive"); app.innerHTML = renderArchive(d); return; }
    const cur = curPick(d);
    const pane = cur === "ideas" ? renderIdeasPane(d) : cur === "loose" ? renderLoosePane(d) : cur === "issues" ? renderIssues(d) : cur === "dec" ? renderDecPane(d) : renderGoalPane(d, cur);
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.draft : null;
    app.innerHTML = `${renderStrip(d)}${renderCheck(d)}<div class="row">${renderPending(d)}${renderNow(d)}</div>${renderRunning(d)}${renderPicker(d, cur)}${pane}`;
    if (d.view && d.view.titles) { applyTitles(app, d.view.titles); applyTitles(document.getElementById("meta"), d.view.titles); }
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
      const live = j.runs.some((x) => x.status === V.RunStatus.RUNNING);
      data = j;
      if (I18n.project(j.lang, j.names)) lastSig = "";  // 项目语言和称谓：读者没选过语言时跟着项目
      if (sig !== lastSig || live) render();
      lastSig = sig;
      const now = new Date().toLocaleTimeString(I18n.lang() === "zh" ? "zh-CN" : "en-GB", {hour12: false});
      document.getElementById("tick").textContent = SITE ? T("board.tick.static") : ARCHIVE ? T("board.tick.archive", {t: now}) : T("board.tick.live", {t: now});
    } catch (e) {
      document.getElementById("tick").textContent = T("board.tick.failed") + e.message;
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
    const ev = g && g.events.find((x) => x.project_seq === n);
    if (!ev) return;
    if (ev.layer === V.Kind.TASK && ev.stage != null) closedStages.delete(gid + ":" + ev.stage);
    if ((g.structure && g.structure.record || []).includes(n)) openRecord.add(gid);
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
    if (SITE) { apprMsg = T("board.appr.static"); render(); return; }
    if (act !== V.Edge.APPROVE && !body.text) { apprMsg = T("board.appr.write_first"); render(); return; }
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
      (g ? g.stages || [] : []).filter((x) => x.state === V.State.PASSED).forEach((x) => {
        const k = fa.dataset.foldall + ":" + x.order;
        fa.dataset.open === "1" ? closedStages.delete(k) : closedStages.add(k);
      });
      render(); return;
    }
    const fd = e.target.closest("[data-fold]");
    if (fd) { closedStages.has(fd.dataset.fold) ? closedStages.delete(fd.dataset.fold) : closedStages.add(fd.dataset.fold); render(); return; }
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
    back.textContent = "← " + T("board.project_board");
  }
  load().then(() => { if (ARCHIVE && openTask) document.querySelector(".task.open")?.scrollIntoView({block: "center"}); });
  if (!ARCHIVE && !SITE) setInterval(() => { if (document.visibilityState === "visible") load(); }, 5000);
})();
