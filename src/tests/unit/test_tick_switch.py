"""
The per-tick switch check that loops make, and the honoured rule that counts them.

Each case writes a real configuration file to a temporary folder. The check then reads the key
the way a running loop does, fresh from disk. Expected answers are literals.
"""
import datetime
import json
import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import cron_job_switches as sw
from lupin_mcp import cron_switch_read as csr

JOB = "probe-loop"
NOW = datetime.datetime( 2026, 11, 14, 15, 0, 0, tzinfo=datetime.timezone( datetime.timedelta( hours=-5 ) ) )


def _ini( tmp_path, line ):
    """
    Write a configuration file holding one line under a section header.

    Requires:
        - line is the text of the key line, or "" for none

    Ensures:
        - returns the file's path as a str
    """
    path = tmp_path / "lupin-app.ini"
    path.write_text( "[Lupin]\n" + line + "\n" )
    return str( path )


def _switch( tmp_path, line, with_summary=True ):
    """
    Build a TickSwitch over a temporary file, with its log captured.

    Requires:
        - line is the key line to write

    Ensures:
        - returns ( switch, logged lines, summary path, ini path )
    """
    ini     = _ini( tmp_path, line )
    summary = tmp_path / "job-summary.json"
    logged  = []
    switch  = csr.TickSwitch( JOB, lambda: ini, ( lambda: summary ) if with_summary else None, logged.append )
    return switch, logged, summary, ini


def test_a_true_key_lets_the_tick_work_and_logs_nothing_on_the_first_tick( tmp_path ):
    switch, logged, summary, _ = _switch( tmp_path, "cron job probe-loop enabled = true" )
    assert switch.allowed( NOW ) is True
    assert logged == []
    assert not summary.exists()


def test_a_false_key_skips_the_tick_and_logs_one_line_however_many_ticks_skip( tmp_path ):
    switch, logged, summary, _ = _switch( tmp_path, "cron job probe-loop enabled = false" )
    assert [ switch.allowed( NOW ) for _ in range( 3 ) ] == [ False, False, False ]
    assert logged == [ "probe-loop: INI key 'cron job probe-loop enabled' is false, so ticks skip their work until it is true" ]
    assert not summary.exists()


def test_flipping_the_file_takes_effect_on_the_next_tick_with_no_restart( tmp_path ):
    switch, logged, _, ini = _switch( tmp_path, "cron job probe-loop enabled = true" )
    assert switch.allowed( NOW ) is True
    with open( ini, "w" ) as handle: handle.write( "[Lupin]\ncron job probe-loop enabled = false\n" )
    assert switch.allowed( NOW ) is False
    with open( ini, "w" ) as handle: handle.write( "[Lupin]\ncron job probe-loop enabled = true\n" )
    assert switch.allowed( NOW ) is True
    assert logged == [ "probe-loop: INI key 'cron job probe-loop enabled' is false, so ticks skip their work until it is true",
                       "probe-loop: INI key 'cron job probe-loop enabled' is true, so ticks run again" ]


def test_a_missing_key_skips_the_tick_logs_an_error_and_writes_a_failed_summary( tmp_path ):
    switch, logged, summary, _ = _switch( tmp_path, "" )
    assert switch.allowed( NOW ) is False
    assert logged == [ "probe-loop: ERROR: INI key 'cron job probe-loop enabled' is missing or holds neither true nor false, so ticks skip their work" ]
    attempt = json.loads( summary.read_text() )[ "last_attempt" ]
    assert ( attempt[ "outcome" ], attempt[ "stage" ], attempt[ "failure" ] ) == ( "failed", "switch", "switch unreadable" )
    assert attempt[ "evidence" ] == "INI key 'cron job probe-loop enabled' is missing or holds neither true nor false"
    assert attempt[ "started_at" ] == "2026-11-14T15:00:00-05:00"


def test_a_word_other_than_true_or_false_is_unreadable_never_on( tmp_path ):
    switch, logged, summary, _ = _switch( tmp_path, "cron job probe-loop enabled = yes" )
    assert switch.allowed( NOW ) is False
    assert logged[ 0 ].startswith( "probe-loop: ERROR:" )
    assert json.loads( summary.read_text() )[ "last_attempt" ][ "outcome" ] == "failed"


def test_an_unreadable_key_with_no_summary_still_skips_and_logs( tmp_path ):
    switch, logged, summary, _ = _switch( tmp_path, "", with_summary=False )
    assert switch.allowed( NOW ) is False
    assert len( logged ) == 1
    assert not summary.exists()


def test_a_summary_that_cannot_be_written_is_reported_and_the_tick_still_skips( tmp_path ):
    ini    = _ini( tmp_path, "" )
    logged = []
    def broken(): raise OSError( "disk full" )
    switch = csr.TickSwitch( JOB, lambda: ini, broken, logged.append )
    assert switch.allowed( NOW ) is False
    assert logged[ -1 ] == "probe-loop: could not write the failed summary: disk full"


def test_a_job_is_honoured_by_job_run_or_by_a_named_reader_and_its_key():
    assert sw.is_honoured( { "job": "a", "cron_managed": True } ) is True
    assert sw.is_honoured( { "job": "a", "enabled_key": "cron job a enabled", "switch_reader": "m:f" } ) is True
    assert sw.is_honoured( { "job": "a", "switch_reader": "m:f" } ) is False                                   # a reader with no key
    assert sw.is_honoured( { "job": "a", "enabled_key": "cron job a enabled" } ) is False                      # a key nothing reads
    assert sw.is_honoured( { "job": "a", "enabled_key": "cron job a enabled", "switch_reader": "  " } ) is False
    assert sw.is_honoured( { "job": "a", "enabled_key": "cron job a enabled", "switch_reader": 7 } ) is False
    assert sw.is_honoured( { "job": "a", "cron_managed": False } ) is False
