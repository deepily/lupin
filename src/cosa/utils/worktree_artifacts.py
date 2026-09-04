"""
Give a freshly-created worktree the UNTRACKED, NON-SECRET artifacts it needs to run a
whole tier — the members `provision_worktree_venv` does not cover (row dde8b87a).

THE DEFECT THIS CLOSES. The spawn path provisioned a `.venv` and nothing else, so a
spawned seat passed `INTERPRETER OK` and was still unable to run its own tier.
`INTERPRETER OK` and a TIER-CAPABLE TREE are different claims, and the spawn path only
ever made the first. Measured 2026-09-04: a freshly spawned worktree had `.venv` and no
`node_modules`, so every `.test.ts` in it died with `Cannot find package 'tsx'` — which
reads as a broken test rather than as a missing tree, and is why this member went
unfound while the two that fail loudly were already documented.

⚠️ THIS IS A SECOND HELPER, NOT A REWRITE OF THE FIRST. `provision_worktree_venv` has
its own script, its own exit-code vocabulary, and a `main_repo` verdict that carries a
LOCATION fact (`placement_alarm`) nothing else surfaces. Folding a second concern into
it would put two answers behind one status field, which is the shape this repo keeps
paying for. The two run side by side and are read side by side.

⚠️ IT NEVER RAISES, DELIBERATELY. Same fail-open shape as `provision_worktree_venv` and
`stash_guard.py`: a seat without `node_modules` is worse off; a spawn that DIES because
provisioning failed is worse still. Every non-recoverable outcome is logged at WARNING
naming the target and the exit code, because the failure this row exists to kill is the
one that looks like success.

🔴 WHAT IT WILL NEVER PROVISION, and this is a ruling rather than a preference: nothing
under `src/conf/keys/**` (Mr. Radio, 2026-09-01, overturning earlier advice that said to
symlink one), not the repo-root `.env` (JWT_SECRET_KEY, POSTGRES_PASSWORD), and no build
OUTPUT such as `src/lupin_app/static/dist/` — a symlinked output directory means a build
run in a throwaway tree writes into the shared checkout. The allow list lives in the
script, next to the reasoning for each member.
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
        - provisioned is True ONLY on script exit 0 — meaning every borrowable artifact
          is now present, or the main checkout had none to lend
        - a falsy target is a no-op reported as status "no_target", never an error
        - a target with no script (a foreign repo, an old checkout) is a no-op reported
          as status "script_absent", never an error
        - the main checkout is a no-op reported as status "main_repo" — it owns the real
          artifacts — and is NOT logged here, because `provision_worktree_venv` already
          carries the location warning for that same target and a second copy of it
          would read as two seats in the shared tree rather than one
        - every other non-zero exit is reported as status "failed" AND logged at WARNING
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
