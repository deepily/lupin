"""
The kind-by-language table of the need set, the seed census and the seeded draw.

The split of the matched needs by kind is not defaulted: plan_quota refuses to run without one.
"""
import json
import os
import pathlib
import random
import threading

from cosa.repo.doc_lint.quota_split import quotas
from lupin_mcp.reuse_needset import errors as er

MATCHED_KINDS = ( "near_copy", "work_alike", "cross_language" )
LANGS         = ( "ts", "py" )
NONE_KIND     = "nothing"
ALL_KINDS     = MATCHED_KINDS + ( NONE_KIND, )
PLAN_FORMAT   = "needset-plan-1"


def _invalid( why ):
    """Raises: NeedsetError QUOTA_INVALID with the reason."""
    raise er.NeedsetError( er.QUOTA_INVALID, why )


def plan_quota( total, matched, none, ts_share, kind_split=None ):
    """
    Fill the kind-by-language table so the language margins are exact.

    Requires:
        - total, matched and none are whole numbers with matched + none == total
        - ts_share is a number from 0 to 1
        - kind_split maps each of MATCHED_KINDS to a whole number, and the three sum to matched

    Ensures:
        - returns { kind: { "ts": n, "py": m } } for the three matched kinds and nothing
        - the ts cells sum to the largest-remainder share of total, and the py cells to the rest
        - the nothing kind takes its own largest-remainder language split, and the matched kinds share the ts total left
        - each matched kind's ts count is at most its size

    Raises:
        - NeedsetError KIND_SPLIT_UNSET when kind_split is None
        - NeedsetError QUOTA_INVALID for a split with the wrong keys, a negative or non-integer count, a wrong sum, or numbers that do not add up
    """
    if kind_split is None: raise er.NeedsetError( er.KIND_SPLIT_UNSET, "no kind_split supplied: the split of the matched needs by kind is Rick's to fill in" )
    for name, n in ( ( "total", total ), ( "matched", matched ), ( "none", none ) ):
        if not isinstance( n, int ) or isinstance( n, bool ) or n < 0: _invalid( f"{name} must be a whole number of 0 or more, got {n!r}" )
    if matched + none != total: _invalid( f"matched {matched} + none {none} is not total {total}" )
    if not isinstance( ts_share, ( int, float ) ) or isinstance( ts_share, bool ) or not 0 <= ts_share <= 1: _invalid( f"ts_share must be a number from 0 to 1, got {ts_share!r}" )
    if set( kind_split ) != set( MATCHED_KINDS ): _invalid( f"kind_split needs exactly the kinds {MATCHED_KINDS}" )
    for kind, n in kind_split.items():
        if not isinstance( n, int ) or isinstance( n, bool ) or n < 0: _invalid( f"kind_split[{kind!r}] must be a whole number of 0 or more, got {n!r}" )
    if sum( kind_split.values() ) != matched: _invalid( f"kind_split sums to {sum( kind_split.values() )}, not matched {matched}" )
    mix        = { "ts": ts_share, "py": 1 - ts_share }
    ts_total   = quotas( total, mix )[ "ts" ]
    none_split = quotas( none, mix )
    ts_matched = ts_total - none_split[ "ts" ]
    table      = { NONE_KIND: none_split }
    shares     = { k: ( n / matched if matched else 0 ) for k, n in kind_split.items() }
    ts_by_kind = quotas( ts_matched, shares )
    for kind in MATCHED_KINDS: table[ kind ] = { "ts": ts_by_kind[ kind ], "py": kind_split[ kind ] - ts_by_kind[ kind ] }
    if sum( row[ "ts" ] for row in table.values() ) != ts_total or any( n < 0 for row in table.values() for n in row.values() ):  # pragma: no cover - each kind's ts count is its size times a share of at most 1
        _invalid( f"the language margins do not hold for total {total}, none {none}, ts_share {ts_share}" )
    return { kind: table[ kind ] for kind in ALL_KINDS }


def census( pool ):
    """
    Count the eligible seeds in every cell before any model call.

    Requires:
        - pool maps ( kind, lang ) to a list of seed ids; a missing cell counts as 0

    Ensures:
        - returns { kind: { "ts": n, "py": m } } counting distinct ids
    """
    return { kind: { lang: len( set( pool.get( ( kind, lang ), [] ) ) ) for lang in LANGS } for kind in ALL_KINDS }


