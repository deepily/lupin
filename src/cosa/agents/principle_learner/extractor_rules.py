"""
The deterministic rules the principle extractor holds a model's output to.

The model proposes; these functions decide what is kept. A model that breaks a rule fails here,
so the rules hold with a live model and with a recorded double alike. Nothing here reads a database
or calls a model, and every function is a pure function of its arguments.

The rules are these. A field holds at most three hypotheses, each under 240 characters.
A condition is kept only when its words appear in the card or the answer.
A global statement names no project, and a bare yes creates no principle.
An answer given after a reveal with no draft is marked possibly influenced.
"""

import re

from cosa.agents.prediction_engine.ask_family import PROJECT_PATTERN, UNKNOWN_PROJECT
from cosa.agents.prediction_engine.exposure import revealed_before_answer
from cosa.utils.iso_timestamp import aware_moment
from cosa.utils.notification_utils import parse_field_selections

MAX_HYPOTHESES   = 3
MAX_STATEMENT    = 240
UNKNOWN          = "unknown"
RELATIONS        = ( "supports", "contradicts", "refines" )
KINDS            = ( "decision", "ask_form" )
GLOBAL_SCOPE     = "global"
PROJECT_SCOPE    = "project:"
WHOLE_ANSWER_KEY = "$answer"


def card_text( episode ):
    """
    Gather the text of the card that a condition may be grounded in.

    Requires:
        - episode is an episode_view result

    Ensures:
        - returns the title, the abstract, each field prompt and each option label, one per line
        - a missing title or abstract adds nothing
    """
    parts = [ episode[ "title" ], episode[ "abstract" ] ]
    for field in episode[ "fields" ]:
        parts.append( field[ "prompt" ] )
        parts.extend( option[ "label" ] for option in field[ "options" ] )
    return "\n".join( part for part in parts if part )


def project_names( sender_ids ):
    """
    List the project names that appear in a set of sender ids.

    Requires:
        - sender_ids is an iterable of sender id strings or None

    Ensures:
        - returns a sorted list of lower-case project names, the text between "@" and the next dot
        - an id with no project part adds nothing, and the unknown label is never listed
    """
    names = set()
    for sender in sender_ids:
        match = PROJECT_PATTERN.search( sender or "" )
        if match and match.group( 1 ) != UNKNOWN_PROJECT: names.add( match.group( 1 ).lower() )
    return sorted( names )


def field_answers( answer ):
    """
    Split a decoded answer into one entry per field.

    Requires:
        - answer is the first value derive_answer returns

    Ensures:
        - returns [ { "field_key", "text", "bare_yes" } ] in the order answered
        - a yes or no answer and a free-text answer are one entry under the whole-answer key
        - a field answer is one entry per header; its text is the picks joined, or the submitted text
        - bare_yes is True only for a yes with no qualifier
        - an answer that is none or unread gives []

    Raises:
        - ValueError if a card header is literally the whole-answer key, since its entry could not be told from a whole answer
    """
    kind = answer[ "kind" ]
    if kind == "stance":
        qualifier = answer[ "qualifier" ]
        text      = answer[ "stance" ] if not qualifier else f"{answer[ 'stance' ]} {qualifier}"
        return [ { "field_key": WHOLE_ANSWER_KEY, "text": text, "bare_yes": answer[ "stance" ] == "yes" and not qualifier } ]
    if kind == "text":
        return [ { "field_key": WHOLE_ANSWER_KEY, "text": answer[ "text" ] or "", "bare_yes": False } ]
    if kind == "fields":
        entries = []
        for header, record in answer[ "fields" ].items():
            if header == WHOLE_ANSWER_KEY: raise ValueError( f"card header {header!r} is reserved for the whole answer" )
            text = ", ".join( str( pick ) for pick in record[ "selected" ] ) or record[ "text" ] or ""
            entries.append( { "field_key": header, "text": text, "bare_yes": record.get( "stance" ) == "yes" and not record.get( "qualifier" ) } )
        return entries
    return []


