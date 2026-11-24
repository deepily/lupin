"""
The prompt the principle extractor sends, and the reader of what comes back.

One call covers every field of one answered ask. The prompt carries the card, the earlier questions the
episode view kept, the answer per field, and the nearest existing principles with their dimensions.
It carries no answer text from any other conversation. The model answers in JSON, and a reply that is
not JSON is reported and never guessed at.
"""

import json

from cosa.agents.io_models.utils.json_object_recovery import recover_json_object
from cosa.config.configuration_manager import ConfigurationManager
from cosa.config.switch_reader import read_switch
from cosa.agents.principle_learner.vocabulary import VOCABULARY_VERSION, headings_block, shown_dimension

PROMPT_VERSION = f"extractor-v2-vocab-{VOCABULARY_VERSION}"


DECISION_STAGES    = ( "who_decides", "what_to_do_once_asked" )
DECISION_STAGE_KEY = "principle learner decision stage enabled"
BARE_YES_KEY      = "principle learner bare yes relations enabled"
UNINFORMATIVE_KEY = "principle learner uninformative relation enabled"
UNREAD_KEY        = "principle learner unread answers enabled"
DEDUP_KEY         = "principle learner source dedup enabled"
BARE_YES_TAG      = "bareyes"
UNINFORMATIVE_TAG = "uninformative"
UNREAD_TAG        = "unread"
DEDUP_TAG         = "dedup"

# Every switch that changes what the extractor writes tags the version it writes under, so its rows sit beside the old ones
# and derive_statuses, which counts current-version evidence only, never mixes them. One entry per switch: ( INI key, tag ).
# The order here is the order of the tags in the version string. A new switch of this kind adds its entry here and nowhere else.
VERSION_TAGS       = ( ( BARE_YES_KEY, BARE_YES_TAG ), ( UNINFORMATIVE_KEY, UNINFORMATIVE_TAG ), ( UNREAD_KEY, UNREAD_TAG ), ( DEDUP_KEY, DEDUP_TAG ), ( DECISION_STAGE_KEY, "stage" ) )


def switch_on( key ):
    """
    Read one boolean INI switch as the extractor does.

    Requires:
        - key is an INI key holding a boolean

    Ensures:
        - returns True only when the key is true; an absent or unreadable key is False and an unreadable one prints a line
    """
    return read_switch( ConfigurationManager, key, "false", lambda error: f"[principle extractor] switch {key!r} unreadable, treated as off: {error}" )


def active_tags( reader=None ):
    """
    Name the version tags of the switches that are on.

    Requires:
        - reader is None, or a function taking an INI key and returning whether that switch is on

    Ensures:
        - returns the tags of VERSION_TAGS whose switch reads on, in VERSION_TAGS order, using switch_on when reader is None
    """
    reader = switch_on if reader is None else reader
    return tuple( tag for key, tag in VERSION_TAGS if reader( key ) )

BARE_YES_ADDENDUM = """
- A bare yes may also contradict or refine a listed principle: name it in "relations" with "contradicts" or "refines"."""

UNINFORMATIVE_ADDENDUM = """
- A bare yes says nothing about a listed principle whose antecedent (the situation it applies when) is not in the card.
  Name it in "relations" as "uninformative" and add it to "antecedents": {"<principle id>": {"quote": "<the principle's antecedent, quoted>", "card_lacks_it": true}}.
  Without the quote and card_lacks_it true, the relation is refused."""

DEDUP_ADDENDUM = """
- When the answer states a rule beyond this card ("always", "never", "from now on" or the same sense), add to that hypothesis
  "standing_instruction": true and "standing_quote": "<the words, quoted from the answer>". Without the quote the hypothesis is refused.
  An answer that only refuses this card is not a standing instruction: leave both fields out."""

UNREAD_ADDENDUM = """
- An answer marked unread_stance is the raw text of a yes or no answer the system could not classify. Read it as written;
  it is not a bare yes, so propose hypotheses or name relations as for any other answer."""


def extractor_version_of( model, tags=() ):
    """
    Name the extractor version a model and the current prompt make.

    Requires:
        - model is the extractor model id
        - tags is the tuple active_tags returns

    Ensures:
        - returns "<model>:<prompt version>" with "+<tag>" added for each tag, the string the extractor stores on its rows
        - with no tags the version is exactly PROMPT_VERSION's, unchanged from before any switch tagged it
    """
    return f"{model}:{PROMPT_VERSION}" + "".join( f"+{tag}" for tag in tags )


def current_extractor_version( model, reader=None ):
    """
    Name the extractor version a model makes under the live switches.

    Requires:
        - model is the extractor model id; reader is as active_tags takes it

    Ensures:
        - returns extractor_version_of( model, active_tags( reader ) ), the one string the job writes under and every reader of its rows must ask for
    """
    return extractor_version_of( model, active_tags( reader ) )


def active_prompt_version( reader=None ):
    """
    Name the prompt version, with the tags of the switches that are on.

    Requires:
        - reader is as active_tags takes it

    Ensures:
        - returns PROMPT_VERSION with "+<tag>" added for each active tag
    """
    return PROMPT_VERSION + "".join( f"+{tag}" for tag in active_tags( reader ) )


