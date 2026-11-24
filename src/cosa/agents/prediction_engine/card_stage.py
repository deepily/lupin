"""
The decision stage of the asking card, read from its own words and never from a model.

A principle learned at one stage must not be applied at the other. "Ask me before re-spinning" answers who decides, and
a card that already asks "Re-spin this agent?" is past that. The extractor stores the stage of each answer it reads
(decision_stage on the evidence row). Retrieval compares it with the stage of the card at ask time, and that stage comes
from here.

The rule reads only what exists at ask time. That is the card's title, its message and each field's prompt. It does not read
option labels. A card that asks what to do once asked may offer "Ask me before re-spinning" as one answer.
It does not read the abstract, which is long and often mentions delegation in passing. It never reads an answer.
"""

from cosa.agents.principle_learner.extractor_prompt import DECISION_STAGES

WHO_DECIDES            = DECISION_STAGES[ 0 ]
WHAT_TO_DO_ONCE_ASKED  = DECISION_STAGES[ 1 ]

# A card whose own question asks about delegating a decision. Matched as case-folded substrings of the question text.
DELEGATION_PHRASES     = ( "ask me before", "ask me first", "ask before", "check with me first", "without asking", "without my approval",
                           "need my approval", "on your own", "you decide", "who decides", "should i ask", "should i check with you" )

# Response types that are a decision between options even when the card carries no option list of its own.
DECISION_RESPONSE_TYPES = ( "yes_no", "multiple_choice" )


def question_text( episode ):
    """
    Gather the words a card uses to ask its question.

    Requires:
        - episode is an episode_view result

    Ensures:
        - returns the title, the message and each field prompt joined by newlines, case-folded, skipping empty parts
        - option labels, descriptions and the abstract are not included
    """
    parts = [ episode[ "title" ], episode[ "message" ] ] + [ field[ "prompt" ] for field in episode[ "fields" ] ]
    return "\n".join( part for part in parts if part ).casefold()


def card_stage_of( episode ):
    """
    Name the decision stage of the card being asked.

    Requires:
        - episode is an episode_view result, with title, message, response_type and fields

    Ensures:
        - returns WHO_DECIDES when the question text holds any of DELEGATION_PHRASES
        - otherwise returns WHAT_TO_DO_ONCE_ASKED when the card is a decision: a yes or no, a multiple choice, or any card with a field that has options
        - otherwise returns None, so retrieval skips the stage rule rather than guessing
        - no model is called, nothing is read from the database and no answer is read
    """
    if any( phrase in question_text( episode ) for phrase in DELEGATION_PHRASES ): return WHO_DECIDES
    if episode[ "response_type" ] in DECISION_RESPONSE_TYPES or any( field[ "options" ] for field in episode[ "fields" ] ): return WHAT_TO_DO_ONCE_ASKED
    return None
