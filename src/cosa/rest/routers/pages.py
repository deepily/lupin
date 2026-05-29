"""
Pages router — maps clean /app/* URLs to static HTML files.

Pure file-serving router using FileResponse. No business logic,
no authentication enforcement (auth is handled client-side by each page's JS).

Generated on: 2026-02-21
"""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

import cosa.utils.util as cu

router = APIRouter( tags=[ "pages" ] )

# Resolve the static directory once at import time
_static_dir = os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), "..", "..", "..", "fastapi_app", "static" )
_static_dir = os.path.normpath( _static_dir )

# Route table: clean URL → relative path under static/
_ROUTE_TABLE = {
    "/app"                       : "html/landing.html",
    "/app/notifications"         : "html/notifications.html",
    "/app/multiplexer"           : "html/multiplexer.html",
    "/app/auth/login"            : "html/auth/login.html",
    "/app/auth/register"         : "html/auth/register.html",
    "/app/auth/profile"          : "html/auth/profile.html",
    "/app/auth/change-password"  : "html/auth/change-password.html",
    "/app/admin"                 : "html/admin/dashboard.html",
    "/app/admin/users"           : "html/auth/admin/users.html",
    "/app/admin/snapshots"       : "html/admin/snapshots.html",
    "/app/admin/proxy-ratify"    : "html/auth/admin/proxy-ratify.html",
    "/app/admin/proxy-dashboard" : "html/auth/admin/proxy-dashboard.html",
    "/app/admin/dev-tools"       : "html/dev-tools.html",
    "/app/admin/peer-queue-watch": "html/admin/peer-queue-watch.html",
    "/app/docs"                  : "html/document-viewer.html",
    "/app/audio"                 : "html/audio-player.html",
}


def _serve_file( relative_path: str ):
    """
    Create a FileResponse for a static HTML file.

    Requires:
        - relative_path is a valid path under the static directory
        - The file exists on disk

    Ensures:
        - Returns FileResponse with text/html media type
        - Sets `Cache-Control: no-cache` so browsers revalidate the SPA
          shell on every load. Prevents the stale-HTML trap that bit the
          doc-viewer on 2026-05-21 (Rachel's PNG plot rendered as bytecode
          because the browser cached the pre-image-MIME-dispatch HTML).
          `FileResponse` still emits `ETag` + `Last-Modified` headers, so
          revalidation is a cheap conditional GET — server returns 304
          Not Modified when content is unchanged.

    Raises:
        - 404 if file not found (FastAPI default behavior)
    """
    full_path = os.path.join( _static_dir, relative_path )
    return FileResponse(
        full_path,
        media_type = "text/html",
        headers    = { "Cache-Control": "no-cache" },
    )


# Note: / is handled by system router (health check endpoint).
# Users arrive at /app via the nav bar or bookmarks.

# Register all /app/* routes
@router.get( "/app", include_in_schema=False )
async def page_app():
    return _serve_file( _ROUTE_TABLE[ "/app" ] )

@router.get( "/app/notifications", include_in_schema=False )
async def page_notifications():
    return _serve_file( _ROUTE_TABLE[ "/app/notifications" ] )

@router.get( "/app/multiplexer", include_in_schema=False )
async def page_multiplexer():
    return _serve_file( _ROUTE_TABLE[ "/app/multiplexer" ] )

@router.get( "/app/auth/login", include_in_schema=False )
async def page_auth_login():
    return _serve_file( _ROUTE_TABLE[ "/app/auth/login" ] )

@router.get( "/app/auth/register", include_in_schema=False )
async def page_auth_register():
    return _serve_file( _ROUTE_TABLE[ "/app/auth/register" ] )

@router.get( "/app/auth/profile", include_in_schema=False )
async def page_auth_profile():
    return _serve_file( _ROUTE_TABLE[ "/app/auth/profile" ] )

@router.get( "/app/auth/change-password", include_in_schema=False )
async def page_auth_change_password():
    return _serve_file( _ROUTE_TABLE[ "/app/auth/change-password" ] )

@router.get( "/app/admin", include_in_schema=False )
async def page_admin():
    return _serve_file( _ROUTE_TABLE[ "/app/admin" ] )

@router.get( "/app/admin/users", include_in_schema=False )
async def page_admin_users():
    return _serve_file( _ROUTE_TABLE[ "/app/admin/users" ] )

@router.get( "/app/admin/snapshots", include_in_schema=False )
async def page_admin_snapshots():
    return _serve_file( _ROUTE_TABLE[ "/app/admin/snapshots" ] )

@router.get( "/app/admin/proxy-ratify", include_in_schema=False )
async def page_admin_proxy_ratify():
    return _serve_file( _ROUTE_TABLE[ "/app/admin/proxy-ratify" ] )

@router.get( "/app/admin/proxy-dashboard", include_in_schema=False )
async def page_admin_proxy_dashboard():
    return _serve_file( _ROUTE_TABLE[ "/app/admin/proxy-dashboard" ] )

@router.get( "/app/admin/dev-tools", include_in_schema=False )
async def page_admin_dev_tools():
    return _serve_file( _ROUTE_TABLE[ "/app/admin/dev-tools" ] )

@router.get( "/app/admin/peer-queue-watch", include_in_schema=False )
async def page_admin_peer_queue_watch():
    return _serve_file( _ROUTE_TABLE[ "/app/admin/peer-queue-watch" ] )

@router.get( "/app/docs", include_in_schema=False )
async def page_docs():
    return _serve_file( _ROUTE_TABLE[ "/app/docs" ] )

@router.get( "/app/audio", include_in_schema=False )
async def page_audio():
    return _serve_file( _ROUTE_TABLE[ "/app/audio" ] )
