"""
`self_respin` reads the `io` slot too, `root` first (row e1e2c545).

WHAT THIS ROW TURNED OUT TO BE, which is NOT what it was filed as. Chloé filed it on
2026-09-20 having measured an 88-minute-stale root record on her own seat: a self-respin
in that window would have seeded a fresh seat with a phase already finished. That harm
is CLOSED — `8068c65e` gave `self_respin` the reap's own predicate, which enforces a
1200s freshness window, so the stale record is now refused out loud. Re-measured
2026-09-26 with a positive control before any negative was trusted.

WHAT REMAINED is the mirror of the defect `8068c65e` fixed for the reap, and its own
reasoning names it: *"a parameter whose legal values are not all readable is the tool's
defect, not the seat's."* The reap got an io primary plus a root-record fallback.
`self_respin` got nothing — it read `root` alone. So a seat holding a complete, fresh,
session-matched memento at `io` had to write a SECOND copy at `root` before it could
self-respin, which is redundant work the tool was in a position to spare it.

⚠️ AND WHAT WAS NEVER WRONG, recorded because the row's own plan said it was. The
refusal a real seat gets is already actionable: leg 1 names both acceptable root targets
and the exact `memento_io.py` command. The bare "no memento at slot" that suggested
otherwise was a probe passing the ROOT path as the caller's claim — not what a seat that
wrote `io` passes. This is not a fix for a confusing message.

THE SPLIT IS NOT OVERRULED (Mr. Radio, 2026-09-26). `root` stays this door's primary and
`io` stays the reap's; each merely also READS the other. `reap_memento`'s module
docstring remains the authority on which door owns which slot.

🔴 WHAT THIS FILE IS HERE TO STOP. The row's own instruction: *"the test that matters
asserts the SEEDED CONTENT, not that a file exists"* — a file-exists test passes on
exactly the stale record the row is about. So the end-to-end arm plants a distinctive
string and proves THAT string is what flowed through the gate the successor rehydrates
from. And the staleness arm exists because a fallback that skipped the window would
REOPEN the original defect: it must refuse at both slots, never rescue.
"""

import datetime

import pytest

import lupin_mcp.self_respin_core as sr
from lupin_mcp.memento_slot import (
    SLOT_IO, SLOT_ROOT, slot_pointer_path, slot_record_path,
    verify_memento_at_any_readable_slot,
)
from lupin_mcp.persona_normalization import persona_slug


UTC     = datetime.timezone.utc
PERSONA = "cheech"
SID     = "sid1"
SLUG    = persona_slug( PERSONA )

# The distinctive payload. A byte count cannot tell this from any other 1200-byte body,
# which is the whole point of the row's "assert the SEEDED CONTENT" instruction.
CANARY  = "CANARY-e1e2c545-the-io-slot-record-is-what-came-through"


def _dt( minute ):
    return datetime.datetime( 2026, 8, 14, 2, minute, tzinfo=UTC )


def _write_pair( root, slot, *, written_at, canary=CANARY, sid=SID, persona=PERSONA ):
    """
    Write the record+pointer pair memento_io produces at `slot`; return the pointer path.

    Ensures:
        - the record carries a real machine-readable header and `canary` in its body
        - the pointer names the record by basename, as memento_io writes it
    """
    record  = slot_record_path( str( root ), persona, sid, slot )
    pointer = slot_pointer_path( str( root ), persona, slot )
    header  = ( f"<!-- memento-record: persona={persona_slug( persona )} "
                f"session_id={sid[ :8 ].lower()} written_at={written_at.isoformat()} "
                f"slot={slot} -->\n" )
    body    = header + f"# memento\n{canary}\n" + ( "x" * 1400 )
    record.parent.mkdir( parents=True, exist_ok=True )
    record.write_text( body )
    pointer.parent.mkdir( parents=True, exist_ok=True )
    pointer.write_text(
        "<!-- MEMENTO POINTER — NOT THE RECORD. Safe to overwrite; it destroys nothing. -->\n"
        f"<!-- current: {record.name} -->\n"
    )
    return str( pointer )


def _verify( tmp_path, claimed_path, *, now=_dt( 21 ) ):
    """The live seam, exactly as self_respin's gate calls it."""
    return sr._default_verify_slot(
        claimed_path, repo_root=str( tmp_path ), persona=PERSONA, session_id=SID,
        now=now, read_text_fn=lambda p: _read_or_none( p ),
    )


def _read_or_none( path ):
    try:
        with open( path, encoding="utf-8" ) as fh: return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# 1. POSITIVE CONTROL — first, so every negative below means something
