"""Body embeddings for the candidate stage, cached by text sha."""
import hashlib
import json
import os
import pathlib
import time

from cosa.repo.symindex.candidates import vector_build as vb
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, EMBEDDING_SHAPE

CONTENT_TYPE = "code"
ROLE         = "document"


def body_text( d, limit ):
    """
    Return the text that is embedded for a definition and whether it was cut.

    Requires:
        - d is a definition record from extract; its text begins with its signature
        - limit is a positive int, the frozen body_chars

    Ensures:
        - returns ( text, truncated ): the definition's text cut at limit characters, and True when characters were dropped
        - a text of exactly limit characters is whole and not truncated

    Raises:
        - ValueError if limit is below 1
    """
    if limit < 1: raise ValueError( f"body_chars must be 1 or more, got {limit}" )
    text = d[ "text" ]
    return text[ :limit ], len( text ) > limit


def engine_tag( client ):
    """
    Name the code engine that will embed, so another engine's vectors are never reused.

    Requires:
        - client has info() answering a body with engines.code

    Ensures:
        - returns 16 hex digits of the sha256 of the code engine's block, key order ignored
    """
    block = client.info()[ "engines" ][ CONTENT_TYPE ]
    return hashlib.sha256( json.dumps( block, sort_keys=True ).encode( "utf-8" ) ).hexdigest()[ :16 ]


def _read( folder, sha ):
    """
    Read one cached vector, or None when it is not cached.

    Requires:
        - folder is the cache folder of one engine
    """
    path = folder / f"{sha}.json"
    if not path.is_file(): return None
    return json.loads( path.read_text( encoding="utf-8" ) )


def _write( folder, sha, vector ):
    """
    Write one vector so a reader never sees half of it.

    Requires:
        - folder exists and vector is a list of floats

    Ensures:
        - the file appears under its final name only once it is complete
    """
    tmp = folder / f"{sha}.json.tmp"
    tmp.write_text( json.dumps( vector ), encoding="utf-8" )
    os.replace( tmp, folder / f"{sha}.json" )


def ensure_vectors( defs, client, cache_dir, body_chars, sleep=time.sleep ):
    """
    Embed the body text of every definition, reading from the cache what was embedded before.

    Requires:
        - defs are definition records; client has embed( texts, content_type, role ) and info()
        - cache_dir is the vectors folder under the run data; body_chars is the frozen cut

    Ensures:
        - returns { "vectors", "truncated", "embedded", "reused" }: a vector per definition id, the ids whose text was cut, and the
          counts of distinct texts embedded now and read from the cache
        - texts are embedded with the code engine and the document role, on both sides of a comparison
        - a text shared by several definitions is embedded once
        - a second call over the same texts and the same engine makes no embed call
        - vectors cached under another engine or revision are not used
        - every vector has the same length

    Raises:
        - ValueError if body_chars is below 1
        - CandidateError EMBEDDING_SHAPE if the vectors differ in length, cached ones included
    """
    folder = pathlib.Path( cache_dir ) / engine_tag( client )
    folder.mkdir( parents=True, exist_ok=True )
    texts, truncated, sha_of = {}, [], {}
    for d in defs:
        text, cut = body_text( d, body_chars )
        sha = vs.text_hash( text )
        texts[ sha ] = text
        sha_of[ d[ "id" ] ] = sha
        if cut: truncated.append( d[ "id" ] )
    found   = { sha: _read( folder, sha ) for sha in texts }
    missing = sorted( sha for sha, vector in found.items() if vector is None )
    if missing:
        fresh = vb.embed_all( client, [ texts[ sha ] for sha in missing ], CONTENT_TYPE, ROLE, vb.BATCH_SIZE, vb.PAUSE_SECONDS, sleep )
        for sha, vector in zip( missing, fresh ):
            found[ sha ] = [ float( x ) for x in vector ]
            _write( folder, sha, found[ sha ] )
    if len( { len( v ) for v in found.values() } ) > 1: raise CandidateError( EMBEDDING_SHAPE, "the cached and new vectors differ in length" )
    return { "vectors": { i: found[ sha ] for i, sha in sha_of.items() }, "truncated": truncated, "embedded": len( missing ), "reused": len( texts ) - len( missing ) }
