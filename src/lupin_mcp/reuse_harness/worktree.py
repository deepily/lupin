"""
The worktree port of the run harness: the frozen server with an empty client folder.

Plan 3, section 7.3 asks for a worktree "with today's frozen server and the client folder empty".
The run builds its client into CLIENT_ROOT, the folder the server serves pages and assets from.
Emptying it makes both arms start from nothing. The tree is cut at the frozen sha, never at the tip of main.
It is not removed when the run ends. The scorer reads the client the run built, and the arbiter janitor sweeps the tree once idle.
"""
import os
import shutil

from cosa.repo.doc_lint import pool_builder
from cosa.utils.worktree_artifacts import provision_worktree_artifacts
from cosa.utils.worktree_venv import provision_worktree_venv
from lupin_mcp.reuse_harness import errors as err

# R6 of the generic plan: the server mounts this folder at /static and reads its pages from it.
CLIENT_ROOT = "src/lupin_app/static"
BASE_DIR    = ".claude/worktrees"
READY       = "ok"


class Worktrees:
    """Makes and inspects the worktrees of runs."""

    def __init__( self, repo_root, base_dir=BASE_DIR, venv=provision_worktree_venv, artifacts=provision_worktree_artifacts ):
        """
        Remember where runs are cut from and how a tree is provisioned.

        Requires:
            - repo_root is the main checkout the runs are cut from
            - base_dir is relative to repo_root and is gitignored, so the janitor sweeps it
            - venv and artifacts take a path and return a dict with a status, as the provisioners in cosa.utils do

        Ensures:
            - nothing is created yet
        """
        self.repo_root = repo_root
        self.base_dir  = base_dir
        self.venv      = venv
        self.artifacts = artifacts

    def create( self, run_id, commit, remove_paths ):
        """
        Cut a worktree at the commit, provision it and empty the client folder.

        Requires:
            - run_id is a non-empty string with no path separator
            - commit is a full sha
            - remove_paths are relative paths, with no leading slash and no parent step

        Ensures:
            - returns the absolute path of a detached worktree at commit
            - CLIENT_ROOT exists and is empty; every remove path is gone
            - the venv and artifacts were provisioned and reported ok; keys and .env are never linked

        Raises:
            - HarnessError WORKTREE_EXISTS if the path is taken
            - HarnessError WORKTREE_NOT_READY if a provisioner did not report ok, or a remove path leaves the tree
            - RuntimeError from git if the commit cannot be checked out
        """
        path = os.path.join( self.repo_root, self.base_dir, run_id )
        if os.path.exists( path ): raise err.HarnessError( err.WORKTREE_EXISTS, f"{path} is taken" )
        pool_builder.run_git( self.repo_root, [ "worktree", "add", "--detach", path, commit ] )
        for name, provision in ( ( "venv", self.venv ), ( "artifacts", self.artifacts ) ):
            outcome = provision( path )
            if outcome[ "status" ] != READY: raise err.HarnessError( err.WORKTREE_NOT_READY, f"{name} provisioning answered {outcome[ 'status' ]}: {outcome[ 'detail' ]}" )
        shutil.rmtree( os.path.join( path, CLIENT_ROOT ), ignore_errors=True )
        os.makedirs( os.path.join( path, CLIENT_ROOT ) )
        for relative in remove_paths: self._remove( path, relative )
        return path

    def _remove( self, path, relative ):
        """Delete one path of the tree, a file or a folder; a path already absent stays absent."""
        target = os.path.realpath( os.path.join( path, relative ) )
        if not target.startswith( os.path.realpath( path ) + os.sep ): raise err.HarnessError( err.WORKTREE_NOT_READY, f"{relative} leaves the worktree" )
        if os.path.isdir( target ): shutil.rmtree( target )
        elif os.path.exists( target ): os.remove( target )

    def client_entries( self, path ):
        """Return the sorted names directly in the client folder of the worktree."""
        return sorted( os.listdir( os.path.join( path, CLIENT_ROOT ) ) )

    def exists( self, path, relative ):
        """Say whether the worktree holds the path."""
        return os.path.exists( os.path.join( path, relative ) )
