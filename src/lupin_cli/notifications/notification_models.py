#!/usr/bin/env python3
"""
Pydantic models for notification requests and responses (Phase 2.3).

Provides type-safe validation for CLI and API interactions with the
Lupin notification system. These models ensure data integrity for
response-required notifications with SSE blocking.

Models:
    - NotificationRequest: Request parameters with field validation
    - SSE Events: RespondedEvent, ExpiredEvent, OfflineEvent, ErrorEvent
    - NotificationResponse: Typed response from notify_user_sync

Usage:
    from lupin_cli.notifications.notification_models import NotificationRequest

    request = NotificationRequest(
        message="Approve deployment?",
        response_type="yes_no",
        response_default="no"
    )
"""

from pydantic import BaseModel, Field, field_validator, EmailStr
from typing import Optional, Literal, Union
from enum import Enum
import re


# ============================================================================
# Helper Functions
# ============================================================================

def extract_sender_from_message( message: str, agent_type: str = "claude.code" ) -> Optional[str]:
    """
    Extract sender ID from message prefix like [LUPIN] or [COSA].

    Requires:
        - message is a string
        - agent_type is a valid agent identifier (e.g., "claude.code", "deep.research")

    Ensures:
        - Returns {agent_type}@{project}.deepily.ai if [PREFIX] found
        - Returns None if no prefix found
        - Project name is lowercased

    Examples:
        "[LUPIN] Build complete" -> "claude.code@lupin.deepily.ai"
        "[COSA] Tests passed"    -> "claude.code@cosa.deepily.ai"
        "[LUPIN] Research done", "deep.research" -> "deep.research@lupin.deepily.ai"
        "No prefix message"      -> None

    Args:
        message: Notification message text
        agent_type: Agent type identifier (default: "claude.code")

    Returns:
        str or None: Sender ID in email format, or None if no prefix
    """
    match = re.match( r'^\[([A-Z]+)\]', message )
    if match:
        project = match.group( 1 ).lower()
        return f"{agent_type}@{project}.deepily.ai"
    return None


def parse_sender_id( sender_id: str ) -> dict:
    """
    Parse sender_id into components (backward compatible).

    Requires:
        - sender_id is a string in format: agent@project.deepily.ai
          or agent@project.deepily.ai#session_id

    Ensures:
        - Returns dict with agent_type, project, session_id, full_sender_id, base_sender_id
        - session_id is None for old format (backward compatible)
        - Works with both old and new formats

    Examples:
        parse_sender_id( "claude.code@lupin.deepily.ai" )
        -> { "agent_type": "claude.code", "project": "lupin", "session_id": None, ... }

        parse_sender_id( "claude.code@lupin.deepily.ai#a1b2c3d4" )
        -> { "agent_type": "claude.code", "project": "lupin", "session_id": "a1b2c3d4", ... }

    Args:
        sender_id: Full sender_id string

    Returns:
        dict with parsed components
    """
    # Handle new format with session_id
    if "#" in sender_id:
        base, session_id = sender_id.rsplit( "#", 1 )
    else:
        base = sender_id
        session_id = None

    # Parse agent type and project
    try:
        agent_part, domain = base.split( "@", 1 )
        project = domain.split( "." )[ 0 ]
    except ( ValueError, IndexError ):
        agent_part = "unknown"
        project = "unknown"

    return {
        "agent_type"     : agent_part,
        "project"        : project,
        "session_id"     : session_id,
        "full_sender_id" : sender_id,
        "base_sender_id" : base
    }


# ============================================================================
# Enums (Type-Safe Choices)
# ============================================================================

class NotificationType(str, Enum):
    """Notification type enumeration."""
    TASK                   = "task"
    PROGRESS               = "progress"
    ALERT                  = "alert"
    CUSTOM                 = "custom"
    USER_INITIATED_MESSAGE = "user_initiated_message"


