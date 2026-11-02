"""
The judge's reading of each control entry, kept in the run folder.

A run used to keep only whether a plant was accepted. The rating itself, the p_overlap the judge gave, lived only in the Jev cache.
This module records each reading as the checker takes it, as judged or not judged with the reason, and writes them beside the stage report.
It records what the sweeper returns and changes nothing the checker sees.
"""
import json
import pathlib

from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

JUDGED              = "judged"
NOT_JUDGED          = "not_judged"
NOT_RETRIEVED       = "not_retrieved"
RETRIEVED_NOT_SENT  = "retrieved_not_sent"
FAILED              = "failed"
NOT_REACHED         = "not_reached"
NO_ANSWER           = "no_answer"
MALFORMED_ANSWER    = "malformed_answer"
READINGS_FILE       = "judge-readings.json"
FORMAT              = 1


def rating_of( probabilities, policy=vd.POLICY ):
    """
    Read one answer's probabilities as the judge's rating.

    Requires:
        - probabilities is the answer mapping of one candidate, or anything at all

    Ensures:
        - returns { p_overlap, confidence, choice } for a valid answer, p_overlap being reuse plus extend rounded to 6 places
        - returns None for a malformed answer
    """
    if vd.malformed_reason( probabilities, policy ) is not None: return None
    p, confidence, choice = vd.call_facts( probabilities )
    return { "p_overlap": round( p, 6 ), "confidence": round( confidence, 6 ), "choice": choice }


def entry_key( need, rec, template, model, shape ):
    """
    Name the cache entry the judge reads for one candidate.

    Requires:
        - rec is the record the judge is shown; shape is the packed request shape, or None for the one-request path

    Ensures:
        - returns reuse_pack.candidate_key for a packed shape, else the request hash of the one-request body
    """
    text = rt.entry_text( rec )
    if shape is None: return rt.request_hash( rt.build_request( need, text, template, model ) )
    return rp.candidate_key( need, text, template, model, shape )


class SweepTap:
    """
    A sweeper that passes every sweep to the real one and writes down what came back.

    Requires:
        - ctx is the reuse context whose sweeper is wrapped; the wrapper goes on a copy, so ctx keeps its own

    Ensures:
        - calling it returns exactly what the wrapped sweeper returns
        - sweeps holds, per sweep, keys ( entry id to cache key ), answers ( entry id to its probabilities ), failed and not_reached
        - the wrapped sweeper is read from ctx when a sweep is asked for, so a context that has none is not touched before then
    """

    def __init__( self, ctx ):
        """Hold the context whose sweeper is wrapped; nothing has been swept."""
        self.ctx    = ctx
        self.sweeps = []

    def __call__( self, ctx, need, entries, frozen=False, template=None, model=None, gaps=None ):
        """Ensures: runs the wrapped sweep, records it and returns its result unchanged."""
        packed = self.ctx.sweeper is not None
        out    = rt._sweeper( self.ctx )( ctx, need, entries, frozen=frozen, template=template, model=model, gaps=gaps )
        tmpl, mdl = template or ctx.template, model or ctx.model
        self.sweeps.append( { "keys": { e[ "id" ]: entry_key( need, e, tmpl, mdl, ctx.request_shape if packed else None ) for e in entries },
                              "answers": { a[ "id" ]: a[ "probabilities" ] for a in out[ "answers" ] }, "failed": list( out[ "failed" ] ), "not_reached": list( out[ "not_reached" ] ) } )
        return out


def judge_reading( ident, sweeps, retrieved ):
    """
    Say what the judge did with one entry in one check.

    Requires:
        - sweeps are a SweepTap's sweeps for the check; retrieved says the candidate stage sent the entry to the judge

    Ensures:
        - returns { status, key, ... } with status judged ( plus p_overlap, confidence, choice ) or not_judged ( plus reason )
        - an entry the judge answered is judged, whichever sweep answered it; a malformed answer is not_judged with malformed_answer
        - an entry a sweep asked about and did not answer is not_judged with failed, not_reached or no_answer
        - an entry no sweep asked about is not_judged: not_retrieved when the stage did not send it, retrieved_not_sent when it did and no sweep asked, with no key
    """
    seen = []
    for sw in sweeps:
        if ident not in sw[ "keys" ]: continue
        key = sw[ "keys" ][ ident ]
        if ident in sw[ "answers" ]:
            rating = rating_of( sw[ "answers" ][ ident ] )
            return { "status": JUDGED, "key": key, **rating } if rating is not None else { "status": NOT_JUDGED, "reason": MALFORMED_ANSWER, "key": key }
        seen.append( { "status": NOT_JUDGED, "reason": FAILED if ident in sw[ "failed" ] else NOT_REACHED if ident in sw[ "not_reached" ] else NO_ANSWER, "key": key } )
    if seen: return seen[ 0 ]
    return { "status": NOT_JUDGED, "reason": RETRIEVED_NOT_SENT if retrieved else NOT_RETRIEVED, "key": None }


def readings_of( report ):
    """
    Pull every pair's two judge readings out of a stage report.

    Requires:
        - report is a stage report, or any dict

    Ensures:
        - returns { format, passes: [ { pass, rows } ] } where a row is { rewrite, same_job, plant, original } and each side is { id, retrieved, ranks, fusion, judge }
        - a report with no control stage, or a control row without readings, gives no row for it
    """
    control = report[ "stages" ][ "control" ][ "report" ] if "stages" in report and "control" in report[ "stages" ] and "report" in report[ "stages" ][ "control" ] else None
    if not isinstance( control, dict ): return { "format": FORMAT, "passes": [] }
    passes = control[ "passes" ] if "passes" in control and control[ "passes" ] else [ control ]
    side   = lambda s: { k: s[ k ] for k in ( "id", "retrieved", "ranks", "fusion", "judge" ) }
    out    = []
    for n, one in enumerate( passes, start=1 ):
        rows = [ { "rewrite": r[ "rewrite" ], "same_job": r[ "same_job" ], "plant": side( r[ "plant" ] ), "original": side( r[ "original" ] ) }
                 for r in ( one[ "rows" ] if "rows" in one else [] ) if "judge" in r[ "plant" ] ]
        out.append( { "pass": n, "rows": rows } )
    return { "format": FORMAT, "passes": out }


def write_readings( run_dir, report ):
    """
    Write the readings beside stage-reports.json.

    Ensures:
        - writes judge-readings.json in run_dir, derived from the report's rows so the two cannot disagree
        - returns the path
    """
    path = pathlib.Path( run_dir ) / READINGS_FILE
    path.write_text( json.dumps( readings_of( report ), sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return path
