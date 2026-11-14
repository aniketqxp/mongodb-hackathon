// J1 UI. Talks only to ui/server.py:
//   /ui/*  -> the J2 harness (feed, watch, retract, PIN-checked directive confirm)
//   /api/* -> read-only core routes from OPS/CONTRACT.md (/why, /ledger)
// No enforcement happens here: the gate and block > boost run in the harness and core.
"use strict";

const S = {
  cfg: null,         // {pack_id, scopes, labels, api_base, memory_source, vocab}
  scope: null,       // current scope_id
  feed: null,        // last /ui/feed response
  mem: {},           // node_id -> text (remembered across refreshes so retracted ones keep a label)
  retracted: new Set(),
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const qs = (o) => new URLSearchParams(o).toString();
const ICON = { animals: "🐙", space: "🚀", science: "🔬", music: "🎵", art_craft: "🎨", cooking: "🍳", gaming: "🎮",
  nature: "🌿", history: "🏛️", comedy: "😂", spooky: "👻", action: "💥" };
const MATURITY = { 0: "all ages", 1: "7+", 2: "10+", 3: "13+" };
const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const memText = (id) => S.mem[id] || id;
const dur = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// ---------- HTTP ----------
class ApiError extends Error {
  constructor(code, detail, status) { super(`${code}: ${detail}`); this.code = code; this.detail = detail; this.status = status; }
}
async function call(method, path, body) {
  const res = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty */ }
  if (data && data.error) throw new ApiError(data.error.code, data.error.detail, res.status);
  if (!res.ok) throw new ApiError("internal", `HTTP ${res.status}`, res.status);
  return data;
}
const scoped = (extra = {}) => ({ pack_id: S.cfg.pack_id, scope_id: S.scope, ...extra });

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._h);
  toast._h = setTimeout(() => t.classList.remove("show"), 3500);
}

// ---------- Feed ----------
async function loadFeed({ reset = false } = {}) {
  if (reset) { S.retracted.clear(); }
  const prev = S.feed && S.feed.scope_id === S.scope ? S.feed.slate : [];
  S.feed = await call("GET", `/ui/feed?${qs({ scope_id: S.scope, ...(reset ? { reset: 1 } : {}) })}`);
  S.feed.memories.forEach((m) => { S.mem[m.node_id] = m.text; });
  renderFeed();
  return { prev, next: S.feed.slate };
}

function renderFeed() {
  const f = S.feed;
  const showMarks = f.had_previous && f.removed.length > 0; // only after something was replaced
  $("#cards").innerHTML = f.slate.map((e) => {
    const mark = e.status === "boosted" ? "boosted" : showMarks ? e.status : "";
    const badge = {
      boosted: `<span class="badge boost">Boosted</span>`,
      kept: `<span class="badge kept">Kept</span>`,
      new: `<span class="badge new">New</span>`,
    }[mark] || "";
    return `
      <article class="vcard ${esc(mark)}" data-id="${esc(e.video_id)}">
        <button class="thumb t-${esc(e.topic)}" data-act="watch" aria-label="Watch ${esc(e.title)}">
          <span aria-hidden="true">${ICON[e.topic] || "▶️"}</span>
          ${e.duration_s ? `<span class="dur">${dur(e.duration_s)}</span>` : ""}
        </button>
        <div class="vbody">
          <div class="vtitle">${esc(e.title)}</div>
          <div class="vmeta">${esc(e.topic.replace("_", " & "))} ${badge}</div>
        </div>
        <div class="vmore">
          <button class="more-btn" data-act="menu" aria-label="More options" aria-haspopup="menu">⋮</button>
          <div class="menu" role="menu" hidden>
            <button role="menuitem" data-act="why">Why this?</button>
            <button role="menuitem" data-act="unrec">Don't recommend</button>
          </div>
        </div>
      </article>`;
  }).join("") || `<p class="hint">Nothing to recommend right now.</p>`;
}

