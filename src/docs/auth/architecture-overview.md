# Authentication Architecture Overview

**Version**: 1.0
**Last Updated**: 2025.10.04
**Target Audience**: Architects, Senior Developers

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Database Schema](#database-schema)
4. [Authentication Flows](#authentication-flows)
5. [Security Architecture](#security-architecture)
6. [Scalability Considerations](#scalability-considerations)

---

## System Overview

The Lupin Authentication System is a JWT-based authentication solution built on FastAPI with the following characteristics:

### Design Principles

- **Stateless Authentication**: JWT tokens carry all user information
- **Token Rotation**: Refresh tokens rotate on each use for enhanced security
- **Multi-Mode Support**: JWT (production), mock (development), Firebase (future)
- **Role-Based Access Control**: Admin/user roles with middleware enforcement
- **Audit Trail**: Comprehensive logging of all authentication events
- **Backward Compatibility**: Seamless integration with existing mock auth systems

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Web Framework | FastAPI 0.104+ | Async HTTP/WebSocket server |
| Authentication | PyJWT 2.10.1 | JWT token generation/validation |
| Password Hashing | bcrypt (via passlib 1.7.4) | Secure password storage |
| Database | SQLite 3 | Auth data persistence |
| Email | SMTP (via smtplib) | Verification & password reset emails |
| WebSocket | FastAPI WebSockets | Real-time authentication |

### System Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                     External Systems                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  Client  │  │  Mobile  │  │WebSocket │  │ Email MTA│       │
│  │  Browser │  │   App    │  │  Client  │  │(Gmail)   │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
└───────┼─────────────┼─────────────┼─────────────┼──────────────┘
        │             │             │             │
        │     HTTPS   │             │ WSS        │ SMTP
        │             │             │             │
┌───────┼─────────────┼─────────────┼─────────────┼──────────────┐
│       │             │             │             │              │
│  ┌────▼──────────────▼─────────────▼─────────────▼────┐       │
│  │          Lupin FastAPI Application                  │       │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐   │       │
│  │  │   Auth     │  │  WebSocket │  │   Email    │   │       │
│  │  │  Routers   │  │  Handlers  │  │  Service   │   │       │
│  │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘   │       │
│  │        │               │               │           │       │
│  │  ┌─────▼───────────────▼───────────────▼──────┐   │       │
│  │  │      Authentication Services                │   │       │
│  │  │  • JWT Service    • Refresh Token Service   │   │       │
│  │  │  • User Service   • Password Service        │   │       │
│  │  │  • Rate Limiter   • Audit Logger            │   │       │
│  │  └──────────────────┬──────────────────────────┘   │       │
│  │                     │                              │       │
│  │              ┌──────▼──────┐                       │       │
│  │              │  SQLite DB  │                       │       │
│  │              │  (auth.db)  │                       │       │
│  │              └─────────────┘                       │       │
│  └──────────────────────────────────────────────────┘       │
│                                                               │
│                  Lupin Application Server                    │
└───────────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### Core Components

#### 1. JWT Service (`jwt_service.py`)

**Responsibilities**:
- Generate access and refresh tokens
- Validate token signatures and expiration
- Decode token payloads
- Type-based token validation (access vs refresh)

**Key Functions**:
```python
def generate_tokens( user_id: int, email: str, roles: List[str] ) -> Tuple[str, str]
    # Returns: (access_token, refresh_token)

def decode_and_validate_token( token: str, expected_type: str ) -> Dict
    # Validates and returns token payload

def generate_access_token( user_id: int, email: str, roles: List[str] ) -> str
def generate_refresh_token( user_id: int ) -> str
```

**Configuration**:
- `jwt secret key`: Signing key (HS256)
- `jwt access token expiration seconds`: 1800 (30 min)
- `jwt refresh token expiration days`: 7

---

#### 2. User Service (`user_service.py`)

**Responsibilities**:
- User registration with password hashing
- User authentication (email/password verification)
- User lookup by ID and email
- Password updates
- Email verification status management

**Key Functions**:
```python
def register_user( email: str, password: str ) -> Tuple[bool, str, Optional[Dict]]
    # Hashes password, creates user, returns user data

def authenticate_user( email: str, password: str ) -> Tuple[bool, str, Optional[Dict]]
    # Verifies credentials, returns user data

def get_user_by_id( user_id: int ) -> Optional[Dict]
def get_user_by_email( email: str ) -> Optional[Dict]

def update_user_password( user_id: int, old_password: str, new_password: str ) -> Tuple[bool, str]
def mark_email_verified( user_id: int ) -> bool
```

**Database Tables**: `users`

---

#### 3. Password Service (`password_service.py`)

**Responsibilities**:
- Password hashing (bcrypt)
- Password verification
- Password strength validation

**Key Functions**:
```python
def hash_password( password: str ) -> str
    # bcrypt hash with 12 rounds

def verify_password( plain_password: str, hashed_password: str ) -> bool
    # Constant-time comparison

def validate_password_strength( password: str ) -> Tuple[bool, str]
    # Enforces complexity requirements
```

**Security Features**:
- bcrypt algorithm (resistant to rainbow tables)
- 12 rounds (configurable, ~250ms per hash)
- Constant-time comparison (timing attack protection)

---

#### 4. Refresh Token Service (`refresh_token_service.py`)

**Responsibilities**:
- Store refresh tokens (SHA-256 hashed)
- Validate refresh tokens
- Revoke tokens (logout)
- Cleanup expired tokens
- Token rotation on refresh

**Key Functions**:
```python
def create_refresh_token( user_id: int, token: str ) -> bool
    # Stores SHA-256 hash of token

def validate_refresh_token( token: str ) -> Optional[int]
    # Returns user_id if valid

def revoke_refresh_token( token: str ) -> bool
def revoke_all_user_tokens( user_id: int ) -> int
def cleanup_expired_refresh_tokens() -> int
```

**Database Tables**: `refresh_tokens`

---

#### 5. Rate Limiter (`rate_limiter.py`)

**Responsibilities**:
- Track failed login attempts
- Enforce account lockout
- Reset on successful login

**Key Functions**:
```python
def record_failed_attempt( email: str, ip_address: str ) -> None
def is_account_locked( email: str ) -> bool
def reset_failed_attempts( email: str ) -> None
def get_failed_attempts_count( email: str ) -> int
```

**Configuration**:
- `auth max failed attempts`: 5
- `auth lockout duration minutes`: 15

**Database Tables**: `failed_login_attempts`

---

#### 6. Auth Audit Logger (`auth_audit.py`)

**Responsibilities**:
- Log all authentication events
- Track IP addresses and user agents
- Support incident response and compliance

**Event Types**:
- `login_success`, `login_failure`
- `register`, `logout`
- `password_changed`, `password_reset_requested`, `password_reset_completed`
- `email_verification_requested`, `email_verified`

**Key Functions**:
```python
def log_auth_event( event_type: str, user_id: Optional[int], email: str,
                    ip_address: str, user_agent: str, metadata: Optional[Dict] ) -> None
```

**Database Tables**: `auth_audit_log`

---

#### 7. Email Token Service (`email_token_service.py`)

**Responsibilities**:
- Generate verification/reset tokens
- Validate tokens
- Cleanup expired tokens

**Key Functions**:
```python
def generate_verification_token( user_id: int ) -> Tuple[bool, str, Optional[str]]
def validate_verification_token( token: str ) -> Tuple[bool, str, Optional[int]]

def generate_password_reset_token( user_id: int ) -> Tuple[bool, str, Optional[str]]
def validate_password_reset_token( token: str ) -> Tuple[bool, str, Optional[int]]
```

**Token Lifetimes**:
- Verification: 24 hours
- Password reset: 1 hour

**Database Tables**: `email_verification_tokens`, `password_reset_tokens`

---

#### 8. Email Service (`email_service.py`)

**Responsibilities**:
- Send verification emails
- Send password reset emails
- SMTP connection management

**Key Functions**:
```python
def send_verification_email( to_email: str, verification_token: str ) -> Tuple[bool, str]
def send_password_reset_email( to_email: str, reset_token: str ) -> Tuple[bool, str]
```

**Configuration**:
- `smtp host`, `smtp port`, `smtp username`, `smtp password`
- `smtp use tls`, `smtp from email`
- `app base url` (for email links)

---

#### 9. Auth Middleware (`auth_middleware.py`)

**Responsibilities**:
- FastAPI dependency injection for authentication
- Role-based access control (RBAC)
- Current user extraction from JWT

**Key Dependencies**:
```python
async def get_current_user( credentials: HTTPAuthorizationCredentials ) -> Dict
    # Required authentication - raises 401 if invalid

async def get_current_user_optional( credentials: Optional[...] ) -> Optional[Dict]
    # Optional authentication - returns None if not authenticated

# RBAC functions
def require_roles( *roles: str ) -> Callable
def require_all_roles( *roles: str ) -> Callable
def is_admin( user: Dict ) -> bool
def is_user( user: Dict ) -> bool
```

**Usage Example**:
```python
@router.get("/admin-only")
async def admin_endpoint( current_user: Dict = Depends( require_admin ) ):
    # Only admins can access
    return {"admin": current_user["email"]}
```

---

### Component Interactions

**Registration Flow**:
```
Client → Auth Router → User Service → Password Service → Auth Database
                    → Email Token Service → Email Service → SMTP
```

**Login Flow**:
```
Client → Auth Router → User Service → Password Service (verify)
                    → Rate Limiter (check/record)
                    → JWT Service (generate tokens)
                    → Refresh Token Service (store)
                    → Auth Audit (log event)
                    → Client (return tokens)
```

**Protected Endpoint Flow**:
```
Client → Auth Middleware → JWT Service (validate)
                        → User Service (lookup)
                        → Route Handler (execute)
```

**Token Refresh Flow**:
```
Client → Auth Router → Refresh Token Service (validate)
                    → JWT Service (generate new tokens)
                    → Refresh Token Service (rotate - revoke old, store new)
                    → Client (return new tokens)
```

---

## Database Schema

### Entity Relationship Diagram

```
┌─────────────────┐
│     users       │
│─────────────────│
│ id (PK)         │◄────────┬──────────────────┐
│ email (UNIQUE)  │         │                  │
│ password_hash   │         │                  │
│ email_verified  │         │                  │
│ is_active       │         │                  │
│ roles (JSON)    │         │                  │
│ created_at      │         │                  │
│ last_login_at   │         │                  │
└─────────────────┘         │                  │
                             │                  │
      ┌──────────────────────┼──────────────────┼──────────────┐
      │                      │                  │              │
      │                      │                  │              │
┌─────▼──────────────┐ ┌─────▼──────────────┐ │ ┌────────────▼────────┐
│ refresh_tokens     │ │ failed_login_      │ │ │ email_verification_ │
│────────────────────│ │   attempts         │ │ │   tokens            │
│ id (PK)            │ │────────────────────│ │ │─────────────────────│
│ user_id (FK)       │ │ id (PK)            │ │ │ id (PK)             │
│ token_hash (UNIQUE)│ │ user_id (FK)       │ │ │ user_id (FK)        │
│ created_at         │ │ ip_address         │ │ │ token (UNIQUE)      │
│ expires_at         │ │ attempted_at       │ │ │ created_at          │
└────────────────────┘ └────────────────────┘ │ │ expires_at          │
                                               │ │ used                │
┌──────────────────────────────────────────────┤ └─────────────────────┘
│                                              │
│                                              │
│                                              │
│  ┌───────────────────────┐ ┌────────────────▼────────┐
│  │ auth_audit_log        │ │ password_reset_         │
│  │───────────────────────│ │   tokens                │
│  │ id (PK)               │ │─────────────────────────│
│  │ user_id (FK nullable) │ │ id (PK)                 │
│  │ email                 │ │ user_id (FK)            │
│  │ event_type            │ │ token (UNIQUE)          │
│  │ ip_address            │ │ created_at              │
│  │ user_agent            │ │ expires_at              │
│  │ metadata (JSON)       │ │ used                    │
│  │ created_at            │ └─────────────────────────┘
│  └───────────────────────┘
│
└────────────────────┘
```

### Table Definitions

#### users
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email_verified BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    roles TEXT NOT NULL,  -- JSON array: ["user"], ["admin", "user"]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active);
```

#### refresh_tokens
```sql
CREATE TABLE refresh_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,  -- SHA-256 hash
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens(expires_at);
```

#### failed_login_attempts
```sql
CREATE TABLE failed_login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,  -- Nullable (email may not exist)
    email TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_failed_login_email ON failed_login_attempts(email);
CREATE INDEX idx_failed_login_time ON failed_login_attempts(attempted_at);
```

#### auth_audit_log
```sql
CREATE TABLE auth_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,  -- Nullable
    email TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'login_success', 'password_changed', etc.
    ip_address TEXT,
    user_agent TEXT,
    metadata TEXT,  -- JSON for additional data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_audit_user ON auth_audit_log(user_id);
CREATE INDEX idx_audit_event ON auth_audit_log(event_type);
CREATE INDEX idx_audit_time ON auth_audit_log(created_at);
```

#### email_verification_tokens
```sql
CREATE TABLE email_verification_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_verification_token ON email_verification_tokens(token);
CREATE INDEX idx_verification_user ON email_verification_tokens(user_id);
```

#### password_reset_tokens
```sql
CREATE TABLE password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_reset_token ON password_reset_tokens(token);
CREATE INDEX idx_reset_user ON password_reset_tokens(user_id);
```

---

## Authentication Flows

### Registration & Email Verification

```
┌──────┐                  ┌──────────┐                   ┌──────────┐
│Client│                  │ FastAPI  │                   │   SMTP   │
└───┬──┘                  └────┬─────┘                   └────┬─────┘
    │                          │                              │
    │ POST /auth/register      │                              │
    ├─────────────────────────►│                              │
    │ {email, password}        │                              │
    │                          │                              │
    │                          ├──► hash_password()           │
    │                          ├──► INSERT INTO users         │
    │                          │                              │
    │ 201 Created              │                              │
    │ {user, message}          │                              │
    │◄─────────────────────────┤                              │
    │                          │                              │
    │ POST /auth/request-      │                              │
    │   verification           │                              │
    ├─────────────────────────►│                              │
    │ Authorization: Bearer... │                              │
    │                          │                              │
    │                          ├──► generate_token()          │
    │                          ├──► INSERT INTO email_...     │
    │                          │                              │
    │                          │ Send verification email      │
    │                          ├─────────────────────────────►│
    │                          │                              │
    │ 200 OK                   │                              │
    │◄─────────────────────────┤                              │
    │                          │                              │
    │                          │                              │
    │ [User clicks link in email with token]                  │
    │                          │                              │
    │ POST /auth/verify-email  │                              │
    ├─────────────────────────►│                              │
    │ {token}                  │                              │
    │                          │                              │
    │                          ├──► validate_token()          │
    │                          ├──► UPDATE users SET          │
    │                          │     email_verified = 1       │
    │                          ├──► UPDATE tokens SET used=1  │
    │                          │                              │
    │ 200 OK                   │                              │
    │◄─────────────────────────┤                              │
```

### Login with Rate Limiting

```
┌──────┐             ┌──────────┐              ┌──────────┐
│Client│             │ FastAPI  │              │ Database │
└───┬──┘             └────┬─────┘              └────┬─────┘
    │                     │                         │
    │ POST /auth/login    │                         │
    ├────────────────────►│                         │
    │ {email, password}   │                         │
    │                     │                         │
    │                     ├──► is_account_locked()  │
    │                     ├────────────────────────►│
    │                     │◄────────────────────────┤
    │                     │ locked? NO              │
    │                     │                         │
    │                     ├──► authenticate_user()  │
    │                     ├────────────────────────►│
    │                     │ SELECT ... WHERE email  │
    │                     │◄────────────────────────┤
    │                     │ {user_data}             │
    │                     │                         │
    │                     ├──► verify_password()    │
    │                     │ [bcrypt comparison]     │
    │                     │                         │
    │  ┌─── Success ──────┤                         │
    │  │                  │                         │
    │  │                  ├──► reset_failed_attempts│
    │  │                  ├────────────────────────►│
    │  │                  │ DELETE WHERE email      │
    │  │                  │                         │
    │  │                  ├──► generate_tokens()    │
    │  │                  ├──► store_refresh_token()│
    │  │                  ├────────────────────────►│
    │  │                  │ INSERT INTO refresh_... │
    │  │                  │                         │
    │  │                  ├──► log_auth_event()     │
    │  │                  ├────────────────────────►│
    │  │                  │ INSERT INTO audit_log   │
    │  │                  │                         │
    │  │ 200 OK           │                         │
    │  │ {user, tokens}   │                         │
    │  │◄─────────────────┤                         │
    │  │                  │                         │
    │  └────────────────────────────────────────────┘
    │                     │                         │
    │  ┌─── Failure ──────┤                         │
    │  │                  │                         │
    │  │                  ├──► record_failed_attempt│
    │  │                  ├────────────────────────►│
    │  │                  │ INSERT INTO failed_...  │
    │  │                  │                         │
    │  │                  ├──► get_failed_count()   │
    │  │                  ├────────────────────────►│
    │  │                  │◄────────────────────────┤
    │  │                  │ count = 5 → LOCKED!     │
    │  │                  │                         │
    │  │ 429 Too Many Req │                         │
    │  │ {lockout message}│                         │
    │  │◄─────────────────┤                         │
    │  │                  │                         │
    │  └────────────────────────────────────────────┘
```

### Token Refresh with Rotation

```
┌──────┐              ┌──────────┐               ┌──────────┐
│Client│              │ FastAPI  │               │ Database │
└───┬──┘              └────┬─────┘               └────┬─────┘
    │                      │                          │
    │ POST /auth/refresh   │                          │
    ├─────────────────────►│                          │
    │ {refresh_token}      │                          │
    │                      │                          │
    │                      ├──► validate_refresh_token│
    │                      ├─────────────────────────►│
    │                      │ SELECT ... WHERE         │
    │                      │   token_hash = SHA256()  │
    │                      │◄─────────────────────────┤
    │                      │ {user_id}                │
    │                      │                          │
    │                      ├──► get_user_by_id()      │
    │                      ├─────────────────────────►│
    │                      │◄─────────────────────────┤
    │                      │ {user_data}              │
    │                      │                          │
    │                      ├──► generate_new_tokens() │
    │                      │                          │
    │                      ├──► revoke_old_token()    │
    │                      ├─────────────────────────►│
    │                      │ DELETE WHERE token_hash  │
    │                      │                          │
    │                      ├──► store_new_token()     │
    │                      ├─────────────────────────►│
    │                      │ INSERT INTO refresh_...  │
    │                      │                          │
    │ 200 OK               │                          │
    │ {new_tokens}         │                          │
    │ - access_token (NEW) │                          │
    │ - refresh_token(NEW) │                          │
    │◄─────────────────────┤                          │
    │                      │                          │
    │ [Client stores both  │                          │
    │  new tokens]         │                          │
```

---

## Security Architecture

### Defense Layers

1. **Transport Security** (HTTPS)
   - TLS 1.2+ encryption
   - HSTS header enforcement

2. **Authentication Security**
   - bcrypt password hashing (12 rounds)
   - JWT signature verification (HS256)
   - Token expiration enforcement

3. **Authorization Security**
   - RBAC middleware
   - Role checking on endpoints
   - Admin privilege separation

4. **Rate Limiting**
   - Failed login tracking
   - Account lockout (5 attempts, 15 min)
   - IP-based tracking

5. **Audit Logging**
   - All auth events logged
   - IP and user agent tracking
   - Forensics and compliance

6. **Input Validation**
   - Pydantic models
   - Email format validation
   - Password strength requirements

7. **Security Headers**
   - X-Frame-Options: DENY
   - X-Content-Type-Options: nosniff
   - X-XSS-Protection: 1; mode=block
   - Strict-Transport-Security: max-age=31536000

---

## Scalability Considerations

### Current Limitations (SQLite)

- **Single-writer concurrency**: SQLite locks on writes
- **File-based storage**: Not ideal for distributed systems
- **No connection pooling**: Direct file access

### Migration Path to Production Database

**PostgreSQL Migration** (Future):
```python
# Replace SQLite with PostgreSQL
DATABASE_URL = "postgresql://user:pass@host/dbname"

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=40
)
```

**Benefits**:
- Horizontal scalability
- Better concurrency
- Connection pooling
- Replication support

### Horizontal Scaling

**Current (Single Server)**:
- Uvicorn with 4 workers
- Shared SQLite database
- In-memory rate limiting

**Future (Multi-Server)**:
- Load balancer (nginx/HAProxy)
- PostgreSQL database cluster
- Redis for rate limiting
- Shared session storage

---

## Next Steps

- **[API Reference](api-reference.md)** - Detailed endpoint documentation
- **[Security Guide](security-guide.md)** - Security best practices
- **[Operations Guide](operations-guide.md)** - Deployment and maintenance

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Architecture Team
