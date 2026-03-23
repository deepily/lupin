# Authentication API Reference

**Version**: 1.0
**Base URL**: `http://localhost:7999` (development) | `https://your-domain.com` (production)
**Authentication**: Bearer tokens (JWT)
**Last Updated**: 2025.10.04

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication Flow](#authentication-flow)
3. [Endpoint Reference](#endpoint-reference)
   - [Registration & Login](#registration--login)
   - [Token Management](#token-management)
   - [User Profile](#user-profile)
   - [Password Management](#password-management)
   - [Email Verification](#email-verification)
4. [Common Response Codes](#common-response-codes)
5. [Rate Limiting](#rate-limiting)
6. [Error Handling](#error-handling)

---

## Overview

The Lupin Authentication API provides JWT-based authentication with the following features:

- **Email/password registration and login**
- **JWT access tokens** (30-minute expiration)
- **Refresh tokens** (7-day expiration with rotation)
- **Role-Based Access Control** (RBAC) - admin/user roles
- **Email verification workflow**
- **Password reset functionality**
- **Rate limiting** (5 failed attempts = 15-minute lockout)
- **Security hardening** (bcrypt hashing, audit logging, security headers)

---

## Authentication Flow

### Standard Login Flow

```
1. POST /auth/login → Receive access_token + refresh_token
2. Use access_token in Authorization header for protected endpoints
3. When access_token expires (30 min):
   - POST /auth/refresh with refresh_token
   - Receive new access_token + new refresh_token (rotation)
4. Repeat step 3 as needed (refresh tokens valid for 7 days)
```

### First-Time Registration Flow

```
1. POST /auth/register → Create account
2. POST /auth/login → Get tokens
3. (Optional) POST /auth/request-verification → Send verification email
4. POST /auth/verify-email → Verify email with token
```

---

## Endpoint Reference

### Registration & Login

#### POST /auth/register

Register a new user account.

**Request**:
```http
POST /auth/register HTTP/1.1
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecureP@ssw0rd!"
}
```

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | Valid email address |
| password | string | Yes | Min 8 chars, must include uppercase, lowercase, number, special char |

**Success Response** (201 Created):
```json
{
  "message": "User created successfully",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "email_verified": false,
    "is_active": true,
    "roles": ["user"],
    "created_at": "2025-10-04T10:30:00Z"
  }
}
```

**Error Responses**:
- **400 Bad Request**: Invalid email format or weak password
  ```json
  {
    "detail": "Password must be at least 8 characters and contain uppercase, lowercase, number, and special character"
  }
  ```
- **409 Conflict**: Email already registered
  ```json
  {
    "detail": "User with this email already exists"
  }
  ```

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "password": "MySecure123!"
  }'
```

**JavaScript Example**:
```javascript
const response = await fetch( 'http://localhost:7999/auth/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'alice@example.com',
    password: 'MySecure123!'
  })
});

const data = await response.json();
console.log( data.user );
```

---

#### POST /auth/login

Authenticate user and receive JWT tokens.

**Request**:
```http
POST /auth/login HTTP/1.1
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecureP@ssw0rd!"
}
```

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | Registered email address |
| password | string | Yes | User password |

**Success Response** (200 OK):
```json
{
  "message": "Login successful",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "email_verified": false,
    "roles": ["user"]
  },
  "tokens": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

**Error Responses**:
- **401 Unauthorized**: Invalid credentials
  ```json
  {
    "detail": "Invalid email or password"
  }
  ```
- **429 Too Many Requests**: Account locked due to failed attempts
  ```json
  {
    "detail": "Account is locked due to too many failed login attempts. Try again in 15 minutes."
  }
  ```

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "password": "MySecure123!"
  }'
```

**JavaScript Example**:
```javascript
const response = await fetch( 'http://localhost:7999/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'alice@example.com',
    password: 'MySecure123!'
  })
});

const data = await response.json();
// Store tokens securely
localStorage.setItem( 'access_token', data.tokens.access_token );
localStorage.setItem( 'refresh_token', data.tokens.refresh_token );
```

---

### Token Management

#### POST /auth/refresh

Refresh access token using refresh token. Implements token rotation for security.

**Request**:
```http
POST /auth/refresh HTTP/1.1
Content-Type: application/json

{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| refresh_token | string | Yes | Valid refresh token from login/previous refresh |

**Success Response** (200 OK):
```json
{
  "tokens": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

**Important**: Both tokens rotate on refresh. Always store the new refresh token.

**Error Responses**:
- **401 Unauthorized**: Invalid or expired refresh token
  ```json
  {
    "detail": "Invalid or expired refresh token"
  }
  ```

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**JavaScript Example**:
```javascript
async function refreshAccessToken() {
  const refreshToken = localStorage.getItem( 'refresh_token' );

  const response = await fetch( 'http://localhost:7999/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  if ( response.ok ) {
    const data = await response.json();
    // Store new tokens (rotation)
    localStorage.setItem( 'access_token', data.tokens.access_token );
    localStorage.setItem( 'refresh_token', data.tokens.refresh_token );
    return data.tokens.access_token;
  } else {
    // Refresh failed - redirect to login
    window.location.href = '/login';
  }
}
```

---

#### POST /auth/logout

Revoke refresh token (logout).

**Request**:
```http
POST /auth/logout HTTP/1.1
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| Authorization | Yes | Bearer {access_token} |

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| refresh_token | string | Yes | Refresh token to revoke |

**Success Response** (200 OK):
```json
{
  "message": "Logged out successfully"
}
```

**Error Responses**:
- **401 Unauthorized**: Invalid access token
- **400 Bad Request**: Refresh token not provided

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/logout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -d '{
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**JavaScript Example**:
```javascript
async function logout() {
  const accessToken = localStorage.getItem( 'access_token' );
  const refreshToken = localStorage.getItem( 'refresh_token' );

  await fetch( 'http://localhost:7999/auth/logout', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`
    },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  // Clear local storage
  localStorage.removeItem( 'access_token' );
  localStorage.removeItem( 'refresh_token' );

  window.location.href = '/login';
}
```

---

### User Profile

#### GET /auth/me

Get current authenticated user information.

**Request**:
```http
GET /auth/me HTTP/1.1
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| Authorization | Yes | Bearer {access_token} |