class NotificationPriority(str, Enum):
    """Notification priority enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ResponseType(str, Enum):
    """Response type for notifications."""
    YES_NO           = "yes_no"
    OPEN_ENDED       = "open_ended"
    MULTIPLE_CHOICE  = "multiple_choice"
    OPEN_ENDED_BATCH = "open_ended_batch"


# ============================================================================
# Request Model
# ============================================================================

class NotificationRequest(BaseModel):
    """
    Request model for response-required notifications.

    Validates all parameters before sending to Lupin API, ensuring
    data integrity and providing clear error messages for invalid input.

    Attributes:
        message: Notification message text (required, non-empty)
        response_type: Response type (yes_no or open_ended)
        notification_type: Type of notification (task, progress, alert, custom)
        priority: Priority level (low, medium, high, urgent)
        target_user: Target user email address
        timeout_seconds: Response timeout (1-600 seconds)
        response_default: Default response for timeout/offline
        title: Terse technical title for voice-first UX
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Notification message text"
    )

    response_type: ResponseType = Field(
        ...,
        description="Response type (yes_no or open_ended)"
    )

    notification_type: NotificationType = Field(
        default=NotificationType.CUSTOM,
        description="Notification type"
    )

    priority: NotificationPriority = Field(
        default=NotificationPriority.MEDIUM,
        description="Priority level"
    )

    target_user: Optional[str] = Field(
        default=None,
        description="Target user email address. Resolved from config/env at dispatch time if not set."
    )

    timeout_seconds: int = Field(
        default=120,
        ge=1,
        le=600,
        description="Response timeout in seconds (1-600)"
    )

    response_default: Optional[str] = Field(
        default=None,
        description="Default response value for timeout/offline"
    )

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Terse technical title for voice-first UX"
    )

    sender_id: Optional[str] = Field(
        default=None,
        pattern=r'^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#([a-f0-9]{8}|[a-z]+(-[a-z]+)*|[a-z]+-[a-f0-9]{8}))?$',
        description="Sender ID (e.g., claude.code@lupin.deepily.ai#a1b2c3d4, claude.code.job@lupin.deepily.ai#cc-a0ebba60). Supports 2+ word agent names, hex suffix, hyphenated topic, or job ID (prefix-hex)."
    )

    response_options: Optional[dict] = Field(
        default=None,
        description="Options for multiple_choice type. Structure: {questions: [{question, header, multi_select, options: [{label, description}]}]}"
    )

    abstract: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Supplementary context for the notification (plan details, URLs, markdown). Displayed alongside message in action-required cards."
    )

    session_name: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Human-readable session name (e.g., 'cats vs dogs comparison'). If provided, used instead of auto-generated name in UI."
    )

    job_id: Optional[str] = Field(
        default=None,
        pattern=r'^([a-z]+-[a-f0-9]{8}(::[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?|[a-f0-9]{64}(::[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?)$',
        description="Agentic job ID for routing notifications to job cards. Accepts short format (e.g., 'dr-a1b2c3d4'), compound short format (e.g., 'cc-e0b063cc::UUID'), SHA256 hash (64 hex chars), or compound hash (64 hex chars::UUID)."
    )

    suppress_ding: bool = Field(
        default=False,
        description="Suppress notification sound (ding) while still speaking message via TTS. Used for conversational TTS from queue operations where interruption ding is undesirable."
    )

    @field_validator( 'message' )
    @classmethod
    def message_not_whitespace( cls, v: str ) -> str:
        """
        Ensure message is not just whitespace.

        Requires:
            - v is a string

        Ensures:
            - Returns stripped string
            - Raises ValueError if whitespace-only

        Raises:
            - ValueError if message is empty after stripping
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError( 'Message cannot be empty or whitespace-only' )
        return stripped

    @field_validator( 'response_options' )
    @classmethod
    def validate_multiple_choice_options( cls, v: Optional[dict], info ) -> Optional[dict]:
        """
        Validate response_options for multiple_choice type.

        Requires:
            - v is None or a dict with 'questions' array
            - Each question has 'question', 'header', 'multi_select', 'options'
            - Each option has 'label' and optional 'description'

        Ensures:
            - Returns validated dict or None
            - Raises ValueError if structure is invalid

        Raises:
            - ValueError if options structure is malformed
        """
        if v is None:
            return v

        response_type = info.data.get( 'response_type' )
        if response_type == ResponseType.MULTIPLE_CHOICE:
            if 'questions' not in v or not isinstance( v['questions'], list ):
                raise ValueError( "response_options must have 'questions' array for multiple_choice type" )

            for i, q in enumerate( v['questions'] ):
                if not isinstance( q, dict ):
                    raise ValueError( f"Question {i} must be a dict" )
                if 'question' not in q:
                    raise ValueError( f"Question {i} missing 'question' field" )
                if 'options' not in q or not isinstance( q['options'], list ):
                    raise ValueError( f"Question {i} missing 'options' array" )
                if len( q['options'] ) < 2 or len( q['options'] ) > 20:
                    raise ValueError( f"Question {i} must have 2-20 options" )
                for j, opt in enumerate( q['options'] ):
                    if not isinstance( opt, dict ) or 'label' not in opt:
                        raise ValueError( f"Question {i} option {j} must have 'label'" )

        elif response_type == ResponseType.OPEN_ENDED_BATCH:
            if 'questions' not in v or not isinstance( v['questions'], list ):
                raise ValueError( "response_options must have 'questions' array for open_ended_batch type" )

            for i, q in enumerate( v['questions'] ):
                if not isinstance( q, dict ):
                    raise ValueError( f"Question {i} must be a dict" )
                if 'question' not in q:
                    raise ValueError( f"Question {i} missing 'question' field" )

        return v

    @field_validator( 'response_default' )
    @classmethod
    def validate_yes_no_default( cls, v: Optional[str], info ) -> Optional[str]:
        """
        For yes_no type, default must be 'yes' or 'no'.

        Requires:
            - v is None or a string
            - info contains validated field data

        Ensures:
            - For yes_no type: returns 'yes', 'no', or None
            - For open_ended type: returns any string or None
            - Raises ValueError for invalid yes_no defaults

        Raises:
            - ValueError if yes_no default is not 'yes' or 'no'
        """
        if v is not None:
            response_type = info.data.get( 'response_type' )
            if response_type == ResponseType.YES_NO:
                if v not in ('yes', 'no'):
                    raise ValueError(
                        "For yes_no type, response_default must be 'yes' or 'no'"
                    )
        return v

    def to_api_params( self ) -> dict:
        """
        Convert to API query parameters for /api/notify endpoint.

        Phase 2.5: API key authentication moved to X-API-Key header.

        Requires:
            - All model fields are validated

        Ensures:
            - Returns dict with all required parameters
            - Converts enums to string values
            - Includes optional parameters if set
            - Excludes None values for cleaner API calls
            - Does NOT include api_key (moved to headers in Phase 2.5)

        Returns:
            dict: Query parameters for requests.post()
        """
        if self.target_user is None:
            raise ValueError(
                "target_user is None at serialization time. "
                "Resolve via resolve_target_user() before calling to_api_params()."
            )

        params = {
            "message"            : self.message,
            "type"               : self.notification_type.value,
            "priority"           : self.priority.value,
            "target_user"        : self.target_user,
            "response_requested" : "true",
            "response_type"      : self.response_type.value,
            "timeout_seconds"    : self.timeout_seconds
        }

        # Add optional parameters
        if self.response_default is not None:
            params["response_default"] = self.response_default

        if self.title is not None:
            params["title"] = self.title

        # Sender ID: explicit > extracted from message > None (API will use default)
        resolved_sender_id = self.sender_id
        if not resolved_sender_id:
            resolved_sender_id = extract_sender_from_message( self.message )
        if resolved_sender_id:
            params["sender_id"] = resolved_sender_id

        # Add response_options for multiple_choice type (JSON serialized)
        if self.response_options is not None:
            import json
            params["response_options"] = json.dumps( self.response_options )

        # Add abstract for supplementary context
        if self.abstract is not None:
            params["abstract"] = self.abstract

        # Add session_name for UI display
        if self.session_name is not None:
            params["session_name"] = self.session_name

        # Add job_id for routing to job cards
        if self.job_id is not None:
            params["job_id"] = self.job_id

        # Add suppress_ding for conversational TTS (skip notification sound)
        if self.suppress_ding:
            params["suppress_ding"] = "true"

        return params


# ============================================================================
# SSE Event Models
# ============================================================================

class SSEEventBase(BaseModel):
    """Base model for all SSE events."""
    status: str


class RespondedEvent(SSEEventBase):
    """
    User responded to notification (success case).

    Attributes:
        status: Always "responded"
        response: User's response value (yes/no or text)
        default_used: Whether default value was used (always False)
    """
    status: Literal["responded"] = "responded"
    response: str
    default_used: bool = False


class ExpiredEvent(SSEEventBase):
    """
    Notification expired due to timeout.

    Attributes:
        status: Always "expired"
        response: Default value if provided, None otherwise
        default_used: True if default provided, False otherwise
        timeout: Always True (indicates timeout occurred)
    """
    status: Literal["expired"] = "expired"
    response: Optional[str]
    default_used: bool
    timeout: bool = True


class OfflineEvent(SSEEventBase):
    """
    User was offline, used default value immediately.

    Attributes:
        status: Always "offline"
        response: Default value (required for offline)
        default_used: Always True
    """
    status: Literal["offline"] = "offline"
    response: str
    default_used: bool = True


class ErrorEvent(SSEEventBase):
    """
    Server error occurred during processing.

    Attributes:
        status: Always "error"
        message: Error description
        response: Always None (no response on error)
    """
    status: Literal["error"] = "error"
    message: str
    response: Optional[str] = None


# Union type for all possible SSE events
SSEEvent = Union[RespondedEvent, ExpiredEvent, OfflineEvent, ErrorEvent]


# ============================================================================
# Response Model
# ============================================================================

class NotificationResponse(BaseModel):
    """
    Response from notify_user_sync function.

    Encapsulates the result of a synchronous notification request,
    including the user's response value, exit code, and metadata.

    Attributes:
        response_value: User's response (str) or None on error
        exit_code: 0=success, 1=error, 2=timeout
        status: Event status (responded, expired, offline, error)
        default_used: Whether default value was used
        is_timeout: Whether notification timed out
    """

    response_value: Optional[str] = Field(
        default=None,
        description="User's response value or None on error"
    )

    exit_code: int = Field(
        ...,
        ge=0,
        le=2,
        description="Exit code: 0=success, 1=error, 2=timeout"
    )

    status: Optional[str] = Field(
        default=None,
        description="Event status (responded, expired, offline, error)"
    )

    default_used: bool = Field(
        default=False,
        description="Whether default value was used"
    )

    is_timeout: bool = Field(
        default=False,
        description="Whether notification timed out"
    )

    @property
    def success( self ) -> bool:
        """
        Whether notification was successful.

        Requires:
            - exit_code is 0, 1, or 2

        Ensures:
            - Returns True if exit_code == 0
            - Returns False otherwise

        Returns:
            bool: True if successful (exit_code 0)
        """
        return self.exit_code == 0

    @property
    def is_error( self ) -> bool:
        """
        Whether an error occurred.

        Requires:
            - exit_code is 0, 1, or 2

        Ensures:
            - Returns True if exit_code == 1
            - Returns False otherwise

        Returns:
            bool: True if error (exit_code 1)
        """
        return self.exit_code == 1


# ============================================================================
# Async (Fire-and-Forget) Models - Phase 2.4
# ============================================================================

class AsyncNotificationRequest(BaseModel):
    """
    Request model for fire-and-forget (async) notifications.

    Simpler than NotificationRequest - no response_type or timeout fields
    since async notifications don't wait for responses.

    Attributes:
        message: Notification message text (required, non-empty)
        notification_type: Type of notification (task, progress, alert, custom)
        priority: Priority level (low, medium, high, urgent)
        target_user: Target user email address
        timeout: HTTP request timeout in seconds (1-30)
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Notification message text"
    )

    notification_type: NotificationType = Field(
        default=NotificationType.CUSTOM,
        description="Notification type"
    )

    priority: NotificationPriority = Field(
        default=NotificationPriority.MEDIUM,
        description="Priority level"
    )

    target_user: Optional[str] = Field(
        default=None,
        description="Target user email address. Resolved from config/env at dispatch time if not set."
    )

    timeout: int = Field(
        default=5,
        ge=1,
        le=30,
        description="HTTP request timeout in seconds (1-30)"
    )

    sender_id: Optional[str] = Field(
        default=None,
        pattern=r'^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#([a-f0-9]{8}|[a-z]+(-[a-z]+)*|[a-z]+-[a-f0-9]{8}))?$',
        description="Sender ID (e.g., claude.code@lupin.deepily.ai#a1b2c3d4, claude.code.job@lupin.deepily.ai#cc-a0ebba60). Supports 2+ word agent names, hex suffix, hyphenated topic, or job ID (prefix-hex)."
    )

    abstract: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Supplementary context for the notification (plan details, URLs, markdown). Displayed alongside message in action-required cards."
    )

    session_name: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Human-readable session name (e.g., 'cats vs dogs comparison'). If provided, used instead of auto-generated name in UI."
    )

    job_id: Optional[str] = Field(
        default=None,
        pattern=r'^([a-z]+-[a-f0-9]{8}(::[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?|[a-f0-9]{64}(::[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?)$',
        description="Agentic job ID for routing notifications to job cards. Accepts short format (e.g., 'dr-a1b2c3d4'), compound short format (e.g., 'cc-e0b063cc::UUID'), SHA256 hash (64 hex chars), or compound hash (64 hex chars::UUID)."
    )

    suppress_ding: bool = Field(
        default=False,
        description="Suppress notification sound (ding) while still speaking message via TTS. Used for conversational TTS from queue operations where interruption ding is undesirable."
    )

    queue_name: Optional[str] = Field(
        default=None,
        pattern=r'^(run|todo|done|dead)$',
        description="Queue where job is running (run/todo/done/dead). Used for provisional job card registration when notifications arrive before job is fetched."
    )

    progress_group_id: Optional[str] = Field(
        default=None,
        pattern=r'^[a-z]{2,3}-[a-f0-9]{6,8}(-\d+)?$',
        description="Progress group ID for in-place DOM updates. Format: {prefix}-{hex} or {prefix}-{hex}-{batch}. Supports pg-XXXXXXXX (existing) and pr-XXXXXXXX-N+ (proxy batches, unbounded)."
    )

    @field_validator( 'message' )
    @classmethod
    def message_not_whitespace( cls, v: str ) -> str:
        """
        Ensure message is not just whitespace.

        Requires:
            - v is a string

        Ensures:
            - Returns stripped string
            - Raises ValueError if whitespace-only

        Raises:
            - ValueError if message is empty after stripping
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError( 'Message cannot be empty or whitespace-only' )
        return stripped

    def to_api_params( self ) -> dict:
        """
        Convert to API query parameters for /api/notify endpoint.

        Phase 2.5: API key authentication moved to X-API-Key header.

        Requires:
            - All model fields are validated

        Ensures:
            - Returns dict with all required parameters
            - Converts enums to string values
            - Does NOT include response_requested (fire-and-forget mode)
            - Does NOT include api_key (moved to headers in Phase 2.5)

        Returns:
            dict: Query parameters for requests.post()
        """
        if self.target_user is None:
            raise ValueError(
                "target_user is None at serialization time. "
                "Resolve via resolve_target_user() before calling to_api_params()."
            )

        params = {
            "message"     : self.message,
            "type"        : self.notification_type.value,
            "priority"    : self.priority.value,
            "target_user" : self.target_user
        }

        # Sender ID: explicit > extracted from message > None (API will use default)
        resolved_sender_id = self.sender_id
        if not resolved_sender_id:
            resolved_sender_id = extract_sender_from_message( self.message )
        if resolved_sender_id:
            params["sender_id"] = resolved_sender_id

        # Add abstract for supplementary context
        if self.abstract is not None:
            params["abstract"] = self.abstract

        # Add session_name for UI display
        if self.session_name is not None:
            params["session_name"] = self.session_name

        # Add job_id for routing to job cards
        if self.job_id is not None:
            params["job_id"] = self.job_id

        # Add suppress_ding for conversational TTS (skip notification sound)
        if self.suppress_ding:
            params["suppress_ding"] = "true"

        # Add queue_name for provisional job card registration
        if self.queue_name is not None:
            params["queue_name"] = self.queue_name

        # Add progress_group_id for in-place DOM updates
        if self.progress_group_id is not None:
            params["progress_group_id"] = self.progress_group_id

        return params


class AsyncNotificationResponse(BaseModel):
    """
    Response from async notification (fire-and-forget).

    More informative than simple bool return - captures delivery status,
    connection count, and error details.

    Attributes:
        success: Whether notification was sent successfully
        status: Status code (queued, user_not_available, error, etc.)
        message: Status message or error description
        target_user: Target user email address
        target_system_id: System UUID if user found
        connection_count: Number of active WebSocket connections
    """

    success: bool = Field(
        ...,
        description="Whether notification was sent successfully"
    )

    status: str = Field(
        ...,
        description="Status: queued, user_not_available, error, connection_error, timeout"
    )

    message: Optional[str] = Field(
        default=None,
        description="Status message or error description"
    )

    target_user: str = Field(
        ...,
        description="Target user email address"
    )

    target_system_id: Optional[str] = Field(
        default=None,
        description="System UUID if user found"
    )

    connection_count: int = Field(
        default=0,
        ge=0,
        description="Number of active WebSocket connections"
    )

    @property
    def is_queued( self ) -> bool:
        """
        Whether notification was queued for delivery.

        Requires:
            - status is a valid status string

        Ensures:
            - Returns True if status == "queued"
            - Returns False otherwise

        Returns:
            bool: True if notification was queued successfully
        """
        return self.status == "queued"

    @property
    def is_error( self ) -> bool:
        """
        Whether an error occurred.

        Requires:
            - status is a valid status string

        Ensures:
            - Returns True for error statuses
            - Returns False for success statuses

        Returns:
            bool: True if error occurred
        """
        return self.status in ("error", "connection_error", "timeout")


# ============================================================================
# Target User Resolution
# ============================================================================

def resolve_target_user( explicit_value: Optional[str] = None ) -> str:
    """
    Resolve target user email using precedence chain.

    Requires:
        - At least one source provides a non-empty email

    Ensures:
        - Returns email string from highest-priority source
        - Raises ValueError if no source provides an email

    Precedence:
        1. explicit_value (caller-provided)
        2. LUPIN_DEV_EMAIL env var
        3. ~/.notifications/config -> global_notification_recipient
        4. ValueError (fail loud)

    Args:
        explicit_value: Caller-provided email (highest priority)

    Returns:
        str: Resolved email address

    Raises:
        ValueError: If no source provides an email
    """
    import os

    # 1. Explicit value from caller
    if explicit_value:
        return explicit_value

    # 2. Environment variable
    env_email = os.getenv( "LUPIN_DEV_EMAIL" )
    if env_email:
        return env_email

    # 3. Config file via config_loader
    try:
        from cosa.utils.config_loader import get_api_config
        env = os.getenv( "LUPIN_ENV", "local" )
        config = get_api_config( env )
        config_email = config.get( "global_notification_recipient" )
        if config_email:
            return config_email
    except Exception:
        pass  # Config loading failed — fall through to error

    # 4. Fail loud
    raise ValueError(
        "Cannot resolve target_user. Set one of:\n"
        "  1. Pass target_user explicitly\n"
        "  2. Set LUPIN_DEV_EMAIL environment variable\n"
        "  3. Configure global_notification_recipient in ~/.notifications/config"
    )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for notification_models - validates Pydantic models and job_id field.

    Tests:
        1. NotificationRequest basic creation
        2. AsyncNotificationRequest basic creation
        3. job_id validation (valid patterns)
        4. job_id validation (invalid patterns - should reject)
        5. job_id inclusion in to_api_params()
        6. sender_id validation patterns
        7. Response models creation
    """
    import cosa.utils.util as cu
    from pydantic import ValidationError

    cu.print_banner( "Notification Models Smoke Test", prepend_nl=True )

    tests_passed = 0
    tests_failed = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Test 1: NotificationRequest basic creation
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n1. Testing NotificationRequest basic creation..." )
    try:
        req = NotificationRequest(
            message="Test message",
            response_type=ResponseType.YES_NO
        )
        assert req.message == "Test message"
        assert req.response_type == ResponseType.YES_NO
        assert req.job_id is None  # Default
        print( "   ✓ NotificationRequest created successfully" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Test 2: AsyncNotificationRequest basic creation
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n2. Testing AsyncNotificationRequest basic creation..." )
    try:
        async_req = AsyncNotificationRequest(
            message="Async test message"
        )
        assert async_req.message == "Async test message"
        assert async_req.job_id is None  # Default
        print( "   ✓ AsyncNotificationRequest created successfully" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Test 3: job_id validation - valid patterns
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n3. Testing job_id validation (valid patterns)..." )
    valid_job_ids = [
        "dr-a1b2c3d4",      # Deep Research prefix (short format)
        "pod-12345678",     # Podcast prefix (short format)
        "aj-abcdef01",      # Agentic job prefix (short format)
        "x-00000000",       # Single letter prefix (short format)
        "61d021320bed364e82d50af9128ddf8e1a63d8680d76ec06b1b03e27d8dee435",  # SHA256 hash (queue job format)
        "0" * 64,           # All zeros SHA256 (edge case)
        "f" * 64,           # All f's SHA256 (edge case)
        # Compound short format (prefix-hex8::UUID) - Session 230 speculative job IDs
        "cc-e0b063cc::0cf47e2d-d5a1-4cd4-addf-79810fd32b15",
        "swe-abcd1234::a1b2c3d4-e5f6-7890-abcd-ef0123456789",
        "dr-12345678::00000000-0000-0000-0000-000000000000",
        # Compound hash format (SHA256::UUID) - Session 108 user-scoped job IDs
        "2cd3847c0e234a8077b7ed28f9a5c3e1b4d6a7890abcdef0123456789ab4b7c4::0cf47e2d-d5a1-4cd4-addf-79810fd32b15",
        "61d021320bed364e82d50af9128ddf8e1a63d8680d76ec06b1b03e27d8dee435::a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6",
        "0" * 64 + "::00000000-0000-0000-0000-000000000000",  # Edge case: all zeros compound
    ]
    all_valid_passed = True
    for job_id in valid_job_ids:
        try:
            req = NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                job_id=job_id
            )
            assert req.job_id == job_id
            print( f"   ✓ Valid job_id accepted: {job_id}" )
        except ValidationError as e:
            print( f"   ✗ Valid job_id rejected: {job_id} - {e}" )
            all_valid_passed = False

    if all_valid_passed:
        tests_passed += 1
    else:
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Test 4: job_id validation - invalid patterns (should reject)
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n4. Testing job_id validation (invalid patterns - should reject)..." )
    invalid_job_ids = [
        "DR-a1b2c3d4",      # Uppercase prefix (invalid)
        "dr_a1b2c3d4",      # Underscore instead of hyphen
        "dr-a1b2c3d",       # Too short (7 hex chars for short format)
        "dr-a1b2c3d4e",     # Too long (9 hex chars for short format)
        "dr-ABCDEF01",      # Uppercase hex (invalid)
        "123-a1b2c3d4",     # Numeric prefix (invalid)
        "dr-ghijklmn",      # Non-hex characters
        "",                 # Empty string
        "a" * 63,           # SHA256 too short (63 chars)
        "a" * 65,           # SHA256 too long (65 chars)
        "A" * 64,           # SHA256 uppercase (invalid)
        "g" * 64,           # SHA256 non-hex characters
        # Invalid compound short formats
        "dr-a1b2c3d4:a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6",   # Single colon in short compound
        "dr-a1b2c3d4::a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",      # UUID without hyphens in short compound
        "dr-a1b2c3d4::a1b2c3d4-e5f6-a7b8-c9d0",                # Truncated UUID in short compound
        # Invalid compound hash formats
        "a" * 64 + ":a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6",   # Single colon (should be ::)
        "a" * 64 + "::a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",      # UUID without hyphens
        "a" * 64 + "::a1b2c3d4-e5f6-a7b8-c9d0",                # Truncated UUID
        "a" * 63 + "::a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6",  # SHA256 one char short in compound
    ]
    all_invalid_rejected = True
    for job_id in invalid_job_ids:
        try:
            req = NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                job_id=job_id
            )
            print( f"   ✗ Invalid job_id accepted (should reject): {job_id}" )
            all_invalid_rejected = False
        except ValidationError:
            print( f"   ✓ Invalid job_id correctly rejected: {job_id!r}" )

    if all_invalid_rejected:
        tests_passed += 1
    else:
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Test 5: job_id inclusion in to_api_params()
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n5. Testing job_id inclusion in to_api_params()..." )
    try:
        # Test NotificationRequest
        req_with_job = NotificationRequest(
            message="Test with job_id",
            response_type=ResponseType.YES_NO,
            target_user="test@example.com",
            job_id="dr-a1b2c3d4"
        )
        params = req_with_job.to_api_params()
        assert "job_id" in params, "job_id missing from params"
        assert params["job_id"] == "dr-a1b2c3d4"
        print( "   ✓ NotificationRequest.to_api_params() includes job_id" )

        # Test AsyncNotificationRequest
        async_req_with_job = AsyncNotificationRequest(
            message="Async test with job_id",
            target_user="test@example.com",
            job_id="pod-12345678"
        )
        async_params = async_req_with_job.to_api_params()
        assert "job_id" in async_params, "job_id missing from async params"
        assert async_params["job_id"] == "pod-12345678"
        print( "   ✓ AsyncNotificationRequest.to_api_params() includes job_id" )

        # Test None job_id is excluded
        req_no_job = NotificationRequest(
            message="Test without job_id",
            response_type=ResponseType.YES_NO,
            target_user="test@example.com"
        )
        params_no_job = req_no_job.to_api_params()
        assert "job_id" not in params_no_job, "job_id should not be in params when None"
        print( "   ✓ None job_id correctly excluded from params" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Test 6: sender_id validation patterns
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n6. Testing sender_id validation patterns..." )
    valid_sender_ids = [
        "claude.code@lupin.deepily.ai",
        "claude.code@lupin.deepily.ai#a1b2c3d4",
        "deep.research@lupin.deepily.ai#cli",
        "podcast.gen@cosa.deepily.ai#cats-vs-dogs",
        "deep.research@lupin.deepily.ai#dr-a0ebba60",  # Job ID format (prefix-hex)
        "podcast.gen@lupin.deepily.ai#pod-12345678",   # Another job ID format
        "claude.code.job@lupin.deepily.ai",            # 3-word agent name (no session)
        "claude.code.job@lupin.deepily.ai#cc-a1b2c3d4",  # 3-word agent name with job ID
    ]
    all_sender_valid = True
    for sender_id in valid_sender_ids:
        try:
            req = NotificationRequest(
                message="Test",
                response_type=ResponseType.YES_NO,
                sender_id=sender_id
            )
            print( f"   ✓ Valid sender_id accepted: {sender_id}" )
        except ValidationError as e:
            print( f"   ✗ Valid sender_id rejected: {sender_id}" )
            all_sender_valid = False

    if all_sender_valid:
        tests_passed += 1
    else:
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Test 7: Response models creation
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n7. Testing response models creation..." )
    try:
        # NotificationResponse
        response = NotificationResponse(
            response_value="yes",
            exit_code=0,
            status="responded"
        )
        assert response.success is True
        assert response.is_error is False
        print( "   ✓ NotificationResponse created successfully" )

        # AsyncNotificationResponse
        async_response = AsyncNotificationResponse(
            success=True,
            status="queued",
            target_user="test@example.com",
            connection_count=2
        )
        assert async_response.is_queued is True
        assert async_response.is_error is False
        print( "   ✓ AsyncNotificationResponse created successfully" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    print( "\n" + "=" * 60 )
    print( f"Smoke Test Results: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )

    if tests_failed == 0:
        print( "\n✓ All smoke tests passed!" )
        return True
    else:
        print( f"\n✗ {tests_failed} test(s) failed" )
        return False


if __name__ == "__main__":
    quick_smoke_test()
