"""
Regression pin for row 779bd08f — a post-ask reason CARRIES ITS PRE-ASK HISTORY,
and the last sentence of the field is therefore the OLDEST fact in it.

THE INCIDENT THIS PINS. On 2026-08-29 a reap reported, for one seat:

    memento_alarm: ... (Rio): unparseable_present
    reason: memento header session_id (ea46bc1a) != seat (00ee9fa9) — a prior
            holder's memento in this slot

Two experienced readers took that as a contradiction — the status says "cannot
parse a header", the reason says "parsed a header naming somebody else" — and
opened a row on the theory that the reap had a second defect resolving slots.
It does not. Both fields were correct and they describe DIFFERENT MOMENTS:

  · `unparseable_present` is the POST-ask verdict, on the header-less file the
    seat wrote in RESPONSE to being asked.
  · the ea46bc1a sentence is the PRE-ask verdict, from before the seat wrote
    anything, when the slot still held the previous holder's memento — and it
    survives inside the post-ask reason behind an `at ask time:` marker.

The sentence was quoted without that marker, which is the whole misreading.

WHY THIS IS WORTH A TEST RATHER THAN A COMMENT. The carry-forward is deliberate
and useful — it is how a manager learns what the slot looked like before the ask
— but nothing asserted it, so a refactor could drop the suffix and no test would
notice. The failure would be silent and would only surface as a manager missing
context during a reap, which is exactly when nobody is reading carefully.

Every seam (clock, file read, DM, sleep) is injected — no live server. The disk
MUTATES inside `sleep_fn`, which is how the seat's mid-reap write is modelled:
that is the real sequence, not a contrived one.
"""

import datetime

from lupin_mcp import reap_memento


_NOW  = datetime.datetime( 2026, 8, 29, 22, 30, 0, tzinfo=datetime.timezone.utc )
_REPO = "/repos/lupin"

# The real ids from the incident, kept so the test reads as the receipt it is.
_SEAT_SID  = "00ee9fa9aaaa"   # Rio's live seat, being reaped
_PRIOR_SID = "ea46bc1abbbb"   # the previous Rio seat, whose memento sat in the slot

_SLOT = f"{_REPO}/io/mementos/rio.md"


def _now_fn():
    return _NOW


def _prior_holder_record():
    """A complete, parseable memento — belonging to the PREVIOUS seat."""
    header = ( f"<!-- memento-record: persona=rio session_id={_PRIOR_SID[ :8 ]} "
               f"written_at=2026-08-26T22:06:34-04:00 slot=io -->\n" )
    return header + ( "x" * 1200 )


def _hand_written_record():
    """
    What the seat actually wrote when asked: a human heading, no machine header.
    This is the shape 9 of 13 canonical slots carry today (see row 48b5f19e).
    """
    return "# Memento — Rio, session 00ee9fa9\n" + ( "x" * 1200 )


class _MutatingDisk:
    """
    Reads the prior holder's file until `swap()` is called, then the seat's own
    hand-written one — modelling the seat writing its memento mid-reap, in
    response to the ask.
    """
    def __init__( self ):
        self.files   = { _SLOT: _prior_holder_record() }
        self.swapped = False

    def swap( self ):
        self.files[ _SLOT ] = _hand_written_record()
        self.swapped = True

    def read( self, path ):
        return self.files.get( str( path ) )


def _ident():
    return { "persona": { "name": "Rio" }, "session_id": _SEAT_SID, "cwd": _REPO }


def _coord( disk ):
    # The seat writes DURING the ask window; sleep_fn is that window's seam.
    def _sleep( _seconds ):
        disk.swap()
    return reap_memento.coordinate_mementos(
        { "cc-author-mr-radio-2": _ident() }, write_memento=True,
        now_fn=_now_fn, read_text_fn=disk.read,
        dm_fn=lambda persona, session_id, body: { "status": "sent" },
        sleep_fn=_sleep )


def test_the_post_ask_reason_still_carries_the_pre_ask_verdict():
    """
    THE PIN. The seat's slot held a PRIOR HOLDER's memento at ask time and a
    header-less one after. The final verdict must be the POST-ask status, and
    its reason must still contain the PRE-ask finding — naming the prior
    session — behind the `at ask time:` marker.
    """
    disk = _MutatingDisk()
    out  = _coord( disk )[ "cc-author-mr-radio-2" ]

    assert disk.swapped, "the mid-reap write never happened; the test proves nothing"

    # POST-ask status, from the header-less file the seat just wrote.
    assert out[ "status" ] == "unparseable_present"

    # PRE-ask history, preserved in the tail. This is the exact pairing that read
    # as a contradiction in the incident and is in fact correct.
    assert "at ask time:" in out[ "reason" ]
    assert _PRIOR_SID[ :8 ] in out[ "reason" ]


def test_the_pre_ask_half_is_marked_as_history_not_as_the_verdict():
    """
    THE ANTI-MISREAD GUARD, and the direction that actually failed in the field.
    The prior-session id must appear ONLY behind the `at ask time:` marker — never
    ahead of it, where it would read as the current finding. If a refactor moves
    the carry-forward to the FRONT of the reason, this goes red even though the
    previous test would still pass.
    """
    reason = _coord( _MutatingDisk() )[ "cc-author-mr-radio-2" ][ "reason" ]

    head, marker, tail = reason.partition( "at ask time:" )
    assert marker, "the historical half lost its marker — it now reads as the verdict"
    assert _PRIOR_SID[ :8 ] in tail
    assert _PRIOR_SID[ :8 ] not in head


def test_a_clean_pre_ask_slot_leaves_no_prior_session_anywhere_in_the_reason():
    """
    THE NEGATIVE CONTROL. Without a prior holder, no session id but the seat's own
    may appear — so the assertions above are pinning the carry-forward and not
    merely finding a substring that is always present.
    """
    class _EmptyThenHandWritten( _MutatingDisk ):
        def __init__( self ):
            super().__init__()
            self.files = { }          # nothing at the slot at ask time

    disk   = _EmptyThenHandWritten()
    reason = _coord( disk )[ "cc-author-mr-radio-2" ][ "reason" ]

    assert "at ask time:" in reason
    assert _PRIOR_SID[ :8 ] not in reason
