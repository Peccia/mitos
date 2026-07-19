"""The operator console (V2.2): review inbox candidates + browse/copy one-shot prompts.

`compile.py review` serves a single-page app from build/review_ui/ on 127.0.0.1 only.
Two views: the inbox queue (diff each candidate against the *current* registry,
accept/reject) and the prompt library (all registry prose, copy/compose for one-shot
use in chat applications — the iterative middle layer between the registry and rented
chat tools).

Security: candidates are untrusted, agent-produced text. The server emits JSON only;
the client renders exclusively via textContent — never live HTML/markdown. Accept
routes through the same engine as `adopt` (commands.route_into_registry); every
decision appends to inbox/decisions.jsonl (tracked — V3's procedural-memory signal).
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import difflib
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

import yaml

from . import commands, loader, render, staging as staging_mod
from .commands import _now, _real_registry_rel, route_into_registry
from .io import sha256
from .loader import Registry
from .planner import plan_machine

UI_DIR = Path(__file__).resolve().parent.parent / "review_ui"
DECISIONS = "decisions.jsonl"


def _partial_logical(rel: str) -> str:
    """Strip the Mitos-overlay `local/` rel prefix (see loader._load_partials) to
    recover the logical name reg.partials is keyed by. A partial's `.rel` carries the
    prefix for overlay-sourced entries (needed so Accept routes edits back into
    registry/local/), but reg.partials itself is keyed by the unprefixed logical
    name — the two diverge for every overlay-sourced partial."""
    prefix = f"{loader.LOCAL_OVERLAY}/"
    return rel[len(prefix):] if rel.startswith(prefix) else rel

_CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


# ── candidates ───────────────────────────────────────────────────────────────
def load_candidates(reg: Registry) -> list[dict]:
    """Every inbox candidate, with its diff against the current registry computed at
    review time (full snapshots, not patches — so this is always the live comparison)."""
    inbox = loader.inbox_dir(reg)
    out: list[dict] = []
    if not inbox.is_dir():
        return out
    for folder in sorted(p for p in inbox.iterdir() if p.is_dir()):
        meta_path = folder / "meta.yaml"
        if not meta_path.is_file():
            continue
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        payload_file = next((f for f in sorted(folder.iterdir())
                             if f.is_file() and f.name != "meta.yaml"), None)
        payload = (payload_file.read_text(encoding="utf-8", errors="replace")
                   if payload_file else "")
        current, proposed, acceptable, note = _bodies(reg, meta, payload)
        # For graph candidates, surface the target project, the document IDs the fragment
        # proposes, and the IDs it removes, so the Knowledge Graph tab can flag in-flight
        # documents without parsing the jsonld (and its IRI scheme) client-side. Empty for
        # non-graph candidates.
        project, doc_ids, removal_ids, effort_ids, effort_removal_ids = \
            _graph_candidate_targets(reg, meta, payload)
        doc_delta = _doc_delta(reg, meta, payload)
        # A graph candidate with nothing to add/change and no in-flight removal is a
        # true no-op — the console de-emphasizes (never hides) Accept for it; the
        # server-side accept path is the real check either way.
        no_changes = (meta.get("kind") == "graph"
                     and not doc_delta.get("added") and not doc_delta.get("changed")
                     and not doc_delta.get("removed"))
        registry_path = meta.get("registry_path") or ""
        out.append({
            "id": folder.name,
            "registry_path": registry_path,
            "kind": meta.get("kind", ""),
            "resources": (_candidate_resources(folder)
                         if registry_path.endswith("SKILL.md") else {}),
            "resources_provided": bool(meta.get("resources_provided")),
            "project": project,
            "doc_ids": doc_ids,
            "removal_ids": removal_ids,
            "effort_ids": effort_ids,
            "effort_removal_ids": effort_removal_ids,
            "doc_delta": doc_delta,
            "no_changes": no_changes,
            "store": meta.get("store", ""),
            "source": meta.get("source") or {},
            "deploy_path": meta.get("deploy_path", ""),
            "captured_at": meta.get("captured_at", ""),
            "note": meta.get("note", ""),
            "payload": proposed,
            "diff": _diff_rows(current, proposed),
            "acceptable": acceptable,
            "accept_note": note,
            "stale": _stale(reg, meta),
            # the real (overlay-aware) registry files a manual resolution must edit —
            # a partial overridden by the local overlay routes to its registry/local/ path
            "sources": [_real_registry_rel(reg, s) for s in (meta.get("sources") or [])],
        })
    return out


def _graph_candidate_targets(reg: Registry, meta: dict, payload: str
                             ) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """(project_slug, [upserted_doc_id, …], [removed_doc_id, …],
        [upserted_effort_id, …], [removed_effort_id, …]) a graph candidate proposes;
    ("", [], [], [], []) for non-graph. Removals live in meta (the fragment carries
    only upserts), so removed docs/efforts are flagged in-flight just like upserted
    ones."""
    if meta.get("kind") != "graph":
        return "", [], [], [], []
    slug = meta.get("project") or ""
    removals = [str(r) for r in (meta.get("removals") or [])]
    effort_removals = [str(r) for r in (meta.get("effort_removals") or [])]
    try:
        from . import graph as graphmod
        _name, _desc, docs, efforts = graphmod.parse_fragment(payload, slug)
        return (slug, [d.drive_id for d in docs], removals, [e.id for e in efforts],
               effort_removals)
    except Exception:
        return slug, [], removals, [], effort_removals


def _doc_delta(reg: Registry, meta: dict, payload: str) -> dict:
    """Added/changed/removed document IDs for a `kind: graph` candidate — the diff-aware
    view (batch2 item 2): re-running `connect` re-enumerates a whole store, so the generic
    line diff over the full merged JSON-LD is noisy; this set-compares the candidate's
    proposed documents against the CURRENT registry/graph/<slug>.jsonld and surfaces only
    what actually differs. "changed" = same drive_id, different name/date_modified/
    web_url/doc_type/store.

    "removed" here means "not present in this candidate's enumeration" — PRESENTATION
    ONLY. The accept/upsert path is untouched (upsert_document never deletes; only an
    explicit `removals` entry in meta does that — see `removal_ids`), so nothing in
    this list is deleted unless the reviewer separately proposes it.

    Scoped to the candidate's own store when one is recorded (meta["store"], from item
    1's one-candidate-per-store shape) so a store-A candidate never flags store-B's (or
    another store's) documents as "removed" — comparing against the whole graph would
    otherwise manufacture a false "these got removed" signal for data the candidate
    never touched. Unscoped (compares the whole graph) for a single-store candidate,
    matching legacy keyless documents. {} for a non-graph candidate or an unparsable one
    (the accept-path's own error already covers that case)."""
    if meta.get("kind") != "graph":
        return {}
    slug = meta.get("project") or ""
    from . import graph as graphmod
    try:
        _name, _desc, docs, _efforts = graphmod.parse_fragment(payload, slug)
    except graphmod.GraphError:
        return {}
    existing_pg = reg.graphs.get(slug)
    existing_docs = existing_pg.documents if existing_pg else []
    store = meta.get("store") or ""
    if store:
        existing_docs = [d for d in existing_docs if d.store == store]
    existing_by_id = {d.drive_id: d for d in existing_docs}
    proposed_by_id = {d.drive_id: d for d in docs}

    def _differs(a, b) -> bool:
        return ((a.name, a.date_modified, a.web_url, a.doc_type, a.store)
                != (b.name, b.date_modified, b.web_url, b.doc_type, b.store))

    added = sorted(i for i in proposed_by_id if i not in existing_by_id)
    changed = sorted(i for i in proposed_by_id
                     if i in existing_by_id and _differs(existing_by_id[i], proposed_by_id[i]))
    removed = sorted(i for i in existing_by_id if i not in proposed_by_id)
    return {"added": added, "changed": changed, "removed": removed}


def _bodies(reg: Registry, meta: dict, payload: str) -> tuple[str, str, bool, str]:
    """(current_registry_text, proposed_text, acceptable, note) for one candidate —
    derived exactly as accept would route it, so the diff shows what accept would do."""
    if meta.get("kind") == "graph":
        # a knowledge-graph mapping: the diff is current vs. merged canonical JSON-LD
        from . import graph as graphmod
        slug = meta.get("project") or ""
        if slug not in reg.projects:
            return "", payload, False, f"unknown project {slug!r} for graph candidate"
        try:
            merged = _merged_graph(reg, slug, payload, meta.get("removals"),
                                   meta.get("effort_removals"))
        except graphmod.GraphError as e:
            return "", payload, False, f"invalid graph fragment: {e}"
        current = (graphmod.canonical_jsonld(reg.graphs[slug])
                   if slug in reg.graphs else "")
        return current, graphmod.canonical_jsonld(merged), True, ""
    if meta.get("sections"):
        cur = [(s["source"], reg.partials[s["source"]].body)
               for s in meta["sections"] if s["source"] in reg.partials]
        return (render.plain_document(cur) if cur else ""), payload, True, ""
    if meta.get("verbatim"):
        # a structured metadata edit (propose_meta_edit): the payload IS the full file
        # (frontmatter + body) — diff and write it whole, never strip frontmatter first.
        rp = meta.get("registry_path") or ""
        if not rp:
            return "", payload, False, "no registry route for a verbatim candidate"
        real = _real_registry_rel(reg, rp)
        dest = reg.root / "registry" / real
        if not dest.is_file():
            return "", payload, True, "new file — accept creates it verbatim"
        return dest.read_text(encoding="utf-8"), payload, True, ""
    rp = meta.get("registry_path") or ""
    planned = _planned_output(reg, meta.get("deploy_path", ""))
    if planned is not None and planned.kind != "text":
        # a captured config/artifact (e.g. a pre-cutover mcp_config.json): its
        # canonical source is connections/, never a registry prose file
        return "", payload, False, (
            "generated config — not registry prose. If the edit is wanted, apply it to "
            "the canonical source (connections/servers.yaml) and redeploy; then reject.")
    if not rp:
        return "", payload, False, (
            "no registry route — generated config or unrouted content. Review it, fix "
            "the canonical source if warranted, then reject.")
    sources = meta.get("sources")
    if sources is None and planned is not None:
        sources = planned.sources
    if sources is not None and len(sources) > 1:
        cur = [(s, reg.partials[s].body) for s in sources if s in reg.partials]
        return (render.plain_document(cur) if cur else ""), payload, False, (
            "multi-source document captured without a per-section base — route the "
            "edit into its partial(s) by hand, then reject this candidate.")
    if not rp.endswith(".md"):
        # invariant: prose stays prose — only Markdown routes mechanically; YAML
        # (manifests, servers) is structural and gets merged by hand
        return "", payload, False, (
            f"registry path {rp!r} is not Markdown prose — apply it by hand if "
            "warranted, then reject.")
    proposed = (render.strip_frontmatter(payload)
                if rp.endswith("SKILL.md") else payload)
    if rp in reg.partials:
        return reg.partials[rp].body, proposed, True, ""
    skill = next((s for s in reg.skills.values() if s.rel == rp), None)
    if skill is not None:
        return skill.body, proposed, True, ""
    dest = reg.root / "registry" / rp
    if dest.is_file():
        return render.strip_frontmatter(dest.read_text(encoding="utf-8")), proposed, True, ""
    return "", payload, True, "new file — accept creates it verbatim"


def _planned_output(reg: Registry, deploy_path: str):
    """The output currently planned at deploy_path, if any — the fallback context for
    candidates captured before meta recorded `sources`."""
    if not deploy_path:
        return None
    for machine in reg.machines:
        for o in plan_machine(reg, machine):
            if o.deploy_path == deploy_path:
                return o
    return None


def _current_source_text(reg: Registry, meta: dict) -> str | None:
    """Current on-disk text for a drift/verbatim candidate's registry_path — the same
    routing _bodies() diffs against, factored out so propose_edit/propose_meta_edit can
    snapshot a `registry_base_hash` at capture time and _stale() can detect drift
    against it later. None when there's no current file yet (a new-file candidate)."""
    rp = meta.get("registry_path") or ""
    if not rp:
        return None
    if meta.get("verbatim"):
        real = _real_registry_rel(reg, rp)
        dest = reg.root / "registry" / real
        return dest.read_text(encoding="utf-8") if dest.is_file() else None
    if rp in reg.partials:
        return reg.partials[rp].body
    skill = next((s for s in reg.skills.values() if s.rel == rp), None)
    if skill is not None:
        return skill.body
    dest = reg.root / "registry" / rp
    return (render.strip_frontmatter(dest.read_text(encoding="utf-8"))
            if dest.is_file() else None)


def _stale(reg: Registry, meta: dict) -> bool | None:
    """Has the registry moved since this candidate was captured? None = unknowable
    (no base recorded, or the deployed render flavor can't be reconstructed here)."""
    if meta.get("sections"):
        for s in meta["sections"]:
            p = reg.partials.get(s["source"])
            if p is None:
                return True
            # `s["text"]` is the EXPANDED section text recorded at deploy (planner runs
            # the personalization pass before it lands in the lockfile/meta); `p.body` is
            # always the placeholder form. Fold the recorded text back through this
            # partial's own tokens before comparing, or every personalized partial would
            # show as permanently stale regardless of whether it actually changed.
            reversed_text = render.reverse_expand_placeholders(reg, p.body, s["text"].strip("\n"))
            if p.body != reversed_text:
                return True
        return False
    registry_base_hash = meta.get("registry_base_hash") or ""
    if registry_base_hash:
        # console-authored candidates (propose_edit / propose_meta_edit) record the
        # exact current text at propose time — a file that vanished since counts as
        # drift too (accept would otherwise silently recreate it from stale content).
        current = _current_source_text(reg, meta)
        if current is None:
            return True
        return sha256(current.encode("utf-8")) != registry_base_hash
    base_hash = meta.get("base_hash") or ""
    if not base_hash:
        return None
    rp = meta.get("registry_path") or ""
    tool = (meta.get("source") or {}).get("tool") or ""
    try:
        if rp.endswith("SKILL.md"):
            skill = next((s for s in reg.skills.values() if s.rel == rp), None)
            if skill is None:
                return None
            return sha256(render.render_skill(skill, tool).encode("utf-8")) != base_hash
        if rp in reg.partials:
            doc = render.plain_document([(rp, reg.partials[rp].body)])
            return sha256(doc.encode("utf-8")) != base_hash
    except (ValueError, KeyError):
        return None
    return None


def _diff_rows(current: str, proposed: str) -> list[dict]:
    """Side-by-side line rows: {t: eq|chg|del|ins, l: str|None, r: str|None}.
    Plain data for the client to render — no HTML generated server-side."""
    a = current.rstrip("\n").split("\n") if current else []
    b = proposed.rstrip("\n").split("\n") if proposed else []
    rows: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            rows.extend({"t": "eq", "l": a[i1 + k], "r": b[j1 + k]}
                        for k in range(i2 - i1))
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            left = a[i1 + k] if i1 + k < i2 else None
            right = b[j1 + k] if j1 + k < j2 else None
            t = "chg" if left is not None and right is not None else \
                ("del" if right is None else "ins")
            rows.append({"t": t, "l": left, "r": right})
    return rows


# ── decisions ────────────────────────────────────────────────────────────────
def decide(reg: Registry, candidate_id: str, decision: str, reason: str = "",
          force: bool = False) -> dict:
    """Accept (route into the registry) or reject a candidate. Either way the folder
    is removed and one line lands in inbox/decisions.jsonl.

    An accept whose candidate has drifted (_stale() is True — the registry moved since
    capture) is refused unless `force` is set: the client-side disabled-Accept-button
    was cosmetic only (the client can't be trusted to enforce this), so the gate lives
    here too. `force` still routes through the full accept path below — same
    revalidation, same decisions.jsonl entry — it only skips the staleness refusal."""
    if decision not in ("accept", "reject"):
        return {"ok": False, "error": f"unknown decision {decision!r}"}
    inbox = loader.inbox_dir(reg).resolve()
    if any(sep in candidate_id for sep in ("/", "\\")) or candidate_id in ("", ".", ".."):
        return {"ok": False, "error": "invalid candidate id"}
    folder = inbox / candidate_id
    if not folder.is_dir() or not (folder / "meta.yaml").is_file():
        return {"ok": False, "error": f"unknown candidate {candidate_id!r}"}
    meta = yaml.safe_load((folder / "meta.yaml").read_text(encoding="utf-8")) or {}
    changed: list[str] = []
    warnings: list[str] = []
    if decision == "accept":
        payload_file = next((f for f in sorted(folder.iterdir())
                             if f.is_file() and f.name != "meta.yaml"), None)
        payload = (payload_file.read_text(encoding="utf-8", errors="replace")
                   if payload_file else "")
        _cur, _prop, acceptable, note = _bodies(reg, meta, payload)
        if not acceptable:
            return {"ok": False, "error": note}
        # staleness is only meaningful once the candidate is otherwise acceptable — a
        # boundary-straddling or unroutable candidate should surface ITS specific error,
        # not a generic "moved" one that would mask it.
        if _stale(reg, meta) and not force:
            return {"ok": False, "stale": True,
                    "error": "registry moved since this candidate was captured — "
                             "review the diff, then re-propose or force accept"}
        if meta.get("kind") == "graph":
            # a knowledge-graph mapping upserts into registry/graph/, not prose routing
            changed, err = _apply_graph_candidate(reg, meta, payload)
            if err:
                return {"ok": False, "error": err}
        else:
            verbatim = bool(meta.get("verbatim"))
            if verbatim:
                # the candidate sat on disk as untrusted text since propose — re-run the
                # same frontmatter/target/binding checks propose_meta_edit applied before
                # it ever reaches route_into_registry's verbatim write.
                verr = _revalidate_verbatim(reg, meta, payload)
                if verr:
                    return {"ok": False, "error": verr}
            sections = ([(s["source"], s["text"]) for s in meta["sections"]]
                        if meta.get("sections") else None)
            changed, warnings, err = route_into_registry(
                reg, meta.get("registry_path") or "", payload, sections=sections,
                keep_frontmatter=verbatim)
            if err:
                return {"ok": False, "error": err}
            # sync supporting files (examples/, scripts/) alongside the skill — ONLY
            # when the candidate explicitly carries a resources block (R4: absent must
            # never touch existing files; an explicit empty set deletes them). Runs
            # regardless of whether `changed` is non-empty — a resources-only edit
            # (SKILL.md body/frontmatter untouched) must still sync its files.
            rp = meta.get("registry_path") or ""
            if rp.endswith("SKILL.md") and meta.get("resources_provided"):
                real = _real_registry_rel(reg, rp)
                _sync_skill_resources(reg.root / "registry" / real, folder)
    entry = {
        "id": candidate_id,
        "decision": decision,
        "registry_path": meta.get("registry_path") or "",
        "kind": meta.get("kind", ""),
        "source": meta.get("source") or {},
        "decided_at": _now(),
        "reason": reason,
        "changed": changed,
    }
    with (inbox / DECISIONS).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    shutil.rmtree(folder)
    return {"ok": True, "decision": decision, "changed": changed, "warnings": warnings}


# ── knowledge graph (kind: graph candidates — the one human-gated valve) ──────
def _graph_dir(reg: Registry, slug: str) -> str:
    """`graph` or `local/graph`, depending on whether the project lives in the overlay.
    A local project's graph MUST land under registry/local/graph/ — the loader reads core
    graphs only when no overlay projects exist, so a core write would never be loaded."""
    return "local/graph" if (reg.projects.get(slug) or {}).get("_is_local") else "graph"


def _graph_rel(reg: Registry, slug: str) -> str:
    """Registry-relative path of a project's graph file (e.g. `local/graph/apdict.jsonld`)."""
    return f"{_graph_dir(reg, slug)}/{slug}.jsonld"


def _graph_file(reg: Registry, slug: str) -> Path:
    return reg.root / "registry" / _graph_dir(reg, slug) / f"{slug}.jsonld"


def _merged_graph(reg: Registry, slug: str, fragment_text: str,
                  removals: list[str] | None = None,
                  effort_removals: list[str] | None = None):
    """The project graph as it WOULD be after accepting this candidate: the existing
    graph (or a fresh one) with the fragment's documents and efforts upserted,
    `removals` dropped, and `effort_removals` removed (resetting their child docs to
    project root). Pure — writes nothing. Raises graph.GraphError on an invalid
    fragment or a missing-name new project. Effort removals are applied before effort
    and doc upserts so any re-parented docs in the fragment land cleanly."""
    from . import graph as graphmod
    name, desc, docs, efforts = graphmod.parse_fragment(fragment_text, slug)
    path = _graph_file(reg, slug)
    if slug in reg.graphs:
        base = reg.graphs[slug]
    elif path.is_file():
        base = graphmod.load_project_graph(path)
    else:
        pname = name or (reg.projects.get(slug) or {}).get("name")
        if not pname:
            raise graphmod.GraphError(
                f"no graph yet for {slug!r} and the fragment has no Project node — include "
                f"the Project node or seed registry/graph/{slug}.jsonld first")
        base = graphmod.ProjectGraph(slug=slug, name=pname, description=desc or "",
                                     documents=[], path=path)
    if name:
        base.name = name
    if desc:
        base.description = desc
    # effort removals first — resets child docs before any upserts land
    for eid in (effort_removals or []):
        eid = str(eid).strip()
        if eid:
            base = graphmod.remove_effort(base, eid)
    from dataclasses import replace as _dc_replace
    for e in efforts:
        # keep every parsed field (notably org_domain) — only normalise the parent IRI;
        # a positional reconstruction here would silently drop fields added later.
        base = graphmod.upsert_effort(base, _dc_replace(e, is_part_of=base.iri))
    for d in docs:
        base = graphmod.upsert_document(base, d)
    for rid in (removals or []):
        rid = str(rid).strip()
        if rid:
            base = graphmod.remove_document(base, rid)
    base.path = path
    return base


def _apply_graph_candidate(reg: Registry, meta: dict, payload: str) -> tuple[list[str], str | None]:
    """Accept a graph candidate: upsert the fragment into registry/graph/<slug>.jsonld,
    written canonically. Returns (changed_paths, error).

    A doc dropped by `removals` is also auto-dismissed (moved to the Recovery list) so
    it stops resurfacing in Discovery just because it's no longer mapped — the staged
    snapshot that surfaced it originally is never pruned. Snapshotted from the graph
    BEFORE the merge (the fragment carries no metadata for a pure removal), and only
    once the write has actually succeeded."""
    from . import graph as graphmod
    from .io import write_text
    slug = meta.get("project") or ""
    if slug not in reg.projects:
        return [], f"unknown project {slug!r} for graph candidate"
    removals = [str(r) for r in (meta.get("removals") or [])]
    removed_docs = []
    if removals:
        existing = reg.graphs.get(slug)
        by_id = {d.drive_id: d for d in existing.documents} if existing else {}
        removed_docs = [
            {"id": rid, "name": by_id[rid].name, "dateModified": by_id[rid].date_modified,
             "webUrl": by_id[rid].drive_url}
            for rid in removals if rid in by_id]
    try:
        merged = _merged_graph(reg, slug, payload, meta.get("removals"),
                               meta.get("effort_removals"))
        write_text(_graph_file(reg, slug), graphmod.canonical_jsonld(merged))
    except graphmod.GraphError as e:
        return [], f"invalid graph fragment: {e}"
    if removed_docs:
        dismiss_docs(reg, slug, removed_docs, source="removal")
    return [_graph_rel(reg, slug)], None


def _graph_note(n_docs: int, n_removals: int,
                n_efforts: int = 0, n_effort_removals: int = 0) -> str:
    """Human-readable summary of a graph candidate for the inbox card."""
    parts = []
    if n_docs:
        parts.append(f"{n_docs} document mapping(s)")
    if n_removals:
        parts.append(f"{n_removals} removal(s)")
    if n_efforts:
        parts.append(f"{n_efforts} effort(s)")
    if n_effort_removals:
        parts.append(f"{n_effort_removals} effort removal(s)")
    return (" + ".join(parts) or "no changes") + " proposed in the operator console"


# Built from the loader's whitelist so the console accepts exactly the set the
# compiler deploys — one source of truth, never a second hand-kept list.
_RESOURCE_PATH_RE = re.compile(
    r"^(" + "|".join(loader._SKILL_RESOURCE_DIRS) + r")/[^/].*[^/]$")


def _write_resource_file(folder: Path, relpath: str, text: str) -> None:
    """Write one skill supporting file into a candidate folder, under one of the
    resource subdirectories the loader scans (loader._SKILL_RESOURCE_DIRS)."""
    relpath = str(relpath).replace("\\", "/").strip()
    if not _RESOURCE_PATH_RE.match(relpath) or ".." in PurePosixPath(relpath).parts:
        raise ValueError(f"invalid resource path {relpath!r} — must be under one of "
                         f"{'/, '.join(loader._SKILL_RESOURCE_DIRS)}/ (no '..')")
    dest = folder / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(str(text), encoding="utf-8", newline="\n")


def _candidate_resources(folder: Path) -> dict[str, str]:
    """Supporting files (loader._SKILL_RESOURCE_DIRS subdirectories) staged alongside a
    skill candidate's payload, for the console's Supporting Files panel. Empty if the
    candidate carries none."""
    out: dict[str, str] = {}
    for sub in loader._SKILL_RESOURCE_DIRS:
        subdir = folder / sub
        if not subdir.is_dir():
            continue
        for f in sorted(subdir.rglob("*")):
            if f.is_file():
                out[f.relative_to(folder).as_posix()] = f.read_text(
                    encoding="utf-8", errors="replace")
    return out


def _sync_skill_resources(dest_skill_md: Path, candidate_folder: Path) -> None:
    """Replace a skill's resource directories (loader._SKILL_RESOURCE_DIRS) with what
    the candidate carries. Only ever called when the candidate's meta marked
    `resources_provided` (R4: an absent resources block must never touch existing files)
    — an explicit empty set deletes the directories, a populated one replaces them
    wholesale."""
    dest_dir = dest_skill_md.parent
    for sub in loader._SKILL_RESOURCE_DIRS:
        existing = dest_dir / sub
        if existing.is_dir():
            shutil.rmtree(existing)
        src = candidate_folder / sub
        if src.is_dir():
            shutil.copytree(src, existing)


def _write_candidate(reg: Registry, slug: str, meta: dict, payload_filename: str,
                     payload_text: str, resources: dict[str, str] | None = None) -> str:
    """Create inbox/<ts>--console--<slug>[-N]/ with meta.yaml + one payload file (+ any
    resource files under examples/, scripts/). Shared by every propose_* function — the
    console never writes registry/ directly (invariant #3), it only ever adds a
    candidate here. Returns the folder name (candidate id)."""
    inbox = loader.inbox_dir(reg)
    inbox.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    # mkdir() itself is the existence check — two concurrent requests (e.g. a
    # double-clicked Propose button) racing a separate exists()-then-mkdir() would
    # otherwise both pass the check and one loses with an uncaught FileExistsError,
    # which the server has no handler for: it drops the connection with no HTTP
    # response, surfacing to the browser as a bare "Failed to fetch".
    folder = inbox / f"{ts}--console--{slug}"
    n = 2
    while True:
        try:
            folder.mkdir()
            break
        except FileExistsError:
            folder = inbox / f"{ts}--console--{slug}-{n}"
            n += 1
    (folder / "meta.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (folder / payload_filename).write_text(payload_text, encoding="utf-8")
    if resources is not None:
        for relpath, text in resources.items():
            _write_resource_file(folder, relpath, text)
    return folder.name


def propose_graph_change(reg: Registry, slug: str, documents: list[dict],
                         removals: list[str] | None = None, reason: str = "",
                         efforts: list[dict] | None = None,
                         effort_removals: list[str] | None = None,
                         store: str = "") -> dict:
    """Save proposed document and effort mappings as a `kind: graph` inbox candidate.
    Writes only inbox/, never registry/ (invariant #3).

    `documents` is a list of {id, name, description, dateModified, parentId?} to
    upsert; `removals` is a list of document IDs to drop. `efforts` is a list of
    {id, name, description, orgDomain?} to upsert; `effort_removals` is a list of
    effort IDs to remove. A candidate may carry only removals (no upserts).
    `parentId` in a document dict is the effort ID (or "" / omitted for project root).

    `store` (optional) is the document_store server key this candidate's documents were
    enumerated from — a multi-store project's connect loop proposes ONE candidate per
    store, so every document in the batch shares it; a document dict may still carry its
    own `store` key to override (e.g. a hand-curated console edit). Recorded on the
    candidate's meta so the review UI can label which store it's for. IDs are store-native
    (a document is identified by its connector-provided ID alone), so a store-A candidate's
    documents can only ever carry store-A IDs — the upsert below (matched by drive_id) never
    touches a different store's nodes.

    The fragment always includes ALL current + proposed efforts so that document
    isPartOf links validate self-consistently. Returns {ok, id, registry_path} or
    {ok: False, error}."""
    from . import graph as graphmod
    if slug not in reg.projects:
        return {"ok": False, "error": f"unknown project {slug!r}"}

    # ── parse document dicts ──────────────────────────────────────────────────
    # An upsert replaces the whole node, so a caller that doesn't send `type`/`store` (an
    # older console payload) must not wipe an existing annotation — preserve each from the
    # current graph when the key is absent.
    existing = {d.drive_id: d for d in (reg.graphs.get(slug).documents
                                        if reg.graphs.get(slug) else [])}
    docs = []
    for d in documents:
        try:
            parent_id = str(d.get("parentId", "")).strip()
            parent_iri = (graphmod.CREATIVE_WORK_NS + parent_id) if parent_id else ""
            did = str(d["id"]).strip()
            prior = existing.get(did)
            docs.append(graphmod.Document(
                drive_id=did, name=str(d["name"]).strip(),
                description=str(d.get("description", "")).strip(),
                date_modified=str(d["dateModified"]).strip(),
                is_part_of=parent_iri,
                keywords=str(d.get("keywords", "")).strip(),
                web_url=str(d.get("webUrl", "")).strip(),
                doc_type=(str(d["type"]).strip() if "type" in d
                          else (prior.doc_type if prior else "")),
                store=(str(d["store"]).strip() if "store" in d
                      else (store or (prior.store if prior else "")))))
        except KeyError as e:
            return {"ok": False, "error": f"document missing required field {e}"}

    removals = [r for r in (str(x).strip() for x in (removals or [])) if r]
    effort_removals = [r for r in (str(x).strip() for x in (effort_removals or [])) if r]

    # A removal whose ID is also being upserted is contradictory — the upsert wins.
    upsert_ids = {d.drive_id for d in docs}
    removals = [r for r in removals if r not in upsert_ids]

    # ── build effective efforts for the fragment ──────────────────────────────
    # Start with existing efforts, apply proposed upserts, remove deleted ones.
    # This ensures the fragment is self-consistent so parse_fragment can validate it.
    existing_pg = reg.graphs.get(slug)
    proj_iri = graphmod.PROJECT_NS + slug
    effective_efforts: dict[str, graphmod.CreativeWork] = {
        e.id: e for e in (existing_pg.efforts if existing_pg else [])}
    _valid_domains = loader.known_org_domains(reg)
    for e_dict in (efforts or []):
        _dom = str(e_dict.get("orgDomain", "")).strip()
        if _dom and _dom not in _valid_domains:
            # reject here, not at accept time — an unknown domain written into the
            # graph would fail loader validation and break every subsequent compile
            return {"ok": False, "error": f"unknown org domain {_dom!r}; valid: "
                                          f"{', '.join(sorted(_valid_domains))}"}
        try:
            eid = str(e_dict["id"]).strip()
            effective_efforts[eid] = graphmod.CreativeWork(
                id=eid, name=str(e_dict["name"]).strip(),
                description=str(e_dict.get("description", "")).strip(),
                is_part_of=proj_iri,
                org_domain=str(e_dict.get("orgDomain", "")).strip(),
                goal=str(e_dict.get("goal", "")).strip())
        except KeyError as ex:
            return {"ok": False, "error": f"effort missing required field {ex}"}
    for eid in effort_removals:
        effective_efforts.pop(eid, None)
    # Also remove from effort_removals any effort that is simultaneously being upserted.
    upsert_effort_ids = {str(e["id"]).strip() for e in (efforts or []) if "id" in e}
    effort_removals = [r for r in effort_removals if r not in upsert_effort_ids]

    if not docs and not removals and not efforts and not effort_removals:
        return {"ok": False, "error": "no documents to propose"}

    name = (reg.projects[slug].get("name")) or slug
    desc = reg.graphs[slug].description if slug in reg.graphs else ""
    fragment = graphmod.canonical_jsonld(
        graphmod.ProjectGraph(slug=slug, name=name, description=desc,
                              documents=docs, efforts=list(effective_efforts.values())))
    try:
        graphmod.parse_fragment(fragment, slug)          # defensive: must round-trip
    except graphmod.GraphError as e:
        return {"ok": False, "error": f"invalid document(s) or effort(s): {e}"}
    graph_rel = _graph_rel(reg, slug)
    meta = {
        "registry_path": graph_rel,
        "kind": "graph",
        "project": slug,
        "source": {"machine": socket.gethostname() or "console", "tool": "console"},
        "base_hash": "",
        "deploy_path": "",
        "captured_at": _now(),
        "note": _graph_note(len(docs), len(removals),
                            len(efforts or []), len(effort_removals)),
    }
    if removals:
        meta["removals"] = removals
    if effort_removals:
        meta["effort_removals"] = effort_removals
    if reason:
        meta["reason"] = reason
    if store:
        meta["store"] = store
    cid = _write_candidate(reg, f"graph-{slug}", meta, "graph.jsonld", fragment)
    return {"ok": True, "id": cid, "registry_path": graph_rel}


# ── propose (a console prompt-library edit → inbox candidate) ─────────────────
def _slug_path(registry_path: str) -> str:
    """Filesystem-safe candidate slug from a registry path — last two parts, sans
    extension (mirrors commands._slug so console candidates name like captured ones)."""
    parts = PurePosixPath(registry_path).parts
    base = "-".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    base = base.rsplit(".", 1)[0] if "." in base.rsplit("/", 1)[-1] else base
    return re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower()


def propose_edit(reg: Registry, kind: str, ident: str, body: str,
                 reason: str = "") -> dict:
    """Save an edited prompt-library prompt as an inbox candidate. The console never
    writes registry/ directly (invariant #3) — it drops a candidate the existing Accept
    path (decide → route_into_registry) merges, exactly like a deploy-captured drift.
    Returns {ok, id, registry_path} or {ok: False, error}."""
    if kind == "skill":
        skill = reg.skills.get(ident)
        if skill is None:
            return {"ok": False, "error": f"unknown skill {ident!r}"}
        registry_path = skill.rel
        current_text = skill.body
    elif kind == "prompt":
        prompt = reg.prompts.get(ident)
        if prompt is None:
            return {"ok": False, "error": f"unknown prompt {ident!r}"}
        registry_path = prompt.rel
        current_text = prompt.body
    elif kind == "partial":
        logical = _partial_logical(ident)
        if logical not in reg.partials:
            return {"ok": False, "error": f"unknown partial {ident!r}"}
        registry_path = ident
        current_text = reg.partials[logical].body
    else:
        return {"ok": False, "error": f"unknown kind {kind!r}"}
    # registry_path is registry-controlled (a known skill.rel / partial key), but guard
    # before it becomes a folder + file name — only Markdown prose routes mechanically.
    if ".." in registry_path or not registry_path.endswith(".md"):
        return {"ok": False, "error": f"unroutable registry path {registry_path!r}"}
    meta = {
        "registry_path": registry_path,
        "kind": "drift",
        "source": {"machine": socket.gethostname() or "console", "tool": "console"},
        "base_hash": "",          # legacy deploy-capture field — unused for console edits
        # the exact current body at propose time, so _stale() can detect a registry
        # change before this candidate is accepted (a console edit has no deploy-time
        # base to compare against otherwise — see docs/managing-state.md FM2 fix).
        "registry_base_hash": sha256(current_text.encode("utf-8")),
        "deploy_path": "",        # not a deployed file; routing comes from registry_path
        "sources": [registry_path],
        "captured_at": _now(),
        "note": "edited in the operator console prompt library",
    }
    if reason:
        meta["reason"] = reason
    cid = _write_candidate(reg, _slug_path(registry_path), meta,
                           PurePosixPath(registry_path).name, body)
    return {"ok": True, "id": cid, "registry_path": registry_path}


# ── structured metadata editing (Track A — no raw YAML ever reaches the operator) ──
# Per-kind editable whitelist: `name` is deliberately never editable (it must stay in
# sync with the skill's folder / the prompt's registered identity). Everything else in
# the skill/prompt's frontmatter that isn't listed here (e.g. a skill's `hermes:` block)
# passes through untouched — _validate_meta_fields only ever overlays whitelisted keys
# onto a copy of the current frontmatter, it never drops unknown ones.
_SKILL_META_WHITELIST = {"description", "version", "author", "license", "platforms",
                         "targets", "category", "extends_skill", "extends_role", "scope"}
_PROMPT_META_WHITELIST = {"description", "version", "category", "targets"}


def _meta_whitelist(kind: str) -> set[str]:
    return _SKILL_META_WHITELIST if kind == "skill" else _PROMPT_META_WHITELIST


def _meta_dict(fm: dict, whitelist: set[str]) -> dict:
    """The editable-field subset of a skill/prompt's frontmatter, for the console's
    metadata panel. List-shaped fields default to [] rather than "" when absent."""
    return {k: fm.get(k, [] if k in ("targets", "platforms") else "") for k in whitelist}


def _validate_meta_fields(kind: str, current_fm: dict, fields: dict) -> tuple[dict, str | None]:
    """Overlay whitelisted `fields` onto a copy of `current_fm`. Returns
    (new_frontmatter, error) — error is None on success. `fields` may be a strict subset
    (or empty — a body-only edit); anything not named in `fields` is left untouched."""
    whitelist = _meta_whitelist(kind)
    unknown = set(fields) - whitelist
    if unknown:
        return {}, f"unknown or non-editable field(s) {sorted(unknown)}"
    merged = dict(current_fm)
    for key, val in fields.items():
        if key == "targets":
            if not isinstance(val, list) or not val:
                return {}, "targets must be a non-empty list"
            bad = set(val) - loader.KNOWN_TARGETS
            if bad:
                return {}, f"unknown target(s) {sorted(bad)}"
            merged["targets"] = [str(t) for t in val]
        elif key == "platforms":
            if not isinstance(val, list) or not val:
                return {}, "platforms must be a non-empty list"
            merged["platforms"] = [str(p) for p in val]
        else:
            merged[key] = str(val)
    return merged, None


def _check_target_binding(reg: Registry, skill_name: str, new_targets: list[str]) -> str | None:
    """Refuse a skill-target edit that drops 'claude-code' while a project still binds
    the skill — that binding requires claude-code (loader._validate enforces it at
    compile time; this catches the break at propose/accept time instead)."""
    if "claude-code" in new_targets:
        return None
    bound = sorted(slug for slug, proj in reg.projects.items()
                   if skill_name in (proj.get("skills") or []))
    if bound:
        return (f"cannot remove 'claude-code' from {skill_name!r} targets — bound to "
                f"project(s) {bound}")
    return None


def propose_meta_edit(reg: Registry, kind: str, ident: str, fields: dict, body: str,
                      reason: str = "", resources: dict[str, str] | None = None) -> dict:
    """Propose a structured metadata + body edit for a skill or prompt. The server
    reassembles YAML frontmatter itself (current frontmatter, whitelisted fields
    overlaid, `yaml.safe_dump`'d) — the operator only ever fills in form fields and the
    body textarea, never raw YAML. The candidate carries `verbatim: true` so accept
    writes the full file (frontmatter + body) rather than stripping frontmatter first.

    `resources` (skill only) is the FULL replacement set of supporting files
    (examples/*, scripts/*) — omit (None) to leave a skill's existing resources
    untouched; pass {} to delete them all; pass a populated dict to replace them
    wholesale (R4: absent vs. empty is a meaningful distinction, recorded as
    `resources_provided` in the candidate's meta so accept applies it correctly).
    Returns {ok, id, registry_path} or {ok: False, error}."""
    if kind == "skill":
        obj = reg.skills.get(ident)
        if obj is None:
            return {"ok": False, "error": f"unknown skill {ident!r}"}
    elif kind == "prompt":
        obj = reg.prompts.get(ident)
        if obj is None:
            return {"ok": False, "error": f"unknown prompt {ident!r}"}
    else:
        return {"ok": False, "error": f"unknown kind {kind!r} for metadata editing"}
    registry_path = obj.rel
    if ".." in registry_path or not registry_path.endswith(".md"):
        return {"ok": False, "error": f"unroutable registry path {registry_path!r}"}
    if not str(body).strip():
        return {"ok": False, "error": "body is required"}

    fields = fields or {}
    new_fm, err = _validate_meta_fields(kind, obj.frontmatter, fields)
    if err:
        return {"ok": False, "error": err}
    if kind == "skill" and "targets" in fields:
        bind_err = _check_target_binding(reg, ident, new_fm["targets"])
        if bind_err:
            return {"ok": False, "error": bind_err}
    if kind == "skill":
        ext_err = loader.validate_skill_extension(reg, ident, new_fm)
        if ext_err:
            return {"ok": False, "error": ext_err}
        scope_err = loader.validate_skill_scope(ident, new_fm)
        if scope_err:
            return {"ok": False, "error": scope_err}

    payload = ("---\n" + yaml.safe_dump(new_fm, sort_keys=False, allow_unicode=True)
              + "---\n\n" + str(body).rstrip("\n") + "\n")
    meta = {
        "registry_path": registry_path,
        "kind": "drift",
        "verbatim": True,
        "source": {"machine": socket.gethostname() or "console", "tool": "console"},
        "base_hash": "",
        "deploy_path": "",
        "sources": [registry_path],
        "captured_at": _now(),
        "note": "metadata edited in the operator console",
    }
    # snapshot the current full file (frontmatter + body) at propose time — a verbatim
    # candidate diffs the whole file, so its stale-check base must be the whole file too.
    real = _real_registry_rel(reg, registry_path)
    dest = reg.root / "registry" / real
    if dest.is_file():
        meta["registry_base_hash"] = sha256(dest.read_text(encoding="utf-8").encode("utf-8"))
    if reason:
        meta["reason"] = reason
    if kind == "skill" and resources is not None:
        meta["resources_provided"] = True
    try:
        cid = _write_candidate(reg, _slug_path(registry_path), meta,
                               PurePosixPath(registry_path).name, payload,
                               resources=resources if kind == "skill" else None)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "id": cid, "registry_path": registry_path}


_FM_LINE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def _revalidate_verbatim(reg: Registry, meta: dict, payload: str) -> str | None:
    """Re-run propose_meta_edit's checks on a verbatim candidate at accept time — it sat
    on disk as untrusted text since propose (this module's own security note). Returns
    an error string, or None when the frontmatter is well-formed and still passes."""
    rp = meta.get("registry_path") or ""
    m = _FM_LINE.match(payload)
    if not m:
        return f"verbatim candidate {rp!r} has no YAML frontmatter"
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return f"verbatim candidate {rp!r} has invalid frontmatter: {e}"
    if not isinstance(fm, dict):
        return f"verbatim candidate {rp!r} frontmatter must be a mapping"
    if rp.endswith("SKILL.md"):
        skill = next((s for s in reg.skills.values() if s.rel == rp), None)
        if skill is None:
            return None   # a brand-new file — nothing registered yet to validate against
        if fm.get("name") != skill.frontmatter.get("name"):
            return f"{rp!r}: 'name' must not change"
        targets = fm.get("targets")
        if not isinstance(targets, list) or not targets:
            return f"{rp!r}: targets must be a non-empty list"
        bad = set(targets) - loader.KNOWN_TARGETS
        if bad:
            return f"{rp!r}: unknown target(s) {sorted(bad)}"
        bind_err = _check_target_binding(reg, skill.name, [str(t) for t in targets])
        if bind_err:
            return bind_err
        ext_err = loader.validate_skill_extension(reg, skill.name, fm)
        if ext_err:
            return ext_err
        scope_err = loader.validate_skill_scope(skill.name, fm)
        if scope_err:
            return scope_err
    else:
        prompt = next((p for p in reg.prompts.values() if p.rel == rp), None)
        if prompt is not None:
            if fm.get("name") != prompt.frontmatter.get("name"):
                return f"{rp!r}: 'name' must not change"
            targets = fm.get("targets", [])
            if targets and not isinstance(targets, list):
                return f"{rp!r}: targets must be a list"
            bad = set(targets or []) - loader.KNOWN_TARGETS
            if bad:
                return f"{rp!r}: unknown target(s) {sorted(bad)}"
    return None


_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def propose_new_skill(reg: Registry, name: str, frontmatter_fields: dict,
                      body: str, reason: str = "", org_domain: str = "",
                      resources: dict[str, str] | None = None) -> dict:
    """Propose a brand-new skill as a `kind: new` inbox candidate. The console never
    writes registry/ directly (invariant #3) — accept routes through the same
    route_into_registry() path as an edit; since the target path doesn't exist yet,
    route_into_registry writes it verbatim, and _bodies() already reports it as a
    diff-free "new file" candidate. Always lands in the user's private overlay
    (registry/local/skills/<name>/SKILL.md), never core.

    `org_domain`, when set, is stamped into the frontmatter as-is — it marks this skill
    as a domain-template org (see loader.known_org_domains / org_index); propose_new_org_
    domain is the only caller that passes it. `frontmatter_fields` may also carry
    `extends_skill`/`extends_role` (the Org tab's "+ Extend department" button) —
    validated the same way a metadata edit is. `resources` seeds examples/*, scripts/*
    files alongside the new SKILL.md (optional).
    Returns {ok, id, registry_path} or {ok: False, error}."""
    name = str(name).strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    if not _SKILL_NAME_RE.match(name):
        return {"ok": False, "error": "name must be lowercase alphanumerics and hyphens "
                                       "(matches the existing skill slug convention)"}
    if name in reg.skills:
        return {"ok": False, "error": f"skill {name!r} already exists"}
    targets = frontmatter_fields.get("targets") or []
    if not isinstance(targets, list) or not targets:
        return {"ok": False, "error": "targets is required and must be a non-empty list"}
    bad = set(targets) - loader.KNOWN_TARGETS
    if bad:
        return {"ok": False, "error": f"unknown target(s) {sorted(bad)}"}
    if not str(body).strip():
        return {"ok": False, "error": "body is required"}
    meta_fm = {
        "name": name,
        "description": str(frontmatter_fields.get("description", "")),
        "version": str(frontmatter_fields.get("version", "") or "1.0.0"),
        "author": str(frontmatter_fields.get("author", "") or "console"),
        "license": str(frontmatter_fields.get("license", "") or "MIT"),
        "platforms": frontmatter_fields.get("platforms") or ["linux", "macos", "windows"],
        "targets": targets,
        "category": str(frontmatter_fields.get("category", "") or "general"),
    }
    if org_domain:
        meta_fm["org_domain"] = org_domain
    ext_skill = str(frontmatter_fields.get("extends_skill", "") or "").strip()
    ext_role = str(frontmatter_fields.get("extends_role", "") or "").strip()
    if ext_skill:
        meta_fm["extends_skill"] = ext_skill
    if ext_role:
        meta_fm["extends_role"] = ext_role
    ext_err = loader.validate_skill_extension(reg, name, meta_fm)
    if ext_err:
        return {"ok": False, "error": ext_err}
    registry_path = f"local/skills/{name}/SKILL.md"
    payload = ("---\n" + yaml.safe_dump(meta_fm, sort_keys=False, allow_unicode=True)
              + "---\n\n" + str(body).rstrip("\n") + "\n")
    meta = {
        "registry_path": registry_path,
        "kind": "new",
        "source": {"machine": socket.gethostname() or "console", "tool": "console"},
        "base_hash": "",
        "deploy_path": "",
        "captured_at": _now(),
        "note": ("new org domain created in the operator console" if org_domain
                 else "new skill created in the operator console"),
    }
    if reason:
        meta["reason"] = reason
    if resources is not None:
        meta["resources_provided"] = True
    try:
        cid = _write_candidate(reg, _slug_path(registry_path), meta, "SKILL.md", payload,
                               resources=resources)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "id": cid, "registry_path": registry_path}


def propose_new_org_domain(reg: Registry, domain: str, reason: str = "") -> dict:
    """Propose a brand-new org domain (the console's `+ ORG` button): a single `kind:
    new` skill candidate at registry/local/skills/org-<domain>/SKILL.md carrying
    `org_domain: <domain>` in its frontmatter plus a CEO/VP/Assistant template body (the
    same numbered-heading shape _parse_org_skill expects). Once accepted, the domain is
    immediately valid for a project's `org:` field (loader.known_org_domains) and
    appears in the console's Org tab domain switcher (org_index) — no separate routing
    table edit required, since domain discovery reads the skill's own frontmatter.
    Returns {ok, id, registry_path} or {ok: False, error}."""
    domain = str(domain).strip().lower()
    if not domain:
        return {"ok": False, "error": "domain is required"}
    if not _SKILL_NAME_RE.match(domain):
        return {"ok": False, "error": "domain must be lowercase alphanumerics and hyphens "
                                       "(matches the existing skill slug convention)"}
    if domain in loader.known_org_domains(reg):
        return {"ok": False, "error": f"org domain {domain!r} already exists"}
    name = f"org-{domain}"
    title = domain.replace("-", " ").title()
    body = (
        "# Instructions\n\n"
        "Use this when a project request needs real planning or multi-step execution — "
        f"not a quick lookup. Handle it as the owner's {title} organization. Truth over "
        "politeness: if the request is unsound, mis-scoped, or would incur unacceptable "
        "risk, say so as the CEO before anything is built.\n\n"
        "## 1. CEO — intent and objectives\n"
        "- Restate the request as concrete objectives and a clear definition of "
        "\"done\".\n\n"
        "## 2. VP — plan\n"
        "- Turn objectives into a concrete plan grounded in real project context.\n\n"
        "## 3. Assistant — execution\n"
        "- Execute the plan: gather context, draft, and report back.\n"
    )
    fields = {
        "description": f"Run a substantive request through the simulated {title} "
                       f"organization — CEO (intent), VP (plan), Assistant (execution).",
        "category": "productivity",
        "targets": ["hermes"],
    }
    return propose_new_skill(reg, name, fields, body, reason=reason, org_domain=domain)


def propose_new_prompt(reg: Registry, name: str, frontmatter_fields: dict,
                       body: str, reason: str = "") -> dict:
    """Propose a brand-new first-class prompt as a `kind: new` inbox candidate. The
    console never writes registry/ directly (invariant #3) — accept routes through
    route_into_registry(), which writes the file verbatim since the target path
    doesn't exist yet. Always lands in the user's private overlay
    (registry/local/prompts/<name>.md), never core.

    Prompts are simpler than skills: no author/license/platforms/scope/extends/resources.
    `targets` is optional — omitting it (or passing []) means console-only (not an error).
    Returns {ok, id, registry_path} or {ok: False, error}.
    """
    name = str(name).strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    if not _SKILL_NAME_RE.match(name):
        return {"ok": False, "error": "name must be lowercase alphanumerics and hyphens "
                                      "(matches the existing slug convention)"}
    if name in reg.prompts:
        return {"ok": False, "error": f"prompt {name!r} already exists"}
    if not str(body).strip():
        return {"ok": False, "error": "body is required"}
    targets = frontmatter_fields.get("targets") or []
    if not isinstance(targets, list):
        return {"ok": False, "error": "targets must be a list (may be empty for console-only)"}
    bad = set(targets) - loader.KNOWN_TARGETS
    if bad:
        return {"ok": False, "error": f"unknown target(s) {sorted(bad)}"}
    meta_fm = {
        "name": name,
        "description": str(frontmatter_fields.get("description", "")),
        "version": str(frontmatter_fields.get("version", "") or "1.0.0"),
        "category": str(frontmatter_fields.get("category", "") or "general"),
        "targets": targets,
    }
    registry_path = f"local/prompts/{name}.md"
    payload = ("---\n" + yaml.safe_dump(meta_fm, sort_keys=False, allow_unicode=True)
              + "---\n\n" + str(body).rstrip("\n") + "\n")
    meta = {
        "registry_path": registry_path,
        "kind": "new",
        "source": {"machine": socket.gethostname() or "console", "tool": "console"},
        "base_hash": "",
        "deploy_path": "",
        "captured_at": _now(),
        "note": "new prompt created in the operator console",
    }
    if reason:
        meta["reason"] = reason
    try:
        cid = _write_candidate(reg, _slug_path(registry_path), meta, f"{name}.md", payload)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "id": cid, "registry_path": registry_path}


