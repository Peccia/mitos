// Operator console client. One rule above all: candidate and registry text is
// untrusted — it only ever reaches the page through textContent, never innerHTML.
"use strict";

let STATE = null;

// ── client-persisted state (localStorage; private-mode safe) ──────────────────
const LS = {
  favorites: "oc.favorites", recents: "oc.recents", drafts: "oc.drafts",
  draftBase: "oc.draftBase", collapsed: "oc.collapsed", compose: "oc.compose",
  graphDrafts: "oc.graphDrafts", editorOrigin: "oc.editorOrigin",
  opsMachine: "oc.opsMachine",
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
// key -> the registry body the draft was FIRST made against (recorded once, at the
// no-draft → draft transition). A draft has no server-tracked base (console edits set
// base_hash: "" — see review.py), so this is the only way the client can tell "the
// registry moved under this unsaved draft" from "the user is still just editing" —
// compared directly against p.body since p.body is refetched live on every reload.
let draftBase = store.get(LS.draftBase, {});
// metaDrafts[key] -> { description?, version?, category?, targets? } — in-progress
// structured frontmatter edits from the metadata panel. Deliberately NOT persisted to
// localStorage (unlike body drafts): a stale metadata draft surviving a refresh could
// silently reapply an outdated targets list on the next Save — the failure mode the
// raw-YAML editing approach was rejected over. Cleared on Revert or on tab reload.
let metaDrafts = {};
// resourceDrafts[key] -> the FULL desired {relpath: text} set for a skill's supporting
// files (examples/*, scripts/*), or undefined when untouched. Same non-persistence
// rationale as metaDrafts: a stale resource draft surviving a refresh could silently
// delete files the operator meant to keep (the absent-vs-empty distinction the server
// enforces — see review.py's R4 design note). Cleared on Revert or on tab reload.
let resourceDrafts = {};
let collapsed = store.get(LS.collapsed, {});   // list group id -> true when collapsed
let compose = store.get(LS.compose, { items: [], text: null }); // items: keys; text: edited merge
let selectedKey = null;                        // the prompt shown in the detail pane
let filterChip = "all";                        // active list filter chip
let PROMPTS = [];                              // flat prompt list (rebuilt each render)
let PMAP = new Map();                          // key -> prompt
let graphSlug = null;                          // selected project in the Knowledge Graph tab
let graphProjFilter = "";                       // sidebar project-search text
let stagedData = null;   // { ok, slug, documents, staged_at } from /api/graph/staged
// Selection is per-pool — a checked doc in "Staged" must not vanish (or bleed into the
// count/add-list of) "Unassigned" when the operator toggles between them mid-review.
let stagedSel = { project: new Set(), unassigned: new Set() };
function curStagedSel() { return stagedSel[stagedPool]; }
let stagedFilter = "";     // client-side search text for the staged list
let stagedPool = "project"; // "project" | "unassigned" — which staged pool the toggle shows
let leftTab = "discovery"; // "discovery" | "recovery" — which pane the left column shows
let dismissedData = null; // { ok, slug, documents, is_unassigned } from /api/graph/dismissed
let recoverFilter = "";    // client-side search text for the recovery list
let openEditor = null;     // { where:"registry"|"staged", vals:{id,name,description,dateModified,keywords}, lockId }
let selectedCandidateId = null;  // which inbox candidate is shown in the detail pane
// graphDrafts[slug] = {
//   add:{id:doc}, edit:{id:doc}, remove:{id:{id,name}},
//   effortAdd:{id:effort}, effortEdit:{id:effort}, effortRemove:{id:{id,name}}
// } — local, persisted.
let graphDrafts = store.get(LS.graphDrafts, {});

// ── Skills tab state ──────────────────────────────────────────────────────────
let expandedSkillName = null;   // slug of the currently expanded skill row, or null
let skillFilterText = "";       // client-side search text
let skillFilterTarget = "";     // filter by target slug, "" = all
let skillFilterOrg = false;     // filter to only org-domain skills
let orgSkillViewMode = {};      // skill name -> "role" | "agentsmd" per-skill

// ── Ops (compile/deploy from the console) state ─────────────────────────────
let opsMachine = store.get(LS.opsMachine, null);  // last-selected deploy target, persisted
let opsPollTimer = null;                          // setInterval id while an op is running


const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

// Keyboard-focusable clickable row: role=button + tabindex so a plain <div onclick> row
// (the list rows here predate any keyboard-nav need) can be reached and activated
// without a pointer. Reuses whatever the row's own .onclick already does via row.click()
// rather than duplicating the activation logic.
function makeRowFocusable(row) {
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); row.click(); }
  });
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
  // orgData feeds both the Graph tab's effort editor and the Skills tab's org expansion.
  // Load eagerly on every refresh if not yet cached so the Skills tab doesn't need a
  // separate trigger; fall back to empty object so joins against it are always safe.
  if (!orgData) {
    try { orgData = await (await fetch("/api/org")).json(); }
    catch (e) { orgData = {}; }
    if (orgData && !orgDomain) orgDomain = Object.keys(orgData)[0] || null;
  }
  const rootEl = $("root");
  if (rootEl) { rootEl.textContent = STATE.root; rootEl.title = STATE.root; }
  const countEl = $("inbox-count");
  if (countEl) countEl.textContent = STATE.candidates.length || "";
  // An accepted graph candidate may have auto-dismissed a removed doc (see
  // _apply_graph_candidate) — refetch Recovery so it doesn't linger stale and let a
  // now-unmapped-but-still-dismissed doc reappear in Discovery until a full reload.
  if (graphSlug && dismissedData) loadDismissed(graphSlug);
  // render the panes independently — a fault in one must not blank the others
  safeRender($("view-inbox"), renderInbox);
  safeRender($("view-graph"), renderGraph);
  safeRender($("view-skills"), renderSkills);
  safeRender($("prompt-list"), renderPrompts);
  safeRender($("ops-bar"), renderOpsBar);
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

async function sendDecision(id, decision, reason, force) {
  try {
    const res = await fetch("/api/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, decision, reason, force: !!force }),
    });
    const out = await res.json();
    if (out.ok) {
      const routed = (out.changed || []).length
        ? ` → registry/${out.changed.join(", registry/")}` : "";
      toast(`${decision === "accept" ? "Accepted" : "Rejected"} ${id}${routed} — review git status, then commit.`, 4200);
      await refresh();
    } else if (out.stale) {
      // the server re-checked and refused too (the disabled button is only a hint,
      // not enforcement) — surface it exactly like any other rejection.
      toast(`Error: ${out.error}`, 5000);
      await refresh();
    } else {
      toast(`Error: ${out.error}`, 5000);
    }
  } catch (err) {
    console.error(err);
    toast(`Failed to send decision: ${err.message || err}`, 6000);
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
  makeRowFocusable(row);
  return row;
}

function candidateCard(c) {
  const card = el("article", "card");

  const head = el("div", "card-head");
  head.append(el("span", "badge kind", c.kind || "drift"));
  if (c.stale === true) head.append(el("span", "badge stale", "registry moved"));
  if (!c.acceptable) head.append(el("span", "badge manual", "manual"));
  if (c.kind !== "new" && c.accept_note.startsWith("new file"))
    head.append(el("span", "badge new", "new"));
  head.append(el("code", "", c.registry_path || c.deploy_path));
  const src = c.source || {};
  head.append(el("span", "muted", `${src.machine || "?"} / ${src.tool || "?"} · ${c.captured_at}`));
  card.append(head);

  if (c.note) card.append(el("div", "card-note muted", c.note));
  if (c.stale === true && c.acceptable) {
    const staleDiv = el("div", "accept-note warning-callout");
    staleDiv.append(el("div", "callout-title", "⚠️ Registry moved since this was captured"));
    const desc = el("div", "callout-body");
    desc.append(el("p", "", "The diff below is against the CURRENT registry file, so it "
      + "already reflects what accepting would overwrite. Confirm you've reviewed it "
      + "before forcing the accept through."));
    staleDiv.append(desc);
    card.append(staleDiv);
  }
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

  if (c.kind === "new") {
    card.append(el("div", "muted card-note", "New file — nothing to diff against; see the proposed text below."));
  } else {
    card.append(diffTable(c.diff));
  }

  const details = el("details", "payload");
  details.append(el("summary", "", "Proposed text (raw)"));
  details.append(el("pre", "", c.payload));
  card.append(details);

  const actions = el("div", "card-actions");
  const reason = el("input");
  reason.type = "text";
  reason.placeholder = "Reason (optional — logged to decisions.jsonl)";
  const isStale = c.stale === true && c.acceptable;
  const accept = el("button", "accept", isStale ? "Force accept" : "Accept");
  const reject = el("button", "reject", "Reject");
  reject.onclick = () => sendDecision(c.id, "reject", reason.value);
  const copy = el("button", "ghost", "Copy proposed");
  copy.onclick = () => copyText(c.payload, c.id);
  if (isStale) {
    // stale candidates start disabled — an explicit confirmation is required before
    // the (now-relabeled) button will fire the accept with force:true. This is a UX
    // hint only: the server re-checks staleness itself and refuses without force
    // regardless of what the client sends (review.decide()).
    accept.disabled = true;
    const confirmLabel = el("label", "force-confirm");
    const confirmBox = el("input");
    confirmBox.type = "checkbox";
    confirmBox.onchange = () => { accept.disabled = !confirmBox.checked; };
    confirmLabel.append(confirmBox,
      document.createTextNode(" I understand this reverts newer registry changes"));
    actions.append(confirmLabel);
    accept.onclick = () => sendDecision(c.id, "accept", reason.value, true);
  } else {
    accept.disabled = !c.acceptable;
    if (!c.acceptable) accept.title = c.accept_note;
    accept.onclick = () => sendDecision(c.id, "accept", reason.value, false);
  }
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
    // no selection clear here — a refetch of the same pool (e.g. after an accept) must
    // not wipe the operator's in-progress checklist (FM3).
    renderGraph();
  } catch (e) {
    // fail silently — discovery pane shows the "run mitos connect --stage" hint
  }
}

// Recovery list mirrors the same Staged/Unassigned pool the Discovery toggle shows —
// a dismissal always lands beside whichever staging file surfaced the document.
async function loadDismissed(slug) {
  try {
    const r = await fetch("/api/graph/dismissed?slug=" + encodeURIComponent(slug)
      + (stagedPool === "unassigned" ? "&pool=unassigned" : ""));
    dismissedData = await r.json();
    renderGraph();
  } catch (e) {
    // fail silently — recovery pane shows an empty state
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
    makeRowFocusable(row);
    list.append(row);
  }
}

function selectProject(slug) {
  if (slug === graphSlug) return;
  graphSlug = slug;
  stagedData = null; stagedSel = { project: new Set(), unassigned: new Set() };
  stagedFilter = ""; stagedPool = "project";
  dismissedData = null; recoverFilter = ""; leftTab = "discovery";
  openEditor = null;
  renderGraph();
  loadStaged(slug);
  loadDismissed(slug);
}

// ── right: workspace = Discovery/Recovery tabs (left) | Registry pane (right) ──
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
  buildLeftPane(discovery, g);
  buildRegistryPane(registry, g);
  return ws;
}

// Left column is tabbed: Discovery (staged docs not yet mapped) and Recovery (docs
// dismissed from Discovery, or auto-dismissed when removed from the registry).
function buildLeftPane(container, g) {
  const tabs = el("div", "left-pane-tabs");
  for (const [val, label] of [["discovery", "Discovery"], ["recovery", "Recovery"]]) {
    const b = el("button", "left-tab" + (leftTab === val ? " active" : ""), label);
    b.onclick = () => {
      if (leftTab === val) return;
      leftTab = val;
      renderGraph();
      if (val === "recovery" && (!dismissedData || dismissedData.slug !== g.slug)) loadDismissed(g.slug);
    };
    tabs.append(b);
  }
  container.append(tabs);
  if (leftTab === "recovery") buildRecoveryPane(container, g);
  else buildDiscoveryPane(container, g);
}

// Documents in the staged pool that aren't already mapped into the project graph or
// dismissed into Recovery, plus the subset matching the current filter. Recomputed
// cheaply on each targeted update.
function stagedVisible(g) {
  const mappedIds = new Set((g.documents || []).map((d) => d.id));
  // The shared unassigned pool is drawn from across all projects, so a document already
  // mapped to ANY project (not just the selected one) is spoken for and must not reappear
  // here. Per-project staging keeps the narrower selected-project-only exclusion.
  if (stagedData && stagedData.is_unassigned) {
    ((STATE && STATE.graphs) || []).forEach((gr) =>
      (gr.documents || []).forEach((d) => mappedIds.add(d.id)));
  }
  const dismissedIds = new Set(
    ((dismissedData && dismissedData.slug === g.slug && dismissedData.documents) || [])
      .map((d) => d.id));
  const all = (stagedData.documents || [])
    .filter((d) => !mappedIds.has(d.id) && !dismissedIds.has(d.id));
  const q = stagedFilter.trim().toLowerCase();
  const filtered = q
    ? all.filter((d) => (d.name + " " + (d.description || "")).toLowerCase().includes(q))
    : all;
  return { all, filtered };
}

