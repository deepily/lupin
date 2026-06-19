"""
Authentication Router for FastAPI.

Provides endpoints for user registration, login, token refresh,
logout, and user information retrieval.
"""

from fastapi import APIRouter, HTTPException, status, Header, Depends, Request
from typing import Optional, Dict

from cosa.rest.auth_models import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    RefreshRequest, RefreshResponse,
    LogoutRequest, LogoutResponse,
    UserResponse, TokenResponse,
    ErrorResponse,
    RequestVerificationRequest, VerifyEmailRequest,
    RequestPasswordResetRequest, ResetPasswordRequest,
    ChangePasswordRequest,
    MessageResponse
)
from cosa.rest.user_service import (
    create_user,
    authenticate_user,
    get_user_by_id,
    get_user_by_email,
    mark_email_verified,
    reset_password_with_token,
    update_user_password
)
from cosa.rest.jwt_service import (
    create_access_token,
    create_refresh_token,
    decode_and_validate_token
)
from cosa.rest.refresh_token_service import (
    store_refresh_token,
    rotate_refresh_token,
    revoke_refresh_token
)
from cosa.rest.email_service import (
    send_verification_email,
    send_password_reset_email
)
from cosa.rest.email_token_service import (
    generate_verification_token,
    validate_verification_token,
    generate_password_reset_token,
    validate_password_reset_token
)
from cosa.rest.rate_limiter import (
    check_account_lockout,
    record_failed_login,
    clear_failed_attempts
)
from cosa.rest.auth_audit import log_auth_event
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.auth_middleware import get_current_user as get_current_user_dependency

# Initialize router and config
router = APIRouter(
    prefix     = "/auth",
    tags       = ["Authentication"],
    responses  = {
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        400: {"model": ErrorResponse, "description": "Bad Request"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"}
    }
)

config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def _create_token_response( user_id: str, email: str, roles: list ) -> TokenResponse:
    """
    Create JWT token pair response.

    Requires:
        - user_id is valid UUID string
        - email is valid email address
        - roles is list of role strings

    Ensures:
        - Generates access and refresh tokens
        - Stores refresh token in database
        - Returns TokenResponse with expiration info

    Raises:
        - HTTPException if token generation fails

    Returns:
        TokenResponse: Token pair with metadata
    """
    try:
        # Generate tokens
        access_token = create_access_token( user_id, email, roles )
        refresh_token = create_refresh_token( user_id, email )

        # Store refresh token
        payload = decode_and_validate_token( refresh_token, expected_type="refresh" )
        jti = payload["jti"]

        success, message = store_refresh_token(
            user_id = user_id,
            token   = refresh_token,
            jti     = jti
        )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail      = f"Failed to store refresh token: {message}"
            )

        # Get token expiration from config
        expires_in = config_mgr.get(
            "jwt access token expire minutes",
            30,
            return_type="int"
        ) * 60  # Convert to seconds

        return TokenResponse(
            access_token  = access_token,
            refresh_token = refresh_token,
            token_type    = "bearer",
            expires_in    = expires_in
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Token generation failed: {str( e )}"
        )


def _user_dict_to_response( user_dict: dict ) -> UserResponse:
    """
    Convert user dictionary to UserResponse model.

    Requires:
        - user_dict contains required user fields

    Ensures:
        - Returns properly formatted UserResponse

    Returns:
        UserResponse: Pydantic model
    """
    return UserResponse(
        id              = user_dict["id"],
        email           = user_dict["email"],
        roles           = user_dict["roles"],
        email_verified  = user_dict["email_verified"],
        is_active       = user_dict["is_active"],
        created_at      = user_dict["created_at"],
        last_login_at   = user_dict.get( "last_login_at" )
    )


