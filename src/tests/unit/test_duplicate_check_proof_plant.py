"""Unit tests for semdup.proof.plant: draw, banned words, stripping and rewrite checks."""
import ast
import random

import pytest

from cosa.repo.semdup import extract as ex
from cosa.repo.semdup.proof import plant as pl
from cosa.repo.symindex import dups
from cosa.repo.symindex.need_writer import name_hits

ORIGINAL = "def scale_all( values, ratio ):\n    out = []\n    for value in values:\n        out.append( value * ratio )\n    return out\n"
DIFFERENT = "def spread( xs, k ):\n    return sum( x * k for x in xs if x )\n"
SAME_SHAPE = "def stretch( things, amount ):\n    acc = []\n    for thing in things:\n        acc.append( thing * amount )\n    return acc\n"


def record( i, lang, nodes=40 ):
    """Build the part of a definition record that the draw reads."""
    return { "id": f"d-{i:04d}", "lang": lang, "nodes": nodes }


def pool_of( script, python, nodes=40 ):
    """Build a pool of the given sizes."""
    return [ record( i, "ts", nodes ) for i in range( script ) ] + [ record( 1000 + i, "py", nodes ) for i in range( python ) ]


# ---- select_originals -------------------------------------------------------------------------------------------

def test_sixty_originals_are_exactly_thirty_six_script_and_twenty_four_python():
    chosen = pl.select_originals( pool_of( 150, 150 ), 60, 7, 25 )
    assert len( chosen ) == 60 and sum( 1 for d in chosen if d[ "lang" ] != "py" ) == 36 and sum( 1 for d in chosen if d[ "lang" ] == "py" ) == 24
    assert [ d[ "id" ] for d in chosen ] == sorted( d[ "id" ] for d in chosen )


def test_the_script_count_rounds_and_does_not_truncate():
    chosen = pl.select_originals( pool_of( 10, 10 ), 3, 1, 25 )
    assert sum( 1 for d in chosen if d[ "lang" ] != "py" ) == 2 and sum( 1 for d in chosen if d[ "lang" ] == "py" ) == 1


def test_the_same_seed_gives_the_same_draw_whatever_order_the_pool_arrives_in_and_another_seed_a_different_one():
    pool     = pool_of( 80, 80 )
    shuffled = list( pool )
    random.Random( 99 ).shuffle( shuffled )
    assert pl.select_originals( pool, 20, 5, 25 ) == pl.select_originals( shuffled, 20, 5, 25 )
    assert pl.select_originals( pool, 20, 5, 25 ) != pl.select_originals( pool, 20, 6, 25 )


def test_a_definition_under_min_nodes_is_never_drawn_and_a_shortage_is_refused_by_language():
    pool = pool_of( 10, 10, nodes=24 ) + [ record( 500, "ts", 25 ), record( 501, "py", 25 ) ]
    assert [ d[ "id" ] for d in pl.select_originals( pool, 2, 1, 25, script_share=0.5 ) ] == [ "d-0500", "d-0501" ]
    with pytest.raises( ValueError, match="need 36 script and 24 Python .* found 1 and 1" ): pl.select_originals( pool, 60, 1, 25 )
    with pytest.raises( ValueError, match="found 40 and 3" ): pl.select_originals( pool_of( 40, 3 ), 10, 1, 25 )
    with pytest.raises( ValueError, match="count must be 1 or more" ): pl.select_originals( pool, 0, 1, 25 )


# ---- banned_names and strip_names ---------------------------------------------------------------------------------

def test_a_script_definitions_banned_words_are_its_declared_names_name_class_file_stem_and_their_long_words():
    rec    = { "name": "UserStore.getUserProfile", "file": "src/js/userStore.ts", "declared": [ "id", "profileCache", "tmp" ] }
    banned = pl.banned_names( rec )
    assert "getUserProfile" in banned and "UserStore" in banned and "userStore" in banned and "profileCache" in banned and "tmp" in banned
    assert "profile" in banned and "cache" in banned and "store" in banned and "user" in banned and "id" not in banned
    assert banned == sorted( banned, key=lambda n: ( -len( n ), n ) ) and len( banned ) == len( set( banned ) )


