"""
Near-match quantity guard — refuse a near match when either question carries a number and the two
questions do not say the same thing about it.

WHY (row 1b3ec88f, measured :8000 job ts-8278f1c5, 2026-10-03 21:02:20 EDT). "Convert 10 miles to
kilometers" was answered "10 kilometers is about 6.21 miles" by replaying the snapshot of "How many
miles is 10 kilometers?". The embedder scored the pair 93.4, above the 90.0 near-match threshold: the
two questions share every content word and differ only in which unit the 10 belongs to, which a
similarity score reads as almost nothing. A replay serves a stored ANSWER, so a near match that
changes the quantity asked about is a confidently wrong reply.

THE PREDICATE (second version, after Rio's review of the first). Build, for each question, the ORDERED
sequence of its numbers and its content words:

    "Convert 100 degrees fahrenheit to celsius"   -> [ convert, 100, degree, fahrenheit, celsius ]
    "How many miles is 10 kilometers?"            -> [ mile, 10, kilometer ]
    "Uh... what's 253 plus, uh, 147?"             -> [ 253, plus, 147 ]

When NEITHER question has a number, nothing is refused: the guard is silent and the near match behaves
as it did before. When EITHER has one, the near match is refused unless the two sequences are
identical. So a unit that differs ("miles to kilometers" / "miles to feet"), an order that differs
("fahrenheit to celsius" / "celsius to fahrenheit"), a number that differs, a number's sign or decimal
point that differs, or a number that moved relative to the words around it, all refuse.

Content words are lowercase alphabetic tokens with the function words REMOVED, plural-folded, and
hesitations ("uh", "um", "hmm") dropped. The function-word list is the English stop-word list that ships
with spaCy, the library the cache's normaliser already uses; no list of units is kept here, so a unit
this module has never seen is still compared as a word. A number is a digit run with an optional sign,
a decimal point, or thousands grouping; the symbols % $ + * x / and = are folded to the words they stand
for ("percent", "dollar", "plus", "times", "divided", "equal"), and a "-" between two numbers is "minus"
(a hyphen elsewhere is dropped), so "2 + 2" and "2 plus 2" are the same and "5 - 3" and "5 + 3" are not.

FAILS CLOSED, AND THE PRICE IS NAMED. Refusing a near match costs one cache hit (the question is routed
and answered afresh); allowing a wrong one costs a wrong answer. So wording that only a person would
call the same is refused when it has a number in it: "What's 5 kilometers in miles?" against "How many
miles is 5 kilometers?" (the number moved), or "Convert" against "Calculate". The cost on the eval
corpus is measured in io/findings-1b3ec88f-fix-2.md.

KNOWN GAPS (named, not bridged): a number spelled as a word ("ten") is not a number to this
predicate; a conversion with NO number ("convert miles to kilometers" vs "convert kilometers to miles")
has no numbers on either side, so the guard is silent; and only near matches are guarded here, not
tier-1 exact hits.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from spacy.lang.en.stop_words import STOP_WORDS

_NUMBER      = r"(?:(?<![\w.])[-−])?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"
_WORD        = r"[^\W\d_]+(?:['’][^\W\d_]+)?"
_TOKEN       = re.compile( f"{_NUMBER}|{_WORD}|[%$+*/=\\-\u00d7\u00f7]" )
_HESITATION  = re.compile( r"u+h+|u+m+|h+m+|e+r+m*|a+h+|e+h+|o+h+" )
_CLITICS     = ( "s", "re", "ll", "d", "ve", "m", "t" )
_SYMBOL_WORD = { "%": "percent", "$": "dollar", "+": "plus", "*": "times", "\u00d7": "times",
                 "/": "divided", "\u00f7": "divided", "=": "equal" }


def _fold_plural( word: str ) -> str:
    """
    Reduce a plural noun to its singular, crudely and on purpose.

    Requires:
        - word is a non-empty lowercase alphabetic string

    Ensures:
        - "ies" -> "y"; "sses"/"xes"/"zes"/"ches"/"shes" lose "es"; any other trailing "s" is dropped
          unless the word ends "ss", "us" or "is" (glass, plus, this); nothing under four letters changes
        - two spellings that fold to different strings are different words (fails closed)
    """
    if len( word ) <= 3:                                                   return word
    if word.endswith( "ies" ):                                             return word[ :-3 ] + "y"
    if word.endswith( ( "sses", "xes", "zes", "ches", "shes" ) ):          return word[ :-2 ]
    if word.endswith( "s" ) and not word.endswith( ( "ss", "us", "is" ) ): return word[ :-1 ]
    return word


def _canonical_number( token: str ) -> str:
    """
    One spelling per numeric value, sign included.

    Requires:
        - token matched the number pattern: optional sign, digits with optional "," grouping and
          optional ".digits", or ".digits"

    Ensures:
        - "10", "10.0" and "1,000"/"1000" compare equal; "-5" differs from "5"; ".5" is 0.5
        - "-0" is "0"
        - never raises
    """
    text = token.replace( "−", "-" ).replace( ",", "" )
    try:
        value = Decimal( text ).normalize()
    except InvalidOperation:       # pragma: no cover — the pattern admits only parseable text
        return token
    return format( value if value != 0 else Decimal( 0 ), "f" )


def _content_word( token: str ) -> Optional[ str ]:
    """
    The comparable form of a word token, or None when it is a function word or a hesitation.

    Requires:
        - token matched the word pattern (letters, optionally one apostrophe clitic)

    Ensures:
        - "what's" is "what" (a trailing 's, 're, 'll, 'd, 've, 'm or 't clitic is dropped)
        - returns None for spaCy stop words and for hesitation sounds
        - otherwise the lowercase plural-folded word
    """
    word = token.lower().replace( "’", "'" )
    if "'" in word:
        stem, clitic = word.split( "'", 1 )
        word         = stem if clitic in _CLITICS else stem + clitic
    if word in STOP_WORDS or _HESITATION.fullmatch( word ): return None
    return _fold_plural( word )


def quantity_tokens( text: str ) -> List[ str ]:
    """
    The ordered sequence of numbers and content words in a question.

    Requires:
        - text is a string

    Ensures:
        - numbers appear in their canonical spelling, words in their comparable form
        - function words, hesitations and punctuation are absent
        - the symbols in _SYMBOL_WORD appear as the word they stand for
    """
    tokens = []
    for match in _TOKEN.finditer( text ):
        token = match.group()
        if token == "-":
            # a hyphen joining a number to a word ("45-degree", "couch-to-5K") is not subtraction;
            # it is the minus operator only between two numbers: "5-3", "5 - 3"
            before, after = text[ :match.start() ].rstrip()[ -1: ], text[ match.end(): ].lstrip()[ :1 ]
            if before.isdigit() and after.isdigit(): tokens.append( "minus" )
        elif token in _SYMBOL_WORD:
            tokens.append( _SYMBOL_WORD[ token ] )
        elif token[ -1 ].isdigit():
            tokens.append( _canonical_number( token ) )
        else:
            word = _content_word( token )
            if word is not None: tokens.append( word )
    return tokens


def has_number( text: str ) -> bool:
    """Whether the question carries a number: a digit run, signed, decimal or grouped."""
    return re.search( _NUMBER, text ) is not None


def quantities_differ( asked: Optional[ str ], stored: Optional[ str ] ) -> bool:
    """
    Whether replaying the answer to `stored` for `asked` could change the quantity asked about.

    Requires:
        - asked and stored are the two questions' text; either may be None

    Ensures:
        - True when either question is None (it cannot be verified, so the near match is refused)
        - False when neither question has a number
        - otherwise True unless the two ordered sequences of numbers and content words are identical
        - never raises
    """
    if asked is None or stored is None: return True
    if not has_number( asked ) and not has_number( stored ): return False
    return quantity_tokens( asked ) != quantity_tokens( stored )
