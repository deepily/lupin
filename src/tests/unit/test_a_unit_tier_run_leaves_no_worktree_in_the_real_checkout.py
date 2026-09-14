"""
A unit-tier run must leave no worktree behind in the box's real checkout.

Row 033538f6 (2026-09-14). Spawn-mechanics tests drive `spawn_sessions` for real with a
fake runner and never stub seat provisioning, so each tier run created one permanent tree
per seat name in the real repo: 26 re-appeared within 13 seconds of the first run after
the 233-tree removal. The unit conftest now names the real checkout in
LUPIN_SEAT_WORKTREE_REFUSE_ROOT, and the provisioner refuses it.
"""

import subprocess
from pathlib import Path

from cosa.utils import seat_worktree
import cosa.utils.util as cu
from lupin_mcp import session_spawner


def _registered( root ):
    out = subprocess.run( [ "git", "-C", root, "worktree", "list", "--porcelain" ], capture_output=True, text=True ).stdout
    return { line[ len( "worktree " ): ] for line in out.splitlines() if line.startswith( "worktree " ) }


class _Runner:
    def __init__( self ): self.calls = []
    def __call__( self, argv, env=None ):
        self.calls.append( argv )
        class R: returncode = 0
        return R()


def test_the_conftest_names_the_real_main_checkout():
    named = Path( __import__( "os" ).environ[ seat_worktree.REFUSE_ROOT_ENV ] )
    assert ( named / ".git" ).is_dir(), f"the refused root is not a main checkout: {named}"
    assert named.resolve() == Path( seat_worktree._main_checkout_of( cu.get_project_root() ) )


def test_a_real_spawn_with_a_fake_runner_creates_no_tree_in_the_real_checkout( tmp_path ):
    """The measured leak, reproduced: the exact call shape the persona-chain tests use."""
    main   = seat_worktree._main_checkout_of( cu.get_project_root() )
    before = _registered( main )

    result = session_spawner.spawn_sessions( 1, "t", "sid-leak-probe", script_path="x",
                                             runner=_Runner(), session_dir=tmp_path )

    assert _registered( main ) == before, "a unit test created a worktree in the real checkout"
    assert result[ "spawned" ][ 0 ][ "worktree_status" ] == "refused_root"


def test_the_guard_does_not_touch_a_temporary_repo( tmp_path ):
    """CONTROL — the provisioning tests build their own repo and must still get a real tree."""
    repo = tmp_path / "demo"
    ( repo / "src" / "scripts" ).mkdir( parents=True )
    script = Path( cu.get_project_root() ) / "src" / "scripts" / "provision-seat-worktree.sh"
    ( repo / "src" / "scripts" / "provision-seat-worktree.sh" ).write_text( script.read_text() )
    for args in ( [ "init", "-q" ], [ "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A" ],
                  [ "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed" ] ):
        subprocess.run( [ "git", "-C", str( repo ), *args ], check=True )

    result = seat_worktree.provision_seat_worktree( str( repo ), "seat-alpha" )

    assert result[ "status" ] == "created", result
