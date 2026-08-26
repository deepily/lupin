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
    _commits_the_whole_worktree,
    _mentions_git_commit,
    _modified_tracked_paths,
    _pathspec_of,
    _strip_heredoc_bodies,
    evaluate_commit_scope,
    build_commit_scope_notice_response,
    SCOPE_INDEX,
    SCOPE_DASH_A,
    SCOPE_PATHSPEC,
    LARGE_FILE_BYTES,
)


def _reader( *paths ):
    """A staged_reader returning a fixed set."""
    return lambda cwd: list( paths )


def _bash( command ):
    return ( "Bash", { "command": command } )


# ── Manifest fixture ─────────────────────────────────────────────────────────

MANIFEST = """# Claude Session Manifest (Multi-Session)
**Format Version**: 2.0

---

## Session: e5398ce6
**Status**: active

### Touched Files
- 2026-08-25T17:17:00 | src/mine_one.py
- 2026-08-25T17:20:00 | src/mine_two.py

---

## Session: aa11bb22
**Status**: active

### Touched Files
- 2026-08-25T16:00:00 | src/theirs.py

---
"""

MY_SESSION = "e5398ce6-fd21-4cb6-8556-1a44844f8fcf"


@pytest.fixture
def repo( tmp_path ):
    """A tree carrying the parallel-session manifest."""
    ( tmp_path / ".claude-session.md" ).write_text( MANIFEST )
    return str( tmp_path )


# ── PROOF 1 — RED FIRST: a contaminated index is refused, naming the foreign file

def test_a_peers_staged_file_is_refused_and_its_owner_named( repo ):
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py", "src/theirs.py" ),
    )

    assert reason is not None
    assert "src/theirs.py" in reason
    assert "claimed by session aa11bb22" in reason
    assert "1 staged file(s) are NOT claimed" in reason


def test_a_file_no_session_claims_is_refused_too( repo ):
    """Unaccounted is unaccounted, even when no peer section names it."""
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py", "src/nobody.py" ),
    )

    assert "src/nobody.py" in reason
    assert "claimed by no session" in reason


def test_the_refusal_always_prints_the_full_unscoped_set( repo ):
    """The unscoped list is the thing the original defect was missing."""
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py", "src/mine_two.py", "src/theirs.py" ),
    )

    assert "THE FULL STAGED SET (3 file(s))" in reason
    for path in ( "src/mine_one.py", "src/mine_two.py", "src/theirs.py" ):
        assert path in reason


# ── PROOF 2 — NEGATIVE CONTROL: a clean single-seat index commits untouched ──

def test_a_clean_single_seat_index_is_not_refused( repo ):
    """Not refuse-always in disguise. Zero friction on the normal path."""
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py", "src/mine_two.py" ),
    )

    assert reason is None


@pytest.mark.parametrize( "auto", [ "history.md", "TODO.md", "CLAUDE.md", ".claude-session.md" ] )
def test_sanctioned_auto_includes_ride_along( repo, auto ):
    """CLAUDE.md sanctions these on any session's commit."""
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py", auto ),
    )

    assert reason is None


def test_the_verdict_is_deterministic( repo ):
    """Same staged set, same verdict every run — peer noise must not move it."""
    tool, payload = _bash( "git commit -m x" )
    call = lambda: commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py", "src/theirs.py" ),
    )

    assert call() == call() == call()


# ── PROOF 3 — the escape hatch is honoured ──────────────────────────────────

def test_the_hatch_lets_a_deliberate_peer_landing_through( repo ):
    """A manager landing a peer's reviewed work on purpose stays possible."""
    tool, payload = _bash( "LUPIN_COMMIT_SCOPE_ACK=1 git commit -m 'land reviewed work'" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/theirs.py" ),
    )

    assert reason is None


@pytest.mark.parametrize( "value", [ "1", "true", "on", "yes", "TRUE" ] )
def test_every_truthy_hatch_value_is_honoured( repo, value ):
    tool, payload = _bash( f"LUPIN_COMMIT_SCOPE_ACK={value} git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/theirs.py" )
    ) is None


def test_a_falsy_hatch_does_not_open_it( repo ):
    tool, payload = _bash( "LUPIN_COMMIT_SCOPE_ACK=0 git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/theirs.py" )
    ) is not None


