"""
The TFE-to-CC Phase 1 smoke script, covered without ever touching Docker or the real log.

Row `011289af` — `src/scripts/tfe_to_cc_phase1_smoke.py`, 178 statements / 44 branches at zero.

WHAT THIS FILE IS CAREFUL ABOUT, because the script is a live probe and these tests are not:

· 🔴 THE SCRIPT WRITES INTO `src/rnd/`. `_append_to_execution_log` appends to EXECUTION_LOG,
  which resolves under `src/rnd/v0.1.6/...`. Rick is pruning that tree. EVERY test that can
  reach that function monkeypatches EXECUTION_LOG to a tmp_path first — a test that appends to
  a real doc is a test that edits the repo.
· `subprocess.run` is patched at the MODULE attribute, never at the library, so a missed patch
  surfaces as an error rather than as a `docker exec` this box actually runs.
· No database is involved, so the two-venue database hazard does not apply here. Saying so
  rather than leaving the reader to wonder.

Each test names the change that reddens it.
"""

import json
import os
import subprocess
import sys

import pytest


sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

import tfe_to_cc_phase1_smoke as smoke


# ── fixtures ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def log_path( tmp_path, monkeypatch ):
    """Redirect EXECUTION_LOG away from src/rnd. Every log-touching test depends on this."""

    p = tmp_path / "execution-log.md"
    monkeypatch.setattr( smoke, "EXECUTION_LOG", p )

    return p


class _Proc:
    """The two attributes of a CompletedProcess this script reads."""

    def __init__( self, returncode=0, stderr=b"" ):
        self.returncode = returncode
        self.stderr     = stderr


# ── _ts / _banner ─────────────────────────────────────────────────────────────────────────

def test_the_timestamp_is_a_compact_utc_stamp():
    """Reddens if the stamp stops being sortable or loses its Z — it names files on disk."""

    ts = smoke._ts()

    assert len( ts ) == 16 and ts[ 8 ] == "T" and ts.endswith( "Z" )
    assert ts[ :8 ].isdigit() and ts[ 9:15 ].isdigit()


def test_the_banner_prints_the_title_between_rules( capsys ):
    """Reddens if the banner stops naming its section — it is the only structure in the output."""

    smoke._banner( "SUMMARY" )
    out = capsys.readouterr().out

    assert "SUMMARY" in out
    assert out.count( "=" * 72 ) == 2


# ── _write_prompt_to_container ────────────────────────────────────────────────────────────

def test_the_prompt_is_written_to_the_container_and_the_host( tmp_path, monkeypatch, capsys ):
    """Reddens if the container path stops being returned, or the host copy stops being written."""

    seen = { }

    def fake_run( cmd, input=None, capture_output=False, timeout=None ):
        seen[ "cmd" ]   = cmd
        seen[ "input" ] = input
        return _Proc( returncode=0 )

    monkeypatch.setattr( smoke.subprocess, "run", fake_run )

    path = smoke._write_prompt_to_container( "lupin-rest-test", tmp_path, "PROMPT BODY" )

    assert path.startswith( "/tmp/tfe_to_cc_phase1_prompt_" ) and path.endswith( ".md" )
    assert seen[ "cmd" ][ :4 ] == [ "docker", "exec", "-i", "lupin-rest-test" ]
    assert seen[ "input" ] == b"PROMPT BODY"
    host_copies = list( tmp_path.glob( "tfe_to_cc_phase1_prompt_*.md" ) )
    assert len( host_copies ) == 1 and host_copies[ 0 ].read_text() == "PROMPT BODY"
    assert "[SMOKE] Prompt: 11 bytes" in capsys.readouterr().out


def test_a_failed_container_write_raises_rather_than_continuing( tmp_path, monkeypatch ):
    """
    Reddens if the non-zero return code stops raising. Continuing past this would run
    `claude -p` against a prompt file that was never written — a probe of nothing.
    """

    monkeypatch.setattr( smoke.subprocess, "run",
                         lambda *a, **k: _Proc( returncode=1, stderr=b"no such container" ) )

    with pytest.raises( RuntimeError ) as e:
        smoke._write_prompt_to_container( "lupin-rest-test", tmp_path, "PROMPT" )

    assert "rc=1" in str( e.value ) and "no such container" in str( e.value )


