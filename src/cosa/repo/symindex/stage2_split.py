"""
The fit and check split of the labelled-pair run, drawn by twin group.

The unit is the twin group, not the member. A twin of a fit member must never sit in the check half.
Otherwise the check half would hold the answer to the fit. The split is fixed before any call is made.
The record this module writes carries the seed, the manifest's sha256 and both halves.
Its own sha256 is what gets written into the plan.

No file other than the manifest and the output is touched, and no model is called.
"""
import argparse
import collections
import hashlib
import json
import pathlib
import random

STRATA = ( "exact", "near" )


def twin_groups( manifest ):
    """
    Join the manifest's exact clusters and near pairs into connected twin groups.

    Requires:
        - manifest holds "exact" and "near" lists of records whose "members" are dicts with an "id"
    Ensures:
        - returns a list of { "members": sorted ids, "stratum": "exact" or "near" }, sorted by first member
        - a member in an exact cluster and a near pair joins both into one group
        - the stratum is "exact" when any exact cluster is in the group, and "near" otherwise
        - the result does not depend on the order the manifest lists its records in
    Raises:
        - ValueError when a record has fewer than two members, since a lone member has no twin
    """
    parent = {}

    def find( x ):
        parent.setdefault( x, x )
        while parent[ x ] != x:
            parent[ x ] = parent[ parent[ x ] ]
            x           = parent[ x ]
        return x

    exact_ids = set()
    for kind in STRATA:
        for rec in manifest[ kind ]:
            ids = [ m[ "id" ] for m in rec[ "members" ] ]
            if len( ids ) < 2: raise ValueError( f"a {kind} record with a lone member: {ids!r}" )
            if kind == "exact": exact_ids.update( ids )
            for other in ids[ 1: ]: parent[ find( other ) ] = find( ids[ 0 ] )
    grouped = collections.defaultdict( list )
    for x in list( parent ): grouped[ find( x ) ].append( x )
    groups = [ { "members": sorted( ids ), "stratum": "exact" if exact_ids.intersection( ids ) else "near" } for ids in grouped.values() ]
    return sorted( groups, key=lambda g: g[ "members" ][ 0 ] )


def split_groups( groups, seed ):
    """
    Halve each stratum by a seeded shuffle.

    Requires:
        - groups come from twin_groups
        - seed is an int chosen and recorded by a person; there is no default
    Ensures:
        - returns { "fit": [...], "check": [...] }; every group is in exactly one half
        - each stratum is cut separately, and the fit half takes the odd group
        - the halves are the same for the same seed whatever order groups arrive in
        - within a half the groups are listed by first member
    """
    halves = { "fit": [], "check": [] }
    for stratum in STRATA:
        pool = sorted( ( g for g in groups if g[ "stratum" ] == stratum ), key=lambda g: g[ "members" ][ 0 ] )
        random.Random( seed ).shuffle( pool )
        cut = ( len( pool ) + 1 ) // 2
        halves[ "fit" ]   += pool[ :cut ]
        halves[ "check" ] += pool[ cut: ]
    for h in halves: halves[ h ].sort( key=lambda g: g[ "members" ][ 0 ] )
    return halves


def split_record( manifest, manifest_sha256, seed ):
    """
    Build the record that is written into the plan before the run.

    Ensures:
        - returns a dict with the unit, seed, manifest_sha256, counts of groups and members, and both halves
    """
    groups = twin_groups( manifest )
    halves = split_groups( groups, seed )
    return { "unit"            : "twin group",
             "seed"            : seed,
             "manifest_sha256" : manifest_sha256,
             "groups"          : len( groups ),
             "members"         : sum( len( g[ "members" ] ) for g in groups ),
             "fit"             : halves[ "fit" ],
             "check"           : halves[ "check" ] }


def record_sha256( record ):
    """Ensures: returns the sha256 of the record's canonical JSON, keys sorted and no spaces."""
    return hashlib.sha256( json.dumps( record, sort_keys=True, separators=( ",", ":" ) ).encode() ).hexdigest()


def half_by_member( record ):
    """Ensures: returns { member id: "fit" or "check" } for every member in the record."""
    return { i: h for h in ( "fit", "check" ) for g in record[ h ] for i in g[ "members" ] }


def main( argv=None ):
    """
    Write the split record for a manifest and print its sha256.

    Raises:
        - FileExistsError when the output file exists, so a recorded split is never overwritten
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--manifest", required=True ); ap.add_argument( "--seed", type=int, required=True ); ap.add_argument( "--out", required=True )
    a   = ap.parse_args( argv )
    out = pathlib.Path( a.out )
    if out.exists(): raise FileExistsError( f"{out} already exists; a recorded split is never overwritten" )
    raw = pathlib.Path( a.manifest ).read_bytes()
    rec = split_record( json.loads( raw ), hashlib.sha256( raw ).hexdigest(), a.seed )
    out.write_text( json.dumps( rec, indent=1, sort_keys=True ) + "\n" )
    print( f"groups={rec[ 'groups' ]} fit={len( rec[ 'fit' ] )} check={len( rec[ 'check' ] )} record_sha256={record_sha256( rec )}" )
    return 0


if __name__ == "__main__":
    raise SystemExit( main() )
