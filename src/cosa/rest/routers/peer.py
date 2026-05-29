"""
Peer Queue Proxy + Watcher Router.

Provides admin endpoints that let the dev server (:7999) observe and watch
queue state on a peer Lupin server (typically the test server at :8000)
without the user having to authenticate against the peer directly.

Endpoints:
    GET  /api/admin/peer-queue/{queue_name}         — one-shot queue read
    POST /api/admin/peer-queue-watch/start          — start background watcher
    POST /api/admin/peer-queue-watch/stop           — stop watcher for caller
    GET  /api/admin/peer-queue-watch/status         — current watcher state

Auth:
    All endpoints require admin role via Depends( require_admin ).

    Outbound auth to the peer uses a service-account JWT obtained via
    POST /auth/login against the peer itself (Option B). Credentials come
    from LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD env vars.
    Tokens are cached per-host and refreshed on 401.

    JWT pass-through (forwarding the caller's Authorization header) was
    tried first but doesn't work: dev and test share the JWT signing
    secret but have SEPARATE user databases, so the peer's verify_jwt_token
    → get_user_by_id() fails with "User not found".

SSRF protection:
    The target host must appear in config key "peer queue allowed hosts"
    (comma-separated list under [Lupin: Baseline]). Values are docker-compose
    service names + in-container port (7999), e.g. "lupin-rest-test:7999" —
    NOT host-mapped ports, since the dev container reaches peers over the
    compose network.

Drain notification:
    When the watcher detects `consecutive_zero >= stable_for`, it fires a
    high-priority notification via src/cosa/agents/utils/sync_notify.py,
    which POSTs to /api/notify on the local Lupin server. The WebSocket
    fanout layer routes it to cosa-voice (TTS) and any other subscribers.
    The notification is delivered regardless of whether the admin UI tab
    is still open.
"""

import asyncio
import os
import time
import traceback
from typing import Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from cosa.rest.auth_middleware import require_admin
from cosa.config.configuration_manager import ConfigurationManager
import cosa.utils.util as du


_config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

router = APIRouter( tags=["peer-queue"] )

# Valid queue names accepted by the upstream /api/get-queue/{name} endpoint.
_VALID_QUEUE_NAMES = { "todo", "run", "done", "dead" }

# Per-admin background watcher tasks. Keyed by admin user_id.
_active_watchers: Dict[ str, asyncio.Task ] = {}

# Per-admin watcher state snapshot. Updated by the task loop; read by /status.
_watcher_state: Dict[ str, Dict ] = {}

# Service-account JWT cache keyed by peer host. Value: { "token": str, "expires_at": epoch_seconds }.
# Lazily populated by _get_peer_jwt; invalidated on 401 via _invalidate_peer_jwt.
_peer_jwt_cache: Dict[ str, Dict ] = {}


# ============================================================================
# Helpers
# ============================================================================

def _get_allowed_hosts() -> List[ str ]:
    """Parse 'peer queue allowed hosts' config into a clean list."""
    raw = _config_mgr.get( "peer queue allowed hosts", default="", return_type="string" )
    if not raw: return []
    return [ h.strip() for h in raw.split( "," ) if h.strip() ]


def _is_host_allowed( host: str, whitelist: Optional[ List[ str ] ] = None ) -> bool:
    """Pure predicate: is the host in the whitelist? Exposed for unit testing."""
    if whitelist is None: whitelist = _get_allowed_hosts()
    return host in whitelist


def _validate_host_and_queue( host: str, queue_name: str ) -> None:
    """Raise HTTPException if host or queue_name is invalid."""
    if queue_name not in _VALID_QUEUE_NAMES:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = f"queue_name must be one of {sorted( _VALID_QUEUE_NAMES )}, got {queue_name!r}"
        )
    if not _is_host_allowed( host ):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = f"host {host!r} not in 'peer queue allowed hosts' whitelist"
        )


