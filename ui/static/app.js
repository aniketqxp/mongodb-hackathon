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
const mins = (s) => (s ? `${Math.round(s / 60)} min` : "");

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
  $("#feed-source").textContent = `Slate from the J2 harness · memory source: ${S.feed.memory_source}` +
    (S.feed.memory_source === "seed" ? " (seed graph until the real /memory/search lands)" : "");
  renderFeed();
  return { prev, next: S.feed.slate };
}

function renderFeed() {
  const f = S.feed;
  const used = f.memories.map((m) => m.node_id);
  const all = [...used, ...[...S.retracted].filter((n) => !used.includes(n))];
  $("#memory-strip").innerHTML = all.length
    ? `<span class="hint">Built from watch memory:</span>` +
      all.map((n) => `<span class="mem ${S.retracted.has(n) ? "gone" : ""}" title="${esc(n)}">${esc(memText(n))}</span>`).join("")
    : `<span class="hint">No usable memory for this child yet.</span>`;

  const showMarks = f.had_previous && f.removed.length > 0; // only after something was replaced
  $("#cards").innerHTML = f.slate.map((e) => {
    const mark = e.status === "boosted" ? "boosted" : showMarks ? e.status : "";
    const badge = {
      boosted: `<span class="badge boost">Boosted by parent rule</span>`,
      kept: `<span class="badge kept">Kept</span>`,
      new: `<span class="badge new">New</span>`,
    }[mark] || "";
    return `
      <article class="vcard ${esc(mark)}" data-id="${esc(e.video_id)}">
        <div class="thumb t-${esc(e.topic)}" aria-hidden="true">${ICON[e.topic] || "▶️"}</div>
        <div class="vbody">
          ${badge}
          <div class="vtitle">${esc(e.title)}</div>
          <div class="vmeta">${esc(e.topic.replace("_", " & "))} · ${esc(MATURITY[e.maturity] ?? e.maturity)} · ${esc(mins(e.duration_s))}</div>
          <div class="vactions">
            <button class="small" data-act="watch">Watch</button>
            <button class="small" data-act="why">Why this?</button>
            <button class="small ghost" data-act="unrec">Un-recommend</button>
          </div>
        </div>
      </article>`;
  }).join("") || `<p class="hint">Nothing to recommend right now.</p>`;
}

const entry = (vid) => S.feed.slate.find((e) => e.video_id === vid);

