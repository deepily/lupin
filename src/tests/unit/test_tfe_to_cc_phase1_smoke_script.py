"""
Unit tests for src/scripts/tfe_to_cc_phase1_smoke.py — the TFE-to-CC Phase 1 live probe.

WHY THIS FILE EXISTS (row 9ad838d6, under epic e2099400): `src/scripts` is entering the
coverage frame and this module was the largest remaining zero — 178 statements and 44
branches, nothing measured. Measured here before a line was written, so the number is this
tree's rather than a relayed one: 178 statements / 44 branches / 11%, which matches
Tiberius's watched figure exactly.

These are behaviour tests, not a coverage veneer: every assertion names something the probe
must do, and the mutation table on the row records which named test reddens when each
behaviour is broken.

⚠️ THE ISOLATION HAZARD, AND WHY THE FIXTURE IS AUTOUSE.
`_append_to_execution_log` does a read-modify-WRITE on `EXECUTION_LOG`, which is a real
TRACKED document in this repo — `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/
20-tfe-to-cc-phase1-live-test.md`, 17 KB at the time of writing. A single unguarded call
appends test noise to a checked-in design doc. The autouse fixture repoints the module's
`EXECUTION_LOG` at a tmp_path file, so the failure has to be opted out of rather than opted
into, and one test asserts the redirect itself rather than trusting it.

The second hazard is the container: `_write_prompt_to_container` and `_run_claude_p` shell
out to `docker exec`. Every test patches `mod.subprocess.run`, so no test needs Docker, a
server, or a socket. The one test that executes the module top-to-bottom patches the stdlib
`subprocess.run` instead, for the reason given on that test.

⚠️ THE COLLECTION QUESTION, MEASURED RATHER THAN REASONED (asked by Mr. Radio, and worth
recording because the next seat down the zero-coverage list will copy this file).

The worry is reasonable: the script is named `..._smoke.py`, it lives beside a `src/tests/
smoke/` venue, and a script that pytest tries to COLLECT as a test module would be imported
by the collector at a moment nothing has patched `subprocess` — the import itself is safe
(the `__main__` guard holds), but a collected module is a module pytest may also try to
report on, and the name invites it.

It does not happen, and I checked both ways it could:

    pytest src/scripts/                          -> no tests collected   (directory recursion)
    pytest src/scripts/tfe_to_cc_phase1_smoke.py -> no tests collected   (path named EXPLICITLY)

The second is the one worth knowing. Naming a file on the command line does NOT bypass
`python_files`, which pytest.ini pins to `test_*.py`; this script matches neither that nor
the `*_test.py` default, so it is invisible to the collector even when pointed straight at
it. So NO special handling is needed to keep it out of collection — no `collect_ignore`, no
rename, no marker.

⇒ WHAT THE NEXT SEAT SHOULD ACTUALLY COPY is the import, not a collection workaround: put
`src/scripts` on `sys.path` and import the script under its REAL module name, so coverage
attributes to the real file. A `runpy`/`exec` load or a copy into tmp_path would run the same
source under a different filename and score zero against the file you were asked to cover.
The one place `runpy` IS right is the `__main__` guard, which cannot be reached by importing;
that test says so at its own site.
"""

import json
import os
import runpy
import re
import subprocess
import sys
from pathlib import Path

import pytest


def _load_module():
    """Import the script under its real name (src/scripts on path) so coverage targets the file."""
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import tfe_to_cc_phase1_smoke
    return tfe_to_cc_phase1_smoke


mod = _load_module()


class _FakeProc:
    """Stand-in for CompletedProcess — only the two attributes the script reads."""

    def __init__( self, returncode=0, stderr=b"" ):
        self.returncode = returncode
        self.stderr     = stderr


@pytest.fixture( autouse=True )
def redirected_execution_log( monkeypatch, tmp_path ):
    """Repoint EXECUTION_LOG at tmp_path so no test can append to the tracked design doc."""
    log = tmp_path / "20-tfe-to-cc-phase1-live-test.md"
    monkeypatch.setattr( mod, "EXECUTION_LOG", log )
    return log


# ────────────────────────────────────────────────────────────────────────
# The guard itself
# ────────────────────────────────────────────────────────────────────────

class TestTheIsolationGuard:

    def test_the_execution_log_is_redirected_away_from_the_tracked_doc( self, redirected_execution_log ):
        """The autouse redirect is asserted, not assumed — it is the only thing standing between
        these tests and a checked-in 17 KB design document."""
        assert mod.EXECUTION_LOG == redirected_execution_log
        assert "src/rnd" not in str( mod.EXECUTION_LOG )

    def test_the_real_execution_log_is_a_tracked_file_under_src_rnd( self ):
        """States the size of the hazard the redirect exists for: the real target is a repo doc,
        so an unguarded append is a source-tree edit rather than a scratch write."""
        real_root = Path( mod.__file__ ).resolve().parent.parent.parent
        expected  = real_root / "src/rnd/v0.1.6/2026.04.10-test-fix-expediter/20-tfe-to-cc-phase1-live-test.md"
        assert expected.exists()


