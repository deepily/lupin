"""
The packed request body, how its answers are read, and the four cache keys.

Plan: src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.07-jev-reuse-sweep-packed-request-plan.md
sections 10.3 a (the four keys) and 10.3 b to d. Nothing here reaches Jev.
"""
import pytest

from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

NEED  = "read an RSS feed and return its articles"
E1    = { "id": "cosa.feeds.parse_feed", "sig": "( url )", "doc": "Parse an RSS feed.", "file": "src/cosa/feeds.py" }
E2    = { "id": "cosa.mathx.add", "sig": "( a, b )", "doc": "Add two numbers.", "file": "src/cosa/mathx.py" }
E3    = { "id": "lupin_mcp.tool.serve", "sig": "()", "doc": "Serve the tool.", "file": "src/lupin_mcp/tool.py" }
PROBS = { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 }


def answer_for( qmap, ids ):
    """A response that answers only the entries in `ids`."""
    return { "answers": { qmap[ i ]: { "probabilities": dict( PROBS ) } for i in ids } }


def test_the_need_is_in_state_once_and_each_candidate_has_its_own_question():
    body, qmap = rp.pack_request( NEED, [ E1, E2, E3 ] )
    assert body[ "state" ] == { "need": NEED }
    assert body[ "model" ] == rt.JEV_MODEL
    assert sorted( qmap ) == sorted( [ E1[ "id" ], E2[ "id" ], E3[ "id" ] ] )
    assert sorted( body[ "questions" ] ) == sorted( qmap.values() )
    for e in ( E1, E2, E3 ):
        q = body[ "questions" ][ qmap[ e[ "id" ] ] ]
        assert q[ "type" ] == "choice" and q[ "criteria" ] == rt.PROMPT_TEMPLATE[ "criteria" ]
        assert rt.entry_text( e ) in q[ "instructions" ]
        assert "CANDIDATE" not in q[ "instructions" ]


def test_a_candidate_text_appears_only_in_its_own_question():
    body, qmap = rp.pack_request( NEED, [ E1, E2 ] )
    assert rt.entry_text( E2 ) not in body[ "questions" ][ qmap[ E1[ "id" ] ] ][ "instructions" ]
    assert rt.entry_text( E1 ) not in body[ "questions" ][ qmap[ E2[ "id" ] ] ][ "instructions" ]


def test_the_body_is_the_same_for_the_same_inputs_and_changes_with_each_input():
    base = rp.pack_request( NEED, [ E1, E2 ] )[ 0 ]
    assert rp.pack_request( NEED, [ E1, E2 ] )[ 0 ] == base
    assert rp.pack_request( NEED + "!", [ E1, E2 ] )[ 0 ] != base
    assert rp.pack_request( NEED, [ E1 ] )[ 0 ] != base


def test_a_moving_model_alias_is_refused():
    with pytest.raises( ValueError, match="moving alias" ):
        rp.pack_request( NEED, [ E1 ], model="jev-latest" )


def test_an_empty_pack_is_refused():
    with pytest.raises( ValueError, match="empty" ):
        rp.pack_request( NEED, [] )


def test_two_entries_with_one_id_are_refused_because_their_questions_would_collide():
    with pytest.raises( ValueError, match="duplicate" ):
        rp.pack_request( NEED, [ E1, dict( E1 ) ] )


def test_an_entry_is_answered_only_when_its_answer_is_present():
    body, qmap = rp.pack_request( NEED, [ E1, E2, E3 ] )
    answered, unasked = rp.pack_answers( answer_for( qmap, [ E1[ "id" ], E3[ "id" ] ] ), qmap )
    assert sorted( answered ) == sorted( [ E1[ "id" ], E3[ "id" ] ] )
    assert answered[ E1[ "id" ] ] == PROBS
    assert unasked == [ E2[ "id" ] ]


def test_an_answer_without_probabilities_is_unasked_not_unrelated():
    body, qmap = rp.pack_request( NEED, [ E1, E2 ] )
    response   = { "answers": { qmap[ E1[ "id" ] ]: { "probabilities": dict( PROBS ) }, qmap[ E2[ "id" ] ]: {} } }
    answered, unasked = rp.pack_answers( response, qmap )
    assert list( answered ) == [ E1[ "id" ] ] and unasked == [ E2[ "id" ] ]


@pytest.mark.parametrize( "response", [ None, {}, { "answers": None }, { "answers": [] }, { "answers": "x" } ] )
def test_a_response_with_no_usable_answers_leaves_every_entry_unasked( response ):
    body, qmap = rp.pack_request( NEED, [ E1, E2 ] )
    answered, unasked = rp.pack_answers( response, qmap )
    assert answered == {} and unasked == [ E1[ "id" ], E2[ "id" ] ]


def test_an_answer_for_a_question_nobody_asked_is_ignored():
    body, qmap = rp.pack_request( NEED, [ E1 ] )
    response   = answer_for( qmap, [ E1[ "id" ] ] )
    response[ "answers" ][ "q_stranger" ] = { "probabilities": dict( PROBS ) }
    answered, unasked = rp.pack_answers( response, qmap )
    assert list( answered ) == [ E1[ "id" ] ] and unasked == []


OLD_PATH_KEY = "a88c01aa991a2d2e8607c11e70f49731cb9cc902"        # request_hash of the body below, measured at 4a4a38e39 and at 5785c22c0


def test_the_old_path_key_is_untouched():
    """request_hash( build_request( ... ) ) is the key of every cached 15:34 response."""
    body = rt.build_request( NEED, rt.entry_text( E1 ) )
    assert rt.request_hash( body ) == OLD_PATH_KEY


def test_four_keys_never_collide_for_one_candidate():
    text   = rt.entry_text( E1 )
    stage1 = rp.stage1_key( NEED, text, pack_size=10, run_index=3 )
    cand   = rp.candidate_key( NEED, text )
    body   = rp.pack_request( NEED, [ E1 ] )[ 0 ]
    pack   = rp.pack_key( body )
    old    = rt.request_hash( rt.build_request( NEED, text ) )
    assert len( { stage1, cand, pack, old } ) == 4


def test_stage_one_keys_differ_by_pack_size_and_by_run_index():
    text = rt.entry_text( E1 )
    k    = rp.stage1_key( NEED, text, pack_size=10, run_index=3 )
    assert k == rp.stage1_key( NEED, text, pack_size=10, run_index=3 )
    assert k != rp.stage1_key( NEED, text, pack_size=50, run_index=3 )
    assert k != rp.stage1_key( NEED, text, pack_size=10, run_index=4 )


def test_the_candidate_key_ignores_pack_size_and_neighbours():
    text = rt.entry_text( E1 )
    assert rp.candidate_key( NEED, text ) == rp.candidate_key( NEED, text )
    assert rp.candidate_key( NEED, text ) != rp.candidate_key( NEED + "!", text )
    assert rp.candidate_key( NEED, text ) != rp.candidate_key( NEED, rt.entry_text( E2 ) )


def test_the_pack_key_changes_when_a_neighbour_changes():
    a = rp.pack_key( rp.pack_request( NEED, [ E1, E2 ] )[ 0 ] )
    b = rp.pack_key( rp.pack_request( NEED, [ E1, E3 ] )[ 0 ] )
    assert a != b