@router.post(
    "/register",
    response_model  = RegisterResponse,
    status_code     = status.HTTP_201_CREATED,
    summary         = "Register new user",
    description     = "Create new user account with email and password. Returns user info and JWT token pair."
)
async def register( request: RegisterRequest ) -> RegisterResponse:
    """
    Register new user account.

    Requires:
        - Valid email address
        - Password meeting strength requirements
        - Optional roles (defaults to ["user"])

    Ensures:
        - User created in database
        - Password hashed securely
        - JWT tokens generated and returned
        - Returns 201 on success
        - Returns 400 if validation fails

    Raises:
        - HTTPException 400 if email already exists
        - HTTPException 400 if password too weak
        - HTTPException 500 if registration fails

    Returns:
        RegisterResponse: User info and tokens
    """
    # Create user
    success, message, user_id = create_user(
        email    = request.email,
        password = request.password,
        roles    = request.roles
    )

    if not success:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = message
        )

    # Get user info
    user_dict = get_user_by_id( user_id )
    if not user_dict:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "User created but retrieval failed"
        )

    # Generate tokens
    tokens = _create_token_response(
        user_id = user_id,
        email   = request.email,
        roles   = user_dict["roles"]
    )

    return RegisterResponse(
        message = "User registered successfully",
        user    = _user_dict_to_response( user_dict ),
        tokens  = tokens
    )


@router.post(
    "/login",
    response_model  = LoginResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "User login",
    description     = "Authenticate user with email and password. Returns user info and JWT token pair. Includes rate limiting and account lockout (Phase 8)."
)
async def login( login_request: LoginRequest, request: Request ) -> LoginResponse:
    """
    Authenticate user and return tokens with rate limiting (Phase 8).

    Requires:
        - Valid email and password
        - User account is active
        - Account not locked due to failed attempts

    Ensures:
        - Account lockout checked
        - Credentials validated
        - Failed attempts recorded on failure
        - Failed attempts cleared on success
        - JWT tokens generated on success
        - All events logged to audit log
        - Returns 200 on success
        - Returns 401 if credentials invalid
        - Returns 429 if account locked

    Raises:
        - HTTPException 429 if account locked
        - HTTPException 401 if authentication fails
        - HTTPException 500 if login processing fails

    Returns:
        LoginResponse: User info and tokens
    """
    # Get client IP address
    client_ip = request.client.host if request.client else "unknown"

    # Check for account lockout (Phase 8)
    is_locked, unlock_time = check_account_lockout( login_request.email )

    if is_locked:
        log_auth_event(
            event_type  = "login_failure",
            email       = login_request.email,
            ip_address  = client_ip,
            details     = f"Account locked until {unlock_time}",
            success     = False
        )

        raise HTTPException(
            status_code = status.HTTP_429_TOO_MANY_REQUESTS,
            detail      = f"Account locked due to multiple failed attempts. Try again after {unlock_time}"
        )

    # Authenticate user
    success, message, user_dict = authenticate_user(
        email    = login_request.email,
        password = login_request.password
    )

    if not success:
        # Record failed attempt (Phase 8)
        record_failed_login( login_request.email, client_ip )

        # Log failed login (Phase 8)
        log_auth_event(
            event_type  = "login_failure",
            email       = login_request.email,
            ip_address  = client_ip,
            details     = message,
            success     = False
        )

        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = message
        )

    # Clear failed attempts on successful login (Phase 8)
    clear_failed_attempts( login_request.email )

    # Generate tokens
    tokens = _create_token_response(
        user_id = user_dict["id"],
        email   = user_dict["email"],
        roles   = user_dict["roles"]
    )

    # Log successful login (Phase 8)
    log_auth_event(
        event_type  = "login_success",
        user_id     = user_dict["id"],
        email       = user_dict["email"],
        ip_address  = client_ip,
        details     = "Login successful",
        success     = True
    )

    return LoginResponse(
        message = "Login successful",
        user    = _user_dict_to_response( user_dict ),
        tokens  = tokens
    )


