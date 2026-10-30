"""
Unit tests for semdup.proof.flag_items, which adds the owed flag pairs as new items.

The run folder is the cli tests' toy world, written by label_prep.prepare, so the packets and key are the real writers' output.
"""
import json
import pathlib

import pytest

from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup.proof import flag_items as fi
from cosa.repo.semdup.proof import label_load as ll
from cosa.repo.semdup.proof import label_prep as lp
from cosa.repo.semdup.proof import proof_cli as pc
from cosa.repo.semdup.proof import proof_run as pr
from tests.unit.test_semdup_proof_cli import World, venue, world  # noqa: F401  (fixtures)

REVIEWERS = ( "rick", "second" )


@pytest.fixture
def flagged( world, tmp_path, monkeypatch, venue ):  # noqa: F811
    """The toy world with an unofficial record that owes four flag pairs."""
    monkeypatch.setattr( fi.label_prep, "REVIEWERS", REVIEWERS )
    toy   = world.toy
    owed  = sorted( toy.key( a, b ) for a, b in ( ( "m1", "d1" ), ( "m2", "d2" ), ( "m3", "d1" ), ( "m4", "d2" ) ) )
    path  = tmp_path / "1.json"
    path.write_text( json.dumps( { "unofficial": True, "owed": owed } ), encoding="utf-8" )
    world.record = path
    world.owed   = owed
    return world


def argv( w, *extra ):
    """Return the command line for a world."""
    return [ "--run-dir", str( w.run_dir ), "--record", str( w.record ), *extra ]


def run( w, *extra ):
    """Run the command with the toy's parts."""
    return fi.main( argv( w, *extra ), make_parts=lambda *a: w.parts() )


def snapshot( w ):
    """Return the bytes of the key and of each packet."""
    return { "key": w.key.read_bytes(), **{ r: p.read_bytes() for r, p in w.packets.items() } }


def test_main_appends_the_flag_items_and_leaves_every_original_byte_in_place( flagged, capsys ):
    before = snapshot( flagged )
    rows   = ll.key_rows( flagged.key )
    assert run( flagged ) == 0
    out    = json.loads( capsys.readouterr().out )
    after  = snapshot( flagged )
    assert out[ "status" ] == "added" and out[ "added" ] == 4
    assert out[ "original_bytes_sha_before" ] == out[ "original_bytes_sha_after" ]
    assert out[ "original_bytes_sha_before" ][ "rick" ] == fi.sha_of( before[ "rick" ] )
    for r in REVIEWERS: assert after[ r ].startswith( before[ r ] ) and len( after[ r ].splitlines() ) == len( before[ r ].splitlines() ) + 4
    new_rows = ll.key_rows( flagged.key )
    assert all( new_rows[ i ] == row for i, row in rows.items() ) and len( new_rows ) == len( rows ) + 4
    flags    = { i: r for i, r in new_rows.items() if i not in rows }
    assert { pr.label_key( r[ "a" ], r[ "b" ] ) for r in flags.values() } == set( flagged.owed )
    assert all( r[ "kind" ] == "flag" and r[ "stratum" ] == "flag" for r in flags.values() )
    assert not list( flagged.run_dir.rglob( "*" + fi.NEW_SUFFIX ) )


def test_the_new_items_hold_the_pools_own_texts_in_the_item_the_pair_item_builder_makes( flagged ):
    run( flagged )
    toy   = flagged.toy
    mine  = { i["item_id"]: i for i in map( json.loads, flagged.packets[ "rick" ].read_text().splitlines() ) }
    want  = lp.pair_item( toy.d[ "d1" ], toy.m[ "m1" ], 3 )
    assert mine[ want[ "item" ][ "item_id" ] ] == pk.blind_form( want[ "item" ] )


def test_each_reviewer_gets_the_new_items_in_a_seeded_order_of_their_own( flagged ):
    run( flagged )
    tails = []
    for r in REVIEWERS:
        lines = flagged.packets[ r ].read_text().splitlines()
        tails.append( [ json.loads( l )[ "item_id" ] for l in lines[ -4: ] ] )
    assert sorted( tails[ 0 ] ) == sorted( tails[ 1 ] ) and tails[ 0 ] != tails[ 1 ]


def test_load_run_and_monolith_spec_ignore_the_flag_rows_and_the_loader_now_wants_labels_for_them( flagged ):
    before = pc.monolith_spec( pc.load_run( flagged.run_dir )[ "items" ], flagged.toy.spec[ "monolith_defs" ] )
    paths, _ = flagged.label_both()
    kept     = pathlib.Path( paths[ 1 ] ).read_bytes()
    pathlib.Path( paths[ 1 ] ).unlink()
    run( flagged )
    pathlib.Path( paths[ 1 ] ).write_bytes( kept )
    loaded = pc.load_run( flagged.run_dir )
    assert pc.monolith_spec( loaded[ "items" ], flagged.toy.spec[ "monolith_defs" ] ) == before
    assert loaded[ "planted" ] == pc.load_run( flagged.run_dir )[ "planted" ]
    with pytest.raises( ValueError, match="4 pairs are not labelled by both reviewers" ):
        ll.resolved_labels( paths[ 0 ], paths[ 1 ], flagged.key )


