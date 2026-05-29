"""
File-based store for inter-session commons.

Append-only topic files under `<project_root>/io/commons/`. Topic-level
YAML frontmatter declares whether the topic is reserved (`broadcast-acks`,
`presence`, `system-events`) or free-form. Each entry has a markdown header
line plus an inline JSON metadata line. POSIX `fcntl.flock` provides
multi-writer safety for the append path.

Per AC1, AC2, AC3, AC4, AC5, AC9 in
src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md.

**Persona color storage**: AC3 + C4 ratify color as stored at post-time
(immutable per-allocation, no read-time re-derivation). The header line
carries `persona_name` + `persona_icon` for human readability; `persona_color`
is auto-injected into entry metadata under the key `_persona_color` (and
similarly `_session_id` is mirrored into metadata for parser convenience).
The output dict from `read()` pulls both back out as top-level fields.
"""

import fcntl
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

RESERVED_TOPICS              = ( "broadcast-acks", "broadcasts", "presence", "system-events" )
DEFAULT_PERSONA_NAME         = "<unknown>"
DEFAULT_PERSONA_ICON         = "💬"
DEFAULT_PERSONA_COLOR        = "#888888"
SCHEMA_VERSION               = 1

# Entry separator: the on-disk delimiter between entries. Must NOT collide
# with markdown syntax that legitimately appears in entry bodies. The legacy
# value `"\n---\n"` collided with markdown thematic-break syntax, silently
# truncating any entry whose body contained `---` on its own line — see
# src/rnd/v0.1.7/2026.05.18-body-display-truncation-investigation.md.
# read() supports both forms during the migration window; migration script
# at src/scripts/migrate-commons-entry-separator.py converts legacy files.
ENTRY_SEPARATOR              = "\n<<<__lupin_commons_entry_boundary__>>>\n"
LEGACY_ENTRY_SEPARATOR       = "\n---\n"

