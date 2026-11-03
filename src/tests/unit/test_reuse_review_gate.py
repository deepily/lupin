"""
Unit tests for the `reuse review gating` flag: report-only when false, reject when true.
"""
import json
import pathlib

import pytest

import cosa.utils.util as cu
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


def test_absent_key_could_not_check_and_says_so( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "other = 1\n" ) ) is None
    assert gate.LOG_TAG in capsys.readouterr().err


def test_absent_key_quiet_prints_nothing( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "" ), quiet=True ) is None
    assert capsys.readouterr().err == ""


def test_doubled_key_could_not_check( tmp_path ):
    assert gate.read_gating( _ini( tmp_path, "reuse review gating = true\nreuse review gating = true\n" ), quiet=True ) is None


def test_garbled_value_could_not_check_and_says_so( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "reuse review gating = maybe\n" ) ) is None
    assert "'maybe'" in capsys.readouterr().err


def test_garbled_value_quiet( tmp_path, capsys ):
    assert gate.read_gating( _ini( tmp_path, "reuse review gating = maybe\n" ), quiet=True ) is None
    assert capsys.readouterr().err == ""


def test_unreadable_file_could_not_check( tmp_path ):
    assert gate.read_gating( str( tmp_path / "missing.ini" ), quiet=True ) is None


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


# ---- C1: finding kinds, fail closed, exit 3 (Plan 3 section 12.3) ----

import io
import pathlib

REAL_LINTER_RECORDS = pathlib.Path( __file__ ).parent / "docstring_lint_real_records.json"      # printed by the real linter with --json on a probe file


def _real_records():
    return json.loads( REAL_LINTER_RECORDS.read_text( encoding="utf-8" ) )


def test_the_real_linter_record_has_exactly_the_keys_the_gate_calls_linter_shaped():
    # red when: LINTER_KEYS is a guess. The fixture is the linter's own output, so a key it adds or drops shows here.
    records = _real_records()
    assert len( records ) > 1
    assert all( set( r ) == gate.LINTER_KEYS for r in records )


def test_linter_shaped_record_is_docstring_lint():
    # the named test of the linter-shape rule, fed with records printed by the real linter
    for record in _real_records(): assert gate.kind_of( record ) == gate.ADVISORY_KIND
    verdict = gate.evaluate( _real_records(), True )
    assert ( verdict[ "mode" ], verdict[ "reject" ], verdict[ "blocking" ] ) == ( "reject", False, [] )


@pytest.mark.parametrize( "record", [
    { "path": "a.py", "line": 3, "rule": "", "message": "m" },                       # no rule id
    { "path": "a.py", "line": 3, "rule": 7, "message": "m" },                        # a rule id that is not text
    { "path": "a.py", "line": 3, "rule": "summary-length" },                         # a key short
    { "path": "a.py", "line": 3, "rule": "summary-length", "message": "m", "x": 1 }, # a key over
    "summary is 99 characters",                                                      # a bare string
    { },
] )
def test_a_finding_with_no_kind_fails_closed_when_gating_is_on( record ):
    assert gate.kind_of( record ) is None and gate.blocks( record )
    assert gate.evaluate( [ record ], True )[ "reject" ] is True
    assert gate.evaluate( [ record ], False )[ "reject" ] is False                   # the same finding only reports when the gate is off


@pytest.mark.parametrize( "kind", gate.REUSE_KINDS )
def test_every_reuse_evidence_kind_blocks( kind ):
    finding = { "kind": kind, "detail": "x" }
    assert gate.kind_of( finding ) == kind and gate.blocks( finding )
    verdict = gate.evaluate( [ finding ], True )
    assert ( verdict[ "mode" ], verdict[ "reject" ], verdict[ "blocking" ] ) == ( "reject", True, [ finding ] )


def test_one_ignored_ruling_is_refused_with_gating_on_and_only_reported_with_it_off():
    # ruling 9's words: a diff that ignores a reviewer's DUPLICATE or EXTEND ruling is refused
    finding = { "kind": "ignored_ruling", "symbol": "m.f", "ruling": "EXTEND m.g" }
    assert gate.evaluate( [ finding ], True )[ "reject" ] is True
    off = gate.evaluate( [ finding ], False )
    assert ( off[ "mode" ], off[ "reject" ], off[ "count" ] ) == ( "report-only", False, 1 )


def test_a_kind_the_gate_does_not_know_blocks():
    assert gate.blocks( { "kind": "banana" } ) and not gate.blocks( { "kind": "docstring_lint" } )
    assert gate.kind_of( { "kind": "" } ) is None                                      # an empty kind is no kind