const entry = (vid) => S.feed.slate.find((e) => e.video_id === vid);
const closeMenus = () => document.querySelectorAll(".vcard .menu").forEach((m) => { m.hidden = true; });

// ---------- Watch / gate ----------
async function watch(vid, title) {
  try {
    const r = await call("POST", "/ui/watch", { scope_id: S.scope, video_id: vid });
    if (r.admitted) { toast("Watched. Saved to memory."); return; }
    toast(`Blocked: “${title || vid}” is above the age limit.`);
    addReceipt({
      title: "Gate blocked a video",
      html: `<p><b>${esc(title || vid)}</b> · nothing saved to memory</p>`,
    });
  } catch (e) { toast(`Watch failed: ${e.detail}`); }
}

function probe() {
  const g = (S.feed.receipt.gated || [])[0];
  if (!g) { toast("Nothing in this child's interests is above their age limit."); return; }
  watch(g.video_id, g.title);
}

// ---------- Why this? / un-recommend ----------
async function why(vid, mode = "why") {
  const e = entry(vid);
  $("#why-title").textContent = mode === "unrec" ? `Don't recommend “${e.title}”` : `Why “${e.title}”?`;
  $("#why-body").innerHTML = `<p class="hint">Loading…</p>`;
  $("#why-dialog").showModal();
  const memories = `
    <h3>${mode === "unrec" ? "Remove which memory?" : "Because"}</h3>
    <div class="chain">${e.supports.map((n) => `
      <div class="link">${esc(memText(n))}<br>
        <button class="small ${mode === "unrec" ? "primary" : "ghost"}" data-retract="${esc(n)}" data-vid="${esc(vid)}">Remove</button>
      </div>`).join("") || "<p class='hint'>Parent rule</p>"}</div>`;
  if (mode === "unrec") { $("#why-body").innerHTML = memories; return; }
  try {
    const r = await call("GET", `/api/why/${encodeURIComponent(e.decision_id)}?${qs(scoped())}`);
    $("#why-body").innerHTML = `
      ${memories}
      <h3>Provenance</h3>
      <div class="chain">${(r.provenance || []).map((p) => `<div class="link"><span class="mono">${esc(p.node_id)}</span> —${esc(p.rel || "")}→ decision<br>${esc(memText(p.node_id))}</div>`).join("") || "<p class='hint'>none returned</p>"}</div>
      <h3>Ledger</h3>
      <ul>${(r.ledger || []).map((l) => `<li><span class="mono">${esc(l.ts || "")}</span> ${esc(l.actor || "")} ${esc(l.action || "")} ${esc(l.target || "")}</li>`).join("") || "<li class='hint'>no entries</li>"}</ul>`;
  } catch (err) {
    $("#why-body").innerHTML = `${memories}<p class="receipt err">Core provenance unavailable: ${esc(err.detail)}</p>`;
  }
}

async function unrecommend(vid) {
  const e = entry(vid);
  if (e.supports.length === 1) {
    if (confirm(`Remove “${memText(e.supports[0])}”?`)) {
      await retract(e.supports[0], `parent_unrecommend:${vid}`);
    }
    return;
  }
  why(vid, "unrec"); // several memories: let the parent pick which one is wrong
}

