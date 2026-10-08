"""
The packed request to Jev: its body, how its answers are read, and its cache keys.

One request holds the need once in `state` and one three-way question per candidate.
The question is the same one the single-entry path asks; only the packing differs.
Nothing in this module sends anything.
"""
from cosa.repo.doc_lint import jev_transport as jt
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


def _row( request_hash, entries, parent ):
    """Ensures: returns a request row before the request is sent, with every outcome field empty."""
    return { "request_hash": request_hash, "size": len( entries ), "ids": [ e[ "id" ] for e in entries ], "split_from": parent, "status": None,
             "attempts": 0, "tokens_in": None, "tokens_out": None, "unasked": [], "http": None, "http_status": None, "error": None }


def _post( transport, body ):
    """Ensures: returns ( response, meta ); meta is None for a transport that only has post()."""
    if hasattr( transport, "post_with_meta" ): return transport.post_with_meta( body )
    return transport.post( body ), None


def send_pack( transport, need, entries, template=rt.PROMPT_TEMPLATE, model=rt.JEV_MODEL, budget=None, parent=None ):
    """
    Send one pack and account for every entry in it.

    Requires:
        - entries is a non-empty list of symbol dicts with unique ids
        - transport has post_with_meta( body ) returning ( response, meta ), or post( body )
        - budget, when given, is a TokenBudget; attempts are read from its tally
        - parent is the request hash of the pack this one was split from, or None
    Ensures:
        - returns { answers, failed, not_reached, rows }: answers are { id, probabilities } in entry order
        - an entry is answered only when its answer is present; every other entry is failed, never unrelated
        - a 422 splits the pack in half and resends each half, the larger half second; a 422 on one entry
          fails that entry
        - an attempt refused by the budget before any HTTP leaves the pack not reached
        - any other error fails every entry of the pack, and the row keeps the error class and HTTP status
        - rows lists this request first, then the rows of its halves, each with status answered, failed,
          refused or not_reached, its attempts, its reported tokens and the ids it asked about
    Raises:
        - ValueError for an empty pack
    """
    if not entries: raise ValueError( "a pack cannot be empty" )
    body, qmap = pack_request( entries=entries, need=need, template=template, model=model )
    row        = _row( pack_key( body ), entries, parent )
    response, meta, error, sent = None, None, None, True
    if budget is not None: budget.open_request( body, len( entries ) ); budget.begin_tally()
    try:
        response, meta = _post( transport, body )
    except Exception as e:                                          # any transport error ends this one request, never the run
        error = e
    taken = budget.end_tally() if budget is not None else None
    if isinstance( error, jt.JevBudgetSpent ): sent = False
    row[ "attempts" ] = taken if taken is not None else ( meta[ "attempts" ] if meta is not None else ( 1 if sent else 0 ) )
    if error is None:
        usage = rt.usage_of( response )
        if budget is not None: budget.close_request( usage )
        answered, unasked = pack_answers( response, qmap )
        row.update( http=meta, tokens_in=usage[ 0 ] if usage else None, tokens_out=usage[ 1 ] if usage else None, unasked=unasked )
        row[ "status" ] = "answered" if answered else "failed"
        if not answered: row[ "error" ] = "NoAnswers"
        return { "answers": [ { "id": i, "probabilities": answered[ i ] } for i in row[ "ids" ] if i in answered ], "failed": unasked, "not_reached": [], "rows": [ row ] }
    if budget is not None: budget.fail_request()
    if isinstance( error, jt.JevConfigError ): row[ "http_status" ] = error.status
    if isinstance( error, jt.JevConfigError ) and error.status == 422:
        row[ "status" ] = "refused"
        if len( entries ) == 1: return { "answers": [], "failed": row[ "ids" ], "not_reached": [], "rows": [ row ] }
        half  = len( entries ) // 2
        left  = send_pack( transport, need, entries[ :half ], template, model, budget, row[ "request_hash" ] )
        right = send_pack( transport, need, entries[ half: ], template, model, budget, row[ "request_hash" ] )
        return { "answers": left[ "answers" ] + right[ "answers" ], "failed": left[ "failed" ] + right[ "failed" ],
                 "not_reached": left[ "not_reached" ] + right[ "not_reached" ], "rows": [ row ] + left[ "rows" ] + right[ "rows" ] }
    if not sent and row[ "attempts" ] == 0:
        row[ "status" ] = "not_reached"
        return { "answers": [], "failed": [], "not_reached": row[ "ids" ], "rows": [ row ] }
    row[ "status" ], row[ "error" ] = "failed", type( error ).__name__
    return { "answers": [], "failed": row[ "ids" ], "not_reached": [], "rows": [ row ] }
