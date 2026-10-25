"""
Unit tests for semdup.proof.label_prep: planting, monolith pairs, packets, answer key.
"""
import asyncio
import json
import pathlib
import subprocess

import pytest

from cosa.repo.doc_lint import model_transport
from cosa.repo.labelling import packets as lb_packets
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup import frozen as fz
from cosa.repo.semdup.proof import label_prep as lp
from cosa.repo.semdup.proof import monolith_pairs as mp
from cosa.repo.semdup.proof import plant
from cosa.repo.symindex import need_input

PY_FIT = "def fit( rows ):\n    total = 0\n    for row in rows:\n        if row > 1:\n            total = total + row * 2\n    return total\n"
SENTENCE = "A function that adds up the given numbers and returns the total."
CFG = { "min_nodes": 25, "clone_cover": 0.5, "body_chars": 10000, "config_sha": "c" * 64, "jscpd": fz.JSCPD }


class FakeEmbed:
    """Embed a text as its word counts over a fixed vocabulary, so unlike texts differ."""

    VOCAB = ( "alpha", "beta", "gamma", "delta", "return", "const", "total", "items" )

    def embed( self, texts, content_type, role ):
        return [ [ float( t.count( w ) ) for w in self.VOCAB ] for t in texts ]

    def info( self ):
        return { "engines": { "code": { "revision": "r1", "model": "m" } } }


def js_function( name, body_words ):
    """Return a script function long enough to be judged, whose body repeats the words given."""
    lines = "\n".join( f"    const {w}{i} = items.map( x => x + {i} ).filter( x => x > {i} );" for i, w in enumerate( body_words ) )
    return f"function {name}( items ) {{\n{lines}\n    return items.length;\n}}\n"


# ---- small helpers ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize( "reply, expected", [
    ( "```python\ndef f():\n    return 1\n```", "def f():\n    return 1" ),
    ( "```\nx = 1\n```", "x = 1" ),
    ( "  def f(): pass  \n", "def f(): pass" ),
] )
def test_unfence_removes_exactly_one_surrounding_fence_and_nothing_else( reply, expected ):
    assert lp.unfence( reply ) == expected


def test_make_ask_passes_the_model_and_both_prompts_and_unfences_the_reply():
    seen = []
    async def complete( model, system, user ):
        seen.append( ( model, system, user ) )
        return "```ts\nfunction a() {}\n```"
    assert lp.make_ask( complete, "m1" )( "sys", "usr" ) == "function a() {}"
    assert seen == [ ( "m1", "sys", "usr" ) ]


def test_script_shape_reads_a_function_a_bare_method_and_returns_none_for_a_non_function():
    func   = lp.script_shape( "function a( x ) { return x + 1; }" )
    method = lp.script_shape( "a( x ) { return x + 1; }" )
    assert func and method and len( func & method ) >= 4          # the same body, a declaration against a member, so they share most windows and not all
    assert lp.script_shape( "const value = 5;" ) is None
    assert lp.script_shape( "function a( x ) { return x + 1; }" ) != lp.script_shape( "function a( x ) { for ( const y of x ) { if ( y ) { while ( y ) { y--; } } } return x; }" )


def test_the_need_for_a_python_definition_comes_from_need_input_and_a_script_one_is_stripped( monkeypatch ):
    got  = need_input.NeedInput( member_id="m.fit", kind="function", text="def NAME(): pass", forbidden=[ "fit" ] )
    monkeypatch.setattr( plant, "python_need", lambda rec, root: got )
    assert lp._need_for( { "lang": "py" }, "/r" ) is got
    rec  = { "lang": "ts", "id": "d-1", "name": "Panel.render", "declared": [ "items" ], "text": "render( items ) { return items; }" }          # a class member: the name is qualified, the source holds the bare name
    need = lp._need_for( rec, "/r" )
    assert ( need.kind, need.member_id, need.forbidden ) == ( "method", "d-1", [ "render", "items" ] ) and need.text == "NAME( ARG1 ) { return ARG1; }"
    nested = lp._need_for( { **rec, "name": "outer.<locals>.inner" }, "/r" )
    assert nested.kind == "function"
    assert lp._need_for( { **rec, "name": "plain" }, "/r" ).kind == "function"


def test_a_script_need_leaves_short_local_names_alone_so_a_sentence_can_use_the_words_a_and_b():
    rec  = { "lang": "ts", "id": "d-1", "name": "pick", "declared": [ "a", "b", "xs", "items" ], "text": "pick( a, b, xs, items ) { return a + b + xs + items; }" }
    need = lp._need_for( rec, "/r" )
    assert need.forbidden == [ "pick", "items" ] and "a" not in need.forbidden and "b" not in need.forbidden and "xs" not in need.forbidden
    assert need.text == "NAME( a, b, xs, ARG1 ) { return a + b + xs + ARG1; }"


def test_a_retry_names_the_own_word_the_last_sentence_used_and_how_long_it_was():
    need  = need_input.NeedInput( member_id="m", kind="function", text="def NAME(): pass", forbidden=[ "fit" ] )
    users = []
    replies = iter( [ "A function that returns the fit of the given rows into a number.", SENTENCE ] )
    def ask( system, user ):
        users.append( user )
        return next( replies )
    assert lp.write_sentence( need, "py", ask )[ 0 ] == SENTENCE
    assert 'the word "fit" is a name in the original code' in users[ 1 ] and "own_identifier" in users[ 1 ]
    assert 'the word "fit"' not in users[ 0 ]


