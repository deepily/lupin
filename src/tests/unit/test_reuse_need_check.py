"""
The mechanical check of the 100 need sentences for the end-to-end run.

Plan: src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.07-jev-reuse-sweep-packed-request-plan.md
section 12.2, the third numbered point. Nothing here reaches Jev. The shipped sample and manifest live outside git, so the
two tests that read them skip with a stated reason when the files are absent.
"""
import json
import pathlib

import pytest

from lupin_mcp import reuse_need_check as nc
from lupin_mcp import reuse_tools as rt

A = "cosa.alpha.mod_a.Parser.read_items"
B = "cosa.beta.mod_b.Loader.fetch_rows"
C = "cosa.gamma.mod_c.Reader.scan_lines"
D = "cosa.delta.mod_d.solo.lonely_helper"

INDEX = {
    A: { "id": A, "sig": "( self, source_url, limit=5 )", "doc": "Parse a feed from a web address.", "file": "src/cosa/alpha/mod_a.py" },
    B: { "id": B, "sig": "( self, table_name )",          "doc": "Pull each record out of the store.",      "file": "src/cosa/beta/mod_b.py" },
    C: { "id": C, "sig": "( self, *chunks, **extras )",   "doc": "Scan text one line at a time.",    "file": "src/cosa/gamma/mod_c.py" },
    D: { "id": D, "sig": "( x )",                          "doc": "Help with something small.",       "file": "src/cosa/delta/mod_d.py" },
}

GOOD = "A function that reads an online news bulletin and returns the list of articles it holds."


def member( i ): return { "id": i, "file": INDEX[ i ][ "file" ], "in_index": True, "sendable": True }


# A and B are an exact pair, B and C a near pair: A and C are linked only through B.
MANIFEST = {
    "exact": [ { "cluster": 0, "kind": "exact", "members": [ member( A ), member( B ) ] } ],
    "near":  [ { "kind": "near", "jaccard": 0.9, "members": [ member( B ), member( C ) ] } ],
}


def failed_names( rows, i ): return [ f[ "check" ] for f in next( r for r in rows if r[ "member" ] == i )[ "failures" ] ]


# ---- groups ----

def test_a_member_linked_to_another_only_through_a_third_is_still_a_twin():
    groups = nc.twin_groups( MANIFEST )
    assert groups[ A ] == [ B, C ]
    assert groups[ C ] == [ A, B ]
    assert groups[ B ] == [ A, C ]
    assert D not in groups


def test_two_separate_groups_do_not_merge():
    other = { "exact": [ { "members": [ member( D ), member( D ) ] } ], "near": [] }
    groups = nc.twin_groups( { "exact": MANIFEST[ "exact" ] + other[ "exact" ], "near": [] } )
    assert groups[ A ] == [ B ]
    assert groups[ D ] == []


# ---- identifier tokens ----

def test_identifier_tokens_hold_id_parts_file_stem_arguments_and_their_subparts():
    t = nc.identifier_tokens( INDEX[ A ] )
    assert { "cosa", "alpha", "mod_a", "parser", "read_items", "source_url", "limit", "self" } <= t
    assert { "items", "read", "source" } <= t                      # snake_case parts of 4 or more characters
    assert "url" not in t and "mod" not in t                      # 3 characters: below the floor


def test_camel_case_parts_and_star_arguments_count():
    t = nc.identifier_tokens( { "id": "p.CamelCaseThing.run", "sig": "( *chunks, **extras, key )", "doc": "", "file": "p/x.py" } )
    assert { "camel", "case", "thing", "chunks", "extras", "key" } <= t


def test_a_signature_that_does_not_parse_still_yields_its_words():
    t = nc.identifier_tokens( { "id": "p.f", "sig": "( a: , broken", "doc": "", "file": "p/x.py" } )
    assert { "broken" } <= t


# ---- runs ----

def test_shared_run_finds_four_words_case_insensitively_and_returns_them():
    assert nc.shared_run( "It will Parse A feed from here", "x — parse a FEED from the web" ) == "parse a feed from"


def test_three_words_in_common_are_not_a_run():
    assert nc.shared_run( "parse a feed today", "parse a feed from" ) is None