# ────────────────────────────────────────────────────────────────────────
# _ts
# ────────────────────────────────────────────────────────────────────────

class TestTimestamp:

    def test_ts_is_a_compact_utc_stamp( self ):
        assert re.fullmatch( r"\d{8}T\d{6}Z", mod._ts() )

    def test_ts_reads_the_clock_rather_than_returning_a_constant( self, monkeypatch ):
        """Pins the stamp to a known instant so a hardcoded return value cannot pass."""
        class _FixedDatetime:
            @staticmethod
            def now( tz ):
                import datetime as _dt
                return _dt.datetime( 2026, 8, 29, 22, 15, 30, tzinfo=tz )

        monkeypatch.setattr( mod, "datetime", _FixedDatetime )
        assert mod._ts() == "20260829T221530Z"


# ────────────────────────────────────────────────────────────────────────
# _banner
# ────────────────────────────────────────────────────────────────────────

class TestBanner:

    def test_banner_frames_the_title_between_two_rules( self, capsys ):
        mod._banner( "SUMMARY" )
        lines = capsys.readouterr().out.splitlines()
        assert lines[ 0 ] == ""
        assert lines[ 1 ] == "=" * 72
        assert lines[ 2 ] == "  SUMMARY"
        assert lines[ 3 ] == "=" * 72


# ────────────────────────────────────────────────────────────────────────
# _write_prompt_to_container
# ────────────────────────────────────────────────────────────────────────

class TestWritePromptToContainer:

    def test_it_pipes_the_prompt_into_the_named_container_and_returns_the_container_path( self, monkeypatch, tmp_path, capsys ):
        seen = {}

        def _fake_run( cmd, input=None, capture_output=None, timeout=None ):
            seen[ "cmd" ]     = cmd
            seen[ "input" ]   = input
            seen[ "timeout" ] = timeout
            return _FakeProc( returncode=0 )

        monkeypatch.setattr( mod.subprocess, "run", _fake_run )
        path = mod._write_prompt_to_container( "lupin-rest-test", tmp_path, "PROMPT BODY" )

        assert path.startswith( "/tmp/tfe_to_cc_phase1_prompt_" ) and path.endswith( ".md" )
        assert seen[ "cmd" ][ :4 ] == [ "docker", "exec", "-i", "lupin-rest-test" ]
        assert seen[ "cmd" ][ 4 ] == "sh"
        assert seen[ "cmd" ][ 5 ] == "-c"
        assert seen[ "cmd" ][ 6 ] == f"cat > {path}"
        assert seen[ "input" ]   == b"PROMPT BODY"
        assert seen[ "timeout" ] == 15

    def test_it_also_keeps_a_host_copy_for_inspection( self, monkeypatch, tmp_path, capsys ):
        monkeypatch.setattr( mod.subprocess, "run", lambda *a, **k: _FakeProc( returncode=0 ) )
        mod._write_prompt_to_container( "lupin-rest-test", tmp_path, "PROMPT BODY" )

        copies = list( tmp_path.glob( "tfe_to_cc_phase1_prompt_*.md" ) )
        assert len( copies ) == 1
        assert copies[ 0 ].read_text() == "PROMPT BODY"
        assert "Prompt: 11 bytes" in capsys.readouterr().out

    def test_a_nonzero_docker_exit_raises_rather_than_returning_a_path( self, monkeypatch, tmp_path ):
        """A silent failure here would hand a container path that holds no prompt, and the run
        would fail much later with an empty-prompt symptom."""
        monkeypatch.setattr( mod.subprocess, "run", lambda *a, **k: _FakeProc( returncode=3, stderr=b"no such container" ) )

        with pytest.raises( RuntimeError ) as excinfo:
            mod._write_prompt_to_container( "lupin-rest-test", tmp_path, "PROMPT BODY" )

        assert "rc=3" in str( excinfo.value )
        assert "no such container" in str( excinfo.value )

    def test_a_failed_write_leaves_no_host_copy_behind( self, monkeypatch, tmp_path ):
        monkeypatch.setattr( mod.subprocess, "run", lambda *a, **k: _FakeProc( returncode=1 ) )
        with pytest.raises( RuntimeError ):
            mod._write_prompt_to_container( "lupin-rest-test", tmp_path, "PROMPT BODY" )
        assert list( tmp_path.glob( "*.md" ) ) == []


# ────────────────────────────────────────────────────────────────────────
# _run_claude_p
# ────────────────────────────────────────────────────────────────────────