_HEADER_RE = re.compile(
    r"^## (?P<ts>\S+) \| (?P<persona_name>.+?) (?P<persona_icon>\S+) #(?P<session_id>[A-Za-z0-9_-]+)\s*$"
)
_METADATA_RE = re.compile( r"^\*\*metadata\*\*:\s*`(?P<json>.+)`\s*$" )


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string (microsecond precision; suffix +00:00)."""
    return datetime.now( timezone.utc ).isoformat( timespec="microseconds" )


def _frontmatter_block( topic: str, reserved: bool, created_iso: str ) -> str:
    """Build the YAML frontmatter block (without trailing newline)."""
    block = (
        f"---\n"
        f"topic: {topic}\n"
        f"reserved: {str( reserved ).lower()}\n"
        f"schema_version: {SCHEMA_VERSION}\n"
        f"created: {created_iso}\n"
        f"---\n"
    )
    return block


def _split_frontmatter( content: str ) -> Tuple[ Dict[ str, Any ], str ]:
    """
    Split YAML frontmatter (between two `---` lines) from rest of file.

    Returns (frontmatter_dict, remainder_text). If no frontmatter present,
    returns ({}, content).
    """
    if not content.startswith( "---\n" ):
        return ( { }, content )
    rest = content[ 4: ]
    end_idx = rest.find( "\n---\n" )
    if end_idx == -1:
        return ( { }, content )
    fm_text = rest[ :end_idx ]
    body    = rest[ end_idx + 5: ]
    try:
        fm = yaml.safe_load( fm_text ) or { }
    except yaml.YAMLError:
        fm = { }
    if not isinstance( fm, dict ):
        fm = { }
    return ( fm, body )


def _parse_entry_block( block: str ) -> Optional[ Dict[ str, Any ] ]:
    """
    Parse a single entry block (header + optional metadata + body).

    Returns dict with `{ts, sender_session_id, persona_name, persona_icon,
    persona_color, body, metadata}`, or None if the block is empty / malformed.
    """
    stripped = block.strip()
    if not stripped:
        return None
    lines = stripped.split( "\n" )
    header_match = _HEADER_RE.match( lines[ 0 ] )
    if not header_match:
        return None
    ts            = header_match.group( "ts" )
    persona_name  = header_match.group( "persona_name" ).strip()
    persona_icon  = header_match.group( "persona_icon" )
    session_id    = header_match.group( "session_id" )

    metadata      = { }
    body_lines    = [ ]
    for line in lines[ 1: ]:
        md_match = _METADATA_RE.match( line )
        if md_match and not metadata:
            try:
                metadata = json.loads( md_match.group( "json" ) )
            except ( json.JSONDecodeError, ValueError ):
                metadata = { }
            continue
        body_lines.append( line )
    body = "\n".join( body_lines ).strip()
    persona_color = metadata.pop( "_persona_color", DEFAULT_PERSONA_COLOR )
    metadata.pop( "_session_id", None )
    return {
        "ts"                : ts,
        "sender_session_id" : session_id,
        "persona_name"      : persona_name,
        "persona_icon"      : persona_icon,
        "persona_color"     : persona_color,
        "body"              : body,
        "metadata"          : metadata,
    }


def _warn_orphan_blocks( path: Path, count: int ) -> None:
    """
    Log a warning when read() encountered orphan blocks (content that did
    NOT parse into valid entries). Orphan blocks usually indicate one of:
    - Legacy `\\n---\\n` separator colliding with markdown thematic breaks
      in entry bodies (run `src/scripts/migrate-commons-entry-separator.py`)
    - Manual edits that corrupted the on-disk format
    - A `_format_entry` change that didn't round-trip cleanly

    Emits to stderr — single line per read() call. See
    src/rnd/v0.1.7/2026.05.18-body-display-truncation-investigation.md §5.3
    (defense-in-depth fix).
    """
    sys.stderr.write(
        f"[commons_store] WARN: {count} orphan block(s) in {path} — "
        f"likely separator-collision (legacy '\\n---\\n' colliding with markdown "
        f"thematic break); run migrate-commons-entry-separator.py\n"
    )


def _format_entry(
    ts            : str,
    session_id    : str,
    persona_name  : str,
    persona_icon  : str,
    persona_color : str,
    body          : str,
    metadata      : Dict[ str, Any ],
) -> str:
    """
    Build an entry's markdown block (without trailing `---` separator).

    Mirrors `_persona_color` + `_session_id` into metadata so they survive
    a round-trip through the parser. Per the immutability rule (C4), color
    is set at post-time and never re-derived.
    """
    merged_metadata = dict( metadata )
    merged_metadata[ "_persona_color" ] = persona_color
    merged_metadata[ "_session_id" ]    = session_id
    metadata_json = json.dumps( merged_metadata, ensure_ascii=False )
    return (
        f"## {ts} | {persona_name} {persona_icon} #{session_id}\n"
        f"**metadata**: `{metadata_json}`\n\n"
        f"{body.strip()}\n"
    )


class CommonsStore:
    """
    File-based store for commons topic files.

    Manages a `<root>/io/commons/` directory: creates it on first use,
    seeds reserved topics with frontmatter, and provides append-only post +
    read + presence operations.

    Requires:
        - `root` is a path-like; the project root (or any base path for tests)

    Ensures:
        - `<root>/io/commons/` and `<root>/io/commons/archive/` exist
        - Reserved topic files (`broadcast-acks.md`, `presence.md`,
          `system-events.md`) exist with frontmatter declaring `reserved: true`
        - Idempotent on repeat construction (no overwrites)
    """

    def __init__( self, root: os.PathLike ):
        self.root          = Path( root )
        self.commons_dir   = self.root / "io" / "commons"
        self.archive_dir   = self.commons_dir / "archive"
        self.commons_dir.mkdir( parents=True, exist_ok=True )
        self.archive_dir.mkdir( parents=True, exist_ok=True )
        self._seed_reserved_topics()

    def _seed_reserved_topics( self ) -> None:
        """Create reserved topic files with frontmatter if not already present."""
        now_iso = _now_iso()
        for topic in RESERVED_TOPICS:
            path = self.commons_dir / f"{topic}.md"
            if path.exists():
                continue
            path.write_text( _frontmatter_block( topic, True, now_iso ), encoding="utf-8" )

    def _topic_path( self, topic: str ) -> Path:
        return self.commons_dir / f"{topic}.md"

    def post(
        self,
        topic         : str,
        body          : str,
        sender_session_id : str,
        persona_name  : Optional[ str ] = None,
        persona_icon  : Optional[ str ] = None,
        persona_color : Optional[ str ] = None,
        metadata      : Optional[ Dict[ str, Any ] ] = None,
    ) -> Dict[ str, Any ]:
        """
        Append an entry to `topic`. Free-form topics auto-create on first post.

        Per AC3: persona fields are stored at post-time (immutable); missing
        fields are substituted with defaults (`<unknown>` / `💬` / `#888888`).

        Returns the parsed entry dict (same shape as `read()` yields).

        Multi-writer safety via `fcntl.flock` per F6 REUSE rationale.
        """
        ts            = _now_iso()
        persona_name  = persona_name  if persona_name  is not None else DEFAULT_PERSONA_NAME
        persona_icon  = persona_icon  if persona_icon  is not None else DEFAULT_PERSONA_ICON
        persona_color = persona_color if persona_color is not None else DEFAULT_PERSONA_COLOR
        metadata      = dict( metadata ) if metadata else { }

        path = self._topic_path( topic )
        entry_text = _format_entry(
            ts            = ts,
            session_id    = sender_session_id,
            persona_name  = persona_name,
            persona_icon  = persona_icon,
            persona_color = persona_color,
            body          = body,
            metadata      = metadata,
        )

        with open( path, "a+", encoding="utf-8" ) as f:
            fcntl.flock( f.fileno(), fcntl.LOCK_EX )
            try:
                f.seek( 0, os.SEEK_END )
                empty_file = f.tell() == 0
                if empty_file:
                    f.write( _frontmatter_block( topic, False, ts ) )
                f.write( ENTRY_SEPARATOR )
                f.write( entry_text )
            finally:
                fcntl.flock( f.fileno(), fcntl.LOCK_UN )

        return {
            "ts"                : ts,
            "sender_session_id" : sender_session_id,
            "persona_name"      : persona_name,
            "persona_icon"      : persona_icon,
            "persona_color"     : persona_color,
            "body"              : body.strip(),
            "metadata"          : metadata,
        }

    def read(
        self,
        topic : str,
        since : Optional[ str ] = None,
        limit : int = 50,
    ) -> List[ Dict[ str, Any ] ]:
        """
        Return parsed entries from `topic` (newest first when no `since`,
        ascending when `since` supplied). Honors `limit` strictly.

        Missing free-form topic → empty list. Missing reserved topic → raises
        FileNotFoundError (per AC4: should never happen post-AC2).
        """
        path = self._topic_path( topic )
        if not path.exists():
            if topic in RESERVED_TOPICS:
                raise FileNotFoundError( f"Reserved topic file missing: {path}" )
            return [ ]
        content    = path.read_text( encoding="utf-8" )
        _, body    = _split_frontmatter( content )
        # Try the canonical separator first. Fall back to the legacy "\n---\n"
        # separator for files that have not yet been migrated. The legacy
        # split is INTENTIONALLY a fallback (not a parallel always-attempt)
        # because legacy split collides with markdown thematic-break syntax;
        # using it on a migrated file would re-introduce the truncation bug.
        if ENTRY_SEPARATOR in body:
            raw_blocks = body.split( ENTRY_SEPARATOR )
        else:
            raw_blocks = body.split( LEGACY_ENTRY_SEPARATOR )
        entries: List[ Dict[ str, Any ] ] = [ ]
        orphan_count = 0
        for block in raw_blocks:
            if not block.strip():
                continue
            entry = _parse_entry_block( block )
            if entry is not None:
                entries.append( entry )
            else:
                orphan_count += 1
        if orphan_count > 0:
            _warn_orphan_blocks( path, orphan_count )
        if since is not None:
            entries = [ e for e in entries if e[ "ts" ] > since ]
            entries.sort( key=lambda e: e[ "ts" ] )
        else:
            entries.sort( key=lambda e: e[ "ts" ], reverse=True )
        return entries[ :limit ]

    def who( self, topic: Optional[ str ] = None, retention_hours: int = 24 ) -> List[ Dict[ str, Any ] ]:
        """
        Presence: sessions with at least one post in the last `retention_hours`.

        Per AC5: 24h window calculated at call-time. If `topic` is provided,
        scans only that topic file; otherwise scans ALL active topic files.
        """
        cutoff_iso = ( datetime.now( timezone.utc ) - _hours_delta( retention_hours ) ).isoformat( timespec="microseconds" )
        topics = [ topic ] if topic else self._all_topic_names()
        latest_by_session: Dict[ str, Dict[ str, Any ] ] = { }
        for t in topics:
            try:
                entries = self.read( t, since=cutoff_iso, limit=100000 )
            except FileNotFoundError:
                continue
            for e in entries:
                sid = e[ "sender_session_id" ]
                prior = latest_by_session.get( sid )
                if prior is None or e[ "ts" ] > prior[ "last_post_ts" ]:
                    latest_by_session[ sid ] = {
                        "session_id"     : sid,
                        "persona_name"   : e[ "persona_name" ],
                        "persona_icon"   : e[ "persona_icon" ],
                        "persona_color"  : e[ "persona_color" ],
                        "last_post_ts"   : e[ "ts" ],
                    }
        return sorted( latest_by_session.values(), key=lambda row: row[ "last_post_ts" ], reverse=True )

    def _all_topic_names( self ) -> List[ str ]:
        """Enumerate topic names from `*.md` files in commons_dir (sorted)."""
        return sorted( p.stem for p in self.commons_dir.glob( "*.md" ) )


def _hours_delta( hours: int ):
    """Return a timedelta of `hours` hours (extracted for testability)."""
    from datetime import timedelta
    return timedelta( hours=hours )
