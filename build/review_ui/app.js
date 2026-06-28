// Operator console client. One rule above all: candidate and registry text is
// untrusted — it only ever reaches the page through textContent, never innerHTML.
"use strict";

let STATE = null;

// ── client-persisted state (localStorage; private-mode safe) ──────────────────
const LS = {
  favorites: "oc.favorites", recents: "oc.recents", drafts: "oc.drafts",
  collapsed: "oc.collapsed", compose: "oc.compose", graphDrafts: "oc.graphDrafts",
};
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); }
    catch (e) { return fallback; }
  },
  set(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* ignore */ } },
};
let favorites = store.get(LS.favorites, []);   // prompt keys, in pin order
let recents = store.get(LS.recents, []);       // prompt keys, most-recent first
let drafts = store.get(LS.drafts, {});         // key -> in-progress edited body
let collapsed = store.get(LS.collapsed, {});   // list group id -> true when collapsed
let compose = store.get(LS.compose, { items: [], text: null }); // items: keys; text: edited merge
let selectedKey = null;                        // the prompt shown in the detail pane
let filterChip = "all";                        // active list filter chip
let PROMPTS = [];                              // flat prompt list (rebuilt each render)
let PMAP = new Map();                          // key -> prompt
let graphSlug = null;                          // selected project in the Knowledge Graph tab
let graphProjFilter = "";                       // sidebar project-search text
let stagedData = null;   // { ok, slug, documents, staged_at } from /api/graph/staged
let stagedSel = new Set(); // drive IDs checked in the staged checklist
let stagedFilter = "";     // client-side search text for the staged list
let stagedPool = "project"; // "project" | "unassigned" — which staged pool the toggle shows
let openEditor = null;     // { where:"registry"|"staged", vals:{id,name,description,dateModified,keywords}, lockId }
let selectedCandidateId = null;  // which inbox candidate is shown in the detail pane
// graphDrafts[slug] = {
//   add:{id:doc}, edit:{id:doc}, remove:{id:{id,name}},
//   effortAdd:{id:effort}, effortEdit:{id:effort}, effortRemove:{id:{id,name}}
// } — local, persisted
let graphDrafts = store.get(LS.graphDrafts, {});

