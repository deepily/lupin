"""
The phone's door to the podcasts published to the owner's Google Drive.

GET /api/podcast-drive/list lists the job folders in the configured Drive folder. GET
/api/podcast-drive/stream/{drive_file_id} streams one file, honouring HTTP Range so the phone can seek.
Both use the desktop Drive token, so the phone needs no Google sign-in.

Security: a Lupin login is required, and only the user named by `podcast drive owner email` gets in,
because the token reaches one person's Drive. The stream serves only files inside a job folder directly
under the configured folder, never an arbitrary file id.
"""

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from cosa.agents.podcast_generator.drive_hook import _make_publisher
from cosa.agents.podcast_generator.play_links import title_from_folder_name, title_from_script_text
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.auth import get_current_user
from cosa.rest.dependencies.config import get_config_manager
from cosa.utils.drive_publisher import DrivePublishError

router = APIRouter( prefix="/api/podcast-drive", tags=[ "podcast-drive" ] )

OWNER_KEY              = "podcast drive owner email"
FOLDER_KEY             = "podcast drive folder name"
TOKEN_KEY              = "podcast drive token path"
DEFAULT_FOLDER         = "Lupin Podcasts"
DEFAULT_TOKEN_PATH     = "/src/conf/keys/google-drive-oauth-token.json"
STREAM_PATH_TEMPLATE   = "/api/podcast-drive/stream/{file_id}"
LIST_LIMIT             = 50
STREAM_CHUNK_BYTES     = 64 * 1024
SCRIPT_HEAD_BYTES      = 4096
PASSED_THROUGH_HEADERS = ( "Content-Range", "Content-Length", "Accept-Ranges" )


def _owner_publisher( current_user, config_mgr ):
    """
    Check the caller owns the Drive token, then build the publisher.

    Requires:
        - current_user is the authenticated user dict with an "email" key
        - config_mgr is the ConfigurationManager

    Ensures:
        - returns the DrivePublisher for the caller who is the configured owner

    Raises:
        - HTTPException 403 when the owner email is unset or is not the caller's, before any Drive call
        - HTTPException 503 when the Drive token is missing or unusable
    """
    owner = config_mgr.get( OWNER_KEY, default="", silent=True ).strip().lower()
    if not owner or current_user.get( "email", "" ).strip().lower() != owner:
        raise HTTPException( status_code=403, detail="Only the owner of the Drive token may use the podcast Drive" )
    drive_ini = SimpleNamespace(
        drive_folder_name = config_mgr.get( FOLDER_KEY, default=DEFAULT_FOLDER, silent=True ),
        drive_token_path  = config_mgr.get( TOKEN_KEY,  default=DEFAULT_TOKEN_PATH, silent=True ),
    )
    try:
        return _make_publisher( drive_ini )
    except DrivePublishError as e:
        raise HTTPException( status_code=503, detail=f"Drive unavailable: {e}" )


def _title_for( publisher, folder, files ):
    """
    Pick a job's plain title from its script, else from its folder name.

    The script's first heading wins when the folder holds a `-script.md`.

    Requires:
        - folder is { "name", ... }; files are the folder's file dicts

    Ensures:
        - returns a non-empty string; a script that cannot be read falls back to the folder name

    Raises:
        - nothing
    """
    for file in files:
        if file[ "name" ].endswith( "-script.md" ):
            try:
                title = title_from_script_text( publisher.read_head( file[ "id" ], SCRIPT_HEAD_BYTES ).decode( "utf-8", errors="replace" ) )
            except DrivePublishError:
                title = None
            if title: return title
    return title_from_folder_name( folder[ "name" ] )


@router.get( "/list", summary="List podcasts in the owner's Drive folder, newest first" )
def list_podcasts(
    current_user : dict                 = Depends( get_current_user ),
    config_mgr   : ConfigurationManager = Depends( get_config_manager ),
):
    """
    List the job folders in the configured Drive folder with their files.

    Requires:
        - the caller is logged in and is the configured Drive owner

    Ensures:
        - returns [ { job_folder, title, created_ts, files: [ { name, mime, size, drive_file_id, stream_url } ] } ], newest first
        - a Drive folder that does not exist yet gives an empty list

    Raises:
        - HTTPException 403 for any other user, 503 when Drive cannot be reached
    """
    publisher = _owner_publisher( current_user, config_mgr )
    try:
        top_id = publisher.find_top_folder()
        if top_id is None: return []
        result = []
        for folder in publisher.list_job_folders( top_id, LIST_LIMIT ):
            files = publisher.list_folder_files( folder[ "id" ] )
            result.append( {
                "job_folder" : folder[ "name" ],
                "title"      : _title_for( publisher, folder, files ),
                "created_ts" : folder.get( "createdTime" ),
                "files"      : [ {
                    "name"          : f[ "name" ],
                    "mime"          : f[ "mimeType" ],
                    "size"          : int( f[ "size" ] ) if "size" in f else None,
                    "drive_file_id" : f[ "id" ],
                    "stream_url"    : STREAM_PATH_TEMPLATE.format( file_id=f[ "id" ] ),
                } for f in files ],
            } )
        return result
    except DrivePublishError as e:
        raise HTTPException( status_code=503, detail=f"Drive unavailable: {e}" )


@router.get( "/stream/{drive_file_id}", summary="Stream one Drive podcast file, with Range support" )
def stream_podcast_file(
    drive_file_id : str,
    request       : Request,
    current_user  : dict                 = Depends( get_current_user ),
    config_mgr    : ConfigurationManager = Depends( get_config_manager ),
):
    """
    Stream a file from a job folder in the configured Drive folder.

    Requires:
        - the caller is logged in and is the configured Drive owner
        - drive_file_id names a file in a job folder directly under the configured folder

    Ensures:
        - the browser's Range header goes to Drive and Drive's answer (200, 206 or 416) comes back with
          Content-Range, Content-Length and Accept-Ranges passed through
        - the body is streamed in chunks, never held whole in memory

    Raises:
        - HTTPException 403 for any other user, 404 for any file outside the folder, 503 when Drive cannot be reached
    """
    publisher = _owner_publisher( current_user, config_mgr )
    try:
        top_id = publisher.find_top_folder()
        meta   = publisher.file_inside_top_folder( drive_file_id, top_id ) if top_id is not None else None
        if meta is None: raise HTTPException( status_code=404, detail="No such podcast file" )
        upstream = publisher.open_media( drive_file_id, request.headers.get( "range" ) )
    except DrivePublishError as e:
        raise HTTPException( status_code=503, detail=f"Drive unavailable: {e}" )

    headers = { name: upstream.headers[ name ] for name in PASSED_THROUGH_HEADERS if name in upstream.headers }
    headers.setdefault( "Accept-Ranges", "bytes" )
    return StreamingResponse(
        upstream.iter_content( chunk_size=STREAM_CHUNK_BYTES ),
        status_code = upstream.status_code,
        media_type  = meta[ "mimeType" ],
        headers     = headers,
        background  = BackgroundTask( upstream.close ),
    )
