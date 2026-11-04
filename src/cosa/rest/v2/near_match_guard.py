"""
Near-match guard: refuse a near match when a number is involved and the questions differ.

Why it exists. "Convert 10 miles to kilometers" was once answered "10 kilometers is about 6.21 miles".
The cache replayed the snapshot of "How many miles is 10 kilometers?". The embedder scored the pair
93.4, above the 90.0 near-match threshold. The questions share every content word and differ only in
which unit the 10 belongs to, and a similarity score reads that as almost nothing. A replay serves a
stored answer, so a near match that changes the quantity asked about is a confidently wrong reply.

The predicate. For each question, build the ordered sequence of its numbers and content words.
Examples:

    "Convert 100 degrees fahrenheit to celsius"   -> [ convert, 100, degree, fahrenheit, to, celsius ]
    "How many miles is 10 kilometers?"            -> [ many, mile, 10, kilometer ]
    "Uh... what's 253 plus, uh, 147?"             -> [ 253, plus, 147 ]

When neither question has a number, nothing is refused and the near match behaves as before. When
either has one, the near match is refused unless the two sequences are identical. A different unit,
order, number, sign or decimal point refuses. So does a number that moved relative to its words.

Content words are lowercase alphabetic tokens, plural-folded, with hesitations ("uh", "um", "hmm")
dropped. Only a short allowlist of noise words is dropped, in `_NOISE_WORDS`. Every other word is
compared, so a word nobody has thought of fails closed. No list of units is kept, so an unseen unit
is still compared as a word. A number is a digit run with an optional sign, decimal point or
thousands grouping. The symbols % $ + * x / and = become the words they stand for. A "-" between two
numbers is "minus", and a hyphen elsewhere is dropped. So "2 + 2" and "2 plus 2" match, while
"5 - 3" and "5 + 3" do not.

The guard fails closed, and the price is accepted. Refusing a near match costs one cache hit, because
the question is routed and answered afresh. Allowing a wrong one costs a wrong answer. Wording that
only a person would call the same is therefore refused when it has a number in it. Examples are
"What's 5 kilometers in miles?" against "How many miles is 5 kilometers?", or "Convert" against
"Calculate".

Known gaps. A number spelled as a word ("ten") is not a number to this predicate. A conversion with
no number on either side, such as "convert miles to kilometers" against "convert kilometers to
miles", leaves the guard silent. Only near matches are guarded here, not tier-1 exact hits.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import List, Optional

# THE NOISE LIST IS AN ALLOWLIST (row 1b3ec88f, fourth round). Every word NOT named here is compared, so a
# word nobody has thought of fails closed. The first two versions dropped spaCy's whole stop-word list and
# then a denylist of "meaning-bearing" words; each review found another word that flips an answer that
# the lists still dropped (more/less, then and/or, without, can't, modals, ...). Only articles, "of",
# "please", and the present-tense "is", "are", "be", "do", "does" are dropped. Not dropped, on Rio's fourth
# review: "a" (it can be an algebra variable: "solve 5a = 10"), "am" ("5 am" vs "5 pm"), and the past tense
# was / were / did / been (an answer that depends on time can flip).
# wh-words (what, how, who, whom ...), modals, prepositions and quantifiers are all COMPARED.
_NOISE_WORDS = frozenset( { "an", "the", "of", "please", "is", "are", "be", "do", "does" } )
_NUMBER      = r"(?:(?<![\w.])[-−])?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"
_WORD        = r"[^\W\d_]+(?:['’][^\W\d_]+)?"
_TOKEN       = re.compile( f"{_NUMBER}|{_WORD}|[%$+*/=\\-\u00d7\u00f7]" )
_HESITATION  = re.compile( r"u+h+|u+m+|h+m+|e+r+m*|a+h+|e+h+|o+h+" )
# what an apostrophe clitic stands for: "'s" is dropped (possessive or "is"), the rest become their words,
# and "n't" becomes "not" so "can't" is "can not", never "can"
_NT_STEMS     = { "can": "can", "won": "will", "shan": "shall", "ain": "be" }   # every other "...n't" loses its "n"
_CLITIC_WORDS = { "s": [], "re": [ "are" ], "m": [ "am" ], "ll": [ "will" ], "d": [ "would" ],
                  "ve": [ "have" ], "t": [ "not" ] }
_SYMBOL_WORD = { "%": "percent", "$": "dollar", "+": "plus", "*": "times", "\u00d7": "times",
                 "/": "divided", "\u00f7": "divided", "=": "equal" }


def _fold_plural( word: str ) -> str:
    """
    Reduce a plural noun to its singular using simple suffix rules.

    The folding is crude. A word that folds wrongly still fails closed, because two different foldings are
    different words.

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


def _content_words( token: str ) -> List[ str ]:
    """
    The comparable words a word token stands for; empty when it is noise or a hesitation.

    Requires:
        - token matched the word pattern (letters, optionally one apostrophe clitic)

    Ensures:
        - "what's" is ["what"]; "I'll" is ["i", "will"]; "can't" and "cannot" are ["can", "not"];
          "isn't" and "don't" are ["not"] (the "is" and "do" are noise); "won't" is ["will", "not"]
        - returns [] for the _NOISE_WORDS and for hesitation sounds
        - every other word, lowercase and plural-folded, is returned: nothing is dropped by default
        - never returns an empty string: a bare "n't" (stem "n", which loses its "n") is just ["not"]
    """
    word = token.lower().replace( "\u2019", "'" )
    if word == "cannot": return [ "can", "not" ]
    tail = []
    if "'" in word:
        stem, clitic = word.split( "'", 1 )
        if clitic in _CLITIC_WORDS:
            tail = _CLITIC_WORDS[ clitic ]
            word = _NT_STEMS.get( stem, stem[ :-1 ] ) if clitic == "t" else stem
        else:
            word = stem + clitic
    words = []
    if word and word not in _NOISE_WORDS and not _HESITATION.fullmatch( word ): words.append( _fold_plural( word ) )
    return words + [ w for w in tail if w not in _NOISE_WORDS ]


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
            tokens.extend( _content_words( token ) )
    return tokens


def has_number( text: str ) -> bool:
    """Whether the question carries a number: a digit run, signed, decimal or grouped."""
    return re.search( _NUMBER, text ) is not None


def quantities_differ( asked: Optional[ str ], stored: Optional[ str ] ) -> bool:
    """
    Whether replaying the answer to `stored` for `asked` could change the quantity asked.

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
