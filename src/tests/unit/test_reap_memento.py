"""
Unit tests for lupin_mcp.reap_memento — the reap-path memento coordinator (row 0a36d83d).

THE DEFECT UNDER TEST: `dismiss_sessions( write_memento=True )` used to report
success and write nothing. These tests assert the coordinator's ACTUAL verdicts —
a memento proven (or not) on disk — not that a flag was echoed. Per Mr. Radio's
review the guard must be shown to fail in BOTH directions: a skip that never fires
is as broken as one that always fires, and the header-less file is a real input.

Every seam (clock, file read, DM send, sleep) is injected — no live server.
"""

import datetime

import pytest

from lupin_mcp import reap_memento


# ── Fixtures / helpers ────────────────────────────────────────────────────────
_NOW = datetime.datetime( 2026, 8, 14, 15, 5, 0, tzinfo=datetime.timezone.utc )


def _now_fn():
    return _NOW


def _memento( sid8="abc12345", written_at="2026-08-14T15:00:00+00:00", body_bytes=1200 ):
    """A valid, fresh, complete memento with a line-1 memento-record header."""
    header = ( f"<!-- memento-record: persona=Rio session_id={sid8} "
               f"written_at={written_at} slot=io -->\n" )
    return header + ( "x" * body_bytes )


class _Disk:
    """Injected file store: maps str(path) -> text; missing key reads as None."""
    def __init__( self, files=None ):
        self.files = dict( files or {} )
    def read( self, path ):
        return self.files.get( str( path ) )


class _DM:
    """Records every ask; optionally raises for a named persona."""
    def __init__( self, raise_for=None ):
        self.calls     = []
        self.raise_for = set( raise_for or [] )
    def __call__( self, persona, session_id, body ):
        self.calls.append( { "persona": persona, "session_id": session_id, "body": body } )
        if persona in self.raise_for:
            raise RuntimeError( "dm boom" )
        return { "status": "sent" }


def _ident( name="Rio", sid="abc12345ffff", cwd="/proj" ):
    # `cwd` is the seat's own repo, and it is NOT optional in a real bridge — all 23
    # live bridges carry one (row 80b930e6). The slot is now derived per-seat from
    # this field rather than from the batch-wide project_root, so a fixture without
    # it would describe a seat that cannot exist. It defaults to "/proj" to match the
    # project_root these tests already pass, keeping every verdict below unchanged.
    return { "persona": { "name": name }, "session_id": sid, "cwd": cwd }


# ── seat_memento_slot ─────────────────────────────────────────────────────────
def test_seat_memento_slot_uses_bare_persona_slug():
    slot = reap_memento.seat_memento_slot( "/proj", "Mr. Radio" )
    assert str( slot ) == "/proj/io/mementos/mr-radio.md"


# ── parse_memento_header ──────────────────────────────────────────────────────
def test_parse_header_empty_text_is_empty():
    assert reap_memento.parse_memento_header( "" ) == {}
    assert reap_memento.parse_memento_header( None ) == {}


def test_parse_header_no_marker_is_empty():
    assert reap_memento.parse_memento_header( "just a body, no header at all" ) == {}


def test_parse_header_ignores_stray_header_below_line_one():
    # The provenance stamp is line 1. A stray marker deeper in the body is not it.
    text = "# a real memento body\nsome prose\n<!-- memento-record: session_id=abc12345 -->\n"
    assert reap_memento.parse_memento_header( text ) == {}


def test_parse_header_parses_fields_and_skips_bare_tokens():
    text = "<!-- memento-record: persona=Rio bareword session_id=abc12345 slot=io -->\nbody"
    fields = reap_memento.parse_memento_header( text )
    assert fields[ "persona" ]    == "Rio"
    assert fields[ "session_id" ] == "abc12345"
    assert fields[ "slot" ]       == "io"
    assert "bareword" not in fields          # a token without '=' is ignored


