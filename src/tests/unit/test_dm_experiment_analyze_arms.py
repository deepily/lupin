"""
Unit tests for the DM-verbosity pilot analysis (`analyze_arms.py`, plan item 7).

The headline test is the reason co-primary B exists: a fixture where rejection
causes a retry with ZERO behaviour change — a 200-word intent becomes a 200-word
refusal plus a 90-word resend — and co-primary A (all attempts) moves while
co-primary B (first attempts only) does not. That split is the whole point:
A alone moving means we measured retries, not restraint.

Loads the dashed-directory script via importlib; its analysis logic imports no
cosa, so these run in isolation.

Venue: :7999-eligible (pure unit — no server, no DB, no state mutation).
"""

import os
import json
import importlib.util

import pytest


def _load_analyzer():
    lupin_root = os.environ[ "LUPIN_ROOT" ]
    path       = os.path.join( lupin_root, "src", "scripts", "dm-experiment", "analyze_arms.py" )
    spec       = importlib.util.spec_from_file_location( "dm_analyze_arms", path )
    module     = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


AN = _load_analyzer()

TUE = "2026-08-04"
WED = "2026-08-05"


def _row( slot_id, arm, words, follows_rejection=False, length_gate="passed",
          delivery_outcome="delivered", experiment="two-arm-v1" ):
    return {
        "slot_id"           : slot_id,
        "effective_arm"     : arm,
        "words"             : words,
        "follows_rejection" : follows_rejection,
        "length_gate"       : length_gate,
        "delivery_outcome"  : delivery_outcome,
        "experiment"        : experiment,
        "est_tokens"        : words * 6,       # arbitrary chars/4-shaped stand-in
        "chars"             : words * 6,
    }


def _retry_fixture():
    """
    Three matched clock-hour pairs, each the zero-behaviour-change retry pattern:
      blind day     — one 200-word delivery
      rejecting day — a 200-word refusal (first attempt) + a 90-word resend
    A must move (200 vs mean(200,90)=145 excess); B must not (both first attempts 200).
    """
    rows = []
    for hour in ( 9, 10, 11 ):
        rows.append( _row( f"{TUE}T{hour:02d}", "blind", 200 ) )
        rows.append( _row( f"{WED}T{hour:02d}", "rejecting", 200, follows_rejection=False,
                           length_gate="rejected", delivery_outcome="not_attempted" ) )
        rows.append( _row( f"{WED}T{hour:02d}", "rejecting", 90, follows_rejection=True,
                           length_gate="passed", delivery_outcome="delivered" ) )
    return rows


# --------------------------------------------------------------------------- #
# classifier + eligibility                                                    #
# --------------------------------------------------------------------------- #
def test_is_experiment_row():
    assert AN.is_experiment_row( { "experiment": "two-arm-v1" } ) is True
    assert AN.is_experiment_row( { "arm": "signal_only" } ) is False
    assert AN.is_experiment_row( {} ) is False


def test_eligible_rows_excludes_exempt_and_baseline():
    rows = [
        _row( f"{TUE}T09", "blind", 100 ),                                    # eligible
        _row( f"{TUE}T09", "blind", 100, length_gate="exempt" ),              # arbiter — excluded
        { "arm": "signal_only", "words": 100, "slot_id": f"{TUE}T09" },       # baseline — excluded
    ]
    elig = AN.eligible_rows( rows )
    assert len( elig ) == 1
    assert elig[ 0 ][ "length_gate" ] == "passed"


def test_eligible_rows_excludes_temp_slots():
    # A transient live-gate-smoke slot (slot_id starts "TEMP-") must be dropped in
    # code, not by deletion — the exclusion is deletion-independent.
    rows = [
        _row( f"{TUE}T09", "blind", 100 ),                                   # eligible
        _row( "TEMP-live-gate-smoke", "rejecting", 200 ),                    # transient — excluded
    ]
    elig = AN.eligible_rows( rows )
    assert len( elig ) == 1
    assert elig[ 0 ][ "slot_id" ] == f"{TUE}T09"


