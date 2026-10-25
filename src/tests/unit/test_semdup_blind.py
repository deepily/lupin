"""Unit tests for semdup.blind: what the judge may see, and the refusal on a surviving token."""
import json

import pytest

from cosa.repo.semdup import blind as bl
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex

SCRUB = bl.scrub_tokens( [ "ARM-WITH", "ARM-WITHOUT" ] )


def make( name="helper", text="def helper( x ):\n    return x + 1", file="src/a/mod.py", lang="py", origin="new", sig="( x )" ):
    """Build a definition record the way extract does."""
    return { "id": ex.definition_id( origin, file, name, text ), "origin": origin, "lang": lang, "file": file, "name": name, "line": 7, "end_line": 9,
             "sig": sig, "text": text, "calls": [ "zeta" ], "nodes": 12, "public": True, "declared": [ "x" ] }


def test_the_scrub_list_is_the_tool_tokens_plus_the_arm_labels_once_each():
    assert bl.scrub_tokens( [ "ARM-WITH", "check_exists" ] ) == [ *bl.REUSE_TOOL_TOKENS, "ARM-WITH" ]
    assert bl.REUSE_TOOL_TOKENS == ( "check_exists", "fetch_similar", "read_capability", "record_search", "reuse-reviewer", "reuse-receipt", "SEARCHED" )


def test_ordinary_words_the_existing_client_uses_are_not_in_the_scrub_list():
    for word in ( "receipt", "persona", "searched", "exists", "similar" ): assert word not in bl.REUSE_TOOL_TOKENS


@pytest.mark.parametrize( "call", [ lambda: bl.scrub_tokens( [ "ok", "" ] ), lambda: bl.assert_blind( "text", [ "" ] ), lambda: bl.strip_comment_lines( "x", "py", [ "" ] ) ] )
def test_an_empty_scrub_token_is_refused_because_it_is_found_in_every_text( call ):
    with pytest.raises( ValueError, match="empty token" ):
        call()


@pytest.mark.parametrize( "token", bl.REUSE_TOOL_TOKENS + ( "ARM-WITH", "ARM-WITHOUT" ) )
def test_assert_blind_refuses_each_token_and_names_it_without_quoting_the_text( token ):
    with pytest.raises( err.SemdupError ) as caught:
        bl.assert_blind( f"prefix secret-body {token} suffix", SCRUB )
    assert caught.value.code == err.BLINDNESS_BREACH and token in caught.value.detail and "secret-body" not in caught.value.detail


def test_assert_blind_passes_clean_text_and_matches_case_exactly():
    bl.assert_blind( "a function that searched and checked whether it exists", SCRUB )
    bl.assert_blind( "Check_Exists is not the tool name", SCRUB )                 # the match is on the exact characters


def test_assert_blind_lists_every_token_found():
    with pytest.raises( err.SemdupError ) as caught:
        bl.assert_blind( "check_exists then fetch_similar", SCRUB )
    assert caught.value.detail.endswith( "check_exists, fetch_similar" )


@pytest.mark.parametrize( "file, expected", [
    ( "src/a/mod.py", "src/a/mod.py" ),
    ( ".claude/worktrees/arm-with-3/src/a/mod.py", "src/a/mod.py" ),
    ( "runs/one/.claude/worktrees/seat-x/src/a/mod.py", "src/a/mod.py" ),
    ( "src/worktrees/keep/mod.py", "src/worktrees/keep/mod.py" ),
] )
def test_a_worktree_prefix_is_dropped_from_a_path_and_nothing_else( file, expected ):
    assert bl.relative_path( file ) == expected


def test_a_python_comment_line_with_a_token_is_removed_and_one_without_is_kept():
    text = "def f():\n    # uses check_exists first\n    # plain note\n    return 1"
    assert bl.strip_comment_lines( text, "py", SCRUB ) == "def f():\n    # plain note\n    return 1"


@pytest.mark.parametrize( "marker", [ "//", "/*", "*" ] )
def test_a_script_comment_line_with_a_token_is_removed_for_each_marker( marker ):
    text = f"function f() {{\n    {marker} see fetch_similar\n    return 1;\n}}"
    assert bl.strip_comment_lines( text, "ts", SCRUB ) == "function f() {\n    return 1;\n}"


def test_a_token_in_code_or_a_trailing_comment_is_not_removed_and_so_is_refused_later():
    text = "x = 1  # check_exists\ny = 'check_exists'"
    assert bl.strip_comment_lines( text, "py", SCRUB ) == text
    with pytest.raises( err.SemdupError ):
        bl.blind_definition( make( text=text ), SCRUB )


def test_an_unknown_language_is_a_key_error():
    with pytest.raises( KeyError ):
        bl.strip_comment_lines( "x", "rb", SCRUB )


