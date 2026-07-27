#!/usr/bin/env python3
"""
Is the DATABASE's schema at the HEAD revision of the CHECKED-OUT TREE? (row 4aa2b9d5)

THE GAP THIS CLOSES
-------------------
`main.py` runs migrations to head at startup, which closes the code-newer-than-schema
window BY CONSTRUCTION — for any path that goes through startup.

**`lupin-vm.sh push-bundle --checkout` does not go through startup.** Moving code
WITHOUT bouncing the servers is the entire point of that verb. So it is precisely a
path that lands new code on a box while skipping the startup migrate.

⇒ Post-`--checkout`, a VM can run code that `SELECT`s a column its database does not
  have. The concrete instance (María 🌸, commit `9fbb6258`): it selects
  `body_changed_ts`, added by migration `38e025169a73`. Against a pre-migration
  schema that is a 500 on **every task query** — the store, not a corner feature.

Preflight had 31 assertions across 5 layers and **not one looked at the schema**. A
box could pass every one of them green while running two migrations behind, and the
green would be honest about everything it actually asserted.

WHY IT USES THE APP'S OWN RESOLVERS AND NOT A HAND-ROLLED EQUIVALENT
--------------------------------------------------------------------
`cosa.rest.db.auto_migrate` already exposes exactly what is needed, and it is the
SAME code path `main.py` uses to migrate at startup — so the CHECK and the FIX agree
by construction. A second implementation would be a second authority, free to drift
from the thing it is supposed to be describing.

  - `build_alembic_config()`  — an alembic Config built PROGRAMMATICALLY.
      ⚠️ There is no `alembic.ini` in the container: the image bind-mounts only
      `./src`, and `alembic.ini` lives at the repo ROOT. Anything that reaches for
      the ini file works on the dev box and fails on the VM.
  - `resolve_database_url()`  — the URL.
      ⚠️ `cfg.get_main_option( "sqlalchemy.url" )` returns **None** here. That was
      the first attempt on the live VM and it died inside `create_engine`. Use the
      resolver.

⚠️ MUST RUN INSIDE THE CONTAINER. That is where the venv, the app package, and DB
   reachability live; the rest of preflight's layer A runs on the HOST as the SSH
   user, which can reach none of the three.

NOT A DUPLICATE OF `check_schema_parity.py` — they ask different questions
--------------------------------------------------------------------------
`src/scripts/check_schema_parity.py` (in the tree since 2026-05-29) compares the ORM
MODELS against the live database's `information_schema.columns`. It catches a model
column with no migration behind it.

THIS script compares the DATABASE's alembic revision against the TREE's head. It
catches a migration that exists and has not been applied.

    parity  : "do the models and the DB agree about columns?"   — the SYMPTOM
    at_head : "has every migration in this tree been run?"      — the CAUSE

They overlap but neither subsumes the other: a migration that changes only an index,
a constraint, or a column TYPE moves the revision without changing the column set, so
parity would report clean. Conversely a hand-edited DB can match head and still have
drifted columns. Run both; they are cheap.

⚠️ Worth knowing: `check_schema_parity.py` was never wired into preflight either —
   the same declared-and-unasserted shape this row is about, sitting one file over.

THREE OUTCOMES, DELIBERATELY NOT TWO
------------------------------------
  0  AT_HEAD          schema matches the tree's head revision
  1  DRIFT            they disagree — this is the defect
  2  CANNOT_DETERMINE the question could not be answered

"the schema is behind" and "I could not read the schema" have DIFFERENT REMEDIES —
migrate versus fix connectivity — and collapsing them would reproduce, inside this
check, the very defect class the surrounding work exists to remove. Per the settled
rule from the María thread, the caller must treat 2 as BLOCKING: the question is
"does not-knowing make the action UNSAFE?", and here it does.

Usage (from the host):
    docker exec <container> python /var/lupin/src/scripts/check_schema_at_head.py
"""

import os
import sys

EXIT_AT_HEAD          = 0
EXIT_DRIFT            = 1
EXIT_CANNOT_DETERMINE = 2


