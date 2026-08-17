"""
Unit tests for the MIXED-BATCH memento slot derivation (row 80b930e6).

THE DEFECT UNDER TEST: the reap bound ONE `project_root` for the whole batch
(cosa_voice_mcp.py:2783, `cu.get_project_root()` = LUPIN_ROOT) and
`coordinate_mementos` reused that single root for every seat. The per-seat loop
varied the PERSONA but never the ROOT, so a batch spanning two repos verified
every seat against lupin's `io/mementos/` — reading a stranger's memento for any
non-lupin seat.

WHY THE EXISTING SUITE MISSED IT: test_reap_memento.py passes a synthetic
`project_root="/proj"` and every batch there is single-rooted by construction.
A single-rooted batch cannot express the bug — the mixed case was untested, not
passing.

THE DIVERGENCE THIS FILE PINS: two seats reaped TOGETHER from DIFFERENT repos,
each holding a valid memento in its OWN repo. Against the old code the lupin
seat passes and the planning-is-prompting seat does not — reproducing the
incident's exact shape, where a correct-looking result for the lupin half masks
a wrong-file read for the other. A test that only asserted "the batch failed"
would go green for the wrong reason; these assert WHICH seat and WHICH slot.

Every seam (clock, file read, DM send, sleep) is injected — no live server.
"""

import datetime

import pytest

from lupin_mcp import reap_memento


# ── Fixtures / helpers ────────────────────────────────────────────────────────
_NOW = datetime.datetime( 2026, 8, 14, 15, 5, 0, tzinfo=datetime.timezone.utc )

# The two repos in play. LUPIN_REPO stands in for LUPIN_ROOT — the root the old
# code applied to EVERY seat; PLAN_REPO is the non-lupin residency it ignored.
LUPIN_REPO = "/repos/lupin"
PLAN_REPO  = "/repos/planning-is-prompting"


def _now_fn():
    return _NOW


def _memento( persona, sid8, written_at="2026-08-14T15:00:00+00:00", body_bytes=1200 ):
    """A valid, fresh, complete memento with a line-1 memento-record header."""
    header = ( f"<!-- memento-record: persona={persona} session_id={sid8} "
               f"written_at={written_at} slot=io -->\n" )
    return header + ( "x" * body_bytes )


class _Disk:
    """Injected file store: maps str(path) -> text; missing key reads as None."""
    def __init__( self, files=None ):
        self.files = dict( files or {} )
    def read( self, path ):
        return self.files.get( str( path ) )


class _DM:
    """Records every ask so a wrongly-asked seat is visible, not just a status."""
    def __init__( self ):
        self.calls = []
    def __call__( self, persona, session_id, body ):
        self.calls.append( { "persona": persona, "session_id": session_id, "body": body } )
        return { "status": "sent" }


def _ident( name, sid, cwd ):
    """
    A `_capture_reap_identity`-shaped dict INCLUDING the seat's own cwd — the
    bridge field that is present in 23/23 live bridges and that the capture used
    to drop on the floor.
    """
    return { "persona": { "name": name }, "session_id": sid, "cwd": cwd }


def _slot( repo, persona_slug ):
    return f"{repo}/io/mementos/{persona_slug}.md"


# The mixed batch: one seat per repo, each memento correctly in its OWN repo.
_TIFFANY_SID = "aaaa1111ffff"
_RIO_SID     = "bbbb2222ffff"


def _mixed_identities():
    return {
        "cc-author-tiffany-1": _ident( "Tiffany", _TIFFANY_SID, LUPIN_REPO ),
        "cc-author-rio-1"    : _ident( "Rio",     _RIO_SID,     PLAN_REPO  ),
    }


def _mixed_disk():
    return _Disk( {
        _slot( LUPIN_REPO, "tiffany" ): _memento( "Tiffany", _TIFFANY_SID[ :8 ] ),
        _slot( PLAN_REPO,  "rio"     ): _memento( "Rio",     _RIO_SID[ :8 ]     ),
    } )