def test_blind_definition_returns_only_what_the_judge_may_see():
    d = make( origin="server" )
    b = bl.blind_definition( d, SCRUB )
    assert sorted( b ) == [ "file", "id", "lang", "name", "sig", "text" ]
    assert b[ "id" ] == bl.opaque_id( d ) and b[ "name" ] == "helper" and b[ "text" ] == d[ "text" ]
    assert "server" not in json.dumps( b ) and "zeta" not in json.dumps( b )                  # neither the origin nor the calls reach the judge


def test_origin_and_line_numbers_never_change_what_the_judge_sees():
    a = bl.blind_definition( make( origin="new" ), SCRUB )
    b = bl.blind_definition( { **make( origin="server" ), "line": 900, "end_line": 903, "calls": [], "declared": [] }, SCRUB )
    assert json.dumps( a, sort_keys=True ) == json.dumps( b, sort_keys=True )


def test_two_definitions_identical_except_for_the_worktree_path_give_the_same_bytes():
    one = bl.blind_definition( make( file=".claude/worktrees/arm-with/src/a/mod.py" ), SCRUB )
    two = bl.blind_definition( make( file=".claude/worktrees/arm-without/src/a/mod.py" ), SCRUB )
    assert json.dumps( one, sort_keys=True ).encode() == json.dumps( two, sort_keys=True ).encode()
    assert one[ "file" ] == "src/a/mod.py" and "arm" not in one[ "file" ]


def test_the_opaque_id_changes_with_path_name_or_text_but_not_with_origin_or_worktree():
    base = bl.opaque_id( make() )
    assert base.startswith( "x-" ) and len( base ) == 12
    assert bl.opaque_id( make( origin="server" ) ) == base
    assert bl.opaque_id( make( file=".claude/worktrees/w/src/a/mod.py" ) ) == base
    for other in ( make( file="src/a/other.py" ), make( name="other" ), make( text="def helper( x ):\n    return x + 2" ) ):
        assert bl.opaque_id( other ) != base


@pytest.mark.parametrize( "field, value", [ ( "name", "check_exists" ), ( "file", "src/fetch_similar/mod.py" ), ( "sig", "( record_search )" ),
                                            ( "text", "def helper( x ):\n    return 'reuse-reviewer'" ) ] )
def test_a_token_in_the_name_path_signature_or_a_string_literal_is_refused( field, value ):
    with pytest.raises( err.SemdupError ) as caught:
        bl.blind_definition( make( **{ field: value } ), SCRUB )
    assert caught.value.code == err.BLINDNESS_BREACH


def test_a_prompt_body_that_mentions_check_exists_in_a_string_literal_raises_and_does_not_pass():
    d = make( text="def helper( x ):\n    msg = \"call check_exists\"\n    return msg" )
    with pytest.raises( err.SemdupError, match="check_exists" ):
        bl.blind_definition( d, SCRUB )


def test_an_arm_label_in_a_comment_is_removed_and_in_code_is_refused():
    assert "ARM-WITH" not in bl.blind_definition( make( text="def helper( x ):\n    # run ARM-WITH\n    return 1" ), SCRUB )[ "text" ]
    with pytest.raises( err.SemdupError, match="ARM-WITH" ):
        bl.blind_definition( make( text="def helper( x ):\n    return 'ARM-WITH'" ), SCRUB )


def test_candidate_order_is_stable_under_input_reordering_and_hides_the_input_order():
    blinded = [ bl.blind_definition( make( name=f"fn{i}", text=f"def fn{i}():\n    return {i}" ), SCRUB ) for i in range( 12 ) ]
    forward = bl.candidate_order( blinded )
    assert [ b[ "id" ] for b in bl.candidate_order( list( reversed( blinded ) ) ) ] == [ b[ "id" ] for b in forward ]
    assert [ b[ "id" ] for b in forward ] != [ b[ "id" ] for b in blinded ]               # not the input order
    assert [ b[ "id" ] for b in forward ] != sorted( b[ "id" ] for b in blinded )          # and not the id order: it is the sha order
    assert blinded[ 0 ] in forward and len( forward ) == 12 and forward is not blinded


def test_breaching_ids_names_each_definition_blind_definition_refuses_in_sorted_order_and_none_of_the_clean():
    clean = make( name="ok" )
    leak1 = make( name="leak_a", text="def leak_a( x ):\n    return check_exists( x )" )
    leak2 = make( name="leak_b", text="def leak_b( x ):\n    return ARM-WITH" )
    assert bl.breaching_ids( [ leak2, clean, leak1 ], SCRUB ) == sorted( [ leak1[ "id" ], leak2[ "id" ] ] )
    assert bl.breaching_ids( [ clean ], SCRUB ) == [] and bl.breaching_ids( [], SCRUB ) == []
    for d in ( leak1, leak2 ):
        with pytest.raises( err.SemdupError ) as caught: bl.blind_definition( d, SCRUB )
        assert caught.value.code == err.BLINDNESS_BREACH
