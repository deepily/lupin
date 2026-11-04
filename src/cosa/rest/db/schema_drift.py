"""
ORM-vs-database schema drift detector, the startup alarm (fail-open).

Why this exists:
    A ``mapped_column`` can land in ``postgres_models.py`` before its migration exists.
    With uvicorn ``--reload`` off on ``:7999``, a model edit sits inert until a bounce.
    So the migration must be applied before the bounce, not only committed first.
    Otherwise the model and its column land together at restart. The ORM then selects
    a column the database lacks, and every read of that table returns 500 fleet-wide.
    ``/api/tasks`` is the task store that the Stop-hook and the arbiter both read.
    A pytest-tier detector fires only when someone runs pytest, after reads fail.
    This module fires at boot, on the box where the drift landed.

Design contract:
    1. Fail-open, always. Drift produces an alarm and the server serves anyway. A
       refused boot would take down the box carrying the MCP transport, the task
       store and the owed-work oracle. That turns a partial outage into a total one.
       The worst case here is a false alarm, which is the correct price.
    2. The alarm of record is the synchronous `CRITICAL` log on stderr, which needs no
       network, auth, event loop or database. Any richer channel is decoration on top,
       and its failure must never degrade the alarm.
    3. Nothing here may raise or block. ``emit_startup_drift_alarm`` swallows every
       exception, including one raised while reporting an exception.
    4. Read-only against the database: reflection via ``inspect(engine)`` only.
       ``MigrationContext.get_current_heads()`` returns ``()`` without a version table
       and never calls ``_ensure_version_table()``, so it creates no table.
    5. The alarm names model, table, column and revisions, so no re-diagnosis is needed.

Placement:
    Called from the ``lupin_app.main`` lifespan after ``run_migrations_to_head()``.
    ``upgrade head`` cannot invent a migration for a column that has none, so the
    defect survives auto-migrate and is visible afterwards. Running before it would
    alarm on every legitimately pending migration, and such an alarm gets ignored.

Named limits (the detector is partial and is not sold as complete):
    - It checks the ORM-has / DB-lacks direction only, the class that causes a 500.
      A column the DB has and the ORM lacks is harmless to reads and not reported.
    - It compares presence, not type, nullability or server default. Presence is what
      raises ``UndefinedColumn``. Type nuance belongs to the ``compare_metadata()``
      tier. Presence-only means no false alarms from reflection nuance.
    - It reads ``postgres_models.Base`` only; tables on another base are invisible.
"""

import asyncio
import sys
import traceback

from sqlalchemy import create_engine, inspect


# How long the post-startup notification may take before it is abandoned. Short
# by design: the notify is the SECOND channel and the CRITICAL log has already
# fired, so a slow delivery must never linger. Not a config key — one knob for
# the recipient is the ratified surface; a timeout knob would be noise.
NOTIFY_TIMEOUT_SECONDS = 5.0


# Drift kinds, so callers/tests match on a constant rather than a magic string.
KIND_MISSING_TABLE  = "missing_table"
KIND_MISSING_COLUMN = "missing_column"
# Row 0aae1a28 (c). The DB is stamped BEHIND the tree's head while every mapped
# column happens to be present. Column-diffing is STRUCTURALLY BLIND to this: a
# migration that only adds an index, a constraint, or changes a column TYPE moves
# the revision without changing the column set, so `find_missing_columns` returns
# empty and the old early-return meant the revisions were never even read.
KIND_REVISION_BEHIND = "revision_behind_head"


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

    This is the whole oracle. It is small and one-directional: ORM-has / DB-lacks
    is the class that produces a live 500.

    Requires:
        - engine is a connectable SQLAlchemy Engine
        - metadata is the MetaData carrying the mapped tables

    Ensures:
        - returns a list of drift dicts, sorted by (table, column) for a stable
          alarm text across boots
        - a table missing entirely yields one row (kind=missing_table) and its
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

    Both are advisory context for the alarm text and never a gate. A drift finding
    stands whether or not the revisions could be read.

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
    Render the `CRITICAL` alarm text.

    Names model, table, column and both revisions, so the reader can act
    without re-deriving the diagnosis.

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
    # The two findings have DIFFERENT diagnoses and DIFFERENT remedies, so the
    # header must not assert the column one when only a revision gap was found.
    # A missing column is a live 500; a revision gap alone is not — saying it is
    # would be an alarm that overstates, and an alarm that overstates gets
    # discounted the next time it fires correctly.
    has_columns  = any( row[ "kind" ] != KIND_REVISION_BEHIND for row in drift )
    has_revision = any( row[ "kind" ] == KIND_REVISION_BEHIND for row in drift )

    lines = [
        "=" * 78,
        "CRITICAL: ORM/DATABASE SCHEMA DRIFT DETECTED AT STARTUP" if has_columns
        else "WARNING: DATABASE IS BEHIND THE TREE'S MIGRATION HEAD",
        "=" * 78,
    ]

    if has_columns:
        lines += [
            "The ORM maps columns the live database does not have. Reads of the",
            "affected tables will fail with UndefinedColumn (HTTP 500) until the",
            "missing migration lands. The server is starting ANYWAY (fail-open).",
        ]
    else:
        lines += [
            "Every mapped column is present, so this is NOT a live 500 — but the",
            "database is stamped behind the tree's head. A migration that changes",
            "only an index, a constraint, or a column TYPE moves the revision",
            "without changing the column set, which is why the column check above",
            "reads clean. The server is starting ANYWAY (fail-open).",
        ]

    lines += [
        "",
        f"  DB stamped revision : {db_revision or 'unknown'}",
        f"  Migration head      : {head_revision or 'unknown'}",
        "",
        f"  {len( drift )} drift finding(s):",
    ]

    for row in drift:
        if row[ "kind" ] == KIND_REVISION_BEHIND:
            lines.append( f"    - REVISION BEHIND  db={db_revision or 'unknown'} tree={head_revision or 'unknown'}" )
        elif row[ "kind" ] == KIND_MISSING_TABLE:
            lines.append( f"    - TABLE MISSING  {row[ 'table' ]}  (model {row[ 'model' ]})" )
        else:
            lines.append( f"    - COLUMN MISSING {row[ 'table' ]}.{row[ 'column' ]}  (model {row[ 'model' ]})" )

    lines.append( "" )
    if has_columns:
        lines += [
            "  Remedy: write the missing Alembic migration (never a hand-run ALTER)",
            "  and restart. Do NOT add the column to an allowlist.",
        ]
    if has_revision:
        lines += [
            "  Remedy for the revision gap: the startup migrate did NOT take. This",
            "  runs AFTER 'alembic upgrade head', so reaching it means the upgrade",
            "  no-opped against a database it did not move. Check which database",
            "  the app resolved and re-run the migrate against THAT one.",
        ]
    lines.append( "=" * 78 )
    return "\n".join( lines )


