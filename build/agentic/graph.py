"""The knowledge graph: a lean, schema.org index of each project's Workspace documents.

the knowledge-graph design. The graph is an *index, not a knowledge base*: it exists
only to route an agent to the correct, current document. Three entity types —
`schema:Project`, `schema:CreativeWork` (an effort grouping), and `schema:DigitalDocument`
— keyed by `http://peccia.net/` IRIs, with the Drive ID as each document's natural key.
No blank nodes (validation rejects them), no content snapshots, no CRUD history.
Provenance lives in git + inbox, not here.

Isolation rule (the boring-beats-clever rule): rdflib is imported lazily inside this
module so the rest of the compiler never pays for it unless registry/graph/ holds files.

Storage is one canonical JSON-LD file per project (`registry/graph/<slug>.jsonld`):
deterministic, sorted, IRI-only, so git diffs stay clean and merges conflict-light.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Vocabulary (public schema.org + Paul's IRI namespace) ────────────────────
SCHEMA = "https://schema.org/"
PECCIA = "http://peccia.net/"
PROJECT_NS = PECCIA + "project/"
DOCUMENT_NS = PECCIA + "document/"
CREATIVE_WORK_NS = PECCIA + "creativework/"

# The @context every stored graph carries (kept verbatim in canonical output). An
# explicit @vocab — not the bare "https://schema.org" string — so terms resolve offline
# and deterministically to https://schema.org/<term> without fetching a remote context.
JSONLD_CONTEXT = {"@vocab": SCHEMA}

# Effort IDs are IRI suffixes: only lowercase alphanumerics and hyphens, no leading/
# trailing/consecutive hyphens (same discipline as DNS labels).
_EFFORT_ID_RE = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')


class GraphError(Exception):
    """A schema/shape violation in a project graph. The loader rewraps this as a
    RegistryError so a bad graph aborts compilation exactly like a dangling partial."""


# ── In-memory shape (plain data — no rdflib types leak past this module) ──────
@dataclass(frozen=True)
class Document:
    drive_id: str          # schema:identifier — the natural key; also the IRI suffix
    name: str              # schema:name (title)
    description: str       # schema:description (short, human-gated summary)
    date_modified: str     # schema:dateModified (ISO date — the freshness signal)
    is_part_of: str = ""   # IRI of parent Project or CreativeWork; "" → project root
    keywords: str = ""     # schema:keywords — optional comma-separated tags
    web_url: str = ""      # schema:url — the connector-provided link (store-agnostic)

    @property
    def iri(self) -> str:
        return DOCUMENT_NS + self.drive_id

    @property
    def drive_url(self) -> str:
        """The document's URL. Uses the connector-provided web_url when present; falls back
        to a synthesized Google Drive link so existing graphs (no url field) still render."""
        return self.web_url or f"https://drive.google.com/open?id={self.drive_id}"


@dataclass(frozen=True)
class CreativeWork:
    id: str               # slug — the IRI suffix under creativework/
    name: str             # schema:name
    description: str      # schema:description
    is_part_of: str       # must be the project IRI

    @property
    def iri(self) -> str:
        return CREATIVE_WORK_NS + self.id


@dataclass
class ProjectGraph:
    slug: str                                   # IRI suffix under project/
    name: str                                   # schema:name
    description: str                            # schema:description ("" if absent)
    documents: list[Document] = field(default_factory=list)
    efforts: list[CreativeWork] = field(default_factory=list)
    path: Path | None = None                    # source file, for diagnostics

    @property
    def iri(self) -> str:
        return PROJECT_NS + self.slug


# ── Load + validate ──────────────────────────────────────────────────────────
def load_project_graph(path: Path) -> ProjectGraph:
    """Parse one `<slug>.jsonld` file, validate its shape, return plain data.

    Raises GraphError (loudly) on a blank node, an unknown type, a missing required
    field, an out-of-namespace IRI, or more than one Project node.
    """
    projects, docs, efforts = _parse_nodes(path.read_text(encoding="utf-8"), path.name)
    if len(projects) != 1:
        raise GraphError(
            f"{path.name}: expected exactly one schema:Project node, found "
            f"{len(projects)} — one project graph per file")
    proj_iri, (proj_name, proj_desc) = next(iter(projects.items()))
    slug = proj_iri[len(PROJECT_NS):]
    effort_iris = {e.iri for e in efforts}
    for effort in efforts:
        if effort.is_part_of != proj_iri:
            raise GraphError(
                f"{path.name}: effort {effort.id!r} isPartOf {effort.is_part_of} but "
                f"this file's project is {proj_iri}")
    for part_of, _doc in docs:
        if part_of != proj_iri and part_of not in effort_iris:
            raise GraphError(
                f"{path.name}: document isPartOf {part_of} but this file's project is "
                f"{proj_iri} and no matching effort is defined")
    # Normalise: docs parented directly to the project use "" (not the project IRI) so
    # canonical_jsonld and grouping logic can treat "" as "project root".
    documents = sorted(
        (Document(d.drive_id, d.name, d.description, d.date_modified,
                  "" if d.is_part_of == proj_iri else d.is_part_of, d.keywords,
                  d.web_url)
         for _p, d in docs),
        key=lambda d: (d.name.lower(), d.drive_id))
    efforts_sorted = sorted(efforts, key=lambda e: (e.name.lower(), e.id))
    return ProjectGraph(slug=slug, name=proj_name, description=proj_desc,
                        documents=documents, efforts=efforts_sorted, path=path)


def _parse_nodes(text: str, label: str) -> tuple[dict, list, list]:
    """The shared JSON-LD parser/validator. Returns:
      ({project_iri: (name, description)},
       [(isPartOf_iri, Document)],
       [CreativeWork])

    Two-pass over subjects: pass 1 collects all CreativeWork IRIs so that pass 2
    can validate document isPartOf links against the known effort set. Raises
    GraphError on a blank node, an unknown type, an out-of-namespace IRI, or a
    missing/duplicated required field."""
    try:
        from rdflib import BNode, Graph, URIRef
        from rdflib.namespace import RDF
    except ModuleNotFoundError as e:  # pragma: no cover - environment guard
        raise GraphError(
            "rdflib is required to load schema.org JSON-LD — "
            "`pip install -r build/requirements.txt`") from e

    g = Graph()
    try:
        g.parse(data=text, format="json-ld")
    except Exception as e:  # rdflib raises a grab-bag of parse errors
        raise GraphError(f"{label}: invalid JSON-LD: {e}") from e

    SDO = lambda term: URIRef(SCHEMA + term)  # noqa: E731

    # No blank nodes anywhere — every node is an IRI (deterministic graph).
    for s, _p, o in g:
        if isinstance(s, BNode) or isinstance(o, BNode):
            raise GraphError(
                f"{label}: blank node found — every node must be an IRI "
                f"(give it an http://peccia.net/ id)")

    allowed = {str(SDO("Project")), str(SDO("DigitalDocument")), str(SDO("CreativeWork"))}

    # ── Pass 1: collect Project + CreativeWork nodes ──────────────────────────
    projects: dict[str, tuple[str, str]] = {}     # iri -> (name, description)
    raw_efforts: list[tuple[str, str, str]] = []  # (iri, name, description)

    for subj in set(g.subjects()):
        types = {str(t) for t in g.objects(subj, RDF.type)}
        if not types:
            raise GraphError(f"{label}: node {subj} has no @type")
        unknown = types - allowed
        if unknown:
            raise GraphError(
                f"{label}: node {subj} has unsupported type(s) {sorted(unknown)} — only "
                f"schema:Project, schema:CreativeWork, and schema:DigitalDocument are allowed")
        s = str(subj)
        if str(SDO("Project")) in types:
            if not s.startswith(PROJECT_NS):
                raise GraphError(f"{label}: Project IRI {s} must start with {PROJECT_NS}")
            name = _one_literal(g, subj, SDO("name"), label, "Project", "name")
            desc = g.value(subj, SDO("description"))
            projects[s] = (name, str(desc) if desc is not None else "")
        elif str(SDO("CreativeWork")) in types:
            if not s.startswith(CREATIVE_WORK_NS):
                raise GraphError(
                    f"{label}: CreativeWork IRI {s} must start with {CREATIVE_WORK_NS}")
            effort_id = s[len(CREATIVE_WORK_NS):]
            if not _EFFORT_ID_RE.match(effort_id):
                raise GraphError(
                    f"{label}: effort id {effort_id!r} must match ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ "
                    f"(lowercase alphanumerics and hyphens, no leading/trailing/consecutive hyphens)")
            name = _one_literal(g, subj, SDO("name"), label, "CreativeWork", "name")
            desc = g.value(subj, SDO("description"))
            raw_efforts.append((s, name, str(desc) if desc is not None else ""))

    effort_iris = {iri for iri, _, _ in raw_efforts}

    # ── Pass 2: validate DigitalDocument nodes ────────────────────────────────
    docs: list[tuple[str, Document]] = []
    for subj in set(g.subjects()):
        types = {str(t) for t in g.objects(subj, RDF.type)}
        if str(SDO("DigitalDocument")) not in types:
            continue
        s = str(subj)
        if not s.startswith(DOCUMENT_NS):
            raise GraphError(
                f"{label}: DigitalDocument IRI {s} must start with {DOCUMENT_NS}")
        drive_id = _one_literal(g, subj, SDO("identifier"), label, "Document", "identifier")
        if s != DOCUMENT_NS + drive_id:
            raise GraphError(
                f"{label}: document IRI {s} must equal {DOCUMENT_NS}<identifier> "
                f"(identifier={drive_id!r}) — the Drive ID is the key")
        name = _one_literal(g, subj, SDO("name"), label, "Document", "name")
        description = _one_literal(g, subj, SDO("description"), label, "Document",
                                   "description")
        date_modified = _one_literal(g, subj, SDO("dateModified"), label, "Document",
                                     "dateModified")
        _check_date(date_modified, label)
        part_of = g.value(subj, SDO("isPartOf"))
        if part_of is None:
            raise GraphError(
                f"{label}: document {name!r} is missing schema:isPartOf "
                f"(every document must belong to a project or effort)")
        part_of_str = str(part_of)
        if not (part_of_str.startswith(PROJECT_NS) or part_of_str in effort_iris):
            raise GraphError(
                f"{label}: document {name!r} isPartOf {part_of_str} must be a "
                f"{PROJECT_NS} IRI or a known CreativeWork IRI in this file")
        keywords_val = g.value(subj, SDO("keywords"))
        keywords = str(keywords_val) if keywords_val is not None else ""
        url_val = g.value(subj, SDO("url"))
        web_url = str(url_val) if url_val is not None else ""
        docs.append((part_of_str, Document(drive_id=drive_id, name=name,
                                           description=description,
                                           date_modified=date_modified,
                                           is_part_of=part_of_str,
                                           keywords=keywords,
                                           web_url=web_url)))

    # Build CreativeWork objects (is_part_of validated later by load_project_graph)
    efforts = [CreativeWork(id=iri[len(CREATIVE_WORK_NS):], name=name, description=desc,
                            is_part_of="")  # placeholder; caller fills from context
               for iri, name, desc in raw_efforts]

    # Attach is_part_of to each effort from the graph
    for i, (iri, name, desc) in enumerate(raw_efforts):
        part_of = g.value(URIRef(iri), SDO("isPartOf"))
        efforts[i] = CreativeWork(id=iri[len(CREATIVE_WORK_NS):], name=name, description=desc,
                                  is_part_of=str(part_of) if part_of is not None else "")

    return projects, docs, efforts


def parse_fragment(text: str, slug: str,
                   label: str = "graph fragment") -> tuple[str | None, str | None, list, list]:
    """Parse a `kind: graph` candidate for one project: zero or more DigitalDocument nodes,
    zero or more CreativeWork nodes, and optionally the Project node, for `slug`. Returns
    (project_name_or_None, project_description_or_None, documents, efforts). Raises
    GraphError if any node belongs to a different project, or on any shape violation."""
    proj_iri = PROJECT_NS + slug
    projects, docs, efforts = _parse_nodes(text, label)
    for iri in projects:
        if iri != proj_iri:
            raise GraphError(
                f"{label}: Project node {iri} does not match project {slug!r} ({proj_iri})")
    for part_of, _doc in docs:
        if not (part_of == proj_iri or part_of.startswith(CREATIVE_WORK_NS)):
            raise GraphError(
                f"{label}: document isPartOf {part_of} but the candidate is for project "
                f"{slug!r} ({proj_iri})")
    for effort in efforts:
        if effort.is_part_of and effort.is_part_of != proj_iri:
            raise GraphError(
                f"{label}: effort {effort.id!r} isPartOf {effort.is_part_of} but the "
                f"candidate is for project {slug!r} ({proj_iri})")
    name, desc = projects.get(proj_iri, (None, None))
    # Normalise: project-IRI parented docs use "" so callers don't need to know the IRI.
    normalised = [Document(d.drive_id, d.name, d.description, d.date_modified,
                           "" if d.is_part_of == proj_iri else d.is_part_of, d.keywords,
                           d.web_url)
                  for _p, d in docs]
    return name, desc, normalised, efforts


def _one_literal(g, subj, pred, label: str, kind: str, field_name: str) -> str:
    """Require exactly one literal value for a predicate; return it as a string."""
    vals = list(g.objects(subj, pred))
    if not vals:
        raise GraphError(
            f"{label}: {kind} {subj} is missing required schema:{field_name}")
    if len(vals) > 1:
        raise GraphError(
            f"{label}: {kind} {subj} has multiple schema:{field_name} values")
    return str(vals[0])


def _check_date(value: str, label: str) -> None:
    try:
        _dt.date.fromisoformat(value[:10])
    except ValueError as e:
        raise GraphError(
            f"{label}: schema:dateModified {value!r} is not an ISO date "
            f"(YYYY-MM-DD)") from e


# ── Canonical serialization (deterministic, IRI-only) ────────────────────────
def canonical_jsonld(pg: ProjectGraph) -> str:
    """Re-emit a ProjectGraph as canonical JSON-LD: fixed key order, efforts then documents
    sorted, one Project node followed by its CreativeWork efforts then its documents.
    Identical data → identical bytes."""
    project_node: dict = {
        "@id": pg.iri,
        "@type": "Project",
        "name": pg.name,
    }
    if pg.description:
        project_node["description"] = pg.description
    graph_nodes = [project_node]
    for e in sorted(pg.efforts, key=lambda e: (e.name.lower(), e.id)):
        graph_nodes.append({
            "@id": e.iri,
            "@type": "CreativeWork",
            "name": e.name,
            "description": e.description,
            "isPartOf": {"@id": pg.iri},
        })
    for d in sorted(pg.documents, key=lambda d: (d.name.lower(), d.drive_id)):
        parent_iri = d.is_part_of if d.is_part_of else pg.iri
        doc_node: dict = {
            "@id": d.iri,
            "@type": "DigitalDocument",
            "identifier": d.drive_id,
            "name": d.name,
            "description": d.description,
            "dateModified": d.date_modified,
            "isPartOf": {"@id": parent_iri},
        }
        if d.web_url:
            doc_node["url"] = d.web_url
        if d.keywords:
            doc_node["keywords"] = d.keywords
        graph_nodes.append(doc_node)
    doc = {"@context": JSONLD_CONTEXT, "@graph": graph_nodes}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def is_canonical(path: Path, pg: ProjectGraph) -> bool:
    """True when the file on disk already equals its canonical serialization."""
    return path.read_text(encoding="utf-8") == canonical_jsonld(pg)


# ── Mutation (upsert-only — the knowledge-graph design) ─────────────────────
def upsert_document(pg: ProjectGraph, doc: Document) -> ProjectGraph:
    """Add a document mapping or update an existing one (matched by Drive ID). The
    fixed entity shape means there is no general triple-retraction problem."""
    kept = [d for d in pg.documents if d.drive_id != doc.drive_id]
    kept.append(doc)
    kept.sort(key=lambda d: (d.name.lower(), d.drive_id))
    return ProjectGraph(slug=pg.slug, name=pg.name, description=pg.description,
                        documents=kept, efforts=pg.efforts, path=pg.path)


def remove_document(pg: ProjectGraph, drive_id: str) -> ProjectGraph:
    """Drop a document mapping (a doc that left the project)."""
    kept = [d for d in pg.documents if d.drive_id != drive_id]
    return ProjectGraph(slug=pg.slug, name=pg.name, description=pg.description,
                        documents=kept, efforts=pg.efforts, path=pg.path)


def upsert_effort(pg: ProjectGraph, effort: CreativeWork) -> ProjectGraph:
    """Add an effort or update an existing one (matched by id)."""
    kept = [e for e in pg.efforts if e.id != effort.id]
    kept.append(effort)
    kept.sort(key=lambda e: (e.name.lower(), e.id))
    return ProjectGraph(slug=pg.slug, name=pg.name, description=pg.description,
                        documents=pg.documents, efforts=kept, path=pg.path)


def remove_effort(pg: ProjectGraph, effort_id: str) -> ProjectGraph:
    """Remove an effort and reset any child documents' is_part_of back to the project."""
    effort_iri = CREATIVE_WORK_NS + effort_id
    new_docs = [
        Document(d.drive_id, d.name, d.description, d.date_modified,
                 "" if d.is_part_of == effort_iri else d.is_part_of,
                 d.keywords, d.web_url)
        for d in pg.documents
    ]
    kept_efforts = [e for e in pg.efforts if e.id != effort_id]
    return ProjectGraph(slug=pg.slug, name=pg.name, description=pg.description,
                        documents=new_docs, efforts=kept_efforts, path=pg.path)


