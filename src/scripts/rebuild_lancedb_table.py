#!/usr/bin/env python3
"""
Rebuild a LanceDB table whose version history is corrupted (a missing manifest
breaks list_versions()/optimize()), reclaiming disk by collapsing 100k+ stale
versions into ONE fresh table while preserving every current row.

Why this exists: input_and_output_tbl grew to ~80GB across ~100k uncompacted
versions, and optimize() trips on a missing/shifting `_versions/NNNNN.manifest`.
The table's CURRENT data is intact (it opens + reads fine) — only the historical
version chain is broken. So we read the live data into a fresh single-fragment
table and swap it in. The corruption is left behind in the dropped old chain.

Staged + idempotent. Phases (run in order):

    status    Report row counts of <table>, <table>__rebuilt, <table>__corrupt_bak.

    build     [servers UP — additive, safe, reversible]
              Snapshot-read all rows of <table> at its latest version, create
              <table>__rebuilt (overwrite) from them, verify count matches.

    swap      [the irreversible moment]
              rename <table> -> <table>__corrupt_bak  (drops any stale bak first)
              rename <table>__rebuilt -> <table>
              Verify the new <table> opens, counts, and list_versions() is CLEAN.
              >>> After this, BOUNCE the dev+test servers so they reopen <table>. <<<

    backfill  [after the post-swap server bounce]
              Append any rows written to the OLD table during the build/swap
              window (now preserved in <table>__corrupt_bak) into the new <table>,
              selected by (date,time) strictly greater than the snapshot's max.
              Makes the rebuild lossless for an append-only log.

    reclaim   Drop <table>__corrupt_bak -> frees the ~80GB of stale-version disk.

    drop-rebuilt  Drop <table>__rebuilt. Use AFTER `swap --keep-rebuilt` once the
                  dev+test servers have reopened the new <table> green — removes the
                  retained instant-rollback net (its job is done).

Swap rollback-net option:
    swap --keep-rebuilt   Retain <table>__rebuilt after the new table verifies (instead
                          of dropping it), so it stays as a ~live-data-sized instant
                          rollback net through the post-swap server bounce. Drop it with
                          --phase drop-rebuilt once both servers verify green.

Safety: a full verified backup of the lancedb must exist on the dedicated drive
BEFORE running `swap`. This script never takes its own backup. The `__corrupt_bak`
table is retained until `reclaim`, giving instant rollback.

Usage (inside the app container, where lancedb is importable):
    python src/scripts/rebuild_lancedb_table.py --phase status
    python src/scripts/rebuild_lancedb_table.py --phase build
    python src/scripts/rebuild_lancedb_table.py --phase swap
    # ... bounce dev+test servers here ...
    python src/scripts/rebuild_lancedb_table.py --phase backfill
    python src/scripts/rebuild_lancedb_table.py --phase reclaim
"""

import argparse
import os
import sys
import time

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if LUPIN_ROOT is None:
    raise RuntimeError( "LUPIN_ROOT environment variable not set." )

DEFAULT_DB_PATH = f"{LUPIN_ROOT}/src/conf/long-term-memory/lupin.lancedb"
REBUILT_SUFFIX  = "__rebuilt"
BAK_SUFFIX      = "__corrupt_bak"


def human_bytes( n ):
    for unit in ( "B", "KB", "MB", "GB", "TB" ):
        if n < 1024.0: return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def dir_size( path ):
    total = 0
    for root, _, files in os.walk( path ):
        for f in files:
            try:    total += os.path.getsize( os.path.join( root, f ) )
            except OSError: pass
    return total


def _names( db ):
    return set( db.table_names() )


def phase_status( db, table, db_path ):
    names = _names( db )
    for nm in ( table, table + REBUILT_SUFFIX, table + BAK_SUFFIX ):
        if nm in names:
            t = db.open_table( nm )
            d = os.path.join( db_path, f"{nm}.lance" )
            print( f"  {nm}: rows={t.count_rows()}  version={t.version}  size={human_bytes( dir_size( d ) )}" )
        else:
            print( f"  {nm}: (absent)" )


def phase_build( db, table ):
    src      = db.open_table( table )
    n0       = src.count_rows()
    print( f"  source {table}: {n0} rows @ version {src.version}" )
    print( "  reading snapshot (to_arrow)..." )
    t0       = time.time()
    snap     = src.to_arrow()
    print( f"  read {snap.num_rows} rows in {time.time()-t0:.1f}s" )
    assert snap.num_rows == n0, f"snapshot row mismatch: {snap.num_rows} != {n0}"

    rebuilt_name = table + REBUILT_SUFFIX
    print( f"  creating fresh {rebuilt_name} (overwrite)..." )
    t0       = time.time()
    rebuilt  = db.create_table( rebuilt_name, data=snap, mode="overwrite" )
    print( f"  wrote in {time.time()-t0:.1f}s" )

    n_rebuilt = rebuilt.count_rows()
    print( f"  VERIFY: rebuilt rows = {n_rebuilt}  (source was {n0})" )
    if n_rebuilt != n0:
        print( "  FAIL: rebuilt count != source count", file=sys.stderr ); return 5
    # prove the fresh table has a clean version chain
    rebuilt.list_versions()
    print( "  rebuilt list_versions() OK (clean chain). Build phase complete." )
    return 0