def test_temp_slot_has_zero_effect_on_counts_and_coprimary():
    # End-to-end: adding a TEMP- row changes neither counts nor the co-primary pairs.
    # (It also proves clock_hour is never called on "TEMP-…" — which would raise.)
    base      = _retry_fixture()
    with_temp = base + [ _row( "TEMP-live-gate-smoke", "rejecting", 200 ) ]
    assert AN.counts_only( with_temp )       == AN.counts_only( base )
    assert AN.matched_pair_diffs( with_temp ) == AN.matched_pair_diffs( base )


def test_slot_date_and_clock_hour():
    r = _row( f"{WED}T14", "blind", 10 )
    assert AN.slot_date( r )  == WED
    assert AN.clock_hour( r ) == 14


def test_excess_words():
    assert AN.excess_words( 200 ) == 140
    assert AN.excess_words( 60 )  == 0
    assert AN.excess_words( 10 )  == 0


# --------------------------------------------------------------------------- #
# THE headline split — A moves, B does not                                    #
# --------------------------------------------------------------------------- #
def test_coprimary_A_moves_while_B_stays_flat():
    rows = _retry_fixture()
    a = AN.co_primary( rows, first_attempts_only=False )
    b = AN.co_primary( rows, first_attempts_only=True )

    assert a[ "test" ][ "n_pairs" ] == 3
    assert b[ "test" ][ "n_pairs" ] == 3
    # A: rejecting mean excess = mean(140,30)=85; blind=140; diff = -55 per pair
    assert a[ "test" ][ "observed" ] == pytest.approx( -55.0 )
    # B: first attempts only — both arms 200 words → diff 0, dead flat
    assert b[ "test" ][ "observed" ] == pytest.approx( 0.0 )


def test_matched_pair_diffs_drops_incomplete_hours():
    rows = [
        _row( f"{TUE}T09", "blind", 100 ),          # hour 9: blind only — no rejecting mirror
        _row( f"{TUE}T10", "blind", 100 ),          # hour 10: complete pair
        _row( f"{WED}T10", "rejecting", 100 ),
    ]
    pairs = AN.matched_pair_diffs( rows )
    assert [ p[ "hour" ] for p in pairs ] == [ 10 ]


def test_matched_pair_diffs_empty_pool_returns_empty():
    assert AN.matched_pair_diffs( [ { "arm": "signal_only", "words": 1, "slot_id": f"{TUE}T09" } ] ) == []


def test_first_day_arm_none_when_pair_only_on_later_date():
    # first_day is TUE (a hour-10 row anchors it); the hour-9 pair lives only on WED,
    # so first_day_rows is empty → first_day_arm is None (the else branch).
    rows = [
        _row( f"{TUE}T10", "blind", 100 ), _row( f"{WED}T10", "rejecting", 100 ),
        _row( f"{WED}T09", "blind", 100 ), _row( f"{WED}T09", "rejecting", 100 ),
    ]
    pairs = { p[ "hour" ]: p for p in AN.matched_pair_diffs( rows ) }
    assert pairs[ 9 ][ "first_day_arm" ] is None


# --------------------------------------------------------------------------- #
# randomization test + percentile                                            #
# --------------------------------------------------------------------------- #
def test_randomization_exact_known_values():
    res = AN.randomization_test( [ 2.0, 4.0 ] )
    assert res[ "method" ]      == "exact"
    assert res[ "n_pairs" ]     == 2
    assert res[ "observed" ]    == pytest.approx( 3.0 )
    # null means over the four sign vectors: {-3,-1,1,3}; |m|>=3 for two of them
    assert res[ "p_value" ]     == pytest.approx( 0.5 )
    assert res[ "interval_lo" ] == pytest.approx( -3.0 )
    assert res[ "interval_hi" ] == pytest.approx( 3.0 )


def test_randomization_empty():
    res = AN.randomization_test( [] )
    assert res[ "n_pairs" ] == 0
    assert res[ "observed" ] is None
    assert res[ "method" ] == "none"


def test_randomization_sampled_branch_for_large_n():
    # 19 pairs exceeds the exact-enumeration cap → the sampled path with a fixed seed.
    res = AN.randomization_test( [ 1.0 ] * 19 )
    assert res[ "method" ]  == "sampled"
    assert res[ "n_pairs" ] == 19
    assert res[ "observed" ] == pytest.approx( 1.0 )


def test_percentile_empty_is_none():
    assert AN._percentile( [], 50 ) is None