# ── prompt library ───────────────────────────────────────────────────────────
_FAVORITES_FILE = "registry/local/prompt-favorites.yaml"


def _load_favorites(root) -> list[str]:
    """Prompt names the user has pinned, persisted in registry/local/prompt-favorites.yaml."""
    p = (root / _FAVORITES_FILE) if root else None
    if not p or not p.is_file():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        favs = data.get("favorites", [])
        return [str(f) for f in favs] if isinstance(favs, list) else []
    except Exception:
        return []


def _save_favorites(root, names: list[str]) -> None:
    """Write the favorites list back to registry/local/prompt-favorites.yaml."""
    p = root / _FAVORITES_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"favorites": sorted(set(names))}, allow_unicode=True),
        encoding="utf-8")


def toggle_favorite(root, name: str) -> list[str]:
    """Add or remove a prompt name from favorites. Returns the updated list."""
    favs = _load_favorites(root)
    if name in favs:
        favs = [f for f in favs if f != name]
    else:
        favs = favs + [name]
    _save_favorites(root, favs)
    return sorted(set(favs))


def _suppressed_example_partials(reg: Registry) -> set[str]:
    """Logical context-partial names bound by `example: true` projects — hidden from
    the Prompt Library once the user has overlay projects. The same step-aside
    convention as graph_index here and planner._suppressed_examples: shipped samples
    render only on a fresh clone, never on a configured fleet."""
    if not any(p.get("_is_local") for p in reg.projects.values()):
        return set()
    hidden: set[str] = set()
    for p in reg.projects.values():
        if p.get("example"):
            for path in (p.get("context") or {}).values():
                hidden.add(str(path).split("registry/", 1)[-1])
    return hidden


