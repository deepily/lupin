"""
ORM-vs-database schema drift detector — the startup alarm (Half 3b, FAIL-OPEN).

Why this exists
---------------
A ``mapped_column`` can land in ``postgres_models.py`` before its migration
exists. On ``:7999`` uvicorn runs with ``--reload``, so **the model edit IS the
deploy**: the ORM immediately SELECTs a column the database lacks and every read
of that table 500s fleet-wide.

Measured incident (2026-07-19): ``task_items.park_reason_captured_at`` — 12 live
500s on ``/api/tasks`` over 2m 28s. ``/api/tasks`` is the task store, the
owed-work oracle that both the Stop-hook and the arbiter read, so a read outage
there is fleet-wide rather than local.

A pytest-tier detector only fires when someone runs pytest — which is *after* the
store has already 500'd. This module is the tier that fires at boot, on the box
where the drift actually landed.

Design contract (all of it load-bearing)
----------------------------------------
1. **FAIL-OPEN, always.** Drift produces an alarm and the server **SERVES
   ANYWAY**. A refused boot would take down the box carrying the MCP transport,
   the task store, and the owed-work oracle — converting a partial outage into a
   total one. Worst case here is a false alarm, which is the correct price.

2. **The alarm of record is the synchronous CRITICAL log on stderr.** stderr has
   no dependencies: no network, no auth, no event loop, no database. Any richer
   channel (a UI notification) is strictly decoration layered on top, and its
   failure must never degrade the alarm.

3. **Nothing here may raise, and nothing here may block.**
   :func:`emit_startup_drift_alarm` swallows every exception, including
   exceptions raised while reporting an exception. A detector bug must not be
   able to abort a boot that would otherwise have succeeded.

4. **Read-only against the database.** Verified at source before use, because a
   comparison run at boot must not itself mutate the schema it is judging:
   - ``inspect(engine).get_table_names() / get_columns()`` — reflection only.
   - ``MigrationContext.get_current_heads()`` guards on ``_has_version_table()``
     and returns ``()`` when absent; it does **not** call
     ``_ensure_version_table()``, so no ``CREATE TABLE`` is issued
     (alembic 1.18.1, ``runtime/migration.py:499-542``).

5. **The alarm names model, table, column, and revisions.** A startup alarm
   reading only "drift detected" reproduces the diagnosis cost it exists to
   remove (Mr. Radio's constraint).

Placement
---------
Called from the ``lupin_app.main`` lifespan **after** ``run_migrations_to_head()``.
"After" is correct and was ruled on: ``upgrade head`` cannot fabricate a
migration for a column that has none, so the target defect survives auto-migrate
untouched and is fully visible afterwards. Running "before" would instead alarm
on every legitimately-pending migration — a false alarm on every boot after any
new migration lands, which is how a detector gets ignored into uselessness.

Named limits (this detector is partial, and is not sold as complete)
--------------------------------------------------------------------
- It checks the **ORM-has / DB-lacks** direction only. That is precisely the
  500-causing class. A column the DB has but the ORM does not is harmless to
  reads and is deliberately not reported here.
- It compares **presence**, not type, nullability, or server default. Presence is
  what produces ``UndefinedColumn``; type nuance is the ``compare_metadata()``
  tier's job (Half 2), which is where a richer diff belongs. Keeping this tier
  presence-only is deliberate: it has no false-alarm surface from reflection
  nuance, and an alarm that cries wolf gets ignored.
- It reads ``postgres_models.Base`` only. Tables mapped on any other declarative
  base are invisible to it.
"""

import sys
import traceback

from sqlalchemy import create_engine, inspect


# Drift kinds, so callers/tests match on a constant rather than a magic string.
KIND_MISSING_TABLE  = "missing_table"
KIND_MISSING_COLUMN = "missing_column"