function buildDiscoveryPane(container, g) {
  const head = el("div", "pane-head");
  const toggle = el("div", "pool-toggle");
  for (const [val, label] of [["project", "Staged"], ["unassigned", "Unassigned"]]) {
    const b = el("button", "pool-opt" + (stagedPool === val ? " active" : ""), label);
    b.onclick = () => {
      if (stagedPool === val) return;
      // selection is per-pool (stagedSel[val]) — switching pools must not touch it
      stagedPool = val; stagedData = null; stagedFilter = ""; dismissedData = null;
      loadStaged(g.slug);
      loadDismissed(g.slug);
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
      if (!pending.has(doc.id) && !d.add[doc.id]) curStagedSel().add(doc.id);
    });
    renderStagedRows(g);
  };
  const clr = el("button", "ghost tiny", "Clear");
  clr.onclick = () => { curStagedSel().clear(); renderStagedRows(g); };
  const add = el("button", "accept tiny staged-add");
  add.onclick = () => addSelectedStaged(g);
  const dismissSel = el("button", "ghost tiny danger", "Dismiss selected");
  dismissSel.title = "Move the selected documents to Recovery so they stop showing up here";
  dismissSel.onclick = () => {
    const picked = (stagedData && stagedData.documents || []).filter((d) => curStagedSel().has(d.id));
    if (!picked.length) { toast("Tick at least one document."); return; }
    dismissStaged(g, picked);
  };
  sbar.append(search, info, selAll, clr, add, dismissSel);
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
  for (const id of [...curStagedSel()]) if (pending.has(id) || draft.add[id]) curStagedSel().delete(id);
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
      cb.checked = curStagedSel().has(d.id); cb.disabled = isPending || inDraft;
      cb.onchange = () => {
        if (cb.checked) curStagedSel().add(d.id); else curStagedSel().delete(d.id);
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
        const dismiss = el("button", "ghost tiny danger", "Dismiss");
        dismiss.title = "Move to Recovery — won't reappear here until restored";
        dismiss.onclick = () => dismissStaged(g, [d]);
        actions.append(map, tweak, dismiss);
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
    info.textContent = `${all.length} staged · ${curStagedSel().size} selected`
      + (stagedData.staged_at ? ` · ${stagedData.staged_at}` : "");
  }
  if (add) {
    add.textContent = `Add selected (${curStagedSel().size})`;
    add.disabled = curStagedSel().size === 0;
  }
}

function addSelectedStaged(g) {
  // stagedData is always the CURRENT pool's fetch, so filtering it against the current
  // pool's selection is correct here — cross-pool selections stay in their own set and
  // are never visible (or addable) while the other pool is showing.
  const picked = (stagedData && stagedData.documents || []).filter((d) => curStagedSel().has(d.id));
  if (!picked.length) { toast("Tick at least one document."); return; }
  for (const d of picked) draftUpsert(g.slug, stagedDoc(d), true);
  curStagedSel().clear();
  toast(`Added ${picked.length} to the draft — review in the dock, then Propose.`);
  renderGraph();
}

// Moves one or more staged docs to Recovery — a manual dismissal (as opposed to the
// server's auto-dismissal of docs dropped by an accepted removal).
async function dismissStaged(g, docs) {
  if (!docs.length) return;
  try {
    const r = await fetch("/api/graph/dismiss", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: g.slug, documents: docs,
        pool: stagedPool === "unassigned" ? "unassigned" : "",
      }),
    });
    const out = await r.json();
    if (!out.ok) { toast(out.error || "Dismiss failed."); return; }
    for (const d of docs) curStagedSel().delete(d.id);
    dismissedData = null;
    toast(`Dismissed ${docs.length} — find ${docs.length === 1 ? "it" : "them"} in Recovery.`);
    loadDismissed(g.slug);
  } catch (e) {
    toast("Dismiss failed — server unreachable.");
  }
}

// ── left pane (Recovery tab): docs dismissed from Discovery or dropped by a removal ──
function buildRecoveryPane(container, g) {
  const head = el("div", "pane-head");
  const search = el("input", "staged-search");
  search.type = "search"; search.placeholder = "Filter recovered…"; search.value = recoverFilter;
  search.oninput = () => { recoverFilter = search.value; renderRecoveryRows(g); };
  head.append(search);
  container.append(head);
  container.append(el("div", "recover-rows"));
  setTimeout(() => renderRecoveryRows(g), 0);
}

function renderRecoveryRows(g) {
  const rows = document.querySelector("#graph-workspace .recover-rows");
  if (!rows) return;
  rows.replaceChildren();
  if (!dismissedData || !dismissedData.ok || dismissedData.slug !== g.slug) {
    rows.append(el("div", "muted pane-hint", "Nothing recovered yet."));
    return;
  }
  const all = dismissedData.documents || [];
  const q = recoverFilter.trim().toLowerCase();
  const visible = q ? all.filter((d) => (d.name || "").toLowerCase().includes(q)) : all;
  if (all.length === 0) {
    rows.append(el("div", "muted",
      "Nothing dismissed, and nothing removed from this project yet."));
    return;
  }
  if (visible.length === 0) {
    rows.append(el("div", "muted", "No matches for current filter."));
    return;
  }
  for (const d of visible) {
    const row = el("div", "staged-row");
    const body = el("div", "staged-body");
    const nameLine = el("div", "staged-nameline");
    nameLine.append(el("span", "staged-name", d.name || d.id));
    const isRemoval = d.source === "removal";
    nameLine.append(el("span", "badge " + (isRemoval ? "removed" : "dismissed"),
      isRemoval ? "Removed" : "Dismissed"));
    body.append(nameLine);
    const meta = el("div", "staged-meta");
    if (d.dismissed_at) meta.append(el("span", "muted staged-mod", d.dismissed_at));
    const actions = el("span", "row-actions");
    const restore = el("button", "ghost tiny", "Restore");
    restore.title = "Move back to Discovery so it can be mapped again";
    restore.onclick = () => restoreDoc(g, d.id);
    actions.append(restore);
    meta.append(actions);
    if (d.webUrl) {
      const a = el("a", "staged-link", "Open");
      a.target = "_blank"; a.rel = "noopener";
      a.href = d.webUrl;
      meta.append(a);
    }
    body.append(meta);
    row.append(body);
    rows.append(row);
  }
}

async function restoreDoc(g, id) {
  try {
    const r = await fetch("/api/graph/restore", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: g.slug, ids: [id],
        pool: stagedPool === "unassigned" ? "unassigned" : "",
      }),
    });
    const out = await r.json();
    if (!out.ok) { toast(out.error || "Restore failed."); return; }
    dismissedData = null;
    toast("Restored — back in Discovery.");
    loadDismissed(g.slug);
  } catch (e) {
    toast("Restore failed — server unreachable.");
  }
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
    if (effort.orgDomain) {
      nameSpan.append(el("span", "effort-domain-tag", " · org: " + effort.orgDomain));
    }
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
                       vals: { id: effort.id, name: effort.name, description: effort.description || "",
                               orgDomain: effort.orgDomain || "" } };
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
  bindEnterToApply(inputs, apply);
  scrollCardIntoView(card);
  return card;
}

// The card isn't in the DOM yet when built — the caller appends it synchronously right
// after this returns, so a 0ms timeout runs just after that append lands. Softens the
// layout shift an in-place row-replacement editor causes (no reachability hunt after).
function scrollCardIntoView(card) {
  setTimeout(() => card.scrollIntoView({ block: "nearest", behavior: "smooth" }), 0);
}

// Enter in a single-line field editor submits the card's non-destructive Apply action —
// never a registry write, so binding the most reflexive keystroke here is safe (contrast
// the inbox Reason field, which deliberately does NOT bind Enter to Accept).
function bindEnterToApply(inputs, apply) {
  for (const inp of Object.values(inputs)) {
    if (!inp || inp.tagName === "SELECT") continue;
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); apply.click(); }
    });
  }
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

  // Org domain — the routing tag: work in this effort loads the matching org-* skill.
  // Optional; untagged efforts route by the nature of the request. Domains come from
  // the same dynamic discovery the Org tab uses (skills with org_domain frontmatter).
  const domWrap = el("div", "graph-field");
  domWrap.append(el("label", "", "Org domain"));
  const domSel = el("select", "graph-select");
  const noDom = el("option", "", "(none — route by request)"); noDom.value = "";
  domSel.append(noDom);
  for (const dom of Object.keys(orgData || {}).sort()) {
    const opt = el("option", "", dom); opt.value = dom;
    domSel.append(opt);
  }
  // Round-trip safety: an existing tag whose domain skill has since been removed must
  // survive an unrelated edit rather than being silently wiped.
  if (vals.orgDomain && !(orgData || {})[vals.orgDomain]) {
    const opt = el("option", "", vals.orgDomain + " (unknown domain)");
    opt.value = vals.orgDomain;
    domSel.append(opt);
  }
  domSel.value = vals.orgDomain || "";
  domWrap.append(domSel); card.append(domWrap); inputs.orgDomain = domSel;

  inputs.name.focus();

  const actions = el("div", "inline-actions");
  const apply = el("button", "accept tiny", "Apply");
  apply.onclick = () => {
    const effort = { id: inputs.id.value.trim().toLowerCase(),
                     name: inputs.name.value.trim(),
                     description: inputs.description.value.trim(),
                     orgDomain: inputs.orgDomain.value };
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
  bindEnterToApply(inputs, apply);
  scrollCardIntoView(card);
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
  const total = c.adds + c.edits + c.removes + (c.effortAdds || 0) + (c.effortEdits || 0)
    + (c.effortRemoves || 0);
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

async function proposeGraphDraft(slug = graphSlug, reason = null, autoAccept = false) {
  if (!slug) return;
  const d = draftFor(slug);
  const documents = [...Object.values(d.add), ...Object.values(d.edit)].map((x) => ({
    id: x.id, name: x.name, description: x.description || "",
    dateModified: x.dateModified, keywords: x.keywords || "", parentId: x.parentId || "" }));
  const removals = Object.keys(d.remove);
  const efforts = [...Object.values(d.effortAdd), ...Object.values(d.effortEdit)].map((x) => ({
    id: x.id, name: x.name, description: x.description || "",
    orgDomain: x.orgDomain || "" }));
  const effortRemovals = Object.keys(d.effortRemove);
  if (!documents.length && !removals.length && !efforts.length && !effortRemovals.length) {
    toast("No changes to propose."); return;
  }
  const reasonText = reason != null ? reason
    : (($("graph-dock-reason") && $("graph-dock-reason").value.trim()) || "");
  try {
    const res = await fetch("/api/graph", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, documents, removals, efforts, effortRemovals,
                            reason: reasonText }),
    });
    const out = await res.json();
    if (!out.ok) { toast(`Error: ${out.error}`, 5000); return; }
    draftClear(slug);
    if ($("graph-dock-reason")) $("graph-dock-reason").value = "";
    if (!autoAccept) {
      toast(`Proposed → inbox/${out.id}. Review and Accept in the Inbox tab.`, 5000);
      await refresh();
      return;
    }
    // Chain straight to accept — same server-side validation and decisions.jsonl entry
    // as a manual Inbox accept (decide() below), just without the tab hop. Nothing here
    // writes registry/ directly (invariant #3 still holds — propose, then decide, same
    // as a human clicking both buttons in sequence).
    const acc = await fetch("/api/decide", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: out.id, decision: "accept", reason: reasonText }),
    });
    const accOut = await acc.json();
    if (accOut.ok) {
      const routed = (accOut.changed || []).length
        ? ` → registry/${accOut.changed.join(", registry/")}` : "";
      toast(`Proposed and accepted${routed} — review git status, then commit.`, 4200);
    } else {
      // propose succeeded but accept failed (validation, staleness, etc.) — the
      // candidate stays in the inbox exactly like a normal failed accept; nothing lost.
      toast(`Proposed → inbox/${out.id}, but accept failed: ${accOut.error}. `
        + `Review it in the Inbox tab.`, 6500);
    }
    await refresh();
  } catch (err) {
    console.error(err);
    toast(`Failed to propose changes: ${err.message || err}`, 6000);
  }
}

