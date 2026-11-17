/* Vectiq dashboard. No build step, no framework: a tiny DOM helper, a hash router and one function per page.
   Everything shown comes from /api; nothing user-supplied is ever put into innerHTML. */
"use strict";

const root = document.getElementById("app");
const S = { me: null, gid: null, meta: null, route: [], dirty: null };

/* ---------------------------------------------------------------- DOM helpers */

function h(tag, attrs, ...kids) {
  const svg = tag.startsWith("svg:");
  const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4)) : document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.setAttribute("class", Array.isArray(v) ? v.filter(Boolean).join(" ") : v);
      else if (k === "style") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else if (k === "value" && !svg) el.value = v;
      else if (k === "checked" || k === "disabled" || k === "selected") el[k] = !!v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  add(el, kids);
  return el;
}
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
function clear(el, ...kids) { el.replaceChildren(); return add(el, kids); }
const fmt = (n) => (n === null || n === undefined ? "–" : Number(n).toLocaleString());
const plural = (n, w) => `${fmt(n)} ${w}${n === 1 ? "" : "s"}`;

function rel(ts) {
  if (!ts) return "–";
  const d = ts - Date.now() / 1000, a = Math.abs(d);
  const [n, u] = a < 60 ? [a, "s"] : a < 3600 ? [a / 60, "m"] : a < 86400 ? [a / 3600, "h"] : [a / 86400, "d"];
  const t = `${Math.max(1, Math.round(n))}${u}`;
  return d < 0 ? `${t} ago` : `in ${t}`;
}
function when(ts) { return ts ? new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "–"; }
function initials(name) { return (name || "?").replace(/^npub1/, "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?"; }

function avatar(p, size = "") {
  const fallback = () => h("div", { class: ["avatar", size], title: p.name }, initials(p.name));
  if (!p.avatar) return fallback();
  const img = h("img", { class: ["avatar", size], src: p.avatar, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
  img.addEventListener("error", () => img.replaceWith(fallback()), { once: true });
  return img;
}
function who(p, sub) {
  return h("div", { class: "who" }, avatar(p, "sm"),
    h("div", { class: "grow" }, h("div", { class: "n" }, p.name), sub ? h("div", { class: "id" }, sub) : null));
}
function rolePill(r) {
  const dot = h("i");
  if (r.color) dot.style.background = r.color;
  return h("span", { class: "role" }, dot, r.name);
}
function pill(text, kind) { return h("span", { class: ["pill", kind] }, text); }
function empty(text) { return h("div", { class: "empty" }, h("div", { class: "mark" }, h("i")), h("div", null, text)); }
function card(title, ...body) {
  return h("section", { class: "card" }, title ? h("header", null, typeof title === "string" ? h("h2", null, title) : title) : null, body);
}
function stat(k, v, s, accent) { return h("div", { class: ["stat", accent && "accent"] }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), s ? h("div", { class: "s" }, s) : null); }
function btn(label, onclick, kind = "", extra = {}) { return h("button", { class: ["btn", kind], type: "button", onclick, ...extra }, label); }

/* ---------------------------------------------------------------- API, toasts, dialogs */

class ApiError extends Error {}
async function api(method, path, body) {
  const opts = { method, credentials: "same-origin", headers: { "X-Requested-With": "vectiq" } };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); } catch { throw new ApiError("Can't reach the bot. Is it running?"); }
  if (res.status === 401 && !path.startsWith("/api/auth")) { S.me = null; showLogin(); throw new ApiError("Please sign in."); }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : {};
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : `Something went wrong (${res.status}).`);
  return data;
}
const C = (p) => `/api/c/${encodeURIComponent(S.gid)}${p}`;

function toast(text, err = false) {
  const t = h("div", { class: ["toast", err && "err"], role: err ? "alert" : "status" }, text);
  document.getElementById("toasts").appendChild(t);
  setTimeout(() => t.remove(), err ? 7000 : 4000);
}
async function run(button, fn) {
  if (button) button.classList.add("busy");
  try { const r = await fn(); if (r && r.message) toast(r.message); return r; }
  catch (e) { toast(e.message, true); throw e; }
  finally { if (button) button.classList.remove("busy"); }
}

function overlay(inner, onclose) {
  const scrim = h("div", { class: "scrim" }, inner);
  const close = () => { scrim.remove(); document.removeEventListener("keydown", esc); onclose && onclose(); };
  const esc = (e) => e.key === "Escape" && close();
  scrim.addEventListener("mousedown", (e) => e.target === scrim && close());
  document.addEventListener("keydown", esc);
  document.body.appendChild(scrim);
  return close;
}
function modal(title, body, actions = [], onclose = null) {
  let close;
  const foot = h("footer", null, btn("Cancel", () => close(), "ghost"), actions.map((a) => {
    const b = btn(a.label, async () => {
      try { await run(b, a.run); close(); a.after && a.after(); } catch { /* toast shown */ }
    }, a.kind || "primary");
    return b;
  }));
  const m = h("div", { class: "modal", role: "dialog", "aria-modal": "true" },
    h("header", null, h("h2", null, title), h("button", { class: "btn ghost sm right", type: "button", onclick: () => close(), "aria-label": "Close" }, "✕")),
    body, actions.length ? foot : null);
  close = overlay(m, onclose);
  setTimeout(() => m.querySelector("input, select, textarea")?.focus(), 30);
  return close;
}
function confirmBox(title, text, label = "Confirm", kind = "danger") {
  return new Promise((resolve) => {
    let done = false;
    modal(title, h("p", { class: "muted" }, text), [{ label, kind, run: async () => { done = true; } }], () => resolve(done));
  });
}
function drawer(content) { return overlay(h("aside", { class: "drawer" }, content)); }

function field(label, input, help) { return h("label", { class: "f" }, label, input, help ? h("span", { class: "help" }, help) : null); }
function input(attrs = {}) { return h("input", { class: "input", type: "text", ...attrs }); }
function textarea(attrs = {}) { return h("textarea", { class: "input", ...attrs }); }
function select(options, value, attrs = {}) {
  return h("select", { class: "input", ...attrs }, options.map(([v, l]) => h("option", { value: v, selected: String(v) === String(value) }, l)));
}
function toggle(checked, onchange, attrs = {}) {
  const i = h("input", { type: "checkbox", checked, onchange: (e) => onchange && onchange(e.target.checked), ...attrs });
  return h("label", { class: "toggle" }, i, h("span"));
}

/* channels and roles of the current community, cached per visit */
async function meta(force = false) {
  if (!S.meta || force || S.meta.gid !== S.gid) S.meta = { gid: S.gid, ...(await api("GET", C("/channels"))) };
  return S.meta;
}
function channelSelect(channels, value) {
  return select([["", "Pick a channel…"], ...channels.map((c) => [c.id, `#${c.name}${c.category ? ` · ${c.category}` : ""}`])], value);
}

/* ---------------------------------------------------------------- sign-in */

