"""
Bookmark janitor (ask-answer / task-store-map / heartbeat-acked) — row bd5c27e1.

THE STANDARD THIS SUITE IS HELD TO
----------------------------------
Same as the dm-inbox sibling: every guard is proven by MUTATING IT AWAY and watching
the matching test go red. "Zero deleted" is a real failure mode for a janitor, so a
test that merely asserts "nothing bad happened" is indistinguishable from a no-op.

The arms specific to THIS module, beyond the sibling's:
  * SENTINEL carve-out — `.heartbeat-acked-unknown.json` (empty-id fallback) is KEPT,
    and mutating the sentinel set away makes it prunable. The row's "never reap an
    unparseable name" is derived, not assumed.
  * heartbeat-HOLD is never caught — the acked glob must not widen into the hold
    family, which moves to /tmp elsewhere.
  * FULL-id filenames match the [:8] live prefix — these three carry the whole
    session id (unlike dm-inbox's truncation), and the gate must still recognise a
    live session.

Venue: :7999-eligible. tmp_path only, no network, no DB, no container.
"""
import json
import os
import time

import pytest

# Imported by PACKAGE PATH, exactly as the arbiter imports it in production — a
# sys.path insert + bare import would grade a different import graph than ships.
import lupin_cli.claude_code.hooks.lib.bookmark_janitor as jan


DAY = 24 * 60 * 60

# One representative file per family, parameterized so every arm runs against all three.
FAMILIES = [
    ( jan.FAMILY_ASK_ANSWER,      ".ask-answer-hwm-" ),
    ( jan.FAMILY_TASK_STORE_MAP,  ".task-store-map-" ),
    ( jan.FAMILY_HEARTBEAT_ACKED, ".heartbeat-acked-" ),
]


def _write( root, prefix, sid, age_days, body="{}" ):
    """Create one bookmark file with a REAL mtime `age_days` in the past; return Path."""
    path = root / f"{prefix}{sid}.json"
    path.write_text( body )
    when = time.time() - ( age_days * DAY )
    os.utime( path, ( when, when ) )
    return path


# ── ARM 1 — the positive control: it CAN delete (per family) ──────────────

@pytest.mark.parametrize( "family,prefix", FAMILIES )
def test_an_orphaned_ancient_bookmark_IS_deleted( tmp_path, family, prefix ):
    doomed = _write( tmp_path, prefix, "dead0001-full-session-id", age_days=30 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ "live0001-full-session-id" ], families=[ family ] )
    assert pruned == [ str( doomed ) ]
    assert not doomed.exists()


# ── ARM 2 — the live gate, at the SAME age as one that dies ───────────────

@pytest.mark.parametrize( "family,prefix", FAMILIES )
def test_a_live_sessions_bookmark_survives_at_the_same_age_as_one_deleted( tmp_path, family, prefix ):
    """One variable different, opposite outcome — both 30 days old, only liveness differs."""
    live_file = _write( tmp_path, prefix, "live0001-aaaa-bbbb", age_days=30 )
    dead_file = _write( tmp_path, prefix, "dead0001-aaaa-bbbb", age_days=30 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ "live0001-aaaa-bbbb" ], families=[ family ] )
    assert live_file.exists(),     "a LIVE session's bookmark was reaped"
    assert not dead_file.exists(), "the orphan survived — the age arm never fired"
    assert pruned == [ str( dead_file ) ]


def test_the_live_gate_beats_age_no_matter_how_ancient( tmp_path ):
    ancient_but_live = _write( tmp_path, ".ask-answer-hwm-", "live0001-aaaa", age_days=3650 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ "live0001-aaaa" ], families=[ jan.FAMILY_ASK_ANSWER ] )
    assert ancient_but_live.exists()
    assert pruned == [ ]


