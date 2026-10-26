"""
Unit tests for `pg_hierarchical_search`: every level and failure arm.

The manager, its synonym table, normalizer, embedding table and the Postgres session are all
fakes, so no database runs. Each test names the level that answered.
"""

import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cosa.memory import two_tier_question_search as tt


def _manager( synonyms="unset", normalizer="unset", snapshots=None, embedding=None, initialized=True ):
    """A manager stub; `synonyms` and `normalizer` may be None (lazy init), False, or a fake."""
    snaps = snapshots or {}
    m = SimpleNamespace(
        debug=True, verbose=False,
        _canonical_synonyms = MagicMock() if synonyms == "unset" else synonyms,
        _normalizer         = MagicMock() if normalizer == "unset" else normalizer,
        is_initialized      = lambda: initialized,
        get_snapshot_by_id  = lambda sid: snaps.get( sid ),
        _question_embeddings_tbl = SimpleNamespace( get_embedding = lambda q: embedding ),
        _record_to_snapshot      = lambda record: ( "snap", record ),
        _pg_record_from_entity   = lambda entity: ( "rec", entity ),
    )
    return m


@pytest.fixture
def fake_db( monkeypatch ):
    """Replace the session factory and repository the search imports at call time."""
    hits = []
    seen = {}
    @contextmanager
    def get_db(): yield "session"
    class Repo:
        def __init__( self, session ): seen[ "session" ] = session
        def get_snapshots_by_question( self, embedding, threshold, limit ):
            seen.update( embedding=embedding, threshold=threshold, limit=limit )
            return hits
    monkeypatch.setattr( "cosa.rest.db.database.get_db", get_db )
    monkeypatch.setattr( "cosa.rest.db.repositories.solution_snapshot_repository.SolutionSnapshotRepository", Repo )
    return hits, seen


def test_an_uninitialized_manager_is_refused():
    """RuntimeError before anything else is touched."""
    with pytest.raises( RuntimeError, match="initialized" ):
        tt.pg_hierarchical_search( _manager( initialized=False ), "q" )


def test_an_empty_question_is_refused():
    """ValueError for an empty question."""
    with pytest.raises( ValueError, match="empty" ):
        tt.pg_hierarchical_search( _manager(), "" )


@pytest.mark.parametrize( "kwargs", [ { "threshold_question": -1 }, { "threshold_question": 100.5 },
                                      { "threshold_gist": -0.1 }, { "threshold_gist": 101 } ] )
def test_out_of_range_thresholds_are_refused( kwargs ):
    """Either threshold outside 0..100 is a ValueError."""
    with pytest.raises( ValueError, match="between 0.0 and 100.0" ):
        tt.pg_hierarchical_search( _manager(), "q", **kwargs )


def test_level_one_exact_verbatim_match_short_circuits_at_100():
    """A verbatim synonym hit whose snapshot exists returns [(100.0, snapshot)] and never embeds."""
    syn = MagicMock()
    syn.find_exact_verbatim.return_value = "sid-1"
    m = _manager( synonyms=syn, snapshots={ "sid-1": "S1" } )
    assert tt.pg_hierarchical_search( m, "what time" ) == [ ( 100.0, "S1" ) ]
    syn.find_exact_normalized.assert_not_called()


def test_level_one_ghost_synonym_is_deleted_and_the_search_falls_through( fake_db, capsys ):
    """A verbatim hit on a missing snapshot is cleaned, then later levels still run."""
    syn = MagicMock()
    syn.find_exact_verbatim.return_value = "ghost-id-123456"
    syn.find_exact_normalized.return_value = None
    norm = MagicMock()
    norm.normalize.return_value = "what time"
    m = _manager( synonyms=syn, normalizer=norm, embedding=[0.1] )
    assert tt.pg_hierarchical_search( m, "What time?" ) == []
    syn.delete_by_snapshot_id.assert_called_once_with( "ghost-id-123456" )
    syn.find_exact_normalized.assert_called_once_with( "what time" )
    assert "[GHOST]" in capsys.readouterr().out


def test_level_two_normalized_match_returns_the_snapshot():
    """No verbatim hit; the normalized form hits and its snapshot is returned at 100."""
    syn = MagicMock()
    syn.find_exact_verbatim.return_value = None
    syn.find_exact_normalized.return_value = "sid-2"
    norm = MagicMock()
    norm.normalize.return_value = "norm"
    m = _manager( synonyms=syn, normalizer=norm, snapshots={ "sid-2": "S2" } )
    assert tt.pg_hierarchical_search( m, "Q" ) == [ ( 100.0, "S2" ) ]
    syn.find_exact_normalized.assert_called_once_with( "norm" )


