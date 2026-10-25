"""
Loss tracing: where, in the search pipeline, does a need's key get lost.

Each need goes through four stages in order: retrieved, rated relevant, read and ruled the same job.
The first stage that fails names the loss. A finished trace is kept in a ledger, so a stopped run repeats no call.
"""
import asyncio
import collections
import copy
import inspect
import json

from cosa.repo.doc_lint import harness_report, harness_runner, model_transport
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import agent_probe, finalize
from lupin_mcp.reuse_needset import errors as er

NOT_RETRIEVED      = "NOT_RETRIEVED"
NOT_RATED_RELEVANT = "NOT_RATED_RELEVANT"
NOT_READ           = "NOT_READ"
NOT_RULED_SAME_JOB = "NOT_RULED_SAME_JOB"
FOUND              = "FOUND"
ALT_MATCH          = "ALT_MATCH"
CORRECT_NO_MATCH   = "CORRECT_NO_MATCH"
FALSE_MATCH        = "FALSE_MATCH"
ASKED_VERDICTS     = ( "REUSE", "EXTEND" )
TRACE_STAGE        = "trace"
CHECK_TOOL         = "check_exists"
REVIEWER_KEY       = "reviewer_confirmed"


def asked_ids( receipt ):
    """
    List the entries the checker sent to the judge.

    Requires:
        - receipt is a checker receipt of the candidate route, built and stored or not

    Ensures:
        - returns the candidate stage's ids followed by its widened ids, sorted
        - this is the field on the packed and the unpacked path alike
        - it is not the request rows, which leave out an entry whose answer came from the cache

    Raises:
        - NeedsetError RECEIPT_FIELD_ABSENT when the receipt has no candidate stage or the stage failed, so a missing field is never read as nothing retrieved
    """
    stage = receipt[ "candidate_stage" ] if "candidate_stage" in receipt else None
    if stage is None or "error" in stage: raise er.NeedsetError( er.RECEIPT_FIELD_ABSENT, f"receipt {receipt[ 'id' ]} holds no candidate stage ids" )
    return sorted( set( stage[ "ids" ] ) | set( stage[ "widened_ids" ] ) )


def check_need( need, ctx ):
    """
    Ask the checker about one need and return its receipt, stored nowhere.

    Requires:
        - need is a final need; ctx is a reuse context with the candidate stage on

    Ensures:
        - runs the candidate route with the need's seed left out, so a need is not found by its own source
        - the language is the need's write language, and all for a cross-language need
        - a nothing need has no seed to leave out

    Raises:
        - ReuseError from the question
    """
    language = "all" if need[ "kind" ] == "cross_language" else need[ "write_lang" ]
    text     = need[ "need" ].strip()
    return rt.run_question( ctx, CHECK_TOOL, text, text, exclude_id=need[ "seed" ], prepared=rt.prepare( ctx ), sweep_only=False, write=False, language=language )


def index_locator( ctx ):
    """
    Build the function that finds a symbol's file and line range in the index.

    Ensures:
        - returns where( symbol id ) giving { file, line, end_line }
        - the symbols are the searchable ones (public and private), the same set a search ranks, so a shortlisted id is always found
        - where raises NeedsetError RECEIPT_FIELD_ABSENT for a symbol the index lacks or one with no end_line
    """
    by_id = { r[ "id" ]: r for r in rt.sx_build.read_searchable( rt.prepare( ctx )[ 3 ] ) }

    def where( symbol_id ):
        """Ensures: returns the symbol's location from the index."""
        r = by_id.get( symbol_id )
        if r is None or "end_line" not in r: raise er.NeedsetError( er.RECEIPT_FIELD_ABSENT, f"{symbol_id}: no file and end_line in the index" )
        return { "file": r[ "file" ], "line": r[ "line" ], "end_line": r[ "end_line" ] }

    return where