class TestRunClaudeP:

    def test_it_returns_the_child_exit_code_and_captures_both_streams( self, monkeypatch, tmp_path, capsys ):
        seen = {}

        def _fake_run( cmd, stdout=None, stderr=None, timeout=None ):
            seen[ "cmd" ]     = cmd
            seen[ "timeout" ] = timeout
            stdout.write( b"{}\n" )
            stderr.write( b"warn\n" )
            return _FakeProc( returncode=7 )

        monkeypatch.setattr( mod.subprocess, "run", _fake_run )
        out_path = tmp_path / "stream.jsonl"
        err_path = tmp_path / "stderr.log"

        assert mod._run_claude_p( "lupin-rest-test", "/tmp/p.md", out_path, err_path ) == 7
        assert out_path.read_bytes() == b"{}\n"
        assert err_path.read_bytes() == b"warn\n"
        assert seen[ "timeout" ] == mod.WALL_CLOCK_LIMIT
        assert "Exit code: 7" in capsys.readouterr().out

    def test_the_invocation_pins_the_model_turn_cap_and_tool_policy( self, monkeypatch, tmp_path ):
        """The probe's whole point is that it runs read-only on the Max subscription — the
        disallowed-tools list is the control, so it is asserted rather than assumed."""
        seen = {}

        def _fake_run( cmd, stdout=None, stderr=None, timeout=None ):
            seen[ "cmd" ] = cmd
            return _FakeProc( returncode=0 )

        monkeypatch.setattr( mod.subprocess, "run", _fake_run )
        mod._run_claude_p( "lupin-rest-test", "/tmp/p.md", tmp_path / "o", tmp_path / "e" )

        shell = seen[ "cmd" ][ -1 ]
        assert seen[ "cmd" ][ :2 ] == [ "docker", "exec" ]
        assert f"--model {mod.MODEL}" in shell
        assert f"--max-turns {mod.MAX_TURNS}" in shell
        assert "--output-format stream-json" in shell
        assert 'cat /tmp/p.md' in shell
        for banned in ( "Edit", "Write", "Bash" ):
            assert banned in shell.split( "--disallowedTools" )[ 1 ]

    def test_a_wall_clock_timeout_reports_minus_one_rather_than_hanging_the_caller( self, monkeypatch, tmp_path, capsys ):
        def _fake_run( cmd, stdout=None, stderr=None, timeout=None ):
            raise subprocess.TimeoutExpired( cmd, timeout )

        monkeypatch.setattr( mod.subprocess, "run", _fake_run )
        rc = mod._run_claude_p( "lupin-rest-test", "/tmp/p.md", tmp_path / "o", tmp_path / "e" )

        assert rc == -1
        assert f"TIMEOUT after {mod.WALL_CLOCK_LIMIT}s" in capsys.readouterr().out


# ────────────────────────────────────────────────────────────────────────
# _parse_stream
# ────────────────────────────────────────────────────────────────────────

