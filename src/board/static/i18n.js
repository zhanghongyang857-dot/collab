// Board language: ?lang= → localStorage → the project's language → the toolkit default.
// vocab.js ships both packs (window.I18N_PACKS); this picks one, exposes t(key, vars) and I18n.name(kind, code),
// fills elements marked data-i18n / data-i18n-title / data-i18n-placeholder, and adds the 中 / EN switch to the header.
(function () {
  const packs = window.I18N_PACKS || {};
  const ok = (x) => x === "zh" || x === "en";
  const KEY = "board.lang";
  const query = new URLSearchParams(location.search).get("lang");
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { saved = null; }
  const explicit = ok(query) ? query : ok(saved) ? saved : null;  // the reader chose; the project's language doesn't override it
  let lang = explicit || (ok(window.BOARD_LANG) ? window.BOARD_LANG : "en");
  let overrides = {};  // the project's config.json "names", "sections" and "text", e.g. the demo's Ming titles

  function merged(l) {
    const p = packs[l] || packs.en || {names: {}, sections: {}, fields: {}, text: {}};
    const on = overrides.names || {}, names = {};
    for (const k of Object.keys(p.names || {})) names[k] = {...p.names[k], ...(on[k] || {})};
    return {...p, names, sections: {...p.sections, ...(overrides.sections || {})}, text: {...p.text, ...(overrides.text || {})}};
  }

  function use(l) {
    lang = ok(l) ? l : "en";
    window.I18N = merged(lang);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    apply(document);
    const sw = document.getElementById("langsw");
    if (sw) sw.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.lang === lang));
  }

  const SINGULAR = /(?<![\d.,])1(<\/\w+>)? (goal|task|run|post|step|day|hour|minute|second|error|warning|question|call|row|record|issue|event|card|slot|member|item|attempt|round|file|stage|decision)s\b/g;

  function t(key, vars) {
    let s = ((window.I18N || {}).text || {})[key];
    if (s == null || s === "") s = ((packs.en || {}).text || {})[key];
    if (s == null) s = key;
    if (!vars) return s;
    s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
    return lang === "en" ? s.replace(SINGULAR, "1$1 $2") : s;  // "1 goals" → "1 goal"
  }

  function name(kind, code) {
    if (code == null || code === "") return "";
    return ((window.I18N.names || {})[kind] || {})[code] || code;
  }

  function apply(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    root.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  }

  // The page reports the project's language (and name overrides) once its data arrives; returns true if the board switched.
  function project(l, names) {
    const next = explicit || (ok(l) ? l : lang);
    if (next === lang && JSON.stringify(names || {}) === JSON.stringify(overrides)) return false;
    overrides = names || {};
    use(next);
    return true;
  }

  function choose(l) {
    try { localStorage.setItem(KEY, l); } catch (e) { /* private mode: only this page */ }
    const u = new URL(location.href);
    u.searchParams.delete("lang");
    location.replace(u.toString());
  }

  function addSwitch() {
    const top = document.querySelector("header.top") || document.querySelector("header") || document.body;
    if (!top || document.getElementById("langsw")) return;
    const sw = document.createElement("span");
    sw.id = "langsw";
    sw.className = "langsw";
    sw.innerHTML = '<button type="button" data-lang="zh" lang="zh-CN">中</button><span>/</span><button type="button" data-lang="en" lang="en">EN</button>';
    sw.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { if (b.dataset.lang !== lang || !explicit) choose(b.dataset.lang); }));
    top.appendChild(sw);
    use(lang);
  }

  // 项目一行摘要：新结构项目给结构化的 alerts（按语言拼），旧结构项目给服务端写好的一句
  function summary(p) {
    if (!p.alerts) return p.summary || "";
    const C = "①②③④⑤⑥⑦⑧⑨⑩";
    return p.alerts.map((a) => a.kind === "stage" ? `${a.id} ${C[a.no - 1] || a.no}/${a.of}` : a.kind === "blocked" ? `${a.id} ${name("state", "blocked")}`
      : a.kind === "pending_ruling" ? `${a.id} ${name("state", "pending_ruling")}` : `${a.id} ${t("srv.await_complete")}`).join(" · ");
  }
  const blocked = (p) => (p.alerts ? p.alerts.some((a) => a.kind === "blocked") : /受阻/.test(p.summary || ""));  // 旧结构的摘要是中文原文

  window.t = t;
  window.I18n_summary = summary;
  window.I18n_blocked = blocked;
  window.I18n = {t, name, apply, project, use, lang: () => lang, explicit: () => explicit};
  window.N = name;
  window.WHO = (x) => (x ? (((window.I18N.names || {}).seat || {})[x] || (x === "none" ? name("seat_class", "none") : x)) : "");
  use(lang);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addSwitch);
  else addSwitch();
})();