@router.post(
    "/refresh",
    response_model  = RefreshResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Refresh access token",
    description     = "Exchange refresh token for new token pair. Old refresh token is revoked (token rotation)."
)
async def refresh( request: RefreshRequest ) -> RefreshResponse:
    """
    Refresh access token using refresh token.

    Implements token rotation security pattern:
    - Old refresh token is revoked
    - New refresh token is issued
    - New access token is issued

    Requires:
        - Valid, non-revoked refresh token

    Ensures:
        - Old token revoked
        - New token pair generated
        - Returns 200 on success
        - Returns 401 if token invalid/expired/revoked

    Raises:
        - HTTPException 401 if token invalid
        - HTTPException 500 if refresh fails

    Returns:
        RefreshResponse: New token pair
    """
    # Rotate token (validates, revokes old, issues new)
    success, message, new_refresh_token = rotate_refresh_token(
        old_token = request.refresh_token
    )

    if not success:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = message
        )

    # Decode new refresh token to get user info
    try:
        payload = decode_and_validate_token( new_refresh_token, expected_type="refresh" )
        user_id = payload["sub"]
        email = payload["email"]

        # Get user to get roles
        user_dict = get_user_by_id( user_id )
        if not user_dict:
            raise HTTPException(
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail      = "User not found"
            )

        # Generate new access token
        access_token = create_access_token( user_id, email, user_dict["roles"] )

        # Get token expiration from config
        expires_in = config_mgr.get(
            "jwt access token expire minutes",
            30,
            return_type="int"
        ) * 60  # Convert to seconds

        return RefreshResponse(
            message = "Token refreshed successfully",
            tokens  = TokenResponse(
                access_token  = access_token,
                refresh_token = new_refresh_token,
                token_type    = "bearer",
                expires_in    = expires_in
            )
        )

    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Token refresh failed: {str( e )}"
        )


@router.post(
    "/logout",
    response_model  = LogoutResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "User logout",
    description     = "Revoke refresh token to logout user. Access token remains valid until expiration."
)
async def logout( request: LogoutRequest ) -> LogoutResponse:
    """
    Logout user by revoking refresh token.

    Note: Access tokens remain valid until expiration (stateless JWT design).
    For immediate logout, client should discard access token.

    Requires:
        - Valid refresh token (may be expired)

    Ensures:
        - Refresh token revoked in database
        - Returns 200 on success
        - Returns 400 if token invalid

    Raises:
        - HTTPException 400 if token invalid
        - HTTPException 500 if logout fails

    Returns:
        LogoutResponse: Success message
    """
    try:
        # Decode token to get JTI
        payload = decode_and_validate_token( request.refresh_token, expected_type="refresh" )
        jti = payload["jti"]

        # Revoke token
        success, message = revoke_refresh_token( jti )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_400_BAD_REQUEST,
                detail      = message
            )

        return LogoutResponse( message="Logout successful" )

    except HTTPException:
        raise
    except Exception as e:
        # If token is expired, we can still try to revoke it
        # Extract JTI without validation
        try:
            import jwt
            unverified = jwt.decode(
                request.refresh_token,
                options={"verify_signature": False, "verify_exp": False}
            )
            jti = unverified.get( "jti" )

            if jti:
                success, message = revoke_refresh_token( jti )
                if success:
                    return LogoutResponse( message="Logout successful" )

        except Exception:
            pass

        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = f"Invalid token: {str( e )}"
        )