def test_percentile_basic():
    assert AN._percentile( [ 0, 1, 2, 3, 4 ], 50 ) == 2


# --------------------------------------------------------------------------- #
# order effect + secondaries                                                  #
# --------------------------------------------------------------------------- #
def test_order_effect_groups_by_first_day_arm():
    rows = _retry_fixture()             # first day is TUE (blind) → all pairs blind-first
    oe   = AN.order_effect( rows )
    assert oe[ "blind_first_n" ]        == 3
    assert oe[ "rejecting_first_n" ]    == 0
    assert oe[ "blind_first_mean" ]     == pytest.approx( -55.0 )
    assert oe[ "rejecting_first_mean" ] is None


def test_secondaries_metrics():
    rows = _retry_fixture()
    sec  = AN.secondaries( rows )
    # blind: 3 attempts of 200 words, all delivered, all >= 150
    assert sec[ "blind" ][ "attempts" ]               == 3
    assert sec[ "blind" ][ "delivered" ]              == 3
    assert sec[ "blind" ][ "pct_ge_threshold" ]       == pytest.approx( 1.0 )
    assert sec[ "blind" ][ "attempts_per_delivered" ] == pytest.approx( 1.0 )
    # rejecting: 6 attempts (3×200 rejected + 3×90 resend), 3 delivered
    assert sec[ "rejecting" ][ "attempts" ]               == 6
    assert sec[ "rejecting" ][ "delivered" ]              == 3
    assert sec[ "rejecting" ][ "pct_ge_threshold" ]       == pytest.approx( 0.5 )
    assert sec[ "rejecting" ][ "attempts_per_delivered" ] == pytest.approx( 2.0 )
    # blind never refuses a draft, so all-in == delivered-only (200 words × 6 = 1200).
    assert sec[ "blind" ][ "mean_est_tokens_delivered" ]        == pytest.approx( 1200.0 )
    assert sec[ "blind" ][ "mean_est_tokens_delivered_all_in" ] == pytest.approx( 1200.0 )


def test_secondaries_bunching_and_reject_loops():
    rows = [
        _row( f"{TUE}T09", "rejecting", 145 ),   # bunched just below 150
        _row( f"{TUE}T09", "rejecting", 160, follows_rejection=True, length_gate="rejected" ),  # a loop
    ]
    sec = AN.secondaries( rows )[ "rejecting" ]
    assert sec[ "bunching_share_140_149" ]   == pytest.approx( 0.5 )
    assert sec[ "repeated_rejection_loops" ] == 1


def test_secondaries_all_in_counts_refused_draft_tokens():
    """
    Row 35d0a451: the delivered-only mean HID tokens burned on refused drafts. The
    all-in figure counts every token the arm spent over the messages that landed, so
    for an arm that refuses drafts it is strictly higher — and the gap is exactly the
    refused-draft tokens amortised over deliveries.
    """
    rows = _retry_fixture()
    sec  = AN.secondaries( rows )[ "rejecting" ]
    # delivered-only: the 3 resends of 90 words × 6 = 540 each -> mean 540.
    assert sec[ "mean_est_tokens_delivered" ] == pytest.approx( 540.0 )
    # all-in: every token spent (3×1200 refused + 3×540 delivered = 5220) over 3 landed.
    assert sec[ "mean_est_tokens_delivered_all_in" ] == pytest.approx( 5220.0 / 3.0 )
    # the point of the row — the refused drafts are no longer invisible.
    assert sec[ "mean_est_tokens_delivered_all_in" ] > sec[ "mean_est_tokens_delivered" ]
    burned_over_delivered = ( 3 * 1200 ) / 3.0   # the refused 200-word drafts, per delivery
    assert ( sec[ "mean_est_tokens_delivered_all_in" ]
             - sec[ "mean_est_tokens_delivered" ] ) == pytest.approx( burned_over_delivered )


def test_secondaries_empty_arm_is_none():
    sec = AN.secondaries( [] )[ "blind" ]
    assert sec[ "attempts" ]         == 0
    assert sec[ "pct_ge_threshold" ] is None
    assert sec[ "attempts_per_delivered" ] is None
    assert sec[ "mean_est_tokens_attempt" ] is None
    assert sec[ "mean_est_tokens_delivered_all_in" ] is None