async function showLogin() {
  let opts = { vector_code: true };
  try { opts = await api("GET", "/api/auth/options"); } catch { /* show the password form anyway */ }
  let npub = "";
  try { npub = localStorage.getItem("vectiq.npub") || ""; } catch { /* storage off */ }
  const title = h("h1", null, "Sign in");
  const sub = h("p", { class: "muted" });
  const body = h("div", { class: "stack" });
  clear(root, h("div", { class: "login" }, h("div", { class: "card" },
    h("div", { class: "row" }, h("div", { class: "mark" }, h("i")), h("b", null, "Vectiq"), h("span", { class: "faint" }, "dashboard")),
    title, sub, body)));

  function passwordForm() {
    title.textContent = "Sign in";
    sub.textContent = "With your dashboard username and password.";
    const user = input({ class: "input big", autocomplete: "username", spellcheck: "false", autocapitalize: "none", placeholder: "Username" });
    const pass = input({ class: "input big", type: "password", autocomplete: "current-password", placeholder: "Password" });
    const go = btn("Sign in", null, "primary");
    const submit = async (e) => {
      e && e.preventDefault();
      try { await run(go, () => api("POST", "/api/auth/login", { username: user.value, password: pass.value })); boot(); }
      catch { pass.select(); }
    };
    go.addEventListener("click", submit);
    const show = h("label", { class: "row faint", style: { fontSize: "13px", gap: "8px" } },
      h("input", { type: "checkbox", onchange: (e) => { pass.type = e.target.checked ? "text" : "password"; } }), "Show password");
    clear(body, h("form", { class: "stack", onsubmit: submit }, field("Username", user), field("Password", pass), show, go),
      opts.vector_code ? h("div", { class: "stack", style: { gap: "4px", marginTop: "4px" } },
        h("div", { class: "faint", style: { fontSize: "13px" } }, "No password yet, or forgot it?"),
        btn("Sign in with a code from Vector", codeStepOne, "ghost sm", { style: { alignSelf: "flex-start", paddingLeft: 0 } })) : null);
    user.focus();
  }

  function codeStepOne() {
    title.textContent = "Sign in with Vector";
    sub.textContent = "The bot sends a one-time code to your Vector DMs. Afterwards you can set a password on the Account page.";
    const npubIn = input({ class: "input big", placeholder: "npub1…", value: npub, spellcheck: "false", autocapitalize: "none" });
    const go = btn("Send me a code", null, "primary");
    const submit = async (e) => {
      e && e.preventDefault();
      npub = npubIn.value.trim();
      try { localStorage.setItem("vectiq.npub", npub); } catch { /* fine */ }
      try { const r = await run(go, () => api("POST", "/api/auth/request", { npub })); codeStepTwo(r.message); } catch { /* toast */ }
    };
    go.addEventListener("click", submit);
    clear(body, h("form", { class: "stack", onsubmit: submit }, field("Your npub", npubIn, "Find it in Vector under your profile."), go),
      h("p", { class: "faint", style: { fontSize: "13px", margin: "4px 0 0" } }, "Tip: type ", h("span", { class: "mono" }, "!dashboard"),
        " in any chat with the bot and it DMs you a link."),
      btn("← Username and password", passwordForm, "ghost sm", { style: { alignSelf: "flex-start", paddingLeft: 0 } }));
    npubIn.focus();
  }
  function codeStepTwo(message) {
    const codeIn = input({ class: "input code-in", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", placeholder: "••••••" });
    const go = btn("Sign in", null, "primary");
    const submit = async (e) => {
      e && e.preventDefault();
      try { await run(go, () => api("POST", "/api/auth/verify", { npub, code: codeIn.value.trim() })); boot(); } catch { codeIn.select(); }
    };
    go.addEventListener("click", submit);
    codeIn.addEventListener("input", () => { codeIn.value = codeIn.value.replace(/\D/g, ""); if (codeIn.value.length === 6) submit(); });
    clear(body, h("p", { class: "muted", style: { margin: 0 } }, message, " Open Vector and check your DMs from the bot."),
      h("form", { class: "stack", onsubmit: submit }, field("Code", codeIn), go),
      btn("Use a different npub", codeStepOne, "ghost sm", { style: { alignSelf: "flex-start", paddingLeft: 0 } }));
    codeIn.focus();
  }
  passwordForm();
}

/* ---------------------------------------------------------------- shell and router */

const PAGES = [
  ["overview", "◈", "Overview"], ["members", "☺", "Members"], ["moderation", "⚑", "Moderation"],
  ["leveling", "▲", "Leveling"], ["economy", "◎", "Economy"], ["tickets", "✉", "Tickets"],
  ["rolemenus", "❖", "Role menus"], ["giveaways", "✦", "Giveaways"], ["games", "▣", "Games"],
  ["onboarding", "➜", "Onboarding"], ["securitycam", "◉", "Security cam"],
  ["announce", "✎", "Announce"], ["audit", "☰", "Audit log"],
];
const MODULE_OF = { moderation: "moderation", leveling: "leveling", economy: "economy", tickets: "tickets", rolemenus: "roles",
  giveaways: "giveaways", games: "games", onboarding: "onboarding", securitycam: "securitycam" };

async function boot() {
  try { S.me = await api("GET", "/api/me"); } catch { return; }
  if (!location.hash || location.hash === "#/") {
    const first = S.me.communities[0];
    location.hash = first ? `#/c/${first.id}/overview` : "#/settings";
  }
  route();
}
window.addEventListener("hashchange", () => S.me && route());

function route() {
  document.querySelectorAll(".scrim").forEach((x) => x.remove());   // dialogs and panels don't outlive their page
  clearTimeout(S.panelTimer);
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  S.route = parts;
  if (parts[0] === "c" && parts[1]) {
    if (!S.me.communities.some((c) => c.id === parts[1])) { location.hash = "#/"; return; }
    if (S.gid !== parts[1]) S.meta = null;
    S.gid = parts[1];
  } else if (!S.gid && S.me.communities[0]) S.gid = S.me.communities[0].id;
  const page = parts[0] === "c" ? parts[2] || "overview" : parts[0];
  renderShell(page);
}

function renderShell(page) {
  const comm = S.me.communities.find((c) => c.id === S.gid);
  const main = h("main", { class: "main" });
  const shell = h("div", { class: "shell" });
  const nav = h("nav", { class: "nav" },
    comm ? [h("h3", null, "Community"), PAGES.filter(([id]) => !MODULE_OF[id] || S.me.modules[MODULE_OF[id]]).map(([id, ico, label]) =>
      h("a", { href: `#/c/${encodeURIComponent(S.gid)}/${id}`, class: page === id && "on", onclick: () => shell.classList.remove("open") },
        h("span", { class: "ico" }, ico), label))] : null,
    (S.me.panels || []).length ? [h("h3", null, "Modules"), S.me.panels.filter((p) => p.scope !== "community" || comm).map((p) => {
      const href = p.scope === "community" ? `#/c/${encodeURIComponent(S.gid)}/m/${encodeURIComponent(p.module)}` : `#/m/${encodeURIComponent(p.module)}`;
      return h("a", { href, class: page === "m" && S.route.includes(p.module) && "on", onclick: () => shell.classList.remove("open") },
        h("span", { class: "ico" }, p.icon), p.label);
    })] : null,
    h("h3", null, "Bot"),
    h("a", { href: "#/settings", class: page === "settings" && "on" }, h("span", { class: "ico" }, "⚙"), "Settings"),
    S.me.owner ? h("a", { href: "#/setup", class: page === "setup" && "on" }, h("span", { class: "ico" }, "✧"), "Setup wizard") : null,
    S.me.owner ? h("a", { href: "#/restore", class: page === "restore" && "on" }, h("span", { class: "ico" }, "↺"), "Restore points") : null,
    S.me.owner ? h("a", { href: "#/webhooks", class: page === "webhooks" && "on" }, h("span", { class: "ico" }, "⇄"), "Webhooks") : null,
    S.me.owner ? h("a", { href: "#/users", class: page === "users" && "on" }, h("span", { class: "ico" }, "⚿"), "Users") : null,
    h("a", { href: "#/account", class: page === "account" && "on" }, h("span", { class: "ico" }, "☻"), "My account"));
  const side = h("aside", { class: "side" },
    h("div", { class: "brand" }, h("div", { class: "mark" }, h("i")), h("div", null, "Vectiq", h("br"), h("small", null, "dashboard"))),
    comm ? h("button", { class: "switcher", type: "button", onclick: pickCommunity },
      h("div", { class: "avatar sm" }, initials(comm.name)),
      h("div", { class: "grow" }, h("div", { class: "ellipsis", style: { fontWeight: 600 } }, comm.name), h("div", { class: "faint", style: { fontSize: "12px" } }, plural(comm.members, "member"))),
      S.me.communities.length > 1 ? h("span", { class: "faint" }, "⇅") : null) : null,
    nav,
    h("div", { class: "me" }, avatar(S.me.user, "sm"), h("div", { class: "grow ellipsis" }, h("div", { class: "ellipsis", style: { fontWeight: 600 } }, S.me.user.name),
      h("div", { class: "faint", style: { fontSize: "12px" } }, S.me.owner ? "Bot owner" : "Community admin")),
    btn("Sign out", signOut, "ghost sm")));
  const top = h("div", { class: "topbar" }, btn("☰", () => shell.classList.toggle("open"), "ghost sm", { "aria-label": "Menu" }),
    h("div", { class: "mark" }, h("i")), h("b", { class: "ellipsis" }, comm ? comm.name : "Vectiq"));
  add(shell, [side, h("div", { style: { minWidth: 0 } }, top, main)]);
  shell.addEventListener("click", (e) => { if (shell.classList.contains("open") && e.target === shell) shell.classList.remove("open"); });
  clear(root, shell);
  const fn = { overview, members, moderation, leveling, economy, tickets, rolemenus, giveaways, games, onboarding, securitycam, announce, audit,
    settings, setup, restore, webhooks, users, account, m: modulePanel }[page];
  if (!fn || (!comm && !["settings", "setup", "restore", "webhooks", "users", "account", "m"].includes(page))) { clear(main, empty("Nothing here.")); return; }
  clear(main, h("div", { class: "boot", style: { minHeight: "50vh" } }, h("div", { class: "mark" }, h("i"))));
  fn(main).catch((e) => clear(main, card(null, h("p", { class: "muted" }, e.message))));
}

function pickCommunity() {
  if (S.me.communities.length < 2) return;
  let close;
  const list = h("div", { class: "list" }, S.me.communities.map((c) =>
    h("div", { class: "item click", onclick: () => { close(); location.hash = `#/c/${c.id}/${S.route[2] || "overview"}`; } },
      h("div", { class: "avatar" }, initials(c.name)), h("div", { class: "grow" }, h("b", null, c.name), h("div", { class: "faint" }, plural(c.members, "member"))),
      c.id === S.gid ? pill("current", "green") : null)));
  close = modal("Switch community", list);
}
async function signOut() {
  try { await api("POST", "/api/auth/logout"); } catch { /* signed out anyway */ }
  S.me = null; location.hash = ""; showLogin();
}
function head(title, sub, ...right) {
  return h("div", { class: "pagehead" }, h("div", { class: "grow" }, h("h1", null, title), sub ? h("p", null, sub) : null), right);
}

/* ---------------------------------------------------------------- overview */

const CAPS = [["manage_roles", "Manage Roles"], ["manage_channels", "Manage Channels"], ["manage_messages", "Manage Messages"],
  ["moderate_members", "Timeout members"], ["kick", "Kick"], ["ban", "Ban"]];

async function overview(main) {
  const d = await api("GET", C("/overview"));
  const st = d.stats, comm = d.community;
  const missing = CAPS.filter(([k]) => k in d.bot_can && !d.bot_can[k]).map(([, l]) => l);
  clear(main,
    head(comm.name, `Owned by ${comm.owner.name} · ${plural(comm.members, "member")} · ${plural(comm.channels, "channel")}`),
    missing.length ? h("section", { class: "card", style: { borderColor: "#5a4518", background: "var(--warn-bg)", marginBottom: "16px" } },
      h("b", { style: { color: "var(--warn)" } }, "The bot is missing permissions: "), missing.join(", "),
      h("div", { class: "muted", style: { marginTop: "4px", fontSize: "13px" } }, "Give the bot's account a role with them in Vector, or those features won't work.")) : null,
    h("div", { class: "stats" },
      stat("Members", fmt(comm.members), null, true),
      stat("Messages · 30d", fmt(d.activity.reduce((a, r) => a + r.messages, 0))),
      stat("Joined · 30d", fmt(d.activity.reduce((a, r) => a + r.joins, 0)), `${fmt(d.activity.reduce((a, r) => a + r.leaves, 0))} left`),
      stat("Ranked members", fmt(st.ranked)),
      stat("Open tickets", fmt(st.open_tickets)),
      stat("Cases · 7d", fmt(st.cases_week)),
      stat("Giveaways running", fmt(st.giveaways)),
      stat("Coins in circulation", fmt(st.economy.cash + st.economy.bank), plural(st.economy.wallets, "wallet")),
      stat("Onboarding done", `${fmt(st.onboarding.completed)}/${fmt(st.onboarding.started)}`)),
    h("div", { class: "grid g21", style: { marginTop: "16px" } },
      card(h("div", { class: "row grow" }, h("h2", null, "Activity, last 30 days"),
        h("div", { class: "legend right" }, h("span", null, h("i", { style: { background: "var(--accent)" } }), "messages"),
          h("span", null, h("i", { style: { background: "var(--info)" } }), "joins"), h("span", null, h("i", { style: { background: "var(--danger)" } }), "leaves"))),
      d.activity.length ? activityChart(last30(d.activity)) : empty("No activity recorded yet.")),
      card("Busiest channels", d.top_channels.length ? hbars(d.top_channels.map((c) => [c.name ? `#${c.name}` : "deleted channel", c.messages])) : empty("Nothing yet."))),
    h("div", { style: { marginTop: "16px" } }, card(h("div", { class: "row grow" }, h("h2", null, "Recent moderation"),
      h("a", { class: "right", href: `#/c/${S.gid}/moderation` }, "All cases →")),
    d.recent_cases.length ? casesTable(d.recent_cases, false) : empty("No cases. A quiet community."))));
}

function last30(rows) {
  const by = Object.fromEntries(rows.map((r) => [r.day, r]));
  const out = [];
  for (let i = 29; i >= 0; i--) {
    const day = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    out.push(by[day] || { day, messages: 0, joins: 0, leaves: 0 });
  }
  return out;
}
function activityChart(rows) {
  const W = 720, H = 200, P = 22, max = Math.max(1, ...rows.map((r) => r.messages)), bw = (W - P) / rows.length;
  const svg = h("svg:svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": "Messages per day" });
  const grid = h("svg:g", { class: "grid" });
  for (let i = 0; i <= 3; i++) {
    const y = 8 + ((H - P - 8) * i) / 3;
    grid.appendChild(h("svg:line", { x1: P, x2: W, y1: y, y2: y }));
    grid.appendChild(h("svg:text", { x: 0, y: y + 3 }, fmt(Math.round(max * (1 - i / 3)))));
  }
  svg.appendChild(grid);
  rows.forEach((r, i) => {
    const x = P + i * bw + 2, bh = ((H - P - 8) * r.messages) / max;
    const bar = h("svg:rect", { class: "bar", x, y: H - P - bh, width: Math.max(bw - 4, 2), height: Math.max(bh, 1), rx: 3 });
    bar.appendChild(h("svg:title", null, `${r.day}: ${r.messages} messages, ${r.joins} joined, ${r.leaves} left`));
    svg.appendChild(bar);
    if (r.joins) svg.appendChild(h("svg:rect", { class: "join", x, y: H - P + 3, width: Math.max(bw / 2 - 3, 1), height: Math.min(4 + r.joins, 14) / 2 + 2, rx: 1 }));
    if (r.leaves) svg.appendChild(h("svg:rect", { class: "leave", x: x + bw / 2, y: H - P + 3, width: Math.max(bw / 2 - 3, 1), height: Math.min(4 + r.leaves, 14) / 2 + 2, rx: 1 }));
    if (rows.length <= 10 || i % Math.ceil(rows.length / 7) === 0 || i === rows.length - 1) svg.appendChild(h("svg:text", { x, y: H - 1 }, r.day.slice(5)));
  });
  return svg;
}
function hbars(items) {
  const max = Math.max(1, ...items.map(([, v]) => v));
  return h("div", null, items.map(([label, v]) => {
    const fill = h("i"); fill.style.width = `${(100 * v) / max}%`;
    return h("div", { class: "hbar" }, h("span", { class: "ellipsis" }, label), h("div", { class: "progress" }, fill), h("span", { class: "num faint", style: { textAlign: "right" } }, fmt(v)));
  }));
}

/* ---------------------------------------------------------------- members */

async function members(main) {
  const { roles } = await meta();
  const roleById = Object.fromEntries(roles.map((r) => [r.id, r]));
  const q = input({ placeholder: "Search by name or npub", type: "search" });
  const filter = select([["", "Everyone"], ["admins", "Admins"], ["warned", "With warnings"], ["timed_out", "Timed out"], ["bots", "Bots"]], "");
  const list = h("div");
  const more = btn("Load more", null, "sm");
  let offset = 0, timer;
  async function load(reset) {
    if (reset) offset = 0;
    const d = await api("GET", C(`/members?q=${encodeURIComponent(q.value)}&filter=${filter.value}&offset=${offset}&limit=50`));
    const rows = d.members.map((m) => h("tr", { class: "click", onclick: () => openMember(m.id) },
      h("td", null, who(m, m.id.slice(0, 16) + "…")),
      h("td", { class: "hide-sm" }, h("div", { class: "row wrap", style: { gap: "4px" } },
        m.owner ? pill("owner", "green") : m.admin ? pill("admin", "green") : null, m.bot ? pill("bot") : null,
        m.timed_out ? pill("timed out", "yellow") : null, m.roles.slice(0, 3).map((id) => roleById[id] ? rolePill(roleById[id]) : null),
        m.roles.length > 3 ? h("span", { class: "faint" }, `+${m.roles.length - 3}`) : null)),
      h("td", { class: "num" }, m.level), h("td", { class: "num hide-sm" }, fmt(m.xp)), h("td", { class: "num hide-sm" }, fmt(m.coins)),
      h("td", { class: "num" }, m.warnings ? pill(String(m.warnings), "red") : h("span", { class: "faint" }, "0"))));
    if (reset) clear(list, d.total ? h("div", { class: "scroll-x" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", null, "Member"), h("th", { class: "hide-sm" }, "Roles"), h("th", { class: "num" }, "Level"),
        h("th", { class: "num hide-sm" }, "XP"), h("th", { class: "num hide-sm" }, "Coins"), h("th", { class: "num" }, "Warns"))),
      h("tbody", null, rows))) : empty("No members match."));
    else list.querySelector("tbody").append(...rows);
    offset += d.members.length;
    more.classList.toggle("hidden", offset >= d.total);
    count.textContent = plural(d.total, "member");
  }
  const count = h("span", { class: "muted" });
  more.addEventListener("click", () => run(more, () => load(false)));
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load(true), 220); });
  filter.addEventListener("change", () => load(true));
  clear(main, head("Members", "Click someone to see their record and act on it.", count),
    card(null, h("div", { class: "row wrap", style: { marginBottom: "14px" } }, h("div", { class: "search grow" }, q), h("div", { style: { width: "200px" } }, filter)),
      list, h("div", { class: "row", style: { justifyContent: "center", marginTop: "12px" } }, more)));
  await load(true);
}