def check_schema_drift( database_url=None ):
    """
    Compare the ORM metadata against the live database.

    Ensures:
        - returns a report dict { drift, db_revision, head_revision } when drift
          is present
        - returns None when the database satisfies every mapped column
        - disposes the engine it creates
        - may raise: this is the inner, testable form. The boot path calls
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
        # ⚠️ READ THE REVISIONS ALWAYS (row 0aae1a28 (c)). This used to sit behind
        # `if not drift: return None`, which made the revision comparison DEAD
        # CODE unless a column was already missing — the revisions were only ever
        # decoration on an alarm raised by something else. A DB one migration
        # behind on an index/constraint/type-only change has a complete column
        # set, so the old early-return reported it clean.
        db_revision, head_revision = read_revisions( engine )
    finally:
        engine.dispose()

    # Only when BOTH are readable can they disagree meaningfully. An unreadable
    # revision degrades to None and must not manufacture an alarm — that would be
    # a detector that fires on its own blindness.
    if db_revision is not None and head_revision is not None and db_revision != head_revision:
        drift = drift + [ {
            "kind"     : KIND_REVISION_BEHIND,
            "table"    : None,
            "column"   : None,
            "model"    : None,
        } ]

    if not drift:
        return None

    return {
        "drift"         : drift,
        "db_revision"   : db_revision,
        "head_revision" : head_revision
    }


def emit_startup_drift_alarm( database_url=None, debug=False ):
    """
    Boot-path entry point: detect drift, log the `CRITICAL` alarm, never raise.

    It makes no network call, awaits nothing, and swallows every exception,
    including one raised while reporting an exception. That is the fail-open
    contract: a bug here must never abort a boot that would otherwise succeed.

    Ensures:
        - on drift: writes the `CRITICAL` alarm to stderr and returns the report
        - on no drift: returns None (and prints a one-liner when debug)
        - on any internal failure: returns None, having written a bounded
          diagnostic to stderr; never propagates
        - performs no network I/O and no awaiting

    Args:
        database_url: optional explicit URL (None → the app's resolved URL)
        debug:        when True, print a one-liner on the clean path

    Returns:
        dict | None — the drift report, for a caller that wants to route it to a
        richer channel after startup completes. Never required.
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


# ─────────────────────────────────────────────────────────────────────────────
# The notification leg — the SECOND channel, never the first.
#
# Ratified by Rick 2026-07-19: one INI key naming the recipient, EMPTY DEFAULT.
# Empty means the notify is not attempted at all and the CRITICAL log stands
# alone. That default is the load-bearing part: an unconfigured deployment
# degrades to log-only rather than misdelivering the alarm to a guessed
# identity. There is no fallback recipient, and inventing one would be the bug.
#
# Every constraint from the lifespan contract still binds here:
#   - nothing in this section is awaited in the pre-yield critical path
#   - delivery is scheduled as a task that cannot begin until the app is serving
#   - the whole path is timeout-bounded and every exception is swallowed
#   - stderr CRITICAL has ALREADY fired before any of this runs
# ─────────────────────────────────────────────────────────────────────────────


def build_drift_notification( report ):
    """
    Render the spoken message and the detail card for the drift notification.

    Ensures:
        - the spoken line is short enough for TTS and names the count, not the
          inventory; the per-column detail goes in the abstract
        - the abstract names model, table, and column for every finding

    Args:
        report: the dict returned by check_schema_drift()

    Returns:
        tuple( message: str, abstract: str )
    """
    drift   = report[ "drift" ]
    plural  = "s" if len( drift ) != 1 else ""
    message = (
        f"Schema drift detected at startup: {len( drift )} finding{plural}. "
        "The server is serving anyway. Check the container log for the critical alarm."
    )
    abstract = format_drift_alarm( drift, report[ "db_revision" ], report[ "head_revision" ] )
    return ( message, abstract )


def push_drift_notification( report, recipient_email, notification_queue ):
    """
    Resolve the configured recipient and enqueue the drift notification.

    Synchronous and blocking (a DB lookup plus a queue push), so callers run it
    off the event loop. It is separate from the async wrapper so the resolution
    logic can be tested without an event loop.

    Requires:
        - recipient_email is a non-empty string
        - notification_queue exposes push_notification()

    Ensures:
        - returns True when a notification was enqueued
        - returns False when the configured recipient does not resolve to a user,
          having warned on stderr, because a misconfigured key must be visible and
          push_notification() itself accepts an unknown user_id silently, so the
          alarm would otherwise vanish without trace

    Args:
        report:             the drift report
        recipient_email:    the configured recipient address
        notification_queue: the live NotificationFifoQueue

    Returns:
        bool
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.user_repository import UserRepository

    db = next( get_db() )
    try:
        user = UserRepository( db ).get_by_email( recipient_email )
    finally:
        db.close()

    if user is None:
        # Deliberately loud. A silent skip here would look identical to a clean
        # boot, which is the failure mode the whole detector exists to remove.
        print(
            f"[schema-drift] WARNING: configured alarm recipient '{recipient_email}' "
            "does not resolve to a user; drift notification NOT sent. The CRITICAL "
            "log above stands as the alarm of record.",
            file  = sys.stderr,
            flush = True
        )
        return False

    message, abstract = build_drift_notification( report )
    notification_queue.push_notification(
        message  = message,
        type     = "alert",
        priority = "urgent",
        user_id  = str( user.id ),
        abstract = abstract,
        source   = "schema_drift_alarm"
    )
    return True


async def deliver_drift_notification( report, recipient_email, notification_queue,
                                      timeout_seconds=NOTIFY_TIMEOUT_SECONDS ):
    """
    Deliver the drift notification, bounded and non-fatal.

    Ensures:
        - the blocking work runs in a worker thread, so a slow DB lookup cannot
          stall the event loop of a server that is already accepting traffic
        - abandoned after timeout_seconds
        - never raises: a delivery failure is reported to stderr and swallowed,
          because the alarm of record has already fired and the second channel
          must not be able to damage the first

    Args:
        report:             the drift report
        recipient_email:    the configured recipient address
        notification_queue: the live NotificationFifoQueue
        timeout_seconds:    delivery deadline

    Returns:
        bool — True when a notification was enqueued, False otherwise
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread( push_drift_notification, report, recipient_email, notification_queue ),
            timeout = timeout_seconds
        )
    except Exception:
        print( "[schema-drift] WARNING: drift notification failed; CRITICAL log stands.", file=sys.stderr )
        traceback.print_exc( file=sys.stderr )
        return False