# --------------------------------------------------------------------------- #
# counts-only                                                                 #
# --------------------------------------------------------------------------- #
def test_counts_only_flags_seven_ok_and_short_mismatch():
    rows = [ _row( f"{TUE}T{h:02d}", "blind", 50 ) for h in range( 9, 16 ) ]   # 7 distinct slots
    rows += [ _row( f"{TUE}T09", "rejecting", 50 ) ]                            # 1 slot only
    report = AN.counts_only( rows )
    assert report[ ( TUE, "blind" ) ]     == { "distinct_slots": 7, "ok": True }
    assert report[ ( TUE, "rejecting" ) ] == { "distinct_slots": 1, "ok": False }


def test_format_counts_empty_and_populated():
    assert "no eligible experiment rows" in AN.format_counts( [] )
    text = AN.format_counts( [ _row( f"{TUE}T09", "blind", 50 ) ] )
    assert "MISMATCH" in text and f"{TUE} blind" in text


# --------------------------------------------------------------------------- #
# load_rows + format_report + main                                            #
# --------------------------------------------------------------------------- #
def _write_corpus( tmp_path, rows ):
    path = tmp_path / "corpus.jsonl"
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( "\n" )                                   # a blank line must be skipped
        for r in rows:
            fh.write( json.dumps( r ) + "\n" )
    return str( path )


def test_load_rows_skips_blank_lines( tmp_path ):
    path = _write_corpus( tmp_path, _retry_fixture() )
    assert len( AN.load_rows( path ) ) == 9


def test_format_report_contains_both_coprimaries():
    text = AN.format_report( _retry_fixture() )
    assert "Co-primary A (all attempts)" in text
    assert "Co-primary B (first attempts only)" in text
    assert "chars/4 est" in text                           # est_tokens labelled an estimate
    assert "est_tokens/delivered_all_in=" in text          # the all-in figure is reported beside it (row 35d0a451)
    assert "incl refused drafts" in text                   # and labelled as counting refused drafts


def test_main_full_report( tmp_path, capsys ):
    path = _write_corpus( tmp_path, _retry_fixture() )
    assert AN.main( [ "--corpus", path ] ) == 0
    assert "Co-primary A" in capsys.readouterr().out


def test_main_counts_only( tmp_path, capsys ):
    path = _write_corpus( tmp_path, _retry_fixture() )
    assert AN.main( [ "--corpus", path, "--counts-only" ] ) == 0
    assert "Slot coverage" in capsys.readouterr().out


def test_main_defaults_to_corpus_path( tmp_path, monkeypatch, capsys ):
    path = _write_corpus( tmp_path, _retry_fixture() )
    monkeypatch.setattr( AN, "default_corpus_path", lambda: path )
    assert AN.main( [] ) == 0
    assert "Co-primary A" in capsys.readouterr().out


def test_default_corpus_path_points_at_tmp():
    assert AN.default_corpus_path().endswith( "/src/tmp/dm_traffic.jsonl" )


# ═════════════════════════════════════════════════════════════════════════════
# Delivery-delay secondary (row 1fc6b180)
#
# The stamp this reads — `delivered_at` on the corpus row — landed AFTER the
# corpus started filling, so the honest hazard is a mean computed over a
# denominator nobody named. Every test below pins BOTH the value and the count
# it was built from; a mean whose n is unstated is what these exist to prevent.
# ═════════════════════════════════════════════════════════════════════════════

def _timed_row( slot_id, arm, words, assigned=None, delivered=None, **kw ):
    """A _row with the two delivery stamps attached (either may be omitted)."""
    row = _row( slot_id, arm, words, **kw )
    if assigned  is not None: row[ "assigned_at_utc" ] = assigned
    if delivered is not None: row[ "delivered_at" ]    = delivered
    return row


def test_parse_ts_returns_none_for_missing_or_unparseable():
    assert AN._parse_ts( None )        is None
    assert AN._parse_ts( "" )          is None
    assert AN._parse_ts( "not-a-ts" )  is None


