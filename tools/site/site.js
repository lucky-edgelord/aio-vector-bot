/* Vectiq docs: search, copy buttons, mobile menu, the "on this page" highlight and the home page chat. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // mobile navigation
  const menu = $(".menu");
  if (menu) {
    menu.addEventListener("click", () => {
      const open = document.body.classList.toggle("nav-open");
      menu.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (e) => {
      if (document.body.classList.contains("nav-open") && !e.target.closest(".side") && !e.target.closest(".menu")) {
        document.body.classList.remove("nav-open");
        menu.setAttribute("aria-expanded", "false");
      }
    });
  }

  // copy buttons
  document.addEventListener("click", async (e) => {
    const b = e.target.closest(".copy");
    if (!b) return;
    const code = $("pre", b.parentElement);
    try { await navigator.clipboard.writeText(code.innerText.replace(/\n$/, "")); } catch { return; }
    b.textContent = "Copied"; b.classList.add("done");
    setTimeout(() => { b.textContent = "Copy"; b.classList.remove("done"); }, 1400);
  });

  // keep the active heading highlighted in "On this page"
  const links = $$(".toc a");
  if (links.length && "IntersectionObserver" in window) {
    const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    const seen = new Set();
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) en.isIntersecting ? seen.add(en.target.id) : seen.delete(en.target.id);
      const first = [...byId.keys()].find((id) => seen.has(id));
      if (first) links.forEach((a) => a.classList.toggle("on", a === byId.get(first)));
    }, { rootMargin: "-70px 0px -65% 0px" });
    byId.forEach((_, id) => { const h = document.getElementById(id); if (h) io.observe(h); });
  }

  // search
  const input = $("#q"), box = $("#results");
  let index = null, loading = null, hits = [], cursor = -1;
  const load = () => loading || (loading = fetch(new URL("search.json", document.currentScript ? document.currentScript.src : location.href))
    .then((r) => r.json()).then((d) => (index = d)).catch(() => (index = [])));
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const words = (q) => q.toLowerCase().split(/[^a-z0-9!.]+/).filter(Boolean);
  function search(q) {
    const ws = words(q);
    if (!ws.length) return [];
    const out = [];
    for (const p of index) for (const s of p.s) {
      const head = s.h.toLowerCase(), title = p.t.toLowerCase(), text = s.t.toLowerCase();
      let score = 0, ok = true;
      for (const w of ws) {
        let m = 0;
        if (head.includes(w)) m += head.startsWith(w) ? 9 : 6;
        if (title.includes(w)) m += 4;
        if (text.includes(w)) m += 1 + Math.min(3, text.split(w).length - 2) * 0.3;
        if (!m) { ok = false; break; }
        score += m;
      }
      if (ok) out.push({ p, s, score: score + (s.id ? 0 : 1) });
    }
    return out.sort((a, b) => b.score - a.score).slice(0, 8);
  }
  function snippet(text, ws) {
    const low = text.toLowerCase();
    let at = -1;
    for (const w of ws) { at = low.indexOf(w); if (at >= 0) break; }
    const from = Math.max(0, at - 40);
    let out = esc(text.slice(from, from + 150));
    for (const w of ws) out = out.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
    return (from ? "…" : "") + out;
  }
  function show() {
    const q = input.value.trim();
    if (!q || !index) { box.hidden = true; return; }
    hits = search(q); cursor = -1;
    const ws = words(q);
    box.innerHTML = hits.length
      ? hits.map((h, i) => `<a href="${h.p.u}${h.s.id ? "#" + h.s.id : ""}" role="option" data-i="${i}"><small>${esc(h.p.g)} / ${esc(h.p.t)}</small><b>${esc(h.s.h)}</b><span>${snippet(h.s.t, ws)}</span></a>`).join("")
      : `<p>Nothing matches “${esc(q)}”. Try a command name or a setting.</p>`;
    box.hidden = false;
  }
  function move(d) {
    const items = $$("a", box); if (!items.length) return;
    cursor = (cursor + d + items.length) % items.length;
    items.forEach((a, i) => a.setAttribute("aria-selected", String(i === cursor)));
    items[cursor].scrollIntoView({ block: "nearest" });
  }
  if (input) {
    input.addEventListener("focus", () => load().then(show));
    input.addEventListener("input", () => load().then(show));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") { const a = $$("a", box)[Math.max(cursor, 0)]; if (a) location.href = a.href; }
      else if (e.key === "Escape") { box.hidden = true; input.blur(); }
    });
    document.addEventListener("click", (e) => { if (!e.target.closest(".search")) box.hidden = true; });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
    });
  }

  // home: a header that gains a background once you scroll
  const top = $(".top");
  if (document.body.classList.contains("home") && top) {
    const onScroll = () => top.classList.toggle("stuck", scrollY > 24);
    onScroll(); addEventListener("scroll", onScroll, { passive: true });
  }

  // home: the chat plays once, a command is typed and the bot answers
  const typed = $("#typed");
  if (typed) {
    const steps = $$("[data-step]", $(".chat"));
    const text = "!event create Game night | friday 8pm | 2h | Bring snacks";
    const showAll = () => {
      steps.forEach((s) => s.classList.add("in"));
      $$("[data-n]").forEach((e) => (e.textContent = e.dataset.n));
      typed.textContent = "";
    };
    if (reduced || !("IntersectionObserver" in window)) { showAll(); }
    else {
      let started = false;
      const go = () => {
        if (started) return; started = true;
        let i = 0;
        const type = () => {
          typed.textContent = text.slice(0, ++i);
          if (i < text.length) return setTimeout(type, 26 + Math.random() * 30);
          setTimeout(() => {
            typed.textContent = "";
            const reveal = (n) => steps.filter((s) => s.dataset.step === String(n)).forEach((s) => s.classList.add("in"));
            reveal(1);
            setTimeout(() => reveal(2), 900);
            setTimeout(() => reveal(3), 1900);
            setTimeout(() => {
              reveal(4);
              $$("[data-n]").forEach((e) => {
                const n = +e.dataset.n; let c = 0;
                const tick = () => { e.textContent = c; if (c++ < n) setTimeout(tick, 260); };
                tick();
              });
            }, 3000);
          }, 380);
        };
        setTimeout(type, 500);
      };
      new IntersectionObserver((en, o) => { if (en[0].isIntersecting) { go(); o.disconnect(); } }, { threshold: 0.35 }).observe($(".chat"));
    }
  }
})();