function discardGraphDraft(slug = graphSlug, after = renderGraph) {
  if (!slug || !draftTotal(slug)) return;
  draftClear(slug);
  openEditor = null;
  toast("Draft discarded.");
  after();
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
      fm: s.frontmatter || {}, resources: s.resources || {},
      group: `skill:${s.category}`,
      groupLabel: catLabels[s.category] || s.category.replace(/^./, (c) => c.toUpperCase()),
      search: `${s.name} ${s.description || ""} ${s.body}`.toLowerCase(),
      favorited: !!s.favorited,
    });
  }
  for (const p of STATE.prompts.prompts) {
    out.push({
      key: `prompt:${p.name}`, kind: "prompt", ident: p.name, name: p.name, label: p.name,
      desc: p.description || "", catName: p.category,
      meta: p.description || "", targets: p.targets || [], body: p.body,
      fm: p.frontmatter || {},
      group: `prompt:${p.category}`,
      groupLabel: catLabels[p.category] || p.category.replace(/^./, (c) => c.toUpperCase()),
      search: `${p.name} ${p.description || ""} ${p.body}`.toLowerCase(),
      favorited: !!p.favorited,
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

// skill groups first (departments before the rest), then prompts, then
// identity/context/projects partials — the same ordering the old flat list used,
// with first-class prompts slotted in between skills and partials.
function groupOrder(gid) {
  if (gid.startsWith("skill:")) {
    const cat = gid.slice(6);
    return [0, cat === "departments" ? 0 : 1, cat];
  }
  if (gid.startsWith("prompt:")) return [1, 0, gid.slice(7)];
  const rank = { identity: 1, context: 2, projects: 3 }[gid.slice(8)] ?? 9;
  return [2, rank, gid];
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
  seedServerFavorites();       // pick up pins made from another session/device
  renderChips();
  renderList();
  renderDetail();
  renderCompose();
}

// prompt_index() only tracks .favorited on skills/prompts (registry/local/prompt-
// favorites.yaml has no per-partial entries), so this is a one-way, additive merge —
// it never removes a local pin, only adds ones the server knows about that this
// session hasn't seen yet. A real unfavorite always goes through toggleFavorite(),
// which tells the server directly.
function seedServerFavorites() {
  let changed = false;
  for (const p of PROMPTS) {
    if (p.favorited && !favorites.includes(p.key)) { favorites.push(p.key); changed = true; }
  }
  if (changed) store.set(LS.favorites, favorites);
}

function pruneKeys() {
  favorites = favorites.filter((k) => PMAP.has(k));
  recents = recents.filter((k) => PMAP.has(k));
  compose.items = compose.items.filter((k) => PMAP.has(k));
  for (const k of Object.keys(drafts)) if (!PMAP.has(k)) delete drafts[k];
  for (const k of Object.keys(draftBase)) if (!PMAP.has(k)) delete draftBase[k];
  if (selectedKey && !PMAP.has(selectedKey)) selectedKey = null;
}

// ── left pane: filterable, collapsible, with Favorites + Recent pinned on top ──
// Chips reflect the categories actually present in PROMPTS, not an invented tab list —
// skills and prompts stay coarse ("Skills" / "Prompts"), partials keep their existing
// per-group chips (identity/context/projects) since that grouping is more useful there.
const _partialLabels = { identity: "Identity", context: "Context", projects: "Projects" };

function renderChips() {
  const box = $("filter-chips");
  box.replaceChildren();
  const chips = [["all", "All"]];
  if (PROMPTS.some((p) => p.kind === "skill")) chips.push(["skill", "Skills"]);
  if (PROMPTS.some((p) => p.kind === "prompt")) chips.push(["prompt", "Prompts"]);
  const partialCats = [...new Set(PROMPTS.filter((p) => p.kind === "partial").map((p) => p.catName))];
  for (const cat of partialCats) chips.push([cat, _partialLabels[cat] || cat]);
  for (const [id, label] of chips) {
    const c = el("button", "chip" + (filterChip === id ? " active" : ""), label);
    c.onclick = () => { filterChip = id; renderChips(); renderList(); };
    box.append(c);
  }
}

function chipAllows(p) {
  if (filterChip === "all") return true;
  if (filterChip === "skill") return p.kind === "skill";
  if (filterChip === "prompt") return p.kind === "prompt";
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

let favManageMode = false;      // Favorites section: "Manage" mode (checkboxes, no drag)
let favSelection = new Set();   // keys checked while in manage mode

function appendSection(list, gid, label, items) {
  const isCollapsed = !!collapsed[gid];
  const isFav = gid === "_fav";
  const header = el("div", "list-group");
  header.append(el("span", "caret", isCollapsed ? "▸" : "▾"),
                el("span", "list-group-label", label),
                el("span", "list-count", String(items.length)));
  if (isFav && items.length) {
    const manageBtn = el("button", "chip tiny fav-manage-btn", favManageMode ? "Done" : "Manage");
    manageBtn.onclick = (e) => {
      e.stopPropagation();
      favManageMode = !favManageMode;
      if (!favManageMode) favSelection.clear();
      renderList();
    };
    header.append(manageBtn);
  }
  header.onclick = () => {
    collapsed[gid] = !isCollapsed;
    store.set(LS.collapsed, collapsed);
    renderList();
  };
  list.append(header);
  if (isCollapsed) return;
  if (isFav && favManageMode && items.length) {
    const bar = el("div", "fav-manage-bar");
    const unpinBtn = el("button", "chip tiny", `Unpin selected (${favSelection.size})`);
    unpinBtn.disabled = favSelection.size === 0;
    unpinBtn.onclick = () => {
      for (const key of favSelection) toggleFavorite(key);
      favSelection.clear();
      renderList();
    };
    bar.append(unpinBtn);
    list.append(bar);
  }
  for (const p of items) list.append(listRow(p, isFav));
}

function listRow(p, isFavSection = false) {
  const row = el("div", "list-row" + (p.key === selectedKey ? " active" : ""));
  row.dataset.key = p.key;
  const pinned = favorites.includes(p.key);
  const manageActive = isFavSection && favManageMode;

  if (manageActive) {
    const cb = el("input");
    cb.type = "checkbox";
    cb.className = "fav-select-cb";
    cb.checked = favSelection.has(p.key);
    cb.onclick = (e) => e.stopPropagation();
    cb.onchange = () => {
      if (cb.checked) favSelection.add(p.key); else favSelection.delete(p.key);
      renderList();
    };
    row.append(cb);
  } else {
    const star = el("button", "row-star" + (pinned ? " on" : ""), pinned ? "★" : "☆");
    star.title = pinned ? "Unpin from Favorites" : "Pin to Favorites";
    star.onclick = (e) => { e.stopPropagation(); toggleFavorite(p.key); };
    row.append(star);
  }

  // line 1 is the name — it owns the row width and is never out-competed; state tags
  // ride along on the right. The description, when present, drops to a muted line 2
  // clamped to one line, with the full text in the tooltip and the detail pane.
  const col = el("div", "row-col");
  const line1 = el("div", "row-line1");
  const name = el("span", "row-name", p.label);
  name.title = p.name;
  line1.append(name);
  if (drafts[p.key] != null) {
    line1.append(el("span", "row-tag edited", "edited"));
    if (draftBase[p.key] != null && draftBase[p.key] !== p.body) {
      const tag = el("span", "row-tag stale", "base moved");
      tag.title = "The registry file changed since this draft was started — review "
        + "before saving, the old base is no longer what Save to Inbox would diff against.";
      line1.append(tag);
    }
  }
  if (compose.items.includes(p.key)) line1.append(el("span", "row-tag", "compose"));
  col.append(line1);
  if (p.desc) {
    const desc = el("span", "row-desc", p.desc);
    desc.title = p.desc;
    col.append(desc);
  }

  row.append(col);

  if (isFavSection && !favManageMode) {
    // Native HTML5 drag-and-drop reorders `favorites` in place — no library needed.
    row.draggable = true;
    row.ondragstart = (e) => {
      e.dataTransfer.setData("text/plain", p.key);
      row.classList.add("dragging");
    };
    row.ondragend = () => row.classList.remove("dragging");
    row.ondragover = (e) => { e.preventDefault(); row.classList.add("drag-over"); };
    row.ondragleave = () => row.classList.remove("drag-over");
    row.ondrop = (e) => {
      e.preventDefault();
      row.classList.remove("drag-over");
      const draggedKey = e.dataTransfer.getData("text/plain");
      if (!draggedKey || draggedKey === p.key) return;
      const from = favorites.indexOf(draggedKey);
      const to = favorites.indexOf(p.key);
      if (from < 0 || to < 0) return;
      favorites.splice(from, 1);
      favorites.splice(to, 0, draggedKey);
      store.set(LS.favorites, favorites);
      renderList();
    };
  }

  row.onclick = manageActive ? undefined : () => selectPrompt(p.key);
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

// ── Contextual Return Bar: lets a "jump to edit" flow (e.g. Skills card → Edit Base
// Prompt) return to where it came from. Persisted so a refresh doesn't lose it;
// re-verified against live STATE at render time so it never restores against a
// deleted/renamed origin (accept/deploy/sync can remove the thing we'd return to) —
// no hashing or timestamps needed, an existence recheck is enough.
let editorOrigin = store.get(LS.editorOrigin, null);   // {tab, key, scrollY} | null

function openContextualEditor({ kind, ident, returnTab, returnExtra }) {
  if (returnTab) {
    editorOrigin = { tab: returnTab, key: `${kind}:${ident}`, scrollY: window.scrollY,
                     ...(returnExtra || {}) };
    store.set(LS.editorOrigin, editorOrigin);
  }
  filterChip = "all";
  showTab("prompts");
  renderChips();
  renderList();
  selectPrompt(`${kind}:${ident}`);
}

function originStillValid() {
  if (!editorOrigin) return false;
  const sep = editorOrigin.key.indexOf(":");
  const kind = editorOrigin.key.slice(0, sep), ident = editorOrigin.key.slice(sep + 1);
  if (kind === "skill") return (STATE?.prompts?.skills || []).some((s) => s.name === ident);
  if (kind === "prompt") return (STATE?.prompts?.prompts || []).some((p) => p.name === ident);
  return false;
}

function renderReturnBar(box, key) {
  if (!editorOrigin || editorOrigin.key !== key) return;
  if (!originStillValid()) { editorOrigin = null; store.set(LS.editorOrigin, null); return; }
  const label = editorOrigin.tab.charAt(0).toUpperCase() + editorOrigin.tab.slice(1);
  const bar = el("div", "return-bar", `← Return to ${label}`);
  bar.onclick = () => {
    const { tab, scrollY } = editorOrigin;
    editorOrigin = null;
    store.set(LS.editorOrigin, null);
    showTab(tab);
    window.scrollTo(0, scrollY || 0);
  };
  box.append(bar);
}

// ── Contextual Editor: the shared textarea+gutter+toolbar+preview editing surface,
// used by the Prompt Library detail pane (below) and the Skills tab's skill editor.
// A caller owns everything around it — header, status text, action row — since those
// differ per context (Save-to-inbox/Revert here, Save-as-new-skill/Cancel there); this
// only owns the editing surface itself.
//
// opts: { value: string, onInput(newValue), statusText(value) -> string }
// returns: { root, textarea, refreshStatus() }
function buildContextualEditor(opts) {
  const root = el("div", "ce-root");
  const ta = el("textarea");
  ta.spellcheck = false;
  ta.value = opts.value;

  // ── markdown toolbar: wraps the selection (or inserts at the cursor) — plain
  // textarea selection splicing, no editor library needed. ──────────────────────
  function wrapSelection(before, after) {
    const start = ta.selectionStart, end = ta.selectionEnd;
    const sel = ta.value.slice(start, end);
    ta.value = ta.value.slice(0, start) + before + sel + after + ta.value.slice(end);
    ta.selectionStart = start + before.length;
    ta.selectionEnd = start + before.length + sel.length;
    ta.dispatchEvent(new Event("input"));
    ta.focus();
  }
  function prefixLines(prefix) {
    const start = ta.selectionStart, end = ta.selectionEnd;
    const lineStart = ta.value.lastIndexOf("\n", start - 1) + 1;
    let lineEnd = ta.value.indexOf("\n", end);
    if (lineEnd < 0) lineEnd = ta.value.length;
    const block = ta.value.slice(lineStart, lineEnd);
    const prefixed = block.split("\n").map((l) => prefix + l).join("\n");
    ta.value = ta.value.slice(0, lineStart) + prefixed + ta.value.slice(lineEnd);
    ta.selectionStart = lineStart;
    ta.selectionEnd = lineStart + prefixed.length;
    ta.dispatchEvent(new Event("input"));
    ta.focus();
  }
  const toolbar = el("div", "editor-toolbar");
  const tbtn = (icon, title, action) => {
    const b = el("button", "tiny ghost icon-btn", icon);
    b.type = "button";
    b.title = title;
    b.setAttribute("aria-label", title);
    b.onclick = (e) => { e.preventDefault(); action(); };
    return b;
  };
  toolbar.append(
    tbtn("B", "Bold", () => wrapSelection("**", "**")),
    tbtn("I", "Italic", () => wrapSelection("_", "_")),
    tbtn("</>", "Inline code", () => wrapSelection("`", "`")),
    tbtn("🔗", "Link", () => wrapSelection("[", "](url)")),
    tbtn("H", "Heading", () => prefixLines("## ")),
    tbtn("≡", "Bulleted list", () => prefixLines("- ")),
    el("span", "toolbar-divider"),
  );
  const previewToggle = el("button", "tiny ghost", "Preview");
  previewToggle.type = "button";
  toolbar.append(previewToggle);

  const editorWrap = el("div", "editor-wrap");
  const gutter = el("div", "line-nums");
  const preview = el("div", "md-preview");
  preview.hidden = true;

  function syncGutter() {
    const n = ta.value === "" ? 1 : ta.value.split("\n").length;
    gutter.textContent = Array.from({length: n}, (_, i) => i + 1).join("\n");
    gutter.scrollTop = ta.scrollTop;
  }

  // The one deliberate, narrowly-scoped exception to this file's "textContent only,
  // never innerHTML" rule (see the header comment) — a sanitized markdown preview.
  // window.snarkdown's output ALWAYS passes through window.DOMPurify.sanitize()
  // before touching the DOM; never used for candidate/registry raw text elsewhere.
  function updatePreview() {
    if (preview.hidden) return;
    const html = window.snarkdown ? window.snarkdown(ta.value) : "";
    preview.innerHTML = window.DOMPurify ? window.DOMPurify.sanitize(html) : "";
  }

  previewToggle.onclick = () => {
    preview.hidden = !preview.hidden;
    previewToggle.classList.toggle("active", !preview.hidden);
    editorWrap.classList.toggle("with-preview", !preview.hidden);
    updatePreview();
  };

  function refreshStatus() {
    let cursor = "";
    if (document.activeElement === ta) {
      const before = ta.value.slice(0, ta.selectionStart);
      const ln = before.split("\n");
      cursor = ` · Ln ${ln.length}, Col ${ln[ln.length - 1].length + 1}`;
    }
    status.textContent = opts.statusText(ta.value) + cursor;
    status.classList.toggle("modified", !!(opts.isModified && opts.isModified()));
  }

  ta.oninput = () => {
    syncGutter();
    updatePreview();
    opts.onInput(ta.value);
    refreshStatus();
  };
  ta.addEventListener("scroll", () => { gutter.scrollTop = ta.scrollTop; });
  ta.addEventListener("click", refreshStatus);
  ta.addEventListener("keyup", refreshStatus);
  ta.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const start = ta.selectionStart, end = ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + "  " + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + 2;
    ta.dispatchEvent(new Event("input"));
  });

  editorWrap.append(gutter, ta, preview);
  syncGutter();
  const status = el("div", "detail-status muted");
  root.append(toolbar, editorWrap, status);
  refreshStatus();

  return { root, textarea: ta, refreshStatus };
}

// ── extends_skill/extends_role selects — parsed client-side from each candidate
// parent skill's raw body (mirrors review.py's _ORG_ROLE_HEADING_RE parsing) so the
// dropdown works without depending on orgData, which only covers org_domain skills and
// may not be fetched yet when a skill is opened from the Prompt Library. ────────────
const EXT_ROLE_HEADING_RE = /^###\s+(.+?)\s+—\s+.+$/;

function extendableSkills() {
  return (STATE.prompts.skills || []).filter((s) =>
    !s.extends_skill && s.body.includes("## Extended C-suite Roles"));
}

function getRolesForSkill(skillName) {
  const skill = (STATE.prompts.skills || []).find((s) => s.name === skillName);
  if (!skill) return [];
  const roles = [];
  let inExtended = false;
  for (const raw of skill.body.split("\n")) {
    const line = raw.trim();
    if (!inExtended) {
      if (line === "## Extended C-suite Roles") inExtended = true;
      continue;
    }
    if (line.startsWith("## ") && !line.startsWith("### ")) break;
    const m = line.match(EXT_ROLE_HEADING_RE);
    if (m) roles.push(m[1].trim());
  }
  return roles;
}

// Builds the linked extends_skill/extends_role <select> pair. `onChange(skillVal,
// roleVal)` fires after any user change (including the automatic role reset when the
// parent skill changes) — callers use it to persist drafts or refresh dependent UI
// (e.g. the New Skill form's target checkboxes). Preselects `currentSkill`/`currentRole`
// even if they no longer resolve (stale registry state), injecting them as an extra
// option rather than silently discarding the saved value.
function buildExtensionSelects(currentSkill, currentRole, onChange) {
  const skillSelect = document.createElement("select");
  skillSelect.className = "graph-select";
  const roleSelect = document.createElement("select");
  roleSelect.className = "graph-select";

  function populateSkillOptions() {
    skillSelect.replaceChildren();
    skillSelect.append(new Option("— none (regular skill) —", ""));
    const eligible = extendableSkills();
    for (const s of eligible) skillSelect.append(new Option(s.name, s.name));
    if (currentSkill && !eligible.some((s) => s.name === currentSkill)) {
      skillSelect.append(new Option(`${currentSkill} (saved value, not currently extendable)`, currentSkill));
    }
    skillSelect.value = currentSkill || "";
  }

  function populateRoleOptions(wantRole) {
    roleSelect.replaceChildren();
    const parent = skillSelect.value;
    if (!parent) {
      roleSelect.append(new Option("— select a skill first —", ""));
      roleSelect.disabled = true;
      return;
    }
    roleSelect.disabled = false;
    const roles = getRolesForSkill(parent);
    roleSelect.append(new Option("— none —", ""));
    for (const r of roles) roleSelect.append(new Option(r, r));
    if (wantRole && !roles.includes(wantRole)) {
      roleSelect.append(new Option(`${wantRole} (saved value, not found in parent body)`, wantRole));
    }
    roleSelect.value = wantRole || "";
  }

  populateSkillOptions();
  populateRoleOptions(currentRole);

  skillSelect.onchange = () => {
    populateRoleOptions("");
    if (onChange) onChange(skillSelect.value, roleSelect.value);
  };
  roleSelect.onchange = () => {
    if (onChange) onChange(skillSelect.value, roleSelect.value);
  };

  return { skillSelect, roleSelect };
}

function fieldWrap(label, node) {
  const f = el("div", "graph-field");
  f.append(el("label", "", label));
  f.append(node);
  return f;
}

// ── metadata panel: structured frontmatter fields for skills/prompts — no raw YAML
// ever reaches the operator. Server (propose_meta_edit) reassembles the frontmatter
// from these fields; partials carry none of this (body-only, as before). ────────────
function metaCurrent(p) {
  return { ...(p.fm || {}), ...(metaDrafts[p.key] || {}) };
}

function metaModified(p) {
  const d = metaDrafts[p.key];
  return !!d && Object.keys(d).length > 0;
}

function buildMetaPanel(p) {
  if (p.kind === "partial") return null;   // partials have no editable frontmatter
  const wrap = el("div", "meta-panel");
  const current = metaCurrent(p);

  const setField = (key, val) => {
    metaDrafts[p.key] = metaDrafts[p.key] || {};
    metaDrafts[p.key][key] = val;
  };

  const textField = (key, label, ph) => {
    const f = el("div", "graph-field");
    f.append(el("label", "", label));
    const inp = el("input");
    inp.type = "text";
    inp.value = current[key] || "";
    if (ph) inp.placeholder = ph;
    inp.oninput = () => { setField(key, inp.value); refreshStatusBadge(); };
    f.append(inp);
    return f;
  };

  // full-width — the auto-fit meta-grid squeezed this to a narrow column
  wrap.append(textField("description", "Description"));

  const grid = el("div", "meta-grid");
  grid.append(textField("version", "Version", "1.0.0"));
  grid.append(textField("category", "Category", "general"));
  wrap.append(grid);
  // extends_skill/extends_role live in the Skills & Orgs tab (renderSkillExtensionSection)
  // — not here, to avoid the same two-tabs-edit-the-same-thing problem Supporting Files had.

  const targetsWrap = el("div", "graph-field");
  targetsWrap.append(el("label", "", "Targets"));
  const targetsRow = el("div", "target-checks");
  const currentTargets = new Set(current.targets || []);
  for (const t of (STATE.known_targets || [])) {
    const label = el("label", "target-check");
    const cb = el("input");
    cb.type = "checkbox";
    cb.value = t;
    cb.checked = currentTargets.has(t);
    cb.onchange = () => {
      const next = new Set(current.targets || []);
      if (cb.checked) next.add(t); else next.delete(t);
      setField("targets", [...next]);
      refreshStatusBadge();
    };
    label.append(cb, document.createTextNode(" " + t));
    targetsRow.append(label);
  }
  targetsWrap.append(targetsRow);
  wrap.append(targetsWrap);

  const badge = el("span", "meta-modified-badge" + (metaModified(p) ? "" : " hidden"),
                   "● metadata modified");
  badge.id = "meta-modified-badge";
  wrap.append(badge);
  function refreshStatusBadge() {
    badge.classList.toggle("hidden", !metaModified(p));
  }

  return wrap;
}

// ── skill supporting files — a shared inline editor ─────────────────────────────
// used by both the skill detail pane (Prompt Library) and the New Skill form.
// Mirrors loader._SKILL_RESOURCE_DIRS (the union of the harnesses' conventions).
const RESOURCE_PATH_RE = /^(examples|scripts|references|templates|resources)\/[^/].*[^/]$/;
const RESOURCE_SCRIPT_EXTENSIONS = new Set(["py", "js", "sh", "ps1"]);

function routeForFilename(filename) {
  const ext = (filename.split(".").pop() || "").toLowerCase();
  return (RESOURCE_SCRIPT_EXTENSIONS.has(ext) ? "scripts" : "examples") + "/" + filename;
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsText(file);
  });
}

// U+FFFD (replacement character) is what a UTF-8 decode emits in place of any byte
// sequence it can't decode — a cheap proxy for "this wasn't text to begin with" without
// re-reading the file as raw bytes. Mirrors the server's hard UnicodeDecodeError
// (loader._load_skill_resources) — this is just an earlier, friendlier warning.
const REPLACEMENT_CHAR = String.fromCharCode(0xFFFD);
const NULL_CHAR = String.fromCharCode(0);
function looksBinary(text) {
  return text.includes(NULL_CHAR) || text.includes(REPLACEMENT_CHAR);
}

function buildResourceEditor(getResources, setResources) {
  const wrap = el("div", "resource-editor");
  const list = el("div", "resource-list");
  const fileEditor = el("div", "resource-file-editor hidden");

  function closeFileEditor() { fileEditor.replaceChildren(); fileEditor.classList.add("hidden"); }

  function openFileEditor(path, text) {
    fileEditor.replaceChildren();
    fileEditor.classList.remove("hidden");
    fileEditor.append(el("label", "resource-file-label", path));
    const ta = document.createElement("textarea");
    ta.className = "resource-textarea";
    ta.value = text;
    fileEditor.append(ta);
    const actions = el("div", "detail-actions");
    const saveBtn = el("button", "tiny accept", "Save file");
    saveBtn.onclick = () => {
      setResources({ ...getResources(), [path]: ta.value });
      closeFileEditor();
      renderRows();
    };
    const cancelBtn = el("button", "tiny ghost", "Cancel");
    cancelBtn.onclick = closeFileEditor;
    actions.append(saveBtn, cancelBtn);
    fileEditor.append(actions);
  }

  function renderRows() {
    list.replaceChildren();
    const res = getResources();
    const paths = Object.keys(res).sort();
    if (!paths.length) list.append(el("div", "muted", "No supporting files."));
    for (const path of paths) {
      const row = el("div", "resource-row");
      row.append(el("span", "resource-path", path));
      const editBtn = el("button", "tiny", "Edit");
      editBtn.onclick = () => openFileEditor(path, res[path]);
      const delBtn = el("button", "tiny ghost", "×");
      delBtn.title = "Delete this file";
      delBtn.onclick = () => {
        const next = { ...getResources() };
        delete next[path];
        setResources(next);
        renderRows();
      };
      row.append(editBtn, delBtn);
      list.append(row);
    }
  }

  const addRow = el("div", "resource-add-row");
  const pathInput = el("input");
  pathInput.type = "text";
  pathInput.placeholder = "examples/sample.md or scripts/validate.sh";
  const addBtn = el("button", "ghost tiny", "+ Add file");
  addBtn.onclick = () => {
    const p = pathInput.value.trim();
    if (!RESOURCE_PATH_RE.test(p)) {
      toast("Path must be under examples/, scripts/, references/, templates/ or resources/ — e.g. examples/sample.md", 4000);
      return;
    }
    pathInput.value = "";
    openFileEditor(p, "");
  };
  addRow.append(pathInput, addBtn);

  const uploadInput = document.createElement("input");
  uploadInput.type = "file";
  uploadInput.multiple = true;
  uploadInput.hidden = true;
  uploadInput.onchange = async () => {
    const files = Array.from(uploadInput.files || []);
    uploadInput.value = "";   // allow re-selecting the same file(s) later
    let current = getResources();
    let changed = false;
    for (const file of files) {
      let text;
      try {
        text = await readFileAsText(file);
      } catch (e) {
        toast(`Could not read ${file.name} — skipped.`, 4000);
        continue;
      }
      if (looksBinary(text)) {
        toast(`${file.name} looks like a binary file — only UTF-8 text is supported here, skipped.`, 5000);
        continue;
      }
      const path = routeForFilename(file.name);
      if (current[path] !== undefined) toast(`Replaced existing ${path}`, 3000);
      current = { ...current, [path]: text };
      changed = true;
    }
    if (changed) {
      setResources(current);
      renderRows();
    }
  };
  const uploadBtn = el("button", "ghost tiny", "Upload file(s)");
  uploadBtn.title = "Pick one or more UTF-8 text files — routed to examples/ or scripts/ by extension";
  uploadBtn.onclick = () => uploadInput.click();
  addRow.append(uploadBtn, uploadInput);

  wrap.append(list, addRow, fileEditor);
  renderRows();
  return wrap;
}

// Supporting files themselves are edited in the Skills & Orgs tab (renderSkillFilesSection)
// — this stays only to gate the Prompt Library's "Revert" button, which resets a skill's
// body + metadata + any pending resource draft together as one full discard.
function resourcesModified(p) {
  return resourceDrafts[p.key] !== undefined;
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
  renderReturnBar(box, p.key);
  const head = el("div", "detail-head-banner");
  const headTop = el("div", "detail-head");
  headTop.append(el("strong", "detail-name", p.name));
  if (p.kind === "skill") headTop.append(el("span", "badge kind", p.catName));
  head.append(headTop);
  const chips = el("div", "doc-tags");
  if (p.kind === "partial") {
    // partials: show audience info (no editable targets)
    if (p.targets && p.targets.length) {
      for (const t of p.targets) chips.append(el("span", "tag-chip", t));
    } else if (p.meta) {
      chips.append(el("span", "muted", p.meta));
    }
  } else if (p.kind === "prompt") {
    // prompts: show live targets from the metadata panel draft (or the saved value)
    const liveTargets = metaCurrent(p).targets;
    if (liveTargets && liveTargets.length) {
      for (const t of liveTargets) chips.append(el("span", "tag-chip", t));
    }
  }
  // skills: no chips here — targets are editable in the metadata panel directly below
  if (chips.children.length) head.append(chips);

  box.append(head);

  const metaPanel = buildMetaPanel(p);
  if (metaPanel) box.append(metaPanel);

  const editor = buildContextualEditor({
    value: drafts[p.key] != null ? drafts[p.key] : p.body,
    onInput(value) {
      if (value === p.body) { delete drafts[p.key]; delete draftBase[p.key]; }
      else {
        if (drafts[p.key] == null) draftBase[p.key] = p.body;  // first edit: pin the base
        drafts[p.key] = value;
      }
      store.set(LS.drafts, drafts);
      store.set(LS.draftBase, draftBase);
    },
    statusText(value) {
      const modified = drafts[p.key] != null;
      return `${modified ? "● " : ""}${value.length.toLocaleString()} chars · ${p.kind} · ${p.ident}`;
    },
    isModified() { return drafts[p.key] != null; },
  });
  editor.textarea.id = "detail-body";
  box.append(editor.root);

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
  revert.disabled = drafts[p.key] == null && !metaModified(p) && !resourcesModified(p);
  revert.title = "Discard local edits (body + metadata + supporting files) and restore the registry text";
  revert.onclick = () => {
    delete drafts[p.key];
    delete draftBase[p.key];
    delete metaDrafts[p.key];
    delete resourceDrafts[p.key];
    store.set(LS.drafts, drafts);
    store.set(LS.draftBase, draftBase);
    renderDetail();
    renderList();
  };
  right.append(reason, save, revert);
  actions.append(left, right);
  box.append(actions);
}

function currentBody(p) {
  const ta = $("detail-body");
  return ta && selectedKey === p.key ? ta.value
    : (drafts[p.key] != null ? drafts[p.key] : p.body);
}

async function saveDraft(p, body, reason) {
  const payload = { kind: p.kind, ident: p.ident, body, reason };
  if (p.kind !== "partial" && metaDrafts[p.key]) payload.fields = metaDrafts[p.key];
  if (p.kind === "skill" && resourceDrafts[p.key] !== undefined) {
    payload.resources = resourceDrafts[p.key];
  }
  const res = await fetch("/api/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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

// ── Skills tab: card grid over registry skills ──────────────────────────────────
// The fixed target-adapter set now comes from /api/state (loader.KNOWN_TARGETS,
// build/agentic/loader.py) instead of a hardcoded duplicate — see STATE.known_targets.

function truncate(s, n) {
  return s.length > n ? s.slice(0, n).trimEnd() + "…" : s;
}


function renderSkills() {

  const box = $("view-skills");
  box.replaceChildren();

  if (newSkillOpen)     { box.append(newSkillForm());      return; }
  if (newOrgDomainOpen) { box.append(newOrgDomainForm()); return; }

  // ── toolbar: filter bar (left) + action buttons (right) ─────────────────
  const toolbar = el("div", "skills-toolbar");

  const filterBar = el("div", "skill-filter-bar");
  const searchInp = el("input");
  searchInp.type = "text";
  searchInp.placeholder = "Filter skills…";
  searchInp.value = skillFilterText;
  searchInp.oninput = () => { skillFilterText = searchInp.value; renderSkills(); };
  filterBar.append(searchInp);

  // target filter chips — sourced from STATE.known_targets (never hardcoded)
  const chipRow = el("div", "skill-filter-chips");
  for (const t of ["all", ...(STATE.known_targets || [])]) {
    const active = (t === "all" ? "" : t) === skillFilterTarget;
    const b = el("button", "pool-opt" + (active ? " active" : ""), t === "all" ? "All" : t);
    b.onclick = () => { skillFilterTarget = t === "all" ? "" : t; renderSkills(); };
    chipRow.append(b);
  }
  const orgChip = el("button", "pool-opt" + (skillFilterOrg ? " active" : ""), "Orgs only");
  orgChip.onclick = () => { skillFilterOrg = !skillFilterOrg; renderSkills(); };
  chipRow.append(orgChip);
  filterBar.append(chipRow);
  toolbar.append(filterBar);

  const btnGroup = el("div", "skill-toolbar-btns");
  const newSkillBtn = el("button", "accept", "+ New skill");
  newSkillBtn.onclick = () => { newSkillOpen = true; renderSkills(); };
  const newOrgBtn = el("button", "", "+ New org");
  newOrgBtn.title = "Scaffold a new org domain skill";
  newOrgBtn.onclick = () => { newOrgDomainOpen = true; renderSkills(); };
  btnGroup.append(newSkillBtn, newOrgBtn);
  toolbar.append(btnGroup);
  box.append(toolbar);

  // ── build domain-by-skill lookup from orgData ────────────────────────────
  // orgData is keyed by domain ("software"), each entry has .skill ("org-software").
  // Join direction: skill name → domain key. orgData may be null on first paint.
  const orgDomainBySkill = {};
  for (const [dom, data] of Object.entries(orgData || {})) {
    orgDomainBySkill[data.skill] = dom;
  }

  // ── filter ───────────────────────────────────────────────────────────────
  const q = skillFilterText.trim().toLowerCase();
  const skills = (STATE.prompts.skills || []);
  const visible = skills.filter(s => {
    if (skillFilterOrg && !orgDomainBySkill[s.name]) return false;
    if (skillFilterTarget && !(s.targets || []).includes(skillFilterTarget)) return false;
    if (q && !s.name.includes(q) && !(s.description || "").toLowerCase().includes(q)) return false;
    return true;
  });

  if (!visible.length) {
    box.append(el("div", "empty-state",
      skills.length ? "No skills match the current filter." : "No skills yet — create one to get started."));
    return;
  }

  const list = el("div", "skills-list");
  for (const s of visible) {
    list.append(skillRow(s, orgDomainBySkill[s.name] || null));
  }
  box.append(list);
}

// ── skillRow: collapsible accordion row showing static skill properties ──────
// The property grid is read-only — SKILL.md's body and frontmatter are edited in the
// Prompt Library via the existing editorOrigin return-bar flow. Supporting files
// (examples/, scripts/) are a separate concern — additional content uploaded alongside
// SKILL.md, not part of it — so they're editable right here (renderSkillFilesSection).
function skillRow(s, domain) {
  const isOpen = expandedSkillName === s.name;
  const row = el("div", "skill-row" + (isOpen ? " open" : ""));

  // ── collapsed header ─────────────────────────────────────────────────────
  const header = el("div", "skill-row-header");
  // Chevron always renders "▸" — the open/closed rotation is a pure CSS transition
  // on transform, driven by the .skill-row.open ancestor class.
  header.append(el("span", "skill-chevron", "▸"));
  header.append(el("strong", "", s.name));
  const catBadge = el("span", "badge kind", s.category || "general");
  catBadge.dataset.category = s.category || "general";
  header.append(catBadge);
  if (domain) header.append(el("span", "skill-org-badge", "org: " + domain));
  // scope: project is the noteworthy state (global is the silent default) — surface it
  // in the collapsed header so it's visible without expanding the row.
  const draftScope = (metaDrafts[`skill:${s.name}`] || {}).scope;
  if ((draftScope || s.frontmatter.scope) === "project") {
    header.append(el("span", "skill-org-badge", "scope: project"));
  }
  if (s.description) header.append(el("span", "muted skill-row-desc", s.description));

  // target chips pinned to the right of the header
  if (s.targets && s.targets.length) {
    const chips = el("div", "doc-tags skill-row-targets");
    for (const t of s.targets) {
      const chip = el("span", "tag-chip", t);
      chip.dataset.target = t;
      chips.append(chip);
    }
    header.append(chips);
  }

  header.onclick = () => {
    expandedSkillName = isOpen ? null : s.name;
    renderSkills();
  };
  row.append(header);

  // ── expanded body ────────────────────────────────────────────────────────
  if (isOpen) {
    const body = el("div", "skill-row-body");

    // Static property grid — read-only; editing happens in the Prompt Library
    const props = el("div", "skill-props");
    const prop = (label, val) => {
      const r = el("div", "skill-prop-card");
      r.append(el("span", "skill-prop-label muted", label));
      r.append(el("span", "skill-prop-value", String(val || "—")));
      return r;
    };
    props.append(prop("Version",   s.frontmatter.version   || "—"));
    props.append(prop("Author",    s.frontmatter.author    || "—"));
    props.append(prop("License",   s.frontmatter.license   || "—"));
    props.append(prop("Targets",   (s.targets || []).join(", ") || "—"));
    props.append(prop("Platforms", (s.frontmatter.platforms || []).join(", ") || "—"));
    body.append(props);

    // Action: navigate to Prompt Library with return-bar back to Skills
    const actBar = el("div", "skill-actions-bar");
    const editBtn = el("button", "", "Edit prompt →");
    editBtn.title = "Open in Prompt Library to edit body and metadata";
    editBtn.onclick = () =>
      openContextualEditor({ kind: "skill", ident: s.name, returnTab: "skills" });
    actBar.append(editBtn);
    body.append(actBar);

    body.append(renderSkillFilesSection(s));
    body.append(renderSkillExtensionSection(s));
    body.append(renderSkillScopeSection(s));

    // Org structure panel — only for org-domain skills
    if (domain && orgData && orgData[domain]) {
      body.append(renderSkillOrgSection(s.name, domain));
    }

    row.append(body);
  }

  return row;
}

// ── skill-row supporting files: examples/, scripts/ live here directly, independent
// of SKILL.md's body/metadata (Prompt-Library-only). Shares resourceDrafts/saveDraft
// with the Prompt Library editor via the same `skill:<name>` key, so a draft started
// on either surface is visible — and savable — from both. ────────────────────────
function renderSkillFilesSection(s) {
  const key = `skill:${s.name}`;
  const section = el("div", "skill-files-section");

  const header = el("div", "resources-panel-header");
  header.append(el("h4", "", "Supporting Files"));
  const badge = el("span", "meta-modified-badge hidden", "● files modified");
  header.append(badge);
  section.append(header);
  section.append(el("div", "muted resources-hint",
    "Deployed alongside SKILL.md and bundled into claude.ai zips."));

  const actions = el("div", "detail-actions");
  const reason = el("input");
  reason.type = "text";
  reason.placeholder = "Reason (optional — logged on accept)";
  const save = el("button", "accept tiny", "Save files to inbox");
  save.title = "Propose the current supporting-file set as an inbox candidate";
  const revert = el("button", "reject tiny", "Revert files");
  revert.title = "Discard local supporting-file edits for this skill";

  // buildResourceEditor funnels every mutation (add/edit/delete/upload) through
  // setResources below, so this one place keeps Save/Revert and the badge in sync —
  // unlike the disabled-state-computed-once approach the Prompt Library panel uses,
  // which doesn't need to react since it lives inside a full-page re-render already.
  function refreshActionState() {
    const hasDraft = resourceDrafts[key] !== undefined;
    save.disabled = !hasDraft;
    revert.disabled = !hasDraft;
    badge.classList.toggle("hidden", !hasDraft);
  }
  refreshActionState();

  section.append(buildResourceEditor(
    () => resourceDrafts[key] !== undefined ? resourceDrafts[key] : (s.resources || {}),
    (next) => { resourceDrafts[key] = next; refreshActionState(); },
  ));

  save.onclick = () => {
    const body = drafts[key] != null ? drafts[key] : s.body;
    saveDraft({ key, kind: "skill", ident: s.name }, body, reason.value);
  };
  revert.onclick = () => { delete resourceDrafts[key]; renderSkills(); };
  actions.append(reason, save, revert);
  section.append(actions);
  return section;
}

// ── skill-row extension assignment: extends_skill/extends_role, moved here from the
// Prompt Library metadata panel for the same reason as Supporting Files — it's a
// structural choice about where this skill sits in an org, not part of authoring its
// body. Shares metaDrafts (only the two extension keys) and saveDraft with the Prompt
// Library, same `skill:<name>` key, so a draft either surface starts is visible from
// both and Prompt Library's "Revert" still discards it as part of a full reset. ────
function renderSkillExtensionSection(s) {
  const key = `skill:${s.name}`;
  const section = el("div", "skill-extension-section");

  const header = el("div", "resources-panel-header");
  header.append(el("h4", "", "Extension"));
  const badge = el("span", "meta-modified-badge hidden", "● extension modified");
  header.append(badge);
  section.append(header);
  section.append(el("div", "muted resources-hint",
    "Both fields together turn this skill into an extension — its body splices into the "
    + "named parent skill's matching role section at render time; it never deploys "
    + "standalone. Leave both blank for a regular skill."));

  const actions = el("div", "detail-actions");
  const reason = el("input");
  reason.type = "text";
  reason.placeholder = "Reason (optional — logged on accept)";
  const save = el("button", "accept tiny", "Save extension to inbox");
  save.title = "Propose this skill's extension assignment as an inbox candidate";
  const revert = el("button", "reject tiny", "Revert extension");
  revert.title = "Discard the local extends_skill/extends_role edit for this skill";

  function refreshActionState() {
    const d = metaDrafts[key];
    const hasDraft = !!d && (("extends_skill" in d) || ("extends_role" in d));
    save.disabled = !hasDraft;
    revert.disabled = !hasDraft;
    badge.classList.toggle("hidden", !hasDraft);
  }

  const current = { ...(s.frontmatter || {}), ...(metaDrafts[key] || {}) };
  const { skillSelect, roleSelect } = buildExtensionSelects(
    current.extends_skill, current.extends_role,
    (skillVal, roleVal) => {
      metaDrafts[key] = metaDrafts[key] || {};
      metaDrafts[key].extends_skill = skillVal;
      metaDrafts[key].extends_role = roleVal;
      refreshActionState();
    });
  const extGrid = el("div", "meta-grid");
  extGrid.append(fieldWrap("Extends skill", skillSelect));
  extGrid.append(fieldWrap("Extends role", roleSelect));
  section.append(extGrid);
  refreshActionState();

  save.onclick = () => {
    const body = drafts[key] != null ? drafts[key] : s.body;
    saveDraft({ key, kind: "skill", ident: s.name }, body, reason.value);
  };
  revert.onclick = () => {
    const d = metaDrafts[key];
    if (d) {
      delete d.extends_skill;
      delete d.extends_role;
      if (!Object.keys(d).length) delete metaDrafts[key];
    }
    renderSkills();
  };
  actions.append(reason, save, revert);
  section.append(actions);
  return section;
}

// ── skill-row scope assignment: global (default, deploys to every shared/global
// directory a target offers — the antigravity_skills dir, the personal
// claude_code_skills dir, hermes, claude-app) vs project (deploys ONLY to the
// projects that name this skill in their manifest's `skills:` list, on whichever of
// claude-code/antigravity it targets). Mirrors renderSkillExtensionSection's pattern —
// same metaDrafts/saveDraft plumbing, same skill:<name> key. The list of bound
// projects itself is read-only here: the console doesn't write project manifests
// (see docs/managing-state.md, invariant #3) — add/remove a project's binding by
// editing that project's registry/projects/<slug>.yaml `skills:` list directly. ──
function renderSkillScopeSection(s) {
  const key = `skill:${s.name}`;
  const section = el("div", "skill-extension-section");

  const header = el("div", "resources-panel-header");
  header.append(el("h4", "", "Scope"));
  const badge = el("span", "meta-modified-badge hidden", "● scope modified");
  header.append(badge);
  section.append(header);
  section.append(el("div", "muted resources-hint",
    "Global (default): deploys to every shared directory this skill's targets offer. "
    + "Project: deploys only to the projects below, on claude-code/antigravity — hermes and "
    + "claude-app ignore this and always stay global."));

  function refreshActionState() {
    const d = metaDrafts[key];
    const hasDraft = !!d && ("scope" in d);
    save.disabled = !hasDraft;
    revert.disabled = !hasDraft;
    badge.classList.toggle("hidden", !hasDraft);
  }

  const current = { ...(s.frontmatter || {}), ...(metaDrafts[key] || {}) };
  const scopeRow = el("div", "meta-grid");
  const scopeSelect = el("select");
  for (const [val, label] of [["global", "Global"], ["project", "Project"]]) {
    const opt = el("option", "", label);
    opt.value = val;
    if ((current.scope || "global") === val) opt.selected = true;
    scopeSelect.append(opt);
  }
  scopeSelect.onchange = () => {
    metaDrafts[key] = metaDrafts[key] || {};
    metaDrafts[key].scope = scopeSelect.value;
    refreshActionState();
    renderSkills();
  };
  scopeRow.append(fieldWrap("Scope", scopeSelect));
  section.append(scopeRow);

  if ((current.scope || "global") === "project") {
    const boundWrap = el("div", "graph-field");
    boundWrap.append(el("label", "", "Bound projects (edit their manifest to change)"));
    if (s.bound_projects && s.bound_projects.length) {
      const chips = el("div", "doc-tags");
      for (const slug of s.bound_projects) chips.append(el("span", "tag-chip", slug));
      boundWrap.append(chips);
    } else {
      boundWrap.append(el("div", "muted",
        "No project currently lists this skill — it will deploy nowhere until a "
        + "project's registry/projects/<slug>.yaml adds it to `skills:`."));
    }
    section.append(boundWrap);
  }

  const actions = el("div", "detail-actions");
  const reason = el("input");
  reason.type = "text";
  reason.placeholder = "Reason (optional — logged on accept)";
  const save = el("button", "accept tiny", "Save scope to inbox");
  save.title = "Propose this skill's scope as an inbox candidate";
  const revert = el("button", "reject tiny", "Revert scope");
  revert.title = "Discard the local scope edit for this skill";
  save.onclick = () => {
    const body = drafts[key] != null ? drafts[key] : s.body;
    saveDraft({ key, kind: "skill", ident: s.name }, body, reason.value);
  };
  revert.onclick = () => {
    const d = metaDrafts[key];
    if (d) {
      delete d.scope;
      if (!Object.keys(d).length) delete metaDrafts[key];
    }
    renderSkills();
  };
  actions.append(reason, save, revert);
  section.append(actions);
  refreshActionState();
  return section;
}

// ── renderSkillOrgSection: org role tree / Agent-MD folder view ──────────────
// Embedded within the expanded body of an org-domain skill row. Uses the same
// renderRoleTree / renderAgentsMdPicker / renderAgentsMdTree functions the old
// Org tab used — they are unchanged; only the container changes.
function renderSkillOrgSection(skillName, domain) {
  const section = el("div", "skill-org-section");
  section.append(el("h4", "skill-org-heading", "Organization — " + domain));

  const mode = orgSkillViewMode[skillName] || "role";
  const viewToggle = el("div", "pool-toggle");
  for (const [id, label] of [["role", "Role Tree"], ["agentsmd", "Agent-MD Folder"]]) {
    const b = el("button", "pool-opt" + (mode === id ? " active" : ""), label);
    b.onclick = () => {
      orgSkillViewMode[skillName] = id;
      if (id === "agentsmd" && orgMachine && !orgTreeCache[orgMachine]) {
        loadOrgTree(orgMachine);   // async; calls renderSkills() on completion
      } else {
        renderSkills();
      }
    };
    viewToggle.append(b);
  }
  section.append(viewToggle);

  if (mode === "role") {
    section.append(renderRoleTree(orgData[domain]));
  } else {
    section.append(renderAgentsMdPicker());
    section.append(renderAgentsMdTree());
  }
  return section;
}

// ── New skill form ────────────────────────────────────────────────────────────
// Feeds POST /api/skills/new. Nothing writes registry/ directly (invariant #3);
// this lands a `kind: new` inbox candidate like every other console write.
let newSkillOpen = false;
let newSkillDraftBody = "# Instructions\n\n";
let newSkillPrefillName = "";         // set by the Org tab's "Edit playbook" before jumping here
let newSkillPrefillExtendsSkill = ""; // set by a role card's "+ Extend department" button
let newSkillPrefillExtendsRole = "";
// Everything the operator types survives a re-render while the form is open (e.g. an
// unrelated refresh() firing elsewhere, or loadOrgTree()'s renderSkills() call landing
// mid-edit) — without this, any such render rebuilds the form from scratch: prefills
// were already consumed-and-cleared (see newSkillPrefill* above, correctly, they can't
// leak), but live typed input had nowhere to survive to and was silently dropped.
// `targets: null` means "not yet touched by the operator" — applyParentTargets() may
// still auto-populate it; once the operator toggles a checkbox it becomes an explicit
// array and further auto-population is skipped.
let newSkillFieldDraft = { name: "", description: "", category: "", targets: null };
let newSkillResources = {};

function resetNewSkillDraft() {
  newSkillDraftBody = "# Instructions\n\n";
  newSkillFieldDraft = { name: "", description: "", category: "", targets: null };
  newSkillResources = {};
}

function newSkillForm() {
  const wrap = el("div", "inline-editor new-skill-form");
  const isExtension = !!newSkillPrefillExtendsSkill;
  wrap.append(el("h3", "", isExtension ? "New department extension" : "New skill"));

  const inputs = {};
  const field = (key, label, ph) => {
    const f = el("div", "graph-field");
    f.append(el("label", "", label));
    const inp = el("input");
    inp.type = "text";
    if (ph) inp.placeholder = ph;
    f.append(inp);
    wrap.append(f);
    inputs[key] = inp;
    return inp;
  };
  const nameInput = field("name", "Name (slug)", "my-new-skill");
  nameInput.value = newSkillFieldDraft.name || newSkillPrefillName;
  newSkillPrefillName = "";  // consumed on first render either way — never leaks forward
  nameInput.addEventListener("input", () => { newSkillFieldDraft.name = nameInput.value; });
  const descInput = field("description", "Description", "One-line summary");
  descInput.value = newSkillFieldDraft.description;
  descInput.addEventListener("input", () => { newSkillFieldDraft.description = descInput.value; });
  const catInput = field("category", "Category", "general");
  catInput.value = newSkillFieldDraft.category;
  catInput.addEventListener("input", () => { newSkillFieldDraft.category = catInput.value; });
  // Enter moves to the next field rather than submitting — this form has required
  // fields (targets) further down that Enter can't satisfy, so focus-advance is the
  // safe non-destructive action here (contrast bindEnterToApply, used where a single
  // Enter press really can complete the form).
  const focusNext = (next) => (e) => { if (e.key === "Enter") { e.preventDefault(); next.focus(); } };
  nameInput.addEventListener("keydown", focusNext(descInput));
  descInput.addEventListener("keydown", focusNext(catInput));

  const prefillExtSkill = newSkillPrefillExtendsSkill;
  const prefillExtRole = newSkillPrefillExtendsRole;
  newSkillPrefillExtendsSkill = "";
  newSkillPrefillExtendsRole = "";

  const targetsWrap = el("div", "graph-field");
  targetsWrap.append(el("label", "", "Targets"));
  const targetsRow = el("div", "target-checks");
  const targetBoxes = {};
  for (const t of (STATE.known_targets || [])) {
    const label = el("label", "target-check");
    const cb = el("input");
    cb.type = "checkbox";
    cb.value = t;
    if (newSkillFieldDraft.targets) cb.checked = newSkillFieldDraft.targets.includes(t);
    cb.onchange = () => {
      newSkillFieldDraft.targets = (STATE.known_targets || []).filter((tt) => targetBoxes[tt].checked);
    };
    label.append(cb, document.createTextNode(" " + t));
    targetsRow.append(label);
    targetBoxes[t] = cb;
  }
  targetsWrap.append(targetsRow);

  // an extension defaults to its parent's targets — it never deploys standalone, but
  // targets is still required shape (schema uniformity), so save the operator a click.
  // Re-applied live whenever the parent select changes, not just on initial prefill.
  function applyParentTargets(parentName) {
    const parentTargets = new Set(
      (STATE.prompts.skills || []).find((s) => s.name === parentName)?.targets || []);
    for (const t of (STATE.known_targets || [])) targetBoxes[t].checked = parentTargets.has(t);
    newSkillFieldDraft.targets = [...parentTargets];
  }

  const { skillSelect: extSkillSelect, roleSelect: extRoleSelect } = buildExtensionSelects(
    prefillExtSkill, prefillExtRole,
    (skillVal) => { if (skillVal) applyParentTargets(skillVal); });
  // Skip the auto-populate once the operator has touched targets (draft.targets set) —
  // a re-render mid-edit (see the draft-state note above) must not clobber their choice.
  if (isExtension && !newSkillFieldDraft.targets) applyParentTargets(prefillExtSkill);

  const extGrid = el("div", "meta-grid");
  extGrid.append(fieldWrap("Extends skill (leave blank for a regular skill)", extSkillSelect));
  extGrid.append(fieldWrap("Extends role", extRoleSelect));
  wrap.append(extGrid);
  wrap.append(el("div", "muted extension-hint",
    "Both fields together turn this into an extension — it splices into the named "
    + "parent skill's matching role section at render time and never deploys standalone."));

  wrap.append(targetsWrap);

  const editor = buildContextualEditor({
    value: newSkillDraftBody,
    onInput(value) { newSkillDraftBody = value; },
    statusText(value) { return `${value.length.toLocaleString()} chars · new skill body`; },
  });
  wrap.append(editor.root);

  const resWrap = el("div", "resources-panel");
  resWrap.append(el("div", "resources-panel-header", "Supporting Files (optional)"));
  resWrap.append(buildResourceEditor(
    () => newSkillResources, (next) => { newSkillResources = next; }));
  wrap.append(resWrap);

  const actions = el("div", "detail-actions");
  const reason = el("input");
  reason.type = "text";
  reason.placeholder = "Reason (optional — logged on accept)";
  const create = el("button", "accept", isExtension ? "Create extension" : "Create skill");
  create.onclick = async () => {
    const targets = (STATE.known_targets || []).filter((t) => targetBoxes[t].checked);
    const fm = { description: descInput.value.trim(), category: catInput.value.trim(), targets };
    if (extSkillSelect.value.trim()) fm.extends_skill = extSkillSelect.value.trim();
    if (extRoleSelect.value.trim()) fm.extends_role = extRoleSelect.value.trim();
    const res = await fetch("/api/skills/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: nameInput.value.trim(),
        frontmatter: fm,
        body: editor.textarea.value,
        reason: reason.value,
        resources: Object.keys(newSkillResources).length ? newSkillResources : undefined,
      }),
    });
    const out = await res.json();
    if (out.ok) {
      toast(`Proposed → inbox/${out.id} — review in the Inbox tab, then Accept.`, 5000);
      newSkillOpen = false;
      resetNewSkillDraft();
      await refresh();
    } else {
      toast(`Error: ${out.error}`, 5000);
    }
  };
  const cancel = el("button", "ghost", "Cancel");
  cancel.onclick = () => { newSkillOpen = false; resetNewSkillDraft(); renderSkills(); };
  actions.append(reason, create, cancel);
  wrap.append(actions);
  return wrap;
}

