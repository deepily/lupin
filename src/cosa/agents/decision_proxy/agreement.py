"""
The two agreements the trust gate records, kept apart.

Success is agreement with the forecast: the proxy's forecast and the human's answer say the same thing.
Rule agreement is agreement with the policy disposition: what the row's action implies, and the human's answer.
A human approval scores as success only when the forecast was "approved".
A forecast of "requires_review" asks for a human look, so a human approval of it scores as success too (20 Nov 2026).
A human approval scores as rule agreement when the action was act or suggest.

Mr. Radio's reading of "rule", for Rick to confirm (20 Nov 2026): the plan does not define it more precisely.

A neither answer is no ruling (Rick, 23 Nov 2026). It is passed as None and scores as neither agreement nor disagreement. It counts as a request to re-frame the question.

Dependency Rule:
    - Pure functions: no database, no I/O, no configuration.
"""

FORECAST_APPROVED        = "approved"
FORECAST_REQUIRES_REVIEW = "requires_review"
IMPLIES_APPROVAL  = ( "act", "suggest" )
THREE_WAY_STANCES = ( "yes", "no", "neither" )

REFRAME_WINDOW    = 20
REFRAME_BAR       = 0.1


def forecast_agreement( forecast_value, user_answer ):
    """
    Say whether the human's answer agreed with the proxy's forecast.

    Requires:
        - forecast_value is the proxy's decision value, "approved" or anything else (None for a shadow row)
        - user_answer is True when the human approved, False when they did not, or None for a neither (no ruling)

    Ensures:
        - returns None when user_answer is None: no ruling is neither agreement nor disagreement
        - returns True when the forecast was "approved" and the human approved
        - returns True when the forecast was anything else and the human did not approve
        - returns True when the forecast was "requires_review", whatever the human answered: the human looked, which is what it asked for
        - a human approval with any other forecast, or none, returns False, as the orchestrator has always scored it
    """
    if user_answer is None: return None
    if forecast_value == FORECAST_REQUIRES_REVIEW: return True
    return ( forecast_value == FORECAST_APPROVED ) == user_answer


def three_way_agreement( forecast_value, answer_stance ):
    """
    Say whether the human's answer stance matched a stored forecast's stance, in shadow.

    Requires:
        - forecast_value is a stored stance's value ("yes", "no" or "neither"), from either shadow source, or None when no forecast was stored
        - answer_stance is the human's answer stance ("yes", "no" or "neither"), or None when nobody human answered

    Ensures:
        - returns None when either side is missing or is not one of the three stances: nothing to compare
        - returns True when the two stances are the same, False when they differ (the stance comparison is accuracy_comparators.compare_yes_no's)
        - a comment on the answer does not change the stance scored
        - never feeds a trust counter: the caller records the result on the decision row only
    """
    if forecast_value not in THREE_WAY_STANCES or answer_stance not in THREE_WAY_STANCES: return None
    from cosa.agents.prediction_engine.accuracy_comparators import compare_yes_no
    return compare_yes_no( { "value": forecast_value }, { "value": answer_stance } )[ 0 ]


def rule_agreement( action, user_answer ):
    """
    Say whether the human's answer agreed with what the row's action implies.

    Requires:
        - action is the row's policy disposition: shadow, suggest, act or defer
        - user_answer is True, False, or None when no human answered

    Ensures:
        - returns None for a shadow row, a defer row, or a row nobody answered: the action implies no verdict, or there is no answer to compare
        - an act or suggest row implies approval: returns True when the human approved, False when they did not
        - the result is never folded into the forecast's success
    """
    if action not in IMPLIES_APPROVAL or user_answer is None: return None
    return bool( user_answer )


def reframe_rate( recent_stances ):
    """
    Say what share of a category's recent asks were answered neither, a request to re-frame.

    Requires:
        - recent_stances is a list of answer stances ("yes", "no", "neither" or None), oldest first

    Ensures:
        - only the last REFRAME_WINDOW entries count
        - returns neither-count divided by the entries counted, 0.0 for an empty list
    """
    window = recent_stances[ -REFRAME_WINDOW: ]
    if not window: return 0.0
    return window.count( "neither" ) / len( window )


def reframe_blocks_promotion( recent_stances ):
    """
    Say whether a category's re-frame rate is above the bar that blocks its promotion.

    Requires:
        - recent_stances is as reframe_rate takes it

    Ensures:
        - returns True when reframe_rate is strictly above REFRAME_BAR (a placeholder of 1 in 10, reset from the replay)
        - returns False at the bar exactly
    """
    return reframe_rate( recent_stances ) > REFRAME_BAR
