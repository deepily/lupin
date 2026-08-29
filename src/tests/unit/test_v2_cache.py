#!/usr/bin/env python3
"""
Unit tests for the CJ Flow v2 cache adapter (unit C2) — src/cosa/rest/v2/cache.py.

Hermetic: every collaborator (repositories, embedding provider, normalizers,
db scope) is a fake, so the whole two-tier lookup + tagged write-back is
exercised with NO live Postgres and NO model server. :7999-eligible.

Carries the two behavioural C2 guards, each proven able to fail (the paste-the-red
receipts live in the unit's report):
    - R-C1: the replay signal is a tier-1 EXACT hit, never an ANN float score —
            an ANN candidate at 100.0 must NOT replay.
    - R-D2: write-back REBINDS runtime_stats with { **... }, never mutates the
            shared mutable default in place.
"""

import json
import types

import numpy as np
import pytest

from cosa.rest.v2 import cache as cache_mod
from cosa.rest.v2.cache import V2Cache, CacheLookup


# ────────────────────────────────────────────────────────────── fakes

class _Store:
    """In-memory stand-in for the DB, shared by the fake repositories."""

    def __init__( self ):
        self.rows             = {}   # id_hash -> fake ORM row
        self.syn_verbatim     = {}   # question -> snapshot_id
        self.syn_normalized   = {}   # normalized -> snapshot_id
        self.syn_gist         = {}   # gist -> snapshot_id
        self.embeddings       = {}   # question -> vector
        self.ann_result       = []   # list[ (pct, row) ]
        self.upserts          = []   # list[ (id_hash, fields) ]
        self.added_synonyms   = []   # list[ kwargs ]
        self.added_embeddings = []   # list[ (question, vec) ]
        self.deleted_synonyms = []   # list[ snapshot_id ]


class _FakeSnapshotRepo:
    """Records calls AND persists — the persisted row is what a later lookup reads,
    so a write_back → lookup round trip closes through the SAME in-memory store."""
    def __init__( self, session ):
        self.store = session
    def get_snapshot_by_id( self, id_hash ):
        return self.store.rows.get( id_hash )
    def get_snapshots_by_question( self, embedding, threshold, limit ):
        return self.store.ann_result
    def upsert_snapshot( self, id_hash, **fields ):
        self.store.upserts.append( ( id_hash, fields ) )
        row = types.SimpleNamespace( id_hash=id_hash, **fields )
        self.store.rows[ id_hash ] = row          # persist: a later lookup can find it
        return row


class _FakeSynRepo:
    """Records calls AND persists the verbatim/normalized synonym keys, so a
    write_back registration is visible to a later tier-1 lookup (the round trip)."""
    def __init__( self, session ):
        self.store = session
    def find_exact_verbatim( self, question ):
        return self.store.syn_verbatim.get( question )
    def find_exact_normalized( self, question_normalized ):
        return self.store.syn_normalized.get( question_normalized )
    def find_exact_gist( self, question_gist ):
        # The real CanonicalSynonymRepository has had this since it was written; the
        # fake omitted it because nothing read it yet. A fake that is missing a method
        # the real class has does not fail where the real one would — it fails
        # everywhere, on a path the real one handles fine.
        return self.store.syn_gist.get( question_gist )
    def delete_by_snapshot_id( self, snapshot_id ):
        self.store.deleted_synonyms.append( snapshot_id )
        # idempotent re-registration: drop any prior keys for this snapshot
        self.store.syn_verbatim   = { q: s for q, s in self.store.syn_verbatim.items()   if s != snapshot_id }
        self.store.syn_normalized = { q: s for q, s in self.store.syn_normalized.items() if s != snapshot_id }
        self.store.syn_gist       = { q: s for q, s in self.store.syn_gist.items()       if s != snapshot_id }
        return 0
    def add_synonym( self, **kwargs ):
        self.store.added_synonyms.append( kwargs )
        self.store.syn_verbatim[   kwargs[ "question_verbatim" ] ]   = kwargs[ "snapshot_id" ]
        self.store.syn_normalized[ kwargs[ "question_normalized" ] ] = kwargs[ "snapshot_id" ]
        if kwargs.get( "question_gist" ):
            self.store.syn_gist[ kwargs[ "question_gist" ] ] = kwargs[ "snapshot_id" ]
        return kwargs


class _FakeQEmbRepo:
    def __init__( self, session ):
        self.store = session
    def get_embedding( self, question ):
        return self.store.embeddings.get( question )
    def add_embedding( self, question, embedding ):
        self.store.added_embeddings.append( ( question, embedding ) )
        self.store.embeddings[ question ] = embedding   # persist: a later probe is free
        return ( question, embedding )


