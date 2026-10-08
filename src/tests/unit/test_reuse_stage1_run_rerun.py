"""
The runner reruns an arm its ceiling stopped, with the flags --attempt and --reason.

Every transport here is a stand-in, as in the runner's own tests, and no real ledger or cache is touched.
"""
import pytest

from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from tests.unit.test_reuse_stage1_run import loader, read, run, scratch      # noqa: F401  the fixture and the helpers

ARM = [ "arm", "--question", "1", "--arm", "single1" ]


def stop_single1( scratch ):
    """Ensures: runs single1 under a ceiling too low for it, so the ceiling stops it."""
    run( scratch, "ledger-init" )
    assert run( scratch, *ARM, "--ceiling", "1000" ) == 0
    assert read( scratch, "s1-q1-single1" )[ "stop_reason" ] == "ceiling"


def test_a_stopped_arm_is_run_again_with_attempt_and_reason( scratch, capsys ):
    stop_single1( scratch )
    capsys.readouterr()
    assert run( scratch, *ARM, "--ceiling", "5000000", "--attempt", "2", "--reason", "the ceiling was too low" ) == 0
    again = read( scratch, "s1-q1-single1-a2" )
    assert again[ "state" ] == "complete" and again[ "attempt" ] == 2 and again[ "retry_reason" ] == "the ceiling was too low" and again[ "ceiling_tokens" ] == 5_000_000
    assert "s1-q1-single1-a2: state complete" in capsys.readouterr().out
    assert read( scratch, "s1-q1-single1" )[ "stop_reason" ] == "ceiling"


def test_the_first_attempt_is_still_the_default_and_needs_no_reason( scratch ):
    run( scratch, "ledger-init" )
    assert run( scratch, *ARM, "--ceiling", "5000000" ) == 0
    assert read( scratch, "s1-q1-single1" )[ "attempt" ] == 1 and read( scratch, "s1-q1-single1" )[ "retry_reason" ] is None


def test_a_rerun_without_a_reason_and_a_reason_without_a_rerun_are_refused( scratch ):
    stop_single1( scratch )
    with pytest.raises( s1.DriverRefused, match="reason" ): run( scratch, *ARM, "--ceiling", "5000000", "--attempt", "2" )
    with pytest.raises( s1.DriverRefused, match="first attempt has no reason" ): run( scratch, *ARM, "--ceiling", "5000000", "--reason", "why" )
    assert not ( scratch.data / "stage1-results" / "s1-q1-single1-a2.json" ).exists()


def test_an_arm_that_completed_is_refused_a_rerun_through_the_command_line( scratch, capsys ):
    run( scratch, "ledger-init" )
    run( scratch, *ARM, "--ceiling", "5000000" )
    argv = [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.ledger ), *ARM, "--ceiling", "5000000", "--attempt", "2", "--reason", "again" ]
    capsys.readouterr()
    assert rr.cli( argv, loader=loader ) == 2
    assert "already completed as attempt 1" in capsys.readouterr().err and not ( scratch.data / "stage1-results" / "s1-q1-single1-a2.json" ).exists()


def test_an_attempt_that_is_not_a_whole_number_is_refused_by_the_parser( scratch ):
    run( scratch, "ledger-init" )
    with pytest.raises( SystemExit ): run( scratch, *ARM, "--ceiling", "5000000", "--attempt", "two", "--reason", "x" )