**Success Response** (200 OK):
```json
{
  "id": 1,
  "email": "user@example.com",
  "email_verified": true,
  "is_active": true,
  "roles": ["user", "admin"],
  "created_at": "2025-10-04T10:30:00Z",
  "last_login_at": "2025-10-04T14:20:00Z"
}
```

**Error Responses**:
- **401 Unauthorized**: Invalid or expired access token
  ```json
  {
    "detail": "Could not validate credentials"
  }
  ```

**cURL Example**:
```bash
curl -X GET http://localhost:7999/auth/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**JavaScript Example**:
```javascript
async function getCurrentUser() {
  const accessToken = localStorage.getItem( 'access_token' );

  const response = await fetch( 'http://localhost:7999/auth/me', {
    headers: {
      'Authorization': `Bearer ${accessToken}`
    }
  });

  if ( response.ok ) {
    const user = await response.json();
    return user;
  } else if ( response.status === 401 ) {
    // Token expired - try refresh
    await refreshAccessToken();
    return getCurrentUser(); // Retry
  }
}
```

---

### Password Management

#### PUT /auth/change-password

Change user password (requires current password verification).

**Request**:
```http
PUT /auth/change-password HTTP/1.1
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

{
  "current_password": "OldP@ssw0rd!",
  "new_password": "NewSecureP@ss123!"
}
```

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| Authorization | Yes | Bearer {access_token} |

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| current_password | string | Yes | User's current password |
| new_password | string | Yes | New password (must meet strength requirements) |

**Success Response** (200 OK):
```json
{
  "message": "Password changed successfully"
}
```

**Error Responses**:
- **400 Bad Request**: New password doesn't meet requirements
  ```json
  {
    "detail": "Password must be at least 8 characters and contain uppercase, lowercase, number, and special character"
  }
  ```
- **401 Unauthorized**: Current password incorrect
  ```json
  {
    "detail": "Current password is incorrect"
  }
  ```

**cURL Example**:
```bash
curl -X PUT http://localhost:7999/auth/change-password \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -d '{
    "current_password": "OldP@ssw0rd!",
    "new_password": "NewSecureP@ss123!"
  }'
