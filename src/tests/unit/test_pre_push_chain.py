"""
The pre-push hook, driven by real pushes from a scratch repository to a scratch bare remote.

The hook checks the tip of each pushed ref, in a throwaway worktree, with that commit's own gate.
Each test asserts both what git said and whether the remote received the ref, because a hook
that prints a refusal and still lets the push through looks the same on the terminal.
"""

import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
HOOK         = os.path.join( PROJECT_ROOT, "src", "scripts", "pre-push-chain.sh" )
VENV         = os.path.join( PROJECT_ROOT, ".venv" )
TRACKED      = (
    "src/tests/run-doclint-gate.sh",
    "src/scripts/lib/resolve-venv-pytest.sh",
    "src/conf/dm-tutor-lowercase-words.txt",
)
CLEAN        = '"""\nAdd two numbers.\n"""\n'
LOUD         = '"""\nThis module must NEVER change.\n"""\n'

pytestmark = pytest.mark.skipif( not os.path.isdir( VENV ), reason="the gate needs a .venv beside the tree, and this tree has none" )


def _git( repo, *args, check=True ):
    done = subprocess.run( [ "git", "-c", "user.email=t@t", "-c", "user.name=t", *args ], cwd=repo, capture_output=True, text=True, timeout=120 )
    if check: assert done.returncode == 0, done.stderr
    return done


def _write( repo, rel, text ):
    path = repo / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text, encoding="utf-8" )


def _commit( repo, message ):
    _git( repo, "add", "-A" )
    _git( repo, "commit", "-q", "--no-verify", "-m", message )
    return _git( repo, "rev-parse", "HEAD" ).stdout.strip()


