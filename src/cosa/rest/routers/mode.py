"""
Mode management API endpoints.

Allows users to switch between agent-specific modes for direct routing.
When in a mode, all user input bypasses the LLM router and routes directly
to the selected agent.

Generated on: 2026-01-12
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from cosa.rest.auth import get_current_user
from cosa.rest.todo_fifo_queue import MODE_METADATA

router = APIRouter( prefix="/api/mode", tags=["mode"] )


# ============================================================================
# Request/Response Models
# ============================================================================

class ModeSetRequest( BaseModel ):
    """Request body for setting user mode."""
    mode: Optional[str] = None  # None = system mode


class ModeResponse( BaseModel ):
    """Response for mode queries."""
    user_id       : str
    mode          : Optional[str]
    display_name  : str
    is_system_mode: bool


class ModeChangeResponse( ModeResponse ):
    """Response for mode changes."""
    previous_mode: Optional[str]
    message      : str


class ModeInfo( BaseModel ):
    """Information about a single mode."""
    key         : str
    display_name: str
    description : str


class AvailableModesResponse( BaseModel ):
    """Response for listing available modes."""
    modes: List[ModeInfo]


# ============================================================================
# Dependencies
# ============================================================================

def get_todo_queue():
    """
    Dependency to get todo queue from main module.

    Requires:
        - fastapi_app.main module is available
        - main_module has jobs_todo_queue attribute

    Ensures:
        - Returns the todo queue instance with mode management methods

    Raises:
        - ImportError if main module not available
        - AttributeError if todo queue not found
    """
    import fastapi_app.main as main_module
    return main_module.jobs_todo_queue


def _get_display_name( mode: Optional[str] ) -> str:
    """
    Get display name for a mode.

    Requires:
        - mode is None or a valid mode key

    Ensures:
        - Returns "System" for None
        - Returns display_name from MODE_METADATA if found
        - Falls back to title-cased mode key
    """
    if mode is None:
        return "System"

    if mode in MODE_METADATA:
        return MODE_METADATA[ mode ][ "display_name" ]

    return mode.title()


# ============================================================================
# Endpoints
# ============================================================================

@router.get(
    "/available",
    response_model = AvailableModesResponse,
    summary        = "List available modes",
    description    = "List all selectable agent modes including system mode."
)
async def get_available_modes(
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue )
):
    """
    Get list of available modes.

    Returns all modes that can be selected, including system mode.
    """
    modes_data = todo_queue.get_available_modes()

    modes = [ ModeInfo( **m ) for m in modes_data ]

    return AvailableModesResponse( modes=modes )


@router.get(
    "/current",
    response_model = ModeResponse,
    summary        = "Get current mode",
    description    = "Return the authenticated user's current agent mode."
)
async def get_mode(
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue )
):
    """
    Get current mode for the authenticated user.

    Returns the user's current mode or system mode if not set.
    Uses current_user["uid"] (system ID) for consistent identification
    across the codebase.
    """
    user_id      = current_user[ "uid" ]
    mode         = todo_queue.get_user_mode( user_id )
    display_name = _get_display_name( mode )

    return ModeResponse(
        user_id       =user_id,
        mode          =mode,
        display_name  =display_name,
        is_system_mode=( mode is None )
    )


@router.post(
    "/current",
    response_model = ModeChangeResponse,
    summary        = "Set current mode",
    description    = "Set the user's agent mode to a specific key or null for system mode."
)
async def set_mode(
    request     : ModeSetRequest,
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue )
):
    """
    Set mode for the authenticated user.

    Set mode to a specific agent (e.g., "math", "calendar") or None for system mode.
    Uses current_user["uid"] (system ID) for consistent identification
    across the codebase.
    """
    user_id = current_user[ "uid" ]

    try:
        previous = todo_queue.set_user_mode( user_id, request.mode )
    except ValueError as e:
        raise HTTPException( status_code=400, detail=str( e ) )

    display_name = _get_display_name( request.mode )

    return ModeChangeResponse(
        user_id       =user_id,
        mode          =request.mode,
        display_name  =display_name,
        is_system_mode=( request.mode is None ),
        previous_mode =previous,
        message       =f"Mode changed to {display_name}"
    )


@router.delete(
    "/current",
    response_model = ModeChangeResponse,
    summary        = "Clear current mode",
    description    = "Clear the user's agent mode back to system default."
)
async def clear_mode(
    current_user = Depends( get_current_user ),
    todo_queue   = Depends( get_todo_queue )
):
    """
    Clear mode for the authenticated user (return to system mode).

    Equivalent to POST with mode=null, but more explicit.
    Uses current_user["uid"] (system ID) for consistent identification
    across the codebase.
    """
    user_id  = current_user[ "uid" ]
    previous = todo_queue.clear_user_mode( user_id )

    return ModeChangeResponse(
        user_id       =user_id,
        mode          =None,
        display_name  ="System",
        is_system_mode=True,
        previous_mode =previous,
        message       ="Returned to System mode"
    )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test to validate mode router imports and models."""
    import cosa.utils.util as du

    du.print_banner( "Mode Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import the router
        print( "Testing router import..." )
        assert router is not None
        assert router.prefix == "/api/mode"
        print( "✓ Router imported successfully" )

        # Test 2: Test Pydantic models
        print( "\nTesting Pydantic models..." )

        req = ModeSetRequest( mode="math" )
        assert req.mode == "math"
        print( "✓ ModeSetRequest works" )

        # Note: user_id is now system ID format (e.g., "ricardo_felipe_ruiz_6bdc")
        # not email format, to align with all other routers
        resp = ModeResponse(
            user_id="test_user_abc123",
            mode="math",
            display_name="Math Agent",
            is_system_mode=False
        )
        assert resp.user_id == "test_user_abc123"
        print( "✓ ModeResponse works" )

        change_resp = ModeChangeResponse(
            user_id="test_user_abc123",
            mode="calendar",
            display_name="Calendar",
            is_system_mode=False,
            previous_mode="math",
            message="Mode changed to Calendar"
        )
        assert change_resp.previous_mode == "math"
        print( "✓ ModeChangeResponse works" )

        mode_info = ModeInfo(
            key="math",
            display_name="Math Agent",
            description="Direct math calculations"
        )
        assert mode_info.key == "math"
        print( "✓ ModeInfo works" )

        # Test 3: Test display name helper
        print( "\nTesting _get_display_name()..." )
        assert _get_display_name( None ) == "System"
        assert _get_display_name( "math" ) == "Math Agent"
        assert _get_display_name( "unknown" ) == "Unknown"
        print( "✓ _get_display_name() works" )

        # Test 4: List endpoints
        print( "\nRegistered endpoints:" )
        for route in router.routes:
            print( f"  {route.methods} {route.path}" )

    except Exception as e:
        print( f"✗ Error: {e}" )
        import traceback
        traceback.print_exc()

    print( "\n✓ Mode router smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