def classify( kind, key, evidence ):
    """
    Name where a need's key was lost.

    Requires:
        - key is the list of key symbol ids; evidence holds verdict, asked, shortlist, read and rulings
        - rulings is a dict when the probe ran and None when it did not

    Ensures:
        - a matched need returns { lost_at, alt } with lost_at the first stage whose set of key symbols is empty, narrowing the set stage by stage
        - a found need has a key symbol that was retrieved, rated relevant, read and ruled the same job
        - ALT_MATCH replaces NOT_RULED_SAME_JOB when a shortlisted symbol outside the key was ruled the same job, and alt lists those symbols
        - a nothing need returns FALSE_MATCH when the checker ended with reuse or extend, or the probe ruled a shortlisted symbol the same job, else CORRECT_NO_MATCH
    """
    ruled = evidence[ "rulings" ] or {}
    same  = sorted( i for i in evidence[ "shortlist" ] if ruled.get( i ) in agent_probe.SAME_JOB )
    if kind == "nothing":
        return { "lost_at": FALSE_MATCH if evidence[ "verdict" ] in ASKED_VERDICTS or same else CORRECT_NO_MATCH, "alt": same }
    asked   = set( key ) & set( evidence[ "asked" ] )
    listed  = asked & set( evidence[ "shortlist" ] )
    read    = listed & set( evidence[ "read" ] )
    judged  = { i for i in read if ruled.get( i ) in agent_probe.SAME_JOB }
    lost_at = NOT_RETRIEVED if not asked else NOT_RATED_RELEVANT if not listed else NOT_READ if not read else FOUND if judged else NOT_RULED_SAME_JOB
    alt     = [ i for i in same if i not in key ] if lost_at == NOT_RULED_SAME_JOB else []
    return { "lost_at": ALT_MATCH if alt else lost_at, "alt": alt }


def _evidence( receipt, probe_out, root, where ):
    """
    Gather the facts classify reads.

    Ensures:
        - read lists the shortlisted symbols whose whole definition one Read call showed; it is empty when the probe did not run
    """
    shortlist = [ row[ "id" ] for row in receipt[ "shortlist" ] ]
    reads     = probe_out[ "reads" ] if probe_out is not None else []
    seen      = []
    for i in shortlist:
        loc = where( i ) if reads else None
        if loc is not None and any( agent_probe.covers( r, root, loc[ "file" ], loc[ "line" ], loc[ "end_line" ] ) for r in reads ): seen.append( i )
    return { "verdict": receipt[ "verdict" ], "receipt_id": receipt[ "id" ], "index_sha": receipt[ "index_sha" ], "asked": asked_ids( receipt ), "shortlist": shortlist,
             "read": seen, "rulings": probe_out[ "rulings" ] if probe_out is not None else None }


async def trace_need( need, ctx, probe, root, model, ask=check_need, where=None ):
    """
    Trace one need and return its record.

    Requires:
        - need is a final need; probe( sentence, receipt, root, model ) is an async function returning { rulings, reads, transcript }
        - where( symbol id ) gives { file, line, end_line }

    Ensures:
        - the probe runs only when its rulings can change the answer: for a matched need when a key symbol reached the shortlist, for a nothing need when the checker did not already end in reuse or extend and the shortlist is not empty
        - returns { id, kind, write_lang, selection_route, key, lost_at, alt, evidence, transcript }
    """
    receipt = ask( need, ctx )
    key     = need[ "key" ][ "symbols" ]
    listed  = bool( set( key ) & set( asked_ids( receipt ) ) & { row[ "id" ] for row in receipt[ "shortlist" ] } )
    nothing = need[ "kind" ] == "nothing"
    wanted  = ( receipt[ "verdict" ] not in ASKED_VERDICTS and bool( receipt[ "shortlist" ] ) ) if nothing else listed
    out     = await probe( need[ "need" ], receipt, root, model ) if wanted else None
    ev      = _evidence( receipt, out, root, where )
    return { "id": need[ "id" ], "kind": need[ "kind" ], "write_lang": need[ "write_lang" ], "selection_route": need[ "selection_route" ], "key": list( key ),
             **classify( need[ "kind" ], key, ev ), "evidence": ev, "transcript": out[ "transcript" ] if out is not None else None }


def trace_version():
    """
    Name the trace, so a changed checker call, classifier or probe prompt is a ledger miss.

    Ensures:
        - returns model_transport.prompt_version over the sources of check_need and classify and the probe's own version
    """
    return model_transport.prompt_version( "needset-trace", inspect.getsource( check_need ), inspect.getsource( classify ), agent_probe.prompt_version() )


