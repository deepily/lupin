# Phase 7: Email Verification & Password Reset

**Status**: ✅ COMPLETED on 2025.09.29

---


**Timeline**: Week 4, Days 1-3
**Status**: NOT_STARTED
**Blocking**: Phase 6 complete ✅

#### Objectives
- Implement email verification workflow
- Add password reset functionality
- Send transactional emails via SMTP or SendGrid

#### Files to Create

**1. `src/cosa/rest/email_service.py`** (Email sending)

```python
"""
Email Service for Authentication Workflows.

Handles sending verification emails, password reset emails,
and other transactional emails for the authentication system.
"""

from typing import Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cosa.config.configuration_manager import ConfigurationManager

config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def send_verification_email( email: str, token: str, user_name: str ) -> bool:
    """
    Send email verification email to user.

    Requires:
        - email is valid email address
        - token is verification token
        - user_name is display name
        - Email service configured

    Ensures:
        - Email sent via configured provider
        - Returns True on success, False on failure
        - Email contains verification link

    Returns:
        bool: True if sent successfully
    """
    verification_url = f"{config_mgr.get('app base url')}/auth/verify-email?token={token}"

    subject = "Verify Your Lupin Account"
    body = f"""
    Hi {user_name},

    Please verify your email address by clicking the link below:

    {verification_url}

    This link expires in 24 hours.

    If you didn't create this account, please ignore this email.

    Best regards,
    The Lupin Team
    """

    return _send_email( email, subject, body )


def send_password_reset_email( email: str, token: str, user_name: str ) -> bool:
    """
    Send password reset email to user.

    Requires:
        - email is valid email address
        - token is reset token (15 min expiration)
        - user_name is display name

    Ensures:
        - Email sent via configured provider
        - Returns True on success, False on failure
        - Email contains reset link with short expiration warning

    Returns:
        bool: True if sent successfully
    """
    reset_url = f"{config_mgr.get('app base url')}/auth/reset-password?token={token}"

    subject = "Reset Your Lupin Password"
    body = f"""
    Hi {user_name},

    You requested a password reset for your Lupin account.

    Click the link below to reset your password:

    {reset_url}

    This link expires in 15 minutes.

    If you didn't request this reset, please ignore this email.
    Your password will not be changed unless you click the link above.

    Best regards,
    The Lupin Team
    """

    return _send_email( email, subject, body )


def _send_email( to_email: str, subject: str, body: str ) -> bool:
    """
    Internal email sending via SMTP.

    Requires:
        - SMTP configuration in lupin-app.ini
        - Valid email credentials

    Ensures:
        - Sends email via configured SMTP server
        - Returns success status
        - Logs errors without raising exceptions

    Returns:
        bool: True if sent, False on error
    """
    try:
        smtp_host = config_mgr.get( "smtp host", "localhost" )
        smtp_port = config_mgr.get( "smtp port", 587, return_type="int" )
        smtp_user = config_mgr.get( "smtp username", "" )
        smtp_pass = config_mgr.get( "smtp password", "" )
        from_email = config_mgr.get( "smtp from email", "noreply@lupin.ai" )

        # Create message
        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach( MIMEText( body, "plain" ) )

        # Send via SMTP
        with smtplib.SMTP( smtp_host, smtp_port ) as server:
            if smtp_user and smtp_pass:
                server.starttls()
                server.login( smtp_user, smtp_pass )

            server.send_message( msg )

        print( f"[EMAIL] Sent to {to_email}: {subject}" )
        return True

    except Exception as e:
        print( f"[EMAIL] Failed to send to {to_email}: {e}" )
        return False
```

**2. `src/cosa/rest/email_token_service.py`** (Token generation/validation)

