"""
Unit tests for memento_repo_root's refusal paths, driven by a fake git runner.

Requires:
    - lupin_mcp.memento_repo_root is importable

Ensures:
    - a git that raises, or a root slot with no start or no working tree, returns None and warns once
"""

from pathlib import Path

from lupin_mcp import memento_repo_root as mrr


def test_a_runner_that_raises_is_no_answer_not_an_exception( tmp_path ):
    """_git_answer swallows the runner's exception and returns None."""
    def boom( argv, cwd ): raise OSError( "git missing" )
    assert mrr._git_answer( tmp_path, "--show-toplevel", boom ) is None


def test_a_relative_answer_resolves_against_start( tmp_path ):
    """A relative answer such as '.git' is read from start, then resolved."""
    assert mrr._git_answer( tmp_path, "--git-common-dir", lambda argv, cwd: ".git\n" ) == ( tmp_path / ".git" ).resolve()


def test_the_root_slot_refuses_a_none_start_and_says_so():
    """No start: None, one warning naming the root slot, and git is never asked."""
    warnings, calls = [], []
    got = mrr.slot_base_root( None, mrr.SLOT_ROOT, run_fn=lambda a, c: calls.append( a ), warn_fn=warnings.append )
    assert got is None and calls == []
    assert len( warnings ) == 1 and "root slot from None" in warnings[ 0 ]


def test_the_root_slot_refuses_when_git_cannot_name_a_working_tree( tmp_path ):
    """git answers blank: None and one warning that names the start path."""
    warnings = []
    got = mrr.slot_base_root( tmp_path, mrr.SLOT_ROOT, run_fn=lambda a, c: "", warn_fn=warnings.append )
    assert got is None
    assert len( warnings ) == 1 and str( tmp_path ) in warnings[ 0 ] and "root slot" in warnings[ 0 ]


def test_the_root_slot_returns_the_toplevel_git_names( tmp_path ):
    """The seat's own toplevel, as a resolved Path, with no warning."""
    warnings = []
    got = mrr.slot_base_root( tmp_path, mrr.SLOT_ROOT, run_fn=lambda a, c: f"{tmp_path}\n", warn_fn=warnings.append )
    assert got == Path( tmp_path ).resolve() and warnings == []