// ---------- Watch / gate ----------
async function watch(vid, title) {
  try {
    const r = await call("POST", "/ui/watch", { scope_id: S.scope, video_id: vid });
    if (r.admitted) { toast(`Watch saved to memory (${r.node_id}).`); return; }
    toast(`Blocked by the gate: nothing saved.`);
    addReceipt({
      title: "Gate blocked a video",
      html: `<p><b>${esc(title || vid)}</b> was rejected (<span class="mono">${esc(r.reason)}</span>, enforced by the ${esc(r.enforced_by)}).</p>
             <p class="hint">No memory, no dependency edge and no slate entry was created.</p>`,
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
  $("#why-title").textContent = mode === "unrec" ? `Un-recommend “${e.title}”` : `Why “${e.title}”?`;
  $("#why-body").innerHTML = `<p class="hint">Loading…</p>`;
  $("#why-dialog").showModal();
  const memories = `
    <h3>${mode === "unrec" ? "Pick the memory to remove" : "Memories behind this video"}</h3>
    <div class="chain">${e.supports.map((n) => `
      <div class="link">${esc(memText(n))} <span class="mono">(${esc(n)})</span><br>
        <button class="small ${mode === "unrec" ? "primary" : "ghost"}" data-retract="${esc(n)}" data-vid="${esc(vid)}">Remove this memory</button>
      </div>`).join("") || "<p class='hint'>Boosted by a parent rule, not by memory.</p>"}</div>
    ${e.boosted_by ? `<p class="hint">Boosted by rule <span class="mono">${esc(e.boosted_by)}</span>.</p>` : ""}
    ${mode === "unrec" ? `<p class="hint">Removing a memory replaces every video that relied only on it. Videos with other support stay.</p>` : ""}`;
  if (mode === "unrec") { $("#why-body").innerHTML = memories; return; }
  try {
    const r = await call("GET", `/api/why/${encodeURIComponent(e.decision_id)}?${qs(scoped())}`);
    $("#why-body").innerHTML = `
      <p class="hint">Decision <span class="mono">${esc(r.decision?.decision_id || e.decision_id)}</span> · ${esc(r.decision?.status || "")}</p>
      ${memories}
      <h3>Provenance from the core</h3>
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
    if (confirm(`Un-recommend “${e.title}”?\n\nThis removes the memory “${memText(e.supports[0])}” and replaces every video that relied only on it.`)) {
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
      title: `Removed memory: ${memText(nodeId)}`,
      html: `
        <div class="diff">
          <div class="col"><h4>Before</h4>${prev.map((x) => `<div class="${nextIds.has(x.video_id) ? "same" : "gone"}">${esc(x.title)}</div>`).join("")}</div>
          <div class="col"><h4>After</h4>${next.map((x) => `<div class="${x.status === "new" ? "added" : "same"}">${esc(x.title)}${x.status === "kept" && x.supports.length ? " ✓" : ""}</div>`).join("")}</div>
        </div>
        <p class="hint">${removed.length} replaced (relied only on this memory) · ${kept.length} kept ✓ · ${added.length} new.</p>
        <details><summary>Core recall plan &amp; diff</summary>
          <p>Replayed decisions: <span class="mono">${esc((r.replayed || []).join(", ") || "none")}</span></p>
          <ul>${(r.plan?.actions || []).map((a) => `<li><span class="act ${esc(a.action)}">${esc(a.action)}</span><span class="mono">${esc(a.id)}</span>${a.reason ? ` <span class="hint">(${esc(a.reason)})</span>` : ""}</li>`).join("")}</ul>
          <p class="hint mono">GET /diff → changed: ${esc(JSON.stringify(r.diff?.changed || []))} · preserved: ${esc(JSON.stringify(r.diff?.preserved || []))}</p>
        </details>`,
    });
    toast(`${removed.length} replaced, ${kept.length} kept.`);
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
  const tgt = d.target.value ? `${d.target.kind.replace("_", " ")} “${d.target.value}”` : "(fill in a target)";
  const until = d.expires_at ? new Date(d.expires_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : null;
  if (d.type === "suppress") return `Hide ${tgt} from the feed${until ? ` until ${until}` : " (needs an end time)"}.`;
  if (d.type === "prioritize") return `Show more ${tgt}: up to ${d.cap || "?"} per feed${until ? `, until ${until}` : ""}.`;
  return `Remove memory ${d.target.value ? `“${memText(d.target.value)}”` : "(pick one)"} and repair what depended on it.`;
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

function openDirective() {
  if (!$("#parent-text").value.trim()) { toast("Type an instruction first."); return; }
  // CONTRACT v0.1 has no route for D1's compiler yet (OPS/BLOCKERS.md), so the parent fills the
  // typed slots. Swap this for the compiler call when it lands; the PIN step stays.
  $("#compiler-note").textContent = "The sentence compiler (D1) is not connected yet, so pick the slots yourself. Nothing is saved until you confirm with the PIN.";
  if (!$("#d-exp").value) $("#d-exp").value = nextSundayLocal();
  $("#d-pin").value = "";
  $("#directive-form").hidden = false;
  syncDirectiveForm();
  $("#d-value").focus();
}

async function confirmDirective(ev) {
  ev.preventDefault();
  const d = draftDirective();
  const problem = validate(d);
  if (problem) { toast(problem); return; }
  const pin = $("#d-pin").value;
  if (!pin) { toast("Enter the parent PIN to confirm."); return; }
  try {
    if (d.type === "retract") {
      // Same PIN gate, then the normal retraction path.
      await call("POST", "/ui/confirm-directive", { pin, scope_id: S.scope, directive: d });
      S.retracted.add(d.target.value);
      $("#directive-form").hidden = true;
      await loadFeed();
      addReceipt({ title: "Memory removed by parent rule", html: `<p>${esc(plainWords(d))}</p>` });
      return;
    }
    const r = await call("POST", "/ui/confirm-directive", { pin, scope_id: S.scope, directive: d });
    $("#directive-form").hidden = true;
    $("#parent-text").value = "";
    await loadFeed();
    const rc = S.feed.receipt;
    const mine = (list) => list.filter((x) => x.directive_id === r.directive_id);
    const blocked = mine(rc.suppressed), boosted = mine(rc.boosted);
    addReceipt({
      title: `Rule saved · ${r.status || "active"}`,
      html: `<p>${esc(plainWords(d))}</p>
        <p class="hint">“${esc(d.source_text)}” → <span class="mono">${esc(r.directive_id)}</span>, confirmed with PIN.</p>
        ${d.type === "suppress" ? `<p><b>Blocked ${blocked.length}:</b> ${esc(blocked.map((x) => x.title).join(", ") || "nothing in this feed matched")}</p>` : ""}
        ${d.type === "prioritize" ? `<p><b>Boosted ${boosted.length}:</b> ${esc(boosted.map((x) => x.title).join(", ") || "nothing allowed matched")}</p>` : ""}
        <p class="hint">Order of rules: age gate &gt; block &gt; boost.</p>`,
    });
    toast("Rule confirmed. Feed updated.");
  } catch (e) {
    if (e.status === 403) { toast("Wrong PIN. Nothing was saved."); $("#d-pin").select(); return; }
    addReceipt({ title: "Rule rejected", html: `<p>${esc(e.code)}: ${esc(e.detail)}</p>`, err: true });
  }
}

// ---------- Receipts ----------
function addReceipt({ title, html, err }) {
  const box = $("#receipts");
  if (box.querySelector(".hint:only-child")) box.innerHTML = "";
  const el = document.createElement("div");
  el.className = `receipt ${err ? "err" : ""}`;
  el.innerHTML = `<div class="rhead"><span>${esc(title)}</span><span class="ts">${now()}</span></div>${html}`;
  box.prepend(el);
}

// ---------- Boot ----------
async function pingApi() {
  const chip = $("#chip-api");
  try {
    await call("GET", `/api/ledger?${qs(scoped({ limit: 1 }))}`);
    chip.className = "chip api ok";
    chip.lastElementChild.textContent = S.cfg.api_base;
  } catch (e) {
    chip.className = "chip api down";
    chip.lastElementChild.textContent = "API down";
    chip.title = e.detail;
  }
}

async function boot() {
  S.cfg = await call("GET", "/ui/config");
  S.scope = S.cfg.scopes[0].scope_id;
  $("#scope-select").innerHTML = S.cfg.scopes.map((s) => `<option value="${esc(s.scope_id)}">${esc(s.label)}</option>`).join("");
  $("#chip-pack").textContent = `pack ${S.cfg.pack_id}`;
  $("#chip-mem").textContent = `memory ${S.cfg.memory_source}`;
  await pingApi();
  await loadFeed();

  $("#scope-select").addEventListener("change", async (e) => {
    S.scope = e.target.value;
    S.retracted.clear();
    $("#receipts").innerHTML = `<p class="hint">Confirmed rules and un-recommends show up here with what changed.</p>`;
    await loadFeed();
  });
  $("#cards").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const vid = btn.closest(".vcard").dataset.id;
    if (btn.dataset.act === "watch") watch(vid, entry(vid).title);
    if (btn.dataset.act === "why") why(vid);
    if (btn.dataset.act === "unrec") unrecommend(vid);
  });
  $("#why-body").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-retract]");
    if (b && confirm(`Remove the memory “${memText(b.dataset.retract)}”?`)) retract(b.dataset.retract, `parent_unrecommend:${b.dataset.vid}`);
  });
  $("#btn-reload").addEventListener("click", async () => {
    $("#receipts").innerHTML = `<p class="hint">Confirmed rules and un-recommends show up here with what changed.</p>`;
    await loadFeed({ reset: true });
    toast("Started over for this child.");
  });
  $("#btn-probe").addEventListener("click", probe);
  $("#parent-form").addEventListener("submit", (e) => { e.preventDefault(); openDirective(); });
  $("#directive-form").addEventListener("submit", confirmDirective);
  $("#directive-form").addEventListener("input", syncDirectiveForm);
  $("#directive-form").addEventListener("change", syncDirectiveForm);
  $("#btn-cancel").addEventListener("click", () => { $("#directive-form").hidden = true; });
}

boot().catch((e) => toast(`UI failed to start: ${e.message}`));
