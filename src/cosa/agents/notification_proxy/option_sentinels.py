"""
Answers that name a POSITION instead of a value (row 9046ef58).

THE PROBLEM. Almost every question in a Q&A script has a stable answer you can write
down — "general", "default", "yes". The expeditor's DOCUMENT CHOICE CARD does not: its
option labels are the basenames of whatever documents the user happens to have,
discovered while the run is in flight. No fixed string in a script file can ever equal
one.

WHAT WAS TRIED FIRST, AND WHY IT FAILED. The entry's answer was written as a directive
— "Pick the first document option in the list" — on the strength of the matcher prompt
telling the model to *"pick the option label that best aligns with the script's
answer"*. On a live run the model returned THE DIRECTIVE ITSELF as the answer. The
expeditor received a label that was not in the option set, correctly refused to guess
which document was meant, and the run cancelled — the exact failure the entry was added
to prevent. Prompt wording is not a contract; a resolver is.

THE FIX. A sentinel names a position, and this module turns it into a real label using
the options that arrived WITH the notification. The proxy then submits a label the card
actually offered, so the expeditor's no-silent-guess rule stays intact — it is still the
one deciding whether the answer is a legal option; we simply stop handing it prose.

⚠️ TEST-HARNESS SCOPE. This resolves answers for the AUTOMATED responder only. It never
runs in a path a human's answer travels.
"""


import re


FIRST_OPTION = "__first_option__"
LAST_OPTION  = "__last_option__"

SENTINELS = ( FIRST_OPTION, LAST_OPTION )

# Anything SHAPED like a sentinel. A value matching this but absent from SENTINELS is a
# typo or a case variant, and it must never be forwarded as a literal — see resolve().
_SENTINEL_SHAPE = re.compile( r"^__\w+__$" )


def is_sentinel( answer ):
    """
    Whether an answer names a position rather than a value.

    Requires:
        - answer is any value; a non-string is simply not a sentinel

    Ensures:
        - returns True only for an EXACT, CASE-SENSITIVE match against SENTINELS,
          after stripping surrounding whitespace
        - a sentinel is a token, not prose: "pick __first_option__" is NOT one
        - "__FIRST_OPTION__" is NOT one either. Case-folding would turn a value whose
          entire job is to be unambiguous into a fuzzy match — and the near-miss does
          not pass quietly, because resolve() raises on it.

    Raises:
        - nothing
    """
    return isinstance( answer, str ) and answer.strip() in SENTINELS


def looks_like_a_sentinel( answer ):
    """
    Whether a value is SHAPED like a sentinel, valid or not.

    Requires:
        - answer is any value; a non-string never looks like one

    Ensures:
        - returns True for any stripped "__word__", typos and case variants included

    Raises:
        - nothing
    """
    return isinstance( answer, str ) and bool( _SENTINEL_SHAPE.match( answer.strip() ) )


def option_labels( notification ):
    """
    Every option label a multiple-choice notification is offering, in order.

    Requires:
        - notification is a dict; a missing or malformed response_options yields []

    Ensures:
        - returns labels in the order the card presents them
        - skips options with an empty or missing label rather than yielding ""
        - returns a list, never None

    Raises:
        - nothing
    """
    questions = ( notification.get( "response_options" ) or {} ).get( "questions" ) or []
    labels    = []
    for question in questions:
        for option in question.get( "options" ) or []:
            label = ( option.get( "label" ) or "" ).strip()
            if label:
                labels.append( label )
    return labels


def resolve( answer, notification, excluded_labels=() ):
    """
    Turn a positional sentinel into a real option label.

    Requires:
        - answer is the scripted answer, sentinel or not
        - notification is the multiple-choice notification the answer is for
        - excluded_labels names escape hatches the sentinel must never select

    Ensures:
        - a non-sentinel answer is returned UNCHANGED — this is a pass-through for
          every ordinary entry
        - a sentinel returns the first (or last) label that is not excluded
        - returns None when a sentinel cannot be resolved, so the caller reports "no
          answer" rather than submitting a sentinel string as if it were a label. A
          visible skip beats a submitted "__first_option__", which reads to the
          expeditor as an unknown label and cancels the run for a reason nobody can
          see from the outside.

    Raises:
        - ValueError when the answer is SHAPED like a sentinel but is not one —
          "__frist_option__", "__FIRST_OPTION__". Returning it unchanged would forward
          the literal string to the card, which is the SAME defect the sentinels
          replaced (prose submitted as a label) wearing a new name. A typo in a config
          file must not degrade into a cancelled run whose cause is invisible.
    """
    if looks_like_a_sentinel( answer ) and not is_sentinel( answer ):
        raise ValueError(
            f"{answer.strip()!r} is shaped like a positional sentinel but is not one; "
            f"valid sentinels are {SENTINELS} and the match is case-sensitive"
        )
    if not is_sentinel( answer ):
        return answer

    excluded = { label.strip().lower() for label in excluded_labels }
    labels   = [ label for label in option_labels( notification )
                 if label.lower() not in excluded ]
    if not labels:
        return None

    return labels[ 0 ] if answer.strip() == FIRST_OPTION else labels[ -1 ]
