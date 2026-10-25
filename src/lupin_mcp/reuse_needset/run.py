"""
Run the drafting: plan, draw, one job per seed, parallel cells, needs and a report.

Nothing here talks to a model or an index by itself; the caller hands in the pieces, so a test can use fakes.
"""
import asyncio
import json
import pathlib

from lupin_mcp import reuse_need_check as nc
from lupin_mcp.reuse_needset import draft, keys, pool, quota, schema
from lupin_mcp.reuse_needset import errors as er

SAME_JOB_SYSTEM = "You compare two code definitions. Answer with one JSON object and nothing else."
PLAN_FILE       = "needset-plan.json"
DRAFTS_FILE     = "needset-drafts.jsonl"
REPORT_FILE     = "needset-draft-report.json"
REPORT_FORMAT   = "needset-draft-report-1"


class Env:
    """Everything a run reads: records, search context, model calls and run labels."""

    def __init__( self, by_id, kept, ctx, twins, strip_fn, ask, ledger, model_id, server, source_commit, seed, kind_split, set_by, set_at,
                  none_draft_fn=None, parallel=3, smoke=False, extras=None ):
        """
        Hold the inputs.

        Requires:
            - by_id maps every index id to its record and kept is the eligible list; ctx is a keys.KeyContext over kept
            - twins is pool.twin_map output; strip_fn( rec ) returns a strip.strip_member result
            - ask( system, user ) returns reply text; ledger is a draft.SharedLedger
            - none_draft_fn is draft.make_none_drafter output, needed only when the quota asks for nothing needs
            - extras is a dict of facts about the inputs that a report prints; it is not read by the run
        """
        self.by_id, self.kept, self.ctx, self.twins, self.strip_fn = by_id, kept, ctx, twins, strip_fn
        self.ask, self.ledger, self.model_id, self.server       = ask, ledger, model_id, server
        self.source_commit, self.seed, self.kind_split          = source_commit, seed, kind_split
        self.set_by, self.set_at, self.none_draft_fn            = set_by, set_at, none_draft_fn
        self.parallel, self.smoke                               = parallel, smoke
        self.extras                                             = {} if extras is None else extras


def cell_name( kind, lang ):
    """Return the cell's name, kind and language joined by a slash."""
    return f"{kind}/{lang}"


def write_or_check_plan( path, record ):
    """
    Write the plan record, or accept the one already on disk when it is the same.

    Ensures:
        - a first run writes the record once; a resume with an identical record changes nothing

    Raises:
        - NeedsetError PLAN_ALREADY_WRITTEN when a different plan is on disk
    """
    try:
        quota.write_plan( path, record )
    except er.NeedsetError:
        if json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) ) != record: raise


def near_copy_job( env, seed_id, lang ):
    """Build the job for a seed keyed on its twin group, or None without a twin."""
    twins = keys.twins_of( seed_id, env.twins, set( env.by_id ) )
    if not twins: return None
    seed = env.by_id[ seed_id ]
    return { "seed": seed, "keys": [ env.by_id[ t ] for t in twins ], "stripped": env.strip_fn( seed ), "write_lang": lang,
             "meta": { "route": None, "key_source": schema.TWIN_SOURCE, "key_lang": env.by_id[ twins[ 0 ] ][ "lang" ] } }


def routed_job( env, kind, seed_id, lang, route ):
    """Build the job for a work-alike seed through its route, or None without a key."""
    found = keys.find_key( env.ctx, seed_id, route, lambda prompt: env.ask( SAME_JOB_SYSTEM, prompt ), env.ledger, env.model_id, kind )
    if found[ "key" ] is None: return None
    seed, key = env.by_id[ seed_id ], env.by_id[ found[ "key" ] ]
    return { "seed": seed, "keys": [ key ], "stripped": env.strip_fn( seed ), "write_lang": lang,
             "meta": { "route": route, "key_source": found[ "source" ], "key_lang": key[ "lang" ], "asked": found[ "asked" ] } }


def nothing_job( env, file, lang ):
    """Build the job for a file: the entry line of each eligible symbol in it."""
    lines = [ nc.entry_text_of( r ) for r in env.kept if r[ "file" ] == file and r[ "lang" ] == lang ]
    return { "seed": file, "lines": lines, "write_lang": lang, "meta": { "route": None, "key_source": None, "key_lang": None } }


