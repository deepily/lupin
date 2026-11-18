"""
Retune the two retrieval settings on a tune window and score them on a final window.

The grid is the plan's: a similarity threshold from 0.50 to 0.90 and a top k of 3, 5, 8 or 10. Each
point replays the live engine over every eligible ask. The first 70 percent of the asks, in time order,
are the tune window and the last 30 percent are the final window. The point with the most correct
forecasts per 100 asks on the tune window wins. The final window only reports how it did.

The open-ended settings are not touched here; free text has too few asks to tune.
"""

from cosa.agents.prediction_engine.config import RESPONSE_TYPE_MULTIPLE_CHOICE, RESPONSE_TYPE_YES_NO
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, replay

ELIGIBLE_TYPES  = ( RESPONSE_TYPE_YES_NO, RESPONSE_TYPE_MULTIPLE_CHOICE )
TUNE_FRACTION   = 0.7
THRESHOLDS      = tuple( round( 0.50 + 0.05 * step, 2 ) for step in range( 9 ) )
TOP_KS          = ( 3, 5, 8, 10 )
FROZEN_METRIC   = "cosine"
THRESHOLD_KEY   = "prediction engine cbr similarity threshold"
TOP_K_KEY       = "prediction engine cbr top k"
METRIC_KEY      = "prediction engine retrieval metric"


def eligible_asks( asks ):
    """
    Keep the asks the two retuned settings serve.

    Requires:
        - asks is a list of ask dicts with response_type and a question_embedding

    Ensures:
        - returns the yes/no and multiple-choice asks that carry a stored vector, in input order
    """
    return [ ask for ask in asks if ask[ "response_type" ] in ELIGIBLE_TYPES and ask[ "question_embedding" ] is not None ]


def split_windows( count, tune_fraction=TUNE_FRACTION ):
    """
    Split a time-ordered run into a tune window and a final window by position.

    Requires:
        - count is the number of eligible asks, replayed in time order
        - 0 < tune_fraction < 1

    Ensures:
        - returns ( tune_size, final_size ) with tune_size the floor of count times tune_fraction
        - the two sizes add up to count
    """
    tune = int( count * tune_fraction )
    return tune, count - tune


def grid( thresholds=THRESHOLDS, top_ks=TOP_KS ):
    """
    List the grid points in the order they are tried.

    Requires:
        - thresholds and top_ks are sequences of numbers

    Ensures:
        - returns ( threshold, top_k ) pairs, thresholds ascending within each top k
    """
    return [ ( threshold, top_k ) for top_k in top_ks for threshold in thresholds ]


def _per_hundred( correct, total ):
    """
    Express a correct count as correct forecasts per 100 asks.

    Requires:
        - 0 <= correct <= total

    Ensures:
        - returns 0.0 for an empty window, else 100 times the share, so an abstention costs a point
    """
    return 0.0 if total == 0 else round( 100.0 * correct / total, 4 )


def retune( asks, engine, snapshot_sha256, thresholds=THRESHOLDS, top_ks=TOP_KS, tune_fraction=TUNE_FRACTION ):
    """
    Try every grid point and name the best one on the tune window.

    Requires:
        - asks is the full list of ask dicts replay takes
        - engine is a PredictionEngine; its threshold, top k and metric are set for each point and put back after

    Ensures:
        - replays the eligible asks once per grid point under the cosine metric, forecasts only from earlier answers
        - returns { points, best, tune_size, final_size, eligible, tune_cohort_sha256 }
        - each point holds threshold, top_k, tune_correct, tune_per_100, final_correct and final_per_100
        - best is the point with the highest tune_per_100; a tie goes to the higher threshold, then the smaller top k
        - tune_cohort_sha256 is the checksum of the tune window's ask ids in time order
        - the engine's three settings are restored, even when a replay raises

    Raises:
        - ValueError when there are no eligible asks
    """
    eligible = eligible_asks( asks )
    if not eligible: raise ValueError( "no eligible asks: the retune needs yes/no or multiple-choice asks with a stored vector" )
    saved = ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric )
    points = []
    try:
        engine.retrieval_metric = FROZEN_METRIC
        for threshold, top_k in grid( thresholds, top_ks ):
            engine.similarity_threshold = threshold
            engine.cbr_top_k            = top_k
            run     = replay( asks, engine, snapshot_sha256, baselines={}, target_types=ELIGIBLE_TYPES )
            records = run[ "records" ][ ENGINE_ARM ]
            tune_size, final_size = split_windows( len( records ), tune_fraction )
            tune_correct  = sum( 1 for r in records[ :tune_size ] if r[ "meta" ][ "correct" ] )
            final_correct = sum( 1 for r in records[ tune_size: ] if r[ "meta" ][ "correct" ] )
            points.append( {
                "threshold"     : threshold,
                "top_k"         : top_k,
                "tune_correct"  : tune_correct,
                "tune_per_100"  : _per_hundred( tune_correct, tune_size ),
                "final_correct" : final_correct,
                "final_per_100" : _per_hundred( final_correct, final_size ),
            } )
            ids = [ r[ "meta" ][ "notification_id" ] for r in records[ :tune_size ] ]
    finally:
        engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric = saved
    best = sorted( points, key=lambda p: ( -p[ "tune_per_100" ], -p[ "threshold" ], p[ "top_k" ] ) )[ 0 ]
    return {
        "points"             : points,
        "best"               : best,
        "tune_size"          : tune_size,
        "final_size"         : final_size,
        "eligible"           : len( records ),
        "tune_cohort_sha256" : sha256_of_rows( [ { "id": i } for i in ids ] ),
    }


def frozen_settings( result ):
    """
    Name the INI values a retune freezes.

    Requires:
        - result is the dict retune returns

    Ensures:
        - returns the threshold, the top k and the cosine metric keyed by their INI names
        - leaves the open-ended keys out
    """
    return {
        THRESHOLD_KEY : result[ "best" ][ "threshold" ],
        TOP_K_KEY     : result[ "best" ][ "top_k" ],
        METRIC_KEY    : FROZEN_METRIC,
    }
