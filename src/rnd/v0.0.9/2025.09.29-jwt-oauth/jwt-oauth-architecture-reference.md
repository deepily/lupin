# JWT/OAuth Authentication System - Architecture Reference

**Created**: 2025.09.29
**Status**: REFERENCE DOCUMENTATION
**Project**: Lupin/COSA Authentication System Upgrade

**Note**: This document contains the timeless architectural design and decisions. For current implementation status, see [jwt-oauth-active-implementation.md](jwt-oauth-active-implementation.md). For completed phase details, see [completed-phases/](completed-phases/).

---

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [Current System Analysis](#current-system-analysis)
3. [Architecture Design](#architecture-design)
4. [WebSocket Authentication Integration](#websocket-authentication-integration)
5. [Backward Compatibility Strategy](#backward-compatibility-strategy)
6. [Testing Strategy](#testing-strategy)
7. [Configuration Management](#configuration-management)
8. [Security Considerations](#security-considerations)
9. [Decision Log](#decision-log)

---

## Executive Summary

### Current State
Lupin currently uses a **mock authentication system** that mimics Firebase JWT tokens but doesn't actually validate them. The system accepts tokens in the format `Bearer mock_token_email_user@example.com` and provides basic user identification without real security.

**Key Components**:
- `src/cosa/rest/auth.py` - Mock Firebase token validation
- `src/cosa/rest/user_id_generator.py` - Email → System ID conversion
- Mock user database with 3 hardcoded users (ricardo, alice, bob)
- WebSocket two-phase authentication flow
- 6 protected REST endpoints using `Depends(get_current_user)`

### Goal
Implement a **production-ready JWT authentication system** with:
- Real token generation and validation using PyJWT
- Secure password storage with bcrypt hashing
- Access tokens (30 min) + Refresh tokens (7 days)
- Role-Based Access Control (RBAC)
- Email verification workflow
- Backward compatibility during migration

### Strategy
**Incremental, testable migration** with:
- Configuration-driven switching (`auth_mode = mock|jwt|firebase`)
- Dual token support during transition
- Phase-by-phase rollout with rollback capability
- Comprehensive testing at every step
- Zero breaking changes to existing functionality

### Timeline Estimate
- **Phase 1-2** (Foundation): Week 1 (JWT service + User management)
- **Phase 3-4** (Authentication): Week 2 (Endpoints + Token validation)
- **Phase 5-6** (Integration): Week 3-4 (WebSocket + Frontend)
- **Phase 7-8** (Features): Week 4-5 (Email + RBAC)
- **Phase 9-10** (Production): Week 5-6 (Migration + Documentation)

**Total**: 5-6 weeks for complete implementation

### Risk Assessment
| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking WebSocket connections | HIGH | Maintain backward compatibility, gradual rollout |
| Token theft vulnerability | HIGH | Implement refresh token rotation, httpOnly cookies |
| User data migration issues | MEDIUM | Comprehensive migration scripts, testing |
| Performance degradation | MEDIUM | Token caching, database indexing |
| Frontend integration complexity | MEDIUM | Incremental updates, mock mode fallback |

---

## Current System Analysis

### Authentication Touch Points Inventory

#### 1. REST API Endpoints (6 files using authentication)
**Files Found via Grep**:
```
/src/cosa/rest/auth.py
/src/cosa/rest/routers/system.py
/src/cosa/rest/routers/queues.py
/src/cosa/rest/routers/websocket.py
/src/cosa/rest/routers/speech.py
/src/cosa/rest/routers/websocket_admin.py
```

**Protected Endpoints**:
- `/api/push` - Queue job submission (POST, requires auth)
- `/api/get-speech` - TTS generation (GET, requires auth)
- `/api/websocket-sessions/*` - Admin WebSocket management (requires auth)
- `/api/notify` - Notification system (requires auth)
- `/api/auth-test` - Authentication test endpoint (requires auth)

**Authentication Patterns**:
```python
# Pattern 1: Full user object
async def endpoint( current_user: dict = Depends( get_current_user ) ):
    user_id = current_user["uid"]
    email = current_user["email"]
    ...

# Pattern 2: User ID only
async def endpoint( user_id: str = Depends( get_current_user_id ) ):
    # Simplified for endpoints that only need ID
    ...

# Pattern 3: Optional authentication
async def endpoint( current_user: Optional[dict] = Depends( get_optional_user ) ):
    if current_user:
        # Authenticated behavior
    else:
        # Public behavior
```

#### 2. WebSocket Authentication Flow
**Endpoints**:
- `/ws/audio/{session_id}` - TTS audio streaming
- `/ws/queue/{session_id}` - Queue updates and notifications

**Two-Phase Authentication Process**:
```
Phase 1: Connection Establishment
  1. Client connects to WebSocket endpoint
  2. Server accepts connection immediately (no auth yet)
  3. Connection is in "pending auth" state

Phase 2: Token Validation
  1. Client sends: {"type": "auth_request", "token": "Bearer mock_token_email_user@example.com"}
  2. Server calls verify_firebase_token( extracted_token )
  3. Server associates user_id with session_id
  4. Server sends: {"type": "auth_success", "user_id": "...", "session_id": "..."}
  OR
  5. Server closes connection with error
```

**Session ID Format**: Must match pattern `^[a-z]+ [a-z]+$` (e.g., "wise penguin", "clever dolphin")

#### 3. Mock User Database
**Location**: `src/cosa/rest/user_id_generator.py`

**Hardcoded Users**:
```python
MOCK_USER_DATABASE = {
    "ricardo_felipe_ruiz_6bdc": {
        "email": "ricardo.felipe.ruiz@gmail.com",
        "name": "Ricardo",
        "email_verified": True
    },
    "alice_smith_a1b2": {
        "email": "alice.smith@example.com",
        "name": "Alice",
        "email_verified": True
    },
    "bob_jones_3c4d": {
        "email": "bob.jones@example.com",
        "name": "Bob",
        "email_verified": True
    }
}
```

#### 4. User ID Generation Algorithm
**Function**: `email_to_system_id( email: str ) -> str`

**Algorithm**:
1. Extract local part before '@'
2. Convert to lowercase, replace non-alphanumeric with '_'
3. Generate 4-character collision-resistant hash from full email
4. Format: `{sanitized_local_part}_{4_char_hash}`

**Example**: `ricardo.felipe.ruiz@gmail.com` → `ricardo_felipe_ruiz_6bdc`

**Critical**: This algorithm **MUST BE PRESERVED** as it's used throughout the system for:
- File path generation
- Database keys
- Session identification
- Solution snapshot ownership

### Existing Infrastructure to Preserve

#### 1. HTTPBearerWith401 Custom Class
**Location**: `src/cosa/rest/auth.py:41-58`

**Purpose**: Override FastAPI's default HTTPBearer to return **401** (Unauthorized) instead of **403** (Forbidden) when authentication is missing.

**Rationale**: Smoke tests specifically validate 401 responses for missing auth.

**Must Maintain**: This behavior is tested and expected by existing smoke tests.

#### 2. Quick Smoke Test Pattern
**Standard Pattern**:
```python
def quick_smoke_test():
    """
    Quick smoke test for [module name].

    Requires:
        - [Dependencies]

    Ensures:
        - [Outcomes]

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "Module Name Smoke Test", prepend_nl=True )

    try:
        # Test critical functionality
        print( "Testing feature X..." )
        # ... test code ...
        print( "✓ Feature X working" )

        print( "\\n✓ All tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    quick_smoke_test()
```

**New Modules Must Include**: Every new authentication module must have a `quick_smoke_test()` function.

#### 3. Code Style Requirements
**From CLAUDE.md**:
- **Spacing**: Use spaces inside parentheses and brackets
  ```python
  # CORRECT
  function( arg1, arg2 )
  list[ 0 ]

  # INCORRECT
  function(arg1, arg2)
  list[0]
  ```

- **Variable Alignment**: Align equals signs vertically
  ```python
  # CORRECT
  self.debug           = debug
  self.verbose         = verbose
  self.secret_key      = secret_key
  self.token_expire    = token_expire
  ```

- **Dictionary Alignment**: Align colons vertically
  ```python
  # CORRECT
  config = {
      "model_name"  : "gpt-4",
      "temperature" : 0.7,
      "max_tokens"  : 1024
  }
  ```

- **One-line Conditionals**: For simple checks
  ```python
  # CORRECT
  if debug: print( f"Debug: {value}" )
  if verbose: du.print_banner( "Processing" )
  ```

- **Design by Contract Docstrings**: All functions must include
  ```python
  def function_name( param ):
      """
      Brief description.

      Requires:
          - Preconditions

      Ensures:
          - Postconditions

      Raises:
          - Exceptions
      """
  ```

---

## Architecture Design

### Token Architecture

#### Access Tokens (Short-Lived)

**Lifespan**: 30 minutes (configurable via `jwt_access_token_expire_minutes`)

**Purpose**: Authorize individual API requests and WebSocket connections

**Claims Structure**:
```python
{
    "sub"   : "ricardo_felipe_ruiz_6bdc",  # Subject: system user ID
    "email" : "ricardo.felipe.ruiz@gmail.com",
    "roles" : ["user", "admin"],           # For RBAC
    "exp"   : 1701234567,                  # Expiration timestamp (UTC)
    "iat"   : 1701232767,                  # Issued at timestamp (UTC)
    "jti"   : "unique-token-id-uuid"       # JWT ID for revocation tracking
}
```

**Design Decisions**:

1. **Embed Roles in Token**:
   - ✅ **PRO**: No database lookup on every request, faster validation
   - ✅ **PRO**: Stateless authentication, horizontally scalable
   - ❌ **CON**: Role changes require new token (acceptable with 30min TTL)
   - ❌ **CON**: Slightly larger token size (negligible)
   - **DECISION**: Embed roles for performance, 30min refresh cycle acceptable

2. **Include JTI (JWT ID)**:
   - **PURPOSE**: Enables per-token revocation if needed
   - **USE CASE**: User reports token theft, admin can revoke specific token
   - **IMPLEMENTATION**: Optional tracking table for revoked JTIs
   - **DECISION**: Include for security flexibility

3. **Token Size Considerations**:
   - Typical size: ~250-350 bytes (base64-encoded)
   - HTTP header limit: 8KB (plenty of room)
   - WebSocket message overhead: Negligible
   - **DECISION**: Current claims are optimal, no size concerns

#### Refresh Tokens (Long-Lived)

**Lifespan**: 7 days (configurable via `jwt_refresh_token_expire_days`)

**Purpose**: Obtain new access tokens without re-authentication

**Claims Structure**:
```python
{
    "sub"        : "ricardo_felipe_ruiz_6bdc",
    "email"      : "ricardo.felipe.ruiz@gmail.com",
    "exp"        : 1701838567,
    "iat"        : 1701234567,
    "jti"        : "unique-refresh-token-id",
    "token_type" : "refresh"  # Distinguish from access tokens
}
```

**Design Decisions**:

1. **Static vs Rotating Refresh Tokens**:

   **Static (Current Plan)**:
   - ✅ Simpler implementation
   - ✅ No database update on every refresh
   - ❌ Token theft window = full 7 days

   **Rotating (Future Enhancement)**:
   - ✅ Better security: Each refresh invalidates old token
   - ✅ Detect token theft: Multiple refresh attempts with same token
   - ❌ More complex: Database updates, token family tracking
   - ❌ Edge case: Network failure during refresh leaves user logged out

   **DECISION**: Start with **static** for MVP, plan rotating for Phase 11 (Future Enhancements)

2. **Server-Side Storage Strategy**:

   **Option A: Store Token Hash**:
   - ✅ Even if database leaked, tokens can't be used
   - ✅ Best security practice
   - ❌ Slightly slower lookup (hash comparison)

   **Option B: Store Raw Token**:
   - ✅ Faster lookup (direct comparison)
   - ❌ Database leak = direct token compromise

   **DECISION**: **Store token hash** (bcrypt or SHA-256) for security. Performance difference negligible.

3. **Revocation Mechanism**:
   ```python
   # RefreshTokens table structure
   {
       "jti"          : "unique-token-id",
       "user_id"      : "ricardo_felipe_ruiz_6bdc",
       "token_hash"   : "bcrypt_hash_of_token",
       "expires_at"   : "2025-10-06T12:00:00Z",
       "revoked"      : False,
       "created_at"   : "2025-09-29T12:00:00Z",
       "last_used_at" : "2025-09-30T08:30:00Z"
   }
   ```

   **Revocation Scenarios**:
   - User clicks "Logout" → Set `revoked = True`
   - User clicks "Logout All Devices" → Revoke all user's tokens
   - Admin action → Revoke specific user's tokens
   - Security breach → Revoke all tokens globally

   **DECISION**: Simple boolean flag, cleanup cron job for expired tokens

#### Secret Key Management

**Generation Method**:
```python
import secrets
SECRET_KEY = secrets.token_urlsafe( 32 )  # 256-bit key, URL-safe base64
# Example output: "<REDACTED — row adce3547; generate your own with python -c "import secrets; print( secrets.token_urlsafe( 32 ) )">"
```

**Storage Strategy**:

**Development**:
```bash
# .env file (NOT committed to git)
JWT_SECRET_KEY=<REDACTED — row adce3547; generate your own with python -c "import secrets; print( secrets.token_urlsafe( 32 ) )">
```

**Production**:
```bash
# Environment variable set by deployment system
export JWT_SECRET_KEY="<REDACTED — row adce3547; JWT_SECRET_KEY is REQUIRED, there is no literal fallback>"
```

**Configuration Integration**:
```ini
[Lupin: Baseline]
jwt secret key = ${JWT_SECRET_KEY}  # Read from environment
```

**Fallback for Development**:
```python
# In jwt_service.py
SECRET_KEY = os.getenv( "JWT_SECRET_KEY" )
if not SECRET_KEY:
    if os.getenv( "ENVIRONMENT" ) == "development":
        print( "[WARNING] Using default development secret key" )
        SECRET_KEY = "<REDACTED — row adce3547; JWT_SECRET_KEY is REQUIRED, there is no literal fallback>"
    else:
        raise ValueError( "JWT_SECRET_KEY environment variable not set!" )
```

**Rotation Procedures**:
1. Generate new key
2. Deploy with both old and new keys (verify with either)
3. After all tokens rotated (30 min), remove old key
4. Document rotation in changelog

**DECISION**: Environment variable with development fallback, explicit error in production

#### Algorithm Selection: HS256 vs RS256

**HS256 (HMAC-SHA256) - Symmetric**:
- ✅ Simpler: Single secret key
- ✅ Faster: No RSA computation overhead
- ✅ Smaller keys: 256-bit secret vs 2048-bit RSA
- ❌ Same key signs and verifies
- ❌ Can't distribute verification key publicly

**RS256 (RSA-SHA256) - Asymmetric**:
- ✅ Separate keys: Private signs, public verifies
- ✅ Can distribute public key safely
- ✅ Better for multi-service architecture
- ❌ More complex: Key pair management
- ❌ Slower: RSA computation overhead
- ❌ Larger keys: 2048-4096 bit RSA keys

**Lupin Architecture Analysis**:
- Single monolithic FastAPI application
- No external services need to verify tokens
- Performance-critical WebSocket connections
- Simpler key management preferred

**DECISION**: **HS256** for MVP (simpler, faster). RS256 can be added later if microservices emerge.

### Database Schema Design

#### Database Technology Selection

**Option 1: Extend LanceDB (Existing)**
- ✅ Already integrated and operational
- ✅ No new dependency
- ✅ Consistent with solution snapshot storage
- ❌ Optimized for vector similarity, not relational queries
- ❌ No built-in user/password table patterns
- ❌ Limited transaction support

**Option 2: Add SQLite (Lightweight)**
- ✅ Zero-configuration, file-based
- ✅ Perfect for authentication tables
- ✅ ACID transactions
- ✅ Familiar SQL interface
- ❌ New dependency
- ❌ Separate database to manage

**Option 3: Add PostgreSQL (Enterprise)**
- ✅ Full-featured RDBMS
- ✅ Excellent for authentication
- ✅ Scalable for production
- ❌ Heavy dependency
- ❌ Requires separate service
- ❌ Overkill for Lupin's scale

**DECISION**: **SQLite** for authentication tables (separate concern from vector data)

**Rationale**:
- Authentication is relational data (users, tokens, sessions)
- LanceDB handles vector embeddings and similarity search
- SQLite handles structured auth data with transactions
- Clear separation of concerns
- Both are lightweight, no external services

**Implementation Path**:
```python
# src/cosa/rest/auth_database.py
import sqlite3
from pathlib import Path

def get_auth_db_path():
    """Get authentication database path from configuration."""
    # Default: src/conf/auth/lupin-auth.db
    return config_mgr.get( "auth database path wo root" )

def init_auth_database():
    """Initialize authentication database with schema."""
    db_path = get_auth_db_path()
    Path( db_path ).parent.mkdir( parents=True, exist_ok=True )

    conn = sqlite3.connect( db_path )
    # Create tables...
    conn.close()
```

#### Users Table Schema

```sql
CREATE TABLE users (
    id                TEXT PRIMARY KEY,           -- System ID: "ricardo_felipe_ruiz_6bdc"
    email             TEXT UNIQUE NOT NULL,       -- "ricardo.felipe.ruiz@gmail.com"
    password_hash     TEXT NOT NULL,              -- Bcrypt hash of password
    created_at        TEXT NOT NULL,              -- ISO8601 timestamp
    email_verified    INTEGER DEFAULT 0,          -- Boolean: 0=False, 1=True
    is_active         INTEGER DEFAULT 1,          -- Boolean: 0=Disabled, 1=Active
    roles             TEXT DEFAULT '["user"]',    -- JSON array of roles
    last_login_at     TEXT,                       -- ISO8601 timestamp

    -- Constraints
    CHECK( email_verified IN (0, 1) ),
    CHECK( is_active IN (0, 1) )
);

-- Indexes for performance
CREATE INDEX idx_users_email ON users( email );
CREATE INDEX idx_users_is_active ON users( is_active );
```

**Field Decisions**:

1. **id = System ID format**:
   - Preserves existing `email_to_system_id()` algorithm
   - Maintains consistency across all systems
   - Already tested and validated

2. **password_hash**:
   - Never store plaintext passwords
   - Bcrypt automatically includes salt
   - 60-character bcrypt hash format

3. **email_verified**:
   - Controls whether email verification required
   - Configurable per deployment
   - Development: default verified=1
   - Production: default verified=0, require verification

4. **roles as JSON**:
   - Flexible: Can add new roles without schema changes
   - Default: `'["user"]'` for all new users
   - Admin assignment: Update to `'["user", "admin"]'`
   - Future: `'["user", "admin", "developer"]'`

5. **is_active flag**:
   - Soft deletion: Disable account without losing data
   - Suspended users: Set to 0
   - Token validation checks this flag

#### Refresh Tokens Table Schema

```sql
CREATE TABLE refresh_tokens (
    jti               TEXT PRIMARY KEY,           -- JWT ID (unique token identifier)
    user_id           TEXT NOT NULL,              -- Foreign key to users.id
    token_hash        TEXT NOT NULL,              -- Hash of refresh token
    expires_at        TEXT NOT NULL,              -- ISO8601 timestamp
    revoked           INTEGER DEFAULT 0,          -- Boolean: 0=Valid, 1=Revoked
    created_at        TEXT NOT NULL,              -- ISO8601 timestamp
    last_used_at      TEXT,                       -- ISO8601 timestamp (updated on refresh)
    user_agent        TEXT,                       -- Browser/device info (optional)
    ip_address        TEXT,                       -- Client IP (optional, for security)

    -- Constraints
    FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
    CHECK( revoked IN (0, 1) )
);

-- Indexes for performance
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens( user_id );
CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens( expires_at );
CREATE INDEX idx_refresh_tokens_revoked ON refresh_tokens( revoked );
```

**Field Decisions**:

1. **token_hash vs raw token**:
   - Store SHA-256 or bcrypt hash of token
   - Database leak doesn't expose usable tokens
   - Lookup: Hash incoming token, compare to stored hash

2. **last_used_at tracking**:
   - Update timestamp on each token refresh
   - Identify inactive tokens for cleanup
   - Security monitoring: Detect unusual usage patterns

3. **user_agent & ip_address (optional)**:
   - Enhanced security monitoring
   - Display "Active Sessions" to user with device info
   - Detect token usage from different locations
   - **DECISION**: Implement in Phase 8, optional feature

4. **ON DELETE CASCADE**:
   - Delete user → Automatically revoke all their refresh tokens
   - Maintains referential integrity
   - Clean database state

#### Email Verification Table Schema (Phase 7)

```sql
CREATE TABLE email_verification_tokens (
    token             TEXT PRIMARY KEY,           -- Unique verification token
    user_id           TEXT NOT NULL,              -- Foreign key to users.id
    expires_at        TEXT NOT NULL,              -- ISO8601 timestamp
    used              INTEGER DEFAULT 0,          -- Boolean: 0=Unused, 1=Used
    created_at        TEXT NOT NULL,              -- ISO8601 timestamp

    -- Constraints
    FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
    CHECK( used IN (0, 1) )
);

CREATE INDEX idx_email_verification_user_id ON email_verification_tokens( user_id );
CREATE INDEX idx_email_verification_expires_at ON email_verification_tokens( expires_at );
```

**Verification Flow**:
1. User registers → Generate verification token → Insert into table
2. Send email with link: `https://lupin.app/api/auth/verify-email?token=abc123`
3. User clicks link → Lookup token → Validate not expired/used
4. Mark token as used → Set user.email_verified = 1
5. Cleanup: Cron job deletes expired/used tokens

#### Password Reset Table Schema (Phase 7)

```sql
CREATE TABLE password_reset_tokens (
    token             TEXT PRIMARY KEY,           -- Unique reset token
    user_id           TEXT NOT NULL,              -- Foreign key to users.id
    expires_at        TEXT NOT NULL,              -- ISO8601 timestamp (15 min)
    used              INTEGER DEFAULT 0,          -- Boolean: 0=Unused, 1=Used
    created_at        TEXT NOT NULL,              -- ISO8601 timestamp

    -- Constraints
    FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
    CHECK( used IN (0, 1) )
);

CREATE INDEX idx_password_reset_user_id ON password_reset_tokens( user_id );
CREATE INDEX idx_password_reset_expires_at ON password_reset_tokens( expires_at );
```

**Reset Flow**:
1. User requests reset → Generate token (15 min TTL) → Insert into table
2. Send email with link: `https://lupin.app/reset-password?token=xyz789`
3. User clicks link → Show password reset form
4. User submits new password → Validate token → Update password_hash
5. Mark token as used → Revoke all user's refresh tokens (security)

### Password Security Architecture

#### Hashing Algorithm: Bcrypt

**Library**: Passlib with bcrypt backend

**Installation**:
```bash
pip install passlib[bcrypt]
```

**Configuration**:
```python
from passlib.context import CryptContext

# Create password context with bcrypt
pwd_context = CryptContext(
    schemes = ["bcrypt"],
    deprecated = "auto",
    bcrypt__rounds = 12  # Cost factor: 12 rounds = secure, 14+ = paranoid
)
```

**Cost Factor Analysis**:
- **10 rounds**: ~100ms hashing time, acceptable for high-traffic
- **12 rounds**: ~400ms hashing time, **recommended default**
- **14 rounds**: ~1.6s hashing time, overkill for most applications
- **16 rounds**: ~6.4s hashing time, only for ultra-sensitive data

**DECISION**: **12 rounds** (balanced security vs performance)

#### Password Hashing Functions

```python
def hash_password( plain_password: str ) -> str:
    """
    Hash a plaintext password using bcrypt.

    Requires:
        - plain_password is a non-empty string
        - pwd_context is initialized

    Ensures:
        - Returns bcrypt hash string (60 characters)
        - Hash includes automatic random salt
        - Hash is suitable for storage in database

    Raises:
        - ValueError if password is empty
    """
    if not plain_password:
        raise ValueError( "Password cannot be empty" )

    return pwd_context.hash( plain_password )


def verify_password( plain_password: str, hashed_password: str ) -> bool:
    """
    Verify a plaintext password against stored hash.

    Requires:
        - plain_password is a non-empty string
        - hashed_password is a valid bcrypt hash
        - pwd_context is initialized

    Ensures:
        - Returns True if password matches hash
        - Returns False if password doesn't match
        - Timing-attack resistant (constant-time comparison)

    Raises:
        - None (returns False on any error)
    """
    if not plain_password or not hashed_password:
        return False

    try:
        return pwd_context.verify( plain_password, hashed_password )
    except Exception:
        return False
```

**Security Features**:
- **Automatic salting**: Bcrypt generates unique salt per password
- **Timing-attack resistance**: Passlib uses constant-time comparison
- **Future-proof**: `deprecated="auto"` allows algorithm upgrades

#### Password Strength Validation

```python
import re

def validate_password_strength( password: str ) -> tuple[bool, str]:
    """
    Validate password meets minimum security requirements.

    Requires:
        - password is a string (may be weak or empty)

    Ensures:
        - Returns (True, "") if password is acceptable
        - Returns (False, "error message") if password is weak
        - Checks length, character types, common passwords

    Raises:
        - None (returns validation result)
    """
    # Minimum length
    min_length = 8
    if len( password ) < min_length:
        return False, f"Password must be at least {min_length} characters"

    # Character type requirements (at least 3 of 4)
    has_lowercase = bool( re.search( r'[a-z]', password ) )
    has_uppercase = bool( re.search( r'[A-Z]', password ) )
    has_digit     = bool( re.search( r'\d', password ) )
    has_special   = bool( re.search( r'[!@#$%^&*(),.?":{}|<>]', password ) )

    char_types = sum( [has_lowercase, has_uppercase, has_digit, has_special] )
    if char_types < 3:
        return False, "Password must contain at least 3 of: lowercase, uppercase, digit, special character"

    # Common password check (basic list)
    common_passwords = {
        "password", "12345678", "qwerty123", "admin123", "welcome123",
        "password123", "letmein", "abc12345"
    }
    if password.lower() in common_passwords:
        return False, "Password is too common, please choose a stronger password"

    return True, ""
```

**Configuration Integration**:
```ini
[Lupin: Baseline]
auth password min length             = 8
auth password require complexity     = True
auth password check common           = True
```

**DECISION**: Reasonable requirements without being annoying. Future: Integrate with "Have I Been Pwned" API for leaked password checking.

---

## WebSocket Authentication Integration

### Current Two-Phase Flow Analysis

**Existing Implementation** (`src/cosa/rest/routers/websocket.py`):

```python
@router.websocket( "/ws/queue/{session_id}" )
async def websocket_queue_endpoint( websocket: WebSocket, session_id: str ):
    """
    WebSocket endpoint for queue updates and notifications.
    """
    # Phase 1: Accept connection WITHOUT authentication
    await websocket.accept()

    try:
        # Phase 2: Wait for authentication message
        auth_message = await websocket.receive_json()

        # Validate message structure
        if auth_message.get( "type" ) != "auth_request":
            await websocket.close( code=1008, reason="Expected auth_request" )
            return

        # Extract and validate token
        token = auth_message.get( "token", "" ).replace( "Bearer ", "" )

        # CURRENT: Mock validation
        user_info = await verify_firebase_token( token )

        # Associate user with session
        websocket_manager.add_connection( user_info["uid"], session_id, websocket )

        # Send success message
        await websocket.send_json( {
            "type"       : "auth_success",
            "user_id"    : user_info["uid"],
            "session_id" : session_id
        } )

        # Main message loop
        while True:
            message = await websocket.receive_text()
            # Handle messages...

    except WebSocketDisconnect:
        # Cleanup
        websocket_manager.remove_connection( session_id )
```

**Key Observations**:
1. **Two-phase by design**: Accept connection first, then authenticate
2. **Session ID validation**: Must match `^[a-z]+ [a-z]+$` pattern
3. **User-session mapping**: One user can have multiple sessions
4. **WebSocket manager**: Tracks all active connections by session_id

### JWT Integration Strategy

**No Architectural Changes Needed**: The two-phase flow works perfectly with JWTs!

**Updated Flow**:
```python
# Phase 2: Enhanced validation with JWT
token = auth_message.get( "token", "" ).replace( "Bearer ", "" )

# NEW: Route based on auth_mode configuration
if config_mgr.get( "auth mode" ) == "jwt":
    # Validate JWT
    try:
        payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

        # Check token type (should be access token, not refresh)
        if payload.get( "token_type" ) == "refresh":
            await websocket.close( code=1008, reason="Invalid token type" )
            return

        # Check expiration (jwt.decode does this automatically)
        # Extract user info
        user_id = payload.get( "sub" )
        email   = payload.get( "email" )
        roles   = payload.get( "roles", ["user"] )

        # Verify user still exists and is active
        user = get_user_from_db( user_id )
        if not user or not user.is_active:
            await websocket.close( code=1008, reason="User not active" )
            return

        # Success: Format user_info dict
        user_info = {
            "uid"            : user_id,
            "email"          : email,
            "roles"          : roles,
            "email_verified" : user.email_verified
        }

    except jwt.ExpiredSignatureError:
        await websocket.close( code=1008, reason="Token expired" )
        return
    except jwt.InvalidTokenError:
        await websocket.close( code=1008, reason="Invalid token" )
        return

elif config_mgr.get( "auth mode" ) == "mock":
    # FALLBACK: Keep existing mock validation for backward compatibility
    user_info = await verify_firebase_token( token )

else:
    await websocket.close( code=1008, reason="Unknown auth mode" )
    return
```

**Backward Compatibility**: Both code paths return the same `user_info` structure, so downstream code unchanged.

### Token Expiration Handling (Critical Nuance)

**Problem**: Access tokens expire after 30 minutes, but WebSocket connections can last hours (especially during active conversations or audio streaming).

**Scenario**:
1. User connects at 12:00 PM with valid token (expires 12:30 PM)
2. User has active conversation until 1:00 PM
3. Token expired at 12:30 PM, but connection still active
4. What happens?

**Solution Options**:

**Option A: Grace Period (Recommended for MVP)**:
```python
# Allow expired tokens if connection already established
# Rationale: User authenticated initially, connection is secure

# During initial auth:
connection_auth_time = datetime.utcnow()

# During message handling:
token_age = (datetime.utcnow() - connection_auth_time).total_seconds()
if token_age > (ACCESS_TOKEN_EXPIRE_MINUTES * 60 + 300):  # +5 min grace
    # Connection too old, require re-auth
    await websocket.send_json( {
        "type"    : "auth_required",
        "reason"  : "Session expired",
        "message" : "Please refresh page to continue"
    } )
    await websocket.close()
```

**Option B: Periodic Re-authentication**:
```python
# Every 30 minutes, request new token from client
async def periodic_auth_check():
    while True:
        await asyncio.sleep( 1800 )  # 30 minutes

        # Send re-auth request
        await websocket.send_json( {
            "type"    : "reauth_required",
            "message" : "Please provide updated token"
        } )

        # Wait for new token
        auth_message = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=60  # 1 minute to respond
        )

        # Validate new token...
```
**Complexity**: Client must handle reauth flow, store refresh token, etc.

**Option C: Refresh Token in WebSocket** (Future Enhancement):
```python
# Client sends refresh token via WebSocket
await websocket.send_json( {
    "type"          : "refresh_request",
    "refresh_token" : stored_refresh_token
} )

# Server validates and returns new access token
await websocket.send_json( {
    "type"         : "refresh_success",
    "access_token" : new_access_token
} )
```
**Complexity**: WebSocket must handle token refresh logic, not typical pattern.

**DECISION for MVP**: **Option A (Grace Period)**
- Simplest implementation
- Reasonable security: Initial auth proves identity
- WebSocket connections are typically shorter than grace period
- Can add Options B/C in Phase 11 if needed

**Configuration**:
```ini
[Lupin: Baseline]
websocket connection max duration minutes = 60  # Force reconnect after 1 hour
```

### Session ID Validation Integration

**Current Validation** (`src/cosa/rest/routers/websocket.py:77-111`):

```python
def is_valid_session_id( session_id: str ) -> bool:
    """
    Validate session ID format: "adjective noun" (e.g., 'wise penguin').

    Pattern: ^[a-z]+ [a-z]+$ (lowercase words with single space)

    Security:
        - Rejects tabs, newlines, other whitespace (prevent injection)
        - Enforces single space only
    """
    if not session_id or not session_id.strip():
        return False

    # SECURITY: Reject non-space whitespace
    if any( c in session_id for c in ['\t', '\n', '\r', '\f', '\v'] ):
        return False

    # Check format
    pattern = r'^[a-z]+ [a-z]+$'
    return bool( re.match( pattern, session_id.lower() ) )
```

**Question**: Should session IDs continue to be user-generated "adjective noun" format, or switch to JWT-based session identifiers?

**Analysis**:

**Keep "adjective noun" format**:
- ✅ User-friendly: "wise penguin" easier to remember than UUID
- ✅ Existing pattern working well
- ✅ Session ID independent from authentication
- ✅ Multiple sessions per user (different "adjective noun" per tab)
- ❌ Collision possibility (low, but exists)

**Switch to JWT-based UUIDs**:
- ✅ Guaranteed unique: No collisions
- ✅ Cryptographically secure
- ❌ User-hostile: "7f3a9c2e-4b1d-..." not memorable
- ❌ Breaking change to frontend
- ❌ Session ID coupled to auth token

**DECISION**: **Keep "adjective noun" format**

**Rationale**:
- Session ID is a **presentation concern** (user experience)
- Authentication is a **security concern** (user identity)
- These are **separate concerns**, should not be coupled
- Current format user-friendly and working well
- No compelling reason to change

**Enhancement** (Optional, Phase 11):
- Add collision detection: Check if session_id already active
- If collision, append suffix: "wise penguin 2"
- Or reject and ask user to generate new session_id

### WebSocket Manager Integration

**Current Interface** (assumed from usage):
```python
class WebSocketManager:
    def add_connection( self, user_id: str, session_id: str, websocket: WebSocket ):
        """Add authenticated WebSocket connection."""
        pass

    def remove_connection( self, session_id: str ):
        """Remove WebSocket connection by session ID."""
        pass

    def get_connection( self, session_id: str ) -> WebSocket:
        """Get WebSocket by session ID."""
        pass

    def get_user_connections( self, user_id: str ) -> list[tuple[str, WebSocket]]:
        """Get all sessions for a user."""
        pass
```

**JWT Integration Enhancement**:
```python
def add_connection( self, user_id: str, session_id: str, websocket: WebSocket,
                   connection_metadata: dict ):
    """
    Add authenticated WebSocket connection.

    Args:
        connection_metadata: {
            "auth_time"      : "ISO8601 timestamp",
            "token_exp"      : "ISO8601 timestamp",
            "roles"          : ["user", "admin"],
            "email"          : "user@example.com",
            "ip_address"     : "192.168.1.100",  # Optional
            "user_agent"     : "Mozilla/5.0 ..."  # Optional
        }
    """
    self.connections[session_id] = {
        "user_id"   : user_id,
        "websocket" : websocket,
        "metadata"  : connection_metadata
    }

    # Index by user_id for quick lookup
    if user_id not in self.user_sessions:
        self.user_sessions[user_id] = []
    self.user_sessions[user_id].append( session_id )
```

**Use Cases**:
1. **Admin Dashboard**: Show all active sessions with metadata
2. **Security Monitoring**: Detect unusual connection patterns
3. **User Session Management**: "View Active Sessions" with device info
4. **Force Disconnect**: Admin can terminate specific sessions

**DECISION**: Enhance `add_connection()` to accept metadata dict (Phase 5)

---

## Backward Compatibility Strategy

### Configuration-Based Mode Switching

**Core Mechanism**: Single configuration key controls authentication mode across entire system.

**Configuration** (`lupin-app.ini`):
```ini
[Lupin: Development]
inherits = Lupin: Baseline

# Authentication mode: mock|jwt|firebase
auth mode = mock  # Start with mock for testing

[Lupin: Production]
inherits = Lupin: Baseline

auth mode = jwt  # Switch to real JWT in production

[Lupin: Baseline]
# Default configuration for all environments
auth mode = mock

# JWT-specific configuration (only used if auth_mode = jwt)
jwt secret key                       = ${JWT_SECRET_KEY}
jwt access token expire minutes      = 30
jwt refresh token expire days        = 7
jwt algorithm                        = HS256

# Authentication database
auth database path wo root           = /src/conf/auth/lupin-auth.db
```

**Explainer** (`lupin-app-splainer.ini`):
```ini
[Lupin: Baseline]
auth mode = Authentication mode selection. Options:
  - mock: Use mock tokens (mock_token_email_user@example.com) for development
  - jwt: Use real JWT tokens with database-backed users
  - firebase: Use Firebase Admin SDK for authentication (future)

  IMPORTANT: Mock mode is NOT SECURE and should only be used in development.
  Production deployments must use 'jwt' or 'firebase'.

jwt secret key = Secret key for signing JWT tokens.
  SECURITY: Must be set via environment variable JWT_SECRET_KEY.
  Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
  Never commit secret keys to version control.

  Development: Can use default key (warning logged)
  Production: MUST set JWT_SECRET_KEY environment variable or startup will fail

jwt access token expire minutes = Lifespan of access tokens in minutes.
  Default: 30 minutes (balance between security and user experience)
  Shorter: Better security, more frequent refreshes
  Longer: Better UX, higher security risk if token stolen

  Recommended range: 15-60 minutes

jwt refresh token expire days = Lifespan of refresh tokens in days.
  Default: 7 days (weekly re-login)
  Shorter: More frequent logins, better security
  Longer: Less frequent logins, higher risk

  Recommended range: 7-30 days

jwt algorithm = Algorithm for JWT signing.
  Options: HS256 (symmetric), RS256 (asymmetric)
  Default: HS256 (simpler key management)

  Use RS256 only if you need to distribute public verification key

auth database path wo root = Path to SQLite authentication database.
  Default: /src/conf/auth/lupin-auth.db
  Relative to project root

  Database stores: users, refresh_tokens, email_verification_tokens, password_reset_tokens
```

### Dual Token Support Implementation

**Strategy**: `verify_firebase_token()` function handles BOTH mock tokens and real JWTs transparently.

**Updated Function** (`src/cosa/rest/auth.py`):

```python
async def verify_firebase_token( token: str ) -> Dict:
    """
    Verify authentication token (mock or JWT based on configuration).

    Requires:
        - token is a non-empty string
        - config_mgr is initialized with auth_mode setting

    Ensures:
        - Returns dictionary with complete user information
        - Dictionary includes uid, email, name, email_verified, roles fields
        - User data is validated against database for JWT mode
        - Mock mode provides backward compatibility

    Raises:
        - HTTPException with 401 status if token validation fails
    """
    try:
        # SECURITY: Basic input validation
        if not isinstance( token, str ) or not token.strip():
            raise ValueError( "Invalid token format" )

        if len( token ) > 2000:  # Reasonable limit for both mock and JWT
            raise ValueError( "Token exceeds maximum length" )

        # Get authentication mode from configuration
        auth_mode = config_mgr.get( "auth mode", "mock" )

        # Route to appropriate validation logic
        if auth_mode == "jwt":
            return await verify_jwt_token( token )
        elif auth_mode == "mock":
            return await verify_mock_token( token )
        elif auth_mode == "firebase":
            # Future implementation
            raise HTTPException(
                status_code=501,
                detail="Firebase authentication not yet implemented"
            )
        else:
            raise ValueError( f"Unknown auth mode: {auth_mode}" )

    except HTTPException:
        # Pass through HTTP exceptions
        raise
    except Exception as e:
        print( f"[AUTH] Token verification failed: {e}" )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_jwt_token( token: str ) -> Dict:
    """
    Verify real JWT token and return user information.

    Requires:
        - token is a valid JWT string
        - SECRET_KEY and ALGORITHM are configured
        - User database is accessible

    Ensures:
        - Token signature is valid
        - Token is not expired
        - User exists and is active
        - Returns standardized user info dict

    Raises:
        - HTTPException with 401 if validation fails
    """
    try:
        # Decode and validate JWT
        payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

        # Validate token type (should be access token, not refresh)
        if payload.get( "token_type" ) == "refresh":
            raise ValueError( "Refresh token cannot be used for authentication" )

        # Extract claims
        user_id = payload.get( "sub" )
        email   = payload.get( "email" )
        roles   = payload.get( "roles", ["user"] )

        if not user_id or not email:
            raise ValueError( "Token missing required claims" )

        # Verify user still exists and is active in database
        user = get_user_from_db( user_id )
        if not user:
            raise ValueError( "User not found" )

        if not user["is_active"]:
            raise ValueError( "User account is disabled" )

        # Optional: Check if token JTI is revoked (if implementing per-token revocation)
        jti = payload.get( "jti" )
        if jti and is_token_revoked( jti ):
            raise ValueError( "Token has been revoked" )

        # Return standardized user info
        user_info = {
            "uid"            : user_id,
            "email"          : email,
            "name"           : user.get( "name", email.split( "@" )[0].capitalize() ),
            "email_verified" : user.get( "email_verified", False ),
            "roles"          : roles,
            "picture"        : None,  # For compatibility with Firebase structure
        }

        print( f"[AUTH] JWT verified for user: [{user_info['name']}] ({user_id})" )
        return user_info

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str( e )}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_mock_token( token: str ) -> Dict:
    """
    Verify mock token for development/testing (existing implementation).

    Requires:
        - token follows mock format: mock_token_* or mock_token_email_*
        - user_id_generator module is available

    Ensures:
        - Returns standardized user info dict
        - Compatible with JWT token return structure
        - Logs warning about mock mode usage

    Raises:
        - HTTPException with 401 if mock token format invalid
    """
    # Log warning about mock mode (only log once per session)
    global _mock_mode_warned
    if not _mock_mode_warned:
        print( "[AUTH] ⚠️  WARNING: Using MOCK authentication mode - NOT SECURE!" )
        print( "[AUTH] ⚠️  Set auth_mode=jwt in configuration for production" )
        _mock_mode_warned = True

    # Existing mock validation logic (unchanged)
    if not token.startswith( "mock_token_" ):
        raise ValueError( "Invalid mock token format" )

    # Check if it's the email-based format
    if token.startswith( "mock_token_email_" ):
        email = token.replace( "mock_token_email_", "" )
        if not email or '@' not in email:
            raise ValueError( "Invalid email in token" )
        system_id = email_to_system_id( email )
    else:
        # Legacy format
        system_id = token.replace( "mock_token_", "" )
        if not system_id:
            raise ValueError( "No system ID in token" )

    # Look up user in mock database
    user_data = get_user_info( system_id )
    if not user_data:
        # Generate default user info for unknown system IDs
        user_data = {
            "uid"            : system_id,
            "email"          : f"{system_id}@generated.local",
            "name"           : system_id.split( '_' )[0].capitalize(),
            "email_verified" : False,
            "roles"          : ["user"]
        }
    else:
        user_data["uid"] = system_id
        if "roles" not in user_data:
            user_data["roles"] = ["user"]

    # Return standardized structure
    user_info = {
        "uid"            : user_data["uid"],
        "email"          : user_data["email"],
        "name"           : user_data["name"],
        "email_verified" : user_data["email_verified"],
        "roles"          : user_data["roles"],
        "picture"        : None,
    }

    print( f"[AUTH] Mock token verified for user: [{user_info['name']}] ({user_info['uid']})" )
    return user_info


# Module-level flag to avoid spamming mock mode warning
_mock_mode_warned = False
```

**Key Design Decisions**:

1. **Single Entry Point**: All code continues calling `verify_firebase_token()`, no changes needed downstream

2. **Standardized Return Structure**: Both mock and JWT paths return identical dict structure:
   ```python
   {
       "uid"            : str,
       "email"          : str,
       "name"           : str,
       "email_verified" : bool,
       "roles"          : list[str],
       "picture"        : Optional[str]
   }
   ```

3. **Graceful Warnings**: Mock mode logs warning once per session, not on every request

4. **Forward Compatible**: Adding Firebase mode later is trivial (just another elif branch)

### Mock User Migration Script

**Purpose**: Convert existing mock users (ricardo, alice, bob) to real database accounts.

**Script** (`src/scripts/migrate_mock_to_jwt_users.py`):

```python
#!/usr/bin/env python3
"""
Migrate mock users from MOCK_USER_DATABASE to real authentication database.

This script:
1. Reads hardcoded mock users from user_id_generator.py
2. Creates real user accounts in authentication database
3. Generates default passwords (logged to console for development)
4. Optionally marks users as email_verified for development
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path( __file__ ).parent.parent.parent
sys.path.insert( 0, str( project_root / "src" ) )

from cosa.rest.user_id_generator import MOCK_USER_DATABASE
from cosa.rest.user_service import UserService
from cosa.rest.auth_database import init_auth_database
import cosa.utils.util as du


def migrate_mock_users( default_password: str = "DevPassword123!",
                        email_verified: bool = True ):
    """
    Migrate mock users to real authentication database.

    Requires:
        - MOCK_USER_DATABASE is accessible
        - Authentication database can be initialized
        - UserService is functional

    Ensures:
        - All mock users created in database
        - Default password set for each user
        - Email verification status set
        - No duplicate users created
        - Migration results logged

    Args:
        default_password: Password for all migrated users
        email_verified: Whether to mark users as verified
    """
    du.print_banner( "Mock User Migration", prepend_nl=True )

    print( f"Migrating {len( MOCK_USER_DATABASE )} mock users..." )
    print( f"Default password: {default_password}" )
    print( f"Email verified: {email_verified}" )
    print()

    # Initialize database
    print( "Initializing authentication database..." )
    init_auth_database()
    print( "✓ Database initialized" )
    print()

    # Initialize user service
    user_service = UserService()

    # Migrate each user
    migrated = 0
    skipped = 0

    for system_id, user_data in MOCK_USER_DATABASE.items():
        email = user_data["email"]
        name = user_data["name"]

        print( f"Migrating: {name} ({email})..." )

        try:
            # Check if user already exists
            existing_user = user_service.get_user_by_email( email )
            if existing_user:
                print( f"  ⚠️  User already exists, skipping" )
                skipped += 1
                continue

            # Create user account
            user_service.create_user(
                email           = email,
                password        = default_password,
                email_verified  = email_verified,
                roles           = ["user"]  # All start as regular users
            )

            print( f"  ✓ User created successfully" )
            print( f"    System ID: {system_id}" )
            print( f"    Email: {email}" )
            print( f"    Password: {default_password}" )
            migrated += 1

        except Exception as e:
            print( f"  ✗ Migration failed: {e}" )
            import traceback
            traceback.print_exc()

    print()
    print( "="*60 )
    print( f"Migration complete!" )
    print( f"  Migrated: {migrated}" )
    print( f"  Skipped: {skipped}" )
    print( f"  Total: {len( MOCK_USER_DATABASE )}" )
    print()
    print( "⚠️  IMPORTANT: Save the default password somewhere safe!" )
    print( f"   Default password: {default_password}" )
    print()
    print( "Users can now login with their email and this password." )
    print( "Recommend changing passwords after first login." )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser( description="Migrate mock users to JWT auth database" )
    parser.add_argument(
        "--password",
        default="DevPassword123!",
        help="Default password for migrated users (default: DevPassword123!)"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Do NOT mark emails as verified (require verification flow)"
    )

    args = parser.parse_args()

    migrate_mock_users(
        default_password = args.password,
        email_verified   = not args.no_verify
    )
```

**Usage**:
```bash
# Migrate with default password, emails verified
python src/scripts/migrate_mock_to_jwt_users.py

# Migrate with custom password
python src/scripts/migrate_mock_to_jwt_users.py --password "CustomPass456!"

# Migrate and require email verification
python src/scripts/migrate_mock_to_jwt_users.py --no-verify
```

**Integration into Phase 9**: Run this script as part of production deployment preparation.

### Deprecation Strategy

**Timeline**:
- **Phase 1-4**: Mock mode fully supported (default)
- **Phase 5-8**: JWT mode operational, mock mode supported with warnings
- **Phase 9**: Migration script run, configuration defaults to jwt
- **Phase 10**: Mock mode deprecated, warnings in documentation
- **Phase 11+**: Mock mode removed entirely (breaking change)

**Deprecation Warnings**:
```python
# In verify_mock_token()
if not _mock_mode_warned:
    print( "[AUTH] ⚠️  WARNING: MOCK authentication mode is DEPRECATED" )
    print( "[AUTH] ⚠️  Mock mode will be removed in version 0.1.0" )
    print( "[AUTH] ⚠️  Please migrate to auth_mode=jwt" )
    print( "[AUTH] ⚠️  See docs/authentication-guide.md for migration steps" )
    _mock_mode_warned = True
```

**Documentation Updates** (Phase 10):
- Add deprecation notice to README.md
- Update CLAUDE.md with migration guide
- Create migration checklist document
- Add warnings to configuration explainer

**DECISION**: Keep mock mode indefinitely for development/testing, but mark as insecure and document JWT as production requirement.

---

## Testing Strategy

### Testing Framework Overview

**Multi-Level Testing Approach**:

1. **Quick Smoke Tests**: Embedded in each module for rapid validation
   - Run with `python module_name.py`
   - Tests critical functionality paths
   - ~5-10 test cases per module
   - Used during development and debugging

2. **Unit Tests**: Comprehensive pytest suites
   - Located in `tests/` directory
   - Tests individual functions and edge cases
   - ~10-20 test cases per module
   - Run with `pytest tests/`

3. **Integration Tests**: Cross-module functionality testing
   - Tests authentication flow end-to-end
   - WebSocket authentication integration
   - Database operations with real SQLite
   - Token generation and validation

4. **Smoke Test Baseline**: System-wide validation
   - Uses `/smoke-test-baseline` slash command
   - Establishes comprehensive baseline before changes
   - Pure data collection, no remediation
   - Creates timestamped logs in `src/rnd/`

5. **Smoke Test Remediation**: Post-change verification
   - Uses `/smoke-test-remediation` slash command
   - Compares against baseline
   - Identifies regressions
   - Performs systematic remediation

### Testing Requirements by Phase

**Phase 1: JWT Service Foundation**
- Token generation (access + refresh)
- Token validation (signature, expiration)
- Secret key management
- Algorithm selection (HS256)

**Phase 2: User Management & Password Security**
- Database initialization
- User CRUD operations
- Password hashing (bcrypt)
- Password strength validation
- Authentication logic

**Phase 3: Authentication Endpoints**
- Register endpoint
- Login endpoint
- Token refresh endpoint
- Logout endpoint
- Request/response models

**Phase 4: Refresh Token Management**
- Token storage and hashing
- Token rotation
- Token revocation
- Cleanup operations

**Phase 5: WebSocket Authentication**
- JWT token validation in WebSocket
- Mock token backward compatibility
- Configuration-based routing
- User database lookup

**Phase 6: Authentication Middleware**
- FastAPI dependencies
- Role-based access control
- Admin/user role checks
- Permission enforcement

**Phase 7: Email Verification**
- Email service integration
- Token generation
- Verification flow
- Password reset flow

**Phase 8: Rate Limiting & Security**
- Failed login tracking
- Account lockout
- Audit logging
- Security headers

### Test Execution Guidelines

**Pre-Implementation**:
1. Run `/smoke-test-baseline full` to establish baseline
2. Review baseline report for current system state
3. Identify potential impact areas

**During Implementation**:
1. Write quick_smoke_test() for each new module
2. Run smoke test after each module completion
3. Fix issues immediately before proceeding

**Post-Implementation**:
1. Run `/smoke-test-remediation [baseline_report] FULL`
2. Review remediation report for regressions
3. Address critical issues before phase completion
4. Re-run baseline for next phase

**Continuous Testing**:
- Run `pytest` before each commit
- Verify all smoke tests pass
- Check for warning messages
- Validate configuration changes

---

## Configuration Management

### Configuration File Structure

**Primary Configuration**: `src/conf/lupin-app.ini`
**Documentation**: `src/conf/lupin-app-splainer.ini`

### Authentication Configuration Keys

```ini
[Lupin: Baseline]
# ================================
# Authentication Mode
# ================================
auth mode = mock

# ================================
# JWT Configuration
# ================================
jwt secret key                       = ${JWT_SECRET_KEY}
jwt access token expire minutes      = 30
jwt refresh token expire days        = 7
jwt algorithm                        = HS256

# ================================
# Database Configuration
# ================================
auth database path wo root           = /src/conf/auth/lupin-auth.db

# ================================
# Password Security
# ================================
auth password min length             = 8
auth password require complexity     = True
auth password check common           = True

# ================================
# Email Configuration (Phase 7)
# ================================
email smtp host                      = smtp.gmail.com
email smtp port                      = 587
email smtp use tls                   = True
email smtp username                  = ${EMAIL_USERNAME}
email smtp password                  = ${EMAIL_PASSWORD}
email from address                   = noreply@lupin.app
email from name                      = Lupin Authentication

# ================================
# Rate Limiting (Phase 8)
# ================================
auth max failed attempts             = 5
auth lockout duration minutes        = 15
auth cleanup old attempts hours      = 24

# ================================
# WebSocket Configuration
# ================================
websocket connection max duration minutes = 60
websocket grace period minutes            = 5

# ================================
# Application Configuration
# ================================
app base url                         = http://localhost:7999
```

### Environment Variables

**Required for Production**:
- `JWT_SECRET_KEY`: Secret key for JWT signing (256-bit, URL-safe base64)
- `EMAIL_USERNAME`: SMTP username for email service
- `EMAIL_PASSWORD`: SMTP password for email service

**Optional**:
- `ENVIRONMENT`: Set to "development" for dev mode, "production" for prod
- `LUPIN_CONFIG_MGR_CLI_ARGS`: Configuration manager arguments

### Configuration Access Pattern

```python
from cosa.config.configuration_manager import ConfigurationManager

config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

# Get configuration values
auth_mode = config_mgr.get( "auth mode", "mock" )
access_expire = config_mgr.get( "jwt access token expire minutes", 30, return_type="int" )
secret_key = config_mgr.get( "jwt secret key" )
```

### Configuration Validation

**Startup Validation**:
```python
def validate_auth_configuration():
    """
    Validate authentication configuration at startup.

    Ensures:
        - Required environment variables set for production
        - Valid auth_mode selection
        - JWT secret key present if auth_mode=jwt
        - Database path accessible
    """
    auth_mode = config_mgr.get( "auth mode", "mock" )

    if auth_mode == "jwt":
        secret_key = config_mgr.get( "jwt secret key" )
        if not secret_key or secret_key == "<REDACTED — row adce3547; JWT_SECRET_KEY is REQUIRED, there is no literal fallback>":
            if os.getenv( "ENVIRONMENT" ) == "production":
                raise ValueError( "JWT_SECRET_KEY must be set for production" )

    # Additional validation...
```

---

## Security Considerations

### Threat Model

**Primary Threats**:
1. **Credential Theft**: Attacker obtains user passwords
2. **Token Theft**: Attacker steals access or refresh tokens
3. **Brute Force**: Attacker attempts password guessing
4. **Session Hijacking**: Attacker takes over active session
5. **Database Breach**: Attacker gains access to database

### Security Principles

**Defense in Depth**:
- Multiple layers of security controls
- No single point of failure
- Assume any layer can be compromised

**Principle of Least Privilege**:
- Users have minimum necessary permissions
- Role-based access control limits capabilities
- Admin access tightly controlled

**Secure by Default**:
- Production requires JWT mode
- Development fallbacks warn loudly
- Insecure configurations rejected

### Mitigation Strategies

#### 1. Password Security

**Implementation**:
- Bcrypt hashing with 12 rounds
- Automatic salt generation
- Password strength requirements
- Common password rejection

**Protects Against**:
- Database breach (hashes can't be reversed)
- Rainbow table attacks (salt unique per password)
- Weak passwords (strength validation)

#### 2. Token Security

**Implementation**:
- Short-lived access tokens (30 min)
- Refresh token rotation
- Token hash storage in database
- JTI for per-token revocation

**Protects Against**:
- Token theft (limited exposure window)
- Token reuse (rotation invalidates old tokens)
- Database breach (hashed tokens unusable)

#### 3. Rate Limiting

**Implementation**:
- Failed login attempt tracking
- Account lockout after 5 failures
- 15-minute lockout duration
- Exponential backoff (future)

**Protects Against**:
- Brute force attacks
- Credential stuffing
- Automated attack tools

#### 4. Audit Logging

**Implementation**:
- Log all authentication events
- Track IP addresses and user agents
- Permanent audit trail
- Security event monitoring

**Protects Against**:
- Undetected breaches (audit trail for forensics)
- Insider threats (accountability)
- Compliance violations (evidence of controls)

#### 5. WebSocket Security

**Implementation**:
- Two-phase authentication
- Grace period for token expiration
- Connection duration limits
- Session ID validation

**Protects Against**:
- Unauthorized connections
- Session hijacking
- Replay attacks

### Security Headers

**HTTP Security Headers** (Phase 8):
```python
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY"
response.headers["X-XSS-Protection"] = "1; mode=block"
response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
```

**Protects Against**:
- MIME type sniffing attacks
- Clickjacking
- Cross-site scripting (XSS)
- Man-in-the-middle attacks

### Known Security Limitations

**Accepted Risks**:
1. **No 2FA**: Planned for Phase 11 (future enhancement)
2. **localStorage tokens**: XSS vulnerability, httpOnly cookies planned
3. **SQLite limitations**: May need PostgreSQL for scale
4. **Single secret key**: Key rotation requires coordination

**Future Enhancements**:
- Two-factor authentication (TOTP)
- Hardware security key support (WebAuthn)
- IP-based geo-fencing
- Anomaly detection
- Passwordless authentication

---

## Decision Log

| Date | Decision | Rationale | Alternatives Considered |
|------|----------|-----------|-------------------------|
| 2025.09.29 | Use SQLite for auth tables | Clear separation from LanceDB vector data, ACID transactions for auth | LanceDB (not optimized for relational), PostgreSQL (too heavy) |
| 2025.09.29 | HS256 for JWT algorithm | Simpler key management, faster, sufficient for monolithic app | RS256 (overkill for single-service architecture) |
| 2025.09.29 | Static refresh tokens (MVP) | Simpler implementation, acceptable for MVP | Rotating tokens (better security, more complex) |
| 2025.09.29 | Store refresh token hashes | Better security if database leaked | Store raw tokens (faster lookup but riskier) |
| 2025.09.29 | Bcrypt with 12 rounds | Balance security and performance | 14+ rounds (slower), Argon2 (newer but less tested) |
| 2025.09.29 | Keep "adjective noun" session IDs | User-friendly, working well, separate concern from auth | JWT-based UUIDs (less user-friendly) |
| 2025.09.29 | Grace period for WebSocket token expiration | Simplest for MVP, reasonable security | Periodic re-auth (more complex), refresh via WebSocket (non-standard) |
| 2025.09.29 | Dual token support during migration | Zero downtime migration, backward compatible | Hard cutover (risky), parallel systems (complex) |
| 2025.09.29 | Implement token rotation in Phase 3 | Changed from static to rotating refresh tokens for better security | Static tokens (simpler but less secure) |
| 2025.09.29 | Two-tier role system (admin/user only) | Simpler RBAC matching actual requirements, removed moderator concept | Three-tier (admin/moderator/user) - unnecessary complexity |
| 2025.09.29 | SMTP for email (Phase 7) | Simple, works with any email provider, no external dependencies | SendGrid (costs money), AWS SES (requires AWS account) |
| 2025.09.29 | In-memory rate limiting (Phase 8) | Simple, fast, sufficient for single-server deployment | Redis (overkill for MVP), database-backed (slower) |

---

**Document Purpose**: Architectural reference for JWT/OAuth authentication system. Extracted from monolithic design document and organized for reusability.

**Last Updated**: 2025.09.30
**Document Version**: 1.0
**Maintained By**: [LUPIN] Development Team