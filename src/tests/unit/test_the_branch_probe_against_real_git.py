#!/usr/bin/env python3
"""
The probe, driven against REAL git — not against a hand-written fake.

WHY, and it is CLAUDE.md § A HAND-WRITTEN FIXTURE IS NOT MERELY SIMPLER THAN REALITY:
a fixture is authored on the PARSER's side of the boundary, so it is systematically
better-formed than what the producer emits. My fakes in the sibling file return
`"wt-feature"` and `"3"`. Real git returns `"wt-feature\\n"` and `"3\\n"`, and a
detached HEAD returns `"HEAD\\n"`. Every one of those passes through `.strip()` here —
but a fixture written by the same person who wrote the strip cannot demonstrate that,
because they would have written the fixture with the newline only if they had already
thought of it.

So this builds a real repository, makes real commits, and asks real git. It also
obtains its runner through `default_sweep_git`, so the REUSE seam — borrowing
`orphaned_head_sweep._git` rather than retyping it — is exercised end to end rather
than asserted about.

⚠️ It SKIPS when the planning-is-prompting checkout is absent, and says so. A test that
silently passed in that case would be reporting on a runner it never obtained, which is
the empty-population defect this repo keeps re-deriving.
"""
import os
import subprocess
import sys

import pytest

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src not in sys.path:
    sys.path.insert( 0, _src )

from lupin_mcp import reap_branch


@pytest.fixture
def real_git_runner():
    """The SAME `_git` the session-end sweep uses, or an explicit skip."""
    runner = reap_branch.default_sweep_git()
    if runner is None:
        pytest.skip( "planning-is-prompting checkout not resolvable — "
                     "$PLANNING_IS_PROMPTING_ROOT unset or the sweep script is absent" )
    return runner


def _run( cwd, *args ):
    subprocess.run( [ "git", "-C", str( cwd ), *args ], check=True,
                    capture_output=True, text=True )


@pytest.fixture
def repo( tmp_path ):
    """A real repo: a target line, and a feature branch two commits ahead of it."""
    _run( tmp_path, "init", "-q", "-b", "the-line" )
    _run( tmp_path, "config", "user.email", "t@t" )
    _run( tmp_path, "config", "user.name",  "t" )
    ( tmp_path / "a.txt" ).write_text( "base\n" )
    _run( tmp_path, "add", "-A" )
    _run( tmp_path, "commit", "-qm", "base" )
    _run( tmp_path, "switch", "-q", "-c", "wt-feature" )
    for n in ( "b", "c" ):
        ( tmp_path / f"{n}.txt" ).write_text( "work\n" )
        _run( tmp_path, "add", "-A" )
        _run( tmp_path, "commit", "-qm", f"work {n}" )
    return tmp_path


def test_real_git_output_parses_despite_its_trailing_newline( repo, real_git_runner ):
    """The whole reason this file exists — git's real stdout, not a tidied string."""
    raw = real_git_runner( str( repo ), "rev-parse", "--abbrev-ref", "HEAD" ).stdout
    assert raw.endswith( "\n" ), "fixture premise broken: git no longer emits a trailing newline"
    assert reap_branch.seat_branch( str( repo ), real_git_runner ) == ( "wt-feature", None )


def test_a_real_unmerged_branch_is_counted_and_named( repo, real_git_runner ):
    out = reap_branch.probe_seat_branches(
        { "seat": { "cwd": str( repo ), "persona": "Clayton" } },
        target_branch="the-line", git_fn=real_git_runner )
    assert out[ "seat" ][ "status"  ] == "unmerged"
    assert out[ "seat" ][ "commits" ] == 2
    assert out[ "seat" ][ "branch"  ] == "wt-feature"


def test_the_resume_line_it_prints_actually_runs( repo, real_git_runner ):
    """
    A resume command nobody has executed is a claim about a command. This runs it and
    asserts it lists the right number of commits — so the successor's next step is
    proven, not merely spelled.
    """
    out    = reap_branch.probe_seat_branches(
        { "seat": { "cwd": str( repo ), "persona": "C" } },
        target_branch="the-line", git_fn=real_git_runner )
    resume = out[ "seat" ][ "resume" ]
    assert resume == "git log --oneline the-line..wt-feature"

    proc = subprocess.run( resume.split(), cwd=str( repo ), capture_output=True, text=True )
    assert proc.returncode == 0
    assert len( [ l for l in proc.stdout.splitlines() if l.strip() ] ) == 2


def test_a_real_merged_branch_is_quiet( repo, real_git_runner ):
    """NEGATIVE CONTROL against a real merge — without it, 'unmerged' could be constant."""
    _run( repo, "switch", "-q", "the-line" )
    _run( repo, "merge", "-q", "--no-edit", "wt-feature" )
    _run( repo, "switch", "-q", "wt-feature" )
    out = reap_branch.probe_seat_branches(
        { "seat": { "cwd": str( repo ), "persona": "C" } },
        target_branch="the-line", git_fn=real_git_runner )
    assert out[ "seat" ][ "status" ] == "merged"
    assert reap_branch.branch_alarm( out ) is None


def test_a_real_detached_head_reads_detached( repo, real_git_runner ):
    """Real git says 'HEAD\\n' here. A fixture author writes 'HEAD' and never learns."""
    sha = real_git_runner( str( repo ), "rev-parse", "HEAD" ).stdout.strip()
    _run( repo, "checkout", "-q", sha )
    assert reap_branch.seat_branch( str( repo ), real_git_runner ) == ( None, "detached" )


def test_a_real_directory_that_is_not_a_repo_reads_not_a_worktree( tmp_path, real_git_runner ):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert reap_branch.seat_branch( str( plain ), real_git_runner ) == ( None, "not_a_worktree" )


def test_a_nonexistent_target_ref_reads_probe_failed_never_zero( repo, real_git_runner ):
    """
    Real git exits non-zero on an unknown revision. That must read as 'could not look',
    NOT as a merged branch — a wrong target silently reporting 'merged' would make this
    whole mechanism quietly useless.
    """
    out = reap_branch.probe_seat_branches(
        { "seat": { "cwd": str( repo ), "persona": "C" } },
        target_branch="no-such-branch-xyz", git_fn=real_git_runner )
    assert out[ "seat" ][ "status" ] == "probe_failed"
    assert reap_branch.branch_alarm( out ) is not None      # and it is NOT silent about it
