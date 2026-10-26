"""
Unit tests of the worktree port, against a real git repository.

The commit the run is cut from holds an old client and the reuse skill.
A later commit changes both, so a tree cut from the tip of main shows up as the wrong file content.
The provisioners are stubs that record the path they got.
"""
import os
import subprocess

import pytest

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import worktree


def git_in( root, *args ):
    """Run git in a test repository and return its output."""
    return subprocess.run( [ "git", "-C", str( root ), "-c", "user.name=t", "-c", "user.email=t@example.com", *args ], check=True, capture_output=True, text=True ).stdout.strip()


class Provisioner:
    """A provisioner stub that records the paths it was given and answers a fixed status."""

    def __init__( self, status="ok" ):
        """Remember the status to answer."""
        self.status = status
        self.paths  = []

    def __call__( self, path ):
        """Record the path and answer."""
        self.paths.append( path )
        return { "status" : self.status, "detail" : f"stub {self.status}" }


@pytest.fixture
def repo( tmp_path ):
    """Build a repository: a frozen commit, then a later commit that changes the skill."""
    git_in( tmp_path, "init", "-q", "-b", "main" )
    for relative, text in { f"{worktree.CLIENT_ROOT}/html/old.html": "old", f"{worktree.CLIENT_ROOT}/js/old.js": "old", f"{arms.SKILL_PATH}/SKILL.md": "frozen skill", "CLAUDE.md": "rules", "src/cosa/server.py": "server" }.items():
        ( tmp_path / relative ).parent.mkdir( parents=True, exist_ok=True )
        ( tmp_path / relative ).write_text( text )
    git_in( tmp_path, "add", "." )
    git_in( tmp_path, "commit", "-q", "-m", "frozen" )
    frozen = git_in( tmp_path, "rev-parse", "HEAD" )
    ( tmp_path / arms.SKILL_PATH / "SKILL.md" ).write_text( "later skill" )
    git_in( tmp_path, "commit", "-q", "-a", "-m", "later" )
    venv, artifacts = Provisioner(), Provisioner()
    return { "root" : tmp_path, "frozen" : frozen, "venv" : venv, "artifacts" : artifacts,
             "trees" : worktree.Worktrees( str( tmp_path ), venv=venv, artifacts=artifacts ) }


def test_create_cuts_the_tree_at_the_frozen_sha_not_at_the_tip( repo ):
    path = repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    assert ( open( os.path.join( path, arms.SKILL_PATH, "SKILL.md" ) ).read(), git_in( path, "rev-parse", "HEAD" ) ) == ( "frozen skill", repo[ "frozen" ] )


def test_create_puts_the_tree_under_the_worktrees_folder_and_returns_its_path( repo ):
    path = repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    assert path == os.path.join( str( repo[ "root" ] ), worktree.BASE_DIR, "run1" )


def test_create_empties_the_client_folder_but_keeps_the_folder_and_the_server( repo ):
    path = repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    assert repo[ "trees" ].client_entries( path ) == []
    assert os.path.isdir( os.path.join( path, worktree.CLIENT_ROOT ) )
    assert repo[ "trees" ].exists( path, "src/cosa/server.py" )


def test_client_entries_lists_what_the_run_builds_sorted( repo ):
    path = repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    for name in ( "b.html", "a.js" ): open( os.path.join( path, worktree.CLIENT_ROOT, name ), "w" ).close()
    assert repo[ "trees" ].client_entries( path ) == [ "a.js", "b.html" ]


def test_create_removes_the_arms_paths_and_keeps_them_when_the_arm_removes_nothing( repo ):
    without = repo[ "trees" ].create( "run-without", repo[ "frozen" ], [ arms.SKILL_PATH ] )
    with_   = repo[ "trees" ].create( "run-with", repo[ "frozen" ], [] )
    assert ( repo[ "trees" ].exists( without, arms.SKILL_PATH ), repo[ "trees" ].exists( with_, arms.SKILL_PATH ) ) == ( False, True )
    assert repo[ "trees" ].exists( without, "CLAUDE.md" )


def test_create_removes_a_single_file_and_tolerates_a_path_that_is_already_absent( repo ):
    path = repo[ "trees" ].create( "run1", repo[ "frozen" ], [ "CLAUDE.md", "no/such/path" ] )
    assert repo[ "trees" ].exists( path, "CLAUDE.md" ) is False


def test_create_refuses_a_remove_path_that_leaves_the_tree( repo ):
    ( repo[ "root" ] / "outside.txt" ).write_text( "keep" )
    with pytest.raises( err.HarnessError ) as caught: repo[ "trees" ].create( "run1", repo[ "frozen" ], [ "../../../outside.txt" ] )
    assert caught.value.code == err.WORKTREE_NOT_READY
    assert ( repo[ "root" ] / "outside.txt" ).read_text() == "keep"


def test_create_refuses_a_remove_path_into_a_sibling_tree_whose_name_starts_with_its_own( repo ):
    sibling = repo[ "root" ] / worktree.BASE_DIR / "run1-extra"
    sibling.mkdir( parents=True )
    ( sibling / "built.js" ).write_text( "keep" )
    with pytest.raises( err.HarnessError ) as caught: repo[ "trees" ].create( "run1", repo[ "frozen" ], [ "../run1-extra" ] )
    assert caught.value.code == err.WORKTREE_NOT_READY
    assert ( sibling / "built.js" ).read_text() == "keep"


def test_create_provisions_the_venv_and_the_artifacts_in_the_new_tree( repo ):
    path = repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    assert ( repo[ "venv" ].paths, repo[ "artifacts" ].paths ) == ( [ path ], [ path ] )


@pytest.mark.parametrize( "which", [ "venv", "artifacts" ] )
def test_create_refuses_a_tree_a_provisioner_did_not_ready( repo, which ):
    trees = worktree.Worktrees( str( repo[ "root" ] ), venv=Provisioner( "failed" if which == "venv" else "ok" ), artifacts=Provisioner( "failed" if which == "artifacts" else "ok" ) )
    with pytest.raises( err.HarnessError ) as caught: trees.create( "run1", repo[ "frozen" ], [] )
    assert caught.value.code == err.WORKTREE_NOT_READY and which in caught.value.detail and "stub failed" in caught.value.detail


def test_create_refuses_a_taken_path_and_leaves_it_alone( repo ):
    first = repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    open( os.path.join( first, worktree.CLIENT_ROOT, "built.js" ), "w" ).close()
    with pytest.raises( err.HarnessError ) as caught: repo[ "trees" ].create( "run1", repo[ "frozen" ], [] )
    assert caught.value.code == err.WORKTREE_EXISTS
    assert repo[ "trees" ].client_entries( first ) == [ "built.js" ]


def test_create_lets_git_refuse_an_unknown_commit( repo ):
    with pytest.raises( RuntimeError ): repo[ "trees" ].create( "run1", "0" * 40, [] )


def test_the_default_provisioners_are_the_shared_ones():
    from cosa.utils.worktree_artifacts import provision_worktree_artifacts
    from cosa.utils.worktree_venv import provision_worktree_venv
    trees = worktree.Worktrees( "/x" )
    assert ( trees.venv, trees.artifacts ) == ( provision_worktree_venv, provision_worktree_artifacts )
