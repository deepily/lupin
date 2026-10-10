"""
A second end-to-end measurement beside the first, with its own prefix and estimate.

The page-route measurement asks the same needs as the old question, so it needs run names and result files
of its own. Everything here runs on the stand-in transport, so no test makes a live call.
"""
import json

import pytest

from lupin_mcp import reuse_e2e_run as run
from tests.unit.test_reuse_e2e_cli import setup  # noqa: F401  (setup is a fixture)

CEILING = [ "--ceiling", "100000000" ]


def prefixed( setup, name, extra=() ): return setup.args( name, *CEILING, extra=list( extra ) ) if name in ( "canary", "run" ) else setup.args( name, extra=list( extra ) )


def results( setup ): return setup.data / "e2e-results"


def read( setup, name ): return json.loads( ( results( setup ) / name ).read_text( encoding="utf-8" ) )


def test_a_second_measurement_under_another_prefix_opens_its_own_run_and_files( setup, capsys ):
    assert run.cli( prefixed( setup, "canary" ) ) == 0
    assert run.cli( prefixed( setup, "canary" ) ) == 2                                          # the control: the same prefix is a run name used before
    capsys.readouterr()
    assert run.cli( prefixed( setup, "canary", [ "--prefix", "pg", "--questions", "pages" ] ) ) == 0
    assert sorted( p.name for p in results( setup ).iterdir() ) == [ "e2e-canary.canary.json", "e2e-canary.json", "pg-canary.canary.json", "pg-canary.json" ]
    assert read( setup, "pg-canary.json" )[ "run_name" ] == "pg-canary" and read( setup, "pg-canary.json" )[ "questions" ] == [ "pages" ]


def test_approving_and_running_under_a_prefix_touches_only_that_prefixs_files( setup, capsys ):
    pg = [ "--prefix", "pg", "--questions", "pages" ]
    assert run.cli( prefixed( setup, "canary" ) ) == 0
    assert run.cli( prefixed( setup, "canary", pg ) ) == 0
    assert run.cli( prefixed( setup, "run", pg ) ) == 2                                          # pg's canary is not approved yet
    assert run.cli( setup.args( "approve", "--by", "cheech", "--why", "read it", extra=pg ) ) == 0
    assert read( setup, "pg-canary.canary.json" )[ "approved" ][ "by" ] == "cheech" and read( setup, "e2e-canary.canary.json" )[ "approved" ] is None
    assert run.cli( prefixed( setup, "run", pg ) ) == 0
    out = read( setup, "pg-run.json" )
    assert ( out[ "run_name" ], out[ "state" ], out[ "canary_run" ], len( out[ "members" ] ) ) == ( "pg-run", "complete", "pg-canary", 95 )
    assert not ( results( setup ) / "e2e-run.json" ).exists()


def test_the_estimate_option_sets_the_allowance_and_the_default_is_unchanged( setup ):
    assert run.cli( prefixed( setup, "canary", [ "--prefix", "pg", "--questions", "pages", "--estimate-tokens", "1000000" ] ) ) == 0
    assert read( setup, "pg-canary.canary.json" )[ "allowance_tokens" ] == 1_500_000
    assert run.cli( prefixed( setup, "canary" ) ) == 0
    assert read( setup, "e2e-canary.canary.json" )[ "allowance_tokens" ] == 630_000_000          # 1.5 times the 420,000,000 default


def test_one_prefix_only_for_a_step_that_spends_and_a_clean_name_for_every_prefix( setup, capsys ):
    for step in ( "canary", "run" ):
        assert run.cli( prefixed( setup, step, [ "--prefix", "e2e,pg" ] ) ) == 2 and "one prefix" in capsys.readouterr().err
    assert run.cli( setup.args( "approve", "--by", "x", "--why", "y", extra=[ "--prefix", "e2e,pg" ] ) ) == 2 and "one prefix" in capsys.readouterr().err
    for bad in ( "", "Bad", "../x", "a b", "s2", "x" * 17, "1pg", "-pg" ):
        assert run.cli( prefixed( setup, "canary", [ f"--prefix={bad}" ] ) ) == 2 and "prefix" in capsys.readouterr().err
    assert not results( setup ).exists()                                                           # every refusal came before a run was opened


def test_an_estimate_that_is_not_a_positive_number_is_refused_before_a_run_is_opened( setup, capsys ):
    for bad in ( "0", "-5" ):
        assert run.cli( prefixed( setup, "canary", [ "--estimate-tokens", bad ] ) ) == 2 and "estimate" in capsys.readouterr().err
    assert not results( setup ).exists()


def test_the_report_reads_every_prefix_and_pairs_the_two_questions( setup, capsys ):
    both = [ "--questions", "old,pages", "--prefix", "e2e,pg" ]
    assert run.cli( prefixed( setup, "canary" ) ) == 0
    assert run.cli( prefixed( setup, "canary", [ "--prefix", "pg", "--questions", "pages" ] ) ) == 0
    capsys.readouterr()
    assert run.cli( setup.args( "report", extra=both ) ) == 0
    out = capsys.readouterr().out
    assert "old: n run: 5 of 100" in out and "pages: n run: 5 of 100" in out and "paired on_shortlist" in out


def test_the_report_of_a_prefix_with_no_result_file_is_refused_and_names_it( setup, capsys ):
    """Once pinned as "none ran, no failure"; that hid a misspelt prefix."""
    assert run.cli( prefixed( setup, "canary" ) ) == 0
    capsys.readouterr()
    assert run.cli( setup.args( "report", extra=[ "--questions", "old,pages", "--prefix", "e2e,pgg" ] ) ) == 2
    err = capsys.readouterr().err
    assert "pgg" in err and "no result file" in err


def test_the_report_of_a_prefix_with_only_its_canary_still_reads_it( setup, capsys ):
    assert run.cli( prefixed( setup, "canary", [ "--prefix", "pg", "--questions", "pages" ] ) ) == 0
    capsys.readouterr()
    assert run.cli( setup.args( "report", extra=[ "--questions", "pages", "--prefix", "pg" ] ) ) == 0
    assert "pages: n run: 5 of 100" in capsys.readouterr().out


def test_an_estimate_above_the_room_left_is_refused_before_the_first_send( setup, capsys ):
    room = 952_380_952
    assert run.cli( prefixed( setup, "canary", [ "--estimate-tokens", str( room + 1 ) ] ) ) == 2
    err = capsys.readouterr().err
    assert str( room + 1 ) in err and str( room ) in err and "room" in err
    assert not results( setup ).exists()                                                           # nothing was opened or sent
    assert run.cli( prefixed( setup, "canary", [ "--estimate-tokens", str( room ) ] ) ) == 0         # the boundary: an estimate equal to the room is allowed


def test_the_default_report_still_reads_the_first_measurement_only( setup, capsys ):
    assert run.cli( prefixed( setup, "canary" ) ) == 0
    capsys.readouterr()
    assert run.cli( setup.args( "report" ) ) == 0
    assert "old: n run: 5 of 100" in capsys.readouterr().out
