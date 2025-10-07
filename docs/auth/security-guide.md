# Authentication Security Guide

**Version**: 1.0
**Last Updated**: 2025.10.04
**Target Audience**: DevOps, Security Engineers, Backend Developers

---

## Table of Contents

1. [Security Overview](#security-overview)
2. [Common Vulnerabilities & Prevention](#common-vulnerabilities--prevention)
3. [Production Hardening Checklist](#production-hardening-checklist)
4. [HTTPS & Transport Security](#https--transport-security)
5. [Token Security](#token-security)
6. [Database Security](#database-security)
7. [Monitoring & Incident Response](#monitoring--incident-response)
8. [Compliance Considerations](#compliance-considerations)

---

## Security Overview

The Lupin Authentication System implements defense-in-depth with multiple security layers:

| Security Feature | Implementation | Risk Mitigation |
|------------------|---------------|-----------------|
| Password Hashing | bcrypt (12 rounds) | Prevents password theft |
| JWT Signing | HS256 with secret key | Prevents token forgery |
| Token Rotation | Refresh token rotation | Limits token theft impact |
| Rate Limiting | 5 failed attempts, 15-min lockout | Prevents brute force |
| Audit Logging | All auth events logged | Enables incident response |
| Security Headers | X-Frame, XSS, HSTS | Prevents client-side attacks |
| Email Verification | Optional verification flow | Prevents fake accounts |
| Token Expiration | 30-min access, 7-day refresh | Limits stolen token lifespan |

**Security Principles Applied**:
- **Least Privilege**: Default user role has minimal permissions
- **Defense in Depth**: Multiple security layers
- **Fail Secure**: Errors default to denying access
- **Privacy by Design**: No email enumeration, secure error messages

---

## Common Vulnerabilities & Prevention

### 1. Cross-Site Scripting (XSS)

**Attack**: Malicious JavaScript injected into web pages to steal tokens.

**Prevention**:
```javascript
// ❌ VULNERABLE: localStorage accessible to XSS
localStorage.setItem( 'access_token', token );

// ✅ SECURE: Use httpOnly cookies (production)
// Backend sets cookie, JavaScript cannot access
response.set_cookie(
    key="access_token",
    value=access_token,
    httponly=True,  // Blocks JavaScript access
    secure=True,    // HTTPS only
    samesite="Strict"
)
```

**Current Status**: Development uses localStorage (XSS vulnerable), production should use httpOnly cookies.

**Mitigation**:
- [ ] Implement Content Security Policy (CSP)
- [ ] Sanitize all user inputs
- [ ] Use httpOnly cookies for production

---

### 2. Cross-Site Request Forgery (CSRF)

**Attack**: Attacker tricks authenticated user into making unwanted requests.

**Prevention**:
```python
# Backend: Verify SameSite cookie attribute
response.set_cookie(
    key="access_token",
    samesite="Strict",  // Prevents cross-site requests
    secure=True
)
```

```javascript
// Frontend: Include CSRF token in requests
headers: {
    'X-CSRF-Token': getCsrfToken()
}
```

**Current Status**: Not fully implemented for cookie-based auth.

**Mitigation**:
- [ ] Add CSRF token support for cookie authentication
- [ ] Use SameSite=Strict cookies
- [ ] Verify Referer header for state-changing operations

---

### 3. Token Theft

**Attack**: Attacker steals JWT tokens from network or storage.

**Prevention**:

**Transport Security**:
```bash
# HTTPS enforcement (all production traffic)
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

**Token Rotation**:
```javascript
// Both tokens rotate on refresh
POST /auth/refresh
{
  "refresh_token": "old_token"
}

Response:
{
  "tokens": {
    "access_token": "new_access_token",  // Changed
    "refresh_token": "new_refresh_token"  // Also changed!
  }
}
```

**Short Expiration**:
- Access tokens: 30 minutes
- Refresh tokens: 7 days

**Current Implementation**: ✅ Token rotation enabled, ✅ Short expiration.

**Mitigation**:
- [x] HTTPS only in production
- [x] Token rotation on refresh
- [x] Short token lifetimes
- [ ] Consider IP-based token validation

---

### 4. Brute Force Attacks

**Attack**: Automated password guessing attempts.

**Prevention**:
```python
# Rate limiting configuration
auth max failed attempts = 5
auth lockout duration minutes = 15
```

**Implementation**:
- Failed attempts tracked per email
- Account locked after 5 failures
- 15-minute lockout period
- Successful login clears failed attempts

**Current Implementation**: ✅ Rate limiting active.

**Enhanced Mitigations**:
- [ ] CAPTCHA after 3 failed attempts
- [ ] Progressive delay between attempts
- [ ] IP-based rate limiting
- [ ] Geo-blocking suspicious locations

---

### 5. SQL Injection

**Attack**: Malicious SQL code injected through user inputs.

**Prevention**:
```python
# ✅ SECURE: Parameterized queries (prevents SQL injection)
cursor.execute(
    "SELECT * FROM users WHERE email = ?",
    (email,)  // Parameter binding
)

# ❌ VULNERABLE: String concatenation
cursor.execute(
    f"SELECT * FROM users WHERE email = '{email}'"  // Don't do this!
)
```

**Current Implementation**: ✅ All queries use parameterized statements.

**Verification**:
```bash
# Search codebase for unsafe patterns
grep -r "f\"SELECT" src/cosa/rest/*.py
# Should return: No matches
```

---

### 6. Email Enumeration

**Attack**: Attacker determines which emails have accounts.

**Prevention**:
```python
# ✅ SECURE: Same response regardless of email existence
@router.post("/auth/request-password-reset")
async def request_password_reset(email: str):
    # Always return 200, even if email doesn't exist
    return {
        "message": "If an account exists with this email, a password reset link has been sent"
    }
```

**Current Implementation**: ✅ No email enumeration in password reset.

**Verification Points**:
- [ ] Registration returns same error for duplicate/invalid email
- [ ] Login returns "Invalid email or password" (not "Email not found")
- [ ] Password reset always returns 200 OK

---

### 7. Session Fixation

**Attack**: Attacker forces user to use known session ID.

**Prevention**:
```javascript
// Generate new session ID on login
sessionId = generateSessionId();  // Random generation
localStorage.setItem( 'session_id', sessionId );
```

**Current Implementation**: ✅ Client-generated session IDs using random words.

**Enhanced Mitigations**:
- [ ] Server-generated session IDs
- [ ] Invalidate old session on password change
- [ ] Bind session to IP address (optional)

---

## Production Hardening Checklist

### Environment Configuration

#### HTTPS & Transport Security
- [ ] **Enforce HTTPS** - Redirect all HTTP to HTTPS
  ```nginx
  server {
      listen 80;
      return 301 https://$server_name$request_uri;
  }
  ```

- [ ] **Configure SSL/TLS** - Use TLS 1.2+ only
  ```nginx
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_ciphers HIGH:!aNULL:!MD5;
  ```

- [ ] **Set HSTS Header** - Already implemented
  ```http
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  ```

#### Secrets Management
- [ ] **Rotate JWT Secret** - Use environment variable
  ```bash
  export JWT_SECRET_KEY=$(openssl rand -hex 32)
  ```

- [ ] **Secure Secret Storage** - Use secrets manager
  ```bash
  # AWS Secrets Manager, HashiCorp Vault, etc.
  aws secretsmanager get-secret-value --secret-id jwt-secret-key
  ```

- [ ] **Remove Default Secrets** - Change all default passwords/keys

#### Database Security
- [ ] **Database Encryption at Rest** - Enable SQLite encryption or use encrypted filesystem
  ```python
  # SQLCipher for SQLite encryption
  from pysqlcipher3 import dbapi2 as sqlite
  ```

- [ ] **Database Backups** - Encrypt backups
  ```bash
  # Encrypted backup
  tar -czf - auth.db | gpg --encrypt > auth.db.tar.gz.gpg
  ```

- [ ] **File Permissions** - Restrict database access
  ```bash
  chmod 600 auth.db  # Owner read/write only
  chown lupin:lupin auth.db
  ```

#### Rate Limiting
- [ ] **Enable Rate Limiting** - Already configured
  ```ini
  auth max failed attempts = 5
  auth lockout duration minutes = 15
  ```

- [ ] **IP-Based Rate Limiting** - Add nginx rate limiting
  ```nginx
  limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/m;

  location /auth/login {
      limit_req zone=auth burst=5;
  }
  ```

#### SMTP Security
- [ ] **Use TLS for Email** - Already configured
  ```ini
  smtp use tls = True
  ```

- [ ] **Secure SMTP Credentials** - Use environment variables
  ```bash
  export SMTP_USERNAME="your_smtp_user"
  export SMTP_PASSWORD="your_smtp_password"
  ```

- [ ] **Email Rate Limiting** - Prevent email bombing

### Application Security

#### Input Validation
- [ ] **Validate Email Format** - Already implemented (Pydantic EmailStr)
- [ ] **Enforce Password Strength** - Already implemented (8 chars, mixed case, number, special)
- [ ] **Sanitize User Inputs** - Prevent XSS in user-generated content

#### Output Encoding
- [ ] **Escape HTML in Responses** - Prevent reflected XSS
- [ ] **Content-Type Headers** - Set correct MIME types
  ```http
  Content-Type: application/json; charset=utf-8
  ```

#### Error Handling
- [ ] **Generic Error Messages** - Don't expose system details
  ```python
  # ❌ Don't expose
  "Database connection to postgresql://user:pass@host failed"

  # ✅ Generic message
  "Authentication failed. Please try again."
  ```

- [ ] **Log Detailed Errors Securely** - Log to secure location
  ```python
  logger.error(f"Auth error for user {user_id}: {detailed_error}")
  # User sees: "Authentication failed"
  ```

### Frontend Security

#### Token Storage
- [ ] **Use httpOnly Cookies (Production)** - Migrate from localStorage
  ```javascript
  // ❌ Development (XSS vulnerable)
  localStorage.setItem( 'access_token', token );

  // ✅ Production (XSS protected)
  // Server sets httpOnly cookie
  ```

#### Content Security Policy
- [ ] **Implement CSP Header**
  ```http
  Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'
  ```

#### Subresource Integrity
- [ ] **Use SRI for CDN Resources**
  ```html
  <script src="https://cdn.example.com/lib.js"
          integrity="sha384-hash"
          crossorigin="anonymous"></script>
  ```

---

## HTTPS & Transport Security

### SSL/TLS Configuration

**Nginx Configuration** (Production):
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Certificate
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # SSL Protocols
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';

    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    # Security Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # FastAPI Proxy
    location / {
        proxy_pass http://127.0.0.1:7999;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket Support
    location /ws/ {
        proxy_pass http://127.0.0.1:7999;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}

# HTTP to HTTPS Redirect
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

### Certificate Management

**Let's Encrypt (Free SSL)**:
```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal (cron)
0 12 * * * certbot renew --quiet
```

---

## Token Security

### JWT Secret Key Management

**Generate Strong Secret**:
```bash
# Generate 32-byte hex string
openssl rand -hex 32
# Output: a1b2c3d4e5f6...

# Set as environment variable
export JWT_SECRET_KEY="a1b2c3d4e5f6..."
```

**Configuration** (lupin-app.ini):
```ini
# Use environment variable
jwt secret key = ${JWT_SECRET_KEY}
```

**Rotation Strategy**:
1. Generate new secret key
2. Update configuration
3. Restart service
4. All existing tokens invalidated (users must re-login)

**Best Practices**:
- Rotate secrets quarterly
- Use different secrets for dev/staging/prod
- Never commit secrets to version control
- Use secrets manager (AWS Secrets Manager, Vault)

### Token Validation

**Server-Side Validation**:
```python
# verify_jwt_token checks:
# 1. Valid signature (prevents forgery)
# 2. Not expired (prevents replay)
# 3. Correct token type (access vs refresh)
# 4. User still exists
# 5. User is active
```

**Client-Side Handling**:
```javascript
// Never trust client-side token validation
// Always verify on server for security-critical operations
```

---

## Database Security

### Encryption

**SQLite Encryption** (Production):
```python
# Install SQLCipher
pip install pysqlcipher3

# Use encrypted database
import pysqlcipher3.dbapi2 as sqlite

conn = sqlite.connect( 'auth.db' )
conn.execute( f"PRAGMA key = '{encryption_key}'" )
```

### Backup Security

**Encrypted Backups**:
```bash
#!/bin/bash
# Backup script with encryption

BACKUP_DIR="/secure/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="auth_${TIMESTAMP}.db"

# Copy database
cp /path/to/auth.db "${BACKUP_DIR}/${BACKUP_FILE}"

# Encrypt
gpg --encrypt --recipient admin@yourcompany.com \
    "${BACKUP_DIR}/${BACKUP_FILE}"

# Remove unencrypted copy
rm "${BACKUP_DIR}/${BACKUP_FILE}"

# Keep only last 30 days
find "${BACKUP_DIR}" -name "auth_*.gpg" -mtime +30 -delete
```

### Access Control

**File Permissions**:
```bash
# Database file
chmod 600 /path/to/auth.db
chown lupin:lupin /path/to/auth.db

# Backup directory
chmod 700 /secure/backups
chown root:root /secure/backups
```

---

## Monitoring & Incident Response

### Audit Log Monitoring

**Key Events to Monitor**:
```sql
-- Failed login attempts
SELECT COUNT(*) FROM auth_audit_log
WHERE event_type = 'login_failure'
  AND created_at > datetime('now', '-1 hour')
GROUP BY ip_address
HAVING COUNT(*) > 10;

-- Password reset requests
SELECT * FROM auth_audit_log
WHERE event_type = 'password_reset_requested'
  AND created_at > datetime('now', '-1 day');

-- Unusual access patterns
SELECT user_id, COUNT(DISTINCT ip_address) as ip_count
FROM auth_audit_log
WHERE event_type = 'login_success'
  AND created_at > datetime('now', '-1 hour')
GROUP BY user_id
HAVING ip_count > 3;
```

### Alerting Rules

**Configure Alerts** (example with AWS CloudWatch):
```yaml
# Multiple failed logins
Alert: HighFailedLoginRate
Condition: failed_logins > 50 per 5 minutes
Action: SNS notification to security team

# Unusual password resets
Alert: PasswordResetSpike
Condition: password_resets > 100 per hour
Action: Email + Slack notification

# Multiple IPs per user
Alert: SuspiciousIPPattern
Condition: distinct_ips_per_user > 5 per hour
Action: Investigate and potentially lock account
```

### Incident Response

**Suspected Token Theft**:
1. Identify affected user(s)
2. Revoke all refresh tokens for user
3. Force password reset
4. Review audit logs for unauthorized access
5. Notify user of security incident

```python
# Revoke all user tokens
from cosa.rest.refresh_token_service import revoke_all_user_tokens

revoke_all_user_tokens( user_id=123 )
```

**Suspected Breach**:
1. Rotate JWT secret key (invalidates all tokens)
2. Force password reset for all users
3. Review database for unauthorized changes
4. Audit access logs
5. Notify affected users

---

## Compliance Considerations

### GDPR (EU)

**Right to Erasure**:
```python
# Delete user data endpoint
@router.delete("/auth/users/{user_id}")
async def delete_user_data( user_id: int ):
    # Delete user record
    # Delete associated tokens
    # Delete audit logs (or anonymize)
    # Delete from all related tables
    pass
```

**Data Minimization**:
- Only collect necessary data (email, password hash)
- Don't store plaintext passwords
- Anonymize audit logs after 90 days

### CCPA (California)

**Data Access Request**:
```python
# Export user data
@router.get("/auth/users/{user_id}/export")
async def export_user_data( user_id: int ):
    # Return all user data in machine-readable format
    return {
        "user": get_user_by_id( user_id ),
        "auth_logs": get_user_audit_logs( user_id ),
        "tokens": get_user_tokens( user_id )
    }
```

### HIPAA (Healthcare)

**Encryption Requirements**:
- [ ] Encrypt data at rest (database encryption)
- [ ] Encrypt data in transit (HTTPS)
- [ ] Encrypt backups
- [ ] Access logging (audit trail)
- [ ] Access controls (RBAC)

---

## Security Checklist Summary

**Critical (Before Production)**:
- [ ] HTTPS enforced (all traffic)
- [ ] JWT secret rotated from default
- [ ] Database backups encrypted
- [ ] httpOnly cookies for tokens
- [ ] Rate limiting enabled
- [ ] Audit logging active
- [ ] Security headers configured

**Important (Within 30 Days)**:
- [ ] CSRF protection implemented
- [ ] CAPTCHA on registration/login
- [ ] Monitoring and alerting configured
- [ ] Incident response plan documented
- [ ] Penetration testing completed

**Recommended (Within 90 Days)**:
- [ ] Database encryption at rest
- [ ] IP-based rate limiting
- [ ] Geo-blocking for suspicious regions
- [ ] Automated security scanning
- [ ] Security audit by third party

---

## Next Steps

- **[Operations Guide](operations-guide.md)** - Deployment and maintenance procedures
- **[Troubleshooting](troubleshooting.md)** - Common security issues and solutions
- **[API Reference](api-reference.md)** - Secure API usage patterns

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Security Team