# ---------------------------------------------------------------------------

def test_positive_control_a_root_slot_memento_still_passes( tmp_path ):
    """
    Ensures: the unchanged primary path still verifies.

    🔴 THIS RUNS FIRST ON PURPOSE. Every other assertion in this file is a claim about
    what the gate REFUSES or ACCEPTS, and a gate wired to nothing refuses everything —
    which would make the negatives below pass for the wrong reason. Two earlier probes
    of this same code returned confident Falses that were the probe's own defects, so
    the instrument proves it can say yes before any no is believed.
    """
    pointer = _write_pair( tmp_path, SLOT_ROOT, written_at=_dt( 20 ) )
    ok, reason = _verify( tmp_path, pointer )
    assert ok, reason
    assert "'root' slot" in reason


# ---------------------------------------------------------------------------
# 2. THE FIX — an io-slot memento is now readable by this door
# ---------------------------------------------------------------------------

def test_an_io_slot_memento_is_accepted_by_the_self_respin_door( tmp_path ):
    """
    Ensures: the row's scenario — wrote `--slot io`, re-spinning through the root door.

    Before this row that was a refusal, and the seat's only remedy was to write a second
    copy of a memento it had already written correctly.
    """
    pointer = _write_pair( tmp_path, SLOT_IO, written_at=_dt( 20 ) )
    ok, reason = _verify( tmp_path, pointer )
    assert ok, reason


def test_the_fallback_hit_names_both_slots_out_loud( tmp_path ):
    """
    Ensures: a fallback success says WHERE it was found AND where it should have gone.

    Mr. Radio's condition, and the reap's own rule: a silent rescue teaches the fleet
    nothing and the next seat repeats it. Asserted on both slot names rather than on the
    word "fallback", so rewording the sentence cannot quietly drop the information.
    """
    pointer = _write_pair( tmp_path, SLOT_IO, written_at=_dt( 20 ) )
    ok, reason = _verify( tmp_path, pointer )
    assert ok
    assert SLOT_IO   in reason
    assert SLOT_ROOT in reason
    assert f"--slot {SLOT_ROOT}" in reason


# ---------------------------------------------------------------------------
# 3. THE FALLBACK WIDENS WHERE THE PROOF LOOKS, NEVER WHAT IT DEMANDS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "slot", [ SLOT_ROOT, SLOT_IO ] )
def test_a_stale_memento_is_refused_at_either_slot( tmp_path, slot ):
    """
    🔴 THE ARM THAT STOPS THIS FIX REOPENING THE ROW IT CLOSES.

    The original harm was an 88-minute-stale record seeding a successor with finished
    work. A fallback that skipped the freshness window would restore exactly that, and
    it would look like a passing test suite — the io arm above would still be green. So
    staleness is asserted at BOTH slots: 88 minutes, the measured figure from the row.
    """
    pointer = _write_pair( tmp_path, slot, written_at=_dt( 21 ) - datetime.timedelta( minutes=88 ) )
    ok, reason = _verify( tmp_path, pointer )
    assert not ok
    assert "stale" in reason


@pytest.mark.parametrize( "slot", [ SLOT_ROOT, SLOT_IO ] )
def test_another_sessions_memento_is_refused_at_either_slot( tmp_path, slot ):
    """
    Ensures: the session-identity gate holds at the fallback slot too.

    A persona outlives its sessions, so a pointer can resolve to an EARLIER session of
    the same persona. That is the catch `8068c65e` documented, and widening the search
    must not widen whose memento counts.
    """
    _write_pair( tmp_path, slot, written_at=_dt( 20 ), sid="otherxyz" )
    # The pointer for THIS persona exists, but the record beside it names another session.
    pointer = str( slot_pointer_path( str( tmp_path ), PERSONA, slot ) )
    ok, reason = _verify( tmp_path, pointer )
    assert not ok


def test_a_total_miss_reports_the_root_reason_because_it_is_the_actionable_one( tmp_path ):
    """
    Ensures: with nothing at either slot, the refusal is the PRIMARY's.

    Mirrors the reap, which reports its io primary on a total miss. The root reason is
    the one worth printing here: it names both acceptable root targets and the
    `memento_io.py` command that writes them, so the seat can act rather than guess.
    """
    stray = tmp_path / "elsewhere" / "cheech-memento.md"
    stray.parent.mkdir( parents=True )
    stray.write_text( "# not at any slot\n" + "x" * 1400 )
    ok, reason = _verify( tmp_path, str( stray ) )
    assert not ok
    assert f"{SLOT_ROOT!r} slot" in reason
    assert "memento_io.py write" in reason