const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function toast(msg, ms = 2600) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.hidden = true; }, ms);
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied ${label} (${text.length.toLocaleString()} chars)`);
  } catch (e) {
    toast("Clipboard unavailable — select and copy from the expanded text.");
  }
}

// ── data ─────────────────────────────────────────────────────────────────────
async function refresh() {
  const res = await fetch("/api/state");
  STATE = await res.json();
  const rootEl = $("root");
  if (rootEl) rootEl.textContent = STATE.root;
  const countEl = $("inbox-count");
  if (countEl) countEl.textContent = STATE.candidates.length || "";
  // render the panes independently — a fault in one must not blank the others
  safeRender($("view-inbox"), renderInbox);
  safeRender($("view-graph"), renderGraph);
  safeRender($("prompt-list"), renderPrompts);
}

function safeRender(box, fn) {
  try {
    fn();
  } catch (e) {
    console.error(e);
    box.replaceChildren(el("div", "empty-state", `Render error: ${e.message}`));
    toast(`Render error: ${e.message}`, 6000);
  }
}

async function sendDecision(id, decision, reason) {
  const res = await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, decision, reason }),
  });
  const out = await res.json();
  if (out.ok) {
    const routed = (out.changed || []).length
      ? ` → registry/${out.changed.join(", registry/")}` : "";
    toast(`${decision === "accept" ? "Accepted" : "Rejected"} ${id}${routed} — review git status, then commit.`, 4200);
    await refresh();
  } else {
    toast(`Error: ${out.error}`, 5000);
  }
}

// ── inbox ────────────────────────────────────────────────────────────────────
function renderInbox() {
  const view = $("view-inbox");
  view.replaceChildren();
  const candidates = STATE.candidates || [];
  if (!candidates.length) {
    const wrap = el("div", "empty-wrap");
    wrap.append(el("div", "empty-state", "The queue is clear — nothing awaits review."));
    view.append(wrap);
    return;
  }
  if (!selectedCandidateId || !candidates.find((c) => c.id === selectedCandidateId)) {
    selectedCandidateId = candidates[0].id;
  }
  const split = el("div"); split.id = "inbox-split";
  const list = el("aside"); list.id = "inbox-list";
  const detail = el("section"); detail.id = "inbox-detail";
  for (const c of candidates) list.append(inboxListRow(c));
  const selected = candidates.find((c) => c.id === selectedCandidateId);
  if (selected) detail.append(candidateCard(selected));
  split.append(list, detail);
  view.append(split);
}

function inboxListRow(c) {
  const row = el("div", "inbox-list-row" + (c.id === selectedCandidateId ? " active" : ""));
  const head = el("div", "inbox-row-head");
  head.append(el("span", "badge kind", c.kind || "drift"));
  if (c.stale === true) head.append(el("span", "badge stale", "moved"));
  if (!c.acceptable) head.append(el("span", "badge manual", "manual"));
  head.append(el("code", "inbox-row-path", c.registry_path || c.deploy_path || c.id));
  row.append(head);
  const src = c.source || {};
  const meta = el("div", "inbox-row-meta");
  meta.textContent = `${src.machine || "?"}/${src.tool || "?"} · ${c.captured_at || ""}`;
  row.append(meta);
  if (c.note) {
    const note = el("div", "inbox-row-note");
    note.textContent = c.note;
    row.append(note);
  }
  row.onclick = () => {
    selectedCandidateId = c.id;
    renderInbox();
  };
  return row;
}

function candidateCard(c) {
  const card = el("article", "card");

  const head = el("div", "card-head");
  head.append(el("span", "badge kind", c.kind || "drift"));
  if (c.stale === true) head.append(el("span", "badge stale", "registry moved"));
  if (!c.acceptable) head.append(el("span", "badge manual", "manual"));
  if (c.accept_note.startsWith("new file")) head.append(el("span", "badge new", "new"));
  head.append(el("code", "", c.registry_path || c.deploy_path));
  const src = c.source || {};
  head.append(el("span", "muted", `${src.machine || "?"} / ${src.tool || "?"} · ${c.captured_at}`));
  card.append(head);

  if (c.note) card.append(el("div", "card-note muted", c.note));
  if (c.accept_note && !c.accept_note.startsWith("new file")) {
    if (!c.acceptable) {
      const noteDiv = el("div", "accept-note warning-callout");
      noteDiv.append(el("div", "callout-title", "⚠️ Action Required: Manual Resolution"));

      const desc = el("div", "callout-body");
      desc.append(el("p", "", c.accept_note));

      if (c.sources && c.sources.length > 0) {
        desc.append(el("p", "", "This file is compiled from the following registry sources — edit these by hand:"));
        const list = el("ul");
        c.sources.forEach((src) => {
          const li = el("li");
          li.append(el("code", "", `registry/${src}`));
          list.append(li);
        });
        desc.append(list);
      }

      noteDiv.append(desc);
      card.append(noteDiv);
    } else {
      card.append(el("div", "accept-note", c.accept_note));
    }
  }

  card.append(diffTable(c.diff));

  const details = el("details", "payload");
  details.append(el("summary", "", "Proposed text (raw)"));
  details.append(el("pre", "", c.payload));
  card.append(details);

  const actions = el("div", "card-actions");
  const reason = el("input");
  reason.type = "text";
  reason.placeholder = "Reason (optional — logged to decisions.jsonl)";
  const accept = el("button", "accept", "Accept");
  accept.disabled = !c.acceptable;
  if (!c.acceptable) accept.title = c.accept_note;
  accept.onclick = () => sendDecision(c.id, "accept", reason.value);
  const reject = el("button", "reject", "Reject");
  reject.onclick = () => sendDecision(c.id, "reject", reason.value);
  const copy = el("button", "ghost", "Copy proposed");
  copy.onclick = () => copyText(c.payload, c.id);
  actions.append(reason, copy, accept, reject);
  card.append(actions);
  return card;
}

function diffTable(rows) {
  const box = el("div", "diff");
  const cell = (text, cls) => {
    const d = el("div", "diff-cell" + (cls ? " " + cls : ""), text === null ? "" : text);
    if (text === null) d.classList.add("empty");
    return d;
  };
  // collapse long runs of unchanged lines, keeping 3 lines of context each side
  let i = 0;
  while (i < rows.length) {
    if (rows[i].t === "eq") {
      let j = i;
      while (j < rows.length && rows[j].t === "eq") j++;
      const run = j - i;
      const emit = (r) => {
        const row = el("div", "diff-row");
        row.append(cell(r.l), cell(r.r));
        box.append(row);
        return row;
      };
      if (run > 8) {
        for (let k = i; k < i + 3; k++) emit(rows[k]);
        const hidden = [];
        for (let k = i + 3; k < j - 3; k++) hidden.push(emit(rows[k]));
        hidden.forEach((r) => r.classList.add("hidden-row"));
        const fold = el("div", "diff-row");
        const foldCell = el("div", "diff-fold", `⋯ ${run - 6} unchanged lines ⋯`);
        foldCell.onclick = () => { hidden.forEach((r) => r.classList.remove("hidden-row")); fold.remove(); };
        fold.append(foldCell);
        box.insertBefore(fold, hidden.length ? hidden[0] : null);
        for (let k = j - 3; k < j; k++) emit(rows[k]);
      } else {
        for (let k = i; k < j; k++) emit(rows[k]);
      }
      i = j;
    } else {
      const r = rows[i];
      const row = el("div", "diff-row");
      if (r.t === "chg") row.append(cell(r.l, "chg"), cell(r.r, "chg"));
      else if (r.t === "del") row.append(cell(r.l, "del"), cell(null));
      else row.append(cell(null), cell(r.r, "ins"));
      box.append(row);
      i++;
    }
  }
  if (!rows.length) box.append(el("div", "diff-fold", "(no current registry text — whole payload is new)"));
  return box;
}

// ── knowledge graph: per-project document mappings (draft → propose → inbox) ──
// A project sidebar (left) drives a two-pane workspace: Discovery (the staged/unassigned
// pool, left) and Registry (the project's mapped documents, right). Adds, edits, and
// removals accumulate in a local, per-project `graphDrafts[slug]` and are submitted as ONE
// kind:graph candidate from the persistent dock — never touching registry/ directly
// (invariant #3). Like the prompt library, the structure renders once and only the dynamic
// sub-parts re-render on a keystroke, so focus and half-typed inputs survive.

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
    + `-${String(d.getDate()).padStart(2, "0")}`;
}

// ── draft state (per project, persisted) ──────────────────────────────────────
function draftFor(slug) {
  const d = graphDrafts[slug] || (graphDrafts[slug] = {});
  d.add = d.add || {}; d.edit = d.edit || {}; d.remove = d.remove || {};
  d.effortAdd = d.effortAdd || {}; d.effortEdit = d.effortEdit || {};
  d.effortRemove = d.effortRemove || {};
  return d;
}
function saveDrafts() { store.set(LS.graphDrafts, graphDrafts); }
function draftCounts(slug) {
  const d = draftFor(slug);
  return {
    adds: Object.keys(d.add).length, edits: Object.keys(d.edit).length,
    removes: Object.keys(d.remove).length,
    effortAdds: Object.keys(d.effortAdd).length,
    effortEdits: Object.keys(d.effortEdit).length,
    effortRemoves: Object.keys(d.effortRemove).length,
  };
}
function draftTotal(slug) {
  const c = draftCounts(slug);
  return c.adds + c.edits + c.removes + c.effortAdds + c.effortEdits + c.effortRemoves;
}
// Upsert a doc into the draft. `isAdd` routes it to add (a new mapping) vs edit (an existing
// one); either way a pending removal of the same id is cancelled — you can't both keep and drop.
function draftUpsert(slug, doc, isAdd) {
  const d = draftFor(slug);
  delete d.remove[doc.id];
  delete (isAdd ? d.edit : d.add)[doc.id];   // it can only be one of the two
  (isAdd ? d.add : d.edit)[doc.id] = doc;
  saveDrafts();
}
function draftRemove(slug, doc) {
  const d = draftFor(slug);
  delete d.add[doc.id]; delete d.edit[doc.id];   // removing supersedes a pending add/edit
  d.remove[doc.id] = { id: doc.id, name: doc.name };
  saveDrafts();
}
function draftUndo(slug, id) {
  const d = draftFor(slug);
  delete d.add[id]; delete d.edit[id]; delete d.remove[id];
  saveDrafts();
}
function effortDraftUpsert(slug, effort, isAdd) {
  const d = draftFor(slug);
  delete d.effortRemove[effort.id];
  delete (isAdd ? d.effortEdit : d.effortAdd)[effort.id];
  (isAdd ? d.effortAdd : d.effortEdit)[effort.id] = effort;
  saveDrafts();
}
function effortDraftRemove(slug, effort) {
  const d = draftFor(slug);
  delete d.effortAdd[effort.id]; delete d.effortEdit[effort.id];
  d.effortRemove[effort.id] = { id: effort.id, name: effort.name };
  saveDrafts();
}
function effortDraftUndo(slug, id) {
  const d = draftFor(slug);
  delete d.effortAdd[id]; delete d.effortEdit[id]; delete d.effortRemove[id];
  saveDrafts();
}
function draftClear(slug) {
  delete graphDrafts[slug];
  saveDrafts();
}

async function loadStaged(slug) {
  try {
    const r = await fetch("/api/graph/staged?slug=" + encodeURIComponent(slug)
      + (stagedPool === "unassigned" ? "&pool=unassigned" : ""));
    stagedData = await r.json();
    stagedSel = new Set();
    renderGraph();
  } catch (e) {
    // fail silently — discovery pane shows the "run mitos connect --stage" hint
  }
}

// Document IDs already spoken for in the Inbox: a doc with an in-flight kind:graph candidate
// for this project (upsert OR removal) can't be drafted again until it's accepted/rejected.
function pendingDocIds(slug) {
  const ids = new Set();
  for (const c of (STATE && STATE.candidates) || []) {
    if (c.kind === "graph" && c.project === slug) {
      for (const id of c.doc_ids || []) ids.add(id);
      for (const id of c.removal_ids || []) ids.add(id);
    }
  }
  return ids;
}

function renderGraph() {
  const view = $("view-graph");
  view.replaceChildren();
  const graphs = (STATE && STATE.graphs) || [];
  if (!graphs.length) {
    view.append(el("div", "empty-state", "No projects in the registry."));
    updateGraphDock();
    return;
  }
  if (!graphs.some((g) => g.slug === graphSlug)) graphSlug = graphs[0].slug;
  const g = graphs.find((x) => x.slug === graphSlug);

  const split = el("div"); split.id = "graph-split";
  split.append(buildGraphSidebar(graphs), buildGraphWorkspace(g));
  view.append(split);
  updateGraphDock();
}

// ── left: searchable project sidebar (scales to 100s–1000s of projects) ───────
function buildGraphSidebar(graphs) {
  const aside = el("aside"); aside.id = "graph-sidebar";
  const search = el("input", "graph-proj-search");
  search.type = "search"; search.placeholder = "Filter projects…"; search.value = graphProjFilter;
  // Only the rows re-render on a keystroke — this input survives, so focus is never lost.
  search.oninput = () => { graphProjFilter = search.value; renderProjRows(); };
  aside.append(search, el("div", "graph-proj-list"));
  // rows are drawn after the sidebar is in the DOM (renderGraph appends it)
  setTimeout(renderProjRows, 0);
  return aside;
}

function renderProjRows() {
  const list = document.querySelector("#graph-sidebar .graph-proj-list");
  if (!list) return;
  const graphs = (STATE && STATE.graphs) || [];
  const q = graphProjFilter.trim().toLowerCase();
  const matches = q
    ? graphs.filter((g) => (g.name + " " + g.slug).toLowerCase().includes(q))
    : graphs;
  list.replaceChildren();
  if (!matches.length) { list.append(el("div", "muted graph-proj-empty", "No projects match.")); return; }
  for (const g of matches) {
    const row = el("div", "graph-proj-row" + (g.slug === graphSlug ? " active" : ""));
    const dot = el("span", "graph-proj-dot " + (g.has_graph ? "mapped" : "empty"));
    dot.title = g.has_graph ? "Has document mappings" : "No graph yet";
    const col = el("div", "graph-proj-col");
    col.append(el("div", "graph-proj-name", g.name));
    const sub = el("div", "graph-proj-sub muted");
    sub.append(el("span", "", `${g.documents.length} doc${g.documents.length === 1 ? "" : "s"}`));
    const dt = draftTotal(g.slug);
    if (dt) sub.append(el("span", "badge draft", `${dt} draft`));
    col.append(sub);
    row.append(dot, col);
    row.onclick = () => selectProject(g.slug);
    list.append(row);
  }
}

function selectProject(slug) {
  if (slug === graphSlug) return;
  graphSlug = slug;
  stagedData = null; stagedSel = new Set(); stagedFilter = ""; stagedPool = "project";
  openEditor = null;
  renderGraph();
  loadStaged(slug);
}

// ── right: workspace = Discovery pane | Registry pane ─────────────────────────
function buildGraphWorkspace(g) {
  const ws = el("section"); ws.id = "graph-workspace";
  const head = el("div", "graph-ws-head");
  head.append(el("strong", "graph-ws-title", g.name));
  head.append(el("code", "graph-ws-slug", g.slug));
  head.append(el("span", "muted", `${g.documents.length} mapped`));
  ws.append(head);
  ws.append(el("p", "graph-help muted",
    "Map, edit, and remove documents below — changes collect in the dock and submit as one "
    + "kind:graph candidate to Accept in the Inbox. Nothing writes the registry directly."));

  const panes = el("div", "graph-panes");
  const discovery = el("div", "graph-pane");
  const registry = el("div", "graph-pane");
  panes.append(discovery, registry);
  ws.append(panes);
  buildDiscoveryPane(discovery, g);
  buildRegistryPane(registry, g);
  return ws;
}

// Documents in the staged pool that aren't already mapped into the project graph, plus the
// subset matching the current filter. Recomputed cheaply on each targeted update.
function stagedVisible(g) {
  const mappedIds = new Set((g.documents || []).map((d) => d.id));
  // The shared unassigned pool is drawn from across all projects, so a document already
  // mapped to ANY project (not just the selected one) is spoken for and must not reappear
  // here. Per-project staging keeps the narrower selected-project-only exclusion.
  if (stagedData && stagedData.is_unassigned) {
    ((STATE && STATE.graphs) || []).forEach((gr) =>
      (gr.documents || []).forEach((d) => mappedIds.add(d.id)));
  }
  const all = (stagedData.documents || []).filter((d) => !mappedIds.has(d.id));
  const q = stagedFilter.trim().toLowerCase();
  const filtered = q
    ? all.filter((d) => (d.name + " " + (d.description || "")).toLowerCase().includes(q))
    : all;
  return { all, filtered };
}

function buildDiscoveryPane(container, g) {
  const head = el("div", "pane-head");
  head.append(el("strong", "", "Discovery"));
  const toggle = el("div", "pool-toggle");
  for (const [val, label] of [["project", "Staged"], ["unassigned", "Unassigned"]]) {
    const b = el("button", "pool-opt" + (stagedPool === val ? " active" : ""), label);
    b.onclick = () => {
      if (stagedPool === val) return;
      stagedPool = val; stagedData = null; stagedSel = new Set(); stagedFilter = "";
      loadStaged(g.slug);
    };
    toggle.append(b);
  }
  head.append(toggle);
  container.append(head);

  if (!stagedData || !stagedData.ok || stagedData.slug !== graphSlug) {
    const hint = stagedPool === "unassigned"
      ? "Run `mitos connect --stage` (no project) to fill the shared unassigned pool."
      : "Run `mitos connect --project " + g.slug + " --stage [--query TEXT]` to stage"
        + " documents for this project.";
    container.append(el("div", "muted pane-hint", hint));
    return;
  }

  const sbar = el("div", "staged-bar");
  const search = el("input", "staged-search");
  search.type = "search"; search.placeholder = "Filter staged…"; search.value = stagedFilter;
  search.oninput = () => { stagedFilter = search.value; renderStagedRows(g); };
  const info = el("span", "muted staged-info");
  const selAll = el("button", "ghost tiny", "Select all");
  selAll.onclick = () => {
    const pending = pendingDocIds(g.slug);
    const d = draftFor(g.slug);
    stagedVisible(g).filtered.forEach((doc) => {
      if (!pending.has(doc.id) && !d.add[doc.id]) stagedSel.add(doc.id);
    });
    renderStagedRows(g);
  };
  const clr = el("button", "ghost tiny", "Clear");
  clr.onclick = () => { stagedSel = new Set(); renderStagedRows(g); };
  const add = el("button", "accept tiny staged-add");
  add.onclick = () => addSelectedStaged(g);
  sbar.append(search, info, selAll, clr, add);
  container.append(sbar);
  container.append(el("div", "staged-rows"));
  // Defer until the workspace is in the DOM (querySelector needs #graph-workspace present)
  setTimeout(() => renderStagedRows(g), 0);
}

// Rebuild ONLY the staged rows (and the counter/add button). Never touches the search box.
function renderStagedRows(g) {
  const rows = document.querySelector("#graph-workspace .staged-rows");
  if (!rows) return;
  const isUnassigned = stagedData && stagedData.is_unassigned;
  const pending = pendingDocIds(g.slug);
  const draft = draftFor(g.slug);
  for (const id of [...stagedSel]) if (pending.has(id) || draft.add[id]) stagedSel.delete(id);
  const { all, filtered } = stagedVisible(g);

  rows.replaceChildren();
  if (all.length === 0) {
    rows.append(el("div", "muted", isUnassigned
      ? "Unassigned pool is empty or all documents are already mapped."
      : "Nothing staged. Run `mitos connect --project " + g.slug
        + " --stage --query …` to discover documents."));
  } else if (filtered.length === 0) {
    rows.append(el("div", "muted", "No matches for current filter."));
  } else {
    for (const d of filtered) {
      // An open "Tweak" editor for this staged doc replaces its row in place.
      if (openEditor && openEditor.where === "staged" && openEditor.vals.id === d.id) {
        rows.append(editorCard(g)); continue;
      }
      const isPending = pending.has(d.id);
      const inDraft = !!draft.add[d.id];
      const row = el("div", "staged-row" + (isPending ? " pending" : "") + (inDraft ? " indraft" : ""));
      const cb = el("input"); cb.type = "checkbox";
      cb.checked = stagedSel.has(d.id); cb.disabled = isPending || inDraft;
      cb.onchange = () => {
        if (cb.checked) stagedSel.add(d.id); else stagedSel.delete(d.id);
        updateStagedMeta(g);
      };
      const body = el("div", "staged-body");
      const nameLine = el("div", "staged-nameline");
      nameLine.append(el("span", "staged-name", d.name));
      if (isPending) nameLine.append(el("span", "badge pending", "Pending"));
      if (inDraft) nameLine.append(el("span", "badge draft", "In draft"));
      body.append(nameLine);
      const meta = el("div", "staged-meta");
      if (d.dateModified) meta.append(el("span", "muted staged-mod", d.dateModified));
      if (isPending) {
        meta.append(el("span", "muted", "awaiting review"));
      } else if (inDraft) {
        const actions = el("span", "row-actions");
        const undo = el("button", "ghost tiny", "Undo");
        undo.onclick = () => { draftUndo(g.slug, d.id); renderGraph(); };
        actions.append(undo);
        meta.append(actions);
      } else {
        const actions = el("span", "row-actions");
        const map = el("button", "ghost tiny", "Map");
        map.title = "Add this document to the draft with its staged values";
        map.onclick = () => { draftUpsert(g.slug, stagedDoc(d), true); renderGraph(); };
        const tweak = el("button", "ghost tiny", "Tweak & map");
        tweak.title = "Edit the title/description before adding to the draft";
        tweak.onclick = () => openTweak(g, d);
        actions.append(map, tweak);
        meta.append(actions);
      }
      if (d.webUrl) {
        const a = el("a", "staged-link", "Open");
        a.target = "_blank"; a.rel = "noopener";
        a.href = d.webUrl;   // webUrl is a known-safe Drive/workspace URL from the connector
        meta.append(a);
      }
      body.append(meta);
      row.append(cb, body);
      rows.append(row);
    }
  }
  updateStagedMeta(g);
}

