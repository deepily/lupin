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
from pathlib import Path
from unittest import mock

import pytest

from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import stage_c as sc

SERIAL = itertools.count( 1 )


@pytest.fixture( autouse=True )
def restore_environment():
    """Ensures: os.environ is restored after each test, since a live run writes into it."""
    saved = sc.model_transport.CLI_PATH
    with mock.patch.dict( os.environ ): yield
    sc.model_transport.CLI_PATH = saved


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
    plan = sc.plan_of( rows, refused, sides, sc.budgets_for( rows ) )
    assert ( plan[ "pairs_total" ], plan[ "pairs_judged" ] ) == ( 3, 2 ) and plan[ "by_stratum" ] == { "flag": 1, "monolith:neighbour": 1 } and plan[ "by_label" ] == { "same_job": 1, "not_same": 1 }
    assert plan[ "calls" ] == { "drafts_min": 2, "drafts_max": 4, "posts": 6, "posts_if_shared": 6 } and plan[ "ambiguous" ] == [ ]
    assert plan[ "budgets" ] == sc.budgets_for( rows ) and plan[ "budgets" ][ "drafts_planned" ] == 4 and plan[ "budgets" ][ "posts_planned" ] == 6
    assert plan[ "refused" ] == [ { "pair": "pair-3", "stratum": "flag", "label": sc.SAME_JOB, "reasons": [ "side b text matches no index record" ] } ]
    assert plan[ "shown" ][ 0 ] == { "pair": "pair-1", "side": "a", "id": "src.m1.f1", "purpose_line": "line pin1" } and len( plan[ "shown" ] ) == 4
    assert plan[ "audit" ][ "sides" ] == 6 and plan[ "audit" ][ "matched" ] == 5 and [ n[ "pair" ] for n in plan[ "audit" ][ "named" ] ] == [ "pair-3" ]
    assert sc.plan_of( rows, refused, sides, sc.budgets_for( rows, post_budget=9 ) )[ "budgets" ][ "posts_budget" ] == 9


def test_the_budgets_follow_the_planned_calls_with_five_percent_headroom_at_86_and_105_pairs():
    at_86, at_105 = sc.budgets_for( [ None ] * 86 ), sc.budgets_for( [ None ] * 105 )
    assert ( at_86[ "drafts_planned" ], at_86[ "drafts_budget" ], at_86[ "posts_planned" ], at_86[ "posts_budget" ], at_86[ "limit" ] ) == ( 172, 181, 258, 271, 452 )
    assert ( at_105[ "drafts_planned" ], at_105[ "drafts_budget" ], at_105[ "posts_planned" ], at_105[ "posts_budget" ], at_105[ "limit" ] ) == ( 210, 221, 315, 331, 552 )
    assert at_105[ "headroom_percent" ] == 5 and at_105[ "overridden" ] == [ ] and at_105[ "short" ] == [ ]
    assert sc.budgets_for( [ ] )[ "limit" ] == 0 and sc.budgets_for( [ None ] )[ "posts_budget" ] == 4, "a budget is rounded up, never down"


def test_a_named_budget_replaces_the_derived_one_and_a_short_one_is_named():
    got = sc.budgets_for( [ None ] * 105, draft_budget=100, post_budget=400, limit=9999 )
    assert ( got[ "drafts_budget" ], got[ "posts_budget" ], got[ "limit" ] ) == ( 100, 400, 9999 ) and got[ "overridden" ] == [ "draft_budget", "post_budget", "limit" ]
    assert got[ "short" ] == [ "draft_budget" ], "only the draft budget is below its planned figure"
    assert sc.budgets_for( [ None ] * 105, limit=500 )[ "short" ] == [ "limit" ] and sc.budgets_for( [ None ] * 105, post_budget=300 )[ "short" ] == [ "post_budget", "limit" ], "the limit of the two budgets together is then short too"
    assert sc.budgets_for( [ None ] * 105, post_budget=300 )[ "limit" ] == 221 + 300, "the limit follows the budgets that are in force"


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
    refusal = { "try": 0, "sentence": "A function that logs.", "failures": [ { "check": "identifier", "detail": "name pieces: log", "words": [ "log" ] } ] }
    reply = iter( [ { "ok": True, "need": "a sentence", "rejections": [ refusal ] }, { "ok": False, "reason": er.NEED_LEAKS_KEY, "rejections": [ refusal, { **refusal, "try": 1 } ] } ] )
    with mock.patch.object( sc.draft, "draft_need", side_effect=lambda job, ask, ledger, max_tries: next( reply ) ) as dn:
        needs, undrafted, rejected = sc.draft_all( rows, lambda r: { "kind": "k", "text": "t", "forbidden": [ ] }, "ask", "ledger", 4 )
    assert needs == { "pair-1": "a sentence" } and dn.call_args[ 0 ][ 1:] == ( "ask", "ledger" ) and dn.call_args[ 1 ] == { "max_tries": 4 }
    assert undrafted == [ { "pair": "pair-2", "stratum": "monolith:neighbour", "label": sc.NOT_SAME, "unsure": True, "raters": 3, "reason": er.NEED_LEAKS_KEY } ]
    assert [ ( r[ "pair" ], r[ "try" ], r[ "outcome" ], r[ "sentence" ], r[ "failures" ][ 0 ][ "check" ] ) for r in rejected ] == [
        ( "pair-1", 0, "accepted_later", "A function that logs.", "identifier" ), ( "pair-2", 0, "undrafted", "A function that logs.", "identifier" ), ( "pair-2", 1, "undrafted", "A function that logs.", "identifier" ) ]
    assert rejected[ 2 ][ "stratum" ] == "monolith:neighbour" and rejected[ 2 ][ "label" ] == sc.NOT_SAME and rejected[ 2 ][ "unsure" ] is True and rejected[ 2 ][ "raters" ] == 3