def test_a_retry_after_a_too_short_sentence_says_how_many_words_it_had():
    need  = need_input.NeedInput( member_id="m", kind="function", text="def NAME(): pass", forbidden=[ "fit" ] )
    users = []
    replies = iter( [ "A function that adds numbers.", SENTENCE ] )
    def ask( system, user ):
        users.append( user )
        return next( replies )
    assert lp.write_sentence( need, "py", ask )[ 0 ] == SENTENCE
    assert "Your last sentence had 5 words" in users[ 1 ] and "Say a little more" in users[ 1 ] and "had" not in users[ 0 ]


def test_top_up_saves_after_every_wave_so_a_later_error_loses_nothing( tmp_path, monkeypatch ):
    pools = { "script": [ synthetic( "ts", i ) for i in range( 4 ) ], "python": [] }
    doc   = doc_of( 10, 8, [], [] )
    seen  = []
    def fake_one( rec, root, method, asks, shape_of ):
        if rec[ "id" ] == "d-ts-000": return { "original": rec[ "id" ], "stratum": method, "status": "failed", "failures": [] }
        return { "original": rec[ "id" ], "stratum": method, "status": "planted", "rewrite_text": TS_TEXT, "tries": 1 }
    monkeypatch.setattr( lp, "plant_one", fake_one )
    lp.top_up_alikes( doc, pools, "/r", { "asks": {}, "shape_of": { "py": None, "ts": None } }, tmp_path, count=60, threads=1, save=lambda: seen.append( len( doc[ "planted" ] ) ) )
    assert len( seen ) >= 2 and seen == sorted( seen ) and seen[ 0 ] < seen[ -1 ]


def test_write_sentence_retries_with_the_failure_kinds_and_gives_up_after_three_tries():
    need  = need_input.NeedInput( member_id="m", kind="function", text="def NAME(): pass", forbidden=[ "fit" ] )
    users = []
    replies = iter( [ "Adds things.", SENTENCE ] )
    def ask( system, user ):
        users.append( user )
        return next( replies )
    assert lp.write_sentence( need, "py", ask ) == ( SENTENCE, [ [ "opener", "word_count" ] ] )
    assert "word_count" in users[ 1 ] and "word_count" not in users[ 0 ]
    calls = []
    assert lp.write_sentence( need, "py", lambda s, u: calls.append( u ) or "Adds things." ) == ( None, [ [ "opener", "word_count" ] ] * 3 ) and len( calls ) == 3


# ---- planting ---------------------------------------------------------------------------------------------------

def orig( lang="py", name="fit", text=PY_FIT, i=1 ):
    """Build a definition record the way extract does."""
    return { "id": f"d-{i}", "lang": lang, "name": name, "file": "src/mod.py" if lang == "py" else "src/js/mod.ts", "text": text, "declared": [ "rows", "total", "row" ], "origin": "server" }


def asks_with( rewrite="def g( a ):\n    return a + 1\n", alike="def g( a ):\n    return sum( a )\n", sentence=SENTENCE ):
    """Return the three asks, each a recording function that answers with its own fixed reply."""
    log = { "rewrite": [], "sentence": [], "alike": [] }
    def make( name, reply ):
        return lambda system, user: log[ name ].append( ( system, user ) ) or reply
    return { "rewrite": make( "rewrite", rewrite ), "sentence": make( "sentence", sentence ), "alike": make( "alike", alike ) }, log


def patch_need( monkeypatch ):
    monkeypatch.setattr( plant, "python_need", lambda rec, root: need_input.NeedInput( member_id="m.fit", kind="function", text="def NAME( ARG1 ): pass", forbidden=[ "fit", "rows" ] ) )


def test_a_fable_rewrite_is_planted_when_it_avoids_the_banned_words_and_the_shape( monkeypatch ):
    patch_need( monkeypatch )
    asks, log = asks_with()
    got = lp.plant_one( orig(), "/r", lp.STRATA[ 0 ], asks, plant.python_shape )
    assert got == { "original": "d-1", "stratum": "fable-planted", "status": "planted", "rewrite_text": "def g( a ):\n    return a + 1\n", "tries": 1 }
    assert "rows" in log[ "rewrite" ][ 0 ][ 1 ] and PY_FIT in log[ "rewrite" ][ 0 ][ 1 ] and not log[ "sentence" ] and not log[ "alike" ]


def test_a_fable_rewrite_that_keeps_a_banned_word_fails_after_three_tries_with_the_failure_kinds( monkeypatch ):
    patch_need( monkeypatch )
    asks, log = asks_with( rewrite="def g( rows ):\n    return rows\n" )
    got = lp.plant_one( orig(), "/r", lp.STRATA[ 0 ], asks, plant.python_shape )
    assert got[ "status" ] == "failed" and len( log[ "rewrite" ] ) == 3 and all( "banned_word" in f for f in got[ "failures" ] )


def test_a_script_original_has_no_python_forbidden_names_but_its_own_declared_names_are_banned():
    asks, log = asks_with( rewrite="function g( a ) { return a + 1; }" )
    rec = orig( "ts", "fit", "function fit( rows ) { let total = 0; for ( const row of rows ) { total += row * 2; } return total; }" )
    got = lp.plant_one( rec, "/r", lp.STRATA[ 0 ], asks, lp.script_shape )
    assert got[ "status" ] == "planted" and "rows" in log[ "rewrite" ][ 0 ][ 1 ]