@router.get(
    "/me",
    response_model  = UserResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Get current user",
    description     = "Get current user information from access token. Requires Authorization header."
)
async def get_current_user( authorization: Optional[str] = Header( None ) ) -> UserResponse:
    """
    Get current user information from access token.

    Requires:
        - Authorization header with Bearer token
        - Valid, non-expired access token

    Ensures:
        - Token validated
        - User information returned
        - Returns 200 on success
        - Returns 401 if token missing/invalid

    Raises:
        - HTTPException 401 if no token provided
        - HTTPException 401 if token invalid/expired
        - HTTPException 404 if user not found

    Returns:
        UserResponse: Current user information
    """
    if not authorization:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Authorization header required"
        )

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len( parts ) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid authorization header format. Expected: Bearer <token>"
        )

    token = parts[1]

    # Validate access token
    try:
        payload = decode_and_validate_token( token, expected_type="access" )
        user_id = payload["sub"]

        # Get user info
        user_dict = get_user_by_id( user_id )
        if not user_dict:
            raise HTTPException(
                status_code = status.HTTP_404_NOT_FOUND,
                detail      = "User not found"
            )

        return _user_dict_to_response( user_dict )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = f"Token validation failed: {str( e )}"
        )


@router.put(
    "/change-password",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Change password",
    description     = "Change password for authenticated user. Requires current password verification."
)
async def change_password( request: ChangePasswordRequest, authorization: Optional[str] = Header( None ) ) -> MessageResponse:
    """
    Change password for authenticated user.

    Requires:
        - Valid JWT access token in Authorization header
        - Current password for verification
        - New password meeting strength requirements

    Ensures:
        - Current password is verified before change
        - Password strength validated
        - Password updated in database
        - Event logged for audit trail

    Raises:
        - HTTPException 401 if token missing/invalid
        - HTTPException 400 if current password incorrect
        - HTTPException 400 if new password too weak
        - HTTPException 404 if user not found

    Returns:
        MessageResponse: Success message
    """
    # Validate JWT token and get user
    if not authorization or not authorization.startswith( "Bearer " ):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Missing or invalid authorization header"
        )

    token = authorization.replace( "Bearer ", "" )

    try:
        payload = decode_and_validate_token( token )
        user_id = payload.get( "sub" )  # JWT standard: "sub" = subject (user_id)

        if not user_id:
            raise HTTPException(
                status_code = status.HTTP_401_UNAUTHORIZED,
                detail      = "Invalid token payload"
            )

    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = f"Token validation failed: {str( e )}"
        )

    # Update password
    success, message = update_user_password(
        user_id          = user_id,
        old_password     = request.current_password,
        new_password     = request.new_password
    )

    if not success:
        # Determine appropriate error status
        if "incorrect" in message.lower() or "invalid" in message.lower():
            status_code = status.HTTP_400_BAD_REQUEST
        elif "not found" in message.lower():
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code = status_code,
            detail      = message
        )

    # Log password change event (Phase 8)
    log_auth_event(
        event_type  = "password_change",
        user_id     = user_id,
        email       = payload.get( "email", "unknown" ),
        ip_address  = "unknown",  # Could extract from request if needed
        details     = "Password changed successfully",
        success     = True
    )

    return MessageResponse( message="Password changed successfully" )


# Phase 7: Email Verification & Password Reset Endpoints

@router.post(
    "/request-verification",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Request email verification",
    description     = "Resend email verification link to authenticated user."
)
async def request_verification( user: Dict = Depends( get_current_user_dependency ) ) -> MessageResponse:
    """
    Resend email verification email to authenticated user.

    Requires:
        - Valid access token (authenticated)
        - User account exists

    Ensures:
        - Generates new verification token
        - Sends verification email
        - Returns 200 on success
        - Returns 401 if not authenticated
        - Returns 400 if email already verified

    Raises:
        - HTTPException 400 if email already verified
        - HTTPException 500 if email sending fails

    Returns:
        MessageResponse: Success message
    """
    try:
        # Check if already verified
        if user.get( "email_verified" ):
            raise HTTPException(
                status_code = status.HTTP_400_BAD_REQUEST,
                detail      = "Email already verified"
            )

        # Generate verification token
        success, message, token = generate_verification_token( user["user_id"] )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail      = message
            )

        # Send verification email
        email_sent = send_verification_email(
            email     = user["email"],
            token     = token,
            user_name = user.get( "email", "" ).split( "@" )[0]
        )

        if not email_sent:
            raise HTTPException(
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail      = "Failed to send verification email"
            )

        return MessageResponse( message="Verification email sent successfully" )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Request verification failed: {str( e )}"
        )