def route_table( env, kind, lang, order ):
    """Return { seed id: route } for a work-alike cell, half and half over its draw order."""
    return keys.assign_routes( order, f"{env.seed}|{kind}|{lang}" )


def job_maker( env, kind, lang, order ):
    """
    Return the make_job function of one cell.

    Ensures:
        - the returned function takes a seed id and returns a job, or None when the seed has no key
        - the routes of a work-alike cell are assigned half and half over the whole order, spares included
    """
    if kind == "near_copy": return lambda seed_id: near_copy_job( env, seed_id, lang )
    if kind == quota.NONE_KIND: return lambda file: nothing_job( env, file, lang )
    routes = route_table( env, kind, lang, order )
    return lambda seed_id: routed_job( env, kind, seed_id, lang, routes[ seed_id ] )


def to_need( record, kind, lang, env ):
    """
    Turn an accepted draft into a need record.

    Requires:
        - record is an ok draft_cell record of the cell ( kind, lang )

    Ensures:
        - returns schema.new_need over it, carrying smoke when the run is a smoke run
        - a nothing need has no seed, no key and no route
    """
    drafter = { "model": env.model_id, "prompt_version": draft.prompt_version(), "server": env.server }
    meta    = record[ "meta" ]
    if kind == quota.NONE_KIND:
        return schema.new_need( kind, lang, None, None, [], None, None, record[ "need" ], env.source_commit, drafter, env.smoke )
    return schema.new_need( kind, lang, record[ "seed" ], meta[ "route" ], record[ "key" ], meta[ "key_lang" ], meta[ "key_source" ], record[ "need" ], env.source_commit, drafter, env.smoke )


def cell_specs( env, drawn, quota_table ):
    """Build the draft_cells specs, one per cell with a wanted count, in sorted cell order."""
    specs = []
    for ( kind, lang ), row in drawn.items():
        wanted = quota_table[ kind ][ lang ]
        if wanted == 0: continue
        order = row[ "primary" ] + row[ "spares" ]
        spec  = dict( cell=cell_name( kind, lang ), wanted=wanted, order=order, make_job=job_maker( env, kind, lang, order ),
                      ask=env.ask, ledger=env.ledger, model_id=env.model_id )
        if kind == quota.NONE_KIND: spec[ "draft_fn" ] = env.none_draft_fn
        specs.append( spec )
    return specs


def run_needset( env, quota_table, out_dir ):
    """
    Write the plan, draw, draft every cell and write the drafts and the report.

    Requires:
        - quota_table comes from quota.plan_quota; out_dir exists
        - env.none_draft_fn is set when the quota holds nothing needs

    Ensures:
        - the plan record is written first, with the reader the pool used, and a resume checks it is unchanged
        - returns { plan, census, cells, needs, report } and writes the plan, the drafts and the report files into out_dir
        - needs are in cell order, then draw order

    Raises:
        - NeedsetError QUOTA_UNFILLABLE from the draw or from a cell that runs out of seeds
        - NeedsetError PLAN_ALREADY_WRITTEN when another plan is on disk
    """
    out       = pathlib.Path( out_dir )
    plan      = quota.plan_record( env.seed, quota_table, env.kind_split, env.source_commit, pool.READER, env.set_by, env.set_at )
    write_or_check_plan( out / PLAN_FILE, plan )
    cells     = pool.cell_pool( env.kept, env.twins, set( env.by_id ) )
    drawn     = quota.draw( cells, quota_table, env.seed )
    results   = asyncio.run( draft.draft_cells( cell_specs( env, drawn, quota_table ), env.parallel ) )
    needs     = [ to_need( rec, *r[ "cell" ].split( "/" ), env ) for r in results for rec in r[ "accepted" ] ]
    report    = { "format": REPORT_FORMAT, "smoke": env.smoke, "census": quota.census( cells ), "replacements": draft.replacement_report( results ),
                  "failed": { r[ "cell" ]: r[ "failed" ] for r in results }, "counts": { r[ "cell" ]: len( r[ "accepted" ] ) for r in results } }
    ( out / DRAFTS_FILE ).write_text( "".join( json.dumps( n, sort_keys=True ) + "\n" for n in needs ), encoding="utf-8" )
    ( out / REPORT_FILE ).write_text( json.dumps( report, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return { "plan": plan, "census": report[ "census" ], "cells": results, "needs": needs, "report": report }