class TestParseStream:

    def _write_stream( self, tmp_path, objs ):
        path  = tmp_path / "stream.jsonl"
        lines = [ o if isinstance( o, str ) else json.dumps( o ) for o in objs ]
        path.write_text( "\n".join( lines ) + "\n" )
        return path

    def test_an_empty_stream_yields_the_zeroed_summary( self, tmp_path ):
        path    = tmp_path / "stream.jsonl"
        path.write_text( "" )
        summary = mod._parse_stream( path )

        assert summary[ "raw_event_count" ] == 0
        assert summary[ "parse_errors" ]    == 0
        assert summary[ "api_key_source" ] is None
        assert summary[ "assistant_text" ] == ""
        assert summary[ "tool_use_names" ] == []

    def test_blank_lines_are_skipped_without_counting_as_events( self, tmp_path ):
        path = self._write_stream( tmp_path, [ "", "   ", { "type": "other" } ] )
        assert mod._parse_stream( path )[ "raw_event_count" ] == 1

    def test_unparseable_lines_are_counted_rather_than_raised( self, tmp_path ):
        """A truncated final line is normal for a killed stream; it must not lose the run."""
        path    = self._write_stream( tmp_path, [ "{not json", { "type": "other" } ] )
        summary = mod._parse_stream( path )

        assert summary[ "parse_errors" ]    == 1
        assert summary[ "raw_event_count" ] == 2

    def test_the_init_event_supplies_the_api_key_source_and_model( self, tmp_path ):
        """apiKeySource is the whole billing question — 'none' is what proves the Max path."""
        path = self._write_stream( tmp_path, [
            { "type": "system", "subtype": "init", "apiKeySource": "none", "model": "claude-sonnet-4-6" },
        ] )
        summary = mod._parse_stream( path )

        assert summary[ "api_key_source" ] == "none"
        assert summary[ "model" ]          == "claude-sonnet-4-6"

    def test_a_system_event_that_is_not_init_leaves_the_metadata_alone( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "system", "subtype": "compact", "apiKeySource": "leaked", "model": "wrong" },
        ] )
        summary = mod._parse_stream( path )

        assert summary[ "api_key_source" ] is None
        assert summary[ "model" ]          is None

    def test_assistant_text_blocks_are_joined_in_order( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "assistant", "message": { "content": [ { "type": "text", "text": "first" } ] } },
            { "type": "assistant", "message": { "content": [ { "type": "text", "text": "second" } ] } },
        ] )
        assert mod._parse_stream( path )[ "assistant_text" ] == "first\nsecond"

    def test_tool_use_blocks_are_counted_and_named( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "assistant", "message": { "content": [
                { "type": "tool_use", "name": "Read" },
                { "type": "tool_use", "name": "Grep" },
            ] } },
        ] )
        summary = mod._parse_stream( path )

        assert summary[ "tool_use_count" ] == 2
        assert summary[ "tool_use_names" ] == [ "Read", "Grep" ]

    def test_a_nameless_tool_use_is_recorded_as_a_question_mark( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "assistant", "message": { "content": [ { "type": "tool_use" } ] } },
        ] )
        assert mod._parse_stream( path )[ "tool_use_names" ] == [ "?" ]

    def test_a_textless_text_block_contributes_an_empty_string( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "assistant", "message": { "content": [ { "type": "text" }, { "type": "text", "text": "x" } ] } },
        ] )
        assert mod._parse_stream( path )[ "assistant_text" ] == "\nx"

    def test_a_block_that_is_neither_text_nor_tool_use_is_ignored( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "assistant", "message": { "content": [ { "type": "thinking", "text": "hidden" } ] } },
        ] )
        summary = mod._parse_stream( path )

        assert summary[ "assistant_text" ] == ""
        assert summary[ "tool_use_count" ] == 0

    def test_an_assistant_event_with_no_message_is_tolerated( self, tmp_path ):
        path = self._write_stream( tmp_path, [ { "type": "assistant" } ] )
        assert mod._parse_stream( path )[ "assistant_text" ] == ""

    def test_an_assistant_message_with_null_content_is_tolerated( self, tmp_path ):
        path = self._write_stream( tmp_path, [ { "type": "assistant", "message": { "content": None } } ] )
        assert mod._parse_stream( path )[ "assistant_text" ] == ""

    def test_rate_limit_events_are_retained_for_the_log( self, tmp_path ):
        path = self._write_stream( tmp_path, [
            { "type": "rate_limit_event", "rate_limit_info": { "status": "allowed_warning" } },
        ] )
        assert mod._parse_stream( path )[ "rate_limit_info" ] == { "status": "allowed_warning" }

    def test_the_result_event_is_retained_whole( self, tmp_path ):
        result  = { "type": "result", "subtype": "success", "is_error": False, "num_turns": 3 }
        path    = self._write_stream( tmp_path, [ result ] )
        assert mod._parse_stream( path )[ "result" ] == result

    def test_an_unknown_event_type_is_ignored_but_still_counted( self, tmp_path ):
        path    = self._write_stream( tmp_path, [ { "type": "user", "message": "hi" } ] )
        summary = mod._parse_stream( path )

        assert summary[ "raw_event_count" ] == 1
        assert summary[ "result" ] is None


# ────────────────────────────────────────────────────────────────────────
# _append_to_execution_log
# ────────────────────────────────────────────────────────────────────────

class TestAppendToExecutionLog:

    def test_a_missing_log_is_created_rather_than_raising( self, redirected_execution_log, capsys ):
        assert not redirected_execution_log.exists()
        mod._append_to_execution_log( "### section" )

        assert redirected_execution_log.read_text() == "\n\n### section\n"
        assert "Execution log updated" in capsys.readouterr().out

    def test_an_existing_log_is_appended_to_rather_than_overwritten( self, redirected_execution_log ):
        """The read-modify-write is the whole reason the autouse redirect exists — this is the
        behaviour that would eat a tracked design doc if it ran unguarded."""
        redirected_execution_log.write_text( "# Existing doc\n\nBody.\n" )
        mod._append_to_execution_log( "### new section" )

        text = redirected_execution_log.read_text()
        assert text.startswith( "# Existing doc\n\nBody." )
        assert text.endswith( "### new section\n" )

    def test_trailing_whitespace_is_normalised_to_one_blank_line_between_sections( self, redirected_execution_log ):
        redirected_execution_log.write_text( "Body.\n\n\n\n" )
        mod._append_to_execution_log( "### new section\n\n\n" )
        assert redirected_execution_log.read_text() == "Body.\n\n### new section\n"