# ---------------------------------------------------------------------------
# 4. THE SEEDED CONTENT — the row's own instruction, end to end
# ---------------------------------------------------------------------------

def test_the_content_that_reaches_the_gate_is_what_was_written_to_the_io_slot( tmp_path ):
    """
    🔴 ASSERTS THE CONTENT, NOT THE EXISTENCE — the row's explicit instruction.

    *"Write slot 1, re-spin through door 2, assert the successor received what was
    written"*, because a test that only checks for a non-empty file passes on exactly
    the stale record this row is about.

    The io record carries a canary string and the ROOT slot is left EMPTY. The read that
    the gate performs is captured, and the canary must appear in it — proving the bytes
    the door accepted came from the io record, not from a root file that does not exist
    and not from the pointer's own two comment lines.
    """
    pointer = _write_pair( tmp_path, SLOT_IO, written_at=_dt( 20 ) )
    seen    = []

    def _recording_read( path ):
        text = _read_or_none( path )
        seen.append( ( str( path ), text ) )
        return text

    ok, reason = sr._default_verify_slot(
        pointer, repo_root=str( tmp_path ), persona=PERSONA, session_id=SID,
        now=_dt( 21 ), read_text_fn=_recording_read,
    )
    assert ok, reason

    io_record = str( slot_record_path( str( tmp_path ), PERSONA, SID, SLOT_IO ) )
    assert not ( tmp_path / f".claude-memento-{SLUG}.md" ).exists(), (
        "the root slot must be EMPTY for this arm — otherwise a pass proves nothing "
        "about which slot the content came from"
    )
    delivered = [ text for path, text in seen if path == io_record and text ]
    assert delivered, f"the gate never read the io record; it read {[ p for p, _ in seen ]}"
    assert CANARY in delivered[ 0 ]


# ---------------------------------------------------------------------------
# 5. The ordering is a parameter, not a hardcoded direction
# ---------------------------------------------------------------------------

def test_the_primary_is_tried_before_the_fallback( tmp_path ):
    """
    Ensures: when BOTH slots hold a valid memento, the PRIMARY answers.

    Without this, a fallback-first implementation would pass every other arm in this
    file — both slots verify, so every `ok` stays True — while silently making `io` the
    door's primary and inverting a ruling. The discriminator is the reason string: a
    primary hit does not carry the fallback's "found at" clause.
    """
    _write_pair( tmp_path, SLOT_IO, written_at=_dt( 20 ), canary="IO-COPY" )
    pointer = _write_pair( tmp_path, SLOT_ROOT, written_at=_dt( 20 ), canary="ROOT-COPY" )
    ok, reason = _verify( tmp_path, pointer )
    assert ok
    assert "found at the" not in reason, (
        "a root-slot memento was reported as a fallback hit — the primary/fallback "
        "order is inverted"
    )


def test_the_slot_order_is_injectable_so_the_reaps_direction_is_expressible( tmp_path ):
    """
    Ensures: the same function serves the opposite direction, io-primary.

    Not speculative generality — it is the proof that the ordering is a PARAMETER rather
    than this door's hardcoded opinion, which is what lets one implementation serve both
    doors instead of two that drift.
    """
    pointer = _write_pair( tmp_path, SLOT_IO, written_at=_dt( 20 ) )
    ok, reason = verify_memento_at_any_readable_slot(
        pointer, repo_root=str( tmp_path ), persona=PERSONA, session_id=SID,
        now=_dt( 21 ), read_text_fn=_read_or_none,
        primary_slot=SLOT_IO, fallback_slot=SLOT_ROOT,
    )
    assert ok
    assert "found at the" not in reason   # io IS the primary here, so no fallback clause


def test_the_verifier_is_injectable( tmp_path ):
    """Ensures: the per-slot verifier is a seam, so the ordering is unit-provable alone."""
    calls = []

    def fake( path, **kw ):
        calls.append( kw[ "slot" ] )
        return ( kw[ "slot" ] == SLOT_IO ), f"fake for {kw[ 'slot' ]}"

    ok, reason = verify_memento_at_any_readable_slot(
        "/irrelevant", repo_root=str( tmp_path ), persona=PERSONA, session_id=SID,
        now=_dt( 21 ), read_text_fn=lambda p: None, verify_at_slot_fn=fake,
    )
    assert calls == [ SLOT_ROOT, SLOT_IO ]   # primary first, then fallback
    assert ok
    assert "fake for io" in reason
