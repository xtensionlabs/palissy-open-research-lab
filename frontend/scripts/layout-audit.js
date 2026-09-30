// Paste into the browser console (or run via Playwright's evaluate) on any Palissy page.
// Reports: sideways scroll, text clipped by overflow, and text boxes that overlap each other.
() => {
  const issues = [];
  const de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + 1) issues.push(`page scrolls sideways: ${de.scrollWidth} > ${de.clientWidth}`);

  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0.05;
  };
  const label = (el) => `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.split(" ").filter(Boolean)[0] : ""}:"${(el.textContent || "").trim().slice(0, 28)}"`;

  // 1. text clipped by overflow
  for (const el of document.querySelectorAll("body *")) {
    if (!visible(el)) continue;
    const cs = getComputedStyle(el);
    if (["hidden", "clip"].includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 2 && (el.textContent || "").trim()) {
      issues.push(`clipped x: ${label(el)} (${el.scrollWidth} > ${el.clientWidth})`);
    }
  }

  // 2. overlapping text boxes from unrelated elements
  const boxes = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (!n.textContent.trim()) continue;
    const el = n.parentElement;
    if (!el || !visible(el) || el.closest("[hidden],script,style,pre.code")) continue;
    // skip text inside scrollable containers that are not on screen
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.width < 2 || r.height < 2) continue;
      boxes.push({ el, r: { l: r.left, t: r.top, rr: r.right, b: r.bottom } });
    }
  }
  // A position:fixed layer (the provenance drawer on narrow screens) sits above the page by
  // design, so text in it is not a collision with text underneath.
  const inFixed = (el) => { for (let n = el; n && n !== document.body; n = n.parentElement) if (getComputedStyle(n).position === "fixed") return true; return false; };
  for (const b of boxes) b.fixed = inFixed(b.el);
  const seen = new Set();
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      if (a.fixed !== b.fixed) continue;
      const w = Math.min(a.r.rr, b.r.rr) - Math.max(a.r.l, b.r.l);
      const h = Math.min(a.r.b, b.r.b) - Math.max(a.r.t, b.r.t);
      if (w > 3 && h > 3) {
        const key = label(a.el) + "|" + label(b.el);
        if (!seen.has(key)) { seen.add(key); issues.push(`overlap: ${label(a.el)}  x  ${label(b.el)} (${Math.round(w)}x${Math.round(h)}px)`); }
      }
    }
    if (issues.length > 25) break;
  }
  return { width: innerWidth, issues: issues.slice(0, 25), count: issues.length };
}