def argv( tmp_path, *more ):
    """Return a full command line for the stage."""
    names = ( "root", "run-dir", "answer-key", "packet", "labels-dir", "symbols", "purposes", "source-commit" )
    return [ x for n in names for x in ( "--" + n, str( tmp_path / n ) ) ] + list( more )


def test_the_command_line_needs_its_inputs_and_defaults_to_a_plan( tmp_path ):
    args = sc.parse_args( argv( tmp_path ) )
    assert args.live is False and args.run_name is None and args.limit is None and args.post_budget is None and args.draft_budget is None
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
    """Return the live command line, naming a real executable as the Claude Code binary."""
    cli = tmp_path / "claude"
    cli.write_text( "#!/bin/sh\n", encoding="utf-8" )
    cli.chmod( 0o755 )
    return argv( tmp_path, "--live", "--run-name", "needset-stage-c-x", "--from-run", str( tmp_path / "from-run" ), "--cli-path", str( cli ), *more )


def stand_ins( tmp_path, rows, undrafted_pair=None, refused=(), by_records=False ):
    """Return the patches that replace the files, the drafter ledger and the strip step."""
    def draft_need( job, ask, ledger, max_tries ):
        if job[ "meta" ][ "stage_c" ] == undrafted_pair: return { "ok": False, "reason": er.NEED_LEAKS_KEY, "rejections": [ { "try": 0, "sentence": "A function that fails.", "failures": [ { "check": "form", "detail": "d", "words": [ ] } ] } ] }
        if by_records: return { "ok": True, "need": f"Need for {job[ 'seed' ][ 'id' ]} against {job[ 'keys' ][ 0 ][ 'id' ]}.", "rejections": [ ] }   # as the saved drafts do: one sentence per record pair
        return { "ok": True, "need": f"Need for {job[ 'meta' ][ 'stage_c' ]}.", "rejections": [ ] }
    return [ mock.patch.object( sc, "collect_rows", return_value=( rows, list( refused ), [ ] ) ), mock.patch.object( sc.draft, "draft_need", side_effect=draft_need ),
             mock.patch.object( sc.draft, "make_ledger", return_value="ledger" ), mock.patch.object( sc.strip, "strip_member", side_effect=lambda r, root: { "kind": "k", "text": "t", "forbidden": [ ] } ),
             mock.patch.object( rt, "prepare" ) ]


def run_live( tmp_path, deps, rows, undrafted_pair=None, refused=(), by_records=False ):
    """Run a live stage on stand-ins and return its result."""
    patches = stand_ins( tmp_path, rows, undrafted_pair, refused, by_records )
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
    rejects = json.loads( ( tmp_path / "run-dir" / sc.REJECTS_FILE ).read_text( encoding="utf-8" ) )
    assert rejects[ "count" ] == 1 and rejects[ "rejected" ][ 0 ][ "pair" ] == "pair-2" and rejects[ "rejected" ][ 0 ][ "failures" ][ 0 ][ "check" ] == "form" and rejects[ "rejected" ][ 0 ][ "outcome" ] == "undrafted"
    assert saved[ "undrafted" ][ 0 ][ "pair" ] == "pair-2" and saved[ "refused" ] == refused and out[ "plan" ][ "pairs_total" ] == 4 and len( saved[ "results" ] ) == 6 and saved[ "status" ] == "done"
    assert os.environ[ rt.RUN_NAME_VARIABLE ] == "needset-stage-c-x" and os.environ[ rt.CEILING_VARIABLE ] == str( sc.jp.CEILING ) and sc.exit_status( out ) == 0