# ── Query (in-process SPARQL — the verb + later the Context Agent) ────────────
SAVED_QUERIES: dict[str, str] = {
    # list a project's documents, newest first — the doc-index source query
    "documents": """
        PREFIX schema: <https://schema.org/>
        SELECT ?id ?name ?description ?modified WHERE {
            ?doc a schema:DigitalDocument ;
                 schema:identifier ?id ;
                 schema:name ?name ;
                 schema:description ?description ;
                 schema:dateModified ?modified .
        } ORDER BY DESC(?modified) ?name
    """,
}


def run_query(pg: ProjectGraph, name: str) -> list[dict]:
    """Run a saved SPARQL query against a project graph, re-rendered to canonical
    JSON-LD first (so the query sees exactly the stored, validated data)."""
    if name not in SAVED_QUERIES:
        raise GraphError(f"unknown saved query {name!r}; known: "
                         f"{sorted(SAVED_QUERIES)}")
    from rdflib import Graph
    g = Graph()
    g.parse(data=canonical_jsonld(pg), format="json-ld")
    rows = []
    for r in g.query(SAVED_QUERIES[name]):
        rows.append({str(k): str(v) for k, v in zip(r.labels, r)})
    return rows


# ── Materialization (the generated, non-adoptable project tree) ──────────────
def roster_markdown(graphs: list[ProjectGraph]) -> str:
    """The Agentic Context root AGENTS.md: every Project + its description. Generated
    from the graph, overwritten every deploy (non-adoptable). Pure markdown, no banner."""
    lines = [
        "# Projects",
        "",
        "Index of active projects, generated from the knowledge graph and current as of "
        "the last deploy. Open a project's folder under `Projects/` for its document "
        "index and source.",
        "",
    ]
    for pg in sorted(graphs, key=lambda p: p.name.lower()):
        desc = f" — {pg.description}" if pg.description else ""
        lines.append(f"- **{pg.name}** (`{pg.slug}`){desc}")
    return "\n".join(lines).rstrip("\n") + "\n"