function stagedDoc(d) {
  return { id: d.id, name: d.name, description: d.description || "",
           dateModified: d.dateModified || todayISO(), keywords: d.keywords || "" };
}

function updateStagedMeta(g) {
  const info = document.querySelector("#graph-workspace .staged-info");
  const add = document.querySelector("#graph-workspace .staged-add");
  const { all } = stagedVisible(g);
  if (info) {
    info.textContent = `${all.length} staged · ${stagedSel.size} selected`
      + (stagedData.staged_at ? ` · ${stagedData.staged_at}` : "");
  }
  if (add) {
    add.textContent = `Add selected (${stagedSel.size})`;
    add.disabled = stagedSel.size === 0;
  }
}

function addSelectedStaged(g) {
  const picked = (stagedData && stagedData.documents || []).filter((d) => stagedSel.has(d.id));
  if (!picked.length) { toast("Tick at least one document."); return; }
  for (const d of picked) draftUpsert(g.slug, stagedDoc(d), true);
  stagedSel = new Set();
  toast(`Added ${picked.length} to the draft — review in the dock, then Propose.`);
  renderGraph();
}

// ── right pane: the project's mapped documents + draft adds, grouped by effort ──
function buildRegistryPane(container, g) {
  const head = el("div", "pane-head");
  head.append(el("strong", "", "Registry"));
  const addDocBtn = el("button", "ghost tiny", "+ Doc");
  addDocBtn.title = "Map a document by hand (e.g. a Drive ID that isn't staged)";
  addDocBtn.onclick = () => {
    openEditor = { where: "registry", lockId: false, kind: "doc",
                   vals: { id: "", name: "", description: "", dateModified: todayISO(), keywords: "", parentId: "" } };
    renderRegistryRows(g);
  };
  const addEffortBtn = el("button", "ghost tiny", "+ Work");
  addEffortBtn.title = "Add a new effort grouping to this project";
  addEffortBtn.onclick = () => {
    openEditor = { where: "registry", lockId: false, kind: "effort",
                   vals: { id: "", name: "", description: "" } };
    renderRegistryRows(g);
  };
  head.append(addDocBtn, addEffortBtn);
  container.append(head);
  container.append(el("div", "registry-rows"));
  setTimeout(() => renderRegistryRows(g), 0);
}