def test_the_drafting_limit_is_the_drafters_own_unless_max_tries_is_given():
    assert sc.tries_of( sc.parse_args( argv( Path( "/t" ) ) ) ) == sc.draft.MAX_TRIES
    assert sc.tries_of( sc.parse_args( argv( Path( "/t" ), "--max-tries", "4" ) ) ) == 4


def test_a_live_run_hands_max_tries_to_the_drafting_step( tmp_path ):
    deps, _state = live_parts( tmp_path )
    ( tmp_path / "run-dir" ).mkdir( exist_ok=True )
    seen = []
    real = sc.draft_all
    patches = stand_ins( tmp_path, [ make_row() ] )
    for p in patches: p.start()
    try:
        with mock.patch.object( sc, "draft_all", side_effect=lambda *a: seen.append( a[ 4 ] ) or real( *a ) ):
            sc.main( live_argv( tmp_path, "--max-tries", "4" ), deps )
            sc.main( live_argv( tmp_path ), deps )
    finally:
        for p in patches: p.stop()
    assert seen == [ 4, sc.draft.MAX_TRIES ]


def test_the_cache_only_drafter_refuses_so_a_replay_never_calls_a_model():
    with pytest.raises( er.NeedsetError ) as caught: sc.cache_only( "system", "user" )
    assert caught.value.code == er.BAD_NEED


def test_save_rejects_writes_the_count_and_the_sentences_beside_their_checks( tmp_path ):
    path = sc.save_rejects( tmp_path, [ { "pair": "pair-1", "sentence": "s" } ] )
    assert path == tmp_path / sc.REJECTS_FILE and json.loads( path.read_text( encoding="utf-8" ) ) == { "count": 1, "rejected": [ { "pair": "pair-1", "sentence": "s" } ] }


def replay_args( tmp_path, *more ):
    """Return the parsed arguments of a save-rejects run whose run folder holds a ledger."""
    ( tmp_path / "run-dir" ).mkdir( exist_ok=True )
    ( tmp_path / "run-dir" / sc.DRAFT_LEDGER ).write_text( "", encoding="utf-8" )
    return sc.parse_args( argv( tmp_path, "--save-rejects", "--cli-path", "/x/claude", *more ) )


def test_replaying_the_saved_ledger_writes_the_rejects_and_makes_no_model_call( tmp_path ):
    args = replay_args( tmp_path, "--max-tries", "3" )
    rows = [ make_row( 1 ), make_row( 2 ) ]
    seen = []

    def draft_need( job, ask, ledger, max_tries ):
        seen.append( ( ask, ledger, max_tries ) )
        return { "ok": job[ "meta" ][ "stage_c" ] == "pair-1", "need": "n", "reason": er.NEED_LEAKS_KEY, "rejections": [ { "try": 0, "sentence": "A function that x.", "failures": [ ] } ] }
    with mock.patch.object( sc.draft, "draft_need", side_effect=draft_need ), mock.patch.object( sc.draft, "make_ledger", return_value="ledger" ) as made, mock.patch.object( sc.strip, "strip_member", return_value={ "kind": "k", "text": "t", "forbidden": [ ] } ) as stripped, \
         mock.patch.object( sc.source_at, "ensure_worktree", return_value="the-tree" ) as tree, mock.patch.object( sc.source_at, "unlock" ) as unlock:
        out = sc.replay_rejects( args, rows, { } )
    assert tree.call_args[ 0 ] == ( str( tmp_path / "root" ), str( tmp_path / "source-commit" ) ) and unlock.call_args[ 0 ] == ( str( tmp_path / "root" ), "the-tree" )
    assert out[ "mode" ] == "stage_c_save_rejects" and out[ "live" ] is False and out[ "drafted" ] == 1 and out[ "rejected" ] == 2 and [ u[ "pair" ] for u in out[ "undrafted" ] ] == [ "pair-2" ]
    assert seen == [ ( sc.cache_only, "ledger", 3 ) ] * 2 and made.call_args[ 0 ] == ( str( tmp_path / "run-dir" / sc.DRAFT_LEDGER ), "/x/claude", "max-plan" ) and stripped.call_args[ 0 ][ 1 ] == "the-tree"
    assert json.loads( Path( out[ "path" ] ).read_text( encoding="utf-8" ) )[ "count" ] == 2