# ── _parse_iso_aware ──────────────────────────────────────────────────────────
def test_parse_iso_aware_accepts_aware():
    dt = reap_memento._parse_iso_aware( "2026-08-14T15:00:00+00:00" )
    assert dt is not None and dt.tzinfo is not None


def test_parse_iso_aware_rejects_naive():
    assert reap_memento._parse_iso_aware( "2026-08-14T15:00:00" ) is None


def test_parse_iso_aware_rejects_garbage_and_none():
    assert reap_memento._parse_iso_aware( "not-a-date" ) is None
    assert reap_memento._parse_iso_aware( None ) is None


# ── verify_seat_memento — the ALL-OR-ASK predicate ────────────────────────────
def _verify( text, sid8="abc12345", window=1200, min_bytes=1000 ):
    disk = _Disk( { "/slot.md": text } ) if text is not None else _Disk()
    return reap_memento.verify_seat_memento(
        "/slot.md", sid8, _NOW, read_text_fn=disk.read,
        window_seconds=window, min_bytes=min_bytes )


def test_verify_true_when_complete_matched_and_fresh():
    ok, reason = _verify( _memento() )
    assert ok is True
    assert "verified" in reason


def test_verify_false_when_file_absent():
    ok, reason = _verify( None )
    assert ok is False and "no memento at slot" in reason


def test_verify_false_when_too_small_zero_byte_defeat():
    # The zero-byte defeat Mr. Radio named: a freshness-only guard would pass this.
    ok, reason = _verify( _memento( body_bytes=1 ) )
    assert ok is False and "too small" in reason


def test_verify_false_when_header_absent_big_body():
    # Header-less file is a REAL input (older / hand-written mementos). Must ASK.
    ok, reason = _verify( "y" * 5000 )
    assert ok is False and "no parseable memento-record header" in reason


def test_verify_false_when_header_has_no_session_id():
    text = "<!-- memento-record: persona=Rio written_at=2026-08-14T15:00:00+00:00 -->\n" + "x" * 1200
    ok, reason = _verify( text )
    assert ok is False and "no session_id" in reason


def test_verify_false_when_session_id_mismatch_prior_holder():
    ok, reason = _verify( _memento( sid8="99999999" ) )
    assert ok is False and "prior holder" in reason


def test_verify_false_when_seat_sid_none_mismatches():
    # exercises the `(seat_sid8 or "")` guard when the caller has no sid
    ok, reason = _verify( _memento( sid8="abc12345" ), sid8=None )
    assert ok is False and "prior holder" in reason


def test_verify_false_when_written_at_naive_or_missing():
    text = "<!-- memento-record: persona=Rio session_id=abc12345 written_at=2026-08-14T15:00:00 -->\n" + "x" * 1200
    ok, reason = _verify( text )
    assert ok is False and "naive" in reason


def test_verify_false_when_written_at_future_dated():
    ok, reason = _verify( _memento( written_at="2026-08-14T15:10:00+00:00" ) )
    assert ok is False and "future-dated" in reason


def test_verify_false_when_stale_beyond_window():
    ok, reason = _verify( _memento( written_at="2026-08-14T14:00:00+00:00" ) )
    assert ok is False and "stale" in reason


def test_verify_true_case_folds_session_id():
    # Header sid stored uppercase, seat sid lowercase → still a match (case-folded).
    ok, reason = _verify( _memento( sid8="ABC12345" ), sid8="abc12345" )
    assert ok is True and "verified" in reason


# ── _identity_bits ────────────────────────────────────────────────────────────
def test_identity_bits_none():
    assert reap_memento._identity_bits( None ) == ( None, None )


def test_identity_bits_persona_dict():
    assert reap_memento._identity_bits( { "persona": { "name": "Rio" }, "session_id": "s1" } ) == ( "Rio", "s1" )


def test_identity_bits_persona_bare_string():
    assert reap_memento._identity_bits( { "persona": "Rio", "session_id": "s1" } ) == ( "Rio", "s1" )