// ── Org tab: READ-ONLY visualization of the existing hand-authored org prose (parsed
// server-side, org_index()/org_tree() in review.py) — role TITLES and playbooks
// (lens/team/vocabulary/trigger) live in the org-*/SKILL.md domain skills,
// hand-authored, never generated or edited here. Orgs are GLOBAL domain skills and are
// never attached to a project — the only org edge in the graph is an effort's orgDomain
// tag, edited in the Knowledge Graph tab's effort editor. The one write path here is
// "+ ORG" (propose a brand-new domain skill as a kind:new inbox candidate).
// ───────────────────────────────────────────────────────────────────────────────────
let orgData = null;          // /api/org response, fetched once and cached
let orgTreeCache = {};       // machine -> /api/org/tree response, cached per machine
let orgDomain = null;        // selected domain key, e.g. "software"
let orgViewMode = "role";    // "role" | "agentsmd"
let orgMachine = null;       // selected machine for the Agent-MD folder view
let newOrgDomainOpen = false; // "+ ORG" inline dialog toggle

async function loadOrgData() {
  if (!orgData) {
    const res = await fetch("/api/org");
    orgData = await res.json();
    if (!orgDomain) orgDomain = Object.keys(orgData)[0] || null;
  }
  renderSkills();
}

async function loadOrgTree(machine) {
  const res = await fetch(`/api/org/tree?machine=${encodeURIComponent(machine)}`);
  orgTreeCache[machine] = await res.json();
  renderSkills();
}

