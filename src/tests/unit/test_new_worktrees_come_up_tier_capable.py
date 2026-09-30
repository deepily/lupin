"""
THE CONTROL FOR ROW dde8b87a: a newly created worktree must come up able to run a WHOLE
tier, not merely able to start an interpreter — and this file reddens if it stops.

THE DEFECT IT GUARDS. The spawn path provisioned a `.venv` and nothing else, so a
spawned seat passed `INTERPRETER OK` and still could not run a single `.test.ts`:
`node_modules` is gitignored, so `git worktree add` cannot produce one, and every
TypeScript run in a fresh tree died with `Cannot find package 'tsx'`. That failure names
a PACKAGE rather than a tree, which is why it reads as a broken test and why this member
went unfound while the two that fail loudly were already documented.

⚠️ IT DRIVES THE REAL THING AT THE LAYER THE INCIDENT ENTERED AT. Real `WorktreeContext`,
real `git worktree add` into a real temporary repo, real `link-worktree-artifacts.sh`.
A helper-level receipt — calling `provision_worktree_artifacts` with a path handed to it
— would establish that the helper works and say nothing about whether the creation path
ever REACHES it. The incident was a spawn, not a helper call.

⚠️ IT CARRIES ITS OWN NEGATIVE CONTROL, and that is the load-bearing part. A test that
only checks the success case cannot tell "provisioning works" from "the assertion cannot
fail". `test_the_control_can_actually_see_an_unprovisioned_tree` builds the same tree
with the provisioning script removed and asserts the artifacts are ABSENT. If that test
ever goes green alongside the others, the instrument is broken, not the code.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

from cosa.agents.shared.worktree_context import WorktreeContext
from cosa.utils.worktree_artifacts import provision_worktree_artifacts


# The real scripts, taken from the tree this test file lives in — never from LUPIN_ROOT,
# which names whatever repo the runner's shell happened to be standing in.
_REPO_ROOT  = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
_SCRIPT_DIR = os.path.join( _REPO_ROOT, "src", "scripts" )

# 🔴 THE EXPECTED SET IS A LITERAL, PINNED HERE, ON PURPOSE. Deriving it from the
# script's own BORROW list would make both sides of every comparison below move
# together, so the assertions could never disagree with the code — a tautology wearing
# an assertion's clothes. These names are hand-written; if the script drops one, this
# file reddens.
_MUST_BE_BORROWED = ( "node_modules", "src/scripts/cloud-run.env" )


def _init_main_checkout( path, with_script=True ):
    """
    Build a temp git repo that looks like a main checkout: one commit, a `.venv` with an
    executable stand-in, the borrowable artifacts, and (optionally) the real scripts.

    Requires:
        - path is an existing directory

    Ensures:
        - the repo has exactly one commit on branch main, with origin/main pointing at it
        - `<path>/.venv/bin/python` exists and is executable
        - every name in _MUST_BE_BORROWED exists under path
        - the provisioning scripts are present iff with_script
    """
    env = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }

    def run( *args ):
        subprocess.run( args, cwd=path, env=env, check=True, capture_output=True )

    run( "git", "init", "-b", "main", "." )
    run( "git", "config", "user.email", "test@example.com" )
    run( "git", "config", "user.name", "Test" )

    script_dir = os.path.join( path, "src", "scripts" )
    os.makedirs( script_dir, exist_ok=True )
    if with_script:
        for name in ( "link-worktree-venv.sh", "link-worktree-artifacts.sh" ):
            dest = os.path.join( script_dir, name )
            shutil.copy2( os.path.join( _SCRIPT_DIR, name ), dest )
            os.chmod( dest, 0o755 )
    else:
        # `src/scripts` must still be a tracked directory, or the worktree would not have
        # it and the cloud-run.env case would be testing directory creation instead of
        # the absence of provisioning. One variable at a time.
        with open( os.path.join( script_dir, ".keep" ), "w" ) as f: f.write( "" )

    with open( os.path.join( path, "README.md" ), "w" ) as f:
        f.write( "# test\n" )
    run( "git", "add", "-A" )
    run( "git", "commit", "-m", "initial" )
    run( "git", "update-ref", "refs/remotes/origin/main", "HEAD" )

    # The main checkout's venv — a tiny executable is enough; the venv script's contract
    # is that `.venv/bin/python` resolves and runs.
    bin_dir = os.path.join( path, ".venv", "bin" )
    os.makedirs( bin_dir, exist_ok=True )
    python  = os.path.join( bin_dir, "python" )
    with open( python, "w" ) as f:
        f.write( '#!/usr/bin/env bash\necho "Python 3.13.7 (stand-in)"\n' )
    os.chmod( python, 0o755 )

    # The borrowable artifacts, created AFTER the commit so they are untracked exactly as
    # they are in the real repo. A tracked stand-in would be present in every worktree by
    # construction and could not fail.
    pkg = os.path.join( path, "node_modules", "tsx" )
    os.makedirs( pkg, exist_ok=True )
    with open( os.path.join( pkg, "package.json" ), "w" ) as f:
        f.write( '{ "name": "tsx" }\n' )
    with open( os.path.join( path, "src", "scripts", "cloud-run.env" ), "w" ) as f:
        f.write( "LUPIN_GCP_PROJECT_ID=stand-in\n" )
    return path


class _StubConfig:

    def __init__( self, values ): self._values = values

    def get( self, key, default=None, return_type="string" ): return self._values.get( key, default )


_CFG = _StubConfig( {
    "cosa worktree sandbox root"         : ".claude/worktrees",
    "cosa worktree base ref"             : "origin/main",
    "cosa worktree auto cleanup"         : False,   # keep the tree so we can inspect it
    "cosa worktree cleanup timeout secs" : 30,
} )


@pytest.fixture
def main_checkout( request ):
    """A temp repo standing in for a main checkout, with or without the scripts."""
    with_script = getattr( request, "param", True )
    with tempfile.TemporaryDirectory() as tmp:
        real = os.path.realpath( tmp )
        _init_main_checkout( real, with_script=with_script )
        from unittest.mock import patch
        with patch( "cosa.agents.shared.worktree_context.cu.get_project_root", return_value=real ):
            yield real
        subprocess.run( [ "git", "worktree", "prune" ], cwd=real, check=False, capture_output=True )


class TestANewWorktreeCanRunAWholeTier:

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "rel", _MUST_BE_BORROWED )
    async def test_a_worktree_created_by_WorktreeContext_has_the_borrowed_artifact( self, main_checkout, rel ):
        """
        The row's first requirement. Parametrised per artifact rather than asserted as a
        set, so a failure NAMES the member that did not land — a single assertion over
        both would tell a reader that something is missing and not which.
        """
        async with WorktreeContext( job_id="tfe-artifacts-control", config_mgr=_CFG, enabled=True ) as wt:
            landed = os.path.join( wt.path, rel )
            assert os.path.exists( landed ), f"new worktree has no {rel} at {landed}"
            assert os.path.islink( landed ), f"{rel} is present but is not a borrowed link"
            assert os.path.realpath( landed ) == os.path.realpath( os.path.join( main_checkout, rel ) )

    @pytest.mark.asyncio
    async def test_the_borrowed_node_modules_actually_resolves_a_package( self, main_checkout ):
        """
        A symlink that resolves to nothing looks identical to success from a stat, and
        the incident was not "no directory" — it was `Cannot find package 'tsx'`. So the
        assertion is that a PACKAGE resolves through the link, which is the thing the
        failing TypeScript run could not do.
        """
        async with WorktreeContext( job_id="tfe-artifacts-resolve", config_mgr=_CFG, enabled=True ) as wt:
            assert os.path.isfile( os.path.join( wt.path, "node_modules", "tsx", "package.json" ) )

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "main_checkout", [ False ], indirect=True )
    async def test_the_control_can_actually_see_an_unprovisioned_tree( self, main_checkout ):
        """
        THE NEGATIVE CONTROL. Same repo, same context manager, provisioning scripts
        removed. The worktree must come up WITHOUT the artifacts — proving the
        assertions above are capable of failing. A green here alongside the others would
        mean this whole file is measuring nothing.
        """
        async with WorktreeContext( job_id="tfe-artifacts-negative", config_mgr=_CFG, enabled=True ) as wt:
            for rel in _MUST_BE_BORROWED:
                assert not os.path.exists( os.path.join( wt.path, rel ) ), \
                    f"a tree with no provisioning script somehow got {rel} — the control is broken"

    @pytest.mark.asyncio
    async def test_a_second_pass_is_idempotent_and_leaves_the_links_alone( self, main_checkout ):
        """Provisioning runs on every worktree creation, so it must never churn."""
        async with WorktreeContext( job_id="tfe-artifacts-idem", config_mgr=_CFG, enabled=True ) as wt:
            before = { rel: os.readlink( os.path.join( wt.path, rel ) ) for rel in _MUST_BE_BORROWED }
            result = provision_worktree_artifacts( wt.path )
            assert result[ "status" ] == "ok"
            assert set( result[ "artifacts" ].values() ) == { "ALREADY" }
            for rel, target in before.items():
                assert os.readlink( os.path.join( wt.path, rel ) ) == target

    @pytest.mark.asyncio
    async def test_a_real_file_the_seat_put_there_is_never_replaced( self, main_checkout ):
        """
        A seat that wrote its own `cloud-run.env` owns it. Provisioning must leave it
        exactly as found — the same no-op contract the venv script has for a real
        `.venv` directory.
        """
        async with WorktreeContext( job_id="tfe-artifacts-mine", config_mgr=_CFG, enabled=True ) as wt:
            mine = os.path.join( wt.path, "src", "scripts", "cloud-run.env" )
            os.remove( mine )
            with open( mine, "w" ) as f: f.write( "LUPIN_GCP_PROJECT_ID=mine\n" )

            result = provision_worktree_artifacts( wt.path )
            assert result[ "status" ] == "ok"
            assert result[ "artifacts" ][ "src/scripts/cloud-run.env" ] == "ALREADY"
            assert not os.path.islink( mine ), "a real file the seat wrote was replaced by a link"
            assert open( mine ).read().strip() == "LUPIN_GCP_PROJECT_ID=mine"

    @pytest.mark.asyncio
    async def test_a_dangling_link_of_ours_is_replaced_rather_than_left_broken( self, main_checkout ):
        """
        The one case worth clearing: a link that resolves to nothing is ours and is
        broken, and leaving it would make every later run report ALREADY over a tree
        that still cannot run.
        """
        async with WorktreeContext( job_id="tfe-artifacts-dangling", config_mgr=_CFG, enabled=True ) as wt:
            link = os.path.join( wt.path, "node_modules" )
            os.remove( link )
            os.symlink( os.path.join( main_checkout, "gone-forever" ), link )
            assert not os.path.exists( link )

            result = provision_worktree_artifacts( wt.path )
            assert result[ "artifacts" ][ "node_modules" ] == "LINKED"
            assert os.path.realpath( link ) == os.path.realpath( os.path.join( main_checkout, "node_modules" ) )

    @pytest.mark.asyncio
    async def test_a_main_checkout_with_nothing_to_lend_is_a_no_op_and_not_a_failure( self, main_checkout ):
        """
        A box that never ran `npm install` has nothing to borrow. That is the operator's
        business, not a provisioning failure — alarming on it would fire on every spawn
        on a fresh box, and an alarm that always fires is one nobody reads.
        """
        shutil.rmtree( os.path.join( main_checkout, "node_modules" ) )
        async with WorktreeContext( job_id="tfe-artifacts-nolend", config_mgr=_CFG, enabled=True ) as wt:
            result = provision_worktree_artifacts( wt.path )
            assert result[ "provisioned" ] is True
            assert result[ "status" ] == "ok"
            assert result[ "artifacts" ][ "node_modules" ] == "SOURCE_ABSENT"

    @pytest.mark.asyncio
    async def test_debug_narrates_the_artifact_outcomes( self, main_checkout, capsys ):
        """
        The narration is how an operator tells "provisioned" from "could not" without
        reading the tree. It reports the OUTCOMES, not merely that the call was made —
        a clean exit is not evidence the work happened.
        """
        async with WorktreeContext( job_id="tfe-artifacts-debug", config_mgr=_CFG,
                                    enabled=True, debug=True ) as wt:
            out = capsys.readouterr().out
            assert "[WorktreeContext] artifacts: ok" in out
            assert "node_modules" in out


class TestTheBorrowListNeverCarriesASecret:
    """
    🔴 THE DENY SIDE IS A RULING, NOT A PREFERENCE (Mr. Radio, 2026-09-01), so it gets a
    test rather than a comment. The allow list is parsed out of the script; the deny list
    is hand-written here. Two provenances, so the comparison can actually disagree.
    """

    _SCRIPT = os.path.join( _SCRIPT_DIR, "link-worktree-artifacts.sh" )

    # Hand-written, deliberately not derived from anything the script can move. Each
    # entry is (needle, mode): "exact" for a path that is forbidden only as itself,
    # "under" for a prefix nothing may live beneath.
    #
    # ⚠️ `.env` IS EXACT, AND THE FIRST CUT OF THIS TEST HAD IT AS A SUBSTRING — which
    # reddened on `src/scripts/cloud-run.env`, a file whose own header reads "No secrets
    # here". The repo-root `.env` is the secret (JWT_SECRET_KEY, POSTGRES_PASSWORD); a
    # name ending in `.env` is not. Left visible because the coarse form is the obvious
    # one to write and would have banned a legitimate member.
    _NEVER = (
        ( "src/conf/keys",          "under" ),
        ( ".env",                   "exact" ),
        ( "src/lupin_app/static/dist", "under" ),
        ( "src/scripts/auth_migration/migration_results.json", "exact" ),
    )

    def _borrow_list( self ):
        """The BORROW=( ... ) array, read out of the shipped script."""
        lines, inside = [], False
        for line in open( self._SCRIPT ):
            stripped = line.strip()
            if stripped.startswith( "BORROW=(" ): inside = True;  continue
            if inside and stripped == ")":       inside = False; break
            if inside and stripped.startswith( '"' ):
                lines.append( stripped.strip( '"' ) )
        return lines

    def test_the_borrow_list_is_found_at_all( self ):
        """
        The positive control for the parser below. An empty list would satisfy every
        deny assertion in this class by vacuum — a loop over nothing is green.
        """
        borrowed = self._borrow_list()
        assert len( borrowed ) >= 2, f"parsed only {borrowed} out of {self._SCRIPT}"
        assert "node_modules" in borrowed

    @pytest.mark.parametrize( "forbidden,mode", _NEVER )
    def test_no_borrowed_path_is_a_secret_or_a_build_output( self, forbidden, mode ):
        """
        A symlink puts a live credential inside a throwaway tree that gets rm -rf'd,
        copied and shared, and the `.venv` precedent makes it look sanctioned. A venv is
        a build artifact; a key is a secret. A build OUTPUT is excluded for a different
        reason: a build run in a throwaway tree would write into the shared checkout.
        """
        for rel in self._borrow_list():
            hit = ( rel == forbidden ) if mode == "exact" else rel.startswith( forbidden )
            assert not hit, f"the borrow list carries a forbidden path: {rel} ({mode} {forbidden})"
