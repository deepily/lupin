"""
The junit reader of the docker smoke step.

A skip, an error, a failure and a file with no test in the report each count as a failed test. A report
that cannot be read refuses, and the refusal prints no counts, so the job reads the run as not executed.

Venue: :7999-eligible. No server, no docker, no state outside tmp_path.
"""

import pytest

from cosa.repo import docker_smoke_report as report

MODULES = ( "test_credential_mount_shape", "test_db_roles_rollback_real_postgres", "test_db_grants_real_postgres" )


def _case( module, name, outcome=None, message="" ):
    """One testcase element; outcome is None, skipped, failure or error."""
    inner = f'<{outcome} message="{message}"/>' if outcome else ""
    return f'<testcase classname="src.tests.smoke.{module}" name="{name}">{inner}</testcase>'


def _junit( tmp_path, cases ):
    path = tmp_path / "junit.xml"
    path.write_text( f'<?xml version="1.0"?><testsuites><testsuite>{"".join( cases )}</testsuite></testsuites>', encoding="utf-8" )
    return str( path )


def _all_pass():
    return [ _case( m, f"test_{i}" ) for i, m in enumerate( MODULES ) ]


def test_an_all_green_report_counts_every_case_as_passed( tmp_path ):
    summary = report.summarize( _junit( tmp_path, _all_pass() ) )
    assert ( summary[ "total" ], summary[ "passed" ], summary[ "failed" ], summary[ "skipped" ] ) == ( 3, 3, 0, 0 )
    assert summary[ "missing" ] == [] and summary[ "skips" ] == []


def test_a_skip_is_counted_as_a_failure_and_names_its_reason( tmp_path ):
    cases   = _all_pass() + [ _case( MODULES[ 2 ], "test_x", "skipped", "docker is not available" ) ]
    summary = report.summarize( _junit( tmp_path, cases ) )
    assert ( summary[ "total" ], summary[ "passed" ], summary[ "failed" ], summary[ "skipped" ] ) == ( 4, 3, 1, 1 )
    assert summary[ "skips" ] == [ f"src.tests.smoke.{MODULES[ 2 ]}::test_x: docker is not available" ]


@pytest.mark.parametrize( "outcome", [ "failure", "error" ] )
def test_a_failure_and_an_error_each_count_as_one_failed_test( tmp_path, outcome ):
    summary = report.summarize( _junit( tmp_path, _all_pass() + [ _case( MODULES[ 0 ], "test_y", outcome, "boom" ) ] ) )
    assert ( summary[ "passed" ], summary[ "failed" ], summary[ "skipped" ] ) == ( 3, 1, 0 )


def test_a_file_with_no_case_in_the_report_counts_as_one_failed_and_is_named( tmp_path ):
    summary = report.summarize( _junit( tmp_path, _all_pass()[ :2 ] ) )
    assert summary[ "missing" ] == [ MODULES[ 2 ] ]
    assert ( summary[ "total" ], summary[ "passed" ], summary[ "failed" ] ) == ( 2, 2, 1 )


def test_an_empty_report_misses_every_expected_file( tmp_path ):
    summary = report.summarize( _junit( tmp_path, [] ) )
    assert summary[ "missing" ] == list( MODULES ) and summary[ "failed" ] == 3 and summary[ "passed" ] == 0


def test_a_class_based_case_still_counts_for_its_module( tmp_path ):
    case = f'<testcase classname="src.tests.smoke.{MODULES[ 0 ]}.TestMount" name="test_z"/>'
    summary = report.summarize( _junit( tmp_path, [ case ] + _all_pass()[ 1: ] ) )
    assert summary[ "missing" ] == []


def test_the_expected_files_can_be_named_by_the_caller( tmp_path ):
    summary = report.summarize( _junit( tmp_path, [ _case( "test_only_one", "test_a" ) ] ), expected=( "test_only_one", ) )
    assert summary[ "missing" ] == [] and summary[ "failed" ] == 0


def test_render_prints_each_skip_and_each_missing_file_above_the_four_count_lines( tmp_path ):
    cases = [ _case( MODULES[ 0 ], "test_a" ), _case( MODULES[ 1 ], "test_b", "skipped", "no docker" ) ]
    text  = report.render( report.summarize( _junit( tmp_path, cases ) ) )
    lines = text.splitlines()
    assert lines[ 0 ] == f"SKIPPED src.tests.smoke.{MODULES[ 1 ]}::test_b: no docker"
    assert lines[ 1 ] == f"MISSING {MODULES[ 2 ]}: no test of this file is in the report"
    assert lines[ 2: ] == [ "Total Tests: 2", "Passed: 1", "Failed: 2", "Skipped: 1" ]


def test_main_exits_zero_on_a_clean_report_and_prints_the_counts( tmp_path, capsys ):
    assert report.main( [ "prog", _junit( tmp_path, _all_pass() ) ] ) == 0
    assert "Total Tests: 3\nPassed: 3\nFailed: 0\nSkipped: 0" in capsys.readouterr().out


def test_main_exits_one_when_anything_failed_was_skipped_or_is_missing( tmp_path, capsys ):
    assert report.main( [ "prog", _junit( tmp_path, _all_pass()[ :2 ] ) ] ) == 1
    assert "Failed: 1" in capsys.readouterr().out


@pytest.mark.parametrize( "argv", [ [ "prog" ], [ "prog", "/nonexistent/junit.xml" ] ] )
def test_main_refuses_with_exit_two_and_no_counts_when_there_is_no_report( argv, capsys ):
    assert report.main( argv ) == 2
    out = capsys.readouterr().out
    assert out.startswith( "REFUSING: the junit report could not be read" ) and "Total Tests" not in out


def test_main_refuses_when_the_report_is_not_xml( tmp_path, capsys ):
    bad = tmp_path / "bad.xml"
    bad.write_text( "this is not xml" )
    assert report.main( [ "prog", str( bad ) ] ) == 2
    assert "Total Tests" not in capsys.readouterr().out