def test_identity_bits_persona_wrong_type_or_missing():
    assert reap_memento._identity_bits( { "persona": 123, "session_id": "s1" } ) == ( None, "s1" )
    assert reap_memento._identity_bits( { "session_id": "s1" } )                  == ( None, "s1" )


# ── _default_read_text (the live file seam) ───────────────────────────────────
def test_default_read_text_reads_and_returns_none_on_missing( tmp_path ):
    target = tmp_path / "m.md"
    target.write_text( "hello" )
    assert reap_memento._default_read_text( str( target ) ) == "hello"
    assert reap_memento._default_read_text( str( tmp_path / "nope.md" ) ) is None


def test_default_read_text_none_on_invalid_utf8_not_crash( tmp_path ):
    # A memento truncated mid-multibyte-char is invalid UTF-8 (UnicodeDecodeError,
    # NOT OSError). It must read as unreadable → None → ASK, never crash the batch.
    target = tmp_path / "bad.md"
    target.write_bytes( b"\xff\xfe partial multibyte \x80\x81" )
    assert reap_memento._default_read_text( str( target ) ) is None


# ── coordinate_mementos — the orchestrator, BOTH directions ───────────────────
def _coord( identities, disk, dm, sleep_fn=None, **kw ):
    return reap_memento.coordinate_mementos(
        identities, project_root="/proj", now_fn=_now_fn,
        read_text_fn=disk.read, dm_fn=dm,
        sleep_fn=sleep_fn if sleep_fn is not None else ( lambda _s: None ), **kw )


def test_coordinate_not_requested_when_write_memento_false():
    dm = _DM()
    out = reap_memento.coordinate_mementos(
        { "tmux-a": _ident() }, project_root="/proj", write_memento=False,
        now_fn=_now_fn, read_text_fn=_Disk().read, dm_fn=dm )
    assert out[ "tmux-a" ][ "status" ] == "not_requested"
    assert dm.calls == []                          # no disk read, no DM


def test_coordinate_skipped_when_no_identity():
    dm  = _DM()
    out = _coord( { "tmux-a": None }, _Disk(), dm, write_memento=True )
    assert out[ "tmux-a" ][ "status" ] == "skipped"
    assert dm.calls == []                          # a seat with no identity is never asked


def test_coordinate_verified_skips_dm_the_skip_direction():
    # SKIP FIRES: a fresh+complete memento already on disk → verified, NO ask.
    slot = str( reap_memento.seat_memento_slot( "/proj", "Rio" ) )
    disk = _Disk( { slot: _memento() } )
    dm   = _DM()
    out  = _coord( { "tmux-a": _ident() }, disk, dm, write_memento=True )
    assert out[ "tmux-a" ][ "status" ] == "verified"
    assert dm.calls == []                          # the double-send / gap guard held


def test_coordinate_written_after_ask_appears_during_poll():
    # ASK FIRES then WRITTEN: empty at first, child writes during the poll window.
    slot = str( reap_memento.seat_memento_slot( "/proj", "Rio" ) )
    disk = _Disk()                                 # slot empty at pass-1
    dm   = _DM()

    def _sleep( _sec ):                            # child "writes" on the first poll
        disk.files[ slot ] = _memento()

    out = _coord( { "tmux-a": _ident() }, disk, dm, sleep_fn=_sleep,
                  write_memento=True, ask_timeout_sec=9, poll_interval_sec=3 )
    assert len( dm.calls ) == 1                     # the seat WAS asked
    assert out[ "tmux-a" ][ "status" ] == "written"
    assert "appeared after ask" in out[ "tmux-a" ][ "reason" ]


def test_coordinate_timeout_when_never_written_visible_failure():
    # ASK FIRES then TIMEOUT: parked/declined child, memento never appears.
    dm  = _DM()
    out = _coord( { "tmux-a": _ident() }, _Disk(), dm,
                  write_memento=True, ask_timeout_sec=6, poll_interval_sec=3 )
    assert len( dm.calls ) == 1
    assert out[ "tmux-a" ][ "status" ] == "timeout_no_memento"
    assert "no fresh+complete memento within 6s" in out[ "tmux-a" ][ "reason" ]


