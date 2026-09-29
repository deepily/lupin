"""
A seat's tree is reused only when nobody is in it (row 81714af0).

MEASURED 2026-09-29: spawn_sessions handed a manager's live working tree, uncommitted edits
and all, to a brand-new worker, because the tree is keyed on the seat NAME and nothing asked
who was in it. Two sessions in one tree is the shared-index hazard the per-seat trees exist
to prevent.

Everything here is real: a real git repository, the real provisioning script, a real
`git worktree add`, and for the live-process arm a real child process whose cwd is the tree.
Only `_resolve_project_root` is stood down, as in test_every_seat_gets_its_own_working_tree.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cosa.utils.seat_worktree import provision_seat_worktree
from lupin_mcp import session_spawner


def _repo_under_test():
    return Path( session_spawner.__file__ ).resolve().parents[ 2 ]


def _git( *args, cwd ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True )


@pytest.fixture
def main_repo():
    with tempfile.TemporaryDirectory() as tmp:
        main = Path( tmp ) / "projects" / "demo"
        ( main / "src" / "scripts" ).mkdir( parents=True )
        for script in ( "provision-seat-worktree.sh", "link-worktree-venv.sh" ):
            shutil.copy( _repo_under_test() / "src" / "scripts" / script, main / "src" / "scripts" / script )
        _git( "init", "-q", cwd=main )
        _git( "config", "user.email", "t@example.com", cwd=main )
        _git( "config", "user.name", "t", cwd=main )
        _git( "add", "-A", cwd=main )
        _git( "commit", "-q", "-m", "seed", cwd=main )
        yield main


def _first_tree( main ):
    """Provision seat 'seat-a' once and return its (real) tree path."""
    first = provision_seat_worktree( str( main ), "seat-a" )
    assert first[ "status" ] == "created", first
    return Path( first[ "work_dir" ] )


def test_a_clean_idle_tree_is_reused_as_before( main_repo ):
    tree   = _first_tree( main_repo )
    second = provision_seat_worktree( str( main_repo ), "seat-a" )
    assert second[ "status" ] == "reused"
    assert Path( second[ "work_dir" ] ) == tree


def _edit_and_memento( tree, memento_text, memento_age_secs ):
    """Edit a tracked file NOW; write a memento whose mtime is `memento_age_secs` OLDER than that edit."""
    import os, time
    edited = tree / "src" / "scripts" / "link-worktree-venv.sh"
    edited.write_text( "# an uncommitted edit\n" )
    memento = tree / ".claude-memento-someone.md"
    memento.write_text( memento_text )
    t = time.time()
    os.utime( edited,  ( t, t ) )
    os.utime( memento, ( t - memento_age_secs, t - memento_age_secs ) )


def test_a_tree_with_a_live_process_inside_it_is_not_reused( main_repo ):
    tree = _first_tree( main_repo )
    # cwd-identified, not PID-identified: the child is found through /proc/<pid>/cwd.
    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(60)" ], cwd=tree )
    try:
        second = provision_seat_worktree( str( main_repo ), "seat-a" )
    finally:
        child.kill(); child.wait()
    assert second[ "status" ] == "occupied", second
    assert second[ "provisioned" ] is False
    assert second[ "work_dir" ] is None, "an occupied tree must not be handed back as the seat's cwd"
    assert "live process" in second[ "occupied_reason" ]
    assert Path( second[ "occupied_tree" ] ) == tree


def test_the_same_tree_is_reused_again_once_the_process_has_left( main_repo ):
    """THE CONTROL: the refusal is about the live process, not a permanent mark on the tree."""
    tree  = _first_tree( main_repo )
    child = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(60)" ], cwd=tree )
    child.kill(); child.wait()
    assert provision_seat_worktree( str( main_repo ), "seat-a" )[ "status" ] == "reused"


def test_a_dirty_tree_with_no_memento_is_not_reused( main_repo ):
    tree = _first_tree( main_repo )
    ( tree / "src" / "scripts" / "link-worktree-venv.sh" ).write_text( "# an adopter's uncommitted edit\n" )
    second = provision_seat_worktree( str( main_repo ), "seat-a" )
    assert second[ "status" ] == "occupied", second
    assert "uncommitted" in second[ "occupied_reason" ]
    assert second[ "work_dir" ] is None


def test_a_dirty_tree_claimed_by_a_memento_is_reused( main_repo ):
    """A re-spun seat comes back to its own work: its memento is the claim."""
    tree = _first_tree( main_repo )
    # mtimes set explicitly: two writes inside one filesystem clock tick compare equal.
    _edit_and_memento( tree, "memento\n", memento_age_secs=-5 )
    second = provision_seat_worktree( str( main_repo ), "seat-a" )
    assert second[ "status" ] == "reused", second
    assert Path( second[ "work_dir" ] ) == tree


def test_an_old_memento_and_a_later_edit_is_occupied( main_repo ):
    """Rick's rule via Mr. Radio: a memento older than the newest change claims nothing."""
    tree = _first_tree( main_repo )
    _edit_and_memento( tree, "memento for another seat\n", memento_age_secs=60 )
    second = provision_seat_worktree( str( main_repo ), "seat-a" )
    assert second[ "status" ] == "occupied", second
    assert "no memento claims" in second[ "occupied_reason" ]


