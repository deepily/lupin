"""
The REUSE-OUTCOME line reader (plan section 12.3, the second step of track B).

The good lines are two real ones from the remediation plan and the template is the real one from the reviewer skill.
Nothing here reads a call log or runs a model.
"""
import json
import pathlib
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.symindex import spec as sp
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


def test_an_unindexed_line_passes_only_for_a_file_the_symbol_index_does_not_hold():
    unheld = [ "src/rnd/v0.2.2/x.md", "src/docs/README.md", "README.md", "src/docs/wiki/x.md", "/etc/hosts",
               "src/cosa/CLAUDE.md", "src/lupin_app/static/css/site.css", "src/scripts/bounce-dev-server.sh", "src/lupin_app/static/html/index.html", "src/conf/lupin-app.ini",   # inside a root, wrong suffix for it (the last four are Chloe's cases)
               "src/cosa/tests/test_x.py", "src/cosa/tests/__init__.py", "src/lupin_mcp/.venv/x.py", "src/scripts/x.min.js",   # inside a root, dropped by the skip rule
               "src/scripts/x.d.ts", "src/lupin_mcp/x.js" ]                                       # a skipped suffix, a script in a Python-only root
    held   = [ "src/lupin_mcp/reuse_outcome.py", "src/scripts/run.mjs", "src/lupin_app/static/js/notifications/x.ts", "src/tests/../lupin_mcp/x.py",
               "src/cosa/repo/symindex/ts_extract.js", "src/conf/x.js", "src/scripts/x.py" ]       # src/scripts is both a Python and a script root
    got     = lines( *[ ( "unindexed", "unindexed", f"{p} is not code" ) for p in unheld + held ] )
    refused = [ r[ "line" ] for r in ro.token_refusals( got, {}, ROOT ) ]
    assert refused == [ g[ "line" ] for g in got[ len( unheld ): ] ], "the roots alone do not decide it; the suffix and the skip rule do, and a path that climbs back in is resolved first"
    assert "symbol index holds" in ro.token_refusals( got[ -1: ], {}, ROOT )[ 0 ][ "reason" ]


def test_the_rule_is_the_indexers_own_for_the_tree_given( tmp_path ):
    for d in ( "src/cosa", "src/lupin_mcp", "src/scripts" ): ( tmp_path / d ).mkdir( parents=True )
    assert ro.is_indexed( "src/scripts/a.mjs", tmp_path ) and not ro.is_indexed( "src/docs/a.md", tmp_path ) and not ro.is_indexed( "src/scripts/a.sh", tmp_path )
    assert not ro.is_indexed( "src/lupin_app/x.py", tmp_path ), "this tree has no lupin_app directory, so it is no root here"
    assert ro.is_indexed( "src/lupin_app/x.py", ROOT ), "the real tree has one"
    assert not ro.is_indexed( "../elsewhere/x.py", tmp_path ), "a path outside the tree is not held"


def test_unindexed_must_stand_in_both_slots_and_a_real_receipt_keeps_its_own_meaning():
    got = lines( ( "unindexed", "rs-bc3ca2c901", "src/rnd/x.md is a note" ),
                 ( "5d37236290c7d93f", "unindexed", "src/rnd/x.md is a note" ),
                 ( "5d37236290c7d93f", "rs-bc3ca2c901", "lupin_mcp.secret.helper is new" ) )
    out = ro.token_refusals( got, EXCLUSIONS, ROOT )
    assert [ r[ "line" ] for r in out ] == [ got[ 0 ][ "line" ], got[ 1 ][ "line" ] ]
    assert "both id slots" in out[ 0 ][ "reason" ] and "needs unindexed in the receipt slot" in out[ 1 ][ "reason" ]
    assert ro.token_refusals( [], EXCLUSIONS, ROOT ) == []


def test_for_a_file_on_disk_the_rule_agrees_with_the_indexers_own_file_list():
    spec    = sp.spec_for( ROOT )
    indexed = { p.resolve() for p in sp.all_files( spec ) }
    assert len( indexed ) > 1000, "the list was read, so agreement below is not over an empty set"
    tracked = [ ROOT / f for f in subprocess.run( [ "git", "ls-files", "src" ], cwd=ROOT, capture_output=True, text=True, check=True ).stdout.split( "\n" ) if f ]
    assert any( p.resolve() not in indexed for p in tracked ) and any( p.resolve() in indexed for p in tracked )
    assert [ p for p in tracked if p.is_file() and ro.is_indexed( p, ROOT ) != ( p.resolve() in indexed ) ] == []


# The call-log check (plan section 12.3, the third step of track B)

