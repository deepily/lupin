"""
The packed request to Jev: its body, how its answers are read, and its cache keys.

One request holds the need once in `state` and one three-way question per candidate.
The question is the same one the single-entry path asks; only the packing differs.
Nothing in this module sends anything.
"""
import concurrent.futures

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_tools as rt

SHAPE           = "packed-choice-1"                           # names the body layout; a new layout needs a new name
KEY_PREFIX      = "q_"
WORKERS_MIN     = 4
WORKERS_MAX     = 8
WORKERS_DEFAULT = 6
KEY_MODES       = ( "candidate", "stage1" )


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
             "attempts": 0, "tokens_in": None, "tokens_out": None, "unasked": [], "http": None, "http_status": None, "error": None, "model": None }


def _post( transport, body ):
    """Ensures: returns ( response, meta ); meta is None for a transport that only has post()."""
    if hasattr( transport, "post_with_meta" ): return transport.post_with_meta( body )
    return transport.post( body ), None


def send_pack( transport, need, entries, template=rt.PROMPT_TEMPLATE, model=rt.JEV_MODEL, budget=None, parent=None, breaker=None ):
    """
    Send one pack and account for every entry in it.

    Requires:
        - entries is a non-empty list of symbol dicts with unique ids
        - transport has post_with_meta( body ) returning ( response, meta ), or post( body )
        - budget, when given, is a TokenBudget; attempts are read from its tally
        - parent is the request hash of the pack this one was split from, or None
        - breaker, when given, is a RefusalBreaker; it hears a 422 of a top-level pack once, under that pack's hash,
          and every answered request
    Ensures:
        - returns { answers, failed, not_reached, rows }: answers are { id, probabilities } in entry order
        - an entry is answered only when its answer is present; every other entry is failed, never unrelated
        - a 422 splits the pack in half and resends each half, the larger half second; a 422 on one entry
          fails that entry
        - an attempt refused by the budget before any HTTP leaves the pack not reached
        - a stopped breaker leaves the pack, or the halves not yet sent, not reached with no HTTP
        - any other error fails every entry of the pack; the row keeps the error class, and the HTTP status
          for a refused key or request (a JevConfigError), which is the only error that carries one
        - rows lists this request first, then the rows of its halves, each with status answered, failed,
          refused or not_reached, its attempts, its reported tokens and the ids it asked about
    Raises:
        - ValueError for an empty pack
        - ReuseError BAD_SPEND_LIMIT for a live transport whose budget is not a TokenBudget; nothing is posted
    """
    if not entries: raise ValueError( "a pack cannot be empty" )
    if isinstance( transport, rt.LiveJevTransport ) and not isinstance( transport.budget, rc.TokenBudget ):
        raise rt.ReuseError( "BAD_SPEND_LIMIT", "a live packed send needs a TokenBudget on its transport" )
    body, qmap = pack_request( entries=entries, need=need, template=template, model=model )
    row        = _row( pack_key( body ), entries, parent )
    if breaker is not None and breaker.stopped:
        row[ "status" ] = "not_reached"
        return { "answers": [], "failed": [], "not_reached": row[ "ids" ], "rows": [ row ] }
    response, meta, error, sent = None, None, None, True
    metered = isinstance( budget, rc.TokenBudget )
    if metered: budget.open_request( body, len( entries ) )
    if budget is not None: budget.begin_tally()
    try:
        response, meta = _post( transport, body )
    except Exception as e:                                          # any transport error ends this one request, never the run
        error = e
    taken = budget.end_tally() if budget is not None else None
    if isinstance( error, jt.JevBudgetSpent ): sent = False
    row[ "attempts" ] = taken if taken is not None else ( meta[ "attempts" ] if meta is not None else ( 1 if sent else 0 ) )
    if error is None:
        usage = rt.usage_of( response )
        if metered: budget.close_request( usage )
        answered, unasked = pack_answers( response, qmap )
        row.update( http=meta, tokens_in=usage[ 0 ] if usage else None, tokens_out=usage[ 1 ] if usage else None, unasked=unasked,
                    model=response[ "model" ] if isinstance( response, dict ) and "model" in response else None )
        row[ "status" ] = "answered" if answered else "failed"
        if not answered: row[ "error" ] = "NoAnswers"
        elif breaker is not None: breaker.answered()
        return { "answers": [ { "id": i, "probabilities": answered[ i ] } for i in row[ "ids" ] if i in answered ], "failed": unasked, "not_reached": [], "rows": [ row ] }
    if metered: budget.fail_request()
    if isinstance( error, jt.JevConfigError ): row[ "http_status" ] = error.status
    if isinstance( error, jt.JevConfigError ) and error.status == 422:
        row[ "status" ] = "refused"
        if breaker is not None and parent is None: breaker.refused( row[ "request_hash" ] )          # the halves of this pack are one family
        if len( entries ) == 1: return { "answers": [], "failed": row[ "ids" ], "not_reached": [], "rows": [ row ] }
        half  = len( entries ) // 2
        left  = send_pack( transport, need, entries[ :half ], template, model, budget, row[ "request_hash" ], breaker )
        right = send_pack( transport, need, entries[ half: ], template, model, budget, row[ "request_hash" ], breaker )
        return { "answers": left[ "answers" ] + right[ "answers" ], "failed": left[ "failed" ] + right[ "failed" ],
                 "not_reached": left[ "not_reached" ] + right[ "not_reached" ], "rows": [ row ] + left[ "rows" ] + right[ "rows" ] }
    if not sent and row[ "attempts" ] == 0:
        row[ "status" ] = "not_reached"
        return { "answers": [], "failed": [], "not_reached": row[ "ids" ], "rows": [ row ] }
    row[ "status" ], row[ "error" ] = "failed", type( error ).__name__
    return { "answers": [], "failed": row[ "ids" ], "not_reached": [], "rows": [ row ] }


