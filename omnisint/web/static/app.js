/* Omnisint UI. Plain DOM, no framework, no external requests.
   Everything rendered here is untrusted third-party data, so it is inserted
   as text nodes — never as HTML. */
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "X-Omnisint-Token": TOKEN, "Content-Type": "application/json",
               ...(opts.headers || {}) },
  });
  const body = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

const state = {
  runId: null, profile: null, tab: "accounts",
  rows: [], selected: null, sort: { key: "confidence", dir: -1 }, poll: null,
  // Accounts the operator stacked into one identity, keyed by URL||platform.
  pins: new Map(), leads: null, leadsAttribution: "",
};

const pinKey = (a) => (a.url || a.platform || "").toLowerCase();
const isPinned = (a) => state.pins.has(pinKey(a));

/* A pin carries the anchors a rescan can actually use: the handle to search,
   the name to match personas against, and context terms to cross-check. */
function pinFrom(a) {
  const m = a.metadata || {};
  const terms = [];
  for (const k of ["company", "employer", "organization", "school",
                   "university", "location", "clan", "job_title"]) {
    const v = m[k];
    if (v && String(v).trim() && terms.length < 6) terms.push(String(v).trim());
  }
  return {
    platform: a.platform, url: a.url || "",
    username: m.username || m.login || m.handle || m.screen_name || "",
    fullname: m.fullname || "",
    terms,
  };
}

function togglePin(a) {
  const k = pinKey(a);
  if (state.pins.has(k)) state.pins.delete(k);
  else state.pins.set(k, pinFrom(a));
  renderPins();
  render();
}

function renderPins() {
  const host = $("pins"); clear(host);
  const n = state.pins.size;
  $("pinCount").textContent = n ? `(${n})` : "";
  $("rescan").disabled = n === 0;
  $("clearPins").disabled = n === 0;
  if (!n) {
    host.appendChild(el("li", "hint",
      "Press + on an account to stack it into one identity."));
    return;
  }
  for (const [k, pin] of state.pins) {
    const li = el("li");
    const x = el("span", "badge", "✕");
    x.title = "remove";
    x.onclick = () => { state.pins.delete(k); renderPins(); render(); };
    li.appendChild(x);
    li.appendChild(document.createTextNode(" " + pin.platform));
    const extra = [pin.fullname, pin.username].filter(Boolean).join(" · ");
    if (extra) li.appendChild(el("span", "type", extra));
    host.appendChild(li);
  }
}

/* -- helpers ------------------------------------------------------------ */
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;   // text, never innerHTML
  return n;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function attrClass(a) {
  if (isPinned(a) || a.pinned)
    notes.unshift({ text: "★ Confirmed by you as your subject — your judgement, "
                        + "not a tool's conclusion.", tone: "good" });
  if (a.corroborated_by && a.corroborated_by.length) return "subject";
  if (a.attribution_level === "likely different person") return "other";
  return a.level;
}
function status(msg) { $("status").textContent = msg; }

function dialog(title, build) {
  $("dlgTitle").textContent = title;
  const body = $("dlgBody"); clear(body); build(body);
  $("modal").classList.add("show");
}
const closeDialog = () => $("modal").classList.remove("show");
$("dlgOk").onclick = closeDialog;
$("dlgX").onclick = closeDialog;
$("modal").onclick = (e) => { if (e.target === $("modal")) closeDialog(); };
addEventListener("keydown", (e) => { if (e.key === "Escape") closeDialog(); });

/* -- tabs --------------------------------------------------------------- */
const TABS = [
  { key: "accounts",  label: "Accounts" },
  { key: "identity",  label: "Identity" },
  { key: "personas",  label: "Identities" },
  { key: "found",     label: "Discovered" },
  { key: "leads",     label: "Look by hand" },
  { key: "infra",     label: "Infrastructure" },
  { key: "breaches",  label: "Breaches" },
  { key: "tools",     label: "Tools" },
  { key: "caveats",   label: "Caveats" },
];

