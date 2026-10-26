"""Unit tests for the docker and stream half of the TFE-to-CC live harness.

The artifact tests cover the pure functions. This file covers the calls that shell out to
`docker exec`, the stream-json reader, the notification post and main().

The docker boundary is a fake subprocess.run that answers by command shape and records every call.
Assertions read the recorded commands and the files the harness wrote.
A harness that sent the wrong command fails here.

The stream-json the fake emits follows the event shapes `_parse_stream` documents.
It is hand-written, not captured from a real `claude -p` run. This file cannot close that gap.

Nothing touches docker, the network or /tmp: Path("/tmp") inside main() is sent to tmp_path.
"""

import importlib.util
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

_HARNESS_PATH = Path( __file__ ).resolve().parent.parent.parent / "scripts" / "tfe_to_cc_phase3_live.py"


@pytest.fixture
def harness( tmp_path, monkeypatch ):
    spec = importlib.util.spec_from_file_location( "tfe_to_cc_phase3_live_io", _HARNESS_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    monkeypatch.setattr( mod, "EXECUTION_LOG", tmp_path / "exec-log.md" )
    return mod


class FakeDocker:
    """A subprocess.run replacement that answers by command shape and records every call."""

    def __init__( self, stream_lines=(), git_log="", diff_stat="", worktree_rc=0, write_rc=0, claude_rc=0, claude_timeout=False ):
        self.calls          = []
        self.stream_lines   = list( stream_lines )
        self.git_log        = git_log
        self.diff_stat      = diff_stat
        self.worktree_rc    = worktree_rc
        self.write_rc       = write_rc
        self.claude_rc      = claude_rc
        self.claude_timeout = claude_timeout

    def __call__( self, cmd, **kw ):
        self.calls.append( { "cmd": cmd, **kw } )
        script = cmd[ -1 ] if isinstance( cmd[ -1 ], str ) else ""
        if "git worktree add" in script:
            return subprocess.CompletedProcess( cmd, self.worktree_rc, stdout="", stderr="boom" if self.worktree_rc else "" )
        if cmd[ 2 ] == "-i":
            return subprocess.CompletedProcess( cmd, self.write_rc, stdout=b"", stderr=b"denied" if self.write_rc else b"" )
        if "claude -p" in script:
            if self.claude_timeout: raise subprocess.TimeoutExpired( cmd, kw.get( "timeout" ) )
            kw[ "stdout" ].write( ( "\n".join( self.stream_lines ) + "\n" ).encode() )
            kw[ "stderr" ].write( b"some stderr\n" )
            return subprocess.CompletedProcess( cmd, self.claude_rc )
        if "git log --oneline" in script:
            return subprocess.CompletedProcess( cmd, 0, stdout=self.git_log, stderr="" )
        if "git diff --stat" in script:
            return subprocess.CompletedProcess( cmd, 0, stdout=self.diff_stat, stderr="" )
        raise AssertionError( f"unexpected command: {cmd}" )

    def find( self, needle ):
        return [ c for c in self.calls if needle in ( c[ "cmd" ][ -1 ] if isinstance( c[ "cmd" ][ -1 ], str ) else "" ) ]


def _install( harness, monkeypatch, docker ):
    monkeypatch.setattr( harness.subprocess, "run", docker )
    return docker


def _result_block( clusters ):
    return "All done.\n```tfe-result\n" + json.dumps( { "clusters": clusters } ) + "\n```\n"


def _stream( text="", model="claude-sonnet-4-6", tools=( "Edit", "Edit", "Bash" ), result=None ):
    events = [ json.dumps( { "type": "system", "subtype": "init", "apiKeySource": "none", "model": model } ),
               json.dumps( { "type": "rate_limit_event", "rate_limit_info": { "status": "allowed" } } ) ]
    content = [ { "type": "text", "text": text } ] + [ { "type": "tool_use", "name": n } for n in tools ]
    events.append( json.dumps( { "type": "assistant", "message": { "content": content } } ) )
    events.append( json.dumps( { "type": "result", **( result or { "subtype": "success", "is_error": False, "num_turns": 7, "duration_ms": 90000, "total_cost_usd": 1.5 } ) } ) )
    return events


# ── small helpers ───────────────────────────────────────────────────────────────

def test_ts_is_a_utc_compact_timestamp( harness ):
    assert re.fullmatch( r"\d{8}T\d{6}Z", harness._ts() )


def test_banner_frames_the_title_with_72_equals( harness, capsys ):
    harness._banner( "HELLO" )
    lines = capsys.readouterr().out.splitlines()
    assert lines == [ "", "=" * 72, "  HELLO", "=" * 72 ]


# ── _create_smoke_worktree ──────────────────────────────────────────────────────

def test_create_worktree_runs_git_worktree_add_in_the_container_and_returns_its_path( harness, monkeypatch, capsys ):
    docker = _install( harness, monkeypatch, FakeDocker() )
    path   = harness._create_smoke_worktree()
    assert re.fullmatch( r"/var/lupin/\.claude/worktrees/phase3-live-\d{8}T\d{6}Z", path )
    cmd = docker.calls[ 0 ][ "cmd" ]
    assert cmd[ :3 ] == [ "docker", "exec", "lupin-rest-test" ]
    assert cmd[ -1 ] == f"cd /var/lupin && git worktree add {path} origin/main"
    assert f"Worktree created: {path}" in capsys.readouterr().out


def test_create_worktree_failure_raises_with_the_exit_code_and_stderr( harness, monkeypatch ):
    _install( harness, monkeypatch, FakeDocker( worktree_rc=128 ) )
    with pytest.raises( RuntimeError, match=r"rc=128.*stderr='boom'" ):
        harness._create_smoke_worktree()


# ── _write_prompt_to_container ──────────────────────────────────────────────────

def test_write_prompt_pipes_the_prompt_in_and_keeps_a_host_copy( harness, monkeypatch, tmp_path ):
    docker = _install( harness, monkeypatch, FakeDocker() )
    container_path, host_path = harness._write_prompt_to_container( "héllo prompt", tmp_path )
    sent = docker.calls[ 0 ]
    assert sent[ "input" ] == "héllo prompt".encode( "utf-8" )
    assert sent[ "cmd" ][ -1 ] == f"cat > {container_path}"
    assert host_path.parent == tmp_path and host_path.read_text() == "héllo prompt"
    assert container_path.startswith( "/tmp/tfe_to_cc_phase3_prompt_" )


def test_write_prompt_failure_raises_and_leaves_no_host_copy( harness, monkeypatch, tmp_path ):
    _install( harness, monkeypatch, FakeDocker( write_rc=1 ) )
    with pytest.raises( RuntimeError, match="Failed to write prompt to container" ):
        harness._write_prompt_to_container( "p", tmp_path )
    assert list( tmp_path.iterdir() ) == []


# ── _invoke_claude_p ────────────────────────────────────────────────────────────

def _invoke( harness, tmp_path, **kw ):
    args = dict( container_prompt_path="/tmp/p.md", worktree_path="/wt", stream_out=tmp_path / "s.jsonl",
                 stderr_out=tmp_path / "e.log", model="m-x", effort="high", max_budget_usd=None )
    args.update( kw )
    return harness._invoke_claude_p( **args )


def test_invoke_builds_the_full_flag_set_and_streams_to_the_given_files( harness, monkeypatch, tmp_path, capsys ):
    docker = _install( harness, monkeypatch, FakeDocker( stream_lines=[ "EVENT" ], claude_rc=0 ) )
    rc = _invoke( harness, tmp_path, effort="max", max_budget_usd=2.5 )
    assert rc == 0
    cmd = docker.calls[ 0 ][ "cmd" ]
    assert cmd[ :5 ] == [ "docker", "exec", "-w", "/wt", "lupin-rest-test" ]
    shell = cmd[ -1 ]
    assert 'claude -p "$(cat /tmp/p.md)"' in shell
    for flag in ( "--model m-x", "--output-format stream-json", "--verbose", f"--max-turns {harness.MAX_TURNS}",
                  "--effort max", "--max-budget-usd 2.5", "--allowedTools", "--disallowedTools" ):
        assert flag in shell, flag
    assert docker.calls[ 0 ][ "timeout" ] == harness.WALL_CLOCK_LIMIT
    assert ( tmp_path / "s.jsonl" ).read_text() == "EVENT\n"
    assert ( tmp_path / "e.log" ).read_text() == "some stderr\n"
    out = capsys.readouterr().out
    assert "effort=max" in out and "budget=$2.5" in out and "Exit code 0" in out


def test_invoke_omits_effort_when_none_and_budget_when_unset( harness, monkeypatch, tmp_path, capsys ):
    docker = _install( harness, monkeypatch, FakeDocker( claude_rc=3 ) )
    rc = _invoke( harness, tmp_path, effort="none" )
    assert rc == 3, "the claude exit code must be returned, not swallowed"
    shell = docker.calls[ 0 ][ "cmd" ][ -1 ]
    assert "--effort" not in shell and "--max-budget-usd" not in shell
    out = capsys.readouterr().out
    assert "effort=" not in out and "budget=" not in out


def test_invoke_returns_minus_one_on_timeout( harness, monkeypatch, tmp_path, capsys ):
    _install( harness, monkeypatch, FakeDocker( claude_timeout=True ) )
    assert _invoke( harness, tmp_path ) == -1
    assert f"TIMEOUT after {harness.WALL_CLOCK_LIMIT}s" in capsys.readouterr().out


# ── _parse_stream ───────────────────────────────────────────────────────────────

def test_parse_stream_summarises_a_realistic_event_stream( harness, tmp_path ):
    lines = _stream( text="first" ) + [
        "", "   ",                                              # blank lines are not events
        "not json at all",                                      # counted as a parse error, not a crash
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text", "text": "second" },
                                                                    { "type": "tool_use" },
                                                                    { "type": "thinking", "thinking": "hmm" } ] } } ),
        json.dumps( { "type": "assistant", "message": None } ),
        json.dumps( { "type": "assistant", "message": { "content": None } } ),
        json.dumps( { "type": "user" } ),                       # an event type it ignores
    ]
    path = tmp_path / "s.jsonl"
    path.write_text( "\n".join( lines ) + "\n" )
    summary = harness._parse_stream( path )
    assert summary[ "api_key_source" ] == "none" and summary[ "model" ] == "claude-sonnet-4-6"
    assert summary[ "assistant_text" ] == "first\nsecond"
    assert summary[ "tool_use_count" ] == 4
    assert summary[ "tool_use_names" ] == { "Edit": 2, "Bash": 1, "?": 1 }
    assert summary[ "rate_limit_info" ] == { "status": "allowed" }
    assert summary[ "result" ][ "num_turns" ] == 7
    assert summary[ "parse_errors" ] == 1
    assert summary[ "raw_event_count" ] == 9


