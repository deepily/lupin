"""
The stored vector set: three float32 matrices, their row ids and a manifest.

There is one set, the current state of the repo. A rebuild writes a new folder beside the live
one and swaps the two by rename. A lookup that finds no set, or a set whose hashes do not match
its manifest, gets a named error and never a recomputed answer.
"""
import hashlib
import json
import os
import pathlib
import shutil

from cosa.repo.symindex.candidates.errors import (
    CandidateError, DEPENDENCY_MISSING, ENGINE_MISMATCH, ENGINE_NOT_LOADED, VECTOR_SET_UNAVAILABLE, VECTOR_SET_CORRUPT )

MATRICES       = ( "prose", "code", "concat" )
MATRIX_FILES   = { "prose": "prose.f32", "code": "code.f32", "concat": "concat.f32" }
IDS_FILE       = "ids.txt"
MANIFEST_FILE  = "manifest.json"
DOCUMENT_ROLES = { "prose": ( "prose", "document" ), "code": ( "code", "document" ), "concat": ( "prose", "document" ) }
QUERY_ROLES    = { "prose": ( "prose", "query" ),    "code": ( "code", "query" ),    "concat": ( "prose", "query" ) }
ENGINE_FIELDS  = ( "model", "revision", "dtype", "device", "query_prefix", "document_prefix", "dimensions" )


def canonical( obj ):
    """
    Serialise an object the same way every time.

    Ensures:
        - returns JSON with sorted keys and no spaces after separators
    """
    return json.dumps( obj, sort_keys=True, separators=( ",", ":" ), ensure_ascii=True )


def file_sha256( path ):
    """
    Hash a file in chunks.

    Ensures:
        - returns the hex sha256 of the file's bytes
    """
    h = hashlib.sha256()
    with open( path, "rb" ) as f:
        for chunk in iter( lambda: f.read( 1 << 20 ), b"" ): h.update( chunk )
    return h.hexdigest()


def manifest_hash( manifest ):
    """
    Return the hash that names a vector set.

    Requires:
        - manifest is a mapping

    Ensures:
        - ignores a stored manifest_hash key, so a sealed manifest hashes to its own value
        - changes when any other field changes, including a file hash
    """
    body = { k: v for k, v in manifest.items() if k != "manifest_hash" }
    return hashlib.sha256( canonical( body ).encode( "utf-8" ) ).hexdigest()


def seal( out_dir, ids, manifest ):
    """
    Write the ids file and the sealed manifest into a new set folder.

    Requires:
        - out_dir holds the three matrix files
        - ids is the sorted list of entry ids, one per matrix row
        - manifest is the manifest without file hashes or manifest_hash

    Ensures:
        - ids.txt is written, one id per line
        - manifest.json holds the manifest with the hash of every file and its own manifest_hash
        - returns the sealed manifest
    """
    out = pathlib.Path( out_dir )
    ( out / IDS_FILE ).write_text( "\n".join( ids ) + "\n", encoding="utf-8" )
    sealed          = dict( manifest )
    sealed[ "files" ] = { name: file_sha256( out / name ) for name in sorted( [ IDS_FILE ] + list( MATRIX_FILES.values() ) ) }
    sealed[ "manifest_hash" ] = manifest_hash( sealed )
    ( out / MANIFEST_FILE ).write_text( json.dumps( sealed, indent=2, sort_keys=True ) + "\n", encoding="utf-8" )
    return sealed


def swap_in( new_dir, live_dir ):
    """
    Make new_dir the live set with two renames.

    Requires:
        - new_dir is a complete, sealed set on the same filesystem as live_dir

    Ensures:
        - the live folder is renamed aside, new_dir is renamed to the live name, then the old set is removed
        - a lookup between the two renames finds no set, and never a half-written one
        - when the second rename fails, the old set is renamed back and the error is raised
    """
    new, live = pathlib.Path( new_dir ), pathlib.Path( live_dir )
    aside     = live.with_name( live.name + ".old" )
    if aside.exists(): shutil.rmtree( aside )
    had_live = live.exists()
    if had_live: os.rename( live, aside )
    try:
        os.rename( new, live )
    except OSError:
        if had_live: os.rename( aside, live )
        raise
    if had_live: shutil.rmtree( aside )


class VectorSet:
    """A loaded vector set: the manifest, the row ids and a memory map per matrix."""

    def __init__( self, manifest, ids, matrices ):
        """
        Hold a checked set.

        Requires:
            - matrices maps each matrix name to a numpy array of shape ( len( ids ), dimension )
        """
        self.manifest      = manifest
        self.ids           = ids
        self.matrices      = matrices
        self.manifest_hash = manifest[ "manifest_hash" ]