def test_words_of_three_letters_inside_a_longer_name_are_not_banned_but_four_letter_ones_are():
    banned = pl.banned_names( { "name": "getMapValues", "file": "a/b.ts", "declared": [] } )
    assert "values" in banned and "get" not in banned and "map" not in banned
    assert "wide" in pl.banned_names( { "name": "isWide", "file": "a/b.ts", "declared": [] } )


def test_self_and_cls_are_never_banned_and_names_under_three_characters_are_dropped():
    rec = { "name": "f.go", "file": "a/b.py", "declared": [ "self", "cls", "ab", "abc" ] }
    assert pl.banned_names( rec, forbidden=[ "self" ] ) == [ "abc" ]


def test_a_python_definitions_banned_words_add_the_declared_locals_that_need_input_does_not_collect(tmp_path):
    ( tmp_path / "src" / "pkg" ).mkdir( parents=True )
    ( tmp_path / "src" / "pkg" / "__init__.py" ).write_text( "", encoding="utf-8" )
    ( tmp_path / "src" / "pkg" / "mod.py" ).write_text( ORIGINAL, encoding="utf-8" )
    rec       = ex.extract_python( tmp_path, tmp_path / "src" / "pkg" / "mod.py", "new" )[ 0 ]
    forbidden = pl.python_forbidden( rec, tmp_path )
    assert "scale_all" in forbidden and "values" in forbidden and "ratio" in forbidden and "out" not in forbidden and "value" not in forbidden
    banned = pl.banned_names( rec, forbidden )
    assert "out" in banned and "value" in banned and "scale" in banned


def test_an_unstripped_text_holds_banned_words_and_the_stripped_text_holds_none():
    rec    = { "name": "getUser", "file": "src/a.ts", "declared": [ "getUserId", "userCount" ] }
    text   = "function getUser( getUserId ) {\n    let userCount = getUserId + 1;\n    return userCount;\n}\n"
    assert name_hits( pl.banned_names( rec ), text ) != []
    stripped, replaced = pl.strip_names( text, rec[ "declared" ], name="getUser" )
    assert name_hits( [ "getUser", "getUserId", "userCount" ], stripped ) == []
    assert stripped == "function NAME( ARG1 ) {\n    let ARG2 = ARG1 + 1;\n    return ARG2;\n}\n" and replaced == [ "getUser", "getUserId", "userCount" ]


def test_overlapping_names_are_replaced_longest_first_so_no_half_replaced_name_is_left():
    text = "getUserId( getUser ) + getUser"
    out, _ = pl.strip_names( text, [ "getUser", "getUserId" ] )
    assert out == "ARG1( ARG2 ) + ARG2"
    out2, _ = pl.strip_names( text, [ "getUser", "getUserId" ], name="getUser" )
    assert out2 == "ARG1( NAME ) + NAME" and "getARG" not in out2


def test_arguments_are_numbered_by_first_appearance_and_only_whole_words_are_replaced():
    out, _ = pl.strip_names( "second first userData first2 second", [ "first", "second", "user" ] )
    assert out == "ARG1 ARG2 userData first2 ARG1"


def test_text_with_no_names_to_replace_comes_back_unchanged():
    assert pl.strip_names( "return 1", [] ) == ( "return 1", [] )
    assert pl.strip_names( "return 1", [ "" ] ) == ( "return 1", [] )


# ---- rewrite_prompt, python_shape and check_rewrite -----------------------------------------------------------------

def test_the_prompt_holds_the_source_and_every_banned_word_and_names_each_failure_without_the_shape():
    system, user = pl.rewrite_prompt( ORIGINAL, [ "values", "ratio" ] )
    assert system == pl.SYSTEM_PROMPT and ORIGINAL in user and "values, ratio" in user and "last try" not in user
    _, retry = pl.rewrite_prompt( ORIGINAL, [ "values" ], { "banned_word": [ "values" ], "unparsable": True, "same_shape": 0.9 } )
    assert "still used: values." in retry and "did not parse" in retry and "built the same way" in retry and "0.9" not in retry


