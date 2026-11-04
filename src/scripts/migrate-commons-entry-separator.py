#!/usr/bin/env python3
"""
One-shot migration of legacy commons entry separators to the canonical one.

Converts `\\n---\\n` between entries in commons topic files to the canonical
`\\n<<<__lupin_commons_entry_boundary__>>>\\n` separator, which does not collide
with markdown thematic-break syntax.

Why: the legacy separator collided with `---` lines inside entry bodies (section
breaks, frontmatter, structured reviews). `CommonsStore.read()` split at the first
`\\n---\\n` in a body and dropped everything after it.

What it does:
- Scans `io/commons/*.md` and `io/commons/archive/**/*.md`.
- Leaves frontmatter untouched, since YAML uses `---` legitimately at file start.
- Replaces a body `\\n---\\n` only when a valid entry header follows it immediately
  (`## <ISO-ts> | <persona-name> <persona-icon> #<session-id>`).
- Leaves a `\\n---\\n` followed by anything else alone, as a body thematic break.
- Copies each file it will change into
  `io/commons/.pre-separator-migration-backup/<run-ts>/` before any write.

Re-running on a migrated tree is a no-op, and unchanged files keep their mtime.
With `--dry-run` it reports what would change and writes nothing.

Run it once with `LUPIN_ROOT` set, so that `src/lupin_mcp/` is importable.
The companion unit tests are in
`src/tests/unit/commons/test_migrate_commons_entry_separator.py`.
"""

import argparse
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple


# Bootstrap LUPIN_ROOT so we can import lupin_mcp.commons_store
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT is None:                                                # pragma: no cover
    raise RuntimeError(                                                # pragma: no cover
        "LUPIN_ROOT environment variable not set.\n"                   # pragma: no cover
        "Set it before running:\n"                                     # pragma: no cover
        "  export LUPIN_ROOT=/path/to/lupin\n"                         # pragma: no cover
        "  python src/scripts/migrate-commons-entry-separator.py"     # pragma: no cover
    )                                                                  # pragma: no cover
_SRC_PATH = os.path.join( _LUPIN_ROOT, "src" )
if _SRC_PATH not in sys.path:                                          # pragma: no cover
    sys.path.insert( 0, _SRC_PATH )                                    # pragma: no cover

from lupin_mcp.commons_store import (
    ENTRY_SEPARATOR,
    LEGACY_ENTRY_SEPARATOR,
    _split_frontmatter,
)


# Regex matching the legacy `\n---\n` separator ONLY when followed by a valid
# entry header. Lookahead does not consume — the replacement is exactly the
# legacy separator's 5 characters. Mirrors `_HEADER_RE` from commons_store.py.
_ENTRY_BOUNDARY_RE = re.compile(
    r"\n---\n(?=## \S+ \| .+? \S+ #[A-Za-z0-9_-]+)"
)


def _now_run_ts() -> str:
    """ISO-style timestamp safe for use in directory names."""
    return datetime.now( timezone.utc ).strftime( "%Y%m%dT%H%M%SZ" )


def _migrate_body( body: str ) -> Tuple[ str, int ]:
    """
    Replace legacy entry-boundary separators in a body with the canonical one.

    A `\\n---\\n` not followed by an entry header is a body thematic break and
    is left untouched.

    Requires:
        - body is the post-frontmatter body string

    Ensures:
        - returns (migrated_body, n_replaced)
        - n_replaced == 0 if no legacy entry boundaries are present
        - migrated_body == body if n_replaced == 0
    """
    n_replaced = 0

    def _sub( _match: re.Match ) -> str:
        nonlocal n_replaced
        n_replaced += 1
        return ENTRY_SEPARATOR

    new_body = _ENTRY_BOUNDARY_RE.sub( _sub, body )
    return ( new_body, n_replaced )


def _reconstruct_content( original: str, body: str, new_body: str ) -> str:
    """
    Rebuild file content with frontmatter kept verbatim and the body replaced.

    The body offset is `len(original) - len(body)`. That holds for every
    `_split_frontmatter` return shape (valid frontmatter, opener without a
    close, no frontmatter), so no shape needs its own branch.
    """
    frontmatter_section = original[ : len( original ) - len( body ) ]
    return frontmatter_section + new_body


def _migrate_file( path: Path, dry_run: bool, backup_root: Path ) -> Tuple[ int, bool ]:
    """
    Migrate a single topic file in-place.

    Requires:
        - path exists and is a `.md` file under `io/commons/` or its archive
        - backup_root is a writable directory (irrelevant in dry-run mode)

    Ensures:
        - returns (n_replaced, mutated)
        - n_replaced is the number of entry-boundary `\\n---\\n` occurrences
          replaced with the new separator
        - mutated is True only if dry_run is False and n_replaced > 0
        - Backup is written to `backup_root/<file-name>` before any
          destructive write
        - Files without legacy entry boundaries are no-ops (mtime preserved)
    """
    content        = path.read_text( encoding="utf-8" )
    _, body        = _split_frontmatter( content )
    new_body, n_replaced = _migrate_body( body )
    if n_replaced == 0:
        return ( 0, False )

    if dry_run:
        return ( n_replaced, False )

    # Backup before mutating
    backup_root.mkdir( parents=True, exist_ok=True )
    backup_path = backup_root / path.name
    shutil.copy2( path, backup_path )

    new_content = _reconstruct_content( content, body, new_body )
    path.write_text( new_content, encoding="utf-8" )
    return ( n_replaced, True )


