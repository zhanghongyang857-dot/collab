// 朝会页（方案 03 第 6.4、10.4 节）：/p/<项目>/meet/<议题>。左栏是本项目的议题，右边是群聊式对话。
// 只画 /api/p/<项目>/meet/<议题> 给的数据；总裁的动作经 POST 同一路径写一条黑板事件，服务端走 flow.py 的检查，
// 总裁带 @ 的发言在后台叫醒相关成员（只有总裁的 @ 能叫醒人，成员写的 @ 只是普通文字）。每 3 秒刷新。
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
  const [, pid, iid] = SITE ? [null, SITE.project, SITE.issue] : location.pathname.match(/^\/p\/([0-9a-f]{8})\/meet\/(I\d+)/) || [];
  const $ = (x) => document.getElementById(x);
  const T = (k, v) => window.t(k, v);  // 界面文字（i18n.js）
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const fmtDur = (s) => (s == null ? "—" : s < 60 ? T("board.dur.s", {s}) : T("board.dur.ms", {m: Math.floor(s / 60), s: s % 60}));
  const fmtTok = (t) => (!t || !t.total ? T("meet.tok_unknown") : (I18n.lang() === "zh" ? (t.total >= 10000 ? (t.total / 10000).toFixed(1) + " 万" : t.total)
    : (t.total >= 1000 ? (t.total / 1000).toFixed(1) + "k" : t.total)) + " token");
  const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "");
  const COLORS = ["#1D9E75", "#7F77DD", "#D85A30", "#C98A06", "#2F7FC1", "#B04A8C"];
  let data = null, lastSig = "", priv = false, busy = false;

  const color = (who) => (who === V.Seat.OWNER ? "var(--accent)" : who === V.Seat.LEAD ? "#888780"
    : COLORS[Math.max(0, (data.issue.attendees || []).findIndex((a) => a.member === who)) % COLORS.length]);
  const av = (who, small) => `<span class="av${small ? " sm" : ""}" style="background:${color(who)}" title="${esc(who)}">${esc(String(who)[0] || "?")}</span>`;

  // 极简 Markdown：转义后处理标题、粗体、行内代码、@ 和换行；不执行任何 HTML
  function md(text, plainAt) {
    return esc(text).split("\n").map((l) => {
      const h = l.match(/^#{1,6}\s+(.*)$/);
      l = h ? `<b>${h[1]}</b>` : l;
      l = l.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
      return plainAt ? l : l.replace(/@([^\s@，。、,.:：；;！!？?()（）]+)/g, '<span class="at">@$1</span>');
    }).join("<br>");
  }

  const ST = V.State, E = V.Edge, MA = V.MeetAction;
  const STAGE_TIP = {
    get [ST.DRAFT]() { return T("meet.tip.draft"); },
    get [ST.DISCUSSING]() { return T("meet.tip.discussing"); },
    get [ST.CLOSING]() { return T("meet.tip.closing", {id: iid}); },
    get [ST.PENDING_RULING]() { return T("meet.tip.pending_ruling"); },
    get [ST.RULED]() { return N("state", ST.RULED); },
    get [ST.CANCELLED]() { return N("state", ST.CANCELLED); },
  };
  const PROC = new Proxy({}, {get: (o, e) => { const s = T("meet.proc." + String(e)); return s === "meet.proc." + String(e) ? undefined : s; }});  // 过程事件在时间线上的一句话
  const SHOW_NOTE = [E.PROGRESS, E.CHANGE];  // 这两类过程事件把说明直接写在时间线上;

  function render() {
    const d = data, i = d.issue;
    document.title = `${i.id} ${i.title} · ${T("board.seq.meeting")}`;
    $("back").href = U("/p/" + pid + "#issues");
    $("back").textContent = "← " + d.project.name;
    $("name").textContent = `${i.id} ${i.title}`;
    $("meta").textContent = `${T(i.type === V.IssueType.REVIEW_MEETING ? "board.seq.review_meeting" : "board.seq.meeting")}${d.goal ? ` · ${d.goal.id} ${d.goal.title}${T("sep.paren_open")}${N("state", d.goal.state)}${T("sep.paren_close")}` : " · " + T("board.issue.project_level")} · ${N("state", i.state)}`;
    $("rooms").innerHTML = `<div class="rh">${esc(d.project.name)} · ${esc(T("board.seq.meeting"))}</div>` + d.rooms.map((r) =>
      `<a class="room ${r.id === iid ? "on" : ""}" href="${U(`/p/${pid}/meet/${esc(r.id)}`)}"><div class="rt"><b>${esc(r.id)} ${esc(r.title)}</b><span class="pill ${r.stage === V.State.PENDING_RULING ? "warn" : r.stage === V.State.DISCUSSING ? "run" : ""}">${esc(N("state", r.stage))}</span></div>
        <div class="meta">${r.goal ? esc(r.goal) : esc(T("board.issue.project_level"))}${r.thinking.length ? " · " + esc(T("board.issue.thinking", {who: r.thinking.join(T("sep.list"))})) : r.last ? ` · ${esc(WHO(r.last.who))}${r.last.private ? esc(T("issue.private_mark")) : r.last.text ? esc(T("sep.colon") + r.last.text.slice(0, 18)) : ""}` : ""}</div></a>`).join("");
    const rd = (d.ready && d.ready.members) || {};
    const heads = i.attendees.map((a) => {
      const r = rd[a.member];
      const mark = r ? (r.ok ? `<span class="rdy ok" title="${esc(T("meet.ready_title", {t: hm(r.time), s: r.seconds}))}">${esc(T("disp.ready"))}</span>` : `<span class="rdy bad" title="${esc(r.error || "")}">${esc(T("disp.not_ready"))}</span>`) : "";
      const cur = d.runs.filter((x) => x.member === a.member).slice(-1)[0];
      const stBadge = cur && (cur.status === V.RunStatus.RUNNING || cur.state === V.RunPhase.FAILED) ? ` <span class="st st-${esc(cur.state)}">${esc(N("run_phase", cur.state))}</span>` : "";
      return `<span class="ahead">${av(a.member, true)}<span>${esc(a.member)}${mark}${stBadge}<span class="meta">${a.view ? " · " + esc(a.view) : ""}</span></span></span>`;
    }).join("");
    const canAdd = [ST.DRAFT, ST.DISCUSSING, ST.CLOSING, ST.PENDING_RULING].includes(i.state) && (d.pool || []).some((m) => m.ok && !i.attendees.some((a) => a.member === m.name));
    $("chead").innerHTML = `<div class="who">${heads}${canAdd ? `<button class="act" type="button" id="addbtn">${esc(T("meet.add"))}</button>` : ""}</div><div class="addpanel" id="addpanel" hidden></div><div class="tip">${esc(STAGE_TIP[i.state] || N("state", i.state))}</div>`;

    // 时间线：过程事件居中，消息是气泡；总裁在右
    const items = [...i.process.map((p) => ({p, k: p.project_seq})), ...i.messages.map((m) => ({m, k: m.project_seq}))].sort((a, b) => a.k - b.k);
    let html = items.map(({p, m}) => {
      if (p) {
        if (p.edge === V.Edge.CREATE) return `<div class="mid"><span>${esc(hm(p.time))} ${esc(T("meet.created", {who: WHO(V.Seat.LEAD)}))}</span></div>`;
        const extra = p.edge === V.Edge.SUMMARIZE ? summaryCard(i) : p.edge === V.Edge.RULE && i.ruling ? `<div class="ruling">${md(i.ruling.note)}</div>` : "";
        const label = SHOW_NOTE.includes(p.edge) && p.note ? p.note : (PROC[p.edge] || p.edge);
        return `<div class="mid"><span>${esc(hm(p.time))} ${esc(label)}</span></div>${extra}`;
      }
      const me = m.from === V.Seat.OWNER;
      const body = m.edge === V.Edge.PASS ? `<span class="meta">${esc(T("meet.pass"))}</span>` : md(m.body || "", !me);
      const tag = `<span class="ktag">${esc(N("speech", m.type))}</span>`;
      const lock = m.private ? ` · ${esc(T(me ? "meet.private_lead" : "meet.private_you"))}` : "";
      return `<div class="msg ${me ? "me" : ""}">${me ? "" : av(m.from)}<div class="mbody"><div class="mmeta">${me ? "" : esc(WHO(m.from)) + " · "}${esc(hm(m.time))} ${tag}${lock}</div>
        <div class="bub ${m.private ? "priv" : ""} ${m.edge === V.Edge.PASS ? "pass" : ""}">${body}</div></div></div>`;
    }).join("");
    // 正在跑的成员：状态、最近动作、已用时间、步数、用量，以及正在写的内容；可停止或让它收尾
    html += d.runs.filter((r) => r.status === V.RunStatus.RUNNING).map((r) => {
      const act = r.state === V.RunPhase.TOOL && r.last_action ? " · " + esc(r.last_action) : r.last_action && r.state !== V.RunPhase.STARTING ? " · " + esc(T("board.issue.latest")) + esc(r.last_action) : "";
      const stall = r.state === V.RunPhase.STALLED ? ` · <b>${esc(T(r.phase === V.RunPhase.TOOL ? "meet.stall_tool" : "meet.stall", {n: r.quiet}))}</b>` : "";
      const lim = r.wrap ? ` · ${esc(T("meet.wrapping", {why: r.wrap}))}` : "";
      const body = r.draft ? md(r.draft, true) + '<span class="caret"></span>' : '<span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>';
      return `<div class="msg live">${av(r.member)}<div class="mbody"><div class="mmeta"><span class="st st-${esc(r.state)}">${esc(N("run_phase", r.state))}</span> ${esc(r.member)}${act}${stall}${lim}</div>
        <div class="bub draft">${body}</div>
        <div class="runmeta">${esc(T("meet.used", {t: fmtDur(r.elapsed)}))} · ${esc(T("board.steps_n", {n: r.steps || 0}))} · ${fmtTok(r.tokens)}
          <button class="act" type="button" data-stop="${esc(r.member)}">${esc(N("meet_action", V.MeetAction.STOP))}</button><button class="act" type="button" data-wrap="${esc(r.member)}">${esc(T("meet.wrap"))}</button></div></div></div>`;
    }).join("");
    // 每位成员最近一次运行没成功的，写明原因；讨论中可以「补叫」（带上它错过的发言）
    const lastRun = {};
    d.runs.forEach((r) => { lastRun[r.member] = r; });
    const failed = Object.values(lastRun).filter((r) => [V.RunStatus.FAILED, V.RunStatus.LOST, V.RunStatus.STOPPED].includes(r.status));
    html += failed.map((r) => `<div class="mid fail"><span class="err">${esc(T(r.status === V.RunStatus.STOPPED ? "meet.stopped" : "meet.missed", {who: r.member, run: r.run}))}${esc(r.stop_reason || r.error || N("run_status", r.status))}</span>${i.state === V.State.DISCUSSING ? ` <button class="act" type="button" data-redo="${esc(r.member)}">${esc(N("meet_action", V.MeetAction.REDELIVER))}</button>` : ""}</div>`).join("");
    const tl = $("tl");
    const atBottom = tl.scrollHeight - tl.scrollTop - tl.clientHeight < 60;
    tl.innerHTML = html || `<div class="empty">${esc(T("meet.empty"))}</div>`;
    if (d.titles) applyTitles(tl, d.titles);
    if (atBottom || !lastSig) tl.scrollTop = tl.scrollHeight;

    // 输入区和动作按钮按状态切换
    const s = i.state, canSay = s === V.State.DISCUSSING;
    $("box").disabled = !canSay;
    $("send").disabled = !canSay;
    $("priv").disabled = !canSay;
    $("box").placeholder = canSay ? T("meet.ph.say", {id: iid}) : s === V.State.PENDING_RULING ? T("meet.ph.rule") : T("meet.ph.closed");
    if (s === V.State.PENDING_RULING) { $("box").disabled = false; }
    const btn = (act, label, cls = "") => `<button class="act ${cls}" data-act="${act}" type="button">${label}</button>`;
    $("acts").innerHTML = ({
      [ST.DRAFT]: btn(E.START, esc(T("meet.btn.start")), "primary") + btn(E.CANCEL, esc(T("meet.btn.cancel"))),
      [ST.DISCUSSING]: btn(E.END_DISCUSSION, esc(N("edge", E.END_DISCUSSION)), "primary"),
      [ST.CLOSING]: btn(E.CONTINUE_DISCUSSION, esc(N("edge", E.CONTINUE_DISCUSSION))),
      [ST.PENDING_RULING]: btn(E.RULE, esc(N("edge", E.RULE)), "primary") + btn(E.CONTINUE_DISCUSSION, esc(N("edge", E.CONTINUE_DISCUSSION))),
    })[s] || "";
    updHint();
  }

  function summaryCard(i) {
    if (!i.summary) return "";
    return `<div class="sumcard"><div><b>${esc(I18N.sections.summary)}</b> ${md(i.summary.note)}</div><div><b>${esc(N("event_field", "options"))}</b> ${md(i.summary.options)}</div><div><b>${esc(T("board.pend.recommended"))}</b> ${md(i.summary.recommendation)}</div></div>`;
  }

  // 称谓：与项目看板相同，只换显示文字
  function applyTitles(root, titles) {
    const keys = Object.keys(titles || {}).filter((k) => titles[k] && titles[k] !== k).sort((x, y) => y.length - x.length);
    if (!keys.length) return;
    const re = new RegExp(keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => { n.nodeValue = n.nodeValue.replace(re, (m) => titles[m]); });
  }

  // @ 菜单和提示
  const names = () => (data ? data.issue.attendees.map((a) => a.member).concat([V.Seat.LEAD]) : []);
  function mentions(t) {
    const out = [];
    (t.match(/@([^\s@，。、,.:：；;！!？?()（）]+)/g) || []).forEach((m) => {
      const n = names().find((x) => x.toLowerCase() === m.slice(1).toLowerCase());
      if (n && !out.includes(n)) out.push(n);
    });
    return out;
  }
  function updHint() {
    if (!data) return;
    const s = data.issue.state;
    if (s === V.State.PENDING_RULING) { $("hint").textContent = T("meet.hint.rule"); return; }
    if (s !== V.State.DISCUSSING) { $("hint").textContent = ""; return; }
    const ms = mentions($("box").value).filter((x) => x !== V.Seat.LEAD);
    $("hint").textContent = priv ? T("meet.hint.private") : ms.length ? T("meet.hint.wakes", {who: ms.join(T("sep.list"))}) : T("meet.hint.none");
  }
  $("box").addEventListener("input", () => {
    $("err").textContent = "";
    updHint();
    const box = $("box"), m = box.value.slice(0, box.selectionStart).match(/@([^\s@]*)$/);
    if (!m || data.issue.state !== V.State.DISCUSSING) { $("menu").hidden = true; return; }
    const q = m[1].toLowerCase();
    const opts = names().filter((n) => n.toLowerCase().startsWith(q));
    $("menu").innerHTML = opts.map((n) => `<div data-o="${esc(n)}">${av(n, true)}${esc(n)}</div>`).join("");
    $("menu").hidden = !opts.length;
  });
  $("menu").addEventListener("click", (e) => {
    const o = e.target.closest("[data-o]");
    if (!o) return;
    const box = $("box"), p = box.selectionStart;
    box.value = box.value.slice(0, p).replace(/@([^\s@]*)$/, "@" + o.dataset.o + " ") + box.value.slice(p);
    $("menu").hidden = true;
    box.focus();
    updHint();
  });
  $("priv").addEventListener("click", () => {
    priv = !priv;
    $("priv").classList.toggle("on", priv);
    $("priv").setAttribute("aria-pressed", String(priv));
    updHint();
  });
  $("box").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && data && data.issue.state === V.State.DISCUSSING) { e.preventDefault(); say(); }
  });
  $("send").addEventListener("click", say);
  // 加人：从班子里选名单外的可用成员；加进来后不叫醒，输入框预填 @他，总裁发出去才叫
  $("chead").addEventListener("click", (e) => {
    if (e.target.closest("#addbtn")) {
      const p = $("addpanel");
      const have = data.issue.attendees.map((a) => a.member);
      p.innerHTML = (data.pool || []).filter((m) => !have.includes(m.name)).map((m) =>
        `<button class="act ${m.ok ? "" : "off"}" type="button" data-add="${esc(m.name)}" ${m.ok ? "" : "disabled"} title="${esc(m.note || m.model || "")}">${esc(m.name)}${m.ok ? "" : esc(T("meet.unavailable"))}</button>`).join("") +
        `<span class="meta"> ${esc(T("meet.add_hint"))}</span>`;
      p.hidden = !p.hidden;
      return;
    }
    const b = e.target.closest("[data-add]");
    if (b) post({action: MA.ADD, members: [b.dataset.add]}).then((ok) => {
      if (ok) { $("box").value = ($("box").value + " @" + b.dataset.add + " ").trimStart(); $("box").focus(); updHint(); }
    });
  });
  $("tl").addEventListener("click", (e) => {
    const b = e.target.closest("[data-redo]");
    if (b) post({action: MA.REDELIVER, member: b.dataset.redo});
    const sp = e.target.closest("[data-stop]");
    if (sp) post({action: MA.STOP, member: sp.dataset.stop});
    const wr = e.target.closest("[data-wrap]");
    if (wr) post({action: MA.WRAP, member: wr.dataset.wrap});
  });
  $("acts").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act, text = $("box").value.trim();
    if (act === V.Edge.RULE && !text) { $("err").textContent = T("meet.err.rule_first"); return; }
    if (act === V.Edge.END_DISCUSSION && data.thinking.length && !confirm(T("meet.confirm.end", {who: data.thinking.join(T("sep.list"))}))) return;
    if (act === V.Edge.CANCEL && !confirm(T("meet.confirm.cancel"))) return;
    post({action: act, text}).then((ok) => { if (ok && act === V.Edge.RULE) $("box").value = ""; });
  });

  function say() {
    const text = $("box").value.trim();
    if (!text) { $("err").textContent = T("meet.err.empty"); return; }
    post({action: E.POST, text, private: priv}).then((ok) => {
      if (!ok) return;
      $("box").value = "";
      if (priv) $("priv").click();
      updHint();
    });
  }

  async function post(body) {
    if (busy) return false;
    if (SITE) { $("err").textContent = T("meet.err.static"); return false; }
    busy = true;
    $("err").textContent = "";
    try {
      const r = await fetch(`/api/p/${pid}/meet/${iid}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Board": "1"}, body: JSON.stringify(body)});
      const j = await r.json();
      if (j.error) { $("err").textContent = j.error; return false; }
      if (j.note) $("err").textContent = j.failed ? j.note : "";
      await load();
      return true;
    } catch (e) {
      $("err").textContent = T("meet.err.send") + e.message;
      return false;
    } finally {
      busy = false;
    }
  }

  async function load() {
    try {
      const j = await getJSON(`/api/p/${pid}/meet/${iid}`);
      if (j.error) throw new Error(j.error);
      const sig = JSON.stringify({...j, generated: 0});
      data = j;
      if (I18n.project(j.lang, j.names)) lastSig = "";  // 项目语言和称谓：读者没选过语言时跟着项目
      if (sig !== lastSig) render();
      lastSig = sig;
      $("tick").textContent = SITE ? T("board.tick.static") : T(data.runs.some((r) => r.status === V.RunStatus.RUNNING) ? "meet.tick.fast" : "meet.tick.slow") + new Date().toLocaleTimeString(I18n.lang() === "zh" ? "zh-CN" : "en-GB", {hour12: false});
    } catch (e) {
      $("tick").textContent = T("board.tick.failed") + e.message;
    }
  }
  if (!pid) { $("tl").innerHTML = `<div class="empty">${esc(T("meet.bad_url"))}</div>`; return; }
  load();
  if (SITE) return;
  // 有人在跑时约 1 秒刷新，否则 3 秒
  let last = 0;
  setInterval(() => {
    const running = data && data.runs.some((r) => r.status === V.RunStatus.RUNNING);
    if (document.visibilityState === "visible" && !busy && Date.now() - last >= (running ? 900 : 2900)) { last = Date.now(); load(); }
  }, 300);
})();
