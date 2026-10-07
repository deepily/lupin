"""
The claim judge is sent a pair whose new text is empty; nothing skips it.

Store id e19f2d9d-73af-4c5e-8628-76bfb7ef86ae. dart_pairs now writes a pair with an empty new text when a
member's doc block was removed and no comment was left. This pins what the harness does with such a
pair. A later change that skips it, or alters its verdict, must change this test.

Seams driven for real: harness_runner.run_all and run_pair over the fake model of test_doc_lint_harness,
which answers from the text it is handed. No live call.
"""

import asyncio

from cosa.repo.doc_lint import harness_runner as hn

from tests.unit.test_doc_lint_harness import CONFIG, FakeModel, L1, L2, L3, OLD, pair


def _run( pairs, tmp_path, model ):
    return asyncio.run( hn.run_all( pairs, CONFIG, hn.Ledger( str( tmp_path / "l" ) ), query_fn=model ) )


def test_a_pair_with_an_empty_new_text_is_judged_and_every_claim_is_absent( tmp_path ):
    model  = FakeModel()
    result = _run( [ pair( "p", "" ) ], tmp_path, model )[ 0 ]
    assert [ k for k, _ in model.calls ].count( "judge" ) == 6
    assert [ [ r[ "verdict" ] for r in run ] for run in result[ "lists" ][ 0 ][ "runs" ] ] == [ [ "absent" ] * 3 ] * 3
    assert [ c[ "text" ] for c in result[ "lists" ][ 0 ][ "claims" ] ] == [ L1, L2, L3 ]


def test_the_same_old_text_with_a_kept_new_text_is_judged_present( tmp_path ):
    result = _run( [ pair( "p", OLD ) ], tmp_path, FakeModel() )[ 0 ]
    assert {r[ "verdict" ] for run in result[ "lists" ][ 0 ][ "runs" ] for r in run} == { "present" }