def model_names_by_table( base ):
    """
    Map each mapped table name to its ORM class name, for alarm text.

    Requires:
        - base is a DeclarativeBase subclass with a populated registry

    Ensures:
        - returns dict { table_name: class_name } for every mapper whose
          local_table is resolvable
        - mappers with no local_table are skipped rather than raising

    Args:
        base: the declarative base (e.g. cosa.rest.postgres_models.Base)

    Returns:
        dict[str, str]
    """
    names = {}
    for mapper in base.registry.mappers:
        local_table = mapper.local_table
        if local_table is not None:
            names[ local_table.name ] = mapper.class_.__name__
    return names


def find_missing_columns( engine, metadata, model_names=None ):
    """
    Find ORM-mapped tables/columns that the live database does not have.

    This is the whole oracle. It is deliberately small and deliberately
    one-directional: ORM-has / DB-lacks is the class that produces a live 500.

    Requires:
        - engine is a connectable SQLAlchemy Engine
        - metadata is the MetaData carrying the mapped tables

    Ensures:
        - returns a list of drift dicts, sorted by (table, column) for a stable
          alarm text across boots
        - a table missing entirely yields ONE row (kind=missing_table) and its
          columns are not enumerated — the table is the actionable unit
        - returns [] when the database satisfies every mapped column
        - performs no writes

    Args:
        engine:      SQLAlchemy Engine to reflect
        metadata:    MetaData whose tables are compared against the DB
        model_names: optional { table: class_name } for richer alarm text

    Returns:
        list[dict] with keys: table, column, model, kind
    """
    if model_names is None:
        model_names = {}

    inspector = inspect( engine )
    db_tables = set( inspector.get_table_names() )
    drift     = []

    for table in metadata.tables.values():

        model = model_names.get( table.name, "?" )

        if table.name not in db_tables:
            drift.append( {
                "table"  : table.name,
                "column" : None,
                "model"  : model,
                "kind"   : KIND_MISSING_TABLE
            } )
            continue

        db_columns = { column[ "name" ] for column in inspector.get_columns( table.name ) }

        for column in table.columns:
            if column.name not in db_columns:
                drift.append( {
                    "table"  : table.name,
                    "column" : column.name,
                    "model"  : model,
                    "kind"   : KIND_MISSING_COLUMN
                } )

    drift.sort( key=lambda row: ( row[ "table" ], row[ "column" ] or "" ) )
    return drift


def read_revisions( engine ):
    """
    Best-effort read of the DB's stamped revision and the migration-script head.

    Both are advisory context for the alarm text, never a gate: a drift finding
    stands on its own whether or not the revisions could be read.

    Ensures:
        - returns ( db_revision, head_revision ), either of which may be None
        - never raises — an unreadable revision degrades to None

    Args:
        engine: SQLAlchemy Engine

    Returns:
        tuple( str|None, str|None )
    """
    db_revision   = None
    head_revision = None

    try:
        from alembic.runtime.migration import MigrationContext
        with engine.connect() as connection:
            # Read-only: get_current_heads() short-circuits on a missing version
            # table and never issues DDL (verified at alembic source).
            heads = MigrationContext.configure( connection ).get_current_heads()
        db_revision = ",".join( heads ) if heads else None
    except Exception:
        db_revision = None

    try:
        from alembic.script import ScriptDirectory
        from cosa.rest.db.auto_migrate import build_alembic_config
        head_revision = ScriptDirectory.from_config( build_alembic_config() ).get_current_head()
    except Exception:
        head_revision = None

    return ( db_revision, head_revision )