@router.post(
    "/verify-email",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Verify email address",
    description     = "Verify email address using token from verification email."
)
async def verify_email( request: VerifyEmailRequest ) -> MessageResponse:
    """
    Verify user email address with token.

    Requires:
        - Valid verification token
        - Token not expired or already used

    Ensures:
        - Token validated
        - User email marked as verified
        - Token marked as used
        - Returns 200 on success
        - Returns 400 if token invalid/expired/used

    Raises:
        - HTTPException 400 if token invalid/expired/used
        - HTTPException 500 if verification fails

    Returns:
        MessageResponse: Success message
    """
    try:
        # Validate token
        success, message, user_id = validate_verification_token( request.token )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_400_BAD_REQUEST,
                detail      = message
            )

        # Mark email as verified
        success, message = mark_email_verified( user_id )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail      = message
            )

        return MessageResponse( message="Email verified successfully" )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Email verification failed: {str( e )}"
        )


@router.post(
    "/request-password-reset",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Request password reset",
    description     = "Send password reset email to user. Returns success even if email not found (security)."
)
async def request_password_reset( request: RequestPasswordResetRequest ) -> MessageResponse:
    """
    Request password reset email.

    Always returns success for security (don't reveal if email exists).

    Requires:
        - Valid email address

    Ensures:
        - If user exists, generates reset token and sends email
        - If user doesn't exist, returns success without sending (security)
        - Returns 200 always
        - Token expires in 1 hour

    Raises:
        - None (always returns success)

    Returns:
        MessageResponse: Success message
    """
    try:
        # Look up user by email
        user_dict = get_user_by_email( request.email )

        # Always return success for security (don't reveal if email exists)
        if not user_dict:
            return MessageResponse( message="If the email exists, a password reset link has been sent" )

        # Generate reset token
        success, message, token = generate_password_reset_token( user_dict["id"] )

        if not success:
            # Still return success to user for security
            return MessageResponse( message="If the email exists, a password reset link has been sent" )

        # Send reset email
        email_sent = send_password_reset_email(
            email     = user_dict["email"],
            token     = token,
            user_name = user_dict["email"].split( "@" )[0]
        )

        # Always return success for security
        return MessageResponse( message="If the email exists, a password reset link has been sent" )

    except Exception as e:
        # Even on error, return success for security
        return MessageResponse( message="If the email exists, a password reset link has been sent" )


@router.post(
    "/reset-password",
    response_model  = MessageResponse,
    status_code     = status.HTTP_200_OK,
    summary         = "Reset password",
    description     = "Reset password using token from password reset email."
)
async def reset_password( request: ResetPasswordRequest ) -> MessageResponse:
    """
    Reset password with reset token.

    Requires:
        - Valid password reset token
        - Token not expired or already used
        - New password meets strength requirements

    Ensures:
        - Token validated
        - Password strength validated
        - Password updated
        - Token marked as used
        - Returns 200 on success
        - Returns 400 if token invalid/expired/used
        - Returns 400 if password weak

    Raises:
        - HTTPException 400 if token invalid/expired/used
        - HTTPException 400 if password doesn't meet requirements
        - HTTPException 500 if password reset fails

    Returns:
        MessageResponse: Success message
    """
    try:
        # Validate reset token
        success, message, user_id = validate_password_reset_token( request.token )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_400_BAD_REQUEST,
                detail      = message
            )

        # Reset password
        success, message = reset_password_with_token( user_id, request.new_password )

        if not success:
            raise HTTPException(
                status_code = status.HTTP_400_BAD_REQUEST,
                detail      = message
            )

        return MessageResponse( message="Password reset successfully" )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Password reset failed: {str( e )}"
        )