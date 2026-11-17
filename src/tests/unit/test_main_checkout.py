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


def test_the_default_timeout_is_ten_seconds_and_a_caller_can_change_it():
    """The timeout reaches the runner unchanged, so a slow caller can ask for more."""
    seen = []
    def run( argv, cwd=None, timeout=None ):
        seen.append( timeout )
        return SimpleNamespace( returncode=0, stdout="/r/.git\n" )
    mc.main_checkout_of( "/x", run )
    mc.main_checkout_of( "/x", run, timeout=60 )
    assert seen == [ 10, 60 ]


def test_a_runner_that_returns_no_stdout_answers_none():
    """A runner that leaves stdout as None is not a path."""
    run = lambda argv, cwd=None, timeout=None: SimpleNamespace( returncode=0, stdout=None )
    assert mc.main_checkout_of( "/x", run ) is None


def test_a_runner_that_raises_anything_answers_none():
    """The teardown's injected runner could raise any error, and it still must not raise."""
    def run( argv, cwd=None, timeout=None ): raise RuntimeError( "boom" )
    assert mc.main_checkout_of( "/x", run ) is None


def test_the_teardown_keeps_its_sixty_second_limit_and_its_never_raises_contract():
    """_main_root hands the runner a 60 second limit and answers None when the runner raises."""
    from cosa.agents.shared import seat_teardown as st
    seen = []
    def run( argv, cwd=None, timeout=None ):
        seen.append( timeout )
        return SimpleNamespace( returncode=0, stdout="/r/main/.git\n" )
    def bad( argv, cwd=None, timeout=None ): raise RuntimeError( "boom" )
    assert st._main_root( "/t", run ) == "/r/main"
    assert seen == [ 60 ]
    assert st._main_root( "/t", bad ) is None


def test_seat_worktree_resolves_a_symlinked_owner_to_its_real_path( tmp_path, monkeypatch ):
    """The provisioning guard compares real paths, so a symlinked answer must be resolved."""
    from cosa.utils import seat_worktree as sw
    real = ( tmp_path / "real" ).resolve()
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to( real )
    monkeypatch.setattr( sw, "main_checkout_of", lambda path: str( link ) )
    assert sw._main_checkout_of( "/anywhere" ) == str( real )


def test_session_spawner_resolves_a_symlinked_owner_to_its_real_path( tmp_path, monkeypatch ):
    """The spawner's main checkout is the resolved path, not the symlink git printed."""
    from lupin_mcp import session_spawner as sp
    real = ( tmp_path / "real" ).resolve()
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to( real )
    monkeypatch.setattr( sp, "main_checkout_of", lambda start: str( link ) )
    assert sp._main_checkout_of( Path( "/anywhere" ) ) == real


def test_the_straggler_stamp_helpers_default_to_the_one_shared_git_runner():
    """The stamp helpers hold no git runner of their own: their default is main_checkout.run_git."""
    from cosa.agents.shared import worktree_straggler_tickets as st
    assert st.run_git is mc.run_git
    assert not hasattr( st, "_plain_run" )
    assert mc.run_git.__defaults__ == ( None, 10 ), "the shared runner keeps its ten second default; the stamp helpers pass their own sixty"
