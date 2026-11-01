"""
The seed lists and the first two stage functions of the first 1,000 calls.

Plan section 11.4 sets the quotas.

Fifty attribution seeds and a hundred yield seeds are drawn once from real tracked code with a recorded seed. They are written to
the run folder before any call, and the stage functions read them back from that file. The draw makes no call and no stage here contacts a model by itself.
"""
import hashlib
import json
import pathlib
import random

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import pool, stages

FORMAT            = "needset-first-thousand-seeds-1"
LISTS_FILE        = "first-thousand-seeds.json"
LANGS             = ( "ts", "py" )
ATTRIBUTION_QUOTA = { "ts": 30, "py": 20 }
YIELD_QUOTA       = { "ts": 50, "py": 50 }


def planted_ids( pairs ):
    """
    List every id of Set A's planted pairs, originals and rewrites.

    Requires:
        - pairs come from positive_control.load_pairs

    Ensures:
        - returns a set holding both ids of every pair
    """
    return { p[ side ][ "id" ] for p in pairs for side in ( "original", "rewrite" ) }


def interleave( by_lang ):
    """
    Merge the per-language lists into one order that alternates languages while both last.

    Ensures:
        - returns every id once, ts first, then py, then ts again, until one language is spent and the rest follow in order
        - a run that is stopped part-way still holds both languages
    """
    ts, py = list( by_lang[ "ts" ] ), list( by_lang[ "py" ] )
    out    = []
    while ts or py:
        if ts: out.append( ts.pop( 0 ) )
        if py: out.append( py.pop( 0 ) )
    return out


def sample_lang( ids, seed, stage_name, lang, count ):
    """
    Draw count ids of one language from a sorted pool.

    Ensures:
        - uses random.Random seeded by the draw seed, the stage and the language, so the order of the pool never matters
        - raises NeedsetError QUOTA_UNFILLABLE naming the stage and language when the pool is short
    """
    if len( ids ) < count: raise er.NeedsetError( er.QUOTA_UNFILLABLE, f"{stage_name}/{lang}: {len( ids )} eligible seeds, {count} wanted" )
    return random.Random( f"{seed}|{stage_name}|{lang}" ).sample( sorted( ids ), count )


def lists_sha( record ):
    """Ensures: returns the sha256 of the record without its own sha, over sorted keys."""
    body = { k: v for k, v in record.items() if k != "sha" }
    return hashlib.sha256( json.dumps( body, sort_keys=True ).encode( "utf-8" ) ).hexdigest()


def draw_lists( kept, seed, planted, source_commit, tracked=None ):
    """
    Draw the attribution and yield seed lists.

    Requires:
        - kept are eligible index records sorted by id, each with id, file and lang (pool.eligible output)
        - planted is the set from planted_ids; tracked is None or the set of tracked file paths

    Ensures:
        - only records whose file is tracked are used when tracked is given
        - no planted id is ever drawn
        - the attribution list holds 30 ts and 20 py ids, and the yield list 50 ts and 50 py ids
        - the two lists share no id
        - each stage holds its ids by language and one interleaved order
        - the record names the seed, the source commit, the pool reader and the pool sizes, and carries its own sha

    Raises:
        - NeedsetError QUOTA_UNFILLABLE when a language runs short in a stage
    """
    usable   = [ r for r in kept if tracked is None or r[ "file" ] in tracked ]
    by_lang  = { lang: [ r[ "id" ] for r in usable if r[ "lang" ] == lang and r[ "id" ] not in planted ] for lang in LANGS }
    record   = { "format": FORMAT, "seed": seed, "source_commit": source_commit, "reader": pool.READER,
                 "pool": { "kept": len( kept ), "tracked": len( usable ), "excluded_planted": sum( 1 for r in usable if r[ "id" ] in planted ), **{ f"{lang}_available": len( by_lang[ lang ] ) for lang in LANGS } } }
    taken    = set()
    for name, quota in ( ( stages.ATTRIBUTION, ATTRIBUTION_QUOTA ), ( stages.YIELD, YIELD_QUOTA ) ):
        chosen = { lang: sample_lang( [ i for i in by_lang[ lang ] if i not in taken ], seed, name, lang, quota[ lang ] ) for lang in LANGS }
        taken |= { i for ids in chosen.values() for i in ids }
        record[ name ] = { "ts": chosen[ "ts" ], "py": chosen[ "py" ], "order": interleave( chosen ) }
    record[ "sha" ] = lists_sha( record )
    return record


