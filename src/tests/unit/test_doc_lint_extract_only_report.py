"""
An extractor-only run (--judge-runs 0) writes its report and exits 0.

With no judge run a claim list holds claims and no verdict rows. The verdict readers indexed
`runs[ 0 ]`, so the report step died with an IndexError once every extractor row was in the ledger.
The report now says the judge did not run. Misses, false alarms and claims lost are None, never
zero and never every seeded pair, and the claim count is printed.
"""

import asyncio
import json

from cosa.repo.doc_lint import harness_cli, harness_report as hr, harness_runner as hn

from test_doc_lint_harness import CONFIG, FakeModel, L1, L2, L3, OLD, pair
from test_doc_lint_jev import cli_args, cli_claude_query

NO_JUDGE = hn.HarnessConfig( "ext-m", "judge-m", "esc-m", "writer-m", 2, 0 )


def _lists( tmp_path ):
    results = asyncio.run( hn.run_all( [ pair( "seeded", OLD, seeded=L1 ), pair( "plain", OLD ) ], NO_JUDGE, hn.Ledger( str( tmp_path / "l" ) ), query_fn=FakeModel() ) )
    return results


def test_the_verdict_readers_answer_nothing_for_a_list_with_no_judge_runs():
    assert hr.final_absent( [] ) == [] and hr.unanimous( [] ) == []


def test_a_claim_list_without_judge_runs_is_not_caught_flagged_or_dropped( tmp_path ):
    lst = _lists( tmp_path )[ 0 ][ "lists" ][ 0 ]
    assert lst[ "claims" ] and lst[ "runs" ] == []
    assert hr.caught( lst, tuple( _lists( tmp_path )[ 0 ][ "seed_span" ] ) ) is False
    assert hr.flagged( lst ) is False and hr.drop_tags( lst ) == ( [], [] )


def test_the_report_of_an_extractor_only_run_says_the_judge_did_not_run( tmp_path ):
    report = hr.build_report( _lists( tmp_path ), NO_JUDGE )
    for l in report[ "lists" ]:
        assert l[ "claims" ] == 6 and l[ "misses" ] is None and l[ "false_alarms" ] is None and l[ "claims_lost" ] is None
    assert report[ "default_gate_pass" ] is False and report[ "judge_ran" ] is False


def test_a_report_with_judge_runs_says_the_judge_ran_and_counts_its_claims( tmp_path ):
    results = asyncio.run( hn.run_all( [ pair( "seeded", OLD, seeded=L1 ) ], CONFIG, hn.Ledger( str( tmp_path / "l" ) ), query_fn=FakeModel() ) )
    report  = hr.build_report( results, CONFIG )
    assert report[ "judge_ran" ] is True and report[ "lists" ][ 0 ][ "claims" ] == 3 and report[ "lists" ][ 0 ][ "misses" ] == 1


def test_the_cli_exits_zero_on_an_extractor_only_run_and_prints_the_claim_count( tmp_path, capsys ):
    code = harness_cli.main( cli_args( tmp_path, "--judge-runs", "0" ), query_fn=cli_claude_query() )
    out  = capsys.readouterr().out
    report = json.loads( ( tmp_path / "r.json" ).read_text() )
    assert code == 0 and report[ "judge_ran" ] is False
    assert f"claims={report[ 'lists' ][ 0 ][ 'claims' ]}" in out and "judge not run" in out
