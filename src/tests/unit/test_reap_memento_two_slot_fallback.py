"""
The reap reads TWO locations: the io slot, then the root RECORD (row 8068c65e).

THE RULING UNDER TEST (Rick via Mr. Radio, 2026-08-30). Rachel's census of all four
of that day's mementos found NO misuse anywhere — one sanctioned verb, well-formed
headers every time. The whole split was a single field: the verb offers `--slot root`
as an ordinary documented option and the reap read `--slot io` only. So a correct call
produced a file nothing would find, and the tool's own success message was honest.
The reap now also looks at the root RECORD.

🔴 WHY THE RECORD AND NEVER THE ROOT POINTER — this is the half of the ruling that
carries the risk, so it gets a negative control of its own. `.claude-memento.md` is
PERSONA-LESS: one file per repo, shared by every seat. Measured 2026-08-30 — Pocholo's
record took it at 14:41, Mr. Radio's took it back at 15:20. Following it on a batch
reap would resolve EVERY seat to whichever wrote last, manufacturing the precise
failure this row exists for: a memento that parses fine and names the wrong work. The
naive build of this fix is strictly more dangerous than the bug, and
`test_negative_control_*` below is what stops it being written.
"""

import datetime

from lupin_mcp import reap_memento
from lupin_mcp.memento_slot import slot_pointer_path, slot_record_path, SLOT_IO, SLOT_ROOT


UTC  = datetime.timezone.utc
_NOW = datetime.datetime( 2026, 8, 30, 19, 5, 0, tzinfo=UTC )
_TS  = "2026-08-30T19:00:00+00:00"

_REPO = "/repo"


def _memento( persona, sid8, written_at=_TS, slot="io", body_bytes=1200 ):
    return ( f"<!-- memento-record: persona={persona} session_id={sid8} "
             f"written_at={written_at} slot={slot} -->\n" + ( "x" * body_bytes ) )


def _read( files ):
    return lambda path: files.get( str( path ) )


def _io( persona ):     return str( slot_pointer_path( _REPO, persona, SLOT_IO ) )
def _io_rec( p, sid ):  return str( slot_record_path( _REPO, p, sid, SLOT_IO ) )
def _root_ptr():        return str( slot_pointer_path( _REPO, "anyone", SLOT_ROOT ) )
def _root_rec( p, sid ):return str( slot_record_path( _REPO, p, sid, SLOT_ROOT ) )


def _resolve( persona, sid8, files ):
    return reap_memento.verify_seat_memento_at_any_readable_slot(
        _REPO, persona, sid8, _NOW, read_text_fn=_read( files ) )


# ---------------------------------------------------------------------------
# Path derivation
# ---------------------------------------------------------------------------
def test_root_record_is_per_persona_and_per_session():
    p = reap_memento.seat_memento_root_record( _REPO, "Pocholo 📣", "fd1bf2e0" )
    assert str( p ) == "/repo/.claude-memento-pocholo-fd1bf2e0.md"


def test_root_record_is_not_the_shared_root_pointer():
    a = reap_memento.seat_memento_root_record( _REPO, "Pocholo 📣", "fd1bf2e0" )
    b = reap_memento.seat_memento_root_record( _REPO, "Mr. Radio 🦉", "93a8751c" )
    assert a != b                       # the whole reason the record is safe
    assert str( a ) != _root_ptr()      # and it is never the shared file


# ---------------------------------------------------------------------------
# The io slot stays PRIMARY
# ---------------------------------------------------------------------------
def test_io_slot_answers_first_and_the_root_is_never_touched():
    seen = []
    files = { _io( "Rio" ): _memento( "rio", "aaaa1111" ) }
    def read( path ):
        seen.append( str( path ) )
        return files.get( str( path ) )
    usable, reason, slot = reap_memento.verify_seat_memento_at_any_readable_slot(
        _REPO, "Rio", "aaaa1111", _NOW, read_text_fn=read )
    assert usable is True
    assert str( slot ) == _io( "Rio" )
    assert not any( "claude-memento" in p for p in seen )   # root never consulted