def _bootstrap_sys_path():
    """
    Put `src/` on sys.path before importing `cosa` (the bootstrap exception).

    Requires:
        - LUPIN_ROOT is set, OR this file sits at <root>/src/scripts/

    Ensures:
        - inserts <root>/src at position 0 when not already present
        - returns the resolved root
        - never raises; a root that cannot be resolved surfaces as an import error
          below, which is reported as CANNOT_DETERMINE with the reason attached
    """
    root = os.environ.get( "LUPIN_ROOT" )
    if not root:
        root = os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ) )
    src = os.path.join( root, "src" )
    if src not in sys.path:
        sys.path.insert( 0, src )
    return root


def read_revisions():
    """
    Read the tree's head revision and the database's current revision.

    Requires:
        - `cosa.rest.db.auto_migrate` is importable
        - the database named by resolve_database_url() is reachable

    Ensures:
        - returns ( head_in_tree, current_in_db, None ) on success
        - returns ( None, None, reason ) when either side could not be read —
          the reason is a human string naming WHICH half failed, because
          "cannot reach the DB" and "cannot read the migration scripts" send an
          operator to entirely different places
        - a database that has NEVER been stamped yields current_in_db of None,
          which is a legitimate READ (an unstamped DB), not a failure — the caller
          decides what an unstamped DB means

    Returns:
        tuple( head_in_tree|None, current_in_db|None, reason|None )
    """
    try:
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine
        from cosa.rest.db.auto_migrate import build_alembic_config, resolve_database_url
    except Exception as e:
        return ( None, None, f"cannot import the migration stack: {e.__class__.__name__}: {e}" )

    try:
        cfg  = build_alembic_config()
        head = ScriptDirectory.from_config( cfg ).get_current_head()
    except Exception as e:
        return ( None, None, f"cannot read the tree's head revision: {e.__class__.__name__}: {e}" )

    try:
        # NB resolve_database_url(), NOT cfg.get_main_option("sqlalchemy.url") — the
        # latter is None here and dies inside create_engine. Measured on the VM.
        url = resolve_database_url()
        engine = create_engine( url )
        with engine.connect() as conn:
            current = MigrationContext.configure( conn ).get_current_revision()
    except Exception as e:
        return ( None, None, f"cannot read the database's current revision: {e.__class__.__name__}: {e}" )

    return ( head, current, None )


def classify( head, current, reason ):
    """
    Turn a revision pair into one of the three outcomes.

    Requires:
        - head/current are revision strings or None; reason is a string or None

    Ensures:
        - returns ( exit_code, verdict, detail )
        - a reason present ⇒ CANNOT_DETERMINE, always. An error is never folded
          into a pass
        - head is None ⇒ CANNOT_DETERMINE. A tree with no migrations cannot
          establish what "at head" means, so agreement cannot be claimed
        - current is None (never stamped) ⇒ DRIFT, not CANNOT_DETERMINE. This is a
          READ that succeeded: the database HAS no revision, so it is definitively
          not at head, and the remedy is the same migrate
        - equality ⇒ AT_HEAD; inequality ⇒ DRIFT
        - never raises
    """
    if reason is not None:
        return ( EXIT_CANNOT_DETERMINE, "CANNOT_DETERMINE", reason )
    if head is None:
        return ( EXIT_CANNOT_DETERMINE, "CANNOT_DETERMINE",
                 "the tree reports no head revision — cannot say what 'at head' means" )
    if current is None:
        return ( EXIT_DRIFT, "DRIFT",
                 "the database has NO alembic revision (never stamped) while the tree "
                 f"expects {head}" )
    if current == head:
        return ( EXIT_AT_HEAD, "AT_HEAD", "" )
    return ( EXIT_DRIFT, "DRIFT",
             f"database is at {current}; the checked-out tree expects {head}" )


def main():
    """Print a parseable record and exit with the outcome's code."""
    _bootstrap_sys_path()
    head, current, reason = read_revisions()
    code, verdict, detail = classify( head, current, reason )

    print( f"HEAD_IN_TREE={head if head is not None else ''}" )
    print( f"CURRENT_IN_DB={current if current is not None else ''}" )
    print( f"VERDICT={verdict}" )
    if detail:
        print( f"DETAIL={detail}" )
    return code


if __name__ == "__main__":
    sys.exit( main() )
