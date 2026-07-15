"""Tests for build/agentic/staging.py — the pure, offline multi-listing helpers shared by
review.py (the console) and connectors/bootstrap.py (the CLI writer). No registry, no
connector, no network — these are unit tests over plain dicts."""
from __future__ import annotations


def test_scope_key_deterministic_and_excludes_exclude_folders():
    """scope_key identity is (store, folder_id, query, recursive) only — exclude_folders is
    a filter, not identity, so editing a server's exclude list must not fork a duplicate
    watch on next stage."""
    from agentic import staging
    base = {"store": "gws", "folder_id": "F1", "query": None, "recursive": True,
            "exclude_folders": ["A"]}
    same_minus_excl = {**base, "exclude_folders": []}
    same_diff_excl = {**base, "exclude_folders": ["B", "C"]}
    assert staging.scope_key(base) == staging.scope_key(same_minus_excl) == staging.scope_key(same_diff_excl)

    diff_folder = {**base, "folder_id": "F2"}
    diff_store = {**base, "store": "other"}
    diff_recursive = {**base, "recursive": False}
    diff_query = {**base, "folder_id": None, "query": "q"}
    keys = {staging.scope_key(base), staging.scope_key(diff_folder), staging.scope_key(diff_store),
            staging.scope_key(diff_recursive), staging.scope_key(diff_query)}
    assert len(keys) == 5, "each identity-relevant field must change the key"


def test_scope_key_normalizes_falsy_variants():
    """None/""/missing all collapse to the same identity for a field — a caller that omits
    `query` and one that passes query=None must produce the same key."""
    from agentic import staging
    a = staging.scope_key({"folder_id": "F1"})
    b = staging.scope_key({"folder_id": "F1", "query": None, "store": "", "recursive": False})
    assert a == b


def test_is_full_scope():
    from agentic import staging
    assert staging.is_full_scope({}) is True
    assert staging.is_full_scope({"folder_id": None, "query": None}) is True
    assert staging.is_full_scope({"folder_id": "F1"}) is False
    assert staging.is_full_scope({"query": "q"}) is False


def test_scope_label():
    from agentic import staging
    assert staging.scope_label({}) == "unscoped"
    assert staging.scope_label({"query": "forecast"}) == 'query "forecast"'
    assert staging.scope_label({"folder_id": "F1"}) == "folder F1"
    assert staging.scope_label({"folder_id": "F1", "recursive": True}) == "folder F1 (recursive)"


def test_normalize_staging_wraps_legacy_single_listing_shape():
    """A pre-multi-scope file (documents/staged_at/connector/scope at the TOP level, no
    "listings" key) must keep reading forever as one listing with a computed scope_key."""
    from agentic import staging
    legacy = {"slug": "x", "staged_at": "T", "connector": "mock",
              "scope": {"query": "q"}, "documents": [{"id": "D1", "name": "n"}]}
    listings = staging.normalize_staging(legacy)
    assert len(listings) == 1
    l = listings[0]
    assert l["staged_at"] == "T" and l["connector"] == "mock"
    assert l["documents"] == [{"id": "D1", "name": "n"}]
    assert l["scope_key"] == staging.scope_key({"query": "q"})


def test_normalize_staging_reads_current_listings_shape():
    from agentic import staging
    data = {"slug": "x", "listings": [
        {"scope_key": "abc", "staged_at": "T1", "connector": "mock",
         "scope": {"query": "q1"}, "documents": [{"id": "A"}]},
        {"scope_key": "def", "staged_at": "T2", "connector": "mock",
         "scope": {"query": "q2"}, "documents": [{"id": "B"}]},
    ]}
    listings = staging.normalize_staging(data)
    assert [l["scope_key"] for l in listings] == ["abc", "def"]


def test_normalize_staging_drops_malformed_entries_without_raising():
    """Staging data is best-effort curation state, not a source of truth — a malformed
    listing entry (not a dict) or an absent documents list is dropped, never raised."""
    from agentic import staging
    data = {"slug": "x", "listings": ["not a dict", {"scope": {}, "documents": "not a list"}]}
    listings = staging.normalize_staging(data)
    assert len(listings) == 1 and listings[0]["documents"] == []
    assert staging.normalize_staging({"slug": "x"}) == []          # no documents, no listings
    assert staging.normalize_staging({"slug": "x", "documents": "nope"}) == []


