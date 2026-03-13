# Phase 8: Rate Limiting & Security Hardening

**Status**: ✅ COMPLETED on 2025.09.29

---


**Timeline**: Week 4, Days 4-5
**Status**: NOT_STARTED
**Blocking**: Phase 7 complete

#### Objectives
- Protect authentication endpoints from brute force attacks
- Implement account lockout after failed login attempts
- Add audit logging for security events
- Configure security headers

#### Files to Create

**1. `src/cosa/rest/rate_limiter.py`** (Rate limiting middleware)

```python
"""
Rate Limiting and Account Lockout for Authentication Endpoints.

Protects against brute force attacks by tracking failed login attempts
and temporarily locking accounts after too many failures.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Tuple
from cosa.rest.auth_database import get_auth_db_connection
from cosa.config.configuration_manager import ConfigurationManager

config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def record_failed_login( email: str, ip_address: str ) -> None:
    """
    Record failed login attempt.

    Requires:
        - email is user email
        - ip_address is client IP

    Ensures:
        - Records attempt in database
        - Increments failure counter
        - Stores timestamp for cleanup
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO failed_login_attempts ( email, ip_address, attempt_time )
            VALUES ( ?, ?, ? )
            """,
            ( email, ip_address, datetime.utcnow().isoformat() )
        )
        conn.commit()
    finally:
        conn.close()


def check_account_lockout( email: str ) -> Tuple[bool, Optional[str]]:
    """
    Check if account is locked due to failed attempts.

    Requires:
        - email is user email
        - Configuration for max attempts and lockout duration

    Ensures:
        - Returns (is_locked: bool, unlock_time: Optional[str])
        - Checks recent attempts within lockout window
        - Implements exponential backoff (future enhancement)

    Returns:
        tuple: (is_locked, unlock_time_iso)
    """
    max_attempts = config_mgr.get( "auth max failed attempts", 5, return_type="int" )
    lockout_minutes = config_mgr.get( "auth lockout duration minutes", 15, return_type="int" )

    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        # Check attempts in last lockout window
        window_start = (datetime.utcnow() - timedelta( minutes=lockout_minutes )).isoformat()

        cursor.execute(
            """
            SELECT COUNT(*) as attempt_count, MAX(attempt_time) as last_attempt
            FROM failed_login_attempts
            WHERE email = ? AND attempt_time >= ?
            """,
            ( email, window_start )
        )
        row = cursor.fetchone()

        if row["attempt_count"] >= max_attempts:
            unlock_time = (datetime.fromisoformat( row["last_attempt"] ) +
                          timedelta( minutes=lockout_minutes )).isoformat()
            return True, unlock_time

        return False, None

    finally:
        conn.close()


def clear_failed_attempts( email: str ) -> None:
    """
    Clear failed login attempts for user (after successful login).

    Requires:
        - email is user email

    Ensures:
        - Deletes all failed attempt records for user
        - Called after successful authentication
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM failed_login_attempts
            WHERE email = ?
            """,
            ( email, )
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_old_attempts() -> int:
    """
    Cleanup old failed login attempts (cron job).

    Requires:
        - Database initialized

    Ensures:
        - Deletes attempts older than 24 hours
        - Returns count of deleted records

    Returns:
        int: Number of records deleted
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cutoff = (datetime.utcnow() - timedelta( hours=24 )).isoformat()

        cursor.execute(
            """
            DELETE FROM failed_login_attempts
            WHERE attempt_time < ?
            """,
            ( cutoff, )
        )
        conn.commit()
        return cursor.rowcount

    finally:
        conn.close()
```

**2. `src/cosa/rest/auth_audit.py`** (Audit logging)