@pytest.fixture
def work( tmp_path ):
    """A scratch repository with the real gate and lint package tracked, the hook installed, and a bare remote."""
    repo, remote = tmp_path / "work", tmp_path / "remote.git"
    repo.mkdir()
    _git( tmp_path, "init", "-q", "--bare", str( remote ) )
    _git( repo, "init", "-q", "-b", "main" )
    for rel in TRACKED:
        ( repo / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copy( os.path.join( PROJECT_ROOT, rel ), repo / rel )
    lint_src = os.path.join( PROJECT_ROOT, "src", "cosa", "repo", "doc_lint" )
    lint_dst = repo / "src" / "cosa" / "repo" / "doc_lint"
    lint_dst.mkdir( parents=True )
    for name in os.listdir( lint_src ):
        if name.endswith( ( ".py", ".txt" ) ): shutil.copy( os.path.join( lint_src, name ), lint_dst / name )
    _write( repo, "src/cosa/__init__.py", "" )
    _write( repo, "src/cosa/repo/__init__.py", "" )
    _write( repo, ".gitignore", ".venv\n.claude/\n" )
    os.symlink( VENV, repo / ".venv" )
    os.symlink( HOOK, repo / ".git" / "hooks" / "pre-push" )
    _git( repo, "remote", "add", "origin", str( remote ) )
    return repo, remote


def _remote_has( remote, ref ):
    return _git( remote, "rev-parse", "--verify", "--quiet", ref, check=False ).returncode == 0


def test_a_clean_commit_is_pushed( work ):
    repo, remote = work
    _write( repo, "src/app/a.py", CLEAN )
    sha = _commit( repo, "clean" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode == 0, done.stderr
    assert "DOCLINT GATE PASSED" in done.stderr
    assert _git( remote, "rev-parse", "refs/heads/main" ).stdout.strip() == sha


def test_a_commit_with_a_finding_is_refused_and_never_reaches_the_remote( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    sha = _commit( repo, "loud" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode != 0
    assert "src/app/loud.py:2: caps: ALL-CAPS word NEVER" in done.stderr
    assert f"[pre-push-chain] REFUSED the push: {sha[ :9 ]} holds documentation lint findings" in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_the_pushed_commit_is_checked_not_the_working_tree( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _write( repo, "src/app/loud.py", CLEAN )    # fixed on disk, not committed

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode != 0
    assert not _remote_has( remote, "refs/heads/main" )


def test_no_verify_is_the_escape_hatch( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    sha = _commit( repo, "loud" )

    done = _git( repo, "push", "-q", "--no-verify", "origin", "main", check=False )

    assert done.returncode == 0, done.stderr
    assert _git( remote, "rev-parse", "refs/heads/main" ).stdout.strip() == sha


def test_a_commit_from_before_the_gate_is_allowed_with_a_loud_line( work ):
    repo, remote = work
    _git( repo, "rm", "-q", "--cached", "-r", "src/tests" , check=False )
    shutil.rmtree( repo / "src" / "tests" )
    _write( repo, "src/app/loud.py", LOUD )
    sha = _commit( repo, "no gate in this commit" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode == 0, done.stderr
    assert f"[pre-push-chain] SKIPPED doc-lint for {sha[ :9 ]}: that commit has no src/tests/run-doclint-gate.sh" in done.stderr
    assert _remote_has( remote, "refs/heads/main" )


def test_a_gate_that_cannot_check_refuses_the_push( work ):
    repo, remote = work
    _write( repo, "src/app/a.py", CLEAN )
    os.remove( repo / "src" / "conf" / "dm-tutor-lowercase-words.txt" )
    sha = _commit( repo, "the word list is gone" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode != 0
    assert f"[pre-push-chain] REFUSED the push: the doc-lint gate could not check {sha[ :9 ]} (exit 2)." in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_a_commit_that_removes_the_gate_its_history_held_is_refused( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud, with the gate present" )
    os.remove( repo / "src" / "tests" / "run-doclint-gate.sh" )
    sha = _commit( repo, "the gate script is deleted" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode != 0
    assert f"[pre-push-chain] REFUSED: {sha[ :9 ]} has removed src/tests/run-doclint-gate.sh, which its history held." in done.stderr
    assert "SKIPPED" not in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_a_tip_that_cannot_be_checked_out_refuses_the_push( work ):
    repo, remote = work
    _write( repo, "src/app/a.py", CLEAN )
    sha = _commit( repo, "clean" )
    _write( repo, ".claude/worktrees", "a file where the worktree directory must go\n" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode != 0
    assert f"[pre-push-chain] REFUSED: could not check out {sha[ :9 ]} to lint it. Nothing was checked." in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_two_refs_at_one_commit_are_linted_once( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )

    done = _git( repo, "push", "-q", "origin", "main", "main:refs/heads/copy", check=False )

    assert done.returncode != 0
    assert done.stderr.count( "DOCLINT GATE FAILED" ) == 1
    assert not _remote_has( remote, "refs/heads/main" ) and not _remote_has( remote, "refs/heads/copy" )


def test_one_bad_ref_among_two_refuses_the_whole_push( work ):
    repo, remote = work
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )
    _git( repo, "branch", "good" )
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )

    done = _git( repo, "push", "-q", "origin", "good", "main", check=False )

    assert done.returncode != 0
    assert "DOCLINT GATE PASSED" in done.stderr and "DOCLINT GATE FAILED" in done.stderr
    assert not _remote_has( remote, "refs/heads/good" ) and not _remote_has( remote, "refs/heads/main" )


def test_a_tag_on_a_commit_with_a_finding_is_refused( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _git( repo, "tag", "-a", "v1", "-m", "an annotated tag" )

    done = _git( repo, "push", "-q", "origin", "v1", check=False )

    assert done.returncode != 0
    assert "DOCLINT GATE FAILED" in done.stderr
    assert not _remote_has( remote, "refs/tags/v1" )


def test_only_the_tip_is_checked_so_a_finding_fixed_below_the_tip_is_pushed( work ):
    repo, remote = work
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _write( repo, "src/app/loud.py", CLEAN )
    sha = _commit( repo, "reworded" )

    done = _git( repo, "push", "-q", "origin", "main", check=False )

    assert done.returncode == 0, done.stderr
    assert _git( remote, "rev-parse", "refs/heads/main" ).stdout.strip() == sha


def test_deleting_a_remote_branch_is_not_checked( work ):
    repo, remote = work
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )
    _git( repo, "push", "-q", "origin", "main:refs/heads/topic" )
    assert _remote_has( remote, "refs/heads/topic" )

    done = _git( repo, "push", "-q", "origin", ":refs/heads/topic", check=False )

    assert done.returncode == 0, done.stderr
    assert "DOCLINT GATE" not in done.stderr
    assert not _remote_has( remote, "refs/heads/topic" )


def test_the_throwaway_worktree_is_removed_after_a_pass_and_after_a_refusal( work ):
    repo, remote = work
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )
    _git( repo, "push", "-q", "origin", "main" )
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _git( repo, "push", "-q", "origin", "main", check=False )

    assert _git( repo, "worktree", "list" ).stdout.count( "\n" ) == 1
    leftovers = os.listdir( repo / ".claude" / "worktrees" ) if ( repo / ".claude" / "worktrees" ).is_dir() else []
    assert leftovers == []