def test_replaying_reads_the_source_tree_the_caller_names_and_needs_a_cli_path_and_a_saved_ledger( tmp_path ):
    args = replay_args( tmp_path )
    with mock.patch.object( sc.draft, "draft_need", return_value={ "ok": True, "need": "n", "rejections": [ ] } ), mock.patch.object( sc.draft, "make_ledger", return_value="l" ), mock.patch.object( sc.strip, "strip_member", return_value={ "kind": "k", "text": "t", "forbidden": [ ] } ) as stripped:
        with mock.patch.object( sc.source_at, "ensure_worktree" ) as made, mock.patch.object( sc.source_at, "unlock" ) as unlock:
            sc.replay_rejects( args, [ make_row( 1 ) ], { "source_root": lambda a: tmp_path / "elsewhere" } )
    assert stripped.call_args[ 0 ][ 1 ] == tmp_path / "elsewhere" and made.call_count == 0 and unlock.call_count == 0
    no_cli = sc.parse_args( argv( tmp_path, "--save-rejects" ) )
    with pytest.raises( er.NeedsetError ) as caught: sc.replay_rejects( no_cli, [ ], { } )
    assert caught.value.code == er.NO_CLI_PATH
    ( tmp_path / "run-dir" / sc.DRAFT_LEDGER ).unlink()
    with pytest.raises( er.NeedsetError, match="no saved draft ledger" ) as caught: sc.replay_rejects( args, [ ], { } )
    assert caught.value.code == er.BAD_NEED


def test_main_with_save_rejects_replays_and_writes_nothing_else( tmp_path ):
    args = argv( tmp_path, "--save-rejects", "--cli-path", "/x/claude" )
    replay_args( tmp_path )
    with mock.patch.object( sc, "collect_rows", return_value=( [ make_row() ], [ ], [ ] ) ), mock.patch.object( sc, "replay_rejects", return_value={ "mode": "stage_c_save_rejects" } ) as rr:
        assert sc.main( args, { } ) == { "mode": "stage_c_save_rejects" }
    rr.assert_called_once()


def test_the_redraft_plan_counts_one_call_per_extra_sentence_and_pair_plus_headroom():
    assert sc.redraft_plan( 27, 2 ) == { "undrafted": 27, "extra_tries": 2, "calls_planned": 54, "calls_budget": 57 }
    assert sc.redraft_plan( 0, 2 )[ "calls_budget" ] == 0 and sc.with_headroom( 100 ) == 105 and sc.with_headroom( 1 ) == 2


class RedraftWorld:
    """Three pairs on a saved ledger, two with no need, and a drafter that logs its asks."""

    def __init__( self, tmp_path, accepts=( "pair-2", ) ):
        ( tmp_path / "claude" ).write_text( "#!/bin/sh\n", encoding="utf-8" )
        ( tmp_path / "claude" ).chmod( 0o755 )
        ( tmp_path / "run-dir" ).mkdir( exist_ok=True )
        ( tmp_path / "run-dir" / sc.DRAFT_LEDGER ).write_text( "", encoding="utf-8" )
        self.rows    = [ make_row( 1 ), make_row( 2 ), make_row( 3 ) ]
        self.accepts = accepts
        self.calls   = [ ]
        self.hook    = [ ]

    def draft_need( self, job, ask, ledger, max_tries ):
        """Fail every pair but pair-1 on the replay; on a live ask accept only the pairs in accepts."""
        pair = job[ "meta" ][ "stage_c" ]
        self.calls.append( ( pair, ask is sc.cache_only, max_tries ) )
        if ask is not sc.cache_only:
            sc.call_cap.charge_attempt( "claude-fable-5-1" )
            self.hook.append( sc.model_transport.CHARGE_HOOK is not None )
        ok = pair == "pair-1" or ( ask is not sc.cache_only and pair in self.accepts )
        rej = [ { "try": n, "sentence": f"A function that {pair} {n}.", "failures": [ { "check": "identifier", "detail": "d", "words": [ "w" ] } ] } for n in range( 1 if pair == "pair-1" else max_tries ) ]            # pair-1 drafted on its second sentence, so one was refused
        return { "ok": ok, "need": f"Need for {pair}." if ok else None, "reason": None if ok else er.NEED_LEAKS_KEY, "rejections": rej }

    def run( self, args ):
        """Run main over the world with the drafting step replaced."""
        with mock.patch.object( sc, "collect_rows", return_value=( self.rows, [ ], [ ] ) ), mock.patch.object( sc.draft, "draft_need", side_effect=self.draft_need ), \
             mock.patch.object( sc.draft, "make_ledger", return_value="ledger" ), mock.patch.object( sc.strip, "strip_member", return_value={ "kind": "k", "text": "t", "forbidden": [ ] } ), \
             mock.patch.object( sc.source_at, "ensure_worktree", return_value="the-tree" ) as made, mock.patch.object( sc.source_at, "unlock" ) as unlock:
            try:
                return sc.main( args, { "drafter": "the-drafter" } )
            finally:
                self.made, self.unlock = made, unlock


