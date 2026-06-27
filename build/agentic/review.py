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

import datetime as _dt
import difflib
import json
import re
import shutil
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

import yaml

from . import loader, render
from .commands import _now, _real_registry_rel, route_into_registry
from .io import sha256
from .loader import Registry
from .planner import plan_machine

UI_DIR = Path(__file__).resolve().parent.parent / "review_ui"
DECISIONS = "decisions.jsonl"

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
        # For graph candidates, surface the target project, the Drive IDs the fragment
        # proposes, and the IDs it removes, so the Knowledge Graph tab can flag in-flight
        # documents without parsing the jsonld (and its IRI scheme) client-side. Empty for
        # non-graph candidates.
        project, doc_ids, removal_ids, effort_ids, effort_removal_ids = \
            _graph_candidate_targets(reg, meta, payload)
        out.append({
            "id": folder.name,
            "registry_path": meta.get("registry_path") or "",
            "kind": meta.get("kind", ""),
            "project": project,
            "doc_ids": doc_ids,
            "removal_ids": removal_ids,
            "effort_ids": effort_ids,
            "effort_removal_ids": effort_removal_ids,
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


def _graph_candidate_targets(reg: Registry, meta: dict,
                             payload: str) -> tuple[str, list[str], list[str], list[str], list[str]]:
    """(project_slug, [upserted_drive_id, …], [removed_drive_id, …],
        [upserted_effort_id, …], [removed_effort_id, …]) a graph candidate proposes;
    ("", [], [], [], []) for non-graph. Removals live in meta (the fragment carries only
    upserts), so removed docs/efforts are flagged in-flight just like upserted ones."""
    if meta.get("kind") != "graph":
        return "", [], [], [], []
    slug = meta.get("project") or ""
    removals = [str(r) for r in (meta.get("removals") or [])]
    effort_removals = [str(r) for r in (meta.get("effort_removals") or [])]
    try:
        from . import graph as graphmod
        _name, _desc, docs, efforts = graphmod.parse_fragment(payload, slug)
        return slug, [d.drive_id for d in docs], removals, [e.id for e in efforts], effort_removals
    except Exception:
        return slug, [], removals, [], effort_removals


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
            merged = _merged_graph(reg, slug, payload, meta.get("removals"))
        except graphmod.GraphError as e:
            return "", payload, False, f"invalid graph fragment: {e}"
        current = (graphmod.canonical_jsonld(reg.graphs[slug])
                   if slug in reg.graphs else "")
        return current, graphmod.canonical_jsonld(merged), True, ""
    if meta.get("sections"):
        cur = [(s["source"], reg.partials[s["source"]].body)
               for s in meta["sections"] if s["source"] in reg.partials]
        return (render.plain_document(cur) if cur else ""), payload, True, ""
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


def _stale(reg: Registry, meta: dict) -> bool | None:
    """Has the registry moved since this candidate was captured? None = unknowable
    (no base recorded, or the deployed render flavor can't be reconstructed here)."""
    if meta.get("sections"):
        for s in meta["sections"]:
            p = reg.partials.get(s["source"])
            if p is None or p.body != s["text"].strip("\n"):
                return True
        return False
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
def decide(reg: Registry, candidate_id: str, decision: str, reason: str = "") -> dict:
    """Accept (route into the registry) or reject a candidate. Either way the folder
    is removed and one line lands in inbox/decisions.jsonl."""
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
        if meta.get("kind") == "graph":
            # a knowledge-graph mapping upserts into registry/graph/, not prose routing
            changed, err = _apply_graph_candidate(reg, meta, payload)
            if err:
                return {"ok": False, "error": err}
        else:
            sections = ([(s["source"], s["text"]) for s in meta["sections"]]
                        if meta.get("sections") else None)
            changed, warnings, err = route_into_registry(
                reg, meta.get("registry_path") or "", payload, sections=sections)
            if err:
                return {"ok": False, "error": err}
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
    graph (or a fresh one) with the fragment's documents and efforts upserted, `removals`
    dropped, and `effort_removals` removed (resetting their child docs to project root).
    Pure — writes nothing. Raises graph.GraphError on an invalid fragment or a missing-name
    new project. Effort removals are applied before doc upserts so any re-parented docs
    in the fragment land cleanly."""
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
    for e in efforts:
        base = graphmod.upsert_effort(base, graphmod.CreativeWork(
            id=e.id, name=e.name, description=e.description, is_part_of=base.iri))
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
    written canonically. Returns (changed_paths, error)."""
    from . import graph as graphmod
    from .io import write_text
    slug = meta.get("project") or ""
    if slug not in reg.projects:
        return [], f"unknown project {slug!r} for graph candidate"
    try:
        merged = _merged_graph(reg, slug, payload, meta.get("removals"),
                               meta.get("effort_removals"))
        write_text(_graph_file(reg, slug), graphmod.canonical_jsonld(merged))
    except graphmod.GraphError as e:
        return [], f"invalid graph fragment: {e}"
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


def propose_graph_change(reg: Registry, slug: str, documents: list[dict],
                         removals: list[str] | None = None, reason: str = "",
                         efforts: list[dict] | None = None,
                         effort_removals: list[str] | None = None) -> dict:
    """Save proposed document and effort mappings as a `kind: graph` inbox candidate.
    Writes only inbox/, never registry/ (invariant #3).

    `documents` is a list of {id, name, description, dateModified, parentId?} to upsert;
    `removals` is a list of Drive IDs to drop. `efforts` is a list of {id, name,
    description} to upsert; `effort_removals` is a list of effort IDs to remove.
    A candidate may carry only removals (no upserts). `parentId` in a document dict is
    the effort ID (or "" / omitted for project root).

    The fragment always includes ALL current + proposed efforts so that document
    isPartOf links validate self-consistently. Returns {ok, id, registry_path} or
    {ok: False, error}."""
    from . import graph as graphmod
    if slug not in reg.projects:
        return {"ok": False, "error": f"unknown project {slug!r}"}

    # ── parse document dicts ──────────────────────────────────────────────────
    docs = []
    for d in documents:
        try:
            parent_id = str(d.get("parentId", "")).strip()
            parent_iri = (graphmod.CREATIVE_WORK_NS + parent_id) if parent_id else ""
            docs.append(graphmod.Document(
                drive_id=str(d["id"]).strip(), name=str(d["name"]).strip(),
                description=str(d.get("description", "")).strip(),
                date_modified=str(d["dateModified"]).strip(),
                is_part_of=parent_iri,
                keywords=str(d.get("keywords", "")).strip(),
                web_url=str(d.get("webUrl", "")).strip()))
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
    for e_dict in (efforts or []):
        try:
            eid = str(e_dict["id"]).strip()
            effective_efforts[eid] = graphmod.CreativeWork(
                id=eid, name=str(e_dict["name"]).strip(),
                description=str(e_dict.get("description", "")).strip(),
                is_part_of=proj_iri)
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
    inbox = loader.inbox_dir(reg)
    inbox.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    folder = inbox / f"{ts}--console--graph-{slug}"
    n = 2
    while folder.exists():
        folder = inbox / f"{ts}--console--graph-{slug}-{n}"
        n += 1
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
    folder.mkdir()
    (folder / "meta.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (folder / "graph.jsonld").write_text(fragment, encoding="utf-8")
    return {"ok": True, "id": folder.name, "registry_path": graph_rel}


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
    elif kind == "prompt":
        prompt = reg.prompts.get(ident)
        if prompt is None:
            return {"ok": False, "error": f"unknown prompt {ident!r}"}
        registry_path = prompt.rel
    elif kind == "partial":
        if ident not in reg.partials:
            return {"ok": False, "error": f"unknown partial {ident!r}"}
        registry_path = ident
    else:
        return {"ok": False, "error": f"unknown kind {kind!r}"}
    # registry_path is registry-controlled (a known skill.rel / partial key), but guard
    # before it becomes a folder + file name — only Markdown prose routes mechanically.
    if ".." in registry_path or not registry_path.endswith(".md"):
        return {"ok": False, "error": f"unroutable registry path {registry_path!r}"}
    inbox = loader.inbox_dir(reg)
    inbox.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    slug = _slug_path(registry_path)
    folder = inbox / f"{ts}--console--{slug}"
    n = 2
    while folder.exists():
        folder = inbox / f"{ts}--console--{slug}-{n}"
        n += 1
    meta = {
        "registry_path": registry_path,
        "kind": "drift",
        "source": {"machine": socket.gethostname() or "console", "tool": "console"},
        "base_hash": "",          # console edit tracks no deployed base → no stale badge
        "deploy_path": "",        # not a deployed file; routing comes from registry_path
        "sources": [registry_path],
        "captured_at": _now(),
        "note": "edited in the operator console prompt library",
    }
    if reason:
        meta["reason"] = reason
    folder.mkdir()
    (folder / "meta.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (folder / PurePosixPath(registry_path).name).write_text(body, encoding="utf-8")
    return {"ok": True, "id": folder.name, "registry_path": registry_path}


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


def prompt_index(reg: Registry) -> dict:
    """All registry prose organized into three sections for the Prompt Library tab.

    - prompts: first-class harness-agnostic assets (registry/prompts/)
    - skills: skill bodies (prompts with harness packaging)
    - partials: identity personas and context prose

    Favorites are the user's pinned prompts, persisted in registry/local/prompt-favorites.yaml
    and surfaced so the UI can highlight them across sessions.
    """
    favorites = set(_load_favorites(reg.root))
    prompts = [{
        "name": p.name,
        "description": p.frontmatter.get("description", ""),
        "category": p.category,
        "targets": p.targets,
        "body": p.body,
        "favorited": p.name in favorites,
    } for p in sorted(reg.prompts.values(), key=lambda p: (p.category, p.name))]
    skills = [{
        "name": s.name,
        "description": s.frontmatter.get("description", ""),
        "category": s.category,
        "targets": s.targets,
        "body": s.body,
        "favorited": s.name in favorites,
    } for s in sorted(reg.skills.values(), key=lambda s: (s.category, s.name))]
    partials = [{
        "rel": p.rel,
        "group": ("identity" if p.rel.startswith("identity/")
                  else "projects" if p.rel.startswith("context/projects/")
                  else "context"),
        "audience": p.audience,
        "body": p.body,
    } for p in sorted(reg.partials.values(), key=lambda p: p.rel)]
    return {"prompts": prompts, "skills": skills, "partials": partials}


def _read_staging(path: Path, slug: str, is_unassigned: bool) -> dict:
    """Parse one inbox/staging/*.json listing into the staged-panel shape."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"ok": False, "error": "staging file is unreadable — re-stage from the CLI"}
    docs = data.get("documents") if isinstance(data.get("documents"), list) else []
    return {"ok": True, "slug": slug, "documents": docs,
            "staged_at": data.get("staged_at", ""), "connector": data.get("connector", ""),
            "scope": data.get("scope", {}), "is_unassigned": is_unassigned}


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
            return {"ok": True, "slug": slug, "documents": [], "staged_at": "",
                    "is_unassigned": True}
        return _read_staging(unassigned, slug, True)
    path = staging / f"{slug}.json"
    if not path.is_file():
        # Fall back to the unassigned pool so that a projectless sync is surfaced in the
        # Knowledge Graph tab even before the user binds documents to a project.
        if not unassigned.is_file():
            return {"ok": True, "slug": slug, "documents": [], "staged_at": "",
                    "is_unassigned": False}
        return _read_staging(unassigned, slug, True)
    return _read_staging(path, slug, False)



def graph_index(reg: Registry) -> list[dict]:
    """Every project with its current document mappings — the Knowledge Graph tab's data.
    Projects without a graph yet appear empty (you can still propose their first docs).

    When local projects exist (the user's overlay), core template projects step aside —
    the same convention as example machines in commands.py."""
    out: list[dict] = []
    has_local = any(p.get("_is_local") for p in reg.projects.values())
    slugs = sorted(
        s for s, p in reg.projects.items()
        if (not has_local or p.get("_is_local")) and (p.get("drive") or {})
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
            "efforts": [{"id": e.id, "name": e.name, "description": e.description}
                        for e in (pg.efforts if pg else [])],
            "documents": [{"id": d.drive_id, "name": d.name,
                           "description": d.description, "dateModified": d.date_modified,
                           "webUrl": d.drive_url, "parentId": _parent_id(d),
                           "keywords": d.keywords}
                          for d in (pg.documents if pg else [])],
        })
    return out


def state(reg: Registry) -> dict:
    return {
        "root": str(reg.root),
        "generated_at": _now(),
        "candidates": load_candidates(reg),
        "prompts": prompt_index(reg),
        "graphs": graph_index(reg),
    }


# ── HTTP server (localhost only) ─────────────────────────────────────────────
def make_server(reg: Registry, port: int = 0) -> ThreadingHTTPServer:
    """The console server, bound to 127.0.0.1. Port 0 = ephemeral (tests)."""
    holder = {"reg": reg}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                return self._json(200, state(holder["reg"]))
            if self.path.startswith("/api/graph/staged"):
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query)
                slug = (q.get("slug") or [""])[0]
                pool = (q.get("pool") or [""])[0]
                return self._json(200, load_staged(holder["reg"], slug, pool))
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
                                  "/api/prompts/favorite"):
                return self._json(404, {"ok": False, "error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._json(400, {"ok": False, "error": "bad request body"})
            if self.path == "/api/prompts/favorite":
                # toggle a prompt/skill name in the user's favorites list
                name = str(body.get("name", ""))
                if not name:
                    return self._json(400, {"ok": False, "error": "name required"})
                updated = toggle_favorite(holder["reg"].root, name)
                return self._json(200, {"ok": True, "favorites": updated})
            if self.path == "/api/propose":
                # save an edited prompt as an inbox candidate — only ever writes inbox/
                result = propose_edit(holder["reg"], str(body.get("kind", "")),
                                      str(body.get("ident", "")),
                                      str(body.get("body", "")),
                                      str(body.get("reason", "") or ""))
                return self._json(200 if result.get("ok") else 400, result)
            if self.path == "/api/graph":
                # propose document/effort mapping(s)/removal(s) as a kind:graph candidate —
                # only writes inbox/
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
            result = decide(holder["reg"], str(body.get("id", "")),
                            str(body.get("decision", "")),
                            str(body.get("reason", "") or ""))
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
            if "/api/decide" in (args[0] if args else ""):
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
