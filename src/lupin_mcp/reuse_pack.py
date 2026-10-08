"""
The packed request to Jev: its body, how its answers are read, and its cache keys.

One request holds the need once in `state` and one three-way question per candidate.
The question is the same one the single-entry path asks; only the packing differs.
Nothing in this module sends anything.
"""
from lupin_mcp import reuse_tools as rt

SHAPE      = "packed-choice-1"                                # names the body layout; a new layout needs a new name
KEY_PREFIX = "q_"


def question_key( entry_id ):
    """
    Name the question that asks about one entry.

    Ensures:
        - returns the same key for the same id, and a different key for a different id
    """
    return KEY_PREFIX + rt.sha( entry_id, 16 )


def pack_request( need, entries, template=rt.PROMPT_TEMPLATE, model=rt.JEV_MODEL ):
    """
    Build the body of one packed request.

    Requires:
        - entries is a non-empty list of symbol dicts with id, sig and doc
        - no two entries share an id
        - model is a pinned name, not a moving alias
    Ensures:
        - returns ( body, qmap ): qmap maps each entry id to its question key
        - state holds the need and nothing else
        - each entry has one choice question with the template's criteria and that entry's text in
          its instructions, so no candidate text reaches another candidate's question
    Raises:
        - ValueError for an empty pack, a repeated id, or a model that ends with "-latest"
    """
    if model.endswith( "-latest" ): raise ValueError( f"model {model!r} is a moving alias; pin a version" )
    if not entries: raise ValueError( "a pack cannot be empty" )
    ids = [ e[ "id" ] for e in entries ]
    if len( set( ids ) ) != len( ids ): raise ValueError( "a pack cannot hold a duplicate id: its questions would collide" )
    qmap      = { e[ "id" ]: question_key( e[ "id" ] ) for e in entries }
    questions = { qmap[ e[ "id" ] ]: { "type"         : "choice",
                                       "instructions" : template[ "instructions" ].replace( "CANDIDATE", f"the candidate {rt.entry_text( e )!r}" ),
                                       "criteria"     : template[ "criteria" ] } for e in entries }
    return { "model": model, "state": { "need": need }, "questions": questions }, qmap


def pack_answers( response, qmap ):
    """
    Read one response against the questions that were asked.

    Ensures:
        - returns ( answered, unasked ): answered maps an entry id to its probabilities mapping
        - an entry is answered only when its question has an answer holding a probabilities mapping
        - every other entry is unasked, in the order of qmap, and is never read as unrelated
        - an answer for a question that was not asked is ignored
    """
    try: answers = response[ "answers" ]
    except ( KeyError, TypeError ): answers = None
    if not isinstance( answers, dict ): return {}, list( qmap )
    answered, unasked = {}, []
    for entry_id, key in qmap.items():
        a = answers.get( key )
        if isinstance( a, dict ) and isinstance( a.get( "probabilities" ), dict ): answered[ entry_id ] = a[ "probabilities" ]
        else: unasked.append( entry_id )
    return answered, unasked


def stage1_key( need, text, pack_size, run_index, template=rt.PROMPT_TEMPLATE, model=rt.JEV_MODEL ):
    """
    Key a response in a measurement arm.

    Ensures:
        - the key holds the shape, model, template hash, need, candidate text, pack size and run index
        - two arms with different pack sizes or run indices never share an answer
    """
    return rt.sha( rt.canonical( { "shape": SHAPE, "model": model, "template": rt.prompt_template_hash( template ), "need": need,
                                   "candidate": text, "pack_size": pack_size, "run_index": run_index } ) )


def candidate_key( need, text, template=rt.PROMPT_TEMPLATE, model=rt.JEV_MODEL ):
    """
    Key one candidate's answer wherever it was packed.

    Ensures:
        - the key holds the shape, model, template hash, need and candidate text, and no pack size or run index
    """
    return rt.sha( rt.canonical( { "shape": SHAPE, "model": model, "template": rt.prompt_template_hash( template ), "need": need, "candidate": text } ) )


def pack_key( body ):
    """Ensures: returns the key of a whole packed body; a changed neighbour changes it."""
    return rt.request_hash( body )
