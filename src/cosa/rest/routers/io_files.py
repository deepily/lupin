"""
Generic file serving endpoint for files in the io/ directory.

Provides a unified endpoint for serving:
- Deep research reports (markdown)
- Podcast scripts (markdown)
- Podcast audio files (mp3)
- Other io/ files (pdf, etc.)

Security:
- Path validation prevents directory traversal
- Only serves files within io/ directory
- Validates file extension against content type

Generated on: 2026-01-20
"""

import os
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

import cosa.utils.util as cu
from cosa.rest.auth import get_current_user
from cosa.rest.routers._dir_listing import list_directory
from cosa.rest.routers._scope_registry import _is_secrets_path

router = APIRouter( tags=[ "io-files" ] )


# Content type mapping by file extension
MEDIA_TYPES = {
    ".md"   : "text/markdown; charset=utf-8",
    ".txt"  : "text/plain; charset=utf-8",
    ".yaml" : "text/yaml; charset=utf-8",
    ".yml"  : "text/yaml; charset=utf-8",
    ".mp3"  : "audio/mpeg",
    ".wav"  : "audio/wav",
    ".pdf"  : "application/pdf",
    ".json" : "application/json",
    ".pptx" : "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png"  : "image/png",
    ".jpg"  : "image/jpeg",
    ".jpeg" : "image/jpeg",
    ".gif"  : "image/gif",
    ".webp" : "image/webp",
}

# Types the browser can render/play inline (browser-native viewers exist).
# These get `Content-Disposition: inline`; everything else defaults to attachment.
# `?download=true` always overrides to attachment regardless of type.
# NOTE: .svg intentionally excluded — SVG can carry script and is a separate decision.
INLINE_TYPES = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".mp3", ".wav",
}


