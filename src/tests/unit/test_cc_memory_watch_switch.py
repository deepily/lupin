"""
The side-services switch in the runaway-memory watcher.

The watcher is deployed as a lone copy and run by the system python, so it cannot import
lupin_mcp. It carries its own copy of the parse rule. The parity tests here fail when the copy and
the original drift apart, in their source and in what they answer.
"""
import inspect
import os
import pathlib
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.utils import cc_memory_watch as watch
from lupin_mcp import cron_switch_read as csr

KEY = "cron job side-services " + "enabled"

VALUES = [ "true", "TRUE", " True ", "false", "False", "", "  ", "yes", "no", "1", "0", "on", "truee", None, 1, True, [], b"true" ]


def _config( tmp_path, text ):
    """Write a config file with the given text and return its path as a string."""
    path = tmp_path / "settings.conf"
    path.write_text( text, encoding="utf-8" )
    return str( path )


def test_the_vendored_parse_rule_has_the_same_source_as_the_original():
    assert inspect.getsource( watch.parse_switch ) == inspect.getsource( csr.parse_switch )


@pytest.mark.parametrize( "raw", VALUES, ids=repr )
def test_the_vendored_parse_rule_answers_as_the_original_does( raw ):
    assert watch.parse_switch( raw ) == csr.parse_switch( raw )


def test_the_value_table_holds_all_three_answers():
    answers = { watch.parse_switch( raw ) for raw in VALUES }
    assert answers == { True, False, None }


def test_the_vendored_key_is_the_one_the_registry_and_the_original_name():
    assert watch.SWITCH_KEY == csr.switch_key( "side-services" )


CASES = [
    ( f"{KEY} = true\n",                              True ),
    ( f"{KEY}=false\n",                               False ),
    ( f"{KEY}   =   TRUE   \n",                       True ),
    ( "",                                             None ),
    ( f"{KEY} = yes\n",                               None ),
    ( f"{KEY} =\n",                                   None ),
    ( f"{KEY} = true\n{KEY} = false\n",               None ),
    ( f"# {KEY} = true\n",                            None ),
    ( f"  {KEY} = true\n",                            None ),
    ( f"{KEY} enabled = true\n",                      None ),
    ( f"[a]\n{KEY} = true\n[b]\nother = 1\n",         True ),
]


@pytest.mark.parametrize( "text,expected", CASES, ids=[ repr( case[ 0 ] ) for case in CASES ] )
def test_reading_the_config_file_agrees_with_the_original_reader( tmp_path, text, expected ):
    path = _config( tmp_path, text )
    assert watch.read_switch( path ) is expected
    assert csr.read_switch( path, "side-services" ) is expected


def test_a_missing_file_reads_as_unknown( tmp_path ):
    assert watch.read_switch( str( tmp_path / "absent.conf" ) ) is None
    assert csr.read_switch( str( tmp_path / "absent.conf" ), "side-services" ) is None


def test_a_file_that_is_not_utf8_reads_as_unknown( tmp_path ):
    path = tmp_path / "binary.conf"
    path.write_bytes( b"\xff\xfe\x00" + KEY.encode() + b" = true\n" )
    assert watch.read_switch( str( path ) ) is None


def test_the_real_config_file_holds_a_value_both_readers_accept():
    real = str( pathlib.Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "conf" / ( "lupin-app" + ".ini" ) )
    assert watch.read_switch( real ) in ( True, False )
    assert watch.read_switch( real ) is csr.read_switch( real, "side-services" )


def test_a_gate_with_no_config_file_never_reads_anything( tmp_path ):
    lines = []
    gate  = watch.SwitchGate( None, log=lines.append )
    assert gate.allowed() is True
    assert lines == []