def test_coordinate_records_dm_send_failure_still_times_out():
    dm  = _DM( raise_for=[ "Rio" ] )               # the ask itself raises
    out = _coord( { "tmux-a": _ident() }, _Disk(), dm,
                  write_memento=True, ask_timeout_sec=3, poll_interval_sec=3 )
    assert out[ "tmux-a" ][ "status" ] == "timeout_no_memento"
    assert "ask send raised: RuntimeError" in out[ "tmux-a" ][ "reason" ]


def test_coordinate_mixed_batch_verified_written_timeout_and_skipped():
    slot_v = str( reap_memento.seat_memento_slot( "/proj", "Rio" ) )     # verified
    slot_w = str( reap_memento.seat_memento_slot( "/proj", "Sam" ) )     # written on poll
    disk   = _Disk( { slot_v: _memento() } )
    dm     = _DM()

    def _sleep( _sec ):
        disk.files[ slot_w ] = _memento( sid8="deadbeef" )

    identities = {
        "tmux-v"    : _ident( "Rio", "abc12345ffff" ),   # verified
        "tmux-w"    : _ident( "Sam", "deadbeef0000" ),   # written after ask
        "tmux-t"    : _ident( "Cleo", "11112222ffff" ),  # timeout (never appears)
        "tmux-skip" : None,                              # no identity
    }
    out = _coord( identities, disk, dm, sleep_fn=_sleep,
                  write_memento=True, ask_timeout_sec=9, poll_interval_sec=3 )
    assert out[ "tmux-v" ][ "status" ]    == "verified"
    assert out[ "tmux-w" ][ "status" ]    == "written"
    assert out[ "tmux-t" ][ "status" ]    == "timeout_no_memento"
    assert out[ "tmux-skip" ][ "status" ] == "skipped"
    # only the two un-verified, identified seats were asked
    assert { c[ "persona" ] for c in dm.calls } == { "Sam", "Cleo" }


def test_coordinate_poll_interval_zero_is_clamped_not_hang():
    # A misconfigured poll_interval_sec=0 must NOT hang the reap: the clamp to >=1
    # bounds the wait, so an unwritten seat still reaches timeout_no_memento.
    dm    = _DM()
    slept = { "n": 0 }

    def _sleep( _sec ):
        slept[ "n" ] += 1
        assert slept[ "n" ] < 100                   # a genuine hang would blow past this

    out = _coord( { "tmux-a": _ident() }, _Disk(), dm, sleep_fn=_sleep,
                  write_memento=True, ask_timeout_sec=3, poll_interval_sec=0 )
    assert out[ "tmux-a" ][ "status" ] == "timeout_no_memento"


def test_coordinate_all_verified_never_polls():
    slot = str( reap_memento.seat_memento_slot( "/proj", "Rio" ) )
    disk = _Disk( { slot: _memento() } )
    dm   = _DM()
    slept = { "n": 0 }

    def _sleep( _sec ):
        slept[ "n" ] += 1

    out = _coord( { "tmux-a": _ident() }, disk, dm, sleep_fn=_sleep, write_memento=True )
    assert out[ "tmux-a" ][ "status" ] == "verified"
    assert slept[ "n" ] == 0                        # no pending → poll loop never entered


# ── resolve_pointer_target + pointer-following (defects at reap_memento.py:104,120) ──
def _pointer( record_name="rio-80d0e093.md", sid8="80d0e093" ):
    """A real-shape POINTER slot: current:/mirror:/regenerate: preamble, header on line 5."""
    return (
        "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite. -->\n"
        f"<!-- current: io/mementos/{record_name} -->\n"
        "<!-- mirror:  /home/x/.claude/mementos/lupin/io/mementos/" + record_name + " -->\n"
        "<!-- regenerate: python3 memento_io.py regenerate-pointer -->\n"
        f"<!-- memento-record: persona=rio session_id={sid8} written_at=2026-08-14T15:00:00+00:00 slot=io -->\n"
        "# Rio ⚡ pointer copy title\n"
    )


