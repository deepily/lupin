"""Tests for cosa.utils.main_checkout, the one main-checkout resolver for non-hook code."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cosa.utils import main_checkout as mc


def _git( cwd, *args ):
    subprocess.run( [ "git", *args ], cwd=cwd, check=True, capture_output=True )


@pytest.fixture
def repo_with_worktree( tmp_path ):
    """A real repository with one linked worktree, made by git itself."""
    main = ( tmp_path / "main" ).resolve()
    main.mkdir()
    _git( main, "init", "-q" )
    _git( main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x" )
    linked = tmp_path / "linked"
    _git( main, "worktree", "add", "-q", "--detach", str( linked ) )
    return main, linked.resolve()


def test_a_linked_worktree_resolves_to_its_main_checkout( repo_with_worktree ):
    """The real producer names the main tree from inside the linked one."""
    main, linked = repo_with_worktree
    assert mc.main_checkout_of( linked ) == str( main )


def test_the_main_checkout_resolves_to_itself( repo_with_worktree ):
    """git prints a relative .git here; the absolute format makes the parent right."""
    main, _ = repo_with_worktree
    assert mc.main_checkout_of( main ) == str( main )


def test_a_folder_outside_any_repository_answers_none( tmp_path ):
    """Git exits non-zero, which is None and not a guess."""
    assert mc.main_checkout_of( tmp_path ) is None


def test_a_missing_folder_answers_none( tmp_path ):
    """The OSError from a folder that does not exist is swallowed."""
    assert mc.main_checkout_of( tmp_path / "nope" ) is None


def test_a_runner_that_times_out_answers_none():
    """A timeout is a SubprocessError, which is None."""
    def run( argv, cwd=None, timeout=None ): raise subprocess.TimeoutExpired( "git", 10 )
    assert mc.main_checkout_of( "/x", run ) is None


@pytest.mark.parametrize( "returncode, stdout", [ ( 128, "/a/.git\n" ), ( 0, "" ), ( 0, "\n" ) ] )
def test_a_failed_or_empty_answer_is_none( returncode, stdout ):
    """A non-zero exit is not trusted even when it printed a path."""
    run = lambda argv, cwd=None, timeout=None: SimpleNamespace( returncode=returncode, stdout=stdout )
    assert mc.main_checkout_of( "/x", run ) is None


def test_the_injected_runner_gets_the_path_as_its_cwd():
    """The path reaches git as cwd, and the answer is the parent of the common dir."""
    seen = {}
    def run( argv, cwd=None, timeout=None ):
        seen[ "cwd" ], seen[ "argv" ] = cwd, argv
        return SimpleNamespace( returncode=0, stdout="/r/main/.git/\n" )
    assert mc.main_checkout_of( Path( "/some/tree" ), run ) == "/r/main"
    assert seen[ "cwd" ] == "/some/tree"
    assert seen[ "argv" ][ -1 ] == "--git-common-dir"
