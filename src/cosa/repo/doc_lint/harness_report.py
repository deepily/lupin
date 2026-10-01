"""
The numbers of the judge harness exit gate (plan 1, section 5).

All of it is plain arithmetic over the runner's results. It counts the seeded removals that
slipped past, with a one-sided 95% upper bound. It counts the untouched pairs that were flagged.
It measures how often the three judge runs agree on a claim. It reports how much of the old
text no verified quote covers.
"""

from scipy.stats import beta

from . import claim_extractor, claim_judge

DEFAULT_POSITIVES_NEEDED = 60
AGREEMENT_BAR            = 0.95
FALSE_ALARM_CEILING      = 0.10
CONFIDENCE               = 0.95


def upper_bound( misses, trials ):
    """
    Return the one-sided 95% Clopper-Pearson upper bound on a miss rate.

    Requires:
        - 0 <= misses <= trials

    Ensures:
        - returns None when trials is 0
        - returns 1.0 when every trial missed
    """
    if trials == 0: return None
    if misses == trials: return 1.0
    return float( beta.ppf( CONFIDENCE, misses + 1, trials - misses ) )


def interval( successes, trials ):
    """
    Return the two-sided 95% Clopper-Pearson interval for a proportion.

    Requires:
        - 0 <= successes <= trials

    Ensures:
        - returns None when trials is 0
        - the lower end is 0.0 for no successes and the upper end 1.0 for all of them
    """
    if trials == 0: return None
    tail  = ( 1 - CONFIDENCE ) / 2
    lower = 0.0 if successes == 0 else float( beta.ppf( tail, successes, trials - successes + 1 ) )
    upper = 1.0 if successes == trials else float( beta.ppf( 1 - tail, successes + 1, trials - successes ) )
    return lower, upper


def final_absent( runs ):
    """
    Return, per claim, whether the majority of judge runs call it dropped.

    Requires:
        - runs is a non-empty list of runs; each run is a list of verdict rows, one per claim

    Ensures:
        - a claim is dropped when more than half of the runs say absent
    """
    return [ sum( 1 for run in runs if run[ i ][ "verdict" ] == "absent" ) * 2 > len( runs ) for i in range( len( runs[ 0 ] ) ) ]


def unanimous( runs ):
    """Return, per claim, whether every judge run gave the same verdict."""
    return [ len( { run[ i ][ "verdict" ] for run in runs } ) == 1 for i in range( len( runs[ 0 ] ) ) ]


def caught( claim_list, seed_span ):
    """
    Say whether one extractor list caught a seeded removal.

    Requires:
        - claim_list is a run_pair list entry; seed_span is ( start, end ) in the old text

    Ensures:
        - True only when a claim judged dropped has a verified quote that overlaps the seed span
        - a flagged claim elsewhere does not count, and a seeded claim the extractor discarded
          or never listed is a miss
    """
    flags = final_absent( claim_list[ "runs" ] ) if claim_list[ "claims" ] else []
    return any( flag and claim_extractor.spans_overlap( ( c[ "start" ], c[ "end" ] ), seed_span )
                for flag, c in zip( flags, claim_list[ "claims" ] ) )


def flagged( claim_list ):
    """Say whether an extractor list has any claim judged dropped."""
    return bool( claim_list[ "claims" ] ) and any( final_absent( claim_list[ "runs" ] ) )