def drafted_text( draft, field_key ):
    """
    Read the text of the draft for one field, from the shape the seen route stores.

    Requires:
        - draft is None, or a dict { "value": ... } as the seen route stores it
        - a whole-answer draft holds its text as a string under value
        - a card draft holds the card's answers map, as the answer door stores it: a JSON string or a dict under value

    Ensures:
        - returns the draft text for the field, or None when there is no draft or none for this field
        - a blank draft counts as no draft
        - a card field's text is its picks joined, or its submitted text
        - it does not use exposure.decode_answer_fields, which drops a yes or no comment and sorts picks, while this keeps both

    Raises:
        - ValueError when the draft is not None and cannot be read in that shape, so a changed shape is never skipped
    """
    if draft is None: return None
    if not isinstance( draft, dict ) or "value" not in draft: raise ValueError( f"draft at reveal is not in the stored shape {{ 'value': ... }}: {draft!r}" )
    value = draft[ "value" ]
    if value is None or value == "": return None
    if field_key == WHOLE_ANSWER_KEY:
        if not isinstance( value, str ): raise ValueError( f"a whole-answer draft must be text, got {value!r}" )
        return value
    fields = parse_field_selections( value if isinstance( value, dict ) else draft )
    if fields is None: raise ValueError( f"draft at reveal holds no readable answers map: {draft!r}" )
    record = fields.get( field_key )
    return None if record is None else ( ", ".join( str( pick ) for pick in record[ "selected" ] ) or record[ "text" ] or None )


def unaided_answer( final_text, draft, field_key, revealed_at, answered_at ):
    """
    Choose the text the extractor reads for a field, and whether it may be influenced.

    Requires:
        - final_text is the submitted text of the field
        - draft is None or in the shape drafted_text reads
        - revealed_at and answered_at are ISO strings, datetimes or None

    Ensures:
        - returns ( text, possibly_influenced )
        - with a draft for the field, returns the draft and False
        - with no draft, returns the final text; it is marked possibly influenced only when revealed_before_answer says so
          (the shared rule in exposure.py), so a reveal at the answer time or later counts as unaided

    Raises:
        - ValueError as drafted_text does
    """
    drafted = drafted_text( draft, field_key )
    if drafted:
        return drafted, False
    return final_text, revealed_before_answer( aware_moment( revealed_at ), aware_moment( answered_at ) )


def ground_condition( condition, grounding_text ):
    """
    Keep a condition only when its text appears in the card or the answer.

    Requires:
        - condition is a string or None
        - grounding_text is the card text and the answer text joined

    Ensures:
        - returns the condition when it is non-blank and its case-folded text occurs in the case-folded grounding text
        - returns the unknown label for a blank, missing or ungrounded condition
    """
    if condition and condition.strip() and condition.strip().casefold() in grounding_text.casefold(): return condition.strip()
    return UNKNOWN


def _names_project( statement, projects ):
    """
    Say whether a statement names any of the given projects as a whole word.

    Requires:
        - statement is a string and projects a list of lower-case names

    Ensures:
        - returns True when a project name occurs in the statement as a whole word, ignoring case
    """
    return any( re.search( rf"(?<![\w-]){re.escape( name )}(?![\w-])", statement, re.IGNORECASE ) for name in projects )


