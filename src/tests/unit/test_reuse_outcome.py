"""
The REUSE-OUTCOME line reader (plan section 12.3, the second step of track B).

The good lines are two real ones from the remediation plan and the template is the real one from the reviewer skill.
Nothing here reads a call log or runs a model.
"""
import pathlib

import pytest

import cosa.utils.util as cu
from lupin_mcp import reuse_outcome as ro

PLAN    = "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.24-reuse-detection-remediation-plan.md"
EXTENDS = f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: EXTENDED lupin_mcp.reuse_shadow.sweep_of :: {PLAN}#12.3-D1"
WROTE   = ( "REUSE-OUTCOME 6a32406077b69d7c :: rs-610460fb20 :: WROTE_NEW the line parser and its unparsed-line finder are new (nothing reads REUSE-OUTCOME); "
            f"the receipt and search readers are extended with a receipt-keyed reader, since receipts_by_symbol and searches_by_symbol see only fetch_similar :: {PLAN}#12.3-B2" )
REUSED  = f"REUSE-OUTCOME 0123456789abcdef :: rs-0123456789 :: REUSED lupin_mcp.reuse_ledger.AccountLedger.close_run :: {PLAN}#12.3-D6"
SKILL   = pathlib.Path( cu.get_project_root() ) / ".claude/skills/reuse-reviewer/SKILL.md"


def test_each_of_the_three_outcomes_is_read_with_every_part():
    got = ro.parse_outcomes( "\n".join( [ REUSED, EXTENDS, WROTE ] ) )
    assert [ g[ "outcome" ] for g in got ] == [ "REUSED", "EXTENDED", "WROTE_NEW" ]
    assert got[ 0 ] == { "receipt": "0123456789abcdef", "search": "rs-0123456789", "outcome": "REUSED", "detail": "lupin_mcp.reuse_ledger.AccountLedger.close_run", "plan": PLAN, "step": "12.3-D6" }
    assert got[ 1 ][ "receipt" ] == "5d37236290c7d93f" and got[ 1 ][ "detail" ] == "lupin_mcp.reuse_shadow.sweep_of" and got[ 1 ][ "step" ] == "12.3-D1"
    assert got[ 2 ][ "detail" ].startswith( "the line parser" ) and " :: " not in got[ 2 ][ "detail" ] and got[ 2 ][ "step" ] == "12.3-B2"
    assert ro.unparsed_outcome_lines( "\n".join( [ REUSED, EXTENDS, WROTE ] ) ) == []


@pytest.mark.parametrize( "line", [
    f"REUSE-OUTCOME 5d37236290c7d9 :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3-D1",                  # receipt too short
    f"REUSE-OUTCOME 5D37236290C7D93F :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3-D1",                # receipt not lower-case hex
    f"REUSE-OUTCOME 5d37236290c7d93f :: bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3-D1",                   # search id without its prefix
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c90 :: REUSED a.b :: {PLAN}#12.3-D1",                 # search id too short
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: DUPLICATE a.b :: {PLAN}#12.3-D1",             # ruling word, not an outcome
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED :: {PLAN}#12.3-D1",                    # no symbol
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b c.d :: {PLAN}#12.3-D1",            # two symbol tokens
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: EXTENDED a.b because it is close :: {PLAN}#12.3-D1",   # free text after the symbol
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: WROTE_NEW :: {PLAN}#12.3-D1",                 # no difference
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: WROTE_NEW it differs :: in a way :: {PLAN}#12.3-D1",   # a separator inside the difference
    "REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b",                                   # no location
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}",                        # no step
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#diffs",                  # near the plan-less step, not it
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#Diff",                   # the plan-less step is lower case
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#fix",                    # a step that is neither form
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3D1",                 # no dash
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3-D1 and more",       # text after the step
    f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a.b :: two words#12.3-D1",             # a space in the plan path
    f"REUSE-OUTCOME <receipt id>x :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3-D1",                   # nearly the template, not the template
    f"REUSE-OUTCOME excluded :: excluded :: REUSED a.b :: {PLAN}#12.3-D1",                             # the search slot takes unindexed, not excluded
] )
def test_each_malformed_line_is_named_and_not_read( line ):
    text = f"intro\n{line}\nafter\n"
    assert ro.unparsed_outcome_lines( text ) == [ line ]
    assert ro.parse_outcomes( text ) == []


def test_the_excluded_and_unindexed_tokens_are_read_as_shape_only():
    text = f"REUSE-OUTCOME excluded :: rs-bc3ca2c901 :: WROTE_NEW refused by the tool :: {PLAN}#12.3-B2\nREUSE-OUTCOME unindexed :: unindexed :: WROTE_NEW src/scripts/x.mjs has no twin :: {PLAN}#12.3-B2"
    assert [ g[ "receipt" ] for g in ro.parse_outcomes( text ) ] == [ "excluded", "unindexed" ]
    assert ro.unparsed_outcome_lines( text ) == []


def test_a_template_line_is_skipped_and_a_real_line_beside_it_is_checked():
    template = "REUSE-OUTCOME <receipt id> :: <search id> :: REUSED <symbol> | EXTENDED <symbol> | WROTE_NEW <difference> :: <plan path>#<step>"
    bad      = f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: REUSED a b :: {PLAN}#12.3-D1"
    text     = f"```text\n{template}\n```\n\n```text\n{EXTENDS}\n{bad}\n```\n  {template}\n"
    assert [ g[ "detail" ] for g in ro.parse_outcomes( text ) ] == [ "lupin_mcp.reuse_shadow.sweep_of" ], "fenced and indented lines are read"
    assert ro.unparsed_outcome_lines( text ) == [ bad ], "only the template is skipped"


def test_prose_that_mentions_the_keyword_is_not_a_line():
    text = "Write a REUSE-OUTCOME line for each lookup.\nSee `REUSE-OUTCOME` in the skill.\nREUSE-OUTCOMES are checked later.\n- REUSE-OUTCOME in a list item\n"
    assert ro.parse_outcomes( text ) == [] and ro.unparsed_outcome_lines( text ) == []


def test_the_reviewer_skill_as_written_has_a_template_and_no_refused_line():
    text = SKILL.read_text( encoding="utf-8" )
    assert "REUSE-OUTCOME <receipt id>" in text, "the skill still carries the template this test reads"
    assert ro.parse_outcomes( text ) == [] and ro.unparsed_outcome_lines( text ) == []


def test_a_diff_with_no_plan_cites_its_task_row_and_diff():
    row  = "6e6f9c90-0fd1-47bd-b222-724665b3093b"
    line = f"REUSE-OUTCOME 5d37236290c7d93f :: rs-bc3ca2c901 :: WROTE_NEW the helper is new :: {row}#diff"
    got  = ro.parse_outcomes( line )
    assert [ ( g[ "plan" ], g[ "step" ], g[ "outcome" ] ) for g in got ] == [ ( row, "diff", "WROTE_NEW" ) ] and ro.unparsed_outcome_lines( line ) == []
    assert ro.parse_outcomes( f"{line}\n{EXTENDS}" )[ 1 ][ "step" ] == "12.3-D1", "the plan form still reads beside it"