def schedule_drift_notification( report, recipient_email, notification_queue,
                                 timeout_seconds=NOTIFY_TIMEOUT_SECONDS ):
    """
    Schedule the drift notification to run once the app is serving.

    create_task() only queues the coroutine until the lifespan yields, so a pre-yield
    call is non-blocking; awaiting pre-yield would dial a server not yet accepting.
    A post-yield call would run at shutdown, since main.py has one yield.

    Ensures:
        - returns None without scheduling anything when there is no drift, no
          recipient configured (the empty default, the common case), or no queue
        - returns the created Task otherwise
        - never raises, including when there is no running event loop

    Args:
        report:             the drift report, or None when there is no drift
        recipient_email:    configured recipient, or "" / None when unconfigured
        notification_queue: the live NotificationFifoQueue, or None
        timeout_seconds:    delivery deadline

    Returns:
        asyncio.Task | None
    """
    if report is None or not recipient_email or notification_queue is None:
        return None

    coroutine = deliver_drift_notification( report, recipient_email, notification_queue, timeout_seconds )
    try:
        return asyncio.create_task( coroutine )
    except Exception:
        # Close the orphaned coroutine explicitly. Left dangling it raises
        # "coroutine was never awaited" from the GC at an arbitrary later point,
        # attributing a warning to whatever code happens to be running then.
        coroutine.close()
        print( "[schema-drift] WARNING: could not schedule drift notification; CRITICAL log stands.", file=sys.stderr )
        return None
