"""
Tests for the commit scope guard.

The defect it installs a control for: `git commit` writes the WHOLE INDEX, and a
path-scoped pre-commit check cannot show you the contamination it exists to
catch. Measured 2026-08-25 — five files staged by name, four peer files
committed.
"""
import os

import pytest

from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
    commit_scope_deny_reason,
    build_commit_scope_deny_response,
    _blank_quoted_spans,
    _human_size,
    _size_of,
    _staged_paths,
    LARGE_FILE_BYTES,
)


def _reader( *paths ):
    """A staged_reader returning a fixed set."""
    return lambda cwd: list( paths )


def _bash( command ):
    return ( "Bash", { "command": command } )


# ── It fires on a real commit ────────────────────────────────────────────────

def test_plain_commit_is_denied_and_lists_the_whole_index():
    tool, payload = _bash( 'git commit -m "a message"' )

    reason = commit_scope_deny_reason( tool, payload, staged_reader=_reader( "mine.py", "theirs.py" ) )

    assert reason is not None
    assert "WHOLE INDEX" in reason
    assert "2 file(s) staged" in reason
    assert "mine.py" in reason
    assert "theirs.py" in reason


def test_the_reason_names_every_staged_path_not_a_summary():
    """The list IS the control — a count without names reproduces the defect."""
    paths = [ f"src/file_{i}.py" for i in range( 12 ) ]
    tool, payload = _bash( "git commit -F -" )

    reason = commit_scope_deny_reason( tool, payload, staged_reader=_reader( *paths ) )

    for path in paths:
        assert path in reason


def test_amend_is_denied_too():
    """--amend still writes the index, so it carries the same hazard."""
    tool, payload = _bash( "git commit --amend --no-edit" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is not None


@pytest.mark.parametrize( "command", [
    "git commit -m x",
    "/usr/bin/git commit -m x",
    "./git commit -m x",
    "cd /repo && git commit -m x",
    "sudo git commit -m x",
    "env git commit -m x",
    "GIT_AUTHOR_NAME=x git commit -m y",
    "git -C /repo commit -m x",
    "true; git commit -m x",
    "if true; then git commit -m x; fi",
] )
def test_natural_spellings_are_caught( command ):
    """Accident threat model: the forms people actually type."""
    tool, payload = _bash( command )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is not None


# ── It stays quiet when it should ────────────────────────────────────────────

def test_acknowledged_commit_passes():
    tool, payload = _bash( 'LUPIN_COMMIT_SCOPE_ACK=1 git commit -m "reviewed the index"' )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is None


@pytest.mark.parametrize( "value", [ "1", "true", "on", "yes", "TRUE" ] )
def test_every_truthy_ack_value_passes( value ):
    tool, payload = _bash( f"{ 'LUPIN_COMMIT_SCOPE_ACK' }={value} git commit -m x" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is None


def test_a_falsy_ack_does_not_acknowledge():
    tool, payload = _bash( "LUPIN_COMMIT_SCOPE_ACK=0 git commit -m x" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is not None


def test_an_ack_elsewhere_on_the_line_does_not_acknowledge():
    """Scoped to this invocation's own prefix — an echo cannot acknowledge a commit."""
    tool, payload = _bash( "echo LUPIN_COMMIT_SCOPE_ACK=1 && git commit -m x" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is not None


def test_empty_index_is_allowed():
    """Nothing staged — the commit fails on its own and there is nothing to review."""
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader() ) is None


def test_unreadable_index_fails_open():
    """Not a repo, git missing, timeout — a guard must never break a tool call."""
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=lambda cwd: None ) is None


@pytest.mark.parametrize( "command", [
    "git status",
    "git add -A",
    "git log --oneline -1",
    "grep -rn 'git commit' docs/",
    "echo 'git commit -m x'",
    "python -c \"print('git commit')\"",
] )
def test_non_commit_commands_are_untouched( command ):
    tool, payload = _bash( command )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is None


def test_a_quoted_separator_does_not_manufacture_a_command_position():
    """The over-block stash_guard had to fix — a separator inside a literal."""
    tool, payload = _bash( "echo 'first; git commit -m x'" )

    assert commit_scope_deny_reason( tool, payload, staged_reader=_reader( "a.py" ) ) is None


def test_non_bash_tools_are_untouched():
    assert commit_scope_deny_reason( "Edit", { "command": "git commit -m x" }, staged_reader=_reader( "a.py" ) ) is None


@pytest.mark.parametrize( "payload", [ None, "not a dict", 42, [] ] )
def test_malformed_tool_input_fails_open( payload ):
    assert commit_scope_deny_reason( "Bash", payload, staged_reader=_reader( "a.py" ) ) is None


@pytest.mark.parametrize( "command", [ "", None, 42 ] )
def test_missing_or_non_string_command_fails_open( command ):
    assert commit_scope_deny_reason( "Bash", { "command": command }, staged_reader=_reader( "a.py" ) ) is None


# ── The size call-out — the 246 MB class ─────────────────────────────────────

def test_a_large_staged_file_is_flagged( tmp_path ):
    """A path list alone reads as harmless; a size beside it does not."""
    big = tmp_path / "voice-commands-xml-train.jsonl.prev"
    big.write_bytes( b"x" * ( LARGE_FILE_BYTES + 1 ) )
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, cwd=str( tmp_path ),
        staged_reader=_reader( "voice-commands-xml-train.jsonl.prev" ),
    )

    assert "LARGE FILE(S)" in reason
    assert "246 MB" in reason
    assert "⚠️" in reason


def test_a_small_staged_file_is_not_flagged( tmp_path ):
    """Positive control — the size call-out is not printed for everything."""
    small = tmp_path / "mod.py"
    small.write_text( "x" )
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, cwd=str( tmp_path ), staged_reader=_reader( "mod.py" ),
    )

    assert "LARGE FILE(S)" not in reason
    assert "mod.py" in reason