def test_check_stages_and_verifies_but_writes_nothing( flagged, capsys ):
    before = snapshot( flagged )
    assert run( flagged, "--check" ) == 0
    assert json.loads( capsys.readouterr().out )[ "status" ] == "checked"
    assert snapshot( flagged ) == before and not list( flagged.run_dir.rglob( "*" + fi.NEW_SUFFIX ) )


def test_stdout_is_the_json_alone_when_the_parts_print_a_banner( flagged, capsys ):
    def noisy( *a ):
        print( "=== configuration banner ===" )
        return flagged.parts()
    fi.main( argv( flagged, "--check" ), make_parts=noisy )
    seen = capsys.readouterr()
    assert json.loads( seen.out )[ "status" ] == "checked" and "configuration banner" in seen.err


def test_refuses_when_the_second_reviewer_has_a_labels_file( flagged ):
    pl.labels_path( flagged.packets[ "second" ] ).write_text( "", encoding="utf-8" )
    before = snapshot( flagged )
    with pytest.raises( ValueError, match="the second reviewer has started" ):
        run( flagged )
    assert snapshot( flagged ) == before


def test_a_first_reviewers_labels_file_does_not_stop_the_command( flagged ):
    flagged.label_both()
    pl.labels_path( flagged.packets[ "second" ] ).unlink()
    assert run( flagged ) == 0


def test_refuses_a_pair_already_in_the_key_and_names_it( flagged ):
    known = flagged.toy.key( "r1", "o1" )
    flagged.record.write_text( json.dumps( { "owed": [ known, *flagged.owed ] } ), encoding="utf-8" )
    before = snapshot( flagged )
    with pytest.raises( ValueError, match=f"1 owed pairs are already in the key: {known}" ):
        run( flagged )
    assert snapshot( flagged ) == before and not list( flagged.run_dir.rglob( "*" + fi.NEW_SUFFIX ) )


def test_refuses_a_definition_the_pool_does_not_hold( flagged ):
    flagged.record.write_text( json.dumps( { "owed": [ pr.label_key( "ghost1", flagged.toy.d[ "d1" ][ "id" ] ) ] } ), encoding="utf-8" )
    with pytest.raises( ValueError, match="1 definitions of the owed pairs are not in the pool: ghost1" ):
        run( flagged )


@pytest.mark.parametrize( "body", [ {}, { "owed": [] } ] )
def test_refuses_a_record_that_owes_nothing( flagged, body ):
    flagged.record.write_text( json.dumps( body ), encoding="utf-8" )
    with pytest.raises( ValueError, match="lists no owed pairs" ):
        run( flagged )


def test_refuses_a_key_that_is_not_in_the_form_the_writer_left( flagged ):
    flagged.key.write_text( json.dumps( json.loads( flagged.key.read_text() ) ), encoding="utf-8" )
    with pytest.raises( ValueError, match="is not in the form label_prep wrote" ):
        run( flagged )


def test_refuses_a_packet_that_does_not_end_in_a_newline( flagged ):
    path = flagged.packets[ "rick" ]
    path.write_bytes( path.read_bytes().rstrip( b"\n" ) )
    with pytest.raises( ValueError, match="does not end in a newline" ):
        run( flagged )


def test_refuses_a_packet_that_holds_only_some_of_the_new_items_and_leaves_no_staged_file( flagged ):
    saved = flagged.key.read_bytes()
    run( flagged )
    flagged.key.write_bytes( saved )
    path  = flagged.packets[ "rick" ]
    lines = path.read_bytes().splitlines( keepends=True )
    path.write_bytes( b"".join( lines[ :-1 ] ) )
    with pytest.raises( ValueError, match="holds only some of the new items" ):
        run( flagged )
    assert not list( flagged.run_dir.rglob( "*" + fi.NEW_SUFFIX ) )


def test_refuses_a_packet_that_holds_the_new_items_but_not_as_its_last_lines( flagged ):
    saved = flagged.key.read_bytes()
    run( flagged )
    flagged.key.write_bytes( saved )
    path  = flagged.packets[ "rick" ]
    lines = path.read_bytes().splitlines( keepends=True )
    path.write_bytes( b"".join( [ lines[ -1 ], *lines[ :-1 ] ] ) )
    with pytest.raises( ValueError, match="holds only some of the new items, or not as its last lines" ):
        run( flagged )