def test_a_hatch_elsewhere_on_the_line_does_not_open_it( repo ):
    """Scoped to this invocation's own prefix."""
    tool, payload = _bash( "echo LUPIN_COMMIT_SCOPE_ACK=1 && git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/theirs.py" )
    ) is not None


# ── PROOF 4 — FAIL-OPEN when no manifest exists ─────────────────────────────

def test_no_manifest_file_fails_open( tmp_path ):
    """Most of the fleet. A seat that never adopted the discipline is not wedged."""
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=str( tmp_path ),
        staged_reader=_reader( "anything.py", "whatever.py" ),
    ) is None


def test_a_session_with_no_section_fails_open( repo ):
    """The manifest exists but says nothing about this seat."""
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id="99999999-0000-0000-0000-000000000000", cwd=repo,
        staged_reader=_reader( "src/theirs.py" ),
    ) is None


def test_a_missing_session_id_fails_open( repo ):
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=None, cwd=repo, staged_reader=_reader( "src/theirs.py" )
    ) is None


def test_an_unreadable_index_fails_open( repo ):
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=lambda cwd: None
    ) is None


def test_an_empty_index_is_allowed( repo ):
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader()
    ) is None


def test_a_section_claiming_nothing_is_not_the_same_as_no_section( tmp_path ):
    """Empty section = this seat claims nothing, so a staged file IS foreign."""
    manifest = "\n".join( [
        "## Session: e5398ce6",
        "**Status**: active",
        "",
        "### Touched Files",
        "",
        "---",
    ] )
    ( tmp_path / ".claude-session.md" ).write_text( manifest )
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=str( tmp_path ),
        staged_reader=_reader( "src/something.py" ),
    ) is not None


# ── Size is an independent trigger, unrelated to ownership ──────────────────

def test_an_oversized_own_file_is_still_refused( repo, tmp_path ):
    """The 246 MB incident: the files were the committer's OWN."""
    big = tmp_path / "src" / "mine_one.py"
    big.parent.mkdir( parents=True, exist_ok=True )
    big.write_bytes( b"x" * ( LARGE_FILE_BYTES + 1 ) )
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/mine_one.py" ),
    )

    assert "LARGE FILE(S) STAGED" in reason
    assert "246 MB" in reason


def test_size_refuses_even_with_no_manifest( tmp_path ):
    """Ownership fail-open must not disable the size trigger."""
    big = tmp_path / "huge.bin"
    big.write_bytes( b"x" * ( LARGE_FILE_BYTES + 1 ) )
    tool, payload = _bash( "git commit -m x" )

    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=str( tmp_path ), staged_reader=_reader( "huge.bin" ),
    )

    assert "LARGE FILE(S) STAGED" in reason


def test_a_small_own_file_triggers_nothing( repo, tmp_path ):
    """Positive control on the size trigger."""
    small = tmp_path / "src" / "mine_one.py"
    small.parent.mkdir( parents=True, exist_ok=True )
    small.write_text( "x" )
    tool, payload = _bash( "git commit -m x" )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/mine_one.py" )
    ) is None


# ── Command matching ────────────────────────────────────────────────────────

@pytest.mark.parametrize( "command", [
    "git commit -m x",
    "/usr/bin/git commit -m x",
    "cd /repo && git commit -m x",
    "sudo git commit -m x",
    "GIT_AUTHOR_NAME=x git commit -m y",
    "git -C /repo commit -m x",
    "git commit --amend --no-edit",
    "if true; then git commit -m x; fi",
] )
def test_natural_spellings_are_caught( repo, command ):
    tool, payload = _bash( command )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/theirs.py" )
    ) is not None


@pytest.mark.parametrize( "command", [
    "git status",
    "git add -A",
    "git log --oneline -1",
    "grep -rn 'git commit' docs/",
    "echo 'git commit -m x'",
    "echo 'first; git commit -m x'",
] )
def test_non_commit_commands_are_untouched( repo, command ):
    tool, payload = _bash( command )

    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader( "src/theirs.py" )
    ) is None


def test_non_bash_tools_are_untouched( repo ):
    assert commit_scope_deny_reason(
        "Edit", { "command": "git commit -m x" }, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/theirs.py" ),
    ) is None


@pytest.mark.parametrize( "payload", [ None, "not a dict", 42, [] ] )
def test_malformed_tool_input_fails_open( repo, payload ):
    assert commit_scope_deny_reason( "Bash", payload, session_id=MY_SESSION, cwd=repo ) is None


