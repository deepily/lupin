#!/usr/bin/env python3
"""
One-time OFFLINE LanceDB → Postgres+pgvector backfill utility (v0.2.0 Lane D · P4).

Q1 ruled BACKFILL (Rick, 2026-07-02 — "memory is the product"): the durable-value
LanceDB tables are exported into their Postgres mirrors at cutover so the flip to
``vector store backend = postgres`` inherits accumulated memory rather than starting
cold. The pure caches (``question_embeddings`` / ``embedding_cache`` / ``gist_cache``
/ ``query_log``) stay FRESH-START (empty; no code here) per design §5.

Three durable tables move (all in the single store lupin.lancedb, grounded in the
Lane A P0 inventory):

    input_and_output_tbl (190,677) → InputAndOutput      keystone solution/IO store
    solution_snapshots   (35)      → SolutionSnapshot     curated snapshots (7 vectors)
    canonical_synonyms   (57)      → CanonicalSynonym     heals Cheech's synonym-loss
                                                          advisory (fresh-start would
                                                          drop the L1/L2 fast-path)

This is NOT in-app migration code (feedback_no_migration_code carves out the one-time
offline export). It honors drop+recreate by loading into freshly-created (empty)
alembic tables and offering truncate-then-load re-run semantics.

Structure mirrors the in-repo ``persona_key_backfill.py`` exemplar: a PURE, fully
covered core (transforms + ``backfill_table``) plus a thin ``# pragma: no cover``
LanceDB-read / DB-session / CLI boundary.

Run (from repo root, PYTHONPATH=src):
    python -m cosa.rest.db.vector_store_backfill                       # DRY-RUN preview (all 3)
    python -m cosa.rest.db.vector_store_backfill --apply               # load into empty tables
    python -m cosa.rest.db.vector_store_backfill --apply --truncate    # reload deterministically
    python -m cosa.rest.db.vector_store_backfill --apply --only=canonical_synonyms   # synonym heal only

Design authority: lupin ->
    src/rnd/v0.2.0/2026.07.02-lane-d-p4-offline-backfill-utility.md
    src/rnd/v0.2.0/2026.06.30-lancedb-to-postgres-pgvector-migration-design.md (§5/§8-P4/§9)

Created: 2026-07-02 (Lane D · Tiffany 💍) · v0.2.0
"""
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional

import numpy as np
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import ARRAY
from pgvector.sqlalchemy import Vector

from cosa.rest.db.vector_store_models import (
    InputAndOutput,
    SolutionSnapshot,
    CanonicalSynonym,
)


# Relative path (under project root) of the single live LanceDB store that holds
# all three source tables (Lane A P0 §1).
_STORE_REL_PATH = "/src/conf/long-term-memory/lupin.lancedb"


# --------------------------------------------------------------------------- #
# Pure value coercers — LanceDB/pyarrow cell → Postgres-ready python value.
# --------------------------------------------------------------------------- #
def _is_na( value: Any ) -> bool:
    """
    True iff a scalar is a null / NaN / NaT (not-a-value) marker.

    Requires:
        - value is a scalar (or None); array-valued inputs are treated as non-NA

    Ensures:
        - returns True for None
        - returns True for NaN float / pandas.NaT / numpy datetime64('NaT')
          (all of which compare unequal to themselves)
        - returns False for any ordinary value, and for inputs whose ``!=`` is
          not a plain bool (e.g. arrays) — those are NOT treated as NA
    """
    if value is None:
        return True
    try:
        return bool( value != value )
    except Exception:
        return False


def _to_vec( value: Any ) -> Optional[List[float]]:
    """
    Coerce a LanceDB fixed-size-list embedding cell to a python ``list[float]``.

    Requires:
        - value is a numpy array, a sequence of numbers, or None

    Ensures:
        - returns None for None or an empty vector
        - returns a plain ``list[float]`` (numpy → tolist) otherwise, verbatim
          (NO re-embedding / normalization — the keystone stays unnormalized)
    """
    if value is None:
        return None
    seq = value.tolist() if hasattr( value, "tolist" ) else list( value )
    if len( seq ) == 0:
        return None
    return [ float( x ) for x in seq ]


def _to_str_list( value: Any ) -> Optional[List[str]]:
    """
    Coerce a LanceDB ``list<string>`` cell to a python ``list`` for ARRAY(Text).

    Requires:
        - value is a numpy array, a sequence, or None

    Ensures:
        - returns None for None
        - returns a plain ``list`` (numpy → tolist) otherwise (empty list preserved)
    """
    if value is None:
        return None
    return value.tolist() if hasattr( value, "tolist" ) else list( value )


