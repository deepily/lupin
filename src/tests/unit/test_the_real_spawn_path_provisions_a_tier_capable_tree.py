"""
THE WIRING GUARD FOR ROW dde8b87a: the REAL spawn path must actually reach the artifact
provisioner, and this file reddens if that call site goes away.

WHY THIS EXISTS SEPARATELY FROM THE HELPER'S OWN TESTS. A component can be complete,
correct, fully covered and entirely absent from the running system, and every test that
builds the component stays green. `test_new_worktrees_come_up_tier_capable.py` drives
`WorktreeContext`; `test_worktree_artifacts_provisioning.py` drives the helper. NEITHER
of them would notice if the one line in `session_spawner` that calls the provisioner
were reverted — and `session_spawner` is the path the incident actually came down.

⚠️ THE ASSERTION IS ON THE FILESYSTEM, NOT ON THE PAYLOAD, and that is deliberate. A
payload field can be populated by more than one path; a symlink appearing inside a
worktree that did not have one a moment ago has exactly one cause. An assertion
satisfied by several states cannot tell you which one fired.

⚠️ IT CARRIES ITS NEGATIVE CONTROL as an arm, not as a separate file: the same real
spawn against a tree whose provisioning script has been removed must leave the artifact
ABSENT. Without it, a test that only ever sees the artifact present cannot distinguish
"the spawn provisions" from "the artifact was already there".
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from lupin_mcp import session_spawner


# The real scripts, from the tree this file lives in — never from LUPIN_ROOT, which
# names whatever repo the runner's shell happened to be standing in.
_REPO_ROOT  = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
_SCRIPT_DIR = os.path.join( _REPO_ROOT, "src", "scripts" )

_GIT_ENV = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }


def _git( cwd, *args ):
    subprocess.run( [ "git", *args ], cwd=cwd, env=_GIT_ENV, check=True, capture_output=True )


def _repo_with_a_worktree( root, with_script=True ):
    """
    Build a real main checkout plus a real linked worktree of it.

    Requires:
        - root is an existing directory

    Ensures:
        - returns (main_checkout, worktree) as absolute real paths
        - the main checkout holds an untracked `node_modules/tsx/package.json`
        - the worktree is a genuine `git worktree add` product, so it holds the tracked
          files and NOTHING untracked — which is the whole condition under test
        - the provisioning script is present iff with_script
    """
    # Named "lupin" on purpose: `_resolve_project_root` answers with LUPIN_ROOT when the
    # MAIN CHECKOUT'S DIRECTORY NAME matches the requested project, which is how a
    # manager already inside a worktree keeps its seats in that worktree. Naming it
    # anything else would make the real resolver refuse, and the arm would then be
    # measuring the resolver rather than the provisioning.
    main = os.path.realpath( os.path.join( root, "lupin" ) )
    os.makedirs( main )
    _git( main, "init", "-b", "main", "." )
    _git( main, "config", "user.email", "test@example.com" )
    _git( main, "config", "user.name", "Test" )

    script_dir = os.path.join( main, "src", "scripts" )
    os.makedirs( script_dir )
    if with_script:
        dest = os.path.join( script_dir, "link-worktree-artifacts.sh" )
        shutil.copy2( os.path.join( _SCRIPT_DIR, "link-worktree-artifacts.sh" ), dest )
        os.chmod( dest, 0o755 )
    else:
        with open( os.path.join( script_dir, ".keep" ), "w" ) as f: f.write( "" )

    with open( os.path.join( main, "README.md" ), "w" ) as f: f.write( "# test\n" )
    _git( main, "add", "-A" )
    _git( main, "commit", "-m", "initial" )

    # Untracked, created AFTER the commit — exactly as `node_modules` is in the real
    # repo. A tracked stand-in would be present in the worktree by construction and
    # could not fail.
    pkg = os.path.join( main, "node_modules", "tsx" )
    os.makedirs( pkg )
    with open( os.path.join( pkg, "package.json" ), "w" ) as f: f.write( '{ "name": "tsx" }\n' )

    worktree = os.path.realpath( os.path.join( root, "seat" ) )
    _git( main, "worktree", "add", worktree, "-b", "seat-branch" )
    return main, worktree


class _FakeCompleted:
    returncode = 0
    stdout     = ""
    stderr     = ""


def _spawn_into( monkeypatch, tree ):
    """
    Fire the REAL spawn path with `LUPIN_ROOT` naming `tree`; return the result.

    🔴 `dry_run=False`, WITH THE TMUX LAUNCH STOOD DOWN BY AN INJECTED RUNNER — and the
    distinction is the whole reason this helper has a comment. A dry run PROVISIONS
    NOTHING by design (both `provision_seat_worktree` and the artifact call are gated on
    it), so a dry-run arm would assert on a path that is switched off and report a green
    that means nothing. The `runner` seam is what makes a real run safe here: nothing is
    spawned, and every step this file is about still executes.
    """
    monkeypatch.setenv( "LUPIN_ROOT", tree )
    # The seat gets its OWN worktree under a real spawn, so `git worktree add` must be
    # able to answer. Everything else about the run is real.
    with tempfile.TemporaryDirectory() as session_dir:
        return session_spawner.spawn_sessions(
            1, "task", "mgr-sid", script_path="/bin/true", project="lupin",
            session_dir=Path( session_dir ), dry_run=False,
            runner=lambda argv, env=None: _FakeCompleted()
        )


class TestTheRealSpawnPathLeavesATierCapableTree:

    def test_a_real_spawn_puts_node_modules_into_the_seats_tree( self, monkeypatch ):
        """
        THE INCIDENT, at the layer it entered at. A seat spawned into a fresh worktree
        got `.venv` and no `node_modules`, so every `.test.ts` there died naming a
        package. Revert the `provision_worktree_artifacts` call in `session_spawner` and
        this test — and only this test — goes red.
        """
        with tempfile.TemporaryDirectory() as tmp:
            main, worktree = _repo_with_a_worktree( tmp )
            try:
                assert not os.path.exists( os.path.join( worktree, "node_modules" ) ), \
                    "the fresh worktree already had node_modules - the arm proves nothing"

                result = _spawn_into( monkeypatch, worktree )

                # ⚠️ SAY WHICH TREE THE ASSERTION IS ABOUT. Under a real run the seat
                # normally gets its OWN sub-worktree; this stand-in repo carries no
                # `provision-seat-worktree.sh`, so that step fails open and the seat
                # stays in `worktree`. Asserting it makes the dependency visible instead
                # of leaving a future reader to discover it when adding that script
                # silently moves what this test is measuring.
                assert result[ "seat_worktrees" ][ 0 ][ "work_dir" ] == worktree

                landed = os.path.join( worktree, "node_modules" )
                assert os.path.islink( landed ), "the real spawn path did not borrow node_modules"
                assert os.path.isfile( os.path.join( landed, "tsx", "package.json" ) ), \
                    "node_modules is linked but a package does not resolve through it"
            finally:
                subprocess.run( [ "git", "worktree", "prune" ], cwd=main, check=False, capture_output=True )

    def test_the_arm_can_actually_see_an_unprovisioned_tree( self, monkeypatch ):
        """
        THE NEGATIVE CONTROL. Same real spawn, same real worktree, provisioning script
        removed from the tree. The artifact must stay ABSENT — proving the assertion
        above is capable of failing rather than describing a tree that was already fine.
        """
        with tempfile.TemporaryDirectory() as tmp:
            main, worktree = _repo_with_a_worktree( tmp, with_script=False )
            try:
                result = _spawn_into( monkeypatch, worktree )

                assert not os.path.exists( os.path.join( worktree, "node_modules" ) ), \
                    "a tree with no provisioning script somehow got node_modules - the control is broken"
                assert result[ "artifact_provisioning" ][ "status" ] == "script_absent"
            finally:
                subprocess.run( [ "git", "worktree", "prune" ], cwd=main, check=False, capture_output=True )

    def test_the_payload_carries_the_artifact_verdict_for_the_seat( self, monkeypatch ):
        """
        The verdict must ride back on the result, not be computed and dropped. A spawn
        that reports success over a seat which cannot run its own tier is the shape this
        repo already names: a clean exit is not evidence the work happened.
        """
        with tempfile.TemporaryDirectory() as tmp:
            main, worktree = _repo_with_a_worktree( tmp )
            try:
                result = _spawn_into( monkeypatch, worktree )

                assert result[ "artifact_provisioning" ][ "status" ] == "ok"
                assert result[ "artifact_provisioning" ][ "artifacts" ][ "node_modules" ] == "LINKED"
                # cloud-run.env is on the borrow list and this stand-in repo has none to
                # lend — which must read as "nothing to borrow", never as a failure.
                assert result[ "artifact_provisioning" ][ "artifacts" ][ "src/scripts/cloud-run.env" ] \
                       == "SOURCE_ABSENT"
                assert result[ "artifact_alarm" ] is None
                assert result[ "spawned" ][ 0 ][ "artifact_alarm" ] is None
            finally:
                subprocess.run( [ "git", "worktree", "prune" ], cwd=main, check=False, capture_output=True )


class TestADryRunBorrowsNothing:
    """
    🔴 THE REGRESSION CONTROL FOR A DEFECT THIS CHANGE ITSELF SHIPPED FOR TWENTY MINUTES.
    The first cut called the provisioner unconditionally. `spawn_sessions` is driven with
    `dry_run=True` by other unit tests, with `LUPIN_ROOT` naming THE TREE UNDER TEST — so
    one tier run linked `node_modules` and `src/scripts/cloud-run.env` into the author's
    own worktree, and NINE cloud-run.env failures disappeared from that run's own failing
    set part-way through it. A tier whose result depends on which test ran first is not a
    measurement.

    ⚠️ THE RULING ALREADY EXISTED three lines above the call site, for
    `provision_seat_worktree`: a dry run means "do not actually spawn", and creating
    things on disk is the loudest side effect this function has. Writing it down did not
    stop the next person adding a side effect beside it, which is why it is a test now.
    """

    def test_a_dry_run_leaves_the_tree_exactly_as_it_found_it( self, monkeypatch ):
        with tempfile.TemporaryDirectory() as tmp:
            main, worktree = _repo_with_a_worktree( tmp )
            try:
                monkeypatch.setenv( "LUPIN_ROOT", worktree )
                with tempfile.TemporaryDirectory() as session_dir:
                    result = session_spawner.spawn_sessions(
                        1, "task", "mgr-sid", script_path="/bin/true", project="lupin",
                        session_dir=Path( session_dir ), dry_run=True
                    )

                assert not os.path.exists( os.path.join( worktree, "node_modules" ) ), \
                    "a DRY RUN borrowed an artifact into the tree it was pointed at"
                assert result[ "artifact_provisioning" ][ "status" ] == "dry_run"
                assert result[ "artifact_alarm" ] is None, \
                    "a dry run must not alarm - there was nothing it was supposed to do"
            finally:
                subprocess.run( [ "git", "worktree", "prune" ], cwd=main, check=False, capture_output=True )
