#!/usr/bin/env python3
"""
ADVERSARIAL regression suite for the hold janitor — Rio ⚡ (session 912fb683),
adversarial seat on the heartbeat-hold fix. Manager: Mr. Radio 🦉.

WRITTEN BEFORE THE IMPLEMENTERS' DIFF EXISTED (working tree clean at authoring
time). These tests encode invariants derived from EXECUTING the real, unmodified
janitor against copies of the live 45-file corpus — not from reading it.

Two invariants here are RED against current `main` and are marked
`xfail(strict=True)`. Strict is deliberate: the moment the fix lands they XPASS,
which pytest reports as a FAILURE, forcing whoever fixed it to delete the marker
consciously. A regression test that silently starts passing is a test nobody
reads twice.

WHY THESE EXIST — the frame every prior round inherited is wrong:
    The review binned the corpus as "22 absent-ttl files = the mementos = at risk
    from the proposed mtime fallback (A2)". But CARGO and TTL-PRESENCE are
    ORTHOGONAL. Executed against copies of the real corpus, the CURRENT janitor —
    no A2, no mtime fallback, unmodified — destroys 10 MORE hand-written mementos
    that happen to carry a numeric ttl_seconds, the instant it is handed roots.
    Deletion does not wait for A2. The delete path is live TODAY at
    heartbeat_hold.py:495, reached from fleet_arbiter_loop.py:502.

NO FIXED CENSUS COUNTS APPEAR IN THIS FILE. The corpus is LIVE — it measured 41,
then 43, then 45 across three reviewers and moved twice DURING review. Any test
asserting a fixed census is a flake by construction.
"""
import json
import datetime
import os

import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hh


UTC        = datetime.timezone.utc
_PRUNE_NOW = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=UTC )

# The conservative threshold the janitor applies with no authoritative live-set.
# DERIVED from the module, never hardcoded — if the module retunes its grace,
# these tests retune with it instead of silently testing the wrong boundary.
_CONSERVATIVE = hh.DEFAULT_TTL_SECONDS + hh.DEFAULT_PRUNE_GRACE_SECONDS


def _write_hold_file( base, sid, age_seconds, ttl=900, **cargo ):
    """A hold whose held_at is `age_seconds` before _PRUNE_NOW, plus arbitrary
    non-schema `cargo` keys (the hand-written-memento shape)."""
    held_at = ( _PRUNE_NOW - datetime.timedelta( seconds=age_seconds ) ).isoformat()
    d = { "session_id" : sid, "held_at": held_at, "ttl_seconds": ttl,
          "work_owed"  : True, "reason": "x" }
    d.update( cargo )
    ( base / f".heartbeat-hold-{sid}.json" ).write_text( json.dumps( d ) )
    return base / f".heartbeat-hold-{sid}.json"


def _has_cargo( path ):
    """True iff the file carries a key `write_hold` cannot emit ⇒ hand-written ⇒
    it is a continuity record, not a machine-written hold. This is the CARGO
    discriminator the census never ran: `write_hold` persists EXACTLY
    HOLD_SCHEMA_FIELDS, so any extra key is conclusive proof of hand authorship."""
    d = json.loads( path.read_text() )
    return bool( set( d.keys() ) - set( hh.HOLD_SCHEMA_FIELDS ) )


# ── THE CONTROL THAT LICENSES EVERY OTHER ASSERTION IN THIS FILE ─────────────
# A survival assertion is worthless until the instrument is proven able to kill.
# This test must pass for the xfails below to mean anything: it establishes that
# `prune_stale_hold_files`, pointed at this dir, DOES delete and DOES decline.

def test_control_instrument_can_both_delete_and_decline( tmp_path ):
    """NEGATIVE + POSITIVE control pair, in one run, against the real function.

    Without this, a `pruned == []` anywhere below would be indistinguishable from
    "the janitor was pointed at the wrong directory" — a null that confirms a
    suspicion sails through the checkpoint a contradicting one never would.
    """
    doomed   = _write_hold_file( tmp_path, "positive-control-ancient", age_seconds=_CONSERVATIVE + 100 )
    survivor = _write_hold_file( tmp_path, "negative-control-fresh",   age_seconds=0 )

    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )

    # POSITIVE control — the instrument can kill. Assert this FIRST.
    assert not doomed.exists(),  "instrument is BROKEN: it cannot delete → every survival below is meaningless"
    assert str( doomed ) in pruned
    # NEGATIVE control — and it correctly declines to.
    assert survivor.exists(),    "janitor reaped a fresh hold — a live session just lost its defence"