def test_swap_replaces_the_packets_first_in_reviewer_order_and_the_key_last( flagged, monkeypatch ):
    seen = []
    real = fi.os.replace
    monkeypatch.setattr( fi.os, "replace", lambda new, old: ( seen.append( pathlib.Path( old ).name ), real( new, old ) )[ 1 ] )
    run( flagged )
    assert seen == [ "packet-rick.jsonl", "packet-second.jsonl", "answer-key.json" ]


def test_a_swap_interrupted_after_the_first_packet_is_finished_by_the_next_run( flagged, capsys, monkeypatch ):
    before = snapshot( flagged )
    real   = fi.os.replace
    calls  = []
    def flaky( new, old ):
        calls.append( old )
        if len( calls ) == 2: raise OSError( "disk gone" )
        real( new, old )
    monkeypatch.setattr( fi.os, "replace", flaky )
    with pytest.raises( OSError, match="disk gone" ):
        run( flagged )
    half = snapshot( flagged )
    assert half[ "rick" ] != before[ "rick" ] and half[ "second" ] == before[ "second" ] and half[ "key" ] == before[ "key" ]
    monkeypatch.setattr( fi.os, "replace", real )
    capsys.readouterr()
    assert run( flagged ) == 0
    out   = json.loads( capsys.readouterr().out )
    after = snapshot( flagged )
    assert out[ "recovered" ] == [ "rick" ] and out[ "original_bytes_sha_before" ] == out[ "original_bytes_sha_after" ]
    assert after[ "rick" ] == half[ "rick" ] and after[ "second" ].startswith( before[ "second" ] ) and after[ "key" ] != before[ "key" ]
    assert len( after[ "rick" ].splitlines() ) == len( before[ "rick" ].splitlines() ) + 4 and len( ll.key_rows( flagged.key ) ) == len( json.loads( before[ "key" ] )[ "items" ] ) + 4
    tails = [ [ json.loads( l )[ "item_id" ] for l in after[ r ].decode().splitlines()[ -4: ] ] for r in REVIEWERS ]
    assert sorted( tails[ 0 ] ) == sorted( tails[ 1 ] ) and tails[ 0 ] != tails[ 1 ]
    assert not list( flagged.run_dir.rglob( "*" + fi.NEW_SUFFIX ) )


def test_a_swap_interrupted_before_the_key_leaves_both_packets_done_and_the_next_run_swaps_only_the_key( flagged, capsys, monkeypatch ):
    real  = fi.os.replace
    calls = []
    def flaky( new, old ):
        calls.append( old )
        if len( calls ) == 3: raise OSError( "disk gone" )
        real( new, old )
    monkeypatch.setattr( fi.os, "replace", flaky )
    with pytest.raises( OSError ):
        run( flagged )
    monkeypatch.setattr( fi.os, "replace", real )
    packets = { r: p.read_bytes() for r, p in flagged.packets.items() }
    rows    = len( ll.key_rows( flagged.key ) )
    capsys.readouterr()
    assert run( flagged ) == 0
    assert json.loads( capsys.readouterr().out )[ "recovered" ] == list( REVIEWERS )
    assert { r: p.read_bytes() for r, p in flagged.packets.items() } == packets and len( ll.key_rows( flagged.key ) ) == rows + 4


def test_the_order_seed_names_the_reviewer_and_the_flags( flagged ):
    toy   = flagged.toy
    items = [ lp.pair_item( toy.d[ "d1" ], toy.m[ n ], 3 )[ "item" ] for n in ( "m1", "m2", "m3", "m4", "m5" ) ] + [ lp.pair_item( toy.d[ "d2" ], toy.m[ n ], 3 )[ "item" ] for n in ( "m1", "m2", "m3" ) ]
    def expected( reviewer ):
        order = sorted( ( pk.blind_form( i ) for i in items ), key=lambda i: i[ "item_id" ] )
        import random
        random.Random( f"3|flags|{reviewer}|0" ).shuffle( order )
        return [ i[ "item_id" ] for i in order ]
    assert expected( "rick" ) != expected( "second" )
    for r in REVIEWERS: assert fi.packet_lines( items, r, 3, [] )[ 1 ] == expected( r )


def test_tail_state_reads_an_empty_packet_as_not_finished( ):
    assert fi.tail_state( b"", { "x" } ) == ( False, b"" )


def test_an_empty_packet_takes_the_new_items_alone( flagged ):
    flagged.packets[ "rick" ].write_bytes( b"" )
    assert run( flagged ) == 0
    assert len( flagged.packets[ "rick" ].read_text().splitlines() ) == 4


