"""
WebSocket administration endpoints for connection and session management.

Provides comprehensive administrative capabilities for WebSocket connection
monitoring, session management, cleanup operations, policy configuration,
and event type introspection.

Generated on: 2025-01-25
"""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import Optional

import cosa.utils.util as du

# Import dependencies
from cosa.rest.auth import get_current_user
from cosa.rest.websocket_manager import WebSocketManager

router = APIRouter(prefix="/api", tags=["websocket-admin"])

# Global dependencies (temporary access via main module)
def get_websocket_manager():
    """
    Dependency to get WebSocket manager from main module.
    
    Requires:
        - lupin_app.main module is available
        - main_module has websocket_manager attribute
        
    Ensures:
        - Returns the WebSocket manager instance
        - Provides access to WebSocket administration
        
    Raises:
        - ImportError if main module not available
        - AttributeError if websocket_manager not found
    """
    import lupin_app.main as main_module
    return main_module.websocket_manager

@router.get(
    "/websocket-sessions",
    summary     = "List WebSocket sessions",
    description = "Return all active WebSocket sessions with total and per-user connection counts."
)
async def get_websocket_sessions(
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Get comprehensive information about all active WebSocket sessions with metrics.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - websocket_manager is properly initialized WebSocketManager
        - WebSocketManager has get_all_sessions_info() method
        - WebSocketManager has user_sessions attribute
        
    Ensures:
        - Retrieves all active WebSocket session information
        - Calculates total session and user counts
        - Returns session details with summary statistics
        - Includes current timestamp for monitoring
        
    Raises:
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager methods not available
        
    Args:
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Session counts, session details, and timestamp
    """
    sessions = websocket_manager.get_all_sessions_info()
    
    # Calculate summary statistics
    total_users = len(websocket_manager.user_sessions)
    
    return {
        "total_sessions": len(sessions),
        "total_users": total_users,
        "sessions": sessions,
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/websocket-sessions/stats",
    summary     = "Get WebSocket statistics",
    description = "Return detailed connection statistics and subscription pattern breakdown."
)
async def get_websocket_stats(
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Get detailed statistics about WebSocket connections and subscription patterns.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - websocket_manager is properly initialized WebSocketManager
        - WebSocketManager has get_subscription_stats() method
        - WebSocketManager has get_connection_count() method
        - WebSocketManager has user_sessions attribute
        
    Ensures:
        - Retrieves comprehensive WebSocket connection statistics
        - Provides subscription pattern analysis and metrics
        - Returns connection and user counts with detailed breakdowns
        - Includes current timestamp for monitoring purposes
        
    Raises:
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager methods not available
        
    Args:
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Connection statistics, subscription stats, and timestamp
    """
    subscription_stats = websocket_manager.get_subscription_stats()
    
    return {
        "connection_count": websocket_manager.get_connection_count(),
        "user_count": len(websocket_manager.user_sessions),
        "subscription_stats": subscription_stats,
        "timestamp": du.get_current_datetime_iso()
    }

@router.post(
    "/websocket-sessions/cleanup",
    summary     = "Cleanup stale sessions",
    description = "Trigger manual cleanup of sessions older than specified max age."
)
async def cleanup_websocket_sessions(
    max_age_hours: Optional[int] = 24,
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Manually trigger cleanup of stale WebSocket sessions with age validation.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - websocket_manager is properly initialized WebSocketManager
        - max_age_hours is a non-negative integer (optional, defaults to 24)
        - WebSocketManager has cleanup_stale_sessions() method
        
    Ensures:
        - Validates max_age_hours is non-negative before processing
        - Performs cleanup of WebSocket sessions older than specified age
        - Returns count of sessions that were cleaned up
        - Includes cleanup parameters in response for verification
        
    Raises:
        - HTTPException with 400 status if max_age_hours is negative
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager cleanup method not available
        
    Args:
        max_age_hours: Maximum session age in hours before cleanup (default: 24)
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Number of sessions cleaned, age limit, and timestamp
    """
    if max_age_hours < 0:
        raise HTTPException(status_code=400, detail="max_age_hours must be positive")
    
    sessions_cleaned = websocket_manager.cleanup_stale_sessions(max_age_hours)
    
    return {
        "sessions_cleaned": sessions_cleaned,
        "max_age_hours": max_age_hours,
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/websocket-sessions/{session_id}",
    summary     = "Get session details",
    description = "Return detailed info for a specific WebSocket session by ID."
)
async def get_websocket_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Get detailed information about a specific WebSocket session by ID.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - session_id is a non-empty string identifier
        - websocket_manager is properly initialized WebSocketManager
        - WebSocketManager has get_session_info() method
        
    Ensures:
        - Looks up session information by session_id
        - Returns detailed session information if found
        - Raises 404 HTTPException if session not found
        - Provides comprehensive session details for monitoring
        
    Raises:
        - HTTPException with 404 status if session not found
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager methods not available
        
    Args:
        session_id: The unique session identifier to look up
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Detailed session information including metadata
    """
    session_info = websocket_manager.get_session_info(session_id)
    
    if not session_info:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return session_info

@router.delete(
    "/websocket-sessions/{session_id}",
    summary     = "Force disconnect session",
    description = "Forcefully disconnect a specific WebSocket session."
)
async def disconnect_websocket_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Forcefully disconnect a WebSocket session with connection verification.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - session_id is a non-empty string identifier
        - websocket_manager is properly initialized WebSocketManager
        - WebSocketManager has is_connected() and disconnect() methods
        
    Ensures:
        - Verifies session exists and is currently connected
        - Forcefully disconnects the specified WebSocket session
        - Returns confirmation with session ID and disconnection status
        - Raises 404 if session not found or already disconnected
        
    Raises:
        - HTTPException with 404 status if session not found or disconnected
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager methods not available
        
    Args:
        session_id: The unique session identifier to disconnect
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Session ID, disconnection status, and timestamp
    """
    if not websocket_manager.is_connected(session_id):
        raise HTTPException(status_code=404, detail="Session not found or already disconnected")
    
    websocket_manager.disconnect(session_id)
    
    return {
        "session_id": session_id,
        "status": "disconnected",
        "timestamp": du.get_current_datetime_iso()
    }

@router.put(
    "/websocket-sessions/single-session-policy",
    summary     = "Set single-session policy",
    description = "Enable or disable the single-session-per-user enforcement policy."
)
async def update_single_session_policy(
    enabled: bool,
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Enable or disable the single-session-per-user policy configuration.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - enabled is a boolean value (True or False)
        - websocket_manager is properly initialized WebSocketManager
        - WebSocketManager has set_single_session_policy() method
        
    Ensures:
        - Updates WebSocket manager single-session-per-user policy
        - Applies policy immediately to new connections
        - Returns confirmation of policy state change
        - Includes timestamp for policy change tracking
        
    Raises:
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager policy method not available
        - TypeError if enabled parameter is not boolean
        
    Args:
        enabled: Boolean flag to enable (True) or disable (False) policy
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Updated policy status and timestamp
    """
    websocket_manager.set_single_session_policy(enabled)
    
    return {
        "single_session_policy": enabled,
        "timestamp": du.get_current_datetime_iso()
    }

@router.get(
    "/websocket-events",
    summary     = "List available events",
    description = "Return sorted list of all available WebSocket event types."
)
async def get_available_events(
    current_user: dict = Depends(get_current_user),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    Get comprehensive list of available WebSocket event types for introspection.
    
    Requires:
        - Valid JWT authentication token in Authorization header
        - websocket_manager is properly initialized WebSocketManager
        - WebSocketManager has available_events attribute
        
    Ensures:
        - Retrieves all available WebSocket event types
        - Returns events in sorted order for consistent output
        - Provides total count of available events
        - Includes timestamp for event type inventory
        
    Raises:
        - HTTPException with 403 status if authentication fails
        - AttributeError if WebSocketManager available_events not accessible
        
    Args:
        current_user: Authenticated user information from JWT token
        websocket_manager: Injected WebSocket manager dependency
        
    Returns:
        dict: Sorted event list, total count, and timestamp
    """
    return {
        "available_events": sorted(list(websocket_manager.available_events)),
        "total_events": len(websocket_manager.available_events),
        "timestamp": du.get_current_datetime_iso()
    }