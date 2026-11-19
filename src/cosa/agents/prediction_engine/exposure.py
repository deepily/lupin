"""
Exposure rules for the forecast fold: unaided answer or switched answer.

Was the final answer given unaided, or after the forecast could have changed it?

The seen route stores the first fold-open time ( prediction_log.fold_opened_at ) and the answer controls' state at
that moment ( prediction_log.draft_at_reveal ). These pure functions turn those two values and the final answer
into one class per card, and a switch rate over many cards. Nothing here touches the database.

An answer and a draft reach this module in four stored forms, all read by decode_answer_fields:

- the wire string the client sends: "yes", "no [comment: text]", or JSON text { "answers": { header: pick or [picks] } };
- the notification's response_value: { "value": <wire string>, "source": "ui", "answered_by": { ... } };
- prediction_log.actual_value for a yes/no or open-ended card: { "value": <wire string> };
- prediction_log.actual_value for a multiple-choice or batch card: { "answers": { ... } }, already decoded by record_outcome.

A draft at reveal is stored as { "value": <the wire string the submit button would send with the controls as they stand> }.
"""

from typing import Optional, Iterable, Tuple

from cosa.utils.notification_utils import extract_qualifier_comment, parse_field_selections

WHOLE_ANSWER_KEY = "$answer"   # the field key of a yes/no or open-ended answer; a card field uses its header
FIELD_TYPES      = ( "multiple_choice", "open_ended_batch" )
TEXT_TYPES       = ( "yes_no", "open_ended" )
SAME             = "same"        # a field the draft already held, with the same picks
UNDRAFTED        = "undrafted"   # a field answered after the reveal that the draft did not hold
UNREADABLE       = "unreadable"  # a draft or answer that could not be decoded

UNAIDED    = "unaided"      # no reveal, or the final answer equals the draft taken at reveal
SWITCHED   = "switched"     # the final answer differs from the draft taken at reveal
EXPOSED    = "exposed"      # revealed, but no draft was sent: cannot tell, counts as exposed
UNANSWERED = "unanswered"   # no final answer yet, so there is nothing to classify


def revealed_before_answer( fold_opened_at, answered_at ) -> bool:
    """
    Say whether a reveal came early enough to influence the answer.

    Requires:
        - fold_opened_at and answered_at are comparable moments, or None

    Ensures:
        - returns False when the fold was never opened
        - returns True when the fold opened and answered_at is unknown
        - returns True only when the reveal is strictly before answered_at; an equal time is too late to influence
    """
    if fold_opened_at is None: return False
    return answered_at is None or fold_opened_at < answered_at


def decode_answer_fields( response_type, stored ):
    """
    Decode an answer or a draft, in any stored form, into the picks it holds per field.

    Requires:
        - response_type is yes_no, multiple_choice, open_ended_batch or open_ended
        - stored is None, or a dict in one of the forms the module docstring lists

    Ensures:
        - returns None for any other response type, so a type added later is never read as free text unnoticed
        - returns { field_key: tuple of picks }, or None when a card answer holds no readable answers map
        - yes_no: one entry under the whole-answer key holding the stance ( yes, no or neither, lower case ), so a
          comment added or changed after the reveal is not a different answer; unreadable text is kept as typed, and
          nothing chosen is the empty tuple
        - open_ended: one entry under the whole-answer key holding the stripped text, or the empty tuple
        - multiple_choice and open_ended_batch: one entry per header, its picks sorted, so the order of a multi-select
          does not matter; a blank pick is dropped; a field with no picks is the empty tuple
        - a stored value of None, or a dict with no value and no answers, is the empty answer: yes_no and open_ended give
          the whole-answer key with an empty tuple, a card gives {}
        - the dict's other keys ( source, answered_by ) are ignored
    """
    if response_type not in FIELD_TYPES and response_type not in TEXT_TYPES: return None
    if response_type in FIELD_TYPES:
        if stored is None: return {}
        fields = parse_field_selections( stored )
        if fields is None: return None
        return { header: tuple( sorted( str( pick ) for pick in record[ "selected" ] if str( pick ).strip() ) ) for header, record in fields.items() }
    text = stored.get( "value" ) if isinstance( stored, dict ) else None
    text = text.strip() if isinstance( text, str ) else ""
    if response_type == "yes_no":
        stance = extract_qualifier_comment( text )[ 0 ]
        picks  = ( stance, ) if stance else ( ( text, ) if text else () )
    else:
        picks  = ( text, ) if text else ()
    return { WHOLE_ANSWER_KEY: picks }


