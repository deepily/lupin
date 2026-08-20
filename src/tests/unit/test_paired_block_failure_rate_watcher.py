"""
Unit coverage for the per-block failure-rate watcher (row d8d019f6, María's row 2ebe4ccb).

THE CONTROL THIS PROTECTS: a paired run that degrades CATEGORICALLY passes every
sample-size check — ~300 pairs survive a 32% failure rate — while the two arms end up
scored on differently-composed corpora. The watcher's job is to notice a rate that
CLIMBS, not a rate that is merely high. These tests pin that distinction, because a
detector that fires on any bad run is a detector people learn to ignore.
"""

import importlib.util, json, os, tempfile

import pytest

import cosa.utils.util as cu

_SPEC = importlib.util.spec_from_file_location(
    "block_watch", os.path.join( cu.get_project_root(), "src", "scripts", "watch-paired-block-failure-rate.py" ) )
watcher = importlib.util.module_from_spec( _SPEC )
_SPEC.loader.exec_module( watcher )


def _rec( seq, ok, wall_ts=1000.0 ):
    return { "phase": "end", "seq": seq, "ok": ok, "wall_ts": wall_ts }


def test_failure_rate_counts_the_string_false_as_a_failure():
    """The jsonl stores ok as the STRING 'False'; a truthiness check would score it as a pass."""
    block = [ _rec( i, "False" ) for i in range( 5 ) ] + [ _rec( i, "True" ) for i in range( 5 ) ]
    assert watcher.failure_rate( block ) == 0.5


def test_escalation_fires_on_the_2026_08_17_signature():
    """10%, 10%, 4%, 38% — the real shape from the 08-17 run. RED if the detector goes quiet."""
    assert watcher.escalating( [ 0.10, 0.10, 0.04, 0.38 ] )


def test_a_uniformly_bad_run_is_NOT_escalation():
    """A flat 30% is a different problem with a different remedy; this control must stay quiet
    about it or it becomes noise nobody reads."""
    assert not watcher.escalating( [ 0.30, 0.30, 0.30, 0.30 ] )


def test_too_few_blocks_never_fires():
    """Two blocks cannot establish a baseline, so a scary-looking second block is not evidence."""
    assert not watcher.escalating( [ 0.02, 0.90 ] )


def test_a_small_rise_off_a_near_zero_base_does_not_fire():
    """Doubling 1% is 2% — arithmetically a doubling, operationally nothing. The absolute floor
    of 25% is what stops the detector crying at ordinary jitter."""
    assert not watcher.escalating( [ 0.01, 0.01, 0.02, 0.04 ] )


def test_read_end_records_skips_start_rows_malformed_lines_and_old_runs():
    """The file is read WHILE it is being written, and it accumulates across runs."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join( d, "ask-attempts.jsonl" )
        with open( p, "w" ) as fh:
            fh.write( json.dumps( { "phase": "start", "seq": 1, "wall_ts": 2000.0 } ) + "\n" )
            fh.write( json.dumps( _rec( 1, "True",  wall_ts=1000.0 ) ) + "\n" )   # a PRIOR run
            fh.write( json.dumps( _rec( 2, "True",  wall_ts=2000.0 ) ) + "\n" )
            fh.write( json.dumps( _rec( 3, "False", wall_ts=2000.0 ) ) + "\n" )
            fh.write( "{not json" + "\n" )                                        # half-flushed tail
        recs = watcher.read_end_records( p, since=1500.0 )
        assert [ r[ "seq" ] for r in recs ] == [ 2, 3 ]


def test_read_end_records_on_a_missing_file_is_empty_not_an_error():
    """The watcher may be armed before the run creates the file."""
    assert watcher.read_end_records( "/nonexistent/ask-attempts.jsonl", since=0.0 ) == []


def test_blocks_yields_only_COMPLETE_blocks():
    """A partial trailing block would report a failure rate over a handful of records and read
    as a spike; the run is still writing it."""
    recs = [ _rec( i, "True" ) for i in range( 120 ) ]
    assert [ i for i, _ in watcher.blocks( recs, 50 ) ] == [ 0, 1 ]


def test_main_prints_one_line_per_block_and_flags_escalation( capsys ):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join( d, "a.jsonl" )
        with open( p, "w" ) as fh:
            for rate in ( 0.0, 0.0, 1.0 ):                 # clean, clean, then a wipeout
                for i in range( 10 ):
                    fh.write( json.dumps( _rec( i, "False" if i < rate * 10 else "True" ) ) + "\n" )
        assert watcher.main( [ "--path", p, "--block", "10" ] ) == 0
    out = capsys.readouterr().out
    assert out.count( "block " ) == 3
    assert "ESCALATING" in out.splitlines()[ 2 ]
    assert "ESCALATING" not in out.splitlines()[ 0 ]
