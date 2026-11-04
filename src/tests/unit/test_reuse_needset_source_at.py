"""
The source commit's worktree, a root that merges into the main tree do not move.
"""
import subprocess

import pytest

from cosa.repo.symindex import build
from cosa.repo.symindex.paths import data_dir
from cosa.repo.symindex.spec import spec_for
from lupin_mcp.reuse_needset import errors as er, source_at, strip

OLD = "def f( x ):\n    return x + 1\n"
NEW = "# a peer added a line above\n\ndef g():\n    return 0\n\n\ndef f( x ):\n    return x + 2\n"
REC = { "id": "cosa.m.f", "name": "f", "file": "src/cosa/m.py", "lang": "py", "line": 1 }
ID  = [ "-c", "user.name=t", "-c", "user.email=t@t" ]


def git( repo, *argv ):
    """Run git in repo and return its stdout."""
    return subprocess.run( [ "git", "-C", str( repo ), *argv ], check=True, capture_output=True, text=True ).stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    """A lupin-shaped repository with one commit that holds the old text."""
    root = tmp_path / "lupin"
    ( root / "src" / "cosa" ).mkdir( parents=True )
    ( root / "src" / "lupin_mcp" ).mkdir()
    ( root / "src" / "cosa" / "m.py" ).write_text( OLD, encoding="utf-8" )
    ( root / "src" / "lupin_mcp" / "keep.py" ).write_text( "X = 1\n", encoding="utf-8" )
    git( root, "init", "-q" )
    git( root, *ID, "add", "." )
    git( root, *ID, "commit", "-qm", "first" )
    return root


def move_the_main_tree( repo ):
    """Commit a newer m.py and leave one more edit in the tree, as peers merging do."""
    ( repo / "src" / "cosa" / "m.py" ).write_text( NEW, encoding="utf-8" )
    git( repo, *ID, "commit", "-qam", "second" )
    ( repo / "src" / "cosa" / "m.py" ).write_text( NEW + "# edited again\n", encoding="utf-8" )


def test_the_worktree_is_made_at_the_commit_under_the_worktrees_folder_and_reused( repo ):
    sha = git( repo, "rev-parse", "HEAD" )
    wt  = source_at.ensure_worktree( repo, sha )
    assert wt == repo / ".claude" / "worktrees" / f"needset-run-{sha[ :9 ]}" and source_at.at_commit( wt, sha )
    assert source_at.ensure_worktree( repo, "HEAD" ) == wt


def test_a_merge_into_the_main_tree_mid_run_moves_no_read_that_takes_the_worktree_as_its_root( repo ):
    wt = source_at.ensure_worktree( repo, "HEAD" )
    out = wt / "src" / "docs" / "index"
    build.build( wt, out )
    before = build.current_generation( out ).name
    move_the_main_tree( repo )
    assert "return x + 1" in strip.bodies_for( [ REC ], wt )[ "cosa.m.f" ] and "return x + 2" in strip.bodies_for( [ REC ], repo )[ "cosa.m.f" ]
    assert "x + 1" in strip.strip_member( REC, wt )[ "text" ]
    assert build.is_fresh( spec_for( wt ), out ) and build.current_generation( out ).name == before
    assert not build.is_fresh( spec_for( repo ), out )                                                         # the main tree is not what that index describes
    assert data_dir( wt ) == data_dir( repo )                                                                  # one data folder and one spend ledger, not a second set named for the folder


def test_a_worktree_at_another_commit_or_with_a_changed_tracked_file_is_refused( repo ):
    first = git( repo, "rev-parse", "HEAD" )
    wt    = source_at.ensure_worktree( repo, first )
    ( wt / "src" / "cosa" / "m.py" ).write_text( "changed\n", encoding="utf-8" )
    with pytest.raises( er.NeedsetError ) as e: source_at.ensure_worktree( repo, first )
    assert e.value.code == er.SOURCE_TREE_MISMATCH and str( wt ) in e.value.detail
    git( wt, "checkout", "--", "src/cosa/m.py" )
    ( wt / "untracked.txt" ).write_text( "generated\n", encoding="utf-8" )
    assert source_at.ensure_worktree( repo, first ) == wt                                                      # an untracked file, such as the generated index, is no change
    ( repo / "src" / "cosa" / "m.py" ).write_text( NEW, encoding="utf-8" )
    git( repo, *ID, "commit", "-qam", "second" )
    second = source_at.ensure_worktree( repo, "HEAD" )
    assert second != wt and source_at.at_commit( second, git( repo, "rev-parse", "HEAD" ) )                    # another commit gets a worktree of its own
    with pytest.raises( er.NeedsetError ) as e: source_at.ensure_worktree( repo, "HEAD", wt )                   # and the first one is not taken for it
    assert e.value.code == er.SOURCE_TREE_MISMATCH
    elsewhere = repo / "not-a-worktree"
    elsewhere.mkdir()
    with pytest.raises( er.NeedsetError ) as e: source_at.ensure_worktree( repo, first, elsewhere )
    assert e.value.code == er.SOURCE_TREE_MISMATCH


def test_an_unknown_commit_and_a_failing_git_are_refused_by_name( repo, monkeypatch ):
    with pytest.raises( er.NeedsetError ) as e: source_at.ensure_worktree( repo, "0" * 40 )
    assert e.value.code == er.SOURCE_TREE_FAILED
    real = subprocess.run

    def failing( argv, **kw ):
        if "worktree" in argv: return subprocess.CompletedProcess( argv, 128, "", "fatal: boom" )
        return real( argv, **kw )

    monkeypatch.setattr( source_at.subprocess, "run", failing )
    with pytest.raises( er.NeedsetError ) as e: source_at.ensure_worktree( repo, "HEAD" )
    assert e.value.code == er.SOURCE_TREE_FAILED and "boom" in e.value.detail


def locked_paths( repo ):
    """List the worktrees git reports as locked."""
    out, here, found = git( repo, "worktree", "list", "--porcelain" ), None, []
    for line in out.splitlines():
        if line.startswith( "worktree " ): here = line[ 9: ]
        if line.startswith( "locked" ): found.append( here )
    return found


def test_the_worktree_is_locked_when_made_and_when_reused_and_unlock_frees_it( repo ):
    wt = source_at.ensure_worktree( repo, "HEAD" )
    assert locked_paths( repo ) == [ str( wt ) ]
    assert source_at.ensure_worktree( repo, "HEAD" ) == wt and locked_paths( repo ) == [ str( wt ) ]           # locking one already locked is no error
    source_at.unlock( repo, wt )
    assert locked_paths( repo ) == []
    source_at.unlock( repo, wt )                                                                                # unlocking one not locked raises nothing
    assert source_at.ensure_worktree( repo, "HEAD" ) == wt and locked_paths( repo ) == [ str( wt ) ]           # a reused, unlocked tree is locked again


def test_a_lock_git_refuses_for_another_reason_is_a_named_failure( repo, monkeypatch ):
    wt   = source_at.ensure_worktree( repo, "HEAD" )
    real = subprocess.run

    def refusing( argv, **kw ):
        if "lock" in argv: return subprocess.CompletedProcess( argv, 128, "", "fatal: no such worktree" )
        return real( argv, **kw )

    monkeypatch.setattr( source_at.subprocess, "run", refusing )
    with pytest.raises( er.NeedsetError ) as e: source_at.lock( repo, wt )
    assert e.value.code == er.SOURCE_TREE_FAILED and "no such worktree" in e.value.detail