def format_drift_alarm( drift, db_revision, head_revision ):
    """
    Render the CRITICAL alarm text.

    Names model, table, column, and both revisions, so the reader can act
    without re-deriving the diagnosis the alarm exists to remove.

    Requires:
        - drift is a non-empty list of drift dicts

    Ensures:
        - returns a multi-line string naming every drifted table/column
        - includes the stamped and head revisions (or "unknown" when unreadable)

    Args:
        drift:         list of drift dicts from find_missing_columns()
        db_revision:   the DB's stamped alembic revision, or None
        head_revision: the migration-script head revision, or None

    Returns:
        str
    """
    lines = [
        "=" * 78,
        "CRITICAL: ORM/DATABASE SCHEMA DRIFT DETECTED AT STARTUP",
        "=" * 78,
        "The ORM maps columns the live database does not have. Reads of the",
        "affected tables will fail with UndefinedColumn (HTTP 500) until the",
        "missing migration lands. The server is starting ANYWAY (fail-open).",
        "",
        f"  DB stamped revision : {db_revision or 'unknown'}",
        f"  Migration head      : {head_revision or 'unknown'}",
        "",
        f"  {len( drift )} drift finding(s):",
    ]

    for row in drift:
        if row[ "kind" ] == KIND_MISSING_TABLE:
            lines.append( f"    - TABLE MISSING  {row[ 'table' ]}  (model {row[ 'model' ]})" )
        else:
            lines.append( f"    - COLUMN MISSING {row[ 'table' ]}.{row[ 'column' ]}  (model {row[ 'model' ]})" )

    lines += [
        "",
        "  Remedy: write the missing Alembic migration (never a hand-run ALTER)",
        "  and restart. Do NOT add the column to an allowlist.",
        "=" * 78,
    ]
    return "\n".join( lines )


def check_schema_drift( database_url=None ):
    """
    Compare the ORM metadata against the live database.

    Ensures:
        - returns a report dict { drift, db_revision, head_revision } when drift
          is present
        - returns None when the database satisfies every mapped column
        - disposes the engine it creates
        - MAY raise — this is the inner, testable form. The boot path calls
          emit_startup_drift_alarm(), which is the one that cannot raise.

    Args:
        database_url: optional explicit URL (None → the app's resolved URL)

    Returns:
        dict | None
    """
    from cosa.rest.db.auto_migrate import resolve_database_url
    from cosa.rest.postgres_models import Base

    url    = resolve_database_url( database_url )
    engine = create_engine( url )
    try:
        drift = find_missing_columns( engine, Base.metadata, model_names_by_table( Base ) )
        if not drift:
            return None
        db_revision, head_revision = read_revisions( engine )
    finally:
        engine.dispose()

    return {
        "drift"         : drift,
        "db_revision"   : db_revision,
        "head_revision" : head_revision
    }


def emit_startup_drift_alarm( database_url=None, debug=False ):
    """
    The boot-path entry point: detect drift and log the CRITICAL alarm.

    This function is **structurally incapable of raising or blocking**. It makes
    no network call, awaits nothing, and swallows every exception — including one
    raised while reporting an exception. That is not defensive habit: it is the
    fail-open contract. A bug in this detector must never be able to abort a boot
    that would otherwise have succeeded.

    Ensures:
        - on drift: writes the CRITICAL alarm to stderr and returns the report
        - on no drift: returns None (and prints a one-liner when debug)
        - on ANY internal failure: returns None, having written a bounded
          diagnostic to stderr; never propagates
        - performs NO network I/O and NO awaiting

    Args:
        database_url: optional explicit URL (None → the app's resolved URL)
        debug:        when True, print a one-liner on the clean path

    Returns:
        dict | None — the drift report, for a caller that wants to route it to a
        richer channel AFTER startup completes. Never required.
    """
    try:
        report = check_schema_drift( database_url=database_url )

        if report is None:
            if debug: print( "[schema-drift] No ORM/database drift detected." )
            return None

        # The alarm of record. stderr, synchronous, no dependencies.
        print(
            format_drift_alarm( report[ "drift" ], report[ "db_revision" ], report[ "head_revision" ] ),
            file  = sys.stderr,
            flush = True
        )
        return report

    except Exception:
        # The detector itself failed. Say so loudly, then get out of the way of
        # the boot. The inner try/except guards the pathological case where even
        # writing the diagnostic raises (e.g. a closed stderr).
        try:
            print( "[schema-drift] WARNING: drift check failed; continuing boot (fail-open).", file=sys.stderr )
            traceback.print_exc( file=sys.stderr )
        except Exception:  # pragma: no cover - stderr itself is unwritable; nothing left to report with
            pass
        return None