def test_level_two_ghost_synonym_is_deleted_and_the_search_goes_on( fake_db ):
    """A normalized hit on a missing snapshot is cleaned and the vector level then answers empty."""
    syn = MagicMock()
    syn.find_exact_verbatim.return_value = None
    syn.find_exact_normalized.return_value = "ghost-id-654321"
    m = _manager( synonyms=syn, embedding=[0.2] )
    assert tt.pg_hierarchical_search( m, "Q" ) == []
    syn.delete_by_snapshot_id.assert_called_once_with( "ghost-id-654321" )


def test_without_a_normalizer_level_two_is_skipped( fake_db ):
    """A normalizer of False skips level 2 entirely."""
    syn = MagicMock()
    syn.find_exact_verbatim.return_value = None
    m = _manager( synonyms=syn, normalizer=False, embedding=[0.2] )
    assert tt.pg_hierarchical_search( m, "Q" ) == []
    syn.find_exact_normalized.assert_not_called()


def test_lazy_init_builds_the_synonym_table_and_normalizer( monkeypatch, fake_db ):
    """None collaborators are built on first use with the manager's flags."""
    built = {}
    class FakeTable:
        def __init__( self, debug, verbose ):
            built[ "table" ] = ( debug, verbose )
        def find_exact_verbatim( self, q ): return None
        def find_exact_normalized( self, q ): return None
    class FakeNormalizer:
        def normalize( self, q ): return q.lower()
    monkeypatch.setitem( sys.modules, "cosa.memory.canonical_synonyms_table",
                         types.SimpleNamespace( CanonicalSynonymsTable=FakeTable ) )
    monkeypatch.setattr( tt, "Normalizer", FakeNormalizer, raising=False )
    monkeypatch.setattr( "cosa.memory.normalizer.Normalizer", FakeNormalizer )
    m = _manager( synonyms=None, normalizer=None, embedding=[0.3] )
    tt.pg_hierarchical_search( m, "Q" )
    assert built[ "table" ] == ( True, False )
    assert isinstance( m._canonical_synonyms, FakeTable ) and isinstance( m._normalizer, FakeNormalizer )


def test_lazy_init_failures_degrade_to_false_and_go_straight_to_vectors( monkeypatch, fake_db ):
    """If neither collaborator can be built, both become False and level 4 still answers."""
    class Boom:
        def __init__( self, *a, **k ): raise RuntimeError( "no db" )
    monkeypatch.setitem( sys.modules, "cosa.memory.canonical_synonyms_table",
                         types.SimpleNamespace( CanonicalSynonymsTable=Boom ) )
    monkeypatch.setattr( "cosa.memory.normalizer.Normalizer", Boom )
    m = _manager( synonyms=None, normalizer=None, embedding=[0.3] )
    assert tt.pg_hierarchical_search( m, "Q" ) == []
    assert m._canonical_synonyms is False and m._normalizer is False


def test_no_query_embedding_returns_empty_without_touching_the_database( monkeypatch ):
    """Level 4 with no embedding returns [] and never opens a session."""
    monkeypatch.setattr( "cosa.rest.db.database.get_db", MagicMock( side_effect=AssertionError( "db opened" ) ) )
    m = _manager( synonyms=False, normalizer=False, embedding=[] )
    assert tt.pg_hierarchical_search( m, "Q" ) == []


@pytest.mark.parametrize( "limit,expected", [ ( 5, 5 ), ( 0, 100 ), ( -3, 100 ) ] )
def test_vector_level_sorts_hits_and_maps_the_limit( fake_db, limit, expected ):
    """Hits sort descending; a non-positive limit means 100; no SQL threshold."""
    hits, seen = fake_db
    hits.extend( [ ( 71.0, "e1" ), ( 93.5, "e2" ), ( 80.0, "e3" ) ] )
    m = _manager( synonyms=False, normalizer=False, embedding=[0.5] )
    got = tt.pg_hierarchical_search( m, "Q", limit=limit )
    assert [ pct for pct, _ in got ] == [ 93.5, 80.0, 71.0 ]
    assert got[ 0 ][ 1 ] == ( "snap", ( "rec", "e2" ) )
    assert seen[ "threshold" ] is None and seen[ "limit" ] == expected and seen[ "embedding" ] == [ 0.5 ]


def test_a_failure_in_the_vector_level_is_reraised( monkeypatch ):
    """The repository raising propagates to the caller after the monitor is stopped."""
    @contextmanager
    def get_db(): raise ConnectionError( "pg down" )
    monkeypatch.setattr( "cosa.rest.db.database.get_db", get_db )
    m = _manager( synonyms=False, normalizer=False, embedding=[0.5] )
    with pytest.raises( ConnectionError, match="pg down" ):
        tt.pg_hierarchical_search( m, "Q" )