class _RecordingFactory:
    """Stands in for SolutionSnapshot — records constructor kwargs."""
    def __init__( self ):
        self.calls = []
    def __call__( self, **kwargs ):
        self.calls.append( kwargs )
        return types.SimpleNamespace( marshalled=True, **kwargs )


class _FakeProvider:
    def __init__( self, vector ):
        self.vector = vector
        self.calls  = []
    def generate_embedding( self, text, content_type="prose" ):
        self.calls.append( ( text, content_type ) )
        return self.vector


class _FakeNormalizer:
    def normalize( self, question ):
        return question.strip().lower()


class _FakeGist:
    def __init__( self ):
        self.calls = []
    def get_normalized_gist( self, text ):
        self.calls.append( text )
        return "gist::" + text


def _db_scope_for( store ):
    class _CM:
        def __enter__( self_ ):
            return store
        def __exit__( self_, *a ):
            return False
    def _scope():
        return _CM()
    return _scope


def _make_orm_row( **over ):
    """A fake solution_snapshots ORM row with all columns defaulted."""
    row = types.SimpleNamespace(
        id_hash="id-1", user_id="u1",
        question="What time is it?", question_normalized="what time is it?",
        question_gist="", answer="10:00", answer_conversational="It is ten.",
        solution_summary="", thoughts="", error="", routing_command="agent router go to time",
        agent_class_name="DateAndTimeAgent", code=[], solution_summary_gist="",
        code_returns="", code_example="", code_type="", programming_language="python",
        language_version="3.10", non_synonymous_questions=[], last_question_asked="",
        created_date="", updated_date="", run_date="",
        synonymous_questions="{}", synonymous_question_gists="{}",
        runtime_stats='{"flow_version": "v1"}', replay_history="[]", replay_stats="{}",
        answer_is_correct="null", is_cache_hit=False,
        question_embedding=[], question_normalized_embedding=[], question_gist_embedding=[],
        solution_embedding=[], code_embedding=[], thoughts_embedding=[], solution_gist_embedding=[],
    )
    for key, value in over.items():
        setattr( row, key, value )
    return row


def _make_snapshot( **over ):
    """A fake memory SolutionSnapshot with every attribute write_back reads."""
    snap = types.SimpleNamespace(
        id_hash="wb-1", user_id="u1",
        question="what's the weather in Tokyo", question_normalized="whats the weather in tokyo",
        question_gist="gist::weather", answer="Sunny", answer_conversational="It's sunny in Tokyo.",
        solution_summary="", thoughts="", error="", routing_command="agent router go to weather",
        agent_class_name="WeatherAgent", code=[], solution_summary_gist="",
        code_returns="", code_example="", code_type="", programming_language="python",
        language_version="3.10", synonymous_questions={}, synonymous_question_gists={},
        non_synonymous_questions=[], last_question_asked="", created_date="d", updated_date="d",
        run_date="", runtime_stats={}, replay_history=[], replay_stats={}, is_cache_hit=False,
        answer_is_correct=None,
        question_embedding=[ 0.1 ] * 4, question_normalized_embedding=[], question_gist_embedding=[],
        solution_embedding=[], code_embedding=[], thoughts_embedding=[], solution_gist_embedding=[],
    )
    for key, value in over.items():
        setattr( snap, key, value )
    return snap


@pytest.fixture
def wired( monkeypatch ):
    """Monkeypatch the three repositories to fakes; return a builder + store."""
    store = _Store()
    monkeypatch.setattr( cache_mod, "SolutionSnapshotRepository", _FakeSnapshotRepo )
    monkeypatch.setattr( cache_mod, "CanonicalSynonymRepository", _FakeSynRepo )
    monkeypatch.setattr( cache_mod, "QuestionEmbeddingRepository", _FakeQEmbRepo )

    def _build( *, provider_vec=None, factory=None, debug=False ):
        provider = _FakeProvider( provider_vec if provider_vec is not None else [ 0.2 ] * 4 )
        factory  = factory if factory is not None else _RecordingFactory()
        cache = V2Cache(
            embedding_provider=provider, snapshot_factory=factory,
            normalizer=_FakeNormalizer(), gist_normalizer=_FakeGist(),
            db_scope=_db_scope_for( store ), query_floor=70.0, ann_limit=7,
            embedding_dim=4, debug=debug, verbose=debug,
        )
        return cache, provider, factory

    return _build, store


# ────────────────────────────────────────────────────────────── lookup

