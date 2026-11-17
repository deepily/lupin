"""
Unit tests for ledger_merge: rotated judge ledgers merge into the live one, read-only.

The files are written by harness_runner.Ledger itself, bound as the daily run binds a ledger.
"""
import json

import pytest

from cosa.repo.doc_lint import harness_runner
from cosa.repo.duplicate_check import ledger_merge as lm

BINDING = "claude_cli=/bin/claude|version={}|max-plan|max-plan"


def key_of( old, model="claude-fable-5-1" ):
    """Build a ledger key for a definition, as the judge does, under the given model."""
    return harness_runner.ledger_key( "semdup", { "old": old, "new": "def f(): pass" }, "p1", model, 0 )


def make( folder, name, version, rulings ):
    """Write one ledger file bound to a Claude Code version; rulings is { key: value }."""
    ledger = harness_runner.Ledger( folder / name, binding=BINDING.format( version ) )
    for key, value in rulings.items(): ledger.put( key, value )
    return folder / name


def value( verdict ): return { "rulings": [ { "candidate": "d-1", "verdict": verdict, "reason": "r" } ] }


def test_merge_adds_every_missing_ruling_keeps_the_model_id_and_stamps_the_source_version( tmp_path ):
    fable, opus = key_of( "a" ), key_of( "b", "claude-opus-5-5" )
    make( tmp_path, "judge-ledger.jsonl", "2.1.325 (Claude Code)", { opus: value( "related" ) } )
    make( tmp_path, "judge-ledger.claude-2.1.317.jsonl", "2.1.317 (Claude Code)", { fable: value( "near_duplicate" ) } )
    report = lm.merge_rotated( tmp_path, apply=True )
    assert report == { "files": 1, "entries": 1, "distinct": 1, "added": 1, "already_held": 0, "conflicts": 0, "models": { "claude-fable-5-1": 1 } }
    lines = [ json.loads( l ) for l in ( tmp_path / "judge-ledger.jsonl" ).read_text( encoding="utf-8" ).splitlines() ]
    assert [ l for l in lines if l.get( "key" ) == fable ] == [ { "key": fable, "value": value( "near_duplicate" ), "cli": "2.1.317" } ]
    assert harness_runner.Ledger( tmp_path / "judge-ledger.jsonl" ).get( opus ) == value( "related" ), "the live ruling is kept"


def test_merge_dry_run_writes_nothing_and_a_second_apply_adds_nothing( tmp_path ):
    make( tmp_path, "judge-ledger.jsonl", "2.1.325 (Claude Code)", {} )
    rotated = make( tmp_path, "judge-ledger.claude-2.1.317.jsonl", "2.1.317 (Claude Code)", { key_of( "a" ): value( "related" ) } )
    live    = tmp_path / "judge-ledger.jsonl"
    before  = ( live.read_bytes(), rotated.read_bytes() )
    assert lm.merge_rotated( tmp_path )[ "added" ] == 1 and ( live.read_bytes(), rotated.read_bytes() ) == before
    assert lm.merge_rotated( tmp_path, apply=True )[ "added" ] == 1
    assert rotated.read_bytes() == before[ 1 ], "a rotated file is never changed"
    assert lm.merge_rotated( tmp_path, apply=True )[ "added" ] == 0


def test_merge_takes_a_live_key_as_it_is_and_the_newest_version_among_rotated_files( tmp_path ):
    held, both = key_of( "held" ), key_of( "both" )
    make( tmp_path, "judge-ledger.jsonl", "2.1.325 (Claude Code)", { held: value( "related" ) } )
    make( tmp_path, "judge-ledger.claude-2.1.9.jsonl", "2.1.9 (Claude Code)", { held: value( "different" ), both: value( "old" ) } )
    make( tmp_path, "judge-ledger.claude-2.1.10.jsonl", "2.1.10 (Claude Code)", { both: value( "new" ) } )
    report = lm.merge_rotated( tmp_path, apply=True )
    assert report[ "already_held" ] == 1 and report[ "added" ] == 1 and report[ "conflicts" ] == 1
    merged = harness_runner.Ledger( tmp_path / "judge-ledger.jsonl" )
    assert merged.get( held ) == value( "related" ) and merged.get( both ) == value( "new" ), "2.1.10 is newer than 2.1.9"


def test_version_of_reads_the_version_and_a_missing_binding_sorts_first():
    assert lm.version_of( BINDING.format( "2.1.317 (Claude Code)" ) ) == ( 2, 1, 317 ) and lm.version_of( None ) == () and lm.version_of( "no version" ) == ()


@pytest.mark.parametrize( "bound", [ "claude_cli=/other/claude|version=2.1.317 (Claude Code)|max-plan|max-plan", "claude_cli=/bin/claude|version=2.1.317 (Claude Code)|work-server|work-server", None ] )
def test_a_rotated_file_bound_to_another_binary_or_backend_or_to_nothing_is_refused_and_nothing_is_written( tmp_path, bound ):
    make( tmp_path, "judge-ledger.jsonl", "2.1.325 (Claude Code)", {} )
    good  = make( tmp_path, "judge-ledger.claude-2.1.316.jsonl", "2.1.316 (Claude Code)", { key_of( "a" ): value( "related" ) } )
    other = tmp_path / "judge-ledger.claude-2.1.317.jsonl"
    other.write_text( ( json.dumps( { "binding": bound } ) + "\n" if bound else "" ) + json.dumps( { "key": key_of( "b" ), "value": value( "related" ) } ) + "\n", encoding="utf-8" )
    live   = tmp_path / "judge-ledger.jsonl"
    before = live.read_bytes()
    with pytest.raises( harness_runner.LedgerBindingError ): lm.merge_rotated( tmp_path, apply=True )
    assert live.read_bytes() == before and good.exists(), "the refusal comes before the first copy"


def test_a_live_ledger_with_no_binding_refuses_the_merge( tmp_path ):
    ( tmp_path / "judge-ledger.jsonl" ).write_text( "", encoding="utf-8" )
    make( tmp_path, "judge-ledger.claude-2.1.317.jsonl", "2.1.317 (Claude Code)", { key_of( "a" ): value( "related" ) } )
    with pytest.raises( harness_runner.LedgerBindingError ): lm.merge_rotated( tmp_path )


def test_rotated_files_can_be_limited_to_those_closed_before_a_day( tmp_path ):
    import os
    from cosa.repo.duplicate_check import ledger_merge as lm
    old, new = tmp_path / "judge-ledger.claude-1.jsonl", tmp_path / "judge-ledger.claude-2.jsonl"
    for p in ( old, new ): p.write_text( "" )
    os.utime( old, ( 1_700_000_000, 1_700_000_000 ) )                     # 2023-11-14
    assert lm.rotated_files( tmp_path, closed_before="2023-11-15" ) == [ old ]
    assert lm.rotated_files( tmp_path, closed_before="2023-11-14" ) == []
    assert set( lm.rotated_files( tmp_path ) ) == { old, new }