def compare_draft_to_answer( response_type, draft_at_reveal, actual_value ):
    """
    Compare the draft taken at reveal with the final answer, field by field.

    Requires:
        - response_type is as decode_answer_fields takes it
        - draft_at_reveal and actual_value are None or stored in a form decode_answer_fields reads

    Ensures:
        - returns { "outcome", "fields" }; fields maps each field the final answer or the draft holds to same,
          switched or undrafted, and leaves out a field that neither holds
        - a field is same when the draft held picks and the final answer holds the same picks
        - a field is switched when the draft held picks and the final picks differ, including none at all
        - a field is undrafted when the draft held no picks for it and the final answer holds some: it was answered
          after the reveal
        - outcome is unreadable when either side cannot be decoded, and fields is then empty
        - otherwise outcome is switched when any field is switched, else undrafted when any field is undrafted or
          no field is held at all, else same
        - the same comparison serves the per-card summary and the extractor, so a draft is read one way
    """
    draft  = decode_answer_fields( response_type, draft_at_reveal )
    final  = decode_answer_fields( response_type, actual_value )
    if draft is None or final is None: return { "outcome": UNREADABLE, "fields": {} }
    fields = {}
    for key in list( final ) + [ key for key in draft if key not in final ]:
        before, after = draft.get( key, () ), final.get( key, () )
        if not before and not after: continue
        fields[ key ] = UNDRAFTED if not before else ( SAME if before == after else SWITCHED )
    states = set( fields.values() )
    if SWITCHED in states: outcome = SWITCHED
    elif UNDRAFTED in states or not states: outcome = UNDRAFTED
    else: outcome = SAME
    return { "outcome": outcome, "fields": fields }


def classify_exposure( fold_opened_at, draft_at_reveal: Optional[dict], actual_value: Optional[dict],
                       *, response_type, answered_at=None ) -> str:
    """
    Classify one card's final answer against the draft taken when its forecast was revealed.

    Requires:
        - fold_opened_at: the first fold-open time, or None when the fold was never opened
        - draft_at_reveal: the stored draft, or None when unknown
        - actual_value: the stored final answer, in a form decode_answer_fields reads, or None when unanswered
        - response_type: the card's response type, passed by keyword
        - answered_at, passed by keyword: when the answer was stored ( the notification's responded_at ), or None when unknown

    Ensures:
        - returns the unanswered class when actual_value is None, whatever else is known
        - returns the unaided class when the fold was never opened, even if a draft is stored
        - returns the unaided class when the fold opened at or after answered_at: equal counts as too late
          to influence, the same way an equal time counts as known in the as-of rule
        - with a reveal and no draft, returns the exposed class
        - with a reveal and a draft, reads compare_draft_to_answer: switched gives the switched class, same gives the
          unaided class, and undrafted or unreadable gives the exposed class, because the answer ( or part of it ) was
          formed after the reveal and cannot be told from an influenced one
        - an answer's source or author never makes a switch
    """
    if actual_value is None: return UNANSWERED
    if not revealed_before_answer( fold_opened_at, answered_at ): return UNAIDED
    if draft_at_reveal is None: return EXPOSED
    outcome = compare_draft_to_answer( response_type, draft_at_reveal, actual_value )[ "outcome" ]
    return { SWITCHED: SWITCHED, SAME: UNAIDED }.get( outcome, EXPOSED )


def switch_rate( cards: Iterable[Tuple[str, bool]] ) -> Optional[float]:
    """
    Share of the cards whose switch could be measured that were switched.

    Requires:
        - cards: ( class, revealed ) pairs, the class from classify_exposure and revealed from revealed_before_answer

    Ensures:
        - a card is measured when it was switched, or was revealed in time and left unaided with a draft equal to its answer
        - the exposed class, an unrevealed card and an unanswered card are left out of both counts
        - returns the switched count over the measured count, rounded to 4 places
        - returns None when no card was measured
    """
    cards    = list( cards )
    switched = sum( 1 for cls, _ in cards if cls == SWITCHED )
    measured = switched + sum( 1 for cls, revealed in cards if cls == UNAIDED and revealed )
    return round( switched / measured, 4 ) if measured else None