```

**JavaScript Example**:
```javascript
async function changePassword( currentPassword, newPassword ) {
  const accessToken = localStorage.getItem( 'access_token' );

  const response = await fetch( 'http://localhost:7999/auth/change-password', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword
    })
  });

  if ( response.ok ) {
    const data = await response.json();
    alert( 'Password changed successfully!' );
  } else {
    const error = await response.json();
    alert( `Error: ${error.detail}` );
  }
}
```

---

#### POST /auth/request-password-reset

Request password reset email (security-conscious - no email enumeration).

**Request**:
```http
POST /auth/request-password-reset HTTP/1.1
Content-Type: application/json

{
  "email": "user@example.com"
}
```

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | Email address to send reset link |

**Success Response** (200 OK):
```json
{
  "message": "If an account exists with this email, a password reset link has been sent"
}
```

**Note**: Always returns 200 OK to prevent email enumeration attacks.

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/request-password-reset \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com"
  }'
```

**JavaScript Example**:
```javascript
async function requestPasswordReset( email ) {
  const response = await fetch( 'http://localhost:7999/auth/request-password-reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: email })
  });

  // Always shows success message (security)
  alert( 'If an account exists with this email, a password reset link has been sent.' );
}
```

---

#### POST /auth/reset-password

Reset password using token from email.

**Request**:
```http
POST /auth/reset-password HTTP/1.1
Content-Type: application/json

{
  "token": "reset_token_from_email",
  "new_password": "NewSecureP@ss123!"
}
```

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| token | string | Yes | Reset token from email (1-hour validity) |
| new_password | string | Yes | New password (must meet strength requirements) |

**Success Response** (200 OK):
```json
{
  "message": "Password reset successfully"
}
```

**Error Responses**:
- **400 Bad Request**: Invalid or expired token
  ```json
  {
    "detail": "Invalid or expired reset token"
  }
  ```
- **400 Bad Request**: Password doesn't meet requirements

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{
    "token": "abc123resettoken",
    "new_password": "NewSecureP@ss123!"
  }'
```

**JavaScript Example**:
```javascript
async function resetPassword( token, newPassword ) {
  const response = await fetch( 'http://localhost:7999/auth/reset-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      token: token,
      new_password: newPassword
    })
  });

  if ( response.ok ) {
    alert( 'Password reset successfully! Please login.' );
    window.location.href = '/login';
  } else {
    const error = await response.json();
    alert( `Error: ${error.detail}` );
  }
}
```

---

### Email Verification

#### POST /auth/request-verification

Request new email verification link (authenticated).

**Request**:
```http
POST /auth/request-verification HTTP/1.1
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| Authorization | Yes | Bearer {access_token} |

**Success Response** (200 OK):
```json
{
  "message": "Verification email sent"
}
```

**Error Responses**:
- **400 Bad Request**: Email already verified
  ```json
  {
    "detail": "Email is already verified"
  }
  ```
- **401 Unauthorized**: Invalid access token

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/request-verification \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**JavaScript Example**:
```javascript
async function requestEmailVerification() {
  const accessToken = localStorage.getItem( 'access_token' );

  const response = await fetch( 'http://localhost:7999/auth/request-verification', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`
    }
  });

  if ( response.ok ) {
    alert( 'Verification email sent! Check your inbox.' );
  }
}
```

---

#### POST /auth/verify-email

Verify email address using token from email.

**Request**:
```http
POST /auth/verify-email HTTP/1.1
Content-Type: application/json