def test_only_docstring_lint_findings_never_reject_and_one_reuse_finding_among_them_does():
    lint = { "kind": "docstring_lint", "path": "a.py" }
    mixed = gate.evaluate( [ lint, _real_records()[ 0 ], { "kind": "no_receipt", "symbol": "m.f" } ], True )
    assert mixed[ "reject" ] is True and mixed[ "blocking" ] == [ { "kind": "no_receipt", "symbol": "m.f" } ]
    assert mixed[ "count" ] == 3 and len( mixed[ "findings" ] ) == 3                   # advisory findings are still reported
    assert gate.evaluate( [ lint, _real_records()[ 0 ] ], True )[ "reject" ] is False


def test_evaluate_with_gating_none_is_neither_a_pass_nor_a_refusal():
    verdict = gate.evaluate( [ { "kind": "no_receipt" } ], None )
    assert ( verdict[ "mode" ], verdict[ "reject" ], verdict[ "count" ] ) == ( "could-not-check", None, 1 )


@pytest.mark.parametrize( "body", [
    "other = 1\n",                                                                      # absent
    "reuse review gating = true\nreuse review gating = true\n",                       # doubled
    "reuse review gating = maybe\n",                                                   # garbled
] )
def test_main_exits_3_for_an_absent_doubled_or_garbled_key_even_with_no_findings( tmp_path, capsys, body ):
    findings = tmp_path / "f.json"; findings.write_text( "[]", encoding="utf-8" )
    assert gate.main( [ "--findings", str( findings ), "--ini", _ini( tmp_path, body ) ] ) == gate.EXIT_COULD_NOT_CHECK == 3
    captured = capsys.readouterr()
    out      = json.loads( captured.out )
    assert ( out[ "mode" ], out[ "reject" ] ) == ( "could-not-check", None )
    assert gate.LOG_TAG in captured.err                                                 # the tagged line goes to stderr


def test_main_exits_3_and_says_so_for_a_file_that_is_not_there( tmp_path, capsys ):
    # the test container mounts only src, so the main checkout's ini can be missing there
    findings = tmp_path / "f.json"; findings.write_text( "[]", encoding="utf-8" )
    assert gate.main( [ "--findings", str( findings ), "--ini", str( tmp_path / "missing.ini" ) ] ) == 3
    captured = capsys.readouterr()
    assert gate.LOG_TAG in captured.err and "could not check" in captured.err


def test_main_exit_codes_for_the_three_answers( tmp_path ):
    findings = tmp_path / "f.json"; findings.write_text( json.dumps( [ { "kind": "ignored_ruling" } ] ), encoding="utf-8" )
    ini = lambda v: _ini( tmp_path, f"reuse review gating = {v}\n" )
    assert gate.main( [ "--findings", str( findings ), "--ini", ini( "true" ) ], out=io.StringIO() ) == 1
    assert gate.main( [ "--findings", str( findings ), "--ini", ini( "false" ) ], out=io.StringIO() ) == 0


def test_the_ini_path_resolver_finds_the_main_checkouts_file_from_a_worktree( monkeypatch ):
    # the path is derived by the resolver (git's common directory); the expected one comes from the git command itself
    import subprocess
    import cosa.utils.util as cu
    monkeypatch.delenv( gate.INI_OVERRIDE, raising=False )
    root   = cu.get_project_root()
    common = subprocess.run( [ "git", "-C", root, "rev-parse", "--path-format=absolute", "--git-common-dir" ], capture_output=True, text=True, check=True ).stdout.strip()
    assert gate.ini_path() == str( pathlib.Path( common ).parent / "src" / "conf" / "lupin-app.ini" )


def conf_text( name ):
    """Ensures: returns the text of a file in the project's conf folder."""
    return ( pathlib.Path( cu.get_project_root() ) / "src" / "conf" / name ).read_text( encoding="utf-8" )


def explainer_of_the_gating_key():
    """Ensures: returns the explainer line of the gating key, exactly one."""
    lines = [ l for l in conf_text( "lupin-app-splainer.ini" ).splitlines() if l.startswith( gate.GATING_KEY ) ]
    assert len( lines ) == 1
    return lines[ 0 ]


def test_the_explainer_names_every_blocking_finding_kind_and_the_advisory_one():
    line = explainer_of_the_gating_key()
    for kind in ( *gate.REUSE_KINDS, gate.ADVISORY_KIND ): assert f"`{kind}`" in line, kind


def test_the_explainer_states_rulings_switch_on_rule_and_the_could_not_check_exit():
    line = explainer_of_the_gating_key()
    assert "ruling 14" in line and "merged with tests passing" in line and "the manager flips it" in line
    assert "exits 3" in line and "no kind" in line and "does not know" in line


def test_neither_the_explainer_nor_the_ini_comment_keeps_the_stale_rule():
    stale = ( "until Rick sets a recall bar", "Stays false until", "carries any finding", "reads as false" )
    for text in ( explainer_of_the_gating_key(), conf_text( "lupin-app.ini" ).split( "reuse review gating  " )[ 0 ].rsplit( "# REUSE REVIEW GATING", 1 )[ 1 ] ):
        for phrase in stale: assert phrase not in text, phrase