def test_resolve_pointer_target_follows_current_beside_slot():
    target = reap_memento.resolve_pointer_target( "/proj/io/mementos/rio.md", _pointer() )
    # Resolved as the basename beside the slot dir — never the current: value's own path.
    assert str( target ) == "/proj/io/mementos/rio-80d0e093.md"


def test_resolve_pointer_target_uses_basename_only_traversal_proof():
    text = "<!-- current: ../../etc/passwd -->\n"
    target = reap_memento.resolve_pointer_target( "/proj/io/mementos/rio.md", text )
    assert str( target ) == "/proj/io/mementos/passwd"     # traversal stripped to basename


def test_resolve_pointer_target_none_when_not_a_pointer():
    assert reap_memento.resolve_pointer_target( "/slot.md", _memento() ) is None
    assert reap_memento.resolve_pointer_target( "/slot.md", "" ) is None
    assert reap_memento.resolve_pointer_target( "/slot.md", None ) is None


# ── parse_memento_header: Defect 2 — the header is on line 5 in a pointer ──────
def test_parse_header_found_below_line_one_in_pointer_preamble():
    # REGRESSION for the splitlines()[0]-only bug: the pointer's memento-record header
    # is line 5, behind the current:/mirror: comments. It MUST be parsed.
    fields = reap_memento.parse_memento_header( _pointer( sid8="80d0e093" ) )
    assert fields[ "session_id" ] == "80d0e093"
    assert fields[ "persona" ]    == "rio"


def test_parse_header_still_parses_a_line_one_record():
    fields = reap_memento.parse_memento_header( _memento( sid8="abc12345" ) )
    assert fields[ "session_id" ] == "abc12345"


# ── verify_seat_memento through a POINTER slot (Defect 1) ──────────────────────
def _verify_via( slot_text, record_text, sid8="80d0e093", window=1200, min_bytes=1000 ):
    files = { "/proj/io/mementos/rio.md": slot_text }
    if record_text is not None:
        files[ "/proj/io/mementos/rio-80d0e093.md" ] = record_text
    disk = _Disk( files )
    return reap_memento.verify_seat_memento(
        "/proj/io/mementos/rio.md", sid8, _NOW, read_text_fn=disk.read,
        window_seconds=window, min_bytes=min_bytes )


def test_verify_follows_pointer_and_verifies_the_record():
    # The pointer is tiny (would fail the byte floor); the record is the complete memento.
    ok, reason = _verify_via( _pointer(), _memento( sid8="80d0e093" ) )
    assert ok is True and "verified" in reason


def test_verify_false_when_pointer_names_an_absent_record():
    ok, reason = _verify_via( _pointer(), None )
    assert ok is False and "current:" in reason


def test_verify_false_when_pointed_record_is_stale():
    # Following the pointer must carry the record's OWN freshness, not the pointer's.
    stale = _memento( sid8="80d0e093", written_at="2026-08-14T14:00:00+00:00" )   # 65 min old > 20 min window
    ok, reason = _verify_via( _pointer(), stale )
    assert ok is False and "stale" in reason


def test_verify_false_when_pointed_record_session_mismatch():
    # A re-granted persona slot: pointer/record belong to a PRIOR holder, not this seat.
    ok, reason = _verify_via( _pointer(), _memento( sid8="80d0e093" ), sid8="ffff0000" )
    assert ok is False and "prior holder" in reason


def test_parse_header_when_text_is_all_comment_lines_no_content():
    # Covers the loop exhausting with no content line (a header-only comment block).
    text = "<!-- memento-record: persona=Rio session_id=abc12345 slot=io -->\n"
    fields = reap_memento.parse_memento_header( text )
    assert fields[ "session_id" ] == "abc12345"