def prompt_index(reg: Registry) -> dict:
    """All registry prose organized into three sections for the Prompt Library tab.

    - prompts: first-class harness-agnostic assets (registry/prompts/)
    - skills: skill bodies (prompts with harness packaging)
    - partials: identity personas and context prose (minus example-project context once
      the user has their own projects — _suppressed_example_partials)

    Favorites are the user's pinned prompts, persisted in registry/local/prompt-favorites.yaml
    and surfaced so the UI can highlight them across sessions.
    """
    favorites = set(_load_favorites(reg.root))
    hidden_partials = _suppressed_example_partials(reg)
    prompts = [{
        "name": p.name,
        "description": p.frontmatter.get("description", ""),
        "category": p.category,
        "targets": p.targets,
        "body": p.body,
        "frontmatter": _meta_dict(p.frontmatter, _PROMPT_META_WHITELIST),
        "favorited": p.name in favorites,
    } for p in sorted(reg.prompts.values(), key=lambda p: (p.category, p.name))]
    skills = [{
        "name": s.name,
        "description": s.frontmatter.get("description", ""),
        "category": s.category,
        "targets": s.targets,
        "body": s.body,
        "frontmatter": _meta_dict(s.frontmatter, _SKILL_META_WHITELIST),
        "favorited": s.name in favorites,
        "resources": {relpath: r.text for relpath, r in s.resources.items()},
        "extends_skill": s.frontmatter.get("extends_skill", ""),
        "extends_role": s.frontmatter.get("extends_role", ""),
        # projects whose manifest `skills:` list names this skill — the read-only
        # "where does scope: project actually apply" view (renderSkillScopeSection).
        # Editing this list happens in the project manifest YAML directly; the console
        # doesn't write project manifests (see docs/managing-state.md, invariant #3).
        "bound_projects": sorted(slug for slug, proj in reg.projects.items()
                                 if s.name in (proj.get("skills") or [])),
    } for s in sorted(reg.skills.values(), key=lambda s: (s.category, s.name))]
    partials = [{
        "rel": p.rel,
        "group": ("identity" if _partial_logical(p.rel).startswith("identity/")
                  else "projects" if _partial_logical(p.rel).startswith("context/projects/")
                  else "context"),
        "audience": p.audience,
        "body": p.body,
    } for p in sorted(reg.partials.values(), key=lambda p: p.rel)
        if _partial_logical(p.rel) not in hidden_partials]
    return {"prompts": prompts, "skills": skills, "partials": partials}