def test_a_FULL_id_filename_matches_an_8char_live_prefix( tmp_path ):
    """
    These families carry the WHOLE session id in the name; the live set does too.
    The gate compares [:8] prefixes, so a full id must recognise its own live session.
    """
    live_file = _write( tmp_path, ".task-store-map-", "abcd1234-5678-90ab-cdef", age_days=99 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ "abcd1234-5678-90ab-cdef" ], families=[ jan.FAMILY_TASK_STORE_MAP ] )
    assert live_file.exists(), "a full-id filename failed to match its own live session's [:8] prefix"
    assert pruned == [ ]


# ── ARM 3 — a null live-set deletes NOTHING; empty set is authoritative ───

def test_a_none_live_set_deletes_nothing_however_ancient( tmp_path ):
    would_die = _write( tmp_path, ".ask-answer-hwm-", "dead0001-aaaa", age_days=3650 )
    pruned    = jan.sweep_and_reclaim_bookmark_files( base_dir=tmp_path, live_session_ids=None )
    assert pruned == [ ]
    assert would_die.exists()
    row = jan.classify_bookmark_file( would_die, jan.FAMILY_ASK_ANSWER, live_session_ids=None )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_NO_LIVE_SET


def test_an_EMPTY_live_set_is_authoritative_and_does_delete( tmp_path ):
    """empty ([], 'enumerated, found none') is NOT None ('could not enumerate')."""
    doomed = _write( tmp_path, ".ask-answer-hwm-", "dead0001-aaaa", age_days=30 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ jan.FAMILY_ASK_ANSWER ] )
    assert pruned == [ str( doomed ) ]


# ── ARM 4 — mutate each guard away, watch the right test go red ───────────

def test_MUTATION_removing_the_live_gate_would_reap_a_live_session( tmp_path, monkeypatch ):
    live_file = _write( tmp_path, ".ask-answer-hwm-", "live0001-aaaa", age_days=30 )
    monkeypatch.setattr( jan, "_live_prefixes", lambda ids: set() )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ "live0001-aaaa" ], families=[ jan.FAMILY_ASK_ANSWER ] )
    assert pruned == [ str( live_file ) ], "mutation changed nothing ⇒ the live gate was not under test"
    assert not live_file.exists()


def test_MUTATION_a_zero_grace_window_reaps_a_file_the_real_window_keeps( tmp_path ):
    young = _write( tmp_path, ".ask-answer-hwm-", "dead0001-aaaa", age_days=1 )
    kept = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ jan.FAMILY_ASK_ANSWER ] )
    assert kept == [ ] and young.exists(), "the grace window never fired"
    reaped = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ jan.FAMILY_ASK_ANSWER ], grace_seconds=0 )
    assert reaped == [ str( young ) ], "grace_seconds ignored ⇒ the age arm is dead code"


# ── ARM 5 — the SENTINEL / carve-out arms (this module's own hazard) ──────

def test_the_acked_unknown_sentinel_is_KEPT_however_ancient( tmp_path ):
    """`.heartbeat-acked-unknown.json` names no session — it must never be reaped."""
    sentinel = _write( tmp_path, ".heartbeat-acked-", "unknown", age_days=3650 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ jan.FAMILY_HEARTBEAT_ACKED ] )
    assert pruned == [ ], "a sentinel name was reaped — the carve-out failed"
    assert sentinel.exists()
    row = jan.classify_bookmark_file( sentinel, jan.FAMILY_HEARTBEAT_ACKED, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_UNPARSEABLE


def test_MUTATION_dropping_the_sentinel_set_would_reap_unknown( tmp_path ):
    """Proves the sentinel arm has teeth: without the sentinel guard, `unknown` dies."""
    sentinel = _write( tmp_path, ".heartbeat-acked-", "unknown", age_days=3650 )
    from dataclasses import replace
    no_sentinel = replace( jan.FAMILY_HEARTBEAT_ACKED, sentinel_ids=frozenset() )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ no_sentinel ] )
    assert pruned == [ str( sentinel ) ], "mutation changed nothing ⇒ the sentinel guard was not under test"


