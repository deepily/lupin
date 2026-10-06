"""
Pages router — maps clean /app/* URLs to static HTML files.

Pure file-serving router using FileResponse. No business logic,
no authentication enforcement (auth is handled client-side by each page's JS).
"""

import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.dependencies.config import get_config_manager

router = APIRouter( tags=[ "pages" ] )

# Resolve the static directory once at import time
_static_dir = os.path.join( os.path.dirname( os.path.abspath( __file__ ) ), "..", "..", "..", "lupin_app", "static" )
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
    "/app/console"               : "html/console.html",
}


def _serve_file( relative_path: str ):
    """
    Create a FileResponse for a static HTML file.

    Requires:
        - relative_path is a valid path under the static directory
        - The file exists on disk

    Ensures:
        - Returns FileResponse with text/html media type
        - Sets `Cache-Control: no-cache` so browsers revalidate the single-page app
          shell on every load. This prevents a stale-HTML trap. A browser that cached
          the old doc-viewer HTML rendered a PNG plot as bytecode, because that HTML
          predated image media-type dispatch. `FileResponse` still emits `ETag` and
          `Last-Modified` headers, so revalidation is a cheap conditional GET. The
          server returns 304 Not Modified when content is unchanged.

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
async def page_notifications( classic: bool = False, config_mgr: ConfigurationManager = Depends( get_config_manager ) ):
    """
    Serve the legacy notifications page, or 302-redirect to the multiplexer.

    Requires:
        - `legacy notifications redirect enabled` is a boolean INI key (default False)

    Ensures:
        - Flag off (default): serves notifications.html unchanged
        - Flag on: returns 302 RedirectResponse to /app/multiplexer
        - Flag on + `?classic=1`: serves notifications.html (escape hatch for the
          held-back JS-client E2E suites and the MVD "Classic UI" link)

    The redirect is gated on the INI key, so flipping it is a one-line config change and
    not a code change. The route stays alive so bookmarks keep working.
    """
    redirect_enabled = config_mgr.get( "legacy notifications redirect enabled", default=False, return_type="boolean" )
    if redirect_enabled and not classic:
        return RedirectResponse( url="/app/multiplexer", status_code=302 )
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

@router.get( "/app/console", include_in_schema=False )
async def page_console():
    """
    Serve the standalone live-console page.

    Requires:
        - html/console.html exists under the static directory

    Ensures:
        - Returns the console page shell with the no-cache revalidation header

    The page shows one seat's live CC console in its own tab. It reads `?seat=` and `?title=`
    client-side. This handler therefore takes no parameters, and a reload or bookmark serves
    the same shell. The page itself reports a missing or malformed seat.
    """
    return _serve_file( _ROUTE_TABLE[ "/app/console" ] )
