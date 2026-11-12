"""
The live pieces of the attribution and yield stages: a final need per seed, and the trace.

By Cheech's ruling, a need becomes final without a person when the drafter's sentence passes the checks and the second model agrees.
By Rick's ruling of 1 November, the seed is then the need's known answer and no partner is searched for.
Partner search is an option, off unless asked for.
A disputed need is counted and dropped, and never traced. Every model call here goes through the cap that the runner has installed.
Every rejected sentence, every disputed need and every unreadable reply goes to the rejection ledger.
"""
import asyncio
import collections
import json
import os
import time
import types

from cosa.repo.symindex.candidates import vector_store
from cosa.utils.jsonl_file import read_jsonl
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import check, draft, finalize, freeze, hardness, keys, loss_trace, run, schema, stage_seeds, stages

KIND          = "work_alike"
SECOND_SYSTEM = "You answer with one JSON object and nothing else."
AGREED_LABEL = { "choice": None, "symbols": None, "final_source": finalize.MODEL_AGREED }
NOT_POOLED   = "not_pooled"
NO_PARTNER   = "no_partner"
DRAFT_FAILED = "draft_failed"
DISPUTED     = "disputed"
UNREADABLE   = "unreadable_reply"
UNSTRIPPABLE = "unstrippable_seed"
REASONS      = ( NOT_POOLED, NO_PARTNER, DRAFT_FAILED, DISPUTED, UNREADABLE, UNSTRIPPABLE )


def route_table( lists, seed ):
    """
    Assign each listed seed its route, half and half within each stage and language.

    Requires:
        - lists come from stage_seeds.load_lists

    Ensures:
        - returns { seed id: route } over both stages; the two stages share no id
    """
    out = {}
    for name in ( stages.ATTRIBUTION, stages.YIELD ):
        for lang in stage_seeds.LANGS: out.update( keys.assign_routes( lists[ name ][ lang ], f"{seed}|{name}|{lang}" ) )
    return out


class RejectionLedger:
    """A file of one JSON line per rejection, flushed to disk as each is added."""

    def __init__( self, path ):
        """
        Hold the path.

        Requires:
            - path is a file in an existing directory; the file may not exist yet
        """
        self.path = str( path )

    def add( self, row ):
        """Ensures: appends the row with the time as one flushed line."""
        with open( self.path, "a", encoding="utf-8" ) as f:
            f.write( json.dumps( { **row, "at": time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) }, sort_keys=True ) + "\n" )
            f.flush()
            os.fsync( f.fileno() )

    def rows( self ):
        """Ensures: returns the rows in file order, [] for a file not yet written."""
        return read_jsonl( self.path, missing_ok=True )


def final_need_fn( renv, routes, second_ask, second_ledger, second_model, tally, rejections, partners=False, job_for=run.routed_job, draft_fn=draft.draft_need, check_fn=check.second_check ):
    """
    Return the synchronous function that turns one seed id into a final need, or None.

    Requires:
        - renv holds ctx ( keys.KeyContext ), ask, ledger, model_id, calls_log, by_id, strip_fn, server, source_commit and smoke, as run.routed_job and run.to_need read them
        - routes maps each seed id to its route; second_ask( prompt ) returns the second model's reply text
        - tally is a Tally; rejections has add( row ), as RejectionLedger has
        - partners is False for the seed to be its own known answer, and True to look for a partner through the routes

    Ensures:
        - with partners off no same-job call is made, and an agreed need is a seed-answer need whose key is the seed
        - a seed that has no row in the search pool, no partner or no accepted sentence is counted under not_pooled, no_partner or draft_failed and gives None; no_partner arises only with partners on
        - every sentence the checks rejected, even one the rewrite then replaced, adds a rejected_sentence row; every drafter reply that could not be read adds an unreadable_draft_reply row; a draft that ends rejected adds draft_failed
        - a disputed need adds a disputed row with the second model's result and note, and every check reply that could not be read adds an unreadable_check_reply row
        - a seed whose same-job or check reply is unreadable twice is counted under unreadable_reply, with its id, code and detail kept, adds a seed_skipped row, and gives None; the stage goes on to the next seed
        - a seed the strip step cannot find (STRIP_FAILED) is counted under unstrippable_seed the same way, with its id, code and detail kept and a seed_skipped row, so one seed cannot fail the stage
        - any other NeedsetError, the call cap's included, is raised
        - a need the second model does not agree to is counted under disputed, its id is kept, and it gives None
        - an agreed need is returned as finalize.final_row makes it, with final_source model_agreed and the key's source texts shown to the checker
    """
    def final_need( seed_id ):
        """Ensures: returns the final need of the seed, or None after counting why not."""
        try:
            return worked( seed_id )
        except er.NeedsetError as error:
            if error.code not in ( er.UNREADABLE_REPLY, er.STRIP_FAILED ): raise
            tally[ UNSTRIPPABLE if error.code == er.STRIP_FAILED else UNREADABLE ] += 1
            tally.skipped.append( { "seed": seed_id, "code": error.code, "detail": error.detail } )
            rejections.add( { "kind": "seed_skipped", "seed": seed_id, "code": error.code, "detail": error.detail } )
            return None

    def worked( seed_id ):
        """Ensures: returns the seed's final need, or None after counting why."""
        if seed_id not in renv.ctx.by_id:
            tally[ NOT_POOLED ] += 1
            return None
        lang = renv.by_id[ seed_id ][ "lang" ]
        job  = job_for( renv, KIND, seed_id, lang, routes[ seed_id ] ) if partners else run.seed_job( renv, seed_id, lang )
        if job is None:
            tally[ NO_PARTNER ] += 1
            return None
        record = draft_fn( job, renv.ask, renv.ledger, renv.model_id )
        for r in record[ "rejections" ]: rejections.add( { "kind": "rejected_sentence", "seed": seed_id, **r } )
        for r in record[ "unreadable" ]: rejections.add( { "kind": "unreadable_draft_reply", "seed": seed_id, **r } )
        if not record[ "ok" ]:
            tally[ DRAFT_FAILED ] += 1
            rejections.add( { "kind": "draft_failed", "seed": seed_id, "reason": record[ "reason" ], "tries": record[ "tries" ] } )
            return None
        need    = run.to_need( record, KIND, lang, renv )
        checked = check_fn( need, second_ask, second_ledger, second_model, key_texts=[ renv.ctx.bodies[ i ] for i in need[ "key" ][ "symbols" ] ],
                            on_unreadable=lambda reply: rejections.add( { "kind": "unreadable_check_reply", "seed": seed_id, "reply": reply } ) )
        if check.disputed( checked ):
            tally[ DISPUTED ] += 1
            tally.ids.append( checked[ "id" ] )
            rejections.add( { "kind": "disputed", "seed": seed_id, "need": checked[ "id" ], "result": checked[ "check" ][ "result" ], "note": checked[ "check" ][ "note" ] } )
            return None
        return finalize.final_row( checked, AGREED_LABEL )
    return final_need