def test_an_old_memento_that_names_the_seat_still_claims_the_tree( main_repo ):
    tree = _first_tree( main_repo )
    _edit_and_memento( tree, "resume seat-a here\n", memento_age_secs=60 )
    assert provision_seat_worktree( str( main_repo ), "seat-a" )[ "status" ] == "reused"


def test_a_newer_memento_claims_the_edit_even_without_naming_the_seat( main_repo ):
    tree = _first_tree( main_repo )
    _edit_and_memento( tree, "memento for another seat\n", memento_age_secs=-60 )
    assert provision_seat_worktree( str( main_repo ), "seat-a" )[ "status" ] == "reused"


def test_untracked_memento_alone_does_not_make_a_clean_tree_occupied( main_repo ):
    tree = _first_tree( main_repo )
    ( tree / ".claude-memento-seat-a.md" ).write_text( "memento\n" )
    assert provision_seat_worktree( str( main_repo ), "seat-a" )[ "status" ] == "reused"


class _Runner:
    def __init__( self ): self.calls = []
    def __call__( self, argv, env=None ):
        self.calls.append( argv )
        class R: returncode = 0
        return R()


def _spawn( monkeypatch, root ):
    monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda project: str( root ) )
    with tempfile.TemporaryDirectory() as sd:
        return session_spawner.spawn_sessions( 1, "task", "mgr-sid", script_path="/bin/true", project="demo",
                                               session_dir=Path( sd ), dry_run=False, runner=_Runner() )


def test_spawn_skips_an_occupied_slot_and_takes_the_next_free_one( monkeypatch, main_repo ):
    first      = _spawn( monkeypatch, main_repo )[ "spawned" ][ 0 ]
    first_tree = Path( first[ "work_dir" ] )
    ( first_tree / "src" / "scripts" / "link-worktree-venv.sh" ).write_text( "# a manager's adopted work\n" )

    # A fresh manifest, so the spawner would again pick index 1 — the occupied slot.
    second = _spawn( monkeypatch, main_repo )[ "spawned" ][ 0 ]
    assert second[ "session_name" ] != first[ "session_name" ]
    assert second[ "session_name" ].endswith( "-2" ), second[ "session_name" ]
    assert Path( second[ "work_dir" ] ) != first_tree
    assert second[ "worktree_status" ] == "created"
    # The manager's edit is exactly where it was left.
    assert ( first_tree / "src" / "scripts" / "link-worktree-venv.sh" ).read_text() == "# a manager's adopted work\n"
