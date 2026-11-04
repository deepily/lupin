"""
Unit tests for the Postgres record helpers lifted into two_tier_question_search.

Covers snapshot to record, record to snapshot, the synonym indexer and the shared similarity
search. The manager, snapshot class and Postgres session are fakes; no database or model runs.
"""

import json
import numpy as np
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cosa.memory import two_tier_question_search as tt

DIM = 4


def _manager( **extra ):
    """A manager stub with the collaborators the helpers call."""
    base = dict(
        debug=True, verbose=True, _embedding_dim=DIM,
        is_initialized      = lambda: True,
        _ensure_list        = lambda v: list( v ) if v is not None else [],
        _record_to_snapshot = lambda record: ( "snap", record ),
        _pg_record_from_entity = lambda entity: ( "rec", entity.id_hash ),
        _canonical_synonyms = MagicMock(),
    )
    base.update( extra )
    return SimpleNamespace( **base )


# ── snapshot_to_pg_record ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "snapshot", [ None, SimpleNamespace( question="" ) ] )
def test_a_missing_or_questionless_snapshot_is_refused( snapshot ):
    """No snapshot, or an empty question, is a ValueError."""
    with pytest.raises( ValueError, match="question cannot be empty" ):
        tt.snapshot_to_pg_record( _manager(), snapshot )


def _snapshot( **overrides ):
    """The smallest snapshot the converter accepts; every other field takes its default."""
    fields = dict( question="what time", id_hash="h1", answer_is_correct=True )
    fields.update( overrides )
    return SimpleNamespace( **fields )


def test_a_bare_snapshot_gets_documented_defaults():
    """Missing fields take empty strings, python 3.10, JSON containers, zero vectors."""
    rec = tt.snapshot_to_pg_record( _manager(), _snapshot() )
    assert rec[ "id_hash" ] == "h1" and rec[ "user_id" ] == "default_user"
    assert rec[ "question" ] == "what time" and rec[ "answer" ] == ""
    assert ( rec[ "programming_language" ], rec[ "language_version" ] ) == ( "python", "3.10" )
    assert rec[ "synonymous_questions" ] == "{}" and rec[ "replay_history" ] == "[]"
    assert rec[ "answer_is_correct" ] == "true" and rec[ "is_cache_hit" ] is False
    assert rec[ "code" ] == [] and rec[ "non_synonymous_questions" ] == []
    assert rec[ "question_embedding" ] == [ 0.0 ] * DIM


def test_snapshot_fields_are_carried_into_the_record():
    """Set fields reach the record, containers are JSON strings, falsy text becomes empty."""
    rec = tt.snapshot_to_pg_record( _manager(), _snapshot(
        user_id="u9", answer="42", error=None, code=( "a", "b" ), synonymous_questions={ "q": 1 },
        runtime_stats={ "ms": 3 }, replay_history=[ 1 ], replay_stats={ "n": 2 }, is_cache_hit=True,
        answer_is_correct=None ) )
    assert rec[ "user_id" ] == "u9" and rec[ "answer" ] == "42" and rec[ "error" ] == ""
    assert rec[ "code" ] == [ "a", "b" ]
    assert json.loads( rec[ "synonymous_questions" ] ) == { "q": 1 }
    assert json.loads( rec[ "runtime_stats" ] ) == { "ms": 3 }
    assert json.loads( rec[ "replay_stats" ] ) == { "n": 2 } and rec[ "is_cache_hit" ] is True
    assert rec[ "answer_is_correct" ] == "null"


@pytest.mark.parametrize( "embedding,expected", [
    ( None,                       [ 0.0 ] * DIM ),
    ( 7,                          [ 0.0 ] * DIM ),            # no __len__
    ( [],                         [ 0.0 ] * DIM ),
    ( [ 1, 2, 3, 4 ],             [ 1.0, 2.0, 3.0, 4.0 ] ),   # exact fit
    ( [ 1, 2 ],                   [ 1.0, 2.0, 0.0, 0.0 ] ),   # padded
    ( [ 1, 2, 3, 4, 5, 6 ],       [ 1.0, 2.0, 3.0, 4.0 ] ),   # truncated
    ( np.array( [ 9, 8, 7, 6, 5 ] ), [ 9.0, 8.0, 7.0, 6.0 ] ),  # ndarray, no truth-value error
] )
def test_embeddings_are_fitted_to_the_manager_dimension( embedding, expected ):
    """Every embedding column is fitted to the manager's dimension."""
    rec = tt.snapshot_to_pg_record( _manager(), _snapshot( question_embedding=embedding ) )
    assert rec[ "question_embedding" ] == expected
    assert all( len( rec[ k ] ) == DIM for k in rec if k.endswith( "_embedding" ) )


