"""
The lexical half of the candidate stage: one need in, one shortlist out.

A stage holds a BM25 index over the code fields and one over the prose fields. A need is ranked
by both, fused with any extra ranked lists the caller brings (vectors, wiki pages), and cut to K.
Nothing here reads a clock, a random source or the network, so a replay gives the same bytes.
"""
import hashlib
import json

from cosa.repo.symindex.candidates import bm25
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates.errors import CandidateError

REPLAY_MISMATCH = "REPLAY_MISMATCH"
FUSION_SOURCES  = ( "code", "prose" )


class Stage:
    """
    A frozen candidate stage.

    Requires:
        - built only by build_stage

    Ensures:
        - holds the sorted entry ids, the two BM25 indexes and the fusion constants
    """

    __slots__ = ( "ids", "code", "prose", "fusion" )

    def __init__( self, ids, code, prose, fusion ):
        """Store the parts and seal the object."""
        object.__setattr__( self, "ids", ids )
        object.__setattr__( self, "code", code )
        object.__setattr__( self, "prose", prose )
        object.__setattr__( self, "fusion", fusion )

    def __setattr__( self, name, value ):
        """
        Refuse every assignment.

        Raises:
            - AttributeError always
        """
        raise AttributeError( f"Stage is frozen, cannot set {name}" )

    def manifest( self ):
        """
        Report the parameters a receipt records.

        Ensures:
            - returns the two index parameter blocks and the fusion constants
        """
        return { "code": self.code.params(), "prose": self.prose.params(), "fusion": dict( self.fusion ) }


def build_stage( entries, purposes=None, k=rf.FUSION_K, depth=rf.FUSION_DEPTH, head=rf.FUSION_HEAD ):
    """
    Build a stage from index entries and stored purpose lines.

    Requires:
        - entries is a list of index records, each with an id
        - purposes is None or a mapping of id to purpose line

    Ensures:
        - an entry with a purpose line carries it in the prose fields, and one without is left as is
        - the input entries are not changed
        - the code index covers id, file, module, name and sig, the prose index covers doc and purpose
    """
    purposes = purposes or {}
    merged   = [ dict( e, purpose=purposes.get( e[ "id" ], "" ) ) for e in entries ]
    return Stage( tuple( sorted( e[ "id" ] for e in entries ) ),
                  bm25.build_bm25( merged, bm25.CODE_FIELDS ),
                  bm25.build_bm25( merged, bm25.PROSE_FIELDS ),
                  { "k": k, "depth": depth, "head": head } )


def shortlist( need, stage, K, extra_lists=None ):
    """
    Choose the candidates for a need.

    Requires:
        - need is the redacted need text, with the redacted spans removed
        - K is a positive integer
        - extra_lists is None or a mapping of source name to a ranked list of ids

    Ensures:
        - ranks the need with the code index and the prose index
        - fuses those lists and the extra lists, taken in sorted source-name order
        - returns { shortlist, ranking, lists }
        - shortlist is the kept ids sorted by id, ready to pack
        - ranking is the same ids in fused order
        - lists holds each source's ranked ids, before fusion
        - the same need, stage and extra lists always give the same result
    """
    lists = { "code": bm25.rank( stage.code, need ), "prose": bm25.rank( stage.prose, need ) }
    for name, ranked in ( extra_lists or {} ).items(): lists[ name ] = list( ranked )
    order = rf.fuse( [ lists[ n ] for n in sorted( lists ) ], stage.fusion[ "k" ], stage.fusion[ "depth" ], stage.fusion[ "head" ], limit=K )
    return { "shortlist": sorted( order ), "ranking": order, "lists": { n: lists[ n ] for n in sorted( lists ) } }


def shortlist_bytes( result ):
    """
    Serialise a shortlist result one way only.

    Ensures:
        - returns UTF-8 JSON with sorted keys and no spaces after separators
    """
    return json.dumps( result, sort_keys=True, separators=( ",", ":" ), ensure_ascii=True ).encode( "utf-8" )


def replay( need, stage, K, recorded, extra_lists=None ):
    """
    Recompute a shortlist and compare it with a recorded one.

    Requires:
        - recorded is the bytes that shortlist_bytes gave on the first run

    Ensures:
        - returns the sha256 of the recomputed bytes when they equal recorded
        - the shortlist is recomputed from scratch, never read from a cache

    Raises:
        - CandidateError REPLAY_MISMATCH when the bytes differ
    """
    again = shortlist_bytes( shortlist( need, stage, K, extra_lists ) )
    if again != recorded: raise CandidateError( REPLAY_MISMATCH, f"recorded {hashlib.sha256( recorded ).hexdigest()[ :12 ]} now {hashlib.sha256( again ).hexdigest()[ :12 ]}" )
    return hashlib.sha256( again ).hexdigest()