def test_parse_stream_of_an_empty_file_is_all_zero( harness, tmp_path ):
    path = tmp_path / "s.jsonl"
    path.write_text( "" )
    summary = harness._parse_stream( path )
    assert summary[ "raw_event_count" ] == 0 and summary[ "result" ] is None and summary[ "assistant_text" ] == ""


# ── git readers ─────────────────────────────────────────────────────────────────

def test_git_readers_return_stdout_on_success_and_empty_on_failure( harness, monkeypatch ):
    docker = _install( harness, monkeypatch, FakeDocker( git_log="abc1234 subj\n", diff_stat=" a | 1 +\n" ) )
    assert harness._git_log_worktree( "/wt" ) == "abc1234 subj\n"
    assert harness._git_diff_stat( "/wt" )    == " a | 1 +\n"
    assert docker.calls[ 0 ][ "cmd" ][ -1 ] == "cd /wt && git log --oneline origin/main..HEAD 2>&1"
    assert docker.calls[ 1 ][ "cmd" ][ -1 ] == "cd /wt && git diff --stat origin/main 2>&1"

    failing = lambda cmd, **kw: subprocess.CompletedProcess( cmd, 1, stdout="fatal: bad revision", stderr="" )
    monkeypatch.setattr( harness.subprocess, "run", failing )
    assert harness._git_log_worktree( "/wt" ) == ""
    assert harness._git_diff_stat( "/wt" )    == ""