def test_the_gate_logs_one_line_per_change_and_reads_fresh_each_time( tmp_path ):
    lines = []
    path  = tmp_path / "settings.conf"
    gate  = watch.SwitchGate( str( path ), log=lines.append )
    path.write_text( f"{KEY} = true\n" )
    assert gate.allowed() is True
    assert gate.allowed() is True
    assert lines == []                                   # on at the first read is not news
    path.write_text( f"{KEY} = false\n" )
    assert gate.allowed() is False
    assert gate.allowed() is False
    assert len( lines ) == 1 and "is false" in lines[ 0 ]
    path.write_text( f"{KEY} = true\n" )
    assert gate.allowed() is True
    assert len( lines ) == 2 and "is true, so sampling resumes" in lines[ 1 ]
    path.write_text( "" )
    assert gate.allowed() is False
    assert gate.allowed() is False
    assert len( lines ) == 3 and lines[ 2 ].startswith( "cc-memory-watch: ERROR" ) and KEY in lines[ 2 ]


def test_a_gate_that_starts_off_or_unreadable_says_so_once( tmp_path ):
    lines = []
    assert watch.SwitchGate( _config( tmp_path, f"{KEY} = false\n" ), log=lines.append ).allowed() is False
    assert watch.SwitchGate( str( tmp_path / "absent.conf" ), log=lines.append ).allowed() is False
    assert [ "is false" in lines[ 0 ], "ERROR" in lines[ 1 ] ] == [ True, True ]


# ── the loop ─────────────────────────────────────────────────────────────

@pytest.fixture
def counted( monkeypatch ):
    """Replace run_once with a counter so a test sees whether a pass sampled."""
    calls = []
    monkeypatch.setattr( watch, "run_once", lambda tracker, emit, now=None: calls.append( now ) or [] )
    return calls


def test_an_off_switch_skips_the_pass_and_a_true_switch_samples( tmp_path, counted, capsys ):
    off = _config( tmp_path, f"{KEY} = false\n" )
    assert watch.main( [ "--once", "--ini", off ] ) == 0
    assert counted == []
    assert "is false" in capsys.readouterr().out
    on = _config( tmp_path, f"{KEY} = true\n" )
    assert watch.main( [ "--once", "--ini", on ] ) == 0
    assert len( counted ) == 1


def test_an_unreadable_switch_skips_the_pass( tmp_path, counted, capsys ):
    assert watch.main( [ "--once", "--ini", str( tmp_path / "absent.conf" ) ] ) == 0
    assert counted == []
    assert "ERROR" in capsys.readouterr().out


def test_no_ini_argument_means_no_gate( counted ):
    assert watch.main( [ "--once" ] ) == 0
    assert len( counted ) == 1


def test_the_loop_stays_alive_while_off_and_resumes_when_the_switch_flips( tmp_path, counted, monkeypatch ):
    path   = tmp_path / "settings.conf"
    path.write_text( f"{KEY} = false\n" )
    sleeps = []

    def fake_sleep( seconds ):
        sleeps.append( seconds )
        if len( sleeps ) == 2: path.write_text( f"{KEY} = true\n" )
        if len( sleeps ) == 3: raise KeyboardInterrupt

    monkeypatch.setattr( watch.time, "sleep", fake_sleep )
    assert watch.main( [ "--ini", str( path ), "--interval", "5" ] ) == 0
    assert sleeps == [ 5.0, 5.0, 5.0 ]
    assert len( counted ) == 1, "two off passes sampled nothing and the first on pass sampled once"


def test_an_interrupt_while_off_ends_the_loop( tmp_path, counted, monkeypatch ):
    def interrupt( seconds ): raise KeyboardInterrupt

    monkeypatch.setattr( watch.time, "sleep", interrupt )
    assert watch.main( [ "--ini", _config( tmp_path, f"{KEY} = false\n" ) ] ) == 0
    assert counted == []


def test_the_registry_names_the_loop_that_calls_the_gate():
    assert ".allowed(" in inspect.getsource( watch.main )


def test_the_unit_template_passes_the_main_config_file_to_the_watcher():
    template = ( pathlib.Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "scripts" / "lupin-cc-memory-watch.service" ).read_text()
    assert "--ini __LUPIN_ROOT__/src/conf/" + "lupin-app" + ".ini" in template
