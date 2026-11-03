"""
Unit tests for the review verdict gate, on stand-ins for git and the census run.

The line carries the tree sha and a census count; a verdict without them is refused.
The census log text is shaped like the real runner's output.
"""
import pytest

from cosa.utils import review_verdict as rv

SHA  = "4832d5a1d0123456789abcdef0123456789abcde"
GOOD = f"[tree-state] sha={SHA[ :9 ]} root=/x branch=detached\n.....\n43 passed, 2 deselected in 12.30s\n"


def test_the_census_counts_come_from_the_pytest_summary_line():
    assert rv.parse_census( GOOD ) == { "sha": SHA[ :9 ], "passed": 43, "failed": 0, "errors": 0 }
    text = f"[tree-state] sha=abc1234 root=/x\n3 failed, 40 passed, 1 error in 9s\n"
    assert rv.parse_census( text ) == { "sha": "abc1234", "passed": 40, "failed": 3, "errors": 1 }
    assert rv.parse_census( "[tree-state] sha=abc1234 x\n2 errors in 1s\n" )[ "errors" ] == 2


def test_a_census_log_without_a_summary_or_a_tree_line_is_refused():
    with pytest.raises( ValueError, match = "no pytest summary" ): rv.parse_census( "[tree-state] sha=abc1234 x\n" )
    with pytest.raises( ValueError, match = "no tree-state" ): rv.parse_census( "43 passed in 1s\n" )


def test_the_verdict_line_holds_the_tree_sha_the_counts_and_the_verdict():
    line = rv.verdict_line( SHA, rv.parse_census( GOOD ), "Merge" )
    assert line == f"REVIEW-VERDICT sha={SHA[ :12 ]} census=43p/0f/0e verdict=Merge"


def test_a_census_run_on_another_tree_is_refused():
    other = GOOD.replace( SHA[ :9 ], "deadbeef0" )
    with pytest.raises( ValueError, match = "census ran on deadbeef0" ): rv.verdict_line( SHA, rv.parse_census( other ), "Merge" )


def test_merge_needs_a_clean_census_and_fix_may_carry_failures():
    red = rv.parse_census( f"[tree-state] sha={SHA[ :9 ]} x\n2 failed, 5 passed in 1s\n" )
    with pytest.raises( ValueError, match = "Merge with 2 failed" ): rv.verdict_line( SHA, red, "Merge" )
    assert rv.verdict_line( SHA, red, "Fix" ).endswith( "census=5p/2f/0e verdict=Fix" )
    with pytest.raises( ValueError, match = "verdict must be" ): rv.verdict_line( SHA, rv.parse_census( GOOD ), "Maybe" )


def test_a_verdict_with_no_census_count_is_refused_by_the_check():
    ok = rv.verdict_line( SHA, rv.parse_census( GOOD ), "Merge" )
    assert rv.check_line( ok, SHA ) == { "sha": SHA[ :12 ], "passed": 43, "failed": 0, "errors": 0, "verdict": "Merge" }
    for bad in ( f"REVIEW-VERDICT sha={SHA[ :12 ]} verdict=Merge", "looks good, merge it", "" ):
        with pytest.raises( ValueError, match = "no census" ): rv.check_line( bad, SHA )


def test_the_check_refuses_a_verdict_for_another_tree():
    ok = rv.verdict_line( SHA, rv.parse_census( GOOD ), "Merge" )
    with pytest.raises( ValueError, match = "verdict is for" ): rv.check_line( ok, "ffffffffffff0000" )


def test_the_check_refuses_a_merge_that_carries_failures():
    forged = f"REVIEW-VERDICT sha={SHA[ :12 ]} census=5p/2f/0e verdict=Merge"
    with pytest.raises( ValueError, match = "Merge with 2 failed" ): rv.check_line( forged, SHA )
    errored = f"REVIEW-VERDICT sha={SHA[ :12 ]} census=5p/0f/1e verdict=Merge"
    with pytest.raises( ValueError, match = "Merge with 0 failed and 1 errors" ): rv.check_line( errored, SHA )


def test_only_a_pytest_shaped_summary_line_counts_and_a_stray_in_seconds_line_cannot_zero_a_red_census():
    red = f"[tree-state] sha=abc1234 x\n2 failed, 5 passed in 1s\nwaiting in 5s\n"
    assert rv.parse_census( red ) == { "sha": "abc1234", "passed": 5, "failed": 2, "errors": 0 }
    banner = "[tree-state] sha=abc1234 x\n=== 1578 passed, 11 skipped, 52 warnings in 157.13s (0:02:37) ===\n"
    assert rv.parse_census( banner )[ "passed" ] == 1578
    with pytest.raises( ValueError, match = "no pytest summary" ): rv.parse_census( "[tree-state] sha=abc1234 x\nno tests ran in 0.01s\nretry in 5s\n" )