# ── pg_record_to_snapshot ──────────────────────────────────────────────────────────────

@pytest.fixture
def captured( monkeypatch ):
    """Replace SolutionSnapshot with a class that records its constructor keywords."""
    class Capture:
        def __init__( self, **kwargs ): self.kwargs = kwargs
    monkeypatch.setattr( tt, "SolutionSnapshot", Capture )
    return Capture


def test_a_full_record_round_trips_json_fields_into_the_constructor( captured ):
    """JSON strings are decoded and the stored id_hash is preserved."""
    rec = { "question": "q", "id_hash": "keep-me", "synonymous_questions": '{"a": 1}',
            "synonymous_question_gists": '{"g": 2}', "runtime_stats": '{"ms": 5}',
            "replay_history": "[1, 2]", "replay_stats": '{"n": 3}', "is_cache_hit": True,
            "answer_is_correct": "false", "code": ( "x", ), "question_embedding": ( 1, 2 ) }
    kw = tt.pg_record_to_snapshot( _manager(), rec ).kwargs
    assert kw[ "id_hash" ] == "keep-me" and kw[ "question" ] == "q"
    assert kw[ "synonymous_questions" ] == { "a": 1 } and kw[ "synonymous_question_gists" ] == { "g": 2 }
    assert kw[ "runtime_stats" ] == { "ms": 5 } and kw[ "replay_history" ] == [ 1, 2 ]
    assert kw[ "replay_stats" ] == { "n": 3 } and kw[ "is_cache_hit" ] is True
    assert kw[ "answer_is_correct"] is False
    assert kw[ "code" ] == [ "x" ] and kw[ "question_embedding" ] == [ 1, 2 ]


def test_a_sparse_record_takes_the_defaults( captured ):
    """Missing keys: empty containers, no answer verdict, python 3.10, empty embeddings."""
    kw = tt.pg_record_to_snapshot( _manager(), { "question": "q", "id_hash": "h" } ).kwargs
    assert kw[ "synonymous_questions" ] == {} and kw[ "replay_history" ] == [] and kw[ "runtime_stats" ] == {}
    assert kw[ "answer_is_correct" ] is None and kw[ "is_cache_hit" ] is False
    assert ( kw[ "programming_language" ], kw[ "language_version" ] ) == ( "python", "3.10" )
    assert kw[ "agent_class_name" ] is None and kw[ "solution_embedding" ] == []


def test_undecodable_json_fields_fall_back_to_their_empty_values( captured ):
    """Every JSON column holding garbage degrades to its empty default, never raises."""
    bad = "not json"
    rec = { "question": "q", "id_hash": "h", "synonymous_questions": bad, "synonymous_question_gists": bad,
            "runtime_stats": bad, "replay_history": bad, "replay_stats": bad, "answer_is_correct": bad }
    kw = tt.pg_record_to_snapshot( _manager(), rec ).kwargs
    assert ( kw[ "synonymous_questions" ], kw[ "synonymous_question_gists" ], kw[ "runtime_stats" ] ) == ( {}, {}, {} )
    assert kw[ "replay_history" ] == [] and kw[ "replay_stats" ] == {} and kw[ "answer_is_correct" ] is None


# ── update_canonical_synonyms ──────────────────────────────────────────────────────────

@pytest.mark.parametrize( "synonyms", [ None, False ] )
def test_no_synonym_table_is_a_quiet_no_op( synonyms, capsys ):
    """Unavailable table: nothing is added, and a verbose manager says it skipped."""
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=synonyms ), SimpleNamespace( last_question_asked="q" ) )
    assert "not available" in capsys.readouterr().out


