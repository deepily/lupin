"""
The numbers of the judge harness exit gate (plan 1, section 5).

All of it is plain arithmetic over the runner's results. It counts the seeded removals that
slipped past, with a one-sided 95% upper bound. It counts the untouched pairs that were flagged.
It measures how often the three judge runs agree on a claim. It reports how much of the old
text no verified quote covers.
"""

from scipy.stats import beta

from . import claim_extractor, claim_judge, history_class

DEFAULT_POSITIVES_NEEDED = 60
AGREEMENT_BAR            = 0.95
FALSE_ALARM_CEILING      = 0.10
FLAGGED_CEILING          = 0.15
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
        - True when a claim judged dropped has a verified quote that overlaps the seed span, or when
          a run flagged for a person overlaps it (the flagged-run rule)
        - a list whose first reply was unreadable (parse_failed) never catches: its flag covers the whole old
          text, which would overlap every span, so it is its own outcome and a miss here
        - a flagged claim or run elsewhere does not count, and a seeded claim the extractor never
          listed, with no flagged run on it, is a miss
    """
    if claim_list[ "parse_failed" ]: return False
    flags = final_absent( claim_list[ "runs" ] ) if claim_list[ "claims" ] else []
    return run_flagged( claim_list, seed_span ) or any( flag and claim_extractor.spans_overlap( ( c[ "start" ], c[ "end" ] ), seed_span )
                                                         for flag, c in zip( flags, claim_list[ "claims" ] ) )


def drop_tags( claim_list ):
    """
    List one extractor list's dropped claims and say which look like history.

    Requires:
        - claim_list is a run_pair list entry

    Ensures:
        - returns ( dropped, tagged ): the indexes of every claim judged dropped, and ( index, kinds ) for the
          ones tagged as history; see history_class
        - the tag excuses nothing: tagged is a subset of dropped
        - an empty claim list gives two empty lists
        - it never changes final_absent, caught or flagged, so the gate figures are measured as before
    """
    if not claim_list[ "claims" ]: return [], []
    return history_class.tag_absent( claim_list[ "claims" ], final_absent( claim_list[ "runs" ] ) )


def run_flagged( claim_list, seed_span ):
    """Say whether a flagged run of an extractor list overlaps a seed span."""
    return any( claim_extractor.spans_overlap( tuple( f ), seed_span ) for f in claim_list[ "flags" ] )


def discarded_on( claim_list, seed_span ):
    """Say whether a discarded quote of an extractor list overlaps a seed span."""
    return any( d[ "start" ] is not None and claim_extractor.spans_overlap( ( d[ "start" ], d[ "end" ] ), seed_span ) for d in claim_list[ "discards" ] )


def flagged( claim_list ):
    """Say whether a judge dropped any claim of an extractor list (a false alarm if unseeded)."""
    return bool( claim_list[ "claims" ] ) and any( final_absent( claim_list[ "runs" ] ) )


def run_flagged_pair( claim_list ):
    """
    Say whether an extractor list has a run of old text flagged for a person, judge aside.

    Ensures:
        - a list whose extractor reply was unreadable (parse_failed) is not a flagged-run pair: its whole-text flag
          is a parse failure, counted apart, so it neither feeds flagged_rate nor flag-only catches
    """
    return bool( claim_list[ "flags" ] ) and not claim_list[ "parse_failed" ]


def call_timing( results ):
    """
    Sum recorded model-call time and call counts by stage over every result.

    Requires:
        - results come from run_all; a result with no "timing" (a report rebuilt from an older run) adds nothing

    Ensures:
        - returns { "stages": { stage: { "seconds", "calls" } }, "untimed_rows" }; a row resumed from the ledger
          is in the totals with its recorded time, and a row with no recorded time is only counted in untimed_rows
    """
    stages  = {}
    untimed = 0
    for r in results:
        timing   = r.get( "timing" )
        if timing is None: continue
        untimed += timing[ "untimed_rows" ]
        for stage, entry in timing[ "stages" ].items():
            total = stages.setdefault( stage, { "seconds": 0.0, "calls": 0 } )
            total[ "seconds" ] += entry[ "seconds" ]
            total[ "calls" ]   += entry[ "calls" ]
    return { "stages": stages, "untimed_rows": untimed }


def build_report( results, config, judge_prompt_version=None, jev_run=False ):
    """
    Turn runner results into the exit-gate figures.

    Requires:
        - results come from run_all with the same config
        - judge_prompt_version, when given, is the judge back end's version (a Jev run), recorded in place of the Claude judge's
        - jev_run is True when the judge back end was Jev, so rows without a probability are counted
        - a result with a seed_span is a seeded-removal pair; the others are unseeded

    Ensures:
        - per extractor list: misses, false alarms, and whether each meets its criterion, so a criterion must hold on every list and not on one lucky draw
        - agreement is reported over all claims and over claims overlapping a seed span, each with its interval, because an overall figure can hide disagreement on the dropped claims
        - parse_failed_pairs counts, per list, the pairs whose extractor reply stayed unreadable after one retry (top level: the largest list); retry_calls counts the retries; such a pair is never a catch, never a flag-only catch, and stays out of flagged_pairs, flagged_rate and mean_flag_words; an unseeded one is in review_pairs
        - reports the escalation count, discarded-claim count (and per code) and mean uncovered fraction
        - per list: seeded_span_discarded counts seeded pairs where a discarded quote overlaps the span (the harness threw the claim away, the extractor did list it), flagged_pairs and flagged_rate count unseeded pairs with a run flagged for a person, mean_flag_words is the mean length of a flagged run, review_rate is the share of unseeded pairs a person would look at (judge false alarm or flag, no ceiling), and caught_by_flag_only counts seeded pairs caught by a flag alone; the top-level seeded_span_discarded, flagged_rate and review_rate are the largest over the lists
        - false_alarm_rate counts the judge's false alarms only; a flagged run is counted apart, in flagged_rate, and flagged_ok is True only when every list's flagged_rate is at most FLAGGED_CEILING (provisional)
        - the model ids and prompt versions used are recorded in the report
        - history_class carries the class version and, per list, claims_lost (every claim judged dropped: nothing is excused) and the tagged count, the dropped claims that look like history; tagged_claims lists each tagged claim with its pair, list, text, quote and kinds, for a person to read. The gate figures above use every dropped claim, as before
        - miss_criterion_met is True only for zero misses on at least 60 seeded pairs in every list
        - false_alarm_ok is True only when every list flags at most FALSE_ALARM_CEILING of the unseeded pairs, so a harness that flags everything cannot pass
        - agreement_ok is True only when both agreement rates are known and at least AGREEMENT_BAR
        - default_gate_pass is True only when all four hold (miss, false alarm, flagged, agreement), and, on a jev_run, only when no claim went without a Jev answer
        - judge_unanswered counts the claim verdicts, over all lists and runs, that carry no Jev probability: Jev gave no answer and the escalation model decided under Jev's name. It is None on a run that did not use Jev
        - call_timing holds per-stage (extractor, judge, escalation) seconds and call counts over the whole run, resumed rows included at their recorded time, and judge_thinking records the setting the judge ran under
        - identical_list_pairs counts pairs whose extractor lists came out the same, because the SDK has no temperature and two "independent" lists can be one list drawn twice

    Raises:
        - nothing
    """
    seeded   = [ r for r in results if r[ "seed_span" ] is not None ]
    unseeded = [ r for r in results if r[ "seed_span" ] is None ]
    lists    = []
    for slot in range( config.extractor_lists ):
        misses = sum( 1 for r in seeded if not caught( r[ "lists" ][ slot ], tuple( r[ "seed_span" ] ) ) )
        alarms = sum( 1 for r in unseeded if flagged( r[ "lists" ][ slot ] ) )
        flag_pairs = sum( 1 for r in unseeded if run_flagged_pair( r[ "lists" ][ slot ] ) )
        review     = sum( 1 for r in unseeded if flagged( r[ "lists" ][ slot ] ) or run_flagged_pair( r[ "lists" ][ slot ] ) or r[ "lists" ][ slot ][ "parse_failed" ] )
        words      = [ w for r in results if not r[ "lists" ][ slot ][ "parse_failed" ] for w in r[ "lists" ][ slot ][ "flag_words" ] ]
        flag_only  = sum( 1 for r in seeded if not r[ "lists" ][ slot ][ "parse_failed" ] and run_flagged( r[ "lists" ][ slot ], tuple( r[ "seed_span" ] ) )
                          and not caught( dict( r[ "lists" ][ slot ], flags=[] ), tuple( r[ "seed_span" ] ) ) )
        lists.append( {
            "slot"              : slot,
            "positives"         : len( seeded ),
            "misses"            : misses,
            "upper_bound"       : upper_bound( misses, len( seeded ) ),
            "unseeded"          : len( unseeded ),
            "false_alarms"      : alarms,
            "false_alarm_rate"  : alarms / len( unseeded ) if unseeded else None,
            "seeded_span_discarded" : sum( 1 for r in seeded if discarded_on( r[ "lists" ][ slot ], tuple( r[ "seed_span" ] ) ) ),
            "flagged_pairs"     : flag_pairs,
            "flagged_rate"      : flag_pairs / len( unseeded ) if unseeded else None,
            "mean_flag_words"   : sum( words ) / len( words ) if words else None,
            "review_pairs"      : review,
            "review_rate"       : review / len( unseeded ) if unseeded else None,
            "caught_by_flag_only": flag_only,
            "parse_failed_pairs": sum( 1 for r in results if r[ "lists" ][ slot ][ "parse_failed" ] ),
            "claims_lost"       : sum( len( drop_tags( r[ "lists" ][ slot ] )[ 0 ] ) for r in results ),
            "history_tagged"    : sum( len( drop_tags( r[ "lists" ][ slot ] )[ 1 ] ) for r in results ),
        } )
    miss_ok = bool( seeded ) and len( seeded ) >= DEFAULT_POSITIVES_NEEDED and all( l[ "misses" ] == 0 for l in lists )
    fa_ok   = all( l[ "false_alarm_rate" ] is not None and l[ "false_alarm_rate" ] <= FALSE_ALARM_CEILING for l in lists )
    flag_ok = all( l[ "flagged_rate" ] is not None and l[ "flagged_rate" ] <= FLAGGED_CEILING for l in lists )
    all_words = [ w for r in results for lst in r[ "lists" ] if not lst[ "parse_failed" ] for w in lst[ "flag_words" ] ]
    all_total = all_same = seed_total = seed_same = escalations = discarded = reextract_calls = 0
    codes     = { code: 0 for code in claim_extractor.DISCARD_CODES }
    uncovered = []
    longest   = 0.0
    for r in results:
        for lst in r[ "lists" ]:
            discarded  += lst[ "discarded" ]
            reextract_calls += lst[ "reextract_calls" ]
            for d in lst[ "discards" ]: codes[ d[ "code" ] ] += 1
            uncovered.append( lst[ "uncovered" ] )
            longest = max( longest, lst[ "longest_quote" ] )
            escalations += sum( row[ "escalated" ] for run in lst[ "runs" ] for row in run )
            for claim, same in zip( lst[ "claims" ], unanimous( lst[ "runs" ] ) if lst[ "claims" ] else [] ):
                all_total += 1
                all_same  += same
                if r[ "seed_span" ] is not None and claim_extractor.spans_overlap( ( claim[ "start" ], claim[ "end" ] ), tuple( r[ "seed_span" ] ) ):
                    seed_total += 1
                    seed_same  += same
    tagged_claims = [ { "pair": r[ "id" ], "list": slot, "claim": lst[ "claims" ][ i ][ "text" ], "quote": lst[ "claims" ][ i ][ "quote" ], "kinds": kinds }
                      for r in results for slot, lst in enumerate( r[ "lists" ] ) for i, kinds in drop_tags( lst )[ 1 ] ]
    agree_all  = all_same / all_total if all_total else None
    agree_seed = seed_same / seed_total if seed_total else None
    agree_ok   = agree_all is not None and agree_seed is not None and agree_all >= AGREEMENT_BAR and agree_seed >= AGREEMENT_BAR
    unanswered = sum( 1 for r in results for lst in r[ "lists" ] for run in lst[ "runs" ] for row in run if row[ "noul" ] is None ) if jev_run else None
    identical  = sum( 1 for r in results if len( { tuple( c[ "quote" ] for c in lst[ "claims" ] ) for lst in r[ "lists" ] } ) == 1 )
    return {
        "models"            : { "extractor": config.extractor_model, "judge": config.judge_model,
                                "escalation": config.escalation_model, "writer": config.writer_model },
        "prompt_versions"   : { "extractor": claim_extractor.PROMPT_VERSION, "judge": claim_judge.PROMPT_VERSION if judge_prompt_version is None else judge_prompt_version },
        "lists"             : lists,
        "agreement_all"     : { "same": all_same, "claims": all_total, "rate": all_same / all_total if all_total else None,
                                "interval": interval( all_same, all_total ) },
        "agreement_seeded"  : { "same": seed_same, "claims": seed_total, "rate": seed_same / seed_total if seed_total else None,
                                "interval": interval( seed_same, seed_total ) },
        "escalations"       : escalations,
        "discarded_claims"  : discarded,
        "discard_codes"     : codes,
        "seeded_span_discarded" : max( ( l[ "seeded_span_discarded" ] for l in lists ), default=0 ),
        "flagged_rate"      : max( ( l[ "flagged_rate" ] for l in lists if l[ "flagged_rate" ] is not None ), default=None ),
        "mean_flag_words"   : sum( all_words ) / len( all_words ) if all_words else None,
        "review_rate"       : max( ( l[ "review_rate" ] for l in lists if l[ "review_rate" ] is not None ), default=None ),
        "reextract_calls"   : reextract_calls,
        "retry_calls"       : sum( lst[ "retry_calls" ] for r in results for lst in r[ "lists" ] ),
        "parse_failed_pairs": max( ( l[ "parse_failed_pairs" ] for l in lists ), default=0 ),
        "longest_quote"     : longest,
        "mean_uncovered"    : sum( uncovered ) / len( uncovered ) if uncovered else None,
        "identical_list_pairs" : identical,
        "history_class"     : { "version": history_class.HISTORY_CLASS_VERSION,
                                "lost": [ l[ "claims_lost" ] for l in lists ], "tagged": [ l[ "history_tagged" ] for l in lists ],
                                "tagged_claims": tagged_claims },
        "pairs"             : len( results ),
        "call_timing"       : call_timing( results ),
        "judge_thinking"    : config.judge_thinking,
        "miss_criterion_met": miss_ok,
        "false_alarm_ok"    : fa_ok,
        "flagged_ok"        : flag_ok,
        "agreement_ok"      : agree_ok,
        "judge_unanswered"  : unanswered,
        "default_gate_pass" : miss_ok and fa_ok and flag_ok and agree_ok and not unanswered,
    }