function counts(key) {
  const p = state.profile;
  if (!p) return "";
  switch (key) {
    case "accounts": return p.accounts.length;
    case "identity": return Object.keys(p.identity.names || {}).length;
    case "personas": return (p.personas || []).length;
    case "found":    return (p.identifiers || []).filter(i => i.origin !== "input").length;
    case "leads":    return (state.leads || []).reduce((n, b) => n + b.items.length, 0);
    case "infra":    return Object.keys(p.infrastructure || {}).length
                          + Object.keys(p.phones || {}).length;
    case "breaches": return (p.breaches || []).length;
    case "tools":    return (p.runs || []).length;
    case "caveats":  return (p.warnings || []).length;
  }
  return "";
}

function renderTabs() {
  const bar = $("tabs"); clear(bar);
  for (const t of TABS) {
    const node = el("div", "tab" + (state.tab === t.key ? " on" : ""));
    node.appendChild(document.createTextNode(t.label));
    const c = counts(t.key);
    if (c !== "" && c !== 0) node.appendChild(el("span", "count", ` (${c})`));
    node.onclick = () => {
      state.tab = t.key; state.selected = null;
      if (t.key === "leads" && !state.leads) loadLeads();
      render();
    };
    bar.appendChild(node);
  }
}

/* -- grid --------------------------------------------------------------- */
function grid(columns, rows, onSelect, rowClass) {
  const host = $("grid"); clear(host);
  if (!rows.length) { host.appendChild(el("div", "empty", "Nothing here.")); return; }

  const table = el("table", "grid");
  const head = el("tr");
  for (const col of columns) {
    const th = el("th");
    th.appendChild(document.createTextNode(col.label));
    if (col.sortable !== false) {
      if (state.sort.key === col.key)
        th.appendChild(el("span", "arrow", state.sort.dir < 0 ? " ▼" : " ▲"));
      th.onclick = () => {
        const s = state.sort;
        s.dir = s.key === col.key ? -s.dir : -1;
        s.key = col.key;
        render();
      };
    }
    if (col.width) th.style.width = col.width;
    head.appendChild(th);
  }
  table.appendChild(head);

  const sorted = rows.slice().sort((a, b) => {
    const k = state.sort.key;
    if (!(k in a) && !(k in b)) return 0;
    const x = a[k], y = b[k];
    const c = (typeof x === "number" && typeof y === "number")
      ? x - y : String(x ?? "").localeCompare(String(y ?? ""));
    return c * state.sort.dir;
  });

  sorted.forEach((row, i) => {
    const tr = el("tr", rowClass ? rowClass(row) : "");
    for (const col of columns) {
      const td = el("td", col.cls || "");
      const v = col.render ? col.render(row) : row[col.key];
      if (v instanceof Node) td.appendChild(v);
      else td.appendChild(document.createTextNode(v === undefined || v === null ? "" : String(v)));
      if (col.title) td.title = col.title(row);
      tr.appendChild(td);
    }
    tr.onclick = () => {
      table.querySelectorAll("tr.sel").forEach(n => n.classList.remove("sel"));
      tr.classList.add("sel");
      state.selected = row;
      if (onSelect) onSelect(row);
    };
    if (state.selected && row === state.selected) tr.classList.add("sel");
    table.appendChild(tr);
    if (i === 0 && !state.selected && onSelect) { state.selected = row; onSelect(row); tr.classList.add("sel"); }
  });
  host.appendChild(table);
}

function link(url) {
  if (!url) return document.createTextNode("—");
  const a = el("a", null, url);
  a.href = url; a.target = "_blank"; a.rel = "noreferrer noopener";
  return a;
}

/* -- detail tree -------------------------------------------------------- */
function detail(title, pairs, notes) {
  $("detailCaption").textContent = title;
  const host = $("detail"); clear(host);
  (notes || []).forEach(n => {
    const d = el("div", "node " + (n.tone || ""), n.text);
    host.appendChild(d);
  });
  if (pairs && pairs.length) {
    host.appendChild(el("div", "node grp", "▼ Fields returned"));
    for (const [k, v] of pairs) {
      const row = el("div", "node");
      row.appendChild(el("span", "k", `   ${k}: `));
      row.appendChild(el("span", "v", String(v)));
      host.appendChild(row);
    }
  }
  if (!host.childNodes.length)
    host.appendChild(el("span", "hint", "Nothing extracted for this row."));
}