def _enumerate_topic_files( commons_dir: Path ) -> List[ Path ]:
    """
    Enumerate `.md` topic files under commons_dir (live + archive).

    Excludes the backup directory if it already exists from a prior run.
    """
    if not commons_dir.exists():
        return [ ]
    backup_name = ".pre-separator-migration-backup"
    files: List[ Path ] = [ ]
    for path in sorted( commons_dir.rglob( "*.md" ) ):
        if backup_name in path.parts:
            continue
        files.append( path )
    return files


def migrate_directory(
    commons_dir : Path,
    dry_run     : bool = False,
    with_backup : bool = True,
) -> dict:
    """
    Run migration over `commons_dir` and its `archive/` subtree.

    Requires:
        - commons_dir is the project's `io/commons/` directory (or a fixture
          equivalent for tests)

    Ensures:
        - returns a summary dict:
            {
                "run_ts"           : str,
                "files_scanned"    : int,
                "files_mutated"    : int,
                "total_replaced"   : int,
                "backup_dir"       : Path or None,
                "dry_run"          : bool,
                "per_file"         : list of dicts with {path, n_replaced, mutated},
            }
        - In dry_run mode, no disk writes occur (files_mutated == 0)
        - When with_backup is True and dry_run is False, backups land under
          `commons_dir/.pre-separator-migration-backup/<run-ts>/`
    """
    run_ts       = _now_run_ts()
    backup_dir   = commons_dir / ".pre-separator-migration-backup" / run_ts if with_backup else None
    files        = _enumerate_topic_files( commons_dir )
    per_file     : List[ dict ] = [ ]
    total_repl   = 0
    n_mutated    = 0

    for path in files:
        if backup_dir is None:
            n_repl, mutated = _migrate_file_no_backup( path, dry_run )
        else:
            n_repl, mutated = _migrate_file( path, dry_run, backup_dir )
        per_file.append( {
            "path"       : path,
            "n_replaced" : n_repl,
            "mutated"    : mutated,
        } )
        total_repl += n_repl
        if mutated:
            n_mutated += 1

    return {
        "run_ts"           : run_ts,
        "files_scanned"    : len( files ),
        "files_mutated"    : n_mutated,
        "total_replaced"   : total_repl,
        "backup_dir"       : backup_dir,
        "dry_run"          : dry_run,
        "per_file"         : per_file,
    }


def _migrate_file_no_backup( path: Path, dry_run: bool ) -> Tuple[ int, bool ]:
    """
    Migrate without writing a backup. Used when `--no-backup` is passed.
    """
    content        = path.read_text( encoding="utf-8" )
    _, body        = _split_frontmatter( content )
    new_body, n_replaced = _migrate_body( body )
    if n_replaced == 0:
        return ( 0, False )
    if dry_run:
        return ( n_replaced, False )
    new_content = _reconstruct_content( content, body, new_body )
    path.write_text( new_content, encoding="utf-8" )
    return ( n_replaced, True )


def _format_summary( summary: dict ) -> str:
    """Build a human-readable summary string for stdout."""
    lines = [
        f"run_ts         : {summary[ 'run_ts' ]}",
        f"dry_run        : {summary[ 'dry_run' ]}",
        f"files_scanned  : {summary[ 'files_scanned' ]}",
        f"files_mutated  : {summary[ 'files_mutated' ]}",
        f"total_replaced : {summary[ 'total_replaced' ]}",
        f"backup_dir     : {summary[ 'backup_dir' ]}",
        "",
        "Per-file:",
    ]
    for entry in summary[ "per_file" ]:
        marker = "✓" if entry[ "mutated" ] else ("?" if entry[ "n_replaced" ] > 0 else "—")
        lines.append( f"  {marker} {entry[ 'path' ]} ({entry[ 'n_replaced' ]} replacements)" )
    return "\n".join( lines )


def main( argv: List[ str ] = None ) -> int:
    """
    CLI entry. Returns 0 on success, 1 on usage error.
    """
    parser = argparse.ArgumentParser( description="Migrate commons entry separator from legacy `\\n---\\n` to canonical." )
    parser.add_argument( "--commons-dir", type=Path, default=None,
                         help="commons directory to migrate (default: $LUPIN_ROOT/io/commons)" )
    parser.add_argument( "--dry-run", action="store_true",
                         help="Report what would change without touching disk" )
    parser.add_argument( "--no-backup", action="store_true",
                         help="Skip backup directory (caller already has off-disk backup)" )
    args = parser.parse_args( argv )

    commons_dir = args.commons_dir
    if commons_dir is None:
        commons_dir = Path( _LUPIN_ROOT ) / "io" / "commons"             # pragma: no cover

    if not commons_dir.exists():
        sys.stderr.write( f"commons directory does not exist: {commons_dir}\n" )
        return 1

    summary = migrate_directory(
        commons_dir = commons_dir,
        dry_run     = args.dry_run,
        with_backup = not args.no_backup,
    )
    sys.stdout.write( _format_summary( summary ) + "\n" )
    return 0


if __name__ == "__main__":                                              # pragma: no cover
    sys.exit( main() )                                                  # pragma: no cover
