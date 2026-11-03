"""
The REUSE-OUTCOME line reader (plan section 12.3, the second step of track B).

The good lines are two real ones from the remediation plan and the template is the real one from the reviewer skill.
Nothing here reads a call log or runs a model.
"""
import pathlib

import pytest

import cosa.utils.util as cu
from lupin_mcp import reuse_exit_gate as eg
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
    assert got[ 0 ] == { "receipt": "0123456789abcdef", "search": "rs-0123456789", "outcome": "REUSED", "detail": "lupin_mcp.reuse_ledger.AccountLedger.close_run", "plan": PLAN, "step": "12.3-D6", "line": REUSED }
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


def test_a_half_filled_template_is_refused_and_listed_not_skipped():
    half_receipt = f"REUSE-OUTCOME <receipt id> :: rs-bc3ca2c901 :: REUSED a.b :: {PLAN}#12.3-D1"
    half_search  = f"REUSE-OUTCOME 5d37236290c7d93f :: <search id> :: REUSED a.b :: {PLAN}#12.3-D1"
    text         = f"{half_receipt}\n{half_search}\n"
    assert ro.unparsed_outcome_lines( text ) == [ half_receipt, half_search ] and ro.parse_outcomes( text ) == []


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


# The tokens `excluded` and `unindexed` (plan section 12.3, the fourth step of track B)

ROOT = pathlib.Path( cu.get_project_root() )


def call( entry, error ):
    """Ensures: a call-log record in the shape the exit gate reads."""
    return { "ts": "2026-11-02T10:00:00+00:00", "tool": "fetch_similar", "caller": "p x", "session": "x", "receipt_id": None, "error": error, "args": repr( { "entry": entry } ) }


def lines( *rows ):
    """Ensures: the parsed outcome lines of rows given as ( receipt, search, text )."""
    return ro.parse_outcomes( "\n".join( f"REUSE-OUTCOME {r} :: {s} :: WROTE_NEW {t} :: {PLAN}#12.3-B4" for r, s, t in rows ) )


EXCLUSIONS = eg.exclusions_by_symbol( [ call( "lupin_mcp.secret.helper", "EXCLUDED_SENSITIVE_CONTENT" ), call( "lupin_mcp.other", "UNKNOWN_ENTRY" ) ] )


def test_an_excluded_line_passes_only_for_a_symbol_the_log_refused():
    got = lines( ( "excluded", "rs-bc3ca2c901", "lupin_mcp.secret.helper has an address in its docstring" ),
                 ( "excluded", "rs-bc3ca2c901", "lupin_mcp.other was never refused" ),
                 ( "excluded", "rs-bc3ca2c901", "lupin_mcp.secret.helper2 is a longer name" ) )
    out = ro.token_refusals( got, EXCLUSIONS, ROOT )
    assert [ r[ "line" ] for r in out ] == [ got[ 1 ][ "line" ], got[ 2 ][ "line" ] ], "an unrelated error and a longer name do not pass; the first word is the whole key"
    assert all( "no EXCLUDED_ refusal" in r[ "reason" ] and "re-run the lookup" in r[ "reason" ] and "log folder" in r[ "reason" ] for r in out )
    assert "lupin_mcp.other" in out[ 0 ][ "reason" ]


def test_an_unindexed_line_passes_only_for_a_file_outside_the_index_roots():
    outside = [ "src/rnd/v0.2.2/x.md", "src/docs/README.md", "README.md", "src/docs/wiki/x.md", "/etc/hosts" ]
    inside  = [ "src/lupin_mcp/reuse_outcome.py", "src/cosa/CLAUDE.md", "src/lupin_app/static/css/site.css", "src/scripts/run.mjs", "src/lupin_app/static/js/notifications/x.ts", "src/tests/../lupin_mcp/x.py" ]
    got     = lines( *[ ( "unindexed", "unindexed", f"{p} is not code" ) for p in outside + inside ] )
    refused = [ r[ "line" ] for r in ro.token_refusals( got, {}, ROOT ) ]
    assert refused == [ g[ "line" ] for g in got[ len( outside ): ] ], "a file inside a root is refused, whatever its suffix, and a path that climbs back in is resolved first"
    assert "inside the index roots" in ro.token_refusals( got[ -1: ], {}, ROOT )[ 0 ][ "reason" ]


def test_the_roots_come_from_the_indexers_settings_for_the_tree_given( tmp_path ):
    for d in ( "src/cosa", "src/lupin_mcp", "src/scripts" ): ( tmp_path / d ).mkdir( parents=True )
    assert ro.outside_index_roots( "src/docs/a.md", tmp_path ) and not ro.outside_index_roots( "src/scripts/a.sh", tmp_path )
    assert ro.outside_index_roots( "src/lupin_app/x.py", tmp_path ), "this tree has no lupin_app directory, so it is no root here"
    assert ro.outside_index_roots( "src/lupin_app/x.py", ROOT ) is False, "the real tree has one"


def test_unindexed_must_stand_in_both_slots_and_a_real_receipt_keeps_its_own_meaning():
    got = lines( ( "unindexed", "rs-bc3ca2c901", "src/rnd/x.md is a note" ),
                 ( "5d37236290c7d93f", "unindexed", "src/rnd/x.md is a note" ),
                 ( "5d37236290c7d93f", "rs-bc3ca2c901", "lupin_mcp.secret.helper is new" ) )
    out = ro.token_refusals( got, EXCLUSIONS, ROOT )
    assert [ r[ "line" ] for r in out ] == [ got[ 0 ][ "line" ], got[ 1 ][ "line" ] ]
    assert "both id slots" in out[ 0 ][ "reason" ] and "needs unindexed in the receipt slot" in out[ 1 ][ "reason" ]
    assert ro.token_refusals( [], EXCLUSIONS, ROOT ) == []