def test_an_opus_work_alike_is_written_from_the_sentence_alone_and_never_sees_the_original( monkeypatch ):
    patch_need( monkeypatch )
    asks, log = asks_with()
    got = lp.plant_one( orig(), "/r", lp.STRATA[ 1 ], asks, plant.python_shape )
    assert got == { "original": "d-1", "stratum": "opus-work-alike", "status": "planted", "rewrite_text": "def g( a ):\n    return sum( a )\n", "tries": 1, "sentence": SENTENCE }
    sent = " ".join( log[ "alike" ][ 0 ] )
    assert SENTENCE in sent and "Python" in sent and "rows" not in sent and "for row in" not in sent and PY_FIT not in sent


def test_a_work_alike_fails_when_no_sentence_passes_or_the_reply_is_unparsable_or_has_the_original_shape( monkeypatch ):
    patch_need( monkeypatch )
    asks, _ = asks_with( sentence="Adds." )
    assert lp.plant_one( orig(), "/r", lp.STRATA[ 1 ], asks, plant.python_shape ) == {
        "original": "d-1", "stratum": "opus-work-alike", "status": "failed", "failures": [ { "sentence": [ [ "opener", "word_count" ] ] * 3 } ] }
    asks, _ = asks_with( alike="def g( :\n" )
    assert lp.plant_one( orig(), "/r", lp.STRATA[ 1 ], asks, plant.python_shape )[ "failures" ] == [ { "unparsable": True } ]
    asks, _ = asks_with( alike=PY_FIT.replace( "fit", "other" ) )
    assert "same_shape" in lp.plant_one( orig(), "/r", lp.STRATA[ 1 ], asks, plant.python_shape )[ "failures" ][ 0 ]


def test_an_original_whose_need_cannot_be_resolved_is_a_named_failure_and_not_a_crash( monkeypatch ):
    def unresolved( rec, root ): raise ValueError( "outer.<locals>.inner not found" )
    monkeypatch.setattr( plant, "python_need", unresolved )
    asks, log = asks_with()
    got = lp.plant_one( orig(), "/r", lp.STRATA[ 0 ], asks, plant.python_shape )
    assert got == { "original": "d-1", "stratum": "fable-planted", "status": "failed", "failures": [ { "need": "outer.<locals>.inner not found" } ] }
    assert not log[ "rewrite" ]


def test_plant_all_makes_every_third_original_a_work_alike_and_tries_replacements_for_failures( monkeypatch ):
    patch_need( monkeypatch )
    tried = []
    def fake_one( rec, root, method, asks, shape_of ):
        tried.append( ( rec[ "id" ], method ) )
        ok = rec[ "id" ] not in ( "d-2", "d-3" )
        return { "original": rec[ "id" ], "stratum": method, "status": "planted" if ok else "failed" }
    monkeypatch.setattr( lp, "plant_one", fake_one )
    got = lp.plant_all( [ orig( i=i ) for i in range( 8 ) ], "/r", {}, None, count=4, threads=2 )
    assert [ p[ "original" ] for p in got[ "planted" ] ] == [ "d-0", "d-1", "d-4", "d-5" ] and [ f[ "original" ] for f in got[ "failed" ] ] == [ "d-2", "d-3" ]
    assert tried == [ ( "d-0", "opus-work-alike" ), ( "d-1", "fable-planted" ), ( "d-2", "fable-planted" ), ( "d-3", "opus-work-alike" ),
                      ( "d-4", "fable-planted" ), ( "d-5", "fable-planted" ) ] or sorted( tried ) == sorted( [ ( "d-0", "opus-work-alike" ), ( "d-1", "fable-planted" ), ( "d-2", "fable-planted" ),
                      ( "d-3", "opus-work-alike" ), ( "d-4", "fable-planted" ), ( "d-5", "fable-planted" ) ] )
    short = lp.plant_all( [ orig( i=i ) for i in range( 2 ) ], "/r", {}, None, count=9, threads=2 )
    assert len( short[ "planted" ] ) == 2 and short[ "failed" ] == []


# ---- the monolith -----------------------------------------------------------------------------------------------

def monolith_root( tmp_path, monkeypatch, text ):
    """Write a monolith file under a temporary root and pin the module to its blob sha."""
    path = tmp_path / lp.MONOLITH_FILE
    path.parent.mkdir( parents=True )
    path.write_text( text, encoding="utf-8" )
    monkeypatch.setattr( lp, "MONOLITH_BLOB", mp.blob_sha( path ) )
    return tmp_path


MONOLITH_TEXT = js_function( "first", [ "alpha", "beta", "gamma" ] ) + js_function( "second", [ "alpha", "beta", "gamma" ] ) + js_function( "third", [ "delta", "items", "total" ] ) + "function tiny() { return 1; }\n"


def test_the_monolith_is_read_from_a_copy_of_the_pinned_bytes_and_small_definitions_are_left_out( tmp_path, monkeypatch ):
    root = monolith_root( tmp_path, monkeypatch, MONOLITH_TEXT )
    tmp, defs = lp.monolith_definitions( root, 25 )
    with tmp:
        assert sorted( d[ "name" ] for d in defs ) == [ "first", "second", "third" ]
        assert all( d[ "file" ] == lp.MONOLITH_FILE and d[ "origin" ] == "server" for d in defs )
        assert pathlib.Path( tmp.name, lp.MONOLITH_FILE ).read_text( encoding="utf-8" ) == MONOLITH_TEXT
    in_repo = { d[ "id" ] for d in ex.extract_tree( root, [ root / lp.MONOLITH_FILE ], "server" )[ "definitions" ] if d[ "nodes" ] >= 25 }
    assert { d[ "id" ] for d in defs } == in_repo


def test_a_monolith_that_is_not_the_pinned_blob_is_refused( tmp_path, monkeypatch ):
    root = monolith_root( tmp_path, monkeypatch, MONOLITH_TEXT )
    ( root / lp.MONOLITH_FILE ).write_text( MONOLITH_TEXT + "// edited\n", encoding="utf-8" )
    with pytest.raises( ValueError, match="pinned" ): lp.monolith_definitions( root, 25 )


