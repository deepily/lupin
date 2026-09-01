"""
THE CONTROL FOR ROW 9b2abfb7 AC4: a newly created worktree must come up with a
resolvable interpreter, and this file reddens if it stops doing so.

It drives the REAL `WorktreeContext`, doing a REAL `git worktree add` into a REAL
temporary repo, and calls the REAL `link-worktree-venv.sh` — nothing about the
provisioning is faked. A mocked version of this test would assert that we call a
function we wrote, which is not the question the row asks. The question is whether a
tree that did not exist a moment ago can run the unit tier.

⚠️ IT CARRIES ITS OWN NEGATIVE CONTROL, and that is the load-bearing part. A test that
only ever checks the success case cannot tell "provisioning works" from "the assertion
cannot fail" — an empty result and a wrong search look identical. So
`test_the_control_can_actually_see_a_missing_interpreter` builds the same tree with the
provisioning script removed and asserts the interpreter is ABSENT. If that test ever
goes green alongside the others, the instrument is broken, not the code.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

from cosa.agents.shared.worktree_context import WorktreeContext
from cosa.utils.worktree_venv import provision_worktree_venv


# The real script, taken from the tree this test file lives in — never from LUPIN_ROOT,
# which names whatever repo the runner's shell happened to be standing in.
_REPO_ROOT  = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
_REAL_SCRIPT = os.path.join( _REPO_ROOT, "src", "scripts", "link-worktree-venv.sh" )


def _init_repo_with_a_venv( path, with_script=True ):
    """
    Build a temp git repo that looks like a main checkout: one commit, a real `.venv`
    holding an executable `bin/python`, and (optionally) the real part-1 script.

    Ensures:
        - the repo has exactly one commit on branch main
        - `<path>/.venv/bin/python` exists and is executable
        - the part-1 script is present iff with_script
    """
    env = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }

    def run( *args ):
        subprocess.run( args, cwd=path, env=env, check=True, capture_output=True )

    run( "git", "init", "-b", "main", "." )
    run( "git", "config", "user.email", "test@example.com" )
    run( "git", "config", "user.name", "Test" )

    if with_script:
        script_dir = os.path.join( path, "src", "scripts" )
        os.makedirs( script_dir, exist_ok=True )
        dest = os.path.join( script_dir, "link-worktree-venv.sh" )
        shutil.copy2( _REAL_SCRIPT, dest )
        os.chmod( dest, 0o755 )

    with open( os.path.join( path, "README.md" ), "w" ) as f:
        f.write( "# test\n" )
    run( "git", "add", "-A" )
    run( "git", "commit", "-m", "initial" )
    run( "git", "update-ref", "refs/remotes/origin/main", "HEAD" )

    # The main checkout's venv — the thing a worktree borrows. A tiny executable is
    # enough: the script's contract is that `.venv/bin/python` resolves and runs.
    bin_dir = os.path.join( path, ".venv", "bin" )
    os.makedirs( bin_dir, exist_ok=True )
    python  = os.path.join( bin_dir, "python" )
    with open( python, "w" ) as f:
        f.write( '#!/usr/bin/env bash\necho "Python 3.13.7 (stand-in)"\n' )
    os.chmod( python, 0o755 )
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
    """A temp repo standing in for a main checkout, with or without the part-1 script."""
    with_script = getattr( request, "param", True )
    with tempfile.TemporaryDirectory() as tmp:
        real = os.path.realpath( tmp )
        _init_repo_with_a_venv( real, with_script=with_script )
        from unittest.mock import patch
        with patch( "cosa.agents.shared.worktree_context.cu.get_project_root", return_value=real ):
            yield real
        subprocess.run( [ "git", "worktree", "prune" ], cwd=real, check=False, capture_output=True )


class TestANewWorktreeIsUsableTheMomentItExists:

    @pytest.mark.asyncio
    async def test_a_worktree_created_by_WorktreeContext_has_a_resolvable_interpreter( self, main_checkout ):
        """
        AC4. Before this row, every `.claude/worktrees/<job_id>` tree came up with no
        interpreter, so a BFE/TFE job running tests inside one saw failures caused by
        its sandbox rather than by the code it was sent to fix.
        """
        async with WorktreeContext( job_id="tfe-venv-control", config_mgr=_CFG, enabled=True ) as wt:
            interpreter = os.path.join( wt.path, ".venv", "bin", "python" )
            assert os.path.exists( interpreter ), f"new worktree has no interpreter at {interpreter}"
            assert os.access( interpreter, os.X_OK ), "interpreter is present but not executable"
            # It must be the MAIN checkout's venv, borrowed — not a copy, not a stray.
            assert os.path.islink( os.path.join( wt.path, ".venv" ) )
            assert os.path.realpath( os.path.join( wt.path, ".venv" ) ) == \
                   os.path.realpath( os.path.join( main_checkout, ".venv" ) )

    @pytest.mark.asyncio
    async def test_the_interpreter_actually_runs( self, main_checkout ):
        """A symlink that resolves to nothing looks identical to success from a stat."""
        async with WorktreeContext( job_id="tfe-venv-runs", config_mgr=_CFG, enabled=True ) as wt:
            out = subprocess.run(
                [ os.path.join( wt.path, ".venv", "bin", "python" ) ],
                capture_output=True, text=True,
            )
            assert out.returncode == 0
            assert "Python" in out.stdout

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "main_checkout", [ False ], indirect=True )
    async def test_the_control_can_actually_see_a_missing_interpreter( self, main_checkout ):
        """
        THE NEGATIVE CONTROL. Same repo, same context manager, part-1 script removed.
        The worktree must come up WITHOUT an interpreter — proving the two assertions
        above are capable of failing. A green here would mean this whole file is
        measuring nothing.
        """
        async with WorktreeContext( job_id="tfe-venv-negative", config_mgr=_CFG, enabled=True ) as wt:
            assert not os.path.exists( os.path.join( wt.path, ".venv" ) ), \
                "a tree with no provisioning script somehow got a venv — the control is broken"

    @pytest.mark.asyncio
    async def test_a_second_entry_is_idempotent_and_leaves_the_link_alone( self, main_checkout ):
        """Provisioning runs on every worktree creation, so it must never churn."""
        async with WorktreeContext( job_id="tfe-venv-idem", config_mgr=_CFG, enabled=True ) as wt:
            link   = os.path.join( wt.path, ".venv" )
            before = os.readlink( link )
            result = provision_worktree_venv( wt.path )
            assert result[ "status" ] == "ok"
            assert "ALREADY PROVISIONED" in result[ "detail" ]
            assert os.readlink( link ) == before

    @pytest.mark.asyncio
    async def test_a_real_venv_directory_is_never_replaced_by_a_link( self, main_checkout ):
        """
        The row's explicit requirement: a no-op on a real `.venv` directory. Standing a
        real directory in the worktree must leave it exactly as found.
        """
        async with WorktreeContext( job_id="tfe-venv-real", config_mgr=_CFG, enabled=True ) as wt:
            link = os.path.join( wt.path, ".venv" )
            os.remove( link )
            bin_dir = os.path.join( link, "bin" )
            os.makedirs( bin_dir )
            python = os.path.join( bin_dir, "python" )
            with open( python, "w" ) as f: f.write( "#!/usr/bin/env bash\necho mine\n" )
            os.chmod( python, 0o755 )

            result = provision_worktree_venv( wt.path )
            assert result[ "status" ] == "ok"
            assert not os.path.islink( link ), "a real .venv directory was replaced by a symlink"
            assert subprocess.run( [ python ], capture_output=True, text=True ).stdout.strip() == "mine"

    @pytest.mark.asyncio
    async def test_debug_narrates_the_provisioning_outcome( self, main_checkout, capsys ):
        """
        The narration is how an operator tells "provisioned" from "could not" without
        reading the tree. A clean exit is not evidence the work happened, so the line
        reports the STATUS the helper returned, not merely that it was called.
        """
        async with WorktreeContext( job_id="tfe-venv-debug", config_mgr=_CFG,
                                    enabled=True, debug=True ) as wt:
            out = capsys.readouterr().out
            assert "[WorktreeContext] venv: ok" in out
            assert wt.path in out