def test_control_null_ttl_hold_survives_beside_a_reaped_one( tmp_path ):
    """The mandated negative control: a fresh-mtime null-TTL hold must SURVIVE,
    asserted BESIDE the proof that an ancient well-formed one is reaped in the
    same sweep. Run together so the survival is earned, not assumed."""
    null_ttl = tmp_path / ".heartbeat-hold-null-ttl.json"
    null_ttl.write_text( json.dumps( {
        "session_id" : "null-ttl", "persona": "Rio ⚡",
        "held_at"    : _PRUNE_NOW.isoformat(), "ttl_seconds": None, "reason": "fresh, null ttl",
    } ) )
    doomed = _write_hold_file( tmp_path, "ancient-wellformed", age_seconds=_CONSERVATIVE + 100 )

    hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )

    assert not doomed.exists(), "instrument broken — cannot delete; the survival below proves nothing"
    assert null_ttl.exists(),   "null-TTL hold reaped: 'can't prove age → KEEP' (:488) regressed"


# ── P0 #1 — CARGO PRESERVATION (GREEN since 2026-07-26 — the guard landed) ───
#
# THE MARKER FIRED, AND IT IS DELETED CONSCIOUSLY, WHICH IS WHAT STRICT WAS FOR.
# `xfail(strict=True)` reported XPASS-as-FAILURE the moment precondition 1 of
# `11461241` landed — `classify_hold_file( allow_cargo_deletion=False )` as the
# structural DEFAULT, cargo_bearing ⇒ VERDICT_KEEP at the prunable decision
# (heartbeat_hold.py). Removing the marker is the acknowledgement the strict flag
# was designed to extract; the test itself is unchanged and now guards the fix.
#
# The marker's own words, preserved because they are the receipt: "the CURRENT
# janitor deletes hand-written mementos that carry a numeric ttl. Executed against
# copies of the live corpus, roots-alone destroys 10 real cargo-bearing files
# (the_nights_finding, why_lupin_is_held, board_state, harvest_state, ...), 7 of
# them the design author's own. Deletion does NOT wait for A2."
#
# ⚠️ THE SECOND MARKER BELOW IS STILL ARMED AND MUST STAY ARMED. Two-anchor
# (held_at vs mtime) is a DIFFERENT defect and this fix does not touch it. A seat
# who deletes both because "the milestone landed" removes a live gate.
def test_janitor_never_deletes_a_file_carrying_non_schema_cargo( tmp_path ):
    """THE INVARIANT THIS MILESTONE IS ABOUT.

    A file carrying a key `write_hold` cannot emit was written BY HAND, by an
    agent, as a continuity record. It is irreplaceable. Age is not licence to
    delete it — an ancient memento is not cruft, it is an old memento.

    Note the ages: these span the real corpus's actual span (68h–556h by held_at),
    all far past the 6.25h conservative threshold. The doc's motivating anecdote is
    Sam destroying two irreplaceable records by hand; this is the same act by cron.
    """
    precious = [
        _write_hold_file( tmp_path, "memento-a", age_seconds=_CONSERVATIVE * 12,
                          note_to_my_successor="the thing that must outlive me" ),
        _write_hold_file( tmp_path, "memento-b", age_seconds=_CONSERVATIVE * 60,
                          the_nights_finding="the worst finding is mine", board_state="open" ),
        _write_hold_file( tmp_path, "memento-c", age_seconds=_CONSERVATIVE * 90,
                          harvest_state="pending", role="manager" ),
    ]
    ordinary = _write_hold_file( tmp_path, "ordinary-husk", age_seconds=_CONSERVATIVE * 12 )

    hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )

    # The husk SHOULD go — proves the sweep ran and is not vacuously passing.
    assert not ordinary.exists(), "sweep did not run: this test would pass vacuously"
    for p in precious:
        assert _has_cargo( p ) or not p.exists()   # guard the guard
        assert p.exists(), f"IRREPLACEABLE CARGO DESTROYED: {p.name} — {sorted( set( json.loads( p.read_text() ).keys() ) - set( hh.HOLD_SCHEMA_FIELDS ) ) if p.exists() else 'gone'}"


# ── P0 #2 — TWO ANCHORS, ONE ARTIFACT (RED on main) ──────────────────────────

@pytest.mark.xfail( strict=True, reason=(
    "P0/Rio: the janitor ages on held_at (:486/:493) while is_fresh ages on the FILE "
    "MTIME (:539). B1 exists BECAUSE agents stamp a stale held_at from a past receipt. "
    "So a LIVE session that refreshes its hold reads HONORED to the hook and PRUNABLE "
    "to the janitor. Executed: is_honored=True while the real janitor deleted the file. "
    "The janitor's docstring claims it 'only ever deletes a hold it can PROVE is "
    "ancient' — it proves it with the one field its own module documents as a liar." ) )