def test_punctuation_does_not_hide_a_run():
    assert nc.shared_run( "parse, a feed; from here", "parse a feed from" ) == "parse a feed from"


# ---- form ----

@pytest.mark.parametrize( "need, why", [
    ( "A function that reads feeds.",                                                 "words" ),
    ( "A function that " + "word " * 40 + "ends.",                                    "words" ),
    ( "Reads an online news feed and returns the list of articles it holds today.",   "start" ),
    ( "A function that reads a feed. It returns articles and prints a nice summary.", "sentence" ),
] )
def test_form_failures_name_their_reason( need, why ):
    assert why in nc.check_form( need )


@pytest.mark.parametrize( "need", [ GOOD, "A method that reads an online news bulletin and returns the list of articles it holds",
                                   "a class that holds an online news bulletin and returns the list of articles it holds." ] )
def test_form_passes_the_three_shapes( need ):
    assert nc.check_form( need ) is None


# ---- one need ----

def test_a_clean_need_has_no_failures():
    assert nc.check_need( A, GOOD, INDEX, nc.twin_groups( MANIFEST ) ) == []


def test_the_members_own_identifier_fails_and_the_token_is_named():
    f = nc.check_need( A, "A function that calls read_items to return the list of articles it holds.", INDEX, nc.twin_groups( MANIFEST ) )
    assert [ x[ "check" ] for x in f ] == [ "identifier" ]
    assert "read_items" in f[ 0 ][ "detail" ]


def test_a_twin_identifier_reached_only_through_the_group_fails():
    f = nc.check_need( A, "A function that can scan text and returns the list of articles it holds.", INDEX, nc.twin_groups( MANIFEST ) )
    assert [ x[ "check" ] for x in f ] == [ "identifier" ]       # scan comes from C, linked to A only through B
    assert "scan" in f[ 0 ][ "detail" ]


def test_the_same_need_is_clean_for_a_member_outside_that_group():
    assert nc.check_need( D, "A function that can scan text and returns the list of articles it holds.", INDEX, nc.twin_groups( MANIFEST ) ) == []


def test_a_run_shared_with_the_member_text_fails():
    f = nc.check_need( A, "A function that will parse a feed from a web address and return articles.", INDEX, nc.twin_groups( MANIFEST ) )
    assert [ x[ "check" ] for x in f ] == [ "member_text_run" ]
    assert "parse a feed from" in f[ 0 ][ "detail" ]


def test_a_run_shared_only_with_a_twin_text_fails_as_a_twin_run():
    f = nc.check_need( A, "A function that will pull each record out of the store, one at a time.", INDEX, nc.twin_groups( MANIFEST ) )
    assert [ x[ "check" ] for x in f ] == [ "twin_text_run" ]
    assert "pull each record out" in f[ 0 ][ "detail" ]


def test_a_missing_index_record_stops_the_check_loudly():
    with pytest.raises( ValueError, match = "not in the index" ):
        nc.check_need( A, GOOD, { A: INDEX[ A ] }, nc.twin_groups( MANIFEST ) )


# ---- all of them ----

def test_check_all_reports_missing_and_extra_members_and_passes_only_when_all_clean():
    needs = { A: GOOD, D: "A function that holds a small thing and returns the list of articles it holds." }
    res   = nc.check_all( needs, [ A, D, B ], INDEX, nc.twin_groups( MANIFEST ) )
    assert res[ "summary" ][ "checked" ] == 2 and res[ "summary" ][ "missing" ] == [ B ]
    assert res[ "summary" ][ "all_pass" ] is False
    assert failed_names( res[ "rows" ], B ) == [ "sample" ]
    res2 = nc.check_all( { **needs, C: GOOD }, [ A, D ], INDEX, nc.twin_groups( MANIFEST ) )
    assert res2[ "summary" ][ "extra" ] == [ C ] and res2[ "summary" ][ "all_pass" ] is False


def test_check_all_passes_a_clean_full_sample():
    res = nc.check_all( { A: GOOD, D: GOOD }, [ A, D ], INDEX, nc.twin_groups( MANIFEST ) )
    assert res[ "summary" ][ "all_pass" ] is True and res[ "summary" ][ "failed" ] == 0
    assert len( res[ "rows" ] ) == 2


