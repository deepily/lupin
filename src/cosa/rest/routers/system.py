"""
System administration and health monitoring endpoints.

Provides essential system management capabilities including health checks,
configuration refresh, session ID generation, authentication testing,
and WebSocket session management with cleanup functionality.

Generated on: 2025-01-24
"""

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Any, Optional

# Import dependencies
from ..auth import get_current_user, get_current_user_id
from ..dependencies.config import get_config_manager, get_snapshot_manager, get_id_generator
from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.solution_snapshot_mgr import SolutionSnapshotManager
from cosa.agents.two_word_id_generator import TwoWordIdGenerator
import cosa.utils.util as du


# ─── Pydantic models for similarity confirmation toggle ──────────────
class SimilarityConfirmationRequest( BaseModel ):
    enabled: bool

class SimilarityConfirmationResponse( BaseModel ):
    enabled  : bool
    previous : Optional[ bool ] = None


def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Requires:
        - lupin_app.main module is available
        - main_module has jobs_todo_queue attribute

    Ensures:
        - Returns the todo queue instance

    Raises:
        - ImportError if main module not available
        - AttributeError if todo queue not found
    """
    import lupin_app.main as main_module
    return main_module.jobs_todo_queue

router = APIRouter(tags=["system"])

@router.get(
    "/",
    response_class = JSONResponse,
    summary        = "Root health check",
    description    = "Basic health check returning service name, status, version, and timestamp."
)
async def health_check():
    """
    Basic health check endpoint for service status monitoring.
    
    Requires:
        - FastAPI application is running and responsive
        
    Ensures:
        - Returns healthy status with service identification
        - Includes current timestamp in ISO format
        - Provides version information for monitoring systems
        - Response is consistently formatted for health checks
        
    Raises:
        - None (endpoint is designed to always succeed)
        
    Returns:
        dict: Health status with service name, timestamp, and version
    """
    return {
        "status": "healthy",
        "service": "lupin-fastapi",
        "timestamp": du.get_current_datetime_iso(),
        "version": "0.1.0"
    }

@router.get(
    "/health",
    response_class = JSONResponse,
    summary        = "Lightweight health check",
    description    = "Minimal health endpoint for high-frequency monitoring. Returns status and timestamp."
)
async def health():
    """
    Simplified health endpoint for lightweight monitoring checks.
    
    Requires:
        - FastAPI application is running and responsive
        
    Ensures:
        - Returns "ok" status for monitoring systems
        - Includes current timestamp in ISO format
        - Provides minimal response for high-frequency health checks
        
    Raises:
        - None (endpoint is designed to always succeed)
        
    Returns:
        dict: Simple status and timestamp for monitoring
    """
    return {
        "status": "ok",
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/api/server-info",
    response_class = JSONResponse,
    summary        = "Get server info",
    description    = "Return current config block ID, masked database URL, and environment name."
)
async def get_server_info( config_mgr: ConfigurationManager = Depends( get_config_manager ) ):
    """
    Return current server configuration state for infrastructure monitoring.

    Requires:
        - FastAPI application is running with initialized config manager

    Ensures:
        - Returns current config block ID, masked database URL, and environment
        - Database password is always masked in the response
        - No authentication required (infrastructure metadata only)

    Returns:
        dict: config_block_id, database_url (masked), environment
    """
    from cosa.rest.db import database as db_module

    env    = os.environ.get( "LUPIN_ENV", "development" ).lower()
    db_url = str( db_module.engine.url )
    masked = db_url.replace( str( db_module.engine.url.password or "" ), "***" )

    return {
        "config_block_id" : config_mgr.config_block_id,
        "database_url"    : masked,
        "environment"     : env
    }


@router.get(
    "/api/init",
    response_class = JSONResponse,
    summary        = "Hot-reload configuration",
    description    = "Reload configuration and optionally swap active config block and database connection at runtime."
)
async def init( config_block_id: Optional[ str ] = None ):
    """
    Refresh configuration and reload application resources without restart.

    Optionally accepts a config_block_id query parameter to hot-swap
    the server's configuration block and database connection at runtime.

    Requires:
        - FastAPI application is running with initialized components
        - Configuration files exist at specified paths (lupin-app.ini)
        - LUPIN_CONFIG_MGR_CLI_ARGS environment variable is set
        - lupin_app.main module is accessible with global components

    Ensures:
        - Reinitializes the singleton ConfigurationManager (not a throwaway)
        - If config_block_id provided, swaps database connection to match
        - Reloads solution snapshots from disk if snapshot_mgr exists
        - Returns success status with current config state

    Raises:
        - None (catches all exceptions and returns error status)

    Returns:
        dict: Success/error status with config state and timestamp
    """
    try:
        from cosa.rest.db.database import swap_database
        import cosa.rest.dependencies.config as config_module
        import lupin_app.main as main_module

        # Get the singleton config manager (not a throwaway instance)
        config_mgr = config_module.get_config_manager()

        if config_block_id is not None:
            block_id = config_block_id.replace( "+", " " )
            env_map  = {
                "Lupin: Testing"     : "testing",
                "Lupin: Development" : "development",
                "Lupin: Production"  : "production"
            }
            new_env = env_map.get( block_id, "development" )

            # Reinitialize config manager with new block (in place)
            config_mgr.init( config_block_id=block_id )

            # Swap database connection to match
            new_db_url = swap_database( new_env )
        else:
            config_mgr.init()
            new_db_url = "(unchanged)"

        config_mgr.print_configuration( brackets=True )

        # Flush every registered cache uniformly. Each cache module
        # (snapshot_mgr in main.py, prediction_engine, scope_registry,
        # any future cache) self-registers an invalidator at import time
        # via cosa.config.cache_registry; /api/init no longer needs to
        # know about each cache explicitly. Resolves Mr. Radio's
        # /api/init invalidation bug (filed 2026-05-15, session ea85fd64).
        from cosa.config.cache_registry import invalidate_all
        caches_invalidated = invalidate_all()

        # Eagerly rebuild PredictionEngine after reset so the first request
        # hitting the engine doesn't pay the cold-start cost.
        try:
            from cosa.agents.prediction_engine.prediction_engine import get_prediction_engine
            get_prediction_engine( config_mgr=config_mgr )
        except Exception as pe:
            print( f"[INIT] PredictionEngine eager-rebuild note: {pe}" )

        return {
            "status"             : "success",
            "config_block_id"    : config_mgr.config_block_id,
            "database_url"       : new_db_url,
            "environment"        : os.environ.get( "LUPIN_ENV", "development" ),
            "caches_invalidated" : caches_invalidated,
            "timestamp"          : du.get_current_datetime_iso()
        }
    except Exception as e:
        return {
            "status"    : "error",
            "message"   : f"Init failed: {str( e )}",
            "timestamp" : du.get_current_datetime_iso()
        }

@router.get(
    "/api/prediction-engine/reset",
    response_class = JSONResponse,
    summary        = "Reset PredictionEngine singleton",
    description    = "Destroy and re-create the PredictionEngine singleton with current config. Used by integration tests to ensure LanceDB table isolation between tests."
)
async def reset_prediction_engine( drop_table: bool = True ):
    """
    Lightweight endpoint to reset the PredictionEngine singleton.

    Ensures:
        - LanceDB table is dropped if it exists and drop_table=True (server has write permission)
        - PredictionEngine singleton is destroyed and re-created
        - New instance reads current config (e.g., test LanceDB table after hot-swap)
        - No config reinit, DB swap, or snapshot reload (use /api/init for those)
    """
    try:
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine, get_prediction_engine
        import cosa.utils.util as cu

        config_mgr  = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        table_name  = config_mgr.get( "prediction engine lancedb table", default="prediction_decisions" )
        table_dropped = False

        # Clear the decision store (server process has write permission, test process may not).
        # v0.2.0 §6: under the postgres backend clear the pgvector prediction_decisions
        # rows (the alembic-managed table is kept); under lancedb drop the table.
        from cosa.rest.db.repositories.vector_store_backend import is_postgres_backend
        if drop_table:
            if is_postgres_backend( config_mgr ):
                try:
                    from cosa.rest.db.database import get_db
                    from cosa.rest.db.repositories.prediction_decision_repository import PredictionDecisionRepository
                    with get_db() as session:
                        PredictionDecisionRepository( session ).delete_all()
                    table_dropped = True
                except Exception as drop_err:
                    print( f"[PE-RESET] Postgres clear note: {drop_err}" )
            else:
                try:
                    import lancedb
                    lancedb_path = cu.get_project_root() + "/src/conf/long-term-memory/lupin.lancedb"
                    db = lancedb.connect( lancedb_path )
                    if table_name in db.table_names():
                        db.drop_table( table_name )
                        table_dropped = True
                except Exception as drop_err:
                    print( f"[PE-RESET] Table drop note: {drop_err}" )

        PredictionEngine.reset()
        engine = get_prediction_engine( config_mgr=config_mgr )

        return {
            "status"           : "success",
            "prediction_table" : engine.lancedb_table,
            "table_dropped"    : table_dropped,
            "timestamp"        : du.get_current_datetime_iso()
        }
    except Exception as e:
        return {
            "status"  : "error",
            "message" : f"PredictionEngine reset failed: {str( e )}",
            "timestamp": du.get_current_datetime_iso()
        }


@router.get(
    "/api/get-session-id",
    summary     = "Generate session ID",
    description = "Generate and return a unique two-word session ID for WebSocket routing."
)
async def get_session_id(
    id_gen: TwoWordIdGenerator = Depends(get_id_generator)
):
    """
    Generate and return a unique session ID for WebSocket communication routing.
    
    Requires:
        - id_gen dependency is properly initialized TwoWordIdGenerator
        - TwoWordIdGenerator has loaded word lists and is functional
        
    Ensures:
        - Generates a unique two-word hyphenated ID string
        - Logs the generated session ID for debugging
        - Returns session ID with current timestamp
        - ID is suitable for WebSocket message routing
        
    Raises:
        - None (TwoWordIdGenerator handles internal errors gracefully)
        
    Args:
        id_gen: Injected TwoWordIdGenerator dependency
        
    Returns:
        dict: Contains generated session_id and timestamp
        
    Note:
        This ID will be used to route asynchronous WebSocket messages
        to the correct client in future implementations
    """
    session_id = id_gen.get_id()
    print(f"[API] Generated new session ID: {session_id}")
    
    return {
        "session_id": session_id,
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/api/auth-test",
    summary     = "Test authentication",
    description = "Verify JWT authentication is functioning. Returns authenticated user details."
)
async def auth_test(current_user: dict = Depends(get_current_user)):
    """
    Test endpoint to verify authentication system functionality.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - get_current_user dependency is properly configured
        - Firebase authentication system is accessible
        
    Ensures:
        - Returns success status with authenticated user information
        - Confirms authentication system is working correctly
        - Includes user details from JWT token payload
        - Provides timestamp for testing verification
        
    Raises:
        - HTTPException with 401 status if authentication fails
        - HTTPException with 401 status if token is invalid/missing
        
    Args:
        current_user: Authenticated user information from JWT token
        
    Returns:
        dict: Success message, user details, and timestamp
        
    Note:
        REFACTORING CHANGE: This endpoint now returns 401 (Unauthorized) status
        when called without auth token, fixing test expectations.
        Changed from 403 to 401 on 2025.09.28.
    """
    return {
        "status": "success",
        "message": "Authentication is working",
        "user": current_user,
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/api/websocket-sessions",
    summary     = "List WebSocket sessions",
    description = "Return info about all active WebSocket sessions including user counts and policy state."
)
async def get_websocket_sessions(
    current_user: dict = Depends(get_current_user)
):
    """
    Get comprehensive information about all active WebSocket sessions with metrics.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - lupin_app.main module is accessible
        - WebSocketManager is initialized in main module
        - WebSocketManager has get_all_sessions_info() method
        
    Ensures:
        - Retrieves all active WebSocket session information
        - Calculates session metrics including total and unique users
        - Identifies users with multiple concurrent sessions
        - Returns single session policy configuration status
        - Includes comprehensive session details and statistics
        
    Raises:
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager not properly initialized
        
    Args:
        current_user: Authenticated user information from JWT token
        
    Returns:
        dict: Session metrics, policy info, session list, and timestamp
    """
    # Get WebSocketManager from main module
    import lupin_app.main as main_module
    websocket_manager = main_module.websocket_manager
    
    sessions = websocket_manager.get_all_sessions_info()
    
    # Calculate metrics
    total_sessions = len(sessions)
    user_sessions = {}
    for session in sessions:
        user_id = session.get('user_id')
        if user_id:
            if user_id not in user_sessions:
                user_sessions[user_id] = 0
            user_sessions[user_id] += 1
    
    return {
        "total_sessions": total_sessions,
        "unique_users": len(user_sessions),
        "users_with_multiple_sessions": sum(1 for count in user_sessions.values() if count > 1),
        "single_session_policy": websocket_manager.single_session_per_user,
        "sessions": sessions,
        "timestamp": du.get_current_datetime_iso()
    }

@router.post(
    "/api/websocket-sessions/cleanup",
    summary     = "Cleanup stale sessions",
    description = "Remove WebSocket sessions older than the specified age limit."
)
async def cleanup_stale_sessions(
    max_age_hours: int = 24,
    current_user: dict = Depends(get_current_user)
):
    """
    Clean up stale WebSocket sessions older than specified age limit.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - lupin_app.main module is accessible
        - WebSocketManager is initialized in main module
        - max_age_hours is a positive integer value
        - WebSocketManager has cleanup_stale_sessions() method
        
    Ensures:
        - Identifies and removes WebSocket sessions older than max_age_hours
        - Returns count of sessions that were cleaned up
        - Logs cleanup operation for monitoring purposes
        - Includes cleanup parameters in response for verification
        
    Raises:
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager not properly initialized
        - ValueError if max_age_hours is invalid
        
    Args:
        max_age_hours: Maximum age in hours before session is stale (default: 24)
        current_user: Authenticated user information from JWT token
        
    Returns:
        dict: Number of sessions cleaned, age limit, and timestamp
    """
    # Get WebSocketManager from main module
    import lupin_app.main as main_module
    websocket_manager = main_module.websocket_manager
    
    cleaned = websocket_manager.cleanup_stale_sessions(max_age_hours)
    
    return {
        "sessions_cleaned": cleaned,
        "max_age_hours": max_age_hours,
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/api/debug/websocket-state",
    summary     = "Debug WebSocket state",
    description = "Expose complete internal WebSocket manager state for troubleshooting. Debug endpoint."
)
async def get_websocket_state():
    """
    Get complete internal state of WebSocket manager for debugging.

    **DEBUG ENDPOINT**: This endpoint exposes internal WebSocket manager state
    for troubleshooting connection and authentication issues. Should be removed
    or protected in production environments.

    Requires:
        - lupin_app.main module is accessible
        - WebSocketManager is initialized in main module

    Ensures:
        - Returns all active_connections (session IDs)
        - Returns session_to_user mapping (session → user ID)
        - Returns user_sessions mapping (user ID → list of sessions)
        - Returns session_subscriptions mapping (session → subscribed events)
        - Returns session_timestamps for age calculation
        - Includes helper analysis for quick diagnostics

    Raises:
        - AttributeError if WebSocketManager not properly initialized

    Returns:
        dict: Complete internal state with mappings and diagnostics

    Example Response:
        {
            "active_connections": ["faithful zebra", "wise penguin"],
            "session_to_user": {"wise penguin": "ricardo_felipe_ruiz_6bdc"},
            "user_sessions": {"ricardo_felipe_ruiz_6bdc": ["wise penguin"]},
            "session_subscriptions": {"wise penguin": ["*"]},
            "diagnostics": {
                "unmapped_sessions": ["faithful zebra"],
                "total_active": 2,
                "authenticated": 1,
                "unauthenticated": 1
            }
        }
    """
    # Get WebSocketManager from main module
    import lupin_app.main as main_module
    websocket_manager = main_module.websocket_manager

    # Extract internal state
    active_sessions = list(websocket_manager.active_connections.keys())
    session_to_user_map = dict(websocket_manager.session_to_user)
    user_sessions_map = {k: list(v) for k, v in websocket_manager.user_sessions.items()}
    session_subscriptions = {k: list(v) for k, v in websocket_manager.session_subscriptions.items()}

    # Build session timestamps (convert to ISO format)
    session_timestamps = {}
    for session_id, timestamp in websocket_manager.session_timestamps.items():
        session_timestamps[session_id] = timestamp.isoformat()

    # Diagnostic analysis
    unmapped_sessions = [sid for sid in active_sessions if sid not in session_to_user_map]
    authenticated_count = len(session_to_user_map)
    unauthenticated_count = len(unmapped_sessions)

    # Check for orphaned user mappings (user has sessions but none are active)
    orphaned_users = []
    for user_id, sessions in user_sessions_map.items():
        active_user_sessions = [s for s in sessions if s in active_sessions]
        if not active_user_sessions:
            orphaned_users.append(user_id)

    return {
        "active_connections": active_sessions,
        "session_to_user": session_to_user_map,
        "user_sessions": user_sessions_map,
        "session_subscriptions": session_subscriptions,
        "session_timestamps": session_timestamps,
        "diagnostics": {
            "total_active_connections": len(active_sessions),
            "authenticated_sessions": authenticated_count,
            "unauthenticated_sessions": unauthenticated_count,
            "unmapped_sessions": unmapped_sessions,
            "unique_users_connected": len(user_sessions_map),
            "orphaned_user_mappings": orphaned_users,
            "single_session_policy_enabled": websocket_manager.single_session_per_user
        },
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/api/config/client",
    summary     = "Get client config",
    description = "Return client-side timing configuration including token refresh, heartbeat, and timezone."
)
async def get_client_config( user_id: str = Depends( get_current_user_id ) ):
    """
    Return client-side configuration parameters for authenticated users.

    **Authentication**: REQUIRED - JWT token validated via dependency injection

    Requires:
        - Valid JWT token in Authorization header
        - ConfigurationManager initialized
        - lupin-app.ini contains timing settings (or uses defaults)

    Ensures:
        - Returns JSON with all client timing parameters
        - Only accessible to authenticated users (401 if unauthenticated)
        - Units converted appropriately for client use
        - Fallback defaults provided for missing config values

    Args:
        user_id: Authenticated user ID (injected by dependency, ensures JWT valid)

    Returns:
        JSON response with timing parameters:
        {
            "token_refresh_check_interval_ms": 600000,    # 10 mins in milliseconds
            "token_expiry_threshold_secs": 300,           # 5 mins in seconds
            "token_refresh_dedup_window_ms": 60000,       # 60 secs in milliseconds
            "websocket_heartbeat_interval_secs": 30,      # Reference value (secs)
            "app timezone": "America/New_York"            # IANA timezone for display
        }

    Example:
        GET /api/config/client
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

        Response 200:
        {
            "token_refresh_check_interval_ms": 600000,
            "token_expiry_threshold_secs": 300,
            "token_refresh_dedup_window_ms": 60000,
            "websocket_heartbeat_interval_secs": 30,
            "app timezone": "America/New_York"
        }
    """
    # Note: user_id parameter required by Depends() - validates JWT token
    # We don't use the actual user_id value, but it ensures authentication

    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    # Fetch from config with fallback defaults
    refresh_check_interval_mins = config_mgr.get(
        "jwt token refresh check interval mins",
        default=10, return_type="int"
    )
    expiry_threshold_mins = config_mgr.get(
        "jwt token refresh expiry threshold mins",
        default=5, return_type="int"
    )
    dedup_window_secs = config_mgr.get(
        "jwt token refresh dedup window secs",
        default=60, return_type="int"
    )
    heartbeat_interval_secs = config_mgr.get(
        "websocket heartbeat interval seconds",
        default=30, return_type="int"
    )
    app_timezone = config_mgr.get(
        "app timezone",
        default="America/New_York"
    )
    tfe_auto_fix_enabled = config_mgr.get(
        "test fix expediter auto fix enabled",
        default=False, return_type="boolean"
    )

    # TTS preview-and-pause cost-reduction feature (2026-05-13)
    # See src/rnd/v0.1.7/2026.05.13-tts-preview-and-pause-design.md
    tts_preview_enabled = config_mgr.get(
        "tts preview enabled",
        default=True, return_type="boolean"
    )
    tts_preview_fraction = config_mgr.get(
        "tts preview fraction",
        default=0.25, return_type="float"
    )
    tts_preview_min_chars = config_mgr.get(
        "tts preview min chars",
        default=100, return_type="int"
    )

    # Commons Traffic Visibility — broadcast-card Recent Activity feature flag (2026-05-14)
    # See src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (Q9 — default True)
    commons_traffic_visibility_enabled = config_mgr.get(
        "commons traffic visibility enabled",
        default=True, return_type="boolean"
    )
    commons_traffic_visibility_default_hours_window = config_mgr.get(
        "commons traffic visibility default hours window",
        default="today"
    )

    lupin_env = os.environ.get( "LUPIN_ENV", "" ).lower()
    if lupin_env in [ "test", "testing" ]:
        env_label = "TEST"
    else:
        env_label = "DEVELOPMENT"

    return {
        "env_label": env_label,

        # Convert minutes → milliseconds (for setInterval)
        "token_refresh_check_interval_ms": int( refresh_check_interval_mins * 60 * 1000 ),

        # Convert minutes → seconds (for JWT exp comparison)
        "token_expiry_threshold_secs": int( expiry_threshold_mins * 60 ),

        # Convert seconds → milliseconds (for Date.now() comparison)
        "token_refresh_dedup_window_ms": int( dedup_window_secs * 1000 ),

        # Already in seconds (reference value for logging/debugging)
        "websocket_heartbeat_interval_secs": int( heartbeat_interval_secs ),

        # IANA timezone name for client-side date/time formatting
        "app timezone": app_timezone,

        # TestFixExpediter auto-fix INI default — drives initial state of the
        # "auto-fix on failure" checkbox in the test runner submission card
        "test_fix_expediter_auto_fix_enabled": bool( tfe_auto_fix_enabled ),

        # TTS verbosity-limiter feature flags (2026-05-13; boundary-scan 2026-05-22)
        # When enabled, every TTS message is truncated client-side to roughly
        # <fraction> of its length and only that slice is synthesized. Saves TTS
        # provider character costs because providers charge at request-time.
        "tts_preview_enabled"            : bool( tts_preview_enabled ),
        "tts_preview_fraction"           : float( tts_preview_fraction ),
        "tts_preview_min_chars"          : int( tts_preview_min_chars ),

        # TTS interaction mode (chorus / solo) — drives mode-conditional icon
        # rendering for the per-session DND toggle on each sender card. Added
        # 2026-05-14 evening per src/rnd/v0.1.7/2026.05.14-per-session-dnd-toggle-and-slider-move.md
        "tts_interaction_mode"           : config_mgr.get( "tts interaction mode", default="chorus" ),

        # Commons Traffic Visibility (2026-05-14) — feature flag for the broadcast-card
        # Recent Activity stream. JS-side reads this at constructor time to gate the
        # render block + WS subscription. Default True per Q9 ratification.
        # See src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md
        "commons_traffic_visibility_enabled"              : bool( commons_traffic_visibility_enabled ),
        "commons_traffic_visibility_default_hours_window" : commons_traffic_visibility_default_hours_window,
    }


@router.get(
    "/api/config/similarity-confirmation",
    summary     = "Get similarity confirmation toggle",
    description = "Return the current runtime state of the similarity confirmation feature."
)
async def get_similarity_confirmation(
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue )
):
    """
    Get current state of the similarity confirmation toggle.

    Requires:
        - Valid JWT authentication token in Authorization header
        - todo_queue dependency provides access to live config_mgr

    Ensures:
        - Returns JSON with current enabled/disabled state

    Returns:
        dict: { "enabled": true/false }
    """
    enabled = todo_queue.config_mgr.get(
        "similarity confirmation enabled", default=True, return_type="boolean"
    )
    return { "enabled": enabled }


@router.post(
    "/api/config/similarity-confirmation",
    summary     = "Set similarity confirmation toggle",
    description = "Toggle the similarity confirmation feature at runtime. Returns new and previous values."
)
async def set_similarity_confirmation(
    body: SimilarityConfirmationRequest,
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue )
):
    """
    Set the similarity confirmation toggle at runtime.

    Requires:
        - Valid JWT authentication token in Authorization header
        - body.enabled is a boolean
        - todo_queue dependency provides access to live config_mgr

    Ensures:
        - Updates similarity_confirmation_enabled in the queue's config_mgr
        - Returns new value and previous value for verification

    Returns:
        dict: { "enabled": true/false, "previous": true/false }
    """
    previous = todo_queue.config_mgr.get(
        "similarity confirmation enabled", default=True, return_type="boolean"
    )
    todo_queue.config_mgr.set_config(
        "similarity confirmation enabled", str( body.enabled ).lower()
    )
    return { "enabled": body.enabled, "previous": previous }