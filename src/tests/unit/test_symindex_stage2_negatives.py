"""
Tests of the hard-negative selector for the labelled-pair run.

For each twin-group member it picks neighbours that look alike on the surface but are not twins.
It needs no model and no network. The tests pin the constants, the word rules and the choice.
They also pin the old random negatives it keeps and the near-copies it holds out for a person to read.
The last tests cover the report of how many each member got.
"""
import hashlib
import json
import pathlib

import pytest

from cosa.repo.symindex import stage2_negatives as ng

FIX = pathlib.Path( __file__ ).parent / "fixtures"


def _rec( i, sig="()", doc="", lang="py" ):
    """Ensures: returns a symbol record with the fields the selector reads."""
    return { "id": i, "sig": sig, "doc": doc, "file": "f.py", "lang": lang }


def _index( *recs ): return { r[ "id" ]: r for r in recs }


# --- the numbers and the words -------------------------------------------------------------------------------------------

def test_the_constants_are_the_rulings():
    assert ng.LEXICAL_PER_MEMBER == 25                         # Cheech, Q1: 25 lexical hard negatives for each member
    assert ng.HELD_OUT_AT == 0.9
    assert ng.MIN_WORD_LENGTH == 3
    assert ng.FORMAT == "stage2-negatives-1"
    assert ng.PACKAGE_DEPTH == 2


def test_words_split_snake_case_camel_case_dots_and_digits_and_lower_the_case():
    assert ng.words( "send_NotificationNow v2.fetchHTTPData" ) == frozenset( { "send", "notification", "now", "fetch", "http", "data" } )
    assert ng.words( "http200 status404" ) == frozenset( { "http", "status" } )                       # digits are not words


def test_words_drop_short_words_and_the_stop_words():
    assert ng.words( "a to be of self and the user None" ) == frozenset( { "user" } )


def test_the_surface_words_of_a_symbol_are_its_own_name_its_signature_and_its_first_doc_line_not_its_path():
    rec = _rec( "cosa.agents.deep_research.job.DeepResearchJob.run_stage", "( self, topic_name )", "Runs one research stage." )
    assert ng.surface_words( rec ) == frozenset( { "run", "stage", "topic", "name", "runs", "one", "research" } )


def test_the_package_of_an_id_is_its_first_two_parts_and_a_short_id_is_its_own_package():
    assert ng.package_of( "cosa.agents.deep_research.job.Job.run" ) == "cosa.agents"
    assert ng.package_of( "solo" ) == "solo"


def test_the_overlap_of_two_word_sets_is_their_jaccard_and_empty_sets_overlap_nothing():
    assert ng.jaccard( frozenset( "abcd" ), frozenset( "cdef" ) ) == pytest.approx( 2 / 6 )
    assert ng.jaccard( frozenset(), frozenset() ) == 0.0 and ng.jaccard( frozenset( "a" ), frozenset( "b" ) ) == 0.0


# --- the lexical neighbours of one member --------------------------------------------------------------------------------

def _pool():
    """Ensures: returns a member and a pool of near, far, twin and out-of-scope entries."""
    member = _rec( "pk.sub.mod.fetch_user_record", "( user_id )", "Fetch one user record." )
    recs   = [ member,
               _rec( "pk.sub.mod.fetch_user_name", "( user_id )", "Fetch one user name." ),
               _rec( "pk.sub.mod.fetch_account_record", "( account )", "Fetch one account record." ),
               _rec( "pk.sub.mod.render_page", "( html )", "Draw the page." ),
               _rec( "other.sub.mod.fetch_user_record2", "( user_id )", "Fetch one user record." ),
               _rec( "pk.sub.mod.fetch_user_ts", "( user_id )", "Fetch one user record.", lang="ts" ),
               _rec( "pk.sub.mod.twin_of_member", "( user_id )", "Fetch one user record." ) ]
    return member, recs