def mark( tally ):
    """Ensures: returns what the tally holds now, to hand to counted as the point a stage began."""
    return ( dict( tally ), len( tally.ids ), len( tally.skipped ) )


def counted( tally, since=None ):
    """
    Return the reason counts, disputed ids and skipped seeds that grew since a mark.

    Requires:
        - since is None for everything, or what mark( tally ) returned earlier

    Ensures:
        - a stage that began at the mark reports only its own seeds, not those of a stage that ran before it
        - skipped lists each seed skipped for an unreadable reply, with its code and detail
    """
    before, first, skipped = ( {}, 0, 0 ) if since is None else since
    return { **{ k: tally[ k ] - before.get( k, 0 ) for k in REASONS }, "disputed_ids": tally.ids[ first: ], "skipped": tally.skipped[ skipped: ] }


class Tally( collections.Counter ):
    """A count of why seeds gave no final need, with the disputed ids and the skipped seeds."""

    def __init__( self ):
        """Ensures: starts empty, with an empty ids list and an empty skipped list."""
        super().__init__()
        self.ids     = []
        self.skipped = []


def yield_row( need ):
    """Ensures: returns the row hardness.source_hard reads, with seed_is_answer set."""
    return { "seed": need[ "seed" ], "need": need[ "need" ], "targets": list( need[ "key" ][ "symbols" ] ), "lang": need[ "write_lang" ], "seed_is_answer": need[ "key" ][ "source" ] == schema.SEED_SOURCE }


def build_parts( env, built, lists, models, drafter, second, ledgers, partners=False, trace_all=loss_trace.trace_all, identity=freeze.identity, load_vectors=vector_store.load_vectors ):
    """
    Return the four live parts of the attribution and yield stages.

    Requires:
        - env holds root, seed, source_commit, server, strip_fn and ctx ( the reuse context ); built is smoke.index_parts' result
        - lists come from stage_seeds.load_lists; models holds second and probe; drafter and second are ask( system, user ) functions
        - ledgers holds draft, second, trace and rejections, the ledgers of the stages; rejections has add( row )
        - partners is False unless a partner search was asked for, and then each seed is its own known answer

    Ensures:
        - returns { make_need, prepare_fn, trace_fn, index, tally }
        - make_need and prepare_fn run the blocking calls on a worker thread, one seed at a time, under the cap's stage name
        - trace_fn is loss_trace.trace_all over the run's ctx, trace ledger and the index and vector identity taken now
        - the identity is read when the parts are built and again at each trace, so an index or vector set that moves mid-run is refused before any call
    """
    by_id, kept, measures, twins, bodies = built
    vectors  = load_vectors( env.ctx.candidate_stage.vectors_dir )
    rows     = set( vectors.ids )
    pooled   = [ r for r in kept if r[ "id" ] in rows ]
    renv     = types.SimpleNamespace( ctx=keys.KeyContext( pooled, measures, bodies, env.seed, vectors ), ask=drafter, ledger=ledgers[ "draft" ], model_id=draft.DRAFTER_MODEL,
                                      calls_log=None, by_id=by_id, strip_fn=env.strip_fn, server=env.server, source_commit=env.source_commit, smoke=False )
    tally    = Tally()
    final    = final_need_fn( renv, route_table( lists, env.seed ), lambda prompt: second( SECOND_SYSTEM, prompt ), ledgers[ "second" ], models[ "second" ], tally, ledgers[ "rejections" ], partners )
    gen      = lambda: rt.prepare( env.ctx )[ 3 ]
    frozen   = identity( gen(), env.ctx.candidate_stage.vectors_dir )

    async def make_need( seed_id ):
        """Ensures: returns the seed's final need, or None."""
        return await asyncio.to_thread( final, seed_id )

    async def prepare_fn( seed_id ):
        """Ensures: returns the seed's yield row, or None."""
        need = await asyncio.to_thread( final, seed_id )
        return None if need is None else yield_row( need )

    async def trace_fn( needs ):
        """Ensures: returns the trace records of the needs."""
        live = identity( gen(), env.ctx.candidate_stage.vectors_dir )
        return await trace_all( needs, env.ctx, ledgers[ "trace" ], env.root, models[ "probe" ], env.source_commit, frozen, live )

    return { "make_need": make_need, "prepare_fn": prepare_fn, "trace_fn": trace_fn, "index": hardness.build_index( list( by_id.values() ) ), "tally": tally }