def test_janitor_never_reaps_a_hold_the_hook_considers_honored( tmp_path ):
    """B1's OWN documented scenario, replayed against the janitor.

    heartbeat_hold.py's B1 comment: "Agents have no reliable wall-clock, so
    `held_at` (anchored to a stale past receipt) can make a JUST-WRITTEN hold read
    stale". That is not a hypothetical — it is the stated reason mtime-anchoring
    was built. A live session in exactly that state loses its hold to the janitor
    and is then poked forever: the precise ping-storm the design forbids.
    """
    stale_receipt = ( _PRUNE_NOW - datetime.timedelta( hours=8 ) ).isoformat()
    path = tmp_path / ".heartbeat-hold-live-refresher.json"
    path.write_text( json.dumps( {
        "session_id" : "live-refresher", "persona": "Rio ⚡", "held_at": stale_receipt,
        "ttl_seconds": 900, "work_owed": True, "reason": "alive; just refreshed this file",
    } ) )
    # The agent JUST wrote it — host-real mtime is now. This is host truth and,
    # per B1, the thing that "cannot lie" about when the hold was refreshed.
    now_epoch = _PRUNE_NOW.timestamp()
    os.utime( path, ( now_epoch, now_epoch ) )

    hold = hh.read_hold( "live-refresher", base_dir=tmp_path )
    assert hh.is_honored( hold, now=_PRUNE_NOW ), "precondition: the hook must consider this hold honored"

    hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )

    assert path.exists(), (
        "the janitor deleted a hold the hook considers HONORED — two anchors on one "
        "artifact: hook says 'alive, do not poke', janitor says 'ancient, delete'" )


def test_live_session_ids_is_the_belt_that_closes_the_two_anchor_gap( tmp_path ):
    """PASSES today — and that is the point: the fix already exists in the library
    and the ONLY production call site (fleet_arbiter_loop.py:502) does not pass it.

    This is why spec item 1's two halves must land TOGETHER: `roots` widens the
    blast radius, `live_session_ids` is the belt that contains it. Shipping roots
    without the live-set ships the blast radius with the belt unbuckled."""
    stale_receipt = ( _PRUNE_NOW - datetime.timedelta( hours=8 ) ).isoformat()
    path = tmp_path / ".heartbeat-hold-live-refresher.json"
    path.write_text( json.dumps( {
        "session_id" : "live-refresher", "persona": "Rio ⚡", "held_at": stale_receipt,
        "ttl_seconds": 900, "work_owed": True, "reason": "alive; just refreshed",
    } ) )

    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW,
                                        live_session_ids=[ "live-refresher" ] )

    assert pruned == [ ]
    assert path.exists(), "the belt itself is broken — live_session_ids no longer protects"


# ── #6 — "SWEPT 0 ROOTS" MUST NOT WEAR THE SAME SILENCE AS "FOUND 0 PRUNABLE" ─

def test_report_swept_zero_roots_is_distinguishable_from_found_zero_prunable( tmp_path ):
    """#6 — two OPPOSITE facts must not share one silence.

    (a) swept a real root, nothing was prunable  → success
    (b) swept NOTHING (bad root list)            → total failure
    Both yield `prunable: 0`. The report is only acceptance evidence if a reader
    can tell them apart WITHOUT already knowing the answer. Measured motivation:
    every `external repo * path` in lupin-app.ini is a CONTAINER path that does not
    exist on the host where the arbiter actually runs — so a registry-derived root
    list reaches zero of the real corpus, and `if pruned:` at :503 logged nothing
    about it. A janitor that does nothing and reports success.
    """
    real_root = tmp_path / "real"; real_root.mkdir()
    _write_hold_file( real_root, "fresh-nothing-to-do", age_seconds=0 )

    swept_real = hh.report_hold_files( base_dirs=[ real_root ], now=_PRUNE_NOW )
    swept_none = hh.report_hold_files( base_dirs=[ tmp_path / "does-not-exist" ], now=_PRUNE_NOW )

    # The lone zero they share — and which therefore proves nothing on its own.
    assert swept_real[ "counts" ][ "prunable" ] == swept_none[ "counts" ][ "prunable" ] == 0

    # ...and the fields that MUST break the tie.
    assert swept_real[ "roots_swept" ] and swept_real[ "files_found" ] > 0, \
        "a successful sweep must PROVE it reached something"
    assert swept_none[ "roots_swept" ] == [ ], "a failed sweep must not claim it swept a root"
    assert swept_none[ "roots_unreachable" ], \
        "a root that could not be reached must be NAMED, not silently contribute zero"
    assert swept_real[ "roots_swept" ] != swept_none[ "roots_swept" ], \
        "'swept 0 roots' and 'found 0 prunable' are wearing the same silence — #6 regressed"


