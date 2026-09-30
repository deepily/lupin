"""
Enter at the layer the incident entered at: drive the real `spawn_sessions`, not the
helper underneath it (follow-up to 3d180af6).

WHY THIS FILE EXISTS SEPARATELY FROM THE HELPER TESTS. 3d180af6 shipped with an
end-to-end receipt that called `provision_worktree_venv` directly, with the main repo's
path HANDED TO IT. That proves the helper announces a main-repo target. It says nothing
about whether the real spawn path ever reaches that branch — and "does the spawn path
reach it" is the entire question, because the incident was a spawn, not a helper call.

⇒ A TEST THAT ENTERS BELOW THE LAYER THE INCIDENT ENTERED AT CANNOT SPEAK TO THE
INCIDENT. Two seats produced this the same evening from opposite ends: a repro that
called a handler directly instead of dispatching the click proved the lookup was wrong
and proved nothing about the operator's failure. Same rule, and it is not about
mocking — nothing was mocked in either case. It is about where you knock.

WHAT IS REAL HERE, AND IT IS NEARLY EVERYTHING. The real `_resolve_project_root`, the
real `provision_worktree_venv`, the real `link-worktree-venv.sh`. Only the tmux launch
is stood down, via `dry_run=True`, which is also what makes this safe to run on :7999:
nothing is spawned, no manifest is written, and exit 3 is a refusal that does nothing.
The single variable between the two cases is `LUPIN_ROOT`.

⚠️ AND BOTH DIRECTIONS ARE REQUIRED, NOT ONE. "The alarm fires" and "the alarm fires
WHEN IT SHOULD" are different claims, and only the second is worth having. The
ordinary-worktree case is the negative control; without it a placement alarm that
fired on every spawn would pass just as happily.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import pytest

from lupin_mcp import session_spawner


def _tree_under_test():
    """
    The tree the CODE UNDER TEST was imported from — asked of the module, never of this
    file. That is the tree whose behaviour these assertions are about, and with the two
    pins on this repo it can differ from where the test file sits.
    """
    return Path( session_spawner.__file__ ).resolve().parents[ 2 ]


def _main_checkout():
    """The main checkout, resolved from git rather than hardcoded — `git-common-dir`
    answers with the parent repo from inside any worktree."""
    out = subprocess.run(
        [ "git", "rev-parse", "--path-format=absolute", "--git-common-dir" ],
        capture_output=True, text=True, cwd=_tree_under_test()
    )
    if out.returncode != 0: return None
    return str( Path( out.stdout.strip() ).parent )


def _spawn_against( monkeypatch, caplog, root ):
    """Fire the REAL spawn path with `LUPIN_ROOT` naming `root`; return (result, records)."""
    monkeypatch.setenv( "LUPIN_ROOT", root )
    with tempfile.TemporaryDirectory() as tmp:
        with caplog.at_level( logging.WARNING, logger="cosa.utils.worktree_venv" ):
            result = session_spawner.spawn_sessions(
                1, "task", "mgr-sid", script_path="/bin/true", project="lupin",
                session_dir=Path( tmp ), dry_run=True
            )
    return result, [ r for r in caplog.records if r.levelno >= logging.WARNING ]


class TestTheRealSpawnPathAnnouncesWhereTheSeatLanded:

    def test_a_spawn_resolving_to_the_main_checkout_says_so_on_the_payload( self, monkeypatch, caplog ):
        """The incident condition: a manager whose LUPIN_ROOT names the main checkout."""
        main = _main_checkout()
        if main is None: pytest.skip( "not a git tree - cannot resolve the main checkout" )

        result, records = _spawn_against( monkeypatch, caplog, main )

        assert result[ "venv_provisioning" ][ "status" ] == "main_repo"
        assert result[ "placement_alarm" ] is not None
        assert main in result[ "placement_alarm" ]
        assert records, "no warning-level record reached a non-debug caller"
        assert result[ "venv_alarm" ] is None      # there is no venv problem on this path

    def test_a_spawn_resolving_to_an_ordinary_worktree_says_nothing( self, monkeypatch, caplog ):
        """
        THE NEGATIVE CONTROL, and the half that makes the other half mean something. An
        alarm that fired on every spawn would satisfy the test above and be useless.
        """
        here = str( _tree_under_test() )
        main = _main_checkout()
        if main is None or here == main: pytest.skip( "running in the main checkout - no worktree arm available" )

        result, records = _spawn_against( monkeypatch, caplog, here )

        assert result[ "venv_provisioning" ][ "status" ] != "main_repo"
        assert result[ "placement_alarm" ] is None
        assert records == []
