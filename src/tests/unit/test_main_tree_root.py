"""
main_tree_root — fleet logs resolve to the main tree, never a seat's tree (row aec2319f).

Measured 2026-10-02: the janitor refused 6 of 6 seat trees for holding ignored files that
are not build output, and for 2 of them the files were fleet logs the seat's own machinery
wrote (io/commons, io/worktree-janitor/seat-teardown.jsonl).
"""

import os

import pytest

from lupin_cli.claude_code.hooks.lib.main_tree import WORKTREE_LANE_MARK, main_tree_root
from lupin_cli.claude_code.hooks import session_end
from lupin_mcp.commons_store import CommonsStore


MAIN = os.path.join( os.sep, "repos", "lupin" )
SEAT = os.path.join( MAIN, ".claude", "worktrees", "seat-cc-author-x-1" )


@pytest.mark.parametrize( "path, expected", [
    ( MAIN,                                                       MAIN ),
    ( SEAT,                                                       MAIN ),
    ( os.path.join( SEAT, "src", "cosa" ),                        MAIN ),
    ( os.path.join( MAIN, ".claude", "worktrees" ),               MAIN ),
    ( os.path.join( SEAT, ".claude", "worktrees", "inner" ),      MAIN ),
    ( os.path.join( MAIN, ".claude", "worktrees-old", "t" ),      os.path.join( MAIN, ".claude", "worktrees-old", "t" ) ),
    ( os.path.join( os.sep, ".claude", "worktrees", "t" ),        os.sep ),
] )
def test_main_tree_root_cuts_at_the_outermost_lane( path, expected ):
    assert main_tree_root( path ) == expected


def test_the_lane_mark_is_the_documented_lane():
    assert WORKTREE_LANE_MARK == os.sep + ".claude" + os.sep + "worktrees" + os.sep


def test_commons_store_built_on_a_seat_tree_writes_into_the_main_tree( tmp_path ):
    main = tmp_path / "lupin"
    seat = main / ".claude" / "worktrees" / "seat-cc-author-x-1"
    seat.mkdir( parents=True )

    store = CommonsStore( seat )

    assert store.commons_dir == main / "io" / "commons"
    assert ( main / "io" / "commons" / "presence.md" ).is_file()
    assert not ( seat / "io" ).exists()


def test_seat_teardown_log_lands_in_the_main_tree_not_the_seat( tmp_path ):
    main = tmp_path / "lupin"
    seat = main / ".claude" / "worktrees" / "seat-cc-author-x-1"
    seat.mkdir( parents=True )
    opened = []

    def fake_popen( argv, **kwargs ):
        opened.append( kwargs[ "stdout" ].name )
        return "handle"

    out = session_end._schedule_seat_teardown(
        { "reason": "exit", "cwd": str( seat ) }, popen_fn=fake_popen, lupin_root=str( seat ) )

    assert out == "handle"
    assert opened == [ str( main / "io" / "worktree-janitor" / "seat-teardown.jsonl" ) ]
    assert not ( seat / "io" ).exists()