def test_merge_documents_dedupes_and_accumulates_scope_keys():
    from agentic import staging
    l1 = {"scope_key": "k1", "documents": [{"id": "A", "name": "Alpha"}, {"id": "B", "name": "Beta"}]}
    l2 = {"scope_key": "k2", "documents": [{"id": "B", "name": "Beta (again)"}, {"id": "C", "name": "Gamma"}]}
    merged = {d["id"]: d for d in staging.merge_documents([l1, l2])}
    assert set(merged) == {"A", "B", "C"}
    assert merged["A"]["scope_keys"] == ["k1"]
    assert merged["B"]["scope_keys"] == ["k1", "k2"]        # present in both, order preserved
    assert merged["C"]["scope_keys"] == ["k2"]
    assert merged["B"]["name"] == "Beta"                    # first-seen fields win, not overwritten


def test_merge_documents_skips_ids_missing_or_blank():
    from agentic import staging
    l1 = {"scope_key": "k1", "documents": [{"id": "", "name": "no id"}, {"name": "missing id"},
                                            {"id": "  ", "name": "blank id"}, {"id": "OK"}]}
    merged = staging.merge_documents([l1])
    assert [d["id"] for d in merged] == ["OK"]


def test_overlapping_listings_reports_shared_ids_excludes_self():
    from agentic import staging
    l1 = {"scope_key": "k1", "scope": {"query": "q1"}, "documents": [{"id": "A"}, {"id": "B"}]}
    l2 = {"scope_key": "k2", "scope": {"query": "q2"}, "documents": [{"id": "B"}, {"id": "C"}]}
    l3 = {"scope_key": "k3", "scope": {"query": "q3"}, "documents": [{"id": "Z"}]}
    ov = staging.overlapping_listings("k1", {"A", "B"}, [l1, l2, l3])
    # `label` is what the operator calls that watch — its name when set, else the derived
    # scope, so an overlap note reads the same way the console's watch row does.
    assert ov == [{"scope_key": "k2", "scope": {"query": "q2"},
                   "label": 'query "q2"', "count": 1}]
    l2["label"] = "Q2 planning"
    assert staging.overlapping_listings("k1", {"A", "B"}, [l1, l2])[0]["label"] == "Q2 planning"
    # no overlap at all → empty list
    assert staging.overlapping_listings("k3", {"Z"}, [l1, l2, l3]) == []


def test_clean_label_trims_collapses_and_caps():
    """An operator-supplied watch name is normalized to one trimmed line within LABEL_MAX;
    anything unstringy or empty means "no label" (the caller falls back to scope_label)."""
    from agentic import staging
    assert staging.clean_label("  Marketing \n  archive ") == "Marketing archive"
    assert staging.clean_label("x" * 200) == "x" * staging.LABEL_MAX
    assert staging.clean_label("   ") == ""
    assert staging.clean_label(None) == ""
    assert staging.clean_label(42) == ""


def test_listing_label_prefers_the_operator_name_over_the_derived_scope():
    from agentic import staging
    scoped = {"scope": {"folder_id": "FA", "recursive": True}}
    assert staging.listing_label(scoped) == "folder FA (recursive)"
    assert staging.listing_label({**scoped, "label": "Q1 plans"}) == "Q1 plans"
    assert staging.listing_label({}) == "unscoped"


def test_normalize_staging_reads_and_cleans_a_label_defaulting_to_empty():
    """A label round-trips through normalize (and is cleaned on the way in); a listing
    written before labels existed — or the legacy single-listing shape — reads as ""."""
    from agentic import staging
    listings = staging.normalize_staging({"slug": "p", "listings": [
        {"scope_key": "k1", "scope": {"query": "q1"}, "label": "  Q1  plans ", "documents": []},
        {"scope_key": "k2", "scope": {"query": "q2"}, "documents": []},
    ]})
    assert [l["label"] for l in listings] == ["Q1 plans", ""]
    legacy = staging.normalize_staging({"slug": "p", "scope": {"query": "q"}, "documents": []})
    assert legacy[0]["label"] == ""