@router.get(
    "/api/io/file",
    summary     = "Serve IO file",
    description = "Serve files from the io/ directory with extension validation and traversal protection."
)
async def get_io_file(
    path        : str  = Query( ..., description="Relative path within io/ directory" ),
    download    : bool = Query( False, description="Force download with Content-Disposition: attachment" ),
    current_user: dict = Depends( get_current_user ),
):
    """
    Serve files from the io/ directory with security validation.

    Supports serving:
    - Markdown files (.md) - research reports, podcast scripts
    - Audio files (.mp3, .wav) - podcast audio
    - Documents (.pdf, .txt, .json)

    Requires:
        - path is a relative path within io/ directory
        - File must exist
        - File extension must be in allowed list

    Ensures:
        - Returns file with appropriate content type
        - Prevents directory traversal attacks
        - Returns 400 for invalid/unsafe paths
        - Returns 404 for missing files

    Args:
        path: Relative path within io/ directory (URL-decoded automatically)

    Returns:
        FileResponse or PlainTextResponse depending on file type

    Raises:
        HTTPException 400: Invalid or unsafe path
        HTTPException 404: File not found
    """
    # Decode the path (FastAPI does this, but be explicit)
    decoded_path = unquote( path )

    # Get project root and io base
    project_root = cu.get_project_root()
    io_base = project_root + "/io"

    # Strip absolute io_base prefix if present (legacy artifact paths from older jobs)
    io_base_slash = io_base + "/"
    if decoded_path.startswith( io_base_slash ):
        decoded_path = decoded_path[ len( io_base_slash ): ]
    elif decoded_path.startswith( "/" ):
        decoded_path = decoded_path.lstrip( "/" )
    # Strip relative "io/" prefix — reports commonly embed paths like
    # "io/test-suite/foo.json", which would otherwise double to "io/io/..."
    # after joining with io_base.
    if decoded_path.startswith( "io/" ):
        decoded_path = decoded_path[ 3: ]

    full_path = os.path.join( io_base, decoded_path )

    # Normalize to prevent directory traversal (../ attacks)
    full_path = os.path.normpath( full_path )

    # Security: ensure resolved path is within io/ directory
    if not full_path.startswith( io_base ):
        raise HTTPException(
            status_code = 400,
            detail      = "Invalid path: must be within io/ directory"
        )

    # Secrets blocklist — applies even to io/ paths (defense-in-depth).
    # Filename-pattern match; runs after traversal block.
    if _is_secrets_path( decoded_path ):
        raise HTTPException(
            status_code = 400,
            detail      = "Path matches secrets blocklist"
        )

    # Directory branch (polymorphic response) — must come before isfile check
    if os.path.isdir( full_path ):
        # Compute relative-to-io path (the path callers expect for io scope)
        rel_to_io = os.path.relpath( full_path, io_base )
        if rel_to_io == ".":
            rel_to_io = ""  # at io root
        listing = list_directory(
            abs_dir          = full_path,
            rel_dir          = rel_to_io,
            scope            = "io",
            allowed_exts     = set( MEDIA_TYPES.keys() ),
            parent_validator = lambda p: bool( p ),
        )
        return JSONResponse( content=listing )

    # Check if file exists
    if not os.path.isfile( full_path ):
        raise HTTPException(
            status_code = 404,
            detail      = f"File not found: {decoded_path}"
        )

    # Determine content type from extension
    _, ext = os.path.splitext( full_path )
    ext = ext.lower()

    if ext not in MEDIA_TYPES:
        raise HTTPException(
            status_code = 400,
            detail      = f"Unsupported file type: {ext}"
        )

    media_type = MEDIA_TYPES[ ext ]

    # Force download: always return FileResponse with attachment Content-Disposition
    if download:
        try:
            filename = os.path.basename( full_path )
            return FileResponse(
                path                 = full_path,
                media_type           = media_type,
                filename             = filename,
                content_disposition_type = "attachment"
            )
        except Exception as e:
            raise HTTPException(
                status_code = 500,
                detail      = f"Error serving file: {str( e )}"
            )

    # For text files, use PlainTextResponse (better encoding handling)
    if ext in [ ".md", ".txt", ".json", ".yaml", ".yml" ]:
        try:
            with open( full_path, "r", encoding="utf-8" ) as f:
                content = f.read()
            return PlainTextResponse(
                content    = content,
                media_type = media_type
            )
        except Exception as e:
            raise HTTPException(
                status_code = 500,
                detail      = f"Error reading file: {str( e )}"
            )

    # For binary files (audio, pdf, images), use FileResponse
    else:
        try:
            filename = os.path.basename( full_path )
            # Inline-renderable types (pdf, png/jpg/gif/webp, mp3/wav) get
            # Content-Disposition: inline so the browser renders/plays them
            # in place. Other binary types (.pptx, etc.) default to attachment
            # so they download. `?download=true` is handled above and always
            # forces attachment regardless of type.
            disposition = "inline" if ext in INLINE_TYPES else "attachment"
            return FileResponse(
                path                     = full_path,
                media_type               = media_type,
                filename                 = filename,
                content_disposition_type = disposition,
            )
        except Exception as e:
            raise HTTPException(
                status_code = 500,
                detail      = f"Error serving file: {str( e )}"
            )


@router.get(
    "/api/io/health",
    summary     = "IO files health check",
    description = "Report io/ directory status and file counts in research and podcast subdirectories."
)
async def io_files_health():
    """
    Health check for io files endpoint.

    Returns status of io/ directory availability.
    """
    project_root = cu.get_project_root()
    io_path = project_root + "/io"
    io_exists = os.path.isdir( io_path )

    # Count files in subdirectories
    subdirs = {}
    if io_exists:
        for subdir in [ "deep-research", "podcasts" ]:
            subdir_path = os.path.join( io_path, subdir )
            if os.path.isdir( subdir_path ):
                file_count = sum( 1 for _, _, files in os.walk( subdir_path ) for f in files )
                subdirs[ subdir ] = file_count

    return {
        "status"      : "ok",
        "io_path"     : io_path,
        "io_exists"   : io_exists,
        "subdirs"     : subdirs,
        "media_types" : list( MEDIA_TYPES.keys() )
    }