def system_prompt_for( tags=() ):
    """
    Build the system prompt for the active version tags.

    Requires:
        - tags is a tuple drawn from the tags of VERSION_TAGS, as active_tags returns it

    Ensures:
        - the base is STAGE_SYSTEM_PROMPT when the stage tag is on, else SYSTEM_PROMPT; no other tag changes the base
        - returns the base unchanged for no tags, else it with one addendum per tag that has one, appended after the headings block
    """
    extra = { BARE_YES_TAG: BARE_YES_ADDENDUM, UNINFORMATIVE_TAG: UNINFORMATIVE_ADDENDUM, UNREAD_TAG: UNREAD_ADDENDUM, DEDUP_TAG: DEDUP_ADDENDUM }
    return ( STAGE_SYSTEM_PROMPT if "stage" in tags else SYSTEM_PROMPT ) + "".join( extra[ tag ] for tag in tags if tag in extra )


SYSTEM_PROMPT = """You extract short conditional preference principles from one answered question.

You are given a card the owner was asked, the earlier questions that framed it, the owner's answer for each field,
and the owner's nearest existing principles. For each field, decide what the answer shows about the owner's preferences.

Rules:
- Propose at most three hypotheses per field. Each statement is one sentence under 240 characters.
- A condition must be words that appear in the card or the answer. If you cannot ground it, leave it empty.
- Do not name a project in a global statement. Give a project-scoped statement the scope "project:<name>".
- When the answer is a bare yes, propose no hypothesis. Only say which listed principles the yes supports.
- The dimension must be one of the owner's headings below, written exactly as listed. Pick the closest one.
  Name an existing principle in "relations" when the answer supports, contradicts or refines it, using its id exactly as listed.
- An answer marked possibly_influenced was given after the owner saw a forecast: say so in the rationale, and weigh it less.

Reply with JSON only, in this shape:
{"fields": [{"field_key": "...", "kind": "decision" or "ask_form", "dimension": "...",
             "hypotheses": [{"statement": "...", "rationale": "...", "scope": "global", "condition": "...", "grounded_in": "answer" or "card"}],
             "relations": {"<principle id>": "supports" or "contradicts" or "refines"}}]}

The owner's headings:
""" + headings_block()

# Added to the system prompt only under the decision-stage switch. The stage is a condition on the answer, never a vocabulary heading.
STAGE_RULE = """

Decision stage: when the card is a question about whether to act, say which stage this answer is at, per field, as "decision_stage".
- "who_decides": the owner is answering who decides, for example "Ask me before re-spinning".
- "what_to_do_once_asked": the owner is answering what to do once asked, for example "Yes, re-spin this agent now".
- Use null when the field is not a decision about acting. Never invent a third value.
Add "decision_stage": "who_decides" or "what_to_do_once_asked" or null to each field result."""

STAGE_SYSTEM_PROMPT = SYSTEM_PROMPT + STAGE_RULE


def build_user_prompt( episode, entries, neighbours ):
    """
    Write the user prompt for one answered ask.

    Requires:
        - episode is an episode_view result
        - entries is a list of { "field_key", "text", "bare_yes", "possibly_influenced" }
        - neighbours is a list of principle rows with id, dimension, statement and scope

    Ensures:
        - returns one string holding the card, the history, the answers and the principles, as JSON blocks
        - no notification id, owner id or sender id is written into the prompt
        - an entry marked unread_stance carries that flag; every other entry is written as before
        - history entries carry tier, confidence, status, inferred and the answer value, and no ids
        - a principle's dimension is shown as its approved heading when it has one, so an old name never contradicts the heading rule
        - an entry carrying a "structure" (option ids and linked conditions from the meaning record) shows it under that key; an entry without one is written exactly as before
    """
    card    = { "title": episode[ "title" ], "abstract": episode[ "abstract" ], "fields": episode[ "fields" ] }
    history = [ { key: entry.get( key ) for key in ( "tier", "confidence", "status", "inferred", "answer" ) } for entry in episode[ "history" ] ]
    known   = [ { "id": str( row.id ), "dimension": shown_dimension( row.dimension ), "statement": row.statement, "scope": row.scope } for row in neighbours ]
    answers = [ { "field_key": entry[ "field_key" ], "answer": entry[ "text" ], "bare_yes": entry[ "bare_yes" ],
                  "possibly_influenced": entry[ "possibly_influenced" ], **( { "structure": entry[ "structure" ] } if entry.get( "structure" ) is not None else {} ),
                  **( { "unread_stance": True } if entry.get( "unread_stance" ) else {} ) }
                for entry in entries ]
    return "\n\n".join( [ "CARD\n" + json.dumps( card, indent=1, sort_keys=True ), "EARLIER QUESTIONS\n" + json.dumps( history, indent=1, sort_keys=True ),
                          "ANSWERS\n" + json.dumps( answers, indent=1, sort_keys=True ), "EXISTING PRINCIPLES\n" + json.dumps( known, indent=1, sort_keys=True ) ] )


def parse_reply( text ):
    """
    Read the model's reply as the JSON it was asked for.

    Requires:
        - text is the model's reply string

    Ensures:
        - returns the list of field results when the reply holds a JSON object with a "fields" list of objects
        - the JSON is recovered by recover_json_object with no label, so no file is written and a code fence,
          a lead-in line or trailing prose does no harm; this function only checks the shape
        - returns None for anything else; a malformed reply is never repaired here
    """
    parsed = recover_json_object( text )
    fields = parsed.get( "fields" ) if isinstance( parsed, dict ) else None
    return fields if isinstance( fields, list ) and all( isinstance( f, dict ) for f in fields ) else None