# ── markdown renderer branches the artifact tests do not reach ──────────────────

def _changes( **over ):
    base = { "run_id": "r1", "started_at": "s", "ended_at": "e", "duration_s": 1.0, "model": "m-a",
             "model_reported": None, "effort": "high", "max_budget_usd": None, "worktree": "/wt", "exit_code": 0,
             "validation_ok": True, "validation_issues": [],
             "overall": { "clusters_total": 1, "fixed": 1, "already_clean": 0, "unclear": 0, "failed": 0, "unknown": 0 },
             "clusters": [], "worktree_commits": [], "git_diffstat": "", "possibly_leaked_to_submodules": {} }
    base.update( over )
    return base


def _row( cid, pytest_passed ):
    return { "id": cid, "verdict": "fixed", "commit_sha": "abc1234", "files": [ "a.py" ], "pytest_passed": pytest_passed }


def test_render_md_shows_each_pytest_state_the_reported_model_the_diffstat_and_the_issues( harness ):
    md = harness._render_changes_md( _changes(
        model_reported="m-b", max_budget_usd=3.0, git_diffstat=" a.py | 2 +-",
        validation_issues=[ "cluster 'C1': missing verdict" ],
        clusters=[ _row( "C1", True ), _row( "C2", False ), _row( "C3", None ) ] ) )
    assert "- **Model**: `m-a` (reported: `m-b`)" in md
    assert "- **Max budget**: $3.0" in md
    assert "| **C1** | `fixed` | `abc1234` | `a.py` | ✓ |" in md
    assert "| **C2** | `fixed` | `abc1234` | `a.py` | ✗ |" in md
    assert "| **C3** | `fixed` | `abc1234` | `a.py` | — |" in md
    assert "## Worktree diffstat vs origin/main\n\n```\n a.py | 2 +-\n```" in md
    assert "## Validation issues\n\n- cluster 'C1': missing verdict" in md


