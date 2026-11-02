"""
Unit tests for the judge-alone stage of the first-thousand trial, on fakes.

Files are small fixtures in a temp folder, and the transport is a stand-in that answers the two questions of a pack.
"""
import hashlib
import itertools
import json
import os
import subprocess
import types
from unittest import mock

import pytest

from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import stage_c as sc

SERIAL = itertools.count( 1 )


@pytest.fixture( autouse=True )
def restore_environment():
    """Ensures: os.environ is restored after each test, since a live run writes into it."""
    with mock.patch.dict( os.environ ): yield


def rec( n, doc="does a thing", **more ):
    """Return an index record with a file, a line range and a pin."""
    return { "id": f"src.m{n}.f{n}", "sig": f"( a{n} )", "doc": doc, "file": f"src/m{n}.py", "name": f"f{n}", "lang": "py", "pin": f"pin{n}", "line": 1, "end_line": 2, **more }


def lines_of( n ):
    """Return the two source lines of record n, indented as a method body would be."""
    return [ f"    def f{n}( a{n} ):", f"        return {n}   " ]


def source_lines( file ):
    """Return the lines of a fixture file src/m<n>.py."""
    return lines_of( int( file.split( "/m" )[ 1 ].split( "." )[ 0 ] ) )


def pair( n, a, b, **more ):
    """Return one pair as read_pairs builds it, with side texts that match records a and b."""
    return { "pair": f"pair-{n}", "stratum": "flag", "label": sc.SAME_JOB, "unsure": False, "raters": 2, "a_id": f"d-a{n}", "b_id": f"d-b{n}",
             "a_text": "\n".join( lines_of( a ) ), "b_text": "\n".join( lines_of( b ) ), **more }


def world( count=4 ):
    """Return ( records, index, by_id, purposes ) for records 1 to count, all with purpose lines."""
    records = [ rec( n ) for n in range( 1, count + 1 ) ]
    return records, sc.text_index( records, source_lines ), { r[ "id" ]: r for r in records }, { r[ "pin" ]: f"line {r[ 'pin' ]}" for r in records }


def test_norm_text_dedents_and_trims_trailing_space_and_outer_blank_lines():
    assert sc.norm_text( "\n    def f():   \n        return 1\n\n" ) == "def f():\n    return 1"
    assert sc.norm_text( "\n".join( lines_of( 1 ) ) ) == sc.norm_text( "def f1( a1 ):\n    return 1" )


def test_the_text_index_maps_texts_to_ids_skips_records_without_a_range_and_shows_ambiguity():
    twin   = rec( 1 ) | { "id": "src.other.twin" }
    nolines = rec( 3, line=None, end_line=None )
    index  = sc.text_index( [ rec( 1 ), twin, rec( 2 ), nolines ], source_lines )
    assert index[ sc.norm_text( "\n".join( lines_of( 1 ) ) ) ] == [ "src.m1.f1", "src.other.twin" ]
    assert len( index ) == 2 and sc.norm_text( "\n".join( lines_of( 3 ) ) ) not in index
    assert sc.text_index( [ rec( 1, line=1, end_line=None ) ], source_lines ) == { }, "a record needs both ends of its range"


def test_git_source_lines_asks_git_once_per_file_and_gives_no_lines_for_a_file_git_cannot_show():
    runs = [ types.SimpleNamespace( returncode=0, stdout="a\nb\n" ), types.SimpleNamespace( returncode=128, stdout="" ) ]
    with mock.patch.object( sc.subprocess, "run", side_effect=runs ) as run:
        read = sc.git_source_lines( "/repo", "abc123" )
        assert read( "x.py" ) == [ "a", "b" ] and read( "x.py" ) == [ "a", "b" ] and read( "gone.py" ) == []
    assert run.call_count == 2 and run.call_args_list[ 0 ][ 0 ][ 0 ] == [ "git", "-C", "/repo", "show", "abc123:x.py" ]