def test_the_shape_of_a_source_is_its_first_functions_shingles_and_none_when_there_is_no_function_or_it_does_not_parse():
    assert pl.python_shape( ORIGINAL ) == dups.shingles( ast.parse( ORIGINAL ).body[ 0 ] )
    assert pl.python_shape( "    " + ORIGINAL.replace( "\n", "\n    " ).rstrip( " " ) ) is not None
    assert pl.python_shape( "async def f( x ):\n    return x\n" ) is not None
    assert pl.python_shape( "x = 1\n" ) is None and pl.python_shape( "def (:\n" ) is None


def test_a_rewrite_that_passes_is_accepted_and_a_different_shape_is_below_the_near_cut():
    assert dups.jaccard( pl.python_shape( ORIGINAL ), pl.python_shape( DIFFERENT ) ) < pl.SAME_SHAPE
    assert pl.check_rewrite( ORIGINAL, DIFFERENT, [ "values", "ratio" ] ) == {}


def test_a_rewrite_with_a_banned_word_is_refused_with_the_words_found():
    failed = pl.check_rewrite( ORIGINAL, DIFFERENT.replace( "xs", "values" ), [ "values", "ratio" ] )
    assert failed == { "banned_word": [ "values" ] }


def test_a_rewrite_that_does_not_parse_is_refused_as_unparsable_only():
    assert pl.check_rewrite( ORIGINAL, "def broken( :\n", [ "values" ] ) == { "unparsable": True }


def test_a_rewrite_built_the_same_way_is_refused_with_its_jaccard_and_one_just_under_the_cut_passes():
    failed = pl.check_rewrite( ORIGINAL, SAME_SHAPE, [ "values", "ratio" ] )
    assert list( failed ) == [ "same_shape" ] and failed[ "same_shape" ] >= pl.SAME_SHAPE
    near = dups.jaccard( pl.python_shape( ORIGINAL ), pl.python_shape( SAME_SHAPE ) )
    assert pl.check_rewrite( ORIGINAL, SAME_SHAPE, [], threshold=near + 0.01 ) == {}
    assert list( pl.check_rewrite( ORIGINAL, SAME_SHAPE, [], threshold=near ) ) == [ "same_shape" ]


def test_an_original_that_does_not_parse_cannot_be_compared_so_only_the_other_checks_apply():
    assert pl.check_rewrite( "not python (", DIFFERENT, [ "values" ] ) == {}


def test_a_script_rewrite_is_checked_through_the_shape_reader_it_is_given():
    shapes = { "orig": { 1, 2, 3 }, "same": { 1, 2, 3 }, "other": { 7, 8, 9 }, "bad": None }
    read   = lambda text: shapes[ text ]
    assert pl.check_rewrite( "orig", "same", [], shape_of=read ) == { "same_shape": 1.0 }
    assert pl.check_rewrite( "orig", "other", [], shape_of=read ) == {}
    assert pl.check_rewrite( "orig", "bad", [], shape_of=read ) == { "unparsable": True }


# ---- plant_rewrite --------------------------------------------------------------------------------------------------

def test_the_first_passing_rewrite_is_kept_and_the_tries_are_counted():
    asked = []
    def ask( system, user ):
        asked.append( user )
        return DIFFERENT
    assert pl.plant_rewrite( ORIGINAL, [ "values" ], ask ) == { "status": "planted", "rewrite": DIFFERENT, "tries": 1 } and len( asked ) == 1


def test_a_failed_try_is_named_in_the_next_prompt_and_a_later_pass_is_kept():
    replies, asked = [ DIFFERENT.replace( "xs", "values" ), DIFFERENT ], []
    def ask( system, user ):
        asked.append( user )
        return replies.pop( 0 )
    out = pl.plant_rewrite( ORIGINAL, [ "values" ], ask )
    assert out == { "status": "planted", "rewrite": DIFFERENT, "tries": 2 } and "still used: values." not in asked[ 0 ] and "still used: values." in asked[ 1 ]


def test_three_failed_tries_give_up_with_every_failure_so_the_next_original_is_drawn():
    out = pl.plant_rewrite( ORIGINAL, [ "values" ], lambda system, user: "def broken( :" )
    assert out == { "status": "failed", "tries": 3, "failures": [ { "unparsable": True } ] * 3 }
    one = pl.plant_rewrite( ORIGINAL, [ "values" ], lambda system, user: "def broken( :", tries=1 )
    assert one[ "tries" ] == 1 and len( one[ "failures" ] ) == 1