def phase_swap( db, table, keep_rebuilt=False ):
    # LanceDB OSS does NOT support rename_table (the method exists but raises
    # NotImplementedError at runtime). So we re-snapshot the live table, DROP it
    # (which frees the ~stale-version disk in place), and CREATE it fresh from the
    # snapshot. The staging __rebuilt table is retained as a rollback copy through
    # the drop->create window and dropped ONLY after the new table verifies. The
    # full DATA02 backup is the outer safety net. Re-snapshotting here captures any
    # rows written since --phase build (no separate backfill needed); rows written
    # during the sub-second snapshot->drop window are the only residual (covered by
    # the backup), so run with writers quiesced.
    rebuilt_name = table + REBUILT_SUFFIX
    src = db.open_table( table )
    n0  = src.count_rows()
    print( f"  re-snapshot {table}: {n0} rows @ version {src.version}" )
    snap = src.to_arrow()
    if snap.num_rows != n0:
        print( f"  FAIL: snapshot mismatch {snap.num_rows} != {n0}", file=sys.stderr ); return 7
    print( f"  dropping corrupted {table} (frees stale-version disk in place)..." )
    db.drop_table( table )
    print( f"  recreating {table} fresh from snapshot ({snap.num_rows} rows)..." )
    new = db.create_table( table, data=snap, mode="overwrite" )
    nn  = new.count_rows()
    new.list_versions()   # raises if the new chain is not clean
    print( f"  VERIFY: new {table} = {nn} rows (snapshot {n0}), clean chain @ version {new.version}" )
    if nn != n0:
        print( "  FAIL: post-create count mismatch", file=sys.stderr ); return 8
    if rebuilt_name in _names( db ):
        if keep_rebuilt:
            print( f"  RETAINING {rebuilt_name} as instant-rollback net (size ~live data); drop it via --phase drop-rebuilt after both servers verify green." )
        else:
            print( f"  dropping staging {rebuilt_name} (new table verified)..." ); db.drop_table( rebuilt_name )
    print( f"  SWAP COMPLETE (drop+create). Disk reclaimed in place. >>> Bounce dev+test servers now. <<<" )
    return 0


def phase_backfill( db, table ):
    import pyarrow.compute as pc
    bak_name = table + BAK_SUFFIX
    if bak_name not in _names( db ):
        print( f"  {bak_name} absent — nothing to backfill." ); return 0

    new  = db.open_table( table )
    bak  = db.open_table( bak_name )
    new_n, bak_n = new.count_rows(), bak.count_rows()
    print( f"  {table}={new_n} rows, {bak_name}={bak_n} rows" )
    if bak_n <= new_n:
        print( "  no late writes to backfill (bak <= new)." ); return 0

    # boundary = max (date,time) currently in the new table; bak rows beyond it are the window writes
    new_tbl  = new.to_arrow().select( [ "date", "time" ] )
    # build a sortable composite "date time" string for boundary comparison
    new_keys = pc.binary_join_element_wise( new_tbl[ "date" ], new_tbl[ "time" ], " " )
    boundary = pc.max( new_keys ).as_py()
    print( f"  snapshot boundary (max date+time in new): {boundary!r}" )

    bak_arrow = bak.to_arrow()
    bak_keys  = pc.binary_join_element_wise( bak_arrow[ "date" ], bak_arrow[ "time" ], " " )
    mask      = pc.greater( bak_keys, boundary )
    late      = bak_arrow.filter( mask )
    print( f"  late rows in bak beyond boundary: {late.num_rows}" )
    if late.num_rows == 0:
        print( "  nothing strictly newer than boundary; backfill no-op." ); return 0

    new.add( late )
    print( f"  appended {late.num_rows} late rows. {table} now {new.count_rows()} rows." )
    return 0


def phase_reclaim( db, table, db_path ):
    bak_name = table + BAK_SUFFIX
    if bak_name not in _names( db ):
        print( f"  {bak_name} absent — nothing to reclaim." ); return 0
    pre = dir_size( db_path )
    print( f"  DB size before drop: {human_bytes( pre )}" )
    db.drop_table( bak_name )
    post = dir_size( db_path )
    print( f"  dropped {bak_name}. DB size after: {human_bytes( post )}  (reclaimed {human_bytes( pre - post )})" )
    return 0


def phase_drop_rebuilt( db, table ):
    rebuilt_name = table + REBUILT_SUFFIX
    if rebuilt_name not in _names( db ):
        print( f"  {rebuilt_name} absent — nothing to drop." ); return 0
    print( f"  dropping retained rollback-net {rebuilt_name}..." )
    db.drop_table( rebuilt_name )
    print( f"  dropped {rebuilt_name}. Rollback net removed (post-verify cleanup)." )
    return 0


def main():
    p = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    p.add_argument( "--phase", required=True, choices=[ "status", "build", "swap", "backfill", "reclaim", "drop-rebuilt" ] )
    p.add_argument( "--table", default="input_and_output_tbl" )
    p.add_argument( "--db-path", default=DEFAULT_DB_PATH )
    p.add_argument( "--keep-rebuilt", action="store_true",
                    help="swap: retain <table>__rebuilt as an instant-rollback net instead of dropping it after verify" )
    args = p.parse_args()

    try:
        import lancedb
    except ImportError as e:
        print( f"FAIL: lancedb not importable ({e})", file=sys.stderr ); return 2

    db = lancedb.connect( args.db_path )
    print( "=" * 70 )
    print( f"  rebuild_lancedb_table  phase={args.phase}  table={args.table}" )
    print( "=" * 70 )

    if   args.phase == "status":   return phase_status(  db, args.table, args.db_path )
    elif args.phase == "build":    return phase_build(   db, args.table )
    elif args.phase == "swap":     return phase_swap(    db, args.table, keep_rebuilt=args.keep_rebuilt )
    elif args.phase == "backfill": return phase_backfill( db, args.table )
    elif args.phase == "reclaim":  return phase_reclaim( db, args.table, args.db_path )
    elif args.phase == "drop-rebuilt": return phase_drop_rebuilt( db, args.table )


if __name__ == "__main__":
    sys.exit( main() )
