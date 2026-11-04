"""
Unit tests for TwoTierQuestionSearch's debug trace and its small coercion helpers.

The lookup runs against in-memory fakes, so no database or model runs. Each test names the
debug line or helper arm it reaches and asserts the behaviour that arm gives.
"""

import types

import pytest

from cosa.memory.two_tier_question_search import TwoTierQuestionSearch


class _Store:
    """In-memory stand-in for the open session."""
    def __init__( self, rows=None, verbatim=None, cached=None, ann=None ):
        self.rows, self.verbatim, self.cached, self.ann = rows or {}, verbatim or {}, cached or {}, ann or []


class _SnapRepo:
    def __init__( self, s ): self.s = s
    def get_snapshot_by_id( self, sid ): return self.s.rows.get( sid )
    def get_snapshots_by_question( self, emb, threshold, limit ): return self.s.ann


class _SynRepo:
    def __init__( self, s ): self.s = s
    def find_exact_verbatim( self, q ): return self.s.verbatim.get( q )
    def find_exact_normalized( self, q ): return None


class _EmbRepo:
    def __init__( self, s ): self.s = s
    def get_embedding( self, q ): return self.s.cached.get( q )


class _Provider:
    def __init__( self, vec ): self.vec = vec
    def generate_embedding( self, text, content_type="prose" ): return self.vec


def _search( store, vec=None, debug=True ):
    class CM:
        def __enter__( self_ ): return store
        def __exit__( self_, *a ): return False
    return TwoTierQuestionSearch(
        embedding_provider=_Provider( vec ), snapshot_factory=lambda **kw: types.SimpleNamespace( **kw ),
        normalizer=types.SimpleNamespace( normalize=lambda q: q.lower() ), gist_normalizer=object(),
        db_scope=lambda: CM(), synonym_repo_cls=_SynRepo, snapshot_repo_cls=_SnapRepo,
        embedding_repo_cls=_EmbRepo, embedding_dim=4, debug=debug )


def _row( **over ):
    """The smallest ORM row `_orm_to_snapshot` accepts."""
    row = types.SimpleNamespace(
        id_hash="r1", question="q", question_normalized="", question_gist="", answer="", answer_conversational="",
        thoughts="", error="", routing_command="", agent_class_name=None, code=None, solution_summary="",
        solution_summary_gist="", code_returns="", code_example="", code_type="", programming_language="",
        language_version="", non_synonymous_questions=None, last_question_asked="", created_date="",
        updated_date="", run_date="", synonymous_questions=None, synonymous_question_gists="",
        runtime_stats=None, replay_history="", replay_stats="", answer_is_correct="", is_cache_hit=False,
        question_embedding=None, question_normalized_embedding=None, question_gist_embedding=None,
        solution_embedding=None, code_embedding=None, thoughts_embedding=None, solution_gist_embedding=None )
    for k, v in over.items(): setattr( row, k, v )
    return row


def test_an_empty_query_embedding_is_a_tier_two_miss_and_says_so( capsys ):
    """The provider returns []: a miss with embed fields set, ann timing None, and a debug line."""
    got = _search( _Store(), vec=[] ).lookup( "Hello" )
    assert got.tier == "miss" and got.t_ann_ms is None and got.embed_cached is False
    assert "empty query embedding" in capsys.readouterr().out


def test_a_ghost_synonym_falls_through_and_says_so( capsys ):
    """A synonym naming a missing row is a miss for that tier; the id is in the debug line."""
    got = _search( _Store( verbatim={ "Hello": "ghost-1" } ), vec=[] ).lookup( "Hello" )
    assert got.tier == "miss" and got.is_replay_hit is False
    assert "missing snapshot ghost-1" in capsys.readouterr().out


def test_a_cached_query_embedding_skips_the_provider( capsys ):
    """A cached vector is used with embed_cached True, even if the provider would have failed."""
    store = _Store( cached={ "Hello": [ 0.1, 0.2 ] }, ann=[ ( 91.0, _row() ) ] )
    got = _search( store, vec=None ).lookup( "Hello" )
    assert got.tier == "ann" and got.embed_cached is True and got.best_score == 91.0
    assert "served from cache" in capsys.readouterr().out


def test_loads_or_decodes_json_and_defaults_only_for_empty_cells():
    """None and '' give the default; a JSON string is decoded; garbage raises."""
    f = TwoTierQuestionSearch._loads_or
    assert f( None, {} ) == {} and f( "", [] ) == []
    assert f( '{"a": 1}', {} ) == { "a": 1 }
    with pytest.raises( ValueError ):
        f( "{not json", {} )


def test_ensure_list_coerces_none_lists_and_other_sequences():
    """None is []; a list is returned as is (same object); a tuple becomes a new list."""
    f = TwoTierQuestionSearch._ensure_list
    lst = [ 1 ]
    assert f( None ) == [] and f( lst ) is lst and f( ( 1, 2 ) ) == [ 1, 2 ]


@pytest.mark.parametrize( "vec,expected", [ ( None, [ 0.0 ] * 4 ), ( [], [ 0.0 ] * 4 ), ( [ 1, 2, 3, 4 ], [ 1.0, 2.0, 3.0, 4.0 ] ),
                                            ( [ 1 ], [ 1.0, 0.0, 0.0, 0.0 ] ), ( [ 1, 2, 3, 4, 5 ], [ 1.0, 2.0, 3.0, 4.0 ] ) ] )
def test_fit_embedding_zero_fills_pads_and_truncates( vec, expected ):
    """_fit_embedding returns a vector of the configured dimension."""
    assert _search( _Store() )._fit_embedding( vec ) == expected


def test_orm_row_with_empty_cells_marshals_to_defaults():
    """None cells become empty containers and zero vectors of the dimension."""
    snap = _search( _Store() )._orm_to_snapshot( _row() )
    assert snap.synonymous_questions == {} and snap.code == [] and snap.non_synonymous_questions == []
    assert snap.question_embedding == [ 0.0 ] * 4
    assert ( snap.programming_language, snap.language_version ) == ( "python", "3.10" )