def test_a_redraft_without_live_names_the_undrafted_pairs_and_the_calls_and_writes_nothing( tmp_path ):
    world = RedraftWorld( tmp_path )
    before = sorted( p.name for p in ( tmp_path / "run-dir" ).iterdir() )
    out = world.run( argv( tmp_path, "--redraft", "--cli-path", str( tmp_path / "claude" ) ) )
    assert out == { "live": False, "mode": "stage_c_redraft", "plan": { "undrafted": 2, "extra_tries": 2, "calls_planned": 4, "calls_budget": 5 }, "pairs": [ "pair-2", "pair-3" ] }
    assert world.calls == [ ( "pair-1", True, 2 ), ( "pair-2", True, 2 ), ( "pair-3", True, 2 ) ] and sorted( p.name for p in ( tmp_path / "run-dir" ).iterdir() ) == before
    assert world.made.call_args[ 0 ] == ( str( tmp_path / "root" ), str( tmp_path / "source-commit" ) ) and world.unlock.call_args[ 0 ] == ( str( tmp_path / "root" ), "the-tree" )


def test_a_live_redraft_asks_only_the_undrafted_pairs_for_more_sentences_and_keeps_the_rest_failed( tmp_path ):
    world = RedraftWorld( tmp_path )
    out = world.run( argv( tmp_path, "--redraft", "--live", "--cli-path", str( tmp_path / "claude" ) ) )
    assert world.calls[ 3: ] == [ ( "pair-2", False, 4 ), ( "pair-3", False, 4 ) ] and world.hook == [ True, True ]
    assert out[ "live" ] is True and out[ "accepted" ] == 1 and out[ "still_failing" ] == 1 and out[ "calls" ] == 2 and out[ "plan" ][ "calls_budget" ] == 5
    done = json.loads( ( tmp_path / "run-dir" / sc.REDRAFT_FILE ).read_text( encoding="utf-8" ) )
    assert done[ "accepted" ] == { "pair-2": "Need for pair-2." } and [ u[ "pair" ] for u in done[ "still_failing" ] ] == [ "pair-3" ] and done[ "tries" ] == 4 and done[ "calls" ] == 2 and done[ "by_stage" ] == { sc.REDRAFT_STAGE: 2 }
    rows = [ json.loads( l ) for l in ( tmp_path / "run-dir" / sc.REDRAFT_CALLS ).read_text( encoding="utf-8" ).splitlines() ]
    assert [ r[ "stage" ] for r in rows ] == [ sc.REDRAFT_STAGE ] * 2 and not ( tmp_path / "run-dir" / "call-ledger.jsonl" ).exists()
    rejects = json.loads( ( tmp_path / "run-dir" / sc.REJECTS_FILE ).read_text( encoding="utf-8" ) )
    assert sorted( { r[ "pair" ] for r in rejects[ "rejected" ] } ) == [ "pair-1", "pair-2", "pair-3" ] and rejects[ "count" ] == 9
    assert sorted( ( r[ "pair" ], r[ "outcome" ] ) for r in rejects[ "rejected" ] if r[ "try" ] == 0 ) == [ ( "pair-1", "accepted_later" ), ( "pair-2", "accepted_later" ), ( "pair-3", "undrafted" ) ]
    assert sc.model_transport.CLI_PATH == str( tmp_path / "claude" ) and world.unlock.call_count == 1


def test_a_live_redraft_stops_at_its_own_budget_and_leaves_the_judge_count_alone( tmp_path ):
    world = RedraftWorld( tmp_path )
    ( tmp_path / "run-dir" / sc.REDRAFT_CALLS ).write_text( "".join( json.dumps( { "n": n, "stage": sc.REDRAFT_STAGE, "model": "m", "ts": "t" } ) + "\n" for n in range( 1, 6 ) ), encoding="utf-8" )
    with pytest.raises( er.NeedsetError ) as caught: world.run( argv( tmp_path, "--redraft", "--live", "--cli-path", str( tmp_path / "claude" ) ) )
    assert caught.value.code in ( er.STAGE_BUDGET_REACHED, er.CALL_CAP_REACHED ) and not ( tmp_path / "run-dir" / sc.REDRAFT_FILE ).exists()
    assert world.unlock.call_count == 1                                           # the tree is released when the run fails