function showAccount(a) {
  const notes = [
    { text: `${a.platform} — exists ${pct(a.confidence)} (${a.level}), `
          + `same person ${pct(a.attribution)} (${a.attribution_level})` },
    { text: `   sources: ${(a.sources || []).join(", ")}` , tone: "" },
  ];
  if (a.persona) notes.push({ text: `   identity: ${a.persona} — ${a.persona_note || ""}`,
                              tone: a.attribution_level === "likely different person" ? "warn" : "" });
  if (isPinned(a) || a.pinned)
    notes.unshift({ text: "★ Confirmed by you as your subject — your judgement, "
                        + "not a tool's conclusion.", tone: "good" });
  if (a.corroborated_by && a.corroborated_by.length)
    notes.push({ text: `   ± corroborated by: ${a.corroborated_by.join(", ")}`, tone: "good" });
  if (a.url) notes.push({ text: `   ${a.url}` });
  detail(`Detail — ${a.platform}`, Object.entries(a.metadata || {}), notes);
}

/* -- views -------------------------------------------------------------- */
function viewAccounts() {
  grid([
    { key: "pin", label: "+", width: "26px", sortable: false, cls: "pincell",
      render: r => {
        const b = el("button", "pinbtn" + (isPinned(r) ? " on" : ""),
                     isPinned(r) ? "✓" : "+");
        b.title = isPinned(r)
          ? "Confirmed as your subject — click to unstack"
          : "Stack this account into one identity";
        b.onclick = (e) => { e.stopPropagation(); togglePin(r); };
        return b;
      } },
    { key: "confidence", label: "Exists", width: "62px", cls: "num",
      render: r => pct(r.confidence) },
    { key: "attribution", label: "Same?", width: "78px", cls: "num",
      render: r => (r.attribution_level === "same person" ? "✔ "
                  : r.attribution_level === "likely different person" ? "✖ " : "? ")
                  + pct(r.attribution) },
    { key: "platform", label: "Platform", width: "150px" },
    { key: "url", label: "URL", render: r => link(r.url), sortable: false },
    { key: "sources_s", label: "Sources", width: "132px" },
    { key: "extract", label: "Extracted", sortable: false },
  ], state.profile.accounts.map(a => ({
      ...a,
      sources_s: (a.sources || []).join(","),
      extract: (a.corroborated_by || []).length
        ? "± " + a.corroborated_by.join(", ")
        : Object.entries(a.metadata || {}).filter(([k]) => k !== "avatar")
            .slice(0, 2).map(([k, v]) => `${k}=${v}`).join(", "),
    })), showAccount, r => (isPinned(r) ? "pinned" : attrClass(r)));
}

function summaryBlock() {
  const sm = state.profile.summary;
  if (!sm) return null;
  const box = el("div", "summary");
  box.appendChild(el("div", "sumhead", sm.headline));

  const meta = el("div", "summeta");
  const add = (label, values) => {
    if (!values || !values.length) return;
    const d = el("div");
    d.appendChild(el("b", null, label + ": "));
    d.appendChild(document.createTextNode(values.join(" · ")));
    meta.appendChild(d);
  };
  add("Roles", sm.roles); add("Employers", sm.employers);
  add("Schools", sm.schools); add("Locations", sm.locations);
  add("Sites", sm.websites);
  if (sm.bio_terms && sm.bio_terms.length)
    add("Bio mentions", sm.bio_terms.slice(0, 10).map(t => t.n > 1 ? `${t.term} ×${t.n}` : t.term));
  if (meta.childNodes.length) box.appendChild(meta);

  if (sm.topics && sm.topics.length) {
    const bars = el("div", "topics");
    const max = sm.topics[0].count || 1;
    sm.topics.forEach(t => {
      const row = el("div", "topicrow");
      row.appendChild(el("span", "tname", t.topic));
      const track = el("span", "tbar");
      const fill = el("span", "tfill");
      fill.style.width = `${Math.max(6, (t.count / max) * 100)}%`;
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("span", "tnum", String(t.count)));
      row.title = t.platforms.join(", ");
      bars.appendChild(row);
    });
    box.appendChild(bars);
  }
  box.appendChild(el("div", "sumbasis", `Based on ${sm.account_count} ${sm.scope}.`));
  box.appendChild(el("div", "hint", sm.caveat));
  return box;
}

