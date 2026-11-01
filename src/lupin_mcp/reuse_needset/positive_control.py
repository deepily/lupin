"""
The one-time positive control: plant, find and remove Set A's 20 synthetic pairs.

Planting is in memory only. The pool is copied, the rewrites are added to the copy, and the copy is dropped.
Nothing is written to the symindex, the vector store or the proof's evidence folder.
The checker is a callable the caller brings, so this module makes no model call and imports no sourcer or scorer.
"""
import copy
import hashlib
import json

from lupin_mcp.reuse_needset import errors as er

PLANTED_SHA    = "4ec34350a03203c41c4a6dbcdbd873fbfbda3e38f47d7ca653a706819d470224"
STRATUM        = "opus-work-alike"
EXPECTED_PAIRS = 20
INDEX_FIELDS   = ( "id", "file", "module", "name", "sig", "doc" )


def load_pairs( path, expected_sha=PLANTED_SHA ):
    """
    Read the synthetic pairs from the proof's planted file, which is opened for reading only.

    Requires:
        - path is the planted.json of the proof's key folder

    Ensures:
        - returns the entries of stratum opus-work-alike, in file order, each with original and rewrite
        - the file's sha256 equals expected_sha and the count equals EXPECTED_PAIRS, else nothing is returned

    Raises:
        - NeedsetError CONTROL_INPUT_CHANGED when the sha or the pair count differs
    """
    raw = open( path, "rb" ).read()
    got = hashlib.sha256( raw ).hexdigest()
    if got != expected_sha: raise er.NeedsetError( er.CONTROL_INPUT_CHANGED, f"{path}: sha256 {got} is not {expected_sha}" )
    pairs = [ p for p in json.loads( raw )[ "planted" ] if p[ "stratum" ] == STRATUM ]
    if len( pairs ) != EXPECTED_PAIRS: raise er.NeedsetError( er.CONTROL_INPUT_CHANGED, f"{path}: {len( pairs )} {STRATUM} pairs, expected {EXPECTED_PAIRS}" )
    return pairs


def pool_digest( records ):
    """
    Fingerprint a pool of index records.

    Ensures:
        - returns the sha256 of the records as canonical JSON, in the order given
        - two pools have the same digest only when they hold the same records in the same order
    """
    return hashlib.sha256( json.dumps( records, sort_keys=True, separators=( ",", ":" ) ).encode( "utf-8" ) ).hexdigest()


def plant( records, pairs ):
    """
    Return a copy of the pool with each pair's rewrite added as an index record.

    Requires:
        - records is a list of index records, each with an id; pairs come from load_pairs

    Ensures:
        - records is not changed, and the copy shares no object with it
        - each rewrite is added with the index fields only, and the copy is sorted by id like the index

    Raises:
        - NeedsetError CONTROL_ID_COLLIDES when a rewrite's id is already in the pool or planted twice
    """
    taken = { r[ "id" ] for r in records }
    added = []
    for p in pairs:
        rid = p[ "rewrite" ][ "id" ]
        if rid in taken: raise er.NeedsetError( er.CONTROL_ID_COLLIDES, f"{rid}: already in the pool" )
        taken.add( rid )
        added.append( { f: p[ "rewrite" ].get( f, "" ) for f in INDEX_FIELDS } )
    return sorted( [ *copy.deepcopy( records ), *added ], key=lambda r: r[ "id" ] )


def lexical_find( need_fn, K, build_stage, shortlist ):
    """
    Build a find function that asks the word stage only, which makes no model call.

    Requires:
        - need_fn( pair ) returns the need text for a pair; build_stage and shortlist are the candidate stage's functions

    Ensures:
        - returns find( pool, pair ) giving the ids the word stage shortlists for the pair's need over that pool
    """
    def find( pool, pair ):
        """Ensures: returns the shortlisted ids for the pair's need."""
        return shortlist( need_fn( pair ), build_stage( pool ), K )[ "shortlist" ]
    return find


def run_control( records, pairs, find_fn, build_stage ):
    """
    Plant the pairs, ask the checker about each, remove them and prove the pool is as it was.

    Requires:
        - find_fn( planted_pool, pair ) returns the ids the checker asked about for that pair's need
        - build_stage builds a stage with an ids field from records, so the stage ids are checked too

    Ensures:
        - returns { pairs, found, missed, digest_before, digest_after, stage_ids_equal }
        - missed lists the rewrite ids the checker did not ask about; found counts the others
        - the pool the caller passed is the one checked after: its digest and its stage ids equal what they were before

    Raises:
        - NeedsetError CONTROL_NOT_RESTORED when the digest or the stage ids differ after the run
    """
    before, stage_before = pool_digest( records ), build_stage( records ).ids
    planted = plant( records, pairs )
    missed  = [ p[ "rewrite" ][ "id" ] for p in pairs if p[ "rewrite" ][ "id" ] not in set( find_fn( planted, p ) ) ]
    del planted
    after, stage_after = pool_digest( records ), build_stage( records ).ids
    if after != before or stage_after != stage_before: raise er.NeedsetError( er.CONTROL_NOT_RESTORED, f"pool digest {before} became {after}" )
    return { "pairs": len( pairs ), "found": len( pairs ) - len( missed ), "missed": missed, "digest_before": before, "digest_after": after, "stage_ids_equal": True }
