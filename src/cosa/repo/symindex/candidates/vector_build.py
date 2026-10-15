"""
Build the stored vector set by posting batches of text to the embeddings endpoints.

The build loads no model and makes no device choice: the GPU work runs in the server.
No function body is embedded. The text is the name, path, signature, docstring and purpose line.
"""
import pathlib
import time

from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, EMBEDDING_SHAPE, ENGINE_NOT_LOADED

BATCH_SIZE    = 64
PAUSE_SECONDS = 0.5
WARM_TEXT     = "warm up"


class EndpointClient:
    """
    The FastAPI embeddings endpoints, reached through the provider's own HTTP path.

    Every call passes pin_fastapi, so no environment variable or INI value reroutes it
    to the model server, which has no role field.
    """

    def __init__( self, provider=None, get=None ):
        """
        Hold the provider and the HTTP getter.

        Requires:
            - provider is an EmbeddingProvider, or None for the process singleton
            - get stands in for requests.get, or is None
        """
        self._provider = provider
        self._get      = get

    def embed( self, texts, content_type, role ):
        """
        Embed texts with one engine and one role.

        Ensures:
            - returns one vector per text, in order
        """
        if self._provider is None:
            from cosa.memory.embedding_provider import get_embedding_provider
            self._provider = get_embedding_provider()
        return self._provider.generate_embeddings_batch( texts, content_type=content_type, role=role, pin_fastapi=True )

    def info( self ):
        """
        Read GET /api/embeddings/info.

        Ensures:
            - returns the parsed body, with its engines block

        Raises:
            - RuntimeError when the key is missing or the answer is not 200
        """
        from cosa.memory.embedding_provider import EmbeddingProvider
        base_url, api_key, prefix = EmbeddingProvider._resolve_http_target( True )
        if not api_key: raise RuntimeError( "embeddings info: no API key found" )
        get = self._get
        if get is None:
            import requests
            get = requests.get
        response = get( f"{base_url}{prefix}/info", headers={ "X-API-Key": api_key }, timeout=30 )
        if response.status_code != 200:
            raise RuntimeError( f"embeddings info answered {response.status_code}: {response.text[ :200 ]}" )
        return response.json()


def entry_texts( entry, purpose ):
    """
    Build the text each matrix embeds for one entry.

    Requires:
        - entry is an index record with file, name, sig and doc
        - purpose is the stored purpose line, or "" when none is stored

    Ensures:
        - holds no function body: only name, path, signature, docstring and purpose
        - code text is the path, name and signature
        - prose text is the name, purpose and docstring
        - concat text is the code text followed by the prose text
    """
    code  = f"{entry[ 'file' ]}::{entry[ 'name' ]}{entry[ 'sig' ]}"
    prose = " ".join( p for p in ( entry[ "name" ] + ".", purpose, entry[ "doc" ] ) if p )
    return { "code": code, "prose": prose, "concat": code + "\n" + prose }


def _embed_all( client, texts, content_type, role, batch_size, pause_seconds, sleep ):
    """
    Embed every text in batches, one batch at a time, with a pause between batches.

    Ensures:
        - returns one vector per text, in order
        - every vector has the length of the first

    Raises:
        - CandidateError EMBEDDING_SHAPE when a batch returns the wrong count or a ragged row
    """
    vectors = []
    for i in range( 0, len( texts ), batch_size ):
        batch = texts[ i:i + batch_size ]
        out   = client.embed( batch, content_type, role )
        if len( out ) != len( batch ):
            raise CandidateError( EMBEDDING_SHAPE, f"asked for {len( batch )} vectors and got {len( out )}" )
        vectors.extend( out )
        if i + batch_size < len( texts ): sleep( pause_seconds )
    if len( { len( v ) for v in vectors } ) > 1: raise CandidateError( EMBEDDING_SHAPE, "the vectors differ in length" )
    return vectors


def reuse_mismatches( old_manifest, info ):
    """
    Name the clauses of the reuse guard that a live set fails.

    Requires:
        - old_manifest is the sealed manifest of the live set
        - info is the body of GET /api/embeddings/info, with its engines block

    Ensures:
        - returns [] only when the code engine, the prose engine, the device class, the libraries and the
          document roles in old_manifest equal the ones a build made now would record
        - otherwise returns the failing clause names: engines.code, engines.prose, device_class, libraries,
          document_roles
        - a manifest that lacks one of those fields, or holds one of the wrong shape, returns [ "manifest" ]
    """
    engines = info[ "engines" ]
    try:
        failed = [ f"engines.{kind}" for kind in ( "code", "prose" ) if old_manifest[ "engines" ][ kind ] != engines[ kind ] ]
        if old_manifest[ "device_class" ] != engines[ "device_class" ]: failed.append( "device_class" )
        if old_manifest[ "libraries" ] != engines[ "libraries" ]: failed.append( "libraries" )
        if { k: tuple( v ) for k, v in old_manifest[ "document_roles" ].items() } != vs.DOCUMENT_ROLES: failed.append( "document_roles" )
    except ( KeyError, TypeError, AttributeError ):
        return [ "manifest" ]
    return failed