function renderRegistryRows(g) {
  const box = document.querySelector("#graph-workspace .registry-rows");
  if (!box) return;
  box.replaceChildren();
  const draft = draftFor(g.slug);
  const pending = pendingDocIds(g.slug);

  // ── unplaced editor: a fresh add (doc or effort) with no matching existing row ──
  const isEditorOpen = openEditor && openEditor.where === "registry";
  const editorId = isEditorOpen ? openEditor.vals.id : null;
  const isEffortEditor = isEditorOpen && openEditor.kind === "effort";
  const isDocEditor = isEditorOpen && openEditor.kind === "doc";
  const editorUnplaced = isEditorOpen && editorId === ""
    || (isDocEditor && !g.documents.some((d) => d.id === editorId) && !draft.add[editorId])
    || (isEffortEditor && !g.efforts.some((e) => e.id === editorId) && !draft.effortAdd[editorId]);
  if (editorUnplaced && isEffortEditor) box.append(effortEditorCard(g));
  else if (editorUnplaced && isDocEditor) box.append(editorCard(g));

  // ── effort-grouped rendering ──────────────────────────────────────────────
  // Effective efforts = registry + draft adds/edits, minus draft removes
  const effMap = {};
  for (const e of (g.efforts || [])) effMap[e.id] = { ...e };
  for (const e of Object.values(draft.effortAdd)) effMap[e.id] = { ...e, _status: "add" };
  for (const e of Object.values(draft.effortEdit)) effMap[e.id] = { ...effMap[e.id], ...e, _status: "edit" };
  for (const id of Object.keys(draft.effortRemove)) {
    if (effMap[id]) effMap[id] = { ...effMap[id], _status: "remove" };
  }

  // "project root" section: draft adds without a parentId, then docs with parentId=""
  const rootDraftAdds = Object.values(draft.add).filter((d) => !d.parentId);
  const rootDocs = (g.documents || []).filter((d) => !d.parentId);
  const hasEfforts = Object.keys(effMap).length > 0;

  if (hasEfforts) {
    const rootSection = el("div", "effort-section");
    const rootHead = el("div", "effort-header");
    rootHead.append(el("span", "effort-name", "Project Documents"));
    rootSection.append(rootHead);
    const rootDocs2 = el("div", "effort-docs");
    _renderDocGroup(rootDocs2, g, rootDraftAdds, rootDocs, draft, pending, false);
    rootSection.append(rootDocs2);
    box.append(rootSection);
  } else {
    // No efforts — flat list with pending doc adds first
    _renderDocGroup(box, g, Object.values(draft.add), g.documents || [], draft, pending, true);
    if (!(g.documents || []).length && !Object.keys(draft.add).length && !isEditorOpen) {
      box.append(el("div", "empty-state", "No documents mapped yet — Add one or Map from Discovery."));
    }
  }

  // ── effort sections ───────────────────────────────────────────────────────
  for (const effort of Object.values(effMap).sort((a, b) =>
      (a.name || "").localeCompare(b.name || ""))) {
    const status = effort._status || "mapped";
    const section = el("div", "effort-section" + (status === "remove" ? " effort-remove" : ""));

    // effort header row
    const head = el("div", "effort-header");
    const nameSpan = el("span", "effort-name" + (status === "remove" ? " struck" : ""), effort.name);
    head.append(nameSpan);
    if (status !== "mapped") {
      const label = { add: "Pending add", edit: "Pending edit", remove: "Pending remove" }[status];
      head.append(el("span", "badge draft", label));
    }
    const actions = el("span", "row-actions");
    if (status === "add" || status === "edit" || status === "remove") {
      const undo = el("button", "ghost tiny", "Undo");
      undo.onclick = () => { effortDraftUndo(g.slug, effort.id); renderGraph(); };
      actions.append(undo);
    }
    if (status !== "remove") {
      const edit = el("button", "ghost tiny", "Edit");
      edit.onclick = () => {
        openEditor = { where: "registry", lockId: true, kind: "effort",
                       vals: { id: effort.id, name: effort.name, description: effort.description || "" } };
        renderRegistryRows(g);
      };
      actions.append(edit);
      if (status !== "add") {
        const rm = el("button", "ghost tiny danger", "Remove");
        rm.title = "Schedule this effort for removal (its documents reset to Project root)";
        rm.onclick = () => { effortDraftRemove(g.slug, effort); renderGraph(); };
        actions.append(rm);
      }
    }
    head.append(actions);
    section.append(head);

    if (effort.description) {
      section.append(el("div", "effort-desc muted", effort.description));
    }

    // effort editor in-place
    if (isEffortEditor && editorId === effort.id) {
      section.append(effortEditorCard(g));
    }

    // documents belonging to this effort
    const effortDraftAdds = Object.values(draft.add).filter((d) => d.parentId === effort.id);
    const effortDocs = (g.documents || []).filter((d) => d.parentId === effort.id);
    const docBox = el("div", "effort-docs");
    _renderDocGroup(docBox, g, effortDraftAdds, effortDocs, draft, pending, false);
    section.append(docBox);

    box.append(section);
  }
}