def _to_datetime( value: Any ) -> Optional[datetime]:
    """
    Coerce a LanceDB timestamp cell to a python ``datetime``.

    Requires:
        - value is a datetime, numpy.datetime64, epoch-ms number, or a null/NaT
          marker

    Ensures:
        - returns None for null/NaT
        - returns the value unchanged when already a ``datetime`` (pandas.Timestamp
          is a datetime subclass and is honored here — LanceDB timestamp[ms] cells
          arrive as python datetime)
        - converts numpy.datetime64 (via ms) and an epoch-millisecond number (utc)
          to ``datetime``
    """
    if _is_na( value ):
        return None
    if isinstance( value, datetime ):
        return value
    if isinstance( value, np.datetime64 ):
        ms = int( value.astype( "datetime64[ms]" ).astype( "int64" ) )
        return _naive_utc_from_ms( ms )
    return _naive_utc_from_ms( float( value ) )


def _naive_utc_from_ms( epoch_ms: float ) -> datetime:
    """
    Convert an epoch-millisecond value to a NAIVE UTC ``datetime``.

    Requires:
        - epoch_ms is a number of milliseconds since the Unix epoch

    Ensures:
        - returns a tz-naive UTC datetime (matches the naive DateTime columns and
          the naive python datetimes LanceDB timestamp[ms] cells arrive as)
    """
    return datetime.fromtimestamp( epoch_ms / 1000.0, tz=timezone.utc ).replace( tzinfo=None )


def _clean_scalar( value: Any ) -> Any:
    """
    Coerce a LanceDB scalar cell to a plain python scalar.

    Requires:
        - value is a scalar (numpy scalar, python scalar, or None)

    Ensures:
        - returns None for null / NaN
        - unwraps a numpy scalar to its python equivalent (.item())
        - returns any other value unchanged
    """
    if _is_na( value ):
        return None
    if isinstance( value, np.generic ):
        return value.item()
    return value


# --------------------------------------------------------------------------- #
# Column-kind dispatch — one generic row transform for all three tables. The
# kind is read from the Lane B model's own column TYPE (not a hand-kept list),
# so the transform tracks the schema instead of drifting from it.
# --------------------------------------------------------------------------- #
def _classify( column ) -> str:
    """
    Classify a SQLAlchemy column by the coercer its type needs.

    Requires:
        - column is a SQLAlchemy Column with a ``.type``

    Ensures:
        - returns "vec" for pgvector Vector, "array" for postgres ARRAY,
          "dt" for DateTime, else "scalar"
    """
    column_type = column.type
    if isinstance( column_type, Vector ):
        return "vec"
    if isinstance( column_type, ARRAY ):
        return "array"
    if isinstance( column_type, DateTime ):
        return "dt"
    return "scalar"


def _row_to_kwargs( row: Dict[str, Any], model, skip ) -> Dict[str, Any]:
    """
    Transform one LanceDB source-row dict into ``model( **kwargs )`` arguments.

    Requires:
        - row is a dict keyed by source column name (missing keys read as None)
        - model is a Lane B vector-store model class
        - skip is a set of column names to omit (e.g. the synthetic autoincrement PK)

    Ensures:
        - returns a kwargs dict covering every model column except those in skip,
          each value coerced by its column kind (vec / array / dt / scalar)
    """
    kwargs: Dict[str, Any] = { }
    for column in model.__table__.columns:
        name = column.name
        if name in skip:
            continue
        raw  = row.get( name )
        kind = _classify( column )
        if kind == "vec":
            kwargs[ name ] = _to_vec( raw )
        elif kind == "array":
            kwargs[ name ] = _to_str_list( raw )
        elif kind == "dt":
            kwargs[ name ] = _to_datetime( raw )
        else:
            kwargs[ name ] = _clean_scalar( raw )
    return kwargs


# --------------------------------------------------------------------------- #
# Table registry — what moves. Extend by one row if the Manager later rules
# prediction_decisions into Lane D (no structural change).
# --------------------------------------------------------------------------- #
class BackfillSpec( NamedTuple ):
    """One durable table's export plan (source table → target model)."""
    label:        str
    source_table: str
    model:        Any
    skip:         frozenset


BACKFILL_SPECS: List[BackfillSpec] = [
    BackfillSpec( "input_and_output",   "input_and_output_tbl", InputAndOutput,   frozenset( { "id" } ) ),
    BackfillSpec( "solution_snapshots", "solution_snapshots",   SolutionSnapshot, frozenset() ),
    BackfillSpec( "canonical_synonyms", "canonical_synonyms",   CanonicalSynonym, frozenset() ),
]