def check_hypothesis( hypothesis, grounding_text, projects ):
    """
    Check one hypothesis and return it cleaned, or the reason it is rejected.

    Requires:
        - hypothesis is a dict from the model's output
        - projects is the list project_names returns for the owner's asks

    Ensures:
        - returns ( cleaned, None ) or ( None, reason )
        - rejects a missing, blank or non-string statement, and a statement of 240 characters or more
        - scope is the global scope or the project scope of a listed project; any other scope is rejected
        - a global statement that names a listed project is rejected; a statement scoped to that project may name it
        - cleaned holds statement, rationale (string or None), scope, condition grounded as ground_condition does,
          and grounded_in as given or None
    """
    statement = hypothesis.get( "statement" )
    if not isinstance( statement, str ) or not statement.strip(): return None, "statement_missing"
    statement = statement.strip()
    if len( statement ) >= MAX_STATEMENT: return None, "statement_too_long"
    scope = hypothesis.get( "scope", GLOBAL_SCOPE )
    if scope != GLOBAL_SCOPE and not ( isinstance( scope, str ) and scope.startswith( PROJECT_SCOPE ) and scope[ len( PROJECT_SCOPE ): ] in projects ):
        return None, "scope_unknown"
    if scope == GLOBAL_SCOPE and _names_project( statement, projects ): return None, "global_statement_names_project"
    rationale = hypothesis.get( "rationale" )
    return { "statement": statement, "rationale": rationale if isinstance( rationale, str ) else None, "scope": scope,
             "condition": ground_condition( hypothesis.get( "condition" ), grounding_text ), "grounded_in": hypothesis.get( "grounded_in" ) }, None


def check_field( field_result, grounding_text, projects, bare_yes, neighbour_ids ):
    """
    Check the model's result for one field.

    Requires:
        - field_result is a dict with optional kind, dimension, hypotheses (a list) and relations (a dict of principle id to relation)
        - neighbour_ids is the set of principle ids the model was shown

    Ensures:
        - returns { "kind", "dimension", "hypotheses", "relations", "rejected" }
        - more than three hypotheses rejects every hypothesis of the field, with the reason too_many_hypotheses
        - a bare yes keeps no hypothesis (reason bare_yes_creates_none) and keeps only supports relations
        - a relation to a principle the model was not shown, or with an unknown relation word, is dropped and listed in rejected
        - a kind outside the two allowed, or a blank dimension, rejects the whole field: no hypothesis and no relation is kept
        - rejected is a list of { "what", "reason" }; nothing is dropped without an entry
    """
    rejected   = []
    kind       = field_result.get( "kind" )
    dimension  = field_result.get( "dimension" )
    raw        = field_result.get( "hypotheses" )
    raw        = raw if isinstance( raw, list ) else []
    hypotheses = []
    if kind not in KINDS or not isinstance( dimension, str ) or not dimension.strip():
        rejected.append( { "what": "field", "reason": "kind_or_dimension_invalid" } )
    elif len( raw ) > MAX_HYPOTHESES:
        rejected.append( { "what": "hypotheses", "reason": "too_many_hypotheses" } )
    elif bare_yes:
        if raw: rejected.append( { "what": "hypotheses", "reason": "bare_yes_creates_none" } )
    else:
        for index, hypothesis in enumerate( raw ):
            cleaned, reason = check_hypothesis( hypothesis, grounding_text, projects ) if isinstance( hypothesis, dict ) else ( None, "hypothesis_not_an_object" )
            if cleaned is None: rejected.append( { "what": f"hypothesis {index}", "reason": reason } )
            else: hypotheses.append( cleaned )
    relations = {}
    given     = field_result.get( "relations" )
    if rejected and rejected[ 0 ][ "reason" ] == "kind_or_dimension_invalid": given = None
    for principle_id, relation in ( given.items() if isinstance( given, dict ) else [] ):
        if principle_id not in neighbour_ids: rejected.append( { "what": f"relation {principle_id}", "reason": "principle_not_shown" } )
        elif relation not in RELATIONS: rejected.append( { "what": f"relation {principle_id}", "reason": "relation_unknown" } )
        elif bare_yes and relation != "supports": rejected.append( { "what": f"relation {principle_id}", "reason": "bare_yes_only_supports" } )
        else: relations[ principle_id ] = relation
    return { "kind": kind, "dimension": dimension.strip() if isinstance( dimension, str ) else None, "hypotheses": hypotheses,
             "relations": relations, "rejected": rejected }