```python
"""
Email Token Service for Verification and Password Reset.

Handles generation and validation of secure tokens for
email verification and password reset workflows.
"""

import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Tuple
from cosa.rest.auth_database import get_auth_db_connection


def generate_verification_token( user_id: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Generate email verification token.

    Requires:
        - user_id is valid UUID
        - Database initialized

    Ensures:
        - Generates cryptographically secure random token
        - Stores token in database with 24h expiration
        - Returns (success, message, token)

    Returns:
        tuple: (success: bool, message: str, token: Optional[str])
    """
    token = secrets.token_urlsafe( 32 )
    expires_at = (datetime.utcnow() + timedelta( hours=24 )).isoformat()

    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO email_verification_tokens ( token, user_id, expires_at, created_at )
            VALUES ( ?, ?, ?, ? )
            """,
            ( token, user_id, expires_at, datetime.utcnow().isoformat() )
        )
        conn.commit()
        return True, "Token generated", token

    except Exception as e:
        conn.rollback()
        return False, f"Token generation failed: {e}", None

    finally:
        conn.close()


def validate_verification_token( token: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Validate email verification token.

    Requires:
        - token is verification token string
        - Database initialized

    Ensures:
        - Checks token exists and not expired
        - Checks token not already used
        - Returns (success, message, user_id)
        - Marks token as used on success

    Returns:
        tuple: (success: bool, message: str, user_id: Optional[str])
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT user_id, expires_at, used
            FROM email_verification_tokens
            WHERE token = ?
            """,
            ( token, )
        )
        row = cursor.fetchone()

        if not row:
            return False, "Invalid token", None

        user_id, expires_at, used = row["user_id"], row["expires_at"], row["used"]

        if used:
            return False, "Token already used", None

        if datetime.fromisoformat( expires_at ) < datetime.utcnow():
            return False, "Token expired", None

        # Mark token as used
        cursor.execute(
            """
            UPDATE email_verification_tokens
            SET used = 1
            WHERE token = ?
            """,
            ( token, )
        )
        conn.commit()

        return True, "Token valid", user_id

    except Exception as e:
        return False, f"Validation failed: {e}", None

    finally:
        conn.close()


def generate_password_reset_token( user_id: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Generate password reset token (15 min expiration).

    Requires:
        - user_id is valid UUID
        - Database initialized

    Ensures:
        - Generates cryptographically secure random token
        - Stores token with 15 minute expiration
        - Returns (success, message, token)

    Returns:
        tuple: (success: bool, message: str, token: Optional[str])
    """
    token = secrets.token_urlsafe( 32 )
    expires_at = (datetime.utcnow() + timedelta( minutes=15 )).isoformat()

    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO password_reset_tokens ( token, user_id, expires_at, created_at )
            VALUES ( ?, ?, ?, ? )
            """,
            ( token, user_id, expires_at, datetime.utcnow().isoformat() )
        )
        conn.commit()
        return True, "Token generated", token

    except Exception as e:
        conn.rollback()
        return False, f"Token generation failed: {e}", None

    finally:
        conn.close()


def validate_password_reset_token( token: str ) -> Tuple[bool, str, Optional[str]]:
    """
    Validate password reset token.

    Requires:
        - token is reset token string
        - Database initialized

    Ensures:
        - Checks token exists and not expired (15 min)
        - Checks token not already used
        - Returns (success, message, user_id)
        - Marks token as used on success

    Returns:
        tuple: (success: bool, message: str, user_id: Optional[str])
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT user_id, expires_at, used
            FROM password_reset_tokens
            WHERE token = ?
            """,
            ( token, )
        )
        row = cursor.fetchone()

        if not row:
            return False, "Invalid token", None

        user_id, expires_at, used = row["user_id"], row["expires_at"], row["used"]

        if used:
            return False, "Token already used", None

        if datetime.fromisoformat( expires_at ) < datetime.utcnow():
            return False, "Token expired", None

        # Mark token as used
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used = 1
            WHERE token = ?
            """,
            ( token, )
        )
        conn.commit()

        return True, "Token valid", user_id

    except Exception as e:
        return False, f"Validation failed: {e}", None

    finally:
        conn.close()
```

**3. Update `src/cosa/rest/auth_database.py`** (Add new tables)

