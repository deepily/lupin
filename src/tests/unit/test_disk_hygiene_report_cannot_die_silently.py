"""
Guard for `src/scripts/disk-hygiene-report.sh` — row d2dd3ee3.

WHY. This is the only surface in the tree that computes worktree merged-ness, and
on 2026-09-05 it was found exiting 1 with ZERO stdout and ZERO stderr. It had
become precisely what its own header warns against — *"a janitor that says cleanup
complete without counts is exactly how you get to three quarters of a million
files"* — except worse, because it said nothing at all, and silence is
indistinguishable from a clean run.

The cause was an unmatched `lupin-v1-*` glob passing through literally, `du`
exiting 1, `pipefail` propagating, and `set -e` killing the script before the
report heredoc printed, with `2>/dev/null` eating the only message.

🔴 THE POINT OF THIS FILE IS THE CLASS, NOT THE INSTANCE. Fixing the glob alone
would have left the failure mode installed, and that is not a hypothetical: the
ERR trap added alongside the glob fix immediately exposed a SECOND unguarded
pipeline (`find | wc -l` over a directory that exists in the main checkout and in
no worktree) which would have kept the report silent in every worktree. One test
here pins the instance; the rest pin the property that a death is LOUD.
"""

import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

SCRIPT = cu.get_project_root() + "/src/scripts/disk-hygiene-report.sh"


def _run( lupin_root, env_extra=None ):
    """
    Run the report against lupin_root.

    Ensures:
        - returns CompletedProcess with text stdout/stderr
    """
    env = dict( os.environ )
    env[ "LUPIN_ROOT" ] = str( lupin_root )
    if env_extra: env.update( env_extra )
    return subprocess.run(
        [ "bash", SCRIPT ], capture_output=True, text=True, env=env, timeout=600
    )


@pytest.fixture
def fake_root( tmp_path ):
    """
    A minimal repo standing in for LUPIN_ROOT, with NO sibling worktree dirs.

    This reproduces the original defect's precondition exactly: the
    `lupin-wt-*` / `lupin-v1-*` globs next to it match nothing at all.
    """
    projects = tmp_path / "projects"
    root     = projects / "lupin"
    root.mkdir( parents=True )
    subprocess.run( [ "git", "-C", str( root ), "init", "-q", "-b", "main" ], check=True )
    subprocess.run( [ "git", "-C", str( root ), "config", "user.email", "g@e.com" ], check=True )
    subprocess.run( [ "git", "-C", str( root ), "config", "user.name", "g" ], check=True )
    ( root / "seed.txt" ).write_text( "seed\n" )
    subprocess.run( [ "git", "-C", str( root ), "add", "-A" ], check=True )
    subprocess.run( [ "git", "-C", str( root ), "commit", "-q", "-m", "seed" ], check=True )
    return root


def test_an_unmatched_glob_does_not_kill_the_report( fake_root ):
    """
    🔴 THE ORIGINAL DEFECT, pinned. No `lupin-wt-*` and no `lupin-v1-*` exist beside
    this root, so both globs are unmatched — the exact condition that produced a
    silent exit 1 on the real box for an unknown length of time.
    """
    done = _run( fake_root )

    assert done.returncode == 0, (
        f"report died on unmatched globs: rc={done.returncode}\n"
        f"stdout={done.stdout!r}\nstderr={done.stderr!r}"
    )
    assert "disk hygiene" in done.stdout


def test_the_report_prints_its_counts_not_just_a_verdict( fake_root ):
    """
    The script's own stated reason for existing: *"This prints NUMBERS, not a
    verdict."* A run that exits 0 having printed nothing is the failure this row is
    about, so exit code alone is never the assertion.
    """
    done = _run( fake_root )

    assert done.returncode == 0
    for field in ( "hook logs", "worktrees", "worktree bytes", "transcripts", "io/ total" ):
        assert field in done.stdout, f"missing {field!r} from:\n{done.stdout}"