# The detail file's name, referenced by the lightweight index's pointer line.
DETAILS_FILENAME = "AGENTS_DETAILS.md"

# Curation cap: the always-loaded index/full document blocks list at most this many docs
# per group (newest first), with a "…and N more" footer. A graph that enumerates a whole
# Drive can hold dozens of low-signal docs; an uncapped flat dump would tax every request.
# Full detail for every document always remains in AGENTS_DETAILS.md (uncapped).
INDEX_LIMIT = 50


def _cap(docs: list, limit: int = INDEX_LIMIT) -> tuple[list, int]:
    """The first `limit` docs (already recency-ordered) and the count omitted."""
    return (docs[:limit], max(0, len(docs) - limit)) if limit else (docs, 0)


def project_index_markdown(pg: ProjectGraph) -> str:
    """A project's `Projects/<slug>/AGENTS.md`: the LIGHTWEIGHT index the harness auto-loads
    on every request — titles only, grouped by effort. Full descriptions, document IDs, links,
    and tags live in the on-demand details file."""
    lines = [
        f"# {pg.name} — documents",
        "",
        "Document titles, generated from the knowledge graph. Full details (document IDs, links, "
        f"descriptions, tags) are in [`{DETAILS_FILENAME}`]({DETAILS_FILENAME}). To change "
        f"this list, edit `registry/graph/{pg.slug}.jsonld` and redeploy.",
        "",
    ]
    if not pg.documents:
        lines.append("_No documents mapped yet._")
        return "\n".join(lines) + "\n"

    # group documents: effort IRI → [Document]; "" → project-root docs
    groups: dict[str, list[Document]] = {"": []}
    for e in pg.efforts:
        groups[e.iri] = []
    for d in _by_recency(pg.documents):
        groups.setdefault(d.is_part_of or "", []).append(d)

    def _doc_list(docs: list[Document]) -> list[str]:
        shown, omitted = _cap(docs)
        out = [f"- {d.name}" for d in shown]
        if omitted:
            out.append(f"- _…and {omitted} more — see [`{DETAILS_FILENAME}`]"
                       f"({DETAILS_FILENAME})_")
        return out

    has_efforts = any(len(v) > 0 for k, v in groups.items() if k)
    if not has_efforts:
        lines += _doc_list(groups[""])
    else:
        if groups[""]:
            lines += ["## Project Documents", ""] + _doc_list(groups[""]) + [""]
        for e in sorted(pg.efforts, key=lambda e: (e.name.lower(), e.id)):
            docs_in_effort = groups.get(e.iri, [])
            lines += [f"## {e.name}", ""]
            if docs_in_effort:
                lines += _doc_list(docs_in_effort) + [""]
            else:
                lines += ["_No documents in this effort._", ""]

    return "\n".join(lines).rstrip("\n") + "\n"