def test_refuses_a_run_planted_under_another_config( tmp_path, monkeypatch ):
    other = World( tmp_path, config_sha="not-the-frozen-sha" )
    monkeypatch.setattr( fi.frozen, "frozen_path", lambda: other.toy.wiring[ "frozen_path" ] )
    monkeypatch.setattr( fi.frozen, "live_config", lambda: other.toy.cfg )
    with pytest.raises( ValueError, match="planted under config not-the-frozen-sha" ):
        fi.main( [ "--run-dir", str( other.run_dir ), "--record", "none" ], make_parts=lambda *a: pytest.fail( "parts must not be built" ) )


def test_a_failed_check_removes_the_staged_files_and_swaps_nothing( flagged, monkeypatch ):
    def broken( *a ): raise ValueError( "boom" )
    monkeypatch.setattr( fi, "verify", broken )
    before = snapshot( flagged )
    with pytest.raises( ValueError, match="boom" ):
        run( flagged )
    assert snapshot( flagged ) == before and not list( flagged.run_dir.rglob( "*" + fi.NEW_SUFFIX ) )


# ---- verify, one doctored staged file at a time --------------------------------------------------------------------

@pytest.fixture
def staged( flagged ):
    """Stage the files without swapping; return ( the result, the original bytes, the key )."""
    old = { r: p.read_bytes() for r, p in flagged.packets.items() }
    key = json.loads( flagged.key.read_text() )
    got = fi.stage( flagged.run_dir, flagged.owed, fi.label_id_defs( pr.build_pool( pc.build_spec( pc.load_run( flagged.run_dir ), flagged.toy.spec[ "monolith_defs" ],
                    [ *flagged.toy.spec[ "distractors" ], *[ p[ "original" ] for p in flagged.toy.spec[ "planted" ] ] ], {}, [] ), 3 ) ), REVIEWERS, 3 )
    return got, old, key


def test_stage_reports_the_same_original_row_sha_before_and_after( staged ):
    got, _, _ = staged
    assert got[ "before" ] == got[ "after" ] and got[ "added" ] == 4


def test_verify_passes_the_staged_files( staged ):
    got, old, key = staged
    assert fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 4 ) is None


def test_verify_names_a_packet_that_does_not_begin_with_the_original_bytes( staged ):
    got, old, key = staged
    new = got[ "packets" ][ "rick" ]
    new.write_bytes( b"x" + new.read_bytes() )
    with pytest.raises( ValueError, match="does not begin with the original packet bytes" ):
        fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 4 )


def test_verify_names_a_packet_that_adds_the_wrong_number_of_items( staged ):
    got, old, key = staged
    with pytest.raises( ValueError, match="adds 4 items, not 3" ):
        fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 3 )


def test_verify_names_a_packet_line_that_is_not_in_blind_form( staged ):
    got, old, key = staged
    new  = got[ "packets" ][ "rick" ]
    line = json.loads( new.read_text().splitlines()[ -1 ] )
    new.write_bytes( new.read_bytes()[ : -len( json.dumps( line, sort_keys=True ) ) - 1 ] + ( json.dumps( { **line, "answer": True }, sort_keys=True ) + "\n" ).encode() )
    with pytest.raises( Exception, match="PACKET_LEAK" ):
        fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 4 )


def test_verify_names_a_staged_key_that_changed_an_original_row( staged ):
    got, old, key = staged
    path = got[ "key_new" ]
    doc  = json.loads( path.read_text() )
    doc[ "items" ][ next( iter( key[ "items" ] ) ) ][ "stratum" ] = "tampered"
    path.write_text( json.dumps( doc ) )
    with pytest.raises( ValueError, match="changed an original row" ):
        fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 4 )


def test_verify_names_a_staged_key_that_lost_or_gained_rows( staged ):
    got, old, key = staged
    path = got[ "key_new" ]
    doc  = json.loads( path.read_text() )
    doc[ "items" ].pop( next( i for i in doc[ "items" ] if i not in key[ "items" ] ) )
    path.write_text( json.dumps( doc ) )
    with pytest.raises( ValueError, match="the original rows plus the new ones" ):
        fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 4 )


def test_verify_names_a_staged_key_that_changed_a_field_outside_its_items( staged ):
    got, old, key = staged
    path = got[ "key_new" ]
    doc  = json.loads( path.read_text() )
    doc[ "seed" ] = -1
    path.write_text( json.dumps( doc ) )
    with pytest.raises( ValueError, match="outside its items" ):
        fi.verify( got[ "packets" ], got[ "key_new" ], old, key, 4 )


def test_swap_replaces_each_file_and_discard_removes_the_staged_ones( tmp_path ):
    old, new = tmp_path / "a", tmp_path / "a.new"
    old.write_text( "old" )
    new.write_text( "new" )
    fi.swap( [ ( new, old ) ] )
    assert old.read_text() == "new" and not new.exists()
    new.write_text( "again" )
    fi.discard( [ ( new, old ) ] )
    fi.discard( [ ( new, old ) ] )
    assert not new.exists() and old.read_text() == "new"