@pytest.mark.parametrize( "command", [ "", None, 42 ] )
def test_missing_or_non_string_command_fails_open( repo, command ):
    assert commit_scope_deny_reason(
        "Bash", { "command": command }, session_id=MY_SESSION, cwd=repo
    ) is None


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


# ── Row 292dd3d8 — `git commit -a` writes what the INDEX NEVER HELD ───────────
# The guard weighs `git diff --cached`. `-a` stages every modified tracked file
# inside git, at commit time, AFTER this hook has returned. Measured 2026-08-25:
# `git commit -am` with an empty index was ALLOWED unconditionally while carrying
# every peer modification in the tree.

def _modified( *paths ):
    """A modified-tracked reader returning a fixed set."""
    return lambda cwd: list( paths )


@pytest.mark.parametrize( "command", [
    'git commit -am "x"',        # the short cluster — the common spelling
    'git commit -a -m "x"',
    'git commit --all -m x',
    'git commit -va -m x',       # an a buried in a longer cluster
] )
def test_commit_dash_a_is_refused_for_a_peer_file_it_never_staged( repo, command ):
    tool, payload = _bash( command )
    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader(), modified_reader=_modified( "src/theirs.py" ),
    )
    assert reason is not None
    assert "src/theirs.py" in reason


def test_commit_dash_a_still_passes_when_the_whole_tree_is_mine( repo ):
    """Not refuse-always: -a is fine when everything it sweeps is this seat's."""
    tool, payload = _bash( 'git commit -am "x"' )
    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py" ), modified_reader=_modified( "src/mine_two.py" ),
    ) is None


def test_a_plain_commit_ignores_the_modified_set_entirely( repo ):
    """Without -a, an unstaged peer file is NOT going to be committed — allow."""
    tool, payload = _bash( 'git commit -m "x"' )
    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py" ), modified_reader=_modified( "src/theirs.py" ),
    ) is None


def test_amend_is_not_all( repo ):
    """`--amend` starts like `--all` and is a different flag. Do not false-trip."""
    tool, payload = _bash( 'git commit --amend --no-edit' )
    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py" ), modified_reader=_modified( "src/theirs.py" ),
    ) is None


def test_an_a_inside_the_message_does_not_count_as_dash_a( repo ):
    """The flag scan runs on the quote-blanked command, so prose cannot trip it."""
    tool, payload = _bash( 'git commit -m "add all the files -a"' )
    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py" ), modified_reader=_modified( "src/theirs.py" ),
    ) is None


def test_an_unreadable_modified_set_fails_open_not_shut( repo ):
    """A guard must never wedge a commit because a second git read failed."""
    tool, payload = _bash( 'git commit -am "x"' )
    assert commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py" ), modified_reader=lambda cwd: None,
    ) is None


def test_the_union_does_not_double_count_a_path_in_both_sets( repo ):
    """A file both staged AND modified is one file, not two — the count proves it."""
    tool, payload = _bash( 'git commit -am "x"' )
    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/theirs.py" ), modified_reader=_modified( "src/theirs.py" ),
    )
    assert "(1 file(s))" in reason
    assert "1 file(s) this commit would carry" in reason


def test_the_dash_a_refusal_does_not_say_staged( repo ):
    """Telling a seat to `git restore --staged` a file it never staged is a wrong map."""
    tool, payload = _bash( 'git commit -am "x"' )
    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader(), modified_reader=_modified( "src/theirs.py" ),
    )
    assert "git restore --staged" not in reason
    assert "drop -a and commit your paths by name" in reason
    assert "THE FULL SET THIS COMMIT WOULD CARRY" in reason


def test_a_plain_commit_still_speaks_of_the_staged_set( repo ):
    """The -a wording must not leak onto the ordinary path."""
    tool, payload = _bash( 'git commit -m "x"' )
    reason = commit_scope_deny_reason(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/theirs.py" ),
    )
    assert "THE FULL STAGED SET" in reason
    assert "git restore --staged" in reason


@pytest.mark.parametrize( "command,expected", [
    ( "git commit -am x",        True  ),
    ( "git commit --all",        True  ),
    ( "git commit -a",           True  ),
    ( "git commit -m x",         False ),
    ( "git commit --amend",      False ),
    ( "git commit --no-verify",  False ),
    ( "git commit",              False ),
] )
def test_the_dash_a_detector_reads_the_flags_it_should( command, expected ):
    assert _commits_the_whole_worktree( command, _mentions_git_commit( command ) ) is expected


