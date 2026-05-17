#!/usr/bin/env python3
"""
One-shot migration script: rename-and-merge legacy DM topic files into the
post-fix canonical lowercase + sanitized name.

Per `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/01-design.md`
§2.2 (Q4 ratified migration option α — active rename + merge, 2026-05-17).

**What it does**:
- Scans `io/commons/dm-*.md` (and `io/commons/archive/dm-*.md`) for case-variant
  topic files (e.g. `dm-Tiberius.md` alongside `dm-tiberius.md`).
- Groups variants by canonical name = `_derive_dm_topic`-equivalent (lowercase +
  unicode-aware sanitization on the persona part).
- For each group:
  - **canonical-only**     → no-op (already correctly named)
  - **variant(s) only**    → rename variant → canonical
  - **canonical + variants** → merge entries (parse via `_parse_entry_block`,
    dedupe by `(ts, sender_session_id, body_hash)`, sort by ts, rewrite
    canonical from scratch, unlink variants)
- Backs up every file it's about to mutate to
  `io/commons/.pre-migration-backup/<run-ts>/` BEFORE any destructive op.
- Supports an explicit ALIAS_MAP for short-form aliases that don't auto-derive
  (e.g. `dm-radio` → `dm-mr_radio`, since "radio" → "mr radio" isn't reversible).

**Idempotency**: re-running on a clean tree finds zero variants and is a no-op
(the canonical files just pass through with their natural mtime intact).

**Dry-run mode** (`--dry-run`): scans + reports what WOULD change without
touching disk.

**Venue**: this is a one-shot operational tool, not part of the request path.
Run from a CoSA-context shell (so PYTHONPATH covers `src/lupin_mcp/`).

Per Rick's Q9 binding rule: 100% coverage on this script — exercised by the
companion unit test suite in `src/tests/unit/commons/test_migrate_dm_topic_case.py`.
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Bootstrap LUPIN_ROOT so we can import lupin_mcp.commons_store + cosa_voice_mcp
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT is None:                                                # pragma: no cover
    raise RuntimeError(                                                # pragma: no cover
        "LUPIN_ROOT environment variable not set.\n"                   # pragma: no cover
        "Set it before running:\n"                                     # pragma: no cover
        "  export LUPIN_ROOT=/path/to/lupin\n"                         # pragma: no cover
        "  python src/scripts/migrate-dm-topic-case.py"                # pragma: no cover
    )                                                                  # pragma: no cover
_SRC_PATH = os.path.join( _LUPIN_ROOT, "src" )
if _SRC_PATH not in sys.path:                                          # pragma: no cover
    sys.path.insert( 0, _SRC_PATH )                                    # pragma: no cover

from lupin_mcp.commons_store import (
    ENTRY_SEPARATOR,
    _format_entry,
    _frontmatter_block,
    _parse_entry_block,
    _split_frontmatter,
)
from lupin_mcp.cosa_voice_mcp import _derive_dm_topic


# Short-form aliases that don't auto-derive via `_derive_dm_topic`. Keys are
# legacy topic stems (without `dm-` prefix); values are the post-fix canonical
# stem. Add entries as new aliases surface.
ALIAS_MAP : Dict[ str, str ] = {
    "radio": "mr_radio",   # Tiberius's manual workaround topic from 2026-05-17 Sub-bug C
}


def _now_run_ts() -> str:
    """Timestamp for the backup-dir name (filesystem-safe)."""
    return datetime.now( timezone.utc ).strftime( "%Y%m%dT%H%M%SZ" )


def _derive_canonical_stem( filename: str ) -> str:
    """
    Given a `dm-<persona>.md` filename, return the canonical stem AFTER the
    `dm-` prefix (matching what `_derive_dm_topic` would produce).

    - `dm-Tiberius.md`   → `tiberius`
    - `dm-Mr Radio.md`   → `mr_radio` (if such a file ever existed)
    - `dm-tiberius.md`   → `tiberius` (no-op)
    - `dm-maría.md`      → `maría`
    - `dm-radio.md`      → `mr_radio` via ALIAS_MAP

    Returns the stem only (no `dm-` prefix). Assumes filename starts with
    `dm-` and ends with `.md`; otherwise raises ValueError.
    """
    if not filename.startswith( "dm-" ) or not filename.endswith( ".md" ):
        raise ValueError( f"Not a DM topic filename: {filename!r}" )
    stem = filename[ 3:-3 ]   # strip `dm-` prefix + `.md` suffix
    # Check alias first — alias keys are the LEGACY stem, mapped to canonical
    if stem in ALIAS_MAP:
        return ALIAS_MAP[ stem ]
    # Apply the same sanitization the wrapper helper uses
    derived = _derive_dm_topic( stem )   # yields e.g. "dm-tiberius"
    return derived[ 3: ]                 # strip the `dm-` prefix back off


def _group_topics_by_canonical( dm_files: List[ Path ] ) -> Dict[ str, List[ Path ] ]:
    """
    Group `dm-*.md` files by their canonical stem.

    Returns a dict `canonical_stem → [Path, ...]`. Files that share a canonical
    are case-variants OR alias-targets of each other.
    """
    groups : Dict[ str, List[ Path ] ] = { }
    for path in dm_files:
        try:
            canonical = _derive_canonical_stem( path.name )
        except ValueError:
            continue   # skip files that don't match `dm-*.md`
        groups.setdefault( canonical, [ ] ).append( path )
    return groups


def _parse_topic_file( path: Path ) -> Tuple[ dict, List[ dict ] ]:
    """
    Parse a topic file into (frontmatter_dict, [entry_dict, ...]).

    Entries are returned in their on-disk order (NOT sorted yet).
    """
    content = path.read_text( encoding="utf-8" )
    frontmatter, body = _split_frontmatter( content )
    entries : List[ dict ] = [ ]
    for block in body.split( ENTRY_SEPARATOR ):
        entry = _parse_entry_block( block )
        if entry is not None:
            entries.append( entry )
    return ( frontmatter, entries )


def _entry_dedupe_key( entry: dict ) -> str:
    """
    Build a hash key for entry deduplication.

    Key spans `(ts, sender_session_id, body)` so re-runs OR cross-file
    duplicates collapse to one entry. Hashed for size + comparability.
    """
    body_hash = hashlib.sha1( entry.get( "body", "" ).encode( "utf-8" ) ).hexdigest()[ :12 ]
    return f"{entry.get( 'ts', '' )}|{entry.get( 'sender_session_id', '' )}|{body_hash}"


def _merge_entries( entries_per_file: List[ List[ dict ] ] ) -> List[ dict ]:
    """
    Merge entries from N files: dedupe by key, sort by ts ascending.
    """
    seen : Dict[ str, dict ] = { }
    for entries in entries_per_file:
        for entry in entries:
            key = _entry_dedupe_key( entry )
            if key not in seen:
                seen[ key ] = entry
    merged = list( seen.values() )
    merged.sort( key=lambda e: e.get( "ts", "" ) )
    return merged


def _rebuild_topic_file_text( topic: str, entries: List[ dict ] ) -> str:
    """
    Build the full topic-file text content from frontmatter + entries.

    Uses the same `_format_entry` and `ENTRY_SEPARATOR` the live store uses,
    so post-migration files round-trip through `CommonsStore.read` identically
    to natively-written files.
    """
    if entries:
        first_ts = entries[ 0 ].get( "ts" ) or datetime.now( timezone.utc ).isoformat( timespec="microseconds" )
    else:
        first_ts = datetime.now( timezone.utc ).isoformat( timespec="microseconds" )
    parts = [ _frontmatter_block( topic, False, first_ts ) ]
    for entry in entries:
        parts.append( ENTRY_SEPARATOR )
        parts.append( _format_entry(
            ts            = entry[ "ts" ],
            session_id    = entry[ "sender_session_id" ],
            persona_name  = entry[ "persona_name" ],
            persona_icon  = entry[ "persona_icon" ],
            persona_color = entry[ "persona_color" ],
            body          = entry[ "body" ],
            metadata      = entry[ "metadata" ],
        ) )
    return "".join( parts )


def _backup_files( files: List[ Path ], backup_dir: Path ) -> None:
    """Copy each file into `backup_dir`, preserving the original filename."""
    backup_dir.mkdir( parents=True, exist_ok=True )
    for src in files:
        shutil.copy2( src, backup_dir / src.name )


def migrate_directory(
    commons_dir : Path,
    dry_run     : bool = False,
    backup_root : Optional[ Path ] = None,
) -> Dict[ str, int ]:
    """
    Run the migration over a single commons directory (e.g. `io/commons/` or
    `io/commons/archive/`).

    Returns a stats dict for the caller to report:
        {
            "scanned"       : <int>,
            "no_op"         : <int>,
            "renamed"       : <int>,
            "merged"        : <int>,
            "files_unlinked": <int>,
        }
    """
    if not commons_dir.exists():
        return { "scanned": 0, "no_op": 0, "renamed": 0, "merged": 0, "files_unlinked": 0 }

    dm_files = sorted( commons_dir.glob( "dm-*.md" ) )
    groups   = _group_topics_by_canonical( dm_files )

    stats = { "scanned": len( dm_files ), "no_op": 0, "renamed": 0, "merged": 0, "files_unlinked": 0 }

    for canonical_stem, variants in groups.items():
        canonical_filename = f"dm-{canonical_stem}.md"
        canonical_path     = commons_dir / canonical_filename

        # Sort variants: canonical (if present) first, then rest alphabetically
        variants_sorted = sorted( variants, key=lambda p: ( p.name != canonical_filename, p.name ) )

        canonical_present = canonical_path in variants_sorted
        non_canonical     = [ p for p in variants_sorted if p.name != canonical_filename ]

        if not non_canonical:
            # Only the canonical file exists — no-op
            stats[ "no_op" ] += 1
            continue

        if not canonical_present and len( non_canonical ) == 1:
            # Single variant, no canonical → rename
            src = non_canonical[ 0 ]
            print( f"  RENAME   {src.name} → {canonical_filename}" )
            if not dry_run:
                if backup_root is not None:
                    _backup_files( [ src ], backup_root )
                src.rename( canonical_path )
            stats[ "renamed" ] += 1
            continue

        # Either: canonical + variant(s), OR multiple variants without canonical.
        # Merge all entries into the canonical file.
        all_files = ( [ canonical_path ] if canonical_present else [ ] ) + non_canonical
        print( f"  MERGE    {canonical_filename} ← {[ p.name for p in all_files ]}" )

        entries_per_file = [ _parse_topic_file( p )[ 1 ] for p in all_files ]
        merged = _merge_entries( entries_per_file )
        new_text = _rebuild_topic_file_text( f"dm-{canonical_stem}", merged )

        if not dry_run:
            if backup_root is not None:
                _backup_files( all_files, backup_root )
            canonical_path.write_text( new_text, encoding="utf-8" )
            for p in non_canonical:
                p.unlink()
                stats[ "files_unlinked" ] += 1
        stats[ "merged" ] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot rename-and-merge migration for legacy DM topic files."
    )
    parser.add_argument(
        "--commons-root",
        type=Path,
        default=Path( _LUPIN_ROOT ) / "io" / "commons",
        help="Path to `io/commons/` (default: $LUPIN_ROOT/io/commons)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without touching disk.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the pre-migration backup (only valid with --dry-run or for testing).",
    )
    args = parser.parse_args()

    commons_dir = args.commons_root
    archive_dir = commons_dir / "archive"

    backup_root : Optional[ Path ] = None
    if not args.no_backup and not args.dry_run:
        backup_root = commons_dir / ".pre-migration-backup" / _now_run_ts()
        print( f"Backup dir: {backup_root}" )

    print( f"=== Migrating {commons_dir} ===" )
    main_stats = migrate_directory(
        commons_dir = commons_dir,
        dry_run     = args.dry_run,
        backup_root = backup_root,
    )

    print( f"=== Migrating {archive_dir} ===" )
    archive_stats = migrate_directory(
        commons_dir = archive_dir,
        dry_run     = args.dry_run,
        backup_root = backup_root,
    )

    print( "" )
    print( "Summary:" )
    print( f"  Main dir:    scanned={main_stats[ 'scanned' ]}, no-op={main_stats[ 'no_op' ]}, renamed={main_stats[ 'renamed' ]}, merged={main_stats[ 'merged' ]}, unlinked={main_stats[ 'files_unlinked' ]}" )
    print( f"  Archive dir: scanned={archive_stats[ 'scanned' ]}, no-op={archive_stats[ 'no_op' ]}, renamed={archive_stats[ 'renamed' ]}, merged={archive_stats[ 'merged' ]}, unlinked={archive_stats[ 'files_unlinked' ]}" )

    if args.dry_run:
        print( "" )
        print( "(dry-run: no changes written)" )

    return 0


if __name__ == "__main__":                                            # pragma: no cover
    sys.exit( main() )                                                # pragma: no cover