# ────────────────────────────────────────────────────────────────────────
# _format_execution_section
# ────────────────────────────────────────────────────────────────────────

def _summary( **overrides ):
    base = {
        "api_key_source"  : "none",
        "model"           : "claude-sonnet-4-6",
        "result"          : { "subtype": "success", "is_error": False, "num_turns": 4,
                              "duration_ms": 1234, "total_cost_usd": 0.5 },
        "assistant_text"  : "text",
        "tool_use_count"  : 2,
        "tool_use_names"  : [ "Read", "Grep" ],
        "rate_limit_info" : None,
        "raw_event_count" : 9,
        "parse_errors"    : 0,
    }
    base.update( overrides )
    return base


_DEFAULT = object()   # distinct from None, which is a MEANINGFUL value for `parsed`


def _section( summary=None, parsed=_DEFAULT, validation_ok=True, validation_issues=None,
              fallback_used=False, exit_code=0 ):
    return mod._format_execution_section(
        summary           = _summary() if summary is None else summary,
        parsed            = { "root_cause": "off-by-five" } if parsed is _DEFAULT else parsed,
        validation_ok     = validation_ok,
        validation_issues = [] if validation_issues is None else validation_issues,
        fallback_used     = fallback_used,
        exit_code         = exit_code,
        stream_path       = Path( "/tmp/stream.jsonl" ),
        prompt_size       = 4096,
    )


class TestFormatExecutionSection:

    def test_a_clean_run_reports_its_metadata_and_a_pass_verdict( self ):
        text = _section()

        assert "- Prompt size: 4096 bytes" in text
        assert f"- Container: `{mod.CONTAINER}`" in text
        assert f"- Max turns: {mod.MAX_TURNS}" in text
        assert "- Stream-json dump: `/tmp/stream.jsonl`" in text
        assert "- Exit code: `0`" in text
        assert "- apiKeySource: `none`" in text
        assert "- Raw event count: 9" in text
        assert "- Result subtype: `success`" in text
        assert "- num_turns: `4`" in text
        assert "**Verdict**: ✅ PASS" in text

    def test_a_primary_parse_is_labelled_primary_and_the_payload_is_embedded_as_json( self ):
        text = _section()
        assert "- Parse source: primary (fenced JSON)" in text
        assert "- Validation: PASS" in text
        assert '"root_cause": "off-by-five"' in text

    def test_a_fallback_parse_is_labelled_as_such( self ):
        """Which parser produced the payload is the finding the probe exists to record."""
        assert "- Parse source: fallback (regex)" in _section( fallback_used=True )

    def test_validation_failures_are_listed_line_by_line( self ):
        text = _section( validation_ok=False, validation_issues=[ "missing root_cause", "bad shape" ] )

        assert "- Validation: FAIL" in text
        assert "    - missing root_cause" in text
        assert "    - bad shape" in text
        assert "**Verdict**: ❌ FAIL" in text

    def test_missing_metadata_renders_as_a_question_mark_rather_than_none( self ):
        text = _section( summary=_summary( api_key_source=None, model=None ) )
        assert "- apiKeySource: `?`" in text
        assert "- Model used: `?`" in text

    def test_a_run_with_no_result_event_omits_the_result_block_entirely( self ):
        text = _section( summary=_summary( result=None ) )
        assert "- Result subtype:" not in text
        assert "**Verdict**: ❌ FAIL" in text

    def test_rate_limit_information_is_surfaced_when_present( self ):
        text = _section( summary=_summary( rate_limit_info={ "status": "allowed_warning" } ) )
        assert "- rate_limit_info: `{'status': 'allowed_warning'}`" in text

    def test_rate_limit_information_is_omitted_when_absent( self ):
        assert "rate_limit_info" not in _section()

    def test_a_total_parse_failure_says_so_and_dumps_the_assistant_tail( self ):
        """When both parsers miss, the tail is the only evidence of what the model actually said."""
        text = _section( summary=_summary( assistant_text="line one\nline two" ), parsed=None )

        assert "- Both primary + fallback parsers failed." in text
        assert "- Assistant text tail (last 2000 chars):" in text
        assert "  line one" in text
        assert "  line two" in text

    def test_the_tail_is_capped_at_two_thousand_characters( self ):
        text = _section( summary=_summary( assistant_text="X" * 2500 ), parsed=None )
        assert "  " + "X" * 2000 in text
        assert "X" * 2001 not in text

    def test_a_parse_failure_with_no_assistant_text_omits_the_tail_block( self ):
        text = _section( summary=_summary( assistant_text="" ), parsed=None )

        assert "- Both primary + fallback parsers failed." in text
        assert "Assistant text tail" not in text

    def test_a_nonzero_exit_code_fails_the_verdict( self ):
        assert "**Verdict**: ❌ FAIL" in _section( exit_code=1 )

    def test_an_api_key_source_other_than_none_fails_the_verdict( self ):
        """A key source that is not 'none' means the run was billed, which is the failure the
        whole probe was built to detect."""
        assert "**Verdict**: ❌ FAIL" in _section( summary=_summary( api_key_source="ANTHROPIC_API_KEY" ) )

    def test_an_errored_result_fails_the_verdict( self ):
        result = { "subtype": "success", "is_error": True, "num_turns": 4 }
        assert "**Verdict**: ❌ FAIL" in _section( summary=_summary( result=result ) )

    def test_a_non_success_subtype_fails_the_verdict( self ):
        result = { "subtype": "error_max_turns", "is_error": False, "num_turns": 4 }
        assert "**Verdict**: ❌ FAIL" in _section( summary=_summary( result=result ) )

    def test_an_unparsed_payload_fails_the_verdict( self ):
        assert "**Verdict**: ❌ FAIL" in _section( parsed=None )

    def test_a_run_that_burns_the_whole_turn_budget_fails_the_verdict( self ):
        """The cap is strict: reaching MAX_TURNS means the model ran out of room, not that it
        finished. A `<=` here would call a truncated run a pass."""
        result = { "subtype": "success", "is_error": False, "num_turns": mod.MAX_TURNS }
        assert "**Verdict**: ❌ FAIL" in _section( summary=_summary( result=result ) )

    def test_one_turn_under_the_cap_still_passes( self ):
        result = { "subtype": "success", "is_error": False, "num_turns": mod.MAX_TURNS - 1 }
        assert "**Verdict**: ✅ PASS" in _section( summary=_summary( result=result ) )

    def test_a_missing_turn_count_is_read_as_zero_rather_than_raising( self ):
        result = { "subtype": "success", "is_error": False, "num_turns": None }
        assert "**Verdict**: ✅ PASS" in _section( summary=_summary( result=result ) )

    def test_the_section_is_headed_by_a_dated_title_naming_the_model( self ):
        first = _section().splitlines()[ 0 ]
        assert first.startswith( "### " )
        assert f"model={mod.MODEL}" in first