def test_monolith_candidates_tags_the_jscpd_clone_structural_and_the_closest_unlinked_pair_neighbour( tmp_path, monkeypatch ):
    root = monolith_root( tmp_path, monkeypatch, MONOLITH_TEXT )
    got  = lp.monolith_candidates( root, CFG, FakeEmbed(), tmp_path / "vec", per_source=1 )
    names = { d[ "id" ]: d[ "name" ] for d in got[ "defs" ] }
    seen  = [ ( sorted( names[ i ] for i in p[ "ids" ] ), p[ "source" ] ) for p in got[ "pairs" ] ]
    assert seen[ 0 ] == ( [ "first", "second" ], "structural" ) and seen[ 1 ][ 1 ] == "neighbour" and len( seen ) == 2
    assert got[ "blob" ] == lp.MONOLITH_BLOB
    nominated = lp.monolith_candidates( root, CFG, FakeEmbed(), tmp_path / "vec", per_source=1, nominated=[ [ sorted( names, key=names.get )[ 0 ], sorted( names, key=names.get )[ 2 ] ] ] )
    assert [ p[ "source" ] for p in nominated[ "pairs" ] ][ -1 ] == "nominated"


# ---- items, packets and the key ---------------------------------------------------------------------------------

def rec( i, text ):
    return { "id": f"d-{i}", "text": text }


def test_a_pair_item_holds_only_the_two_texts_and_a_key_row_says_which_id_is_a():
    made = lp.pair_item( rec( 1, "first text" ), rec( 2, "second text" ), 7 )
    assert made[ "item" ][ "type" ] == "semdup_pair" and set( made[ "item" ][ "payload" ] ) == { "a", "b" }
    ids = { "first text": "d-1", "second text": "d-2" }
    assert made[ "row" ] == { "a": ids[ made[ "item" ][ "payload" ][ "a" ] ], "b": ids[ made[ "item" ][ "payload" ][ "b" ] ] }
    assert made[ "item" ][ "item_id" ].startswith( "pair-" ) and "d-1" not in made[ "item" ][ "item_id" ]
    swapped = lp.pair_item( rec( 2, "second text" ), rec( 1, "first text" ), 7 )
    assert swapped == made
    orders = { lp.pair_item( rec( 1, "first text" ), rec( 2, "second text" ), s )[ "item" ][ "payload" ][ "a" ] for s in range( 12 ) }
    assert orders == { "first text", "second text" }


def test_an_item_id_is_the_same_for_either_order_and_differs_between_pairs():
    assert lp.item_id( "d-1", "d-2" ) == lp.item_id( "d-2", "d-1" ) != lp.item_id( "d-1", "d-3" )
    assert lp.unordered_key( "d-2", "d-1" ) == "d-1|d-2"


def test_a_rewrite_record_is_a_new_origin_definition_with_a_stable_id( tmp_path ):
    made = lp.rewrite_record( { "rewrite_text": "def g( a ):\n    return a + 1" }, orig(), tmp_path, 3 )
    assert ( made[ "origin" ], made[ "file" ], made[ "name" ], made[ "lang" ] ) == ( "new", "src/mod.py", "g", "py" )
    again = lp.rewrite_record( { "rewrite_text": "def g( a ):\n    return a + 1" }, orig(), tmp_path / "other", 3 )
    assert again[ "id" ] == made[ "id" ]
    script = lp.rewrite_record( { "rewrite_text": "function g( a ) { return a + 1; }" }, orig( "ts" ), tmp_path, 4 )
    assert ( script[ "file" ], script[ "lang" ], script[ "name" ] ) == ( "src/js/mod.ts", "ts", "g" )
    with pytest.raises( ValueError, match="no definition" ): lp.rewrite_record( { "rewrite_text": "# nothing here" }, orig(), tmp_path, 5 )
    with pytest.raises( ValueError, match="no definition" ): lp.rewrite_record( { "rewrite_text": "const value = 5;" }, orig( "ts" ), tmp_path, 7 )


def test_a_relative_folder_gives_the_same_record_as_an_absolute_one( tmp_path, monkeypatch ):
    monkeypatch.chdir( tmp_path )
    result = { "rewrite_text": "def g( a ):\n    return a + 1" }
    assert lp.rewrite_record( result, orig(), "rel/out", 1 ) == lp.rewrite_record( result, orig(), tmp_path / "abs", 1 )


def test_a_class_member_rewrite_is_read_inside_a_class_and_loses_the_class_name_and_carries_the_originals_path( tmp_path ):
    member = { "rewrite_text": "public unmount(): void {\n    this.open = false;\n}" }
    made   = lp.rewrite_record( member, orig( "ts" ), tmp_path, 6 )
    assert ( made[ "name" ], made[ "file" ], made[ "origin" ] ) == ( "unmount", "src/js/mod.ts", "new" )
    assert made[ "id" ] == ex.definition_id( "new", "src/js/mod.ts", "unmount", made[ "text" ] ) and "PlantedWrapper" not in json.dumps( made )
    assert "planted" not in json.dumps( made )


def test_a_rewrite_that_cannot_be_extracted_is_a_named_failure_so_the_next_original_takes_its_place( monkeypatch ):
    patch_need( monkeypatch )
    shape = lambda text: { 1, 2, 3 } if "def " in text else { 7, 8, 9 }
    for method, kwargs in ( ( lp.STRATA[ 0 ], { "rewrite": "x = 1\n" } ), ( lp.STRATA[ 1 ], { "alike": "x = 1\n" } ) ):
        asks, _ = asks_with( **kwargs )
        got = lp.plant_one( orig(), "/r", method, asks, shape )
        assert got[ "status" ] == "failed" and got[ "stratum" ] == method and "no definition could be extracted" in got[ "failures" ][ 0 ][ "extract" ]