function viewIdentity() {
  const p = state.profile, rows = [];
  const push = (kind, map) => Object.entries(map || {}).forEach(([value, seen]) =>
    rows.push({ kind, value, seen: seen.join(", "), n: seen.length }));
  push("Name", p.identity.names); push("Location", p.identity.locations);
  push("Bio", p.identity.bios); push("Avatar", p.identity.avatars);
  const block = summaryBlock();
  grid([
    { key: "kind", label: "Attribute", width: "80px" },
    { key: "n", label: "Seen", width: "50px", cls: "num" },
    { key: "value", label: "Value" },
    { key: "seen", label: "Platforms" },
  ], rows, r => detail(`Detail — ${r.kind}`, [["value", r.value], ["platforms", r.seen]],
      [{ text: r.n > 1 ? `✔ corroborated on ${r.n} platforms` : "seen on one platform only",
         tone: r.n > 1 ? "good" : "warn" }]));
  if (block) $("grid").insertBefore(block, $("grid").firstChild);
}

function viewPersonas() {
  const rows = (state.profile.personas || []).map(p => ({
    ...p, role: p.primary ? "PRIMARY — your subject"
        : (state.profile.personas.some(x => x.primary) ? "likely someone else" : "unresolved"),
    where: p.platforms.join(", "), n: p.platforms.length,
    shown: p.name + ((p.variants || []).length ? `  (also: ${p.variants.join(", ")})` : "") }));
  grid([
    { key: "shown", label: "Identity", width: "230px" },
    { key: "role", label: "Assessment", width: "170px" },
    { key: "n", label: "#", width: "36px", cls: "num" },
    { key: "where", label: "Platforms" },
  ], rows, r => detail(`Detail — ${r.name}`,
      (r.variants || []).map(v => ["also seen as", v]),
      [{ text: r.note, tone: r.primary ? "good" : "warn" }]),
    r => (r.primary ? "subject" : (r.role === "unresolved" ? "possible" : "other")));
}

function viewFound() {
  const rows = (state.profile.identifiers || []).filter(i => i.origin !== "input");
  grid([
    { key: "value", label: "Identifier", width: "260px" },
    { key: "type", label: "Type", width: "80px" },
    { key: "origin", label: "Discovered via" },
  ], rows, r => detail(`Detail — ${r.value}`, [], [
      { text: `${r.type} found by ${r.origin}` },
      { text: "Use the Scan box to search this identifier in its own right.",
        tone: "" }]),
    r => (r.type === "email" ? "confirmed" : "possible"));
  const host = $("grid");
  if (rows.length) {
    const bar = el("div", "footbar");
    const b = el("button", null, "Add all to targets");
    b.onclick = () => {
      $("targets").value = rows.map(r => r.value).join(", ");
      status(`${rows.length} identifier(s) queued — press Scan to search them.`);
    };
    bar.appendChild(b);
    host.appendChild(bar);
  }
}

function viewLeads() {
  const host = $("grid"); clear(host);
  const note = el("div", "summary");
  note.appendChild(el("div", "sumhead", "Where to look by hand"));
  note.appendChild(el("div", null,
    "Omnisint never queries these — it points you at them. Resources marked "
    + "“touches the subject” reach their own infrastructure when you use them, "
    + "which is not passive."));
  if (state.leadsAttribution)
    note.appendChild(el("div", "sumbasis", "Catalogue: " + state.leadsAttribution));
  host.appendChild(note);

  const rows = [];
  (state.leads || []).forEach(b => b.items.forEach(e =>
    rows.push({ ...e, bucket: b.bucket, warn: (e.flags || []).join(", ") })));
  if (!rows.length) {
    host.appendChild(el("div", "empty",
      "No catalogued resource takes these identifier types."));
    return;
  }
  const table = el("table", "grid");
  const head = el("tr");
  ["For", "Resource", "URL", "Notes", "Good for"].forEach(h => head.appendChild(el("th", null, h)));
  table.appendChild(head);
  rows.forEach(r => {
    const tr = el("tr", (r.flags || []).includes("touches the subject") ? "other" : "possible");
    tr.appendChild(el("td", null, r.bucket));
    tr.appendChild(el("td", null, r.name));
    const td = el("td"); td.appendChild(link(r.url)); tr.appendChild(td);
    tr.appendChild(el("td", null, r.warn || "free · passive"));
    tr.appendChild(el("td", null, r.best_for || r.desc || ""));
    tr.onclick = () => detail(`Lead — ${r.name}`,
      [["url", r.url], ["category", r.category], ["pricing", r.pricing],
       ["opsec", r.opsec]].concat(r.opsec_note ? [["opsec note", r.opsec_note]] : []),
      [{ text: r.desc || "", tone: "" },
       ...((r.flags || []).includes("touches the subject")
          ? [{ text: "Using this reaches the subject's infrastructure.", tone: "warn" }] : [])]);
    table.appendChild(tr);
  });
  host.appendChild(table);
}

