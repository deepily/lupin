"""
Analyse the DM-verbosity two-arm pilot corpus (plan item 7).

The unit of evidence is 14 matched clock-hour pairs, NOT the thousands of
messages — messages are correlated within session and hour, so each hour
contributes one number per arm and Wednesday mirrors Tuesday at every clock
hour. Two co-primaries that must AGREE:

    A — all attempts:      hour-level mean( max( words - 60, 0 ) ) per eligible attempt
    B — first attempts:    the same, over rows where follows_rejection is False

Both are reported rejecting-minus-blind across the matched pairs, with an exact
sign-flip randomization interval (each pair's arm assignment was randomized, so
under the null each pair's difference may flip sign).

    Both move   -> sessions genuinely wrote shorter.
    Only A moves -> we measured retries, not restraint.
    Neither     -> no effect at this dose in one hour.

Classifier (Maria's ruling): a row is in-experiment iff experiment == "two-arm-v1"
-> use effective_arm. The 776 legacy rows carry arm == "signal_only" and are
NEVER pooled into an arm — an observational baseline under a third condition.

Bootstrap standalone: sets sys.path from LUPIN_ROOT first; the analysis logic
imports no cosa, so the unit tests exercise it in isolation.

Run:  python src/scripts/dm-experiment/analyze_arms.py [--corpus PATH] [--counts-only]
"""

import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:                                                     # pragma: no cover
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )                # pragma: no cover

import json
import random
import argparse
import datetime

# ---------------------------------------------------------------------------
EXPERIMENT_TAG                 = "two-arm-v1"
TARGET_WORDS                   = 60                # excess words are measured over this
REJECT_THRESHOLD               = 150               # the rejecting arm's gate (for %>=150 + bunching)
BUNCHING_LOW                   = 140               # bunching band [140, 149] just below the threshold
BLIND                          = "blind"
REJECTING                      = "rejecting"
EXEMPT_GATE                    = "exempt"
TEMP_SLOT_PREFIX               = "TEMP-"           # transient dogfood slots — never analysed
DELIVERED                      = "delivered"
EXPECTED_SLOTS_PER_ARM_PER_DAY = 7
_EXACT_ENUM_MAX_PAIRS          = 18                # 2**18 = 262144 sign vectors — enumerate exactly at/below this
_SAMPLED_ITERATIONS            = 100000            # fallback for the (never-in-this-design) large-N case


def load_rows( path ):
    """
    Read the JSONL corpus into a list of dicts.

    Requires:
        - path names a readable JSONL file (one JSON object per non-blank line)

    Ensures:
        - returns a list of dicts; blank lines are skipped
    """
    rows = []
    with open( path, "r", encoding="utf-8" ) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append( json.loads( line ) )
    return rows


def is_experiment_row( row ):
    """
    Ensures:
        - returns True iff the row was written under the two-arm experiment
          (experiment == "two-arm-v1"); legacy signal_only rows return False
    """
    return row.get( "experiment" ) == EXPERIMENT_TAG


def eligible_rows( rows ):
    """
    The behavioural population: in-experiment attempts that are NOT exempt and
    NOT transient TEMP- dogfood slots.

    Ensures:
        - returns experiment rows whose length_gate is not "exempt"
        - the exempt arbiter poker is excluded — it is out of the experiment by
          design, so it must not enter either arm's denominator
        - rows whose slot_id starts with "TEMP-" are excluded IN CODE, not by
          deletion — a transient live-gate-smoke slot must never reach the
          analysis whether or not someone remembers to delete it. This is the
          single chokepoint feeding co-primaries, secondaries, and counts.
    """
    return [ r for r in rows
             if is_experiment_row( r )
             and r.get( "length_gate" ) != EXEMPT_GATE
             and not r.get( "slot_id", "" ).startswith( TEMP_SLOT_PREFIX ) ]


