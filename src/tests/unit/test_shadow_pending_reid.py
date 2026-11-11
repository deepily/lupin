"""
Tests for the one-off repair of the shadow audit's queue (lupin_mcp.shadow_pending_reid).

Every queue item is written by the real producer, sa.enqueue_pending.
Every repaired item is drained by the real run_pending.
The sweep refuses an id the index does not hold, as the real sweep does.
"""
import io
import json

import pytest

from cosa.repo.symindex.candidates import shadow_audit as sa
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import shadow_pending_reid as sp

DAY     = "2026-11-10"
LIVE    = { "verdict": "NEW", "candidate_ids": [] }
ENTRIES = [ { "id": "m.regroup", "file": "src/m.py", "name": "regroup", "line": 10 },
            { "id": "m.fit_body", "file": "src/m.py", "name": "fit_body", "line": 40 },
            { "id": "m.twin", "file": "src/m.py", "name": "twin", "line": 60 },
            { "id": "n.twin", "file": "src/m.py", "name": "twin", "line": 90 } ]
CODE    = [ "--code", "d-aaaaaaaaaa=src/m.py:regroup", "--code", "d-bbbbbbbbbb=src/m.py:fit_body" ]
DROP    = [ "--drop", "d-cccccccccc", "--drop", "d-dddddddddd" ]


@pytest.fixture
def data( tmp_path ):
    """
    Build the queue.

    Ensures:
        - shadow-pending holds two code items and two test items, each queued under a d- id, each with attempts 1
    """
    for n, d in enumerate( ( "d-aaaaaaaaaa", "d-bbbbbbbbbb", "d-cccccccccc", "d-dddddddddd" ) ):
        sa.enqueue_pending( tmp_path, f"need number {n}", "py", "gen1", "idx1", LIVE, "2026-11-09", known_miss=True, exclude_id=d, tie="heuristic" )
    sa.run_pending( tmp_path, lambda need, **kw: ( _ for _ in () ).throw( CandidateError( "AUDIT_SWEEP_REFUSED", sa.UNKNOWN_ENTRY ) ), DAY )   # attempts 1, as the live items hold
    return tmp_path


def folder_of( data ):
    return data / "shadow-pending"


def run( data, *args, entries=None ):
    entries = ENTRIES if entries is None else entries
    out     = io.StringIO()
    rc      = sp.main( [ str( folder_of( data ) ), *args ], out=out, entries_fn=lambda: entries )
    return rc, out.getvalue()


def items_of( data ):
    return [ json.loads( p.read_text() ) for p in sorted( folder_of( data ).glob( "*.json" ) ) ]


def test_a_dry_run_lists_each_item_and_changes_nothing( data ):
    before = { p.name: p.read_text() for p in folder_of( data ).glob( "*.json" ) }
    rc, text = run( data, *CODE, *DROP )
    assert rc == 0 and text.count( "DRY-RUN" ) == 4 and "rewrite d-aaaaaaaaaa -> m.regroup" in text and "remove d-cccccccccc -> None" in text
    assert { p.name: p.read_text() for p in folder_of( data ).glob( "*.json" ) } == before
    assert not ( data / "shadow-audit" ).exists()


def test_apply_rewrites_the_code_items_removes_the_rest_and_the_drain_then_audits_the_rewritten_ones( data ):
    originals = { i[ "exclude_id" ]: i for i in items_of( data ) }
    rc, text = run( data, *CODE, *DROP, "--reason", "test definitions are no longer judged (b309030e)", "--apply" )
    assert rc == 0 and text.count( "APPLY" ) == 4
    held = items_of( data )
    for item in held:
        old = originals[ { "m.regroup": "d-aaaaaaaaaa", "m.fit_body": "d-bbbbbbbbbb" }[ item[ "exclude_id" ] ] ]
        assert { k: v for k, v in item.items() if k not in ( "id", "exclude_id", "attempts" ) } == { k: v for k, v in old.items() if k not in ( "id", "exclude_id", "attempts" ) }, "need, language, generation, index_sha, live, queued_on, known_miss and tie are carried over"
        assert old[ "attempts" ] == 1 and item[ "attempts" ] == 0 and item[ "id" ] != old[ "id" ] and item[ "exclude_id" ] != old[ "exclude_id" ]
    assert sorted( i[ "exclude_id" ] for i in held ) == [ "m.fit_body", "m.regroup" ] and all( i[ "attempts" ] == 0 and i[ "known_miss" ] for i in held )
    assert all( p.name == f"{i[ 'id' ]}.json" for p, i in zip( sorted( folder_of( data ).glob( "*.json" ) ), sorted( held, key=lambda i: i[ "id" ] ) ) ), "each file is named by its own queue id"
    known = { e[ "id" ] for e in ENTRIES }

    def sweep( need, exclude_id=None ):
        if exclude_id not in known: raise CandidateError( "AUDIT_SWEEP_REFUSED", sa.UNKNOWN_ENTRY )
        return { "verdict": "NEW", "causal_ids": [] }

    out = sa.run_pending( data, sweep, DAY )
    assert out[ "audited" ] == 2 and out[ "failed" ] == 0 and out[ "dropped" ] == 0
    log = [ json.loads( l ) for l in ( data / "shadow-audit" / sp.LOG_NAME ).read_text().splitlines() ]
    assert [ l[ "action" ] for l in log ].count( "remove" ) == 2 and all( l[ "reason" ].startswith( "test definitions" ) for l in log if l[ "action" ] == "remove" )
    assert sorted( l[ "new" ] for l in log if l[ "action" ] == "rewrite" ) == [ "m.fit_body", "m.regroup" ] and all( l[ "new_file" ].endswith( ".json" ) for l in log if l[ "action" ] == "rewrite" )