{
  "token": "verification_token_from_email"
}
```

**Request Body**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| token | string | Yes | Verification token from email (24-hour validity) |

**Success Response** (200 OK):
```json
{
  "message": "Email verified successfully"
}
```

**Error Responses**:
- **400 Bad Request**: Invalid or expired token
  ```json
  {
    "detail": "Invalid or expired verification token"
  }
  ```

**cURL Example**:
```bash
curl -X POST http://localhost:7999/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{
    "token": "abc123verifytoken"
  }'
```

**JavaScript Example**:
```javascript
async function verifyEmail( token ) {
  const response = await fetch( 'http://localhost:7999/auth/verify-email', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: token })
  });

  if ( response.ok ) {
    alert( 'Email verified successfully!' );
    window.location.href = '/profile';
  } else {
    const error = await response.json();
    alert( `Verification failed: ${error.detail}` );
  }
}
```

---

## Common Response Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Request successful |
| 201 | Created | Resource created (registration) |
| 400 | Bad Request | Invalid input data |
| 401 | Unauthorized | Invalid or missing authentication |
| 403 | Forbidden | Valid auth but insufficient permissions |
| 404 | Not Found | Resource not found |
| 409 | Conflict | Resource already exists (duplicate email) |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server error |

---

## Rate Limiting

**Login Endpoint Rate Limiting**:
- **Limit**: 5 failed attempts per email
- **Window**: 15 minutes
- **Action**: Account locked for 15 minutes after 5th failed attempt
- **Reset**: Successful login clears failed attempt counter

**Status Code**: `429 Too Many Requests`

**Example Response**:
```json
{
  "detail": "Account is locked due to too many failed login attempts. Try again in 15 minutes."
}
```

**Configuration** (lupin-app.ini):
```ini
auth max failed attempts = 5
auth lockout duration minutes = 15
```

---

## Error Handling

### Standard Error Response Format

All errors follow FastAPI's standard format:

```json
{
  "detail": "Human-readable error message"
}
```

### Common Error Scenarios

**1. Token Expired**:
```json
{
  "detail": "Token has expired"
}
```
**Action**: Use refresh token to get new access token

**2. Invalid Token**:
```json
{
  "detail": "Could not validate credentials"
}
```
**Action**: Re-authenticate (redirect to login)

**3. Weak Password**:
```json
{
  "detail": "Password must be at least 8 characters and contain uppercase, lowercase, number, and special character"
}
```
**Action**: Strengthen password according to requirements

**4. Account Locked**:
```json
{
  "detail": "Account is locked due to too many failed login attempts. Try again in 15 minutes."
}
```
**Action**: Wait 15 minutes before retrying

---

## Password Requirements

**Minimum Requirements**:
- ✓ At least 8 characters
- ✓ One uppercase letter (A-Z)
- ✓ One lowercase letter (a-z)
- ✓ One number (0-9)
- ✓ One special character (!@#$%^&*()_+-=[]{}|;':",./<>?)

**Example Valid Passwords**:
- `MySecure123!`
- `P@ssw0rd2025`
- `Tr0ub4dor&3`

**Example Invalid Passwords**:
- `password` (no uppercase, no number, no special)
- `PASSWORD123` (no lowercase, no special)
- `Pass123` (too short, no special)

---

## JWT Token Structure

### Access Token Payload

```json
{
  "sub": 1,                          // User ID
  "email": "user@example.com",
  "roles": ["user"],
  "type": "access",
  "exp": 1728045600,                 // Expiration (Unix timestamp)
  "iat": 1728043800                  // Issued at (Unix timestamp)
}
```

### Refresh Token Payload

```json
{
  "sub": 1,                          // User ID
  "type": "refresh",
  "exp": 1728648600,                 // Expiration (7 days)
  "iat": 1728043800                  // Issued at
}
```

**Token Lifetimes**:
- **Access Token**: 30 minutes (1800 seconds)
- **Refresh Token**: 7 days (604800 seconds)
- **Verification Token**: 24 hours
- **Reset Token**: 1 hour

---

## Security Headers

All API responses include security headers:

```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

---

## Next Steps

- **[Integration Guide](integration-guide.md)** - Learn how to integrate the authentication API into your application
- **[Security Guide](security-guide.md)** - Best practices for secure implementation
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Development Team
