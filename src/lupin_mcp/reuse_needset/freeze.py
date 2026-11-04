"""
Freeze the index and vector set a need set was drawn against.

The answer keys name symbols of one index at one commit. A scoring run on a rebuilt index or a refreshed vector set
would blame the checker for what the data changed. So the manifest records three hashes, and each arm checks them
before it makes a call.
"""
import json
import os
import pathlib
import shutil

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates import freshness as fr
from cosa.repo.symindex.candidates import vector_store as vs
from lupin_mcp.reuse_needset import errors as er

IDENTITY_KEYS = ( "index_manifest", "symbols_sha", "vector_build_info_sha" )
FROZEN_DIR    = "frozen"
INDEX_SUBDIR  = "index"
VECTOR_SUBDIR = "vectors"
IDENTITY_FILE = "needset-frozen.json"


def identity( index_gen, vectors_dir ):
    """
    Name the index generation and the vector set a run reads.

    Requires:
        - index_gen is an index generation folder holding header.json
        - vectors_dir is a vector set folder holding build-info.json

    Ensures:
        - returns { index_manifest, symbols_sha, vector_build_info_sha }, three hex strings
        - index_manifest and symbols_sha come from the generation's header, the third is the sha256 of the build-info file's bytes
        - the vector set must have been built from this generation, so a set built from another index is refused

    Raises:
        - NeedsetError FREEZE_INCOMPLETE when the header or the build info is missing or unreadable
        - NeedsetError VECTORS_NOT_FROM_INDEX when the build info names another index manifest
    """
    try:
        header = sx_build.read_header( index_gen )
        manifest, symbols = fr.index_manifest( header ), header[ "symbols_sha" ]
    except ( OSError, ValueError, KeyError ) as e:
        raise er.NeedsetError( er.FREEZE_INCOMPLETE, f"no readable index header in {index_gen}: {type( e ).__name__}" )
    info = fr.read_build_info( vectors_dir )
    if info is None: raise er.NeedsetError( er.FREEZE_INCOMPLETE, f"no readable {fr.BUILD_INFO_FILE} in {vectors_dir}" )
    if info[ "index_manifest" ] != manifest:
        raise er.NeedsetError( er.VECTORS_NOT_FROM_INDEX, f"the vector set was built from index {info[ 'index_manifest' ][ :12 ]}, the index is {manifest[ :12 ]}" )
    return { "index_manifest": manifest, "symbols_sha": symbols, "vector_build_info_sha": vs.file_sha256( pathlib.Path( vectors_dir ) / fr.BUILD_INFO_FILE ) }


def _read_only( folder ):
    """Ensures: every file under folder is mode 0444 and every folder, itself included, 0555."""
    for root, dirs, files in os.walk( folder ):
        for f in files: os.chmod( os.path.join( root, f ), 0o444 )
    for root, dirs, files in os.walk( folder, topdown=False ):
        os.chmod( root, 0o555 )


def freeze( index_gen, vectors_dir, dest ):
    """
    Copy the index generation and the vector set into a read-only folder.

    Requires:
        - index_gen and vectors_dir are as for identity
        - dest is a folder that does not exist yet, or one this function froze from the same hashes

    Ensures:
        - writes dest/index, dest/vectors and dest/needset-frozen.json, all read-only
        - returns the identity, read back from the copies and equal to the source's
        - a second call over the same source returns the identity and changes nothing

    Raises:
        - NeedsetError FREEZE_INCOMPLETE and VECTORS_NOT_FROM_INDEX from identity
        - NeedsetError FROZEN_COPY_EXISTS when dest holds a copy of other hashes, or a folder that is not a frozen copy
    """
    dest = pathlib.Path( dest )
    want = identity( index_gen, vectors_dir )
    if dest.exists():
        try:
            held = identity( dest / INDEX_SUBDIR, dest / VECTOR_SUBDIR )
        except er.NeedsetError as e:
            raise er.NeedsetError( er.FROZEN_COPY_EXISTS, f"{dest} exists and is not a frozen copy: {e.code}" )
        if held != want: raise er.NeedsetError( er.FROZEN_COPY_EXISTS, f"{dest} holds a copy of other hashes: {sorted( k for k in want if held[ k ] != want[ k ] )}" )
        return held
    dest.mkdir( parents=True )
    shutil.copytree( index_gen, dest / INDEX_SUBDIR )
    shutil.copytree( vectors_dir, dest / VECTOR_SUBDIR )
    got = identity( dest / INDEX_SUBDIR, dest / VECTOR_SUBDIR )
    if got != want: raise er.NeedsetError( er.FROZEN_COPY_EXISTS, f"the copy in {dest} differs from its source: {sorted( k for k in want if got[ k ] != want[ k ] )}" )
    ( dest / IDENTITY_FILE ).write_text( json.dumps( got, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    _read_only( dest )
    return got


def require_same( manifest, live, arm ):
    """
    Refuse a run whose index or vectors differ from the frozen ones.

    Requires:
        - manifest is a need set manifest holding the three identity keys
        - live is identity() of what the arm is about to read
        - arm names the caller, for the message

    Ensures:
        - returns None when all three hashes are equal

    Raises:
        - NeedsetError FREEZE_INCOMPLETE when the manifest lacks a key
        - NeedsetError INDEX_DIFFERS when index_manifest or symbols_sha differs
        - NeedsetError VECTORS_DIFFER when the vector build-info hash differs
    """
    absent = [ k for k in IDENTITY_KEYS if not isinstance( manifest.get( k ), str ) or not manifest[ k ] ]
    if absent: raise er.NeedsetError( er.FREEZE_INCOMPLETE, f"{arm}: the manifest records no {absent}" )
    for code, keys in ( ( er.INDEX_DIFFERS, IDENTITY_KEYS[ :2 ] ), ( er.VECTORS_DIFFER, IDENTITY_KEYS[ 2: ] ) ):
        off = [ k for k in keys if live[ k ] != manifest[ k ] ]
        if off: raise er.NeedsetError( code, f"{arm}: {off} differ from the frozen set; the manifest has {[ manifest[ k ][ :12 ] for k in off ]}, this run reads {[ live[ k ][ :12 ] for k in off ]}" )
