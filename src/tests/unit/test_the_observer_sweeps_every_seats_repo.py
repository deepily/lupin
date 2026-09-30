"""
The self-re-spin observer must find EVERY seat's marker, not only the seats that
happen to share its own LUPIN_ROOT.

Rick ruled 2026-09-03 (row db56ac6d): a seat's data keys on the seat's OWN repo,
everywhere. So the marker writer moves to the seat's repo (item 3a). This module
is the other half. It cannot be "handed the repo" the way the boot-receipt finder
was, because it takes no seat — it asks about EVERYBODY at once — so the reader
sweeps every repo root under the parent instead. Same shape, same reason, as
`respin_wake_check.find_misplaced_receipts`.

⚠️ WHY EVERY ARM NAMES ITS CASE. Today the marker writer and this reader are BOTH
ambient, so they agree BY ACCIDENT, and nearly every seat on the box is in `lupin`.
A test written from the common case passes identically before and after the fix.
Two arms below are therefore CONTROLS and are supposed to be untouched by the
change: a same-repo seat must land on exactly the root it lands on today, and an
explicit `base_dir` must still mean that one directory and no other.

⚠️ AND THE SIDECARS MOVE WITH THE MARKER. `self_respin_core` writes the marker, the
wake proof and the keys-sent stamp into ONE directory, so a marker found under a
sibling root has its sidecars there too. Every cross-repo arm below plants a DECOY
sidecar under the observer's ambient root: finding the marker but reading its proof
from the ambient root would report every cross-repo seat as unproven, and only a
decoy can tell those two states apart.
"""
import datetime
import json
import os
import types

import pytest

import cosa.agents.heartbeat_arbiter.self_respin_observer as obs


UTC        = datetime.timezone.utc
WAKE_NONCE = "wake-nonce-3b"
SID        = "611e3c47"            # a real cross-repo self-respin: maria, planning-is-prompting
HOME_SID   = "a2715c0f"            # a seat in the observer's own repo


def _dt( minute, second=0 ):
    return datetime.datetime( 2026, 8, 14, 2, minute, second, tzinfo=UTC )


def _marker( sid, persona ):
    """A synthetic on-disk marker. fired_at 02:20, deadline 02:22."""
    return {
        "session_id"         : sid,
        "persona"            : persona,
        "tmux_session"       : f"{sid}-mgr",
        "fired_at"           : _dt( 20 ).isoformat(),
        "expected_return_by" : _dt( 22 ).isoformat(),
        "pre_clear_status"   : "over_budget",
        "pre_clear_pct"      : 51.4,
        "memento_path"       : f"/x/.claude-memento-{persona}.md",
        "memento_verified"   : True,
        "wake_nonce"         : WAKE_NONCE,
    }


def _write_marker( root, sid, persona="maria" ):
    path = root / f"{obs.MARKER_PREFIX}{sid}.json"
    path.write_text( json.dumps( _marker( sid, persona ) ) )
    return path


def _write_proof( root, sid, nonce=WAKE_NONCE ):
    """The consumer's wake proof. Its mtime is NOW, which is after every fired_at
    in these fixtures (2026-08-14), so it always satisfies the freshness rule."""
    path = root / f"{obs.WAKE_PROOF_PREFIX}{sid}.marker"
    path.write_text( f"{obs.WAKE_PROOF_NONCE_LINE} {nonce}\n" )
    return path


def _write_keys_sent( root, sid, *, delay_seconds ):
    """The injector's send stamp. The MTIME is the timestamp, so it is set here
    explicitly to `fired_at + delay_seconds`."""
    path  = root / f"{obs.KEYS_SENT_PREFIX}{sid}.marker"
    path.write_text( "" )
    stamp = ( _dt( 20 ) + datetime.timedelta( seconds=delay_seconds ) ).timestamp()
    os.utime( path, ( stamp, stamp ) )
    return path


def _returned_fetch( sid, persona ):
    """A pressure fetch whose record makes `sid` classify RETURNED."""
    def fake_fetch():
        return { "personas": { persona: {
            "session_id"      : sid,
            "tmux_session"    : f"{sid}-mgr",
            "status"          : "within_budget",
            "last_turn_age_s" : 5.0,
        } } }
    return fake_fetch


@pytest.fixture
def fleet( tmp_path, monkeypatch ):
    """A projects-data parent holding two repo roots, with the observer's AMBIENT
    root being `lupin` — the arrangement measured on the box, where 69 of 69
    markers sat under lupin and 0 under planning-is-prompting."""
    parent  = tmp_path / "projects-data"
    ambient = parent / "lupin"
    sibling = parent / "planning-is-prompting"
    ambient.mkdir( parents=True )
    sibling.mkdir( parents=True )
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh
    monkeypatch.setattr( hh, "fleet_data_root", lambda: ambient )
    return parent, ambient, sibling


# ---------------------------------------------------------------------------
# THE DEFECT — a seat outside the observer's own repo is not late, it is ABSENT
# ---------------------------------------------------------------------------
def test_a_cross_repo_seats_marker_is_found_at_all( fleet ):
    _, _ambient, sibling = fleet
    _write_marker( sibling, SID )
    assert [ m[ "session_id" ] for m in obs.read_markers() ] == [ SID ], \
        "a seat whose repo is not the observer's own is invisible to the sweep"


def test_a_same_repo_seat_still_reads_from_the_very_same_root( fleet ):
    """NEGATIVE CONTROL. Unchanged behaviour for the common case — without it,
    'the sweep widened' is satisfied by code that reads from anywhere at all."""
    _, ambient, _sibling = fleet
    _write_marker( ambient, HOME_SID, persona="cheech" )
    assert [ m[ "session_id" ] for m in obs.read_markers() ] == [ HOME_SID ]


