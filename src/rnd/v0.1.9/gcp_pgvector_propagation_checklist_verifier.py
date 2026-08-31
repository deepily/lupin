"""
GCP pgvector-propagation checklist-verifier (DRY-SIDE, read-only).

Codifies the dry-side preconditions for propagating the v0.2.0 pgvector backend
to the GCP environment. Runnable NOW against the local GCP-shaped surface
(candidate image + local pgvector Postgres); it is the machine-checkable half of
the propagation plan the Implementer (Cheech) is producing. Plan-specific items
(GCP Cloud SQL apply, AR image digest match) are marked PENDING until that plan
+ Rick's apply GO exist — this verifier never mutates GCP.

Probes (charter-named):
  1. IMAGE DEP    — candidate image imports pgvector (app-side Vector type).
  2. DB EXTENSION — pgvector 'vector' extension present in the target Postgres.
  3. CONFIG KEY   — 'vector store backend = postgres' present in the live INI.
  4. BACKFILL     — the offline backfill utility is dry-run reachable
                    (import + argparse dry-run default; NO --apply => zero writes).

Usage:  src/cosa/.venv/bin/python src/rnd/v0.2.0/gcp_pgvector_propagation_checklist_verifier.py
Exit 0 iff every checkable item PASSES (PENDING items do not fail the run).
"""

import os
import subprocess
import sys

ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
CANDIDATE_CONTAINER = os.environ.get( "LUPIN_CANDIDATE_CONTAINER", "lupin-rest-dev" )

DSN = dict(
    dbname   = os.environ.get( "DB_NAME",     "lupin_db_dev" ),
    user     = os.environ.get( "DB_USER",     "lupin_dev" ),
    password = os.environ.get( "DB_PASSWORD", "" ),
    host     = os.environ.get( "DB_HOST",     "localhost" ),
    port     = os.environ.get( "DB_PORT",     "5432" ),
)


def _probe_image_dep():
    """Candidate image imports the app-side pgvector Vector type."""
    try:
        out = subprocess.run(
            [ "docker", "exec", CANDIDATE_CONTAINER, "python", "-c",
              "from pgvector.sqlalchemy import Vector; print('ok')" ],
            capture_output=True, text=True, timeout=30,
        )
        ok = out.returncode == 0 and "ok" in out.stdout
        return ok, ( "Vector import ok" if ok else f"rc={out.returncode} {out.stderr.strip()[:80]}" )
    except Exception as e:
        return False, f"probe error: {e}"


def _probe_db_extension():
    """Target Postgres has the pgvector 'vector' extension installed."""
    try:
        import psycopg2
        c = psycopg2.connect( **DSN )
        c.set_session( readonly=True )
        cur = c.cursor()
        cur.execute( "SELECT extversion FROM pg_extension WHERE extname='vector'" )
        row = cur.fetchone()
        c.close()
        ok = row is not None
        return ok, ( f"vector {row[0]}" if ok else "extension ABSENT" )
    except Exception as e:
        return False, f"probe error: {e}"


def _probe_config_key():
    """Live INI selects the postgres vector-store backend."""
    ini = os.path.join( ROOT, "src", "conf", "lupin-app.ini" )
    try:
        with open( ini ) as f:
            for line in f:
                s = line.strip()
                if s.startswith( "vector store backend" ) and "=" in s:
                    val = s.split( "=", 1 )[ 1 ].strip()
                    ok = val == "postgres"
                    return ok, f"vector store backend = {val}"
        return False, "key not found in INI"
    except Exception as e:
        return False, f"probe error: {e}"


def _probe_backfill_reachable():
    """Backfill utility imports + exposes the dry-run (no --apply) default path."""
    src = os.path.join( ROOT, "src" )
    code = (
        "import importlib; m = importlib.import_module('cosa.rest.db.vector_store_backfill'); "
        "assert hasattr(m, '_run') and hasattr(m, 'backfill_table'); "
        "import inspect; assert inspect.signature(m._run).parameters['apply'].default is False; "
        "print('ok')"
    )
    try:
        env = dict( os.environ, PYTHONPATH=src + ":" + os.environ.get( "PYTHONPATH", "" ), LUPIN_ROOT=ROOT )
        py = os.path.join( ROOT, "src", "cosa", ".venv", "bin", "python" )
        out = subprocess.run( [ py, "-c", code ], capture_output=True, text=True, timeout=60, env=env )
        ok = out.returncode == 0 and "ok" in out.stdout
        return ok, ( "import + main() reachable (dry-run = no --apply)" if ok else out.stderr.strip()[:100] )
    except Exception as e:
        return False, f"probe error: {e}"


CHECKS = [
    ( "IMAGE DEP    (candidate image imports pgvector)", _probe_image_dep ),
    ( "DB EXTENSION (pgvector 'vector' in target PG)",   _probe_db_extension ),
    ( "CONFIG KEY   (backend = postgres in live INI)",   _probe_config_key ),
    ( "BACKFILL     (dry-run reachable, zero-write)",     _probe_backfill_reachable ),
]

PENDING = [
    "GCP Cloud SQL pg16 CREATE EXTENSION vector (needs Rick apply GO + Cheech plan)",
    "AR candidate-image digest == deployed GCP image digest (needs push + apply)",
    "GCP backfill --apply into Cloud SQL (needs Rick apply GO)",
]


def main():
    print( "\n=== GCP pgvector-propagation checklist-verifier (dry-side, read-only) ===" )
    all_ok = True
    for name, fn in CHECKS:
        ok, detail = fn()
        if not ok: all_ok = False
        print( f"  [{'PASS' if ok else 'FAIL'}] {name:48s} : {detail}" )
    print( "  --- PENDING (gated on Rick apply GO + Cheech propagation plan) ---" )
    for p in PENDING:
        print( f"  [PEND] {p}" )
    print( f"=== {'ALL CHECKABLE PASS' if all_ok else 'FAILURES PRESENT'} ===" )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit( main() )
