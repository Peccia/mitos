"""The knowledge graph: a lean, schema.org index of each project's Workspace documents.

the knowledge-graph design. The graph is an *index, not a knowledge base*: it exists
only to route an agent to the correct, current document. Exactly two entity types —
`schema:Project` and `schema:DigitalDocument` — keyed by `http://peccia.net/` IRIs, with
the Drive ID as each document's natural key. No blank nodes (validation rejects them), no
content snapshots, no CRUD history. Provenance lives in git + inbox, not here.

Isolation rule (the boring-beats-clever rule): rdflib is imported lazily inside this
module so the rest of the compiler never pays for it unless registry/graph/ holds files.

Storage is one canonical JSON-LD file per project (`registry/graph/<slug>.jsonld`):
deterministic, sorted, IRI-only, so git diffs stay clean and merges conflict-light.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path

# ── Vocabulary (public schema.org + Paul's IRI namespace) ────────────────────
SCHEMA = "https://schema.org/"
PECCIA = "http://peccia.net/"
PROJECT_NS = PECCIA + "project/"
DOCUMENT_NS = PECCIA + "document/"

# The @context every stored graph carries (kept verbatim in canonical output). An
# explicit @vocab — not the bare "https://schema.org" string — so terms resolve offline
# and deterministically to https://schema.org/<term> without fetching a remote context.
JSONLD_CONTEXT = {"@vocab": SCHEMA}


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

    @property
    def iri(self) -> str:
        return DOCUMENT_NS + self.drive_id

    @property
    def drive_url(self) -> str:
        return f"https://drive.google.com/open?id={self.drive_id}"


@dataclass
class ProjectGraph:
    slug: str                                   # IRI suffix under project/
    name: str                                   # schema:name
    description: str                            # schema:description ("" if absent)
    documents: list[Document] = field(default_factory=list)
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
    projects, docs = _parse_nodes(path.read_text(encoding="utf-8"), path.name)
    if len(projects) != 1:
        raise GraphError(
            f"{path.name}: expected exactly one schema:Project node, found "
            f"{len(projects)} — one project graph per file")
    proj_iri, (proj_name, proj_desc) = next(iter(projects.items()))
    slug = proj_iri[len(PROJECT_NS):]
    for part_of, _doc in docs:
        if part_of != proj_iri:
            raise GraphError(
                f"{path.name}: document isPartOf {part_of} but this file's project is "
                f"{proj_iri}")
    documents = sorted((d for _p, d in docs), key=lambda d: (d.name.lower(), d.drive_id))
    return ProjectGraph(slug=slug, name=proj_name, description=proj_desc,
                        documents=documents, path=path)


def _parse_nodes(text: str, label: str) -> tuple[dict, list]:
    """The shared JSON-LD parser/validator behind load_project_graph (a whole file) and
    parse_fragment (an inbox candidate). Returns ({project_iri: (name, description)},
    [(isPartOf_iri, Document)]). Raises GraphError on a blank node, an unknown type, an
    out-of-namespace IRI, or a missing/duplicated required field. The caller decides
    project cardinality and isPartOf consistency."""
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

    projects: dict[str, tuple[str, str]] = {}     # iri -> (name, description)
    docs: list[tuple[str, Document]] = []
    allowed = {str(SDO("Project")), str(SDO("DigitalDocument"))}
    for subj in set(g.subjects()):
        types = {str(t) for t in g.objects(subj, RDF.type)}
        if not types:
            raise GraphError(f"{label}: node {subj} has no @type")
        unknown = types - allowed
        if unknown:
            raise GraphError(
                f"{label}: node {subj} has unsupported type(s) {sorted(unknown)} — only "
                f"schema:Project and schema:DigitalDocument are allowed")
        s = str(subj)
        if str(SDO("Project")) in types:
            if not s.startswith(PROJECT_NS):
                raise GraphError(f"{label}: Project IRI {s} must start with {PROJECT_NS}")
            name = _one_literal(g, subj, SDO("name"), label, "Project", "name")
            desc = g.value(subj, SDO("description"))
            projects[s] = (name, str(desc) if desc is not None else "")
        else:  # DigitalDocument
            if not s.startswith(DOCUMENT_NS):
                raise GraphError(
                    f"{label}: DigitalDocument IRI {s} must start with {DOCUMENT_NS}")
            drive_id = _one_literal(g, subj, SDO("identifier"), label, "Document",
                                    "identifier")
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
                    f"(every document must belong to a project)")
            if not str(part_of).startswith(PROJECT_NS):
                raise GraphError(
                    f"{label}: document {name!r} isPartOf {part_of} must be a "
                    f"{PROJECT_NS} IRI")
            docs.append((str(part_of), Document(drive_id=drive_id, name=name,
                                                description=description,
                                                date_modified=date_modified)))
    return projects, docs


def parse_fragment(text: str, slug: str,
                   label: str = "graph fragment") -> tuple[str | None, str | None, list]:
    """Parse a `kind: graph` candidate for one project: zero or more DigitalDocument nodes
    (and optionally the Project node) for `slug`. Returns (project_name_or_None,
    project_description_or_None, documents). Raises GraphError if any node belongs to a
    different project, or on any shape violation. The caller upserts the documents into
    registry/graph/<slug>.jsonld (the one human-gated valve — never a direct write)."""
    proj_iri = PROJECT_NS + slug
    projects, docs = _parse_nodes(text, label)
    for iri in projects:
        if iri != proj_iri:
            raise GraphError(
                f"{label}: Project node {iri} does not match project {slug!r} ({proj_iri})")
    for part_of, _doc in docs:
        if part_of != proj_iri:
            raise GraphError(
                f"{label}: document isPartOf {part_of} but the candidate is for project "
                f"{slug!r} ({proj_iri})")
    name, desc = projects.get(proj_iri, (None, None))
    return name, desc, [d for _p, d in docs]


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
    """Re-emit a ProjectGraph as canonical JSON-LD: fixed key order, documents sorted,
    one Project node followed by its documents. Identical data → identical bytes."""
    project_node: dict = {
        "@id": pg.iri,
        "@type": "Project",
        "name": pg.name,
    }
    if pg.description:
        project_node["description"] = pg.description
    graph_nodes = [project_node]
    for d in sorted(pg.documents, key=lambda d: (d.name.lower(), d.drive_id)):
        graph_nodes.append({
            "@id": d.iri,
            "@type": "DigitalDocument",
            "identifier": d.drive_id,
            "name": d.name,
            "description": d.description,
            "dateModified": d.date_modified,
            "isPartOf": {"@id": pg.iri},
        })
    doc = {"@context": JSONLD_CONTEXT, "@graph": graph_nodes}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def is_canonical(path: Path, pg: ProjectGraph) -> bool:
    """True when the file on disk already equals its canonical serialization."""
    return path.read_text(encoding="utf-8") == canonical_jsonld(pg)


# ── Mutation (upsert-only — the knowledge-graph design) ─────────────────────
def upsert_document(pg: ProjectGraph, doc: Document) -> ProjectGraph:
    """Add a document mapping or update an existing one (matched by Drive ID). The
    fixed two-type shape means there is no general triple-retraction problem."""
    kept = [d for d in pg.documents if d.drive_id != doc.drive_id]
    kept.append(doc)
    kept.sort(key=lambda d: (d.name.lower(), d.drive_id))
    return ProjectGraph(slug=pg.slug, name=pg.name, description=pg.description,
                        documents=kept, path=pg.path)


def remove_document(pg: ProjectGraph, drive_id: str) -> ProjectGraph:
    """Drop a document mapping (a doc that left the project)."""
    kept = [d for d in pg.documents if d.drive_id != drive_id]
    return ProjectGraph(slug=pg.slug, name=pg.name, description=pg.description,
                        documents=kept, path=pg.path)


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

# Descriptions in the lightweight index are clamped so the always-loaded file stays small;
# the full text lives in the details file.
_INDEX_DESC_MAX = 100


def project_index_markdown(pg: ProjectGraph) -> str:
    """A project's `Projects/<slug>/AGENTS.md`: the LIGHTWEIGHT index the harness auto-loads
    on every request — title (linked), a clamped one-line description, last-modified. The
    full descriptions, Drive IDs, and links live in the on-demand details file, named in the
    pointer line below. Fetch the live doc by its Drive ID; the index is current as of the
    last deploy, the content always is."""
    lines = [
        f"# {pg.name} — documents",
        "",
        "Lightweight document index, generated from the knowledge graph. Full descriptions, "
        f"Drive IDs, and links are in [`{DETAILS_FILENAME}`]({DETAILS_FILENAME}). To change "
        f"this list, edit `registry/graph/{pg.slug}.jsonld` and redeploy.",
        "",
    ]
    if not pg.documents:
        lines.append("_No documents mapped yet._")
        return "\n".join(lines) + "\n"
    lines += ["| Document | Description | Modified |", "|---|---|---|"]
    for d in _by_recency(pg.documents):
        lines.append(f"| [{_cell(d.name)}]({d.drive_url}) | {_cell(_clamp(d.description))} "
                     f"| {_cell(d.date_modified)} |")
    return "\n".join(lines).rstrip("\n") + "\n"


def project_details_markdown(pg: ProjectGraph) -> str:
    """A project's `Projects/<slug>/AGENTS_DETAILS.md`: the DETAILED reference, read on
    demand — per document the full `schema:description`, the Drive ID, the link, and the
    modified date. Generated and non-adoptable, like the index."""
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
    for d in _by_recency(pg.documents):
        lines += [
            f"## {d.name}",
            f"- **Drive ID:** `{d.drive_id}`",
            f"- **Link:** {d.drive_url}",
            f"- **Modified:** {d.date_modified}",
            "",
            d.description or "_No description._",
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _by_recency(documents: list) -> list:
    """Documents newest-first, then by name — the stable order both files render in."""
    return sorted(documents, key=lambda d: (d.date_modified, d.name), reverse=True)


def _clamp(text: str, limit: int = _INDEX_DESC_MAX) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _cell(text: str) -> str:
    """Escape a value for a one-line Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()
