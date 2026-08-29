"""Reviewer-authored (Tiffany 💍) pointer-resolution cases for reap_memento.

Independent of Rio's 8 tests in test_reap_memento.py — these were authored against the
DEFECT, not against the fix. They pin: valid-record-behind-pointer, missing-record,
the case3 corruption path (banner present, no `current:` → fail loud with a DISTINCT
reason), subdir/traversal `current:` never reading outside the slot dir, and a legacy
direct record still verifying. Provenance-pinned so a worktree run cannot silently
import the main-tree module (the conftest sys.path[0] false-green, row a9f87d29).
"""

import datetime

from lupin_mcp import reap_memento

# Provenance guard: fail loud if the module under test is not the tree we are running in,
# so a false green off a different tree cannot pass unnoticed (row a9f87d29 / bab95a0a).
assert reap_memento.__file__.endswith( "src/lupin_mcp/reap_memento.py" ), reap_memento.__file__

_NOW = datetime.datetime( 2026, 8, 14, 15, 5, 0, tzinfo=datetime.timezone.utc )
_PTR = "/proj/io/mementos/rio.md"
_REC = "/proj/io/mementos/rio-abc12345.md"


class _Disk:
    def __init__( self, files ): self.files = dict( files )
    def read( self, path ): return self.files.get( str( path ) )


def _record( sid8="abc12345", written_at="2026-08-14T15:00:00+00:00", body_bytes=1200 ):
    header = ( f"<!-- memento-record: persona=Rio session_id={sid8} "
               f"written_at={written_at} slot=io -->\n" )
    return header + ( "x" * body_bytes )


def _pointer( current="io/mementos/rio-abc12345.md", with_current=True, embed_record=True ):
    lines = [ "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->" ]
    if with_current: lines.append( f"<!-- current: {current} -->" )
    lines.append( "<!-- mirror:  /home/rruiz/.claude/mementos/lupin/io/mementos/rio-abc12345.md -->" )
    lines.append( "<!-- regenerate: memento_io.py regenerate-pointer -->" )
    text = "\n".join( lines ) + "\n"
    if embed_record: text += _record()
    return text


def _verify( files ):
    return reap_memento.verify_seat_memento( _PTR, "abc12345", _NOW,
        read_text_fn=_Disk( files ).read, window_seconds=1200, min_bytes=1000 )


def test_case1_valid_record_behind_pointer_is_present():
    ok, reason = _verify( { _PTR: _pointer(), _REC: _record() } )
    assert ok is True, reason


def test_case2_record_missing_fails_loud():
    ok, reason = _verify( { _PTR: _pointer() } )
    assert ok is False
    assert "record is unreadable or absent" in reason, reason


def test_case3_banner_without_current_fails_loud_distinct_reason():
    ok, reason = _verify( { _PTR: _pointer( with_current=False ) } )
    assert ok is False, reason
    assert "names no `current:` record" in reason, reason
    _, missing = _verify( { _PTR: _pointer() } )
    assert reason != missing


def test_case4_subdir_current_backstopped_by_session_gate():
    files = { _PTR: _pointer( current="deep/sub/rio-abc12345.md" ),
              "/proj/io/mementos/rio-abc12345.md": _record( sid8="ffff0000" ),
              "/proj/io/mementos/deep/sub/rio-abc12345.md": _record() }
    ok, reason = _verify( files )
    assert ok is False and "prior holder" in reason, reason


def test_case5_traversal_current_never_reads_outside_dir():
    files = { _PTR: _pointer( current="../../../../tmp/rio-abc12345.md" ),
              "/tmp/rio-abc12345.md": _record() }
    ok, reason = _verify( files )
    assert ok is False and "unreadable or absent" in reason, reason


def test_legacy_direct_record_still_verifies():
    ok, reason = _verify( { _PTR: _record() } )
    assert ok is True, reason