def test_a_total_miss_reports_the_io_slot_and_its_reason():
    usable, reason, slot = _resolve( "Rio", "aaaa1111", {} )
    assert usable is False
    assert str( slot ) == _io( "Rio" )
    assert "no memento at slot" in reason


# ---------------------------------------------------------------------------
# The root RECORD fallback — the ruling's purpose
# ---------------------------------------------------------------------------
def test_pocholos_real_case_now_resolves_from_the_root_record():
    """
    Pocholo's actual 2026-08-30 state: the io pointer still names his 08-29 session
    (7b4e09c5) while his real memento is the root record for fd1bf2e0. Before the
    ruling this reap read a STALE memento that parses fine — the row's worst case.
    """
    files = {
        _io( "Pocholo 📣" )                    : ( "<!-- MEMENTO POINTER -->\n"
                                                   "<!-- current: pocholo-7b4e09c5.md -->\n"
                                                   + _memento( "pocholo", "7b4e09c5" ) ),
        _io_rec( "Pocholo 📣", "7b4e09c5" )    : _memento( "pocholo", "7b4e09c5" ),
        _root_rec( "Pocholo 📣", "fd1bf2e0" )  : _memento( "pocholo", "fd1bf2e0", slot="root" ),
    }
    usable, reason, slot = _resolve( "Pocholo 📣", "fd1bf2e0", files )
    assert usable is True
    assert str( slot ) == _root_rec( "Pocholo 📣", "fd1bf2e0" )


def test_a_fallback_hit_says_where_it_was_found_and_where_it_belonged():
    """A silent rescue teaches the fleet nothing and the next seat repeats it."""
    files = { _root_rec( "Rio", "aaaa1111" ): _memento( "rio", "aaaa1111", slot="root" ) }
    usable, reason, _ = _resolve( "Rio", "aaaa1111", files )
    assert usable is True
    assert "root-slot RECORD"        in reason
    assert _root_rec( "Rio", "aaaa1111" ) in reason   # where it was found
    assert _io( "Rio" )              in reason        # where it should have been
    assert "--slot io"               in reason        # and how to put it there


def test_a_stale_root_record_is_still_refused():
    files = { _root_rec( "Rio", "aaaa1111" ):
              _memento( "rio", "aaaa1111", written_at="2026-08-30T10:00:00+00:00", slot="root" ) }
    usable, _, _ = _resolve( "Rio", "aaaa1111", files )
    assert usable is False


def test_another_sessions_root_record_is_refused():
    """The fallback widens WHERE we look, never WHOSE memento counts."""
    files = { _root_rec( "Rio", "aaaa1111" ): _memento( "rio", "bbbb2222", slot="root" ) }
    usable, _, _ = _resolve( "Rio", "aaaa1111", files )
    assert usable is False


# ---------------------------------------------------------------------------
# 🔴 NEGATIVE CONTROL — the root POINTER must never be a handoff source
# ---------------------------------------------------------------------------
def test_negative_control_the_shared_root_pointer_is_never_consulted():
    """
    The 14:41 → 15:20 case, exactly. The root pointer holds Mr. Radio's memento; this
    reap is for Pocholo, whose root RECORD does not exist. A build that followed the
    pointer would return TRUE here with somebody else's work — parsing fine, naming the
    wrong seat. It must be a miss, and the pointer must not even be read.
    """
    seen  = []
    files = { _root_ptr(): _memento( "mr-radio", "93a8751c", slot="root" ) }
    def read( path ):
        seen.append( str( path ) )
        return files.get( str( path ) )

    usable, reason, slot = reap_memento.verify_seat_memento_at_any_readable_slot(
        _REPO, "Pocholo 📣", "fd1bf2e0", _NOW, read_text_fn=read )

    assert usable is False
    assert _root_ptr() not in seen                    # never even opened
    assert str( slot ) == _io( "Pocholo 📣" )