def planted_pair( i, stratum="fable-planted" ):
    o = rec( f"o{i}", f"original text {i}" )
    return { "original": o, "rewrite": rec( f"r{i}", f"rewrite text {i}" ), "stratum": stratum }


def test_prepare_writes_one_blind_packet_per_reviewer_and_the_key_apart_and_only_once( tmp_path ):
    mono = { "defs": [ rec( "m1", "mono one" ), rec( "m2", "mono two" ) ], "pairs": [ { "ids": [ "d-m1", "d-m2" ], "source": "structural" } ], "blob": "b" * 40 }
    got  = lp.prepare( [ planted_pair( 1 ), planted_pair( 2, "opus-work-alike" ) ], mono, [ "rick", "reviewer-2" ], 5, tmp_path, "c" * 64 )
    assert got[ "items" ] == 3 and set( got[ "packets" ] ) == { "rick", "reviewer-2" }
    key = json.loads( pathlib.Path( got[ "key" ] ).read_text( encoding="utf-8" ) )
    assert key[ "config_sha" ] == "c" * 64 and key[ "monolith_blob" ] == "b" * 40 and len( key[ "items" ] ) == 3
    assert sorted( r[ "stratum" ] for r in key[ "items" ].values() ) == [ "fable-planted", "monolith:structural", "opus-work-alike" ]
    assert sorted( r[ "kind" ] for r in key[ "items" ].values() ) == [ "monolith", "planted", "planted" ]
    assert not pathlib.Path( got[ "key" ] ).is_relative_to( tmp_path / "packets" )
    lines = [ json.loads( l ) for l in pathlib.Path( got[ "packets" ][ "rick" ] ).read_text( encoding="utf-8" ).splitlines() ]
    assert sorted( l[ "item_id" ] for l in lines ) == sorted( key[ "items" ] ) and all( set( l ) == { "item_id", "type", "payload" } and set( l[ "payload" ] ) == { "a", "b" } for l in lines )
    assert not any( word in json.dumps( lines ) for word in ( "d-", "fable", "opus", "monolith:", "structural", "o1", "r1" ) )
    other = [ json.loads( l )[ "item_id" ] for l in pathlib.Path( got[ "packets" ][ "reviewer-2" ] ).read_text( encoding="utf-8" ).splitlines() ]
    assert other != [ l[ "item_id" ] for l in lines ] and sorted( other ) == sorted( key[ "items" ] )
    before = pathlib.Path( got[ "packets" ][ "rick" ] ).read_bytes()
    with pytest.raises( FileExistsError, match="already exists" ): lp.prepare( [ planted_pair( 1 ) ], mono, [ "rick", "reviewer-2" ], 5, tmp_path, "c" * 64 )
    assert pathlib.Path( got[ "packets" ][ "rick" ] ).read_bytes() == before


def test_a_packet_prepared_here_is_read_back_by_the_packet_tools_blind_form( tmp_path ):
    mono = { "defs": [ rec( "m1", "mono one" ), rec( "m2", "mono two" ) ], "pairs": [ { "ids": [ "d-m1", "d-m2" ], "source": "neighbour" } ], "blob": "b" * 40 }
    got  = lp.prepare( [ planted_pair( 1 ) ], mono, [ "rick", "reviewer-2" ], 5, tmp_path, "c" * 64 )
    for line in pathlib.Path( got[ "packets" ][ "rick" ] ).read_text( encoding="utf-8" ).splitlines(): assert lb_packets.blind_form( json.loads( line ) ) == json.loads( line )


# ---- pools and the whole run ------------------------------------------------------------------------------------

def synthetic( lang, i ):
    """Return a definition record big enough to be drawn, with a body of its own."""
    ext  = "py" if lang == "py" else "ts"
    text = f"def fn_{i}( v ):\n    return v\n" if lang == "py" else f"function fn_{i}( v ) {{ return v; }}\n"
    return { "id": f"d-{lang}-{i:03d}", "origin": "server", "lang": lang, "file": f"src/{ext}/m{i}.{ext}", "name": f"fn_{i}", "sig": f"fn_{i}( v )", "text": text,
             "declared": [ "v" ], "nodes": 40 }


def test_select_pools_draws_sixty_percent_script_leaves_out_scrub_token_definitions_and_is_the_same_whatever_the_order():
    server = [ synthetic( "py", i ) for i in range( 100 ) ]
    client = [ synthetic( "ts", i ) for i in range( 100 ) ]
    client.append( { **synthetic( "ts", 500 ), "text": "function check_exists() { return 1; }" } )
    client.append( { **synthetic( "ts", 501 ), "name": "outer.<locals>.inner" } )
    got  = lp.select_pools( server, client, CFG, 11, 60 )
    assert ( len( got[ "script" ] ), len( got[ "python" ] ) ) == ( 72, 48 )
    assert not { "d-ts-500", "d-ts-501" } & { d[ "id" ] for d in got[ "script" ] }
    assert lp.select_pools( list( reversed( server ) ), list( reversed( client ) ), CFG, 11, 60 ) == got