def write_lists( run_dir, record ):
    """
    Write the seed lists to the run folder once.

    Requires:
        - run_dir exists; record comes from draw_lists

    Ensures:
        - a first call writes the file and returns its path
        - a second call with the same record changes nothing

    Raises:
        - NeedsetError PLAN_ALREADY_WRITTEN when a different list is already there
    """
    path = pathlib.Path( run_dir ) / LISTS_FILE
    text = json.dumps( record, sort_keys=True, indent=4 ) + "\n"
    if path.exists():
        if json.loads( path.read_text( encoding="utf-8" ) ) != record: raise er.NeedsetError( er.PLAN_ALREADY_WRITTEN, f"{path} holds different seed lists" )
        return path
    path.write_text( text, encoding="utf-8" )
    return path


def load_lists( path ):
    """
    Read the seed lists back and check them.

    Ensures:
        - returns the record when its format is right and its sha matches its content

    Raises:
        - NeedsetError MANIFEST_MISMATCH when the file is missing, is not this format or its sha does not match
    """
    try:
        record = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ) as error:
        raise er.NeedsetError( er.MANIFEST_MISMATCH, f"{path}: seed lists unreadable ({error.__class__.__name__})" ) from error
    if record.get( "format" ) != FORMAT or record.get( "sha" ) != lists_sha( record ): raise er.NeedsetError( er.MANIFEST_MISMATCH, f"{path}: not the seed lists, or changed since they were written" )
    return record


def attribution_stage( lists_path, make_need, trace_fn ):
    """
    Return the attribution stage function: seeds end to end through the trace.

    Requires:
        - make_need is an async function taking a seed id and returning a matched final need, or None for a seed with no partner
        - trace_fn is an async function taking the list of needs and returning the trace records, as loss_trace.trace_all does
        - any model call they make is counted by the cap the runner has installed

    Ensures:
        - the seeds come from the written file, which load_lists has checked, in the file's interleaved order
        - the returned function takes no argument and returns attribution_report's dict plus seeds, needs and skipped
        - when no seed gives a need the report says so and stops the run, and the trace is not called
    """
    async def stage():
        """Ensures: returns the attribution report."""
        lists            = load_lists( lists_path )
        needs, skipped   = [], []
        for seed_id in lists[ stages.ATTRIBUTION ][ "order" ]:
            need = await make_need( seed_id )
            if need is None: skipped.append( seed_id )
            else: needs.append( need )
        head = { "seeds": len( lists[ stages.ATTRIBUTION ][ "order" ] ), "needs": len( needs ), "skipped": skipped, "lists_sha": lists[ "sha" ] }
        if not needs: return { **head, "stop": True, "reason": "no seed gave a need" }
        return { **head, **stages.attribution_report( await trace_fn( needs ) ) }
    return stage


def yield_stage( lists_path, prepare_fn, index ):
    """
    Return the yield stage function: the natural yield per language.

    Requires:
        - prepare_fn is run_yield's: an async function taking a seed id and returning a row or None
        - index is a hardness index

    Ensures:
        - the seeds come from the written file, checked by load_lists, in the file's interleaved order
        - the returned function takes no argument and returns run_yield's dict plus the list sha and the per-language seed counts drawn
    """
    async def stage():
        """Ensures: returns the yield report."""
        lists = load_lists( lists_path )
        out   = await stages.run_yield( lists[ stages.YIELD ][ "order" ], prepare_fn, index )
        return { **out, "lists_sha": lists[ "sha" ], "drawn": { lang: len( lists[ stages.YIELD ][ lang ] ) for lang in LANGS } }
    return stage
