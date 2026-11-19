"""
The review-card marker: the ask-time field that marks an ask as the learner's question.

A review card asks Rick to rule on a contested principle. Its answer is a ruling and not an answer to a
real ask. So it is never forecast, scored, stored as a case or read by the extractor.

The marker is the key `review_card`, set to true in the ask's `response_options` when the card is created.
Every filter reads it from the ask and from nothing else. A copy on the stored answer can be lost when an
answer arrives another way, so nothing depends on one.
"""
import json
from typing import Any

REVIEW_CARD_KEY    = "review_card"
REVIEW_CARD_SOURCE = "review_card"


def is_review_card( response_options: Any ) -> bool:
    """
    Say whether an ask carries the review-card marker.

    Requires:
        - response_options is the ask's stored schema: a dict, a string, or None

    Ensures:
        - returns True only when the schema is an object whose review_card key is exactly True
        - returns False for None, a list, text that is not JSON, JSON that is not an object, and any other value of the key
    """
    if isinstance( response_options, str ):
        try: response_options = json.loads( response_options )
        except json.JSONDecodeError: return False
    return isinstance( response_options, dict ) and response_options.get( REVIEW_CARD_KEY ) is True