def test_the_chosen_are_of_the_same_package_and_language_not_the_member_nor_an_excluded_id_and_never_zero_overlap():
    member, recs = _pool()
    r = ng.lexical_negatives( member, recs, { "pk.sub.mod.twin_of_member" }, 25 )
    ids = [ c[ "id" ] for c in r[ "chosen" ] ]
    assert ids == [ "pk.sub.mod.fetch_user_name", "pk.sub.mod.fetch_account_record" ]
    assert r[ "pool" ] == 3                                              # the three same-package Python entries left after the exclusions


def test_the_chosen_are_ranked_by_overlap_then_id_and_cut_at_n():
    member = _rec( "pk.a.m.base", "( alpha_beta )", "Alpha beta." )
    names  = [ "gamma", "delta", "omega", "sigma", "theta", "kappa" ]
    extra  = [ "", "", "more", "more", "more extra", "more extra" ]
    recs   = [ member ] + [ _rec( f"pk.a.m.{n}", "( alpha_beta )", f"Alpha beta {e}." ) for n, e in zip( names, extra ) ]
    r = ng.lexical_negatives( member, recs, set(), 4 )
    assert len( r[ "chosen" ] ) == 4
    keys = [ ( -c[ "score" ], c[ "id" ] ) for c in r[ "chosen" ] ]
    assert keys == sorted( keys )


def test_a_candidate_at_or_above_the_held_out_overlap_is_held_out_not_chosen():
    member = _rec( "pk.a.m.fetch_user_record", "( user_id )", "Fetch one user record." )
    copy   = _rec( "pk.a.m.fetch_user_record_v2", "( user_id )", "Fetch one user record." )
    other  = _rec( "pk.a.m.fetch_account", "( user_id )", "Fetch one account." )
    r = ng.lexical_negatives( member, [ member, copy, other ], set(), 25 )
    assert [ c[ "id" ] for c in r[ "held_out" ] ] == [ "pk.a.m.fetch_user_record_v2" ] and r[ "held_out" ][ 0 ][ "score" ] >= 0.9
    assert [ c[ "id" ] for c in r[ "chosen" ] ] == [ "pk.a.m.fetch_account" ]


def test_exactly_the_held_out_overlap_is_held_out_and_just_under_is_chosen():
    ten    = "aaa bbb ccc ddd eee fff ggg hhh iii jjj"
    member = _rec( "pk.a.m.f", f"( {ten} )", "" )                                                                    # ten words; the one-letter name is no word
    nine   = _rec( "pk.a.m.f1", "( " + ten.rsplit( " ", 1 )[ 0 ] + " )", "" )                                      # nine of the ten: 9 / 10, exactly the bar
    eight  = _rec( "pk.a.m.f2", "( " + ten.rsplit( " ", 2 )[ 0 ] + " )", "" )                                      # eight of the ten: 8 / 10, below
    same   = _rec( "pk.a.m.f3", f"( {ten} )", "" )                                                                   # all ten: 1.0
    r = ng.lexical_negatives( member, [ member, nine, eight, same ], set(), 25 )
    assert sorted( c[ "id" ] for c in r[ "held_out" ] ) == [ "pk.a.m.f1", "pk.a.m.f3" ]
    assert [ c[ "id" ] for c in r[ "chosen" ] ] == [ "pk.a.m.f2" ] and r[ "chosen" ][ 0 ][ "score" ] == 0.8


def test_fewer_eligible_candidates_than_n_give_a_short_list_and_no_top_up_from_another_package():
    member, recs = _pool()
    r = ng.lexical_negatives( member, recs, set(), 25 )
    assert len( r[ "chosen" ] ) == 2 and all( ng.package_of( c[ "id" ] ) == "pk.sub" for c in r[ "chosen" ] )


def test_the_choice_does_not_depend_on_the_order_the_entries_come_in():
    member, recs = _pool()
    assert ng.lexical_negatives( member, recs, set(), 25 ) == ng.lexical_negatives( member, list( reversed( recs ) ), set(), 25 )


# --- the old random negatives ---------------------------------------------------------------------------------------------

