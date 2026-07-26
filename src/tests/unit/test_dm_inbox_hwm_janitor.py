"""
HWM janitor — row 8758d0b1.

THE STANDARD THIS SUITE IS HELD TO
----------------------------------
Every guard is proven by MUTATING IT AWAY and watching the corresponding test go
red. A green suite proves nothing until its assertions have been shown to fail —
and this row exists because the obvious remedy (reuse `classify_hold_file`) is a
janitor that deletes zero files and reports success. "Zero deleted" is the
failure mode, so a test that merely asserts "nothing bad happened" is
indistinguishable from the bug.

Arms 1-5 are María's (plan §7). Arms 6-7 came out of the measurement that
corrected the plan:
  6. the sweep deletes a NON-ZERO count — the no-op is the thing being prevented
  7. a non-hex sid8 classifies without raising — `.dm-inbox-hwm-stable-s.json`
     really exists in the repo root, so the ugly input is a known live value

Arm 8 is María's, from row `2a6759de`: the prefix comparison's over-keep is
currently a HAPPY ACCIDENT of comparing truncations. Mutating it to a full-id
comparison must turn the over-keep test RED — which makes the safety derived
rather than lucky.

⚠️ FIXTURE DISCIPLINE (the eeba4858 lesson): each test picks fixtures where the
guarded and unguarded paths genuinely DIVERGE. A control that passes because the
branch was never evaluated is worse than no control.

Venue: :7999-eligible. tmp_path only, no network, no DB, no container.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src/lupin_cli/claude_code/hooks/lib" ) )

import dm_inbox_hwm_janitor as jan


DAY = 24 * 60 * 60


def _write_hwm( root, sid8, age_days, body=None ):
    """
    Create one HWM file with a REAL mtime that many days in the past.

    Ensures:
        - the file's content matches production shape ({cursor_ts, surfaced_ids,
          seeded}) so no test passes because the fixture was conveniently unlike
          the thing it stands for
        - returns the Path
    """
    path = root / f".dm-inbox-hwm-{sid8}.json"
    path.write_text( json.dumps( body if body is not None else
                                 { "cursor_ts": None, "surfaced_ids": [ ], "seeded": True } ) )
    when = time.time() - ( age_days * DAY )
    os.utime( path, ( when, when ) )
    return path


# ── ARM 1 — the positive control: it CAN delete ───────────────────────────

def test_an_orphaned_ancient_hwm_IS_deleted( tmp_path ):
    """
    Without this arm a sweep that deletes nothing reads as a passing test — which
    is exactly what "extend the hold janitor's glob" would have shipped.
    """
    doomed = _write_hwm( tmp_path, "dead0001", age_days=30 )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "live0001" ] )
    assert pruned == [ str( doomed ) ]
    assert not doomed.exists()


# ── ARM 2 — the live gate, at the SAME age as one that dies ───────────────

def test_a_live_sessions_hwm_survives_at_the_same_age_as_one_that_is_deleted( tmp_path ):
    """
    ONE variable different, opposite outcome. Both files are 30 days old; only
    membership in the live set differs. If the ages differed too, a passing test
    would not tell us WHICH guard did the work.
    """
    live_file = _write_hwm( tmp_path, "live0001", age_days=30 )
    dead_file = _write_hwm( tmp_path, "dead0001", age_days=30 )

    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "live0001" ] )

    assert live_file.exists(),     "a LIVE session's HWM was reaped — cursor reset, DM history re-surfaces"
    assert not dead_file.exists(), "the orphaned file survived, so the age arm never fired"
    assert pruned == [ str( dead_file ) ]


def test_the_live_gate_beats_age_no_matter_how_ancient( tmp_path ):
    """A long-running session can legitimately own a very old HWM."""
    ancient_but_live = _write_hwm( tmp_path, "live0001", age_days=3650 )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "live0001" ] )
    assert ancient_but_live.exists()
    assert pruned == [ ]


# ── ARM 3 — a null live-set deletes NOTHING ───────────────────────────────

def test_a_none_live_set_deletes_nothing_however_ancient( tmp_path ):
    """
    An unavailable live-set must never read as "nothing is alive". This is the
    inversion that would let the janitor reap the fleet it exists to tidy up
    after, so it is asserted on a file that WOULD otherwise be prunable.
    """
    would_die = _write_hwm( tmp_path, "dead0001", age_days=3650 )
    pruned    = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=None )
    assert pruned == [ ]
    assert would_die.exists()

    row = jan.classify_hwm_file( would_die, live_session_ids=None )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_NO_LIVE_SET


def test_an_EMPTY_live_set_is_authoritative_and_does_delete( tmp_path ):
    """
    The discriminator for the test above: empty (`[]`, "I enumerated and found
    none") is NOT the same fact as None ("I could not enumerate"). If both kept
    everything, the None-test would pass for the wrong reason.
    """
    doomed = _write_hwm( tmp_path, "dead0001", age_days=30 )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=[ ] )
    assert pruned == [ str( doomed ) ]


# ── ARM 4 — mutate each guard away, watch the right test go red ───────────

def test_MUTATION_removing_the_live_gate_would_reap_a_live_session( tmp_path, monkeypatch ):
    """
    Proves arm 2's assertion has teeth. With the live gate neutered (the live-set
    normalizer returns an empty set — i.e. "nobody matches"), the live file is
    reaped. If this mutation did NOT change the outcome, arm 2 would be green for
    a reason unrelated to the guard.
    """
    live_file = _write_hwm( tmp_path, "live0001", age_days=30 )

    monkeypatch.setattr( jan, "_live_prefixes", lambda ids: set() )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "live0001" ] )

    assert pruned == [ str( live_file ) ], "mutation changed nothing ⇒ arm 2 was not testing the live gate"
    assert not live_file.exists()


def test_MUTATION_a_zero_grace_window_reaps_a_file_the_real_window_keeps( tmp_path ):
    """
    Proves the AGE arm is load-bearing and not decoration. One file, one run each
    way: the real 7-day window keeps a 1-day-old orphan; a 0-second window reaps
    the same file.
    """
    young = _write_hwm( tmp_path, "dead0001", age_days=1 )

    kept = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=[ ] )
    assert kept == [ ] and young.exists(), "the grace window never fired"

    reaped = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=[ ],
                                             grace_seconds=0 )
    assert reaped == [ str( young ) ], "grace_seconds is ignored ⇒ the age arm is dead code"


def test_MUTATION_a_foreign_family_is_never_touched( tmp_path ):
    """
    The glob must not widen. A hold file and a stray dotfile sit in the same root,
    both ancient, both orphaned — and neither is this janitor's business.
    """
    hold  = tmp_path / ".heartbeat-hold-dead0001-aaaa-bbbb.json"
    hold.write_text( json.dumps( { "session_id": "dead0001", "held_at": "2020-01-01T00:00:00+00:00",
                                   "ttl_seconds": 60 } ) )
    other = tmp_path / ".task-store-map-dead0001.json"
    other.write_text( "{}" )
    for p in ( hold, other ):
        when = time.time() - ( 3650 * DAY )
        os.utime( p, ( when, when ) )

    doomed = _write_hwm( tmp_path, "dead0001", age_days=30 )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=[ ] )

    assert pruned == [ str( doomed ) ]
    assert hold.exists(),  "the HWM janitor reaped a HOLD file — cargo loss risk, wrong family"
    assert other.exists(), "the HWM janitor reaped an unrelated dotfile"


# ── ARM 5 — regeneration after deletion ───────────────────────────────────

def test_a_deleted_hwm_reads_back_as_the_UNSEEDED_empty_state( tmp_path ):
    """
    Regeneration is real — but `seeded` comes back FALSE, and that flag is the
    whole story (see the next test). Written against the real `read_hwm`; the
    first draft of this arm called a `read_state` that does not exist, and a test
    that cannot run proves nothing.
    """
    import dm_inbox_reconcile as rec

    doomed = _write_hwm( tmp_path, "dead0001", age_days=30 )
    jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=[ ] )
    assert not doomed.exists()

    state = rec.read_hwm( "dead0001", base_dir=tmp_path )
    assert state[ "cursor_ts" ]    is None
    assert state[ "surfaced_ids" ] == [ ]
    assert state[ "seeded" ]       is False, "a missing HWM must read as UNSEEDED — the swallow depends on it"


def test_deleting_a_LIVE_sessions_hwm_SWALLOWS_its_pending_dms( tmp_path ):
    """
    🔴 THE ARM THAT CORRECTS THE PLAN. §5 claimed the worst case for a false
    delete is a session RE-SURFACING DMs it already showed — "a duplicate DM, not
    data loss." Measured, it is the exact opposite.

    `surface_dm_inbox:327-328` suppresses context entirely when `seeded` is False,
    because a first-ever activation must not replay a backlog (constraint 4). A
    deleted HWM is indistinguishable from a never-existed one, so a pending DM is
    recorded as already-seen and NEVER surfaced.

    ⇒ The blast radius of reaping a LIVE session's HWM is SILENT DM LOSS — bug
    `59f355e0` re-created. This test exists so nobody re-derives the comfortable
    version of that claim.
    """
    import dm_inbox_reconcile as rec

    sid   = "dead0001-aaaa-bbbb-cccc-dddddddddddd"
    row   = [ { "job_id": "dead0001", "message_id": "m1",
                "created_at": "2026-07-26T10:00:00+00:00",
                "body": "an UNREAD peer DM sitting in the inbox",
                "sender_persona": "maria", "sender_icon": "🌸", "thread_id": "t1" } ]
    fetch = lambda since=None, limit=None: ( True, row, False )

    # BASELINE — with its HWM intact the session DOES see the DM. Without this
    # arm the assertion below would pass even if the fixture never delivered
    # anything, which is the control-that-never-fires failure.
    rec.write_hwm( sid, { "cursor_ts": None, "surfaced_ids": [ ], "seeded": True }, base_dir=tmp_path )
    assert rec.surface_dm_inbox( sid, fetch_fn=fetch, base_dir=tmp_path ), \
        "the fixture never surfaced anything ⇒ this test cannot detect the swallow"

    # Now reap it the way the janitor would, and re-run the same reconcile.
    rec._hwm_path( sid, base_dir=tmp_path ).unlink()
    assert rec.surface_dm_inbox( sid, fetch_fn=fetch, base_dir=tmp_path ) == "", \
        "expected the un-surfaced DM to be SWALLOWED after the HWM was reaped"

    # And it is gone for good — recorded as seen, cursor advanced.
    assert rec.surface_dm_inbox( sid, fetch_fn=fetch, base_dir=tmp_path ) == ""
    assert rec.read_hwm( sid, base_dir=tmp_path )[ "surfaced_ids" ] == [ "m1" ], \
        "the DM was not even recorded — a different failure than the one documented"


# ── ARM 6 — the sweep deletes a NON-ZERO count ────────────────────────────

def test_a_realistic_pile_yields_a_NON_ZERO_delete_count( tmp_path ):
    """
    THE ARM THIS ROW EXISTS FOR. The remedy this replaced (reuse the hold
    classifier) would sweep every file, keep every file, and report a clean green.
    A count that is merely "not an error" cannot tell that apart from working.

    Mirrors the real pile's shape: a majority past the window, a minority inside
    it, one live.
    """
    aged  = [ _write_hwm( tmp_path, f"aged{i:04d}", age_days=20 ) for i in range( 12 ) ]
    young = [ _write_hwm( tmp_path, f"yng{i:05d}",  age_days=2  ) for i in range( 5 ) ]
    live  =   _write_hwm( tmp_path, "live0001", age_days=99 )

    report = jan.report_hwm_files( base_dir=tmp_path, live_session_ids=[ "live0001" ] )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path, live_session_ids=[ "live0001" ] )

    assert len( pruned ) == 12, "the sweep is a no-op — the exact failure this row corrected"
    assert len( pruned ) > 0
    assert report[ "counts" ][ "prunable" ] == len( pruned ), \
        "the dry-run PREDICTION disagrees with the act — evidence has drifted from behavior"
    assert all( not p.exists() for p in aged )
    assert all( p.exists() for p in young )
    assert live.exists()


# ── ARM 7 — the ugly-but-real sid8 ────────────────────────────────────────

def test_a_non_hex_sid8_classifies_without_raising( tmp_path ):
    """
    `.dm-inbox-hwm-stable-s.json` really exists in the repo root. Its writer is
    UNIDENTIFIED (both candidate explanations were tested and refuted, 2026-07-26)
    — so the janitor must handle it as an ordinary value, not an assertion.
    """
    odd = _write_hwm( tmp_path, "stable-s", age_days=30 )
    row = jan.classify_hwm_file( odd, live_session_ids=[ ] )
    assert row[ "sid8" ] == "stable-s"
    assert row[ "verdict" ] == jan.VERDICT_PRUNABLE


def test_a_non_hex_sid8_is_STILL_protected_by_the_live_gate( tmp_path ):
    """A weird sid8 must not lose the live protection an ordinary one gets."""
    odd    = _write_hwm( tmp_path, "stable-s", age_days=30 )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "stable-session-12345" ] )
    assert odd.exists(), "an 8-char prefix match failed ⇒ the gate compared full ids"
    assert pruned == [ ]


# ── ARM 8 — the over-keep must be DERIVED, not lucky (María, row 2a6759de) ─

def test_prefix_truncation_over_matches_which_is_the_SAFE_direction( tmp_path ):
    """
    The truncation is not injective — four literals in this repo collapse to
    `stable-s`, though 0 of the 435 files on disk actually collide today (María's
    measurement: latent, not live). Pins that a collision makes the gate KEEP
    more, never less.
    """
    collide = _write_hwm( tmp_path, "stable-s", age_days=30 )
    # A DIFFERENT session id that happens to share the 8-char prefix.
    pruned  = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "stable-sid-67890" ] )
    assert collide.exists()
    assert pruned == [ ]


def test_MUTATION_a_full_id_comparison_would_reap_a_live_sessions_file( tmp_path, monkeypatch ):
    """
    Makes the over-keep safety DERIVED rather than accidental.

    A future reader may see `sid[:8]` and "tidy" it into a full-id comparison. Do
    that, and every truncated FILENAME stops matching every full id in the live
    set — so the gate silently stops protecting anyone. This mutation is that
    change, and it must turn the test above RED.
    """
    live_file = _write_hwm( tmp_path, "live0001", age_days=30 )

    # The tempting "cleanup": compare full ids instead of 8-char prefixes.
    monkeypatch.setattr( jan, "_live_prefixes", lambda ids: { s for s in ids if isinstance( s, str ) } )
    pruned = jan.sweep_and_reclaim_hwm_files( base_dir=tmp_path,
                                              live_session_ids=[ "live0001-4f7a-7ab8-9911-abcdef012345" ] )

    assert pruned == [ str( live_file ) ], \
        "widening the key changed nothing ⇒ the over-keep test is not actually testing the truncation"
    assert not live_file.exists()


# ── the classifier's own edges ────────────────────────────────────────────

def test_a_future_mtime_is_not_evidence_of_youth_and_keeps( tmp_path ):
    """
    Clock skew / a restored backup / a bad touch. A future mtime means the clock
    is unreadable, not that the file is new — and it must not be trusted in either
    direction.
    """
    weird = _write_hwm( tmp_path, "dead0001", age_days=-30 )     # 30 days in the FUTURE
    row   = jan.classify_hwm_file( weird, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_NO_PROVABLE_AGE


def test_hwm_sid8_returns_None_for_a_foreign_name():
    """A foreign file must not read as a zero-length session id."""
    assert jan.hwm_sid8( "/x/.heartbeat-hold-abc.json" )    is None
    assert jan.hwm_sid8( "/x/.dm-inbox-hwm-.json" )         is None
    assert jan.hwm_sid8( "/x/.dm-inbox-hwm-abcd1234.json" ) == "abcd1234"


def test_report_deletes_nothing( tmp_path ):
    """The dry-run arm must be genuinely dry."""
    doomed = _write_hwm( tmp_path, "dead0001", age_days=30 )
    report = jan.report_hwm_files( base_dir=tmp_path, live_session_ids=[ ] )
    assert report[ "counts" ][ "prunable" ] == 1
    assert report[ "deleted" ] == 0
    assert doomed.exists(), "report_hwm_files deleted a file — it is a dry run by contract"


def test_the_grace_default_is_the_ruled_seven_days():
    """Rick's ruling, pinned so a silent re-tune is a failing test."""
    assert jan.DEFAULT_HWM_GRACE_SECONDS == 7 * 24 * 60 * 60


# ── traversal parameterization must not have disturbed the hold family ────

def test_the_hold_familys_default_traversal_is_unchanged( tmp_path ):
    """
    The glob parameter defaults to HOLD_GLOB, so every pre-existing caller keeps
    its exact behavior. Asserted directly rather than assumed from "the hold tests
    still pass".
    """
    import heartbeat_hold as hh

    hold = tmp_path / ".heartbeat-hold-abc123.json"
    hold.write_text( "{}" )
    hwm  = _write_hwm( tmp_path, "dead0001", age_days=30 )

    _r, _u, paths, _s = hh._iter_hold_paths( base_dir=tmp_path )
    assert paths == [ hold ], "the default traversal changed families — every existing caller is affected"

    _r, _u, paths, _s = hh._iter_hold_paths( base_dir=tmp_path, glob_pat=jan.HWM_GLOB )
    assert paths == [ hwm ]