def test_no_synonym_table_and_not_verbose_prints_nothing( capsys ):
    """The skip message needs both debug and verbose."""
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=None, verbose=False ), SimpleNamespace() )
    assert capsys.readouterr().out == ""


def test_the_last_question_is_added_at_full_confidence( capsys ):
    """The primary question is indexed with the snapshot id, confidence 100 and source runtime."""
    syn = MagicMock()
    snap = SimpleNamespace( id_hash="h1", last_question_asked="what time is it", synonymous_questions={ "a": 1, "b": 2 } )
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=syn ), snap )
    syn.add_synonym.assert_called_once_with( snapshot_id="h1", question_verbatim="what time is it",
                                             confidence_score=100.0, source="runtime" )
    out = capsys.readouterr().out
    assert "Added primary question" in out and "Skipping 2 synonymous questions" in out


def test_a_snapshot_without_a_last_question_adds_nothing():
    """Empty last_question_asked: no add_synonym call."""
    syn = MagicMock()
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=syn, verbose=False ),
                                  SimpleNamespace( id_hash="h", last_question_asked="" ) )
    syn.add_synonym.assert_not_called()


def test_a_failing_add_is_reported_not_raised( capsys ):
    """add_synonym raising is swallowed with a message."""
    syn = MagicMock()
    syn.add_synonym.side_effect = RuntimeError( "db locked" )
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=syn, verbose=False ),
                                  SimpleNamespace( id_hash="h", last_question_asked="q" ) )
    assert "Failed to add primary question to synonyms: db locked" in capsys.readouterr().out


def test_verbose_without_synonymous_questions_says_nothing_about_skipping( capsys ):
    """A snapshot with no synonymous_questions attribute or an empty one prints no skip line."""
    syn = MagicMock()
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=syn ), SimpleNamespace( id_hash="h", last_question_asked="" ) )
    tt.update_canonical_synonyms( _manager( _canonical_synonyms=syn ),
                                  SimpleNamespace( id_hash="h", last_question_asked="", synonymous_questions={} ) )
    assert "Skipping" not in capsys.readouterr().out


# ── pg_similarity_search ───────────────────────────────────────────────────────────────

@pytest.fixture
def repo( monkeypatch ):
    """Fake session + repository; the test fills `hits` and reads what the repository was asked."""
    state = SimpleNamespace( hits=[], asked={} )
    @contextmanager
    def get_db(): yield "session"
    class Repo:
        def __init__( self, session ): pass
        def by_code( self, embedding, threshold, limit ):
            state.asked.update( embedding=embedding, threshold=threshold, limit=limit )
            return state.hits
    monkeypatch.setattr( "cosa.rest.db.database.get_db", get_db )
    monkeypatch.setattr( "cosa.rest.db.repositories.solution_snapshot_repository.SolutionSnapshotRepository", Repo )
    return state


def _search( **kw ):
    """Call pg_similarity_search with sensible defaults, overridable per test."""
    args = dict( manager=_manager(), exemplar_snapshot=SimpleNamespace( id_hash="me", emb=[ 0.5, 0.5 ] ),
                 embedding_attr="emb", repo_method_name="by_code", threshold=80.0, limit=3,
                 exclude_self=False, ensure_top_result=False )
    args.update( kw )
    return tt.pg_similarity_search( **args )


def _entity( id_hash ): return SimpleNamespace( id_hash=id_hash )


def test_similarity_refuses_bad_inputs():
    """Uninitialized manager, no exemplar and an out-of-range threshold each raise."""
    with pytest.raises( RuntimeError, match="initialized" ):
        _search( manager=_manager( is_initialized=lambda: False ) )
    with pytest.raises( ValueError, match="Exemplar" ):
        _search( exemplar_snapshot=None )
    for bad in ( -1.0, 100.1 ):
        with pytest.raises( ValueError, match="Threshold" ):
            _search( threshold=bad )