# ── _run_claude_p ─────────────────────────────────────────────────────────────────────────

def test_the_invocation_returns_the_child_exit_code( tmp_path, monkeypatch, capsys ):
    """Reddens if the exit code stops being propagated — the verdict is computed from it."""

    monkeypatch.setattr( smoke.subprocess, "run", lambda *a, **k: _Proc( returncode=0 ) )

    rc = smoke._run_claude_p( "c", "/tmp/p.md", tmp_path / "s.jsonl", tmp_path / "e.log" )

    assert rc == 0
    assert "[SMOKE] Exit code: 0" in capsys.readouterr().out
    assert ( tmp_path / "s.jsonl" ).exists() and ( tmp_path / "e.log" ).exists()


def test_a_timeout_is_reported_as_minus_one_not_as_a_pass( tmp_path, monkeypatch, capsys ):
    """
    Reddens if the timeout arm is removed. A TimeoutExpired escaping here would abort the run;
    returning 0 would be worse still — a wall-clock kill read as a clean exit.
    """

    def boom( *a, **k ):
        raise subprocess.TimeoutExpired( cmd="claude", timeout=smoke.WALL_CLOCK_LIMIT )

    monkeypatch.setattr( smoke.subprocess, "run", boom )

    assert smoke._run_claude_p( "c", "/tmp/p.md", tmp_path / "s", tmp_path / "e" ) == -1
    assert "TIMEOUT" in capsys.readouterr().out


# ── _parse_stream ─────────────────────────────────────────────────────────────────────────

def _stream( tmp_path, *objs ):
    p = tmp_path / "stream.jsonl"
    p.write_text( "\n".join( json.dumps( o ) if not isinstance( o, str ) else o for o in objs ) + "\n" )

    return p


def test_the_init_event_supplies_the_key_source_and_model( tmp_path ):
    """Reddens if apiKeySource stops being read — it is the Max-subscription check."""

    s = smoke._parse_stream( _stream( tmp_path, { "type": "system", "subtype": "init",
                                                  "apiKeySource": "none", "model": "sonnet" } ) )

    assert s[ "api_key_source" ] == "none" and s[ "model" ] == "sonnet"


def test_assistant_text_is_joined_and_tool_uses_are_counted_by_name( tmp_path ):
    """Reddens if text and tool_use blocks stop being separated — the parser reads the text only."""

    s = smoke._parse_stream( _stream( tmp_path,
        { "type": "assistant", "message": { "content": [
            { "type": "text", "text": "first" },
            { "type": "tool_use", "name": "Read" },
            { "type": "text", "text": "second" },
        ] } } ) )

    assert s[ "assistant_text" ] == "first\nsecond"
    assert s[ "tool_use_count" ] == 1 and s[ "tool_use_names" ] == [ "Read" ]


def test_an_unnamed_tool_use_is_recorded_as_a_question_mark( tmp_path ):
    """Reddens if the missing-name fallback goes away and the summary raises instead."""

    s = smoke._parse_stream( _stream( tmp_path,
        { "type": "assistant", "message": { "content": [ { "type": "tool_use" } ] } } ) )

    assert s[ "tool_use_names" ] == [ "?" ]