async function openMember(uid) {
  const box = h("div", { class: "stack" }, h("div", { class: "boot", style: { minHeight: "40vh" } }, h("div", { class: "mark" }, h("i"))));
  const close = drawer(box);
  const refresh = async () => {
    const [d, { roles }] = await Promise.all([api("GET", C(`/members/${encodeURIComponent(uid)}`)), meta()]);
    const m = d.member, r = d.rank, w = d.wallet;
    const roleById = Object.fromEntries(roles.map((x) => [x.id, x]));
    const prog = h("i"); prog.style.width = `${r.span ? Math.min(100, (100 * r.into) / r.span) : 0}%`;
    const act = (action, label, kind, needs) => btn(label, () => memberAction(m, action, label, needs, refresh), kind || "sm");
    const giveRole = select([["", "Give a role…"], ...roles.filter((x) => !m.roles.includes(x.id)).map((x) => [x.id, x.name])], "");
    giveRole.addEventListener("change", () => giveRole.value && run(null, () => api("POST", C(`/members/${uid}/roles`), { role: giveRole.value, add: true })).then(refresh).catch(() => {}));
    clear(box,
      h("div", { class: "row" }, avatar(m, "lg"), h("div", { class: "grow" }, h("h1", { class: "ellipsis" }, m.name),
        h("div", { class: "mono faint ellipsis" }, m.id),
        h("div", { class: "row wrap", style: { marginTop: "6px", gap: "6px" } }, m.owner ? pill("owner", "green") : m.admin ? pill("admin", "green") : null,
          m.bot ? pill("bot") : null, m.timed_out ? pill(`timed out ${m.timed_out_until ? rel(m.timed_out_until) : ""}`, "yellow") : null,
          m.in_community ? null : pill("not in community", "red"), m.joined_at ? h("span", { class: "faint" }, `joined ${rel(m.joined_at)}`) : null)),
      btn("✕", close, "ghost sm", { "aria-label": "Close" })),
      h("div", { class: "stats", style: { gridTemplateColumns: "repeat(3, minmax(0,1fr))" } },
        stat("Level", r.level, `rank #${r.position}`, true), stat("XP", fmt(r.xp), plural(r.messages, "message")),
        stat("Coins", fmt(w.cash + w.bank), `${fmt(w.cash)} cash · ${fmt(w.bank)} bank`)),
      h("div", null, h("div", { class: "row faint", style: { fontSize: "12px", marginBottom: "6px" } }, `${fmt(r.into)} / ${fmt(r.span)} XP to level ${r.level + 1}`), h("div", { class: "progress" }, prog)),
      m.in_community ? card("Moderation", h("div", { class: "row wrap" },
        act("warn", "Warn", "sm", "reason"), m.timed_out ? act("untimeout", "Lift timeout", "sm") : act("timeout", "Timeout", "sm", "duration"),
        act("kick", "Kick", "sm danger", "reason"), act("ban", "Ban", "sm danger", "reason"), act("tempban", "Temp ban", "sm danger", "duration"),
        d.cases.some((c) => c.action === "warn" && c.active) ? act("clearwarns", "Clear warnings", "sm ghost") : null)) : null,
      m.in_community ? card("Roles", h("div", { class: "row wrap", style: { gap: "6px" } },
        m.roles.length ? m.roles.map((id) => roleById[id] ? h("span", { class: "role" }, rolePill(roleById[id]).childNodes[0], roleById[id].name,
          h("button", { class: "btn ghost sm", style: { height: "20px", padding: "0 4px" }, type: "button", title: "Remove",
            onclick: () => run(null, () => api("POST", C(`/members/${uid}/roles`), { role: id, add: false })).then(refresh).catch(() => {}) }, "✕")) : null)
          : h("span", { class: "faint" }, "No roles.")),
      h("div", { style: { marginTop: "12px" } }, giveRole)) : null,
      card("XP and coins", h("div", { class: "form two" }, adjustBox("Add or remove XP", "e.g. 500 or -200", (v) => api("POST", C(`/members/${uid}/xp`), { amount: v }), refresh),
        adjustBox("Add or remove coins", "e.g. 100 or -50", (v) => api("POST", C(`/members/${uid}/coins`), { amount: v }), refresh)),
      h("div", { class: "row", style: { marginTop: "10px" } }, btn("Reset XP", async () => {
        if (await confirmBox("Reset XP?", `${m.name} goes back to level 0.`, "Reset")) run(null, () => api("POST", C(`/members/${uid}/xp`), { reset: true })).then(refresh).catch(() => {});
      }, "ghost sm"))),
      card(`Cases (${d.cases.length})`, d.cases.length ? casesTable(d.cases, false, refresh) : empty("Clean record.")),
      d.transactions.length ? card("Recent coins", h("div", { class: "list" }, d.transactions.map((t) => h("div", { class: "item" },
        h("span", { class: "grow ellipsis" }, t.reason || "–"), h("span", { class: "faint nowrap" }, rel(t.created_at)),
        h("b", { style: { color: t.amount < 0 ? "var(--danger)" : "var(--accent)" }, class: "nowrap" }, `${t.amount > 0 ? "+" : ""}${fmt(t.amount)}`))))) : null,
      d.inventory.length ? card("Inventory", h("div", { class: "row wrap" }, d.inventory.map((i) => pill(`${i.name} ×${i.quantity}`)))) : null,
      d.games.length ? card("Games", h("table", { class: "table" }, h("tr", null, ["Game", "Played", "Won", "Drawn"].map((x, i) => h("th", { class: i && "num" }, x))),
        d.games.map((g) => h("tr", null, h("td", null, g.game), h("td", { class: "num" }, g.played), h("td", { class: "num" }, g.won), h("td", { class: "num" }, g.drawn))))) : null);
  };
  refresh().catch((e) => clear(box, h("p", { class: "muted" }, e.message)));
}
function adjustBox(label, ph, send, after) {
  const i = input({ type: "number", placeholder: ph });
  const b = btn("Apply", async () => { if (!i.value) return; try { await run(b, () => send(parseInt(i.value, 10))); i.value = ""; after(); } catch { /* toast */ } }, "sm");
  return field(label, h("div", { class: "row" }, i, b));
}
function memberAction(m, action, label, needs, after) {
  const reason = input({ placeholder: "Optional, shown in the case log" });
  const duration = input({ placeholder: "e.g. 30m, 2h, 1d" });
  const danger = ["kick", "ban", "tempban"].includes(action);
  const body = h("div", { class: "form" },
    h("p", { class: "muted", style: { margin: 0 } }, `${label}: ${m.name}`),
    needs === "duration" ? field("For how long", duration) : null,
    action !== "untimeout" && action !== "clearwarns" ? field("Reason", reason) : null);
  modal(label, body, [{ label, kind: danger ? "danger" : "primary", after,
    run: () => api("POST", C(`/members/${encodeURIComponent(m.id)}/action`), { action, reason: reason.value, duration: duration.value }) }]);
}

/* ---------------------------------------------------------------- moderation */

function casesTable(cases, withUser = true, after = null) {
  const colour = { warn: "yellow", timeout: "yellow", kick: "red", ban: "red", tempban: "red", unban: "green" };
  return h("div", { class: "scroll-x" }, h("table", { class: "table" },
    h("thead", null, h("tr", null, h("th", null, "#"), withUser !== false ? h("th", null, "Member") : null, h("th", null, "Action"),
      h("th", null, "Reason"), h("th", { class: "hide-sm" }, "By"), h("th", null, "When"), h("th"))),
    h("tbody", null, cases.map((c) => h("tr", null,
      h("td", { class: "faint" }, c.id), withUser !== false ? h("td", { class: "click", onclick: () => openMember(c.user.id), style: { cursor: "pointer" } }, who(c.user)) : null,
      h("td", null, pill(c.action, c.active ? colour[c.action] : "")), h("td", { class: "ellipsis", style: { maxWidth: "260px" } }, c.reason || h("span", { class: "faint" }, "–")),
      h("td", { class: "hide-sm" }, c.moderator.name), h("td", { class: "nowrap faint", title: when(c.created_at) }, rel(c.created_at)),
      h("td", null, c.active && ["warn", "timeout", "tempban"].includes(c.action) ? btn("Remove", async (e) => {
        if (await confirmBox(`Remove case #${c.id}?`, "It stays in the history but no longer counts.", "Remove")) {
          run(e.target, () => api("POST", C(`/cases/${c.id}/deactivate`))).then(() => (after ? after() : route())).catch(() => {});
        }
      }, "ghost sm") : null))))));
}