function viewInfra() {
  const p = state.profile, rows = [];
  Object.entries(p.infrastructure || {}).forEach(([domain, info]) =>
    rows.push({ what: "domain", key: domain,
      summary: ["a", "mx", "ns", "spf"].filter(k => info[k])
        .map(k => `${k.toUpperCase()}: ${info[k].slice(0, 3).join(", ")}`).join("  |  "),
      info }));
  Object.entries(p.phones || {}).forEach(([num, info]) =>
    rows.push({ what: "phone", key: num,
      summary: `${info.region} · ${info.location} · ${info.line_type}`
             + (info.valid ? "" : " · NOT VALID"), info }));
  grid([
    { key: "what", label: "Kind", width: "70px" },
    { key: "key", label: "Identifier", width: "200px" },
    { key: "summary", label: "Records" },
  ], rows, r => detail(`Detail — ${r.key}`, Object.entries(r.info)
      .map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v])));
}

function viewBreaches() {
  grid([
    { key: "source", label: "Source", width: "170px" },
    { key: "identifier", label: "Identifier", width: "220px" },
    { key: "name", label: "Detail" },
  ], (state.profile.breaches || []).map(b => ({ ...b, name: b.name || String(b.detail || "") })),
    r => detail(`Detail — ${r.source}`, Object.entries(r),
      [{ text: r.meaning || "", tone: "warn" }]), () => "other");
}

function viewTools() {
  grid([
    { key: "adapter", label: "Tool", width: "120px" },
    { key: "identifier", label: "Identifier", width: "200px" },
    { key: "ok", label: "Status", width: "130px",
      render: r => (r.ok ? "ok" : (r.error || "failed")) },
    { key: "found", label: "Hits", width: "56px", cls: "num" },
    { key: "inconclusive", label: "No verdict", width: "84px", cls: "num" },
    { key: "duration", label: "Time", width: "64px", cls: "num",
      render: r => `${r.duration.toFixed(1)}s` },
  ], state.profile.runs || [],
    r => detail(`Detail — ${r.adapter}`, Object.entries(r),
      r.ok ? [] : [{ text: "This tool contributed nothing. Absence here is not "
                          + "evidence of absence.", tone: "warn" }]),
    r => (r.ok ? (r.found ? "confirmed" : "weak") : "other"));
}

function viewCaveats() {
  const rows = (state.profile.warnings || []).map((w, i) => ({ i: i + 1, text: w }));
  grid([{ key: "i", label: "#", width: "36px", cls: "num" },
        { key: "text", label: "Caveat", sortable: false }],
    rows, r => detail("Detail — caveat", [], [{ text: r.text, tone: "warn" }]),
    () => "probable");
  const gaps = state.profile.coverage_gaps || {};
  if (Object.keys(gaps).length) {
    const host = $("grid"), t = el("table", "grid");
    const h = el("tr");
    ["Tool", "Why no verdict", "Sites"].forEach(x => h.appendChild(el("th", null, x)));
    t.appendChild(h);
    for (const [tool, reasons] of Object.entries(gaps))
      for (const [reason, n] of Object.entries(reasons)) {
        const tr = el("tr", "weak");
        tr.appendChild(el("td", null, tool));
        tr.appendChild(el("td", null, reason));
        tr.appendChild(el("td", "num", String(n)));
        t.appendChild(tr);
      }
    host.appendChild(el("div", "caption", "Coverage gaps — unchecked, not clear"));
    host.appendChild(t);
  }
}

