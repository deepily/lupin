#!/usr/bin/env python3
"""
================================================================================
INCIDENT-RECOVERY FORK — created 2026-06-23 (Mr. Radio). NOT the canonical tool.
--------------------------------------------------------------------------------
This is a COPY of src/scripts/rebuild_lancedb_table.py with four extra phases
added live during the 2026-06-23 LanceDB outage, retained for future incidents:
    promote-rebuilt      finish a half-failed swap by dir-renaming __rebuilt in
    drop-husk            delete a leftover __broken_husk
    restore-from-backup  per-table restore of one table from the DATA02 mirror
    verbatim-restore-db  quarantine artifact dirs + rsync -a --delete mirror->live

CAVEAT: these were authored under pressure and run via the HOST venv
(lancedb 0.23.0 / lance-0.29 / V1 manifests). The server container runs
lance-4.0.0 / V2 — the V1/V2 manifest split is what broke both servers. The
filesystem phases (restore-from-backup, verbatim-restore-db) are version-agnostic
and safe; the lance-API phases (build/swap/promote) MUST be run with the
container's lance, not this host venv. ALWAYS dry-run destructive steps first.
The canonical rebuild_lancedb_table.py was reverted to its pre-incident state.
================================================================================

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


def phase_swap( db, table ):
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


def phase_promote_rebuilt( db, table, db_path ):
    # RECOVERY for a half-failed `swap`: lance drop_table() partially removed the
    # corrupt live table (freeing the bulk stale-version disk in place) then raised
    # ENOTEMPTY on the final rmdir — leaving a NON-OPENABLE husk in the live slot.
    # The verified `<table>__rebuilt` (built + count-verified) holds the full
    # snapshot. Promote it into the live slot via a filesystem directory rename
    # (lance tables are directory-addressed), keeping the husk aside for rollback.
    rebuilt     = table + REBUILT_SUFFIX
    live_dir    = os.path.join( db_path, f"{table}.lance" )
    rebuilt_dir = os.path.join( db_path, f"{rebuilt}.lance" )
    husk_dir    = os.path.join( db_path, f"{table}__broken_husk.lance" )

    if not os.path.isdir( rebuilt_dir ):
        print( f"  FAIL: {rebuilt}.lance not present — nothing to promote", file=sys.stderr ); return 9
    if os.path.exists( husk_dir ):
        print( f"  FAIL: {husk_dir} already exists — refusing to clobber a prior husk", file=sys.stderr ); return 10

    if os.path.isdir( live_dir ):
        print( f"  moving broken husk {table} -> {table}__broken_husk (reversible)..." )
        os.rename( live_dir, husk_dir )
    print( f"  promoting {rebuilt} -> {table} (directory rename)..." )
    os.rename( rebuilt_dir, live_dir )

    new = db.open_table( table )
    nn  = new.count_rows()
    new.list_versions()   # raises if the promoted chain is not clean
    print( f"  VERIFY: {table} = {nn} rows, clean chain @ version {new.version}" )
    print( f"  PROMOTE COMPLETE. Husk retained at {table}__broken_husk.lance for rollback." )
    print( f"  >>> Bounce dev+test servers now, then --phase drop-husk to free the husk disk. <<<" )
    return 0


def phase_drop_husk( db, table, db_path ):
    import shutil
    husk_dir = os.path.join( db_path, f"{table}__broken_husk.lance" )
    if not os.path.isdir( husk_dir ):
        print( f"  {table}__broken_husk.lance absent — nothing to drop." ); return 0
    pre = dir_size( db_path )
    print( f"  DB size before husk drop: {human_bytes( pre )}" )
    shutil.rmtree( husk_dir )
    post = dir_size( db_path )
    print( f"  dropped husk. DB size after: {human_bytes( post )}  (reclaimed {human_bytes( pre - post )})" )
    return 0


def phase_restore_from_backup( db, table, db_path, backup_path ):
    # EMERGENCY RECOVERY: restore the live table from the dedicated-drive backup
    # after a failed rebuild left it unreadable by the server's lance. Moves the
    # broken live dir aside (reversible, kept for forensics) then copytree's the
    # pristine backup table into the live slot. The backup is the format the
    # server was already running on, so it reopens cleanly.
    import shutil
    src   = os.path.join( backup_path, f"{table}.lance" )
    live  = os.path.join( db_path,     f"{table}.lance" )
    aside = os.path.join( db_path,     f"{table}__failed_promote.lance" )

    if not os.path.isdir( src ):
        print( f"  FAIL: backup table not found: {src}", file=sys.stderr ); return 11
    if os.path.isdir( live ):
        if os.path.exists( aside ):
            print( f"  FAIL: {aside} already exists — refusing to clobber", file=sys.stderr ); return 12
        print( f"  moving broken {table} -> {table}__failed_promote (reversible)..." )
        os.rename( live, aside )
    print( f"  restoring {table} from backup {src} (copytree — may take minutes)..." )
    t0 = time.time()
    shutil.copytree( src, live )
    print( f"  copied in {time.time() - t0:.0f}s" )

    n = db.open_table( table ).count_rows()
    print( f"  VERIFY: restored {table} = {n} rows (opens cleanly via host lance)" )
    print( f"  >>> Now bounce dev+test servers; they reopen the restored table. <<<" )
    return 0


def phase_verbatim_restore_db( db_path, backup_path ):
    # WHOLE-DB verbatim restore: make the live lancedb directory byte-identical to
    # the dedicated-drive backup. Fixes a poisoned table_names() scan caused by
    # broken artifact dirs (*__failed_promote.lance / *__broken_husk.lance) left in
    # the lancedb dir — lance enumerates them as tables and drops real tables from
    # the listing, so the server's "create if not listed" path crashes ("already
    # exists"). Step 1 quarantines those artifacts OUT of the dir (preserving the
    # few rows written after the backup); step 2 rsync -a --delete syncs the backup
    # over the live dir so it exactly matches (and any stray non-backup entry is removed).
    import glob, subprocess
    db_path     = db_path.rstrip( "/" )
    backup_path = backup_path.rstrip( "/" )
    qdir = db_path + "-quarantine"
    os.makedirs( qdir, exist_ok=True )

    moved = []
    for pat in ( "*__failed_promote.lance", "*__broken_husk.lance" ):
        for d in glob.glob( os.path.join( db_path, pat ) ):
            dest = os.path.join( qdir, os.path.basename( d ) )
            if os.path.exists( dest ):
                print( f"  quarantine dest exists, leaving in place: {os.path.basename( d )}" ); continue
            os.rename( d, dest )
            moved.append( os.path.basename( d ) )
            print( f"  quarantined {os.path.basename( d )} -> {qdir}" )
    print( f"  quarantined {len( moved )} artifact dir(s)" )

    if not os.path.isdir( backup_path ):
        print( f"  FAIL: backup dir not found: {backup_path}", file=sys.stderr ); return 13
    print( f"  rsync -a --delete {backup_path}/  ->  {db_path}/ ..." )
    t0 = time.time()
    r = subprocess.run( [ "rsync", "-a", "--delete", backup_path + "/", db_path + "/" ],
                        capture_output=True, text=True )
    if r.returncode != 0:
        print( f"  rsync FAILED ({r.returncode}): {r.stderr[:400]}", file=sys.stderr ); return 14
    print( f"  verbatim sync complete in {time.time() - t0:.0f}s. Live lancedb now matches the mirror." )
    print( f"  >>> Bounce dev+test servers now. <<<" )
    return 0


def main():
    p = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    p.add_argument( "--phase", required=True, choices=[ "status", "build", "swap", "backfill", "reclaim", "promote-rebuilt", "drop-husk", "restore-from-backup", "verbatim-restore-db" ] )
    p.add_argument( "--table", default="input_and_output_tbl" )
    p.add_argument( "--db-path", default=DEFAULT_DB_PATH )
    p.add_argument( "--backup-path", default="/mnt/DATA02/include/www.deepily.ai/projects/lupin/src/conf/long-term-memory/lupin.lancedb",
                    help="lancedb dir on the dedicated backup drive (source for restore-from-backup)" )
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
    elif args.phase == "swap":     return phase_swap(    db, args.table )
    elif args.phase == "backfill": return phase_backfill( db, args.table )
    elif args.phase == "reclaim":  return phase_reclaim( db, args.table, args.db_path )
    elif args.phase == "promote-rebuilt": return phase_promote_rebuilt( db, args.table, args.db_path )
    elif args.phase == "drop-husk":       return phase_drop_husk(       db, args.table, args.db_path )
    elif args.phase == "restore-from-backup": return phase_restore_from_backup( db, args.table, args.db_path, args.backup_path )
    elif args.phase == "verbatim-restore-db": return phase_verbatim_restore_db( args.db_path, args.backup_path )


if __name__ == "__main__":
    sys.exit( main() )