async function moderation(main) {
  const tab = S.route[3] || "cases";
  const tabs = h("div", { class: "tabs" }, [["cases", "Cases"], ["bans", "Bans"]].map(([id, l]) =>
    h("button", { type: "button", class: tab === id && "on", onclick: () => { location.hash = `#/c/${S.gid}/moderation/${id}`; } }, l)));
  if (tab === "bans") {
    const d = await api("GET", C("/bans"));
    clear(main, head("Moderation", "Banned accounts."), tabs, card(null, d.bans.length ? h("div", { class: "list" }, d.bans.map((b) => h("div", { class: "item" },
      h("div", { class: "grow" }, who(b, b.reason || b.id.slice(0, 20) + "…")),
      btn("Unban", async (e) => {
        if (await confirmBox(`Unban ${b.name}?`, "They can rejoin with an invite.", "Unban", "primary")) run(e.target, () => api("POST", C(`/bans/${encodeURIComponent(b.id)}/unban`))).then(route).catch(() => {});
      }, "sm")))) : empty("Nobody is banned.")));
    return;
  }
  const action = S.route[4] || "";
  const d = await api("GET", C(`/cases?limit=200&action=${action}`));
  const filter = select([["", "All actions"], ...["warn", "timeout", "kick", "ban", "tempban", "unban"].map((a) => [a, a])], action);
  filter.addEventListener("change", () => { location.hash = `#/c/${S.gid}/moderation/cases/${filter.value}`; });
  clear(main, head("Moderation", "Every case, newest first. Act on a member from the Members page.", h("div", { style: { width: "180px" } }, filter)),
    tabs, card(null, d.cases.length ? casesTable(d.cases) : empty("No cases yet.")));
}

/* ---------------------------------------------------------------- leveling */

async function leveling(main) {
  const page = parseInt(S.route[3] || "1", 10) || 1;
  const [d, { roles }] = await Promise.all([api("GET", C(`/leveling?page=${page}`)), meta()]);
  const pages = Math.max(1, Math.ceil(d.total / 25));
  const img = h("img", { src: C(`/leaderboard.png?page=${Math.ceil(((page - 1) * 25 + 1) / 8)}`), alt: "Leaderboard card", style: { width: "100%", borderRadius: "16px" } });
  img.addEventListener("error", () => img.replaceWith(empty("No leaderboard image yet.")), { once: true });
  const level = input({ type: "number", min: "1", placeholder: "Level" });
  const role = select([["", "Role…"], ...roles.map((r) => [r.id, r.name])], "");
  const addB = btn("Add reward", () => run(addB, () => api("POST", C("/rewards"), { level: level.value, role: role.value })).then(route).catch(() => {}), "primary sm");
  const pager = h("div", { class: "row", style: { justifyContent: "center", marginTop: "12px" } },
    btn("← Prev", () => { location.hash = `#/c/${S.gid}/leveling/${page - 1}`; }, "sm", { disabled: page <= 1 }),
    h("span", { class: "muted" }, `Page ${page} of ${pages}`),
    btn("Next →", () => { location.hash = `#/c/${S.gid}/leveling/${page + 1}`; }, "sm", { disabled: page >= pages }));
  clear(main, head("Leveling", `${plural(d.total, "member")} have XP.`),
    h("div", { class: "grid g2" },
      card("Leaderboard card", h("p", { class: "muted", style: { marginTop: 0 } }, "The same image members see with !leaderboard."), img),
      card("Role rewards", h("p", { class: "muted", style: { marginTop: 0 } }, "Members get these roles when they reach the level."),
        d.rewards.length ? h("div", { class: "list" }, d.rewards.map((r) => h("div", { class: "item" }, pill(`Level ${r.level}`, "green"), rolePill(r.role),
          btn("Remove", (e) => run(e.target, () => api("DELETE", C(`/rewards/${r.level}`))).then(route).catch(() => {}), "ghost sm right")))) : empty("No rewards yet."),
        h("div", { class: "row wrap", style: { marginTop: "12px" } }, h("div", { style: { width: "110px" } }, level), h("div", { class: "grow" }, role), addB))),
    h("div", { style: { marginTop: "16px" } }, card("Ranking", d.leaderboard.length ? h("div", { class: "scroll-x" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", null, "#"), h("th", null, "Member"), h("th", { class: "num" }, "Level"), h("th", { class: "hide-sm" }, "Progress"),
        h("th", { class: "num" }, "XP"), h("th", { class: "num hide-sm" }, "Messages"))),
      h("tbody", null, d.leaderboard.map((r) => {
        const p = h("i"); p.style.width = `${r.span ? (100 * r.into) / r.span : 0}%`;
        return h("tr", { class: "click", onclick: () => openMember(r.id) }, h("td", { class: r.position <= 3 ? "" : "faint" }, h("b", null, r.position)), h("td", null, who(r)),
          h("td", { class: "num" }, r.level), h("td", { class: "hide-sm", style: { width: "22%" } }, h("div", { class: "progress" }, p)),
          h("td", { class: "num" }, fmt(r.xp)), h("td", { class: "num hide-sm" }, fmt(r.messages)));
      })))) : empty("Nobody has XP yet."), pages > 1 ? pager : null)));
}

/* ---------------------------------------------------------------- economy */

async function economy(main) {
  const [d, { roles }] = await Promise.all([api("GET", C("/economy")), meta()]);
  const sym = d.currency.symbol || "";
  const newItem = () => {
    const name = input({ placeholder: "VIP pass" }), price = input({ type: "number", min: "0", placeholder: "500" });
    const desc = input({ placeholder: "Optional" }), stock = input({ type: "number", min: "0", placeholder: "Unlimited" });
    const role = select([["", "No role"], ...roles.map((r) => [r.id, r.name])], "");
    modal("New shop item", h("div", { class: "form two" }, field("Name", name), field(`Price (${d.currency.name})`, price),
      h("div", { class: "span" }, field("Description", desc)), field("Gives role", role), field("Stock", stock, "Blank = unlimited")),
    [{ label: "Add item", after: route, run: () => api("POST", C("/shop"), { name: name.value, price: price.value, description: desc.value, role: role.value, stock: stock.value }) }]);
  };
  clear(main, head("Economy", `${d.currency.name} ${sym}`, btn("+ New item", newItem, "primary")),
    h("div", { class: "stats" }, stat("Cash", `${sym} ${fmt(d.totals.cash)}`, null, true), stat("In banks", `${sym} ${fmt(d.totals.bank)}`), stat("Wallets", fmt(d.totals.wallets))),
    h("div", { class: "grid g2", style: { marginTop: "16px" } },
      card("Shop", d.shop.length ? h("div", { class: "list" }, d.shop.map((i) => h("div", { class: "item" },
        h("div", { class: "grow" }, h("b", null, i.name), h("div", { class: "faint ellipsis", style: { fontSize: "13px" } }, i.description || (i.role ? "" : "–")),
          i.role ? h("div", { style: { marginTop: "4px" } }, rolePill(i.role)) : null),
        h("div", { style: { textAlign: "right" } }, h("b", { class: "nowrap" }, `${sym} ${fmt(i.price)}`), h("div", { class: "faint", style: { fontSize: "12px" } }, i.stock === null ? "∞ stock" : `${i.stock} left`)),
        btn("✕", async (e) => { if (await confirmBox(`Remove ${i.name}?`, "Members who bought it keep it.", "Remove")) run(e.target, () => api("DELETE", C(`/shop/${encodeURIComponent(i.name)}`))).then(route).catch(() => {}); }, "ghost sm", { title: "Remove" })))) : empty("The shop is empty.")),
      card("Richest members", d.richest.length ? h("table", { class: "table" }, h("tbody", null, d.richest.map((w, i) => h("tr", { class: "click", onclick: () => openMember(w.id) },
        h("td", { class: "faint" }, i + 1), h("td", null, who(w)), h("td", { class: "num" }, h("b", null, `${sym} ${fmt(w.cash + w.bank)}`)))))) : empty("No wallets yet."))));
}

/* ---------------------------------------------------------------- tickets */

async function tickets(main) {
  const status = S.route[3] ?? "open";
  const d = await api("GET", C(`/tickets?status=${status}`));
  const tabs = h("div", { class: "tabs" }, [["open", "Open"], ["closed", "Closed"], ["", "All"]].map(([id, l]) =>
    h("button", { type: "button", class: status === id && "on", onclick: () => { location.hash = `#/c/${S.gid}/tickets/${id}`; } }, l)));
  clear(main, head("Tickets", "Private support channels members open with !ticket open."), tabs,
    card(null, d.tickets.length ? h("div", { class: "list" }, d.tickets.map((t) => h("div", { class: "item click", onclick: () => openTicket(t.id) },
      h("span", { class: "faint" }, `#${t.id}`), h("div", { class: "grow" }, h("b", { class: "ellipsis" }, t.subject),
        h("div", { class: "faint", style: { fontSize: "13px" } }, `${t.user.name} · opened ${rel(t.created_at)}${t.claimed_by ? ` · ${t.claimed_by.name} is on it` : ""}`)),
      h("span", { class: "faint nowrap hide-sm" }, plural(t.messages, "message")),
      pill(t.status, t.status === "open" ? "green" : "")))) : empty(status === "open" ? "No open tickets. 🎉" : "No tickets.")));
}
async function openTicket(id) {
  const d = await api("GET", C(`/tickets/${id}`));
  const t = d.ticket;
  const chat = h("div", { class: "chat" }, d.transcript.length ? d.transcript.map((m) => h("div", { class: "msg" }, avatar(m.author, "sm"),
    h("div", null, h("div", { class: "meta" }, h("b", null, m.author.name), " · ", when(m.at)), h("div", { class: "b" }, m.content)))) : empty("No messages saved."));
  const actions = [];
  if (t.status === "open" && !t.claimed_by) actions.push({ label: "Claim", kind: "", after: route, run: () => api("POST", C(`/tickets/${id}/claim`)) });
  if (t.status === "open") actions.push({ label: "Close ticket", kind: "danger", after: route, run: () => api("POST", C(`/tickets/${id}/close`)) });
  modal(`Ticket #${t.id}: ${t.subject}`, h("div", { class: "stack" },
    h("div", { class: "row wrap" }, who(t.user, `opened ${when(t.created_at)}`), pill(t.status, t.status === "open" ? "green" : ""),
      t.channel ? pill(`#${t.channel.name}`) : null), chat), actions);
}

/* ---------------------------------------------------------------- role menus */

async function rolemenus(main) {
  const [d, m] = await Promise.all([api("GET", C("/rolemenus")), meta()]);
  clear(main, head("Role menus", "Members react to a message to get a role and un-react to drop it.", btn("+ New menu", () => newMenu(m), "primary")),
    d.menus.length ? h("div", { class: "grid g2" }, d.menus.map((menu) => card(h("div", { class: "row grow" }, h("h2", { class: "grow ellipsis" }, menu.title),
      btn("Delete", async (e) => { if (await confirmBox(`Delete “${menu.title}”?`, "Reactions on it stop giving roles. The message itself stays.", "Delete")) run(e.target, () => api("DELETE", C(`/rolemenus/${menu.id}`))).then(route).catch(() => {}); }, "ghost sm")),
    h("div", { class: "faint", style: { marginBottom: "10px" } }, menu.channel ? `#${menu.channel.name}` : "channel deleted", ` · menu #${menu.id}`),
    h("div", { class: "list" }, menu.options.map((o) => h("div", { class: "item" }, h("span", { style: { fontSize: "20px", width: "28px", textAlign: "center" } }, o.emoji), rolePill(o.role))))))) : card(null, empty("No role menus yet.")));
}
function newMenu(m) {
  const ch = channelSelect(m.channels, ""), title = input({ placeholder: "Pick your roles" });
  const rows = h("div");
  const addRow = (emoji = "", role = "") => {
    const e = input({ value: emoji, placeholder: "🎮", style: { textAlign: "center", fontSize: "18px" } });
    const r = input({ value: role, placeholder: "Role name (new or existing)", list: "role-names" });
    const row = h("div", { class: "maprow" }, e, r, btn("✕", () => row.remove(), "ghost sm"));
    rows.appendChild(row);
  };
  [["🎮", "Gamer"], ["🎨", "Artist"]].forEach(([e, r]) => addRow(e, r));
  modal("New role menu", h("div", { class: "form" }, field("Channel", ch), field("Title", title),
    h("div", null, h("div", { class: "row", style: { marginBottom: "8px" } }, h("b", { class: "muted", style: { fontSize: "13px" } }, "Emoji → role"), btn("+ Add", () => addRow(), "ghost sm right")),
      rows, h("p", { class: "faint", style: { fontSize: "12px", margin: 0 } }, "Roles that don't exist yet are created.")),
    h("datalist", { id: "role-names" }, m.roles.map((r) => h("option", { value: r.name })))),
  [{ label: "Post menu", after: route, run: () => api("POST", C("/rolemenus"), { channel: ch.value, title: title.value,
    options: [...rows.children].map((row) => ({ emoji: row.children[0].value, role: row.children[1].value })) }) }]);
}