def test_a_staged_path_that_no_longer_exists_is_still_listed( tmp_path ):
    """A deletion is staged too — an unreadable size must not drop the path."""
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, cwd=str( tmp_path ), staged_reader=_reader( "deleted.py" ),
    )

    assert "deleted.py" in reason
    assert "LARGE FILE(S)" not in reason


# ── Helpers ──────────────────────────────────────────────────────────────────

def test_blank_quoted_spans_leaves_unbalanced_quotes_alone():
    """Unbalanced quotes must not swallow text and hide a real command."""
    assert _blank_quoted_spans( "echo 'unclosed; git commit" ) == "echo 'unclosed; git commit"
    assert "hidden" not in _blank_quoted_spans( "echo 'hidden' ; git commit" )


@pytest.mark.parametrize( "num_bytes,expected", [
    ( 512,                 "512.0 B"  ),
    ( 2048,                "2.0 KB"   ),
    ( 5 * 1024 * 1024,     "5.0 MB"   ),
    ( 3 * 1024 ** 3,       "3.0 GB"   ),
    ( 4096 * 1024 ** 3,    "4096.0 GB" ),
] )
def test_human_size( num_bytes, expected ):
    assert _human_size( num_bytes ) == expected


def test_size_of_returns_none_for_a_missing_file( tmp_path ):
    assert _size_of( "nope.txt", str( tmp_path ) ) is None


def test_size_of_reads_a_real_file( tmp_path ):
    ( tmp_path / "f.txt" ).write_bytes( b"abcde" )

    assert _size_of( "f.txt", str( tmp_path ) ) == 5


def test_staged_paths_fails_open_when_git_raises( monkeypatch ):
    """A timeout or a missing git binary must return None, never propagate."""
    import lupin_cli.claude_code.hooks.lib.commit_scope_guard as guard

    def _boom( *args, **kwargs ):
        raise OSError( "git not found" )

    monkeypatch.setattr( guard.subprocess, "run", _boom )

    assert guard._staged_paths( "/anywhere" ) is None


def test_staged_paths_returns_none_outside_a_repo( tmp_path ):
    """Fail-open source: a non-repo cwd must produce None, not an exception."""
    assert _staged_paths( str( tmp_path ) ) is None


def test_staged_paths_reads_a_real_index( tmp_path ):
    """The real git path, exercised — not only the injected reader."""
    import subprocess
    repo = str( tmp_path )
    for args in ( [ "init", "-q" ], [ "config", "user.email", "t@t" ], [ "config", "user.name", "t" ] ):
        subprocess.run( [ "git" ] + args, cwd=repo, capture_output=True )
    ( tmp_path / "staged.py" ).write_text( "x" )
    subprocess.run( [ "git", "add", "staged.py" ], cwd=repo, capture_output=True )

    assert _staged_paths( repo ) == [ "staged.py" ]


def test_staged_paths_defaults_to_the_process_cwd():
    """cwd=None is the real default and must not raise."""
    result = _staged_paths()

    assert result is None or isinstance( result, list )


def test_the_real_reader_is_used_when_none_is_injected( tmp_path, monkeypatch ):
    """The production path: no staged_reader argument means real git."""
    monkeypatch.chdir( tmp_path )
    tool, payload = _bash( "git commit -m x" )

    # tmp_path is not a repo, so the real reader returns None -> fail-open allow.
    assert commit_scope_deny_reason( tool, payload ) is None


# ── The deny envelope ────────────────────────────────────────────────────────

def test_deny_response_shape():
    out = build_commit_scope_deny_response( "because" )

    assert out == {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : "because",
        }
    }