def test_parse_ts_treats_naive_as_utc_and_preserves_aware():
    naive = AN._parse_ts( "2026-08-04T13:53:17" )
    aware = AN._parse_ts( "2026-08-04T13:53:17+00:00" )
    assert naive.utcoffset().total_seconds() == 0
    assert naive == aware                      # the whole point: the two forms compare


def test_delivery_delay_seconds_computes_the_gap():
    row = _timed_row( f"{TUE}T09", "rejecting", 23,
                      assigned  = "2026-08-04T13:53:17.445054+00:00",
                      delivered = "2026-08-04T13:53:17.482331+00:00" )
    assert AN.delivery_delay_seconds( row ) == pytest.approx( 0.037277, abs=1e-6 )


def test_delivery_delay_seconds_mixes_naive_and_aware_stamps():
    """The live corpus writes one stamp naive and one aware — this must not raise."""
    row = _timed_row( f"{TUE}T09", "rejecting", 23,
                      assigned  = "2026-08-04T13:00:00",
                      delivered = "2026-08-04T13:00:02+00:00" )
    assert AN.delivery_delay_seconds( row ) == pytest.approx( 2.0 )


@pytest.mark.parametrize( "assigned,delivered", [
    ( None,                        "2026-08-04T13:53:17+00:00" ),
    ( "2026-08-04T13:53:17+00:00", None                        ),
    ( None,                        None                        ),
    ( "garbage",                   "2026-08-04T13:53:17+00:00" ),
] )
def test_delivery_delay_seconds_is_none_without_both_stamps( assigned, delivered ):
    row = _timed_row( f"{TUE}T09", "rejecting", 23, assigned=assigned, delivered=delivered )
    assert AN.delivery_delay_seconds( row ) is None


def test_delivery_delay_seconds_reports_a_backwards_clock_rather_than_hiding_it():
    row = _timed_row( f"{TUE}T09", "rejecting", 23,
                      assigned  = "2026-08-04T13:53:17+00:00",
                      delivered = "2026-08-04T13:53:15+00:00" )
    assert AN.delivery_delay_seconds( row ) == pytest.approx( -2.0 )


def test_secondaries_delivery_delay_means_over_stamped_rows_only():
    rows = [
        _timed_row( f"{TUE}T09", "rejecting", 20,
                    assigned="2026-08-04T13:00:00+00:00", delivered="2026-08-04T13:00:02+00:00" ),
        _timed_row( f"{TUE}T09", "rejecting", 20,
                    assigned="2026-08-04T13:10:00+00:00", delivered="2026-08-04T13:10:04+00:00" ),
        # legacy row, written before the stamp landed — must NOT enter the mean
        _row( f"{TUE}T09", "rejecting", 20 ),
        _timed_row( f"{WED}T09", "blind", 20,
                    assigned="2026-08-05T13:00:00+00:00", delivered="2026-08-05T13:00:10+00:00" ),
    ]
    sec = AN.secondaries( rows )
    assert sec[ "rejecting" ][ "mean_delivery_delay_s" ] == pytest.approx( 3.0 )
    assert sec[ "rejecting" ][ "delivery_delay_n" ]      == 2      # NOT 3 — the legacy row is out
    assert sec[ "rejecting" ][ "delivered" ]             == 3      # …but it is still a delivery
    assert sec[ "blind" ][ "mean_delivery_delay_s" ]     == pytest.approx( 10.0 )
    assert sec[ "blind" ][ "delivery_delay_n" ]          == 1


def test_secondaries_delivery_delay_ignores_undelivered_rows():
    rows = [
        _timed_row( f"{TUE}T09", "rejecting", 200, length_gate="rejected",
                    delivery_outcome="rejected",
                    assigned="2026-08-04T13:00:00+00:00", delivered="2026-08-04T13:00:99+00:00" ),
        _timed_row( f"{TUE}T09", "rejecting", 20,
                    assigned="2026-08-04T13:10:00+00:00", delivered="2026-08-04T13:10:05+00:00" ),
    ]
    sec = AN.secondaries( rows )
    assert sec[ "rejecting" ][ "mean_delivery_delay_s" ] == pytest.approx( 5.0 )
    assert sec[ "rejecting" ][ "delivery_delay_n" ]      == 1