def test_an_explicit_base_dir_still_means_that_one_directory( fleet ):
    """REGRESSION CONTROL. A caller that names a directory means that directory:
    the sweep must not silently widen under every existing explicit caller."""
    _, ambient, sibling = fleet
    _write_marker( ambient, HOME_SID, persona="cheech" )
    _write_marker( sibling, SID )
    got = obs.read_markers( base_dir=str( ambient ) )
    assert [ m[ "session_id" ] for m in got ] == [ HOME_SID ]


@pytest.mark.parametrize( "ambient", [ "/", "/toplevel", "relative-root" ] )
def test_a_root_with_no_usable_parent_never_widens_the_sweep( monkeypatch, ambient ):
    """A sweep must never climb toward the filesystem root. Each of these ambient
    roots has a degenerate parent — absent, itself, or `/` — and each must fall back
    to that one directory."""
    recorded = []
    monkeypatch.setattr( obs, "_resolve_base_dir", lambda base_dir: ambient )
    def fake_glob( pattern ):
        recorded.append( pattern )
        return []
    monkeypatch.setattr( obs, "glob", types.SimpleNamespace( glob=fake_glob ) )
    assert obs.read_markers() == []
    assert recorded == [ os.path.join( os.path.normpath( ambient ),
                                       f"{obs.MARKER_PREFIX}*.json" ) ]


def test_a_marker_parked_below_a_repo_root_is_left_alone( fleet ):
    """🔴 MEASURED REGRESSION ARM, and the reason this sweep is one level deep
    rather than recursive.

    A recursive `**` sweep from the parent — the obvious shape, and the one
    `find_misplaced_receipts` uses — was run against the LIVE tree on 2026-09-03 and
    returned 82 markers where the single-root read returns 71. The extra 11 sit in
    `projects-data/lupin/self-respin-archive-pre-f7c5e349/`, retired markers parked
    OUT of the observer's way on purpose. Reading them would re-classify all 11, and
    the janitor deletes any RETURNED marker past its TTL — so a recursive sweep does
    not merely over-report, it destroys the archive it over-reported."""
    _, ambient, _sibling = fleet
    archive = ambient / "self-respin-archive-pre-f7c5e349"
    archive.mkdir()
    _write_marker( archive, "deadbeef", persona="retired" )
    assert obs.read_markers() == [], \
        "a marker parked below a repo root was resurrected by the sweep"


# ---------------------------------------------------------------------------
# THE SIDECARS — written beside the marker, so they must be READ beside it
# ---------------------------------------------------------------------------
def test_a_cross_repo_markers_wake_proof_is_read_beside_it( fleet ):
    """The decoy is the point. A sweep that finds the marker but keeps reading
    proofs from the ambient root picks up the STRANGER nonce and reports a seat
    that came back as never having proven it."""
    _, ambient, sibling = fleet
    _write_marker( sibling, SID )
    _write_proof( sibling, SID )                        # the real proof, beside its marker
    _write_proof( ambient, SID, nonce="STRANGER" )      # decoy under the observer's own root
    out = obs.observe_fleet_self_respin(
        now=_dt( 23 ), fetch_pressure=_returned_fetch( SID, "maria" ) )
    assert len( out ) == 1
    assert out[ 0 ].verdict == obs.SelfRespinVerdict.RETURNED


def test_a_cross_repo_markers_send_stamp_is_read_beside_it( fleet ):
    """Same decoy, on the other sidecar: send_delay_s is measured from the stamp
    next to the marker, not from a same-named stamp under the ambient root."""
    _, ambient, sibling = fleet
    _write_marker( sibling, SID )
    _write_keys_sent( sibling, SID, delay_seconds=30 )
    _write_keys_sent( ambient, SID, delay_seconds=900 )   # decoy
    samples = obs.collect_respin_samples(
        now=_dt( 23 ), fetch_pressure=_returned_fetch( SID, "maria" ) )
    assert len( samples ) == 1
    assert samples[ 0 ][ "send_delay_s" ] == 30.0


def test_the_janitor_sweeps_a_cross_repo_marker_and_its_sidecars( fleet ):
    """A marker the janitor cannot see is a marker that accumulates forever — and
    its proof and send stamp with it."""
    _, _ambient, sibling = fleet
    marker = _write_marker( sibling, SID )
    proof  = _write_proof( sibling, SID )
    stamp  = _write_keys_sent( sibling, SID, delay_seconds=30 )
    swept  = obs.sweep_returned_markers(
        now=_dt( 40 ), fetch_pressure=_returned_fetch( SID, "maria" ), ttl_seconds=900 )
    assert swept == [ SID ]
    assert not marker.exists()
    assert not proof.exists()
    assert not stamp.exists()


# ---------------------------------------------------------------------------
# THE ONE SEAM THAT DOES **NOT** MOVE — and this arm is why it is deliberate
# ---------------------------------------------------------------------------
def test_the_sample_log_stays_at_the_ambient_root( fleet ):
    """Ratified departure from the work order (Mr. Radio, 2026-09-03). The samples
    JSONL is not a SEAT's data — it is the observer's own fleet-wide instrument log,
    one writer and one reader, no seat. Keying it per-repo would scatter one time
    series across N roots and hand its future readers the very multi-root sweep this
    change exists to remove from the marker path. Markers are read from every root;
    samples are written to one."""
    _, ambient, sibling = fleet
    written = obs.append_respin_samples( [ { "schema_version": 2, "session_id": SID } ] )
    assert written == 1
    assert ( ambient / obs.RESPIN_SAMPLES_FILENAME ).exists()
    assert not ( sibling / obs.RESPIN_SAMPLES_FILENAME ).exists()