def test_negative_control_two_seats_do_not_resolve_to_the_same_file():
    """
    A batch reap of two seats in one repo. Both root records exist; each seat must get
    its OWN. Following the shared pointer would collapse both onto one file — the
    failure mode that made the naive build of this fix worse than the bug.
    """
    files = {
        _root_rec( "Pocholo 📣", "fd1bf2e0" )  : _memento( "pocholo",  "fd1bf2e0", slot="root" ),
        _root_rec( "Mr. Radio 🦉", "93a8751c" ): _memento( "mr-radio", "93a8751c", slot="root" ),
        _root_ptr()                            : _memento( "mr-radio", "93a8751c", slot="root" ),
    }
    _, _, a = _resolve( "Pocholo 📣",  "fd1bf2e0", files )
    _, _, b = _resolve( "Mr. Radio 🦉", "93a8751c", files )
    assert str( a ) != str( b )
    assert "pocholo"  in str( a )
    assert "mr-radio" in str( b )


# ---------------------------------------------------------------------------
# The classifier reports WHERE it found the memento
# ---------------------------------------------------------------------------
def test_slot_state_reports_the_root_record_it_actually_read():
    files = { _root_rec( "Rio", "aaaa1111" ): _memento( "rio", "aaaa1111", slot="root" ) }
    state = reap_memento.describe_slot(
        _REPO, "Rio", "aaaa1111", _NOW, read_text_fn=_read( files ) )
    assert state[ "verdict" ] == "ready"
    assert state[ "slot" ]    == _root_rec( "Rio", "aaaa1111" )


def test_slot_state_still_flags_a_prior_holder_on_the_io_slot():
    """With no usable memento anywhere, the io slot's own story is what gets told."""
    files = { _io( "Rio" ): _memento( "rio", "9999zzzz" ) }
    state = reap_memento.describe_slot(
        _REPO, "Rio", "aaaa1111", _NOW, read_text_fn=_read( files ) )
    assert state[ "verdict" ]            == "prior_holder"
    assert state[ "foreign_session_id" ] == "9999zzzz"
    assert state[ "slot" ]               == _io( "Rio" )


def test_verify_fn_is_injectable_and_is_asked_about_both_locations():
    asked = []
    def fake( path, sid8, now, **k ):
        asked.append( str( path ) )
        return False, "nope"
    reap_memento.verify_seat_memento_at_any_readable_slot(
        _REPO, "Rio", "aaaa1111", _NOW, read_text_fn=lambda p: None, verify_fn=fake )
    assert asked == [ _io( "Rio" ), _root_rec( "Rio", "aaaa1111" ) ]


def test_negative_control_a_pointer_following_build_would_return_the_wrong_seats_work():
    """
    🔴 THE CONTROL, MADE PERMANENT — the dangerous build, run side by side with the real one.

    Describing why the root POINTER must not be followed is not the same as showing it.
    This runs the SAME reap twice, changing only WHERE the fallback looks: the shipped
    resolver (root RECORD) versus the build a reader would naturally write (root POINTER).

    Pocholo is being reaped; his root record does not exist; the shared pointer holds
    Mr. Radio's memento. The pointer-following build returns TRUE with the wrong seat's
    work — a memento that parses fine and names work Pocholo never did, which is this
    row's own stated worst case. The shipped resolver returns a clean miss.
    """
    files = { _root_ptr(): _memento( "mr-radio", "93a8751c", slot="root" ) }

    shipped, _, _ = _resolve( "Pocholo 📣", "fd1bf2e0", files )

    # The naive build: same shape, but the fallback consults the shared pointer. Its
    # verify passes only because verify_seat_memento is checking the pointer's OWN
    # header — which belongs to whoever wrote last.
    naive, _ = reap_memento.verify_seat_memento(
        _root_ptr(), "93a8751c", _NOW, read_text_fn=_read( files ) )

    assert shipped is False   # the shipped resolver: an honest miss
    assert naive   is True    # ...and the natural build would have said yes, to the wrong seat