def load_vectors( live_dir ):
    """
    Read and check the live vector set.

    Requires:
        - live_dir is the vectors folder named by the INI key

    Ensures:
        - returns a VectorSet whose manifest hash and every file hash were recomputed and matched
        - the matrices are memory maps of float32 rows, one per id, in id order

    Raises:
        - CandidateError VECTOR_SET_UNAVAILABLE when there is no manifest
        - CandidateError VECTOR_SET_CORRUPT when a hash or a size disagrees with the manifest
        - CandidateError DEPENDENCY_MISSING when numpy is not importable here
    """
    live = pathlib.Path( live_dir )
    path = live / MANIFEST_FILE
    if not path.is_file(): raise CandidateError( VECTOR_SET_UNAVAILABLE, f"no manifest in {live}" )
    try:
        import numpy as np
    except ImportError as e:
        raise CandidateError( DEPENDENCY_MISSING, f"numpy is not importable in this process: {e}" )
    manifest = json.loads( path.read_text( encoding="utf-8" ) )
    if manifest_hash( manifest ) != manifest[ "manifest_hash" ]:
        raise CandidateError( VECTOR_SET_CORRUPT, "the manifest does not hash to its manifest_hash" )
    for name, expected in manifest[ "files" ].items():
        if not ( live / name ).is_file() or file_sha256( live / name ) != expected:
            raise CandidateError( VECTOR_SET_CORRUPT, f"{name} does not match the manifest" )
    ids = ( live / IDS_FILE ).read_text( encoding="utf-8" ).splitlines()
    dim = manifest[ "dimension" ]
    matrices = {}
    for name in MATRICES:
        m = np.memmap( live / MATRIX_FILES[ name ], dtype="<f4", mode="r" )
        if m.size != len( ids ) * dim:
            raise CandidateError( VECTOR_SET_CORRUPT, f"{MATRIX_FILES[ name ]} holds {m.size} values, expected {len( ids )} x {dim}" )
        matrices[ name ] = m.reshape( len( ids ), dim )
    return VectorSet( manifest, ids, matrices )


def check_engines( manifest, info ):
    """
    Compare the engines a set was built with against what the server reports now.

    Requires:
        - manifest holds engines, document_roles and query_roles as the build wrote them
        - info is the body of GET /api/embeddings/info, with its engines block

    Ensures:
        - returns None when model, revision, dtype, device, device class, prefixes, dimensions and roles all agree

    Raises:
        - CandidateError ENGINE_NOT_LOADED when the server reports no revision for an engine
        - CandidateError ENGINE_MISMATCH naming every field that differs
    """
    engines = info[ "engines" ]
    for kind in ( "code", "prose" ):
        if engines[ kind ][ "revision" ] is None:
            raise CandidateError( ENGINE_NOT_LOADED, f"the {kind} engine reports no revision, so it is not loaded" )
    differs = []
    for kind in ( "code", "prose" ):
        for field in ENGINE_FIELDS:
            if manifest[ "engines" ][ kind ][ field ] != engines[ kind ][ field ]:
                differs.append( f"{kind}.{field}: built {manifest[ 'engines' ][ kind ][ field ]!r}, server {engines[ kind ][ field ]!r}" )
    if manifest[ "device_class" ] != engines[ "device_class" ]:
        differs.append( f"device_class: built {manifest[ 'device_class' ]!r}, server {engines[ 'device_class' ]!r}" )
    for key, expected in ( ( "document_roles", DOCUMENT_ROLES ), ( "query_roles", QUERY_ROLES ) ):
        if { k: tuple( v ) for k, v in manifest[ key ].items() } != expected:
            differs.append( f"{key}: the manifest holds {manifest[ key ]!r}" )
    if differs: raise CandidateError( ENGINE_MISMATCH, "; ".join( differs ) )


def query_key( redacted_need ):
    """
    Name the cache file of one redacted need.

    Ensures:
        - returns the hex sha256 of the text, which is the file's stem
    """
    return hashlib.sha256( redacted_need.encode( "utf-8" ) ).hexdigest()


def query_vectors( redacted_need, client, cache_dir, manifest ):
    """
    Return the three query vectors of a need, from the cache or from the server.

    Requires:
        - redacted_need is the need after redaction
        - client has embed( texts, content_type, role ) and info()
        - manifest is the sealed manifest of the live set

    Ensures:
        - a cache file made under this manifest hash is returned without any call
        - a file made under another hash, or one that cannot be read, is a miss
        - on a miss the engines are checked against the manifest first, then each distinct
          ( content type, role ) pair is embedded once with the roles the manifest records
        - the result is written to the cache and returned as { prose, code, concat }

    Raises:
        - CandidateError ENGINE_MISMATCH or ENGINE_NOT_LOADED from check_engines
    """
    cache = pathlib.Path( cache_dir )
    path  = cache / f"{query_key( redacted_need )}.json"
    if path.is_file():
        try:
            stored = json.loads( path.read_text( encoding="utf-8" ) )
            if stored[ "manifest_hash" ] == manifest[ "manifest_hash" ]: return stored[ "vectors" ]
        except ( ValueError, KeyError ):
            pass                                                         # an unreadable cache file is a miss
    check_engines( manifest, client.info() )
    by_pair, vectors = {}, {}
    for name in MATRICES:
        pair = tuple( manifest[ "query_roles" ][ name ] )
        if pair not in by_pair: by_pair[ pair ] = client.embed( [ redacted_need ], pair[ 0 ], pair[ 1 ] )[ 0 ]
        vectors[ name ] = by_pair[ pair ]
    cache.mkdir( parents=True, exist_ok=True )
    tmp = path.with_suffix( ".json.tmp" )
    tmp.write_text( json.dumps( { "manifest_hash": manifest[ "manifest_hash" ], "vectors": vectors } ), encoding="utf-8" )
    os.replace( tmp, path )
    return vectors


def clear_stale_queries( cache_dir, current_hash ):
    """
    Remove cached query vectors made under another vector set.

    Requires:
        - current_hash is the manifest hash of the live set

    Ensures:
        - deletes each cache file whose manifest_hash differs, and any file that cannot be read
        - returns the number of files removed
        - a missing folder removes nothing
    """
    cache = pathlib.Path( cache_dir )
    if not cache.is_dir(): return 0
    removed = 0
    for path in sorted( cache.glob( "*.json" ) ):
        try:
            keep = json.loads( path.read_text( encoding="utf-8" ) )[ "manifest_hash" ] == current_hash
        except ( ValueError, KeyError ):
            keep = False
        if not keep: path.unlink(); removed += 1
    return removed