def test_lookup_empty_question_raises( wired ):
    build, _store = wired
    cache, _p, _f = build()
    with pytest.raises( ValueError ):
        cache.lookup( "" )


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_exact_verbatim_hit( wired, debug ):
    build, store = wired
    cache, provider, factory = build( debug=debug )
    store.syn_verbatim[ "What time is it?" ] = "id-1"
    store.rows[ "id-1" ] = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "What time is it?" )

    assert isinstance( result, CacheLookup )
    assert result.is_replay_hit is True
    assert result.tier == "exact_verbatim"
    assert result.similarity == 100.0
    assert result.best_score == 100.0
    assert result.snapshot is not None
    assert result.t_embed_ms is None       # tier 1 computes NO embedding
    assert result.embed_cached is None
    assert provider.calls == []            # no model call on an exact hit


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_verbatim_ghost_falls_through_to_normalized( wired, debug ):
    build, store = wired
    cache, _p, _f = build( debug=debug )
    # verbatim synonym exists but points at a MISSING row (a ghost)
    store.syn_verbatim[ "What time is it?" ]     = "ghost-id"
    store.syn_normalized[ "what time is it?" ]   = "id-1"
    store.rows[ "id-1" ]                         = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "What time is it?" )

    assert result.is_replay_hit is True
    assert result.tier == "exact_normalized"


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_normalized_ghost_falls_through_to_tier2( wired, debug ):
    build, store = wired
    cache, provider, _f = build( provider_vec=[ 0.3 ] * 4, debug=debug )
    store.syn_normalized[ "what time is it?" ] = "ghost-id"   # ghost → tier 2
    store.ann_result = [ ( 88.0, _make_orm_row( id_hash="ann-1" ) ) ]

    result = cache.lookup( "What time is it?" )

    assert result.is_replay_hit is False
    assert result.tier == "ann"
    assert result.best_score == 88.0


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_tier2_embedding_cache_hit( wired, debug ):
    build, store = wired
    cache, provider, _f = build( debug=debug )
    store.embeddings[ "some new q" ] = [ 0.9 ] * 4          # cache hit → free
    store.ann_result = [ ( 91.5, _make_orm_row( id_hash="ann-1" ) ) ]

    result = cache.lookup( "some new q" )

    assert result.tier == "ann"
    assert result.embed_cached is True
    assert result.t_embed_ms is not None
    assert result.t_ann_ms is not None
    assert result.best_candidate is not None
    assert provider.calls == []                            # served from cache


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_tier2_embedding_generated( wired, debug ):
    build, store = wired
    cache, provider, _f = build( provider_vec=[ 0.4 ] * 4, debug=debug )
    store.ann_result = [ ( 90.0, _make_orm_row( id_hash="ann-1" ) ) ]

    result = cache.lookup( "brand new question" )

    assert result.embed_cached is False
    assert provider.calls == [ ( "brand new question", "prose" ) ]   # verbatim, prose


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_tier2_empty_embedding_is_miss( wired, debug ):
    build, store = wired
    cache, _p, _f = build( provider_vec=[], debug=debug )      # generate returns []
    result = cache.lookup( "unembeddable" )

    assert result.tier == "miss"
    assert result.is_replay_hit is False
    assert result.best_score is None
    assert result.t_ann_ms is None
    assert result.embed_cached is False


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_lookup_tier2_no_candidate_is_miss( wired, debug ):
    build, store = wired
    cache, _p, _f = build( provider_vec=[ 0.5 ] * 4, debug=debug )
    store.ann_result = []                                      # nothing above floor

    result = cache.lookup( "lonely question" )

    assert result.tier == "miss"
    assert result.best_score is None
    assert result.t_ann_ms is not None                        # the probe DID run


def test_lookup_ann_candidate_marshalled_fields( wired ):
    build, store = wired
    factory = _RecordingFactory()
    cache, _p, _f = build( provider_vec=[ 0.6 ] * 4, factory=factory )
    store.ann_result = [ ( 84.0, _make_orm_row( id_hash="ann-9", runtime_stats='{"flow_version": "v1"}' ) ) ]

    cache.lookup( "marshal me" )

    assert factory.calls[ -1 ][ "id_hash" ] == "ann-9"
    assert factory.calls[ -1 ][ "runtime_stats" ] == { "flow_version": "v1" }   # JSON decoded
    assert len( factory.calls[ -1 ][ "question_embedding" ] ) == 4              # fitted to dim


# ────────────────────────────────────────── R-C1 guard (replay signal)

def test_r_c1_ann_at_100_does_not_replay( wired ):
    """
    R-C1: replay fires on a tier-1 EXACT hit, never on an ANN float score — even
    an ANN candidate at a perfect 100.0 must route, not replay.
    """
    build, store = wired
    cache, _p, _f = build( provider_vec=[ 0.7 ] * 4 )
    store.ann_result = [ ( 100.0, _make_orm_row( id_hash="ann-100" ) ) ]

    result = cache.lookup( "self match at one hundred" )

    assert result.tier == "ann"
    assert result.is_replay_hit is False        # the whole point of R-C1
    assert result.best_score == 100.0


