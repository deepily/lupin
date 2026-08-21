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


import json
import re


FIRST_OPTION = "__first_option__"
LAST_OPTION  = "__last_option__"
ALL_OPTIONS  = "__all__"

SENTINELS = ( FIRST_OPTION, LAST_OPTION, ALL_OPTIONS )

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

    token = answer.strip()
    if token == ALL_OPTIONS:
        return encode_multi_select( labels, notification )
    return labels[ 0 ] if token == FIRST_OPTION else labels[ -1 ]


def encode_multi_select( labels, notification ):
    """
    Every label, in the wire format a multi-select card's reader expects.

    ⚠️ THIS FORMAT IS NOT A GUESS — it is what the HUMAN path produces, read off both
    ends before this was written (row 054207ce):

      · the browser builds `{ header, value }` with `value = multi_select ? answers :
        answers[0]`, collects those into `{ <header>: <value> }`, and submits
        `JSON.stringify( { answers: … } )` — notifications.js
        getCurrentQuestionAnswer / submitAllMultipleChoiceAnswers.
      · the agent side json.loads() that and reads `answers[<header>]`, accepting a
        list or a bare string — agent_notification_dispatcher.present_choices,
        voice_io.read_gate_answer, TFE's _aggregate_voice_gate.

    A BARE LABEL STRING SELECTS NOTHING, and that is why "__all__" never worked. A
    non-JSON response_value is wrapped as `{"answers": {"response": <raw>}}` — header
    "response", not the card's — so read_gate_answer sees an ABSENT header, falls to
    its unattended_default of [], and the run reports that the user picked no fixes.
    Silent, and indistinguishable from a human declining.

    Requires:
        - labels is the selectable labels, escapes already removed
        - notification carries exactly one question; its header is the answer's key

    Ensures:
        - returns a JSON string `{"answers": {"<header>": [labels…]}}`
        - returns None when the card has no single header to key the answer under —
          zero questions, more than one, or a question with no header. "Select
          everything" has no unambiguous meaning across several questions, and
          guessing a key produces the absent-header silence described above.

    Raises:
        - nothing
    """
    questions = ( notification.get( "response_options" ) or {} ).get( "questions" ) or []
    if len( questions ) != 1:
        return None

    header = ( questions[ 0 ].get( "header" ) or "" ).strip()
    if not header:
        return None

    return json.dumps( { "answers": { header: labels } } )


# ─────────────────────────────────────────────────────────────────────────────
# Validating an answer against the card that asked (row a1420538)
# ─────────────────────────────────────────────────────────────────────────────
#
# The sentinel resolver above only inspects answers SHAPED like a sentinel. Every
# other answer — from the script matcher, the rule strategy, or the cloud LLM —
# went straight to the card untouched, so the prose-as-a-label failure that the
# sentinels were introduced to kill could still arrive by any of those three
# routes. A CBR prediction hint carrying the retired directive at confidence 0.9
# against an auto-submit floor of 0.9 is what made this concrete: the floor is
# inclusive (`confidence < floor` is the client's reject test — pinned by
# "gate OPENS at exactly the floor" in
# src/tests/unit/notifications_js/batch_prediction_prefill.test.ts), so equal
# PASSES and nothing downstream was checking what came through.
#
# The check below is deliberately the SAME rule the expeditor applies when it
# reads the answer: exact match after stripping. Matching more loosely here would
# wave through values the expeditor then rejects, which is a cancelled run rather
# than a caught one.


