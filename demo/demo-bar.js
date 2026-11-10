// 静态演示站顶上的回目条：第几回、上一回 / 下一回、回目录。只在 demo/site.py 导出的页面里加载。
// 换回时尽量停在同一种页面：项目页带着地址栏里的 #选中项，朝会页在那一回还没开的议题就回项目页。
(function () {
  const S = window.BOARD_STATIC;
  if (!S || !S.chapters) return;
  const n = S.chapter, list = S.chapters, cur = list[n - 1];
  const root = S.base + "/..";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  function where(k) {
    const c = list[k - 1], p = `${root}/ch${k}`;
    if (S.issue) return c.issues.includes(S.issue) ? `${p}/p/${S.project}/meet/${S.issue}/` : `${p}/p/${S.project}/#issues`;
    if (S.page === "team") return `${p}/team/`;
    return `${p}/p/${S.project}/${S.archive ? "archive/" : ""}${location.hash}`;
  }
  const bar = document.createElement("nav");
  bar.className = "demobar";
  bar.innerHTML = `<a class="home" href="${root}/">万历新政 · 演示</a>
    <span class="nav">${n > 1 ? `<a data-k="${n - 1}" href="${where(n - 1)}" title="${esc(list[n - 2].title)}">‹ 上一回</a>` : '<span class="off">‹ 上一回</span>'}
    <select aria-label="选回目">${list.map((c, i) => `<option value="${i + 1}"${i + 1 === n ? " selected" : ""}>${esc(c.title)}</option>`).join("")}</select>
    ${n < list.length ? `<a data-k="${n + 1}" href="${where(n + 1)}" title="${esc(list[n].title)}">下一回 ›</a>` : '<span class="off">下一回 ›</span>'}</span>
    <span class="see">${esc(cur.see)}</span>`;
  // 选中项可能在打开后变了（地址栏 #），点的时候再算去处
  bar.addEventListener("click", (e) => { const a = e.target.closest("a[data-k]"); if (a) a.href = where(+a.dataset.k); });
  bar.querySelector("select").addEventListener("change", (e) => { location.href = where(+e.target.value); });
  const style = document.createElement("style");
  style.textContent = `.demobar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;padding:8px 16px;background:#7a1f1f;color:#fbefe6;font-size:13px;line-height:1.5}
.demobar a{color:#fff;text-decoration:none}.demobar a:hover{text-decoration:underline}.demobar .home{font-weight:600;letter-spacing:.04em}
.demobar .nav{display:flex;gap:10px;align-items:center}.demobar .off{opacity:.45}
.demobar select{font:inherit;color:#7a1f1f;background:#fbefe6;border:0;border-radius:6px;padding:2px 6px;max-width:62vw}
.demobar .see{opacity:.85;flex:1 1 280px;min-width:0}`;
  document.head.appendChild(style);
  document.body.prepend(bar);
})();
