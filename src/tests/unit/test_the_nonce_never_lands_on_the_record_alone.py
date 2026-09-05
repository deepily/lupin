"""
The guard for row c9f4d613: a self-respin nonce must never reach a memento's RECORD
without reaching its MIRROR in the same breath.

WHAT BROKE. `memento_io.py write` lands three copies — record, mirror, pointer — and
sha-verifies record against mirror before it exits. It is airtight. Then lupin's
`self_respin_core.stamp_nonce_into` appended this cycle's nonce line to ONE path, the
record, from a different module in a different repo, with no knowledge that a mirror
exists. The mirror was correct at write time and stale one call later, and nothing
re-verified. Measured 2026-09-04 on two personas, 92 bytes apiece — the blank line plus
the nonce line, which is fixed-length:

    pocholo   record a88997c97931 / 11,080 B      mirror 2ee72c2ccc00 / 10,988 B
    tiberius  record 6cc26efa9953 /  8,425 B      mirror 33f2e9b63609 /  8,333 B

WHY IT MATTERS MORE THAN A DRIFTED COPY. The mirror exists precisely to survive
`git clean` and a pruned worktree, and a restore is a copy back. The one line it was
missing is the one `verify_memento_content` gates on — so the durable copy was unusable
for the single operation it is most needed for, and the seat that restored from it got
its re-spin refused.

WHY THESE TESTS DO NOT DRIVE memento_io. The defect is entirely lupin-side: the writer
was already correct. Driving the real script would add a cross-repo subprocess to the
unit tier for no extra discrimination. It WAS measured end-to-end by hand the day this
landed — real `write --self-respin-nonce` gave header and nonce both at 21:45:53 (a zero
gap) with record and mirror sha-equal and both verifying, and real `amend` with the nonce
last in the body gave the same sha-equality on the second cycle, while a second `write`
refused with exit 3 as immutable. Those receipts are on the row; they are not re-run here.

READ THE CONTROLS BEFORE THE ASSERTIONS. `test_the_append_is_what_strands_a_restore`
reproduces the defect BY HAND and is the positive control: without it, a
`stamp_nonce_into` that had simply been deleted would satisfy the headline test too.
"""

import datetime
import hashlib

import pytest

import lupin_mcp.self_respin_core as sr


UTC   = datetime.timezone.utc
NONCE = "5a45f1a8-783b-4ff2-9208-17fb1c4a75b7"


def _dt( minute, second=0 ):
    return datetime.datetime( 2026, 9, 4, 21, minute, second, tzinfo=UTC )


# A body comfortably over MIN_MEMENTO_SUBSTANCE_BYTES. A fixture under the floor makes
# every arm return the same "nonce-only or near-empty" refusal, and three different
# outcomes then print as one — the blind instrument that nearly mis-reported this fix.
_BODY = ( "board state: row c9f4d613 in progress, accountable manager mr radio, "
          "venue :8000 idle, next act is the mirror-divergence guard.\n" ) * 12


def _sha( text ):
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def _pre_stamped( ts ):
    """The shape `memento_io.cmd_write --self-respin-nonce` produces: the nonce is part
    of the body, so record and mirror are written from ONE string and cannot differ."""
    return f"# memento\n{_BODY}\n{sr.build_nonce_line( NONCE, ts )}\n"


def _two_copies( text, tmp_path ):
    """record + mirror as cmd_write leaves them — byte-identical, in different trees."""
    record = tmp_path / "seat_root" / ".claude-memento-probe-0f26434c.md"
    mirror = tmp_path / "mirror_home" / ".claude-memento-probe-0f26434c.md"
    for p in ( record, mirror ):
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( text, encoding="utf-8" )
    return record, mirror


# ---------------------------------------------------------------------------
# THE HEADLINE. Unwire the retirement — restore the append — and this reddens.
# ---------------------------------------------------------------------------
def test_a_stamp_attempt_leaves_the_record_and_its_mirror_byte_identical( tmp_path ):
    record, mirror = _two_copies( f"# memento\n{_BODY}", tmp_path )
    before = _sha( record.read_text( encoding="utf-8" ) )
    assert before == _sha( mirror.read_text( encoding="utf-8" ) ), "fixture is not two equal copies"

    with pytest.raises( ValueError, match="RETIRED" ):
        sr.stamp_nonce_into( str( record ), NONCE, _dt( 11, 37 ) )

    after_record = _sha( record.read_text( encoding="utf-8" ) )
    after_mirror = _sha( mirror.read_text( encoding="utf-8" ) )
    assert after_record == after_mirror, "the record moved and the mirror did not — the c9f4d613 defect"
    assert after_record == before, "nothing should have been written at all"


