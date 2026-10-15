"""
The real-stage check: where does the candidate stage rank a known target?

It runs on the real index and the live vector set.

Each seeded need names one symbol that answers it. The check asks the real stage for the need's shortlist and reports the
target's rank in it, or `absent`. One negative control removes its target from the entries the stage is given, so the
check is shown able to fail. The Jev sweep is not run: this measures the stage, not the verdict.

What this check does not prove:
    The needs are written by hand from the targets' docstrings, so they are easier than a seat's own wording.
    The stage sees the index of the tree it is run from, which can hold symbols newer than the vector set.
    A rank inside the shortlist says nothing about whether Jev would then choose the target.

Exit 0 means every seeded target was in the shortlist and the control was absent.
Exit 1 means a target was absent or the control was found.
Exit 2 means the run was refused before anything was asked.
"""
import argparse
import json
import pathlib
import sys

from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_tools as rt

ABSENT = "absent"

SEEDS = ( ( "decide whether the test server is idle from a set of observed counters",           "cosa.rest.venue_idle.decide" ),
          ( "ask the server how busy it is without logging in",                                 "cosa.rest.venue_idle.read_signals" ),
          ( "work out which cache file name belongs to a search sentence",                      "cosa.repo.symindex.candidates.vector_store.query_key" ),
          ( "check that an environment variable holds something before calling the model",      "cosa.repo.doc_lint.jev_transport.has_key" ),
          ( "sort wiki pages by how well they match a need and give back the entry ids they pin", "cosa.repo.symindex.candidates.wiki_list.wiki_ranked_ids" ) )
CONTROL_NEED   = SEEDS[ 0 ][ 0 ]
CONTROL_TARGET = SEEDS[ 0 ][ 1 ]


class RunRefused( RuntimeError ):
    """The check cannot start; nothing was asked."""


def rank_of( target, ranking ):
    """
    Find a target's place in a ranking.

    Ensures:
        - returns the 1-based position of target in ranking, or None when it is not there
    """
    return ranking.index( target ) + 1 if target in ranking else None


def check_need( stage, need, target, entries, index_sha, pages ):
    """
    Ask the stage for one need's shortlist and describe it.

    Requires:
        - entries are the sendable index entries the stage is given; index_sha identifies them

    Ensures:
        - returns { need, target, rank, found, asked, total, not_asked, manifest_hash, K, ids_in_entries, ids_unique }
        - rank is the target's 1-based place in the fused ranking, or None
        - asked is the shortlist size, total the entries given, and not_asked their difference
        - ids_in_entries is True only when every shortlisted id is an entry given, and ids_unique when none repeats
    """
    got      = stage.shortlist( need, entries, index_sha, pages )
    held     = { e[ "id" ] for e in entries }
    ranking  = got[ "ranking" ]
    rank     = rank_of( target, ranking )
    return { "need": need, "target": target, "rank": rank, "found": rank is not None, "asked": len( got[ "ids" ] ), "total": len( entries ),
             "not_asked": len( entries ) - len( got[ "ids" ] ), "manifest_hash": got[ "manifest_hash" ], "K": got[ "K" ],
             "ids_in_entries": all( i in held for i in got[ "ids" ] ), "ids_unique": len( set( got[ "ids" ] ) ) == len( got[ "ids" ] ) }


def run_check( stage, entries, index_sha, pages, seeds=SEEDS, control=( CONTROL_NEED, CONTROL_TARGET ) ):
    """
    Run every seeded need and the negative control.

    Requires:
        - seeds is a non-empty sequence of ( need, target id ) with at least five members
        - every seeded target and the control's target is an id in entries

    Ensures:
        - returns the report: { manifest_hash, K, entries, seeds, control, ok }
        - the control is asked on a copy of the entries without its target
        - ok is True only when every seed was found, the control was absent, and every row's counts hold

    Raises:
        - RunRefused for fewer than five seeds or a target that is not in the entries
    """
    if len( seeds ) < 5: raise RunRefused( f"at least five seeded needs are required, got {len( seeds )}" )
    ids = { e[ "id" ] for e in entries }
    for _need, target in list( seeds ) + [ control ]:
        if target not in ids: raise RunRefused( f"target {target} is not in the entries, so the check could not find it even on a good stage" )
    rows    = [ check_need( stage, need, target, entries, index_sha, pages ) for need, target in seeds ]
    without = [ e for e in entries if e[ "id" ] != control[ 1 ] ]
    neg     = check_need( stage, control[ 0 ], control[ 1 ], without, index_sha + "-without-control", pages )
    counts  = all( r[ "ids_in_entries" ] and r[ "ids_unique" ] and r[ "asked" ] + r[ "not_asked" ] == r[ "total" ] for r in rows + [ neg ] )
    manifest = stage.manifest()[ "manifest_hash" ]
    hashes   = all( r[ "manifest_hash" ] == manifest for r in rows + [ neg ] )
    return { "manifest_hash": manifest, "K": stage.K, "entries": len( entries ), "seeds": rows, "control": neg,
             "ok": bool( all( r[ "found" ] for r in rows ) and not neg[ "found" ] and counts and hashes ) }


def summary_lines( report ):
    """Ensures: returns a table of ranks, one line per need, then the control and the verdict."""
    lines = [ f"manifest {report[ 'manifest_hash' ][ :12 ]}  K {report[ 'K' ]}  entries {report[ 'entries' ]}" ]
    for r in report[ "seeds" ]:
        lines.append( f"rank {r[ 'rank' ] if r[ 'found' ] else ABSENT:>6}  asked {r[ 'asked' ]}  {r[ 'target' ]}" )
    c = report[ "control" ]
    lines.append( f"control {'FOUND (check cannot fail)' if c[ 'found' ] else ABSENT}  {c[ 'target' ]}" )
    lines.append( f"overall {'PASS' if report[ 'ok' ] else 'FAIL'}" )
    return lines


def main( argv=None, out=None, err=None, stage=None, top=None ):
    """
    Run the command line.

    Ensures:
        - returns 0, 1 or 2 as the module docstring says, and writes the report to --report when given
        - a stage and a top may be passed in; otherwise the production stage is built for the tree the command runs in
    """
    out, err = sys.stdout if out is None else out, sys.stderr if err is None else err
    parser   = argparse.ArgumentParser( prog="python -m lupin_mcp.reuse_real_stage_check", description=__doc__.split( "\n\n" )[ 0 ] )
    parser.add_argument( "--report", help="a file to write the JSON report to" )
    args = parser.parse_args( argv )
    try:
        top = pathlib.Path.cwd() if top is None else pathlib.Path( top )
        if stage is None: stage = rt._candidate_stage( top )
        ctx = rt.ReuseContext( top, rt.data_dir( top ), candidate_stage=stage )
        flags, entries, sha_, _gen = rt.prepare( ctx )
        if flags: raise RunRefused( f"the index is not usable: {sorted( flags )}" )
        report = run_check( stage, entries, sha_, ctx.pages )
    except ( RunRefused, CandidateError, rt.ReuseError ) as error:
        print( f"reuse-real-stage-check: {error}", file=err )
        return 2
    print( "\n".join( summary_lines( report ) ), file=out )
    if args.report: pathlib.Path( args.report ).write_text( json.dumps( report, sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
    return 0 if report[ "ok" ] else 1


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