def slot_date( row ):
    """Ensures: returns the YYYY-MM-DD date embedded in the row's slot_id."""
    return row[ "slot_id" ][ :10 ]


def clock_hour( row ):
    """Ensures: returns the integer clock hour embedded in the row's slot_id (…THH)."""
    return int( row[ "slot_id" ][ 11:13 ] )


def excess_words( words ):
    """Ensures: returns max( words - 60, 0 ) — attempted words beyond target."""
    return max( words - TARGET_WORDS, 0 )


def _mean( values ):
    """Ensures: returns the arithmetic mean, or None for an empty sequence."""
    return sum( values ) / len( values ) if values else None


def hour_arm_excess( rows_for_arm ):
    """
    Ensures:
        - returns the mean excess-words over the given arm's rows in one hour,
          or None when the arm made no eligible attempt that hour
    """
    return _mean( [ excess_words( r[ "words" ] ) for r in rows_for_arm ] )


def matched_pair_diffs( rows, first_attempts_only=False ):
    """
    Build the matched clock-hour pair differences (rejecting minus blind).

    Requires:
        - rows is the corpus (any mix; only eligible experiment rows are used)
        - first_attempts_only selects co-primary B (follows_rejection is False)

    Ensures:
        - returns a list of dicts, one per clock hour where BOTH arms made an
          eligible attempt: {hour, blind, rejecting, diff, first_day_arm}
        - first_day_arm is the arm of the chronologically-earlier day at that hour
          (the order-effect key: which arm was seen first)
        - hours missing either arm are dropped and cannot enter the estimate
    """
    pool = eligible_rows( rows )
    if first_attempts_only:
        pool = [ r for r in pool if not r.get( "follows_rejection", False ) ]

    dates     = sorted( { slot_date( r ) for r in pool } )
    first_day = dates[ 0 ] if dates else None

    by_hour = {}
    for r in pool:
        by_hour.setdefault( clock_hour( r ), [] ).append( r )

    pairs = []
    for hour in sorted( by_hour ):
        hour_rows      = by_hour[ hour ]
        blind_rows     = [ r for r in hour_rows if r[ "effective_arm" ] == BLIND ]
        rejecting_rows = [ r for r in hour_rows if r[ "effective_arm" ] == REJECTING ]
        blind_stat     = hour_arm_excess( blind_rows )
        rejecting_stat = hour_arm_excess( rejecting_rows )
        if blind_stat is None or rejecting_stat is None:
            continue                                    # incomplete pair — cannot difference
        first_day_rows = [ r for r in hour_rows if slot_date( r ) == first_day ]
        first_day_arm  = first_day_rows[ 0 ][ "effective_arm" ] if first_day_rows else None
        pairs.append( {
            "hour"          : hour,
            "blind"         : blind_stat,
            "rejecting"     : rejecting_stat,
            "diff"          : rejecting_stat - blind_stat,
            "first_day_arm" : first_day_arm,
        } )
    return pairs


def _percentile( sorted_values, pct ):
    """
    Ensures:
        - returns the pct-th percentile of an already-sorted list (nearest-rank),
          or None for an empty list
    """
    if not sorted_values:
        return None
    rank = int( round( ( pct / 100.0 ) * ( len( sorted_values ) - 1 ) ) )
    rank = max( 0, min( len( sorted_values ) - 1, rank ) )
    return sorted_values[ rank ]