def test_the_whole_run_plants_sixty_pairs_sixty_forty_one_third_work_alikes_and_writes_packets_and_key( tmp_path, monkeypatch ):
    root = monolith_root( tmp_path / "repo", monkeypatch, MONOLITH_TEXT )
    monkeypatch.setattr( plant, "python_need", lambda r, rt: need_input.NeedInput( member_id="m", kind="function", text="def NAME(): pass", forbidden=[ "fn", "zzz" ] ) )
    py_reply = "def g( a ):\n    for b in a:\n        if b:\n            a = a + [ b ]\n    return a\n"
    ts_reply = "function g( a ) { for ( const b of a ) { if ( b ) { a.push( b ); } } return a; }"
    def rewrite( system, user ): return py_reply if "def " in user else ts_reply
    def alike( system, user ): return py_reply if "Python" in user else ts_reply
    wiring = { "server_defs": [ synthetic( "py", i ) for i in range( 100 ) ], "client_defs": [ synthetic( "ts", i ) for i in range( 100 ) ],
               "asks": { "rewrite": rewrite, "sentence": lambda s, u: SENTENCE, "alike": alike },
               "shape_of": { "py": lambda text: {1, 2, 3} if "fn_" in text else {7, 8, 9}, "ts": lambda text: {1, 2, 3} if "fn_" in text else {7, 8, 9} },
               "client": FakeEmbed(), "cache_dir": tmp_path / "vec" }
    out = lp.run( tmp_path / "repo", tmp_path / "out", CFG, wiring, seed=3 )
    assert out[ "planted" ] == { "fable-planted": 40, "opus-work-alike": 20 } and out[ "failed" ] == 0 and out[ "items" ] == 60 + sum( out[ "monolith" ].values() )
    assert set( out[ "monolith" ] ) == { "structural", "neighbour", "nominated" } and out[ "monolith" ][ "nominated" ] == 0
    key  = json.loads( pathlib.Path( out[ "key" ] ).read_text( encoding="utf-8" ) )
    kinds = [ r[ "kind" ] for r in key[ "items" ].values() ]
    assert kinds.count( "planted" ) == 60 and len( key[ "items" ] ) == out[ "items" ]
    planted = [ r for r in key[ "items" ].values() if r[ "kind" ] == "planted" ]
    assert sum( 1 for r in planted if r[ "a" ].startswith( "d-ts" ) or r[ "b" ].startswith( "d-ts" ) ) == 36 and sum( 1 for r in planted if r[ "a" ].startswith( "d-py" ) or r[ "b" ].startswith( "d-py" ) ) == 24
    assert (tmp_path / "out" / "key" / "rewrites" / "000" / "src" / "ts" / "m0.ts").is_file() or any( (tmp_path / "out" / "key" / "rewrites").rglob( "*.ts" ) )


def test_a_failure_after_planting_costs_no_model_call_on_the_next_run( tmp_path, monkeypatch ):
    root = monolith_root( tmp_path / "repo", monkeypatch, MONOLITH_TEXT )
    monkeypatch.setattr( plant, "python_need", lambda r, rt: need_input.NeedInput( member_id="m", kind="function", text="def NAME(): pass", forbidden=[ "fn" ] ) )
    py_reply = "def g( a ):\n    for b in a:\n        if b:\n            a = a + [ b ]\n    return a\n"
    ts_reply = "function g( a ) { for ( const b of a ) { if ( b ) { a.push( b ); } } return a; }"
    calls    = []
    def ask( reply ): return lambda system, user: calls.append( 1 ) or ( reply if "Python" in user or "def " in user else ts_reply )
    class Broken:
        def info( self ): raise RuntimeError( "embeddings info: no API key found" )
    wiring = { "server_defs": [ synthetic( "py", i ) for i in range( 100 ) ], "client_defs": [ synthetic( "ts", i ) for i in range( 100 ) ],
               "asks": { "rewrite": ask( py_reply ), "sentence": lambda s, u: calls.append( 1 ) or SENTENCE, "alike": ask( py_reply ) },
               "shape_of": { "py": lambda text: {1, 2, 3} if "fn_" in text else {7, 8, 9}, "ts": lambda text: {1, 2, 3} if "fn_" in text else {7, 8, 9} },
               "client": Broken(), "cache_dir": tmp_path / "vec" }
    with pytest.raises( RuntimeError, match="no API key" ): lp.run( tmp_path / "repo", tmp_path / "out", CFG, wiring, seed=3 )
    used = len( calls )
    assert used >= 60 and ( tmp_path / "out" / "key" / lp.PLANTED_FILE ).is_file() and not ( tmp_path / "out" / "key" / lp.KEY_FILE ).exists()
    out = lp.run( tmp_path / "repo", tmp_path / "out", CFG, { **wiring, "client": FakeEmbed() }, seed=3 )
    assert len( calls ) == used and out[ "planted" ] == { "fable-planted": 40, "opus-work-alike": 20 } and out[ "failed" ] == 0


PY_TEXT = "def g( a ):\n    for b in a:\n        if b:\n            a = a + [ b ]\n    return a\n"
TS_TEXT = "function g( a ) { for ( const b of a ) { if ( b ) { a.push( b ); } } return a; }"


def doc_of( have_ts, have_py, failed_ts, failed_py ):
    """Build a planted document with some work-alikes and some failed originals."""
    planted = [ { "original": synthetic( "ts", 900 + i ), "rewrite": {}, "stratum": "opus-work-alike" } for i in range( have_ts ) ]
    planted += [ { "original": synthetic( "py", 900 + i ), "rewrite": {}, "stratum": "opus-work-alike" } for i in range( have_py ) ]
    planted += [ { "original": synthetic( "ts", 800 ), "rewrite": {}, "stratum": "fable-planted" } ]
    failed = [ { "original": f"d-ts-{i:03d}", "stratum": "opus-work-alike", "status": "failed", "failures": [] } for i in failed_ts ]
    failed += [ { "original": f"d-py-{i:03d}", "stratum": "opus-work-alike", "status": "failed", "failures": [] } for i in failed_py ]
    return { "planted": planted, "failed": failed }


