// 朝会页（方案 03 第 6.4、10.4 节）：/p/<项目>/meet/<议题>。左栏是本项目的议题，右边是群聊式对话。
// 只画 /api/p/<项目>/meet/<议题> 给的数据；总裁的动作经 POST 同一路径写一条黑板事件，服务端走 flow.py 的检查，
// 总裁带 @ 的发言在后台叫醒相关成员（只有总裁的 @ 能叫醒人，成员写的 @ 只是普通文字）。每 3 秒刷新。
(function () {
  const [, pid, iid] = location.pathname.match(/^\/p\/([0-9a-f]{8})\/meet\/(I\d+)/) || [];
  const $ = (x) => document.getElementById(x);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const fmtDur = (s) => (s == null ? "—" : s < 60 ? s + " 秒" : Math.floor(s / 60) + " 分 " + (s % 60) + " 秒");
  const fmtTok = (t) => (!t || !t.total ? "用量未知" : (t.total >= 10000 ? (t.total / 10000).toFixed(1) + " 万" : t.total) + " token");
  const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "");
  const COLORS = ["#1D9E75", "#7F77DD", "#D85A30", "#C98A06", "#2F7FC1", "#B04A8C"];
  let data = null, lastSig = "", priv = false, busy = false;

  const color = (who) => (who === "总裁" ? "var(--accent)" : who === "总管" ? "#888780"
    : COLORS[Math.max(0, (data.issue.与会 || []).findIndex((a) => a.成员 === who)) % COLORS.length]);
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

  const STAGE_TIP = {
    "起草": "总管还在准备（建议题、检查成员能否启动）；准备好会直接进入讨论中，也可以点「开始讨论」",
    "讨论中": "你在主持：只有你的 @ 能叫醒成员；不 @ 只记录。讨论完点「结束讨论」交给总管收尾",
    "收口中": "讨论已结束，等总管收口：在 Claude Desktop 说「收口 " + iid + "」",
    "待裁决": "总管已总结，等你裁决",
    "已裁决": "已裁决",
    "取消": "已取消",
  };
  const PROC = {"建立": "立题", "开始": "进入讨论 · 成员已到场，等你 @ 谁谁开口", "结束讨论": "讨论结束，交给总管收口",
    "继续讨论": "继续讨论", "总结": "总管总结", "裁决": "裁决", "取消": "取消", "变更": "与会名单调整"}
  const SHOW_NOTE = ["进展", "变更"];  // 这两类过程事件把说明直接写在时间线上;

  function render() {
    const d = data, i = d.issue;
    document.title = `${i.编号} ${i.标题} · 朝会`;
    $("back").href = "/p/" + pid + "#issues";
    $("back").textContent = "← " + d.project.name;
    $("name").textContent = `${i.编号} ${i.标题}`;
    $("meta").textContent = `${i.类型 === "会审" ? "框架会审" : "朝会"}${d.goal ? ` · ${d.goal.id} ${d.goal.title}（${d.goal.state}）` : " · 项目级"} · ${i.状态}`;
    $("rooms").innerHTML = `<div class="rh">${esc(d.project.name)} · 朝会</div>` + d.rooms.map((r) =>
      `<a class="room ${r.id === iid ? "on" : ""}" href="/p/${pid}/meet/${esc(r.id)}"><div class="rt"><b>${esc(r.id)} ${esc(r.title)}</b><span class="pill ${r.stage === "待裁决" ? "warn" : r.stage === "讨论中" ? "run" : ""}">${esc(r.stage)}</span></div>
        <div class="meta">${r.goal ? esc(r.goal) : "项目级"}${r.thinking.length ? " · " + esc(r.thinking.join("、")) + " 运行中" : r.last ? ` · ${esc(r.last.who)}${r.last.private ? "（私下）" : r.last.text ? "：" + esc(r.last.text.slice(0, 18)) : ""}` : ""}</div></a>`).join("");
    const rd = (d.ready && d.ready.members) || {};
    const heads = i.与会.map((a) => {
      const r = rd[a.成员];
      const mark = r ? (r.ok ? `<span class="rdy ok" title="${esc(hm(r.time))} 启动检查通过（${r.seconds} 秒）">就绪</span>` : `<span class="rdy bad" title="${esc(r.error || "")}">未就绪</span>`) : "";
      const cur = d.runs.filter((x) => x.member === a.成员).slice(-1)[0];
      const stBadge = cur && (cur.status === "运行中" || cur.state === "失败") ? ` <span class="st st-${esc(cur.state)}">${esc(cur.state)}</span>` : "";
      return `<span class="ahead">${av(a.成员, true)}<span>${esc(a.成员)}${mark}${stBadge}<span class="meta">${a.视角 ? " · " + esc(a.视角) : ""}</span></span></span>`;
    }).join("");
    const canAdd = ["起草", "讨论中", "收口中", "待裁决"].includes(i.状态) && (d.pool || []).some((m) => m.ok && !i.与会.some((a) => a.成员 === m.name));
    $("chead").innerHTML = `<div class="who">${heads}${canAdd ? '<button class="act" type="button" id="addbtn">＋加人</button>' : ""}</div><div class="addpanel" id="addpanel" hidden></div><div class="tip">${esc(STAGE_TIP[i.状态] || i.状态)}</div>`;

    // 时间线：过程事件居中，消息是气泡；总裁在右
    const items = [...i.过程.map((p) => ({p, k: p.项目序})), ...i.消息.map((m) => ({m, k: m.项目序}))].sort((a, b) => a.k - b.k);
    let html = items.map(({p, m}) => {
      if (p) {
        if (p.边 === "建立") return `<div class="mid"><span>${esc(hm(p.时间))} 总管立题</span></div>`;
        const extra = p.边 === "总结" ? summaryCard(i) : p.边 === "裁决" && i.裁决 ? `<div class="ruling">${md(i.裁决.说明)}</div>` : "";
        const label = SHOW_NOTE.includes(p.边) && p.说明 ? p.说明 : (PROC[p.边] || p.边);
        return `<div class="mid"><span>${esc(hm(p.时间))} ${esc(label)}</span></div>${extra}`;
      }
      const me = m.发起 === "总裁";
      const body = m.边 === "PASS" ? '<span class="meta">没有要补充的（PASS）</span>' : md(m.正文 || "", !me);
      const tag = `<span class="ktag">${esc(m.类型)}</span>`;
      const lock = m.私下 ? ` · ${me ? "只有总管能看到" : "只有你和总管能看到"}` : "";
      return `<div class="msg ${me ? "me" : ""}">${me ? "" : av(m.发起)}<div class="mbody"><div class="mmeta">${me ? "" : esc(m.发起) + " · "}${esc(hm(m.时间))} ${tag}${lock}</div>
        <div class="bub ${m.私下 ? "priv" : ""} ${m.边 === "PASS" ? "pass" : ""}">${body}</div></div></div>`;
    }).join("");
    // 正在跑的成员：状态、最近动作、已用时间、步数、用量，以及正在写的内容；可停止或让它收尾
    html += d.runs.filter((r) => r.status === "运行中").map((r) => {
      const act = r.state === "调用工具" && r.last_action ? " · " + esc(r.last_action) : r.last_action && r.state !== "启动中" ? " · 最近：" + esc(r.last_action) : "";
      const stall = r.state === "疑似卡住" ? ` · <b>${r.phase === "调用工具" ? `工具 ${r.quiet} 秒没有新输出` : `${r.quiet} 秒没有动静`}</b>` : "";
      const lim = r.收尾 ? ` · 收尾中（${esc(r.收尾)}）` : "";
      const body = r.draft ? md(r.draft, true) + '<span class="caret"></span>' : '<span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>';
      return `<div class="msg live">${av(r.member)}<div class="mbody"><div class="mmeta"><span class="st st-${esc(r.state)}">${esc(r.state)}</span> ${esc(r.member)}${act}${stall}${lim}</div>
        <div class="bub draft">${body}</div>
        <div class="runmeta">已用 ${fmtDur(r.elapsed)} · ${r.steps || 0} 步 · ${fmtTok(r.tokens)}
          <button class="act" type="button" data-stop="${esc(r.member)}">停止</button><button class="act" type="button" data-wrap="${esc(r.member)}">让它收尾</button></div></div></div>`;
    }).join("");
    // 每位成员最近一次运行没成功的，写明原因；讨论中可以「补叫」（带上它错过的发言）
    const lastRun = {};
    d.runs.forEach((r) => { lastRun[r.member] = r; });
    const failed = Object.values(lastRun).filter((r) => ["失败", "异常结束", "已中断"].includes(r.status));
    html += failed.map((r) => `<div class="mid fail"><span class="err">${esc(r.member)} ${r.status === "已中断" ? "被停止了" : "没叫到"}（${esc(r.run)}）：${esc(r.stop_reason || r.error || r.status)}</span>${i.状态 === "讨论中" ? ` <button class="act" type="button" data-redo="${esc(r.member)}">补叫</button>` : ""}</div>`).join("");
    const tl = $("tl");
    const atBottom = tl.scrollHeight - tl.scrollTop - tl.clientHeight < 60;
    tl.innerHTML = html || '<div class="empty">还没有发言</div>';
    if (d.称谓) applyTitles(tl, d.称谓);
    if (atBottom || !lastSig) tl.scrollTop = tl.scrollHeight;

    // 输入区和动作按钮按状态切换
    const s = i.状态, canSay = s === "讨论中";
    $("box").disabled = !canSay;
    $("send").disabled = !canSay;
    $("priv").disabled = !canSay;
    $("box").placeholder = canSay ? `发给 ${iid} · 输入 @ 叫人；回车发送，Shift+回车换行` : s === "待裁决" ? "写下你的裁决（你的原话会记作依据），点「裁决」" : "现在不能发言";
    if (s === "待裁决") { $("box").disabled = false; }
    const btn = (act, label, cls = "") => `<button class="act ${cls}" data-act="${act}" type="button">${label}</button>`;
    $("acts").innerHTML = ({
      "起草": btn("开始", "开始讨论", "primary") + btn("取消", "取消议题"),
      "讨论中": btn("结束讨论", "结束讨论", "primary"),
      "收口中": btn("继续讨论", "继续讨论"),
      "待裁决": btn("裁决", "裁决", "primary") + btn("继续讨论", "继续讨论"),
    })[s] || "";
    updHint();
  }

  function summaryCard(i) {
    if (!i.总结) return "";
    return `<div class="sumcard"><div><b>总结</b> ${md(i.总结.说明)}</div><div><b>方案</b> ${md(i.总结.方案)}</div><div><b>总管建议</b> ${md(i.总结.建议)}</div></div>`;
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
  const names = () => (data ? data.issue.与会.map((a) => a.成员).concat(["总管"]) : []);
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
    const s = data.issue.状态;
    if (s === "待裁决") { $("hint").textContent = "裁决写进事件，依据是你的原话"; return; }
    if (s !== "讨论中") { $("hint").textContent = ""; return; }
    const ms = mentions($("box").value).filter((x) => x !== "总管");
    $("hint").textContent = priv ? "私下：只有总管能看到，不叫醒任何人" : ms.length ? "会叫醒 " + ms.join("、") : "不 @ 只记录，不叫醒人";
  }
  $("box").addEventListener("input", () => {
    $("err").textContent = "";
    updHint();
    const box = $("box"), m = box.value.slice(0, box.selectionStart).match(/@([^\s@]*)$/);
    if (!m || data.issue.状态 !== "讨论中") { $("menu").hidden = true; return; }
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
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && data && data.issue.状态 === "讨论中") { e.preventDefault(); say(); }
  });
  $("send").addEventListener("click", say);
  // 加人：从班子里选名单外的可用成员；加进来后不叫醒，输入框预填 @他，总裁发出去才叫
  $("chead").addEventListener("click", (e) => {
    if (e.target.closest("#addbtn")) {
      const p = $("addpanel");
      const have = data.issue.与会.map((a) => a.成员);
      p.innerHTML = (data.pool || []).filter((m) => !have.includes(m.name)).map((m) =>
        `<button class="act ${m.ok ? "" : "off"}" type="button" data-add="${esc(m.name)}" ${m.ok ? "" : "disabled"} title="${esc(m.note || m.model || "")}">${esc(m.name)}${m.ok ? "" : "（不可用）"}</button>`).join("") +
        '<span class="meta"> 加进来后能看到之前的公开发言，看不到私下发言；你 @ 他才会开口</span>';
      p.hidden = !p.hidden;
      return;
    }
    const b = e.target.closest("[data-add]");
    if (b) post({action: "加人", members: [b.dataset.add]}).then((ok) => {
      if (ok) { $("box").value = ($("box").value + " @" + b.dataset.add + " ").trimStart(); $("box").focus(); updHint(); }
    });
  });
  $("tl").addEventListener("click", (e) => {
    const b = e.target.closest("[data-redo]");
    if (b) post({action: "补叫", member: b.dataset.redo});
    const sp = e.target.closest("[data-stop]");
    if (sp) post({action: "停止", member: sp.dataset.stop});
    const wr = e.target.closest("[data-wrap]");
    if (wr) post({action: "收尾", member: wr.dataset.wrap});
  });
  $("acts").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act, text = $("box").value.trim();
    if (act === "裁决" && !text) { $("err").textContent = "先在输入框写下裁决"; return; }
    if (act === "结束讨论" && data.thinking.length && !confirm(`${data.thinking.join("、")} 还在思考，结束后他们的发言写不进来。仍然结束？`)) return;
    if (act === "取消" && !confirm("取消这个议题？")) return;
    post({action: act, text}).then((ok) => { if (ok && act === "裁决") $("box").value = ""; });
  });

  function say() {
    const text = $("box").value.trim();
    if (!text) { $("err").textContent = "先写点什么"; return; }
    post({action: "发言", text, private: priv}).then((ok) => {
      if (!ok) return;
      $("box").value = "";
      if (priv) $("priv").click();
      updHint();
    });
  }

  async function post(body) {
    if (busy) return false;
    busy = true;
    $("err").textContent = "";
    try {
      const r = await fetch(`/api/p/${pid}/meet/${iid}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Board": "1"}, body: JSON.stringify(body)});
      const j = await r.json();
      if (j.error) { $("err").textContent = j.error; return false; }
      if (j.note) $("err").textContent = /没能/.test(j.note) ? j.note : "";
      await load();
      return true;
    } catch (e) {
      $("err").textContent = "没发出去：" + e.message;
      return false;
    } finally {
      busy = false;
    }
  }

  async function load() {
    try {
      const r = await fetch(`/api/p/${pid}/meet/${iid}`, {cache: "no-store"});
      const j = await r.json();
      if (j.error) throw new Error(j.error);
      const sig = JSON.stringify({...j, generated: 0});
      data = j;
      if (sig !== lastSig) render();
      lastSig = sig;
      $("tick").textContent = (data.runs.some((r) => r.status === "运行中") ? "有人在跑，每秒刷新 · " : "每 3 秒刷新 · ") + new Date().toLocaleTimeString("zh-CN", {hour12: false});
    } catch (e) {
      $("tick").textContent = "刷新失败：" + e.message;
    }
  }
  if (!pid) { $("tl").innerHTML = '<div class="empty">地址不对：应为 /p/&lt;项目&gt;/meet/&lt;议题&gt;</div>'; return; }
  load();
  // 有人在跑时约 1 秒刷新，否则 3 秒
  let last = 0;
  setInterval(() => {
    const running = data && data.runs.some((r) => r.status === "运行中");
    if (document.visibilityState === "visible" && !busy && Date.now() - last >= (running ? 900 : 2900)) { last = Date.now(); load(); }
  }, 300);
})();