# ────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def wired_main( monkeypatch ):
    """Wire main()'s collaborators to in-memory stand-ins. Nothing here touches Docker."""
    calls = { "prompt_written": [], "claude_run": [], "appended": [] }

    monkeypatch.setattr( mod, "build_diagnosis_bundle_prompt", lambda clusters, failure_context: "PROMPT" )

    def _fake_write( container, host_scratch, prompt ):
        calls[ "prompt_written" ].append( ( container, prompt ) )
        return "/tmp/prompt.md"

    def _fake_run_claude( container, prompt_path, stream_out, stderr_out ):
        calls[ "claude_run" ].append( ( container, prompt_path ) )
        return 0

    monkeypatch.setattr( mod, "_write_prompt_to_container", _fake_write )
    monkeypatch.setattr( mod, "_run_claude_p", _fake_run_claude )
    monkeypatch.setattr( mod, "_append_to_execution_log", lambda section: calls[ "appended" ].append( section ) )
    monkeypatch.setattr( mod, "_parse_stream", lambda path: _summary( assistant_text="DIAGNOSIS" ) )
    monkeypatch.setattr( mod, "parse_diagnosis_block", lambda text: { "root_cause": "off-by-five" } )
    monkeypatch.setattr( mod, "parse_diagnosis_fallback", lambda text: None )
    monkeypatch.setattr( mod, "validate_diagnosis_payload", lambda payload: ( True, [] ) )
    return calls