def test_top_up_retries_failed_work_alikes_first_then_fresh_originals_until_each_share_is_full( tmp_path, monkeypatch ):
    pools = { "script": [ synthetic( "ts", i ) for i in range( 8 ) ], "python": [ synthetic( "py", i ) for i in range( 8 ) ] }
    doc   = doc_of( 10, 5, [ 0, 1 ], [ 0, 1, 2 ] )
    asked = []
    def fake_one( rec, root, method, asks, shape_of ):
        asked.append( rec[ "id" ] )
        if rec[ "id" ] in ( "d-ts-000", "d-py-001" ): return { "original": rec[ "id" ], "stratum": method, "status": "failed", "failures": [ { "again": True } ] }
        return { "original": rec[ "id" ], "stratum": method, "status": "planted", "rewrite_text": TS_TEXT if rec[ "lang" ] != "py" else PY_TEXT, "tries": 1 }
    monkeypatch.setattr( lp, "plant_one", fake_one )
    wiring = { "asks": {}, "shape_of": { "py": None, "ts": None } }
    added  = lp.top_up_alikes( doc, pools, "/r", wiring, tmp_path, count=60, threads=1 )
    assert added == 5 and asked == [ "d-ts-000", "d-ts-001", "d-ts-002", "d-py-000", "d-py-001", "d-py-002", "d-py-003" ]     # failed ones first, a second failure is not tried a third time
    opus = lambda lang: sum( 1 for p in doc[ "planted" ] if p[ "stratum" ] == "opus-work-alike" and ( p[ "original" ][ "lang" ] == "py" ) == ( lang == "py" ) )
    assert ( opus( "ts" ), opus( "py" ) ) == ( 12, 8 )
    assert doc[ "planted" ][ -1 ][ "rewrite" ][ "origin" ] == "new" and (tmp_path / f"{len( doc[ 'planted' ] ) - 1:03d}").is_dir()
    assert sum( 1 for f in doc[ "failed" ] if f.get( "failures" ) == [ { "again": True } ] ) >= 2


def test_top_up_stops_after_its_waves_when_a_group_cannot_be_filled_and_does_nothing_when_it_is_full( tmp_path, monkeypatch ):
    pools = { "script": [ synthetic( "ts", i ) for i in range( 3 ) ], "python": [] }
    monkeypatch.setattr( lp, "plant_one", lambda rec, root, method, asks, shape_of: { "original": rec[ "id" ], "stratum": method, "status": "failed", "failures": [] } )
    doc   = doc_of( 10, 8, [], [] )
    assert lp.top_up_alikes( doc, pools, "/r", { "asks": {}, "shape_of": { "py": None, "ts": None } }, tmp_path, count=60, threads=1, waves=2 ) == 0
    assert len( doc[ "failed" ] ) == 4                      # two places open: two fresh originals, then each of those once more, and no third try
    full = doc_of( 12, 8, [], [] )
    assert lp.top_up_alikes( full, pools, "/r", { "asks": {}, "shape_of": { "py": None, "ts": None } }, tmp_path, count=60 ) == 0 and full[ "failed" ] == []


def test_the_planted_document_is_replaced_whole_and_leaves_no_temporary_file( tmp_path ):
    path = tmp_path / "key" / "planted.json"
    lp.save_doc( path, { "planted": [], "failed": [ 1 ] } )
    lp.save_doc( path, { "planted": [ 1 ], "failed": [] } )
    assert json.loads( path.read_text( encoding="utf-8" ) ) == { "planted": [ 1 ], "failed": [] } and sorted( p.name for p in path.parent.iterdir() ) == [ "planted.json" ]


def test_a_resumed_run_tops_up_the_work_alikes_saves_the_document_and_then_asks_the_models_nothing( tmp_path, monkeypatch ):
    root = monolith_root( tmp_path / "repo", monkeypatch, MONOLITH_TEXT )
    monkeypatch.setattr( plant, "python_need", lambda r, rt: need_input.NeedInput( member_id="m", kind="function", text="def NAME(): pass", forbidden=[ "fn" ] ) )
    state = { "sentence": "Adds.", "calls": 0 }
    def sentence( system, user ):
        state[ "calls" ] += 1
        return state[ "sentence" ]
    def rewrite( system, user ):
        state[ "calls" ] += 1
        return PY_TEXT if "def " in user else TS_TEXT
    def alike( system, user ):
        state[ "calls" ] += 1
        return PY_TEXT if "Python" in user else TS_TEXT
    wiring = { "server_defs": [ synthetic( "py", i ) for i in range( 100 ) ], "client_defs": [ synthetic( "ts", i ) for i in range( 100 ) ],
               "asks": { "rewrite": rewrite, "sentence": sentence, "alike": alike },
               "shape_of": { "py": lambda text: {1, 2, 3} if "fn_" in text else {7, 8, 9}, "ts": lambda text: {1, 2, 3} if "fn_" in text else {7, 8, 9} },
               "client": FakeEmbed(), "cache_dir": tmp_path / "vec" }
    class Broken:
        def info( self ): raise RuntimeError( "no key" )
    real_top_up = lp.top_up_alikes
    monkeypatch.setattr( lp, "top_up_alikes", lambda *a, **k: 0 )                  # the first run stops before any top-up, as a crash would
    with pytest.raises( RuntimeError, match="no key" ): lp.run( tmp_path / "repo", tmp_path / "out", CFG, { **wiring, "client": Broken() }, seed=3 )
    monkeypatch.setattr( lp, "top_up_alikes", real_top_up )
    saved = tmp_path / "out" / "key" / lp.PLANTED_FILE
    first = json.loads( saved.read_text( encoding="utf-8" ) )
    assert not any( p[ "stratum" ] == "opus-work-alike" for p in first[ "planted" ] ) and len( first[ "failed" ] ) > 0
    state[ "sentence" ] = SENTENCE
    out  = lp.run( tmp_path / "repo", tmp_path / "out", CFG, wiring, seed=3 )
    assert out[ "planted" ][ "opus-work-alike" ] == 20 and out[ "planted" ][ "fable-planted" ] == len( first[ "planted" ] )
    assert json.loads( saved.read_text( encoding="utf-8" ) )[ "planted" ][ :len( first[ "planted" ] ) ] == first[ "planted" ]
    used = state[ "calls" ]
    again = tmp_path / "out2"
    ( again / "key" ).mkdir( parents=True )
    ( again / "key" / lp.PLANTED_FILE ).write_text( saved.read_text( encoding="utf-8" ), encoding="utf-8" )
    lp.run( tmp_path / "repo", again, CFG, wiring, seed=3 )
    assert state[ "calls" ] == used