def test_heartbeat_HOLD_is_never_caught_by_the_acked_glob( tmp_path ):
    """
    The acked glob must not widen into the hold family — those move to /tmp elsewhere
    and carry hand-written cargo. Ancient, orphaned, adjacent — still untouched.
    """
    hold = tmp_path / ".heartbeat-hold-dead0001-aaaa-bbbb.json"
    hold.write_text( json.dumps( { "session_id": "dead0001", "held_at": "2020-01-01T00:00:00+00:00",
                                   "ttl_seconds": 60 } ) )
    when = time.time() - ( 3650 * DAY )
    os.utime( hold, ( when, when ) )
    doomed = _write( tmp_path, ".heartbeat-acked-", "dead0001-aaaa-bbbb", age_days=30 )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ jan.FAMILY_HEARTBEAT_ACKED ] )
    assert pruned == [ str( doomed ) ]
    assert hold.exists(), "the bookmark janitor reaped a HOLD file — wrong family, cargo-loss risk"


def test_a_foreign_family_file_classifies_as_unparseable( tmp_path ):
    """A file of another family handed to the wrong classifier is KEPT, typed — never zero-length id."""
    stray = _write( tmp_path, ".task-store-map-", "abcd", age_days=99 )
    row = jan.classify_bookmark_file( stray, jan.FAMILY_ASK_ANSWER, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_UNPARSEABLE
    assert row[ "sid" ] is None


# ── ARM 6 — report is a PREDICTION of the sweep; they must agree ──────────

def test_report_prunable_count_equals_what_sweep_deletes( tmp_path ):
    """Same clock, same live-set: the dry-run tally predicts the deletion count exactly."""
    _write( tmp_path, ".ask-answer-hwm-",     "dead0001-a", age_days=30 )
    _write( tmp_path, ".task-store-map-",     "dead0002-b", age_days=30 )
    _write( tmp_path, ".heartbeat-acked-",    "dead0003-c", age_days=30 )
    _write( tmp_path, ".ask-answer-hwm-",     "live0001-x", age_days=30 )   # kept: live
    now = time.time()
    report = jan.report_bookmark_files( base_dir=tmp_path, live_session_ids=[ "live0001-x" ], now_ts=now )
    assert report[ "deleted" ] == 0
    assert report[ "counts" ][ "prunable" ] == 3
    assert report[ "counts" ][ "keep" ] == 1
    assert report[ "counts" ][ "per_family" ][ "ask_answer" ] == { "prunable": 1, "keep": 1 }
    pruned = jan.sweep_and_reclaim_bookmark_files( base_dir=tmp_path, live_session_ids=[ "live0001-x" ], now_ts=now )
    assert len( pruned ) == report[ "counts" ][ "prunable" ]


def test_report_defaults_to_all_three_families( tmp_path ):
    """families=None means the three owned families — the arbiter passes no families arg."""
    _write( tmp_path, ".ask-answer-hwm-",  "dead-a", age_days=30 )
    _write( tmp_path, ".task-store-map-",  "dead-b", age_days=30 )
    _write( tmp_path, ".heartbeat-acked-", "dead-c", age_days=30 )
    report = jan.report_bookmark_files( base_dir=tmp_path, live_session_ids=[ ] )
    assert report[ "files_found" ] == 3
    assert set( report[ "counts" ][ "per_family" ] ) == { "ask_answer", "task_store_map", "heartbeat_acked" }


# ── ARM 7 — the not-provable-age branches (mtime unreadable / in the future) ─

def test_a_future_mtime_is_not_provable_age_and_is_KEPT( tmp_path ):
    """A future mtime (clock skew / restored backup) is not youth — it is un-clock-able → KEEP."""
    path = _write( tmp_path, ".ask-answer-hwm-", "dead0001-a", age_days=-5 )   # 5 days in the FUTURE
    row  = jan.classify_bookmark_file( path, jan.FAMILY_ASK_ANSWER, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_NO_PROVABLE_AGE
    assert row[ "mtime_age_seconds" ] < 0


def test_an_unreadable_mtime_is_not_provable_age_and_is_KEPT( tmp_path, monkeypatch ):
    path = _write( tmp_path, ".ask-answer-hwm-", "dead0001-a", age_days=30 )
    monkeypatch.setattr( jan, "_file_mtime", lambda p: None )
    row = jan.classify_bookmark_file( path, jan.FAMILY_ASK_ANSWER, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_NO_PROVABLE_AGE
    assert row[ "mtime_age_seconds" ] is None


def test_within_grace_window_is_KEPT( tmp_path ):
    path = _write( tmp_path, ".ask-answer-hwm-", "dead0001-a", age_days=1 )
    row  = jan.classify_bookmark_file( path, jan.FAMILY_ASK_ANSWER, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_KEEP
    assert row[ "reason" ]  == jan.KEEP_TOO_YOUNG


# ── ARM 8 — the small helpers, at their edges ─────────────────────────────

def test_family_session_fragment_edges():
    assert jan.family_session_fragment( ".ask-answer-hwm-sid.json", jan.FAMILY_ASK_ANSWER ) == "sid"
    assert jan.family_session_fragment( ".foreign-sid.json", jan.FAMILY_ASK_ANSWER ) is None
    # empty fragment (prefix immediately followed by suffix) → None, never ""
    assert jan.family_session_fragment( ".ask-answer-hwm-.json", jan.FAMILY_ASK_ANSWER ) is None


def test_live_prefixes_skips_non_strings_and_empties():
    out = jan._live_prefixes( [ "abcd1234-full", "", None, 123, "wxyz9999" ] )
    assert out == { "abcd1234", "wxyz9999" }


def test_family_glob_is_scoped_to_its_prefix():
    assert jan.FAMILY_HEARTBEAT_ACKED.glob == ".heartbeat-acked-*.json"
    assert not jan.FAMILY_HEARTBEAT_ACKED.glob.startswith( ".heartbeat-hold" )


def test_sweep_survives_a_racing_delete( tmp_path, monkeypatch ):
    """A file unlinked out from under the sweep (OSError) is skipped, never raised."""
    doomed = _write( tmp_path, ".ask-answer-hwm-", "dead0001-a", age_days=30 )
    real_unlink = os.unlink
    def _boom( self, *a, **k ):
        raise OSError( "raced" )
    monkeypatch.setattr( type( doomed ), "unlink", _boom )
    pruned = jan.sweep_and_reclaim_bookmark_files(
        base_dir=tmp_path, live_session_ids=[ ], families=[ jan.FAMILY_ASK_ANSWER ] )
    assert pruned == [ ]                     # the racing delete was swallowed
    assert doomed.exists()


def test_classify_defaults_now_ts_when_omitted( tmp_path ):
    """The now_ts=None branch (both classify and report/sweep) resolves to time.time()."""
    path = _write( tmp_path, ".ask-answer-hwm-", "dead0001-a", age_days=30 )
    row  = jan.classify_bookmark_file( path, jan.FAMILY_ASK_ANSWER, live_session_ids=[ ] )
    assert row[ "verdict" ] == jan.VERDICT_PRUNABLE
    # report + sweep with now_ts omitted exercise their own None-defaults
    assert jan.report_bookmark_files( base_dir=tmp_path, live_session_ids=[ ] )[ "counts" ][ "prunable" ] == 1
    assert jan.sweep_and_reclaim_bookmark_files( base_dir=tmp_path, live_session_ids=[ ] ) == [ str( path ) ]


def test_base_dirs_plural_is_honored_in_the_report( tmp_path ):
    """The base_dirs (multi-root) path through report_bookmark_files, distinct from base_dir."""
    _write( tmp_path, ".ask-answer-hwm-", "dead0001-a", age_days=30 )
    report = jan.report_bookmark_files( base_dirs=[ str( tmp_path ) ], live_session_ids=[ ] )
    assert report[ "files_found" ] == 1
    assert report[ "roots_requested" ] == [ str( tmp_path ) ]
