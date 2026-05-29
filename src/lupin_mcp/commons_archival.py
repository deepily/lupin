"""
Daemon-driven 24h rotation for inter-session commons topic files.

Per AC9 in src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md.

Scans `<root>/io/commons/*.md` every `interval_seconds` (default 3600); for each
topic file, entries older than `retention_hours` (default 24) are moved into
`<root>/io/commons/archive/yyyy-mm-dd/<topic>.md`. Active file is rewritten
atomically via tempfile + os.replace; archive append uses fcntl.flock for
multi-writer safety. Reserved topics retain their `reserved: true` frontmatter
through rotation; free-form topics retain `reserved: false`.

Atomicity contract (AC9): archive append runs BEFORE active rewrite. If active
rewrite fails (e.g., disk full mid-replace), no entries are removed from the
active file. The rare archive-succeeds-but-active-rewrite-fails path can leave
the aged entries in BOTH archive and active for one cycle — the next rotation
re-archives, which produces an idempotency-violating duplicate. AC9's primary
constraint ("no data is removed from active file") is preserved.

Daemon scaffold reuses the pattern from
`src/cosa/rest/running_fifo_queue.py:95-107` `_ghost_job_sweep_loop` per F3
of the Phase 1 REUSE pre-pass.
"""

import fcntl
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lupin_mcp.commons_store import (
    ENTRY_SEPARATOR,
    RESERVED_TOPICS,
    _format_entry,
    _frontmatter_block,
    _parse_entry_block,
    _split_frontmatter,
)


def _now_utc() -> datetime:
    """Return current UTC datetime (extracted for test monkeypatching)."""
    return datetime.now( timezone.utc )


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 microsecond string."""
    return _now_utc().isoformat( timespec="microseconds" )


def _today_str_utc() -> str:
    """Return today's UTC date as yyyy-mm-dd (archive subdir name)."""
    return _now_utc().strftime( "%Y-%m-%d" )


def _cutoff_iso( retention_hours: int ) -> str:
    """Return ISO timestamp `retention_hours` ago (UTC)."""
    return ( _now_utc() - timedelta( hours=retention_hours ) ).isoformat( timespec="microseconds" )


def _entries_to_text( topic: str, entries: List[ Dict[ str, Any ] ], reserved: bool, created_iso: str ) -> str:
    """
    Serialize a list of parsed entry dicts back to commons file format.

    Includes a leading frontmatter block and `ENTRY_SEPARATOR`-prefixed
    entry text — matches the exact write shape produced by `CommonsStore.post`.
    """
    out = _frontmatter_block( topic, reserved, created_iso )
    for entry in entries:
        out += ENTRY_SEPARATOR
        out += _format_entry(
            ts            = entry[ "ts" ],
            session_id    = entry[ "sender_session_id" ],
            persona_name  = entry[ "persona_name" ],
            persona_icon  = entry[ "persona_icon" ],
            persona_color = entry[ "persona_color" ],
            body          = entry[ "body" ],
            metadata      = entry[ "metadata" ],
        )
    return out