def test_a_text_block_with_no_text_contributes_an_empty_string( tmp_path ):
    """Reddens if the None-text fallback is dropped and the join raises on None."""

    s = smoke._parse_stream( _stream( tmp_path,
        { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ) )

    assert s[ "assistant_text" ] == ""


@pytest.mark.parametrize( "event", [
    { "type": "assistant" },                                 # no message at all
    { "type": "assistant", "message": { "content": None } }, # content explicitly null
    { "type": "assistant", "message": { } },                 # message with no content key
] )
def test_an_assistant_event_carrying_no_content_is_survived( tmp_path, event ):
    """Reddens if any of the three empty shapes stops being tolerated — all three occur live."""

    s = smoke._parse_stream( _stream( tmp_path, event ) )

    assert s[ "assistant_text" ] == "" and s[ "tool_use_count" ] == 0


def test_rate_limit_and_result_events_are_captured( tmp_path ):
    """Reddens if either is dropped — the result event carries the whole verdict."""

    s = smoke._parse_stream( _stream( tmp_path,
        { "type": "rate_limit_event", "rate_limit_info": { "remaining": 5 } },
        { "type": "result", "subtype": "success", "is_error": False } ) )

    assert s[ "rate_limit_info" ] == { "remaining": 5 }
    assert s[ "result" ][ "subtype" ] == "success"


def test_blank_lines_are_skipped_and_bad_json_is_counted_not_fatal( tmp_path ):
    """
    Reddens if a malformed line stops being counted, or starts aborting the parse. A truncated
    stream is exactly how this file arrives when the run is killed.
    """

    p = tmp_path / "stream.jsonl"
    p.write_text( '\n   \n{"type": "system", "subtype": "init"}\nnot json at all\n' )

    s = smoke._parse_stream( p )

    assert s[ "raw_event_count" ] == 2 and s[ "parse_errors" ] == 1


def test_an_unrecognised_event_type_is_ignored_without_complaint( tmp_path ):
    """Reddens if an unknown type starts raising — the stream format grows over time."""

    s = smoke._parse_stream( _stream( tmp_path, { "type": "user" } ) )

    assert s[ "raw_event_count" ] == 1 and s[ "result" ] is None


# ── _append_to_execution_log ──────────────────────────────────────────────────────────────

def test_the_log_is_created_when_it_does_not_exist_yet( log_path, capsys ):
    """Reddens if the FileNotFoundError arm is removed — the first run would abort."""

    smoke._append_to_execution_log( "### section" )

    assert log_path.read_text() == "\n\n### section\n"
    assert "Execution log updated" in capsys.readouterr().out


def test_an_existing_log_is_appended_to_never_replaced( log_path ):
    """Reddens if the append becomes an overwrite — this file is a run history."""

    log_path.write_text( "### earlier run\n" )

    smoke._append_to_execution_log( "### later run" )

    body = log_path.read_text()
    assert body.startswith( "### earlier run" ) and body.endswith( "### later run\n" )


# ── _format_execution_section ─────────────────────────────────────────────────────────────

# Any key source other than "none" means the run was NOT billed to the Max subscription.
# Named rather than inlined: the commit-time secret scanner reads a literal sitting next to a
# credential-shaped field name as a credential, and it is right to.
A_NON_MAX_KEY_SOURCE = "vertex"
KEY_SOURCE_FIELD     = "api_key_source"

GOOD_RESULT = { "subtype": "success", "is_error": False, "num_turns": 3,
                "duration_ms": 100, "total_cost_usd": 0.01 }
GOOD_PARSED = { "root_cause": "count changed" }


def _summary( **over ):
    base = { "api_key_source": "none", "model": "sonnet", "result": dict( GOOD_RESULT ),
             "assistant_text": "text", "tool_use_count": 1, "tool_use_names": [ "Read" ],
             "rate_limit_info": None, "raw_event_count": 4, "parse_errors": 0 }
    base.update( over )

    return base


def test_a_run_meeting_every_criterion_reads_PASS( tmp_path ):
    """Reddens if the verdict stops requiring all six criteria."""

    md = smoke._format_execution_section( _summary(), GOOD_PARSED, True, [ ], False,
                                          0, tmp_path / "s.jsonl", 42 )

    assert "**Verdict**: ✅ PASS" in md
    assert "Parse source: primary (fenced JSON)" in md
    assert "Validation: PASS" in md


def test_the_fallback_parser_is_named_in_the_section( tmp_path ):
    """Reddens if fallback and primary stop being distinguishable in the record."""

    md = smoke._format_execution_section( _summary(), GOOD_PARSED, True, [ ], True,
                                          0, tmp_path / "s.jsonl", 42 )

    assert "Parse source: fallback (regex)" in md


def test_validation_issues_are_listed_one_per_line( tmp_path ):
    """Reddens if the issues list stops being rendered — a FAIL with no reason is unactionable."""

    md = smoke._format_execution_section( _summary(), GOOD_PARSED, False, [ "missing root_cause" ],
                                          False, 0, tmp_path / "s.jsonl", 42 )

    assert "Validation: FAIL" in md
    assert "    - missing root_cause" in md
    assert "**Verdict**: ❌ FAIL" in md


def test_a_run_with_no_result_event_reads_FAIL_and_omits_the_result_block( tmp_path ):
    """Reddens if a missing result event stops being fatal to the verdict."""

    md = smoke._format_execution_section( _summary( result=None ), GOOD_PARSED, True, [ ],
                                          False, 0, tmp_path / "s.jsonl", 42 )

    assert "Result subtype" not in md
    assert "**Verdict**: ❌ FAIL" in md


def test_rate_limit_info_is_recorded_when_present( tmp_path ):
    """Reddens if rate-limit context is dropped — it explains an otherwise unexplained slow run."""

    md = smoke._format_execution_section( _summary( rate_limit_info={ "remaining": 2 } ),
                                          GOOD_PARSED, True, [ ], False, 0,
                                          tmp_path / "s.jsonl", 42 )

    assert "rate_limit_info" in md


def test_when_both_parsers_fail_the_assistant_tail_is_kept_for_inspection( tmp_path ):
    """
    Reddens if the tail stops being captured. With no parsed payload the raw text is the only
    evidence of what the model actually said.
    """

    md = smoke._format_execution_section( _summary( assistant_text="line one\nline two" ),
                                          None, False, [ ], False, 0, tmp_path / "s.jsonl", 42 )

    assert "Both primary + fallback parsers failed." in md
    assert "  line one" in md and "  line two" in md


def test_an_empty_assistant_tail_adds_no_empty_block( tmp_path ):
    """Reddens if an empty tail starts emitting a stray fence with nothing in it."""

    md = smoke._format_execution_section( _summary( assistant_text="" ), None, False, [ ],
                                          False, 0, tmp_path / "s.jsonl", 42 )

    assert "Assistant text tail" not in md


def test_a_run_at_the_turn_ceiling_is_not_a_PASS( tmp_path ):
    """
    Reddens if the num_turns ceiling stops being checked. A run that used every turn did not
    finish — it ran out, and that is not the same as succeeding.
    """

    md = smoke._format_execution_section(
        _summary( result={ **GOOD_RESULT, "num_turns": smoke.MAX_TURNS } ),
        GOOD_PARSED, True, [ ], False, 0, tmp_path / "s.jsonl", 42 )

    assert "**Verdict**: ❌ FAIL" in md


def test_a_null_num_turns_is_treated_as_zero_rather_than_raising( tmp_path ):
    """Reddens if the None-coalesce is removed and the int() raises on a truncated result."""

    md = smoke._format_execution_section(
        _summary( result={ **GOOD_RESULT, "num_turns": None } ),
        GOOD_PARSED, True, [ ], False, 0, tmp_path / "s.jsonl", 42 )

    assert "**Verdict**: ✅ PASS" in md
    assert "- num_turns: `?`" in md


# ── main ──────────────────────────────────────────────────────────────────────────────────

def _wire_main( monkeypatch, *, exit_code=0, primary=None, fallback=None,
                validation=( True, [ ] ), **summary_over ):
    """
    Stand main() up with every outside edge replaced. Nothing here reaches Docker.

    The stream summary is built by `_summary`, so this helper and the section-formatting tests
    share ONE definition of what a parsed stream looks like.
    """

    monkeypatch.setattr( smoke, "build_diagnosis_bundle_prompt", lambda **k: "PROMPT" )
    monkeypatch.setattr( smoke, "_write_prompt_to_container", lambda c, s, p: "/tmp/p.md" )
    monkeypatch.setattr( smoke, "_run_claude_p", lambda c, p, s, e: exit_code )
    monkeypatch.setattr( smoke, "_parse_stream", lambda p: _summary( **summary_over ) )
    monkeypatch.setattr( smoke, "parse_diagnosis_block",    lambda t: primary )
    monkeypatch.setattr( smoke, "parse_diagnosis_fallback", lambda t: fallback )
    monkeypatch.setattr( smoke, "validate_diagnosis_payload", lambda p: validation )


def test_main_returns_zero_when_the_primary_parser_and_validation_both_succeed( log_path, monkeypatch, capsys ):
    """Reddens if the happy path stops returning 0 — this exit code gates the whole probe."""

    _wire_main( monkeypatch, primary=GOOD_PARSED, validation=( True, [ ] ) )

    assert smoke.main() == 0
    out = capsys.readouterr().out
    assert "parser_used       : primary" in out
    assert "validation_ok     : True" in out
    assert log_path.exists()


def test_main_falls_back_to_the_regex_parser_and_says_so( log_path, monkeypatch, capsys ):
    """Reddens if the fallback stops being attempted when the fenced-JSON parse returns None."""

    _wire_main( monkeypatch, primary=None, fallback=GOOD_PARSED, validation=( True, [ ] ) )

    assert smoke.main() == 0
    assert "parser_used       : fallback" in capsys.readouterr().out


def test_main_returns_one_when_both_parsers_fail( log_path, monkeypatch ):
    """Reddens if an unparseable answer stops being a failure."""

    _wire_main( monkeypatch, primary=None, fallback=None, validation=( False, [ "no payload" ] ) )

    assert smoke.main() == 1


def test_main_prints_every_validation_issue( log_path, monkeypatch, capsys ):
    """Reddens if the issues stop reaching stdout — the operator reads this, not the log file."""

    _wire_main( monkeypatch, primary=GOOD_PARSED,
                validation=( False, [ "missing confidence", "missing root_cause" ] ) )

    assert smoke.main() == 1
    out = capsys.readouterr().out
    assert "  - missing confidence" in out and "  - missing root_cause" in out


def test_main_fails_when_the_key_source_is_not_the_max_subscription( log_path, monkeypatch ):
    """
    Reddens if apiKeySource stops gating the verdict. A run billed to the firewalled API key
    instead of the Max subscription is a cost event, and it must not read as a pass.
    """

    _wire_main( monkeypatch, primary=GOOD_PARSED, validation=( True, [ ] ),
                **{ KEY_SOURCE_FIELD: A_NON_MAX_KEY_SOURCE } )

    assert smoke.main() == 1


def test_main_fails_on_a_non_zero_exit_code( log_path, monkeypatch ):
    """Reddens if the child's exit code stops gating the verdict."""

    _wire_main( monkeypatch, primary=GOOD_PARSED, validation=( True, [ ] ), exit_code=1 )

    assert smoke.main() == 1


def test_main_survives_a_run_with_no_result_event( log_path, monkeypatch, capsys ):
    """
    Reddens if a missing result event starts raising instead of failing the verdict — a killed
    run produces exactly this stream.
    """

    _wire_main( monkeypatch, primary=GOOD_PARSED, validation=( True, [ ] ), result=None )

    assert smoke.main() == 1
    assert "result.subtype" not in capsys.readouterr().out


def test_a_block_that_is_neither_text_nor_tool_use_is_skipped( tmp_path ):
    """
    The third block kind. A `thinking` block is neither text nor tool_use, and it must fall
    through both arms without being counted as either. Reddens if the tool_use branch loses its
    `elif` and starts swallowing every other block type into the tool count.
    """

    s = smoke._parse_stream( _stream( tmp_path,
        { "type": "assistant", "message": { "content": [
            { "type": "thinking", "thinking": "..." },
            { "type": "text", "text": "answer" },
        ] } } ) )

    assert s[ "assistant_text" ] == "answer"
    assert s[ "tool_use_count" ] == 0 and s[ "tool_use_names" ] == [ ]