function _renderDocGroup(container, g, draftAdds, registryDocs, draft, pending, showEmpty) {
  const isEditorOpen = openEditor && openEditor.where === "registry" && openEditor.kind === "doc";
  for (const doc of draftAdds) {
    if (isEditorOpen && openEditor.vals.id === doc.id) {
      container.append(editorCard(g));
    } else {
      container.append(registryRow(g, doc, "add", pending));
    }
  }
  if (showEmpty && !registryDocs.length && !draftAdds.length && !openEditor) {
    container.append(el("div", "empty-state", "No documents mapped yet — Add one or Map from Discovery."));
  }
  for (const doc of registryDocs) {
    if (isEditorOpen && openEditor.vals.id === doc.id) {
      container.append(editorCard(g)); continue;
    }
    const removed = !!draft.remove[doc.id];
    const edited = draft.edit[doc.id];
    const status = removed ? "remove" : (edited ? "edit" : "mapped");
    container.append(registryRow(g, edited || doc, status, pending));
  }
}

function registryRow(g, doc, status, pending) {
  const isPending = pending.has(doc.id);
  const row = el("div", "registry-row " + status + (isPending ? " pending" : ""));
  const body = el("div", "staged-body");
  const nameLine = el("div", "staged-nameline");
  const name = el("span", "staged-name" + (status === "remove" ? " struck" : ""), doc.name);
  nameLine.append(name);
  const badge = { add: "Pending add", edit: "Pending edit", remove: "Pending remove" }[status];
  if (badge) nameLine.append(el("span", "badge draft", badge));
  if (isPending) nameLine.append(el("span", "badge pending", "Awaiting review"));
  body.append(nameLine);

  if (doc.description) body.append(el("div", "registry-desc muted", doc.description));
  if (doc.keywords) {
    const chips = el("div", "doc-tags");
    doc.keywords.split(",").forEach((t) => {
      const c = t.trim(); if (c) chips.append(el("span", "tag-chip muted", c));
    });
    body.append(chips);
  }
  const meta = el("div", "staged-meta");
  if (doc.dateModified) meta.append(el("span", "muted staged-mod", doc.dateModified));
  meta.append(el("span", "muted mono registry-id", doc.id));

  const openUrl = doc.webUrl || `https://drive.google.com/open?id=${doc.id}`;
  const openLink = el("a", "staged-link", "Open");
  openLink.target = "_blank"; openLink.rel = "noopener"; openLink.href = openUrl;
  meta.append(openLink);

  const actions = el("span", "row-actions");
  if (status === "remove" || status === "add" || status === "edit") {
    const undo = el("button", "ghost tiny", "Undo");
    undo.onclick = () => { draftUndo(g.slug, doc.id); renderGraph(); };
    actions.append(undo);
  }
  if (status !== "remove" && !isPending) {
    const edit = el("button", "ghost tiny", "Edit");
    edit.onclick = () => {
      openEditor = { where: "registry", lockId: true, kind: "doc",
                     vals: { id: doc.id, name: doc.name,
                             description: doc.description || "", dateModified: doc.dateModified,
                             keywords: doc.keywords || "", parentId: doc.parentId || "" } };
      renderRegistryRows(g);
    };
    actions.append(edit);
    if (status !== "add") {   // a draft add is undone, not removed — it isn't in the registry yet
      const rm = el("button", "ghost tiny danger", "Remove");
      rm.title = "Schedule this mapping for removal from the registry";
      rm.onclick = () => { draftRemove(g.slug, doc); renderGraph(); };
      actions.append(rm);
    }
  }
  meta.append(actions);
  body.append(meta);
  row.append(body);
  return row;
}

// One inline editor for a document: manual add, staged "Tweak & map", or editing a mapped doc.
// Inputs are local until Apply, so typing never triggers a re-render (focus-safe).
function editorCard() {
  const g = (STATE.graphs || []).find((x) => x.slug === graphSlug);
  const card = el("div", "inline-editor");
  const vals = openEditor.vals;
  const inputs = {};
  const field = (key, label, ph, type, readonly) => {
    const wrap = el("div", "graph-field");
    wrap.append(el("label", "", label));
    const inp = el("input");
    inp.type = type || "text"; inp.value = vals[key] || "";
    if (ph) inp.placeholder = ph;
    if (readonly) { inp.readOnly = true; inp.classList.add("ro"); }
    if (type === "date") inp.classList.add("date");
    wrap.append(inp); card.append(wrap); inputs[key] = inp;
    return inp;
  };
  field("id", "Drive ID", "1AbC…xyz", "text", openEditor.lockId);
  field("name", "Title", "Forecast UI Spec");
  field("description", "Description", "one-line summary");
  field("dateModified", "Modified", "", "date");
  field("keywords", "Tags", "strategy, Q4, draft");

  // Parent effort dropdown
  const draft = draftFor(g.slug);
  const effMap = {};
  for (const e of (g.efforts || [])) effMap[e.id] = e;
  for (const e of Object.values(draft.effortAdd)) effMap[e.id] = e;
  for (const e of Object.values(draft.effortEdit)) effMap[e.id] = { ...effMap[e.id], ...e };
  for (const id of Object.keys(draft.effortRemove)) delete effMap[id];
  const effortList = Object.values(effMap).sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  if (effortList.length) {
    const wrap = el("div", "graph-field");
    wrap.append(el("label", "", "Parent"));
    const sel = el("select", "graph-select");
    const rootOpt = el("option"); rootOpt.value = ""; rootOpt.textContent = "Project root";
    sel.append(rootOpt);
    for (const e of effortList) {
      const opt = el("option"); opt.value = e.id; opt.textContent = e.name;
      if ((vals.parentId || "") === e.id) opt.selected = true;
      sel.append(opt);
    }
    wrap.append(sel); card.append(wrap); inputs.parentId = sel;
  }

  inputs.name.focus();

  const actions = el("div", "inline-actions");
  const apply = el("button", "accept tiny", "Apply");
  apply.onclick = () => {
    const doc = { id: inputs.id.value.trim(), name: inputs.name.value.trim(),
                  description: inputs.description.value.trim(),
                  dateModified: inputs.dateModified.value.trim(),
                  keywords: inputs.keywords.value.trim(),
                  parentId: inputs.parentId ? inputs.parentId.value : "" };
    if (!doc.id || !doc.name || !doc.dateModified) {
      toast("Drive ID, Title, and Modified are required."); return;
    }
    const isAdd = !g.documents.some((d) => d.id === doc.id);
    draftUpsert(g.slug, doc, isAdd);
    openEditor = null;
    renderGraph();
  };
  const cancel = el("button", "ghost tiny", "Cancel");
  cancel.onclick = () => { openEditor = null; renderGraph(); };
  actions.append(apply, cancel);
  card.append(actions);
  return card;
}