def test_modified_tracked_paths_returns_none_outside_a_repo( tmp_path ):
    assert _modified_tracked_paths( str( tmp_path ) ) is None


def test_modified_tracked_paths_reads_a_real_worktree( tmp_path ):
    """The real git path for the -a set, exercised — not only the injected reader."""
    import subprocess
    repo = str( tmp_path )
    for args in ( [ "init", "-q" ], [ "config", "user.email", "t@t" ], [ "config", "user.name", "t" ] ):
        subprocess.run( [ "git" ] + args, cwd=repo, capture_output=True )
    ( tmp_path / "tracked.py" ).write_text( "one\n" )
    subprocess.run( [ "git", "add", "tracked.py" ], cwd=repo, capture_output=True )
    subprocess.run( [ "git", "commit", "-qm", "seed" ], cwd=repo, capture_output=True,
                    env={ **os.environ, "LUPIN_COMMIT_SCOPE_ACK": "1" } )
    ( tmp_path / "tracked.py" ).write_text( "two\n" )     # modified, NOT staged

    assert _modified_tracked_paths( repo ) == [ "tracked.py" ]


def test_modified_tracked_paths_fails_open_when_git_raises( monkeypatch ):
    """A timeout or a missing git binary must return None, never propagate."""
    import lupin_cli.claude_code.hooks.lib.commit_scope_guard as guard

    def _boom( *args, **kwargs ):
        raise OSError( "git not found" )

    monkeypatch.setattr( guard.subprocess, "run", _boom )

    assert guard._modified_tracked_paths( "/anywhere" ) is None


def test_the_real_modified_reader_is_used_when_none_is_injected( tmp_path, monkeypatch ):
    """The production -a path: no modified_reader argument means real git."""
    monkeypatch.chdir( tmp_path )
    tool, payload = _bash( "git commit -am x" )

    # tmp_path is not a repo, so both real readers return None -> fail-open allow.
    assert commit_scope_deny_reason( tool, payload ) is None


def test_a_heredoc_body_quoting_dash_a_does_not_make_this_a_dash_a_commit():
    """
    Measured the moment the -a support shipped: `git commit -F - <<'EOF'` whose
    heredoc body quotes `git commit -am "x"` was refused as a -a commit. An
    unbounded flag scan walks past the command into the next line's text — and a
    guard that refuses honest commits is a guard somebody turns off.
    """
    command = 'git commit -F - <<\'MSG\'\nprobe output:\n    git commit -am "x"  -> ALLOWED\nMSG'
    assert _commits_the_whole_worktree( command, _mentions_git_commit( command ) ) is False


@pytest.mark.parametrize( "command", [
    'git commit -m x; git commit -am y',      # a real -a, but in the NEXT command
    'git commit -m x && git commit --all',
    'git commit -m x | tee log',
] )
def test_the_scan_stops_at_the_end_of_this_command( command ):
    """The first match's flags are this command's flags — not the whole line's."""
    assert _commits_the_whole_worktree( command, _mentions_git_commit( command ) ) is False


# ── Row 292dd3d8, mr radio's ruling 2026-08-25 ───────────────────────────────
# `git commit -- <paths>` is now STANDING PRACTICE, because it takes named paths
# from the working tree and never reads the shared index — which is what makes it
# race-free, and also what made it invisible here: an empty index read as nothing
# to object to. Mandating the safe shape would have made every compliant commit an
# unreviewed one. So the guard learns the pathspec, and gives up out loud.

def test_a_pathspec_commit_is_reviewed_on_the_paths_it_names( repo ):
    tool, payload = _bash( "git commit -F msg.txt -- src/mine_one.py src/theirs.py" )
    verdict = evaluate_commit_scope(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader(),                    # index EMPTY — the whole point
    )
    assert "src/theirs.py" in verdict.deny_reason
    assert "THE PATHS THIS COMMIT NAMES" in verdict.deny_reason


def test_a_pathspec_commit_of_only_my_own_paths_passes( repo ):
    tool, payload = _bash( "git commit -F msg.txt -- src/mine_one.py src/mine_two.py" )
    verdict = evaluate_commit_scope(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader(),
    )
    assert verdict.deny_reason is None
    assert verdict.notice is None