/* ---------------------------------------------------------------- giveaways */

async function giveaways(main) {
  const [d, m] = await Promise.all([api("GET", C("/giveaways")), meta()]);
  const running = d.giveaways.filter((g) => !g.ended), ended = d.giveaways.filter((g) => g.ended);
  const startNew = () => {
    const ch = channelSelect(m.channels, ""), prize = input({ placeholder: "1,000 coins" });
    const dur = input({ value: "1d", placeholder: "30m, 2h, 1d" }), win = input({ type: "number", min: "1", max: String(d.max_winners), value: "1" });
    modal("New giveaway", h("div", { class: "form two" }, h("div", { class: "span" }, field("Prize", prize)), field("Channel", ch), field("Runs for", dur),
      field("Winners", win, `Up to ${d.max_winners}`)),
    [{ label: "Start giveaway", after: route, run: () => api("POST", C("/giveaways"), { channel: ch.value, prize: prize.value, duration: dur.value, winners: win.value }) }]);
  };
  const op = (g, o, label, kind) => btn(label, async (e) => {
    if (o !== "reroll" && !(await confirmBox(`${label} “${g.prize}”?`, o === "end" ? "Winners are drawn now." : "No winners are drawn.", label))) return;
    run(e.target, () => api("POST", C(`/giveaways/${g.id}/${o}`))).then(route).catch(() => {});
  }, kind);
  const row = (g) => h("div", { class: "item" }, h("span", { style: { fontSize: "20px" } }, "🎁"),
    h("div", { class: "grow" }, h("b", { class: "ellipsis" }, g.prize), h("div", { class: "faint", style: { fontSize: "13px" } },
      `${g.channel ? `#${g.channel.name}` : "deleted channel"} · ${plural(g.winners, "winner")} · ${plural(g.entries, "entry").replace("entrys", "entries")} · ${g.ended ? `ended ${rel(g.ends_at)}` : `ends ${rel(g.ends_at)}`}`)),
    g.ended ? op(g, "reroll", "Reroll", "sm") : [op(g, "end", "End now", "sm"), op(g, "cancel", "Cancel", "ghost sm")]);
  clear(main, head("Giveaways", "Members enter by reacting 🎉.", btn("+ New giveaway", startNew, "primary")),
    h("div", { class: "stack" }, card(`Running (${running.length})`, running.length ? h("div", { class: "list" }, running.map(row)) : empty("Nothing running.")),
      card("Recently ended", ended.length ? h("div", { class: "list" }, ended.map(row)) : empty("None yet."))));
}

/* ---------------------------------------------------------------- games */

async function games(main) {
  const [d, m] = await Promise.all([api("GET", C("/games")), meta()]);
  const ch = channelSelect(m.channels, ""), game = select(d.games.map((g) => [g.id, g.title]), d.games[0]?.id);
  const post = btn("Post game", () => run(post, () => api("POST", C("/games"), { channel: ch.value, game: game.value })).catch(() => {}), "primary");
  clear(main, head("Games", "WebXDC mini games, refereed by the bot. Wins pay coins."),
    d.enabled ? card("Post a game", h("div", { class: "row wrap" }, h("div", { class: "grow" }, game), h("div", { class: "grow" }, ch), post)) : null,
    h("div", { class: "grid g2", style: { marginTop: "16px" } }, d.games.map((g) => card(g.title, g.top.length ? h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", null, "Player"), h("th", { class: "num" }, "Won"), h("th", { class: "num" }, "Played"), h("th", { class: "num hide-sm" }, "Score"))),
      h("tbody", null, g.top.map((r) => h("tr", { class: "click", onclick: () => openMember(r.id) }, h("td", null, who(r)), h("td", { class: "num" }, h("b", null, r.won)),
        h("td", { class: "num" }, r.played), h("td", { class: "num hide-sm" }, fmt(r.score)))))) : empty("Nobody has played yet.")))));
}

/* ---------------------------------------------------------------- onboarding */

async function onboarding(main) {
  const d = await api("GET", C("/onboarding"));
  const pct = d.counts.started ? Math.round((100 * d.counts.completed) / d.counts.started) : 0;
  const bar = h("i"); bar.style.width = `${pct}%`;
  const repost = btn("Post / refresh the role menu", () => run(repost, () => api("POST", C("/onboarding/repost"))).catch(() => {}), "primary");
  clear(main, head("Onboarding", "New members go through these steps.", d.enabled ? repost : null),
    h("div", { class: "grid g2" },
      card("Steps", h("div", { class: "row wrap" }, ["join", ...d.steps, "done"].map((s, i, a) => [pill(s.replace("_", " "), s === "join" || s === "done" ? "green" : ""),
        i < a.length - 1 ? h("span", { class: "faint" }, "→") : null])),
      h("p", { class: "muted" }, d.required ? "Members must finish before they can chat." : "Members can chat before they finish."),
      h("a", { href: "#/settings/onboarding" }, "Change in Settings →")),
      card("Progress", h("div", { class: "stats", style: { gridTemplateColumns: "repeat(3, minmax(0,1fr))" } }, stat("Started", fmt(d.counts.started)), stat("Finished", fmt(d.counts.completed), null, true), stat("Rate", `${pct}%`)),
        h("div", { class: "progress", style: { marginTop: "14px" } }, bar))),
    h("div", { style: { marginTop: "16px" } }, card(`Role menu: “${d.title}”`, h("div", { class: "list" }, Object.entries(d.role_menu).map(([e, r]) =>
      h("div", { class: "item" }, h("span", { style: { fontSize: "20px", width: "28px", textAlign: "center" } }, e), h("b", null, r)))),
    h("p", { class: "faint" }, `Posted in ${d.channel ? `#${d.channel}` : "the system channel"}.`))));
}

/* ---------------------------------------------------------------- security cam */

async function securitycam(main) {
  const [d, m] = await Promise.all([api("GET", C("/securitycam")), meta()]);
  if (!d.enabled) {
    clear(main, head("Security cam", "Echo every message into one staff channel."),
      card(null, h("p", { class: "muted" }, "The security cam module is off."), h("a", { href: "#/settings/modules" }, "Turn it on in Settings →")));
    return;
  }
  const ch = channelSelect(m.channels.filter((c) => !d.ignore.includes(c.id)), d.channel);
  const skip = new Set(d.ignore);
  const save = btn("Save", async () => {
    try { await run(save, () => api("PUT", C("/securitycam"), { channel: ch.value, ignore: [...skip] })); securitycam(main); } catch { /* toast */ }
  }, "primary");
  const off = btn("Turn off", async () => {
    try { await run(off, () => api("PUT", C("/securitycam"), { channel: "" })); securitycam(main); } catch { /* toast */ }
  }, "ghost");
  const test = btn("Send a test", () => run(test, () => api("POST", C("/securitycam/test"))).catch(() => {}), "ghost");
  const status = d.channel
    ? h("div", { class: "row" }, pill("recording", "green"), h("span", null, `Echoing to #${d.channel_name}`))
    : h("div", { class: "row" }, pill("off"), h("span", { class: "muted" }, "Pick a channel to start."));
  clear(main, head("Security cam", "Every message from every channel, with avatar, channel, time and attachments, is copied into one channel.",
    d.channel ? test : null),
    h("div", { class: "grid g2" },
      card("Camera", h("div", { class: "form" }, status,
        field("Camera channel", ch, "Keep this channel private to staff. Messages in it are never echoed."),
        h("div", { class: "row" }, save, d.channel ? off : null))),
      card("Since the bot started", h("div", { class: "stats", style: { gridTemplateColumns: "repeat(2, minmax(0,1fr))" } },
        stat("Messages echoed", fmt(d.echoed), null, true), stat("Last echo", d.last ? new Date(d.last).toLocaleTimeString() : "—")),
        h("p", { class: "faint" }, d.include_bots ? "Other bots' messages are included." : "Other bots' messages are skipped."),
        h("a", { href: "#/settings/securitycam" }, "More options in Settings →"))),
    h("div", { style: { marginTop: "16px" } }, card("Channels to skip",
      h("p", { class: "muted" }, "Switch on a channel to leave it out of the echo."),
      h("div", { class: "list" }, m.channels.filter((c) => c.id !== d.channel).map((c) =>
        h("div", { class: "item" }, h("span", { class: "grow" }, `#${c.name}`),
          d.config_ignore.some((x) => x === c.id || x.replace(/^#/, "").toLowerCase() === c.name.toLowerCase())
            ? pill("skipped in config.yaml")
            : toggle(skip.has(c.id), (v) => { if (v) skip.add(c.id); else skip.delete(c.id); })))),
      h("div", { class: "row", style: { marginTop: "12px" } }, btn("Save skips", async (e) => {
        try { await run(e.target, () => api("PUT", C("/securitycam"), { ignore: [...skip] })); } catch { /* toast */ }
      }, "primary sm")))));
}

/* ---------------------------------------------------------------- announce */

async function announce(main) {
  const m = await meta();
  const ch = channelSelect(m.channels, ""), title = input({ placeholder: "Server update" });
  const text = textarea({ placeholder: "What do you want to say? Markdown works.", rows: "7" }), footer = input({ placeholder: "Optional" });
  let asEmbed = true, stamp = true;
  const preview = h("div");
  const draw = () => clear(preview, h("div", { class: "card", style: { background: "var(--bg)" } },
    asEmbed ? h("div", { style: { borderLeft: "3px solid var(--accent)", paddingLeft: "12px" } },
      title.value ? h("b", { style: { display: "block", marginBottom: "4px" } }, title.value) : null,
      h("div", { style: { whiteSpace: "pre-wrap" } }, text.value || h("span", { class: "faint" }, "Your message")),
      footer.value || stamp ? h("div", { class: "faint", style: { fontSize: "12px", marginTop: "8px" } }, [footer.value, stamp ? new Date().toLocaleString() : ""].filter(Boolean).join(" • ")) : null)
      : h("div", { style: { whiteSpace: "pre-wrap" } }, title.value ? h("b", null, title.value + "\n") : null, text.value || h("span", { class: "faint" }, "Your message"))));
  [title, text, footer].forEach((i) => i.addEventListener("input", draw));
  const send = btn("Send", async () => {
    if (!ch.value) return toast("Pick a channel.", true);
    try { await run(send, () => api("POST", C("/announce"), { channel: ch.value, title: title.value, text: text.value, footer: footer.value, embed: asEmbed, timestamp: stamp })); text.value = ""; draw(); } catch { /* toast */ }
  }, "primary");
  clear(main, head("Announce", "Post a message as the bot."),
    h("div", { class: "grid g2" }, card(null, h("div", { class: "form" }, field("Channel", ch), field("Title", title), field("Message", text),
      h("div", { class: "row" }, toggle(true, (v) => { asEmbed = v; draw(); }), h("span", null, "As an embed"), toggle(true, (v) => { stamp = v; draw(); }), h("span", null, "Timestamp")),
      field("Footer", footer), send)), card("Preview", preview)));
  draw();
}

/* ---------------------------------------------------------------- audit */

async function audit(main) {
  const d = await api("GET", C("/audit"));
  clear(main, head("Audit log", "Everything done through this dashboard."), card(null, d.entries.length ? h("div", { class: "scroll-x" }, h("table", { class: "table" },
    h("thead", null, h("tr", null, h("th", null, "When"), h("th", null, "Who"), h("th", null, "Action"), h("th", null, "Details"))),
    h("tbody", null, d.entries.map((e) => h("tr", null, h("td", { class: "nowrap faint", title: when(e.at) }, rel(e.at)), h("td", null, who(e.who)),
      h("td", null, h("b", null, e.action)), h("td", { class: "muted", style: { wordBreak: "break-word" } }, e.detail || "–")))))) : empty("Nothing yet.")));
}

/* ---------------------------------------------------------------- settings */

async function settings(main) {
  const d = await api("GET", "/api/settings");
  const want = S.route[1] || d.groups[0].id;
  const group = d.groups.find((g) => g.id === want) || d.groups[0];
  const changes = {};
  const savebar = h("div", { class: "savebar hidden" }, h("span", { class: "grow" }, "Unsaved changes"));
  const saveB = btn("Save", async () => {
    try { await run(saveB, () => api("PUT", "/api/settings", { changes })); for (const k in changes) delete changes[k]; S.me = await api("GET", "/api/me"); route(); } catch { /* toast */ }
  }, "primary");
  add(savebar, [btn("Discard", () => route(), "ghost sm"), saveB]);
  const mark = (f, row, v) => {
    if (JSON.stringify(v) === JSON.stringify(f.value)) delete changes[f.path]; else changes[f.path] = v;
    row.classList.toggle("changed", f.path in changes);
    savebar.classList.toggle("hidden", !Object.keys(changes).length);
  };
  const rows = group.fields.map((f) => {
    const row = h("div", { class: "setting" });
    const ctl = control(f, d.editable, (v) => mark(f, row, v));
    add(row, [h("div", { class: "l" }, h("b", null, f.label, f.restart ? h("span", { class: "tag pill yellow", title: "Takes effect after a restart" }, "restart") : null,
      f.overridden ? h("span", { class: "tag pill green", title: "Changed here; config.yaml has another value" }, "dashboard") : null),
    h("small", null, f.help || h("span", { class: "mono" }, f.path)),
    f.overridden && d.editable ? h("div", null, btn("Use config.yaml value", () => run(null, () => api("DELETE", `/api/settings/${encodeURIComponent(f.path)}`)).then(route).catch(() => {}), "ghost sm", { style: { paddingLeft: 0 } })) : null),
    ctl]);
    return row;
  });
  S.dirty = changes;
  clear(main, head("Settings", d.editable ? "Changes are saved in the bot's database and override config.yaml (which stays untouched)."
    : "Only bot owners can change these.", d.editable ? h("div", { class: "row" }, h("a", { class: "btn sm", href: "#/setup" }, "Setup wizard"),
    btn("Import", importSettings, "sm"),
    h("a", { class: "btn sm", href: "/api/settings/export", download: "vectiq-config.yaml" }, "Export")) : null),
  h("div", { class: "tabs" }, d.groups.map((g) => h("button", { type: "button", class: g.id === group.id && "on", onclick: () => { location.hash = `#/settings/${g.id}`; } }, g.title))),
  card(group.title, rows), savebar);
}

// Import an exported YAML file: show exactly what would change, then apply it.
function importSettings() {
  const pick = h("input", { type: "file", accept: ".yaml,.yml,text/yaml,text/plain", class: "hidden" });
  document.body.appendChild(pick);
  pick.addEventListener("change", async () => {
    const file = pick.files[0];
    pick.remove();
    if (!file) return;
    const text = await file.text();
    let p;
    try { p = await api("POST", "/api/settings/import", { yaml: text, apply: false }); } catch { return; }
    const show = (v) => (Array.isArray(v) ? v.join(", ") || "none" : v === true ? "on" : v === false ? "off" : v === "" || v == null ? "default" : typeof v === "object" ? JSON.stringify(v) : String(v));
    const body = h("div", { class: "import-preview" },
      h("p", { class: "muted" }, `${file.name}: ${p.changes.length} change${p.changes.length === 1 ? "" : "s"}, ${p.unchanged} already the same.`),
      p.errors.length ? [h("h4", null, "Can't import"), h("ul", { class: "bad" }, p.errors.map((x) => h("li", null, x)))] : null,
      p.changes.length ? h("div", { class: "list" }, p.changes.map((c) => h("div", { class: "item" },
        h("div", { class: "grow" }, h("b", null, c.label, c.restart ? h("span", { class: "tag pill yellow" }, "restart") : null), h("div", { class: "faint mono" }, c.path)),
        h("span", { class: "faint" }, show(c.from)), h("span", { class: "faint" }, " → "), h("b", null, show(c.to))))) : null,
      p.skipped.length ? h("details", null, h("summary", null, `${p.skipped.length} not imported here`),
        h("ul", { class: "faint" }, p.skipped.map((x) => h("li", null, x)))) : null);
    modal("Import settings", body, p.changes.length && !p.errors.length ? [{
      label: `Apply ${p.changes.length} change${p.changes.length === 1 ? "" : "s"}`,
      run: async () => { const r = await api("POST", "/api/settings/import", { yaml: text, apply: true }); toast(r.message); },
      after: async () => { S.me = await api("GET", "/api/me"); route(); },
    }] : []);
  });
  pick.click();
}

function control(f, editable, onchange) {
  const dis = !editable;
  if (f.type === "bool") return h("div", { class: "row", style: { justifyContent: "flex-end" } }, toggle(!!f.value, onchange, { disabled: dis }));
  if (f.type === "enum") { const s = select(f.options.map((o) => [o, o]), f.value, { disabled: dis }); s.addEventListener("change", () => onchange(s.value)); return s; }
  if (f.type === "int" || f.type === "number") {
    const i = input({ type: "number", value: f.value ?? "", min: f.min ?? null, max: f.max ?? null, step: f.type === "number" ? "any" : "1", disabled: dis });
    i.addEventListener("input", () => onchange(i.value === "" ? null : Number(i.value))); return i;
  }
  if (f.type === "longtext") { const t = textarea({ value: f.value || "", rows: "3", disabled: dis }); t.addEventListener("input", () => onchange(t.value)); return t; }
  if (f.type === "list") {
    const t = textarea({ value: (f.value || []).join("\n"), rows: "3", disabled: dis, placeholder: "One per line" });
    t.addEventListener("input", () => onchange(t.value.split("\n").map((x) => x.trim()).filter(Boolean))); return t;
  }
  if (f.type === "emoji_map") {
    const rows = h("div");
    const read = () => Object.fromEntries([...rows.children].map((r) => [r.children[0].value.trim(), r.children[1].value.trim()]).filter(([e, r]) => e && r));
    const addRow = (e = "", r = "") => {
      const a = input({ value: e, disabled: dis, style: { textAlign: "center" } }), b = input({ value: r, disabled: dis, placeholder: "Role" });
      const row = h("div", { class: "maprow" }, a, b, btn("✕", () => { row.remove(); onchange(read()); }, "ghost sm", { disabled: dis }));
      [a, b].forEach((x) => x.addEventListener("input", () => onchange(read())));
      rows.appendChild(row);
    };
    Object.entries(f.value || {}).forEach(([e, r]) => addRow(e, r));
    return h("div", null, rows, editable ? btn("+ Add", () => addRow(), "ghost sm") : null);
  }
  const i = input({ value: f.value ?? "", disabled: dis });
  if (f.type === "channel") {
    i.setAttribute("list", "channel-names");
    i.placeholder = "Channel name";
    channelNames();
  }
  i.addEventListener("input", () => onchange(i.value));
  return i;
}

// One shared <datalist> of the current community's channels, for every channel setting.
async function channelNames() {
  if (document.getElementById("channel-names") || !S.gid) return;
  const list = h("datalist", { id: "channel-names" });
  document.body.appendChild(list);
  try {
    const d = await api("GET", `/api/c/${encodeURIComponent(S.gid)}/channels`);
    add(list, d.channels.map((c) => h("option", { value: c.name })));
  } catch { /* typing a name still works */ }
}

/* ---------------------------------------------------------------- setup wizard */
// An installer-style walk-through: the bot asks one question per screen, a stage list on the
// left shows where you are, Back and Continue (or Enter) move between screens. Questions that
// don't apply are skipped as you answer. Nothing is saved until the "Ready" screen.
async function setup(main) {
  const d = await api("GET", "/api/settings");
  if (!d.editable) { clear(main, card(null, h("p", { class: "muted" }, "Only bot owners can run the setup wizard."))); return; }
  const fields = Object.fromEntries(d.groups.flatMap((g) => g.fields).map((f) => [f.path, f]));
  const T = d.wizard_text;
  let channels = [];
  if (S.gid) { try { channels = (await api("GET", `/api/c/${encodeURIComponent(S.gid)}/channels`)).channels.map((c) => c.name); } catch { /* typing works */ } }
  const comm = S.me.communities.find((c) => c.id === S.gid);
  const changes = {};
  const value = (p) => (p in changes ? changes[p] : fields[p].value);
  const ok = (when) => Object.entries(when || {}).every(([p, vals]) => vals.includes(value(p)));
  const shown = (v) => (Array.isArray(v) ? v.join(", ") || "none" : v === true ? "yes" : v === false ? "no" : v === "" || v == null ? "default" : String(v));
  const norm = (x) => String(x).toLowerCase().replace(/[^a-z0-9]/g, "");
  const channelMissing = (v) => channels.length && v && !channels.some((n) => n === v || norm(n).includes(norm(v)));
  const quiet = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Every screen, worked out again after each answer.
  const screens = () => {
    const out = [{ key: "hello", stage: "Welcome" }];
    for (const st of d.wizard.filter((w) => ok(w.when))) {
      if (st.id === "features") { out.push({ key: "features", stage: st.title, st }); continue; }
      st.paths.filter((p) => ok(d.wizard_when[p])).forEach((p, i) => out.push({ key: `q:${p}`, stage: st.title, st, path: p, first: i === 0 }));
    }
    out.push({ key: "ready", stage: "Ready" });
    return out;
  };
  let current = "hello";
  let done = null;   // set after saving: { message, problems }

  const set = (p, v) => { if (JSON.stringify(v) === JSON.stringify(fields[p].value)) delete changes[p]; else changes[p] = v; };

  // The bot's side of the conversation; a short "typing" pause before it speaks.
  const bot = (lines) => {
    const box = h("div", { class: "wiz-bot" }, h("div", { class: "mark wiz-face", "aria-hidden": "true" }, h("i")));
    const said = h("div", { class: "wiz-said", "aria-live": "polite" });
    box.appendChild(said);
    const speak = () => add(said, lines.filter(Boolean).map((t) => h("p", { class: "wiz-bubble" }, t)));
    if (quiet) speak();
    else { said.appendChild(h("p", { class: "wiz-bubble wiz-typing", "aria-label": "Vectiq is typing" }, h("i"), h("i"), h("i")));
      setTimeout(() => { said.textContent = ""; speak(); }, 420); }
    return box;
  };

  // The answer area for one setting.
  const answer = (p) => {
    const f = { ...fields[p], value: value(p) };
    const help = d.option_help[p] || {};
    if (f.type === "enum" || f.type === "bool") {
      const opts = f.type === "bool" ? [[true, "Yes"], [false, "No"]] : f.options.map((o) => [o, o]);
      const group = h("div", { class: "choices", role: "radiogroup", "aria-label": f.label });
      const pick = (v) => { set(p, v); [...group.children].forEach((b) => { const on = b.dataset.v === JSON.stringify(v); b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on)); }); };
      add(group, opts.map(([v, label]) => h("button", { type: "button", class: "choice" + (v === f.value ? " on" : ""), role: "radio",
        "aria-checked": String(v === f.value), "data-v": JSON.stringify(v), onclick: () => pick(v), ondblclick: () => { pick(v); go(1); } },
      h("b", null, label), help[v] ? h("span", null, help[v]) : null)));
      return group;
    }
    if (f.type === "channel" && channels.length) {
      const known = channels.includes(f.value);
      const other = input({ value: known ? "" : f.value || "", placeholder: "Type a channel name", class: "input" + (known || !f.value ? " hidden" : "") });
      const sel = select([["", "Default"], ...channels.map((n) => [n, `#${n}`]), ["\u0000other", "Another name…"]], known ? f.value : f.value ? "\u0000other" : "");
      sel.addEventListener("change", () => {
        if (sel.value === "\u0000other") { other.classList.remove("hidden"); other.focus(); set(p, other.value); } else { other.classList.add("hidden"); set(p, sel.value); }
      });
      other.addEventListener("input", () => set(p, other.value));
      return h("div", { class: "stack" }, sel, other);
    }
    return control(f, true, (v) => set(p, v));
  };

  const features = (st) => h("div", { class: "wiz-checklist", role: "group", "aria-label": "Features" }, st.paths.flatMap((p, n) => {
    const f = fields[p];
    const box = h("input", { type: "checkbox", checked: !!value(p), "data-path": p, onchange: () => {
      set(p, box.checked);
      if (box.checked && f.slot) st.paths.filter((q) => q !== p && fields[q].slot === f.slot && value(q)).forEach((q) => {
        set(q, false);
        const other = box.closest(".wiz-checklist")?.querySelector(`input[data-path="${q}"]`);
        if (other) other.checked = false;
      });
    } });
    const head = f.group && (n === 0 || fields[st.paths[n - 1]].group !== f.group) ? [h("h4", { class: "wiz-group" }, f.group)] : [];
    return [...head, h("label", { class: "wiz-check" }, box, h("span", null, h("b", null, f.label), h("small", null, f.help)))];
  }));

  const summary = () => {
    const keys = Object.keys(changes);
    if (!keys.length) return h("p", { class: "muted" }, "You haven't changed anything, so there's nothing to save. Go back to change something, or close the wizard.");
    const warn = keys.filter((k) => fields[k].type === "channel" && channelMissing(changes[k]));
    return [
      ...d.wizard.map((st) => [st, keys.filter((k) => st.paths.includes(k))]).filter(([, ks]) => ks.length).map(([st, ks]) =>
        h("div", { class: "wiz-sum" }, h("h4", null, st.title), ks.map((k) => h("div", { class: "wiz-sum-row" },
          h("span", null, fields[k].label), h("span", { class: "faint" }, shown(fields[k].value)), h("span", { class: "faint", "aria-label": "becomes" }, "→"), h("b", null, shown(changes[k])))))),
      warn.length ? h("p", { class: "wiz-warn" }, `I can't find ${warn.map((k) => `"${changes[k]}"`).join(", ")}${comm ? ` in ${comm.name}` : ""}. I'll ignore it until a channel with that name exists.`) : null,
      keys.some((k) => fields[k].restart) ? h("p", { class: "muted" }, "A few of these need me to restart before they take effect.") : null,
    ];
  };

  function go(step) {
    const list = screens();
    const i = Math.max(0, list.findIndex((x) => x.key === current));
    const next = list[Math.min(Math.max(i + step, 0), list.length - 1)];
    current = next.key;
    draw();
  }

  async function apply(btnEl) {
    if (!Object.keys(changes).length) { location.hash = "#/settings"; return; }
    try {
      const r = await run(btnEl, () => api("PUT", "/api/settings", { changes, checkpoint: "Before the setup wizard" }));
      for (const k in changes) delete changes[k];
      S.me = await api("GET", "/api/me");
      let problems = [];
      if (S.gid) { try { problems = (await api("GET", `/api/c/${encodeURIComponent(S.gid)}/setup-check`)).problems; } catch { /* optional */ } }
      done = { message: r.message, problems };
      draw();
    } catch { /* the toast explains */ }
  }

  function draw() {
    const list = screens();
    let i = list.findIndex((x) => x.key === current);
    if (i < 0) { i = Math.min(list.length - 1, 1); current = list[i].key; }
    const scr = done ? { key: "done", stage: "Done" } : list[i];
    const stages = [...new Set([...list.map((x) => x.stage), "Done"])];
    const here = stages.indexOf(scr.stage);
    const side = h("ol", { class: "wiz-stages" }, stages.map((name, n) =>
      h("li", { class: n < here ? "done" : n === here ? "on" : null, "aria-current": n === here ? "step" : null }, name)));
    const pct = done ? 100 : Math.round((i / (list.length - 1)) * 100);

    let talk, body = null;
    if (done) {
      talk = [T.done, done.problems.length ? `There's still something to sort out${comm ? ` in ${comm.name}` : ""}:` : `I've got everything I need${comm ? ` in ${comm.name}` : ""}.`];
      body = [done.problems.length ? h("ul", { class: "wiz-todo" }, done.problems.map((x) => h("li", null, x))) : null,
        h("p", { class: "muted" }, done.message), h("p", { class: "muted" }, "Want to see it work? Join with a second account, or type !verification in the community.")];
    } else if (scr.key === "hello") {
      talk = [T.hello, comm ? `We'll set things up with ${comm.name} in mind.` : null];
    } else if (scr.key === "features") {
      talk = [scr.st.say]; body = features(scr.st);
    } else if (scr.key === "ready") {
      talk = [T.ready]; body = summary();
    } else {
      const f = fields[scr.path];
      talk = [scr.first ? scr.st.say : null, d.wizard_ask[scr.path] || f.label];
      body = [answer(scr.path), f.help ? h("p", { class: "faint wiz-hint" }, f.help) : null,
        f.restart ? h("p", { class: "faint wiz-hint" }, "This one takes effect after a restart.") : null];
    }

    const back = btn("Back", () => go(-1), "ghost", { disabled: done || i === 0 });
    const skip = !done && scr.path ? btn("Skip section", () => {
      const last = list.filter((x) => x.stage === scr.stage).pop();
      current = last.key; go(1);
    }, "ghost") : null;
    let next;
    if (done) next = h("a", { class: "btn primary", href: "#/settings" }, "Finish");
    else if (scr.key === "ready") next = btn(Object.keys(changes).length ? "Save and finish" : "Close", () => apply(next), "primary");
    else next = btn(scr.key === "hello" ? "Let's go" : "Continue", () => go(1), "primary");

    const panel = h("section", { class: "wiz-panel" },
      h("div", { class: "wiz-progress", role: "progressbar", "aria-valuenow": String(pct), "aria-valuemin": "0", "aria-valuemax": "100", "aria-label": "Setup progress" }, h("i", { style: { width: `${pct}%` } })),
      h("div", { class: "wiz-body" }, bot(talk), body ? h("div", { class: "wiz-answer" }, body) : null),
      h("footer", { class: "wiz-foot" }, back, h("span", { class: "grow" }), skip, next));
    const frame = h("div", { class: "wiz" }, h("aside", { class: "wiz-side" }, h("div", { class: "wiz-title" }, "Vectiq setup"), side), panel);
    frame.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && e.target.tagName !== "TEXTAREA" && e.target.tagName !== "BUTTON" && e.target.tagName !== "SELECT") { e.preventDefault(); next.click(); }
      if (e.key === "ArrowLeft" && e.altKey) { e.preventDefault(); back.click(); }
    });
    clear(main, frame);
    S.dirty = changes;
    setTimeout(() => (frame.querySelector(".wiz-answer input:not([type=checkbox]), .wiz-answer select, .wiz-answer textarea, .choice.on, .choice") || next).focus({ preventScroll: true }), quiet ? 0 : 440);
  }
  draw();
}

/* ---------------------------------------------------------------- restore points */
// Like System Restore: a list of moments you can go back to. Rolling back saves "now" first.
async function restore(main) {
  if (!S.me.owner) { clear(main, card(null, h("p", { class: "muted" }, "Only bot owners can see restore points."))); return; }
  const d = await api("GET", "/api/restore-points");
  const KIND = { scheduled: ["Scheduled", ""], automatic: ["Automatic", "yellow"], manual: ["Made by you", "green"] };
  const size = (n) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`);
  const label = input({ placeholder: "What's this one for? e.g. Before the event season", maxlength: "200" });
  const make = btn("Create restore point", async () => {
    try { const r = await run(make, () => api("POST", "/api/restore-points", { label: label.value })); toast(r.message); route(); } catch { /* toast */ }
  }, "primary");
  label.addEventListener("keydown", (e) => { if (e.key === "Enter") make.click(); });
  const rollback = (p) => modal("Roll back?", h("div", { class: "stack" },
    h("p", null, "Everything goes back to how it was on ", h("b", null, p.when), ": ", p.label, "."),
    h("p", { class: "muted" }, "Levels, coins, tickets, events, warnings and settings made since then are undone. Messages already sent in chat stay."),
    h("p", null, "I'll make a restore point of how things are right now first, so you can undo this.")),
  [{ label: "Roll back", kind: "danger", run: async () => { const r = await api("POST", `/api/restore-points/${encodeURIComponent(p.id)}/rollback`); toast(r.message); },
    after: async () => { S.me = await api("GET", "/api/me"); route(); } }]);
  const remove = (p) => modal("Delete this restore point?", h("p", null, `${p.when}: ${p.label}. You can't roll back to it afterwards.`),
    [{ label: "Delete", kind: "danger", run: () => api("DELETE", `/api/restore-points/${encodeURIComponent(p.id)}`), after: route }]);
  const every = Number(d.every_hours) || 0;
  clear(main, head("Restore points", every
    ? `I make one every ${every === 24 ? "day" : `${every} hours`}, and before risky changes like imports and upgrades. I keep ${d.keep_automatic} of those and ${d.keep_manual} of yours.`
    : `Scheduled points are off. I still make one before risky changes, like imports and upgrades.`),
  card("Make one now", h("div", { class: "row" }, h("div", { class: "grow" }, label), make)),
  card(`${d.points.length} restore point${d.points.length === 1 ? "" : "s"}`, d.points.length
    ? h("div", { class: "list" }, d.points.map((p, i) => h("div", { class: "item rp" },
      h("div", { class: "rp-dot", "aria-hidden": "true" }),
      h("div", { class: "grow" }, h("b", null, p.label), h("div", { class: "faint" }, `${p.when} · ${size(p.size)}${i === 0 ? " · newest" : ""}`)),
      pill(KIND[p.kind]?.[0] || p.kind, KIND[p.kind]?.[1] || ""),
      btn("Roll back…", () => rollback(p), "sm"),
      h("a", { class: "btn ghost sm", href: `/api/restore-points/${encodeURIComponent(p.id)}/download`, download: `${p.id}.zip` }, "Download"),
      btn("Delete", () => remove(p), "ghost sm"))))
    : empty("No restore points yet. Make one above, or wait for the first scheduled one.")),
  h("p", { class: "faint" }, `Saved in ${d.dir}. The bot's key in .env is never included.`));
}

/* ---------------------------------------------------------------- module panels */
// Any module can describe a page as data (see vectiq.plugin): status tiles, text, lists, tables, a log and buttons.

const TONE = { green: "green", ok: "green", yellow: "yellow", warn: "yellow", red: "red", bad: "red" };

function panelSection(sec, act) {
  switch (sec.type) {
    case "status": return h("div", { class: "panel-stats" }, (sec.items || []).map((it) =>
      h("div", { class: ["panel-stat", TONE[it.tone] && `tone-${TONE[it.tone]}`] }, h("div", { class: "faint" }, it.label),
        h("div", { class: ["panel-value", it.mono && "mono"] }, String(it.value ?? "–")))));
    case "text": return card(sec.title || null, h("p", { class: sec.tone === "warn" ? "warn" : "muted", style: { margin: 0, whiteSpace: "pre-wrap" } }, sec.text || ""));
    case "list": return card(sec.title || null, (sec.items || []).length ? h("div", { class: "list" }, sec.items.map((it) =>
      h("div", { class: "item" }, h("div", { class: "grow" }, h("b", null, it.title), it.detail ? h("div", { class: "faint" }, it.detail) : null),
        it.tag ? pill(it.tag, TONE[it.tone] || "") : null))) : empty(sec.empty || "Nothing here yet."));
    case "table": return card(sec.title || null, h("div", { class: "tablewrap" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, (sec.columns || []).map((c) => h("th", null, c)))),
      h("tbody", null, (sec.rows || []).map((r) => h("tr", null, r.map((c) => h("td", null, String(c)))))))));
    case "log": {
      const pre = h("pre", { class: "panel-log" }, (sec.lines || []).join("\n") || "Nothing yet.");
      setTimeout(() => { pre.scrollTop = pre.scrollHeight; }, 0);
      return card(sec.title || "Log", pre);
    }
    case "actions": return h("div", { class: "row wrap" }, (sec.items || []).map((a) => {
      const b = btn(a.label, async () => {
        if (a.confirm && !(await confirmBox(a.label, a.confirm, a.label, a.kind === "danger" ? "danger" : "primary"))) return;
        try { const r = await run(b, () => act(a.id)); toast(r.message); } catch { /* toast */ }
      }, a.kind || "");
      return b;
    }));
    default: return null;
  }
}