const VIEWS = { accounts: viewAccounts, identity: viewIdentity, personas: viewPersonas,
                found: viewFound, leads: viewLeads, infra: viewInfra,
                breaches: viewBreaches, tools: viewTools, caveats: viewCaveats };

/* -- render ------------------------------------------------------------- */
function render() {
  renderTabs();
  // Manual leads do not need a scan — looking things up by hand is often
  // what you do *instead* of scanning, so this view must work from an empty
  // session rather than waiting for results that may never come.
  if (state.tab === "leads") { viewLeads(); return; }
  if (!state.profile) return;
  const p = state.profile;

  const seeds = $("seeds"); clear(seeds);
  p.seeds.forEach(s => {
    const li = el("li");
    li.appendChild(document.createTextNode(s.value));
    li.appendChild(el("span", "type", s.type));
    seeds.appendChild(li);
  });
  (p.secondary_terms || []).forEach(t => {
    const li = el("li");
    li.appendChild(el("span", "badge", "±"));
    li.appendChild(document.createTextNode(" " + t));
    li.appendChild(el("span", "type", "cross-check"));
    seeds.appendChild(li);
  });

  const per = $("personas"); clear(per);
  if (!(p.personas || []).length) per.appendChild(el("li", "hint", "No names extracted."));
  p.personas.forEach(x => {
    const li = el("li");
    li.appendChild(el("span", "badge", x.primary ? "★" : "?"));
    li.appendChild(document.createTextNode(" " + x.name));
    li.appendChild(el("span", "type",
      `${x.platforms.length}` + ((x.variants || []).length ? ` +${x.variants.length}` : "")));
    if ((x.variants || []).length) li.title = "also seen as " + x.variants.join(", ");
    per.appendChild(li);
  });

  const same = p.accounts.filter(a => a.attribution_level === "same person").length;
  const diff = p.accounts.filter(a => a.attribution_level === "likely different person").length;
  $("counts").textContent = `${p.accounts.length} accounts · ${same} subject · ${diff} other`;
  $("wtitle").textContent = "Omnisint — " + p.seeds.map(s => s.value).join(", ");
  (VIEWS[state.tab] || viewAccounts)();
}

/* -- run lifecycle ------------------------------------------------------ */
function logLine(ev) {
  const host = $("log");
  const cls = ev.kind === "done" ? "ok" : ev.kind === "fail" ? "fail"
            : ev.kind === "warn" ? "warn" : "start";
  const mark = ev.kind === "done" ? "✔" : ev.kind === "fail" ? "✖"
            : ev.kind === "warn" ? "!" : "·";
  host.appendChild(el("div", cls, `${mark} ${ev.message}`));
  host.scrollTop = host.scrollHeight;
}

async function poll() {
  if (!state.runId) return;
  let run;
  try { run = await api(`/api/run/${state.runId}`); }
  catch (e) { status(`Lost the run: ${e.message}`); clearInterval(state.poll); return; }

  const host = $("log");
  const shown = host.childElementCount;
  run.events.slice(shown).forEach(logLine);

  const total = run.events.filter(e => e.kind === "start").length || 1;
  const done = run.events.filter(e => e.kind === "done" || e.kind === "fail").length;
  $("bar").style.width = `${Math.min(100, (done / total) * 100)}%`;

  if (run.state === "running") {
    status(`Scanning… ${done}/${total} tasks · ${run.elapsed.toFixed(0)}s`);
    return;
  }
  clearInterval(state.poll); state.poll = null;
  $("go").disabled = false; $("stopHint").disabled = true;
  $("bar").style.width = "100%";

  if (run.state === "failed") {
    status(`Scan failed: ${run.error}`);
    dialog("Scan failed", b => b.appendChild(el("div", null, run.error || "unknown error")));
    return;
  }
  state.profile = run.profile;
  state.selected = null;
  $("export").disabled = false;
  status(`Done in ${run.elapsed.toFixed(1)}s.`);
  render();

  const fresh = (run.profile.identifiers || []).filter(i => i.origin !== "input");
  if (fresh.length) {
    status(`Done in ${run.elapsed.toFixed(1)}s — ${fresh.length} new identifier(s) found.`);
    dialog("New identifiers found", b => {
      b.appendChild(el("div", null,
        `This scan turned up ${fresh.length} identifier(s) that were not searched:`));
      const ul = el("ul", "dlglist list");
      fresh.slice(0, 12).forEach(i => {
        const li = el("li");
        li.appendChild(el("span", "badge", i.type === "email" ? "@" : "u"));
        li.appendChild(document.createTextNode(" " + i.value));
        li.appendChild(el("span", "type", i.origin));
        ul.appendChild(li);
      });
      b.appendChild(ul);
      const add = el("button", null, "Queue all for the next scan");
      add.onclick = () => {
        $("targets").value = fresh.map(i => i.value).join(", ");
        closeDialog();
        status("Queued — press Scan to search them.");
      };
      b.appendChild(add);
      b.appendChild(el("div", "hint",
        " A hit on one of these proves the handle exists, not that it is your subject."));
    });
  }
}