class CommonsArchiver:
    """
    Rotate aged commons entries from active topic files into per-day archive subdirs.

    Requires:
        - `root` is a path-like; the project root (or any base path for tests)
        - `interval_seconds` is a positive int (daemon loop period)
        - `retention_hours` is a positive int (age cutoff)

    Ensures:
        - `rotate_once()` walks every `<root>/io/commons/*.md`, splits entries
          older than `retention_hours` into `<root>/io/commons/archive/<yyyy-mm-dd>/<topic>.md`
        - Reserved-topic frontmatter is preserved across rotation (`reserved: true` retained)
        - Active-file rewrite is atomic (tempfile + os.replace in same directory)
        - On any rotation failure, no entries are removed from the active file
        - `start()` spawns a daemon thread that calls `rotate_once()` every
          `interval_seconds`; loop body catches all exceptions
        - `stop()` signals the daemon and joins
    """

    def __init__(
        self,
        root             : os.PathLike,
        interval_seconds : int  = 3600,
        retention_hours  : int  = 24,
        debug            : bool = False,
        verbose          : bool = False,
    ):
        self.root             = Path( root )
        self.commons_dir      = self.root / "io" / "commons"
        self.archive_dir      = self.commons_dir / "archive"
        self.interval_seconds = interval_seconds
        self.retention_hours  = retention_hours
        self.debug            = debug
        self.verbose          = verbose
        self._stop_event      = threading.Event()
        self._thread          : Optional[ threading.Thread ] = None

    def start( self ) -> None:
        """Spawn daemon thread. Idempotent — second call on a live archiver is a no-op."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target = self._run_loop,
            daemon = True,
            name   = "CommonsArchiver",
        )
        self._thread.start()

    def stop( self, join_timeout: Optional[ float ] = 5.0 ) -> None:
        """Signal stop and join. Idempotent — safe to call on never-started archiver."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join( timeout=join_timeout )

    def _run_loop( self ) -> None:
        """Daemon body: rotate every interval_seconds until stop event fires."""
        while not self._stop_event.wait( timeout=self.interval_seconds ):
            try:
                self.rotate_once()
            except Exception as e:
                if self.debug: print( f"[CommonsArchiver] rotate_once raised: {e}" )

    def rotate_once( self ) -> Dict[ str, Tuple[ int, int ] ]:
        """
        Walk all active topic files; rotate aged entries to archive.

        Returns dict mapping topic_name → (kept_count, archived_count).
        Missing commons_dir → empty dict (treated as "nothing to do").
        """
        if not self.commons_dir.exists():
            return { }
        cutoff = _cutoff_iso( self.retention_hours )
        results: Dict[ str, Tuple[ int, int ] ] = { }
        for topic_path in sorted( self.commons_dir.glob( "*.md" ) ):
            topic = topic_path.stem
            kept, archived = self._rotate_topic( topic_path, cutoff )
            results[ topic ] = ( kept, archived )
            if self.verbose: print( f"[CommonsArchiver] {topic}: kept={kept} archived={archived}" )
        return results

    def _rotate_topic( self, topic_path: Path, cutoff_iso: str ) -> Tuple[ int, int ]:
        """
        Rotate a single topic file atomically.

        Holds an fcntl.LOCK_EX on the active file for the read+filter+rewrite
        critical section. Archive append (also flock'd on its own handle)
        runs BEFORE the active rewrite so a mid-replace failure cannot lose
        active-file data.
        """
        topic = topic_path.stem
        with open( topic_path, "r+", encoding="utf-8" ) as active:
            fcntl.flock( active.fileno(), fcntl.LOCK_EX )
            try:
                content      = active.read()
                fm, body     = _split_frontmatter( content )
                raw_blocks   = body.split( ENTRY_SEPARATOR )
                kept: List[ Dict[ str, Any ] ] = [ ]
                aged: List[ Dict[ str, Any ] ] = [ ]
                for block in raw_blocks:
                    entry = _parse_entry_block( block )
                    if entry is None:
                        continue
                    if entry[ "ts" ] < cutoff_iso:
                        aged.append( entry )
                    else:
                        kept.append( entry )

                if not aged:
                    return ( len( kept ), 0 )

                self._append_archive( topic, aged )

                reserved    = topic in RESERVED_TOPICS
                created_iso = fm.get( "created" ) if isinstance( fm, dict ) else None
                if created_iso is None:
                    created_iso = _now_iso()
                new_content = _entries_to_text( topic, kept, reserved, str( created_iso ) )
                self._atomic_rewrite( topic_path, new_content )
                return ( len( kept ), len( aged ) )
            finally:
                fcntl.flock( active.fileno(), fcntl.LOCK_UN )

    def _append_archive( self, topic: str, entries: List[ Dict[ str, Any ] ] ) -> Path:
        """
        Append entries to today's archive file under archive/yyyy-mm-dd/<topic>.md.

        Creates the day-dir on first use; seeds frontmatter on first write to
        a previously-absent file. Multiple rotations on the same day append
        cumulatively to the same archive file. Uses fcntl.LOCK_EX for safety
        against concurrent archive writes (rare, but cheap).
        """
        archive_day_dir = self.archive_dir / _today_str_utc()
        archive_day_dir.mkdir( parents=True, exist_ok=True )
        archive_path = archive_day_dir / f"{topic}.md"
        with open( archive_path, "a+", encoding="utf-8" ) as f:
            fcntl.flock( f.fileno(), fcntl.LOCK_EX )
            try:
                f.seek( 0, os.SEEK_END )
                if f.tell() == 0:
                    f.write( _frontmatter_block( topic, topic in RESERVED_TOPICS, _now_iso() ) )
                for entry in entries:
                    f.write( ENTRY_SEPARATOR )
                    f.write( _format_entry(
                        ts            = entry[ "ts" ],
                        session_id    = entry[ "sender_session_id" ],
                        persona_name  = entry[ "persona_name" ],
                        persona_icon  = entry[ "persona_icon" ],
                        persona_color = entry[ "persona_color" ],
                        body          = entry[ "body" ],
                        metadata      = entry[ "metadata" ],
                    ) )
            finally:
                fcntl.flock( f.fileno(), fcntl.LOCK_UN )
        return archive_path

    def _atomic_rewrite( self, topic_path: Path, content: str ) -> None:
        """
        Atomic file rewrite: write to a sibling tempfile, fsync, then os.replace.

        If the tempfile write or replace raises, the tempfile is cleaned up
        and the original active file is left untouched.
        """
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir    = str( topic_path.parent ),
            prefix = f".{topic_path.name}.",
            suffix = ".tmp",
        )
        try:
            with os.fdopen( tmp_fd, "w", encoding="utf-8" ) as tmp:
                tmp.write( content )
                tmp.flush()
                os.fsync( tmp.fileno() )
            os.replace( tmp_path, topic_path )
        except Exception:
            try:
                os.unlink( tmp_path )
            except OSError:
                pass
            raise
