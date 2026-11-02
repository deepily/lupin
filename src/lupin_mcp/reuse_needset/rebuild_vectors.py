r"""
Rebuild a run's vector set for a new index and refuse any change nobody expected.

It replaces the hand-run rebuild script, whose first run read the wrong purpose store.
Nothing compared its matrices with the last good set.
This one needs the prior generation's folder and checks the purpose store is the live one.
It exits nonzero when the matrices differ from the prior generation by anything it was not told to expect.

    python -m lupin_mcp.reuse_needset.rebuild_vectors --root <main tree> --index <gen>/symbols.jsonl --out-dir <run folder>
        --prior-gen <prior generation folder> [--expect code.f32,prose.f32]

The out dir holds purpose-lines/purpose.jsonl (a copy of the live store), vectors/ and query-cache/ (copied from the last good set).
The embeddings endpoint on :7999 must be up. Only changed rows are embedded.
"""
import argparse
import hashlib
import json
import pathlib
import sys

from lupin_mcp.reuse_needset import errors as er

MATRICES     = ( "code.f32", "concat.f32", "prose.f32", "ids.txt" )
PURPOSE_FILE = "purpose.jsonl"
VECTORS_DIR  = "vectors"
PURPOSE_DIR  = "purpose-lines"
EXIT_REFUSED = 2
REFUSALS     = ( er.PRIOR_GEN_MISSING, er.PURPOSE_STORE_NOT_LIVE, er.MATRICES_CHANGED )


def _sha( path ):
    """Ensures: returns the sha256 of the file's bytes, or None when it is not a file."""
    path = pathlib.Path( path )
    return hashlib.sha256( path.read_bytes() ).hexdigest() if path.is_file() else None


def live_purpose_store( root ):
    """
    Locate the live purpose store of a repository.

    Requires:
        - root is a lupin repository root

    Ensures:
        - returns <reuse-review data dir>/purpose-lines/purpose.jsonl, the path the production lookup reads
    """
    from cosa.repo.symindex import paths
    from cosa.repo.symindex.candidates import storage_paths as sp
    return sp.candidate_dir( "purpose", paths.data_dir( root ) ) / PURPOSE_FILE


def check_prior( prior_gen ):
    """
    Require the prior generation's vector set.

    Requires:
        - prior_gen is the folder of the prior generation, holding vectors/

    Ensures:
        - returns the prior vectors folder when it holds build-info.json and every matrix
    Raises:
        - NeedsetError PRIOR_GEN_MISSING when the folder, its build info or a matrix is absent
    """
    vectors = pathlib.Path( prior_gen ) / VECTORS_DIR
    absent  = [ n for n in ( "build-info.json", *MATRICES ) if not ( vectors / n ).is_file() ]
    if absent: raise er.NeedsetError( er.PRIOR_GEN_MISSING, f"{vectors} lacks {', '.join( absent )}" )
    return vectors


def check_purpose_store( out_dir, live_store ):
    """
    Require that the purpose store the rebuild reads is the live one.

    Requires:
        - out_dir is the run's data folder; live_store is the path the production lookup reads

    Ensures:
        - returns None when <out_dir>/purpose-lines/purpose.jsonl has the same bytes as the live store
    Raises:
        - NeedsetError PURPOSE_STORE_NOT_LIVE when the live store is unreadable, the copy is absent, or the bytes differ
    """
    live, copy = _sha( live_store ), _sha( pathlib.Path( out_dir ) / PURPOSE_DIR / PURPOSE_FILE )
    if live is None: raise er.NeedsetError( er.PURPOSE_STORE_NOT_LIVE, f"the live store {live_store} cannot be read" )
    if copy is None: raise er.NeedsetError( er.PURPOSE_STORE_NOT_LIVE, f"{out_dir}/{PURPOSE_DIR}/{PURPOSE_FILE} is absent" )
    if copy != live: raise er.NeedsetError( er.PURPOSE_STORE_NOT_LIVE, f"{out_dir}/{PURPOSE_DIR}/{PURPOSE_FILE} is not a copy of the live store {live_store}" )


def matrix_changes( prior_vectors, new_vectors ):
    """Ensures: returns the sorted matrix names whose bytes differ; a missing file differs."""
    return sorted( n for n in MATRICES if _sha( pathlib.Path( prior_vectors ) / n ) != _sha( pathlib.Path( new_vectors ) / n ) )


def _live_build( root, index, out_dir ):  # pragma: no cover -- embeds through the live endpoint on :7999; main's test replaces it
    """Ensures: returns the build report, with the vectors rewritten under out_dir."""
    from cosa.repo.symindex import candidate_build as cb
    from cosa.repo.symindex.candidates import vector_build as vb
    return cb.run( root, None, vb.EndpointClient(), index=index, out_dir=out_dir, purposes="skip" )


def rebuild( root, index, out_dir, prior_gen, expect=(), live_store=None, build=_live_build ):
    """
    Rebuild the vectors and compare them with the prior generation.

    Requires:
        - build( root, index, out_dir ) rewrites out_dir/vectors and returns a report; expect names matrices that may change

    Ensures:
        - the prior generation and the purpose store are checked before anything is built
        - returns { build, changed, expected } when every changed matrix was expected
    Raises:
        - NeedsetError PRIOR_GEN_MISSING and PURPOSE_STORE_NOT_LIVE before the build
        - NeedsetError MATRICES_CHANGED naming each matrix that differs and was not expected, after the build
    """
    prior = check_prior( prior_gen )
    check_purpose_store( out_dir, live_purpose_store( root ) if live_store is None else live_store )
    report     = build( root, index, out_dir )
    changed    = matrix_changes( prior, pathlib.Path( out_dir ) / VECTORS_DIR )
    unexpected = [ n for n in changed if n not in expect ]
    if unexpected: raise er.NeedsetError( er.MATRICES_CHANGED, f"{', '.join( unexpected )} differ from the prior generation {prior_gen} and were not expected" )
    return { "build": report, "changed": changed, "expected": sorted( expect ) }


def main( argv=None, out=sys.stdout, err=sys.stderr, live_store=None, build=_live_build ):
    """
    Run the rebuild from the command line.

    Requires:
        - argv is a list or None for sys.argv

    Ensures:
        - returns 0 and prints the report as JSON when every change was expected
        - returns EXIT_REFUSED after printing the code and detail to err; the vectors are already rewritten when only MATRICES_CHANGED refused
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "index", "out-dir", "prior-gen" ): ap.add_argument( f"--{name}", required=True )
    ap.add_argument( "--expect", default="", help="comma list of matrices allowed to differ from the prior generation" )
    args = ap.parse_args( argv )
    try:
        got = rebuild( args.root, args.index, args.out_dir, args.prior_gen, [ n for n in args.expect.split( "," ) if n ], live_store=live_store, build=build )
    except er.NeedsetError as e:
        print( f"rebuild REFUSED: {e}", file=err )
        return EXIT_REFUSED
    print( json.dumps( got, sort_keys=True, default=str ), file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover -- process entry point
    sys.exit( main() )
