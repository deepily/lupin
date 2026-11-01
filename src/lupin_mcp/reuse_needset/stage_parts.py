"""
The live pieces of the attribution and yield stages: a final need per seed, and the trace.

By Cheech's ruling, a need becomes final without a person when the drafter's sentence passes the leak check and the second model agrees.
A disputed need is counted and dropped, and never traced. Every model call here goes through the cap that the runner has installed.
"""
import asyncio
import collections
import types

from cosa.repo.symindex.candidates import vector_store
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import check, draft, finalize, freeze, hardness, keys, loss_trace, run, stage_seeds, stages

KIND          = "work_alike"
SECOND_SYSTEM = "You answer with one JSON object and nothing else."
AGREED_LABEL = { "choice": None, "symbols": None, "final_source": finalize.MODEL_AGREED }
NOT_POOLED   = "not_pooled"
NO_PARTNER   = "no_partner"
DRAFT_FAILED = "draft_failed"
DISPUTED     = "disputed"


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


def final_need_fn( renv, routes, second_ask, second_ledger, second_model, tally, job_for=run.routed_job, draft_fn=draft.draft_need, check_fn=check.second_check ):
    """
    Return the synchronous function that turns one seed id into a final need, or None.

    Requires:
        - renv holds ctx ( keys.KeyContext ), ask, ledger, model_id, calls_log, by_id, strip_fn, server, source_commit and smoke, as run.routed_job and run.to_need read them
        - routes maps each seed id to its route; second_ask( prompt ) returns the second model's reply text
        - tally is a Tally

    Ensures:
        - a seed that has no row in the search pool, no partner or no accepted sentence is counted under not_pooled, no_partner or draft_failed and gives None
        - a need the second model does not agree to is counted under disputed, its id is kept, and it gives None
        - an agreed need is returned as finalize.final_row makes it, with final_source model_agreed and the key's source texts shown to the checker
    """
    def final_need( seed_id ):
        """Ensures: returns the final need of the seed, or None after counting why not."""
        if seed_id not in renv.ctx.by_id:
            tally[ NOT_POOLED ] += 1
            return None
        lang = renv.by_id[ seed_id ][ "lang" ]
        job  = job_for( renv, KIND, seed_id, lang, routes[ seed_id ] )
        if job is None:
            tally[ NO_PARTNER ] += 1
            return None
        record = draft_fn( job, renv.ask, renv.ledger, renv.model_id )
        if not record[ "ok" ]:
            tally[ DRAFT_FAILED ] += 1
            return None
        need    = run.to_need( record, KIND, lang, renv )
        checked = check_fn( need, second_ask, second_ledger, second_model, key_texts=[ renv.ctx.bodies[ i ] for i in need[ "key" ][ "symbols" ] ] )
        if check.disputed( checked ):
            tally[ DISPUTED ] += 1
            tally.ids.append( checked[ "id" ] )
            return None
        return finalize.final_row( checked, AGREED_LABEL )
    return final_need


def counted( tally ):
    """Ensures: returns the tally as a plain dict of the four counts and the disputed ids."""
    return { **{ k: tally[ k ] for k in ( NOT_POOLED, NO_PARTNER, DRAFT_FAILED, DISPUTED ) }, "disputed_ids": list( tally.ids ) }


class Tally( collections.Counter ):
    """A count of why seeds gave no final need, with the ids of the disputed ones."""

    def __init__( self ):
        """Ensures: starts empty, with an empty ids list."""
        super().__init__()
        self.ids = []


def yield_row( need ):
    """Ensures: returns the { seed, need, targets, lang } row that hardness.source_hard reads."""
    return { "seed": need[ "seed" ], "need": need[ "need" ], "targets": list( need[ "key" ][ "symbols" ] ), "lang": need[ "write_lang" ] }


def build_parts( env, built, lists, models, drafter, second, ledgers, trace_all=loss_trace.trace_all, identity=freeze.identity, load_vectors=vector_store.load_vectors ):
    """
    Return the four live parts of the attribution and yield stages.

    Requires:
        - env holds root, seed, source_commit, server, strip_fn and ctx ( the reuse context ); built is smoke.index_parts' result
        - lists come from stage_seeds.load_lists; models holds second and probe; drafter and second are ask( system, user ) functions
        - ledgers holds draft, second and trace, the three ledgers of the stages

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
    final    = final_need_fn( renv, route_table( lists, env.seed ), lambda prompt: second( SECOND_SYSTEM, prompt ), ledgers[ "second" ], models[ "second" ], tally )
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
