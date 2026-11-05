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
SOURCE_CLASH    = "SOURCE_CLASH"
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
        - purposes is None or a mapping of pin to purpose line

    Ensures:
        - an entry with a purpose line carries it in the prose fields, and one without is left as is
        - the input entries are not changed
        - the code index covers id, file, module, name and sig, the prose index covers doc and purpose
    """
    purposes = purposes or {}
    merged   = [ dict( e, purpose=purposes.get( e.get( "pin" ), "" ) ) for e in entries ]
    return Stage( tuple( sorted( e[ "id" ] for e in entries ) ),
                  bm25.build_bm25( merged, bm25.CODE_FIELDS ),
                  bm25.build_bm25( merged, bm25.PROSE_FIELDS ),
                  { "k": k, "depth": depth, "head": head } )


def protected_order( lists, order, stage, K, protect ):
    """
    Keep the plain need's own top ids ahead of the expanded fusion.

    Requires:
        - lists holds every source's ranked ids; order is the fusion of all of them cut to K
        - protect is { head, skip } with head above 0

    Ensures:
        - returns at most K ids in the fused order of all sources
        - holds the first head ids of the fusion of the sources not named in skip
        - then fills up to K from order, best first, skipping ids already held
        - the plain fusion uses the stage's own k and depth and a list head no larger than its own limit
    """
    plain = rf.fuse( [ lists[ n ] for n in sorted( lists ) if n not in protect[ "skip" ] ], stage.fusion[ "k" ], stage.fusion[ "depth" ],
                     min( stage.fusion[ "head" ], protect[ "head" ] ), limit=min( protect[ "head" ], K ) )
    kept  = list( plain )
    for doc_id in order:
        if len( kept ) >= K: break
        if doc_id not in kept: kept.append( doc_id )
    held = set( kept )
    return [ d for d in rf.fuse( [ lists[ n ] for n in sorted( lists ) ], stage.fusion[ "k" ], stage.fusion[ "depth" ], stage.fusion[ "head" ] ) if d in held ]


def shortlist( need, stage, K, extra_lists=None, protect=None ):
    """
    Choose the candidates for a need.

    Requires:
        - need is the redacted need text, with the redacted spans removed
        - K is a positive integer
        - extra_lists is None or a mapping of source name to a ranked list of ids
        - no extra source is named code or prose
        - protect is None, or { head, skip }: head is a count and skip names the extra sources that came from expanded queries

    Ensures:
        - ranks the need with the code index and the prose index
        - fuses those lists and the extra lists, taken in sorted source-name order
        - returns { shortlist, ranking, lists, scores }
        - shortlist is the kept ids sorted by id, ready to pack
        - ranking is the same ids in fused order
        - lists holds each source's ranked ids, before fusion
        - scores holds the rounded BM25 scores of the code and prose lists, in list order
        - the shortlist holds at most K ids: the top head ids of every list, then the best of the rest
        - with protect, the first head ids of the fusion of the sources not in skip are kept first and the rest of K is filled from the fusion of all sources, in its order; the result stays in fused order
        - without protect, or with a head of 0, the result is what it was before protect existed
        - the same need, stage and extra lists always give the same result

    Raises:
        - CandidateError SOURCE_CLASH when an extra source reuses a lexical source name
        - CandidateError HEAD_EXCEEDS_LIMIT when the top head ids of all lists are more than K
    """
    scored = { "code": bm25.rank_scored( stage.code, need ), "prose": bm25.rank_scored( stage.prose, need ) }
    lists  = { name: [ doc_id for doc_id, _ in pairs ] for name, pairs in scored.items() }
    for name, ranked in ( extra_lists or {} ).items():
        if name in lists: raise CandidateError( SOURCE_CLASH, f"{name} is already a lexical source" )
        lists[ name ] = list( ranked )
    order = rf.fuse( [ lists[ n ] for n in sorted( lists ) ], stage.fusion[ "k" ], stage.fusion[ "depth" ], stage.fusion[ "head" ], limit=K )
    if protect is not None and protect[ "head" ] > 0: order = protected_order( lists, order, stage, K, protect )
    return { "shortlist": sorted( order ), "ranking": order, "lists": { n: lists[ n ] for n in sorted( lists ) },
             "scores": { name: [ score for _, score in pairs ] for name, pairs in scored.items() } }


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