def test_r_c1_exact_normalized_is_the_replay_signal( wired ):
    """R-C1: the deterministic exact-normalized match IS the replay signal."""
    build, store = wired
    cache, _p, _f = build()
    store.syn_normalized[ "what time is it?" ] = "id-1"
    store.rows[ "id-1" ] = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "  What Time Is It?  " )   # normalizes to the key

    assert result.is_replay_hit is True
    assert result.tier == "exact_normalized"


# ──────────────────────────────────────── R-C3 guard (verbatim embedding key)

def test_r_c3_embedding_cache_is_keyed_by_verbatim_question( wired ):
    """
    R-C3: the ANN vectors are the snapshot's `question_embedding`, generated from
    its RAW question — so the embedding cache MUST be probed by the verbatim
    string, not the normalized one. Seed the cache at a verbatim key whose
    normalized form DIFFERS, and the tier-2 probe must hit it for free. A
    regression to a normalized-keyed lookup would query "what time is it", miss,
    and this goes red — the silent-miss Cheech flagged, made loud.
    """
    build, store = wired
    cache, provider, _f = build()
    verbatim = "What TIME Is It"                    # normalizes to "what time is it" — DIFFERS
    store.embeddings[ verbatim ] = [ 0.9 ] * 4      # cached ONLY at the verbatim key
    store.ann_result = [ ( 88.0, _make_orm_row( id_hash="ann-1" ) ) ]

    result = cache.lookup( verbatim )

    assert result.embed_cached is True              # verbatim probe hit → free
    assert provider.calls == []                     # no model call


def test_r_c3_normalized_key_alone_does_not_serve_the_verbatim_probe( wired ):
    """
    R-C3 (symmetric): a cache holding ONLY the normalized key must NOT satisfy the
    verbatim probe — the wrong (normalized-keyed) cache would silently hit here.
    Under the correct code the verbatim probe misses and generates; a normalized-
    keyed regression would wrongly report embed_cached=True, so this goes red.
    """
    build, store = wired
    cache, provider, _f = build( provider_vec=[ 0.3 ] * 4 )
    verbatim = "What TIME Is It"
    store.embeddings[ "what time is it" ] = [ 0.9 ] * 4   # ONLY the normalized key present
    store.ann_result = [ ( 88.0, _make_orm_row( id_hash="ann-1" ) ) ]

    result = cache.lookup( verbatim )

    assert result.embed_cached is False                  # verbatim probe missed → generated
    assert provider.calls == [ ( verbatim, "prose" ) ]   # generated from the VERBATIM question


# ────────────────────────────────────────────────────────────── write-back

def test_write_back_empty_question_raises( wired ):
    build, _store = wired
    cache, _p, _f = build()
    with pytest.raises( ValueError ):
        cache.write_back( _make_snapshot( question="" ) )


def test_write_back_empty_id_hash_raises( wired ):
    build, _store = wired
    cache, _p, _f = build()
    with pytest.raises( ValueError ):
        cache.write_back( _make_snapshot( id_hash="" ) )


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_write_back_happy_path_persists_and_tags( wired, debug ):
    build, store = wired
    cache, provider, _f = build( debug=debug )
    snap = _make_snapshot( runtime_stats={ "prior": 1 } )

    id_hash = cache.write_back( snap, created_at_iso="2026-08-14T02:30:00-04:00" )

    assert id_hash == "wb-1"
    # snapshot row upserted with the v2 tag in serialized runtime_stats
    assert len( store.upserts ) == 1
    up_id, fields = store.upserts[ 0 ]
    assert up_id == "wb-1"
    stats = json.loads( fields[ "runtime_stats" ] )
    assert stats[ "flow_version" ] == "v2"
    assert stats[ "created_by" ] == "v2.ask"
    assert stats[ "created_at" ] == "2026-08-14T02:30:00-04:00"
    assert stats[ "prior" ] == 1                              # prior keys preserved
    # canonical synonym re-registered (idempotent reset then add)
    assert store.deleted_synonyms == [ "wb-1" ]
    syn = store.added_synonyms[ 0 ]
    assert syn[ "question_verbatim" ]   == "what's the weather in Tokyo"
    assert syn[ "question_normalized" ] == "whats the weather in tokyo"
    assert syn[ "question_gist" ]       == "gist::weather"
    # verbatim embedding cache populated
    assert store.added_embeddings == [ ( "what's the weather in Tokyo", [ 0.1 ] * 4 ) ]


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_round_trip_write_back_then_identical_lookup_is_tier1_replay( wired, debug ):
    """
    THE CONTROL (row 41333974): a second identical request must hit the cache.

    Every other test drives write_back OR lookup against a fresh store and proves
    half the contract; none composes them. This writes a snapshot back, then looks
    up the SAME verbatim question through the SAME store, and asserts the write
    path made it a tier-1 exact replay — the composition 100% line/branch coverage
    can't see, because every line already runs; what never ran is the round trip.

    The flag being ON in a config file is a setting; THIS is the evidence the
    write path actually populates what the read path reads.
    """
    build, store = wired
    cache, provider, _f = build( debug=debug )
    snap = _make_snapshot()                       # carries a question_embedding → no generation

    written_id = cache.write_back( snap, created_at_iso="2026-08-14T02:30:00-04:00" )
    assert written_id == "wb-1"

    # Second identical request — must come back a deterministic tier-1 exact hit.
    result = cache.lookup( snap.question )

    assert result.is_replay_hit is True
    assert result.tier         == "exact_verbatim"
    assert result.similarity   == 100.0
    assert result.snapshot is not None
    # It is the row we wrote: the v2 tag survived the marshal round trip.
    assert result.snapshot.runtime_stats[ "flow_version" ] == "v2"
    assert result.snapshot.runtime_stats[ "created_by" ]   == "v2.ask"
    # A tier-1 replay computes NO embedding on either leg — zero model calls end to end.
    assert result.t_embed_ms is None
    assert provider.calls == []