def randomization_test( diffs ):
    """
    Exact (or sampled) sign-flip randomization test on matched-pair differences.

    Requires:
        - diffs is a list of per-pair (rejecting minus blind) numbers

    Ensures:
        - returns {n_pairs, observed, p_value, interval_lo, interval_hi, method}
        - observed is the mean difference
        - the null flips each pair's sign independently (its arm assignment was
          randomized); p_value is the two-sided share of |null mean| >= |observed|
        - interval is the 2.5/97.5 percentiles of the null mean distribution
        - n_pairs <= _EXACT_ENUM_MAX_PAIRS enumerates all 2**n sign vectors;
          larger n samples _SAMPLED_ITERATIONS vectors with a fixed seed
        - an empty diffs list returns observed None and a degenerate interval
    """
    n = len( diffs )
    if n == 0:
        return { "n_pairs": 0, "observed": None, "p_value": None,
                 "interval_lo": None, "interval_hi": None, "method": "none" }

    observed = sum( diffs ) / n

    null_means = []
    if n <= _EXACT_ENUM_MAX_PAIRS:
        method = "exact"
        for mask in range( 1 << n ):
            total = 0.0
            for i in range( n ):
                total += diffs[ i ] if ( mask >> i ) & 1 else -diffs[ i ]
            null_means.append( total / n )
    else:
        method = "sampled"
        rng = random.Random( 0 )
        for _ in range( _SAMPLED_ITERATIONS ):
            total = 0.0
            for d in diffs:
                total += d if rng.random() < 0.5 else -d
            null_means.append( total / n )

    null_means.sort()
    abs_obs = abs( observed )
    extreme = sum( 1 for m in null_means if abs( m ) >= abs_obs )
    return {
        "n_pairs"     : n,
        "observed"    : observed,
        "p_value"     : extreme / len( null_means ),
        "interval_lo" : _percentile( null_means, 2.5 ),
        "interval_hi" : _percentile( null_means, 97.5 ),
        "method"      : method,
    }


def co_primary( rows, first_attempts_only ):
    """
    Ensures:
        - returns {pairs, test} for co-primary A (first_attempts_only False) or
          B (True) — the matched-pair diffs and their randomization test
    """
    pairs = matched_pair_diffs( rows, first_attempts_only=first_attempts_only )
    return { "pairs": pairs, "test": randomization_test( [ p[ "diff" ] for p in pairs ] ) }


def order_effect( rows ):
    """
    Pre-declared order-effect secondary: blind-first pairs vs rejecting-first.

    Ensures:
        - returns {blind_first_mean, rejecting_first_mean, blind_first_n,
          rejecting_first_n} over co-primary A's pairs, grouped by which arm the
          chronologically-earlier day showed — turning carryover from an
          assumption into a measurement
    """
    pairs           = matched_pair_diffs( rows, first_attempts_only=False )
    blind_first     = [ p[ "diff" ] for p in pairs if p[ "first_day_arm" ] == BLIND ]
    rejecting_first = [ p[ "diff" ] for p in pairs if p[ "first_day_arm" ] == REJECTING ]
    return {
        "blind_first_mean"     : _mean( blind_first ),
        "rejecting_first_mean" : _mean( rejecting_first ),
        "blind_first_n"        : len( blind_first ),
        "rejecting_first_n"    : len( rejecting_first ),
    }


def _arm_rows( rows, arm ):
    """Ensures: returns eligible rows for one arm."""
    return [ r for r in eligible_rows( rows ) if r[ "effective_arm" ] == arm ]


def _repeated_rejection_loops( arm_rows ):
    """
    Ensures:
        - returns the count of rejected attempts whose immediately-prior attempt
          in the same slot was also rejected (follows_rejection True AND this
          attempt rejected) — a proxy for a session stuck resending over-length
    """
    return sum( 1 for r in arm_rows
                if r.get( "length_gate" ) == "rejected" and r.get( "follows_rejection", False ) )


def _parse_ts( value ):
    """
    Requires:
        - value is an ISO-8601 string, or None

    Ensures:
        - returns a timezone-aware datetime, treating a naive stamp as UTC
          (the corpus writes `ts` naive and `delivered_at`/`assigned_at_utc`
          aware — comparing the two forms raises, so both are normalised here)
        - returns None for None or an unparseable string, so one malformed
          stamp drops ONE row instead of failing the whole analysis
    """
    if not value: return None
    try:
        parsed = datetime.datetime.fromisoformat( value )
    except ValueError:
        return None
    if parsed.tzinfo is None: parsed = parsed.replace( tzinfo=datetime.timezone.utc )
    return parsed