def backfill_table( session, model, source_rows: Iterable[Dict[str, Any]], *,
                    skip=frozenset(), apply: bool = False,
                    truncate: bool = False, batch_size: int = 1000 ) -> Dict[str, int]:
    """
    Stream a LanceDB source into its Postgres target table.

    Requires:
        - session is an open SQLAlchemy Session (caller owns commit/rollback)
        - model is a Lane B vector-store model class
        - source_rows is an iterable of source-row dicts (streamed once)
        - skip is a set of columns to omit; batch_size is a positive int

    Ensures:
        - returns { "source_count", "existing_before", "purged", "inserted" }
        - apply=False (dry-run): counts source rows only, writes NOTHING, inserted=0
        - apply=True, truncate=True: DELETEs all target rows first (purged = the
          prior count), then loads
        - apply=True, truncate=False, target NON-empty: raises ValueError (fail-loud
          — refuses a silent double-load onto the synthetic-PK tables)
        - apply=True: adds a transformed row per source row, flushing every
          batch_size (caller commits); inserted counts the adds

    Raises:
        - ValueError when applying onto a non-empty target without truncate
    """
    existing_before = session.query( model ).count()
    purged          = 0

    if apply and truncate:
        purged = session.query( model ).delete()
        session.flush()
    elif apply and existing_before > 0:
        raise ValueError(
            f"{model.__tablename__} already has {existing_before} row(s); pass "
            f"truncate=True to reload (refusing a silent double-load)"
        )

    source_count = 0
    inserted     = 0
    pending      = 0
    for row in source_rows:
        source_count += 1
        if not apply:
            continue
        session.add( model( **_row_to_kwargs( row, model, skip ) ) )
        inserted += 1
        pending  += 1
        if pending >= batch_size:
            session.flush()
            pending = 0

    if apply and pending > 0:
        session.flush()

    return {
        "source_count"    : source_count,
        "existing_before" : existing_before,
        "purged"          : purged,
        "inserted"        : inserted,
    }


# =========================================================================== #
# IO boundary — live LanceDB read + real DB session + CLI. Excluded from
# coverage (identical boundary to persona_key_backfill._run): it needs the live
# store, a real get_db(), and argv, none of which a unit test should touch.
# =========================================================================== #
def _iter_lancedb_rows( store_uri, table_name, batch_size=1000 ):   # pragma: no cover - live LanceDB IO boundary
    """Yield row dicts from a LanceDB table, streamed in batches (memory-safe)."""
    import lancedb

    db      = lancedb.connect( store_uri )
    table   = db.open_table( table_name )
    dataset = table.to_lance()
    for batch in dataset.to_batches( batch_size=batch_size ):
        for row in batch.to_pylist():
            yield row


def _run( apply=False, truncate=False, only=None ):   # pragma: no cover - CLI/DB/LanceDB IO boundary
    """Open the store + a DB session, run each spec, print a report. Returns exit code."""
    import cosa.utils.util as cu
    from cosa.rest.db.database import get_db

    store_uri = cu.get_project_root() + _STORE_REL_PATH
    specs     = [ spec for spec in BACKFILL_SPECS if only is None or spec.label == only ]
    if not specs:
        valid = [ spec.label for spec in BACKFILL_SPECS ]
        print( f"vector_store_backfill: no spec matches --only={only!r}; valid labels: {valid}" )
        return 1

    mode = "APPLY" if apply else "DRY-RUN"
    tail = " +truncate" if truncate else ""
    print( f"vector_store_backfill [{mode}]{tail} store={store_uri}" )

    with get_db() as session:
        for spec in specs:
            rows   = _iter_lancedb_rows( store_uri, spec.source_table )
            report = backfill_table( session, spec.model, rows, skip=spec.skip, apply=apply, truncate=truncate )
            print( f"  {spec.label:22} source={report['source_count']:>7} "
                   f"existing={report['existing_before']:>7} purged={report['purged']:>7} "
                   f"inserted={report['inserted']:>7}" )
        if apply:
            session.commit()
            print( "  committed." )
        else:
            print( "  [DRY-RUN] no writes." )
    return 0


if __name__ == "__main__":   # pragma: no cover - CLI entry
    argv = sys.argv[ 1: ]
    only_arg = None
    for token in argv:
        if token.startswith( "--only=" ):
            only_arg = token.split( "=", 1 )[ 1 ]
    sys.exit( _run(
        apply    = ( "--apply" in argv ),
        truncate = ( "--truncate" in argv ),
        only     = only_arg,
    ) )