async def trace_all( needs, ctx, ledger, root, model, checker_commit, index_sha=None, probe=agent_probe.run_probe, ask=check_need, where=None, parallel=3 ):
    """
    Trace every need, skipping the ones the ledger holds.

    Requires:
        - needs are final needs and at least one is matched
        - ledger is a harness_runner.Ledger; root is a read-only tree of the source commit
        - checker_commit is the sha of the code tree whose retrieval is measured
        - index_sha is the sha of the index the checker reads; None reads it from ctx

    Ensures:
        - returns the records in the order of needs
        - a need the ledger holds is returned as stored, with no check and no probe call
        - the key of a ledger row holds the need id, the source commit, the index sha, the checker commit, the probe model and the trace version
        - so a retrieval fix, a rebuilt index or another source commit is a ledger miss
        - the probes run through run_parallel, so a failure stops the pending ones and the finished records stay in the ledger

    Raises:
        - NeedsetError BAD_NEED for a smoke need, a need that is not final, a set with no matched need, or an empty source commit, index sha or checker commit, or an index sha of none, before any call
    """
    for n in needs:
        if "smoke" in n or n[ "status" ] != "final": raise er.NeedsetError( er.BAD_NEED, f"{n[ 'id' ]}: only a final, non-smoke need is traced" )
    if not any( n[ "kind" ] != "nothing" for n in needs ): raise er.NeedsetError( er.BAD_NEED, "a trace needs at least one matched need" )
    index_sha = rt.prepare( ctx )[ 2 ] if index_sha is None else index_sha
    for name, value in ( ( "checker_commit", checker_commit ), ( "index_sha", index_sha ) ) + tuple( ( f"{n[ 'id' ]} source_commit", n[ "source_commit" ] ) for n in needs ):
        if not isinstance( value, str ) or not value.strip(): raise er.NeedsetError( er.BAD_NEED, f"{name} must be a non-empty string" )
    if index_sha.strip().lower() == "none": raise er.NeedsetError( er.BAD_NEED, "index_sha must name a built index, not the placeholder none" )
    version = trace_version()
    where   = index_locator( ctx ) if where is None else where

    async def one( need ):
        """Ensures: returns the stored record, or traces the need and stores the result first."""
        key    = harness_runner.ledger_key( TRACE_STAGE, { "old": need[ "id" ], "new": "\0".join( ( need[ "source_commit" ], index_sha, checker_commit ) ) }, version, model, 0 )
        stored = ledger.get( key )
        if stored is not None: return stored
        record = await trace_need( need, ctx, probe, root, model, ask, where )
        ledger.put( key, record )
        return record

    return await harness_runner.run_parallel( needs, one, parallel, lambda n: n[ "id" ] )


def extend_key( need, symbols ):
    """
    Add confirmed alternatives to a need's key.

    Requires:
        - symbols are ids the reviewers confirmed as doing the need's job

    Ensures:
        - returns a copy whose key holds the old and the new symbols sorted, version raised by one and provenance reviewer_confirmed
        - the need itself is not changed, and its id stays the same
    """
    out = copy.deepcopy( need )
    out[ "key" ] = dict( out[ "key" ], symbols=sorted( set( out[ "key" ][ "symbols" ] ) | set( symbols ) ), version=out[ "key" ][ "version" ] + 1, provenance=REVIEWER_KEY )
    return out


def retrace( record, need ):
    """
    Classify a stored record again against the need's key as it stands now.

    Requires:
        - need is the need the record traced, possibly with an extended key

    Ensures:
        - returns a copy of the record with key, lost_at and alt recomputed from the stored evidence, so no call is made
    """
    key = need[ "key" ][ "symbols" ]
    return { **copy.deepcopy( record ), "key": list( key ), **classify( record[ "kind" ], key, record[ "evidence" ] ) }


def confirmation_items( records, needs, source_of ):
    """
    Build the items the reviewers confirm after a trace.

    Requires:
        - source_of( symbol id ) returns the symbol's source text

    Ensures:
        - returns one need_key item for every record that is an ALT_MATCH or a FALSE_MATCH, in record order
        - an ALT_MATCH item shows the proposed alternatives' source as the key sources
        - a FALSE_MATCH item on a nothing need shows the ruled symbols' source as its hits; with none ruled it shows the shortlist's
    """
    by_id, out = { n[ "id" ]: n for n in needs }, []
    for r in records:
        if r[ "lost_at" ] not in ( ALT_MATCH, FALSE_MATCH ): continue
        shown = r[ "alt" ] or r[ "evidence" ][ "shortlist" ]
        texts = [ source_of( i ) for i in shown ]
        out.append( finalize.need_item( by_id[ r[ "id" ] ], hits=texts ) if r[ "kind" ] == "nothing" else finalize.need_item( by_id[ r[ "id" ] ], key_texts=texts ) )
    return out