def test_secondaries_delivery_delay_is_none_with_zero_stamped_rows():
    """An arm with deliveries but no stamps reports n/a over n=0, never 0.0 over n=0."""
    sec = AN.secondaries( [ _row( f"{TUE}T09", "rejecting", 20 ) ] )
    assert sec[ "rejecting" ][ "mean_delivery_delay_s" ] is None
    assert sec[ "rejecting" ][ "delivery_delay_n" ]      == 0
    assert sec[ "blind" ][ "mean_delivery_delay_s" ]     is None
    assert sec[ "blind" ][ "delivery_delay_n" ]          == 0


def test_format_report_shows_delivery_delay_with_its_denominator():
    rows = [
        _timed_row( f"{TUE}T09", "rejecting", 20,
                    assigned="2026-08-04T13:00:00+00:00", delivered="2026-08-04T13:00:02+00:00" ),
        _timed_row( f"{WED}T09", "blind", 20,
                    assigned="2026-08-05T13:00:00+00:00", delivered="2026-08-05T13:00:04+00:00" ),
    ]
    out = AN.format_report( rows )
    assert "delivery_delay_s=2.000 (n=1)" in out
    assert "delivery_delay_s=4.000 (n=1)" in out


# ═════════════════════════════════════════════════════════════════════════════
# Self-addressed exclusion (Rick's ruling, 2026-08-04)
#
# Audit-movement probes were sent as Cheech -> Cheech and landed in the live
# rejecting slot at 23 words each, against real peer traffic averaging 86 —
# dragging the arm 24 words toward the very result the pilot is testing for.
# The rows stay in the corpus (append-only, auditable); they stop voting here.
# ═════════════════════════════════════════════════════════════════════════════

def _addressed_row( slot_id, arm, words, from_session, to_session, **kw ):
    row = _row( slot_id, arm, words, **kw )
    row[ "from_session" ] = from_session
    row[ "to_session" ]   = to_session
    return row


def test_is_self_addressed_true_only_when_both_sessions_match():
    assert AN.is_self_addressed( { "from_session": "abc", "to_session": "abc" } ) is True
    assert AN.is_self_addressed( { "from_session": "abc", "to_session": "xyz" } ) is False


@pytest.mark.parametrize( "row", [
    { "from_session": "abc" },                          # recipient unknown
    { "to_session":   "abc" },                          # sender unknown
    {},                                                 # neither
    { "from_session": "",    "to_session": ""    },     # both blank — not a match
    { "from_session": None,  "to_session": None  },
] )
def test_is_self_addressed_false_when_a_session_is_unknown( row ):
    """An unknown pair is not evidence of self-addressing — never guess a row out."""
    assert AN.is_self_addressed( row ) is False


def test_eligible_rows_drops_self_addressed_keeps_peer_rows():
    rows = [
        _addressed_row( f"{TUE}T09", "rejecting", 23, "cheech", "cheech" ),   # probe
        _addressed_row( f"{TUE}T09", "rejecting", 86, "rachel", "mrradio" ),  # real
    ]
    kept = AN.eligible_rows( rows )
    assert len( kept ) == 1
    assert kept[ 0 ][ "words" ] == 86


def test_self_addressed_rows_do_not_move_the_arm_mean():
    """The measured harm, pinned: 3 probe rows at 23w must not pull 86 down to 62."""
    peer  = [ _addressed_row( f"{TUE}T09", "rejecting", w, f"peer{i}", "mrradio" )
              for i, w in enumerate( ( 123, 81, 60, 97, 69 ) ) ]
    probe = [ _addressed_row( f"{TUE}T09", "rejecting", 23, "cheech", "cheech" )
              for _ in range( 3 ) ]
    sec = AN.secondaries( peer + probe )
    assert sec[ "rejecting" ][ "attempts" ] == 5           # NOT 8
    contaminated = AN.secondaries( [ dict( r, from_session=f"s{i}" )
                                     for i, r in enumerate( peer + probe ) ] )
    assert contaminated[ "rejecting" ][ "attempts" ] == 8  # the control: without the rule they DO vote


def test_counts_only_ignores_self_addressed_slots():
    """A slot whose only traffic is self-addressed must not count as covered."""
    rows = [ _addressed_row( f"{TUE}T09", "rejecting", 23, "cheech", "cheech" ) ]
    assert AN.counts_only( rows ) == {}
