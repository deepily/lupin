#!/usr/bin/env python3
"""
Own-gate tests for cosa.memory.two_tier_question_search (row 29e98243).

The module's two entry points are already exercised 100% line+branch by their
consumers (TwoTierQuestionSearch via test_v2_cache; pg_hierarchical_search via
test_lancedb_solution_manager's TestPg*). This file gives the module its OWN
committed gates so that coverage does not depend on a consumer's suite, and
carries the TRACE-NULL guard Cheech required for the reuse swap:

    A read path that silently drops one of the fields flow._record_lookup stamps
    (tier, similarity, best_score, embed_cached, t_exact_ms, t_embed_ms, t_ann_ms)
    would leave the v2 eval reading nulls it cannot distinguish from "not measured".
    This asserts every one of those seven is populated on a full ANN-tier lookup.

Hermetic — every collaborator is a fake, so :7999-eligible.
"""

import types

import pytest

from cosa.memory.two_tier_question_search import (
    CacheLookup,
    TwoTierQuestionSearch,
    pg_hierarchical_search,
)


# ────────────────────────────────────────────────────────────── fakes

class _Store:
    def __init__( self ):
        self.rows           = {}
        self.syn_verbatim   = {}
        self.syn_normalized = {}
        self.embeddings     = {}
        self.ann_result     = []


class _FakeSnapshotRepo:
    def __init__( self, session ): self.store = session
    def get_snapshot_by_id( self, id_hash ): return self.store.rows.get( id_hash )
    def get_snapshots_by_question( self, embedding, threshold, limit ): return self.store.ann_result


class _FakeSynRepo:
    def __init__( self, session ): self.store = session
    def find_exact_verbatim( self, q ): return self.store.syn_verbatim.get( q )
    def find_exact_normalized( self, nq ): return self.store.syn_normalized.get( nq )


class _FakeQEmbRepo:
    def __init__( self, session ): self.store = session
    def get_embedding( self, q ): return self.store.embeddings.get( q )


class _FakeProvider:
    def __init__( self, vec ): self.vector = vec; self.calls = []
    def generate_embedding( self, text, content_type="prose" ):
        self.calls.append( ( text, content_type ) ); return self.vector


class _FakeNormalizer:
    def normalize( self, q ): return q.strip().lower()


def _db_scope_for( store ):
    class _CM:
        def __enter__( self_ ): return store
        def __exit__( self_, *a ): return False
    return lambda: _CM()


def _orm_row( **over ):
    row = types.SimpleNamespace(
        id_hash="ann-1", user_id="u1", question="q", question_normalized="q",
        question_gist="", answer="a", answer_conversational="", solution_summary="",
        thoughts="", error="", routing_command="cmd", agent_class_name="Cls", code=[],
        solution_summary_gist="", code_returns="", code_example="", code_type="",
        programming_language="python", language_version="3.10", non_synonymous_questions=[],
        last_question_asked="", created_date="", updated_date="", run_date="",
        synonymous_questions="{}", synonymous_question_gists="{}", runtime_stats="{}",
        replay_history="[]", replay_stats="{}", answer_is_correct="null", is_cache_hit=False,
        question_embedding=[], question_normalized_embedding=[], question_gist_embedding=[],
        solution_embedding=[], code_embedding=[], thoughts_embedding=[], solution_gist_embedding=[],
    )
    for k, v in over.items(): setattr( row, k, v )
    return row


def _search( store, *, provider_vec=None ):
    return TwoTierQuestionSearch(
        embedding_provider=_FakeProvider( provider_vec if provider_vec is not None else [ 0.2 ] * 4 ),
        snapshot_factory=lambda **kw: types.SimpleNamespace( **kw ),
        normalizer=_FakeNormalizer(), gist_normalizer=object(),
        db_scope=_db_scope_for( store ),
        synonym_repo_cls=_FakeSynRepo, snapshot_repo_cls=_FakeSnapshotRepo,
        embedding_repo_cls=_FakeQEmbRepo, embedding_dim=4,
    )