def _count( rows, field ):
    """Ensures: returns { value: how many rows hold it }, sorted by value."""
    return dict( sorted( collections.Counter( r[ field ] for r in rows ).items() ) )


def summarize( records ):
    """
    Count the outcomes of a trace.

    Ensures:
        - returns the counts of matched needs by lost_at, by kind and by language
        - not_retrieved_by_route holds, per selection route, how many routed needs there were and how many were not retrieved
        - nothing counts the nothing needs by outcome
        - misses counts the matched needs that are not found, and upper_bound is the 95 percent bound on their rate

    Raises:
        - NeedsetError BAD_NEED when no record is of a matched need
    """
    matched = [ r for r in records if r[ "kind" ] != "nothing" ]
    if not matched: raise er.NeedsetError( er.BAD_NEED, "a summary needs at least one matched need" )
    routed  = [ r for r in matched if r[ "selection_route" ] is not None ]
    misses  = sum( 1 for r in matched if r[ "lost_at" ] != FOUND )
    return { "matched": len( matched ), "by_lost_at": _count( matched, "lost_at" ),
             "by_kind": { k: _count( [ r for r in matched if r[ "kind" ] == k ], "lost_at" ) for k in sorted( { r[ "kind" ] for r in matched } ) },
             "by_lang": { k: _count( [ r for r in matched if r[ "write_lang" ] == k ], "lost_at" ) for k in sorted( { r[ "write_lang" ] for r in matched } ) },
             "not_retrieved_by_route": { k: { "needs": sum( 1 for r in routed if r[ "selection_route" ] == k ),
                                              "not_retrieved": sum( 1 for r in routed if r[ "selection_route" ] == k and r[ "lost_at" ] == NOT_RETRIEVED ) }
                                         for k in sorted( { r[ "selection_route" ] for r in routed } ) },
             "nothing": _count( [ r for r in records if r[ "kind" ] == "nothing" ], "lost_at" ),
             "misses": misses, "miss_rate": misses / len( matched ), "upper_bound": harness_report.upper_bound( misses, len( matched ) ) }


def write_report( out_dir, before, after, records, meta ):
    """
    Write loss-report.json and loss-report.md.

    Requires:
        - before and after are summaries of the trace before and after the confirmations
        - meta holds the checker commit, the index sha, the probe model and the date

    Ensures:
        - the json holds meta, both summaries and one row per need without its transcript
        - the markdown prints the figures before and after the confirmations side by side
    """
    rows = [ { k: v for k, v in r.items() if k != "transcript" } for r in records ]
    ( out_dir / "loss-report.json" ).write_text( json.dumps( { "meta": meta, "before": before, "after": after, "rows": rows }, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    lines = [ "# Loss report", "", *[ f"- {k}: {v}" for k, v in sorted( meta.items() ) ], "", "| outcome | before | after |", "|---|---|---|" ]
    for k in sorted( set( before[ "by_lost_at" ] ) | set( after[ "by_lost_at" ] ) ):
        lines.append( f"| {k} | {before[ 'by_lost_at' ].get( k, 0 )} | {after[ 'by_lost_at' ].get( k, 0 )} |" )
    lines += [ f"| miss rate | {before[ 'miss_rate' ]:.4f} | {after[ 'miss_rate' ]:.4f} |", f"| upper bound | {before[ 'upper_bound' ]:.4f} | {after[ 'upper_bound' ]:.4f} |", "",
               "Not retrieved, by selection route:", "", "| route | needs | not retrieved |", "|---|---|---|" ]
    lines += [ f"| {k} | {v[ 'needs' ]} | {v[ 'not_retrieved' ]} |" for k, v in after[ "not_retrieved_by_route" ].items() ]
    ( out_dir / "loss-report.md" ).write_text( "\n".join( lines ) + "\n", encoding="utf-8" )