def test_with_two_summary_lines_the_last_pytest_one_counts():
    text = "[tree-state] sha=abc1234 x\n2 failed in 1.0s\n5 passed in 1.0s\n"
    got  = rv.parse_census( text )
    assert ( got[ "passed" ], got[ "failed" ] ) == ( 5, 0 )


def test_merge_needs_at_least_one_passed_test_in_the_census():
    empty = rv.parse_census( f"[tree-state] sha={SHA[ :9 ]} x\n3 skipped in 1s\n" )
    assert empty[ "passed" ] == 0
    with pytest.raises( ValueError, match = "Merge with no passed tests" ): rv.verdict_line( SHA, empty, "Merge" )
    assert rv.verdict_line( SHA, empty, "Fix" ).endswith( "census=0p/0f/0e verdict=Fix" )
    with pytest.raises( ValueError, match = "Merge with no passed tests" ): rv.check_line( f"REVIEW-VERDICT sha={SHA[ :12 ]} census=0p/0f/0e verdict=Merge", SHA )


def test_the_check_wants_a_full_twelve_character_hex_sha():
    for short in ( SHA[ :7 ], SHA[ :11 ], SHA[ :13 ], "4832d5a1d01g" ):
        with pytest.raises( ValueError, match = "no census" ): rv.check_line( f"REVIEW-VERDICT sha={short} census=43p/0f/0e verdict=Merge", SHA )


def run_with( out, dirty="", head=SHA, census=GOOD, census_rc=0 ):
    """Return a runner stand-in answering git rev-parse, git status and the census script."""
    def run( cmd ):
        if cmd[ :2 ] == [ "git", "rev-parse" ]: return ( 0, head + "\n" )
        if cmd[ :2 ] == [ "git", "status" ]: return ( 0, dirty )
        return ( census_rc, census )
    return run


def test_main_runs_the_census_and_prints_one_verdict_line():
    out = [ ]
    assert rv.main( [ "--verdict", "Merge" ], run=run_with( out ), out=out.append ) == 0
    assert out == [ f"REVIEW-VERDICT sha={SHA[ :12 ]} census=43p/0f/0e verdict=Merge" ]


def test_main_reads_a_census_log_instead_of_running_one( tmp_path ):
    log = tmp_path / "census.log"
    log.write_text( GOOD )
    out = [ ]
    assert rv.main( [ "--verdict", "Merge", "--census-log", str( log ) ], run=run_with( out, census="NOT RUN" ), out=out.append ) == 0
    assert out[ 0 ].endswith( "census=43p/0f/0e verdict=Merge" )


def test_main_refuses_a_dirty_tree_a_failed_census_and_a_verdict_it_cannot_build():
    out = [ ]
    assert rv.main( [ "--verdict", "Merge" ], run=run_with( out, dirty=" M src/a.py\n" ), out=out.append ) == 2
    assert "tracked changes" in out[ -1 ]
    assert rv.main( [ "--verdict", "Merge" ], run=run_with( out, census="no summary here" ), out=out.append ) == 2
    assert "no tree-state" in out[ -1 ]
    assert rv.main( [ "--verdict", "Merge" ], run=run_with( out, census=GOOD.replace( "43 passed", "1 failed, 4 passed" ) ), out=out.append ) == 2
    assert "Merge with 1 failed" in out[ -1 ]


def test_main_check_accepts_a_line_for_this_tree_and_refuses_the_rest():
    out = [ ]
    ok = rv.verdict_line( SHA, rv.parse_census( GOOD ), "Fix" )
    assert rv.main( [ "--check", ok ], run=run_with( out ), out=out.append ) == 0
    assert out[ -1 ] == ok
    assert rv.main( [ "--check", "merge it" ], run=run_with( out ), out=out.append ) == 2
    assert "no census" in out[ -1 ]


def test_the_default_runner_is_the_harness_run_command_in_the_repo_root_with_the_census_timeout( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", "/the/root" )
    calls = [ ]
    def fake( argv, env=None, cwd=None, timeout=None ):
        calls.append( ( argv, cwd, timeout ) )
        return ( 0, SHA + "\n" ) if argv[ :2 ] == [ "git", "rev-parse" ] else ( 0, "" if argv[ 0 ] == "git" else GOOD )
    monkeypatch.setattr( rv, "run_command", fake )
    out = [ ]
    assert rv.main( [ "--verdict", "Fix" ], out=out.append ) == 0
    assert [ c[ 1: ] for c in calls ] == [ ( "/the/root", rv.CENSUS_SECONDS ) ] * 3 and calls[ 2 ][ 0 ] == [ "bash", "src/tests/run-census-guards.sh" ]


def test_the_wrapper_script_hands_its_arguments_to_the_module():
    import pathlib
    text = ( pathlib.Path( __file__ ).resolve().parents[ 2 ] / "scripts" / "review-verdict.sh" ).read_text()
    assert "python3 -m cosa.utils.review_verdict \"$@\"" in text and "LUPIN_ROOT" in text
