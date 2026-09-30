"""
Give a freshly-created worktree a usable `.venv`, so the unit tier answers the same
question in every tree (row 9b2abfb7 — part 2 of the f42ac20c remedy).

THE DEFECT THIS CLOSES. `.venv` is gitignored, so `git worktree add` never produces
one. Four unit-test files shell out to `<PROJECT_ROOT>/.venv/bin/{python,pytest}`, so
they pass in the main checkout and fail in every worktree without one, with no code
difference between them. Measured on ONE clean tree at ONE sha with only a `.venv`
symlink added and removed: 14 failed without it, 1 failed with it — and the survivor
is an unrelated genuine red, not a venue artifact.

WHY THIS MODULE DOES NOT REIMPLEMENT THE LINKING. `src/scripts/link-worktree-venv.sh`
(part 1) already refuses the main repo by name, no-ops on a real `.venv`, clears only
a dangling symlink of its own, and verifies the interpreter resolves before claiming
success. A second implementation of that predicate is a second thing to keep in sync,
so this delegates and never re-derives. There is deliberately no "is it already
provisioned" fast path here for the same reason.

⚠️ IT CANNOT CROSS-CONTAMINATE REPOS, AND THAT IS STRUCTURAL RATHER THAN CAREFUL.
`session_spawner` keeps two axes apart on purpose: PLATFORM (venv, PYTHONPATH, hooks,
MCP) is pinned to lupin always, WORK (cwd, CLAUDE.md, git identity) follows the target
project. A child booted on another repo's venv cannot import fastmcp, so it cannot DM,
set a topic, or be reaped (measured by Maria, 2026-08-19). This helper cannot blur
that: the script asks `git -C "$TARGET" worktree list` for the TARGET's own main
checkout, so it can only ever link a repo's own venv into that repo's own worktree. A
foreign repo whose main checkout has no venv exits 4 loudly instead of borrowing one.

⚠️ IT NEVER RAISES, DELIBERATELY. A seat without a venv is worse off; a spawn that
dies because provisioning failed is worse still. Same fail-open shape as
`stash_guard.py`. Every non-recoverable outcome is logged at WARNING naming the target
and the exit code, because the failure this whole row exists to kill is the one that
looks like success.
"""

import logging
import os
import subprocess

logger = logging.getLogger( __name__ )

# The part-1 script, relative to the tree being provisioned. Resolved from the TARGET
# rather than from LUPIN_ROOT on purpose: a script shipped inside the tree it acts on
# can only be disagreed with by the environment, never informed by it. Resolving this
# from LUPIN_ROOT is precisely the wrong-tree family that has bitten the verifier, the
# purge script and the unit tier in turn.
_SCRIPT_REL_PATH = os.path.join( "src", "scripts", "link-worktree-venv.sh" )

# Exit codes the script defines. 0 covers both "linked" and "already provisioned"; 3
# is the main checkout refusing to be linked to itself, which is a correct no-op and
# not a failure. Everything else means it could not finish and must be audible.
_EXIT_OK        = 0
_EXIT_MAIN_REPO = 3

_TIMEOUT_SECS = 30


def provision_worktree_venv( target, debug=False ):
    """
    Ensure `target` has a usable `.venv`, by delegating to the part-1 script.

    Requires:
        - target is a path string, or falsy

    Ensures:
        - never raises, for any input or any failure of the underlying script
        - returns a dict with keys: provisioned (bool), status (str),
          exit_code (int or None), target (str or None), detail (str)
        - provisioned is True ONLY when the target now has a usable interpreter
          because this call confirmed or created one (script exit 0)
        - a falsy target is a no-op reported as status "no_target", never an error:
          an explicit project=None spawn inherits the caller's own cwd, which this
          helper does not know and must not guess at
        - a target with no part-1 script (a foreign repo, an old checkout) is a
          no-op reported as status "script_absent", never an error
        - the main checkout is a no-op FOR PROVISIONING, reported as status
          "main_repo" — the script refuses to replace a real .venv directory with a
          link to itself — AND logged at WARNING naming the target, because the
          LOCATION fact riding along with it (this seat is in the shared tree) is
          not a no-op for whoever is about to work there
        - every other non-zero exit is reported as status "failed" AND logged at
          WARNING naming the target and the exit code

    Returns:
        dict
    """
    if not target:
        return { "provisioned": False, "status": "no_target", "exit_code": None,
                 "target": None, "detail": "no work_dir to provision" }

    script = os.path.join( target, _SCRIPT_REL_PATH )
    if not os.path.isfile( script ):
        if debug: print( f"[worktree_venv] no part-1 script at {script} - skipping" )
        return { "provisioned": False, "status": "script_absent", "exit_code": None,
                 "target": target, "detail": f"no provisioning script at {script}" }

    try:
        result = subprocess.run(
            [ script, target ],
            capture_output=True, text=True, timeout=_TIMEOUT_SECS
        )
    except ( OSError, subprocess.SubprocessError ) as e:
        # A script that cannot even be executed must not take the spawn down with it.
        logger.warning( f"[worktree_venv] could not run {script} for {target}: {e}" )
        return { "provisioned": False, "status": "failed", "exit_code": None,
                 "target": target, "detail": f"{type( e ).__name__}: {e}" }

    detail = ( result.stdout or "" ).strip() or ( result.stderr or "" ).strip()

    if result.returncode == _EXIT_OK:
        if debug: print( f"[worktree_venv] {target}: {detail}" )
        return { "provisioned": True, "status": "ok", "exit_code": _EXIT_OK,
                 "target": target, "detail": detail }

    if result.returncode == _EXIT_MAIN_REPO:
        # 🔴 TWO FACTS SHARE THIS EXIT CODE, AND ONLY ONE OF THEM IS BENIGN.
        # PROVISIONING: nothing to do — the main checkout owns the real .venv, and the
        # part-1 script is right to refuse to link it to itself. LOCATION: whoever is
        # about to work here is standing in the tree the whole fleet shares. The second
        # is operationally significant and used to surface NOWHERE — the script's own
        # `detail` is a sentence about a venv, so a careful reader read it as one.
        # Measured 2026-09-02: two workers landed in the main checkout, one wrote to it
        # during a live 14-minute tier run, and a manager had to decide mid-run whether
        # to discard the result. Logged at WARNING because a non-debug caller is exactly
        # who needs to hear it; still a no-op for provisioning, which is what it is.
        logger.warning(
            f"[worktree_venv] {target} is the SHARED MAIN CHECKOUT, not an isolated "
            f"worktree - work here is visible to every other seat on this repo"
        )
        return { "provisioned": False, "status": "main_repo", "exit_code": _EXIT_MAIN_REPO,
                 "target": target, "detail": detail }

    logger.warning(
        f"[worktree_venv] could not provision a .venv for {target} "
        f"(exit {result.returncode}): {detail}"
    )
    return { "provisioned": False, "status": "failed", "exit_code": result.returncode,
             "target": target, "detail": detail }