REAL_LOG    = pathlib.Path( __file__ ).parent / "reuse_call_log_real_2026.11.02.jsonl"
REAL_RECORD = pathlib.Path( __file__ ).parent / "reuse_search_record_real_rs-bc3ca2c901.json"
REAL_RID    = "5d37236290c7d93f"                                       # a check_exists receipt a real seat made
REAL_SID    = "rs-bc3ca2c901"                                          # the record_search made on it, whose record file is the fixture
OTHER_SID   = "rs-98ce3e6760"                                          # a real record_search call in the same log whose record file is not in the fixture


def real_readers( tmp_path ):
    """Ensures: returns ( receipts, searches ) read from the real log and record."""
    logs = tmp_path / "call-log"
    logs.mkdir()
    ( logs / "real.jsonl" ).write_text( REAL_LOG.read_text( encoding="utf-8" ), encoding="utf-8" )
    ( tmp_path / "search-records" ).mkdir()
    ( tmp_path / "search-records" / f"{REAL_SID}.json" ).write_text( REAL_RECORD.read_text( encoding="utf-8" ), encoding="utf-8" )
    records = eg.merge_call_logs( logs )[ 0 ]
    return eg.receipts_by_id( records ), eg.searches_by_receipt( records, tmp_path )


def test_a_line_citing_a_real_receipt_and_its_own_search_passes_the_log_check( tmp_path ):
    receipts, searches = real_readers( tmp_path )
    assert REAL_RID in receipts and REAL_SID in searches[ REAL_RID ], "the readers found the real receipt and search"
    assert ro.log_refusals( lines( ( REAL_RID, REAL_SID, "the helper is new" ) ), receipts, searches ) == []


def test_a_receipt_or_search_that_is_not_in_the_log_is_refused_with_what_to_do( tmp_path ):
    receipts, searches = real_readers( tmp_path )
    got = lines( ( "0123456789abcdef", REAL_SID, "no such receipt" ),
                 ( REAL_RID, "rs-0000000000", "no such search" ),
                 ( REAL_RID, OTHER_SID, "a real search call that has no record file and is on another receipt" ) )
    out = ro.log_refusals( got, receipts, searches )
    assert [ r[ "line" ] for r in out ] == [ g[ "line" ] for g in got ]
    assert out[ 0 ][ "reason" ].startswith( "receipt 0123456789abcdef is not in the log" )
    assert all( r[ "reason" ].startswith( ( "receipt", "search" ) ) and "not in the log" in r[ "reason" ] for r in out )
    assert all( "re-run the lookup" in r[ "reason" ] and "log folder" in r[ "reason" ] and "failed log write" in r[ "reason" ] for r in out )
    assert not any( "fabricat" in r[ "reason" ].lower() for r in out ), "the wording says absent, never made up"


def test_a_receipt_whose_lookup_logged_an_error_is_not_in_the_log():
    receipts = eg.receipts_by_id( [ call( None, "BAD_LANGUAGE" ) | { "tool": "check_exists", "receipt_id": "0123456789abcdef" } ] )
    out      = ro.log_refusals( lines( ( "0123456789abcdef", "rs-bc3ca2c901", "text" ) ), receipts, {} )
    assert len( out ) == 1 and "is not in the log" in out[ 0 ][ "reason" ]


def test_the_log_check_leaves_the_two_tokens_to_the_token_check():
    got = lines( ( "excluded", "rs-bc3ca2c901", "lupin_mcp.x is refused" ), ( "unindexed", "unindexed", "src/rnd/x.md" ), ( REAL_RID, "unindexed", "text" ) )
    out = ro.log_refusals( got, { REAL_RID: "check_exists" }, {} )
    assert out == [], "token lines are not judged here; a real receipt beside unindexed is refused by the token check"
    assert [ r[ "line" ] for r in ro.token_refusals( got[ 2: ], {}, ROOT ) ] == [ got[ 2 ][ "line" ] ]


# The kinds must pair (plan section 12.3, the fifth step of track B)

R_A, R_B, R_C = "0123456789abcdef", "1123456789abcdef", "2123456789abcdef"


def pair_text( *rulings ):
    """Ensures: the rulings of ( symbol, text, receipt ) triples, read by the gate's parser."""
    return eg.parse_rulings( "\n".join( f"RULING {sym} :: {ruling} :: reuse-receipt: {rid}" for sym, ruling, rid in rulings ) )


def outcome_lines( *rows ):
    """Ensures: the parsed outcome lines of ( receipt, outcome text ) rows."""
    return ro.parse_outcomes( "\n".join( f"REUSE-OUTCOME {r} :: rs-bc3ca2c901 :: {text} :: {PLAN}#12.3-B5" for r, text in rows ) )