def delivery_delay_seconds( row ):
    """
    Ensures:
        - returns (delivered_at - assigned_at_utc) in seconds for a row that
          carries BOTH stamps, else None
        - a negative delta is returned as-is rather than clamped — a clock
          that runs backwards is a finding, not something to hide
        - `assigned_at_utc` is the arm-assignment instant, so this measures the
          delay the SENDER waited, not the corpus write latency
    """
    assigned  = _parse_ts( row.get( "assigned_at_utc" ) )
    delivered = _parse_ts( row.get( "delivered_at" ) )
    if assigned is None or delivered is None: return None
    return ( delivered - assigned ).total_seconds()


def secondaries( rows ):
    """
    Ensures:
        - returns per-arm secondary metrics: pct >= threshold, attempts per
          delivered message, bunching share in [140,149], repeated-rejection
          loops, mean est_tokens per attempt and per delivered message, and
          mean delivery delay in seconds
        - est_tokens is labelled an estimate (chars/4) wherever reported
        - mean_delivery_delay_s reports alongside delivery_delay_n, the number
          of delivered rows that actually carried both stamps — a mean over an
          unnamed denominator is not a measurement. Rows written before the
          `delivered_at` stamp landed contribute nothing and are excluded here,
          so the count is how many rows the number is actually built from
    """
    out = {}
    for arm in ( BLIND, REJECTING ):
        arm_rows  = _arm_rows( rows, arm )
        n         = len( arm_rows )
        delivered = [ r for r in arm_rows if r.get( "delivery_outcome" ) == DELIVERED ]
        over      = [ r for r in arm_rows if r[ "words" ] >= REJECT_THRESHOLD ]
        bunched   = [ r for r in arm_rows if BUNCHING_LOW <= r[ "words" ] < REJECT_THRESHOLD ]
        delays    = [ d for d in ( delivery_delay_seconds( r ) for r in delivered ) if d is not None ]
        out[ arm ] = {
            "attempts"                  : n,
            "delivered"                 : len( delivered ),
            "pct_ge_threshold"          : ( len( over ) / n ) if n else None,
            "attempts_per_delivered"    : ( n / len( delivered ) ) if delivered else None,
            "bunching_share_140_149"    : ( len( bunched ) / n ) if n else None,
            "repeated_rejection_loops"  : _repeated_rejection_loops( arm_rows ),
            "mean_est_tokens_attempt"   : _mean( [ r[ "est_tokens" ] for r in arm_rows ] ),
            "mean_est_tokens_delivered" : _mean( [ r[ "est_tokens" ] for r in delivered ] ),
            "mean_delivery_delay_s"     : _mean( delays ),
            "delivery_delay_n"          : len( delays ),
        }
    return out


def counts_only( rows ):
    """
    Ensures:
        - returns {(date, arm): {distinct_slots, ok}} against
          EXPECTED_SLOTS_PER_ARM_PER_DAY — the Tue/Wed 23:00 check that seven
          slots per arm per day actually produced traffic while it is still fixable
    """
    seen = {}   # (date, arm) -> set of slot_ids
    for r in eligible_rows( rows ):
        seen.setdefault( ( slot_date( r ), r[ "effective_arm" ] ), set() ).add( r[ "slot_id" ] )
    report = {}
    for key, slots in sorted( seen.items() ):
        report[ key ] = { "distinct_slots": len( slots ), "ok": len( slots ) == EXPECTED_SLOTS_PER_ARM_PER_DAY }
    return report


def _fmt( value ):
    """Ensures: returns a 3-decimal string for a number, or 'n/a' for None."""
    return "n/a" if value is None else f"{value:.3f}"