def test_the_unrepaired_items_would_have_failed_the_same_drain( data ):
    def sweep( need, exclude_id=None ):
        if not exclude_id.startswith( "m." ): raise CandidateError( "AUDIT_SWEEP_REFUSED", sa.UNKNOWN_ENTRY )
        return { "verdict": "NEW", "causal_ids": [] }
    out = sa.run_pending( data, sweep, DAY )
    assert out[ "audited" ] == 0 and out[ "failed" ] == 4, "the control: the d- items are what the sweep refuses"


def test_an_item_in_neither_list_stops_the_run_and_nothing_changes( data ):
    before = { p.name for p in folder_of( data ).glob( "*.json" ) }
    rc, text = run( data, *CODE, "--drop", "d-cccccccccc", "--reason", "r", "--apply" )
    assert rc == 3 and "is in neither --code nor --drop" in text and { p.name for p in folder_of( data ).glob( "*.json" ) } == before


def test_an_id_in_both_lists_is_refused( data ):
    rc, text = run( data, *CODE, *DROP, "--drop", "d-aaaaaaaaaa" )
    assert rc == 3 and "both as code and as dropped" in text


def test_an_item_that_is_not_a_d_id_is_refused( tmp_path ):
    sa.enqueue_pending( tmp_path, "n", "py", "g", "i", LIVE, DAY, known_miss=True, exclude_id="m.regroup", tie="heuristic" )
    sa.enqueue_pending( tmp_path, "n2", "py", "g", "i", LIVE, DAY )
    rc, text = run( tmp_path )
    assert rc == 3 and "not a d- id" in text


@pytest.mark.parametrize( "entries,held", [ ( [ ], 0 ), ( ENTRIES + [ { "id": "z.regroup", "file": "src/m.py", "name": "regroup", "line": 99 } ], 2 ) ] )
def test_a_definition_the_index_does_not_hold_exactly_once_is_refused_and_no_line_is_guessed( data, entries, held ):
    rc, text = run( data, *CODE, *DROP, entries=entries )
    assert rc == 3 and f"is held {held} times by the index, not once" in text


def test_a_corrupt_file_is_refused_not_skipped( data ):
    ( folder_of( data ) / "x.json" ).write_text( "not json" )
    rc, text = run( data, *CODE, *DROP )
    assert rc == 3 and "x.json is not a queue item" in text
    ( folder_of( data ) / "x.json" ).write_text( "{}" )
    assert run( data, *CODE, *DROP )[ 0 ] == 3


@pytest.mark.parametrize( "pair", [ "d-aaaaaaaaaa", "d-aaaaaaaaaa=src/m.py", "=src/m.py:regroup", "d-aaaaaaaaaa=:regroup" ] )
def test_a_code_pair_that_is_not_id_equals_file_colon_name_is_refused( data, pair ):
    rc, text = run( data, "--code", pair )
    assert rc == 3 and "is not d-id=file:name" in text


def test_removing_with_apply_needs_a_reason_and_changes_nothing_without_one( data ):
    rc, text = run( data, *CODE, *DROP, "--apply" )
    assert rc == 3 and "--reason is required" in text and len( items_of( data ) ) == 4


def test_a_rewrite_whose_target_file_already_exists_stops_there_and_keeps_the_old_file( data, monkeypatch ):
    monkeypatch.setattr( sa, "_write_once", lambda path, text: False )
    rc, text = run( data, *CODE, *DROP, "--reason", "r", "--apply" )
    assert rc == 3 and "already exists" in text and len( items_of( data ) ) == 4


def test_an_empty_folder_applies_an_empty_plan_and_logs_nothing( tmp_path ):
    ( tmp_path / "shadow-pending" ).mkdir()
    assert run( tmp_path, "--apply" )[ 0 ] == 0 and ( tmp_path / "shadow-audit" / sp.LOG_NAME ).read_text() == ""


def test_the_default_entries_come_from_the_lookup_tools_own_context( data, monkeypatch ):
    from lupin_mcp import reuse_tools as rt
    monkeypatch.setattr( rt, "context_from_environment", lambda: "ctx" )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( set(), ENTRIES if ctx == "ctx" else [ ], "sha", "gen" ) )
    out = io.StringIO()
    assert sp.main( [ str( folder_of( data ) ), *CODE, *DROP ], out=out ) == 0 and "rewrite d-aaaaaaaaaa -> m.regroup" in out.getvalue()


def test_the_default_output_is_stdout( data, capsys ):
    sp.main( [ str( folder_of( data ) ), *CODE, *DROP ], entries_fn=lambda: ENTRIES )
    assert "DRY-RUN" in capsys.readouterr().out