async function retract(nodeId, reason) {
  try {
    const r = await call("POST", "/ui/retract", { scope_id: S.scope, target_id: nodeId, reason });
    S.retracted.add(nodeId);
    if ($("#why-dialog").open) $("#why-dialog").close();
    const { prev, next } = await loadFeed();
    const nextIds = new Set(next.map((x) => x.video_id));
    const removed = prev.filter((x) => !nextIds.has(x.video_id));
    const kept = next.filter((x) => x.status === "kept");
    const added = next.filter((x) => x.status === "new");
    addReceipt({
      title: `Removed: ${memText(nodeId)}`,
      html: `
        <div class="diff">
          <div class="col"><h4>Before</h4>${prev.map((x) => `<div class="${nextIds.has(x.video_id) ? "same" : "gone"}">${esc(x.title)}</div>`).join("")}</div>
          <div class="col"><h4>After</h4>${next.map((x) => `<div class="${x.status === "new" ? "added" : "same"}">${esc(x.title)}${x.status === "kept" && x.supports.length ? " ✓" : ""}</div>`).join("")}</div>
        </div>
        <p class="hint">${removed.length} replaced · ${kept.length} kept ✓ · ${added.length} new</p>
        <details><summary>Recall plan</summary>
          <p>Replayed decisions: <span class="mono">${esc((r.replayed || []).join(", ") || "none")}</span></p>
          <ul>${(r.plan?.actions || []).map((a) => `<li><span class="act ${esc(a.action)}">${esc(a.action)}</span><span class="mono">${esc(a.id)}</span>${a.reason ? ` <span class="hint">(${esc(a.reason)})</span>` : ""}</li>`).join("")}</ul>
          <p class="hint mono">GET /diff → changed: ${esc(JSON.stringify(r.diff?.changed || []))} · preserved: ${esc(JSON.stringify(r.diff?.preserved || []))}</p>
        </details>`,
    });
    $("#changes-dialog").showModal();
  } catch (e) {
    addReceipt({ title: "Retract failed", html: `<p>${esc(e.code)}: ${esc(e.detail)}</p>`, err: true });
  }
}