def project_details_markdown(pg: ProjectGraph) -> str:
    """A project's `Projects/<slug>/AGENTS_DETAILS.md`: the DETAILED reference, read on
    demand — per document the full `schema:description`, the Drive ID, the link, and the
    modified date. Grouped by effort. Generated and non-adoptable, like the index."""
    lines = [
        f"# {pg.name} — document details",
        "",
        "Full reference for the documents in `AGENTS.md`, generated from the knowledge "
        f"graph. To change it, edit `registry/graph/{pg.slug}.jsonld` and redeploy.",
        "",
    ]
    if not pg.documents:
        lines.append("_No documents mapped yet._")
        return "\n".join(lines) + "\n"

    effort_map = {e.iri: e for e in pg.efforts}
    groups: dict[str, list[Document]] = {"": []}
    for e in pg.efforts:
        groups[e.iri] = []
    for d in _by_recency(pg.documents):
        groups.setdefault(d.is_part_of or "", []).append(d)

    def _doc_entries(docs: list[Document]) -> list[str]:
        out = []
        for d in docs:
            entry = [
                f"### {d.name}",
                f"- **ID:** `{d.drive_id}`",
                f"- **Link:** {d.drive_url}",
                f"- **Modified:** {d.date_modified}",
            ]
            if d.keywords:
                entry.append(f"- **Tags:** {d.keywords}")
            entry += ["", d.description or "_No description._", ""]
            out += entry
        return out

    has_efforts = any(len(v) > 0 for k, v in groups.items() if k)
    if not has_efforts:
        lines += _doc_entries(groups[""])
    else:
        if groups[""]:
            lines += ["## Project Documents", ""] + _doc_entries(groups[""])
        for e in sorted(pg.efforts, key=lambda e: (e.name.lower(), e.id)):
            docs_in_effort = groups.get(e.iri, [])
            lines += [f"## {e.name}", ""]
            if e.description:
                lines += [e.description, ""]
            if docs_in_effort:
                lines += _doc_entries(docs_in_effort)
            else:
                lines += ["_No documents in this effort._", ""]

    return "\n".join(lines).rstrip("\n") + "\n"