```python
# Add to init_auth_database() function:

# Create email_verification_tokens table
cursor.execute( """
    CREATE TABLE IF NOT EXISTS email_verification_tokens (
        token             TEXT PRIMARY KEY,
        user_id           TEXT NOT NULL,
        expires_at        TEXT NOT NULL,
        used              INTEGER DEFAULT 0,
        created_at        TEXT NOT NULL,

        FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
        CHECK( used IN (0, 1) )
    )
""" )

cursor.execute( "CREATE INDEX IF NOT EXISTS idx_email_verification_user_id ON email_verification_tokens( user_id )" )
cursor.execute( "CREATE INDEX IF NOT EXISTS idx_email_verification_expires_at ON email_verification_tokens( expires_at )" )

# Create password_reset_tokens table
cursor.execute( """
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        token             TEXT PRIMARY KEY,
        user_id           TEXT NOT NULL,
        expires_at        TEXT NOT NULL,
        used              INTEGER DEFAULT 0,
        created_at        TEXT NOT NULL,

        FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
        CHECK( used IN (0, 1) )
    )
""" )

cursor.execute( "CREATE INDEX IF NOT EXISTS idx_password_reset_user_id ON password_reset_tokens( user_id )" )
cursor.execute( "CREATE INDEX IF NOT EXISTS idx_password_reset_expires_at ON password_reset_tokens( expires_at )" )
```

**4. Add endpoints to `src/cosa/rest/routers/auth.py`**

```python
@router.post( "/request-verification" )
async def request_verification( user: Dict = Depends( get_current_user ) ):
    """Resend email verification email."""
    from cosa.rest.email_token_service import generate_verification_token
    from cosa.rest.email_service import send_verification_email

    success, message, token = generate_verification_token( user["uid"] )
    if not success:
        raise HTTPException( status_code=500, detail=message )

    send_verification_email( user["email"], token, user["name"] )
    return {"message": "Verification email sent"}


@router.post( "/verify-email" )
async def verify_email( token: str ):
    """Verify email address with token."""
    from cosa.rest.email_token_service import validate_verification_token
    from cosa.rest.user_service import mark_email_verified

    success, message, user_id = validate_verification_token( token )
    if not success:
        raise HTTPException( status_code=400, detail=message )

    mark_email_verified( user_id )
    return {"message": "Email verified successfully"}


@router.post( "/request-password-reset" )
async def request_password_reset( email: EmailStr ):
    """Request password reset email."""
    from cosa.rest.user_service import get_user_by_email
    from cosa.rest.email_token_service import generate_password_reset_token
    from cosa.rest.email_service import send_password_reset_email

    user = get_user_by_email( email )
    if not user:
        # Return success even if user not found (security)
        return {"message": "If account exists, reset email will be sent"}

    success, message, token = generate_password_reset_token( user["id"] )
    if success:
        send_password_reset_email( user["email"], token, user["name"] )

    return {"message": "If account exists, reset email will be sent"}


@router.post( "/reset-password" )
async def reset_password( token: str, new_password: str ):
    """Reset password with token."""
    from cosa.rest.email_token_service import validate_password_reset_token
    from cosa.rest.user_service import reset_password_with_token

    success, message, user_id = validate_password_reset_token( token )
    if not success:
        raise HTTPException( status_code=400, detail=message )

    success, message = reset_password_with_token( user_id, new_password )
    if not success:
        raise HTTPException( status_code=400, detail=message )

    return {"message": "Password reset successfully"}
```

**5. Configuration Updates** (`lupin-app.ini`)

```ini
# Email Service Configuration
smtp host                         = smtp.gmail.com
smtp port                         = 587
smtp username                     = ${SMTP_USERNAME}
smtp password                     = ${SMTP_PASSWORD}
smtp from email                   = noreply@lupin.ai
app base url                      = http://localhost:7999
```

#### Testing
- Smoke tests for token generation/validation
- Email sending (can mock in tests)
- End-to-end flow testing

---


---

**Source**: Extracted from original monolithic design document (2025.09.29-jwt-oauth-implementation-design-and-tracker.md)
