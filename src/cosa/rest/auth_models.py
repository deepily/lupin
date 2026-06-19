"""
Pydantic Models for Authentication Endpoints.

Request and response models for user registration, login,
token refresh, and user information endpoints.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from datetime import datetime


# Request Models

class RegisterRequest( BaseModel ):
    """
    User registration request.

    Requires:
        - email: Valid email address
        - password: String (will be validated for strength)
        - roles: Optional list of roles (defaults to ["user"])
    """
    email: EmailStr = Field(
        ...,
        description="User email address",
        example="user@example.com"
    )
    password: str = Field(
        ...,
        min_length=8,
        description="User password (min 8 chars, must meet strength requirements)",
        example="SecurePass123!"
    )
    roles: Optional[List[str]] = Field(
        default=None,
        description="User roles (defaults to ['user'])",
        example=["user"]
    )


class LoginRequest( BaseModel ):
    """
    User login request.

    Requires:
        - email: User email address
        - password: User password
    """
    email: EmailStr = Field(
        ...,
        description="User email address",
        example="user@example.com"
    )
    password: str = Field(
        ...,
        description="User password",
        example="SecurePass123!"
    )


class RefreshRequest( BaseModel ):
    """
    Token refresh request.

    Requires:
        - refresh_token: Valid refresh token JWT
    """
    refresh_token: str = Field(
        ...,
        description="Refresh token from previous login",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    )


class LogoutRequest( BaseModel ):
    """
    User logout request.

    Requires:
        - refresh_token: Refresh token to revoke
    """
    refresh_token: str = Field(
        ...,
        description="Refresh token to revoke",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    )


# Response Models

class TokenResponse( BaseModel ):
    """
    JWT token pair response.

    Contains:
        - access_token: Short-lived JWT for API access
        - refresh_token: Long-lived JWT for token refresh
        - token_type: Always "bearer"
        - expires_in: Access token expiration in seconds
    """
    access_token: str = Field(
        ...,
        description="Short-lived access token (30 min)",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    )
    refresh_token: str = Field(
        ...,
        description="Long-lived refresh token (7 days)",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer')",
        example="bearer"
    )
    expires_in: int = Field(
        ...,
        description="Access token expiration time in seconds",
        example=1800
    )


class UserResponse( BaseModel ):
    """
    User information response.

    Contains:
        - id: User UUID
        - email: User email address
        - roles: List of user roles
        - email_verified: Email verification status
        - is_active: Account active status
        - created_at: Account creation timestamp
        - last_login_at: Last login timestamp (optional)
    """
    id: str = Field(
        ...,
        description="User unique identifier (UUID)",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    email: str = Field(
        ...,
        description="User email address",
        example="user@example.com"
    )
    roles: List[str] = Field(
        ...,
        description="User roles",
        example=["user", "admin"]
    )
    email_verified: bool = Field(
        ...,
        description="Email verification status",
        example=False
    )
    is_active: bool = Field(
        ...,
        description="Account active status",
        example=True
    )
    created_at: str = Field(
        ...,
        description="Account creation timestamp (ISO 8601)",
        example="2025-09-29T12:34:56.789012"
    )
    last_login_at: Optional[str] = Field(
        None,
        description="Last login timestamp (ISO 8601)",
        example="2025-09-29T14:22:11.123456"
    )


class RegisterResponse( BaseModel ):
    """
    User registration response.

    Contains:
        - message: Success message
        - user: User information
        - tokens: JWT token pair
    """
    message: str = Field(
        ...,
        description="Success message",
        example="User registered successfully"
    )
    user: UserResponse = Field(
        ...,
        description="User information"
    )
    tokens: TokenResponse = Field(
        ...,
        description="JWT token pair"
    )


class LoginResponse( BaseModel ):
    """
    User login response.

    Contains:
        - message: Success message
        - user: User information
        - tokens: JWT token pair
    """
    message: str = Field(
        ...,
        description="Success message",
        example="Login successful"
    )
    user: UserResponse = Field(
        ...,
        description="User information"
    )
    tokens: TokenResponse = Field(
        ...,
        description="JWT token pair"
    )


class RefreshResponse( BaseModel ):
    """
    Token refresh response.

    Contains:
        - message: Success message
        - tokens: New JWT token pair
    """
    message: str = Field(
        ...,
        description="Success message",
        example="Token refreshed successfully"
    )
    tokens: TokenResponse = Field(
        ...,
        description="New JWT token pair"
    )


class LogoutResponse( BaseModel ):
    """
    User logout response.

    Contains:
        - message: Success message
    """
    message: str = Field(
        ...,
        description="Success message",
        example="Logout successful"
    )


class ErrorResponse( BaseModel ):
    """
    Error response for authentication endpoints.

    Contains:
        - detail: Error message
        - error_code: Optional error code
    """
    detail: str = Field(
        ...,
        description="Error message",
        example="Invalid credentials"
    )
    error_code: Optional[str] = Field(
        None,
        description="Error code for client handling",
        example="AUTH_INVALID_CREDENTIALS"
    )


# Phase 7: Email Verification & Password Reset Models

class RequestVerificationRequest( BaseModel ):
    """Request to resend email verification (authenticated endpoint)."""
    pass  # Uses authenticated user from token


class VerifyEmailRequest( BaseModel ):
    """Request to verify email address with token."""
    token: str = Field(
        ...,
        description="Email verification token from email",
        example="abc123def456"
    )


class RequestPasswordResetRequest( BaseModel ):
    """Request to send password reset email."""
    email: EmailStr = Field(
        ...,
        description="Email address to send reset link",
        example="user@example.com"
    )


class ResetPasswordRequest( BaseModel ):
    """Request to reset password with token."""
    token: str = Field(
        ...,
        description="Password reset token from email",
        example="xyz789abc123"
    )
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password (min 8 characters, must include uppercase, lowercase, digit, special char)",
        example="NewPass123!"
    )


class ChangePasswordRequest( BaseModel ):
    """Request to change password for authenticated user."""
    current_password: str = Field(
        ...,
        min_length=1,
        description="Current password for verification",
        example="OldPass123!"
    )
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password (min 8 characters, must include uppercase, lowercase, digit, special char)",
        example="NewPass123!"
    )


class MessageResponse( BaseModel ):
    """Generic message response."""
    message: str = Field(
        ...,
        description="Status message",
        example="Operation successful"
    )