def test_a_redraft_needs_a_cli_path_and_a_saved_ledger( tmp_path ):
    world = RedraftWorld( tmp_path )
    with pytest.raises( er.NeedsetError ) as caught: world.run( argv( tmp_path, "--redraft" ) )
    assert caught.value.code == er.NO_CLI_PATH
    ( tmp_path / "run-dir" / sc.DRAFT_LEDGER ).unlink()
    with pytest.raises( er.NeedsetError, match="no saved draft ledger" ) as caught: world.run( argv( tmp_path, "--redraft", "--cli-path", "/x" ) )
    assert caught.value.code == er.BAD_NEED


def test_a_redraft_reads_the_source_tree_the_caller_names( tmp_path ):
    world = RedraftWorld( tmp_path )
    with mock.patch.object( sc, "collect_rows", return_value=( world.rows[ :1 ], [ ], [ ] ) ), mock.patch.object( sc.draft, "make_ledger", return_value="l" ), mock.patch.object( sc.strip, "strip_member", return_value={ "kind": "k", "text": "t", "forbidden": [ ] } ) as stripped, \
         mock.patch.object( sc.draft, "draft_need", return_value={ "ok": True, "need": "n", "rejections": [ ] } ):
        with mock.patch.object( sc.source_at, "ensure_worktree" ) as made, mock.patch.object( sc.source_at, "unlock" ) as unlock:
            sc.main( argv( tmp_path, "--redraft", "--cli-path", "/x" ), { "source_root": lambda a: tmp_path / "elsewhere" } )
    assert stripped.call_args[ 0 ][ 1 ] == tmp_path / "elsewhere" and made.call_count == 0 and unlock.call_count == 0


def test_a_live_run_points_the_model_transport_at_the_cli_path_before_any_call( tmp_path ):
    deps, state = live_parts( tmp_path )
    ( tmp_path / "run-dir" ).mkdir( exist_ok=True )
    order = []
    with mock.patch.object( sc.model_transport, "configure", side_effect=lambda **kw: order.append( ( "configure", kw ) ) ) as cfg:
        deps[ "ask" ] = lambda request, _ask=deps[ "ask" ]: ( order.append( ( "ask", None ) ), _ask( request ) )[ 1 ]
        run_live( tmp_path, deps, [ make_row() ] )
    cfg.assert_called_once_with( cli_path=str( tmp_path / "claude" ) )
    assert order[ 0 ] == ( "configure", { "cli_path": str( tmp_path / "claude" ) } ) and ( "ask", None ) in order


def test_a_live_run_leaves_the_real_transport_bound_to_the_cli_path( tmp_path ):
    deps, _state = live_parts( tmp_path )
    ( tmp_path / "run-dir" ).mkdir( exist_ok=True )
    run_live( tmp_path, deps, [ make_row() ] )
    assert sc.model_transport.CLI_PATH == str( tmp_path / "claude" )


def test_a_plan_run_leaves_the_model_transport_alone( tmp_path ):
    with mock.patch.object( sc.model_transport, "configure" ) as cfg, mock.patch.object( sc, "collect_rows", return_value=( [ make_row() ], [ ], [ ] ) ):
        sc.main( argv( tmp_path, "--cli-path", "/x/claude" ), { } )
    cfg.assert_not_called()


def twin_rows():
    """Return four rows: pairs 1 and 2 share records, pair 3 has others, pair 4 reverses pair 1."""
    _records, index, by_id, purposes = world( 4 )
    pairs = [ pair( 1, 1, 2 ), pair( 2, 1, 2, label=sc.NOT_SAME, unsure=True, raters=3, stratum="monolith:neighbour" ), pair( 3, 3, 4 ), pair( 4, 2, 1 ) ]
    rows, _r, _s = sc.split_pairs( pairs, index, by_id, purposes )
    return rows


