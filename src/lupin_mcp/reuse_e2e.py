"""
The end-to-end run: frozen inputs, the reading of one search, and the figures' arithmetic.

The sample, the needs and the manifest are each checked against a hash before anything is read from them.
Nothing here sends a request. The runner that spends tokens is reuse_e2e_run.
"""
import hashlib
import json
import math

from lupin_mcp import reuse_stage2_fit as fit

SAMPLE_SHA256   = "5b6d84fc2dd8dc458b36255e129001f55e3fbe4d252c14c6d65a4994779a91fd"
MANIFEST_SHA256 = "bfbfceab399cf753093f0c9ee0bec73a0de00738a0696126a669e129de466941"
NEEDS_FORMAT    = "reuse-e2e-needs-1"
STRATA          = ( ( "has_exact_cluster", 58 ), ( "near_only", 42 ) )
MEMBERS         = sum( n for _, n in STRATA )
Z_95            = 1.959964


class FrozenInputRefused( ValueError ):
    """A frozen input is not the one the run was written for."""


def _read_checked( path, expected_sha, what ):
    """
    Read a JSON file whose hash must match.

    Requires:
        - path names a file; expected_sha is 64 hex characters
    Ensures:
        - returns the parsed JSON
    Raises:
        - FrozenInputRefused when the file's sha256 differs, naming both, or when it is not JSON
    """
    raw = open( path, "rb" ).read()
    got = hashlib.sha256( raw ).hexdigest()
    if got != expected_sha: raise FrozenInputRefused( f"{what} {path}: sha256 is {got}, the run expects {expected_sha}" )
    try: return json.loads( raw )
    except ValueError as e: raise FrozenInputRefused( f"{what} {path} is not JSON: {e}" ) from e


def load_sample( path, expected_sha=SAMPLE_SHA256 ):
    """
    Read the frozen sample.

    Requires:
        - path names the sample file with a strata mapping of member lists
    Ensures:
        - returns the member ids, the exact-cluster stratum first and the near-only stratum after it
        - the file's hash matched, the strata hold 58 and 42 members, and no member is repeated
    Raises:
        - FrozenInputRefused for any of the above that does not hold
    """
    record  = _read_checked( path, expected_sha, "sample" )
    members = []
    for name, size in STRATA:
        got = record[ "strata" ][ name ][ "members" ]
        if len( got ) != size: raise FrozenInputRefused( f"sample stratum {name} holds {len( got )} members; the run expects {size}, so 58 and 42 in all" )
        members += got
    if len( set( members ) ) != len( members ): raise FrozenInputRefused( "a member is repeated across the sample's strata" )
    return members


def load_needs( path, expected_sha, members ):
    """
    Read the frozen need sentences.

    Requires:
        - members is the sample's member list, in its frozen order
    Ensures:
        - returns [ { member, need } ] in the sample's order, one per member
    Raises:
        - FrozenInputRefused for a wrong hash, a wrong format, a count other than 100, an order that differs from the sample's, or an empty need
    """
    record = _read_checked( path, expected_sha, "needs file" )
    if record[ "format" ] != NEEDS_FORMAT: raise FrozenInputRefused( f"needs file format is {record[ 'format' ]!r}, expected {NEEDS_FORMAT!r}" )
    rows = record[ "needs" ]
    if len( rows ) != MEMBERS: raise FrozenInputRefused( f"needs file holds {len( rows )} needs; the run expects {MEMBERS}" )
    if [ r[ "member" ] for r in rows ] != list( members ): raise FrozenInputRefused( "the needs file's members differ from the sample's, or are in another order" )
    for r in rows:
        if not isinstance( r[ "need" ], str ) or not r[ "need" ].strip(): raise FrozenInputRefused( f"member {r[ 'member' ]} has an empty need" )
    return [ { "member": r[ "member" ], "need": r[ "need" ].strip() } for r in rows ]


def load_twins( path, expected_sha=MANIFEST_SHA256 ):
    """
    Read the twin manifest as a map from a member to the ids of its twins.

    Ensures:
        - returns { id: set of twin ids }, as the fit script reads it
    Raises:
        - FrozenInputRefused when the manifest's hash differs
    """
    return fit.twin_map_from_manifest( _read_checked( path, expected_sha, "manifest" ) )


def read_search( result, twins ):
    """
    Read one finished search against the twins of its member.

    Requires:
        - result has verdict, shortlist and nearest, each entry a dict with an id; nearest is ranked best first
    Ensures:
        - returns { verdict, on_shortlist, ranked_first, top_ten }
        - on_shortlist: any twin is in the shortlist; ranked_first: the best-ranked entry is a twin; top_ten: any twin is in nearest
    """
    near = [ r[ "id" ] for r in result[ "nearest" ] ]
    return { "verdict": result[ "verdict" ], "on_shortlist": any( r[ "id" ] in twins for r in result[ "shortlist" ] ),
             "ranked_first": bool( near ) and near[ 0 ] in twins, "top_ten": any( i in twins for i in near ) }


def incomplete_causes( result, ceiling_hit, ledger_stopped ):
    """
    Name why a search is not complete, one reason per cause and never folded together.

    Requires:
        - result is the public result of a search, or an error result
        - ceiling_hit: the token ceiling refused an attempt during this search; ledger_stopped: the ledger stopped the run during it
    Ensures:
        - returns [] for a complete search
        - otherwise the causes in the order ceiling, ledger, CALL_FAILED, MALFORMED_ANSWER, then the sweep's own stop name
        - entries left unasked with no named reason are named attempts
    """
    if result[ "status" ] != "ok": return [ f"ERROR:{result[ 'error' ]}" ]
    stats, causes = result[ "stats" ], []
    left = stats[ "not_checked" ] > 0
    if left and ceiling_hit: causes.append( "ceiling" )
    if left and ledger_stopped: causes.append( "ledger" )
    if stats[ "failed" ] > 0: causes.append( "CALL_FAILED" )
    if result[ "malformed" ]: causes.append( "MALFORMED_ANSWER" )
    if left and stats[ "stopped_by" ]: causes.append( stats[ "stopped_by" ] )
    if left and not causes: causes.append( "attempts" )
    return causes


def wilson( k, n, z=Z_95 ):
    """Ensures: returns the Wilson interval ( low, high ) of k in n, or ( None, None ) if n is 0."""
    if n == 0: return None, None
    p      = k / n
    centre = ( p + z * z / ( 2 * n ) ) / ( 1 + z * z / n )
    half   = z * math.sqrt( p * ( 1 - p ) / n + z * z / ( 4 * n * n ) ) / ( 1 + z * z / n )
    return max( 0.0, centre - half ), min( 1.0, centre + half )


def mcnemar_exact( only_a, only_b ):
    """Ensures: returns the exact two-sided McNemar p of two discordant counts, 1.0 for none."""
    n = only_a + only_b
    if n == 0: return 1.0
    low = min( only_a, only_b )
    return min( 1.0, 2 * sum( math.comb( n, i ) for i in range( low + 1 ) ) / 2 ** n )
