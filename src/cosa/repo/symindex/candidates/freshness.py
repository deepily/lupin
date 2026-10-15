"""
What a vector set remembers about its index, and the lock that keeps two builds apart.

The build info is a side file inside the set's folder. It is not one of the hashed files and not part of
the manifest, so a new time stamp never changes a set's manifest hash. It travels with the set
through the rename swap. A reader never sees one build's set with another build's info.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import pathlib

from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, BUILD_LOCK_HELD

BUILD_INFO_FILE = "build-info.json"
LOCK_FILE       = "vector-build.lock"


def index_manifest( header ):
    """
    Name the index generation a set is built from.

    Requires:
        - header is the parsed header.json of an index generation, with its manifest

    Ensures:
        - returns the hex sha256 of the canonical JSON of the header's manifest
        - two generations of the same tree state give the same value
    """
    return hashlib.sha256( vs.canonical( header[ "manifest" ] ).encode( "utf-8" ) ).hexdigest()


def utc_now():
    """
    Return the current time as an ISO string in UTC, to the second.

    Ensures:
        - the string ends with +00:00
    """
    return datetime.datetime.now( datetime.timezone.utc ).isoformat( timespec="seconds" )


def write_build_info( set_dir, header, built_at ):
    """
    Write the build info beside the files of a new set.

    Requires:
        - set_dir is the new set's folder, before the swap
        - header is the index header the set's entries were read from
        - built_at is an ISO time string

    Ensures:
        - writes index_manifest, symbols_sha and built_at to build-info.json
        - returns the dict written
    """
    info = { "index_manifest": index_manifest( header ), "symbols_sha": header[ "symbols_sha" ], "built_at": built_at }
    ( pathlib.Path( set_dir ) / BUILD_INFO_FILE ).write_text( json.dumps( info, indent=2, sort_keys=True ) + "\n", encoding="utf-8" )
    return info


def read_build_info( live_dir ):
    """
    Read the build info of a set.

    Ensures:
        - returns the dict in the file
        - returns None when the file is absent, unreadable, not a JSON object, or lacks index_manifest or built_at
          so a set made before this file existed reads as unknown, never as fresh
    """
    try:
        info = json.loads( ( pathlib.Path( live_dir ) / BUILD_INFO_FILE ).read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ):
        return None
    if not isinstance( info, dict ) or "index_manifest" not in info or "built_at" not in info: return None
    return info


def read_manifest( live_dir ):
    """
    Read a set's manifest without hashing its matrices.

    Ensures:
        - returns the parsed manifest.json
        - returns None when it is absent, unreadable, or not a JSON object
    """
    try:
        manifest = json.loads( ( pathlib.Path( live_dir ) / vs.MANIFEST_FILE ).read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ):
        return None
    return manifest if isinstance( manifest, dict ) else None


@contextlib.contextmanager
def refresh_lock( path ):
    """
    Hold the build lock for the length of one build.

    Requires:
        - path is the lock file, in the data folder

    Ensures:
        - one holder at a time across processes; the operating system drops the lock when its process ends,
          so a build that was killed leaves no stale lock
        - the folder is created when missing

    Raises:
        - CandidateError BUILD_LOCK_HELD when another build holds the lock
    """
    os.makedirs( os.path.dirname( os.path.abspath( path ) ), exist_ok=True )
    handle = open( path, "a" )
    try:
        try:
            fcntl.flock( handle, fcntl.LOCK_EX | fcntl.LOCK_NB )
        except BlockingIOError:
            raise CandidateError( BUILD_LOCK_HELD, f"another build holds {path}" )
        yield
    finally:
        handle.close()