def test_round_trip_normalized_variant_also_replays( wired ):
    """
    The round trip closes on tier-1b too: a casing/whitespace variant of the
    written question normalizes to the same key and replays via exact_normalized.
    """
    build, store = wired
    cache, provider, _f = build()
    # question_normalized set to what _FakeNormalizer yields for the question, so the
    # written key and the freshly-normalized lookup key agree (as they do in production,
    # where one Normalizer produces both).
    cache.write_back( _make_snapshot( question_normalized="what's the weather in tokyo" ) )

    # A different surface form of the same question — verbatim misses, normalized hits.
    result = cache.lookup( "  WHAT'S THE WEATHER IN TOKYO  " )

    assert result.is_replay_hit is True
    assert result.tier == "exact_normalized"
    assert result.snapshot is not None
    assert provider.calls == []


def test_write_back_computes_gist_and_embedding_when_absent( wired ):
    build, store = wired
    cache, provider, _f = build( provider_vec=[ 0.8 ] * 4 )
    snap = _make_snapshot( question_gist="", question_embedding=[] )

    cache.write_back( snap )                                  # created_at_iso=None branch

    assert snap.question_gist == "gist::what's the weather in Tokyo"   # gist computed
    assert provider.calls == [ ( "what's the weather in Tokyo", "prose" ) ]
    assert snap.question_embedding == [ 0.8 ] * 4


# ─────────────────────────────────────── snapshot_from_result (construction)

def test_snapshot_from_result_builds_with_normalized_question( wired ):
    build, _store = wired
    cache, _p, factory = build()

    cache.snapshot_from_result(
        question="What TIME is it?", answer="ten", answer_conversational="It is ten.",
        routing_command="agent router go to time", agent_class_name="DateAndTimeAgent",
        user_id="u1", session_id="s1",
    )

    call = factory.calls[ -1 ]
    assert call[ "question" ]              == "What TIME is it?"
    assert call[ "question_normalized" ]   == "what time is it?"      # via the normalizer
    assert call[ "answer" ]                == "ten"
    assert call[ "answer_conversational" ] == "It is ten."
    assert call[ "routing_command" ]       == "agent router go to time"
    assert call[ "agent_class_name" ]      == "DateAndTimeAgent"
    assert call[ "last_question_asked" ]   == "What TIME is it?"
    assert call[ "user_id" ]               == "u1"
    assert call[ "session_id" ]            == "s1"


def test_snapshot_from_result_empty_question_raises( wired ):
    build, _store = wired
    cache, _p, _f = build()
    with pytest.raises( ValueError, match="non-empty question" ):
        cache.snapshot_from_result( question="", answer="a", answer_conversational="c",
                                    routing_command="cmd", agent_class_name="Cls", user_id="u1" )


# ───────────────────────────────────────────── write-back kill-switch

@pytest.mark.parametrize( "debug", [ False, True ] )
def test_write_back_disabled_records_nothing( wired, debug ):
    build, store = wired
    cache, _p, _f = build( debug=debug )

    result = cache.write_back( _make_snapshot(), writeback_enabled=False )

    assert result is None
    assert store.upserts          == []
    assert store.added_synonyms   == []
    assert store.added_embeddings == []
    assert store.deleted_synonyms == []


def test_write_back_enabled_missing_db_scope_raises( monkeypatch ):
    # A missing persist dependency with the flag ON must fail loud, never no-op.
    monkeypatch.setattr( cache_mod, "SolutionSnapshotRepository", _FakeSnapshotRepo )
    cache = V2Cache(
        embedding_provider=_FakeProvider( [ 0.1 ] * 4 ), normalizer=_FakeNormalizer(),
        gist_normalizer=_FakeGist(), snapshot_factory=_RecordingFactory(),
        db_scope=None, embedding_dim=4,
    )
    with pytest.raises( RuntimeError ):
        cache.write_back( _make_snapshot(), writeback_enabled=True )


