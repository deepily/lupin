"""
Near-match quantity guard — refuse a near match whose numbers or the units attached to them differ.

WHY (row 1b3ec88f, measured :8000 job ts-8278f1c5, 2026-10-03 21:02:20 EDT). "Convert 10 miles to
kilometers" was answered "10 kilometers is about 6.21 miles" by replaying the snapshot of "How many
miles is 10 kilometers?". The embedder scored the pair 93.4, above the 90.0 near-match threshold:
the two questions share every content word and differ only in WHICH unit the 10 belongs to, which a
similarity score reads as nearly nothing. A replay serves a stored ANSWER, so a near match that
changes the quantity asked about is a confidently wrong reply.

THE PREDICATE, AND WHAT IT DELIBERATELY IS NOT. It is not a list of units. A QUANTITY here is a
number and the word written immediately after it, in the order they occur:

    "Convert 10 miles to kilometers"      -> [ ( 10, mile ) ]
    "How many miles is 10 kilometers?"    -> [ ( 10, kilometer ) ]

Two questions DIFFER when their ordered numbers differ, or when a number's following word is present
in both and is a different word. A number with no word after it (a symbol, the end of the question)
carries no unit, and an absent unit is compatible with any: "2 + 2" and "2 plus 2" must not be
refused for that. A plural is folded to its singular so "10 miles" and "10 mile" are one unit.

FAILS CLOSED. Refusing a near match costs one cache hit (the question is routed and answered
afresh); allowing a wrong one costs a wrong answer. So every doubt resolves to "differ": "5 dollars"
and "5 bucks" are refused, as are "10" and "10.5". The cost is accepted and is the point.

KNOWN GAPS (named, not bridged): a number spelled as a word ("ten") is not a number to this
predicate; a conversion with NO number ("convert miles to kilometers" vs "convert kilometers to
miles") has an empty signature and passes; and only near matches are guarded here, not tier-1 exact
hits.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

_TOKEN = re.compile( r"\d+(?:[.,]\d+)*|[^\W\d_]+|[^\w\s]" )
_GROUPED_THOUSANDS = re.compile( r"\d{1,3}(?:,\d{3})+(?:\.\d+)?" )


def _fold_plural( word: str ) -> str:
    """
    Reduce a plural noun to its singular, crudely and on purpose.

    Requires:
        - word is a non-empty lowercase alphabetic string

    Ensures:
        - "ies" -> "y"; "sses"/"xes"/"zes"/"ches"/"shes" lose "es"; any other trailing "s" is dropped
          unless the word ends "ss", "us" or "is" (glass, plus, this); nothing under four letters changes
        - two spellings that fold to different strings are treated as different units (fails closed)
    """
    if len( word ) <= 3:                                                   return word
    if word.endswith( "ies" ):                                             return word[ :-3 ] + "y"
    if word.endswith( ( "sses", "xes", "zes", "ches", "shes" ) ):          return word[ :-2 ]
    if word.endswith( "s" ) and not word.endswith( ( "ss", "us", "is" ) ): return word[ :-1 ]
    return word


def _canonical_number( token: str ) -> str:
    """
    One spelling per numeric value, so "10", "10.0" and "1,000"/"1000" compare equal.

    Requires:
        - token is a digit token from the tokenizer, possibly with "." or "," separators

    Ensures:
        - thousands-grouped commas are removed, then the value is normalised as a Decimal
        - a token that is not a clean decimal (e.g. "3,5") is returned unchanged, so it can only
          equal itself
    """
    text = token.replace( ",", "" ) if _GROUPED_THOUSANDS.fullmatch( token ) else token
    try:
        return format( Decimal( text ).normalize(), "f" )
    except InvalidOperation:
        return token


def quantity_signature( text: str ) -> List[ Tuple[ str, Optional[ str ] ] ]:
    """
    The ordered ( number, unit-or-None ) pairs in a question.

    Requires:
        - text is a string

    Ensures:
        - one pair per number token, in the order the numbers occur
        - the unit is the alphabetic token immediately after the number, plural-folded, or None
          when the next token is punctuation, a symbol, or the end
        - "10km" yields ( "10", "km" ): the tokenizer splits digits from letters
    """
    tokens    = _TOKEN.findall( text.lower() )
    signature = []
    for index, token in enumerate( tokens ):
        if not token[ 0 ].isdigit(): continue
        following = tokens[ index + 1 ] if index + 1 < len( tokens ) else ""
        unit      = _fold_plural( following ) if following[ :1 ].isalpha() else None
        signature.append( ( _canonical_number( token ), unit ) )
    return signature


def quantities_differ( asked: str, stored: str ) -> bool:
    """
    Whether replaying the answer to `stored` for `asked` would change the quantity asked about.

    Requires:
        - asked and stored are the two questions' text

    Ensures:
        - True when the ordered numbers differ, or any number's unit is present in both and differs
        - False when both carry no numbers, or the numbers match and no unit conflicts
        - never raises
    """
    left, right = quantity_signature( asked ), quantity_signature( stored )
    if [ n for n, _ in left ] != [ n for n, _ in right ]: return True
    return any( a is not None and b is not None and a != b for ( _, a ), ( _, b ) in zip( left, right ) )
