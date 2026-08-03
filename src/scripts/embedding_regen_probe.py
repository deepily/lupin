#!/usr/bin/env python3
"""
Build a throwaway CLONE of the embedding tables so the regeneration pipeline can
be exercised end to end without the live tables being written at all.

The live tables are READ (SELECT) and never written. Everything this script
creates lives in its own schema (default ``regen_probe``), which can be dropped
in one statement when the rehearsal is over.

What it gives you: a small, real sample carrying REAL stale vectors and REAL
source text, in a schema the regeneration script can be pointed at with
``--table-prefix=regen_probe.``. That is the difference between testing the
pipeline and testing a mock of it — the rows have the same text lengths, the
same norm-1.0 fingerprints, and the same nulls as production.

Run (from repo root, PYTHONPATH=src):
    python src/scripts/embedding_regen_probe.py status          # what exists now
    python src/scripts/embedding_regen_probe.py create --rows=500 --apply
    python src/scripts/embedding_regen_probe.py drop --apply    # clean up

NOTHING happens without --apply. Every command previews its statements first.

Created: 2026-08-02 (Cheech 🌿) · row 5e848dd8
"""
import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from sqlalchemy import text

from cosa.rest.db.database import get_db
from cosa.rest.db.embedding_regeneration import (
    EMBEDDING_DIM,
    NORMALIZED_NORM_CEILING,
    REGEN_SPECS,
)

PROBE_SCHEMA = "regen_probe"

# One entry per SOURCE table (REGEN_SPECS has two specs sharing input_and_output).
SOURCE_TABLES = [ "input_and_output", "prediction_decisions" ]


def _shadow_columns( table ):
    """Shadow columns the regeneration script expects on a given table."""
    return [ spec.shadow_column for spec in REGEN_SPECS if spec.table == table ]


def _era_predicates( table ):
    """
    Predicates isolating each embedding era, so a clone samples BOTH.

    The whole table gets regenerated now, so a probe drawn only from the norm-1.0
    rows would rehearse the run against a quarter of the data it will actually
    meet — and the OpenAI-era rows are the SHORT ones, so it would also
    under-measure batch timing and text length. Half from each era.

    Ensures:
        - returns [(label, sql_predicate), ...] covering the normalized era and
          the current era, both further restricted to rows that have source text
    """
    vector = next( spec.vector_column for spec in REGEN_SPECS if spec.table == table )
    text   = next( spec.text_column   for spec in REGEN_SPECS if spec.table == table )
    has_text = f"{text} IS NOT NULL AND btrim({text}) <> ''"
    norm     = f"sqrt(({vector} <#> {vector}) * -1)"
    return [
        ( "normalized-era", f"{has_text} AND {vector} IS NOT NULL AND {norm} <= {NORMALIZED_NORM_CEILING}" ),
        ( "current-era",    f"{has_text} AND {vector} IS NOT NULL AND {norm} >  {NORMALIZED_NORM_CEILING}" ),
    ]


def build_statements( rows ):
    """
    Build the full clone script.

    Requires:
        - rows is a positive int — total rows to copy per table, split evenly
          between the two embedding eras

    Ensures:
        - returns an ordered list of SQL strings that create the probe schema,
          clone each table's STRUCTURE, copy a sample spanning BOTH eras, and add
          the shadow columns the regeneration script writes into
        - every statement addresses the probe schema; the live tables appear
          only inside SELECTs
    """
    statements = [ f"CREATE SCHEMA IF NOT EXISTS {PROBE_SCHEMA}" ]
    for table in SOURCE_TABLES:
        target   = f"{PROBE_SCHEMA}.{table}"
        per_era  = max( 1, rows // 2 )
        statements += [
            f"DROP TABLE IF EXISTS {target}",
            # LIKE copies the column types (including vector(768)) but no data.
            f"CREATE TABLE {target} (LIKE public.{table} INCLUDING DEFAULTS)",
        ]
        # The only reads of the live table, and they are SELECTs.
        statements += [
            f"INSERT INTO {target} SELECT * FROM public.{table} "
            f"WHERE {predicate} LIMIT {per_era}  -- {label}"
            for label, predicate in _era_predicates( table )
        ]
        statements += [
            f"ALTER TABLE {target} ADD COLUMN IF NOT EXISTS {column} vector({EMBEDDING_DIM})"
            for column in _shadow_columns( table )
        ]
    return statements


def drop_statements():
    """
    Build the teardown script.

    Ensures:
        - returns a single statement removing the probe schema and everything in it
    """
    return [ f"DROP SCHEMA IF EXISTS {PROBE_SCHEMA} CASCADE" ]


def _execute( statements, apply ):
    """Preview every statement; run them only when apply is True."""
    for statement in statements:
        print( f"  {statement}" )
    if not apply:
        print( "\n[DRY-RUN] nothing executed. Re-run with --apply." )
        return 0
    with get_db() as session:
        for statement in statements:
            session.execute( text( statement ) )
        session.commit()
    print( "\napplied." )
    return 0


def _status():
    """Report what the probe schema currently holds. Read-only."""
    with get_db() as session:
        exists = session.execute( text(
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name = :s"
        ), { "s": PROBE_SCHEMA } ).scalar()
        if not exists:
            print( f"schema {PROBE_SCHEMA} does not exist — nothing to clean up." )
            return 0
        for table in SOURCE_TABLES:
            count = session.execute( text( f"SELECT count(*) FROM {PROBE_SCHEMA}.{table}" ) ).scalar()
            print( f"  {PROBE_SCHEMA}.{table:24} {count:>8,} row(s)" )
    return 0


def main():
    argv    = sys.argv[ 1: ]
    command = argv[ 0 ] if argv and not argv[ 0 ].startswith( "-" ) else "status"
    apply   = "--apply" in argv
    rows    = 500
    for token in argv:
        if token.startswith( "--rows=" ):
            rows = int( token.split( "=", 1 )[ 1 ] )

    if command == "status":
        return _status()
    if command == "create":
        print( f"CREATE probe clone ({rows} stale rows per table):" )
        return _execute( build_statements( rows ), apply )
    if command == "drop":
        print( "DROP probe schema:" )
        return _execute( drop_statements(), apply )

    print( f"unknown command {command!r}; valid: status / drop / create" )
    return 1


if __name__ == "__main__":
    sys.exit( main() )