def test_each_ruling_kind_passes_with_its_own_outcome_kind_and_no_other():
    rulings = pair_text( ( "m.a", "DUPLICATE", R_A ), ( "m.b", "EXTEND m.q", R_B ), ( "m.c", "DISTINCT it differs", R_C ) )
    right   = outcome_lines( ( R_A, "REUSED m.q" ), ( R_B, "EXTENDED m.q" ), ( R_C, "WROTE_NEW it differs" ) )
    assert ro.pairing_refusals( right, rulings ) == []
    for rid, wrong in ( ( R_A, ( "EXTENDED m.q", "WROTE_NEW x" ) ), ( R_B, ( "REUSED m.q", "WROTE_NEW x" ) ), ( R_C, ( "REUSED m.q", "EXTENDED m.q" ) ) ):
        for text in wrong:
            got = outcome_lines( ( rid, text ) )
            out = ro.pairing_refusals( got, rulings )
            assert [ r[ "line" ] for r in out ] == [ got[ 0 ][ "line" ] ], f"{rid} with {text}"


def test_a_ruling_distinct_with_an_outcome_reused_is_refused_naming_both():
    rulings = pair_text( ( "m.x", "DISTINCT it differs", R_A ) )
    out     = ro.pairing_refusals( outcome_lines( ( R_A, "REUSED m.q" ) ), rulings )
    assert len( out ) == 1 and "outcome is REUSED" in out[ 0 ][ "reason" ] and "m.x is DISTINCT" in out[ 0 ][ "reason" ] and R_A in out[ 0 ][ "reason" ]


def test_an_outcome_line_whose_receipt_no_ruling_cites_is_refused():
    rulings = pair_text( ( "m.x", "DUPLICATE", R_A ) )
    got     = outcome_lines( ( R_B, "REUSED m.q" ) )
    out     = ro.pairing_refusals( got, rulings )
    assert [ r[ "line" ] for r in out ] == [ got[ 0 ][ "line" ] ] and "no ruling line" in out[ 0 ][ "reason" ]
    assert ro.pairing_refusals( got, {} )[ 0 ][ "reason" ].endswith( "no ruling line" ), "a document with no ruling line at all"


def test_pairing_goes_by_receipt_so_two_symbols_on_one_receipt_pass_when_one_pairs_and_the_tokens_are_left_alone():
    rulings = pair_text( ( "m.x", "DUPLICATE", R_A ), ( "m.y", "DISTINCT it differs", R_A ), ( "m.z", "DISTINCT it differs", "excluded" ) )
    assert ro.pairing_refusals( outcome_lines( ( R_A, "REUSED m.q" ) ), rulings ) == []
    assert ro.pairing_refusals( outcome_lines( ( R_A, "WROTE_NEW it differs" ) ), rulings ) == []
    out = ro.pairing_refusals( outcome_lines( ( R_A, "EXTENDED m.q" ) ), rulings )
    assert len( out ) == 1 and "m.x is DUPLICATE, m.y is DISTINCT" in out[ 0 ][ "reason" ]
    tokens = outcome_lines( ( "excluded", "WROTE_NEW refused" ), ( "unindexed", "WROTE_NEW src/rnd/x.md" ) )
    assert ro.pairing_refusals( tokens, rulings ) == []


def test_a_new_definition_with_no_outcome_line_is_refused():
    rulings = pair_text( ( "m.a", "DUPLICATE", R_A ), ( "m.b", "DISTINCT it differs", R_B ), ( "m.c", "DUPLICATE", R_C ) )
    got     = outcome_lines( ( R_A, "REUSED m.q" ), ( R_C, "REUSED m.q" ) ) + outcome_lines( ( "excluded", "WROTE_NEW m.e is refused" ) )
    out     = ro.missing_outcome_refusals( [ "m.a", "m.b", "m.c", "m.d", "m.e" ], got, rulings )
    assert [ r[ "symbol" ] for r in out ] == [ "m.b", "m.d" ], "m.b has a ruling whose receipt has no outcome line; m.d has no ruling; m.e is named by an excluded line"
    assert "m.b is new in the diff and has no outcome line" == out[ 0 ][ "reason" ]
    assert ro.missing_outcome_refusals( [], got, rulings ) == [] and ro.missing_outcome_refusals( [ "m.a" ], [], rulings ) == [ { "symbol": "m.a", "reason": "m.a is new in the diff and has no outcome line" } ]