def _read_staging(path: Path, slug: str, is_unassigned: bool) -> dict:
    """Parse inbox/staging/*.json — one or more watched-scope LISTINGS (see
    staging.normalize_staging; legacy single-listing files still read as one) — into the
    console's staged-panel shape. `documents` is the union of every listing, deduped by id
    and tagged with the `scope_keys` that produced it (staging.merge_documents) — that
    plural tag is what lets a document watched by two overlapping scopes show once, and
    what the absence-provenance check in _in_scope_flags keys off of. `listings` carries
    each watch's own metadata (label-able scope, staged_at, doc count) for the console's
    watched-scopes strip, without repeating the documents a second time."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"ok": False, "error": "staging file is unreadable — re-stage from the CLI"}
    listings = staging_mod.normalize_staging(data)
    documents = staging_mod.merge_documents(listings)
    summaries = [{"scope_key": l["scope_key"], "label": l["label"],
                 "staged_at": l["staged_at"], "connector": l["connector"],
                 "scope": l["scope"], "count": len(l["documents"])}
                for l in listings]
    # Most-recent-first — the console's watched-scopes strip and the legacy single-stamp
    # display (top listing) both want the freshest watch surfaced first.
    summaries.sort(key=lambda s: s["staged_at"], reverse=True)
    return {"ok": True, "slug": slug, "documents": documents, "listings": summaries,
            "is_unassigned": is_unassigned}


def _dismiss_file(reg: Registry, slug: str, pool: str = "") -> tuple[Path, bool]:
    """Resolve which dismissed-list file backs `slug` for the given pool — mirrors
    load_staged's own fallback so a dismissal always lands beside whichever staging
    file Discovery is actually showing: pool=="unassigned" forces the shared file;
    otherwise the per-project file is used when the per-project staging file exists,
    else the shared unassigned file. Returns (path, is_unassigned)."""
    staging = loader.inbox_dir(reg) / "staging"
    unassigned = staging / "unassigned.dismissed.json"
    if pool == "unassigned":
        return unassigned, True
    if (staging / f"{slug}.json").is_file():
        return staging / f"{slug}.dismissed.json", False
    return unassigned, True


def _read_dismissed(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    docs = data.get("documents") if isinstance(data, dict) else None
    return docs if isinstance(docs, list) else []


def _write_dismissed(path: Path, docs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"documents": docs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def _in_scope_flags(reg: Registry, slug: str, docs: list[dict], pool: str) -> None:
    """Annotate each Recovery doc with `in_scope`: True (present in at least one current
    watched listing), False (provably gone), or None (unknowable). Named `in_scope`, not
    `in_store` — with more than one watched folder/query, presence is always relative to
    a scope, never a flat "is it in the store" fact.

    Staging listings ARE the store's truth as of their own `staged_at` — no connector call
    needed, so this stays offline (invariant #11). Absence is provable two ways:

    - a FULL (unscoped) listing exists and doesn't contain the doc — it enumerates the
      whole store, so its silence about anything is conclusive, regardless of which watch
      (if any) originally surfaced that doc;
    - a SCOPED listing exists whose scope_key matches one this doc's own `scope_keys`
      provenance (recorded at dismiss time — see dismiss_docs) says produced it, and that
      listing no longer contains it — the specific watch that once had it lost it (the
      folder scope narrowed, the file moved out, etc.), even though nothing here can speak
      for OTHER scopes the doc was never part of.

    Anything else is None: no listings at all, or only scoped listings unrelated to this
    doc's provenance. A None doc is never flagged and never purged — the operator sees no
    claim rather than a false one. This generalizes (and, for a single unscoped listing,
    reduces exactly to) the original single-listing rule."""
    staged = load_staged(reg, slug, pool)
    listings = staged.get("listings") or []
    if not staged.get("ok") or not listings:
        for d in docs:
            d["in_scope"] = None
        return
    present = {str(s.get("id")) for s in (staged.get("documents") or []) if s.get("id")}
    full_scope_present = any(staging_mod.is_full_scope(l["scope"]) for l in listings)
    current_keys = {l["scope_key"] for l in listings}
    for d in docs:
        did = str(d.get("id"))
        if did in present:
            d["in_scope"] = True
            continue
        own_keys = set(d.get("scope_keys") or [])
        if full_scope_present or (own_keys & current_keys):
            d["in_scope"] = False
        else:
            d["in_scope"] = None


def load_dismissed(reg: Registry, slug: str, pool: str = "") -> dict:
    """Read the Recovery list backing `slug` — the console's Recovery tab.

    Permanently dismissed documents are filtered out here: the console must never surface
    them again (undo means hand-editing the sidecar), while the record itself stays on disk
    so Discovery keeps filtering the id out too. Everything else is annotated with
    `in_scope` (see _in_scope_flags)."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return {"ok": False, "error": "invalid slug"}
    path, is_unassigned = _dismiss_file(reg, slug, pool)
    rows = _read_dismissed(path)
    docs = [d for d in rows if not d.get("permanent")]
    _in_scope_flags(reg, slug, docs, pool)
    # `all_ids` carries the PERMANENT rows too. Recovery renders `documents` (permanent
    # rows are hidden for good), but Discovery filters on the full id set — otherwise a
    # permanent dismissal, absent from `documents`, would reappear in Discovery: the exact
    # thing "permanent" promises it won't do.
    return {"ok": True, "slug": slug, "documents": docs,
            "all_ids": [str(d["id"]) for d in rows if d.get("id")],
            "is_unassigned": is_unassigned}


def dismiss_docs(reg: Registry, slug: str, docs: list[dict], pool: str = "",
                 source: str = "manual", permanent: bool = False) -> dict:
    """Move one or more documents from Discovery into the Recovery list backing
    `slug`/`pool` (see _dismiss_file). Idempotent — dismissing an already-dismissed id
    updates its entry in place rather than duplicating it. `source` is "manual" (the
    Discovery Dismiss action) or "removal" (auto-dismissed when accept drops the doc
    from the graph).

    `permanent` (the Recovery tab's "Permanently dismiss") hides the document from the
    Recovery UI for good while keeping the sidecar record — the id must stay in the
    dismissed set so Discovery never resurfaces it. Nothing is deleted from the store; the
    console is not a filesystem actor. Undo is deliberate friction: edit the
    `.dismissed.json` sidecar by hand.

    A `d` originating from a Discovery row carries `scope_keys` (which watched listing(s)
    produced it — see staging.merge_documents) — recorded here as provenance so
    _in_scope_flags can later tell "gone from the one scope that ever had it" from "outside
    every scope we're watching". A "removal" auto-dismissal (dropped from the registry
    graph, not from staging) carries none, and stays with none — that's correct: it never
    came from a watched scope in the first place."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return {"ok": False, "error": "invalid slug"}
    if not docs:
        return {"ok": False, "error": "no documents to dismiss"}
    path, _ = _dismiss_file(reg, slug, pool)
    existing = {d["id"]: d for d in _read_dismissed(path) if d.get("id")}
    now = _now()
    src = source if source in ("manual", "removal") else "manual"
    for d in docs:
        did = str(d.get("id") or "").strip()
        if not did:
            continue
        prev = existing.get(did) or {}
        rec = {
            "id": did, "name": d.get("name", ""), "dateModified": d.get("dateModified", ""),
            "webUrl": d.get("webUrl", ""), "dismissed_at": now, "source": src,
        }
        keys = [str(k) for k in (d.get("scope_keys") or []) if k]
        if keys:
            rec["scope_keys"] = keys
        elif prev.get("scope_keys"):
            # Re-dismissing the same id without fresh provenance (e.g. Recovery's
            # Permanently-dismiss button re-posts the existing record) keeps what was
            # already known rather than erasing it.
            rec["scope_keys"] = prev["scope_keys"]
        # A permanent record stays permanent: `permanent=False` is the *default* of every
        # ordinary dismissal, not an instruction to un-permanent an existing one. Only a
        # hand edit of the sidecar reverses it.
        if permanent or prev.get("permanent"):
            rec["permanent"] = True
        existing[did] = rec
    _write_dismissed(path, list(existing.values()))
    return {"ok": True}


def purge_dismissed(reg: Registry, slug: str, ids: list[str], pool: str = "") -> dict:
    """Drop Recovery rows for documents that are gone from the store — the "Clear missing"
    action. Identical mechanics to restore_docs (the record simply leaves the sidecar), but
    a distinct verb because the intent differs: restore means "show it in Discovery again",
    purge means "the store no longer has this, stop tracking it".

    Guarded server-side: only ids the CURRENT listings prove absent (`in_scope is False`)
    are purged. A stale browser tab, or a client that mislabels a row, therefore cannot
    purge a document that's still live in some watched scope."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return {"ok": False, "error": "invalid slug"}
    if not ids:
        return {"ok": False, "error": "no documents to clear"}
    path, _ = _dismiss_file(reg, slug, pool)
    rows = _read_dismissed(path)
    _in_scope_flags(reg, slug, rows, pool)
    missing = {str(d.get("id")) for d in rows if d.get("in_scope") is False}
    asked = {str(i) for i in ids}
    purge = asked & missing
    if not purge:
        return {"ok": False, "error": "those documents are still in a watched scope (or no "
                                      "listing can prove otherwise) — nothing cleared"}
    remaining = [{k: v for k, v in d.items() if k != "in_scope"}
                 for d in rows if str(d.get("id")) not in purge]
    _write_dismissed(path, remaining)
    return {"ok": True, "cleared": sorted(purge)}


def restore_docs(reg: Registry, slug: str, ids: list[str], pool: str = "") -> dict:
    """Remove one or more ids from the Recovery list backing `slug`/`pool` — the
    document reappears in Discovery on its next fetch."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return {"ok": False, "error": "invalid slug"}
    if not ids:
        return {"ok": False, "error": "no documents to restore"}
    path, _ = _dismiss_file(reg, slug, pool)
    id_set = {str(i) for i in ids}
    remaining = [d for d in _read_dismissed(path) if d.get("id") not in id_set]
    _write_dismissed(path, remaining)
    return {"ok": True}


def load_staged(reg: Registry, slug: str, pool: str = "") -> dict:
    """Read inbox/staging/<slug>.json (a connector-produced listing) for the console to
    curate offline. `pool == "unassigned"` forces the shared unassigned pool
    (inbox/staging/unassigned.json) regardless of per-project staging — the explicit toggle.
    Otherwise the per-project file is preferred, falling back to the unassigned pool when it
    is absent (so a projectless sync still surfaces). Never imports a connector."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return {"ok": False, "error": "invalid slug"}
    staging = loader.inbox_dir(reg) / "staging"
    unassigned = staging / "unassigned.json"
    if pool == "unassigned":
        if not unassigned.is_file():
            return {"ok": True, "slug": slug, "documents": [], "listings": [],
                    "is_unassigned": True}
        return _read_staging(unassigned, slug, True)
    path = staging / f"{slug}.json"
    if not path.is_file():
        # Fall back to the unassigned pool so that a projectless sync is surfaced in the
        # Knowledge Graph tab even before the user binds documents to a project.
        if not unassigned.is_file():
            return {"ok": True, "slug": slug, "documents": [], "listings": [],
                    "is_unassigned": False}
        return _read_staging(unassigned, slug, True)
    return _read_staging(path, slug, False)



def refresh_staging(reg: Registry, slug: str, pool: str = "", scope_key: str = "",
                    timeout: int = 180) -> dict:
    """Re-run the enumeration behind ONE watched listing — the Discovery pane's
    "↻ Refresh folder" button, i.e. the "watch a folder" story. `scope_key` picks which
    listing when a project watches more than one scope; omit it when there's exactly one
    (the common case) — with two or more listings and no scope_key, this refuses rather
    than guessing which watch the operator meant.

    Invariant #11 holds by CONSTRUCTION, not by good intentions: this shells out to the
    separate `build/mitos.py` entrypoint exactly as an operator would from a terminal.
    `compile.py` still imports no connector, no OAuth, no network code — the reach lives in
    a child process. (The console already runs compile/deploy; this is the same trust
    model on a localhost-only server.)

    Requires a scope recorded by a previous `--stage` run (bootstrap.stage_listing). A
    listing staged before scopes carried `store`/`recursive`, or staged with no scope at
    all, returns ok:False — the console falls back to showing the copyable CLI command,
    which is also the right answer for a store's FIRST stage (that one may need an
    interactive OAuth consent, which has no place in a web button). Re-staging the SAME
    scope replaces just that listing (stage_listing) — sibling watches are untouched, so
    the returned `staged` snapshot's OTHER listings carry whatever they had before this
    call ran."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return {"ok": False, "error": "invalid slug"}
    staged = load_staged(reg, slug, pool)
    if not staged.get("ok"):
        return {"ok": False, "error": staged.get("error") or "no staged listing to refresh"}
    listings = staged.get("listings") or []
    if not listings:
        return {"ok": False, "error": "nothing staged for this project yet — run the "
                                      "connect command once from a terminal first"}
    if scope_key:
        matches = [l for l in listings if l["scope_key"] == scope_key]
        if not matches:
            return {"ok": False, "error": "that watched listing is gone — reload and try again"}
        listing = matches[0]
    elif len(listings) == 1:
        listing = listings[0]
    else:
        return {"ok": False, "error": f"{len(listings)} watched listings here — specify "
                                      f"which one to refresh"}
    scope = listing.get("scope") or {}
    if not (scope.get("folder_id") or scope.get("query")):
        return {"ok": False, "error": "this listing was staged without a recorded folder "
                                      "scope — re-stage it from the CLI once to enable "
                                      "in-console refresh"}
    target = "unassigned" if staged.get("is_unassigned") else slug
    cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / "mitos.py"),
           "connect", "--stage"]
    if target != "unassigned":
        cmd += ["--project", target]
    if scope.get("store"):
        cmd += ["--store", str(scope["store"])]
    if scope.get("folder_id"):
        cmd += ["--folder-id", str(scope["folder_id"])]
    if scope.get("query"):
        cmd += ["--query", str(scope["query"])]
    if scope.get("recursive"):
        cmd += ["--recursive"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=str(Path(__file__).resolve().parents[2]))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"connect timed out after {timeout}s — run it from a "
                                      f"terminal to see what it's waiting on"}
    except OSError as e:
        return {"ok": False, "error": f"couldn't run connect: {e}"}
    log = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return {"ok": False, "error": log or f"connect exited {proc.returncode}", "log": log}
    return {"ok": True, "log": log, "staged": load_staged(reg, slug, pool)}


def _open_staging(reg: Registry, slug: str, pool: str, scope_key: str) -> tuple:
    """Shared front half of the two pure-file watch edits (remove_watch/rename_watch):
    validate the slug + scope_key, resolve which staging file backs this pool, and parse it
    into (path, slug-as-written, listings). Returns (None, error_dict) on any failure.

    Mirrors load_staged's fallback: when a project's own staging file doesn't exist, checks
    the unassigned pool so operations on projectless-but-staged documents work seamlessly."""
    if not slug or any(s in slug for s in ("/", "\\")) or slug in (".", ".."):
        return None, {"ok": False, "error": "invalid slug"}
    if not scope_key:
        return None, {"ok": False, "error": "scope_key required"}
    staging_dir = loader.inbox_dir(reg) / "staging"
    unassigned = staging_dir / "unassigned.json"
    if pool == "unassigned":
        path = unassigned
    else:
        path = staging_dir / f"{slug}.json"
        if not path.is_file():
            # Fall back to unassigned pool, same as load_staged does.
            path = unassigned
    if not path.is_file():
        return None, {"ok": False, "error": "nothing staged here"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None, {"ok": False, "error": "staging file is unreadable — re-stage from the CLI"}
    return (path, data.get("slug", slug), staging_mod.normalize_staging(data)), None


def _write_listings(path: Path, slug: str, listings: list[dict]) -> None:
    path.write_text(json.dumps({"slug": slug, "listings": listings},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_watch(reg: Registry, slug: str, pool: str = "", scope_key: str = "") -> dict:
    """Drop one watched listing from inbox/staging/<slug>.json — the console's "Remove
    watch" action. Console-only: there is no CLI verb for this (removing a watch is a pure
    file edit with no connector involved, so a CLI counterpart would just be a second way
    to do the same one-line write). The file itself is kept (with the remaining listings,
    or an empty `listings: []` if this was the last one) rather than deleted — that keeps
    _dismiss_file's "does a project-specific staging file exist" pool-fallback check
    working exactly as it does for an empty listing today."""
    opened, err = _open_staging(reg, slug, pool, scope_key)
    if err:
        return err
    path, file_slug, listings = opened
    remaining = [l for l in listings if l["scope_key"] != scope_key]
    if len(remaining) == len(listings):
        return {"ok": False, "error": "no watched listing with that scope_key"}
    _write_listings(path, file_slug, remaining)
    return {"ok": True, "staged": load_staged(reg, slug, pool)}


def rename_watch(reg: Registry, slug: str, pool: str = "", scope_key: str = "",
                 label: str = "") -> dict:
    """Give one watched listing a human name — the console's "Rename" action. Console-only
    and pure file edit, exactly like remove_watch.

    The label is COSMETIC: identity stays `scope_key` (derived from the scope's
    store/folder_id/query/recursive — see staging.scope_key), so renaming a watch never
    touches which documents it holds, never disturbs a sibling watch, and a later refresh
    replays the same scope and keeps the name (bootstrap.stage_listing carries it across).
    An empty label clears the name, restoring the derived scope label — that's the undo.
    Names are free text and deliberately NOT unique-checked: two folders an operator wants
    to call the same thing is their business, and the scope stays visible underneath."""
    opened, err = _open_staging(reg, slug, pool, scope_key)
    if err:
        return err
    path, file_slug, listings = opened
    if not any(l["scope_key"] == scope_key for l in listings):
        return {"ok": False, "error": "no watched listing with that scope_key"}
    clean = staging_mod.clean_label(label)
    for l in listings:
        if l["scope_key"] == scope_key:
            l["label"] = clean
    _write_listings(path, file_slug, listings)
    return {"ok": True, "staged": load_staged(reg, slug, pool)}


def graph_index(reg: Registry) -> list[dict]:
    """Every project with its current document mappings — the Knowledge Graph tab's data.
    Projects without a graph yet appear empty (you can still propose their first docs).

    When local projects exist (the user's overlay), core template projects step aside —
    the same convention as example machines in commands.py."""
    out: list[dict] = []
    has_local = any(p.get("_is_local") for p in reg.projects.values())
    slugs = sorted(
        s for s, p in reg.projects.items()
        if not has_local or p.get("_is_local")
    )
    from . import graph as graphmod
    for slug in slugs:
        pg = reg.graphs.get(slug)

        def _parent_id(d) -> str:
            if not d.is_part_of:
                return ""
            return d.is_part_of[len(graphmod.CREATIVE_WORK_NS):] if d.is_part_of.startswith(
                graphmod.CREATIVE_WORK_NS) else ""

        out.append({
            "slug": slug,
            "name": reg.projects[slug].get("name") or slug,
            "has_graph": pg is not None,
            # org domains live on EFFORTS (orgDomain), never on the project — a project
            # can hold software and marketing work side by side and routes per task
            "efforts": [{"id": e.id, "name": e.name, "description": e.description,
                         "orgDomain": e.org_domain, "goal": e.goal}
                        for e in (pg.efforts if pg else [])],
            "documents": [{"id": d.drive_id, "name": d.name,
                           "description": d.description, "dateModified": d.date_modified,
                           "webUrl": d.drive_url, "parentId": _parent_id(d),
                           "keywords": d.keywords, "type": d.doc_type}
                          for d in (pg.documents if pg else [])],
        })
    return out


# ── org visualization (role TREE reading is READ-ONLY — titles and lens/team/vocabulary/
# trigger playbooks are hand-authored prose in registry/skills/org-*/SKILL.md, parsed
# here, never generated or edited through this endpoint). Domain DISCOVERY is dynamic —
# any skill carrying an `org_domain` frontmatter key is a domain (loader.known_org_domains
# is the same source of truth for effort orgDomain validation) — never a hardcoded table,
# so `+ ORG` can add a domain purely by proposing a new skill candidate.
# Orgs are GLOBAL domain skills — nothing org-shaped is stored per project; the only
# org edge in the graph is an effort's orgDomain tag (see graph.ORG_DOMAIN_PRED). ──
_ORG_NUMBERED_HEADING_RE = re.compile(r"^##\s+\d+\.\s+(.+?)\s+—\s+(.+)$")
_ORG_ROLE_HEADING_RE = re.compile(r"^###\s+(.+?)\s+—\s+(.+)$")
_ORG_LENS_RE = re.compile(r"^-\s+\*\*Lens\*\*:\s*(.+)$")
_ORG_TEAM_RE = re.compile(r"^-\s+\*\*Team\*\*:\s*(.+)$")
_ORG_VOCAB_RE = re.compile(r"^-\s+\*\*Vocabulary\*\*:\s*(.+)$")
_ORG_TRIGGER_RE = re.compile(r"^-\s+Trigger:\s*(.+)$")


def _parse_org_skill(reg: Registry, skill_name: str) -> dict:
    """Walk one org-<domain>/SKILL.md: the numbered primary-chain headings, then the
    Extended C-suite Roles block (### headings + Lens/Team/optional Vocabulary/Trigger).
    Best-effort — an unexpected heading shape just yields fewer parsed roles; this only
    ever degrades the visualization, never registry data (nothing here is written back)."""
    skill = reg.skills.get(skill_name)
    if skill is None:
        return {"skill": skill_name, "primaryChain": [], "extendedRoles": []}
    primary_chain: list[dict] = []
    extended_roles: list[dict] = []
    in_extended = False
    role: dict | None = None
    last_attr: str | None = None    # bullet a wrapped continuation line should extend
    for raw in skill.body.splitlines():
        line = raw.strip()
        if not in_extended:
            m = _ORG_NUMBERED_HEADING_RE.match(line)
            if m:
                primary_chain.append({"title": m.group(1).strip(), "subtitle": m.group(2).strip()})
                continue
            if line == "## Extended C-suite Roles":
                in_extended = True
            continue
        role_m = _ORG_ROLE_HEADING_RE.match(line)
        if role_m:
            if role:
                extended_roles.append(role)
            role = {"title": role_m.group(1).strip(), "subtitle": role_m.group(2).strip(),
                    "lens": "", "team": "", "vocabulary": "", "trigger": ""}
            last_attr = None
            continue
        if line.startswith("## ") and not line.startswith("### "):
            # a non-role "##" heading (e.g. "## Red-Team Protocols") ends the block
            if role:
                extended_roles.append(role)
                role = None
            in_extended = False
            last_attr = None
            continue
        if role is None:
            continue
        matched = False
        for attr, pat in (("lens", _ORG_LENS_RE), ("team", _ORG_TEAM_RE),
                          ("vocabulary", _ORG_VOCAB_RE), ("trigger", _ORG_TRIGGER_RE)):
            m = pat.match(line)
            if m:
                role[attr] = m.group(1).strip()
                last_attr, matched = attr, True
                break
        if matched:
            continue
        # a wrapped continuation of the previous bullet (indented in the source, not a
        # new bullet/heading) — append rather than drop, so long Lens/Trigger text isn't
        # silently truncated mid-sentence
        if last_attr and line and raw[:1] in (" ", "\t"):
            role[last_attr] = f"{role[last_attr]} {line}".strip()
        else:
            last_attr = None
    if role:
        extended_roles.append(role)
    return {"skill": skill_name, "primaryChain": primary_chain, "extendedRoles": extended_roles}


def _extensions_by_target(reg: Registry) -> dict[str, list]:
    """parent skill name -> [extension Skill, ...] (sorted by name), from every skill
    that declares `extends_skill`. Used to surface active extensions on the role card
    they target, without re-deriving this on every _parse_org_skill call."""
    out: dict[str, list] = {}
    for s in reg.skills.values():
        parent = s.frontmatter.get("extends_skill")
        if parent:
            out.setdefault(parent, []).append(s)
    for lst in out.values():
        lst.sort(key=lambda s: s.name)
    return out


def org_index(reg: Registry) -> dict:
    """Every org domain, discovered dynamically from skills carrying an `org_domain`
    frontmatter key (see loader.known_org_domains) — combined with each domain's parsed
    role structure. Role TREE reading stays READ-ONLY here; role structure lives in
    hand-authored prose and is never edited through this endpoint (extensions are the
    one write path onto a role — see propose_new_skill's extends_skill/extends_role)."""
    extensions_by_target = _extensions_by_target(reg)
    out: dict[str, dict] = {}
    for skill in sorted(reg.skills.values(), key=lambda s: s.name):
        domain = skill.frontmatter.get("org_domain")
        if not domain:
            continue
        parsed = _parse_org_skill(reg, skill.name)
        summary = " → ".join(step["title"] for step in parsed["primaryChain"])
        exts = extensions_by_target.get(skill.name, [])
        for role in parsed["extendedRoles"]:
            role["activeExtensions"] = [
                {"name": e.name, "description": e.frontmatter.get("description", "")}
                for e in exts
                if (e.frontmatter.get("extends_role") or "").strip().lower()
                == role["title"].strip().lower()
            ]
        out[domain] = {
            "skill": skill.name,
            "primaryChainSummary": summary,
            "primaryChain": parsed["primaryChain"],
            "extendedRoles": parsed["extendedRoles"],
        }
    return out


def org_tree(reg: Registry, machine_name: str) -> dict:
    """The Agent-MD folder view: reconstruct the on-disk tree the agents-md target
    deploys for a machine, from plan_machine()'s Output.deploy_path values. A read-only
    display projection of what deploy already computes — no new state, no writes.
    Returns {ok, machine, tree} or {ok: False, error}."""
    try:
        outputs = plan_machine(reg, machine_name)
    except KeyError:
        return {"ok": False, "error": f"unknown machine {machine_name!r}"}
    agents_outputs = [o for o in outputs if o.target == "agents-md"]
    if not agents_outputs:
        return {"ok": True, "machine": machine_name, "tree": []}

    all_parts = [PurePosixPath(o.deploy_path).parts for o in agents_outputs]
    min_len = min(len(p) for p in all_parts)
    common_len = 0
    for depth in range(min_len - 1):   # keep each file's own leaf segment uncollapsed
        if len({p[depth] for p in all_parts}) == 1:
            common_len = depth + 1
        else:
            break

    root: dict = {}
    for o, parts in zip(agents_outputs, all_parts):
        rel = parts[common_len:]
        if not rel:
            continue
        node = root
        for part in rel[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("__files__", []).append((rel[-1], o.deploy_path))

    def to_list(node: dict) -> list:
        children = [{"name": name, "deployPath": None, "children": to_list(sub)}
                    for name, sub in sorted(node.items()) if name != "__files__"]
        children += [{"name": fname, "deployPath": dp, "children": []}
                     for fname, dp in sorted(node.get("__files__", []))]
        return children

    return {"ok": True, "machine": machine_name, "tree": to_list(root)}


def state(reg: Registry) -> dict:
    return {
        "root": str(reg.root),
        "generated_at": _now(),
        "candidates": load_candidates(reg),
        "prompts": prompt_index(reg),
        "graphs": graph_index(reg),
        # the fixed target-adapter set (loader.KNOWN_TARGETS) — the metadata panel's
        # targets checkboxes read this instead of hardcoding their own copy.
        "known_targets": sorted(loader.KNOWN_TARGETS),
        # The Mitos-owned prompt placeholders, for the one-shot copy flow: `user_tokens`
        # are auto-substituted at copy time (the operator is never asked to type their own
        # name), `machine_tokens` are left literal (a copied prompt goes to a chat app, not
        # a machine deploy — no machine's paths apply). Every OTHER {{token}} in a prompt is
        # a fillable input the copy modal asks for. See render.user_token_map.
        "user_tokens": render.user_token_map(reg),
        "machine_tokens": render.machine_token_names(),
        # only machines with an Agent-MD folder tree — the Org tab's folder-view picker
        "agents_md_machines": sorted(
            m for m, cfg in reg.machines.items() if "agents-md" in cfg.get("targets", [])),
        # the status bar's machine selector — same convention as cmd_compile: example
        # templates step aside once the overlay defines a real machine; on a fresh clone
        # (no real machines yet) they show so the quick-start deploy rehearsal works
        "machines": sorted(commands.real_machines(reg)),
        "ops": {"compile": commands.compile_status(reg, reg.root / "dist")},
    }


# ── ops: compile/deploy from the console ─────────────────────────────────────
# Single-flight: at most one compile or deploy runs at a time, guarded by _OPS_LOCK.
# cmd_compile/cmd_deploy only ever communicate via print(), so a _TeeWriter installed
# as sys.stdout for the call's duration is the only way to surface their progress —
# it both appends to the shared _OPS_STATE (for a concurrent GET /api/ops/status poll)
# and forwards to the real stdout, so the operator's own terminal still sees it.
_OPS_LOCK = threading.Lock()
_OPS_STATE_LOCK = threading.Lock()
_OPS_STATE: dict = {
    "running": False, "kind": None, "machine": None,
    "log": "", "rc": None, "started_at": None, "finished_at": None,
}


class _TeeWriter:
    def write(self, s: str) -> int:
        if s:
            with _OPS_STATE_LOCK:
                _OPS_STATE["log"] += s
            sys.__stdout__.write(s)
        return len(s)

    def flush(self) -> None:
        sys.__stdout__.flush()


def ops_status() -> dict:
    with _OPS_STATE_LOCK:
        return dict(_OPS_STATE)


def _run_op(kind: str, machine: str | None, fn) -> None:
    """Runs fn() with stdout captured into _OPS_STATE; always releases _OPS_LOCK, even if
    fn() raises — an unhandled exception must not wedge the console into "always running"."""
    with _OPS_STATE_LOCK:
        _OPS_STATE.update(running=True, kind=kind, machine=machine, log="",
                          rc=None, started_at=_now(), finished_at=None)
    try:
        with contextlib.redirect_stdout(_TeeWriter()):
            rc = fn()
    except Exception as e:
        with _OPS_STATE_LOCK:
            _OPS_STATE["log"] += f"\ninternal error: {e}\n"
        rc = 1
    with _OPS_STATE_LOCK:
        _OPS_STATE.update(running=False, rc=rc, finished_at=_now())
    _OPS_LOCK.release()


def run_compile(reg: Registry, target: str | None = None) -> dict:
    """Compile has no network I/O and finishes in well under a second, so this runs
    synchronously in the request thread — but still goes through the same lock/state
    bookkeeping as deploy, so the frontend can poll either operation identically."""
    if not _OPS_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "an operation is already running"}
    _run_op("compile", None, lambda: commands.cmd_compile(reg, reg.root / "dist", target))
    snap = ops_status()
    return {"ok": True, "rc": snap["rc"], "log": snap["log"]}


def run_deploy_plan(reg: Registry, machine: str) -> dict:
    """Read-only preview for the deploy confirm modal — safe to call anytime, including
    while another op is mid-flight (no lock needed)."""
    if machine not in reg.machines:
        return {"ok": False, "error": f"unknown machine {machine!r}"}
    plan = commands.compute_deploy_plan(reg, machine)
    blocked_ids = {id(s) for s in plan.blocked}
    return {
        "ok": True,
        "machine": machine,
        # set when a real apply would refuse outright before any plan is even computed
        # (example-template machine, or an OS mismatch on this host) — unlike blocked_count
        # below (recoverable, safe to preview through), this is unconditional and unfixable
        # by resolving drift, so the frontend disables Confirm & Deploy when it's set.
        "refusal": commands.deploy_apply_refusal(reg, machine),
        "statuses": [
            {"path": s.output.deploy_path, "state": s.state, "detail": s.detail,
             "drift_policy": s.output.drift_policy, "blocked": id(s) in blocked_ids}
            for s in plan.statuses
        ],
        "orphans": list(plan.orphans),
        "blocked_count": len(plan.blocked),
        "skill_warnings": list(plan.skill_warnings),
        "clones": [{"dest": c.dest,
                    "present": commands._checkout_present(commands._dest(c.dest, None))}
                   for c in plan.clones],
    }


def run_deploy_apply(reg: Registry, machine: str) -> dict:
    """Starts a real deploy (dry_run=False) in a background daemon thread — deploy can shell
    out to git clone (up to 600s/repo), so this must not block the request. Deliberately never
    passes force=True/prune=True: those stay CLI-only (see docs/operator-console.md) — the
    existing protect-drift refusal inside cmd_deploy is the real safety net for a blocked
    deploy, not a client-side gate."""
    if machine not in reg.machines:
        return {"ok": False, "error": f"unknown machine {machine!r}"}
    if not _OPS_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "an operation is already running"}
    threading.Thread(
        target=_run_op, args=("deploy", machine,
                              lambda: commands.cmd_deploy(reg, machine, dry_run=False,
                                                          force=False)),
        daemon=True).start()
    return {"ok": True, "started": True}


# ── HTTP server (localhost only) ─────────────────────────────────────────────
def make_server(reg: Registry, port: int = 0) -> ThreadingHTTPServer:
    """The console server, bound to 127.0.0.1. Port 0 = ephemeral (tests)."""
    holder = {"reg": reg}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                return self._json(200, state(holder["reg"]))
            if self.path == "/api/ops/status":
                return self._json(200, ops_status())
            if self.path.startswith("/api/graph/staged"):
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query)
                slug = (q.get("slug") or [""])[0]
                pool = (q.get("pool") or [""])[0]
                return self._json(200, load_staged(holder["reg"], slug, pool))
            if self.path.startswith("/api/graph/dismissed"):
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query)
                slug = (q.get("slug") or [""])[0]
                pool = (q.get("pool") or [""])[0]
                return self._json(200, load_dismissed(holder["reg"], slug, pool))
            if self.path == "/api/org":
                return self._json(200, org_index(holder["reg"]))
            if self.path.startswith("/api/org/tree"):
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query)
                machine = (q.get("machine") or [""])[0]
                result = org_tree(holder["reg"], machine)
                return self._json(200 if result.get("ok") else 400, result)
            name = "index.html" if self.path in ("/", "") else self.path.lstrip("/")
            file = (UI_DIR / name)
            # static assets only, from review_ui/ itself — nothing else is reachable
            if (file.suffix not in _CONTENT_TYPES or not file.is_file()
                    or file.resolve().parent != UI_DIR.resolve()):
                return self._json(404, {"ok": False, "error": "not found"})
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{_CONTENT_TYPES[file.suffix]}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path not in ("/api/decide", "/api/propose", "/api/graph",
                                  "/api/graph/dismiss", "/api/graph/restore",
                                  "/api/graph/purge", "/api/graph/refresh",
                                  "/api/graph/unwatch", "/api/graph/rename-watch",
                                  "/api/reload",
                                  "/api/prompts/favorite", "/api/prompts/new", "/api/skills/new",
                                  "/api/org/new-domain", "/api/ops/compile",
                                  "/api/ops/deploy/plan", "/api/ops/deploy/apply"):
                return self._json(404, {"ok": False, "error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._json(400, {"ok": False, "error": "bad request body"})
            try:
                return self._dispatch_post(body)
            except Exception as e:
                # BaseHTTPRequestHandler has no handler of its own for an exception
                # raised inside do_POST: it propagates out, the connection is dropped
                # with zero bytes written, and the browser reports a bare "Failed to
                # fetch" with no indication of what went wrong. Always answer instead.
                import traceback
                traceback.print_exc()
                return self._json(500, {"ok": False, "error": f"internal error: {e}"})

        def _dispatch_post(self, body):
            if self.path == "/api/reload":
                # The explicit "Reload from disk" button. GET /api/state deliberately
                # serves the cached registry (it is polled), so this is the ONLY path that
                # re-reads registry/ + registry/local/ mid-session.
                try:
                    reloaded = loader.load(holder["reg"].root)
                except Exception as e:
                    # A half-saved YAML in registry/local/ is the common case here. Keep the
                    # last good registry — the console stays usable (and drafts survive)
                    # while the operator fixes the file — and report what broke.
                    return self._json(400, {"ok": False, "error": str(e)})
                holder["reg"] = reloaded
                return self._json(200, {"ok": True, "state": state(reloaded)})
            if self.path == "/api/ops/compile":
                target = body.get("target") or None
                result = run_compile(holder["reg"], str(target) if target else None)
                return self._json(200 if result.get("ok") else 409, result)
            if self.path == "/api/ops/deploy/plan":
                result = run_deploy_plan(holder["reg"], str(body.get("machine", "")))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/ops/deploy/apply":
                result = run_deploy_apply(holder["reg"], str(body.get("machine", "")))
                return self._json(200 if result.get("ok") else 409, result)
            if self.path == "/api/prompts/favorite":
                # toggle a prompt/skill name in the user's favorites list
                name = str(body.get("name", ""))
                if not name:
                    return self._json(400, {"ok": False, "error": "name required"})
                updated = toggle_favorite(holder["reg"].root, name)
                return self._json(200, {"ok": True, "favorites": updated})
            if self.path == "/api/prompts/new":
                # propose a brand-new prompt — only ever writes inbox/ (kind: new)
                fm = body.get("frontmatter")
                result = propose_new_prompt(
                    holder["reg"], str(body.get("name", "")),
                    fm if isinstance(fm, dict) else {},
                    str(body.get("body", "")), str(body.get("reason", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/propose":
                # save an edited prompt as an inbox candidate — only ever writes inbox/.
                # skill/prompt edits carry structured metadata fields (propose_meta_edit
                # reassembles YAML server-side); partial edits stay body-only (propose_edit).
                kind = str(body.get("kind", ""))
                ident = str(body.get("ident", ""))
                text = str(body.get("body", ""))
                reason = str(body.get("reason", "") or "")
                if kind in ("skill", "prompt"):
                    fields = body.get("fields")
                    res = body.get("resources") if kind == "skill" else None
                    result = propose_meta_edit(
                        holder["reg"], kind, ident,
                        fields if isinstance(fields, dict) else {}, text, reason,
                        resources=res if isinstance(res, dict) else None)
                else:
                    result = propose_edit(holder["reg"], kind, ident, text, reason)
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/skills/new":
                # propose a brand-new skill — only ever writes inbox/ (kind: new)
                fm = body.get("frontmatter")
                res = body.get("resources")
                result = propose_new_skill(
                    holder["reg"], str(body.get("name", "")),
                    fm if isinstance(fm, dict) else {},
                    str(body.get("body", "")), str(body.get("reason", "") or ""),
                    resources=res if isinstance(res, dict) else None)
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/org/new-domain":
                # the "+ ORG" button — propose a new domain-template skill (kind: new)
                result = propose_new_org_domain(
                    holder["reg"], str(body.get("domain", "")),
                    str(body.get("reason", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph":
                # propose document/effort mapping(s)/removal(s) as a kind:graph
                # candidate — only writes inbox/
                docs = body.get("documents")
                rem = body.get("removals")
                effs = body.get("efforts")
                eff_rem = body.get("effortRemovals")
                result = propose_graph_change(
                    holder["reg"], str(body.get("slug", "")),
                    docs if isinstance(docs, list) else [],
                    rem if isinstance(rem, list) else [],
                    str(body.get("reason", "") or ""),
                    effs if isinstance(effs, list) else [],
                    eff_rem if isinstance(eff_rem, list) else [])
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph/dismiss":
                # Discovery's manual Dismiss action — moves doc(s) to Recovery
                docs = body.get("documents")
                result = dismiss_docs(
                    holder["reg"], str(body.get("slug", "")),
                    docs if isinstance(docs, list) else [],
                    str(body.get("pool", "") or ""),
                    permanent=bool(body.get("permanent")))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph/purge":
                # Recovery's "Clear missing" — drop rows the current listings prove are
                # gone from every watched scope. Server re-checks in_scope; the client
                # can't force it.
                ids = body.get("ids")
                result = purge_dismissed(
                    holder["reg"], str(body.get("slug", "")),
                    ids if isinstance(ids, list) else [],
                    str(body.get("pool", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph/refresh":
                # "↻ Refresh folder" — replay one watched listing's enumeration via a
                # mitos.py subprocess. scope_key picks which listing when a project
                # watches more than one; refresh_staging defaults to the sole listing
                # when there's exactly one and scope_key is omitted.
                result = refresh_staging(
                    holder["reg"], str(body.get("slug", "")),
                    str(body.get("pool", "") or ""),
                    str(body.get("scope_key", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph/unwatch":
                # "Remove watch" — drop one listing from the staging file. Pure file edit,
                # no connector involved, console-only (no CLI counterpart).
                result = remove_watch(
                    holder["reg"], str(body.get("slug", "")),
                    str(body.get("pool", "") or ""),
                    str(body.get("scope_key", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph/rename-watch":
                # "Rename" — name one watch. Cosmetic only: scope_key stays identity, so
                # nothing about what's watched or refreshed changes. Empty label clears it.
                result = rename_watch(
                    holder["reg"], str(body.get("slug", "")),
                    str(body.get("pool", "") or ""),
                    str(body.get("scope_key", "") or ""),
                    str(body.get("label", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph/restore":
                # Recovery tab's Restore action — the doc reappears in Discovery
                ids = body.get("ids")
                result = restore_docs(
                    holder["reg"], str(body.get("slug", "")),
                    ids if isinstance(ids, list) else [],
                    str(body.get("pool", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            result = decide(holder["reg"], str(body.get("id", "")),
                            str(body.get("decision", "")),
                            str(body.get("reason", "") or ""),
                            force=bool(body.get("force")))
            if result.get("ok") and result.get("changed"):
                # an accept wrote into registry/ — reload so the next state is fresh
                holder["reg"] = loader.load(holder["reg"].root)
            self._json(200 if result.get("ok") else 400, result)

        def _json(self, code: int, obj: dict):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            if args and isinstance(args[0], str) and "/api/decide" in args[0]:
                print(f"  {args[0]}")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def cmd_review(reg: Registry, port: int = 8765, open_browser: bool = True) -> int:
    try:
        server = make_server(reg, port)
    except OSError as e:
        print(f"error: can't bind 127.0.0.1:{port} ({e}) — is another review running? "
              f"Try --port.")
        return 2
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    n = len(load_candidates(reg))
    print(f"operator console at {url} — {n} candidate(s) in the inbox. Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
    return 0
