"""
The runner half of `detect_thread_credited_coverage.py`.

The sibling file tests the pure reduction of an attribution map.
These cases cover the parts around it: finding the project root,
running pytest under the tracer, and the report and exit code of `main()`.
A failed or truncated run must never read as "no thread-credited lines".
"""

import json
import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" ) )

import detect_thread_credited_coverage as dtc


def test_the_project_root_comes_from_lupin_root( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", "/some/tree" )
    assert dtc._project_root() == "/some/tree"


def test_an_unset_lupin_root_refuses( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match = "LUPIN_ROOT not set" ):
        dtc._project_root()


class _Done:
    def __init__( self, returncode, stdout="", stderr="" ):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_clean_run_returns_the_map_the_plugin_wrote( monkeypatch, tmp_path ):
    seen = { }
    out  = str( tmp_path / "attrib.json" )
    def fake_run( cmd, cwd, env, capture_output, text ):
        seen.update( cmd=cmd, cwd=cwd, env=env )
        with open( env[ "LUPIN_THREAD_ATTRIB_OUT" ], "w" ) as fh: json.dump( { "T": { "f.py": [ 3 ] } }, fh )
        return _Done( 0 )
    monkeypatch.setattr( dtc.subprocess, "run", fake_run )
    got = dtc._run_attributed( "src/tests/unit/x", "/root", out, [ "-k", "foo" ] )
    assert got == { "T": { "f.py": [ 3 ] } }
    assert seen[ "cwd" ] == "/root"
    assert seen[ "cmd" ][ 3 ] == "src/tests/unit/x" or "src/tests/unit/x" in seen[ "cmd" ]
    assert seen[ "cmd" ][ -2: ] == [ "-k", "foo" ]
    assert "thread_attribution_plugin" in seen[ "cmd" ]
    assert seen[ "env" ][ "LUPIN_THREAD_ATTRIB_OUT" ] == out
    assert seen[ "env" ][ "LUPIN_THREAD_ATTRIB_PREFIX" ] == os.path.join( "/root", "src" ) + os.sep
    assert seen[ "env" ][ "PYTHONPATH" ].startswith( os.path.join( "/root", "src" ) + os.pathsep +
                                                      os.path.join( "/root", "src", "scripts" ) )


def test_a_failing_run_refuses_and_shows_the_output_tail( monkeypatch, tmp_path ):
    """Even if a map exists, a non-zero exit means the run was cut short."""
    out = str( tmp_path / "attrib.json" )
    with open( out, "w" ) as fh: json.dump( { }, fh )
    monkeypatch.setattr( dtc.subprocess, "run", lambda *a, **k: _Done( 1, "TAIL-OUT", "TAIL-ERR" ) )
    with pytest.raises( RuntimeError, match = "exited 1" ) as caught:
        dtc._run_attributed( "t", "/root", out, [ ] )
    assert "TAIL-OUT" in str( caught.value ) and "TAIL-ERR" in str( caught.value )


def test_a_clean_exit_with_no_map_refuses( monkeypatch, tmp_path ):
    monkeypatch.setattr( dtc.subprocess, "run", lambda *a, **k: _Done( 0 ) )
    with pytest.raises( RuntimeError, match = "never written" ):
        dtc._run_attributed( "t", "/root", str( tmp_path / "missing.json" ), [ ] )


def test_a_bucket_prints_each_thread_and_file_in_sorted_order( capsys ):
    dtc._print_bucket( { "B": { "z.py": [ 2 ], "a.py": [ 1, 2 ] }, "A": { "m.py": [ 9 ] } } )
    lines = capsys.readouterr().out.splitlines()
    assert lines[ 0 ] == "  thread 'A':"
    assert lines[ 1 ].endswith( "m.py" ) and lines[ 1 ].strip().startswith( "1" )
    assert lines[ 3 ] == "  thread 'B':"
    assert lines[ 4 ].endswith( "a.py" ) and lines[ 4 ].strip().startswith( "2" )
    assert lines[ 5 ].strip() == "[1, 2]"
    assert lines[ 6 ].endswith( "z.py" )


def test_the_verdict_fails_only_on_call_time_lines():
    assert dtc.verdict_exit_code( { "call_time": { "T": { "f.py": [ 1 ] } }, "module_scope": { }, "allowed": { } } ) == 1
    assert dtc.verdict_exit_code( { "call_time": { }, "module_scope": { "T": { "f.py": [ 1 ] } },
                                    "allowed": { "T2": { "g.py": [ 1 ] } } } ) == 0


@pytest.fixture
def staged( monkeypatch ):
    """Stand in for the pytest run and the reduction; `seen` records what main handed them."""
    seen = { "buckets": { "call_time": { }, "module_scope": { }, "allowed": { } } }
    monkeypatch.setenv( "LUPIN_ROOT", "/root" )
    def fake_attributed( target, root, out_path, extra ):
        seen.update( target=target, root=root, extra=extra )
        return { "raw": "map" }
    def fake_bucket( attribution, allow, classifier ):
        seen.update( attribution=attribution, allow=allow )
        return seen[ "buckets" ]
    monkeypatch.setattr( dtc, "_run_attributed", fake_attributed )
    monkeypatch.setattr( dtc, "bucket_findings", fake_bucket )
    monkeypatch.setattr( dtc, "make_scope_classifier", lambda: None )
    return seen


def test_nothing_found_prints_none_and_exits_zero( staged, capsys ):
    assert dtc.main( [ "src/tests/unit/x" ] ) == 0
    out = capsys.readouterr().out
    assert out.startswith( "[thread-credited] none" ) and "'src/tests/unit/x'" in out
    assert staged[ "attribution" ] == { "raw": "map" } and staged[ "allow" ] == set()


def test_call_time_lines_exit_one_and_list_the_lines_unless_quiet( staged, capsys ):
    staged[ "buckets" ][ "call_time" ] = { "Worker": { "p.py": [ 4, 5 ] } }
    assert dtc.main( [ "tgt" ] ) == 1
    loud = capsys.readouterr().out
    assert "2 call-time line(s)" in loud and "thread 'Worker'" in loud and "[4, 5]" in loud
    assert dtc.main( [ "tgt", "--quiet" ] ) == 1
    quiet = capsys.readouterr().out
    assert "2 call-time line(s)" in quiet and "thread 'Worker'" not in quiet


def test_module_scope_and_allowed_lines_are_reported_but_do_not_fail( staged, capsys ):
    staged[ "buckets" ][ "module_scope" ] = { "Importer": { "m.py": [ 1 ] } }
    staged[ "buckets" ][ "allowed" ]      = { "zeta": { "a.py": [ 2 ] }, "alpha": { "b.py": [ 3 ] } }
    assert dtc.main( [ "tgt", "--allow-thread", "zeta", "--allow-thread", "alpha" ] ) == 0
    out = capsys.readouterr().out
    assert "1 further line(s) are module-scope declarations" in out and "thread 'Importer'" in out
    assert "belong to allow-listed thread(s): alpha, zeta" in out
    assert staged[ "allow" ] == { "zeta", "alpha" }
    assert dtc.main( [ "tgt", "--quiet" ] ) == 0
    assert "thread 'Importer'" not in capsys.readouterr().out


def test_extra_arguments_reach_pytest_and_json_is_written( staged, tmp_path ):
    staged[ "buckets" ][ "call_time" ] = { "W": { "p.py": [ 1 ] } }
    dest = tmp_path / "found.json"
    assert dtc.main( [ "tgt", "--json", str( dest ), "--quiet", "--", "-x" ] ) == 1
    assert staged[ "extra" ] == [ "-x" ] and staged[ "target" ] == "tgt" and staged[ "root" ] == "/root"
    assert json.loads( dest.read_text() )[ "call_time" ] == { "W": { "p.py": [ 1 ] } }


def test_a_run_that_cannot_be_attributed_exits_two_and_says_so( monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert dtc.main( [ "tgt" ] ) == 2
    assert "CANNOT ATTRIBUTE" in capsys.readouterr().err