// Inline editor for adding or editing an effort.
function effortEditorCard(g) {
  const card = el("div", "inline-editor");
  const vals = openEditor.vals;
  const inputs = {};
  const field = (key, label, ph, readonly) => {
    const wrap = el("div", "graph-field");
    wrap.append(el("label", "", label));
    const inp = el("input");
    inp.type = "text"; inp.value = vals[key] || "";
    if (ph) inp.placeholder = ph;
    if (readonly) { inp.readOnly = true; inp.classList.add("ro"); }
    wrap.append(inp); card.append(wrap); inputs[key] = inp;
    return inp;
  };
  field("id", "Effort ID (slug)", "auth-rework", openEditor.lockId);
  field("name", "Name", "Auth Rework");
  field("description", "Description", "short summary (optional)");
  inputs.name.focus();

  const actions = el("div", "inline-actions");
  const apply = el("button", "accept tiny", "Apply");
  apply.onclick = () => {
    const effort = { id: inputs.id.value.trim().toLowerCase(),
                     name: inputs.name.value.trim(),
                     description: inputs.description.value.trim() };
    if (!effort.id || !effort.name) { toast("Effort ID and Name are required."); return; }
    if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(effort.id)) {
      toast("Effort ID must be lowercase alphanumerics and hyphens, no leading/trailing/consecutive hyphens.");
      return;
    }
    const isAdd = !g.efforts.some((e) => e.id === effort.id);
    effortDraftUpsert(g.slug, effort, isAdd);
    openEditor = null;
    renderGraph();
  };
  const cancel = el("button", "ghost tiny", "Cancel");
  cancel.onclick = () => { openEditor = null; renderGraph(); };
  actions.append(apply, cancel);
  card.append(actions);
  return card;
}

function openTweak(g, d) {
  openEditor = { where: "staged", lockId: true, kind: "doc", vals: stagedDoc(d) };
  renderStagedRows(g);
}

// ── persistent proposal dock ──────────────────────────────────────────────────
function updateGraphDock() {
  const dock = $("graph-dock");
  if (!dock) return;
  const onGraph = !$("view-graph").hidden;
  const c = graphSlug ? draftCounts(graphSlug) : { adds: 0, edits: 0, removes: 0 };
  const total = c.adds + c.edits + c.removes + (c.effortAdds || 0) + (c.effortEdits || 0) + (c.effortRemoves || 0);
  if (!onGraph || !total) { dock.hidden = true; return; }
  dock.hidden = false;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const parts = [];
  if (c.adds) parts.push(plural(c.adds, "doc addition"));
  if (c.edits) parts.push(plural(c.edits, "doc edit"));
  if (c.removes) parts.push(plural(c.removes, "doc removal"));
  if (c.effortAdds) parts.push(plural(c.effortAdds, "effort"));
  if (c.effortEdits) parts.push(plural(c.effortEdits, "effort edit"));
  if (c.effortRemoves) parts.push(plural(c.effortRemoves, "effort removal"));
  $("graph-dock-summary").textContent = `${graphSlug}: ${parts.join(" · ")}`;
}

async function proposeGraphDraft() {
  const slug = graphSlug;
  if (!slug) return;
  const d = draftFor(slug);
  const documents = [...Object.values(d.add), ...Object.values(d.edit)].map((x) => ({
    id: x.id, name: x.name, description: x.description || "",
    dateModified: x.dateModified, keywords: x.keywords || "", parentId: x.parentId || "" }));
  const removals = Object.keys(d.remove);
  const efforts = [...Object.values(d.effortAdd), ...Object.values(d.effortEdit)].map((x) => ({
    id: x.id, name: x.name, description: x.description || "" }));
  const effortRemovals = Object.keys(d.effortRemove);
  if (!documents.length && !removals.length && !efforts.length && !effortRemovals.length) {
    toast("No changes to propose."); return;
  }
  const reason = $("graph-dock-reason").value.trim();
  const res = await fetch("/api/graph", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug, documents, removals, efforts, effortRemovals, reason }),
  });
  const out = await res.json();
  if (out.ok) {
    toast(`Proposed → inbox/${out.id}. Review and Accept in the Inbox tab.`, 5000);
    draftClear(slug);
    $("graph-dock-reason").value = "";
    await refresh();
  } else {
    toast(`Error: ${out.error}`, 5000);
  }
}

function discardGraphDraft() {
  if (!graphSlug || !draftTotal(graphSlug)) return;
  draftClear(graphSlug);
  openEditor = null;
  toast("Draft discarded.");
  renderGraph();
}

// ── prompt library: a two-pane master–detail workspace ───────────────────────
// One flat, uniform prompt model feeds the left list, the detail editor, and the
// composer. Built fresh each render so it tracks /api/state. Skills and partials are
// normalized to the same shape; `key` ("skill:name" | "partial:rel") is the identity.
function buildPrompts() {
  const out = [];
  // `name` stays the full identifier (used by the detail pane, composer, toasts);
  // `label` is the short list display — for skills they're the same, for partials
  // `label` drops the group prefix + .md the group header already implies.
  const catLabels = { departments: "Departments", devops: "DevOps", productivity: "Productivity" };
  for (const s of STATE.prompts.skills) {
    out.push({
      key: `skill:${s.name}`, kind: "skill", ident: s.name, name: s.name, label: s.name,
      desc: s.description || "", catName: s.category,
      meta: s.description || "", targets: s.targets || [], body: s.body,
      group: `skill:${s.category}`,
      groupLabel: catLabels[s.category] || s.category.replace(/^./, (c) => c.toUpperCase()),
      search: `${s.name} ${s.description || ""} ${s.body}`.toLowerCase(),
    });
  }
  const labels = { identity: "Identity", context: "Context", projects: "Projects" };
  for (const p of STATE.prompts.partials) {
    out.push({
      key: `partial:${p.rel}`, kind: "partial", ident: p.rel, name: p.rel,
      label: p.rel.split("/").pop().replace(/\.md$/, ""),
      desc: "", catName: p.group,
      meta: p.audience ? `audience: ${p.audience.join(", ")}` : "all targets",
      targets: null, body: p.body,
      group: `partial:${p.group}`, groupLabel: labels[p.group] || p.group,
      search: `${p.rel} ${p.body}`.toLowerCase(),
    });
  }
  return out;
}