# ────────────────────────────────────────── R-D2 guard (rebind, no mutate)

def test_r_d2_write_back_rebinds_runtime_stats_never_mutates( wired ):
    """
    R-D2: write-back must REBIND runtime_stats with { **old, **tag }. Mutating in
    place would tag the shared mutable default for every default-constructed
    snapshot in the process.
    """
    build, store = wired
    cache, _p, _f = build()
    original = { "prior": 1 }
    snap = _make_snapshot( runtime_stats=original )

    cache.write_back( snap, created_at_iso="2026-08-14T02:30:00-04:00" )

    assert snap.runtime_stats is not original          # rebound to a NEW dict
    assert "flow_version" not in original              # the shared default is untouched
    assert original == { "prior": 1 }


# ────────────────────────────────────────────────────────────── helpers

def _bare_cache():
    return V2Cache(
        embedding_provider=_FakeProvider( [] ), normalizer=_FakeNormalizer(),
        gist_normalizer=_FakeGist(), snapshot_factory=_RecordingFactory(),
        db_scope=_db_scope_for( _Store() ), embedding_dim=4,
    )


def test_fit_embedding_variants():
    cache = _bare_cache()
    assert cache._fit_embedding( [] )             == [ 0.0, 0.0, 0.0, 0.0 ]   # empty → zeros
    assert cache._fit_embedding( None )           == [ 0.0, 0.0, 0.0, 0.0 ]
    assert cache._fit_embedding( [ 1, 2, 3, 4 ] ) == [ 1.0, 2.0, 3.0, 4.0 ]   # exact dim
    assert cache._fit_embedding( [ 1, 2 ] )       == [ 1.0, 2.0, 0.0, 0.0 ]   # pad
    assert cache._fit_embedding( [ 1, 2, 3, 4, 5 ] ) == [ 1.0, 2.0, 3.0, 4.0 ]  # truncate


def test_fit_embedding_numpy_array_readback():
    # Bug 60b5221e: the write-back read path hands _fit_embedding a real numpy
    # ndarray, not a list. The old `if not embedding:` guard raised
    # "truth value of an array with more than one element is ambiguous" on any
    # multi-element vector. Guard on length instead so ndarrays fit like lists.
    cache = _bare_cache()
    assert cache._fit_embedding( np.array( [ 1, 2, 3, 4 ] ) )    == [ 1.0, 2.0, 3.0, 4.0 ]   # exact dim
    assert cache._fit_embedding( np.array( [ 1, 2 ] ) )          == [ 1.0, 2.0, 0.0, 0.0 ]   # pad
    assert cache._fit_embedding( np.array( [ 1, 2, 3, 4, 5 ] ) ) == [ 1.0, 2.0, 3.0, 4.0 ]   # truncate
    assert cache._fit_embedding( np.array( [] ) )                == [ 0.0, 0.0, 0.0, 0.0 ]   # empty → zeros


def test_ensure_list_variants():
    cache = _bare_cache()
    assert cache._ensure_list( None )     == []
    assert cache._ensure_list( [ 1, 2 ] ) == [ 1, 2 ]
    assert cache._ensure_list( ( 1, 2 ) ) == [ 1, 2 ]


def test_loads_or_variants():
    cache = _bare_cache()
    assert cache._loads_or( None, {} )       == {}
    assert cache._loads_or( "", [] )         == []
    assert cache._loads_or( '{"a": 1}', {} ) == { "a": 1 }


def test_synonym_id_is_deterministic():
    cache = _bare_cache()
    a = cache._synonym_id( "id-1", "hello" )
    b = cache._synonym_id( "id-1", "hello" )
    c = cache._synonym_id( "id-2", "hello" )
    assert a == b
    assert a != c
    assert len( a ) == 64        # sha256 hexdigest


def test_ms_since_is_nonnegative():
    import time
    cache = _bare_cache()
    assert cache._ms_since( time.perf_counter_ns() ) >= 0.0


# ─────────────────────────── step 2c — a snapshot nobody owns is not writable

def test_snapshot_from_result_blank_user_id_raises( wired ):
    """
    Rick, 2026-08-20: a caller "cannot file without providing a valid user ID."

    ⚠️ THE TEST HAS TO BE THIS ONE. A test asserting that a POPULATED write works
    would have passed before the change too — user_id defaulted to "" and was
    simply written through. The only assertion that can tell the two versions
    apart is that a BLANK owner is refused.

    RED ON REVERT: delete the user_id raise in snapshot_from_result and a
    blank-user write succeeds.
    """
    build, _store = wired
    cache, _p, _f = build()
    with pytest.raises( ValueError, match="non-empty user_id" ):
        cache.snapshot_from_result( question="q", answer="a", answer_conversational="c",
                                    routing_command="agent router go to math", user_id="" )


