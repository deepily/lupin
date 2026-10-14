"""
Unit tests for the `reuse review gating` flag: report-only when false, reject when true.
"""
import json

import pytest

from lupin_mcp import reuse_review_gate as gate


def _ini( tmp_path, body ):
    p = tmp_path / "lupin-app.ini"
    p.write_text( "[default]\n" + body, encoding="utf-8" )
    return str( p )


@pytest.mark.parametrize( "body, expected", [
    ( "reuse review gating = true\n",  True  ),
    ( "reuse review gating = false\n", False ),
    ( "reuse review gating = TRUE\n",  True  ),
] )
def test_read_gating_clean_values( tmp_path, capsys, body, expected ):
    assert gate.read_gating( _ini( tmp_path, body ) ) is expected
    assert capsys.readouterr().err == ""


def test_absent_key_reads_false_and_says_so( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "other = 1\n" ) ) is False
    assert gate.LOG_TAG in capsys.readouterr().err


def test_absent_key_quiet_prints_nothing( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "" ), quiet=True ) is False
    assert capsys.readouterr().err == ""


def test_doubled_key_reads_false( tmp_path ):
    assert gate.read_gating( _ini( tmp_path, "reuse review gating = true\nreuse review gating = true\n" ), quiet=True ) is False


def test_garbled_value_reads_false_and_says_so( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "reuse review gating = maybe\n" ) ) is False
    assert "'maybe'" in capsys.readouterr().err


def test_garbled_value_quiet( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "reuse review gating = maybe\n" ), quiet=True ) is False
    assert capsys.readouterr().err == ""


def test_unreadable_file_reads_false( tmp_path ):
    assert gate.read_gating( str( tmp_path / "missing.ini" ), quiet=True ) is False


def test_ini_path_env_override( monkeypatch ):
    monkeypatch.setenv( gate.INI_OVERRIDE, "/x/y.ini" )
    assert gate.ini_path() == "/x/y.ini"


def test_ini_path_default_is_main_checkout( monkeypatch ):
    monkeypatch.delenv( gate.INI_OVERRIDE, raising=False )
    monkeypatch.setattr( gate.fleet_size_cap, "main_checkout_ini_path", lambda: "/main/lupin-app.ini" )
    assert gate.ini_path() == "/main/lupin-app.ini"


def test_read_gating_default_path_uses_ini_path( tmp_path, monkeypatch ):
    monkeypatch.setenv( gate.INI_OVERRIDE, _ini( tmp_path, "reuse review gating = true\n" ) )
    assert gate.read_gating() is True


FINDINGS = [ { "rule": "docstring-length", "path": "a.py", "line": 3 }, "plain string finding" ]


def test_report_only_when_gating_false():
    v = gate.evaluate( FINDINGS, False )
    assert ( v[ "mode" ], v[ "reject" ], v[ "count" ] ) == ( "report-only", False, 2 )
    assert v[ "findings" ] == FINDINGS


def test_reject_when_gating_true():
    v = gate.evaluate( FINDINGS, True )
    assert ( v[ "mode" ], v[ "reject" ] ) == ( "reject", True )
    assert v[ "findings" ] == FINDINGS


def test_gating_true_with_no_findings_does_not_reject():
    assert gate.evaluate( [], True )[ "reject" ] is False


def test_flipping_the_flag_in_the_file_flips_the_behaviour( tmp_path, capsys ):
    """The same findings: report-only with the key false, rejected after the file says true."""
    findings = tmp_path / "f.json"
    findings.write_text( json.dumps( FINDINGS ), encoding="utf-8" )
    ini = tmp_path / "lupin-app.ini"
    ini.write_text( "[default]\nreuse review gating = false\n", encoding="utf-8" )
    assert gate.main( [ "--findings", str( findings ), "--ini", str( ini ) ] ) == 0
    assert json.loads( capsys.readouterr().out )[ "mode" ] == "report-only"
    ini.write_text( "[default]\nreuse review gating = true\n", encoding="utf-8" )
    assert gate.main( [ "--findings", str( findings ), "--ini", str( ini ) ] ) == 1
    out = json.loads( capsys.readouterr().out )
    assert ( out[ "mode" ], out[ "reject" ], out[ "count" ] ) == ( "reject", True, 2 )


def test_main_writes_to_given_stream( tmp_path ):
    import io
    findings = tmp_path / "f.json"
    findings.write_text( "[]", encoding="utf-8" )
    buf = io.StringIO()
    assert gate.main( [ "--findings", str( findings ), "--ini", _ini( tmp_path, "reuse review gating = true\n" ) ], out=buf ) == 0
    assert json.loads( buf.getvalue() )[ "reject" ] is False