def test_the_old_random_negatives_are_each_members_candidates_that_are_not_twins_in_order_without_repeats():
    rows = [ { "member": "m1", "candidate": "t1" }, { "member": "m1", "candidate": "r1" }, { "member": "m1", "candidate": "r2" },
             { "member": "m1", "candidate": "r1" }, { "member": "m2", "candidate": "r3" } ]
    assert ng.old_random_by_member( rows, { "m1": [ "t1" ], "m2": [] } ) == { "m1": [ "r1", "r2" ], "m2": [ "r3" ] }


def test_a_member_with_no_rows_has_no_old_random_negatives():
    assert ng.old_random_by_member( [], { "m1": [ "t1" ] } ) == { "m1": [] }


# --- the selection --------------------------------------------------------------------------------------------------------

def _world():
    """Ensures: returns ( twin map, index, old random ) for one twin pair in one package."""
    recs = [ _rec( "pk.a.m.fetch_user_record", "( user_id )", "Fetch one user record." ),
             _rec( "pk.a.m.get_user_record", "( user_id )", "Get one user record from the store." ),
             _rec( "pk.a.m.fetch_user_name", "( user_id )", "Fetch one user name." ),
             _rec( "pk.a.m.fetch_account_record", "( account )", "Fetch one account record." ),
             _rec( "pk.a.m.render_page", "( html )", "Draw the page." ),
             _rec( "pk.a.m.zeta_unrelated", "( q )", "Nothing alike." ),
             _rec( "pk.a.m.later_removed", "( q )", "Gone." ) ]
    twins = { "pk.a.m.fetch_user_record": [ "pk.a.m.get_user_record" ], "pk.a.m.get_user_record": [ "pk.a.m.fetch_user_record" ] }
    old   = { "pk.a.m.fetch_user_record": [ "pk.a.m.render_page", "pk.a.m.removed_since" ], "pk.a.m.get_user_record": [ "pk.a.m.zeta_unrelated" ] }
    return twins, _index( *recs ), old


def test_each_member_gets_its_twins_its_lexical_neighbours_and_its_surviving_random_ones():
    twins, idx, old = _world()
    r = ng.select_negatives( twins, idx, old )[ "members" ]
    m = r[ "pk.a.m.fetch_user_record" ]
    assert m[ "twins" ] == [ "pk.a.m.get_user_record" ]
    assert [ c[ "id" ] for c in m[ "lexical" ] ] == [ "pk.a.m.fetch_user_name", "pk.a.m.fetch_account_record" ]
    assert m[ "random" ] == [ "pk.a.m.render_page" ] and m[ "random_dropped" ] == [ "pk.a.m.removed_since" ]


def test_a_random_negative_is_not_chosen_again_as_a_lexical_one_and_a_twin_is_never_a_negative():
    twins, idx, old = _world()
    old[ "pk.a.m.fetch_user_record" ] = [ "pk.a.m.fetch_user_name" ]
    m = ng.select_negatives( twins, idx, old )[ "members" ][ "pk.a.m.fetch_user_record" ]
    assert "pk.a.m.fetch_user_name" in m[ "random" ] and "pk.a.m.fetch_user_name" not in [ c[ "id" ] for c in m[ "lexical" ] ]
    assert "pk.a.m.get_user_record" not in m[ "random" ] + [ c[ "id" ] for c in m[ "lexical" ] ]


def test_a_random_negative_that_is_a_near_copy_of_the_member_is_held_out_with_the_lexical_ones():
    twins, idx, old = _world()
    idx[ "pk.a.m.fetch_user_record_v2" ] = _rec( "pk.a.m.fetch_user_record_v2", "( user_id )", "Fetch one user record." )
    old[ "pk.a.m.fetch_user_record" ] = [ "pk.a.m.fetch_user_record_v2", "pk.a.m.render_page" ]
    m = ng.select_negatives( twins, idx, old )[ "members" ][ "pk.a.m.fetch_user_record" ]
    assert "pk.a.m.fetch_user_record_v2" not in m[ "random" ]
    assert "pk.a.m.fetch_user_record_v2" in [ c[ "id" ] for c in m[ "held_out" ] ]


