"""
BM25 over split identifiers.

An index is built once from the index entries and never changes. A query is scored by a fixed
sequence of float operations, so one index and one query give the same ranking on every run.
"""
import math
from collections import Counter

from cosa.repo.symindex.candidates.identifier_split import split_identifier

K1            = 1.2
B             = 0.75
SCORE_DIGITS  = 6
CODE_FIELDS   = ( "id", "file", "module", "name", "sig" )
PROSE_FIELDS  = ( "doc", "purpose" )


class Bm25Index:
    """
    A frozen BM25 index over one field set.

    Requires:
        - built only by build_bm25

    Ensures:
        - holds ids, per-term postings, inverse document frequencies and lengths
        - refuses assignment to any attribute after construction
    """

    __slots__ = ( "ids", "postings", "idf", "lengths", "average", "fields", "k1", "b", "_sealed" )

    def __init__( self, ids, postings, idf, lengths, average, fields, k1, b ):
        """
        Store the index parts and seal the object.

        Requires:
            - postings maps a term to a tuple of ( document position, term frequency ) pairs
        """
        object.__setattr__( self, "ids", ids )
        object.__setattr__( self, "postings", postings )
        object.__setattr__( self, "idf", idf )
        object.__setattr__( self, "lengths", lengths )
        object.__setattr__( self, "average", average )
        object.__setattr__( self, "fields", fields )
        object.__setattr__( self, "k1", k1 )
        object.__setattr__( self, "b", b )
        object.__setattr__( self, "_sealed", True )

    def __setattr__( self, name, value ):
        """
        Refuse every assignment.

        Raises:
            - AttributeError always
        """
        raise AttributeError( f"Bm25Index is frozen, cannot set {name}" )

    def params( self ):
        """
        Report what the manifest records about this index.

        Ensures:
            - returns the field names, k1, b, score digits and document count
        """
        return { "fields": list( self.fields ), "k1": self.k1, "b": self.b, "score_digits": SCORE_DIGITS, "documents": len( self.ids ) }


def entry_words( entry, fields ):
    """
    Collect the words of one entry over a field set.

    Requires:
        - entry is a mapping, and a missing or empty field is allowed

    Ensures:
        - returns the split words of each field in field order
    """
    words = []
    for field in fields:
        value = entry.get( field )
        if value: words.extend( split_identifier( str( value ) ) )
    return words


def build_bm25( entries, fields, k1=K1, b=B ):
    """
    Build a frozen index from index entries.

    Requires:
        - entries is a list of mappings that each carry a unique id
        - fields is a tuple of entry keys

    Ensures:
        - documents are ordered by id, so the entry order never matters
        - idf is log( 1 + ( N - n + 0.5 ) / ( n + 0.5 ) ), which is never negative
        - an empty entry list gives an index that ranks nothing
    """
    ordered  = sorted( entries, key=lambda e: e[ "id" ] )
    ids      = tuple( e[ "id" ] for e in ordered )
    counts   = [ Counter( entry_words( e, fields ) ) for e in ordered ]
    lengths  = tuple( sum( c.values() ) for c in counts )
    postings = {}
    for position, counter in enumerate( counts ):
        for term in sorted( counter ): postings.setdefault( term, [] ).append( ( position, counter[ term ] ) )
    n        = len( ids )
    idf      = { term: math.log( 1.0 + ( n - len( rows ) + 0.5 ) / ( len( rows ) + 0.5 ) ) for term, rows in postings.items() }
    average  = sum( lengths ) / n if n else 0.0
    return Bm25Index( ids, { t: tuple( r ) for t, r in postings.items() }, idf, lengths, average, tuple( fields ), k1, b )


def rank_scored( index, query ):
    """
    Score a query against an index.

    Requires:
        - query is a string

    Ensures:
        - each distinct query word counts once, taken in sorted order so the float sum is fixed
        - a score is rounded to SCORE_DIGITS places before any sort
        - returns ( id, rounded score ) pairs ordered by ( -rounded score, id )
        - lists only documents that share a word with the query, each with a score above zero
    """
    scores = {}
    for term in sorted( set( split_identifier( query ) ) ):
        rows = index.postings.get( term )
        if rows is None: continue
        weight = index.idf[ term ]
        for position, freq in rows:
            norm = freq + index.k1 * ( 1.0 - index.b + index.b * index.lengths[ position ] / index.average )
            scores[ position ] = scores.get( position, 0.0 ) + weight * freq * ( index.k1 + 1.0 ) / norm
    rounded = [ ( index.ids[ p ], round( s, SCORE_DIGITS ) ) for p, s in scores.items() ]
    return sorted( rounded, key=lambda r: ( -r[ 1 ], r[ 0 ] ) )


def rank( index, query ):
    """
    Rank the documents of an index for a query.

    Ensures:
        - returns ids ordered by ( -rounded score, id )
    """
    return [ doc_id for doc_id, _ in rank_scored( index, query ) ]
