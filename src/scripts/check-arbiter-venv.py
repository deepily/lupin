#!/usr/bin/env python3
"""
Arbiter host-venv import gate — fails a DEPLOY instead of a running thread.

WHY THIS EXISTS
---------------
On 2026-08-08 the standalone arbiter's `fleet-arbiter-loop` thread died on its first
tick with `ModuleNotFoundError: No module named 'sqlalchemy'` and stayed dead for two
days. Nothing caught it:

  * `systemctl status`  → active (running)      (the PROCESS was fine)
  * `/health`           → 200 {"status":"ok"}   (the endpoint knew nothing of threads)
  * provisioning        → verified only /health

…so the only symptom was an empty Fleet Status panel three hops downstream.

That was the THIRD instance of one class: the light host venv
(`src/scripts/requirements-arbiter.txt`, labelled "CLOSED + FROZEN") drifting behind
the arbiter's import graph. `pyyaml` was added 2026-07-22 after a live
`ModuleNotFoundError('yaml')` on this same VM. A frozen list plus a comment asking
people to keep it current is not a control — this script is the control.

WHAT IT CHECKS
--------------
Every module the arbiter actually imports at RUNTIME, in the venv that will run it,
before the service is started. Import failure ⇒ non-zero exit + the exact remedy.

The follow-through watcher is checked ONLY when `follow through escalation enabled`
is true, mirroring the runtime gate added the same day in
`fleet_arbiter_loop.make_follow_through_watcher_factory` — with the flag off the
arbiter must not import the DB layer at all, and this script asserts that stays true
by NOT requiring those packages.

USAGE
    <arbiter-venv>/bin/python src/scripts/check-arbiter-venv.py
    <arbiter-venv>/bin/python src/scripts/check-arbiter-venv.py --json

Exit codes: 0 = every required module imports · 1 = at least one missing/broken.

Record: src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md
"""
import argparse
import importlib
import json
import os
import sys


# The arbiter's runtime import graph. Ordered roughly boot-first so the earliest
# failure is the most informative one reported.
ALWAYS_REQUIRED = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "yaml",                                        # added 2026-07-22 (live failure)
    "pytz",
    "lupin_arbiter_app.app",
    "lupin_arbiter_app.fleet_arbiter_loop",
    "lupin_arbiter_app.health_watcher",
    "lupin_arbiter_app.context_pressure_writer",
    "cosa.config.configuration_manager",
    "cosa.agents.heartbeat_arbiter.arbiter_job",
    "cosa.agents.heartbeat_arbiter.turn_age_watchdog",
]

# Required ONLY when `follow through escalation enabled` is true. This is the
# sqlalchemy/pgvector/psycopg2 closure that killed the loop on 2026-08-08.
REQUIRED_WHEN_FOLLOW_THROUGH_ENABLED = [
    "sqlalchemy",
    "pgvector",
    "psycopg2",
    "cosa.rest.follow_through_escalation_watcher",
]

REMEDY = (
    "install it into the ARBITER venv and re-run this check:\n"
    "    <arbiter-venv>/bin/python -m pip install -r src/scripts/requirements-arbiter.txt\n"
    "  then add the missing package to src/scripts/requirements-arbiter.txt so the next\n"
    "  provision carries it (that file is the deploy contract, not a comment)."
)


def follow_through_enabled():
    """
    Read the escalation flag the same way the runtime gate does.

    Ensures:
        - returns a bool
        - a config that cannot be loaded degrades to True (CHECK MORE, not less) —
          an unreadable config must never quietly shrink the required set
    """
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        cfg = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        return bool( cfg.get( "follow through escalation enabled", default=False, return_type="boolean" ) )
    except Exception:
        return True


def check_modules( names ):
    """
    Import each name, collecting failures.

    Ensures:
        - returns a list of ( module_name, error_string ) for every failure
        - never raises; an unexpected error is reported as a failure, not propagated
    """
    failures = [ ]
    for name in names:
        try:
            importlib.import_module( name )
        except Exception as e:
            failures.append( ( name, f"{type( e ).__name__}: {e}" ) )
    return failures


def main( argv=None ):
    parser = argparse.ArgumentParser( description="Verify the arbiter host venv can import everything it runs." )
    parser.add_argument( "--json", action="store_true", help="machine-readable output" )
    args = parser.parse_args( argv )

    enabled  = follow_through_enabled()
    required = list( ALWAYS_REQUIRED )
    if enabled:
        required += REQUIRED_WHEN_FOLLOW_THROUGH_ENABLED

    failures = check_modules( required )
    result   = {
        "interpreter"              : sys.executable,
        "lupin_root"               : os.environ.get( "LUPIN_ROOT", "<unset>" ),
        "follow_through_enabled"   : enabled,
        "modules_checked"          : len( required ),
        "failures"                 : [ { "module": m, "error": e } for m, e in failures ],
        "ok"                       : not failures,
    }

    if args.json:
        print( json.dumps( result, indent=2 ) )
    else:
        print( f"arbiter venv check — interpreter: {sys.executable}" )
        print( f"  follow through escalation enabled = {enabled} "
               f"({'DB closure required' if enabled else 'DB closure NOT required'})" )
        print( f"  modules checked: {len( required )}" )
        if failures:
            print( f"  FAILED: {len( failures )}" )
            for m, e in failures:
                print( f"    - {m}: {e}" )
            print( f"\n{REMEDY}" )
        else:
            print( "  OK — every module the arbiter imports at runtime is importable here." )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit( main() )