def test_the_pathspec_refusal_warns_about_working_tree_CONTENT( repo ):
    """
    mr radio's point, and the sharper hazard: a pathspec commit takes the file's
    WORKING-TREE content, so naming a file you legitimately claim still commits
    whatever a peer left uncommitted inside it. Nothing here can stop that — but
    the refusal can at least tell the seat to look at the diff, not the name.
    """
    tool, payload = _bash( "git commit -F msg.txt -- src/theirs.py" )
    reason = evaluate_commit_scope(
        tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader(),
    ).deny_reason
    assert "WORKING-TREE content" in reason
    assert "git diff -- <path>" in reason


@pytest.mark.parametrize( "command,fragment", [
    ( "git commit -F - <<'MSG'\nmessage body\nMSG", "redirection"  ),   # body stripped; the `<<` itself remains
    ( 'git commit -- "src/*.py"',             "magic or globs"   ),
    ( "git commit -S -m x src/a.py",          "optional argument"),
    ( "git commit --frobnicate src/a.py",     "not an option"    ),
    ( 'git commit -m "unbalanced',            "quoting"          ),
] )
def test_an_unparseable_commit_is_ALLOWED_with_a_notice( repo, command, fragment ):
    """Allow-on-doubt: a guard that refuses honest commits gets switched off."""
    tool, payload = _bash( command )
    verdict = evaluate_commit_scope(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/theirs.py" ),   # would otherwise REFUSE
    )
    assert verdict.deny_reason is None
    assert "NOT REVIEWED" in verdict.notice
    assert fragment in verdict.notice


def test_the_notice_envelope_allows_rather_than_denies():
    """No permissionDecision key at all — the commit runs, the seat is told."""
    envelope = build_commit_scope_notice_response( "something" )
    out      = envelope[ "hookSpecificOutput" ]
    assert out[ "hookEventName" ] == "PreToolUse"
    assert out[ "additionalContext" ] == "something"
    assert "permissionDecision" not in out


@pytest.mark.parametrize( "command,staged,modified,heading", [
    ( 'git commit -m x',                      ( "src/theirs.py", ), (), "THE FULL STAGED SET" ),
    ( 'git commit -am x',                     (),                   ( "src/theirs.py", ),
      "THE FULL SET THIS COMMIT WOULD CARRY" ),
    ( 'git commit -F m.txt -- src/theirs.py', (),                   (), "THE PATHS THIS COMMIT NAMES" ),
] )
def test_the_refusal_always_names_which_set_it_reviewed( repo, command, staged, modified, heading ):
    """Three shapes, three sets — a refusal that does not say which is a wrong map."""
    tool, payload = _bash( command )
    reason = evaluate_commit_scope(
        tool, payload, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( *staged ), modified_reader=_modified( *modified ),
    ).deny_reason
    assert heading in reason


@pytest.mark.parametrize( "command,expected", [
    ( "git commit -- a.py b.py",       [ "a.py", "b.py" ] ),
    ( 'git commit -m "fix" -- a.py',   [ "a.py" ]         ),
    ( "git commit -m fix a.py",        [ "a.py" ]         ),   # -m eats "fix", not a.py
    ( "git commit -am x",              []                 ),   # cluster: m eats x
    ( "git commit --amend --no-edit",  []                 ),
    ( "git commit --author=me a.py",   [ "a.py" ]         ),   # = carries its own arg
    ( "git commit",                    []                 ),
] )
def test_the_pathspec_parser_accounts_for_every_option_argument( command, expected ):
    paths, unsure = _pathspec_of( command, _mentions_git_commit( command ) )
    assert unsure is None
    assert paths == expected


def test_the_ack_hatch_still_beats_a_pathspec_commit( repo ):
    tool, payload = _bash( "LUPIN_COMMIT_SCOPE_ACK=1 git commit -F m.txt -- src/theirs.py" )
    verdict = evaluate_commit_scope( tool, payload, session_id=MY_SESSION, cwd=repo, staged_reader=_reader() )
    assert verdict.deny_reason is None and verdict.notice is None


def test_an_optional_arg_option_buried_in_a_CLUSTER_is_still_ambiguous():
    """`-Sm x` — the S is inside the cluster, so the bare-token check never sees it."""
    command = "git commit -Sm x src/a.py"
    paths, unsure = _pathspec_of( command, _mentions_git_commit( command ) )
    assert paths is None
    assert "optional" in unsure