def _assign( slots, eligible, rng ):
    """
    Match every slot of every cell to its own seed id, or find the first slot that cannot be.

    Requires:
        - slots is a list of ( kind, lang ) cells, one entry per seed the cell needs, in sorted cell order
        - eligible maps a cell to its sorted list of ids

    Ensures:
        - returns ( owner, None ) with owner mapping each matched id to the slot index it fills, when every slot matches
        - returns ( owner, index ) with the first slot index that no augmenting path could fill, when one cannot
        - an id eligible for several cells is reassigned along an augmenting path, so a valid assignment is never missed
        - the candidates of each slot are tried in an order shuffled by rng
    """
    owner = {}

    def place( index, seen ):
        """Try to give slot index an id, moving earlier slots to other ids when needed."""
        ids = list( eligible[ slots[ index ] ] )
        rng.shuffle( ids )
        for sid in ids:
            if sid in seen: continue
            seen.add( sid )
            if sid not in owner or place( owner[ sid ], seen ):
                owner[ sid ] = index
                return True
        return False

    for index in range( len( slots ) ):
        if not place( index, set() ): return owner, index
    return owner, None


def draw( pool, quota, seed ):
    """
    Draw the seeds of every cell, with spares, from a sorted pool and a fixed seed.

    Requires:
        - pool maps ( kind, lang ) to a list of seed ids
        - quota comes from plan_quota
        - seed is any value random.Random accepts

    Ensures:
        - returns { ( kind, lang ): { "primary": [ids], "spares": [ids] } } for every cell in sorted cell order
        - the result is the same for the same seed whatever order the pool lists its ids in
        - a seed id is the primary of at most one cell, and a valid assignment is found whenever one exists, even when cells share their ids
        - a spare is an id no cell took as a primary, listed under exactly one cell that finds it eligible
        - spares are shuffled within each cell

    Raises:
        - NeedsetError QUOTA_UNFILLABLE naming the first cell, in sorted order, whose seeds cannot all be found
    """
    rng      = random.Random( seed )
    cells    = sorted( ( kind, lang ) for kind in ALL_KINDS for lang in LANGS )
    eligible = { cell: sorted( set( pool.get( cell, [] ) ) ) for cell in cells }
    slots    = [ cell for cell in cells for _ in range( quota[ cell[ 0 ] ][ cell[ 1 ] ] ) ]
    owner, failed = _assign( slots, eligible, rng )
    if failed is not None:
        cell = slots[ failed ]
        have, want = len( eligible[ cell ] ), quota[ cell[ 0 ] ][ cell[ 1 ] ]
        why = f"has {have} eligible seeds, needs {want}" if have < want else f"has {have} eligible seeds, needs {want}, but the other cells need the same ones"
        raise er.NeedsetError( er.QUOTA_UNFILLABLE, f"cell {cell[ 0 ]}/{cell[ 1 ]} {why}" )
    drawn = { cell: { "primary": [], "spares": [] } for cell in cells }
    for sid in sorted( owner ): drawn[ slots[ owner[ sid ] ] ][ "primary" ].append( sid )
    for cell in cells: rng.shuffle( drawn[ cell ][ "primary" ] )
    leftovers = sorted( { sid for cell in cells for sid in eligible[ cell ] } - set( owner ) )
    for sid in leftovers:
        drawn[ rng.choice( [ cell for cell in cells if sid in eligible[ cell ] ] ) ][ "spares" ].append( sid )
    for cell in cells: rng.shuffle( drawn[ cell ][ "spares" ] )
    return drawn


def plan_record( seed, quota, kind_split, source_commit, pool_reader, set_by, set_at ):
    """
    Build the plan record that is written before the first draft is requested.

    Requires:
        - the arguments are JSON values; kind_split is the table plan_quota was given

    Ensures:
        - returns { format, seed, quota, kind_split, source_commit, pool_reader, kind_split_set_by, kind_split_set_at }
        - the quota keys are strings "kind/lang" so the record is JSON
    """
    flat = { f"{kind}/{lang}": n for kind, row in quota.items() for lang, n in row.items() }
    return { "format": PLAN_FORMAT, "seed": seed, "quota": flat, "kind_split": dict( kind_split ), "source_commit": source_commit,
             "pool_reader": pool_reader, "kind_split_set_by": set_by, "kind_split_set_at": set_at }


def write_plan( path, record ):
    """
    Write the plan record once, all at once.

    Requires:
        - path is writable and its folder exists

    Ensures:
        - the record is written to a temporary file beside path and hard-linked into place, so a reader sees the whole file or none
        - of several writers racing for one path exactly one succeeds
        - no temporary file is left behind, whether the link succeeds or not
        - the file holds the record as sorted-key JSON with a final newline

    Raises:
        - NeedsetError PLAN_ALREADY_WRITTEN when a file exists at path, which is left untouched
    """
    target = pathlib.Path( path )
    temp   = target.with_name( f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp" )
    temp.write_text( json.dumps( record, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    try:
        os.link( temp, target )
    except FileExistsError as e:
        raise er.NeedsetError( er.PLAN_ALREADY_WRITTEN, str( target ) ) from e
    finally:
        temp.unlink()