```python
"""
Authentication Audit Logging.

Records security-relevant events for compliance and incident investigation.
"""

import sqlite3
from datetime import datetime
from typing import Optional
from cosa.rest.auth_database import get_auth_db_connection


def log_auth_event(
    event_type: str,
    user_id: Optional[str],
    email: Optional[str],
    ip_address: Optional[str],
    details: Optional[str] = None,
    success: bool = True
) -> None:
    """
    Log authentication event to audit log.

    Requires:
        - event_type is one of: login, logout, register, password_change, etc.
        - At least one of user_id or email provided

    Ensures:
        - Event recorded in audit log table
        - Timestamp automatically added
        - Never raises exception (logging should not break auth flow)

    Event Types:
        - login_success
        - login_failure
        - logout
        - register
        - password_change
        - email_verify
        - password_reset_request
        - password_reset_complete
        - account_lockout
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO auth_audit_log (
                event_type, user_id, email, ip_address, details, success, event_time
            )
            VALUES ( ?, ?, ?, ?, ?, ?, ? )
            """,
            (
                event_type,
                user_id,
                email,
                ip_address,
                details,
                1 if success else 0,
                datetime.utcnow().isoformat()
            )
        )
        conn.commit()

    except Exception as e:
        # Log error but don't raise (audit logging shouldn't break auth flow)
        print( f"[AUDIT] Failed to log event: {e}" )

    finally:
        conn.close()
```

**3. Update `src/cosa/rest/auth_database.py`** (Add audit tables)

```python
# Add to init_auth_database():

# Create failed_login_attempts table
cursor.execute( """
    CREATE TABLE IF NOT EXISTS failed_login_attempts (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        email             TEXT NOT NULL,
        ip_address        TEXT,
        attempt_time      TEXT NOT NULL
    )
""" )

cursor.execute( "CREATE INDEX IF NOT EXISTS idx_failed_login_email ON failed_login_attempts( email )" )
cursor.execute( "CREATE INDEX IF NOT EXISTS idx_failed_login_time ON failed_login_attempts( attempt_time )" )

# Create auth_audit_log table
cursor.execute( """
    CREATE TABLE IF NOT EXISTS auth_audit_log (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type        TEXT NOT NULL,
        user_id           TEXT,
        email             TEXT,
        ip_address        TEXT,
        details           TEXT,
        success           INTEGER NOT NULL,
        event_time        TEXT NOT NULL,

        CHECK( success IN (0, 1) )
    )
""" )

cursor.execute( "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON auth_audit_log( user_id )" )
cursor.execute( "CREATE INDEX IF NOT EXISTS idx_audit_email ON auth_audit_log( email )" )
cursor.execute( "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON auth_audit_log( event_type )" )
cursor.execute( "CREATE INDEX IF NOT EXISTS idx_audit_time ON auth_audit_log( event_time )" )
```

**4. Update `/auth/login` endpoint** (Add rate limiting)

```python
@router.post( "/login" )
async def login( request: LoginRequest, client_ip: Optional[str] = Header( None, alias="X-Forwarded-For" ) ):
    """Login with rate limiting and lockout."""
    from cosa.rest.rate_limiter import check_account_lockout, record_failed_login, clear_failed_attempts
    from cosa.rest.auth_audit import log_auth_event

    # Check if account is locked
    is_locked, unlock_time = check_account_lockout( request.email )
    if is_locked:
        log_auth_event( "login_failure", None, request.email, client_ip, "Account locked", success=False )
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked due to failed attempts. Try again after {unlock_time}"
        )

    # Authenticate
    success, message, user_dict = authenticate_user( request.email, request.password )

    if not success:
        # Record failed attempt
        record_failed_login( request.email, client_ip or "unknown" )
        log_auth_event( "login_failure", None, request.email, client_ip, message, success=False )
        raise HTTPException( status_code=401, detail=message )

    # Success: clear failed attempts
    clear_failed_attempts( request.email )
    log_auth_event( "login_success", user_dict["id"], user_dict["email"], client_ip, success=True )

    # Generate tokens and return...
```

**5. Configuration Updates** (`lupin-app.ini`)

```ini
# Rate Limiting & Security
auth max failed attempts          = 5
auth lockout duration minutes     = 15
auth cleanup old attempts hours   = 24
```

**6. Add security headers to `main.py`**

```python
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware

# Add security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
```

#### Testing
- Test failed login lockout
- Test successful login clears counter
- Test audit log entries
- Test rate limit thresholds

---

## Implementation Tracking


---

**Source**: Extracted from original monolithic design document (2025.09.29-jwt-oauth-implementation-design-and-tracker.md)