# ---- the wiring and the command ---------------------------------------------------------------------------------

def test_live_wiring_extracts_the_server_and_client_trees_without_the_monolith_and_builds_three_asks( tmp_path, monkeypatch ):
    py = tmp_path / "mod.py"
    py.write_text( PY_FIT, encoding="utf-8" )
    js = tmp_path / "src/lupin_app/static/js/a.ts"
    js.parent.mkdir( parents=True )
    js.write_text( "function a( x ) { return x; }\n", encoding="utf-8" )
    ( js.parent / "notifications.js" ).write_text( "function m() { return 1; }\n", encoding="utf-8" )
    ( js.parent / "a.d.ts" ).write_text( "declare function d(): void;\n", encoding="utf-8" )
    monkeypatch.setattr( lp.sp, "all_files", lambda spec: [ py, tmp_path / "skip.txt" ] )
    listing = "\n".join( [ "src/lupin_app/static/js/a.ts", "src/lupin_app/static/js/notifications.js", "src/lupin_app/static/js/a.d.ts", "src/lupin_app/static/js/readme.md" ] )
    real    = subprocess.run
    monkeypatch.setattr( lp.subprocess, "run", lambda cmd, *a, **k: subprocess.CompletedProcess( cmd, 0, stdout=listing, stderr="" ) if cmd[ :2 ] == [ "git", "ls-files" ] else real( cmd, *a, **k ) )
    models = []
    async def complete( model, system, user ):
        models.append( model )
        return "ok"
    client = FakeEmbed()
    got = lp.live_wiring( tmp_path, tmp_path / "vec", complete=complete, client=client )
    assert [ d[ "name" ] for d in got[ "server_defs" ] ] == [ "fit" ] and [ d[ "name" ] for d in got[ "client_defs" ] ] == [ "a" ]
    assert got[ "client" ] is client and got[ "cache_dir" ] == tmp_path / "vec" and got[ "shape_of" ] == { "py": plant.python_shape, "ts": lp.script_shape }
    for name in ( "rewrite", "sentence", "alike" ): got[ "asks" ][ name ]( "s", "u" )
    assert models == [ "claude-fable-5-1", "claude-sonnet-5-5", "claude-opus-5-5" ]
    default = lp.live_wiring( tmp_path, tmp_path / "vec", complete=complete )
    assert type( default[ "client" ] ).__name__ == "EndpointClient"


def test_main_checks_the_frozen_file_configures_the_binary_runs_and_prints_the_result( tmp_path, monkeypatch, capsys ):
    configured, ran = [], []
    monkeypatch.setattr( model_transport, "configure", lambda path=None: configured.append( path ) )
    monkeypatch.setattr( lp, "run", lambda root, out, cfg, wiring: ran.append( ( root, out, cfg[ "config_sha" ], wiring ) ) or { "items": 1 } )
    assert lp.main( [ "--out", str( tmp_path / "o" ), "--claude-cli-path", "/bin/claude" ], make_wiring=lambda root, cache: ( root, str( cache ) ) ) == 0
    assert configured == [ "/bin/claude" ] and json.loads( capsys.readouterr().out ) == { "items": 1 }
    assert ran[ 0 ][ 2 ] == fz.live_config()[ "config_sha" ] and ran[ 0 ][ 3 ][ 1 ] == str( tmp_path / "o" / "vectors" )
    lp.main( [ "--out", str( tmp_path / "o2" ) ], make_wiring=lambda root, cache: None )
    assert configured[ -1 ] is None


def test_main_refuses_to_run_when_the_frozen_file_is_not_the_live_configuration( tmp_path, monkeypatch ):
    drifted = json.loads( pathlib.Path( fz.frozen_path() ).read_text( encoding="utf-8" ) )
    drifted[ "body_chars" ] = 1
    path = tmp_path / "frozen.json"
    path.write_text( json.dumps( drifted ), encoding="utf-8" )
    monkeypatch.setattr( fz, "frozen_path", lambda: str( path ) )
    monkeypatch.setattr( model_transport, "configure", lambda path=None: None )
    with pytest.raises( err.SemdupError ) as caught: lp.main( [ "--out", str( tmp_path / "o" ) ], make_wiring=lambda root, cache: None )
    assert caught.value.code == err.CONFIG_DRIFT
