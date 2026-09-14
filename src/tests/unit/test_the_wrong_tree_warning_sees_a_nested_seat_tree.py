"""
The wrong-tree warning must still fire for a caller in a seat tree NESTED inside LUPIN_ROOT.

Row 033538f6 (Rick, 2026-09-14) moved seat trees from next to the repo to inside it:
`<main>/.claude/worktrees/seat-<name>`. The detector's fast path returns early for any
caller under `root` by path COMPONENTS, which was right while every worktree was a sibling.
A nested tree sits under `root` by components too, so without a carve-out the fast path
would swallow exactly the population the detector exists to catch. That is the same defect
the separator fix closed for siblings, arriving from the other direction (Mr. Radio named it
in review).

The caller is simulated by compiling a one-line call under a filename inside each tree, so
the detector's own frame walk reads that path. Its tree test runs against a REAL git
layout: a main checkout and a real linked worktree.
"""

import subprocess

import pytest

import cosa.utils.util as cu


def _git( *args, cwd ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True )


@pytest.fixture
def layout( tmp_path, monkeypatch ):
    monkeypatch.setattr( cu, "_wrong_tree_warned", set() )
    main = tmp_path / "projects" / "lupin"
    ( main / "src" ).mkdir( parents=True )
    ( main / "src" / "seed.py" ).write_text( "" )
    _git( "init", "-q", cwd=main )
    _git( "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=main )
    _git( "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed", cwd=main )
    nested  = main / ".claude" / "worktrees" / "seat-cc-author-maria-1"
    sibling = main.parent / "lupin-wt-old-style"
    for tree in ( nested, sibling ):
        assert _git( "worktree", "add", "-q", "--detach", str( tree ), "HEAD", cwd=main ).returncode == 0
    return main, nested, sibling


def _call_from( caller_path, root ):
    code = compile( "cu._warn_once_if_caller_is_in_another_tree( root )", str( caller_path ), "exec" )
    exec( code, { "cu": cu, "root": str( root ) } )


def test_a_caller_in_a_nested_seat_tree_is_warned( layout, capsys ):
    main, nested, _ = layout
    _call_from( nested / "src" / "seed.py", main )
    assert "WRONG-TREE WARNING" in capsys.readouterr().err, \
        "a seat tree nested inside LUPIN_ROOT took the fast path and the warning went blind"


def test_a_caller_in_the_main_checkout_is_still_the_quiet_ordinary_case( layout, capsys ):
    """CONTROL — the carve-out must not make every ordinary run noisy."""
    main, _, _ = layout
    _call_from( main / "src" / "seed.py", main )
    assert capsys.readouterr().err == ""


def test_a_sibling_worktree_is_still_warned( layout, capsys ):
    """CONTROL — the separator fix this sits beside still holds."""
    main, _, sibling = layout
    _call_from( sibling / "src" / "seed.py", main )
    assert "WRONG-TREE WARNING" in capsys.readouterr().err


def test_a_caller_in_the_seat_tree_it_points_at_is_quiet( layout, capsys ):
    """When LUPIN_ROOT IS the seat tree, a caller inside it is the ordinary case."""
    _, nested, _ = layout
    _call_from( nested / "src" / "seed.py", nested )
    assert capsys.readouterr().err == ""
