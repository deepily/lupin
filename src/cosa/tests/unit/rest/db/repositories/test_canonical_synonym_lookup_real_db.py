"""
Real-database tests for the three exact finders of the canonical synonym table.

Each finder reads one of three question columns and answers with the snapshot id. The stored
row has three different texts, so a finder on the wrong column finds nothing. A second row
shows that only an exact value counts.
"""
from datetime import datetime

import pytest

from cosa.rest.db.repositories.canonical_synonym_repository import CanonicalSynonymRepository
from cosa.rest.db.vector_store_models import CanonicalSynonym


def _row( repo, id, snapshot_id, verbatim, normalized, gist ):
    return repo.add_synonym(
        id=id, snapshot_id=snapshot_id, question_verbatim=verbatim, question_normalized=normalized,
        question_gist=gist, created_date=datetime( 2026, 7, 1 ),
    )


@pytest.fixture()
def repo( db_session ):
    r = CanonicalSynonymRepository( db_session )
    _row( r, "a", "snap-a", "How old are you?", "how old are you", "age" )
    _row( r, "b", "snap-b", "Who are you?", "who are you", "identity" )
    db_session.flush()
    return r


@pytest.mark.parametrize( "finder, own_a, own_b", [
    ( "find_exact_verbatim",   "How old are you?", "Who are you?" ),
    ( "find_exact_normalized", "how old are you",  "who are you" ),
    ( "find_exact_gist",      "age",              "identity" ),
] )
def test_each_finder_answers_with_the_snapshot_of_the_row_whose_own_column_matches( repo, finder, own_a, own_b ):
    assert getattr( repo, finder )( own_a ) == "snap-a" and getattr( repo, finder )( own_b ) == "snap-b"


@pytest.mark.parametrize( "finder", [ "find_exact_verbatim", "find_exact_normalized", "find_exact_gist" ] )
def test_each_finder_ignores_the_other_two_columns_and_near_misses( repo, finder ):
    others = { "find_exact_verbatim": ( "how old are you", "age" ), "find_exact_normalized": ( "How old are you?", "age" ), "find_exact_gist": ( "How old are you?", "how old are you" ) }[ finder ]
    for text in others + ( "", "How Old Are You?", "how old are you ", "ag", "age ", " age" ):
        assert getattr( repo, finder )( text ) is None, ( finder, text )


def test_the_shared_lookup_reads_any_column_and_gives_none_on_a_miss( repo ):
    assert repo._snapshot_id_where( CanonicalSynonym.question_gist, "identity" ) == "snap-b"
    assert repo._snapshot_id_where( CanonicalSynonym.question_gist, "nobody" ) is None