function renderOrg() {
  const box = $("view-org");
  box.replaceChildren();
  if (!orgData) { box.append(el("div", "empty-state", "Loading…")); return; }
  if (newOrgDomainOpen) { box.append(newOrgDomainForm()); return; }

  const toolbar = el("div", "org-toolbar");
  const newOrgBtn = el("button", "accept tiny", "+ ORG");
  newOrgBtn.title = "Create a new domain org template (e.g. finance)";
  newOrgBtn.onclick = () => { newOrgDomainOpen = true; renderOrg(); };
  toolbar.append(newOrgBtn);

  const domains = Object.keys(orgData);
  if (!domains.length) {
    box.append(toolbar);
    box.append(el("div", "empty-state", "No org domains found — click + ORG above to create one."));
    return;
  }
  if (!orgDomain || !orgData[orgDomain]) orgDomain = domains[0];

  const switcher = el("div", "pool-toggle org-switcher");
  for (const d of domains) {
    const b = el("button", "pool-opt" + (d === orgDomain ? " active" : ""),
                 d.charAt(0).toUpperCase() + d.slice(1));
    b.onclick = () => { orgDomain = d; renderOrg(); };
    switcher.append(b);
  }
  toolbar.append(switcher);

  const viewToggle = el("div", "pool-toggle");
  for (const [id, label] of [["role", "Role Tree"], ["agentsmd", "Agent-MD Folder View"]]) {
    const b = el("button", "pool-opt" + (orgViewMode === id ? " active" : ""), label);
    b.onclick = () => {
      orgViewMode = id;
      if (id === "agentsmd" && orgMachine && !orgTreeCache[orgMachine]) loadOrgTree(orgMachine);
      else renderOrg();
    };
    viewToggle.append(b);
  }
  toolbar.append(viewToggle);
  box.append(toolbar);

  if (orgViewMode === "role") {
    box.append(renderRoleTree(orgData[orgDomain]));
  } else {
    box.append(renderAgentsMdPicker());
    box.append(renderAgentsMdTree());
  }
}

