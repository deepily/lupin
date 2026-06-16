#!/usr/bin/env python3
"""
Schema parity checker — model columns vs the live database.

For every table in ``Base.metadata`` (the ORM models, the source of truth),
compare the declared columns against the live database's
``information_schema.columns`` and report DRIFT:

    - model-only : a column the ORM model declares but the live DB lacks
                   (this is exactly the ``is_protected`` bug class — a model
                   column with no migration to back it).
    - db-only    : a column the live DB has but the model no longer declares.
    - missing    : an entire model table absent from the live DB.

READ-ONLY: opens a single connection, issues SELECTs against
``information_schema`` only, never mutates. Exits non-zero on any drift so it
can gate a deploy / CI step — the reproducible check that would have caught
``is_protected`` before it broke user-seeding in the cloud.

Usage:
    python src/scripts/check_schema_parity.py
    python src/scripts/check_schema_parity.py --database-url postgresql+psycopg2://u:p@host:5432/db

The URL defaults to the app's own builder (cosa.rest.db.database.get_database_url
via cosa.rest.db.auto_migrate.resolve_database_url), so the check runs against
exactly the DB the app would use, in every environment.
"""

import argparse
import os
import sys

# --- bootstrap: this script may run BEFORE cosa is importable (standalone) ---
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:   # pragma: no cover - import-time env bootstrap (single-arm)
    # Fall back to the repo root inferred from this file's location so the
    # script is runnable without LUPIN_ROOT exported (e.g. ad-hoc operator use).
    _lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
_src_path = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path:   # pragma: no cover - import-time env bootstrap (single-arm)
    sys.path.insert( 0, _src_path )

from sqlalchemy import create_engine, text   # noqa: E402

from cosa.rest.postgres_models import Base                 # noqa: E402
from cosa.rest.db.auto_migrate import resolve_database_url # noqa: E402


def get_model_columns():
    """
    Collect declared columns for every model table.

    Ensures:
        - returns { table_name: set( column_names ) } for all Base.metadata tables

    Returns:
        dict[str, set[str]]
    """
    return {
        table_name: { col.name for col in table.columns }
        for table_name, table in Base.metadata.tables.items()
    }


def get_db_columns( engine, table_names ):
    """
    Collect live columns for the named tables from information_schema.

    Requires:
        - engine is a live SQLAlchemy engine
        - table_names is an iterable of table names to probe (public schema)

    Ensures:
        - returns { table_name: set( column_names ) }; a table absent from the
          live DB maps to an EMPTY set (its model columns then read as drift)

    Returns:
        dict[str, set[str]]
    """
    result = { name: set() for name in table_names }
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ANY( :names )"
            ),
            { "names": list( table_names ) },
        )
        for table_name, column_name in rows:
            result[ table_name ].add( column_name )
    return result


def compute_drift( model_columns, db_columns ):
    """
    Compute per-table drift between model and live DB columns.

    Requires:
        - model_columns and db_columns are { table: set(cols) } over the same
          set of table names

    Ensures:
        - returns { table: { "model_only": sorted[str], "db_only": sorted[str],
          "missing_table": bool } } for every table that has ANY drift; tables
          in parity are omitted

    Returns:
        dict[str, dict]
    """
    drift = {}
    for table_name, model_cols in model_columns.items():
        db_cols    = db_columns.get( table_name, set() )
        model_only = model_cols - db_cols
        db_only    = db_cols - model_cols
        # An entirely-absent live table reads as "every model column is missing".
        missing_table = len( db_cols ) == 0

        if model_only or db_only:
            drift[ table_name ] = {
                "model_only"    : sorted( model_only ),
                "db_only"       : sorted( db_only ),
                "missing_table" : missing_table,
            }
    return drift


def format_report( drift ):
    """
    Render a human-readable drift report.

    Args:
        drift: output of compute_drift

    Returns:
        str — the report text (a clean "in parity" line when drift is empty)
    """
    if not drift:
        return "✓ Schema parity: every model table matches the live database."

    lines = [ "✗ Schema DRIFT detected (model is the source of truth):", "" ]
    for table_name in sorted( drift ):
        info = drift[ table_name ]
        tag  = " (TABLE MISSING from live DB)" if info[ "missing_table" ] else ""
        lines.append( f"  Table '{table_name}'{tag}:" )
        if info[ "model_only" ]:
            lines.append( f"    model-only (needs a migration): {info['model_only']}" )
        if info[ "db_only" ]:
            lines.append( f"    db-only    (orphaned column)   : {info['db_only']}" )
    return "\n".join( lines )


def check_parity( database_url=None ):
    """
    Run the parity check against the resolved database.

    Requires:
        - the resolved database is reachable (read-only)

    Ensures:
        - returns ( drift_dict, report_str ); read-only, no mutation

    Args:
        database_url: optional explicit URL (None → app builder)

    Returns:
        tuple( dict, str )
    """
    url           = resolve_database_url( database_url )
    model_columns = get_model_columns()
    engine        = create_engine( url )
    try:
        db_columns = get_db_columns( engine, model_columns.keys() )
    finally:
        engine.dispose()
    drift = compute_drift( model_columns, db_columns )
    return drift, format_report( drift )


def main( argv=None ):
    """
    CLI entry point. Returns a process exit code (0 = parity, 1 = drift).

    Args:
        argv: optional argument list (defaults to sys.argv[1:])

    Returns:
        int — 0 when in parity, 1 when any drift is found
    """
    parser = argparse.ArgumentParser( description="Check ORM-model vs live-DB schema parity (read-only)." )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy URL to check (default: the app's get_database_url builder).",
    )
    args = parser.parse_args( argv )

    drift, report = check_parity( database_url=args.database_url )
    print( report )
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit( main() )