def format_report( rows ):
    """
    Ensures:
        - returns a plain-text report of both co-primaries, order effect, and
          secondaries — verdict-first, no markdown
    """
    a = co_primary( rows, first_attempts_only=False )
    b = co_primary( rows, first_attempts_only=True )
    lines = [ "DM-verbosity two-arm pilot — rejecting minus blind, 14 matched clock-hour pairs" ]
    for label, res in ( ( "A (all attempts)", a ), ( "B (first attempts only)", b ) ):
        t = res[ "test" ]
        lines.append(
            f"  Co-primary {label}: n_pairs={t['n_pairs']} observed={_fmt(t['observed'])} "
            f"p={_fmt(t['p_value'])} null95=[{_fmt(t['interval_lo'])},{_fmt(t['interval_hi'])}] ({t['method']})" )
    lines.append( "  (Both move -> genuine restraint; only A -> retries not restraint; neither -> no effect at this dose.)" )
    oe = order_effect( rows )
    lines.append(
        f"  Order effect: blind-first mean={_fmt(oe['blind_first_mean'])} (n={oe['blind_first_n']}) "
        f"vs rejecting-first mean={_fmt(oe['rejecting_first_mean'])} (n={oe['rejecting_first_n']})" )
    sec = secondaries( rows )
    for arm in ( BLIND, REJECTING ):
        s = sec[ arm ]
        lines.append(
            f"  {arm}: attempts={s['attempts']} delivered={s['delivered']} "
            f"pct>=150={_fmt(s['pct_ge_threshold'])} attempts/delivered={_fmt(s['attempts_per_delivered'])} "
            f"bunch[140,149]={_fmt(s['bunching_share_140_149'])} reject_loops={s['repeated_rejection_loops']} "
            f"est_tokens/attempt={_fmt(s['mean_est_tokens_attempt'])} (chars/4 est) "
            f"est_tokens/delivered={_fmt(s['mean_est_tokens_delivered'])} (chars/4 est) "
            f"delivery_delay_s={_fmt(s['mean_delivery_delay_s'])} (n={s['delivery_delay_n']})" )
    return "\n".join( lines )


def format_counts( rows ):
    """Ensures: returns a plain-text --counts-only report, flagging any (date,arm) not at 7 slots."""
    report = counts_only( rows )
    lines  = [ f"Slot coverage (expected {EXPECTED_SLOTS_PER_ARM_PER_DAY} per arm per day):" ]
    if not report:
        lines.append( "  no eligible experiment rows found" )
    for ( date, arm ), info in report.items():
        flag = "OK" if info[ "ok" ] else "MISMATCH"
        lines.append( f"  {date} {arm}: {info['distinct_slots']} distinct slots — {flag}" )
    return "\n".join( lines )


def default_corpus_path():
    """Ensures: returns <project_root>/src/tmp/dm_traffic.jsonl (the live corpus)."""
    import cosa.utils.util as cu
    return cu.get_project_root() + "/src/tmp/dm_traffic.jsonl"


def main( argv=None ):
    """
    CLI entry: print the full analysis, or the --counts-only coverage check.

    Ensures:
        - loads the corpus (default the live path, or --corpus PATH)
        - --counts-only prints the per-(date,arm) slot-coverage check
        - otherwise prints both co-primaries, order effect, and secondaries
        - returns 0
    """
    parser = argparse.ArgumentParser( description="Analyse the DM-verbosity two-arm pilot corpus." )
    parser.add_argument( "--corpus", default=None, help="path to the JSONL corpus (default: live dm_traffic.jsonl)" )
    parser.add_argument( "--counts-only", action="store_true", help="print only the per-arm-per-day slot-coverage check" )
    args = parser.parse_args( argv )

    path = args.corpus if args.corpus is not None else default_corpus_path()
    rows = load_rows( path )

    if args.counts_only:
        print( format_counts( rows ) )
    else:
        print( format_report( rows ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )                                                     # pragma: no cover — CLI entry; main() itself is covered directly