async function modulePanel(main) {
  const name = S.route[S.route.indexOf("m") + 1];
  const scoped = S.route[0] === "c";
  const q = scoped ? `?gid=${encodeURIComponent(S.gid)}` : "";
  const act = (id) => api("POST", `/api/panel/${encodeURIComponent(name)}/action/${encodeURIComponent(id)}`, { gid: scoped ? S.gid : "" })
    .then((r) => { setTimeout(draw, 600); return r; });
  async function draw() {
    let d;
    try { d = await api("GET", `/api/panel/${encodeURIComponent(name)}${q}`); } catch (e) { clear(main, card(null, h("p", { class: "muted" }, e.message))); return; }
    if (!main.isConnected) return;
    clear(main, head(d.title || name, d.subtitle || ""), h("div", { class: "stack" }, (d.sections || []).map((sec) => panelSection(sec, act))));
    clearTimeout(S.panelTimer);
    if (d.refresh) S.panelTimer = setTimeout(draw, Math.max(2, d.refresh) * 1000);
  }
  await draw();
}

/* ---------------------------------------------------------------- webhooks */

async function webhooks(main) {
  const d = await api("GET", "/api/webhooks");
  if (!d.enabled) { clear(main, head("Webhooks"), card(null, empty("The webhooks module is turned off. Turn it on in Settings → Modules and restart."))); return; }
  const report = h("div");
  const showReport = (lines) => clear(report, lines && lines.length ? card("Result", h("div", { class: "list" }, lines.map((l) => h("div", { class: "item" }, l)))) : null);
  const sync = btn("Sync now", () => run(sync, async () => { const r = await api("POST", "/api/webhooks/sync"); showReport(r.report); return { message: "Synced." }; }).catch(() => {}), "");
  const edit = (hook, index) => {
    const name = input({ value: hook?.name || "", placeholder: "deploys" }), channel = input({ value: hook?.channel || "", placeholder: "Channel name or id" });
    const community = input({ value: hook?.community || "", placeholder: "Blank = the first community" });
    const evs = new Set(hook?.events || []);
    const boxes = h("div", { class: "row wrap" }, d.events.map((e) => h("label", { class: "row", style: { gap: "6px" } },
      toggle(evs.has(e), (v) => (v ? evs.add(e) : evs.delete(e))), h("span", null, e))));
    const list = d.hooks.map((x) => ({ name: x.name, channel: x.channel, events: x.events }));
    modal(hook ? `Edit ${hook.name}` : "New webhook", h("div", { class: "form" }, field("Name", name), field("Channel", channel), field("Community", community),
      field("Mirror these bot events into it", boxes)),
    [{ label: "Save", after: route, run: async () => {
      const item = { name: name.value.trim(), channel: channel.value.trim(), events: [...evs], ...(community.value.trim() ? { community: community.value.trim() } : {}) };
      if (index === undefined) list.push(item); else list[index] = item;
      const r = await api("PUT", "/api/webhooks", { hooks: list }); setTimeout(() => showReport(r.report), 50); return r;
    } }]);
  };
  clear(main, head("Webhooks", "Each hook is a URL outside tools can post to; it shows up in its channel. Bot events can be mirrored too.",
    sync, btn("+ New webhook", () => edit(null), "primary")),
  d.overridden ? h("p", { class: "muted" }, "This list was changed in the dashboard and overrides webhooks.hooks in config.yaml.") : null,
  card(null, d.hooks.length ? h("div", { class: "list" }, d.hooks.map((x, i) => h("div", { class: "item" },
    h("div", { class: "grow" }, h("b", null, x.name), h("div", { class: "faint", style: { fontSize: "13px" } },
      x.channel_name ? `#${x.channel_name}` : `⚠️ channel “${x.channel}” not found`, x.events.length ? ` · mirrors ${x.events.join(", ")}` : "")),
    x.channel_id ? btn("Test", (e) => run(e.target, () => api("POST", `/api/webhooks/${encodeURIComponent(x.name)}/test`)).catch(() => {}), "sm") : null,
    x.channel_id ? btn("New URL", async (e) => {
      if (!(await confirmBox(`New URL for ${x.name}?`, "The current URL stops working right away.", "Make new URL"))) return;
      try {
        const r = await run(e.target, () => api("POST", `/api/webhooks/${encodeURIComponent(x.name)}/rotate`));
        const box = input({ value: r.url, readonly: true, class: "input mono" });
        modal("Your new webhook URL", h("div", { class: "stack" }, h("p", { class: "muted", style: { margin: 0 } }, "Copy it now: it is only shown once. Use it anywhere a Discord webhook URL works."),
          box, btn("Copy", () => { box.select(); navigator.clipboard?.writeText(r.url).then(() => toast("Copied."), () => {}); }, "primary")));
      } catch { /* toast */ }
    }, "sm") : null,
    btn("Edit", () => edit(x, i), "ghost sm"),
    btn("✕", async (e) => {
      if (!(await confirmBox(`Remove ${x.name}?`, "It's taken out of the list. Delete the hook in Vector too if you want its URL to stop working.", "Remove"))) return;
      run(e.target, () => api("PUT", "/api/webhooks", { hooks: d.hooks.filter((_, j) => j !== i).map((y) => ({ name: y.name, channel: y.channel, events: y.events })) })).then(route).catch(() => {});
    }, "ghost sm", { title: "Remove" })))) : empty("No webhooks yet.")), report,
  h("p", { class: "faint", style: { fontSize: "13px" } }, d.server.enabled ? `Receiving posts at ${d.server.base_url}.` : "The receiving server is off: hooks can mirror bot events, but outside tools can't post until webhooks.server.enabled is on."));
}

