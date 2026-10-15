"""
Candidate search router: the resident search of the reuse-lookup candidate stage.

    PUT  /api/reuse-candidates/stage    hold the entries of one index under a key
    POST /api/reuse-candidates/search   rank a need against a held stage and the stored vectors

The caller uploads the index entries once, then searches by key.
This process builds the BM25 indexes once and keeps the matrices memory-mapped between lookups.
A vectors folder must sit under the reuse-review data directory of this server.
A named failure answers { error, detail }. The status says what to do next:
upload again (409), fix the request (422), or stop (403, 503).
"""
import threading
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cosa.repo.symindex.candidates import errors as ce
from cosa.repo.symindex.candidates.errors import CandidateError
from cosa.repo.symindex.candidates.resident import ResidentSearch
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

router = APIRouter( prefix="/api/reuse-candidates", tags=[ "reuse-candidates" ] )

STATUS_OF = { ce.BAD_STAGE_UPLOAD: 422, "BAD_SEARCH_REQUEST": 422, ce.STAGE_UNKNOWN: 409, ce.VECTOR_SET_REPLACED: 409, ce.PATH_REFUSED: 403 }
SERVICE_UNAVAILABLE = 503

_held = { "search": None }
_make = threading.Lock()


class StageUpload( BaseModel ):
    """The entries of one index, its purpose lines and fusion constants, under the caller's key."""

    key      : str
    entries  : List[ Dict[ str, Any ] ]
    purposes : Optional[ Dict[ str, str ] ] = None
    fusion   : Optional[ Dict[ str, int ] ] = None


def data_root():
    """
    Name the folder a vectors folder must sit under.

    Ensures:
        - returns the reuse-review data directory of this server's repository, as a string
    """
    import cosa.utils.util as du
    from cosa.repo.symindex.paths import data_dir
    return str( data_dir( du.get_project_root() ) )


def resident():
    """
    Return the one resident search of this process, made on first use.

    Ensures:
        - the same object on every call, so held stages and vector sets are shared across requests
    """
    with _make:
        if _held[ "search" ] is None: _held[ "search" ] = ResidentSearch( data_root() )
        return _held[ "search" ]


def failure( error ):
    """
    Turn a candidate error into its response.

    Ensures:
        - the body is { error, detail } with the error's code
        - the status is the one STATUS_OF names, and 503 for any other code
    """
    return JSONResponse( status_code=STATUS_OF.get( error.code, SERVICE_UNAVAILABLE ), content={ "error": error.code, "detail": error.detail } )


@router.put( "/stage", summary="Hold a stage", description="Build the BM25 indexes for uploaded entries and hold them under a key." )
def put_stage( upload: StageUpload, authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ] = None ):
    """
    Hold one stage.

    Ensures:
        - answers { key, entries } when the stage is held, or the named error of the upload
    """
    try:
        return resident().put_stage( upload.key, upload.entries, upload.purposes, upload.fusion )
    except CandidateError as e:
        return failure( e )


@router.post( "/search", summary="Search a held stage", description="Rank a need against a held stage and the stored vectors, and return the shortlist." )
def search( request: Dict[ str, Any ], authenticated_user_id: Annotated[ str, Depends( require_api_key_or_jwt ) ] = None ):
    """
    Run one search.

    Ensures:
        - answers the shortlist body of the search process, or the named error of the search
    """
    try:
        return resident().search( request )
    except CandidateError as e:
        return failure( e )