// skill groups first (departments before the rest), then identity/context/projects —
// the same ordering the old flat list used.
function groupOrder(gid) {
  if (gid.startsWith("skill:")) {
    const cat = gid.slice(6);
    return [0, cat === "departments" ? 0 : 1, cat];
  }
  const rank = { identity: 1, context: 2, projects: 3 }[gid.slice(8)] ?? 9;
  return [1, rank, gid];
}
function cmpTuple(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

function renderPrompts() {
  PROMPTS = buildPrompts();
  PMAP = new Map(PROMPTS.map((p) => [p.key, p]));
  pruneKeys();                 // drop keys for prompts that no longer exist
  renderChips();
  renderList();
  renderDetail();
  renderCompose();
}

function pruneKeys() {
  favorites = favorites.filter((k) => PMAP.has(k));
  recents = recents.filter((k) => PMAP.has(k));
  compose.items = compose.items.filter((k) => PMAP.has(k));
  for (const k of Object.keys(drafts)) if (!PMAP.has(k)) delete drafts[k];
  if (selectedKey && !PMAP.has(selectedKey)) selectedKey = null;
}

// ── left pane: filterable, collapsible, with Favorites + Recent pinned on top ──
function renderChips() {
  const box = $("filter-chips");
  box.replaceChildren();
  for (const [id, label] of [["all", "All"], ["skill", "Skills"],
      ["identity", "Identity"], ["context", "Context"], ["projects", "Projects"]]) {
    const c = el("button", "chip" + (filterChip === id ? " active" : ""), label);
    c.onclick = () => { filterChip = id; renderChips(); renderList(); };
    box.append(c);
  }
}

function chipAllows(p) {
  if (filterChip === "all") return true;
  if (filterChip === "skill") return p.kind === "skill";
  return p.kind === "partial" && p.catName === filterChip;
}

function renderList() {
  const list = $("prompt-list");
  const q = $("search").value.trim().toLowerCase();
  const matches = (p) => (!q || p.search.includes(q)) && chipAllows(p);
  list.replaceChildren();

  const pick = (keys) => keys.map((k) => PMAP.get(k)).filter(Boolean).filter(matches);
  const favs = pick(favorites);
  const recs = pick(recents).filter((p) => !favorites.includes(p.key));
  if (favs.length) appendSection(list, "_fav", "★ Favorites", favs);
  if (recs.length) appendSection(list, "_recent", "⮌ Recently used", recs);

  const groups = new Map();
  for (const p of PROMPTS) {
    if (!matches(p)) continue;
    if (!groups.has(p.group)) groups.set(p.group, { label: p.groupLabel, items: [] });
    groups.get(p.group).items.push(p);
  }
  for (const [gid, g] of [...groups.entries()]
      .sort((a, b) => cmpTuple(groupOrder(a[0]), groupOrder(b[0])))) {
    appendSection(list, gid, g.label, g.items);
  }
  if (!list.children.length) list.append(el("div", "empty-state", "No prompts match."));
}

function appendSection(list, gid, label, items) {
  const isCollapsed = !!collapsed[gid];
  const header = el("div", "list-group");
  header.append(el("span", "caret", isCollapsed ? "▸" : "▾"),
                el("span", "list-group-label", label),
                el("span", "list-count", String(items.length)));
  header.onclick = () => {
    collapsed[gid] = !isCollapsed;
    store.set(LS.collapsed, collapsed);
    renderList();
  };
  list.append(header);
  if (isCollapsed) return;
  for (const p of items) list.append(listRow(p));
}

function listRow(p) {
  const row = el("div", "list-row" + (p.key === selectedKey ? " active" : ""));
  row.dataset.key = p.key;
  const pinned = favorites.includes(p.key);
  const star = el("button", "row-star" + (pinned ? " on" : ""), pinned ? "★" : "☆");
  star.title = pinned ? "Unpin from Favorites" : "Pin to Favorites";
  star.onclick = (e) => { e.stopPropagation(); toggleFavorite(p.key); };

  // line 1 is the name — it owns the row width and is never out-competed; state tags
  // ride along on the right. The description, when present, drops to a muted line 2
  // clamped to one line, with the full text in the tooltip and the detail pane.
  const col = el("div", "row-col");
  const line1 = el("div", "row-line1");
  const name = el("span", "row-name", p.label);
  name.title = p.name;
  line1.append(name);
  if (drafts[p.key] != null) line1.append(el("span", "row-tag edited", "edited"));
  if (compose.items.includes(p.key)) line1.append(el("span", "row-tag", "compose"));
  col.append(line1);
  if (p.desc) {
    const desc = el("span", "row-desc", p.desc);
    desc.title = p.desc;
    col.append(desc);
  }

  row.append(star, col);
  row.onclick = () => selectPrompt(p.key);
  return row;
}

function setActiveRow() {
  for (const row of $("prompt-list").querySelectorAll(".list-row"))
    row.classList.toggle("active", row.dataset.key === selectedKey);
}

// ── right pane: the editable detail / proposal editor ─────────────────────────
function selectPrompt(key) {
  selectedKey = key;
  setActiveRow();      // cheap highlight, preserves list scroll
  renderDetail();
}

function renderDetail() {
  const box = $("prompt-detail");
  box.replaceChildren();
  const p = selectedKey && PMAP.get(selectedKey);
  if (!p) {
    box.append(el("div", "empty-state",
      "Select a prompt to view, edit, copy, or compose."));
    return;
  }
  const head = el("div", "detail-head");
  head.append(el("strong", "detail-name", p.name));
  if (p.kind === "skill") head.append(el("span", "badge kind", p.catName));
  head.append(el("span", "muted",
    p.targets ? `targets: ${p.targets.join(", ")}` : p.meta));
  box.append(head);
  if (p.desc) box.append(el("div", "detail-desc", p.desc));

  const ta = el("textarea");
  ta.id = "detail-body";
  ta.spellcheck = false;
  ta.value = drafts[p.key] != null ? drafts[p.key] : p.body;

  const editorWrap = el("div", "editor-wrap");
  const gutter = el("div", "line-nums");

  function syncGutter() {
    const n = ta.value === "" ? 1 : ta.value.split("\n").length;
    gutter.textContent = Array.from({length: n}, (_, i) => i + 1).join("\n");
    gutter.scrollTop = ta.scrollTop;
  }

  ta.oninput = () => {
    if (ta.value === p.body) delete drafts[p.key];
    else drafts[p.key] = ta.value;
    store.set(LS.drafts, drafts);
    syncGutter();
    updateDetailStatus(p);
  };
  ta.addEventListener("scroll", () => { gutter.scrollTop = ta.scrollTop; });
  ta.addEventListener("click", () => updateDetailStatus(p));
  ta.addEventListener("keyup", () => updateDetailStatus(p));

  editorWrap.append(gutter, ta);
  box.append(editorWrap);
  syncGutter();

  box.append(el("div", "detail-status muted"));

  const actions = el("div", "detail-actions");
  const left = el("span", "action-group");
  const copy = el("button", "", "Copy");
  copy.onclick = () => { copyText(currentBody(p), p.name); pushRecent(p.key); };
  const inComp = compose.items.includes(p.key);
  const comp = el("button", "ghost", inComp ? "Remove from compose" : "Add to compose");
  comp.onclick = () => toggleCompose(p.key);
  const pinned = favorites.includes(p.key);
  const pin = el("button", "ghost", pinned ? "★ Pinned" : "☆ Pin");
  pin.onclick = () => { toggleFavorite(p.key); renderDetail(); };
  left.append(copy, comp, pin);

  const right = el("span", "action-group save-group");
  const reason = el("input");
  reason.type = "text";
  reason.id = "detail-reason";
  reason.className = "detail-reason";
  reason.placeholder = "Reason (optional — logged on accept)";
  const save = el("button", "accept", "Save to inbox");
  save.title = "Propose this edited prompt as an inbox candidate to Accept later";
  save.onclick = () => saveDraft(p, currentBody(p), reason.value);
  const revert = el("button", "reject", "Revert");
  revert.disabled = drafts[p.key] == null;
  revert.title = "Discard local edits and restore the registry text";
  revert.onclick = () => {
    delete drafts[p.key];
    store.set(LS.drafts, drafts);
    renderDetail();
    renderList();
  };
  right.append(reason, save, revert);
  actions.append(left, right);
  box.append(actions);
  updateDetailStatus(p);
}

function currentBody(p) {
  const ta = $("detail-body");
  return ta && selectedKey === p.key ? ta.value
    : (drafts[p.key] != null ? drafts[p.key] : p.body);
}

function updateDetailStatus(p) {
  const detail = $("prompt-detail");
  if (!detail) return;
  const s = detail.querySelector(".detail-status");
  if (!s) return;
  const ta = $("detail-body");
  const modified = drafts[p.key] != null;
  const body = currentBody(p);
  let cursor = "";
  if (ta && document.activeElement === ta) {
    const before = ta.value.slice(0, ta.selectionStart);
    const ln = before.split("\n");
    cursor = ` · Ln ${ln.length}, Col ${ln[ln.length - 1].length + 1}`;
  }
  s.textContent = `${modified ? "● " : ""}${body.length.toLocaleString()} chars · ${p.kind} · ${p.ident}${cursor}`;
  s.classList.toggle("modified", modified);
}

async function saveDraft(p, body, reason) {
  const res = await fetch("/api/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: p.kind, ident: p.ident, body, reason }),
  });
  const out = await res.json();
  if (out.ok) {
    toast(`Proposed → inbox/${out.id} — review in the Inbox tab, then Accept.`, 5000);
    pushRecent(p.key);
    await refresh();          // surface the new candidate + bump the Inbox pill
  } else {
    toast(`Error: ${out.error}`, 5000);
  }
}