def test_report_mode_deletes_nothing_measured_not_asserted( tmp_path ):
    """The diff reports `"deleted": 0` as a HARDCODED constant with the comment
    "structural: this path cannot delete". A field that reports a constant cannot
    detect its own violation — it is a guard that cannot fail, the exact archetype
    this milestone exists to kill. So do not read the field: MEASURE the disk.

    Content-hashed before/after, over every class of file the classifier branches
    on, so "deleted nothing" also means "mutated nothing".
    """
    import hashlib

    _write_hold_file( tmp_path, "ancient-husk",  age_seconds=_CONSERVATIVE * 90 )
    _write_hold_file( tmp_path, "ancient-cargo", age_seconds=_CONSERVATIVE * 90,
                      note_to_my_successor="irreplaceable" )
    _write_hold_file( tmp_path, "fresh",         age_seconds=0 )
    ( tmp_path / ".heartbeat-hold-garbage.json" ).write_text( "{not json" )
    ( tmp_path / ".heartbeat-hold-notanobject.json" ).write_text( '"a string"' )

    def snapshot():
        return { p.name: hashlib.sha256( p.read_bytes() ).hexdigest()
                 for p in sorted( tmp_path.glob( hh.HOLD_GLOB ) ) }

    before = snapshot()
    report = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )
    after  = snapshot()

    # Not vacuous: the report must actually have found and condemned something.
    assert report[ "counts" ][ "prunable" ] > 0, "vacuous — report condemned nothing, so 'no delete' is free"
    assert report[ "counts" ][ "cargo_bearing" ] > 0, "vacuous — no cargo in corpus"
    assert after == before, "REPORT MODE TOUCHED THE DISK — files deleted or mutated"


def test_sweep_ignores_ordinary_files_beside_holds_in_swept_and_skipped_dirs( tmp_path ):
    """Closes the last two uncovered branch arcs (571->563, 613->600): the
    `elif fnmatch( entry.name, HOLD_GLOB )` FALSE path — an ordinary file sitting
    in a swept dir, and in a SKIPPED dir that is being probed.

    Not busywork for the 100% gate. The sweep walks real project roots full of
    ordinary files; the arc that decides "this is not a hold, leave it alone" is
    the one standing between the janitor and every other file in the repo. It was
    the only branch in the new sweep with no test.
    """
    root = tmp_path / "root"; root.mkdir()
    _write_hold_file( root, "a-real-hold", age_seconds=0 )
    ( root / "README.md" ).write_text( "not a hold" )
    ( root / ".heartbeat-hold-a-real-hold.json.tmp" ).write_text( "atomic-write artifact" )

    # a SKIPPED dir (probed, not swept) that also contains a non-hold file
    skipped = root / ".claude" / "worktrees" / "wt"
    skipped.mkdir( parents=True )
    _write_hold_file( skipped, "hold-in-worktree", age_seconds=0 )
    ( skipped / "notes.txt" ).write_text( "not a hold either" )

    report = hh.report_hold_files( base_dirs=[ root ], now=_PRUNE_NOW )

    names = [ os.path.basename( r[ "path" ] ) for r in report[ "files" ] ]
    assert names == [ ".heartbeat-hold-a-real-hold.json" ], \
        f"sweep picked up a non-hold file (or the .tmp artifact): {names}"
    # the skipped dir is not swept — but it IS surfaced, holds and all
    assert report[ "skipped_dirs_with_holds" ], "a skip-listed dir holding a hold must be surfaced"
    assert report[ "skipped_dirs_with_holds" ][ 0 ][ "hold_count" ] == 1, \
        "the probe counted a non-hold file as a hold"


def test_pruned_empty_is_ambiguous_today_documenting_why_report_mode_must_be_loud( tmp_path ):
    """Not a bug in the library — a REQUIREMENT on the report mode being built.

    Both of these return the identical `[]`:
      (a) a sweep that reached a real dir and correctly found nothing prunable
      (b) a sweep that reached a NONEXISTENT dir and saw no files at all
    fleet_arbiter_loop.py:503 then does `if pruned:` — logging NOTHING for either.
    So the "first tick = report only" acceptance evidence for a TOTAL FAILURE is an
    empty log, byte-identical to success. That is a check that cannot fail.

    Report mode MUST emit roots_swept + files_seen UNCONDITIONALLY so these two
    opposite facts stop sharing a silence.
    """
    _write_hold_file( tmp_path, "fresh-nothing-to-do", age_seconds=0 )
    reached_real_dir_found_nothing = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )
    reached_nothing_at_all         = hh.prune_stale_hold_files( base_dir=tmp_path / "does-not-exist",
                                                                now=_PRUNE_NOW )
    assert reached_real_dir_found_nothing == reached_nothing_at_all == [ ]