class TestMain:

    def test_a_clean_run_returns_zero( self, wired_main, capsys ):
        assert mod.main() == 0

    def test_it_builds_the_prompt_from_the_c6_cluster_and_ships_it_to_the_test_container( self, wired_main, monkeypatch ):
        seen = {}
        monkeypatch.setattr( mod, "build_diagnosis_bundle_prompt",
                             lambda clusters, failure_context: seen.update( clusters=clusters, ctx=failure_context ) or "PROMPT" )
        mod.main()

        assert seen[ "clusters" ] == [ mod.CLUSTER_C6 ]
        assert "source_suite" in seen[ "ctx" ]
        assert wired_main[ "prompt_written" ] == [ ( mod.CONTAINER, "PROMPT" ) ]
        assert wired_main[ "claude_run" ]     == [ ( mod.CONTAINER, "/tmp/prompt.md" ) ]

    def test_it_appends_exactly_one_section_to_the_execution_log( self, wired_main ):
        mod.main()
        assert len( wired_main[ "appended" ] ) == 1
        assert wired_main[ "appended" ][ 0 ].startswith( "### " )

    def test_it_prints_the_run_summary_including_the_result_fields( self, wired_main, capsys ):
        mod.main()
        out = capsys.readouterr().out

        assert "apiKeySource      : 'none'" in out
        assert "tool_use_count    : 2" in out
        assert "result.subtype    : 'success'" in out
        assert "result.num_turns  : 4" in out
        assert "parser_used       : primary" in out
        assert "validation_ok     : True" in out

    def test_the_fallback_parser_is_tried_only_when_the_primary_returns_nothing( self, wired_main, monkeypatch, capsys ):
        tried = []
        monkeypatch.setattr( mod, "parse_diagnosis_block", lambda text: tried.append( "primary" ) or None )
        monkeypatch.setattr( mod, "parse_diagnosis_fallback", lambda text: tried.append( "fallback" ) or { "root_cause": "x" } )

        assert mod.main() == 0
        assert tried == [ "primary", "fallback" ]
        assert "parser_used       : fallback" in capsys.readouterr().out

    def test_a_successful_primary_parse_never_reaches_the_fallback( self, wired_main, monkeypatch, capsys ):
        """The guard itself, asserted in the direction that actually exercises it. Its sibling
        above only pins the ORDER once the primary has already failed, which is true whether the
        `if parsed is None` guard is there or not — a mutation to `if True` survives that test and
        is caught here, because running the fallback over a good primary parse THROWS THE GOOD
        PARSE AWAY."""
        tried = []
        monkeypatch.setattr( mod, "parse_diagnosis_block", lambda text: tried.append( "primary" ) or { "root_cause": "x" } )
        monkeypatch.setattr( mod, "parse_diagnosis_fallback", lambda text: tried.append( "fallback" ) or None )

        assert mod.main() == 0
        assert tried == [ "primary" ]
        assert "parser_used       : primary" in capsys.readouterr().out

    def test_when_both_parsers_miss_the_run_fails_and_says_so( self, wired_main, monkeypatch, capsys ):
        monkeypatch.setattr( mod, "parse_diagnosis_block", lambda text: None )
        monkeypatch.setattr( mod, "parse_diagnosis_fallback", lambda text: None )
        monkeypatch.setattr( mod, "validate_diagnosis_payload", lambda payload: ( False, [ "no payload" ] ) )

        assert mod.main() == 1
        out = capsys.readouterr().out
        assert "validation_issues :" in out
        assert "  - no payload" in out

    def test_a_run_with_no_result_event_skips_the_result_lines_and_fails( self, wired_main, monkeypatch, capsys ):
        monkeypatch.setattr( mod, "_parse_stream", lambda path: _summary( result=None ) )

        assert mod.main() == 1
        assert "result.subtype" not in capsys.readouterr().out

    def test_a_billed_run_fails_even_when_everything_else_is_clean( self, wired_main, monkeypatch ):
        monkeypatch.setattr( mod, "_parse_stream", lambda path: _summary( api_key_source="ANTHROPIC_API_KEY" ) )
        assert mod.main() == 1

    def test_a_nonzero_claude_exit_fails_the_run( self, wired_main, monkeypatch ):
        monkeypatch.setattr( mod, "_run_claude_p", lambda *a, **k: 1 )
        assert mod.main() == 1

    def test_a_non_success_result_subtype_fails_the_run( self, wired_main, monkeypatch ):
        """⚠️ THE SUBTYPE IS THE ONLY THING WRONG HERE, DELIBERATELY.

        This payload used to read {"subtype": "error_max_turns", "is_error": True,
        "num_turns": 20} — which fails for THREE independent reasons at once. A mutation
        REMOVING the subtype check survived it: the run still failed on the other two, so the
        test could not tell which criterion did the work, whatever its name said.

        is_error is False and the turn count is well under the cap, so the subtype is the sole
        cause and removing its check now reddens this test. Keep it isolated for that reason."""
        monkeypatch.setattr( mod, "_parse_stream",
                             lambda path: _summary( result={ "subtype": "error_max_turns", "is_error": False, "num_turns": 4 } ) )
        assert mod.main() == 1

    def test_a_failed_validation_fails_the_run( self, wired_main, monkeypatch ):
        monkeypatch.setattr( mod, "validate_diagnosis_payload", lambda payload: ( False, [] ) )
        assert mod.main() == 1


# ────────────────────────────────────────────────────────────────────────
# The defect that WAS pinned here — now fixed (bug c2ee8c96)
# ────────────────────────────────────────────────────────────────────────