def test_snapshot_from_result_will_not_default_the_owner( wired ):
    """
    The parameter has no default either, so a caller cannot omit it and get an
    ownerless row by silence — which is exactly how the flow was producing them.

    RED ON REVERT: give user_id a default and this stops raising.
    """
    build, _store = wired
    cache, _p, _f = build()
    with pytest.raises( TypeError, match="user_id" ):
        cache.snapshot_from_result( question="q", answer="a", answer_conversational="c",
                                    routing_command="agent router go to math" )


# ────────────────────────────────── 6a — tier 1c, the gist probe

class _WordingGist:
    """A gist normalizer that actually collapses WORDING, which is the point.

    `_FakeGist` above prefixes the text and so answers differently for every
    phrasing — fine for the field it was written for, useless for a tier that only
    exists because two wordings should meet. This one lowercases, drops punctuation
    and a small stopword list, and keeps the content words, so "What's on my todo
    list?" and "what is on my todo list" both reduce to "todo list" — and a question
    made only of stopwords reduces to "", which is the case tier 1c must refuse.
    """

    _STOPWORDS = { "what", "whats", "is", "on", "my", "the", "a", "it", "s" }

    def __init__( self ):
        self.calls = []

    def get_normalized_gist( self, text ):
        self.calls.append( text )
        cleaned = "".join( c if c.isalnum() or c.isspace() else " " for c in text.lower() )
        return " ".join( w for w in cleaned.split() if w not in self._STOPWORDS )


@pytest.fixture
def wired_wording_gist( monkeypatch ):
    """The `wired` rig with a gist normalizer that collapses wording."""
    store = _Store()
    monkeypatch.setattr( cache_mod, "SolutionSnapshotRepository", _FakeSnapshotRepo )
    monkeypatch.setattr( cache_mod, "CanonicalSynonymRepository", _FakeSynRepo )
    monkeypatch.setattr( cache_mod, "QuestionEmbeddingRepository", _FakeQEmbRepo )

    def _build( *, debug=False ):
        return V2Cache(
            embedding_provider=_FakeProvider( [ 0.2 ] * 4 ), snapshot_factory=_RecordingFactory(),
            normalizer=_FakeNormalizer(), gist_normalizer=_WordingGist(),
            db_scope=_db_scope_for( store ), query_floor=70.0, ann_limit=7,
            embedding_dim=4, debug=debug, verbose=debug,
        )

    return _build, store


def test_a_reworded_question_replays_on_its_gist( wired_wording_gist ):
    """
    THE POINT OF 6a. One row was written for "what is on my todo list"; the user
    now says "What's on my todo list?". Verbatim differs, normalized differs (the
    apostrophe and the question mark survive normalization), gist is the same.

    RED ON REVERT: drop the gist probe from _exact_probes and this falls through to
    tier 2, where there is no ANN result — a miss, and the agent re-runs a question
    already answered.
    """
    build, store = wired_wording_gist
    cache = build()
    store.syn_gist[ "todo list" ] = "id-1"
    store.rows[ "id-1" ]          = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "What's on my todo list?" )

    assert result.is_replay_hit is True, "a reworded repeat did not replay"
    assert result.tier         == "exact_gist"
    assert result.similarity   == 100.0


def test_the_gist_probe_costs_no_embedding( wired_wording_gist ):
    """
    Tier 1c is a tier-1 probe, not a cheap second ANN pass: one indexed equality
    lookup, no vector. That is what keeps `is_replay_hit` deterministic under R-C1
    and what makes the tier worth having at all.

    RED ON REVERT: implement the gist match by embedding the gist and probing ANN —
    the timings below stop being None and the tier reports a float score.
    """
    build, store = wired_wording_gist
    cache = build()
    store.syn_gist[ "todo list" ] = "id-1"
    store.rows[ "id-1" ]          = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "What's on my todo list?" )

    assert result.is_replay_hit is True
    assert result.t_embed_ms is None, "the gist tier embedded the question"
    assert result.t_ann_ms   is None, "the gist tier ran an ANN probe"


def test_a_stricter_probe_wins_over_the_gist( wired_wording_gist ):
    """
    ORDER. Verbatim and normalized are stricter, so a question that matches either
    gets ITS OWN row — never a same-gist neighbour's. Both rows below share the gist
    "todo list"; the verbatim probe must decide.

    RED ON REVERT: put the gist probe first in _exact_probes and the verbatim
    question replays id-2, the neighbour.
    """
    build, store = wired_wording_gist
    cache = build()
    store.syn_verbatim[ "What's on my todo list?" ] = "id-1"
    store.syn_gist[ "todo list" ]                   = "id-2"
    store.rows[ "id-1" ] = _make_orm_row( id_hash="id-1" )
    store.rows[ "id-2" ] = _make_orm_row( id_hash="id-2" )

    result = cache.lookup( "What's on my todo list?" )

    assert result.tier == "exact_verbatim"
    assert result.snapshot.id_hash == "id-1"