def test_check_all_refuses_to_loop_over_an_empty_sample():
    with pytest.raises( ValueError, match = "empty" ):
        nc.check_all( {}, [], INDEX, nc.twin_groups( MANIFEST ) )


def test_the_resend_list_holds_only_member_ids_and_check_names_and_never_a_twin():
    bad = "A function that can scan text and calls fetch_rows to return the list of articles it holds."
    res = nc.check_all( { A: bad, D: GOOD }, [ A, D ], INDEX, nc.twin_groups( MANIFEST ) )
    assert "fetch_rows" in json.dumps( res ) and "scan" in json.dumps( res )
    resend = nc.resend_list( res )
    assert resend == [ { "member": A, "failed": [ "identifier" ] } ]
    text = json.dumps( resend )
    for twin in ( B, C ):
        assert twin not in text
    for token in ( "scan", "fetch_rows" ):
        assert token not in text


# ---- files and exit codes ----

def needs_document( sample_sha, needs ):
    """The one needs document shape the writer emits and the driver loads."""
    return { "format": nc.NEEDS_FORMAT, "sample_sha256": sample_sha,
             "needs": [ { "member": i, "need": n, "kind": "function", "writer_job_id": "j-" + str( k ), "attempts": 1, "rewrites": 0 } for k, ( i, n ) in enumerate( needs.items() ) ] }


def write_inputs( tmp_path, needs ):
    ( tmp_path / "manifest.json" ).write_text( json.dumps( MANIFEST ) )
    ( tmp_path / "symbols.jsonl" ).write_text( "\n".join( json.dumps( r ) for r in INDEX.values() ) + "\n" )
    ( tmp_path / "sample.json" ).write_text( json.dumps( { "strata": { "one": { "members": [ A ] }, "two": { "members": [ D ] } } } ) )
    ( tmp_path / "needs.json" ).write_text( json.dumps( needs_document( nc.file_sha256( tmp_path / "sample.json" ), needs ) ) )
    return [ "--needs", str( tmp_path / "needs.json" ), "--manifest", str( tmp_path / "manifest.json" ), "--index", str( tmp_path / "symbols.jsonl" ),
             "--sample", str( tmp_path / "sample.json" ), "--out-dir", str( tmp_path / "out" ),
             "--sample-sha256", nc.file_sha256( tmp_path / "sample.json" ), "--manifest-sha256", nc.file_sha256( tmp_path / "manifest.json" ), "--size", "2" ]


