"""
The pre-push hook, driven by real pushes from a scratch repository to a scratch bare remote.

The hook checks the tip of each pushed ref. The gate code, the word list and the epoch commit come
from the tree the hook is installed from; the files that are linted come from the pushed tip. So
each test builds two things: a hook tree, and a separate repository that is pushed. The pushed
repository holds no gate code at all, which is the case a deleted gate script would produce.

Each test asserts what git said and whether the remote received the ref. A hook that prints a
refusal and still lets the push through looks the same on the terminal.
"""

import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
VENV         = os.path.join( PROJECT_ROOT, ".venv" )
HOOK_FILES   = (
    "src/scripts/pre-push-chain.sh",
    "src/tests/run-doclint-gate.sh",
    "src/scripts/lib/resolve-venv-pytest.sh",
    "src/conf/dm-tutor-lowercase-words.txt",
)
EPOCH_REL    = "src/conf/doc-gate-epoch.txt"
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
    _git( repo, "commit", "-q", "--no-verify", "--allow-empty", "-m", message )
    return _git( repo, "rev-parse", "HEAD" ).stdout.strip()


@pytest.fixture
def rig( tmp_path ):
    """
    A hook tree, a repository with the hook installed from it, and a bare remote.

    The repository's first commit is recorded as the epoch, so every later commit descends from it.
    """
    hook_tree, repo, remote = tmp_path / "hooktree", tmp_path / "work", tmp_path / "remote.git"
    for rel in HOOK_FILES:
        ( hook_tree / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copy( os.path.join( PROJECT_ROOT, rel ), hook_tree / rel )
    os.symlink( os.path.join( PROJECT_ROOT, "src", "cosa" ), hook_tree / "src" / "cosa" )
    os.symlink( VENV, hook_tree / ".venv" )

    repo.mkdir()
    _git( tmp_path, "init", "-q", "--bare", str( remote ) )
    _git( repo, "init", "-q", "-b", "main" )
    _write( repo, ".gitignore", ".claude/\n" )
    epoch = _commit( repo, "the epoch" )
    _write( hook_tree, EPOCH_REL, f"# the gate applies from here\n{epoch}\n" )
    os.symlink( hook_tree / "src" / "scripts" / "pre-push-chain.sh", repo / ".git" / "hooks" / "pre-push" )
    _git( repo, "remote", "add", "origin", str( remote ) )
    return hook_tree, repo, remote


def _remote_has( remote, ref ):
    return _git( remote, "rev-parse", "--verify", "--quiet", ref, check=False ).returncode == 0


def _push( repo, *refs ):
    return _git( repo, "push", "-q", "origin", *refs, check=False )


def test_a_clean_tip_is_pushed( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/a.py", CLEAN )
    sha = _commit( repo, "clean" )

    done = _push( repo, "main" )

    assert done.returncode == 0, done.stderr
    assert "DOCLINT GATE PASSED" in done.stderr
    assert _git( remote, "rev-parse", "refs/heads/main" ).stdout.strip() == sha


def test_a_tip_with_a_finding_is_refused_though_it_holds_no_gate_script( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    sha = _commit( repo, "loud" )

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert "src/app/loud.py:2: caps: ALL-CAPS word NEVER" in done.stderr
    assert f"[pre-push-chain] REFUSED the push: {sha[ :9 ]} holds documentation lint findings" in done.stderr
    assert "SKIPPED" not in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_the_pushed_tip_is_checked_not_the_working_tree( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _write( repo, "src/app/loud.py", CLEAN )    # fixed on disk, not committed

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert not _remote_has( remote, "refs/heads/main" )


def test_a_word_list_emptied_in_the_pushed_tree_does_not_switch_the_rule_off( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    _write( repo, "src/conf/dm-tutor-lowercase-words.txt", "" )
    _commit( repo, "loud, with its own empty word list" )

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert "caps: ALL-CAPS word NEVER" in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_no_verify_is_the_escape_hatch( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    sha = _commit( repo, "loud" )

    done = _git( repo, "push", "-q", "--no-verify", "origin", "main", check=False )

    assert done.returncode == 0, done.stderr
    assert _git( remote, "rev-parse", "refs/heads/main" ).stdout.strip() == sha


def test_a_tip_that_does_not_descend_from_the_epoch_is_pushed_with_a_loud_line( rig ):
    hook_tree, repo, remote = rig
    epoch = _git( repo, "rev-parse", "HEAD" ).stdout.strip()
    _git( repo, "checkout", "-q", "--orphan", "old" )
    _write( repo, "src/app/loud.py", LOUD )
    sha = _commit( repo, "a branch from before the gate" )

    done = _push( repo, "old" )

    assert done.returncode == 0, done.stderr
    assert f"[pre-push-chain] SKIPPED doc-lint for {sha[ :9 ]}: it does not descend from the gate's epoch {epoch[ :9 ]}, so it predates the gate" in done.stderr
    assert "DOCLINT GATE" not in done.stderr
    assert _remote_has( remote, "refs/heads/old" )


def test_a_checked_tip_with_no_swept_file_is_refused_as_unchecked( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "notes.md", "# notes\n" )
    sha = _commit( repo, "no python at all" )

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert "REFUSING: no swept file found" in done.stderr
    assert f"[pre-push-chain] REFUSED the push: the doc-lint gate could not check {sha[ :9 ]} (exit 2)." in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


@pytest.mark.parametrize( "content", [ None, "# only a comment\n", "0123456789abcdef0123456789abcdef01234567\n" ] )
def test_a_missing_empty_or_unknown_epoch_refuses_the_push( rig, content ):
    hook_tree, repo, remote = rig
    os.remove( hook_tree / EPOCH_REL )
    if content is not None: _write( hook_tree, EPOCH_REL, content )
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert "[pre-push-chain] REFUSED: no usable epoch commit in " in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_a_hook_tree_with_no_gate_script_refuses_the_push( rig ):
    hook_tree, repo, remote = rig
    os.remove( hook_tree / "src" / "tests" / "run-doclint-gate.sh" )
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert "[pre-push-chain] REFUSED: no gate script at " in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_a_tip_that_cannot_be_checked_out_refuses_the_push( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/a.py", CLEAN )
    sha = _commit( repo, "clean" )
    _write( repo, ".claude/worktrees", "a file where the worktree directory must go\n" )

    done = _push( repo, "main" )

    assert done.returncode != 0
    assert f"[pre-push-chain] REFUSED: could not check out {sha[ :9 ]} to lint it. Nothing was checked." in done.stderr
    assert not _remote_has( remote, "refs/heads/main" )


def test_two_refs_at_one_commit_are_linted_once( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )

    done = _push( repo, "main", "main:refs/heads/copy" )

    assert done.returncode != 0
    assert done.stderr.count( "DOCLINT GATE FAILED" ) == 1
    assert not _remote_has( remote, "refs/heads/main" ) and not _remote_has( remote, "refs/heads/copy" )


def test_one_bad_ref_among_two_refuses_the_whole_push( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )
    _git( repo, "branch", "good" )
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )

    done = _push( repo, "good", "main" )

    assert done.returncode != 0
    assert "DOCLINT GATE PASSED" in done.stderr and "DOCLINT GATE FAILED" in done.stderr
    assert not _remote_has( remote, "refs/heads/good" ) and not _remote_has( remote, "refs/heads/main" )


def test_an_annotated_tag_on_a_commit_with_a_finding_is_refused( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _git( repo, "tag", "-a", "v1", "-m", "an annotated tag" )

    done = _push( repo, "v1" )

    assert done.returncode != 0
    assert "DOCLINT GATE FAILED" in done.stderr
    assert not _remote_has( remote, "refs/tags/v1" )


def test_only_the_tip_is_checked_so_a_finding_fixed_below_the_tip_is_pushed( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _write( repo, "src/app/loud.py", CLEAN )
    sha = _commit( repo, "reworded" )

    done = _push( repo, "main" )

    assert done.returncode == 0, done.stderr
    assert _git( remote, "rev-parse", "refs/heads/main" ).stdout.strip() == sha


def test_deleting_a_remote_branch_is_not_checked( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )
    _git( repo, "push", "-q", "origin", "main:refs/heads/topic" )
    assert _remote_has( remote, "refs/heads/topic" )

    done = _push( repo, ":refs/heads/topic" )

    assert done.returncode == 0, done.stderr
    assert "DOCLINT GATE" not in done.stderr
    assert not _remote_has( remote, "refs/heads/topic" )


def test_the_throwaway_worktree_is_removed_after_a_pass_and_after_a_refusal( rig ):
    hook_tree, repo, remote = rig
    _write( repo, "src/app/a.py", CLEAN )
    _commit( repo, "clean" )
    _git( repo, "push", "-q", "origin", "main" )
    _write( repo, "src/app/loud.py", LOUD )
    _commit( repo, "loud" )
    _push( repo, "main" )

    assert _git( repo, "worktree", "list" ).stdout.count( "\n" ) == 1
    leftovers = os.listdir( repo / ".claude" / "worktrees" ) if ( repo / ".claude" / "worktrees" ).is_dir() else []
    assert leftovers == []


def test_the_recorded_epoch_is_an_ancestor_of_the_tree_it_sits_in():
    with open( os.path.join( PROJECT_ROOT, EPOCH_REL ), encoding="utf-8" ) as handle:
        shas = [ line.strip() for line in handle if line.strip() and not line.lstrip().startswith( "#" ) ]

    assert len( shas ) == 1 and len( shas[ 0 ] ) == 40
    done = subprocess.run( [ "git", "-C", PROJECT_ROOT, "merge-base", "--is-ancestor", shas[ 0 ], "HEAD" ], capture_output=True, text=True, timeout=60 )
    assert done.returncode == 0, f"{shas[ 0 ]} is not an ancestor of HEAD in {PROJECT_ROOT}: {done.stderr}"