def _coord( identities, disk, dm, **kw ):
    """
    NO root is passed. `coordinate_mementos` no longer accepts one (Tiberius
    review): a batch-wide root left in the signature is a root something will
    eventually fall back to, and the ruling is REFUSE. Each seat's slot comes
    from its own identity `cwd`.
    """
    return reap_memento.coordinate_mementos(
        identities, write_memento=True,
        now_fn=_now_fn, read_text_fn=disk.read, dm_fn=dm,
        sleep_fn=lambda _s: None, **kw )


# ── The guard ─────────────────────────────────────────────────────────────────
def test_mixed_batch_verifies_each_seat_against_its_own_repo():
    """
    THE RED, and the whole receipt for row 80b930e6.

    Both seats hold a valid memento in their own repo, so both must verify and
    NEITHER may be asked. Against the pre-fix code the Rio seat is looked up at
    LUPIN's slot, finds nothing, gets DM'd and lands non-verified — while the
    Tiffany seat passes, which is precisely why the bug survived in production.
    """
    dm  = _DM()
    out = _coord( _mixed_identities(), _mixed_disk(), dm )

    # The lupin-resident seat was never the broken half — assert it explicitly so
    # a future regression that breaks BOTH cannot masquerade as this one passing.
    assert out[ "cc-author-tiffany-1" ][ "status" ] == "verified"

    # The divergence. This is the assertion that fails before the fix.
    assert out[ "cc-author-rio-1" ][ "status" ] == "verified", (
        "non-lupin seat was not verified against its own repo — "
        f"slot actually consulted: {out[ 'cc-author-rio-1' ].get( 'slot' )}" )

    # WHICH file was read matters as much as the verdict: a seat verified off the
    # wrong repo's file would still read 'verified' and still be the bug.
    assert out[ "cc-author-rio-1" ][ "slot" ] == _slot( PLAN_REPO, "rio" )
    assert out[ "cc-author-tiffany-1" ][ "slot" ] == _slot( LUPIN_REPO, "tiffany" )

    # A seat with a provable memento must never be disturbed.
    assert dm.calls == []


def test_mixed_batch_does_not_read_a_stranger_memento_at_the_shared_slot():
    """
    The incident itself: lupin's `io/mementos/rio.md` holds a DIFFERENT Rio's
    live memento. The non-lupin Rio must be verified from its own repo and must
    NOT be judged against the stranger's file — the outcome that produced the
    original `unparseable_present` on a seat whose memento was fine.
    """
    stranger_sid8 = "60708b11"                  # this morning's lupin-resident Rio
    disk = _mixed_disk()
    disk.files[ _slot( LUPIN_REPO, "rio" ) ] = _memento( "Rio", stranger_sid8 )

    dm  = _DM()
    out = _coord( _mixed_identities(), disk, dm )

    rio = out[ "cc-author-rio-1" ]
    assert rio[ "status" ] == "verified"
    assert rio[ "slot" ]   == _slot( PLAN_REPO, "rio" )
    assert stranger_sid8 not in str( rio.get( "reason", "" ) )
    assert dm.calls == []


def test_seat_without_cwd_refuses_to_guess_a_repo():
    """
    A bridge with no `cwd` is an anomaly (23/23 live bridges carry one), and the
    reap must not silently fall back to guessing lupin — that guess IS the bug.
    It gets its own status so a manager can tell "I looked in the wrong repo"
    from "the file is corrupt"; folding it into `skipped` would merge those two
    again.
    """
    dm  = _DM()
    out = _coord(
        { "cc-author-ghost-1": { "persona": { "name": "Rio" }, "session_id": _RIO_SID } },
        _mixed_disk(), dm )

    ghost = out[ "cc-author-ghost-1" ]
    assert ghost[ "status" ] == "skipped_no_cwd"
    assert "cwd" in ghost[ "reason" ]
    assert dm.calls == []                       # nothing to ask — no repo to ask about