def test_pathspec_magic_without_a_double_dash_is_also_a_give_up():
    """Magic does not need `--` in front of it to be unresolvable here."""
    command = "git commit -m x src/*.py"
    paths, unsure = _pathspec_of( command, _mentions_git_commit( command ) )
    assert paths is None
    assert "magic or globs" in unsure


# ── A `git commit` inside a heredoc is DATA, not the command being run ───────
# Measured on this guard's OWN commit: the message was written with
# `cat > msg.txt <<'EOF' … EOF`, the body contained the line `git commit -> the
# index`, and the left-to-right search matched THAT — so the real
# `git commit -F msg.txt -- <paths>` was never the thing examined.

def test_a_git_commit_quoted_in_a_heredoc_is_not_the_command( repo ):
    command = (
        "MSG=/tmp/m.txt\n"
        "cat > \"$MSG\" <<'EOF'\n"
        "    git commit             -> the index\n"
        "    git commit -a          -> the index plus modified\n"
        "EOF\n"
        "git commit -F \"$MSG\" -- src/theirs.py"
    )
    verdict = evaluate_commit_scope(
        "Bash", { "command": command }, session_id=MY_SESSION, cwd=repo, staged_reader=_reader(),
    )
    assert verdict.notice is None                       # the prose no longer confuses it
    assert "src/theirs.py" in verdict.deny_reason       # the REAL commit is reviewed
    assert "THE PATHS THIS COMMIT NAMES" in verdict.deny_reason


def test_the_same_command_naming_only_my_own_paths_passes_clean( repo ):
    command = (
        "cat > msg.txt <<'EOF'\n"
        "    git commit -am x\n"
        "EOF\n"
        "git commit -F msg.txt -- src/mine_one.py"
    )
    verdict = evaluate_commit_scope(
        "Bash", { "command": command }, session_id=MY_SESSION, cwd=repo, staged_reader=_reader(),
    )
    assert verdict.deny_reason is None and verdict.notice is None


def test_an_unterminated_heredoc_is_allowed_with_a_notice( repo ):
    """Opened and never closed — the body could hide anything, so decide nothing."""
    command = "git commit -F - <<'EOF'\nsome message that never ends"
    verdict = evaluate_commit_scope(
        "Bash", { "command": command }, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/theirs.py" ),
    )
    assert verdict.deny_reason is None
    assert "never closes" in verdict.notice


@pytest.mark.parametrize( "command,expected", [
    ( "echo hi",                              "echo hi" ),                # untouched
    ( "cat <<EOF\nbody\nEOF\ngit commit -m x", "cat <<EOF\ngit commit -m x" ),
    ( "cat <<-TAG\n\tbody\n\tTAG\ndone",      "cat <<-TAG\ndone" ),       # <<- strips indent
    ( 'cat <<"Q"\nbody\nQ\nx',                'cat <<"Q"\nx' ),           # quoted tag
] )
def test_the_heredoc_stripper_keeps_the_command_and_drops_the_body( command, expected ):
    assert _strip_heredoc_bodies( command ) == expected


def test_blank_quoted_spans_preserves_length_so_offsets_stay_valid():
    """
    The blanked string is used to FIND the command; the raw string is used to read
    its arguments. Collapsing a quoted span to one space desynchronises the two, and
    every offset taken after it points at the wrong character.
    """
    command = 'git commit -F "a longer quoted argument" -- src/a.py'
    assert len( _blank_quoted_spans( command ) ) == len( command )


def test_a_quoted_argument_before_the_pathspec_does_not_shift_the_scan( repo ):
    """
    Measured 2026-08-25: `python3 - "$MSG" <<'EOF' … EOF` then
    `git commit -F "$MSG" -- <paths>` put the match offset 12 characters early, the
    bounded tail began at a newline and read as an EMPTY command, so a pathspec
    commit was judged on the INDEX — the one set it does not write.
    """
    command = (
        "MSG=/tmp/m.txt\n"
        "python3 - \"$MSG\" <<'PYEOF'\n"
        "write the message\n"
        "PYEOF\n"
        "git commit -F \"$MSG\" -- src/theirs.py"
    )
    verdict = evaluate_commit_scope(
        "Bash", { "command": command }, session_id=MY_SESSION, cwd=repo,
        staged_reader=_reader( "src/mine_one.py" ),      # index says CLEAN
    )
    assert "THE PATHS THIS COMMIT NAMES" in verdict.deny_reason
    assert "src/theirs.py" in verdict.deny_reason