def test_the_report_counts_the_members_the_shortfall_the_drops_the_held_out_and_the_pairs():
    twins, idx, old = _world()
    s = ng.select_negatives( twins, idx, old )[ "summary" ]
    assert s[ "members" ] == 2 and s[ "short_of_25" ] == 2 and s[ "got_none" ] == 0
    assert ( s[ "lexical_min" ], s[ "lexical_max" ] ) == ( 2, 2 )
    assert s[ "random_kept" ] == 2 and s[ "random_dropped" ] == 1 and s[ "pairs" ] == s[ "twin_pairs" ] + s[ "lexical_pairs" ] + s[ "random_kept" ]


def test_a_member_that_got_no_lexical_neighbour_is_counted_and_listed_by_name():
    recs = [ _rec( "pk.a.m.alpha", "( one )", "First." ), _rec( "pk.a.m.omega", "( two )", "Second." ) ]
    r = ng.select_negatives( { "pk.a.m.alpha": [ "pk.a.m.omega" ], "pk.a.m.omega": [ "pk.a.m.alpha" ] }, _index( *recs ), { "pk.a.m.alpha": [], "pk.a.m.omega": [] } )
    assert r[ "summary" ][ "got_none" ] == 2 and r[ "summary" ][ "got_none_members" ] == [ "pk.a.m.alpha", "pk.a.m.omega" ]


def test_a_member_missing_from_the_index_is_refused_because_it_cannot_be_asked_about():
    twins, idx, old = _world()
    del idx[ "pk.a.m.get_user_record" ]
    with pytest.raises( ValueError, match="get_user_record" ):
        ng.select_negatives( twins, idx, old )


def test_a_twin_missing_from_the_index_is_refused_too():
    twins, idx, old = _world()
    twins[ "pk.a.m.fetch_user_record" ].append( "pk.a.m.nowhere" )
    with pytest.raises( ValueError, match="nowhere" ):
        ng.select_negatives( twins, idx, old )


def test_the_selection_is_the_same_whatever_order_the_members_and_entries_come_in():
    twins, idx, old = _world()
    flipped = ( dict( reversed( list( twins.items() ) ) ), dict( reversed( list( idx.items() ) ) ), dict( reversed( list( old.items() ) ) ) )
    assert ng.select_negatives( twins, idx, old ) == ng.select_negatives( *flipped )


# --- the real slice -------------------------------------------------------------------------------------------------------

def _real():
    from cosa.repo.symindex import stage2_split as s2
    manifest = json.loads( ( FIX / "stage2-manifest-slice.json" ).read_text() )
    entries  = json.loads( ( FIX / "stage2-symbols-slice.json" ).read_text() )[ "entries" ]
    twins    = {}
    for g in s2.twin_groups( manifest ):
        for i in g[ "members" ]: twins[ i ] = sorted( set( g[ "members" ] ) - { i } )
    return twins, _index( *entries )


def test_on_the_real_slice_every_member_gets_a_same_package_python_neighbour_that_is_not_a_twin():
    twins, idx = _real()
    old = ng.old_random_by_member( json.loads( ( FIX / "stage2-old-pairs-sample.json" ).read_text() )[ "rows" ], twins )
    r   = ng.select_negatives( twins, idx, old )
    assert len( r[ "members" ] ) == 61 and r[ "summary" ][ "members" ] == 61
    for m, rec in r[ "members" ].items():
        for c in rec[ "lexical" ]:
            assert ng.package_of( c[ "id" ] ) == ng.package_of( m ) and idx[ c[ "id" ] ][ "lang" ] == "py"
            assert c[ "id" ] != m and c[ "id" ] not in twins[ m ] and 0.0 < c[ "score" ] < ng.HELD_OUT_AT
        assert len( rec[ "lexical" ] ) <= ng.LEXICAL_PER_MEMBER
    assert any( len( rec[ "lexical" ] ) > 0 for rec in r[ "members" ].values() )
    assert r[ "summary" ][ "random_dropped" ] > 0                                                  # the sample's old randoms are mostly not in the slice


