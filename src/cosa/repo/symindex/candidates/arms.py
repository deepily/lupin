"""
The five arms of the offline comparison, wired onto the candidate stage.

An arm is a choice of ranked lists to fuse. The first arm is BM25 alone and the second adds the purpose lines.
The third adds one concatenated vector list, the fourth a prose and a code vector list, the fifth the wiki page list.
This module builds the stages, picks each arm's lists, and ranks. It measures nothing and reads no needs file.
"""
from cosa.repo.symindex.candidates import candidate_stage as cs
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates import search
from cosa.repo.symindex.candidates.errors import CandidateError

ARM_UNKNOWN         = "ARM_UNKNOWN"
ARM_LIST_MISSING    = "ARM_LIST_MISSING"
FRESH_NEEDS_REFUSED = "FRESH_NEEDS_REFUSED"
FUSION_EMPTY        = "FUSION_EMPTY"

ARMS = ( "C0", "C1", "B1", "B2", "B2w" )
KS   = ( 32, 64, 128, 256, 512 )

ARM_SOURCES = {
    "C0"  : (),
    "C1"  : (),
    "B1"  : ( "vector_concat", ),
    "B2"  : ( "vector_prose", "vector_code" ),
    "B2w" : ( "vector_prose", "vector_code", "wiki" ),
}
ARM_PURPOSE = { "C0": False, "C1": True, "B1": True, "B2": True, "B2w": True }
FRESH_PREFIX = "fresh-"


def build_arm_stages( entries, purposes, k=rf.FUSION_K, depth=rf.FUSION_DEPTH, head=rf.FUSION_HEAD ):
    """
    Build the two stages the arms share.

    Requires:
        - entries is a list of index records, each with an id and a pin
        - purposes is a mapping of pin to purpose line

    Ensures:
        - returns { "plain": stage without purpose lines, "purposed": stage with them }
        - both use the same fusion constants
    """
    return { "plain"    : cs.build_stage( entries, None, k, depth, head ),
             "purposed" : cs.build_stage( entries, purposes, k, depth, head ) }


def lists_for_arm( arm, available ):
    """
    Pick the extra ranked lists an arm fuses.

    Requires:
        - available is a mapping of source name to a ranked list of ids

    Ensures:
        - returns { source: ranked ids } for the sources the arm names and no others
        - the BM25-only arm and the purpose-line arm take no extra list, whatever is available

    Raises:
        - CandidateError ARM_UNKNOWN when arm is not one of the five arm names
        - CandidateError ARM_LIST_MISSING when the arm needs a source that is not available
    """
    if arm not in ARM_SOURCES: raise CandidateError( ARM_UNKNOWN, f"{arm} is not one of {', '.join( ARMS )}" )
    missing = [ name for name in ARM_SOURCES[ arm ] if name not in available ]
    if missing: raise CandidateError( ARM_LIST_MISSING, f"{arm} needs {', '.join( missing )}" )
    return { name: list( available[ name ] ) for name in ARM_SOURCES[ arm ] }


def run_arm( arm, need, stages, available, K ):
    """
    Shortlist one need under one arm.

    Requires:
        - stages comes from build_arm_stages
        - K is a positive integer

    Ensures:
        - returns the candidate stage's result for the arm's stage and lists
        - the result is the one production would build at K, head ids included

    Raises:
        - CandidateError ARM_UNKNOWN or ARM_LIST_MISSING, from lists_for_arm
    """
    extra = lists_for_arm( arm, available )
    stage = stages[ "purposed" if ARM_PURPOSE[ arm ] else "plain" ]
    return cs.shortlist( need, stage, K, extra )


def full_ranking( arm, need, stages, available ):
    """
    Order every entry the arm can reach for one need.

    Ensures:
        - returns the fused order with no cut, so a twin's rank can be read from it
        - an entry that no list holds within the fusion depth is absent
    """
    stage = stages[ "purposed" if ARM_PURPOSE[ arm ] else "plain" ]
    return run_arm( arm, need, stages, available, len( stage.ids ) )[ "ranking" ]


def cosine_sources( ids, matrices, query_vectors ):
    """
    Rank the entries by each stored matrix.

    Requires:
        - matrices maps a matrix name to one float32 row per id
        - query_vectors maps a matrix name to a query vector

    Ensures:
        - returns { "vector_<name>": ranked ids } in the names search.answer uses
        - only matrices that have a query vector are ranked
    """
    return { f"vector_{name}": [ doc_id for doc_id, _ in search.cosine_ranked( ids, matrices[ name ], query_vectors[ name ] ) ]
             for name in sorted( query_vectors ) }


def refuse_fresh_needs( need_ids, fresh_ids=(), needs_sha=None, fresh_sha=None ):
    """
    Stop a run that holds a need reserved for the confirmation phase.

    Requires:
        - need_ids is the ids of the needs about to be used
        - fresh_ids is any extra ids that are reserved
        - needs_sha and fresh_sha are the content hashes of the needs file in use and of the reserved file, both or neither

    Ensures:
        - returns None when no need is reserved
        - an id that starts with "fresh-" or is in fresh_ids counts as reserved
        - the needs file counts as reserved when its hash equals the reserved file's hash

    Raises:
        - CandidateError FRESH_NEEDS_REFUSED naming the reserved ids, or the file
        - ValueError when only one of the two hashes is given
    """
    if ( needs_sha is None ) != ( fresh_sha is None ): raise ValueError( "give both file hashes or neither" )
    if needs_sha is not None and needs_sha == fresh_sha: raise CandidateError( FRESH_NEEDS_REFUSED, "the needs file is the reserved file" )
    reserved = sorted( n for n in need_ids if n.startswith( FRESH_PREFIX ) or n in set( fresh_ids ) )
    if reserved: raise CandidateError( FRESH_NEEDS_REFUSED, ", ".join( reserved ) )


def select_fusion( recall_by_params ):
    """
    Choose the fusion constants from in-sample recall.

    Requires:
        - recall_by_params maps ( k, depth, head ) to a recall figure measured on the 30 in-sample needs

    Ensures:
        - returns the ( k, depth, head ) with the highest recall
        - ties go to the smaller k, then the smaller depth, then the smaller head

    Raises:
        - CandidateError FUSION_EMPTY when there are no candidates
    """
    if not recall_by_params: raise CandidateError( FUSION_EMPTY, "no fusion constants were measured" )
    return min( recall_by_params, key=lambda p: ( -recall_by_params[ p ], p ) )