def test_the_excluded_and_unindexed_lines_are_skipped_by_pairing_not_refused_and_the_token_check_still_judges_them():
    rulings = pair_text( ( "m.z", "DISTINCT it differs", "excluded" ) )
    tokens  = outcome_lines( ( "excluded", "REUSED m.z" ), ( "unindexed", "EXTENDED src/rnd/x.md" ) )
    assert ro.pairing_refusals( tokens, rulings ) == [] and ro.pairing_refusals( tokens, {} ) == [], "no ruling pairs them and nothing is refused, even with a kind that would not pair"
    out = ro.token_refusals( tokens, {}, ROOT )
    assert [ r[ "line" ] for r in out ] == [ t[ "line" ] for t in tokens ], "the token check judges both: no log refusal for the first, and the second lacks unindexed in its search slot"


def two_receipts( tmp_path ):
    """Ensures: returns ( receipts, searches ) for two lookups, each with its own search record."""
    ( tmp_path / "search-records" ).mkdir()
    calls = []
    for rid, sid in ( ( R_A, "rs-aaaaaaaaaa" ), ( R_B, "rs-bbbbbbbbbb" ) ):
        ( tmp_path / "search-records" / f"{sid}.json" ).write_text( json.dumps( { "id": sid, "receipt_id": rid, "candidates": [ { "id": "m.c" } ] } ), encoding="utf-8" )
        calls += [ { "tool": "check_exists", "receipt_id": rid, "error": None }, { "tool": "record_search", "search_id": sid, "receipt_id": rid, "error": None } ]
    return eg.receipts_by_id( calls ), eg.searches_by_receipt( calls, tmp_path )


def test_a_real_search_that_belongs_to_another_receipt_is_refused( tmp_path ):
    receipts, searches = two_receipts( tmp_path )
    base  = outcome_lines( ( R_A, "REUSED m.q" ), ( R_B, "REUSED m.q" ) )
    own   = [ dict( base[ 0 ], search="rs-aaaaaaaaaa" ), dict( base[ 1 ], search="rs-bbbbbbbbbb" ) ]
    cross = [ dict( base[ 0 ], search="rs-bbbbbbbbbb", line="A cites B's search" ), dict( base[ 1 ], search="rs-aaaaaaaaaa", line="B cites A's search" ) ]
    assert ro.log_refusals( own, receipts, searches ) == [], "each receipt with its own search passes"
    out = ro.log_refusals( cross, receipts, searches )
    assert [ r[ "line" ] for r in out ] == [ "A cites B's search", "B cites A's search" ] and all( "is not in the log for receipt" in r[ "reason" ] for r in out )
    anywhere = { sid for found in searches.values() for sid in found }
    assert all( c[ "search" ] in anywhere for c in cross ), "each cited search is in the log, so a check that only asks whether the search exists anywhere would pass both lines"


def test_a_token_line_for_one_definition_does_not_cover_another_that_cites_the_same_token():
    rulings = pair_text( ( "m.d1", "DISTINCT it differs", "excluded" ), ( "m.d2", "DISTINCT it differs", "excluded" ), ( "m.d3", "DISTINCT it differs", "unindexed" ), ( "m.d4", "DISTINCT it differs", "unindexed" ) )
    one     = outcome_lines( ( "excluded", "WROTE_NEW m.d1 is refused" ), ( "unindexed", "WROTE_NEW src/rnd/x.md is a note" ) )
    out     = ro.missing_outcome_refusals( [ "m.d1", "m.d2", "m.d3", "m.d4" ], one, rulings )
    assert [ r[ "symbol" ] for r in out ] == [ "m.d2", "m.d3", "m.d4" ], "only the definition the excluded line names is covered; an unindexed line names a file, not a definition"


def test_a_dart_file_in_a_dart_root_is_held_by_the_index_and_the_rest_are_not( tmp_path ):
    ( tmp_path / "pubspec.yaml" ).write_text( "name: app\n", encoding="utf-8" )
    for d in ( "lib", "lib/generated", "test" ): ( tmp_path / d ).mkdir( parents=True )
    held   = [ "lib/a.dart" ]
    unheld = [ "lib/generated/b.dart", "lib/c.g.dart", "lib/d.freezed.dart", "lib/e.py", "lib/f.js", "test/g.dart", "pubspec.yaml" ]
    assert [ ro.is_indexed( p, tmp_path ) for p in held ] == [ True ]
    assert [ ro.is_indexed( p, tmp_path ) for p in unheld ] == [ False ] * len( unheld ), "a skipped folder, skipped endings, another language and a folder that is not a root"
    line = ro.parse_outcomes( f"REUSE-OUTCOME unindexed :: unindexed :: WROTE_NEW lib/a.dart is code :: {PLAN}#12.3-B4" )
    assert len( ro.token_refusals( line, {}, tmp_path ) ) == 1, "an unindexed claim for the held file is refused in that tree"