def test_main_writes_both_files_and_exits_zero_when_all_pass( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    assert nc.main( args ) == 0
    full   = json.loads( ( tmp_path / "out" / "check-results.json" ).read_text() )
    resend = json.loads( ( tmp_path / "out" / "resend-list.json" ).read_text() )
    assert full[ "summary" ][ "all_pass" ] is True and resend == []
    assert full[ "needs_sha256" ] == nc.file_sha256( tmp_path / "needs.json" ) and len( full[ "needs_sha256" ] ) == 64


def test_main_exits_one_and_keeps_the_token_out_of_the_resend_file( tmp_path ):
    args = write_inputs( tmp_path, { A: "A function that can scan text and returns the list of articles it holds.", D: GOOD } )
    assert nc.main( args ) == 1
    full   = ( tmp_path / "out" / "check-results.json" ).read_text()
    resend = ( tmp_path / "out" / "resend-list.json" ).read_text()
    assert "scan" in full and "scan" not in resend and C not in resend


def test_main_exits_one_when_the_sample_is_not_the_stated_size( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    args[ -1 ] = "3"
    assert nc.main( args ) == 1


def test_main_exits_two_for_a_missing_input_and_writes_nothing( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    ( tmp_path / "manifest.json" ).unlink()
    assert nc.main( args ) == 2
    assert not ( tmp_path / "out" ).exists()


def test_main_exits_two_for_a_needs_file_that_is_not_json( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    ( tmp_path / "needs.json" ).write_text( "{not json" )
    assert nc.main( args ) == 2


def test_a_sample_file_with_a_repeated_member_is_refused( tmp_path ):
    p = tmp_path / "s.json"
    p.write_text( json.dumps( { "strata": { "one": { "members": [ A, A ] } } } ) )
    with pytest.raises( ValueError, match = "twice" ):
        nc.load_sample_ids( p )


def test_a_sample_file_with_no_members_is_refused( tmp_path ):
    p = tmp_path / "s.json"
    p.write_text( json.dumps( { "strata": {} } ) )
    with pytest.raises( ValueError, match = "no members" ):
        nc.load_sample_ids( p )


def test_load_index_keeps_one_record_per_id( tmp_path ):
    p = tmp_path / "s.jsonl"
    p.write_text( json.dumps( INDEX[ A ] ) + "\n\n" + json.dumps( INDEX[ D ] ) + "\n" )
    assert sorted( nc.load_index( p ) ) == sorted( [ A, D ] )


def test_the_results_record_the_sha_of_all_three_inputs( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    assert nc.main( args ) == 0
    full = json.loads( ( tmp_path / "out" / "check-results.json" ).read_text() )
    for key, name in ( ( "needs_sha256", "needs.json" ), ( "sample_sha256", "sample.json" ), ( "manifest_sha256", "manifest.json" ) ):
        assert full[ key ] == nc.file_sha256( tmp_path / name )


def test_the_results_name_the_index_generation_and_its_sha( tmp_path ):
    gen = tmp_path / "gen-abc123def0"
    gen.mkdir()
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    ( gen / "symbols.jsonl" ).write_text( ( tmp_path / "symbols.jsonl" ).read_text() )
    args[ args.index( "--index" ) + 1 ] = str( gen / "symbols.jsonl" )
    assert nc.main( args ) == 0
    full = json.loads( ( tmp_path / "out" / "check-results.json" ).read_text() )
    assert full[ "index_generation" ] == "gen-abc123def0"
    assert full[ "index_sha256" ] == nc.file_sha256( gen / "symbols.jsonl" )


@pytest.mark.parametrize( "flag", [ "--sample-sha256", "--manifest-sha256" ] )
def test_a_sample_or_manifest_that_is_not_the_pinned_file_exits_two_and_writes_nothing( tmp_path, flag, capsys ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    args[ args.index( flag ) + 1 ] = "0" * 64
    assert nc.main( args ) == 2
    assert not ( tmp_path / "out" ).exists()
    assert flag[ 2: ].replace( "-", "_" ) in capsys.readouterr().out


def test_the_pinned_default_shas_are_the_ones_in_plan_section_12_1():
    assert nc.DEFAULT_SAMPLE_SHA.startswith( "5b6d84fc" ) and len( nc.DEFAULT_SAMPLE_SHA ) == 64
    assert nc.DEFAULT_MANIFEST_SHA.startswith( "bfbfceab" ) and len( nc.DEFAULT_MANIFEST_SHA ) == 64


def rewrite_doc( tmp_path, change ):
    doc = json.loads( ( tmp_path / "needs.json" ).read_text() )
    change( doc )
    ( tmp_path / "needs.json" ).write_text( json.dumps( doc ) )


@pytest.mark.parametrize( "row", [ "just a string", { "member": A, "text": "wrong key" }, { "member": A, "need": 7 }, { "need": GOOD }, { "member": 3, "need": GOOD } ] )
def test_a_needs_entry_without_a_member_and_a_text_exits_two( tmp_path, row, capsys ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    rewrite_doc( tmp_path, lambda d: d[ "needs" ].__setitem__( 0, row ) )
    assert nc.main( args ) == 2
    assert "entry 0" in capsys.readouterr().out and not ( tmp_path / "out" ).exists()


def test_a_member_named_twice_in_the_document_exits_two( tmp_path, capsys ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    rewrite_doc( tmp_path, lambda d: d[ "needs" ].append( dict( d[ "needs" ][ 0 ] ) ) )
    assert nc.main( args ) == 2
    assert A in capsys.readouterr().out


@pytest.mark.parametrize( "key, value, word", [ ( "format", "reuse-e2e-needs-2", "format" ), ( "sample_sha256", "0" * 64, "sample_sha256" ), ( "needs", {}, "needs" ) ] )
def test_a_document_with_the_wrong_format_sample_sha_or_list_exits_two( tmp_path, key, value, word, capsys ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    rewrite_doc( tmp_path, lambda d: d.__setitem__( key, value ) )
    assert nc.main( args ) == 2
    assert word in capsys.readouterr().out and not ( tmp_path / "out" ).exists()


def test_the_old_member_keyed_shape_is_refused_not_read( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    ( tmp_path / "needs.json" ).write_text( json.dumps( { A: { "need": GOOD, "job_id": "j" }, D: { "need": GOOD, "job_id": "k" } } ) )
    assert nc.main( args ) == 2


def test_load_needs_returns_member_to_text_in_document_order( tmp_path ):
    p = tmp_path / "n.json"
    p.write_text( json.dumps( needs_document( "ab" * 32, { D: "text d", A: "text a" } ) ) )
    got = nc.load_needs( p, "ab" * 32 )
    assert list( got.items() ) == [ ( D, "text d" ), ( A, "text a" ) ]


def test_a_needs_file_that_is_a_list_exits_two( tmp_path ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    ( tmp_path / "needs.json" ).write_text( "[]" )
    assert nc.main( args ) == 2


def test_a_twin_missing_from_the_index_exits_two_and_names_it( tmp_path, capsys ):
    args = write_inputs( tmp_path, { A: GOOD, D: GOOD } )
    ( tmp_path / "symbols.jsonl" ).write_text( "\n".join( json.dumps( INDEX[ i ] ) for i in ( A, B, D ) ) + "\n" )     # C is gone
    assert nc.main( args ) == 2
    assert C in capsys.readouterr().out and not ( tmp_path / "out" ).exists()


# ---- the four spots the review found unguarded ----

def test_the_file_stem_is_banned_even_when_no_id_part_carries_it():
    rec = { "id": "p.f", "sig": "( )", "doc": "", "file": "p/special_stem.py" }
    assert { "special_stem", "special", "stem" } <= nc.identifier_tokens( rec )
    index = { "p.f": rec }
    f = nc.check_need( "p.f", "A function that returns the special_stem values it holds for every caller today.", index, {} )
    assert [ x[ "check" ] for x in f ] == [ "identifier" ] and "special_stem" in f[ 0 ][ "detail" ]


@pytest.mark.parametrize( "words, ok", [ ( 7, False ), ( 8, True ), ( 40, True ), ( 41, False ) ] )
def test_the_word_count_limits_are_eight_and_forty_inclusive( words, ok ):
    need = "A function that " + " ".join( [ "word" ] * ( words - 3 ) ) + "."
    assert len( need.split() ) == words
    assert ( nc.check_form( need ) is None ) is ok


def test_a_run_shared_with_a_later_twin_is_found_and_names_that_twin():
    f = nc.check_need( A, "A function that will walk text one line at a time and returns counts.", INDEX, nc.twin_groups( MANIFEST ) )
    assert [ x[ "check" ] for x in f ] == [ "twin_text_run" ]
    assert C in f[ 0 ][ "detail" ] and B not in f[ 0 ][ "detail" ]                # the run is in C's text, the second twin


def test_a_need_word_joined_by_underscores_is_split_before_it_is_compared():
    f = nc.check_need( A, "A function that returns wrapped_items values and counts them for each of the records.", INDEX, nc.twin_groups( MANIFEST ) )
    assert [ x[ "check" ] for x in f ] == [ "identifier" ] and "items" in f[ 0 ][ "detail" ]


# ---- the real files, through the real readers (outside git: skipped when absent) ----

def test_the_frozen_sample_file_holds_100_distinct_members_and_each_has_a_twin_group():
    sample, manifest = pathlib.Path( nc.DEFAULT_SAMPLE ), pathlib.Path( nc.DEFAULT_MANIFEST )
    if not ( sample.exists() and manifest.exists() ): pytest.skip( f"{sample} or {manifest} is not on this host" )
    ids = nc.load_sample_ids( sample )
    assert len( ids ) == nc.SAMPLE_SIZE == 100
    groups = nc.twin_groups( json.loads( manifest.read_text( encoding = "utf-8" ) ) )
    assert groups, "the manifest produced no groups"
    assert all( groups[ i ] for i in ids )                       # every sampled member has at least one twin
    assert len( groups ) == 376                                  # the manifest's distinct members, plan 12.1 (inherited figure)


def test_the_production_entry_text_is_the_text_the_check_compares_against():
    assert nc.entry_text_of( INDEX[ A ] ) == rt.entry_text( INDEX[ A ] )
