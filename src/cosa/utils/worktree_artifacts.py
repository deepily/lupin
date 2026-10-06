"""
Give a new worktree the untracked, non-secret artifacts it needs to run a whole tier.

These are the artifacts `provision_worktree_venv` does not cover. The spawn path used
to provision a `.venv` and nothing else. A spawned seat passed the interpreter check
and still could not run its own tier. A working interpreter and a tier-capable
tree are different claims. A spawned worktree with `.venv` and no `node_modules` made
every `.test.ts` die with `Cannot find package 'tsx'`. That reads as a broken test
rather than a missing tree.

This is a second helper and not a rewrite of the first. `provision_worktree_venv` has
its own script, its own exit-code vocabulary, and a `main_repo` verdict that carries a
location fact (`placement_alarm`) that nothing else surfaces. Folding a second concern
into it would put two answers behind one status field. The two run and are read side
by side.

It never raises. This is the same fail-open shape as `provision_worktree_venv` and
`stash_guard.py`. A seat without `node_modules` is worse off, and a spawn that dies
because provisioning failed is worse still. Every non-recoverable outcome is logged at
`WARNING` naming the target and the exit code. The failure to avoid is the one that
looks like success.

It never provisions anything under `src/conf/keys/**`, nor the repo-root `.env`
(JWT_SECRET_KEY, POSTGRES_PASSWORD), nor build output such as `src/lupin_app/static/dist/`.
A symlinked output directory would let a build run in a throwaway tree write into the
shared checkout. The allow list lives in the script, next to the reasoning for each
member.
"""

import logging
import os
import subprocess

logger = logging.getLogger( __name__ )

# Resolved from the TARGET rather than from LUPIN_ROOT, on purpose: a script shipped
# inside the tree it acts on can only be disagreed with by the environment, never
# informed by it. Resolving this from LUPIN_ROOT is the wrong-tree family that has
# bitten the pyc verifier, the purge script and the unit tier in turn.
_SCRIPT_REL_PATH = os.path.join( "src", "scripts", "link-worktree-artifacts.sh" )

# Exit codes the script defines. 0 covers linked, already-present and nothing-to-lend;
# 3 is the main checkout correctly refusing to link its own artifacts to themselves,
# which is a no-op and not a failure. Everything else means it could not finish.
_EXIT_OK        = 0
_EXIT_MAIN_REPO = 3

_TIMEOUT_SECS = 30

# The machine-readable keys the script emits, one per line. Parsed rather than the
# prose, so a wording change cannot silently move a verdict.
_OUTCOME_KEYS = ( "LINKED", "ALREADY", "SOURCE_ABSENT", "REFUSED" )


def parse_artifact_outcomes( stdout ):
    """
    Turn the script's machine-readable lines into {relative_path: outcome}.

    Requires:
        - stdout is a string, possibly empty, possibly carrying prose lines too

    Ensures:
        - returns a dict mapping each reported relative path to one of
          "LINKED" / "ALREADY" / "SOURCE_ABSENT" / "REFUSED"
        - prose lines and unknown keys are ignored, never guessed at
        - never raises

    Returns:
        dict
    """
    outcomes = {}
    for line in ( stdout or "" ).splitlines():
        line = line.strip()
        if "=" not in line: continue
        key, _, rel = line.partition( "=" )
        if key in _OUTCOME_KEYS and rel:
            outcomes[ rel ] = key
    return outcomes


def provision_worktree_artifacts( target, debug=False ):
    """
    Ensure `target` has the borrowable untracked artifacts, by delegating to the script.

    Requires:
        - target is a path string, or falsy

    Ensures:
        - never raises, for any input or any failure of the underlying script
        - returns a dict with keys: provisioned (bool), status (str), exit_code
          (int or None), target (str or None), detail (str), artifacts (dict)
        - provisioned is True only on script exit 0, meaning every borrowable artifact
          is now present, or the main checkout had none to lend
        - a falsy target is a no-op reported as status "no_target", never an error
        - a target with no script (a foreign repo, an old checkout) is a no-op reported
          as status "script_absent", never an error
        - the main checkout is a no-op reported as status "main_repo", because it owns the
          real artifacts. It is not logged here: `provision_worktree_venv` already
          carries the location warning for that target, and a second copy would read as
          two seats in the shared tree rather than one
        - every other non-zero exit is reported as status "failed" and logged at `WARNING`
          naming the target and the exit code
        - artifacts maps each artifact the script reported to its outcome, so a caller
          can tell "linked node_modules" from "the main checkout has none to lend"

    Returns:
        dict
    """
    if not target:
        return { "provisioned": False, "status": "no_target", "exit_code": None,
                 "target": None, "detail": "no work_dir to provision", "artifacts": {} }

    script = os.path.join( target, _SCRIPT_REL_PATH )
    if not os.path.isfile( script ):
        if debug: print( f"[worktree_artifacts] no script at {script} - skipping" )
        return { "provisioned": False, "status": "script_absent", "exit_code": None,
                 "target": target, "detail": f"no provisioning script at {script}",
                 "artifacts": {} }

    try:
        result = subprocess.run(
            [ script, target ],
            capture_output=True, text=True, timeout=_TIMEOUT_SECS
        )
    except ( OSError, subprocess.SubprocessError ) as e:
        logger.warning( f"[worktree_artifacts] could not run {script} for {target}: {e}" )
        return { "provisioned": False, "status": "failed", "exit_code": None,
                 "target": target, "detail": f"{type( e ).__name__}: {e}", "artifacts": {} }

    artifacts = parse_artifact_outcomes( result.stdout )
    detail    = ( result.stdout or "" ).strip() or ( result.stderr or "" ).strip()

    if result.returncode == _EXIT_OK:
        if debug: print( f"[worktree_artifacts] {target}: {artifacts}" )
        return { "provisioned": True, "status": "ok", "exit_code": _EXIT_OK,
                 "target": target, "detail": detail, "artifacts": artifacts }

    if result.returncode == _EXIT_MAIN_REPO:
        return { "provisioned": False, "status": "main_repo", "exit_code": _EXIT_MAIN_REPO,
                 "target": target, "detail": detail, "artifacts": artifacts }

    logger.warning(
        f"[worktree_artifacts] could not provision borrowed artifacts for {target} "
        f"(exit {result.returncode}): {detail}"
    )
    return { "provisioned": False, "status": "failed", "exit_code": result.returncode,
             "target": target, "detail": detail, "artifacts": artifacts }