def test_on_the_real_slice_the_old_random_rows_read_into_six_members_with_no_twins_among_them():
    twins, _ = _real()
    rows = json.loads( ( FIX / "stage2-old-pairs-sample.json" ).read_text() )[ "rows" ]
    old  = ng.old_random_by_member( rows, twins )
    members = {r[ "member" ] for r in rows}
    assert len( members ) == 6
    for m in members: assert not set( old[ m ] ) & set( twins[ m ] ) and 0 < len( old[ m ] ) <= 50


# --- the file and the command --------------------------------------------------------------------------------------------

def _inputs( tmp_path ):
    twins_manifest = FIX / "stage2-manifest-slice.json"
    symbols = tmp_path / "symbols.jsonl"
    symbols.write_text( "\n".join( json.dumps( r ) for r in json.loads( ( FIX / "stage2-symbols-slice.json" ).read_text() )[ "entries" ] ) + "\n" )
    old = tmp_path / "old.json"
    old.write_text( json.dumps( { "rows": json.loads( ( FIX / "stage2-old-pairs-sample.json" ).read_text() )[ "rows" ] } ) )
    return twins_manifest, symbols, old


def test_the_command_writes_the_record_with_the_input_shas_and_prints_the_summary(tmp_path, capsys):
    manifest, symbols, old = _inputs( tmp_path )
    out = tmp_path / "negatives.json"
    assert ng.main( [ "--manifest", str( manifest ), "--symbols", str( symbols ), "--old-stage2", str( old ), "--out", str( out ) ] ) == 0
    rec = json.loads( out.read_text() )
    assert rec[ "format" ] == "stage2-negatives-1"
    assert rec[ "inputs" ] == { "manifest_sha256": hashlib.sha256( manifest.read_bytes() ).hexdigest(), "symbols_sha256": hashlib.sha256( symbols.read_bytes() ).hexdigest(),
                                "old_stage2_sha256": hashlib.sha256( old.read_bytes() ).hexdigest() }
    assert rec[ "constants" ] == { "lexical_per_member": 25, "held_out_at": 0.9, "min_word_length": 3, "package_depth": 2 }
    assert len( rec[ "members" ] ) == 61 and "members=61" in capsys.readouterr().out


def test_the_command_refuses_to_overwrite_a_record_and_needs_all_four_arguments(tmp_path):
    manifest, symbols, old = _inputs( tmp_path )
    out = tmp_path / "negatives.json"; out.write_text( "{}" )
    with pytest.raises( FileExistsError, match="already exists" ):
        ng.main( [ "--manifest", str( manifest ), "--symbols", str( symbols ), "--old-stage2", str( old ), "--out", str( out ) ] )
    assert out.read_text() == "{}"
    with pytest.raises( SystemExit ):
        ng.main( [ "--manifest", str( manifest ), "--symbols", str( symbols ), "--out", str( tmp_path / "x.json" ) ] )


def test_the_command_reads_the_symbols_through_the_one_place_that_decides_what_may_leave_the_machine(tmp_path):
    manifest, symbols, old = _inputs( tmp_path )
    lines = symbols.read_text().splitlines()
    at    = next( k for k, l in enumerate( lines ) if json.loads( l )[ "lang" ] == "ts" )                          # a TypeScript entry is no member
    rec   = json.loads( lines[ at ] ); rec[ "doc" ] = "Mail ops@example.com about it."; lines[ at ] = json.dumps( rec )
    symbols.write_text( "\n".join( lines ) + "\n" )
    out = tmp_path / "negatives.json"
    ng.main( [ "--manifest", str( manifest ), "--symbols", str( symbols ), "--old-stage2", str( old ), "--out", str( out ) ] )
    assert rec[ "id" ] in json.loads( out.read_text() )[ "not_sendable" ]
