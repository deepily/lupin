"""
The prompt the principle extractor sends, and the reader of what comes back.

One call covers every field of one answered ask. The prompt carries the card, the earlier questions the
episode view kept, the answer per field, and the nearest existing principles with their dimensions.
It carries no answer text from any other conversation. The model answers in JSON, and a reply that is
not JSON is reported and never guessed at.
"""

import json

from cosa.agents.io_models.utils.json_object_recovery import recover_json_object
from cosa.agents.principle_learner.vocabulary import VOCABULARY_VERSION, headings_block, shown_dimension

PROMPT_VERSION = f"extractor-v2-vocab-{VOCABULARY_VERSION}"

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
        - history entries carry tier, confidence, status, inferred and the answer value, and no ids
        - a principle's dimension is shown as its approved heading when it has one, so an old name never contradicts the heading rule
    """
    card    = { "title": episode[ "title" ], "abstract": episode[ "abstract" ], "fields": episode[ "fields" ] }
    history = [ { key: entry.get( key ) for key in ( "tier", "confidence", "status", "inferred", "answer" ) } for entry in episode[ "history" ] ]
    known   = [ { "id": str( row.id ), "dimension": shown_dimension( row.dimension ), "statement": row.statement, "scope": row.scope } for row in neighbours ]
    answers = [ { "field_key": entry[ "field_key" ], "answer": entry[ "text" ], "bare_yes": entry[ "bare_yes" ],
                  "possibly_influenced": entry[ "possibly_influenced" ] } for entry in entries ]
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