// "+ ORG": scaffolds a new domain-template skill (org-<domain>) via /api/org/new-domain —
// a single kind:new candidate, immediately valid as an effort's org-domain tag once accepted.
function newOrgDomainForm() {
  const wrap = el("div", "inline-editor new-skill-form");
  wrap.append(el("h3", "", "New org domain"));
  wrap.append(el("div", "muted",
    "Scaffolds a domain-template skill (org-<domain>) with a CEO/VP/Assistant structure. "
    + "Accept it in the Inbox tab to make the domain selectable here and in the Knowledge "
    + "Graph tab's effort editor (Org domain)."));
  const f = el("div", "graph-field");
  f.append(el("label", "", "Domain (slug)"));
  const inp = el("input");
  inp.type = "text";
  inp.placeholder = "finance";
  f.append(inp);
  wrap.append(f);

  const actions = el("div", "detail-actions");
  const create = el("button", "accept", "Create domain");
  create.onclick = async () => {
    const domain = inp.value.trim().toLowerCase();
    if (!domain) { toast("Domain is required."); return; }
    const res = await fetch("/api/org/new-domain", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain }),
    });
    const out = await res.json();
    if (out.ok) {
      toast(`Proposed → inbox/${out.id} — review in the Inbox tab, then Accept.`, 5000);
      newOrgDomainOpen = false;
      await refresh();
    } else {
      toast(`Error: ${out.error}`, 5000);
    }
  };
  const cancel = el("button", "ghost", "Cancel");
  cancel.onclick = () => { newOrgDomainOpen = false; renderSkills(); };

  actions.append(create, cancel);
  wrap.append(actions);
  return wrap;
}