def test_render_md_omits_optional_sections_and_reported_suffix_when_there_is_nothing_to_say( harness ):
    md = harness._render_changes_md( _changes( model_reported="m-a" ) )
    assert "reported:" not in md and "- **Max budget**: none" in md
    for heading in ( "## Worktree commits", "## Worktree diffstat", "## Validation issues", "Possibly leaked" ):
        assert heading not in md


# ── execution log ───────────────────────────────────────────────────────────────

def test_append_creates_the_log_with_its_header_then_appends_below_it( harness, capsys ):
    log = harness.EXECUTION_LOG
    assert not log.exists()
    harness._append_to_execution_log( "first section\n\n" )
    created = log.read_text()
    assert created.startswith( "# 21 — TFE-to-CC Phase 3 (Apply Fixes) — Live Test Execution Log" )
    assert created.endswith( "---\n\nfirst section\n" )

    harness._append_to_execution_log( "second section" )
    assert log.read_text() == created.rstrip() + "\n\nsecond section\n"
    assert f"Execution log: {log}" in capsys.readouterr().out


# ── notification ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__( self, body ): self._body = body
    def read( self ): return self._body


def test_notify_logs_in_then_posts_the_message_with_the_bearer_token( harness, monkeypatch, capsys ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "t@example.com" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    sent = []
    def fake_urlopen( req, timeout=None ):
        sent.append( req )
        return _Resp( json.dumps( { "tokens": { "access_token": "TOK" } } ).encode() )
    monkeypatch.setattr( "urllib.request.urlopen", fake_urlopen )

    harness._send_high_priority_notify( "msg & more", "abs" )

    login, notify = sent
    assert login.full_url == "http://localhost:8000/auth/login"
    assert json.loads( login.data ) == { "email": "t@example.com", "password": "pw" }
    assert notify.full_url.startswith( "http://localhost:8000/api/notify?" )
    assert "message=msg+%26+more" in notify.full_url and "priority=urgent" in notify.full_url
    assert "target_user=t%40example.com" in notify.full_url
    assert notify.get_method() == "POST" and notify.get_header( "Authorization" ) == "Bearer TOK"
    assert "High-priority notification sent." in capsys.readouterr().out


def test_notify_failure_is_reported_not_raised( harness, monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", raising=False )
    harness._send_high_priority_notify( "m", "a" )                 # must not raise
    assert "Notification send failed" in capsys.readouterr().out


# ── main() ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def run_main( harness, monkeypatch, tmp_path ):
    """Drive main() with docker faked, /tmp sent to tmp_path and notify captured."""
    real_path = harness.Path
    monkeypatch.setattr( harness, "Path", lambda p: tmp_path if p == "/tmp" else real_path( p ) )
    monkeypatch.setattr( sys, "argv", [ "phase3" ] )
    notified = []
    monkeypatch.setattr( harness, "_send_high_priority_notify", lambda m, a: notified.append( ( m, a ) ) )

    def go( docker, *argv ):
        _install( harness, monkeypatch, docker )
        monkeypatch.setattr( sys, "argv", [ "phase3", *argv ] )
        rc = harness.main()
        return rc, notified
    go.tmp = tmp_path
    return go


def _only( paths ):
    assert len( paths ) == 1, paths
    return paths[ 0 ]


def test_main_primary_parser_path_returns_0_and_writes_every_artifact( harness, run_main, capsys ):
    block = _result_block( { "C1": { "verdict": "fixed", "commit_sha": "abc1234", "files": [ "src/cosa/x.py" ], "pytest_passed": True },
                             "C2": { "verdict": "unclear", "commit_sha": None } } )
    docker = FakeDocker( stream_lines=_stream( text=block ), git_log="abc1234 fix(tfe): C1 x\n", diff_stat=" x | 1 +\n" )

    rc, notified = run_main( docker, "--model", "opus", "--effort", "none", "--max-budget-usd", "4" )

    assert rc == 0
    shell = _only( docker.find( "claude -p" ) )[ "cmd" ][ -1 ]
    assert "--model opus" in shell and "--effort" not in shell and "--max-budget-usd 4.0" in shell

    changes = json.loads( _only( list( run_main.tmp.glob( "tfe-to-cc-changes-*.json" ) ) ).read_text() )
    assert changes[ "overall" ] == { "clusters_total": len( harness.SELECTED_FIXES ), "fixed": 1, "already_clean": 0,
                                     "unclear": 1, "failed": 0, "unknown": len( harness.SELECTED_FIXES ) - 2 }
    assert changes[ "possibly_leaked_to_submodules" ] == { "src/cosa/": [ "C1" ] }
    assert changes[ "model" ] == "opus" and changes[ "model_reported" ] == "claude-sonnet-4-6"
    assert changes[ "worktree_commits" ] == [ { "sha": "abc1234", "subject": "fix(tfe): C1 x" } ]

    log = harness.EXECUTION_LOG.read_text()
    assert "Parser: primary (tfe-result fence)" in log and "**Verdict**: **1 / 11 fixes landed**" in log
    assert "result.num_turns (coordinator): `7`" in log and "| budget: `$4.0`" in log
    assert "```json" in log and "abc1234 fix(tfe): C1 x" in log and "x | 1 +" in log

    ( msg, abstract ), = notified
    assert msg == "TFE-to-CC Phase 3 complete: 1/11 fixes landed"
    assert "7 turns, 90s wall" in abstract
    out = capsys.readouterr().out
    assert "Parser: primary" in out and "Validation: OK" in out
    assert len( list( run_main.tmp.glob( "tfe_to_cc_phase3_prompt_*.md" ) ) ) == 1


def test_main_falls_back_to_the_git_log_when_the_result_block_is_missing( harness, run_main, capsys ):
    docker = FakeDocker( stream_lines=_stream( text="no fence here" ), git_log="def5678 fix(tfe): C2 added the label\n" )

    rc, _ = run_main( docker )

    assert rc == 0
    log = harness.EXECUTION_LOG.read_text()
    assert "Parser: fallback (git log)" in log and "**Verdict**: **1 / 11 fixes landed**" in log
    assert "Parser: fallback" in capsys.readouterr().out
    assert "(no diffs)" in log                                   # empty diffstat is named, not blank


def test_main_returns_1_when_nothing_landed_and_the_payload_cannot_be_parsed( harness, run_main, monkeypatch, capsys ):
    monkeypatch.setattr( harness, "parse_result_from_git_log", lambda *a, **k: None )
    docker = FakeDocker( stream_lines=[], git_log="" )

    rc, notified = run_main( docker )

    assert rc == 1
    log = harness.EXECUTION_LOG.read_text()
    assert "- Validation OK: False" in log
    assert "- Validation issues:\n    - payload is None (parse failed or block missing)" in log
    assert "Per-cluster verdicts" not in log and "(no commits)" in log
    assert "result.subtype: `None`" in log                       # no result event: every field reads None, none raise
    assert notified[ 0 ][ 0 ] == "TFE-to-CC Phase 3 complete: 0/11 fixes landed"
    assert "Validation: ISSUES" in capsys.readouterr().out


def test_main_returns_1_when_clusters_fixed_but_the_payload_is_invalid( harness, run_main ):
    # a 'fixed' cluster with no commit_sha: counted as fixed (1) yet validation fails, so exit is 1
    block = _result_block( { "C1": { "verdict": "fixed" } } )
    rc, _ = run_main( FakeDocker( stream_lines=_stream( text=block ) ) )
    assert rc == 1
    assert "verdict=fixed but commit_sha is missing" in harness.EXECUTION_LOG.read_text()