def _answer_values( answer ):
    """
    The label (or labels) an answer carries, read the way the card's reader reads it.

    Requires:
        - answer is the value about to be submitted

    Ensures:
        - a plain string yields itself, stripped
        - a JSON object string yields the values of its "answers" map, stripped —
          the shape RuntimeArgumentExpeditor._ask_choice_for_arg parses alongside
          the raw label
        - unparseable JSON, or a JSON value that is not an answers map, yields the
          original text: it is not a label the card offered either, and pretending
          it parsed would hide that
        - a non-string yields itself, so it is compared and rejected rather than
          waved through for not being text

    Raises:
        - nothing
    """
    if not isinstance( answer, str ):
        return [ answer ]

    text = answer.strip()
    if text.startswith( "{" ):
        try:
            answers = json.loads( text ).get( "answers", None )
        except ( json.JSONDecodeError, AttributeError ):
            return [ text ]
        if isinstance( answers, dict ) and answers:
            values = []
            for value in answers.values():
                # A MULTI-SELECT ANSWER CARRIES ITS PICKS AS A LIST under the
                # question's header — the shape encode_multi_select emits and the
                # browser submits. Flattened ONE level so each pick is checked on its
                # own; without this the whole list arrives as a single value, matches
                # no label, and would be reported as one giant unoffered blob.
                if isinstance( value, list ):
                    values.extend( v.strip() if isinstance( v, str ) else v for v in value )
                else:
                    values.append( value.strip() if isinstance( value, str ) else value )
            return values
        # An EMPTY answers map carries no label, and "no values" must not read as "no
        # violations" — that would make the check vacuously pass and submit the raw
        # JSON, which is exactly the unknown-label failure it exists to stop. Reported
        # as itself, like unparseable JSON.
        return [ text ]
    return [ text ]


def unasked_headers( answer, notification ):
    """
    Every header the answer keys a value under that this card never asked under.

    THE FOURTH CASE FROM ROW adf5c1a1, and the one element-wise comparison structurally
    cannot catch: in `{"answers": {"Wrong": ["c1: fix one"]}}` the LABEL is perfectly
    valid — the card did offer it — and the defect is the KEY.

    It matters for the same reason the whole 054207ce chain does. The reader looks the
    answer up under the question's own header (voice_io.read_gate_answer). A header the
    card never asked under is therefore not a wrong answer, it is NO answer: the real
    header reads as absent, the reader falls to its unattended_default, and the agent
    concludes the user chose nothing. Silent, and indistinguishable from a human
    declining — the exact failure shape this family of rows keeps producing.

    Requires:
        - answer is the value about to be submitted
        - notification is the card it answers

    Ensures:
        - returns [] for an answer that is not a JSON answers map — a bare label has no
          header to be wrong, and unoffered_values is what judges it
        - returns [] when the card asks under no headers at all; there is then nothing
          to check against, and inventing a rule would reject every answer to a
          malformed card twice over
        - the comparison is EXACT after stripping, like every other match in this module

    Raises:
        - nothing
    """
    if not isinstance( answer, str ):
        return []

    text = answer.strip()
    if not text.startswith( "{" ):
        return []
    try:
        answers = json.loads( text ).get( "answers", None )
    except ( json.JSONDecodeError, AttributeError ):
        return []
    if not isinstance( answers, dict ) or not answers:
        return []

    questions = ( notification.get( "response_options" ) or {} ).get( "questions" ) or []
    asked     = { ( q.get( "header" ) or "" ).strip() for q in questions }
    asked.discard( "" )
    if not asked:
        return []

    return [ header for header in answers if header.strip() not in asked ]


def unoffered_values( answer, notification ):
    """
    Every value in `answer` that this card never offered as an option.

    Requires:
        - answer is the value about to be submitted
        - notification is the multiple-choice notification it answers

    Ensures:
        - returns [] when every value is one of the card's own option labels
        - the comparison is EXACT after stripping, because that is what the
          expeditor does when it maps the pick back to a file; a looser match here
          would pass values the expeditor then refuses, turning a caught answer
          into a cancelled run
        - checks a MULTI-SELECT answer too, one pick at a time. This used to return []
          for any multi-select card, because the encoding was pinned nowhere and a
          rejection would have been a guess. encode_multi_select pinned it (row
          054207ce), which retired the reason — and a carve-out whose reason expired
          reads exactly like one that still has a reason, so it was measured and
          removed rather than left (row adf5c1a1). An answer whose picks are all
          offered is unaffected; __all__ emits the card's own labels and cannot fail
          this.
        - a card offering NO options rejects everything: the expeditor would refuse
          any answer to it, and a visible skip says so where a submitted value would
          not

    Raises:
        - nothing
    """
    offered = option_labels( notification )
    return [ value for value in _answer_values( answer ) if value not in offered ]