class TestTheTwoVerdictsAgree:
    """These are the AGREEING COUNTERPARTS of two tests that used to pin a defect.

    Until bug c2ee8c96 was fixed, the script computed its verdict TWICE against different
    criteria: `_format_execution_section` (what gets WRITTEN to the log) applied `is_error`
    and the turn-budget cap, `main` (what becomes the EXIT CODE) applied neither. So an
    unattended run could write ❌ FAIL into the execution log and still exit 0 — and the
    exit code is the half automation reads.

    Two tests named `_pins_a_defect_` asserted that WRONG behaviour on purpose so the next
    reader met a name rather than an unexplained green. Their docstring said that on the fix
    they must be REPLACED by their agreeing counterparts rather than patched green. This
    class is that replacement, and these two cases are the two that used to diverge.

    The fix was one shared predicate — `_run_passed` — read by both sites. Restating the
    criteria is what let them drift apart, so a third restatement here would be the same bug
    waiting; that is why these tests assert the two ANSWERS agree rather than re-listing the
    criteria."""

    def test_a_turn_budget_burn_fails_the_exit_code_and_the_log_together( self, wired_main, monkeypatch ):
        result = { "subtype": "success", "is_error": False, "num_turns": mod.MAX_TURNS }
        monkeypatch.setattr( mod, "_parse_stream", lambda path: _summary( result=result ) )

        assert mod.main() == 1
        assert "**Verdict**: ❌ FAIL" in _section( summary=_summary( result=result ) )

    def test_an_errored_result_fails_the_exit_code_and_the_log_together( self, wired_main, monkeypatch ):
        result = { "subtype": "success", "is_error": True, "num_turns": 4 }
        monkeypatch.setattr( mod, "_parse_stream", lambda path: _summary( result=result ) )

        assert mod.main() == 1
        assert "**Verdict**: ❌ FAIL" in _section( summary=_summary( result=result ) )

    def test_a_clean_run_passes_both( self, wired_main, monkeypatch ):
        """The control. Without it the pair above would be satisfied by a predicate that
        simply fails everything."""
        result = { "subtype": "success", "is_error": False, "num_turns": 4 }
        monkeypatch.setattr( mod, "_parse_stream", lambda path: _summary( result=result ) )

        assert mod.main() == 0
        assert "**Verdict**: ✅ PASS" in _section( summary=_summary( result=result ) )

    def test_one_predicate_backs_both_verdicts( self, wired_main, monkeypatch ):
        """Pins the SHAPE of the fix, not just its effect: both sites must call `_run_passed`.
        If someone re-inlines either one, the two can drift apart again silently and every
        other test here would still pass."""
        calls = []
        real  = mod._run_passed
        monkeypatch.setattr( mod, "_run_passed",
                             lambda *a, **k: calls.append( 1 ) or real( *a, **k ) )

        mod.main()
        assert len( calls ) >= 2, "main and the logged section must BOTH consult _run_passed"


# ────────────────────────────────────────────────────────────────────────
# The __main__ guard
# ────────────────────────────────────────────────────────────────────────

class TestMainGuard:

    def test_running_the_script_as_main_exits_with_the_verdict_code( self, monkeypatch, tmp_path ):
        """The `if __name__ == "__main__"` tail cannot be reached by importing, so this is the one
        place runpy is right — it re-executes the REAL file under the real filename, so coverage
        still attributes to the file under test.

        A fresh execution binds its own names, so the stand-ins go on the SOURCE modules rather
        than on `mod`: the re-executed script imports them at its own import time and picks up
        whatever is there. `Path.write_text` is patched for the duration because the fresh module
        recomputes EXECUTION_LOG from `__file__` — the autouse redirect applies to `mod`, not to
        a second copy of it, and without this the run would append to the tracked design doc."""
        from cosa.agents.tfe_to_cc.prompts import bundle_phase1, output_contract

        writes = []
        monkeypatch.setattr( subprocess, "run", lambda *a, **k: _FakeProc( returncode=0 ) )
        monkeypatch.setattr( bundle_phase1, "build_diagnosis_bundle_prompt", lambda **kw: "PROMPT" )
        monkeypatch.setattr( output_contract, "parse_diagnosis_block", lambda text: None )
        monkeypatch.setattr( output_contract, "parse_diagnosis_fallback", lambda text: None )
        monkeypatch.setattr( output_contract, "validate_diagnosis_payload", lambda payload: ( False, [ "stubbed" ] ) )
        monkeypatch.setattr( Path, "write_text", lambda self, data, **kw: writes.append( ( self, data ) ) )

        with pytest.raises( SystemExit ) as excinfo:
            runpy.run_path( mod.__file__, run_name="__main__" )

        assert excinfo.value.code == 1
        assert any( str( target ).endswith( "20-tfe-to-cc-phase1-live-test.md" ) for target, _ in writes )

    def test_importing_the_script_does_not_run_it( self ):
        """The counterpart to the test above: the guard must stay shut on import, or every test
        in this file would shell out to Docker at collection time."""
        source = Path( mod.__file__ ).read_text()
        assert 'if __name__ == "__main__":' in source
        assert mod.__name__ == "tfe_to_cc_phase1_smoke"