# ── classify_slot_presence + the present-vs-absent verdict split (dffebbd6 / ebcb763e) ──
def test_classify_slot_presence_present_empty_absent():
    disk = _Disk( {
        "/proj/io/mementos/full.md"  : "some real content",
        "/proj/io/mementos/blank.md" : "   \n\t  ",          # a write that started and died
    } )
    assert reap_memento.classify_slot_presence( "/proj/io/mementos/full.md",  disk.read ) == "present"
    assert reap_memento.classify_slot_presence( "/proj/io/mementos/blank.md", disk.read ) == "empty"
    assert reap_memento.classify_slot_presence( "/proj/io/mementos/gone.md",  disk.read ) == "absent"


def test_coordinate_unparseable_present_when_h1_only_memento_never_reproven():
    # SHAPE (b): a REAL memento whose identity is a markdown H1 with NO machine header
    # (the clayton.md / krishna.md case). It is on disk, so the reap must NOT call it
    # missing — a manager can OPEN AND READ it. Child never rewrites → unparseable_present.
    slot = str( reap_memento.seat_memento_slot( "/proj", "Clayton" ) )
    disk = _Disk( { slot: "# Memento — Clayton 😎 (session 02eec756)\n" + "x" * 5000 } )
    dm   = _DM()
    out  = _coord( { "tmux-a": _ident( "Clayton", "02eec756ffff" ) }, disk, dm,
                   write_memento=True, ask_timeout_sec=3, poll_interval_sec=3 )
    assert len( dm.calls ) == 1                          # the seat WAS asked (present ≠ verified)
    assert out[ "tmux-a" ][ "status" ] == "unparseable_present"
    assert "OPEN AND READ IT" in out[ "tmux-a" ][ "reason" ]
    assert "no parseable memento-record header" in out[ "tmux-a" ][ "reason" ]  # the at-ask cause


def test_coordinate_unparseable_present_when_pointer_record_vanished():
    # A pointer slot whose current: record is gone: the pointer file is STILL on disk,
    # so the manager can open it to learn what it named → present, not absent.
    slot = str( reap_memento.seat_memento_slot( "/proj", "Rio" ) )
    disk = _Disk( { slot: _pointer() } )                 # pointer present; record file absent
    dm   = _DM()
    out  = _coord( { "tmux-a": _ident( "Rio", "80d0e093ffff" ) }, disk, dm,
                   write_memento=True, ask_timeout_sec=3, poll_interval_sec=3 )
    assert out[ "tmux-a" ][ "status" ] == "unparseable_present"


def test_coordinate_timeout_no_memento_stays_absent_when_slot_empty():
    # The ABSENT side of the split: nothing on disk at all → still timeout_no_memento,
    # the unrecoverable verdict. Backward-compatible with the prior single-status world.
    dm  = _DM()
    out = _coord( { "tmux-a": _ident() }, _Disk(), dm,
                  write_memento=True, ask_timeout_sec=3, poll_interval_sec=3 )
    assert out[ "tmux-a" ][ "status" ] == "timeout_no_memento"
    assert "slot file present but empty" not in out[ "tmux-a" ][ "reason" ]   # truly-absent: no empty note


def test_coordinate_zero_byte_slot_buckets_absent_but_keeps_evidence():
    # Mr. Radio's guard: a 0-byte / whitespace-only slot is a write that started and died.
    # Nothing to read → the ACTION is identical to absent, so it buckets as timeout_no_memento
    # (NOT unparseable_present — that would send a manager to open an empty file). But the
    # reason PRESERVES the started-and-died evidence, distinct from nobody-ever-wrote-one.
    slot = str( reap_memento.seat_memento_slot( "/proj", "Rio" ) )
    disk = _Disk( { slot: "   \n\t  " } )                  # present but whitespace-only
    dm   = _DM()
    out  = _coord( { "tmux-a": _ident() }, disk, dm,
                   write_memento=True, ask_timeout_sec=3, poll_interval_sec=3 )
    assert out[ "tmux-a" ][ "status" ] == "timeout_no_memento"          # verdict drives the action
    assert "slot file present but empty (0 bytes" in out[ "tmux-a" ][ "reason" ]   # evidence preserved
