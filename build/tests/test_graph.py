"""Knowledge-graph and review/propose tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _sandbox_deploy,
    _git_available, _run_git, _make_overlay_hub, _clone_overlay, _seed_overlay,
)

def test_graph_loads_validates_and_is_canonical():
    from agentic import graph
    # the seed graph in the real registry loads, validates, and is canonical on disk
    assert "example-project" in reg.graphs
    pg = reg.graphs["example-project"]
    assert pg.name == "Example Project" and pg.iri.endswith("/project/example-project")
    assert graph.is_canonical(pg.path, pg)

def test_graph_canonical_is_deterministic_and_sorted():
    from agentic import graph
    pg = graph.ProjectGraph(slug="example-project", name="Example Project", description="d",
                            documents=[_doc("zID", "Zeta", "z", "2026-01-01"),
                                       _doc("aID", "Alpha", "a", "2026-02-02")])
    once, twice = graph.canonical_jsonld(pg), graph.canonical_jsonld(pg)
    assert once == twice                                  # deterministic
    # documents serialize sorted by name regardless of input order
    assert once.index('"name": "Alpha"') < once.index('"name": "Zeta"')
    # round-trips: parse the canonical text back and re-emit identically
    p = _write_graph(once)
    try:
        reloaded = graph.load_project_graph(p)
        assert graph.canonical_jsonld(reloaded) == once
    finally:
        p.unlink()

def test_graph_upsert_is_keyed_on_drive_id():
    from agentic import graph
    pg = graph.ProjectGraph(slug="example-project", name="AP", description="",
                            documents=[_doc("D1", "Spec", "old", "2026-01-01")])
    pg = graph.upsert_document(pg, _doc("D1", "Spec v2", "new", "2026-03-03"))  # update
    pg = graph.upsert_document(pg, _doc("D2", "Other", "x", "2026-02-02"))      # add
    by_id = {d.drive_id: d for d in pg.documents}
    assert len(pg.documents) == 2
    assert by_id["D1"].name == "Spec v2" and by_id["D1"].description == "new"
    pg = graph.remove_document(pg, "D1")
    assert [d.drive_id for d in pg.documents] == ["D2"]

def test_graph_sparql_lists_documents_newest_first():
    from agentic import graph
    pg = graph.ProjectGraph(slug="example-project", name="AP", description="",
                            documents=[_doc("D1", "Older", "o", "2026-01-01"),
                                       _doc("D2", "Newer", "n", "2026-09-09")])
    rows = graph.run_query(pg, "documents")
    assert [r["name"] for r in rows] == ["Newer", "Older"]      # ORDER BY DESC(modified)
    assert rows[0]["id"] == "D2"

def test_graph_rejects_malformed_inputs():
    from agentic import graph
    SC = '{"@vocab":"https://schema.org/"}'
    cases = {
        "blank node":   '{"@context":%s,"@graph":[{"@type":"Project","name":"x"}]}' % SC,
        "bad type":     '{"@context":%s,"@graph":[{"@id":"http://peccia.net/project/p",'
                        '"@type":"Thing","name":"x"}]}' % SC,
        "off-namespace": '{"@context":%s,"@graph":[{"@id":"http://evil.com/p",'
                        '"@type":"Project","name":"x"}]}' % SC,
        "two projects": '{"@context":%s,"@graph":['
                        '{"@id":"http://peccia.net/project/a","@type":"Project","name":"A"},'
                        '{"@id":"http://peccia.net/project/b","@type":"Project","name":"B"}]}' % SC,
    }
    for label, text in cases.items():
        p = _write_graph(text)
        try:
            graph.load_project_graph(p)
            raise AssertionError(f"expected GraphError for: {label}")
        except graph.GraphError:
            pass
        finally:
            p.unlink()

def test_graph_rejects_document_missing_field_and_bad_key():
    from agentic import graph
    SC = '{"@vocab":"https://schema.org/"}'
    # a document missing schema:description
    missing = ('{"@context":%s,"@graph":['
               '{"@id":"http://peccia.net/project/example-project","@type":"Project","name":"AP"},'
               '{"@id":"http://peccia.net/document/D1","@type":"DigitalDocument",'
               '"identifier":"D1","name":"Spec","dateModified":"2026-01-01",'
               '"isPartOf":{"@id":"http://peccia.net/project/example-project"}}]}' % SC)
    # a document whose IRI suffix != its identifier (the Drive ID must be the key)
    badkey = ('{"@context":%s,"@graph":['
              '{"@id":"http://peccia.net/project/example-project","@type":"Project","name":"AP"},'
              '{"@id":"http://peccia.net/document/WRONG","@type":"DigitalDocument",'
              '"identifier":"D1","name":"Spec","description":"d",'
              '"dateModified":"2026-01-01",'
              '"isPartOf":{"@id":"http://peccia.net/project/example-project"}}]}' % SC)
    for text in (missing, badkey):
        p = _write_graph(text)
        try:
            graph.load_project_graph(p)
            raise AssertionError("expected GraphError")
        except graph.GraphError:
            pass
        finally:
            p.unlink()

def test_graph_materialization_markdown_split():
    from agentic import graph
    long_desc = "A spec for the forecast UI. " * 8
    pg = graph.ProjectGraph(slug="example-project", name="Example Project",
                            description="forecasting",
                            documents=[_doc("1AbC", "Forecast Spec", long_desc,
                                            "2026-06-14")])
    roster = graph.roster_markdown([pg])
    assert "Example Project" in roster and "`example-project`" in roster and "forecasting" in roster

    # lightweight index: titles only (bullet list), pointer to details; no link/ID/desc/date
    idx = graph.project_index_markdown(pg)
    assert "Forecast Spec" in idx                               # title present
    assert graph.DETAILS_FILENAME in idx                        # pointer to details
    assert "https://drive.google.com/open?id=1AbC" not in idx  # link lives in details
    assert "`1AbC`" not in idx                                  # raw ID lives in details
    assert "2026-06-14" not in idx                              # modified date lives in details
    assert long_desc.strip() not in idx                         # description not in index

    # detailed reference: full description, Drive ID, link
    det = graph.project_details_markdown(pg)
    assert "`1AbC`" in det and long_desc.strip() in det
    assert "https://drive.google.com/open?id=1AbC" in det

    empty = graph.ProjectGraph(slug="x", name="X", description="", documents=[])
    assert "_No documents mapped yet._" in graph.project_index_markdown(empty)
    assert "_No documents mapped yet._" in graph.project_details_markdown(empty)

def test_project_full_markdown_inlines_docs_repo_and_caps():
    from agentic import graph
    docs = [_doc(f"id{i:03}", f"Doc {i:03}", f"desc {i}", f"2026-01-{(i % 28) + 1:02}")
            for i in range(graph.INDEX_LIMIT + 5)]
    pg = graph.ProjectGraph(slug="apdict", name="Ascenzio", description="d", documents=docs)
    full = graph.project_full_markdown(pg, [("git@github.com:Peccia/x.git", "x")])
    # full doc context inline (id + link + per-doc detail), no separate details file needed
    assert "**ID:**" in full and "https://drive.google.com/open?id=" in full
    # repo Workspace Layout names the sibling checkout dir + the clone URL
    assert "## Workspace Layout" in full and "`x/`" in full
    assert "git@github.com:Peccia/x.git" in full
    assert "repository is" in full      # singular phrasing
    # curation cap: at most INDEX_LIMIT entries, with an "…and N more" footer
    assert full.count("### Doc ") == graph.INDEX_LIMIT
    assert "and 5 more document(s)" in full
    # no repo section when the project has no repo
    assert "## Workspace Layout" not in graph.project_full_markdown(pg)

def test_project_full_markdown_multi_repo_workspace_layout():
    from agentic import graph
    pg = graph.ProjectGraph(slug="multi", name="Multi", description="d", documents=[])
    repos = [
        ("git@github.com:you/frontend.git", "frontend"),
        ("git@github.com:you/backend.git", "backend"),
    ]
    full = graph.project_full_markdown(pg, repos)
    assert "## Workspace Layout" in full
    assert "repositories are" in full   # plural phrasing
    assert "`frontend/` — `git@github.com:you/frontend.git`" in full
    assert "`backend/` — `git@github.com:you/backend.git`" in full

def test_graph_keywords_round_trip():
    """schema:keywords is optional; present → emitted + shown in details; absent → omitted."""
    import json
    from agentic import graph
    doc_with = graph.Document("D1", "Spec", "desc", "2026-01-01", keywords="strategy, Q4")
    doc_without = graph.Document("D2", "Brief", "desc", "2026-01-01")
    pg = graph.ProjectGraph(slug="p", name="P", description="", documents=[doc_with, doc_without])

    # canonical serialization: keywords only for doc_with
    raw = graph.canonical_jsonld(pg)
    data = json.loads(raw)
    nodes = {n["identifier"]: n for n in data["@graph"] if n.get("@type") == "DigitalDocument"}
    assert nodes["D1"]["keywords"] == "strategy, Q4"
    assert "keywords" not in nodes["D2"]

    # round-trip: load → graph equals original
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mktemp(suffix=".jsonld"))
    proj_node = {"@id": "http://peccia.net/project/p", "@type": "Project", "name": "P"}
    full = {"@context": {"@vocab": "https://schema.org/"}, "@graph": [proj_node] + list(nodes.values()) +
            [{"@id": "http://peccia.net/project/p", "@type": "Project", "name": "P"}]}
    # write canonical directly and load it
    p.write_text(raw, encoding="utf-8")
    pg2 = graph.load_project_graph(p)
    p.unlink()
    d1 = next(d for d in pg2.documents if d.drive_id == "D1")
    d2 = next(d for d in pg2.documents if d.drive_id == "D2")
    assert d1.keywords == "strategy, Q4"
    assert d2.keywords == ""

    # details file: tags line present for D1, absent for D2
    det = graph.project_details_markdown(pg)
    assert "**Tags:** strategy, Q4" in det
    assert det.count("**Tags:**") == 1     # D2 has no tags line

    # index: no tags in the lightweight index
    idx = graph.project_index_markdown(pg)
    assert "Tags" not in idx

def test_graph_web_url_round_trip_and_drive_fallback():
    """schema:url is optional; when present it is serialized, loaded, and used as the link.
    When absent, drive_url falls back to the synthesized Google Drive URL so existing graphs
    (no url field) still render correctly."""
    import json, tempfile
    from pathlib import Path
    from agentic import graph
    doc_with_url = graph.Document("ID1", "Spec", "desc", "2026-01-01",
                                  web_url="https://example.com/spec")
    doc_without_url = graph.Document("ID2", "Brief", "desc", "2026-01-01")
    pg = graph.ProjectGraph(slug="p", name="P", description="",
                            documents=[doc_with_url, doc_without_url])

    # canonical serialization: url only for doc_with_url
    raw = graph.canonical_jsonld(pg)
    data = json.loads(raw)
    nodes = {n["identifier"]: n for n in data["@graph"] if n.get("@type") == "DigitalDocument"}
    assert nodes["ID1"]["url"] == "https://example.com/spec"
    assert "url" not in nodes["ID2"]

    # round-trip: load preserves web_url; absent field stays empty
    p = Path(tempfile.mktemp(suffix=".jsonld"))
    p.write_text(raw, encoding="utf-8")
    pg2 = graph.load_project_graph(p)
    p.unlink()
    d1 = next(d for d in pg2.documents if d.drive_id == "ID1")
    d2 = next(d for d in pg2.documents if d.drive_id == "ID2")
    assert d1.web_url == "https://example.com/spec"
    assert d2.web_url == ""

    # drive_url property: uses web_url when set; synthesizes Drive link as fallback
    assert d1.drive_url == "https://example.com/spec"
    assert d2.drive_url == "https://drive.google.com/open?id=ID2"

    # markdown renders the correct link for each document
    det = graph.project_details_markdown(pg2)
    assert "https://example.com/spec" in det
    assert "https://drive.google.com/open?id=ID2" in det

    # label is now neutral **ID:** not **Drive ID:**
    assert "**ID:**" in det
    assert "Drive ID" not in det

def test_graph_web_url_flows_through_bootstrap_to_registry():
    """webUrl from the connector survives files_to_documents → propose_graph_change →
    accept → registry, so the stored graph carries the store-agnostic link."""
    import json
    from agentic import graph, loader, review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    mock = MockConnector(files=[
        {"id": "F1", "name": "Spec", "dateModified": "2026-06-18",
         "webUrl": "https://notion.so/spec-page"}])
    out = bootstrap_to_inbox(treg, mock, "example-project")
    assert out["ok"]
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"]
    pg = graph.load_project_graph(
        tmp / "registry" / "graph" / "example-project.jsonld")
    d = next(d for d in pg.documents if d.drive_id == "F1")
    assert d.web_url == "https://notion.so/spec-page"
    assert d.drive_url == "https://notion.so/spec-page"  # no Drive fallback needed

def test_graph_effort_crud_and_doc_reset():
    """upsert_effort / remove_effort round-trip; remove_effort resets child docs."""
    from agentic import graph
    proj_iri = graph.PROJECT_NS + "p"
    effort = graph.CreativeWork(id="auth", name="Auth Rework", description="JWT migration",
                                is_part_of=proj_iri)
    pg = graph.ProjectGraph(slug="p", name="P", description="")
    pg = graph.upsert_effort(pg, effort)
    assert len(pg.efforts) == 1 and pg.efforts[0].id == "auth"

    # doc parented to the effort
    doc = graph.Document("D1", "Spec", "d", "2026-01-01", is_part_of=effort.iri)
    pg = graph.upsert_document(pg, doc)
    assert pg.documents[0].is_part_of == effort.iri

    # remove the effort — child doc's is_part_of resets to ""
    pg = graph.remove_effort(pg, "auth")
    assert not pg.efforts
    assert pg.documents[0].is_part_of == ""

    # upsert is idempotent
    pg = graph.upsert_effort(pg, effort)
    pg = graph.upsert_effort(pg, graph.CreativeWork(id="auth", name="Auth (updated)",
                                                     description="", is_part_of=proj_iri))
    assert len(pg.efforts) == 1 and pg.efforts[0].name == "Auth (updated)"

def test_graph_effort_canonical_round_trip():
    """canonical_jsonld includes CreativeWork nodes; load_project_graph parses them back."""
    from agentic import graph
    proj_iri = graph.PROJECT_NS + "my-proj"
    effort = graph.CreativeWork(id="phase-1", name="Phase 1", description="initial sprint",
                                is_part_of=proj_iri)
    doc_in_effort = graph.Document("D1", "Spec", "desc", "2026-02-01",
                                   is_part_of=effort.iri)
    doc_at_root = graph.Document("D2", "Notes", "n", "2026-01-01")
    pg = graph.ProjectGraph(slug="my-proj", name="My Project", description="demo",
                            documents=[doc_in_effort, doc_at_root], efforts=[effort])
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "my-proj.jsonld"
        p.write_text(graph.canonical_jsonld(pg), encoding="utf-8")
        loaded = graph.load_project_graph(p)
        assert graph.is_canonical(p, loaded)
    assert len(loaded.efforts) == 1 and loaded.efforts[0].id == "phase-1"
    assert loaded.efforts[0].description == "initial sprint"
    by_id = {d.drive_id: d for d in loaded.documents}
    assert by_id["D1"].is_part_of == effort.iri
    assert by_id["D2"].is_part_of == ""

def test_graph_effort_grouping_in_markdown():
    """project_index_markdown and project_details_markdown group docs under effort headers."""
    from agentic import graph
    proj_iri = graph.PROJECT_NS + "proj"
    effort = graph.CreativeWork(id="sprint-1", name="Sprint 1", description="first sprint",
                                is_part_of=proj_iri)
    root_desc = "root document description unique-xray"
    sprint_desc = "sprint document description unique-zulu"
    pg = graph.ProjectGraph(
        slug="proj", name="Proj", description="",
        documents=[
            graph.Document("D1", "Root Doc", root_desc, "2026-01-01"),
            graph.Document("D2", "Sprint Doc", sprint_desc, "2026-02-01",
                           is_part_of=effort.iri),
        ],
        efforts=[effort])
    idx = graph.project_index_markdown(pg)
    assert "Sprint 1" in idx                          # effort header present
    assert "Project Documents" in idx                 # root section present
    assert "Root Doc" in idx and "Sprint Doc" in idx
    assert root_desc not in idx and sprint_desc not in idx   # descriptions absent from index

    det = graph.project_details_markdown(pg)
    assert "Sprint 1" in det and "first sprint" in det   # effort desc in details
    assert "Root Doc" in det and "Sprint Doc" in det
    assert "`D1`" in det and "`D2`" in det
    assert root_desc in det and sprint_desc in det

def test_graph_effort_validation_errors():
    """_parse_nodes rejects invalid effort IDs, wrong namespaces, and docs parented to
    unknown efforts."""
    from agentic import graph
    SC = '{"@vocab":"https://schema.org/"}'
    proj_iri = "http://peccia.net/project/p"

    # effort IRI not in CREATIVE_WORK_NS
    bad_ns = ('{"@context":%s,"@graph":['
              '{"@id":"%s","@type":"Project","name":"P"},'
              '{"@id":"http://peccia.net/OTHER/e","@type":"CreativeWork",'
              '"name":"E","isPartOf":{"@id":"%s"}}]}' % (SC, proj_iri, proj_iri))
    try:
        graph._parse_nodes(bad_ns, "t")
        raise AssertionError("expected GraphError for wrong effort namespace")
    except graph.GraphError:
        pass

    # effort ID with leading hyphen fails regex
    bad_id = ('{"@context":%s,"@graph":['
              '{"@id":"%s","@type":"Project","name":"P"},'
              '{"@id":"http://peccia.net/creativework/-bad","@type":"CreativeWork",'
              '"name":"E","isPartOf":{"@id":"%s"}}]}' % (SC, proj_iri, proj_iri))
    try:
        graph._parse_nodes(bad_id, "t")
        raise AssertionError("expected GraphError for invalid effort id")
    except graph.GraphError:
        pass

    # doc isPartOf an unknown effort IRI (not defined in the file)
    orphan = ('{"@context":%s,"@graph":['
              '{"@id":"%s","@type":"Project","name":"P"},'
              '{"@id":"http://peccia.net/document/D1","@type":"DigitalDocument",'
              '"identifier":"D1","name":"Doc","description":"d","dateModified":"2026-01-01",'
              '"isPartOf":{"@id":"http://peccia.net/creativework/unknown"}}]}' % (SC, proj_iri))
    try:
        graph._parse_nodes(orphan, "t")
        raise AssertionError("expected GraphError for doc with unknown effort parent")
    except graph.GraphError:
        pass

def test_propose_graph_change_with_efforts():
    """propose_graph_change accepts efforts + effort_removals; accepted candidate upserts
    the effort into the graph and resets child docs on effort removal."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)

    proj_iri = graph.PROJECT_NS + "example-project"
    existing_effort = graph.CreativeWork(id="phase-1", name="Phase 1", description="old",
                                         is_part_of=proj_iri)
    seed = graph.ProjectGraph(slug="example-project", name="Example Project", description="d",
                              efforts=[existing_effort],
                              documents=[
                                  graph.Document("D1", "Doc1", "d", "2026-01-01",
                                                 is_part_of=existing_effort.iri)])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    # propose a new effort and a doc parented to it
    out = review.propose_graph_change(
        treg, "example-project",
        [{"id": "D2", "name": "New Doc", "description": "nd", "dateModified": "2026-06-01",
          "parentId": "sprint-a"}],
        efforts=[{"id": "sprint-a", "name": "Sprint A", "description": "new effort"}])
    assert out["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert set(cand["effort_ids"]) == {"phase-1", "sprint-a"}   # both efforts in fragment

    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    effort_ids = {e.id for e in merged.efforts}
    assert effort_ids == {"phase-1", "sprint-a"}
    d2 = next(d for d in merged.documents if d.drive_id == "D2")
    assert d2.is_part_of == graph.CREATIVE_WORK_NS + "sprint-a"

    # now remove phase-1 — D1 (its child) should reset to project root
    treg2 = loader.load(tmp)
    out2 = review.propose_graph_change(treg2, "example-project", [],
                                       effort_removals=["phase-1"])
    assert out2["ok"]
    acc2 = review.decide(loader.load(tmp), out2["id"], "accept", "")
    assert acc2["ok"]
    merged2 = graph.load_project_graph(gdir / "example-project.jsonld")
    assert not any(e.id == "phase-1" for e in merged2.efforts)
    d1 = next(d for d in merged2.documents if d.drive_id == "D1")
    assert d1.is_part_of == ""    # reset to project root

def test_graph_tree_emits_single_self_contained_agents_md():
    from agentic import render
    import copy
    from agentic.loader import Partial
    rig = copy.deepcopy(reg)
    rig.projects["apdict"] = {
        "name": "Ascenzio Predictions", "slug": "apdict", "_is_local": True,
        "local_path": {"example-windows": "apdict"}, "drive": {}, "agents": [],
        "context": {"assistant": "registry/context/projects/apdict.md"},
    }
    rig.partials["context/projects/apdict.md"] = Partial(
        rel="context/projects/apdict.md", audience=["agents-md"], body="Apdict prose context"
    )
    from agentic.graph import ProjectGraph
    rig.graphs["apdict"] = ProjectGraph(slug="apdict", name="Ascenzio Predictions", description="forecasts", efforts=[], path=None)
    from agentic import graph as graphmod
    rig.graphs["apdict"] = graphmod.upsert_document(
        rig.graphs["apdict"], _doc("1AbCxyz", "Forecast UI Spec", "spec", "2026-06-14"))

    win = {o.deploy_path: o for o in planner.plan_machine(rig, "example-windows")
           if o.target == "agentic-graph"}
    # real (local) graphs are present — example-project core graph steps aside
    proj = next(o for p, o in win.items() if p.endswith("Projects/apdict/AGENTS.md"))
    # one self-contained file: NO companion details file on the agentic-harness side
    assert not any(p.endswith("AGENTS_DETAILS.md") for p in win)
    assert not any(p.endswith("Projects/example-project/AGENTS.md") for p in win)
    # the project AGENTS.md is prose (protected) + a generated doc block in one file
    assert proj.drift_policy == "protect" and proj.kind == "text"
    assert proj.sources and not render.is_generated_source(proj.sources[0])
    assert [s for s, _ in proj.section_bodies if render.is_generated_source(s)], \
        "must carry a generated section tagged for marker-free split"
    # full doc context is INLINE here (id + link), unlike the lean agents-md/Hermes index
    assert "https://drive.google.com/open?id=" in proj.content
    # the roster stays wholly generated (no prose, non-adoptable)
    roster = next(o for p, o in win.items() if p.endswith("MitosAgent/AGENTS.md"))
    assert roster.drift_policy == "generated" and roster.sources == []

def test_graph_candidate_propose_accept_upserts_registry():
    from agentic import review
    treg, tmp = _temp_registry()
    # seed a project graph so the upsert merges into an existing file
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    from agentic import graph
    seed = graph.ProjectGraph(slug="example-project", name="Example Project",
                              description="d", documents=[
                                  _doc("OLD", "Existing", "kept", "2026-01-01")])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    # propose two docs (one updates nothing existing, one new) via the console producer
    out = review.propose_graph_change(treg, "example-project", [
        {"id": "NEW1", "name": "Forecast UI Spec", "description": "ui spec",
         "dateModified": "2026-06-14"}], reason="found in drive")
    assert out["ok"] and out["registry_path"] == "graph/example-project.jsonld"
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["kind"] == "graph"
    assert any(r["t"] == "ins" and "NEW1" in (r["r"] or "") for r in cand["diff"])
    # The console's pending-badge needs the target project + proposed Drive IDs surfaced on
    # the candidate (so it never re-parses the jsonld/IRI scheme client-side).
    assert cand["project"] == "example-project"
    assert cand["doc_ids"] == ["NEW1"]

    # accept upserts into registry/graph/example-project.jsonld (existing doc preserved)
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["graph/example-project.jsonld"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    ids = {d.drive_id for d in merged.documents}
    assert ids == {"OLD", "NEW1"}                               # upsert merged, didn't replace
    assert not (_inbox(tmp) / out["id"]).exists()             # candidate consumed

def test_graph_candidate_with_removals_drops_and_upserts():
    """A console draft can carry removals alongside upserts: accept drops the removed Drive
    IDs and merges the upserts, the diff renders the deletion, and removal_ids surface on the
    candidate so the tab flags the in-flight removal."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug="example-project", name="Example Project",
                              description="d", documents=[
                                  _doc("KEEP", "Keeper", "stays", "2026-01-01"),
                                  _doc("GONE", "Goner", "leaves", "2026-01-02")])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    # remove GONE and add NEW1 in one candidate
    out = review.propose_graph_change(
        treg, "example-project",
        [{"id": "NEW1", "name": "Fresh", "description": "added", "dateModified": "2026-06-14"}],
        removals=["GONE"], reason="cleanup")
    assert out["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["kind"] == "graph"
    assert cand["doc_ids"] == ["NEW1"] and cand["removal_ids"] == ["GONE"]
    # the diff shows GONE leaving (present on the current side, gone from the proposed side)
    # and NEW1 arriving — robust to whether the rows align as del/ins or chg
    assert any("GONE" in (r["l"] or "") for r in cand["diff"])
    assert not any("GONE" in (r["r"] or "") for r in cand["diff"])
    assert any("NEW1" in (r["r"] or "") for r in cand["diff"])

    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["graph/example-project.jsonld"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    assert {d.drive_id for d in merged.documents} == {"KEEP", "NEW1"}   # GONE dropped

def test_propose_graph_change_allows_removals_only():
    """A candidate may carry only removals (no upserts) — the empty guard must not reject it,
    and a removal whose id is also being upserted is dropped (the upsert wins)."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug="example-project", name="Example Project", description="d",
                              documents=[_doc("X", "Ex", "", "2026-01-01")])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    out = review.propose_graph_change(treg, "example-project", [], removals=["X"])
    assert out["ok"]
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"]
    assert graph.load_project_graph(gdir / "example-project.jsonld").documents == []

    # contradictory: id both upserted and removed → upsert wins, removal dropped
    treg = loader.load(tmp)
    out2 = review.propose_graph_change(
        treg, "example-project",
        [{"id": "Y", "name": "Why", "dateModified": "2026-02-02"}], removals=["Y"])
    assert out2["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out2["id"])
    assert cand["doc_ids"] == ["Y"] and cand["removal_ids"] == []

def test_local_project_graph_candidate_flow():
    """A project defined only in the registry/local/ overlay must route its accepted graph
    back into registry/local/graph/ — both the proposed candidate's registry_path and the
    accepted file location — so the loader (which reads local graphs when the overlay supplies
    projects) actually picks it up. A core write would silently never load."""
    from agentic import review
    import yaml
    _, tmp = _temp_registry()
    # define an overlay-only project; presence of any local project means core projects are
    # not loaded, and graphs are read only from registry/local/graph/.
    local_projects_dir = tmp / "registry" / "local" / "projects"
    local_projects_dir.mkdir(parents=True, exist_ok=True)
    (local_projects_dir / "private.yaml").write_text(
        yaml.safe_dump({"slug": "private", "name": "Private Project", "stage": "build"}),
        encoding="utf-8")
    treg = loader.load(tmp)
    assert treg.projects["private"]["_is_local"] is True

    # propose its first document mapping — the candidate must target the overlay path
    out = review.propose_graph_change(treg, "private", [
        {"id": "NEW1", "name": "Private Spec", "description": "spec",
         "dateModified": "2026-06-14"}], reason="found in drive")
    assert out["ok"] and out["registry_path"] == "local/graph/private.jsonld"
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["kind"] == "graph"
    assert cand["registry_path"] == "local/graph/private.jsonld"

    # accept writes into registry/local/graph/, NOT the core registry/graph/
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["local/graph/private.jsonld"]
    assert (tmp / "registry" / "local" / "graph" / "private.jsonld").is_file()
    assert not (tmp / "registry" / "graph" / "private.jsonld").exists()

    # and the freshly accepted graph actually loads (the bug: it used to vanish as "no graph yet")
    reloaded = loader.load(tmp)
    assert "private" in reloaded.graphs
    assert {d.drive_id for d in reloaded.graphs["private"].documents} == {"NEW1"}

def test_propose_graph_change_rejects_unknown_project_and_empty():
    from agentic import review
    treg, _tmp = _temp_registry()
    assert not review.propose_graph_change(treg, "no-such", [{"id": "x", "name": "y",
        "dateModified": "2026-01-01"}])["ok"]
    assert not review.propose_graph_change(treg, "example-project", [])["ok"]

def test_graph_tree_deploys_only_on_claude_code_env():
    import copy
    from agentic.loader import Partial
    rig = copy.deepcopy(reg)
    rig.projects["apdict"] = {
        "name": "Ascenzio Predictions", "slug": "apdict", "_is_local": True,
        "local_path": {"example-windows": "apdict"}, "drive": {}, "agents": [],
        "context": {"assistant": "registry/context/projects/apdict.md"},
    }
    rig.partials["context/projects/apdict.md"] = Partial(
        rel="context/projects/apdict.md", audience=["agents-md"], body="Apdict prose context"
    )
    from agentic.graph import ProjectGraph
    rig.graphs["apdict"] = ProjectGraph(slug="apdict", name="Ascenzio Predictions", description="forecasts", efforts=[], path=None)

    # example-linux has no claude-code target → no Agentic Context tree
    linux = [o for o in planner.plan_machine(rig, "example-linux")
             if o.target == "agentic-graph"]
    assert linux == []
    # example-windows (claude-code + agentic_context_root) → roster + per-project index
    win = {o.deploy_path: o for o in planner.plan_machine(rig, "example-windows")
           if o.target == "agentic-graph"}
    assert any(p.endswith("MitosAgent/AGENTS.md") for p in win)
    # local graphs present → local project entries, not core example-project
    assert any(p.endswith("MitosAgent/Projects/apdict/AGENTS.md") for p in win)
    assert not any(p.endswith("MitosAgent/Projects/example-project/AGENTS.md") for p in win)
    for o in win.values():
        # roster is generated; per-project files are prose(protect) + generated block
        assert o.kind == "text" and o.drift_policy in ("generated", "protect")
        assert "DO NOT EDIT" not in o.content and "begin:" not in o.content  # raw context
        assert "<!-- " not in o.content   # marker-free (invariant #5)

def test_graph_tree_round_trips_and_regenerates_without_capture():
    import copy

    from agentic import graph
    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    # inject a document into a local (active) graph so the per-project index renders a table row;
    # apdict is a local graph so it is always in active_graphs regardless of overlay state
    reg2 = copy.deepcopy(reg)
    if "apdict" not in reg2.projects:
        reg2.projects["apdict"] = {
            "name": "Ascenzio Predictions", "slug": "apdict", "_is_local": True,
            "local_path": {"example-windows": "apdict"}, "drive": {}, "agents": [], "context": {},
        }
    if "apdict" not in reg2.graphs:
        reg2.graphs["apdict"] = graph.ProjectGraph(slug="apdict", name="Ascenzio Predictions", description="forecasts", efforts=[], path=None)
    reg2.graphs["apdict"] = graph.upsert_document(
        reg2.graphs["apdict"], _doc("1AbCxyz", "Forecast UI Spec", "spec", "2026-06-14"))
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-graph-"))
    assert cmd_deploy(reg2, "example-windows", dry_run=False, force=False, root=root) == 0
    idx = root / safe_rel("C:/MitosAgent/Projects/apdict/AGENTS.md")
    assert "Forecast UI Spec" in idx.read_text(encoding="utf-8")
    roster = root / safe_rel("C:/MitosAgent/AGENTS.md")
    assert "Ascenzio Predictions" in roster.read_text(encoding="utf-8")

    # edit the generated roster in place, then redeploy: it is silently regenerated
    # (non-adoptable) and nothing is captured to inbox/ (no partial to route back to)
    roster.write_text("hand edit\n", encoding="utf-8", newline="\n")
    before = sorted((_inbox(root)).iterdir()) if (_inbox(root)).exists() else []
    assert cmd_deploy(reg2, "example-windows", dry_run=False, force=False, root=root) == 0
    assert "Ascenzio Predictions" in roster.read_text(encoding="utf-8")   # overwritten
    after = sorted((_inbox(root)).iterdir()) if (_inbox(root)).exists() else []
    assert before == after, "a generated file must not capture an inbox candidate"