@pytest.mark.parametrize( "emb", [ [], None, [ 0.0 ] * 5 ] )
def test_a_missing_or_all_zero_embedding_returns_empty_without_a_query( repo, emb ):
    """No usable query vector: [] and the repository is never asked."""
    assert _search( exemplar_snapshot=SimpleNamespace( id_hash="me", emb=emb ) ) == []
    assert repo.asked == {}


@pytest.mark.parametrize( "exclude_self,limit,asked", [ ( True, 3, 4 ), ( False, 3, 3 ), ( False, 0, 100 ) ] )
def test_the_fetch_limit_depends_on_self_exclusion_and_limit( repo, exclude_self, limit, asked ):
    """Self-exclusion fetches one extra; a non-positive limit fetches 100; no SQL threshold."""
    _search( exclude_self=exclude_self, limit=limit )
    assert repo.asked[ "limit" ] == asked and repo.asked[ "threshold" ] is None


def test_hits_are_filtered_by_threshold_sorted_and_capped_at_limit( repo ):
    """Below-threshold hits drop out; the rest sort descending and are cut to limit."""
    repo.hits[ : ] = [ ( 81.0, _entity( "a" ) ), ( 99.0, _entity( "b" ) ), ( 50.0, _entity( "c" ) ),
                       ( 90.0, _entity( "d" ) ), ( 85.0, _entity( "e" ) ) ]
    got = _search( limit=3 )
    assert [ pct for pct, _ in got ] == [ 99.0, 90.0, 85.0 ]
    assert got[ 0 ][ 1 ] == ( "snap", ( "rec", "b" ) )


def test_the_exemplar_itself_is_skipped_only_when_asked( repo ):
    """exclude_self drops the hit with the exemplar's id_hash; otherwise it stays."""
    repo.hits[ : ] = [ ( 100.0, _entity( "me" ) ), ( 90.0, _entity( "other" ) ) ]
    assert [ s[ 1 ][ 1 ] for s in _search( exclude_self=True ) ] == [ ( "rec", "other" ) ]
    assert [ s[ 1 ][ 1 ] for s in _search( exclude_self=False ) ] == [ ( "rec", "me" ), ( "rec", "other" ) ]


def test_a_zero_limit_returns_every_qualifying_hit( repo ):
    """limit 0 means no cap on the Python side."""
    repo.hits[ : ] = [ ( 90.0 - i, _entity( f"x{i}" ) ) for i in range( 6 ) ]
    assert len( _search( limit=0 ) ) == 6


def test_ensure_top_result_returns_the_best_below_threshold_hit_only_when_nothing_qualifies( repo ):
    """With no qualifying hit the first below-threshold hit is returned; otherwise it is ignored."""
    repo.hits[ : ] = [ ( 70.0, _entity( "near" ) ), ( 60.0, _entity( "far" ) ) ]
    assert _search( ensure_top_result=True ) == [ ( 70.0, ( "snap", ( "rec", "near" ) ) ) ]
    assert _search( ensure_top_result=False ) == []
    repo.hits[ : ] = [ ( 95.0, _entity( "good" ) ), ( 70.0, _entity( "near" ) ) ]
    assert [ pct for pct, _ in _search( ensure_top_result=True ) ] == [ 95.0 ]


def test_a_quiet_manager_adds_the_primary_question_and_a_failed_add_without_printing( capsys ):
    """debug off: success and failure both stay silent; the failure is still swallowed."""
    syn = MagicMock()
    mgr = _manager( _canonical_synonyms=syn, debug=False )
    tt.update_canonical_synonyms( mgr, SimpleNamespace( id_hash="h", last_question_asked="q" ) )
    syn.add_synonym.side_effect = RuntimeError( "x" )
    tt.update_canonical_synonyms( mgr, SimpleNamespace( id_hash="h", last_question_asked="q" ) )
    assert syn.add_synonym.call_count == 2 and capsys.readouterr().out == ""


def test_a_hit_exactly_at_the_threshold_qualifies( repo ):
    """The threshold is inclusive: 80.0 against 80.0 is returned, 79.99 is not."""
    repo.hits[ : ] = [ ( 80.0, _entity( "edge" ) ), ( 79.99, _entity( "under" ) ) ]
    assert [ pct for pct, _ in _search( threshold=80.0 ) ] == [ 80.0 ]
