"""
Hardness sourcing: find real code that a plain word search misses.

A work-alike for Set B is a real function whose need a BM25 search over identifiers and docstrings does not return in its top results.
Hardness is measured per function from the index. Nothing is planted and no pair is mined.
"""
import collections

from cosa.repo.symindex.candidates import bm25
from lupin_mcp.reuse_needset import errors as er

HARDNESS_FIELDS = ( "id", "module", "name", "sig", "doc" )
BM25_K          = 10


def build_index( entries ):
    """
    Build the BM25 index the hardness check searches.

    Requires:
        - entries are index records that each carry a unique id

    Ensures:
        - returns a frozen index over the identifier and docstring fields of HARDNESS_FIELDS
    """
    return bm25.build_bm25( entries, HARDNESS_FIELDS )


def rank_of( index, need, target, exclude=() ):
    """
    Find where a search for a need lists a target.

    Requires:
        - need is the need sentence; target is an index id
        - exclude lists ids left out of the ranking, as the checker leaves out the seed

    Ensures:
        - returns the 1-based position of the target among the ranked ids with the excluded ones removed
        - returns None when the search does not list the target at all
    """
    left = [ i for i in bm25.rank( index, need ) if i not in set( exclude ) ]
    return left.index( target ) + 1 if target in left else None


def is_hard( rank, k=BM25_K ):
    """
    Say whether a rank counts as missed by the search.

    Ensures:
        - returns True for an unlisted target or one ranked below k, and False for a rank of k or better
    """
    return rank is None or rank > k


def source_hard( rows, index, k=BM25_K ):
    """
    Measure every candidate row and mark the hard ones.

    Requires:
        - rows are { seed, need, targets, lang } mappings, with an optional seed_is_answer that is True when the seed is the known answer; targets is a non-empty list of index ids
        - the seed is left out of the ranking, so the search is the one the checker runs, except when it is the known answer, which is then ranked like any other target

    Ensures:
        - returns a copy of each row, in order, with ranks (target to rank or None), hard_members (the targets the search misses) and hard
        - hard is True only when every target is missed
        - the rows given are not changed

    Raises:
        - NeedsetError BAD_NEED for a row with no targets
        - NeedsetError SEED_IS_TARGET for a row whose seed is one of its own targets and is not marked as the known answer, before any rank is read
    """
    out = []
    for row in rows:
        if not row[ "targets" ]: raise er.NeedsetError( er.BAD_NEED, f"{row[ 'seed' ]}: a hardness row needs at least one target" )
        answer = row.get( "seed_is_answer", False )
        if row[ "seed" ] in row[ "targets" ] and not answer: raise er.NeedsetError( er.SEED_IS_TARGET, f"{row[ 'seed' ]}: the seed is left out of the search, so it cannot be its own target" )
        ranks = { t: rank_of( index, row[ "need" ], t, exclude=() if answer else ( row[ "seed" ], ) ) for t in row[ "targets" ] }
        missed = [ t for t in row[ "targets" ] if is_hard( ranks[ t ], k ) ]
        out.append( { **row, "ranks": ranks, "hard_members": missed, "hard": len( missed ) == len( row[ "targets" ] ) } )
    return out


def yield_report( measured, k=BM25_K ):
    """
    Count the hard rows per language.

    Requires:
        - measured is the result of source_hard

    Ensures:
        - returns { k, seeds, hard, by_lang } where by_lang maps a language to { seeds, hard, per_100 }
        - per_100 is the hard rows per 100 seeds of that language, so the natural yield reads directly
    """
    seeds, hard = collections.Counter( r[ "lang" ] for r in measured ), collections.Counter( r[ "lang" ] for r in measured if r[ "hard" ] )
    return { "k": k, "seeds": len( measured ), "hard": sum( hard.values() ),
             "by_lang": { lang: { "seeds": seeds[ lang ], "hard": hard[ lang ], "per_100": 100.0 * hard[ lang ] / seeds[ lang ] } for lang in sorted( seeds ) } }