def _matrix_rows( row_ids, texts, hashes, reusable, embed ):
    """
    Collect the rows of one matrix, embedding only the texts that are new.

    Requires:
        - row_ids, texts and hashes are in id order, one entry per row
        - reusable is { id: ( text hash, vector ) } from the live set, or an empty dict
        - embed takes a list of texts and returns one vector each, in order

    Ensures:
        - a row whose id and text hash both match the live set keeps the live vector
        - every other row is embedded, in one pass in id order
        - returns ( rows, embedded count )
    """
    rows, todo = [ None ] * len( texts ), []
    for n, ( row_id, h ) in enumerate( zip( row_ids, hashes ) ):
        old = reusable.get( row_id )
        if old is not None and old[ 0 ] == h: rows[ n ] = old[ 1 ]
        else: todo.append( n )
    if todo:
        for n, vector in zip( todo, embed( [ texts[ n ] for n in todo ] ) ): rows[ n ] = vector
    return rows, len( todo )


def build_vectors( entries, purposes, client, out_dir, batch_size=BATCH_SIZE, pause_seconds=PAUSE_SECONDS, sleep=time.sleep, reuse=None, stats=None ):
    """
    Embed every entry three ways and write a sealed set into out_dir.

    Requires:
        - entries is a non-empty list of index records with id, file, name, sig, doc and pin
        - purposes is { pin: row } from load_lines
        - client has embed( texts, content_type, role ) and info()
        - out_dir is a new, empty folder beside the live set
        - reuse is the live VectorSet loaded with its row texts, or None to embed everything
        - stats is a dict that gains, per matrix, the counts of reused and embedded rows, or None

    Ensures:
        - rows are in id order, one per entry, as float32
        - with reuse, a row is copied from the live set only when the guard passes and the row's id and text hash
          match; any guard mismatch embeds every row
        - the sidecar row_texts.jsonl is written and sealed, so the next build can reuse these rows
        - the engines are warmed once, then read from info, so the manifest records loaded revisions
        - document roles are the ones in vector_store.DOCUMENT_ROLES, and the manifest records them
        - returns the sealed manifest

    Raises:
        - CandidateError ENGINE_NOT_LOADED when a revision is still null after the warm-up
        - CandidateError EMBEDDING_SHAPE for a wrong count or a ragged row
    """
    import numpy as np
    rows  = sorted( { e[ "id" ]: e for e in entries }.values(), key=lambda e: e[ "id" ] )
    texts = { name: [] for name in vs.MATRICES }
    used  = set()
    for e in rows:
        row = purposes.get( e[ "pin" ] )
        if row is not None: used.add( ( row[ "prompt_hash" ], row[ "writer_version" ] ) )
        for name, text in entry_texts( e, row[ "purpose" ] if row is not None else "" ).items(): texts[ name ].append( text )
    client.embed( [ WARM_TEXT ], "code", "document" )
    client.embed( [ WARM_TEXT ], "prose", "document" )
    info = client.info()
    for kind in ( "code", "prose" ):
        if info[ "engines" ][ kind ][ "revision" ] is None:
            raise CandidateError( ENGINE_NOT_LOADED, f"the {kind} engine reports no revision after the warm-up" )
    out = pathlib.Path( out_dir )
    out.mkdir( parents=True, exist_ok=True )
    row_ids   = [ e[ "id" ] for e in rows ]
    hashes    = { name: [ vs.text_hash( t ) for t in texts[ name ] ] for name in vs.MATRICES }
    usable    = reuse is not None and reuse.row_texts is not None and not reuse_mismatches( reuse.manifest, info )
    dimension = None
    for name in vs.MATRICES:
        content_type, role = vs.DOCUMENT_ROLES[ name ]
        reusable = { i: ( reuse.row_texts[ name ][ k ], reuse.matrices[ name ][ k ] ) for k, i in enumerate( reuse.ids ) } if usable else {}
        embed    = lambda batch, ct=content_type, r=role: _embed_all( client, batch, ct, r, batch_size, pause_seconds, sleep )
        vectors, embedded = _matrix_rows( row_ids, texts[ name ], hashes[ name ], reusable, embed )
        if len( { len( v ) for v in vectors } ) > 1: raise CandidateError( EMBEDDING_SHAPE, f"{name} mixes reused and new vectors of different lengths" )
        if stats is not None: stats[ name ] = { "reused": len( rows ) - embedded, "embedded": embedded }
        matrix  = np.asarray( vectors, dtype="<f4" )
        if dimension is None: dimension = matrix.shape[ 1 ]
        if matrix.shape[ 1 ] != dimension: raise CandidateError( EMBEDDING_SHAPE, f"{name} has {matrix.shape[ 1 ]} columns, expected {dimension}" )
        matrix.tofile( out / vs.MATRIX_FILES[ name ] )
    manifest = {
        "engines"        : { "code": info[ "engines" ][ "code" ], "prose": info[ "engines" ][ "prose" ] },
        "device_class"   : info[ "engines" ][ "device_class" ],
        "libraries"      : info[ "engines" ][ "libraries" ],
        "dimension"      : dimension,
        "rows"           : len( rows ),
        "document_roles" : { k: list( v ) for k, v in vs.DOCUMENT_ROLES.items() },
        "query_roles"    : { k: list( v ) for k, v in vs.QUERY_ROLES.items() },
        "purpose_writers": [ { "prompt_hash": p, "writer_version": w } for p, w in sorted( used ) ]
    }
    vs.write_row_texts( out, row_ids, hashes )
    return vs.seal( out, row_ids, manifest )
