"""
Need expansion: does asking for paraphrases and identifier words lift the known answer?

This is a draft and has not been run. It holds the pure parts and takes the model and the search as arguments.
Each known-answer need gets one drafter call. The model sees the need sentence only, never the code, so the key cannot leak.
The need is then searched five ways: as written, in three paraphrases, and as the identifier words joined into one query.
The lists of the five searches are fused into one. The report gives the known answer's fused rank before and after, and whether it enters the 128 shortlist.
It makes no call of its own and builds no packet.
"""
import json

from cosa.repo.doc_lint import harness_runner
from cosa.repo.symindex.candidates import rank_fusion as rf

STAGE_NAME = "expansion"
BUDGET     = 140                  # 124 needs (37 attribution, 70 yield, 17 control originals) with room for retries
VERSION    = "expansion-1"
SHORTLIST  = 128
SYSTEM     = "You answer with one JSON object and nothing else."
PROMPT     = ( "Below is a one-sentence description of a function someone wants to find in a codebase.\n"
               "Reply with JSON {{\"paraphrases\": [three different wordings of the same description], \"identifiers\": [five words likely to appear in the "
               "function's name, its parameters or its file path]}}. Do not guess a full function name.\n\nDescription: {need}\n" )


def expansion_prompt( need ):
    """
    Build the user prompt for one need.

    Requires:
        - need is the need sentence

    Ensures:
        - returns text holding the sentence and nothing from the code
    """
    return PROMPT.format( need=need )


def parse_expansion( reply ):
    """
    Read the model's reply.

    Requires:
        - reply is the reply text

    Ensures:
        - returns { paraphrases, identifiers } with three paraphrases and one to five identifier words, each stripped and non-empty
        - returns None when the reply is not that shape
    """
    try:
        obj = json.loads( reply[ reply.index( "{" ):reply.rindex( "}" ) + 1 ] )
        paraphrases, identifiers = obj[ "paraphrases" ], obj[ "identifiers" ]
    except ( ValueError, KeyError, TypeError ):
        return None
    shaped = isinstance( paraphrases, list ) and isinstance( identifiers, list ) and len( paraphrases ) == 3 and 1 <= len( identifiers ) <= 5
    if not shaped or not all( isinstance( x, str ) and x.strip() for x in paraphrases + identifiers ): return None
    return { "paraphrases": [ x.strip() for x in paraphrases ], "identifiers": [ x.strip() for x in identifiers ] }


def queries_for( need, expansion ):
    """
    List the five query texts of a need.

    Ensures:
        - returns the need, the three paraphrases, then the identifier words joined by spaces, in that order
    """
    return [ need ] + expansion[ "paraphrases" ] + [ " ".join( expansion[ "identifiers" ] ) ]


def expansion_key( need, model_id ):
    """
    Name the ledger entry that holds a need's saved reply.

    Ensures:
        - returns the key expand_need reads and writes, so a count of saved replies uses the same key
    """
    return harness_runner.ledger_key( STAGE_NAME, { "old": need, "new": expansion_prompt( need ) }, VERSION, model_id, 0 )


def expand_need( need, ask, ledger, model_id ):
    """
    Ask for the expansion of one need once, or read the ledger's saved reply.

    Requires:
        - ask( system, prompt ) returns the reply text; ledger has get( key ) and put( key, value )

    Ensures:
        - the reply is saved before it is read, so an unreadable reply is not paid for twice
        - returns parse_expansion's result
    """
    prompt = expansion_prompt( need )
    key    = expansion_key( need, model_id )
    reply  = ledger.get( key )
    if reply is None:
        reply = ask( SYSTEM, prompt )
        ledger.put( key, reply )
    return parse_expansion( reply )


def union_rank( lists_by_query, known_id, fusion ):
    """
    Rank the known answer before and after the expansion.

    Requires:
        - lists_by_query holds one { source: ranked ids } mapping per query, the need as written first
        - fusion is { k, depth, head }

    Ensures:
        - returns { before, after, enters_before, enters_after }
        - before fuses the first query's lists only, after fuses every list of every query
        - a rank is 1-based, or None when the answer is outside the fused list
        - enters is True when the rank is at most the shortlist size, 128
    """
    def rank( maps ):
        order = rf.fuse( [ ids for m in maps for _, ids in sorted( m.items() ) ], fusion[ "k" ], fusion[ "depth" ], fusion[ "head" ] )
        return order.index( known_id ) + 1 if known_id in order else None
    before, after = rank( lists_by_query[ :1 ] ), rank( lists_by_query )
    return { "before": before, "after": after, "enters_before": before is not None and before <= SHORTLIST, "enters_after": after is not None and after <= SHORTLIST }


def replay( rows, ask, ledger, search, fusion, model_id, into=None ):
    """
    Expand each need, search it five ways and rank its known answer.

    Requires:
        - rows are { id, group, need, known_id } mappings
        - search( query ) returns { source: ranked ids } for one query text

    Ensures:
        - returns one result per row in order, holding id, group and union_rank's figures
        - a row whose reply is unreadable gets unreadable True and no ranks, and is never searched
        - when into is a list, each result is added to it as it is made and it is returned, so an error part-way keeps the finished rows
    """
    out = [] if into is None else into
    for row in rows:
        expansion = expand_need( row[ "need" ], ask, ledger, model_id )
        if expansion is None:
            out.append( { "id": row[ "id" ], "group": row[ "group" ], "unreadable": True } )
            continue
        lists = [ search( q ) for q in queries_for( row[ "need" ], expansion ) ]
        out.append( { "id": row[ "id" ], "group": row[ "group" ], "unreadable": False, **union_rank( lists, row[ "known_id" ], fusion ) } )
    return out


def summarize( results ):
    """
    Count the outcome per group.

    Ensures:
        - returns { group: { needs, unreadable, enter_before, enter_after, lifted, lowered } } sorted by group
        - lifted counts the answers whose rank improved or that came into the fused list, lowered those that got worse or left it
    """
    out = {}
    for r in results:
        g = out.setdefault( r[ "group" ], { "needs": 0, "unreadable": 0, "enter_before": 0, "enter_after": 0, "lifted": 0, "lowered": 0 } )
        g[ "needs" ] += 1
        if r[ "unreadable" ]:
            g[ "unreadable" ] += 1
            continue
        g[ "enter_before" ] += r[ "enters_before" ]
        g[ "enter_after" ]  += r[ "enters_after" ]
        b, a = r[ "before" ], r[ "after" ]
        g[ "lifted" ]  += a is not None and ( b is None or a < b )
        g[ "lowered" ] += b is not None and ( a is None or a > b )
    return dict( sorted( out.items() ) )