function showAdvice(a) {
  const host = $("advice"); clear(host);
  if (!a || (!a.problems.length && !a.suggestions.length)) {
    host.className = "advice hidden"; return;
  }
  host.className = "advice" + (a.noisy ? " bad" : "");
  a.problems.forEach(p => {
    const d = el("div", "aprob");
    d.appendChild(el("span", "amark", p.level === "high" ? "!" : "·"));
    d.appendChild(document.createTextNode(" " + p.text));
    if (p.fix) d.appendChild(el("div", "afix", p.fix));
    host.appendChild(d);
  });
  a.suggestions.forEach(t => host.appendChild(el("div", "atip", "› " + t)));

  const rewrite = (a.problems.find(p => p.rewrite) || {}).rewrite;
  if (a.noisy) {
    const row = el("div", "arow");
    row.appendChild(el("span", "ahint",
      `Rough guess: ${a.expected_hits.toLocaleString()}+ accounts, most of them other people.`));
    if (rewrite) {
      const fix = el("button", null, "Fix it");
      fix.title = rewrite;
      fix.onclick = () => {
        $("targets").value = rewrite;
        showAdvice(null);          // clear now; re-check confirms it
        checkAdvice();
        $("targets").focus();
      };
      row.appendChild(fix);
    }
    const anyway = el("button", null, "Scan anyway");
    anyway.onclick = () => startScan(false, true);
    row.appendChild(anyway);
    const hide = el("button", null, "Dismiss");
    hide.onclick = () => { host.className = "advice hidden"; };
    row.appendChild(hide);
    host.appendChild(row);
  }
}

let adviceTimer = null;
let adviceSeq = 0;
async function checkAdvice() {
  clearTimeout(adviceTimer);
  adviceTimer = setTimeout(async () => {
    const raw = $("targets").value.trim();
    if (!raw) { showAdvice(null); return; }
    // Requests can overtake each other while typing. Stamp each one and
    // drop any reply that is no longer the latest, or a slow response to an
    // old keystroke will paint stale warnings over correct ones.
    const seq = ++adviceSeq;
    try {
      const advice = await api("/api/advise", { method: "POST",
        body: JSON.stringify({ targets: raw }) });
      if (seq === adviceSeq) showAdvice(advice);
    } catch {
      if (seq === adviceSeq) showAdvice(null);
    }
  }, 350);
}

async function loadLeads() {
  const raw = $("targets").value.trim()
    || (state.profile ? state.profile.seeds.map(s => s.value).join(", ") : "");
  if (!raw) { state.leads = []; return; }
  try {
    const r = await api("/api/leads", { method: "POST",
      body: JSON.stringify({ targets: raw, limit: 12 }) });
    state.leads = r.buckets; state.leadsAttribution = r.attribution;
  } catch { state.leads = []; }
  render();
}

