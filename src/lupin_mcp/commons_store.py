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

    def _parse_topic_file( self, path: Path ) -> List[ Dict[ str, Any ] ]:
        """
        Parse one topic file (active or archived) into entries.

        Extracted from `read` so the ACTIVE file and the ARCHIVED dailies go through
        exactly one parser. Two parsers would be two records of one format, and the
        legacy-separator fallback below is precisely the kind of subtlety that
        diverges when it is written twice.

        Ensures:
            - returns the parsed entries, unsorted and unfiltered
            - an unparseable block is counted and warned, never raised
            - a missing file yields [] (the caller decides whether that is a finding)
        """
        if not path.exists():
            return [ ]
        content = path.read_text( encoding="utf-8" )
        _, body = _split_frontmatter( content )
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
        return entries

    def _archive_topic_paths( self, topic: str, since: Optional[ str ] ) -> List[ Path ]:
        """
        The archived daily files for `topic` that could still contribute, NEWEST FIRST.

        `commons_archival` writes to `archive/yyyy-mm-dd/<topic>.md`, so the directory
        name is a usable date key and the irrelevant dailies can be skipped WITHOUT
        opening them. That bound is the point: the post-game topic alone holds 1.1 MB
        across 10 dailies, and a reader that opens all of them to answer a one-day
        question has replaced a wrong answer with a slow one.

        Requires:
            - since is None or an ISO-8601 timestamp string
        Ensures:
            - returns existing `<topic>.md` paths under `archive/*/`, sorted by
              directory name DESCENDING (newest day first)
            - when `since` is given, drops days that ended before it — compared on the
              10-char date prefix, so a `since` mid-day keeps that whole day. Coarse
              ON PURPOSE: the per-entry `ts > since` filter runs afterwards, so a day
              kept unnecessarily costs one file read, while a day dropped wrongly
              loses entries silently. Only one of those two errors is recoverable.
            - a malformed directory name is KEPT, not skipped — an unparseable name is
              not evidence the day is irrelevant
        """
        if not self.archive_dir.is_dir():
            return [ ]
        since_day = since[ :10 ] if since else None
        paths     = [ ]
        for day_dir in sorted( self.archive_dir.iterdir(), key=lambda p: p.name, reverse=True ):
            if not day_dir.is_dir():
                continue
            if since_day is not None and len( day_dir.name ) == 10 and day_dir.name < since_day:
                continue
            candidate = day_dir / f"{topic}.md"
            if candidate.exists():
                paths.append( candidate )
        return paths

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

        READS THE ARCHIVE TOO, and that is a BUG FIX, not a feature (store row
        `ff1924b5`, María 2026-07-26). `commons_archival` rotates entries older than
        24h out of the active file into `archive/yyyy-mm-dd/<topic>.md` — working
        exactly as specified (AC9). **This reader was never extended to follow, so
        commons was write-only beyond one day through its documented interface.**

        Measured at the time of the fix: the active `post-game.md` held 101 bytes — a
        YAML header, zero entries — while its archive held 1,140,882. `read()` returned
        `[]`, and `since="2026-07-18"` returned `[]` too. **An empty list is
        indistinguishable from "this topic has no such content,"** so a handoff of the
        form "the details are on commons" self-expired after a day, silently, and the
        seat honoring it would reasonably conclude the material was lost. That happened.

        THE ARCHIVE IS READ ONLY WHEN THE ACTIVE FILE CANNOT ALREADY ANSWER:
            · with `since` — only when `since` predates the oldest active entry (or the
              active file is empty). A tail of the last hour still touches one file.
            · without `since` — only when the active file yielded fewer than `limit`.
              This is the arm that bit hardest: the caller passes no `since`, the active
              file is empty, and the honest answer is entirely in the archive.

        DE-DUPLICATION IS MANDATORY, NOT DEFENSIVE. `commons_archival`'s own docstring
        records that its archive-append-then-active-rewrite ordering can, on a failed
        rewrite, leave the same entries in BOTH the archive and the active file for a
        cycle. Merging two surfaces without a key would therefore DOUBLE-REPORT exactly
        those entries — a new defect introduced by the fix for an old one.

        Requires:
            - topic is a topic name; since is None or ISO-8601; limit >= 0
        Ensures:
            - returns at most `limit` entries, newest-first without `since`,
              ascending with `since`
            - every returned entry appears exactly once, keyed on
              (ts, sender_session_id, body)
            - the active file is always read; archive dailies are read only under the
              conditions above, newest day first
        """
        path = self._topic_path( topic )
        if not path.exists() and topic in RESERVED_TOPICS:
            raise FileNotFoundError( f"Reserved topic file missing: {path}" )

        # A missing free-form active file is NO LONGER a short-circuit to []. The topic
        # may have been rotated wholesale, or the file removed while its history stands
        # in the archive; returning [] here was half of the reported defect.
        entries = self._parse_topic_file( path )

        if since is not None:
            oldest_active = min( ( e[ "ts" ] for e in entries ), default=None )
            need_archive  = oldest_active is None or since < oldest_active
        else:
            need_archive  = len( entries ) < limit

        if need_archive:
            seen = { ( e[ "ts" ], e[ "sender_session_id" ], e[ "body" ] ) for e in entries }
            for archived in self._archive_topic_paths( topic, since ):
                for entry in self._parse_topic_file( archived ):
                    key = ( entry[ "ts" ], entry[ "sender_session_id" ], entry[ "body" ] )
                    if key in seen:
                        continue                  # rotation left it in both surfaces
                    seen.add( key )
                    entries.append( entry )
                # EARLY STOP ONLY IN THE NO-`since` CASE. There, days are walked newest
                # first and the query wants the newest `limit` entries, so once we hold
                # `limit` of them no older day can displace any. With `since` the query
                # is "everything after T" — there is no sufficient count, so every day
                # the date filter kept must be read.
                if since is None and len( entries ) >= limit:
                    break

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