@pytest.mark.parametrize( "debug", [ False, True ] )
def test_a_question_with_no_gist_never_probes_the_gist_tier( wired_wording_gist, debug ):
    """
    A question made entirely of stopwords reduces to "". Equality on "" would match
    every row whose gist column is also blank — and replay a stranger's answer to a
    question that has nothing in common with this one. An empty gist is not a key.

    RED ON REVERT: drop the blank-gist guard and this replays id-blank.
    """
    build, store = wired_wording_gist
    cache = build( debug=debug )
    store.syn_gist[ "" ]     = "id-blank"
    store.rows[ "id-blank" ] = _make_orm_row( id_hash="id-blank" )

    result = cache.lookup( "what is it?" )

    assert result.is_replay_hit is False, "a question with no gist replayed a blank-gist row"
    assert result.tier == "miss"


def test_a_ghost_gist_synonym_falls_through_rather_than_replaying( wired_wording_gist ):
    """
    The same ghost rule the other two exact probes already obey: a synonym row
    pointing at a snapshot that is gone is a MISS for that tier, not a crash and not
    a replay of nothing. Tier 1c inherits it by going through _resolve_exact — this
    is the test that says so rather than assuming it.
    """
    build, store = wired_wording_gist
    cache = build()
    store.syn_gist[ "todo list" ] = "ghost-id"      # no matching row in store.rows

    result = cache.lookup( "What's on my todo list?" )

    assert result.is_replay_hit is False
    assert result.tier == "miss"


def test_the_shared_base_search_did_not_gain_the_tier():
    """
    BLAST RADIUS. TwoTierQuestionSearch is shared with the snapshot manager's own
    shim, so the gist tier had to land in V2Cache and nowhere else. The seam in the
    base is a hook with no behaviour of its own.

    RED ON REVERT: move the gist probe up into the base and the shared search starts
    replaying on gist for every caller, silently.
    """
    from cosa.memory.two_tier_question_search import TwoTierQuestionSearch

    base_probes = TwoTierQuestionSearch._exact_probes(
        types.SimpleNamespace(), types.SimpleNamespace(), "q", "q"
    )

    assert [ name for name, _probe in base_probes ] == [ "exact_verbatim", "exact_normalized" ]


def test_a_written_back_row_is_findable_by_a_reworded_question( wired_wording_gist ):
    """
    THE ROUND TRIP, which is the only version of this that proves the tier is
    reachable in production: write_back registers the synonym row (gist column
    included, and it always did), and a differently-worded question finds it.

    A test that planted `store.syn_gist` by hand — as the ones above do — proves the
    READ half only. If the write ever stopped filling question_gist, every test but
    this one would stay green.
    """
    build, store = wired_wording_gist
    cache = build()
    # question_gist left EMPTY on purpose: write_back computes it from the same gist
    # normalizer the lookup uses, which is the half this test is here to close.
    cache.write_back( _make_snapshot( question="what is on my todo list",
                                      question_normalized="what is on my todo list",
                                      question_gist="" ), writeback_enabled=True )

    result = cache.lookup( "What's on my todo list?" )

    assert result.is_replay_hit is True, "a written-back row was unreachable by a reworded question"
    assert result.tier == "exact_gist"


def test_an_earlier_hit_never_pays_for_the_gist( wired_wording_gist ):
    """
    The exact path exists to be the cheap one, and building the probe list eagerly made
    every verbatim and normalized hit normalize a question it never looked up
    (Pocholo). Handing back callables only helps if their KEYS are computed inside them
    too.

    RED ON REVERT: compute the gist before returning the list and this records a call
    on a lookup that never reached tier 1c.
    """
    build, store = wired_wording_gist
    cache = build()
    store.syn_verbatim[ "What's on my todo list?" ] = "id-1"
    store.rows[ "id-1" ] = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "What's on my todo list?" )

    assert result.tier == "exact_verbatim"
    assert cache._gist_normalizer.calls == [], (
        f"a verbatim hit computed the gist anyway: {cache._gist_normalizer.calls}"
    )


def test_the_gist_is_computed_when_the_probe_is_actually_reached( wired_wording_gist ):
    """
    The other half, so the test above cannot be satisfied by never computing it at all:
    a lookup that falls through to tier 1c does normalize, exactly once.
    """
    build, store = wired_wording_gist
    cache = build()
    store.syn_gist[ "todo list" ] = "id-1"
    store.rows[ "id-1" ] = _make_orm_row( id_hash="id-1" )

    result = cache.lookup( "What's on my todo list?" )

    assert result.tier == "exact_gist"
    assert cache._gist_normalizer.calls == [ "What's on my todo list?" ]