def test_a_missing_hook_log_directory_reports_zero_rather_than_dying( fake_root ):
    """
    The SECOND failure, which only appeared once the ERR trap made deaths loud.
    `io/claude_code_hooks/logs` exists in the main checkout and in no worktree, so
    `find` exited non-zero there and pipefail took the whole report down.

    ⚠️ It also pins the double-output repair: `find | wc -l || echo 0` emits "0\\n0"
    (wc succeeds and prints 0, then pipefail fires the ||), which the threshold test
    later rejects with "integer expression expected". Zero must be ONE zero.
    """
    assert not ( fake_root / "io" / "claude_code_hooks" / "logs" ).exists()

    done = _run( fake_root )

    assert done.returncode == 0
    assert "hook logs      : 0 files" in done.stdout, done.stdout
    assert "integer expression expected" not in done.stderr, done.stderr


def test_a_death_is_LOUD_and_names_where_it_died( fake_root ):
    """
    🔴 THE CLASS, NOT THE INSTANCE — the case that makes this file worth more than a
    one-line glob fix.

    Every future unguarded pipeline is a candidate for the same silent death. The
    ERR trap is what converts that from invisible to reported, so it gets a test
    that does not depend on any particular command failing: LUPIN_ROOT is pointed
    at a path that is not a git repo, and the run must SAY SO rather than vanish.
    """
    done = _run( fake_root, env_extra={ "LUPIN_ROOT": str( fake_root.parent / "does-not-exist" ) } )

    assert done.returncode != 0, "a broken root produced a SUCCESS — the silence is back"
    assert done.stderr.strip(), "the script died with an empty stderr — that is the whole defect"
    assert "DIED at line" in done.stderr, done.stderr
    assert "clean run" in done.stderr, done.stderr


def test_the_script_does_not_resolve_its_globs_from_the_current_directory( fake_root, tmp_path ):
    """
    `du` with no operands reads the CURRENT directory, so an empty worktree list
    handed straight to du would silently measure wherever the caller happened to be
    standing — a confident number about the wrong tree, which is this repo's most
    frequent defect shape.

    Run from an unrelated cwd holding a large-ish file; the worktree byte count must
    still be 0.00, not the size of that file.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    ( elsewhere / "ballast.bin" ).write_bytes( b"x" * ( 5 * 1024 * 1024 ) )

    env = dict( os.environ )
    env[ "LUPIN_ROOT" ] = str( fake_root )
    done = subprocess.run(
        [ "bash", SCRIPT ], capture_output=True, text=True,
        env=env, cwd=str( elsewhere ), timeout=600
    )

    assert done.returncode == 0, done.stderr
    line = [ l for l in done.stdout.splitlines() if "worktree bytes" in l ][ 0 ]
    assert "0.00 GB external" in line, f"du measured the cwd, not the worktrees: {line}"


@pytest.mark.skipif( shutil.which( "git" ) is None, reason="git required" )
def test_it_still_counts_merged_worktrees_when_some_exist( fake_root ):
    """
    POSITIVE CONTROL FOR THE MERGED-NESS NUMBER. Without it, every assertion above
    is satisfied by a script that reports zeros for everything — the vacuous pass
    that a report full of 0.00 makes so easy to miss.
    """
    # TWO siblings, differing in ONE property, because "N of N merged" would be
    # satisfied by a predicate that answers "merged" unconditionally. The first cut
    # of this test had a single sibling at the tip and asserted 1-of-2; it read 2-of-2
    # and proved nothing either way.
    merged_wt   = fake_root.parent / "lupin-wt-merged"
    unmerged_wt = fake_root.parent / "lupin-wt-unmerged"
    for wt in ( merged_wt, unmerged_wt ):
        subprocess.run(
            [ "git", "-C", str( fake_root ), "worktree", "add", "-q", "--detach", str( wt ) ],
            check=True, capture_output=True
        )

    # give ONE of them a commit its parent does not have — now it is genuinely ahead
    ( unmerged_wt / "ahead.txt" ).write_text( "undelivered\n" )
    subprocess.run( [ "git", "-C", str( unmerged_wt ), "add", "-A" ], check=True )
    subprocess.run( [ "git", "-C", str( unmerged_wt ), "commit", "-q", "-m", "ahead" ], check=True )

    done = _run( fake_root )

    assert done.returncode == 0, done.stderr
    wt_line = [ l for l in done.stdout.splitlines() if "worktrees " in l ][ 0 ]
    assert "3 total" in wt_line, wt_line
    assert "2 fully merged" in wt_line, (
        "the predicate must separate the sibling that is AHEAD from the two that are "
        f"not — an unconditional answer would say 3: {wt_line}"
    )