# ---------------------------------------------------------------------------
# THE POSITIVE CONTROL. This is the defect, applied by hand, so the headline test
# above is known to be asserting something a broken implementation would fail.
# ---------------------------------------------------------------------------
def test_the_append_is_what_strands_a_restore( tmp_path ):
    record, mirror = _two_copies( f"# memento\n{_BODY}", tmp_path )

    # exactly what the retired function did: append to ONE path.
    line = sr.build_nonce_line( NONCE, _dt( 11, 37 ) )
    record.write_text( record.read_text( encoding="utf-8" ).rstrip( "\n" ) + "\n\n" + line + "\n",
                       encoding="utf-8" )

    assert _sha( record.read_text( encoding="utf-8" ) ) != _sha( mirror.read_text( encoding="utf-8" ) )

    now = _dt( 12, 0 )
    ok_record, _        = sr.verify_memento_content( record.read_text( encoding="utf-8" ), NONCE, now )
    ok_mirror, why_not  = sr.verify_memento_content( mirror.read_text( encoding="utf-8" ), NONCE, now )

    assert ok_record is True,  "the record is fine — which is why nobody noticed"
    assert ok_mirror is False, "if the mirror verified, this test could not see the defect at all"
    assert "not found" in why_not          # and the seat is told it looks like a partial write


def test_the_drift_is_exactly_the_blank_line_and_the_nonce_line( tmp_path ):
    """
    Pins the measured 92 bytes to its mechanism, so the figure is derived rather than quoted.

    ⚠️ AND IT PINS A DEPENDENCY THE ROW GOT SLIGHTLY WRONG. The row says the two personas
    drifted equally "because that line is fixed-length". It is not fixed-length — it is
    fixed-length GIVEN MICROSECONDS, because `datetime.isoformat()` omits them when they
    are zero, which costs 7 characters. The real producer stamps `datetime.now()`, so
    microseconds are present ~always and 92 is the figure you see. A fixture built with a
    round timestamp gives 85 and looks like a regression; that is how this test first
    failed, and it is this repo's hand-written-fixture defect in miniature.
    """
    record, mirror = _two_copies( f"# memento\n{_BODY}", tmp_path )
    line = sr.build_nonce_line( NONCE, _dt( 11, 37 ).replace( microsecond=920494 ) )
    record.write_text( record.read_text( encoding="utf-8" ).rstrip( "\n" ) + "\n\n" + line + "\n",
                       encoding="utf-8" )

    delta = len( record.read_bytes() ) - len( mirror.read_bytes() )
    assert delta == len( ( "\n" + line + "\n" ).encode( "utf-8" ) )
    assert delta == 92, "the observed pocholo/tiberius delta — a change here means the line format moved"
    assert len( sr.build_nonce_line( NONCE, _dt( 11, 37 ) ).encode( "utf-8" ) ) == 83   # the microsecond-less case, named not hidden


# ---------------------------------------------------------------------------
# THE FIX'S OWN PROPERTY: pre-stamping is verifiable from EITHER copy.
# ---------------------------------------------------------------------------
def test_a_pre_stamped_memento_verifies_from_the_mirror_as_well_as_the_record( tmp_path ):
    record, mirror = _two_copies( _pre_stamped( _dt( 11, 23 ) ), tmp_path )
    now = _dt( 12, 0 )

    assert _sha( record.read_text( encoding="utf-8" ) ) == _sha( mirror.read_text( encoding="utf-8" ) )
    for copy in ( record, mirror ):
        ok, reason = sr.verify_memento_content( copy.read_text( encoding="utf-8" ), NONCE, now )
        assert ok is True, f"{copy.name}: {reason}"


def test_pre_stamping_still_refuses_a_stale_nonce_from_either_copy( tmp_path ):
    """The point of the fix is not that both copies pass — it is that both copies give the
    SAME verdict. A guard that only ever says True is not discriminating."""
    stale = datetime.datetime( 2026, 9, 4, 18, 0, 0, tzinfo=UTC )      # ~3h before `now`
    record, mirror = _two_copies( _pre_stamped( stale ), tmp_path )
    now = _dt( 12, 0 )

    for copy in ( record, mirror ):
        ok, reason = sr.verify_memento_content( copy.read_text( encoding="utf-8" ), NONCE, now )
        assert ok is False
        assert "stale" in reason