def test_git_source_lines_reads_a_real_commit( tmp_path ):
    env = { **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org" }
    subprocess.run( [ "git", "init", "-q", str( tmp_path ) ], check=True )
    ( tmp_path / "f.py" ).write_text( "one\ntwo\n", encoding="utf-8" )
    subprocess.run( [ "git", "-C", str( tmp_path ), "add", "f.py" ], check=True )
    subprocess.run( [ "git", "-C", str( tmp_path ), "commit", "-q", "-m", "x" ], check=True, env=env )
    sha = subprocess.run( [ "git", "-C", str( tmp_path ), "rev-parse", "HEAD" ], capture_output=True, text=True, check=True ).stdout.strip()
    ( tmp_path / "f.py" ).write_text( "changed\n", encoding="utf-8" )
    read = sc.git_source_lines( tmp_path, sha )
    assert read( "f.py" ) == [ "one", "two" ] and read( "none.py" ) == []


def label_folder( tmp_path ):
    """Return ( labels_dir, answer_key, shas ): the pinned file names holding known bytes."""
    shas = { }
    for name in sc.control_report.LABEL_FILES:
        ( tmp_path / name ).write_text( name, encoding="utf-8" )
        shas[ name ] = hashlib.sha256( name.encode() ).hexdigest()
    ( tmp_path / "answer-key.json" ).write_text( "{}", encoding="utf-8" )
    shas[ "answer-key.json" ] = hashlib.sha256( b"{}" ).hexdigest()
    return str( tmp_path ), str( tmp_path / "answer-key.json" ), shas


def test_the_pins_name_each_changed_file_and_can_be_replaced_or_skipped( tmp_path ):
    folder, key, shas = label_folder( tmp_path )
    sc.check_pins( folder, key, shas )
    sc.check_pins( folder, key, None )
    with pytest.raises( er.NeedsetError ) as e: sc.check_pins( folder, key )
    assert e.value.code == er.CONTROL_LABELS_CHANGED and "labels-rick.jsonl" in str( e.value ) and "answer-key.json" in str( e.value )
    ( tmp_path / "labels-jason.jsonl" ).write_text( "edited", encoding="utf-8" )
    with pytest.raises( er.NeedsetError ) as e: sc.check_pins( folder, key, shas )
    assert "labels-jason.jsonl" in str( e.value ) and "labels-rick.jsonl" not in str( e.value )


def test_the_real_pins_hold_the_names_this_stage_reads():
    assert set( sc.control_report.LABEL_PINS ) == { *sc.control_report.LABEL_FILES, sc.control_report.KEY_FILE }


def test_read_pairs_keeps_three_strata_and_settles_label_raters_and_unsure( tmp_path ):
    items   = { "i1": { "stratum": "flag", "a": "d-1", "b": "d-2" }, "i2": { "stratum": "monolith:structural", "a": "d-3", "b": "d-4" }, "i3": { "stratum": "other", "a": "d-5", "b": "d-6" },
                "i4": { "stratum": "monolith:neighbour", "a": "d-7", "b": "d-8" } }
    key     = tmp_path / "key.json"
    key.write_text( json.dumps( { "items": items } ), encoding="utf-8" )
    packet  = tmp_path / "packet.jsonl"
    packet.write_text( "\n".join( json.dumps( { "item_id": i, "payload": { "a": f"A {i}", "b": f"B {i}" } } ) for i in items ) + "\n", encoding="utf-8" )
    resolved = { "d-1|d-2": True, "d-3|d-4": False, "d-5|d-6": True, "d-7|d-8": True }
    unsure   = sc.pl.UNSURE_PREFIX + " not sure"
    reads    = iter( [ [ { "item_id": "i1", "note": unsure } ], [ { "item_id": "i1", "note": "" }, { "item_id": "i2", "note": "" } ], [ { "item_id": "i4", "note": "" } ] ] )
    with mock.patch.object( sc.label_load, "resolved_labels", return_value=resolved ) as res, mock.patch.object( sc.pk, "read_labels", side_effect=lambda path: next( reads ) ):
        got = sc.read_pairs( str( key ), str( packet ), "/labels", None )
    assert [ g[ "pair" ] for g in got ] == [ "i1", "i2", "i4" ]
    assert [ g[ "label" ] for g in got ] == [ sc.SAME_JOB, sc.NOT_SAME, sc.SAME_JOB ]
    assert [ g[ "unsure" ] for g in got ] == [ True, False, False] and [ g[ "raters" ] for g in got ] == [ 2, 2, 3 ]
    assert got[ 0 ] | { "x": 1 } == { "pair": "i1", "stratum": "flag", "label": sc.SAME_JOB, "unsure": True, "raters": 2, "a_id": "d-1", "b_id": "d-2", "a_text": "A i1", "b_text": "B i1", "x": 1 }
    assert res.call_args[ 0 ][ :2 ] == ( "/labels/labels-rick.jsonl", "/labels/labels-reviewer-2.jsonl" ) and res.call_args[ 1 ] == { "third_path": "/labels/labels-jason.jsonl" }


def test_read_pairs_refuses_changed_label_files_before_reading_anything( tmp_path ):
    folder, key, _shas = label_folder( tmp_path )
    ( tmp_path / "labels-rick.jsonl" ).write_text( "edited", encoding="utf-8" )
    with mock.patch.object( sc.label_load, "resolved_labels", side_effect=AssertionError( "nothing is read" ) ):
        with pytest.raises( er.NeedsetError ) as e: sc.read_pairs( key, str( tmp_path / "p" ), folder )
    assert e.value.code == er.CONTROL_LABELS_CHANGED


def test_prepare_side_gives_the_record_its_line_and_the_text_the_judge_reads():
    r = rec( 1, sig='( a, mode="x" )' )
    got = sc.prepare_side( r, { "pin1": "Do the first thing." } )
    assert got[ "reason"] is None and got[ "has_doc" ] and got[ "has_purpose" ] and got[ "record" ][ "purpose" ] == "Do the first thing."
    assert got[ "record" ][ "sig" ] == "( a, mode=… )".replace( "… )", "…)" ), "string defaults are blanked as the lookup blanks them"
    assert got[ "text" ] == rt.entry_text( got[ "record" ] ) and "Do the first thing." in got[ "text" ] and "mode=\"x\"" not in got[ "text" ]
    assert "purpose" not in r, "the index record is not changed"


def test_prepare_side_names_a_missing_or_empty_purpose_line_and_a_record_the_screen_drops():
    for purposes in ( { }, { "pin1": "" } ):
        got = sc.prepare_side( rec( 1, doc="" ), purposes )
        assert got[ "reason" ] == sc.NO_PURPOSE and got[ "text" ] is None and got[ "record" ] is not None and not got[ "has_purpose" ] and not got[ "has_doc" ]
    dropped = sc.prepare_side( rec( 1, doc="Mail alice@example.org to ask." ), { "pin1": "line" } )
    assert dropped[ "reason" ] == sc.DROPPED and dropped[ "record" ] is None and dropped[ "text" ] is None and dropped[ "has_doc" ] and dropped[ "has_purpose" ]
    assert sc.prepare_side( rec( 1, doc="Mail alice@example.org to ask." ), { } )[ "has_purpose" ] is False


def test_split_pairs_keeps_whole_pairs_and_refuses_each_other_with_every_reason():
    _records, index, by_id, purposes = world( 5 )
    twin_index = dict( index )
    twin_index[ sc.norm_text( "\n".join( lines_of( 5 ) ) ) ] = [ "src.m5.f5", "src.other.twin" ]
    pairs = [ pair( 1, 1, 2 ), pair( 2, 1, 3, label=sc.NOT_SAME, stratum="monolith:structural", unsure=True, raters=3 ), pair( 3, 4, 9 ), pair( 4, 8, 9 ), pair( 5, 2, 2 ),
              pair( 6, 5, 1 ) ]
    purposes_missing = { k: v for k, v in purposes.items() if k != "pin3" }
    rows, refused, sides = sc.split_pairs( pairs, twin_index, by_id, purposes_missing )
    assert [ r[ "pair" ] for r in rows ] == [ "pair-1", "pair-6" ] and rows[ 1 ][ "ambiguous" ] is True and rows[ 0 ][ "ambiguous" ] is False
    assert rows[ 0 ][ "need_seed" ] == by_id[ "src.m1.f1" ] and rows[ 0 ][ "side_a" ][ "record" ][ "purpose" ] == "line pin1" and rows[ 0 ][ "side_b" ][ "record" ][ "id" ] == "src.m2.f2"
    why = { r[ "pair" ]: r[ "reasons" ] for r in refused }
    assert why[ "pair-2" ] == [ "side b no_purpose_line: src.m3.f3" ] and why[ "pair-3" ] == [ "side b text matches no index record" ]
    assert why[ "pair-4" ] == [ "side a text matches no index record", "side b text matches no index record" ]
    assert why[ "pair-5" ] == [ "same_record: both sides are src.m2.f2" ]
    assert len( sides ) == 12 and [ s[ "reason" ] for s in sides if s[ "pair" ] == "pair-4" ] == [ sc.UNMATCHED, sc.UNMATCHED ]
    row = rows[ 0 ]
    assert row[ "stratum" ] == "flag" and row[ "label" ] == sc.SAME_JOB and row[ "raters" ] == 2 and row[ "unsure" ] is False


def test_split_pairs_carries_the_pairs_fields_into_the_row():
    _records, index, by_id, purposes = world( 3 )
    rows, refused, _sides = sc.split_pairs( [ pair( 1, 1, 2, label=sc.NOT_SAME, stratum="monolith:neighbour", unsure=True, raters=3 ) ], index, by_id, purposes )
    assert refused == [ ] and ( rows[ 0 ][ "stratum" ], rows[ 0 ][ "label" ], rows[ 0 ][ "unsure" ], rows[ 0 ][ "raters" ] ) == ( "monolith:neighbour", sc.NOT_SAME, True, 3 )


def test_the_audit_counts_and_names_each_side_that_did_not_arrive_in_full():
    side = lambda **m: { "pair": "p", "stratum": "flag", "side": "a", "id": "i", "matched": True, "has_doc": True, "has_purpose": True, "ambiguous": False, "reason": None } | m
    got  = sc.audit_sides( [ side(), side( side="b", has_doc=False ), side( matched=False, id=None, has_doc=None, has_purpose=None, reason=sc.UNMATCHED ),
                             side( has_purpose=False, reason=sc.NO_PURPOSE ), side( reason=sc.DROPPED ) ] )
    assert ( got[ "sides" ], got[ "matched" ], got[ "with_docstring" ], got[ "with_purpose_line" ] ) == ( 5, 4, 3, 3 )
    assert [ n[ "why" ] for n in got[ "named" ] ] == [ [ "no docstring" ], [ "no index record" ], [ "no purpose line" ], [ "dropped by the screen" ] ]
    assert sc.audit_sides( [ ] ) == { "sides": 0, "matched": 0, "with_docstring": 0, "with_purpose_line": 0, "named": [ ] }


def test_the_plan_counts_calls_shows_every_purpose_line_and_lists_the_refused():
    _records, index, by_id, purposes = world( 3 )
    rows, refused, sides = sc.split_pairs( [ pair( 1, 1, 2 ), pair( 2, 3, 1, label=sc.NOT_SAME, stratum="monolith:neighbour" ), pair( 3, 1, 9 ) ], index, by_id, purposes )
    plan = sc.plan_of( rows, refused, sides )
    assert ( plan[ "pairs_total" ], plan[ "pairs_judged" ] ) == ( 3, 2 ) and plan[ "by_stratum" ] == { "flag": 1, "monolith:neighbour": 1 } and plan[ "by_label" ] == { "same_job": 1, "not_same": 1 }
    assert plan[ "calls" ] == { "drafts_min": 2, "drafts_max": 4, "posts": 6, "post_budget": sc.POST_BUDGET } and plan[ "ambiguous" ] == [ ]
    assert plan[ "refused" ] == [ { "pair": "pair-3", "stratum": "flag", "label": sc.SAME_JOB, "reasons": [ "side b text matches no index record" ] } ]
    assert plan[ "shown" ][ 0 ] == { "pair": "pair-1", "side": "a", "id": "src.m1.f1", "purpose_line": "line pin1" } and len( plan[ "shown" ] ) == 4
    assert plan[ "audit" ][ "sides" ] == 6 and plan[ "audit" ][ "matched" ] == 5 and [ n[ "pair" ] for n in plan[ "audit" ][ "named" ] ] == [ "pair-3" ]
    assert sc.plan_of( rows, refused, sides, 9 )[ "calls" ][ "post_budget" ] == 9


def test_the_cue_is_a_shared_name_piece_between_the_need_and_side_b():
    side_b = sc.prepare_side( rec( 1, name="stopPolling", id="src.js.stopPolling" ), { "pin1": "Stop the poll loop." } )
    assert sc.cue_of( "Stop the polling timer when the view closes.", side_b ) is True
    assert sc.cue_of( "Cancel the repeated background fetch.", side_b ) is False


def make_row( n=1, **more ):
    """Return one judged row built from a world, side a record n and side b record n + 1."""
    _records, index, by_id, purposes = world( n + 1 )
    rows, _r, _s = sc.split_pairs( [ pair( n, n, n + 1, **more ) ], index, by_id, purposes )
    return rows[ 0 ]


def test_the_draft_job_seeds_side_a_keys_side_b_and_writes_in_the_seeds_language():
    row  = make_row()
    seen = []
    job  = sc.draft_job( row, lambda r: seen.append( r ) or { "kind": "function", "text": "t", "forbidden": [ ] } )
    assert job[ "seed" ] is row[ "need_seed" ] and seen == [ row[ "need_seed" ] ] and job[ "keys" ] == [ row[ "side_b" ][ "record" ] ]
    assert job[ "write_lang" ] == "py" and job[ "meta" ] == { "stage_c": "pair-1" } and job[ "stripped" ][ "kind" ] == "function"
    assert job[ "seed" ][ "id" ] != job[ "keys" ][ 0 ][ "id" ]


def test_a_request_holds_side_b_then_side_a_under_the_production_template_and_its_own_repeat():
    row  = make_row( unsure=True, raters=3 )
    reqs = [ sc.request_for( row, "need one", n ) for n in sc.REPEATS ]
    assert [ e[ "id" ] for e in reqs[ 0 ][ "entries" ] ] == [ "src.m2.f2", "src.m1.f1" ] and reqs[ 0 ][ "arm" ] == sc.STAGE_NAME
    assert reqs[ 0 ][ "entries" ][ 0 ] is row[ "side_b" ][ "record" ] and reqs[ 0 ][ "entries" ][ 1 ] is row[ "side_a" ][ "record" ]
    assert [ r[ "repeat" ] for r in reqs ] == [ 1, 2, 3 ] and reqs[ 0 ][ "template" ][ "criteria" ] == rt.PROMPT_TEMPLATE[ "criteria" ] and reqs[ 1 ][ "template" ][ "instructions" ].endswith( "(repeat 2)" )
    assert sc.jp.distinct_bodies( reqs ) == 3
    assert ( reqs[ 0 ][ "stratum" ], reqs[ 0 ][ "unsure" ], reqs[ 0 ][ "raters" ], reqs[ 0 ][ "label" ] ) == ( "flag", True, 3, sc.SAME_JOB ) and reqs[ 0 ][ "cue" ] is False


def fake_send( p_b, p_a ):
    """Return a send function that answers side b with p_b and side a with p_a."""
    def send( transport, need, entries, template, model, budget ):
        probs = { entries[ 0 ][ "id" ]: { "reuse": 0.0, "extend": p_b, "unrelated": 1 - p_b }, entries[ 1 ][ "id" ]: { "reuse": 0.0, "extend": p_a, "unrelated": 1 - p_a } }
        return { "answers": [ { "id": i, "probabilities": p } for i, p in probs.items() ], "rows": [ { "request_hash": f"h-{next( SERIAL )}", "status": "answered", "tokens_in": 100 } ] }
    return send


def test_ask_pair_names_side_b_and_side_a_and_keeps_the_pairs_fields():
    got = sc.ask_pair( None, sc.request_for( make_row( unsure=True, raters=3 ), "need", 2 ), None, fake_send( 0.4, 0.9 ) )
    assert got[ "side_b" ] == { "answered": True, "p_overlap": 0.4, "confidence": 0.6, "choice": "unrelated" } and got[ "side_a" ][ "p_overlap" ] == 0.9 and got[ "side_a" ][ "choice" ] == "extend"
    assert ( got[ "pair" ], got[ "stratum" ], got[ "label" ], got[ "unsure" ], got[ "raters" ], got[ "repeat" ], got[ "cue" ] ) == ( "pair-1", "flag", sc.SAME_JOB, True, 3, 2, False )
    assert got[ "request_hash" ].startswith( "h-" ) and got[ "tokens_in" ] == 100 and got[ "plant" ] == got[ "side_b" ]


def test_draft_all_keeps_passed_needs_and_names_the_pairs_without_one():
    rows  = [ make_row( 1 ), make_row( 2, label=sc.NOT_SAME, stratum="monolith:neighbour", unsure=True, raters=3 ) ]
    reply = iter( [ { "ok": True, "need": "a sentence" }, { "ok": False, "reason": er.NEED_LEAKS_KEY } ] )
    with mock.patch.object( sc.draft, "draft_need", side_effect=lambda job, ask, ledger: next( reply ) ) as dn:
        needs, undrafted = sc.draft_all( rows, lambda r: { "kind": "k", "text": "t", "forbidden": [ ] }, "ask", "ledger" )
    assert needs == { "pair-1": "a sentence" } and dn.call_args[ 0 ][ 1:] == ( "ask", "ledger" )
    assert undrafted == [ { "pair": "pair-2", "stratum": "monolith:neighbour", "label": sc.NOT_SAME, "unsure": True, "raters": 3, "reason": er.NEED_LEAKS_KEY } ]


def argv( tmp_path, *more ):
    """Return a full command line for the stage."""
    names = ( "root", "run-dir", "answer-key", "packet", "labels-dir", "symbols", "purposes", "source-commit" )
    return [ x for n in names for x in ( "--" + n, str( tmp_path / n ) ) ] + list( more )


def test_the_command_line_needs_its_inputs_and_defaults_to_a_plan( tmp_path ):
    args = sc.parse_args( argv( tmp_path ) )
    assert args.live is False and args.run_name is None and args.limit == sc.DRAFT_BUDGET + sc.POST_BUDGET and args.post_budget == sc.POST_BUDGET and args.draft_budget == sc.DRAFT_BUDGET
    assert args.server == "max-plan" and args.ceiling == sc.jp.CEILING and args.cli_path is None and args.from_run is None
    with pytest.raises( SystemExit ): sc.parse_args( [ "--live" ] )


def test_collect_rows_reads_the_symbols_and_purposes_and_splits_the_pairs( tmp_path ):
    records = [ rec( 1 ), rec( 2 ) ]
    ( tmp_path / "symbols" ).write_text( "\n".join( json.dumps( r ) for r in records ) + "\n", encoding="utf-8" )
    ( tmp_path / "purposes" ).write_text( "\n".join( json.dumps( { "pin": r[ "pin" ], "purpose": f"line {r[ 'pin' ]}" } ) for r in records ) + "\n", encoding="utf-8" )
    args = sc.parse_args( argv( tmp_path ) )
    with mock.patch.object( sc, "read_pairs", return_value=[ pair( 1, 1, 2 ) ] ) as rp:
        rows, refused, sides = sc.collect_rows( args, { "source_lines": source_lines, "expected_shas": None } )
        sc.collect_rows( args, { "source_lines": source_lines } )
    assert [ r[ "pair" ] for r in rows ] == [ "pair-1" ] and refused == [ ] and len( sides ) == 2
    assert rp.call_args_list[ 0 ][ 0 ][ 3 ] is None and rp.call_args_list[ 1 ][ 0 ][ 3 ] == "pinned"
    with mock.patch.object( sc, "read_pairs", return_value=[ pair( 1, 1, 2 ) ] ), mock.patch.object( sc, "git_source_lines", return_value=source_lines ) as git:
        sc.collect_rows( args, { } )
    assert git.call_args[ 0 ] == ( str( tmp_path / "root" ), str( tmp_path / "source-commit" ) )


def test_a_plan_prints_and_contacts_nothing( tmp_path ):
    rows, refused, sides = sc.split_pairs( [ pair( 1, 1, 2 ), pair( 2, 1, 9 ) ], *world( 3 )[ 1: ] )
    with mock.patch.object( sc, "collect_rows", return_value=( rows, refused, sides ) ), mock.patch.object( sc.draft, "drafter_call", side_effect=AssertionError( "no drafter" ) ), \
         mock.patch.object( sc.jp, "ask_request", side_effect=AssertionError( "no judge" ) ), mock.patch.object( sc, "live", side_effect=AssertionError( "no live run" ) ):
        out = sc.main( argv( tmp_path ) )
    assert out[ "live" ] is False and out[ "plan" ][ "pairs_judged" ] == 1 and out[ "plan" ][ "refused" ][ 0 ][ "pair" ] == "pair-2"
    assert not ( tmp_path / "run-dir" ).exists(), "a plan writes nothing"


def test_a_live_run_is_refused_without_a_run_name_a_from_run_and_a_cli_path( tmp_path ):
    with mock.patch.object( sc, "collect_rows", return_value=( [ ], [ ], [ ] ) ), mock.patch.object( sc, "live", side_effect=AssertionError( "refused first" ) ):
        for more, code in ( ( [ ], er.BAD_NEED ), ( [ "--run-name", "n" ], er.BAD_NEED ), ( [ "--from-run", "f" ], er.BAD_NEED ), ( [ "--run-name", "n", "--from-run", "f" ], er.NO_CLI_PATH ) ):
            with pytest.raises( er.NeedsetError ) as e: sc.main( argv( tmp_path, "--live", *more ) )
            assert e.value.code == code


def live_parts( tmp_path ):
    """Return ( deps, state ) for a live run on stand-ins."""
    ( tmp_path / "from-run" ).mkdir( exist_ok=True )
    ( tmp_path / "from-run" / "run-env.sh" ).write_text( "export LUPIN_REUSE_JEV_PACK_SIZE=50\nexport LUPIN_REUSE_JEV_TOKEN_CEILING=1\nexport LUPIN_REUSE_JEV_RUN_NAME=old\n", encoding="utf-8" )
    state = { "closed": 0, "asked": [], "stripped": [] }
    ctx   = types.SimpleNamespace( transport=types.SimpleNamespace( budget="B" ) )

    def close( c ):
        state[ "closed" ] += 1
        return "needset-stage-c-x"
    def context( root ):
        state[ "context_root" ] = root
        return ctx
    def ask( request ):
        state[ "asked" ].append( request )
        return { "pair": request[ "pair" ], "label": request[ "label" ], "arm": request[ "arm" ], "repeat": request[ "repeat" ], "request_hash": f"h-{next( SERIAL )}", "status": "answered", "tokens_in": 9,
                 "plant": { "answered": True, "p_overlap": 0.5, "confidence": 0.5, "choice": "extend" }, "original": { "answered": True, "p_overlap": 0.6, "confidence": 0.6, "choice": "extend" } }
    return { "source_root": lambda a: tmp_path / "source-tree", "context": context, "close_run": close, "ask": ask, "drafter": lambda system, user: "unused" }, state


def live_argv( tmp_path, *more ):
    """Return the live command line."""
    return argv( tmp_path, "--live", "--run-name", "needset-stage-c-x", "--from-run", str( tmp_path / "from-run" ), "--cli-path", "/x/claude", *more )


def stand_ins( tmp_path, rows, undrafted_pair=None, refused=() ):
    """Return the patches that replace the files, the drafter ledger and the strip step."""
    def draft_need( job, ask, ledger ):
        if job[ "meta" ][ "stage_c" ] == undrafted_pair: return { "ok": False, "reason": er.NEED_LEAKS_KEY }
        return { "ok": True, "need": f"Need for {job[ 'meta' ][ 'stage_c' ]}." }
    return [ mock.patch.object( sc, "collect_rows", return_value=( rows, list( refused ), [ ] ) ), mock.patch.object( sc.draft, "draft_need", side_effect=draft_need ),
             mock.patch.object( sc.draft, "make_ledger", return_value="ledger" ), mock.patch.object( sc.strip, "strip_member", side_effect=lambda r, root: { "kind": "k", "text": "t", "forbidden": [ ] } ),
             mock.patch.object( rt, "prepare" ) ]


def run_live( tmp_path, deps, rows, undrafted_pair=None, refused=() ):
    """Run a live stage on stand-ins and return its result."""
    patches = stand_ins( tmp_path, rows, undrafted_pair, refused )
    for p in patches: p.start()
    try:
        return sc.main( live_argv( tmp_path ), deps )
    finally:
        for p in patches: p.stop()


def test_a_live_run_drafts_posts_every_repeat_writes_the_report_and_closes_the_run( tmp_path ):
    deps, state = live_parts( tmp_path )
    rows = [ make_row( 1 ), make_row( 2, label=sc.NOT_SAME ), make_row( 3 ) ]
    ( tmp_path / "run-dir" ).mkdir()
    refused = [ { "pair": "pair-9", "stratum": "flag", "label": sc.NOT_SAME, "reasons": [ "side a text matches no index record" ] } ]
    out = run_live( tmp_path, deps, rows, undrafted_pair="pair-2", refused=refused )
    assert out[ "live" ] is True and out[ "closed_run" ] == "needset-stage-c-x" and out[ "close_error" ] is None and out[ "report" ][ "status" ] == sc.jp.DONE
    assert [ ( r[ "pair" ], r[ "repeat" ] ) for r in state[ "asked" ] ] == [ ( "pair-1", 1 ), ( "pair-1", 2 ), ( "pair-1", 3 ), ( "pair-3", 1 ), ( "pair-3", 2 ), ( "pair-3", 3 ) ]
    assert state[ "asked" ][ 0 ][ "need" ] == "Need for pair-1." and state[ "closed" ] == 1 and state[ "context_root" ] == tmp_path / "source-tree"
    assert [ u[ "pair" ] for u in out[ "undrafted" ] ] == [ "pair-2" ] and out[ "undrafted" ][ 0 ][ "reason" ] == er.NEED_LEAKS_KEY
    saved = json.loads( ( tmp_path / "run-dir" / sc.REPORT_FILE ).read_text( encoding="utf-8" ) )
    assert saved[ "undrafted" ][ 0 ][ "pair" ] == "pair-2" and saved[ "refused" ] == refused and out[ "plan" ][ "pairs_total" ] == 4 and len( saved[ "results" ] ) == 6 and saved[ "status" ] == "done"
    assert os.environ[ rt.RUN_NAME_VARIABLE ] == "needset-stage-c-x" and os.environ[ rt.CEILING_VARIABLE ] == str( sc.jp.CEILING ) and sc.exit_status( out ) == 0


def test_a_live_run_uses_the_transport_and_real_drafter_when_no_stand_ins_are_given( tmp_path ):
    deps, state = live_parts( tmp_path )
    for k in ( "ask", "drafter" ): del deps[ k ]
    row = make_row( 1 )
    seen = []

    def post( transport, request, budget ):
        seen.append( ( transport.budget, budget ) )
        return live_parts( tmp_path )[ 0 ][ "ask" ]( request )
    with mock.patch.object( sc, "ask_pair", post ), mock.patch.object( sc.draft, "drafter_call", return_value=lambda s, u: "reply" ) as dc:
        out = run_live( tmp_path, deps, [ row ] )
    dc.assert_called_once()
    assert out[ "report" ][ "status" ] == sc.jp.DONE and seen == [ ( "B", "B" ) ] * 3 and state[ "closed" ] == 1


def test_a_live_run_that_fails_still_closes_the_run_and_a_failed_close_is_reported( tmp_path, capsys ):
    deps, state = live_parts( tmp_path )
    with mock.patch.object( sc, "collect_rows", return_value=( [ make_row() ], [ ], [ ] ) ), mock.patch.object( rt, "prepare", side_effect=RuntimeError( "no index" ) ):
        with pytest.raises( RuntimeError, match="no index" ): sc.main( live_argv( tmp_path ), deps )
    assert state[ "closed" ] == 1
    deps[ "close_run" ] = lambda c: ( _ for _ in () ).throw( OSError( "ledger gone" ) )
    with mock.patch.object( sc, "collect_rows", return_value=( [ make_row() ], [ ], [ ] ) ), mock.patch.object( rt, "prepare", side_effect=RuntimeError( "no index" ) ):
        with pytest.raises( RuntimeError, match="no index" ): sc.main( live_argv( tmp_path ), deps )
    assert "close_run failed while another error was raised" in capsys.readouterr().out
    ( tmp_path / "run-dir" ).mkdir( exist_ok=True )
    out = run_live( tmp_path, deps, [ make_row() ] )
    assert out[ "closed_run" ] is None and "ledger gone" in out[ "close_error" ] and sc.exit_status( out ) == 1


def test_a_live_run_makes_and_releases_its_own_source_tree_when_none_is_given( tmp_path ):
    deps, _state = live_parts( tmp_path )
    del deps[ "source_root" ]
    with mock.patch.object( sc.source_at, "ensure_worktree", return_value=tmp_path / "tree" ) as make, mock.patch.object( sc.source_at, "unlock" ) as unlock:
        run_live( tmp_path, deps, [ make_row() ] )
    make.assert_called_once()
    assert make.call_args[ 0 ] == ( str( tmp_path / "root" ), str( tmp_path / "source-commit" ) ) and unlock.call_args[ 0 ] == ( str( tmp_path / "root" ), tmp_path / "tree" )


def test_a_live_run_that_uses_the_environment_context_builds_it_on_the_source_tree( tmp_path ):
    deps, state = live_parts( tmp_path )
    del deps[ "context" ]
    ctx = types.SimpleNamespace( transport=types.SimpleNamespace( budget="B" ) )
    with mock.patch.object( rt, "context_from_environment", return_value=ctx ) as make:
        run_live( tmp_path, deps, [ make_row() ] )
    make.assert_called_once_with( tmp_path / "source-tree" )
    del deps[ "close_run" ]
    closed_before = state[ "closed" ]
    with mock.patch.object( rt, "context_from_environment", return_value=ctx ), mock.patch.object( rt, "close_run", return_value="closed-by-rt" ) as close:
        out = run_live( tmp_path, deps, [ make_row() ] )
    close.assert_called_once_with( ctx )
    assert out[ "closed_run" ] == "closed-by-rt" and state[ "closed" ] == closed_before


def test_the_cap_ends_a_live_run_with_a_report_and_the_exit_status_says_so( tmp_path ):
    deps, _state = live_parts( tmp_path )
    ( tmp_path / "run-dir" ).mkdir()
    deps[ "ask" ] = lambda request: (_ for _ in () ).throw( er.NeedsetError( er.CALL_CAP_REACHED, "cap" ) )
    out = run_live( tmp_path, deps, [ make_row() ] )
    assert out[ "report" ][ "status" ] == sc.jp.CAP and sc.exit_status( out ) == sc.first_thousand.EXIT_CAP_REACHED


def test_run_cli_prints_the_plan_as_json_and_returns_zero( tmp_path ):
    printed = [ ]
    with mock.patch.object( sc, "collect_rows", return_value=( [ ], [ ], [ ] ) ):
        code = sc.run_cli( argv( tmp_path ), { }, printed.append )
    assert code == 0 and json.loads( printed[ 0 ] )[ "plan" ][ "pairs_judged" ] == 0


class Capture:
    """A transport that keeps each body sent and answers every question with one overlap."""

    def __init__( self ):
        self.bodies = [ ]

    def post_with_meta( self, body ):
        self.bodies.append( body )
        probs = { "reuse": 0.0, "extend": 0.5, "unrelated": 0.5 }
        return { "answers": { k: { "probabilities": dict( probs ) } for k in body[ "questions" ] }, "model": body[ "model" ], "usage": { "input_tokens": 50, "output_tokens": 5 } }, \
               { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1 }


def test_the_real_send_carries_both_purpose_lines_the_need_and_the_repeat_token_in_the_posted_body():
    row, wire = make_row( unsure=True ), Capture()
    got = sc.ask_pair( wire, sc.request_for( row, "Read a feed and list its articles.", 2 ) )
    body = json.dumps( wire.bodies[ 0 ], sort_keys=True )
    assert len( wire.bodies ) == 1 and got[ "status" ] == "answered" and got[ "tokens_in" ] == 50 and got[ "side_b" ][ "answered" ] and got[ "side_a" ][ "answered" ]
    assert row[ "side_a" ][ "record" ][ "purpose" ] in body and row[ "side_b" ][ "record" ][ "purpose" ] in body and "line pin1" in body and "line pin2" in body
    assert "Read a feed and list its articles." in body and "(repeat 2)" in body and "(repeat 1)" not in body
    assert row[ "side_a" ][ "record" ][ "id" ] in body and row[ "side_b" ][ "record" ][ "id" ] in body
    assert len( wire.bodies[ 0 ][ "questions" ] ) == 2, "one post holds both sides' questions"
