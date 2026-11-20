"""
Real embedding vectors for the extractor replay, from the service and a side cache.

The replay's default is a stand-in vector. This module gives the replay the vectors the live extractor job makes,
by calling the same function, default_embed, which routes to the embedding service. No call here loads a model or touches a GPU.
Each vector is cached in a JSON side file.
The key is the sha256 of the text plus the encoder version, so a rerun makes no repeat calls.
"""

import hashlib
import json
import os
from contextlib import contextmanager

from cosa.agents.principle_learner import extractor_store
from cosa.agents.principle_learner.extractor_job import default_embed, encoder_version
from cosa.rest.db.vector_store_models import EMBEDDING_DIM
from cosa.rest.repair_attempt_tracker import cosine_similarity

SENTINEL_KEY    = "__sentinel__"
SENTINEL_TEXT   = "Sentinel probe: does the service still run the model this cache was filled by?"
SENTINEL_FLOOR  = 0.999


class EmbeddingServiceUnavailable( RuntimeError ):
    """Raised when the embedding service is down or saturated, so the replay stops."""


class WrongVectorWidth( ValueError ):
    """Raised when the service returns a vector of the wrong length, which names another model."""


class CacheSentinelMismatch( ValueError ):
    """Raised when the cache's probe vector differs from a fresh probe."""


def cache_key( text, encoder ):
    """
    Name one cached vector.

    Requires:
        - text is a string and encoder a non-empty string

    Ensures:
        - returns the sha256 hex of the encoder, a newline and the text, so a new encoder version never reads an old vector
    """
    return hashlib.sha256( f"{encoder}\n{text}".encode( "utf-8" ) ).hexdigest()


class CachedServiceEmbedder:
    """
    Embed texts through the service, remembering every vector in a side file.

    Requires:
        - cache_path is a file path whose folder exists; the file may be absent
        - embed is a function from text to vector, or None for the live extractor's default_embed
        - encoder is the encoder version string, or None for the one the extractor job reads from the INI file
        - dimension is the vector length the service must return, or None for the stored column's width

    Ensures:
        - construction makes one probe call; it stores the probe's vector in the cache file under a sentinel key when none is there
        - a cache whose stored probe vector has cosine under 0.999 with the fresh probe raises CacheSentinelMismatch
        - a vector of any other length raises WrongVectorWidth and is never cached
        - a text already in the cache is answered from it with no call
        - a failed call raises EmbeddingServiceUnavailable naming the cause, and the cache keeps every vector already made
        - flush writes the cache atomically
    """

    def __init__( self, cache_path, embed=None, encoder=None, dimension=None ):
        self.cache_path = cache_path
        self.embed      = embed if embed is not None else default_embed
        self.encoder    = encoder if encoder is not None else encoder_version()
        self.calls      = 0
        self.hits       = 0
        self.dimension  = dimension if dimension is not None else EMBEDDING_DIM
        self.vectors    = {}
        if os.path.exists( cache_path ):
            with open( cache_path, encoding="utf-8" ) as handle: self.vectors = json.load( handle )
        self._check_sentinel()

    def _fetch( self, text ):
        """
        Ask the service for one vector and check its length.

        Requires:
            - text is a non-empty string

        Ensures:
            - returns the vector as a list of floats of the configured length
            - raises EmbeddingServiceUnavailable when the service raises a RuntimeError or a connection error
            - raises WrongVectorWidth for a vector of another length
        """
        try:
            vector = list( self.embed( text ) )
        except ( RuntimeError, ConnectionError, TimeoutError ) as error:
            if self.vectors: self.flush()
            raise EmbeddingServiceUnavailable( f"embedding service failed after {self.calls} calls: {error}" ) from error
        if len( vector ) != self.dimension:
            raise WrongVectorWidth( f"service returned {len( vector )} numbers, expected {self.dimension}: it is not the model this run names" )
        return vector

    def _check_sentinel( self ):
        """
        Compare a fresh probe with the cache's stored one, or store it when the cache has none.

        Ensures:
            - raises CacheSentinelMismatch when the stored and fresh probe vectors have cosine under 0.999
            - otherwise leaves the stored probe, or adds the fresh one, in memory; flush writes it
        """
        fresh = self._fetch( SENTINEL_TEXT )
        if SENTINEL_KEY not in self.vectors:
            self.vectors[ SENTINEL_KEY ] = fresh
            return
        similarity = cosine_similarity( list( self.vectors[ SENTINEL_KEY ] ), fresh )
        if similarity < SENTINEL_FLOOR:
            raise CacheSentinelMismatch( f"cache {self.cache_path} was filled by another model: probe cosine {similarity:.4f}, floor {SENTINEL_FLOOR}" )

    def __call__( self, text ):
        """
        Return the vector for a text, from the cache or the service.

        Requires:
            - text is a non-empty string

        Ensures:
            - returns a list of floats
            - raises EmbeddingServiceUnavailable when the service raises a RuntimeError or a connection error
            - raises WrongVectorWidth for a vector of another length
        """
        key = cache_key( text, self.encoder )
        if key in self.vectors:
            self.hits += 1
            return list( self.vectors[ key ] )
        vector = self._fetch( text )
        self.calls += 1
        self.vectors[ key ] = vector
        return list( vector )

    def flush( self ):
        """
        Write the cache to its file.

        Ensures:
            - the file holds every vector held so far; a crash mid-write leaves the old file whole
        """
        temporary = f"{self.cache_path}.tmp"
        with open( temporary, "w", encoding="utf-8" ) as handle: json.dump( self.vectors, handle )
        os.replace( temporary, self.cache_path )


@contextmanager
def record_neighbour_cosines( log ):
    """
    Log the cosine of every neighbour the extractor shows the model.

    Requires:
        - log is a list

    Ensures:
        - each call to extractor_store.fetch_neighbours appends one cosine per returned principle: its best cosine over the query vectors
        - the call's result is returned unchanged, and the original function is restored on exit, even after an error
    """
    original = extractor_store.fetch_neighbours
    def wrapped( session, owner_id, encoder, query_vectors, before, *args, **kwargs ):
        found = original( session, owner_id, encoder, query_vectors, before, *args, **kwargs )
        log.extend( max( cosine_similarity( list( row.embedding ), vector ) for vector in query_vectors ) for row in found )
        return found
    extractor_store.fetch_neighbours = wrapped
    try:
        yield log
    finally:
        extractor_store.fetch_neighbours = original