def project_full_markdown(pg: ProjectGraph,
                          repos: list[tuple[str, str]] | None = None) -> str:
    """A project's `Projects/<slug>/AGENTS.md` document block for the agentic-harness tree
    (Antigravity / Claude Code / Claude Desktop): the FULL document context inline — per
    document the description, Drive ID, link, modified date, and tags, grouped by effort —
    plus an optional Workspace Layout section listing repos cloned beside this file. There
    is NO companion details file here (single self-contained AGENTS.md). Capped per group.

    `repos` is a list of (url, dirname) pairs — one entry per cloned checkout. Pass None
    (or omit) when the project has no repo.

    This returns only the GENERATED block; a project's human-authored prose is prepended by
    the planner as a separate, protected section."""
    lines: list[str] = []
    if repos:
        verb = "repositories are" if len(repos) > 1 else "repository is"
        lines += [
            "## Workspace Layout",
            "",
            f"This project's {verb} cloned alongside this file:",
            "",
        ]
        for url, dirname in repos:
            lines.append(f"- `{dirname}/` — `{url}`")
        lines.append("")
    lines += [
        f"# {pg.name} — documents",
        "",
        "Full document context, generated from the knowledge graph. To change it, edit "
        f"`registry/graph/{pg.slug}.jsonld` and redeploy.",
        "",
    ]
    if not pg.documents:
        lines.append("_No documents mapped yet._")
        return "\n".join(lines) + "\n"

    groups: dict[str, list[Document]] = {"": []}
    for e in pg.efforts:
        groups[e.iri] = []
    for d in _by_recency(pg.documents):
        groups.setdefault(d.is_part_of or "", []).append(d)

    def _entries(docs: list[Document]) -> list[str]:
        shown, omitted = _cap(docs)
        out: list[str] = []
        for d in shown:
            entry = [
                f"### {d.name}",
                f"- **ID:** `{d.drive_id}`",
                f"- **Link:** {d.drive_url}",
                f"- **Modified:** {d.date_modified}",
            ]
            if d.keywords:
                entry.append(f"- **Tags:** {d.keywords}")
            entry += ["", d.description or "_No description._", ""]
            out += entry
        if omitted:
            out += [f"_…and {omitted} more document(s) "
                    f"(edit `registry/graph/{pg.slug}.jsonld`)._", ""]
        return out

    has_efforts = any(len(v) > 0 for k, v in groups.items() if k)
    if not has_efforts:
        lines += _entries(groups[""])
    else:
        if groups[""]:
            lines += ["## Project Documents", ""] + _entries(groups[""])
        for e in sorted(pg.efforts, key=lambda e: (e.name.lower(), e.id)):
            docs_in_effort = groups.get(e.iri, [])
            lines += [f"## {e.name}", ""]
            if e.description:
                lines += [e.description, ""]
            if docs_in_effort:
                lines += _entries(docs_in_effort)
            else:
                lines += ["_No documents in this effort._", ""]

    return "\n".join(lines).rstrip("\n") + "\n"


def _by_recency(documents: list) -> list:
    """Documents newest-first, then by name — the stable order both files render in."""
    return sorted(documents, key=lambda d: (d.date_modified, d.name), reverse=True)


def _cell(text: str) -> str:
    """Escape a value for a one-line Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()