def test_pairs_on_the_same_records_in_the_same_order_share_one_body_and_the_reverse_order_does_not():
    rows = twin_rows()
    needs = { "pair-1": "One need.", "pair-2": "One need.", "pair-3": "One need.", "pair-4": "Another need." }
    posting, shared = sc.share_bodies( rows, needs )
    assert [ r[ "pair" ] for r in posting ] == [ "pair-1", "pair-3", "pair-4" ]
    assert { p: [ r[ "pair" ] for r in rs ] for p, rs in shared.items() } == { "pair-1": [ "pair-2" ], "pair-3": [ ], "pair-4": [ ] }
    posting, shared = sc.share_bodies( rows, { "pair-2": "One need.", "pair-3": "One need." } )
    assert [ r[ "pair" ] for r in posting ] == [ "pair-2", "pair-3" ] and shared == { "pair-2": [ ], "pair-3": [ ] }
    different, _s = sc.share_bodies( rows, { "pair-1": "One need.", "pair-2": "A different need." } )
    assert [ r[ "pair" ] for r in different ] == [ "pair-1", "pair-2" ]


def test_the_plan_counts_pairs_on_one_record_pair_as_would_share_before_any_draft():
    rows = twin_rows()
    posting, shared = sc.twin_pairs( rows )
    assert [ r[ "pair" ] for r in posting ] == [ "pair-1", "pair-3", "pair-4" ]
    assert { p: [ r[ "pair" ] for r in rs ] for p, rs in shared.items() } == { "pair-1": [ "pair-2" ], "pair-3": [ ], "pair-4": [ ] }
    plan = sc.plan_of( rows, [ ], [ ], sc.budgets_for( rows ) )
    assert plan[ "would_share" ] == [ { "pair": "pair-2", "with": "pair-1" } ]
    assert plan[ "calls" ][ "posts" ] == 12 and plan[ "calls" ][ "posts_if_shared" ] == 9


def test_twin_pairs_with_one_side_b_and_different_side_a_are_not_twins():
    _records, index, by_id, purposes = world( 4 )
    rows, _r, _s = sc.split_pairs( [ pair( 1, 1, 2 ), pair( 2, 3, 2 ) ], index, by_id, purposes )
    posting, shared = sc.twin_pairs( rows )
    assert [ r[ "pair" ] for r in posting ] == [ "pair-1", "pair-2" ] and shared == { "pair-1": [ ], "pair-2": [ ] }


def test_three_pairs_on_one_record_pair_all_fold_into_the_first():
    _records, index, by_id, purposes = world( 2 )
    rows, _r, _s = sc.split_pairs( [ pair( 1, 1, 2 ), pair( 2, 1, 2 ), pair( 3, 1, 2 ) ], index, by_id, purposes )
    posting, shared = sc.twin_pairs( rows )
    assert [ r[ "pair" ] for r in posting ] == [ "pair-1" ]
    assert { p: [ r[ "pair" ] for r in rs ] for p, rs in shared.items() } == { "pair-1": [ "pair-2", "pair-3" ] }


def test_the_plan_with_no_twins_lists_none_and_posts_every_pair():
    _records, index, by_id, purposes = world( 4 )
    rows, _r, _s = sc.split_pairs( [ pair( 1, 1, 2 ), pair( 2, 3, 4 ) ], index, by_id, purposes )
    plan = sc.plan_of( rows, [ ], [ ], sc.budgets_for( rows ) )
    assert plan[ "would_share" ] == [ ] and plan[ "calls" ][ "posts_if_shared" ] == plan[ "calls" ][ "posts" ] == 6


def test_the_plan_and_the_live_run_group_through_one_function():
    rows = twin_rows()
    with mock.patch.object( sc, "group_rows", wraps=sc.group_rows ) as g:
        sc.twin_pairs( rows )
        sc.share_bodies( rows, { "pair-1": "One need." } )
    assert g.call_count == 2


def test_fan_out_gives_each_sharing_pair_the_posted_results_under_its_own_label():
    rows = twin_rows()
    results = [ { "pair": "pair-1", "label": sc.SAME_JOB, "stratum": "flag", "unsure": False, "raters": 2, "repeat": n, "request_hash": f"h{n}", "tokens_in": 9 } for n in ( 1, 2 ) ]
    out = sc.fan_out( results, { "pair-1": [ rows[ 1 ] ], "pair-3": [ ] } )
    assert out[ :2 ] == results and len( out ) == 4
    assert [ ( r[ "pair" ], r[ "label" ], r[ "stratum" ], r[ "unsure" ], r[ "raters" ], r[ "repeat" ], r[ "request_hash" ], r[ "shared_with" ] ) for r in out[ 2: ] ] == [
        ( "pair-2", sc.NOT_SAME, "monolith:neighbour", True, 3, n, f"h{n}", "pair-1" ) for n in ( 1, 2 ) ]
    assert sc.fan_out( results, { } ) == results


