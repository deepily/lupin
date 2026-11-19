"""
Exposure rules for the forecast fold: unaided answer or switched answer.

Was the final answer given unaided, or after the forecast could have changed it?

The seen route stores the first fold-open time ( prediction_log.fold_opened_at ) and the answer controls' state at
that moment ( prediction_log.draft_at_reveal ). These pure functions turn those two values and the final answer
into one class per card, and a switch rate over many cards. Nothing here touches the database.
"""

from typing import Optional, Iterable

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


def classify_exposure( fold_opened_at, draft_at_reveal: Optional[dict], actual_value: Optional[dict],
                       answered_at=None ) -> str:
    """
    Classify one card's final answer against the draft taken when its forecast was revealed.

    Requires:
        - fold_opened_at: the first fold-open time, or None when the fold was never opened
        - draft_at_reveal: { "value": ... } or None when unknown
        - actual_value: the stored final answer { "value": ... }, or None when unanswered
        - answered_at: when the answer was stored ( the notification's responded_at ), or None when unknown

    Ensures:
        - returns the unanswered class when actual_value is None, whatever else is known
        - returns the unaided class when the fold was never opened, even if a draft is stored
        - returns the unaided class when the fold opened at or after answered_at: equal counts as too late
          to influence, the same way an equal time counts as known in the as-of rule
        - with a reveal and no draft, returns the exposed class
        - with a reveal and a draft, returns the unaided class when the two "value" entries are equal, else the switched class
        - compares the "value" entry only, so an answer's source or author never makes a switch
        - compares values with ==, so a list value is ordered: the same items in another order read as
          switched ( the seen route requires a "value" key in a draft, so a stored draft always has one )

    Raises:
        - KeyError if a given draft or answer holds no "value" entry
    """
    if actual_value is None: return UNANSWERED
    if not revealed_before_answer( fold_opened_at, answered_at ): return UNAIDED
    if draft_at_reveal is None: return EXPOSED
    return UNAIDED if draft_at_reveal[ "value" ] == actual_value[ "value" ] else SWITCHED


def switch_rate( classes: Iterable[str] ) -> Optional[float]:
    """
    Share of answered cards whose answer was switched after the reveal.

    Requires:
        - classes: values returned by classify_exposure

    Ensures:
        - unanswered entries are left out of numerator and denominator
        - returns the switched count over the count of the remaining entries, rounded to 4 places
        - returns None when no answered entry remains
    """
    answered = [ c for c in classes if c != UNANSWERED ]
    if not answered: return None
    return round( answered.count( SWITCHED ) / len( answered ), 4 )