/* ---------------------------------------------------------------- accounts */

function passwordFields() {
  const a = input({ type: "password", autocomplete: "new-password", placeholder: "10+ characters" });
  const b = input({ type: "password", autocomplete: "new-password" });
  return { a, b, check() { if (a.value !== b.value) throw new ApiError("The passwords don't match."); return a.value; } };
}

async function account(main) {
  const d = await api("GET", "/api/account");
  const parts = [head("My account", `Signed in as ${S.me.user.name}.`)];
  if (!d.usernames.length) {
    const user = input({ autocomplete: "username", placeholder: "e.g. lucky", autocapitalize: "none" }), pw = passwordFields();
    const go = btn("Create login", () => run(go, async () => { const r = await api("POST", "/api/account", { username: user.value, password: pw.check() }); setTimeout(route, 50); return r; }).catch(() => {}), "primary");
    parts.push(card("Set up a username and password", h("p", { class: "muted", style: { marginTop: 0 } },
      "So you can sign in without a code from Vector. What you can manage still follows your admin role in Vector."),
    h("div", { class: "form two" }, h("div", { class: "span" }, field("Username", user, "3–32 letters, numbers, dots, dashes or underscores")),
      field("Password", pw.a), field("Password again", pw.b), h("div", { class: "span" }, go))));
  } else {
    for (const username of d.usernames) {
      const cur = input({ type: "password", autocomplete: "current-password" }), pw = passwordFields();
      const go = btn("Change password", () => run(go, async () => { const r = await api("PUT", "/api/account/password", { username, current: cur.value, new: pw.check() }); cur.value = pw.a.value = pw.b.value = ""; return r; }).catch(() => {}), "primary");
      parts.push(card(h("div", { class: "row grow" }, h("h2", null, "Password"), pill(username, "green")),
        h("div", { class: "form two" }, h("div", { class: "span" }, field("Current password", cur)), field("New password", pw.a), field("New password again", pw.b),
          h("div", { class: "span" }, go))));
    }
  }
  const out = btn("Sign out everywhere", async () => {
    if (await confirmBox("Sign out everywhere?", "Every browser signed in to your account has to sign in again, this one too.", "Sign out everywhere")) {
      try { await api("POST", "/api/auth/logout-everywhere"); } catch { /* signed out anyway */ }
      S.me = null; location.hash = ""; showLogin();
    }
  }, "danger");
  parts.push(h("div", { style: { marginTop: "16px" } }, card("Sessions", h("p", { class: "muted", style: { marginTop: 0 } }, "Lost a device or shared a computer?"), out)),
    h("p", { class: "faint mono", style: { marginTop: "16px", wordBreak: "break-all" } }, d.npub));
  clear(main, ...parts);
}