def test_a_live_run_posts_a_shared_body_once_and_reports_every_pair( tmp_path ):
    deps, state = live_parts( tmp_path )
    ( tmp_path / "run-dir" ).mkdir()
    out = run_live( tmp_path, deps, twin_rows(), by_records=True )
    assert sorted( { r[ "pair" ] for r in state[ "asked" ] } ) == [ "pair-1", "pair-3", "pair-4" ] and len( state[ "asked" ] ) == 9
    assert out[ "report" ][ "status" ] == sc.jp.DONE
    saved = json.loads( ( tmp_path / "run-dir" / sc.REPORT_FILE ).read_text( encoding="utf-8" ) )
    assert saved[ "shared" ] == [ { "pair": "pair-2", "with": "pair-1" } ] and len( saved[ "results" ] ) == 12
    twins = [ r for r in saved[ "results" ] if r[ "pair" ] == "pair-2" ]
    assert [ r[ "repeat" ] for r in twins ] == [ 1, 2, 3 ] and {ra[ "label" ] for ra in twins} == { sc.NOT_SAME } and {r[ "shared_with" ] for r in twins} == { "pair-1" }
    assert saved[ "summary" ][ "bypass_proof" ][ "calls_charged_to_the_cap" ] == out[ "report" ][ "used" ]


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


def test_a_live_redraft_exits_zero_through_the_command_line_runner( tmp_path ):
    world = RedraftWorld( tmp_path )
    lines = [ ]
    with mock.patch.object( sc, "collect_rows", return_value=( world.rows, [ ], [ ] ) ), mock.patch.object( sc.draft, "draft_need", side_effect=world.draft_need ), mock.patch.object( sc.draft, "make_ledger", return_value="ledger" ), \
         mock.patch.object( sc.strip, "strip_member", return_value={ "kind": "k", "text": "t", "forbidden": [ ] } ), mock.patch.object( sc.source_at, "ensure_worktree", return_value="the-tree" ), mock.patch.object( sc.source_at, "unlock" ):
        code = sc.run_cli( argv( tmp_path, "--redraft", "--live", "--cli-path", str( tmp_path / "claude" ) ), { "drafter": "the-drafter" }, out=lines.append )
    assert code == 0 and json.loads( lines[ 0 ] )[ "mode" ] == "stage_c_redraft"


def test_the_exit_status_of_the_replay_and_the_redraft_plan_is_zero_and_the_judge_runs_keep_theirs():
    assert sc.exit_status( { "mode": "stage_c_save_rejects", "live": False } ) == 0 and sc.exit_status( { "mode": "stage_c_redraft", "live": False } ) == 0 and sc.exit_status( { "mode": "stage_c_redraft", "live": True } ) == 0
    assert sc.exit_status( { "mode": "stage_c", "live": False } ) == 0


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


def test_the_live_cap_gets_the_derived_budgets_and_a_named_flag_overrides_them( tmp_path ):
    deps, _state = live_parts( tmp_path )
    ( tmp_path / "run-dir" ).mkdir()
    rows = [ make_row( 1 ), make_row( 2 ), make_row( 3 ) ]
    with mock.patch.object( sc.call_cap, "CallCap", wraps=sc.call_cap.CallCap ) as cap:
        out = run_live( tmp_path, deps, rows )
    assert cap.call_args_list[ 0 ][ 0 ][ 1 ] == 17 and cap.call_args_list[ 0 ][ 0 ][ 2 ] == { sc.DRAFT_STAGE: 7 } and out[ "plan" ][ "budgets" ][ "limit" ] == 17
    assert out[ "report" ][ "limit" ] == 17 and cap.call_args_list[ 1 ][ 0 ][ 1 ] == 17 and cap.call_args_list[ 1 ][ 0 ][ 2 ] == { sc.jp.STAGE_NAME: 10 }
    deps, _state = live_parts( tmp_path )
    patches = stand_ins( tmp_path, rows )
    for p in patches: p.start()
    try:
        with mock.patch.object( sc.call_cap, "CallCap", wraps=sc.call_cap.CallCap ) as cap:
            out = sc.main( live_argv( tmp_path, "--limit", "40", "--draft-budget", "11", "--post-budget", "29" ), deps )
    finally:
        for p in patches: p.stop()
    assert cap.call_args_list[ 0 ][ 0 ][ 1:3 ] == ( 40, { sc.DRAFT_STAGE: 11 } ) and cap.call_args_list[ 1 ][ 0 ][ 2 ] == { sc.jp.STAGE_NAME: 29 }
    assert out[ "plan" ][ "budgets" ][ "overridden" ] == [ "draft_budget", "post_budget", "limit" ]
