"""
The two agreements the trust gate records, kept apart.

Success is agreement with the forecast: the proxy's forecast and the human's answer say the same thing.
Rule agreement is agreement with the policy disposition: what the row's action implies, and the human's answer.
A human approval scores as success only when the forecast was "approved".
A deployment is forecast "requires_review", so its approval scores False today. That conflicts with the plan and is Rick's call.
A human approval scores as rule agreement when the action was act or suggest.

Mr. Radio's reading of "rule", for Rick to confirm (20 Nov 2026): the plan does not define it more precisely.

Dependency Rule:
    - Pure functions: no database, no I/O, no configuration.
"""

FORECAST_APPROVED = "approved"
IMPLIES_APPROVAL  = ( "act", "suggest" )


def forecast_agreement( forecast_value, user_answer ):
    """
    Say whether the human's answer agreed with the proxy's forecast.

    Requires:
        - forecast_value is the proxy's decision value, "approved" or anything else (None for a shadow row)
        - user_answer is True when the human approved, False when they did not

    Ensures:
        - returns True when the forecast was "approved" and the human approved
        - returns True when the forecast was anything else and the human did not approve
        - a human approval with no "approved" forecast returns False, as the orchestrator has always scored it
    """
    return ( forecast_value == FORECAST_APPROVED ) == user_answer


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