async function users(main) {
  const d = await api("GET", "/api/users");
  const create = () => {
    const user = input({ autocapitalize: "none", placeholder: "e.g. alice" }), npub = input({ placeholder: "npub1…", spellcheck: "false" }), pw = passwordFields();
    modal("New login", h("div", { class: "form" }, field("Username", user), field("Vector npub", npub, "Their admin role in Vector decides what they can manage."),
      field("Password", pw.a, "Share it with them privately; they can change it on My account."), field("Password again", pw.b)),
    [{ label: "Create", after: route, run: () => api("POST", "/api/users", { username: user.value, npub: npub.value, password: pw.check() }) }]);
  };
  const reset = (u) => {
    const pw = passwordFields();
    modal(`New password for ${u.username}`, h("div", { class: "form" }, field("Password", pw.a), field("Password again", pw.b)),
      [{ label: "Set password", after: route, run: () => api("POST", `/api/users/${encodeURIComponent(u.username)}/password`, { password: pw.check() }) }]);
  };
  clear(main, head("Users", "Dashboard logins. Each belongs to a Vector account, whose admin role decides what it may manage.", btn("+ New login", create, "primary")),
    card(null, d.users.length ? h("div", { class: "scroll-x" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", null, "Username"), h("th", null, "Vector account"), h("th", { class: "hide-sm" }, "Last sign-in"), h("th", null, "Status"), h("th"))),
      h("tbody", null, d.users.map((u) => h("tr", null, h("td", null, h("b", null, u.username)), h("td", null, who(u.person, u.npub.slice(0, 18) + "…")),
        h("td", { class: "hide-sm faint" }, u.last_login ? rel(u.last_login) : "never"),
        h("td", null, u.locked ? pill("locked", "red") : u.can_sign_in ? pill("active", "green") : pill("no access", "yellow")),
        h("td", { class: "nowrap" }, btn("Password", () => reset(u), "ghost sm"), btn("Delete", async (e) => {
          if (await confirmBox(`Delete ${u.username}?`, "They're signed out and can't use this login again.", "Delete")) run(e.target, () => api("DELETE", `/api/users/${encodeURIComponent(u.username)}`)).then(route).catch(() => {});
        }, "ghost sm"))))))) : empty("No logins yet. People can still sign in with a Vector code if that's on.")));
}

/* ---------------------------------------------------------------- start */

boot().catch(() => {});