// ── favorites / recents ───────────────────────────────────────────────────────
function toggleFavorite(key) {
  const i = favorites.indexOf(key);
  if (i >= 0) favorites.splice(i, 1);
  else favorites.unshift(key);
  store.set(LS.favorites, favorites);
  renderList();
  if (selectedKey === key) renderDetail();
}

function pushRecent(key) {
  const i = recents.indexOf(key);
  if (i >= 0) recents.splice(i, 1);
  recents.unshift(key);
  if (recents.length > 12) recents.length = 12;
  store.set(LS.recents, recents);
  renderList();
}

// ── composer: an ordered, editable, persisted scratchpad ──────────────────────
function effectiveBody(key) {
  const p = PMAP.get(key);
  if (!p) return "";
  return (drafts[key] != null ? drafts[key] : p.body).trim();
}
function composeDerive() {
  return compose.items.map(effectiveBody).filter(Boolean).join("\n\n");
}
function composeOutput() {
  return compose.text != null ? compose.text : composeDerive();
}

function toggleCompose(key) {
  const i = compose.items.indexOf(key);
  if (i >= 0) {
    compose.items.splice(i, 1);
  } else {
    compose.items.push(key);
    // extend a hand-edited buffer in place; otherwise keep deriving from parts
    if (compose.text != null) {
      compose.text = (compose.text.trim() + "\n\n" + effectiveBody(key)).trim();
    }
  }
  store.set(LS.compose, compose);
  renderCompose();
  renderList();
  if (selectedKey === key) renderDetail();
}

function moveCompose(idx, d) {
  const j = idx + d;
  if (j < 0 || j >= compose.items.length) return;
  [compose.items[idx], compose.items[j]] = [compose.items[j], compose.items[idx]];
  store.set(LS.compose, compose);
  renderCompose();
}

function removeCompose(idx) {
  compose.items.splice(idx, 1);
  store.set(LS.compose, compose);
  renderCompose();
  renderList();
}

function renderCompose() {
  const bar = $("compose");
  const hasText = compose.text != null && compose.text.trim() !== "";
  if (!compose.items.length && !hasText) { bar.hidden = true; return; }
  bar.hidden = false;
  const out = composeOutput();
  const edited = compose.text != null ? " · edited" : "";
  $("compose-info").textContent =
    `${compose.items.length} part(s)${edited} · ${out.length.toLocaleString()} chars`;

  const parts = $("compose-parts");
  parts.replaceChildren();
  compose.items.forEach((key, idx) => {
    const p = PMAP.get(key);
    const row = el("div", "compose-part");
    row.append(el("span", "part-name", p ? p.name : key));
    const ctl = el("span", "part-ctl");
    const up = el("button", "tiny", "↑"); up.disabled = idx === 0;
    up.onclick = () => moveCompose(idx, -1);
    const down = el("button", "tiny", "↓"); down.disabled = idx === compose.items.length - 1;
    down.onclick = () => moveCompose(idx, 1);
    const rm = el("button", "tiny", "×"); rm.title = "Remove from compose";
    rm.onclick = () => removeCompose(idx);
    ctl.append(up, down, rm);
    row.append(ctl);
    parts.append(row);
  });

  const ta = $("compose-text");
  if (document.activeElement !== ta) ta.value = out;   // don't clobber mid-typing
  ta.oninput = () => {
    compose.text = ta.value;
    store.set(LS.compose, compose);
    $("compose-info").textContent =
      `${compose.items.length} part(s) · edited · ${ta.value.length.toLocaleString()} chars`;
  };
}

// ── wiring ───────────────────────────────────────────────────────────────────
function showTab(which) {
  $("view-inbox").hidden = which !== "inbox";
  $("view-graph").hidden = which !== "graph";
  $("view-prompts").hidden = which !== "prompts";

  // sidebar active state
  const activeNav = which === "prompts" ? "nav-prompts"
    : ({ inbox: "nav-inbox", graph: "nav-graph" }[which] || "");
  for (const id of ["nav-graph", "nav-prompts", "nav-inbox"]) {
    const n = $(id); if (n) n.classList.toggle("active", id === activeNav);
  }

  // topbar context title
  const titleEl = $("topbar-title");
  if (titleEl) {
    const titles = {
      inbox: "Inbox",
      graph: "Knowledge Graph",
      prompts: filterChip === "identity" ? "Identity"
             : filterChip === "skill" ? "Skills" : "Prompt Library",
    };
    titleEl.textContent = titles[which] || "Operator Console";
  }

  updateGraphDock();
  if (which === "prompts") { renderCompose(); $("search").focus(); }
  else $("compose").hidden = true;
}

// Keyboard-first finding: ↑/↓ move the selection, Enter copies it, "/" jumps to the
// search box — the whole library is reachable without the mouse. Editors and the
// reason box are never hijacked; ArrowDown from the search box steps into the list.
function moveSelection(delta) {
  const rows = [...$("prompt-list").querySelectorAll(".list-row")];
  if (!rows.length) return;
  let idx = rows.findIndex((r) => r.dataset.key === selectedKey);
  idx = idx < 0 ? (delta > 0 ? 0 : rows.length - 1) : idx + delta;
  idx = Math.max(0, Math.min(rows.length - 1, idx));
  selectPrompt(rows[idx].dataset.key);
  rows[idx].scrollIntoView({ block: "nearest" });
}

document.addEventListener("keydown", (e) => {
  // Global: Ctrl/Cmd+K focuses the search field from anywhere
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    const s = $("search"); if (s) { s.focus(); s.select(); }
    return;
  }
  // Prompt-library shortcuts only apply when that view is active
  if ($("view-prompts").hidden) return;
  const t = e.target;
  if (t && (t.tagName === "TEXTAREA" || (t.tagName === "INPUT" && t.id !== "search")))
    return;
  if (e.key === "ArrowDown") { e.preventDefault(); moveSelection(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveSelection(-1); }
  else if (e.key === "Enter" && selectedKey) {
    const p = PMAP.get(selectedKey);
    if (p) { e.preventDefault(); copyText(currentBody(p), p.name); pushRecent(p.key); }
  } else if (e.key === "/" && t.id !== "search") {
    e.preventDefault(); $("search").focus();
  }
});

// sidebar navigation
$("nav-inbox").onclick = () => showTab("inbox");
$("nav-graph").onclick = () => { showTab("graph"); if (graphSlug && !stagedData) loadStaged(graphSlug); };
$("nav-prompts").onclick = () => { filterChip = "all"; showTab("prompts"); renderChips(); renderList(); };
// global controls
$("graph-dock-propose").onclick = () => proposeGraphDraft();
$("graph-dock-discard").onclick = () => discardGraphDraft();
$("refresh").onclick = () => refresh().then(() => toast("Reloaded from disk."));
$("search").oninput = () => renderList();
$("compose-copy").onclick = () => copyText(composeOutput(), "composed prompt");
$("compose-clear").onclick = () => {
  compose = { items: [], text: null };
  store.set(LS.compose, compose);
  renderCompose();
  renderList();
};
$("compose-toggle").onclick = () => {
  const body = $("compose-body");
  body.hidden = !body.hidden;
  $("compose-toggle").textContent = body.hidden ? "▸" : "▾";
};
$("compose-rebuild").onclick = () => {
  compose.text = null;
  store.set(LS.compose, compose);
  renderCompose();
};

showTab("inbox");  // set initial active nav + title before data loads
refresh().catch((e) => toast(`Failed to load state: ${e}`, 6000));