async def _login_to_peer( session: aiohttp.ClientSession, host: str ) -> Dict:
    """
    POST /auth/login on the peer using service-account credentials from env vars.

    Raises:
        HTTPException(500) if LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* env vars missing.
        HTTPException(502) if the peer rejects the login or is unreachable.
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD env vars must be set on the dev server for peer-queue auth"
        )

    url  = f"http://{host}/auth/login"
    body = { "email": email, "password": password }
    try:
        async with session.post( url, json=body, timeout=aiohttp.ClientTimeout( total=10.0 ) ) as resp:
            if resp.status != 200:
                preview = (await resp.text())[ :200 ]
                raise HTTPException(
                    status_code = status.HTTP_502_BAD_GATEWAY,
                    detail      = f"peer login {url} returned {resp.status}: {preview}"
                )
            data   = await resp.json()
            tokens = data.get( "tokens", {} )
            token  = tokens.get( "access_token" )
            if not token:
                raise HTTPException(
                    status_code = status.HTTP_502_BAD_GATEWAY,
                    detail      = f"peer login {url} succeeded but response missing tokens.access_token"
                )
            # Conservative 25-min expiry (Lupin JWTs are typically 30m; refresh early).
            return { "token": token, "expires_at": time.time() + ( 25 * 60 ) }
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail      = f"peer login {url} timed out"
        )
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail      = f"peer login {url} failed: {type( e ).__name__}: {e}"
        )


async def _get_peer_jwt( session: aiohttp.ClientSession, host: str ) -> str:
    """Return a cached or freshly-acquired service-account JWT for the peer."""
    cached = _peer_jwt_cache.get( host )
    if cached and cached[ "expires_at" ] > time.time():
        return cached[ "token" ]
    cached = await _login_to_peer( session, host )
    _peer_jwt_cache[ host ] = cached
    return cached[ "token" ]


def _invalidate_peer_jwt( host: str ) -> None:
    _peer_jwt_cache.pop( host, None )


async def _fetch_queue(
    session        : aiohttp.ClientSession,
    host           : str,
    queue_name     : str,
    timeout_seconds: float = 5.0,
    _retry         : bool  = False
) -> Dict:
    """
    Call GET http://{host}/api/get-queue/{queue_name} using a cached service-account JWT.

    On 401 (stale token), invalidates the cache and retries once.

    Raises:
        HTTPException(502) on upstream failure (network, non-2xx after retry, invalid JSON).
    """
    url   = f"http://{host}/api/get-queue/{queue_name}"
    token = await _get_peer_jwt( session, host )
    headers = { "Authorization": f"Bearer {token}" }
    try:
        async with session.get( url, headers=headers, timeout=aiohttp.ClientTimeout( total=timeout_seconds ) ) as resp:
            if resp.status == 401 and not _retry:
                _invalidate_peer_jwt( host )
                return await _fetch_queue( session, host, queue_name, timeout_seconds=timeout_seconds, _retry=True )
            if resp.status != 200:
                body_preview = (await resp.text())[ :200 ]
                raise HTTPException(
                    status_code = status.HTTP_502_BAD_GATEWAY,
                    detail      = f"upstream {url} returned {resp.status}: {body_preview}"
                )
            return await resp.json()
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail      = f"upstream {url} timed out after {timeout_seconds}s"
        )
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_502_BAD_GATEWAY,
            detail      = f"upstream {url} failed: {type( e ).__name__}: {e}"
        )


# ============================================================================
# Pydantic Models
# ============================================================================

class PeerQueueResponse( BaseModel ):
    """One-shot peer queue snapshot."""
    peer_host   : str
    queue_name  : str
    fetched_at  : str
    total_jobs  : int
    upstream    : Dict = Field( ..., description="Raw upstream response body" )


class WatchStartRequest( BaseModel ):
    """Start a peer-queue watcher."""
    host             : str = Field( ..., description="Peer host:port (must be in whitelist)" )
    signal           : str = Field( "run+todo", description="Drain signal: 'run' or 'run+todo'" )
    interval_seconds : int = Field( 60, ge=10, le=600, description="Poll interval (10-600s)" )
    stable_for       : int = Field( 2, ge=1, le=10, description="Consecutive zero polls required" )
    priority         : str = Field( "high", description="Notification priority on drain" )


class WatchStatusResponse( BaseModel ):
    """Current watcher state for the requesting admin."""
    active            : bool
    host              : Optional[ str ]
    signal            : Optional[ str ]
    interval_seconds  : Optional[ int ]
    stable_for        : Optional[ int ]
    started_at        : Optional[ str ]
    last_poll_at      : Optional[ str ]
    last_run          : Optional[ int ]
    last_todo         : Optional[ int ]
    consecutive_zero  : int
    last_error        : Optional[ str ]
    drained_at        : Optional[ str ]


class WatchActionResponse( BaseModel ):
    """Generic response for start/stop actions."""
    status  : str
    message : str


# ============================================================================
# Part 1 — Proxy endpoint
# ============================================================================

@router.get(
    "/api/admin/peer-queue/{queue_name}",
    response_model = PeerQueueResponse,
    summary        = "Proxy a queue read to a peer Lupin server",
    description    = "Admin-only. Forwards the caller's JWT to the peer's /api/get-queue/{name} and returns the response. Peer host must be in the 'peer queue allowed hosts' whitelist."
)
async def get_peer_queue(
    queue_name : str,
    host       : str  = Query( ..., description="Peer docker-compose service:port (e.g. lupin-rest-test:7999)" ),
    admin_user : Dict = Depends( require_admin )
) -> PeerQueueResponse:
    _validate_host_and_queue( host, queue_name )

    async with aiohttp.ClientSession() as session:
        upstream = await _fetch_queue( session, host, queue_name )

    return PeerQueueResponse(
        peer_host  = host,
        queue_name = queue_name,
        fetched_at = du.get_current_datetime_iso(),
        total_jobs = int( upstream.get( "total_jobs", 0 ) ),
        upstream   = upstream
    )


# ============================================================================
# Part 2 — Watcher service
# ============================================================================

async def _watcher_loop(
    user_id          : str,
    host             : str,
    signal           : str,
    interval_seconds : int,
    stable_for       : int,
    priority         : str,
    sender_id        : str
):
    """
    Background task: poll the peer queue, fire notification on drain, exit.
    Updates _watcher_state[user_id] on every iteration for /status to read.
    """
    state = _watcher_state[ user_id ]
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    run_body  = await _fetch_queue( session, host, "run"  )
                    todo_body = await _fetch_queue( session, host, "todo" ) if signal == "run+todo" else None

                    run_count  = int( run_body.get( "total_jobs", 0 ) )
                    todo_count = int( todo_body.get( "total_jobs", 0 ) ) if todo_body else None

                    state[ "last_poll_at" ] = du.get_current_datetime_iso()
                    state[ "last_run" ]     = run_count
                    state[ "last_todo" ]    = todo_count
                    state[ "last_error" ]   = None

                    is_drained = ( run_count == 0 ) and ( signal != "run+todo" or todo_count == 0 )
                    if is_drained:
                        state[ "consecutive_zero" ] = state[ "consecutive_zero" ] + 1
                    else:
                        state[ "consecutive_zero" ] = 0

                    if state[ "consecutive_zero" ] >= stable_for:
                        message = (
                            f"Peer queue drained on {host} — "
                            f"{stable_for} consecutive zero polls "
                            f"(signal={signal})."
                        )
                        await _fire_notification( message, sender_id, priority )
                        state[ "drained_at" ] = du.get_current_datetime_iso()
                        state[ "active" ]     = False
                        return

                except HTTPException as he:
                    state[ "last_error" ] = f"HTTP {he.status_code}: {he.detail}"
                except Exception as e:
                    state[ "last_error" ] = f"{type( e ).__name__}: {e}"
                    traceback.print_exc()

                await asyncio.sleep( interval_seconds )

    except asyncio.CancelledError:
        state[ "active" ]     = False
        state[ "last_error" ] = "cancelled"
        raise


async def _fire_notification( message: str, sender_id: str, priority: str ) -> None:
    """Dispatch notification via the established sync_notify helper."""
    from cosa.agents.utils import sync_notify
    try:
        await asyncio.to_thread(
            sync_notify.notify,
            message   = message,
            sender_id = sender_id,
            priority  = priority,
            debug     = False,
        )
    except Exception as e:
        print( f"[PEER-WATCH] Failed to dispatch notification: {e}" )
        traceback.print_exc()


@router.post(
    "/api/admin/peer-queue-watch/start",
    response_model = WatchActionResponse,
    summary        = "Start a background peer-queue drain watcher",
    description    = "Admin-only. Spawns an asyncio task that polls the peer queue and fires a high-priority notification on drain. One active watcher per admin; re-calling replaces the prior."
)
async def start_watcher(
    request    : WatchStartRequest,
    admin_user : Dict = Depends( require_admin )
) -> WatchActionResponse:
    if request.signal not in ( "run", "run+todo" ):
        raise HTTPException( status.HTTP_400_BAD_REQUEST, f"signal must be 'run' or 'run+todo', got {request.signal!r}" )

    _validate_host_and_queue( request.host, "run" )

    user_id = str( admin_user.get( "uid" ) or admin_user.get( "email" ) or "unknown" )

    # Cancel any existing watcher for this admin before replacing.
    prior = _active_watchers.pop( user_id, None )
    if prior is not None and not prior.done():
        prior.cancel()
        try: await prior
        except ( asyncio.CancelledError, Exception ): pass

    # Seed state snapshot.
    _watcher_state[ user_id ] = {
        "active"           : True,
        "host"             : request.host,
        "signal"           : request.signal,
        "interval_seconds" : request.interval_seconds,
        "stable_for"       : request.stable_for,
        "started_at"       : du.get_current_datetime_iso(),
        "last_poll_at"     : None,
        "last_run"         : None,
        "last_todo"        : None,
        "consecutive_zero" : 0,
        "last_error"       : None,
        "drained_at"       : None,
    }

    sender_id = f"peer-queue-watch/{user_id}"
    task = asyncio.create_task(
        _watcher_loop(
            user_id          = user_id,
            host             = request.host,
            signal           = request.signal,
            interval_seconds = request.interval_seconds,
            stable_for       = request.stable_for,
            priority         = request.priority,
            sender_id        = sender_id,
        ),
        name = f"peer-queue-watch-{user_id}"
    )
    _active_watchers[ user_id ] = task

    return WatchActionResponse(
        status  = "started",
        message = f"Watching {request.host} (signal={request.signal}, interval={request.interval_seconds}s, stable_for={request.stable_for})"
    )


@router.post(
    "/api/admin/peer-queue-watch/stop",
    response_model = WatchActionResponse,
    summary        = "Stop the caller's peer-queue watcher",
    description    = "Admin-only. Idempotent — returns 'not_active' if no watcher was running."
)
async def stop_watcher(
    admin_user : Dict = Depends( require_admin )
) -> WatchActionResponse:
    user_id = str( admin_user.get( "uid" ) or admin_user.get( "email" ) or "unknown" )
    task = _active_watchers.pop( user_id, None )

    if task is None or task.done():
        if user_id in _watcher_state:
            _watcher_state[ user_id ][ "active" ] = False
        return WatchActionResponse( status="not_active", message="no watcher was running" )

    task.cancel()
    try: await task
    except ( asyncio.CancelledError, Exception ): pass

    if user_id in _watcher_state:
        _watcher_state[ user_id ][ "active" ] = False

    return WatchActionResponse( status="stopped", message="watcher cancelled" )


@router.get(
    "/api/admin/peer-queue-watch/status",
    response_model = WatchStatusResponse,
    summary        = "Get current peer-queue watcher status",
    description    = "Admin-only. Returns live state for this admin's watcher (if any)."
)
async def get_watcher_status(
    admin_user : Dict = Depends( require_admin )
) -> WatchStatusResponse:
    user_id = str( admin_user.get( "uid" ) or admin_user.get( "email" ) or "unknown" )
    state   = _watcher_state.get( user_id )

    if state is None:
        return WatchStatusResponse(
            active            = False,
            host              = None,
            signal            = None,
            interval_seconds  = None,
            stable_for        = None,
            started_at        = None,
            last_poll_at      = None,
            last_run          = None,
            last_todo         = None,
            consecutive_zero  = 0,
            last_error        = None,
            drained_at        = None,
        )

    return WatchStatusResponse( **state )


# ============================================================================
# Lifespan — cancel all active watchers on shutdown
# ============================================================================

async def cancel_all_watchers_on_shutdown():
    """Cancel every active watcher. Called from main.py shutdown hook."""
    for user_id, task in list( _active_watchers.items() ):
        if not task.done():
            task.cancel()
    for user_id, task in list( _active_watchers.items() ):
        try: await task
        except ( asyncio.CancelledError, Exception ): pass
    _active_watchers.clear()