# ─────────────────────────────────────── TRACE-NULL guard (the reuse swap)

# The exact fields flow._record_lookup stamps onto the StageTrace from a CacheLookup.
_TRACE_FIELDS = ( "tier", "similarity", "best_score", "embed_cached",
                  "t_exact_ms", "t_embed_ms", "t_ann_ms" )


def test_trace_fields_all_populated_on_ann_lookup():
    """
    The reuse swap must not gut the trace: on a full ANN-tier lookup (embedding
    generated, candidate returned), EVERY field the v2 eval reads is non-None.

    Proven able to fail: if the ANN branch stopped stamping any one of these (e.g.
    returned t_ann_ms=None), this reds. Demonstrated by temporarily nulling a field
    during the reuse review (receipt in the unit report).
    """
    store = _Store()
    store.ann_result = [ ( 88.0, _orm_row() ) ]
    result = _search( store, provider_vec=[ 0.3 ] * 4 ).lookup( "brand new question" )

    assert result.tier == "ann"
    for field in _TRACE_FIELDS:
        assert getattr( result, field ) is not None, f"trace field {field} went null after the reuse swap"


# ─────────────────────────────────────── TwoTierQuestionSearch own gates

def test_lookup_empty_question_raises():
    with pytest.raises( ValueError ):
        _search( _Store() ).lookup( "" )


def test_lookup_exact_verbatim_is_replay_hit_no_embedding():
    store = _Store()
    store.syn_verbatim[ "q" ] = "id-1"
    store.rows[ "id-1" ]      = _orm_row( id_hash="id-1" )
    search = _search( store )
    result = search.lookup( "q" )
    assert isinstance( result, CacheLookup )
    assert result.is_replay_hit is True
    assert result.tier == "exact_verbatim"
    assert result.similarity == 100.0
    assert result.t_embed_ms is None          # tier-1 computes NO embedding
    assert search._embedding_provider.calls == []


def test_lookup_miss_when_no_candidate():
    store = _Store()                          # no synonyms, provider returns a vector, ANN empty
    result = _search( store, provider_vec=[ 0.5 ] * 4 ).lookup( "lonely" )
    assert result.tier == "miss"
    assert result.best_score is None
    assert result.t_ann_ms is not None        # the probe DID run


# ─────────────────────────────────────── pg_hierarchical_search own gates

def _fake_manager( **over ):
    mgr = types.SimpleNamespace(
        debug=False, verbose=False, db_path="/db",
        _canonical_synonyms=None, _normalizer=None,
        _question_embeddings_tbl=types.SimpleNamespace( get_embedding=lambda q: None ),
    )
    mgr.is_initialized = lambda: True
    mgr.get_snapshot_by_id = lambda sid: None
    for k, v in over.items(): setattr( mgr, k, v )
    return mgr


def test_pg_search_not_initialized_raises():
    mgr = _fake_manager()
    mgr.is_initialized = lambda: False
    with pytest.raises( RuntimeError ):
        pg_hierarchical_search( mgr, "q" )


def test_pg_search_empty_question_raises():
    with pytest.raises( ValueError ):
        pg_hierarchical_search( _fake_manager(), "" )


def test_pg_search_bad_threshold_raises():
    with pytest.raises( ValueError ):
        pg_hierarchical_search( _fake_manager(), "q", threshold_question=150.0 )


def test_pg_search_level1_verbatim_hit_returns_tuple():
    snap = types.SimpleNamespace( question="q" )
    syn  = types.SimpleNamespace(
        find_exact_verbatim=lambda q: "sid1", find_exact_normalized=lambda nq: None,
        delete_by_snapshot_id=lambda sid: None,
    )
    mgr = _fake_manager( _canonical_synonyms=syn, _normalizer=types.SimpleNamespace( normalize=lambda q: "n" ) )
    mgr.get_snapshot_by_id = lambda sid: snap
    assert pg_hierarchical_search( mgr, "q" ) == [ ( 100.0, snap ) ]