function renderRoleTree(data) {
  const wrap = el("div", "org-tree");
  const chainWrap = el("div", "org-chain");
  chainWrap.append(el("h4", "", "Primary chain"));
  if (data.primaryChain.length) {
    const list = el("ol", "org-chain-list");
    for (const step of data.primaryChain) {
      const li = el("li");
      li.append(el("strong", "", step.title), document.createTextNode(" — " + step.subtitle));
      list.append(li);
    }
    chainWrap.append(list);
  } else {
    chainWrap.append(el("div", "muted", data.primaryChainSummary || "No primary chain parsed."));
  }
  wrap.append(chainWrap);

  if (data.extendedRoles.length) {
    const rolesWrap = el("div", "org-roles");
    rolesWrap.append(el("h4", "", "Extended C-suite"));
    for (const role of data.extendedRoles) rolesWrap.append(roleCard(role, data.skill));
    wrap.append(rolesWrap);
  }
  return wrap;
}

function roleCard(role, parentSkill) {
  const field = (label, text) => {
    const f = el("div", "role-field");
    f.append(el("strong", "", label + ": "), document.createTextNode(text));
    return f;
  };
  const details = el("details", "org-node-group role-card");
  details.append(el("summary", "", `${role.title} — ${role.subtitle}`));
  const body = el("div", "role-card-body");
  if (role.lens) body.append(field("Lens", role.lens));
  if (role.team) body.append(field("Team", role.team));
  if (role.vocabulary) body.append(field("Vocabulary", role.vocabulary));
  if (role.trigger) body.append(field("Trigger", role.trigger));

  const exts = role.activeExtensions || [];
  if (exts.length) {
    const extWrap = el("div", "role-extensions");
    extWrap.append(el("strong", "", "Active extensions: "));
    for (const e of exts) {
      const badge = el("span", "extension-badge", e.name);
      if (e.description) badge.title = e.description;
      extWrap.append(badge);
    }
    body.append(extWrap);
  }

  if (parentSkill) {
    const extendBtn = el("button", "ghost tiny", "+ Extend department");
    extendBtn.title = `Add a custom skill that extends ${parentSkill}'s ${role.title} role`;
    extendBtn.onclick = (ev) => {
      ev.preventDefault();   // don't toggle the <details> disclosure
      newSkillPrefillExtendsSkill = parentSkill;
      newSkillPrefillExtendsRole = role.title;
      newSkillPrefillName = `${parentSkill}-${role.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
      newSkillOpen = true;
      renderSkills();
    };
    body.append(extendBtn);
  }

  details.append(body);
  return details;
}

function renderAgentsMdPicker() {
  const machines = STATE.agents_md_machines || [];
  if (!machines.length) return el("div", "empty-state", "No machine profile deploys agents-md.");
  if (!orgMachine || !machines.includes(orgMachine)) orgMachine = machines[0];
  const wrap = el("div", "org-machine-picker");
  wrap.append(el("label", "", "Machine "));
  const sel = el("select", "graph-select");
  for (const m of machines) {
    const opt = el("option");
    opt.value = m; opt.textContent = m;
    if (m === orgMachine) opt.selected = true;
    sel.append(opt);
  }
  sel.onchange = () => { orgMachine = sel.value; loadOrgTree(orgMachine); };
  wrap.append(sel);
  return wrap;
}

function renderAgentsMdTree() {
  if (!orgMachine) orgMachine = (STATE.agents_md_machines || [])[0];
  if (!orgMachine) return el("div", "empty-state", "No machine available.");
  const data = orgTreeCache[orgMachine];
  if (!data) { loadOrgTree(orgMachine); return el("div", "empty-state", "Loading…"); }
  if (!data.ok) return el("div", "empty-state", `Error: ${data.error}`);
  if (!data.tree.length) return el("div", "empty-state", "No Agent-MD tree planned for this machine.");
  const root = el("div", "org-tree");
  for (const node of data.tree) root.append(orgTreeNode(node));
  return root;
}

function orgTreeNode(node) {
  if (!node.children.length) {
    const row = el("div", "org-node org-leaf");
    row.append(el("span", "org-node-name", node.name));
    if (node.deployPath) row.append(el("span", "muted org-node-path", node.deployPath));
    return row;
  }
  const details = el("details", "org-node-group");
  details.open = true;
  details.append(el("summary", "", node.name));
  for (const child of node.children) details.append(orgTreeNode(child));
  return details;
}

// ── favorites / recents ───────────────────────────────────────────────────────
function toggleFavorite(key) {
  const i = favorites.indexOf(key);
  if (i >= 0) favorites.splice(i, 1);
  else favorites.unshift(key);
  store.set(LS.favorites, favorites);
  renderList();
  if (selectedKey === key) renderDetail();
  // Partials have no backend-tracked favorite field (prompt_index() only marks
  // .favorited on prompts/skills) — their pin state stays a local-only scratchpad.
  const p = PMAP.get(key);
  if (p && (p.kind === "skill" || p.kind === "prompt")) {
    fetch("/api/prompts/favorite", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: p.ident }),
    }).catch(() => { /* best-effort — local pin state already applied */ });
  }
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
  $("view-inbox").hidden  = which !== "inbox";
  $("view-graph").hidden  = which !== "graph";
  $("view-skills").hidden = which !== "skills";
  $("view-prompts").hidden = which !== "prompts";

  // sidebar active state
  const activeNav = { inbox: "nav-inbox", graph: "nav-graph",
    skills: "nav-skills", prompts: "nav-prompts" }[which] || "";
  for (const id of ["nav-graph", "nav-skills", "nav-prompts", "nav-inbox"]) {
    const n = $(id); if (n) n.classList.toggle("active", id === activeNav);
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

// ── command palette: Ctrl/Cmd+K, find anything across skills/prompts/partials ──
let paletteResults = [];
let paletteIdx = 0;

function openPalette() {
  $("cmdk").hidden = false;
  const input = $("cmdk-input");
  input.value = "";
  renderPaletteResults("");
  input.focus();
}

function closePalette() {
  $("cmdk").hidden = true;
  $("cmdk-input").blur();
}

function renderPaletteResults(query) {
  const q = query.trim().toLowerCase();
  paletteResults = (q ? PROMPTS.filter((p) => p.search.includes(q)) : PROMPTS).slice(0, 40);
  paletteIdx = 0;
  renderPaletteRows();
}

function renderPaletteRows() {
  const box = $("cmdk-results");
  box.replaceChildren();
  if (!paletteResults.length) {
    box.append(el("div", "empty-state", "No matches."));
    return;
  }
  paletteResults.forEach((p, i) => {
    const row = el("div", "cmdk-row" + (i === paletteIdx ? " active" : ""));
    row.append(el("span", "badge kind", p.kind));
    const col = el("div", "row-col");
    col.append(el("div", "row-name", p.label));
    if (p.desc) col.append(el("div", "row-desc", p.desc));
    row.append(col);
    row.onclick = () => selectPaletteResult(i);
    box.append(row);
  });
  box.children[paletteIdx]?.scrollIntoView({ block: "nearest" });
}

function movePaletteSelection(delta) {
  if (!paletteResults.length) return;
  paletteIdx = Math.max(0, Math.min(paletteResults.length - 1, paletteIdx + delta));
  renderPaletteRows();
}

function selectPaletteResult(i) {
  const p = paletteResults[i];
  if (!p) return;
  closePalette();
  filterChip = "all";
  showTab("prompts");
  renderChips();
  renderList();
  selectPrompt(p.key);
  pushRecent(p.key);
}

$("cmdk-input").oninput = (e) => renderPaletteResults(e.target.value);
$("cmdk-input").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); movePaletteSelection(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); movePaletteSelection(-1); }
  else if (e.key === "Enter") { e.preventDefault(); selectPaletteResult(paletteIdx); }
  else if (e.key === "Escape") { e.preventDefault(); closePalette(); }
});
$("cmdk").onclick = (e) => { if (e.target.id === "cmdk") closePalette(); };

document.addEventListener("keydown", (e) => {
  // Global: Ctrl/Cmd+K opens the command palette from anywhere
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    openPalette();
    return;
  }
  if (e.key === "Escape" && !$("deploy-confirm").hidden) {
    e.preventDefault();
    closeDeployConfirm();
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

// ── Ops: compile/deploy from the console ────────────────────────────────────
function renderOpsBar() {
  const badge = $("ops-compile-badge");
  const sel = $("ops-machine");
  if (!badge || !sel || !STATE) return;
  const c = STATE.ops && STATE.ops.compile;
  if (c) {
    badge.className = "badge " + (c.stale ? "stale" : "compiled");
    badge.textContent = c.stale ? `Compile needed (${c.stale_machines.length})` : "Compiled";
    badge.title = c.stale
      ? `Stale for: ${c.stale_machines.join(", ")}`
      : "dist/ matches the current registry";
  }
  const machines = STATE.machines || [];
  const prevValue = sel.value;
  sel.replaceChildren(...machines.map((m) => {
    const opt = el("option", null, m);
    opt.value = m;
    return opt;
  }));
  if (opsMachine && machines.includes(opsMachine)) sel.value = opsMachine;
  else if (machines.includes(prevValue)) sel.value = prevValue;
  else if (machines.length) sel.value = machines[0];
  opsMachine = sel.value || null;
}

function openOpsDrawer() {
  $("ops-drawer").hidden = false;
  $("ops-drawer-body").hidden = false;
  $("ops-drawer-toggle").textContent = "▾";
}

function renderOpsSnapshot(snap) {
  const status = $("ops-drawer-status");
  const log = $("ops-drawer-log");
  log.textContent = snap.log || "";
  log.scrollTop = log.scrollHeight;
  const verb = snap.kind === "deploy" ? "Deploy" : "Compile";
  if (snap.running) {
    status.replaceChildren(el("span", "spinner"),
      document.createTextNode(`${verb}ing${snap.machine ? " " + snap.machine : ""}…`));
  } else {
    status.textContent = snap.rc === 0 ? `${verb} succeeded` : `${verb} failed (rc ${snap.rc})`;
  }
}

// No existing setInterval-based polling exists elsewhere in this file — deploy is the one
// op that can run long enough (repo clones, up to 600s each) to need it; compile always
// finishes synchronously in the request that starts it.
function startOpsPolling() {
  if (opsPollTimer) return;
  opsPollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/ops/status");
      const snap = await res.json();
      renderOpsSnapshot(snap);
      if (!snap.running) {
        clearInterval(opsPollTimer);
        opsPollTimer = null;
        await refresh();
      }
    } catch (err) {
      console.error(err);
      clearInterval(opsPollTimer);
      opsPollTimer = null;
    }
  }, 700);
}

async function runCompile() {
  try {
    const res = await fetch("/api/ops/compile", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const out = await res.json();
    if (!out.ok) { toast(`Error: ${out.error}`, 5000); return; }
    openOpsDrawer();
    renderOpsSnapshot({ running: false, kind: "compile", log: out.log, rc: out.rc });
    toast(out.rc === 0 ? "Compiled." : `Compile failed (rc ${out.rc}).`, 4000);
    await refresh();
  } catch (err) {
    console.error(err);
    toast(`Failed to compile: ${err.message || err}`, 6000);
  }
}

function renderDeployPlan(plan) {
  const body = $("deploy-confirm-body");
  const goBtn = $("deploy-confirm-go");
  body.replaceChildren();
  if (plan.refusal) {
    // a hard, machine-level guard (example template / OS mismatch) — this deploy will be
    // refused outright, before any file is even considered. Disable Confirm rather than
    // let the operator find out only after clicking it and reading the log drawer.
    body.append(el("div", "accept-note warning-callout", plan.refusal));
    goBtn.disabled = true;
    goBtn.title = "This deploy will be refused — see the message above.";
  } else {
    goBtn.disabled = false;
    goBtn.title = "";
  }
  if (!plan.statuses.length) {
    body.append(el("div", "empty-state", "Nothing planned for this machine."));
  }
  for (const s of plan.statuses) {
    const row = el("div", "deploy-plan-row" + (s.blocked ? " is-blocked" : ""));
    row.append(el("span", "plan-state", s.state));
    row.append(el("span", "plan-path", s.path));
    if (s.detail) row.append(el("span", "plan-detail", `— ${s.detail}`));
    if (s.blocked) row.append(el("span", "badge blocked", "blocked"));
    body.append(row);
  }
  if (plan.blocked_count) {
    body.append(el("div", "accept-note warning-callout",
      `${plan.blocked_count} protected file(s) are drifted — deploy will refuse and change `
      + `nothing until resolved via adopt/harvest.`));
  }
  const section = (label, items, render) => {
    if (!items.length) return;
    const sec = el("div", "deploy-plan-section");
    sec.append(el("h4", null, `${items.length} ${label}`));
    for (const item of items) sec.append(el("div", "deploy-plan-row", render(item)));
    body.append(sec);
  };
  section("orphan(s) — kept on disk (--prune is CLI-only)", plan.orphans, (p) => p);
  section("skill warning(s)", plan.skill_warnings, (w) => w);
  section("repo clone(s)", plan.clones,
    (c) => `${c.dest} — ${c.present ? "present, untouched" : "absent -> will clone"}`);
}

async function openDeployConfirm() {
  const machine = opsMachine || ($("ops-machine") && $("ops-machine").value);
  if (!machine) { toast("No machine selected."); return; }
  $("deploy-confirm-machine").textContent = machine;
  const body = $("deploy-confirm-body");
  const goBtn = $("deploy-confirm-go");
  body.replaceChildren(el("div", "empty-state", "Loading plan…"));
  goBtn.disabled = true;
  goBtn.title = "";
  $("deploy-confirm").hidden = false;
  try {
    const res = await fetch("/api/ops/deploy/plan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ machine }),
    });
    const out = await res.json();
    if (!out.ok) {
      body.replaceChildren(el("div", "empty-state", `Error: ${out.error}`));
      return;
    }
    renderDeployPlan(out);
  } catch (err) {
    console.error(err);
    body.replaceChildren(el("div", "empty-state", `Failed to load plan: ${err.message || err}`));
  }
}

function closeDeployConfirm() { $("deploy-confirm").hidden = true; }

async function confirmDeploy() {
  const machine = $("deploy-confirm-machine").textContent;
  closeDeployConfirm();
  try {
    const res = await fetch("/api/ops/deploy/apply", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ machine }),
    });
    const out = await res.json();
    if (!out.ok) { toast(`Error: ${out.error}`, 5000); return; }
    openOpsDrawer();
    renderOpsSnapshot({ running: true, kind: "deploy", machine, log: "" });
    startOpsPolling();
  } catch (err) {
    console.error(err);
    toast(`Failed to start deploy: ${err.message || err}`, 6000);
  }
}

// sidebar navigation
$("nav-inbox").onclick = () => showTab("inbox");
$("nav-graph").onclick = () => {
  showTab("graph");
  if (graphSlug && !stagedData) loadStaged(graphSlug);
  if (graphSlug && !dismissedData) loadDismissed(graphSlug);
};
$("nav-skills").onclick = () => showTab("skills");
$("nav-prompts").onclick = () => { filterChip = "all"; showTab("prompts"); renderChips(); renderList(); };

// global controls
$("graph-dock-propose").onclick = () => proposeGraphDraft();
// Enter in the dock's reason field proposes (inbox-only, never a registry write) — safe
// to bind, unlike the inbox card's Reason field which must NOT trigger Accept.
$("graph-dock-reason").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); $("graph-dock-propose").click(); }
});
$("graph-dock-propose-accept").onclick = () => proposeGraphDraft(graphSlug, null, true);
$("graph-dock-discard").onclick = () => discardGraphDraft();
$("refresh").onclick = () => refresh().then(() => toast("Reloaded from disk."));
$("nav-compile").onclick = () => runCompile();
$("nav-deploy").onclick = () => openDeployConfirm();
$("ops-machine").onchange = () => {
  opsMachine = $("ops-machine").value || null;
  store.set(LS.opsMachine, opsMachine);
};
$("ops-drawer-toggle").onclick = () => {
  const body = $("ops-drawer-body");
  body.hidden = !body.hidden;
  $("ops-drawer-toggle").textContent = body.hidden ? "▸" : "▾";
};
$("ops-drawer-dismiss").onclick = () => { $("ops-drawer").hidden = true; };
$("deploy-confirm-cancel").onclick = () => closeDeployConfirm();
$("deploy-confirm-go").onclick = () => confirmDeploy();
$("deploy-confirm").onclick = (e) => { if (e.target.id === "deploy-confirm") closeDeployConfirm(); };
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