// ---------- Parent directive: parse -> confirm with PIN ----------
function nextSundayLocal() {
  const d = new Date();
  d.setDate(d.getDate() + ((7 - d.getDay()) % 7 || 7));
  d.setHours(23, 59, 0, 0);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function draftDirective() {
  const type = $("#d-type").value;
  const exp = $("#d-exp").value;
  return {
    type,
    target: { kind: type === "retract" ? "node" : $("#d-kind").value, value: $("#d-value").value.trim() },
    expires_at: exp && type !== "retract" ? new Date(exp).toISOString() : null,
    cap: type === "prioritize" ? Number($("#d-cap").value || 0) : 0,
    confirmed_by: null, // set server-side only after the PIN check
    source_text: $("#parent-text").value.trim(),
  };
}

function plainWords(d) {
  const v = d.target.value ? d.target.value.replace("_", " & ") : "…";
  const what = d.target.kind === "tag" ? `videos tagged “${v}”` : `${v} videos`;
  const until = d.expires_at ? new Date(d.expires_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : null;
  if (d.type === "suppress") return `Hide ${what}${until ? ` until ${until}` : " (pick an end time)"}.`;
  if (d.type === "prioritize") return `Show more ${what}, up to ${d.cap || "?"} at a time${until ? `, until ${until}` : ""}.`;
  return `Forget ${d.target.value ? `“${memText(d.target.value)}”` : "…"} and update the feed.`;
}

function validate(d) {
  if (!d.target.value) return "Fill in the target value.";
  if (d.type === "suppress" && !d.expires_at) return "A block needs an end time.";
  if (d.type === "prioritize" && !(d.cap >= 1)) return "A boost needs a cap of at least 1.";
  return null;
}

function syncDirectiveForm() {
  const t = $("#d-type").value;
  $("#wrap-exp").hidden = t === "retract";
  $("#wrap-cap").hidden = t !== "prioritize";
  $("#d-kind").disabled = t === "retract";
  const kind = t === "retract" ? "node" : $("#d-kind").value;
  const opts = kind === "node" ? Object.keys(S.mem).map((id) => [id, S.mem[id]])
    : (S.cfg.vocab[kind] || []).map((v) => [v, ""]);
  $("#values").innerHTML = opts.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
  $("#d-plain").textContent = plainWords(draftDirective());
}

function toLocalInput(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fillSlots(d) {
  $("#d-type").value = d.type;
  if (d.type !== "retract") $("#d-kind").value = d.target.kind;
  $("#d-value").value = d.target.value;
  $("#d-exp").value = d.expires_at ? toLocalInput(d.expires_at) : (d.type === "suppress" ? nextSundayLocal() : "");
  if (d.type === "prioritize") $("#d-cap").value = d.cap || 1;
}

function setCompilerState(kind, note) {
  const tag = $("#compiler-tag");
  tag.textContent = kind === "llm" ? "auto" : "manual";
  tag.className = `tag ${kind === "llm" ? "ok" : ""}`;
  $("#compiler-note").textContent = note;
  $("#compiler-note").hidden = !note;
}

async function openDirective() {
  const text = $("#parent-text").value.trim();
  if (!text) { toast("Type an instruction first."); return; }
  const btn = $("#parent-form button[type=submit]");
  btn.disabled = true; btn.classList.add("busy");
  try {
    // D1's compiler (via ui/server.py): the LLM only fills typed slots; code validates them.
    const r = await call("POST", "/ui/compile", { scope_id: S.scope, text });
    fillSlots(r.directive);
    setCompilerState("llm", "");
  } catch (e) {
    // Rejected or LLM unavailable: the parent can still fill the slots by hand; the same checks apply on confirm.
    if (!$("#d-exp").value) $("#d-exp").value = nextSundayLocal();
    setCompilerState("manual", e.code === "internal" ? "Couldn't read that. Fill in below." : `Not accepted: ${e.detail}`);
  } finally {
    btn.disabled = false; btn.classList.remove("busy");
  }
  $("#directive-form").hidden = false;
  syncDirectiveForm();
  $("#directive-form button[type=submit]").focus();
}

async function confirmDirective(ev) {
  ev.preventDefault();
  const d = draftDirective();
  const problem = validate(d);
  if (problem) { toast(problem); return; }
  try {
    if (d.type === "retract") {
      // Same PIN gate (checked by the compiler), then the normal retraction path.
      await call("POST", "/ui/confirm-directive", { scope_id: S.scope, directive: d });
      S.retracted.add(d.target.value);
      $("#directive-form").hidden = true;
      await loadFeed();
      addReceipt({ title: "Memory removed by parent rule", html: `<p>${esc(plainWords(d))}</p>` });
      return;
    }
    const r = await call("POST", "/ui/confirm-directive", { scope_id: S.scope, directive: d });
    $("#directive-form").hidden = true;
    $("#parent-text").value = "";
    await loadFeed();
    const rc = S.feed.receipt;
    const mine = (list) => list.filter((x) => x.directive_id === r.directive_id);
    const blocked = mine(rc.suppressed), boosted = mine(rc.boosted);
    addReceipt({
      title: "Rule saved",
      html: `<p>${esc(plainWords(d))}</p>
        ${d.type === "suppress" ? `<p><b>Blocked ${blocked.length}</b>${blocked.length ? ": " + esc(blocked.map((x) => x.title).join(", ")) : ""}</p>` : ""}
        ${d.type === "prioritize" ? `<p><b>Boosted ${boosted.length}</b>${boosted.length ? ": " + esc(boosted.map((x) => x.title).join(", ")) : ""}</p>` : ""}`,
    });
    toast(d.type === "suppress" ? `Rule saved · ${blocked.length} hidden` : d.type === "prioritize" ? `Rule saved · ${boosted.length} boosted` : "Rule saved");
  } catch (e) {
    addReceipt({ title: "Rule rejected", html: `<p>${esc(e.code)}: ${esc(e.detail)}</p>`, err: true });
  }
}

// ---------- Receipts ----------
function clearReceipts() {
  $("#receipts").innerHTML = `<p class="hint empty">Your rules and removals will show up here.</p>`;
}

// Profile avatars for each child (scope). Synthetic demo profiles, no real photos.
const AVATARS = [["🦊", "#f08a4b"], ["🐼", "#7aa7ff"], ["🐸", "#5fcf8c"], ["🦉", "#c48af0"]];
function renderKids() {
  $("#kid-pick").innerHTML = S.cfg.scopes.map((s, i) => {
    const [emoji, color] = AVATARS[i % AVATARS.length];
    const on = s.scope_id === S.scope;
    return `<button class="avatar ${on ? "on" : ""}" role="radio" aria-checked="${on}" data-scope="${esc(s.scope_id)}"
      title="${esc(s.label)}" aria-label="${esc(s.label)}" style="--ring:${color}">${emoji}</button>`;
  }).join("");
}

function setKidName() {
  const s = S.cfg.scopes.find((x) => x.scope_id === S.scope);
  const name = (s ? s.label : S.scope).replace(/\s*\(.*\)\s*$/, "");
  $("#parent-text").placeholder = `What should ${name} watch (or not)?`;
}
function addReceipt({ title, html, err }) {
  const box = $("#receipts");
  box.querySelector(".empty")?.remove();
  const el = document.createElement("div");
  el.className = `receipt ${err ? "err" : ""}`;
  el.innerHTML = `<div class="rhead"><span>${esc(title)}</span><span class="ts">${now()}</span></div>${html}`;
  box.prepend(el);
}

// ---------- Boot ----------
async function boot() {
  clearReceipts();
  // Keep the feed and toast clear of the bottom dock, whatever its height.
  new ResizeObserver(([e]) => document.documentElement.style.setProperty("--dock-h", `${Math.ceil(e.contentRect.height) + 24}px`))
    .observe($(".dock"));
  S.cfg = await call("GET", "/ui/config");
  S.scope = S.cfg.scopes[0].scope_id;
  renderKids();
  setKidName();
  await loadFeed();

  $("#kid-pick").addEventListener("click", async (e) => {
    const b = e.target.closest(".avatar");
    if (!b || b.dataset.scope === S.scope) return;
    S.scope = b.dataset.scope;
    renderKids();
    setKidName();
    S.retracted.clear();
    clearReceipts();
    await loadFeed();
  });
  $("#cards").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const vid = btn.closest(".vcard").dataset.id;
    if (btn.dataset.act === "menu") {
      const m = btn.nextElementSibling;
      const open = m.hidden;
      closeMenus();
      m.hidden = !open;
      return;
    }
    closeMenus();
    if (btn.dataset.act === "watch") watch(vid, entry(vid).title);
    if (btn.dataset.act === "why") why(vid);
    if (btn.dataset.act === "unrec") unrecommend(vid);
  });
  $("#why-body").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-retract]");
    if (b && confirm(`Remove the memory “${memText(b.dataset.retract)}”?`)) retract(b.dataset.retract, `parent_unrecommend:${b.dataset.vid}`);
  });
  // Start over (demo reset): Shift+R, only when not typing in a field.
  const startOver = async () => {
    clearReceipts();
    $("#directive-form").hidden = true;
    await loadFeed({ reset: true });
    toast("Started over.");
  };
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest("input, textarea, select, [contenteditable]");
    if (!typing && e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "r") {
      e.preventDefault();
      startOver();
    }
  });
  $("#btn-probe").addEventListener("click", probe);
  $("#examples").addEventListener("click", (e) => {
    const b = e.target.closest(".pill");
    if (!b) return;
    $("#parent-text").value = b.textContent;
    openDirective();
  });
  $("#parent-form").addEventListener("submit", (e) => { e.preventDefault(); openDirective(); });
  $("#directive-form").addEventListener("submit", confirmDirective);
  $("#directive-form").addEventListener("input", syncDirectiveForm);
  $("#directive-form").addEventListener("change", syncDirectiveForm);
  $("#btn-cancel").addEventListener("click", () => { $("#directive-form").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#directive-form").hidden = true; closeMenus(); } });
  document.addEventListener("click", (e) => { if (!e.target.closest(".vmore")) closeMenus(); });
}

boot().catch((e) => toast(`UI failed to start: ${e.message}`));
