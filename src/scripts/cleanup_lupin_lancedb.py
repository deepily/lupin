#!/usr/bin/env python3
"""
Reclaim disk by purging old Lance versions from the project's lancedb.

Each Lance write creates a new transaction with its own data fragments under
`_versions/`. Without periodic cleanup, version history accumulates. On
2026-04-27, lupin.lancedb's `input_and_output_tbl` had grown to 43 GB with
only 620 MB of currently-active data — 42 GB of stale fragments.

This script calls `Table.optimize(cleanup_older_than=...)` (the modern
lancedb API replacing the deprecated `cleanup_old_versions()`) on every
table in the database (or a single named table via --table).
`optimize()` is a single omnibus call that performs BOTH:
  - compaction (merging small data fragments into larger ones for read perf)
  - version cleanup (purging fragments referenced only by manifests older than the cutoff)

Usage:
    # Dry run — list version counts, no deletion
    python src/scripts/cleanup_lupin_lancedb.py --dry-run

    # Live run with default 1-day cutoff
    python src/scripts/cleanup_lupin_lancedb.py --require-stopped

    # More conservative: cleanup anything older than 7 days
    python src/scripts/cleanup_lupin_lancedb.py --older-than-days 7

Safety:
    - Cleanup is irreversible. This script does NOT take its own backup —
      Lupin's nightly ecosystem-level backup is the safety net. See
      ~/.claude memory: feedback_backups_only_to_dedicated_drive.md.
    - Run with NO active writers — pass --require-stopped to fail-fast if
      lupin-rest-dev or lupin-rest-test is running.
    - This project has zero time-travel queries (verified 2026-04-27);
      no consumer breaks when old versions are removed.

Plan:
    src/rnd/v0.1.7/2026.04.27-drop-recursive-chown-image-bloat-audit.md
    (Out-of-scope deferred items list referenced this work)
"""

import argparse
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

# ----------------------------------------------------------------------------
# LUPIN_ROOT bootstrap (canonical Lupin script pattern from CLAUDE.md)
# ----------------------------------------------------------------------------
LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if LUPIN_ROOT is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before running:\n"
        "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
        "  python src/scripts/cleanup_lupin_lancedb.py [...]"
    )

DEFAULT_DB_PATH      = f"{LUPIN_ROOT}/src/conf/long-term-memory/lupin.lancedb"
DEFAULT_OLDER_DAYS   = 1
PROTECTED_CONTAINERS = ( "lupin-rest-dev", "lupin-rest-test" )


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[ 1 ] if __doc__ else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--db-path", default=DEFAULT_DB_PATH,
        help=f"Path to lupin.lancedb directory (default: {DEFAULT_DB_PATH})"
    )
    p.add_argument(
        "--older-than-days", type=int, default=DEFAULT_OLDER_DAYS,
        help=f"Cleanup versions older than N days (default: {DEFAULT_OLDER_DAYS})"
    )
    p.add_argument(
        "--table", default=None,
        help="Cleanup only this table (default: all tables in the DB)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Inspect versions but do not delete anything"
    )
    p.add_argument(
        "--require-stopped", action="store_true",
        help=f"Fail if any of {list(PROTECTED_CONTAINERS)} containers are running"
    )
    return p.parse_args()


def human_bytes( n ):
    for unit in ( "B", "KB", "MB", "GB", "TB" ):
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def dir_size( path ):
    total = 0
    for root, _, files in os.walk( path ):
        for f in files:
            fp = os.path.join( root, f )
            try:
                total += os.path.getsize( fp )
            except OSError:
                pass
    return total