def build_report( results, config ):
    """
    Turn runner results into the exit-gate figures.

    Requires:
        - results come from run_all with the same config
        - a result with a seed_span is a seeded-removal pair; the others are unseeded

    Ensures:
        - per extractor list: misses, false alarms, and whether each meets its criterion, so a
          criterion must hold on every list and not on one lucky draw
        - agreement is reported over all claims and over claims overlapping a seed span, each with
          its interval, because an overall figure can hide disagreement on the dropped claims
        - reports the escalation count, discarded-claim count and mean uncovered fraction
        - the model ids and prompt versions used are recorded in the report
        - miss_criterion_met is True only for zero misses on at least 60 seeded pairs in every list
        - false_alarm_ok is True only when every list flags at most FALSE_ALARM_CEILING of the
          unseeded pairs, so a harness that flags everything cannot pass
        - agreement_ok is True only when both agreement rates are known and at least AGREEMENT_BAR
        - default_gate_pass is True only when all three hold
        - identical_list_pairs counts pairs whose extractor lists came out the same, because the
          SDK has no temperature and two "independent" lists can be one list drawn twice

    Raises:
        - nothing
    """
    seeded   = [ r for r in results if r[ "seed_span" ] is not None ]
    unseeded = [ r for r in results if r[ "seed_span" ] is None ]
    lists    = []
    for slot in range( config.extractor_lists ):
        misses = sum( 1 for r in seeded if not caught( r[ "lists" ][ slot ], tuple( r[ "seed_span" ] ) ) )
        alarms = sum( 1 for r in unseeded if flagged( r[ "lists" ][ slot ] ) )
        lists.append( {
            "slot"              : slot,
            "positives"         : len( seeded ),
            "misses"            : misses,
            "upper_bound"       : upper_bound( misses, len( seeded ) ),
            "unseeded"          : len( unseeded ),
            "false_alarms"      : alarms,
            "false_alarm_rate"  : alarms / len( unseeded ) if unseeded else None,
        } )
    miss_ok = bool( seeded ) and len( seeded ) >= DEFAULT_POSITIVES_NEEDED and all( l[ "misses" ] == 0 for l in lists )
    fa_ok   = all( l[ "false_alarm_rate" ] is not None and l[ "false_alarm_rate" ] <= FALSE_ALARM_CEILING for l in lists )
    all_total = all_same = seed_total = seed_same = escalations = discarded = 0
    uncovered = []
    longest   = 0.0
    for r in results:
        for lst in r[ "lists" ]:
            discarded  += lst[ "discarded" ]
            uncovered.append( lst[ "uncovered" ] )
            longest = max( longest, lst[ "longest_quote" ] )
            escalations += sum( row[ "escalated" ] for run in lst[ "runs" ] for row in run )
            for claim, same in zip( lst[ "claims" ], unanimous( lst[ "runs" ] ) if lst[ "claims" ] else [] ):
                all_total += 1
                all_same  += same
                if r[ "seed_span" ] is not None and claim_extractor.spans_overlap( ( claim[ "start" ], claim[ "end" ] ), tuple( r[ "seed_span" ] ) ):
                    seed_total += 1
                    seed_same  += same
    agree_all  = all_same / all_total if all_total else None
    agree_seed = seed_same / seed_total if seed_total else None
    agree_ok   = agree_all is not None and agree_seed is not None and agree_all >= AGREEMENT_BAR and agree_seed >= AGREEMENT_BAR
    identical  = sum( 1 for r in results if len( { tuple( c[ "quote" ] for c in lst[ "claims" ] ) for lst in r[ "lists" ] } ) == 1 )
    return {
        "models"            : { "extractor": config.extractor_model, "judge": config.judge_model,
                                "escalation": config.escalation_model, "writer": config.writer_model },
        "prompt_versions"   : { "extractor": claim_extractor.PROMPT_VERSION, "judge": claim_judge.PROMPT_VERSION },
        "lists"             : lists,
        "agreement_all"     : { "same": all_same, "claims": all_total, "rate": all_same / all_total if all_total else None,
                                "interval": interval( all_same, all_total ) },
        "agreement_seeded"  : { "same": seed_same, "claims": seed_total, "rate": seed_same / seed_total if seed_total else None,
                                "interval": interval( seed_same, seed_total ) },
        "escalations"       : escalations,
        "discarded_claims"  : discarded,
        "longest_quote"     : longest,
        "mean_uncovered"    : sum( uncovered ) / len( uncovered ) if uncovered else None,
        "identical_list_pairs" : identical,
        "pairs"             : len( results ),
        "miss_criterion_met": miss_ok,
        "false_alarm_ok"    : fa_ok,
        "agreement_ok"      : agree_ok,
        "default_gate_pass" : miss_ok and fa_ok and agree_ok,
    }
