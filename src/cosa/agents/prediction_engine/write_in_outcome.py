"""
The write-in outcome: a per-field forecast that Rick will type his own answer.

On 469 of 1,154 answered multiple-choice cards, at least one field got a typed write-in. The full-answer reply never named one.
This module adds one probability to each option field of a multiple-choice full-answer reply. It is ``write_in_probability``,
the chance that the field's answer is typed rather than picked from the offered options.

It is a separate module, not a change to ``full_answer``. So with its switch off, the full-answer prompt, the parser and the
``context_baseline.predictor_version`` string stay exactly what they were. ``context_baseline`` adds this module's source to
the version only while the switch is on. The forecast's selection and its labels are unchanged; the outcome sits beside them.

The switch is ``prediction engine full answer write in outcome enabled``, default off. It is read only when the full-answer
switch is on too.
"""

import collections

from cosa.agents.io_models.utils.json_object_recovery import recover_json_object
from cosa.agents.prediction_engine import full_answer
from cosa.config.configuration_manager import ConfigurationManager
from cosa.config.switch_reader import read_switch

SWITCH_KEY       = "prediction engine full answer write in outcome enabled"
PROBABILITY_KEY  = "write_in_probability"
OUTCOME_KEY      = "write_in_outcomes"
PREDICTED_AT     = 0.5
FORMAT_NOTE      = ( ' Beside the selection, every field also takes "' + PROBABILITY_KEY + '": p, the chance they type their own answer'
                     " for that field instead of picking an offered option, for example"
                     ' {"option_ids": ["<option id>"], "' + PROBABILITY_KEY + '": 0.1}.' )


def write_in_outcome_enabled():
    """
    Say whether the write-in outcome is switched on.

    Ensures:
        - returns True only when the INI key named by SWITCH_KEY is true; an unreadable setting reads as off and never raises
    """
    return read_switch( lambda env_var_name: ConfigurationManager( env_var_name=env_var_name ), SWITCH_KEY, False,
                        lambda settings_error: f"[WRITE-IN-OUTCOME] ⚠️ Switch '{SWITCH_KEY}' unreadable, treated as off: {settings_error}" )


def with_note( prompt, episode ):
    """
    Add the write-in outcome to a full-answer prompt.

    Requires:
        - prompt is context_baseline.build_full_user_prompt's text for the card; episode is episode_view's result for it

    Ensures:
        - a multiple-choice card's prompt gains FORMAT_NOTE at its end, so the request sits with the reply format
        - any other card's prompt comes back unchanged
    """
    return prompt + FORMAT_NOTE if episode[ "response_type" ] == "multiple_choice" else prompt


def attach( text, episode, record ):
    """
    Read each option field's write-in probability and put it on the forecast record.

    Requires:
        - text is the model's reply; record is full_answer.parse_full_reply's record for the same reply and episode

    Ensures:
        - for a multiple-choice card, returns record with record[ "fields" ][ key ][ PROBABILITY_KEY ] set for every forecast field,
          and record[ OUTCOME_KEY ] mapping each field key to that probability; the selection and "answers" are unchanged
        - a field is found in the reply under the same names full_answer accepts for it
        - for any other card type, returns record unchanged
        - record is changed in place and returned

    Raises:
        - full_answer.ReplyRefused( field_missing ) when a forecast field's entry has no write_in_probability
        - full_answer.ReplyRefused( probabilities_not_normalised ) when it is not a number from 0 to 1
    """
    if episode[ "response_type" ] != "multiple_choice": return record
    given    = recover_json_object( text )[ "fields" ]   # parse_full_reply already read this reply, so both are present
    owners   = collections.Counter( name for field in episode[ "fields" ] for name in full_answer._names_of( field ) )
    outcomes = {}
    for field in episode[ "fields" ]:
        if field[ "key" ] not in record[ "fields" ]: continue
        entry = given[ full_answer._reply_key( field, given, owners ) ]
        if PROBABILITY_KEY not in entry: raise full_answer.ReplyRefused( full_answer.REASON_FIELD_MISSING, f"field {field[ 'key' ]!r} has no {PROBABILITY_KEY}" )
        probability                                             = full_answer._probability( entry[ PROBABILITY_KEY ], f"field {field[ 'key' ]!r} {PROBABILITY_KEY}" )
        record[ "fields" ][ field[ "key" ] ][ PROBABILITY_KEY ] = probability
        outcomes[ field[ "key" ] ]                              = probability
    record[ OUTCOME_KEY ] = outcomes
    return record


def field_outcomes( forecast, actual_fields ):
    """
    Pair each answered option field's write-in forecast with whether Rick typed it.

    Requires:
        - forecast is a forecast record, or None for an abstention
        - actual_fields is compare_multiple_choice's detail[ "fields" ] with per_field True: one score_field record per header the
          answer has, each with "header" and "outcome"

    Ensures:
        - returns one { header, probability, predicted, actual } per actual field whose header the forecast gave a probability
        - actual is True when the field's outcome is other_write_in; predicted is True when the probability is at least PREDICTED_AT
        - a forecast with no OUTCOME_KEY (an abstention, or a version without the outcome) gives an empty list
    """
    if forecast is None or OUTCOME_KEY not in forecast: return []
    outcomes = forecast[ OUTCOME_KEY ]
    return [ { "header": f[ "header" ], "probability": outcomes[ f[ "header" ] ], "predicted": outcomes[ f[ "header" ] ] >= PREDICTED_AT,
               "actual": f[ "outcome" ] == "other_write_in" } for f in actual_fields if f[ "header" ] in outcomes ]


def precision_recall( pairs ):
    """
    Score write-in forecasts against what Rick did, field by field.

    Requires:
        - pairs is a list of field_outcomes records

    Ensures:
        - returns { fields, actual, predicted, true_positive, precision, recall, brier }
        - precision is true_positive over predicted and recall is true_positive over actual, each None with a zero denominator
        - brier is the mean squared gap between probability and actual (1 or 0), None with no fields
    """
    actual    = sum( 1 for pair in pairs if pair[ "actual" ] )
    predicted = sum( 1 for pair in pairs if pair[ "predicted" ] )
    hits      = sum( 1 for pair in pairs if pair[ "predicted" ] and pair[ "actual" ] )
    return {
        "fields"        : len( pairs ),
        "actual"        : actual,
        "predicted"     : predicted,
        "true_positive" : hits,
        "precision"     : hits / predicted if predicted else None,
        "recall"        : hits / actual if actual else None,
        "brier"         : sum( ( pair[ "probability" ] - ( 1.0 if pair[ "actual" ] else 0.0 ) ) ** 2 for pair in pairs ) / len( pairs ) if pairs else None,
    }