def _check_sweep_args( size, workers, key_mode, run_index ):
    """Raises: ValueError naming the argument that is out of range."""
    if type( size ) is not int or size < 1: raise ValueError( f"size must be a positive integer, got {size!r}" )
    if type( workers ) is not int or not WORKERS_MIN <= workers <= WORKERS_MAX: raise ValueError( f"workers must be an integer from {WORKERS_MIN} to {WORKERS_MAX}, got {workers!r}" )
    if key_mode not in KEY_MODES: raise ValueError( f"key_mode must be one of {KEY_MODES}, got {key_mode!r}" )
    if key_mode == "stage1" and ( type( run_index ) is not int or run_index < 1 ): raise ValueError( f"a stage1 sweep needs a run_index of 1 or more, got {run_index!r}" )


def _entry_response( probabilities, row ):
    """Ensures: returns one entry's cached form: the old single answer plus its pack."""
    return { "answers": { "fit": { "probabilities": probabilities } }, "model": row[ "model" ], "pack": { "request_hash": row[ "request_hash" ], "size": row[ "size" ] } }


def sweep_packed( ctx, need, entries, size, workers=WORKERS_DEFAULT, key_mode="candidate", run_index=None, template=None, model=None,
                  frozen=False, gaps=None, budget=None, breaker=None ):
    """
    Ask Jev about every entry in packs.

    Requires:
        - entries are symbol dicts with id, sig and doc; size is the most entries in one request
        - workers is from WORKERS_MIN to WORKERS_MAX
        - key_mode "candidate" keys each answer by need and candidate text alone; "stage1" adds the pack size and
          the run index, so a measurement arm never reads another arm's answers or the production answers
        - when frozen, no transport is used and every answer must already be cached, except the ids in `gaps`
        - breaker, when given, is a RefusalBreaker shared with the caller; else the sweep makes one from BREAKER_422
        - a refused pack and all its halves are one refusal, keyed by the top-level pack's hash; BREAKER_422 refused
          packs in a row, with no answered request between them, stop the sweep and the rest is not reached
    Ensures:
        - returns every key sweep() returns, plus rows (one per HTTP request), requests, unasked and cache_write_failed
        - answered entries are in entry order; a cache hit costs no request and the misses are packed together
        - every answered entry is cached on its own, with the pack it came from
        - failed_attempts holds one { request, ids, attempts } for each request that left entries without an answer
        - attempts_answered and attempts_failed split the rows' attempts by whether the request was answered
        - a pack the budget refuses is not reached and no HTTP is made for it
    Raises:
        - ValueError for an argument out of range
        - ReuseError CACHE_MISSING or CACHE_CORRUPT when frozen and an answer is absent or damaged
    """
    _check_sweep_args( size, workers, key_mode, run_index )
    template, model = template or ctx.template, model or ctx.model
    if budget is None and isinstance( ctx.transport, rt.LiveJevTransport ): budget = ctx.transport.budget
    cache = rt.JevCache( ctx.data )
    breaker = rt.RefusalBreaker( rt.BREAKER_422 ) if breaker is None else breaker

    def key_of( rec ):
        text = rt.entry_text( rec )
        return candidate_key( need, text, template, model ) if key_mode == "candidate" else stage1_key( need, text, size, run_index, template, model )

    state, misses = {}, []                                          # state maps an entry id to its answer, or to ( "failed" | "not_reached" )
    for rec in entries:
        if frozen and gaps is not None and rec[ "id" ] in gaps: state[ rec[ "id" ] ] = gaps[ rec[ "id" ] ]; continue
        hit = cache.get( key_of( rec ) )
        if hit is not None: state[ rec[ "id" ] ] = ( "hit", rt.parse_answer( hit ) ); continue
        if frozen: raise rt.ReuseError( "CACHE_MISSING", f"{rec[ 'id' ]} ({key_of( rec )})" )
        misses.append( rec )
    by_id  = { rec[ "id" ]: rec for rec in entries }
    chunks = [ misses[ i:i + size ] for i in range( 0, len( misses ), size ) ]

    def one( chunk ):
        out = send_pack( ctx.transport, need, chunk, template, model, budget, breaker=breaker )
        unwritten = []
        row_of = { i: r for r in out[ "rows" ] if r[ "status" ] == "answered" for i in r[ "ids" ] }
        for a in out[ "answers" ]:
            try: cache.put( key_of( by_id[ a[ "id" ] ] ), _entry_response( a[ "probabilities" ], row_of[ a[ "id" ] ] ) )
            except OSError: unwritten.append( a[ "id" ] )
        return out, unwritten

    with concurrent.futures.ThreadPoolExecutor( max_workers=workers ) as pool:
        results = list( pool.map( one, chunks ) )
    rows, unwritten = [], []
    for out, bad in results:
        for a in out[ "answers" ]: state[ a[ "id" ] ] = ( "live", a[ "probabilities" ] )
        for i in out[ "failed" ]: state[ i ] = "failed"
        for i in out[ "not_reached" ]: state[ i ] = "not_reached"
        rows += out[ "rows" ]; unwritten += bad
    for n, r in enumerate( rows ): r[ "index" ] = n
    answers = [ { "id": rec[ "id" ], "probabilities": state[ rec[ "id" ] ][ 1 ] } for rec in entries if isinstance( state[ rec[ "id" ] ], tuple ) ]
    failed_attempts = []
    for r in rows:
        left = r[ "unasked" ] if r[ "status" ] == "answered" else ( r[ "ids" ] if r[ "status" ] == "failed" or ( r[ "status" ] == "refused" and r[ "size" ] == 1 ) else [] )
        if left: failed_attempts.append( { "request": r[ "request_hash" ], "ids": left, "attempts": r[ "attempts" ] } )
    return { "answers": answers,
             "failed": [ rec[ "id" ] for rec in entries if state[ rec[ "id" ] ] == "failed" ],
             "not_reached": [ rec[ "id" ] for rec in entries if state[ rec[ "id" ] ] == "not_reached" ],
             "calls": sum( 1 for v in state.values() if isinstance( v, tuple ) and v[ 0 ] == "live" ),
             "cache_hits": sum( 1 for v in state.values() if isinstance( v, tuple ) and v[ 0 ] == "hit" ),
             "attempts_answered": sum( r[ "attempts" ] for r in rows if r[ "status" ] == "answered" ),
             "attempts_failed": sum( r[ "attempts" ] for r in rows if r[ "status" ] != "answered" ),
             "failed_attempts": failed_attempts,
             "tokens_in": sum( r[ "tokens_in" ] or 0 for r in rows ), "tokens_out": sum( r[ "tokens_out" ] or 0 for r in rows ),
             "usage_missing": sum( 1 for r in rows if r[ "status" ] == "answered" and r[ "tokens_in" ] is None ),
             "transport_calls": [ { **r[ "http" ], "model": r[ "model" ] } for r in rows if r[ "http" ] is not None ],
             "rows": rows, "requests": len( rows ), "unasked": [ i for r in rows if r[ "status" ] == "answered" for i in r[ "unasked" ] ],
             "cache_write_failed": unwritten, "refused_422": breaker.refusals, "stopped_by": "consecutive_422" if breaker.stopped else None }


def packed_sweeper( size, workers=WORKERS_DEFAULT, breaker=None ):
    """
    Make the sweeper a ReuseContext takes for the packed path.

    Requires:
        - size and workers are in range for sweep_packed
    Ensures:
        - returns a function with sweep's signature that sweeps in packs with the per-candidate cache key
        - the same function serves the page asks and the entry asks, so both travel through one transport
    Raises:
        - ValueError for a size or worker count out of range
    """
    _check_sweep_args( size, workers, "candidate", None )

    def sweeper( ctx, need, entries, frozen=False, template=None, model=None, gaps=None ):
        return sweep_packed( ctx, need, entries, size, workers=workers, key_mode="candidate", template=template, model=model,
                             frozen=frozen, gaps=gaps, breaker=breaker )

    return sweeper