def check_writers_stopped():
    """Return list of any PROTECTED_CONTAINERS that are currently running."""
    try:
        result = subprocess.run(
            [ "docker", "ps", "--format", "{{.Names}}" ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        running = result.stdout.strip().splitlines()
        return [ n for n in running if n in PROTECTED_CONTAINERS ]
    except ( subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired ):
        return []   # docker not reachable — caller decides


def _to_aware_utc( dt ):
    """Normalize a datetime to aware UTC. Lance returns naive UTC datetimes."""
    return dt.replace( tzinfo=datetime.timezone.utc ) if dt.tzinfo is None else dt.astimezone( datetime.timezone.utc )


def cleanup_table( tbl, older_than, dry_run, table_dir ):
    pre_size   = dir_size( table_dir )
    versions   = tbl.list_versions()
    n_versions = len( versions )

    cutoff = datetime.datetime.now( datetime.timezone.utc ) - older_than
    older_count = sum(
        1 for v in versions
        if _to_aware_utc( v[ "timestamp" ] ) < cutoff
    )

    print( f"  versions:        {n_versions} total, {older_count} older than cutoff" )
    print( f"  table size now:  {human_bytes(pre_size)}" )

    if dry_run:
        print( f"  [dry-run] would call optimize(cleanup_older_than={older_than})" )
        return None

    t0 = time.time()
    tbl.optimize( cleanup_older_than=older_than )
    elapsed = time.time() - t0

    post_size = dir_size( table_dir )
    delta     = pre_size - post_size
    print( f"  optimize() ran in {elapsed:.1f}s  (does compaction + version cleanup)" )
    print( f"  table size after: {human_bytes(post_size)}" )
    print( f"  reclaimed:        {human_bytes(delta)}" )
    return delta


def main():
    args = parse_args()

    try:
        import lancedb
    except ImportError as e:
        print( f"FAIL: lancedb not importable. Activate the venv first.\n  {e}", file=sys.stderr )
        return 2

    if args.require_stopped:
        offending = check_writers_stopped()
        if offending:
            print(
                f"FAIL: writers still running: {', '.join(offending)}\n"
                f"Run: docker compose stop {' '.join(offending)}",
                file=sys.stderr,
            )
            return 3

    db_path = Path( args.db_path )
    if not db_path.exists():
        print( f"FAIL: db path not found: {db_path}", file=sys.stderr )
        return 4

    older_than = datetime.timedelta( days=args.older_than_days )

    print( "=" * 70 )
    print( "  lupin.lancedb cleanup  (compaction + version cleanup via optimize())" )
    print( "=" * 70 )
    print( f"  DB path:        {db_path}" )
    print( f"  Cutoff:         older than {args.older_than_days} day(s)" )
    print( f"  Mode:           {'DRY RUN' if args.dry_run else 'LIVE'}" )
    print( f"  Backup:         relying on Lupin nightly ecosystem-level backup (no per-script backup)" )
    print()

    pre_db_size = dir_size( db_path )
    print( f"  DB size before: {human_bytes(pre_db_size)}" )
    print()

    db     = lancedb.connect( str( db_path ) )
    # NOTE: lancedb 0.30.2 deprecates table_names() in favor of list_tables(),
    # but list_tables() returns a paginated object whose iteration yields
    # (key, value) tuples — not the list of table-name strings we want.
    # table_names() still returns a plain list[str], which is what we need.
    # The deprecation warning is harmless.
    tables = [ args.table ] if args.table else sorted( db.table_names() )
    if not tables:
        print( "No tables to process." )
        return 0

    total_reclaimed = 0
    for name in tables:
        print( f"--- {name} ---" )
        try:
            tbl       = db.open_table( name )
            table_dir = db_path / f"{name}.lance"
            delta     = cleanup_table( tbl, older_than, args.dry_run, table_dir )
            if delta is not None:
                total_reclaimed += delta
        except Exception as e:
            print( f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr )
        print()

    post_db_size = dir_size( db_path )
    print( "=" * 70 )
    print( f"  DB size before: {human_bytes(pre_db_size)}" )
    print( f"  DB size after:  {human_bytes(post_db_size)}" )
    print( f"  Reclaimed:      {human_bytes(pre_db_size - post_db_size)}" )
    if args.dry_run:
        print( "  (dry-run — no actual changes)" )
    print( "=" * 70 )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