async function startScan(withPins, force) {
  const raw = $("targets").value.trim();
  const pins = withPins ? [...state.pins.values()] : [];
  if (!raw && !pins.length) { status("Type something to scan first."); return; }

  // Say what is about to go wrong before spending a minute proving it.
  if (!force && raw) {
    try {
      const a = await api("/api/advise", { method: "POST",
        body: JSON.stringify({ targets: raw }) });
      if (a.noisy) { showAdvice(a); status("Check the warnings above, then Scan anyway."); return; }
    } catch { /* advice is a courtesy; never block a scan on it */ }
  }
  showAdvice(null);
  $("go").disabled = true; $("stopHint").disabled = false;
  $("export").disabled = true;
  clear($("log")); $("bar").style.width = "0";
  state.profile = null; state.selected = null; state.leads = null;
  clear($("grid")); $("grid").appendChild(el("div", "empty", "Scanning…"));
  status(pins.length
    ? `Starting — rescanning around ${pins.length} confirmed account(s)…`
    : "Starting…");
  try {
    const { id } = await api("/api/scan", { method: "POST", body: JSON.stringify({
      targets: raw,
      pinned: pins,
      preset: $("preset").value,
      options: { hudson: $("hudson").checked, darkweb: $("darkweb").checked,
                 nsfw: $("nsfw").checked },
    })});
    state.runId = id;
    state.poll = setInterval(poll, 700);
    poll();
  } catch (e) {
    $("go").disabled = false; $("stopHint").disabled = true;
    status(e.message);
    dialog("Cannot start scan", b => b.appendChild(el("div", null, e.message)));
  }
}

/* -- wiring ------------------------------------------------------------- */
$("rescan").onclick = () => startScan(true);
$("clearPins").onclick = () => { state.pins.clear(); renderPins(); render(); };
$("go").onclick = () => startScan(false);
$("targets").addEventListener("keydown", e => { if (e.key === "Enter") startScan(false); });
$("targets").addEventListener("input", checkAdvice);

$("export").onclick = async () => {
  try {
    const { files } = await api(`/api/export/${state.runId}`, { method: "POST" });
    dialog("Exported", b => {
      b.appendChild(el("div", null, "Written with permissions 600:"));
      const pre = el("div", "tree");
      files.forEach(f => pre.appendChild(el("div", "node", f)));
      b.appendChild(pre);
      b.appendChild(el("div", "hint",
        "A report is personal data. Keep it minimal and delete it when done."));
    });
  } catch (e) { dialog("Export failed", b => b.appendChild(el("div", null, e.message))); }
};

$("toolsBtn").onclick = async () => {
  const { backends } = await api("/api/tools");
  dialog("Backends", b => {
    const t = el("table", "grid");
    const h = el("tr");
    ["Backend", "Status", "Accepts", "Install"].forEach(x => h.appendChild(el("th", null, x)));
    t.appendChild(h);
    backends.forEach(r => {
      const tr = el("tr", r.available ? "confirmed" : "weak");
      tr.appendChild(el("td", null, r.name + (r.opt_in ? " (opt-in)" : "")));
      tr.appendChild(el("td", null, r.available ? "ready" : "missing"));
      tr.appendChild(el("td", null, (r.accepts || []).join(", ")));
      tr.appendChild(el("td", null, r.install || ""));
      t.appendChild(tr);
    });
    b.appendChild(t);
  });
};

$("helpBtn").onclick = () => dialog("About Omnisint", b => {
  [["Primary", "things that identify the person — searched: names, handles, emails, phones, domains."],
   ["Secondary", "things you know about them — never searched, only cross-checked. Put them after a semicolon: alex rivera; northwind labs"],
   ["Exists", "the handle is registered on that platform."],
   ["Same?", "evidence it belongs to your subject. A different question, scored separately — a shared username is not a shared identity."],
   ["Row colours", "green = corroborated as your subject, red = probably a different person, yellow/blue = weaker existence evidence."],
  ].forEach(([k, v]) => {
    const d = el("div", "spaced");
    d.appendChild(el("b", null, k + " — "));
    d.appendChild(document.createTextNode(v));
    b.appendChild(d);
  });
  b.appendChild(el("div", "hint",
    " Findings are unverified third-party signals. Treat anything short of "
    + "confirmed + same person as a lead, not a fact."));
});

(async function boot() {
  renderTabs();
  renderPins();
  try {
    const meta = await api("/api/meta");
    $("case").textContent = `case ${meta.case || "—"} · ${meta.operator}`;
    status(`Ready · v${meta.version} · reports → ${meta.reports_dir}`);
  } catch (e) {
    status("Cannot reach the Omnisint server. Restart it with `omni web`.");
  }
})();
