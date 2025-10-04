# Authentication Troubleshooting Guide

**Version**: 1.0
**Last Updated**: 2025.10.04
**Target Audience**: Developers, DevOps Engineers

---

## Table of Contents

1. [Common Issues](#common-issues)
2. [Debug Procedures](#debug-procedures)
3. [Error Messages Reference](#error-messages-reference)
4. [WebSocket Issues](#websocket-issues)
5. [Database Issues](#database-issues)
6. [Email Issues](#email-issues)
7. [FAQ](#faq)

---

## Common Issues

### Issue 1: "Could not validate credentials" (401)

**Symptoms**:
```json
{
  "detail": "Could not validate credentials"
}
```

**Possible Causes**:

**A. Token Expired**
```javascript
// Check token expiration
const token = localStorage.getItem('access_token');
const payload = JSON.parse(atob(token.split('.')[1]));
const now = Date.now() / 1000;
console.log('Expired:', payload.exp < now);
```

**Solution**: Refresh token
```javascript
await authService.refreshAccessToken();
```

**B. Invalid JWT Signature**
- JWT secret key mismatch between client/server
- Token manually modified

**Debug**:
```bash
# Check server JWT secret
grep "jwt secret key" /etc/lupin/lupin-app.ini

# Verify environment variable
echo $JWT_SECRET_KEY
```

**Solution**: Ensure JWT secret matches across deployments

**C. Wrong Token Type**
- Using refresh token for access endpoint
- Using access token for refresh endpoint

**Debug**:
```python
# Decode token manually
import jwt
token = "your_token_here"
payload = jwt.decode(token, options={"verify_signature": False})
print(payload.get("type"))  # Should be "access" or "refresh"
```

**Solution**: Use correct token type

---

### Issue 2: "Account is locked" (429)

**Symptoms**:
```json
{
  "detail": "Account is locked due to too many failed login attempts. Try again in 15 minutes."
}
```

**Cause**: 5+ failed login attempts within 15 minutes

**Immediate Fix** (Admin Only):
```sql
-- Clear failed attempts for user
DELETE FROM failed_login_attempts
WHERE email = 'user@example.com';
```

**Prevention**:
- Implement CAPTCHA after 3 attempts
- Use password managers
- Enable MFA (future)

**Debug Failed Attempts**:
```sql
-- Check failed attempts
SELECT email, COUNT(*) as attempts, MAX(attempted_at) as last_attempt
FROM failed_login_attempts
WHERE attempted_at > datetime('now', '-15 minutes')
GROUP BY email
ORDER BY attempts DESC;
```

---

### Issue 3: "Invalid email or password" (401)

**Symptoms**:
```json
{
  "detail": "Invalid email or password"
}
```

**Common Mistakes**:

**A. Wrong Password**
- User forgot password → Use password reset

**B. Email Case Sensitivity**
```python
# Email should be case-insensitive
# Check database
SELECT email FROM users WHERE LOWER(email) = LOWER('User@Example.com');
```

**C. Whitespace in Email/Password**
```javascript
// Trim inputs
const email = document.getElementById('email').value.trim();
const password = document.getElementById('password').value;  // Don't trim password!
```

**D. Password Not Set**
- User registered but no password set (migrated from mock)

**Fix**:
```sql
-- Check if user has password hash
SELECT email, password_hash IS NOT NULL as has_password
FROM users
WHERE email = 'user@example.com';

-- If NULL, user needs password reset
```

---

### Issue 4: "Password must be at least 8 characters..." (400)

**Symptoms**:
```json
{
  "detail": "Password must be at least 8 characters and contain uppercase, lowercase, number, and special character"
}
```

**Password Requirements**:
- ✓ Minimum 8 characters
- ✓ One uppercase letter (A-Z)
- ✓ One lowercase letter (a-z)
- ✓ One digit (0-9)
- ✓ One special character (!@#$%^&*()_+-=[]{}|;':",./<>?)

**Valid Examples**:
- `MyPass123!`
- `Secure2025#`
- `Welcome@2025`

**Invalid Examples**:
- `password` (no uppercase, digit, special)
- `PASSWORD123` (no lowercase, special)
- `Pass123` (too short, no special)

**Debug Password Validation**:
```python
from cosa.rest.password_service import validate_password_strength

valid, message = validate_password_strength("MyPass123!")
print(f"Valid: {valid}, Message: {message}")
```

---

### Issue 5: Token Refresh Fails (401)

**Symptoms**:
```json
{
  "detail": "Invalid or expired refresh token"
}
```

**Possible Causes**:

**A. Refresh Token Expired** (7 days)
```sql
-- Check token expiration
SELECT token_hash, expires_at,
       datetime(expires_at) < datetime('now') as expired
FROM refresh_tokens
WHERE user_id = 1;
```

**Solution**: User must re-login

**B. Token Already Used** (rotation)
- Refresh tokens are single-use
- After refresh, old token is revoked

**Solution**: Use the new refresh token returned from `/auth/refresh`

**C. Token Revoked** (logout)
```sql
-- Check if token exists
SELECT COUNT(*) FROM refresh_tokens
WHERE token_hash = '[SHA256_of_token]';
```

**Solution**: User must re-login

---

## Debug Procedures

### Enable Debug Logging

**1. Application Debug Mode**
```ini
# lupin-app.ini
app_debug = True
app_verbose = True
```

**2. Check Logs**
```bash
# Real-time logs
sudo journalctl -u lupin-fastapi -f

# Last 100 lines
sudo journalctl -u lupin-fastapi -n 100 --no-pager

# Filter by keyword
sudo journalctl -u lupin-fastapi | grep "AUTH"
```

### Trace Authentication Flow

**Add Debug Logging** (temporary):
```python
# cosa/rest/auth.py - Add logging
async def verify_jwt_token(token: str) -> Dict:
    print(f"[DEBUG] Verifying token: {token[:20]}...")

    try:
        payload = decode_and_validate_token(token, expected_type="access")
        print(f"[DEBUG] Token payload: {payload}")

        user_data = get_user_by_id(payload.get("sub"))
        print(f"[DEBUG] User data: {user_data}")

        return user_data

    except Exception as e:
        print(f"[DEBUG] Verification failed: {e}")
        raise
```

### Test Individual Components

**1. Test Password Hashing**
```python
from cosa.rest.password_service import hash_password, verify_password

password = "Test123!"
hashed = hash_password(password)
print(f"Hash: {hashed}")

valid = verify_password(password, hashed)
print(f"Verification: {valid}")  # Should be True
```

**2. Test JWT Generation**
```python
from cosa.rest.jwt_service import generate_access_token, decode_and_validate_token

token = generate_access_token(1, "test@example.com", ["user"])
print(f"Token: {token}")

payload = decode_and_validate_token(token, expected_type="access")
print(f"Payload: {payload}")
```

**3. Test Database Connection**
```python
from cosa.rest.auth_database import get_auth_db_connection

conn = get_auth_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM users")
count = cursor.fetchone()[0]
print(f"Total users: {count}")
conn.close()
```

---

## Error Messages Reference

### HTTP 400 - Bad Request

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Invalid email format" | Email doesn't match pattern | Use valid email (user@domain.com) |
| "Password too weak" | Password requirements not met | Meet all password requirements |
| "Passwords do not match" | Password confirmation mismatch | Ensure passwords match exactly |
| "Email already exists" | Duplicate registration | Use different email or login |
| "Invalid or expired token" | Verification/reset token invalid | Request new token |

### HTTP 401 - Unauthorized

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Could not validate credentials" | Invalid/expired token | Refresh token or re-login |
| "Invalid email or password" | Wrong credentials | Check email/password |
| "Token has expired" | Access token expired (30 min) | Refresh token |
| "Current password is incorrect" | Wrong old password for change | Verify current password |
| "Missing authentication" | No Authorization header | Add Bearer token |

### HTTP 403 - Forbidden

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Insufficient permissions" | User lacks required role | Contact admin for permissions |
| "Admin access required" | Non-admin accessing admin endpoint | Login with admin account |

### HTTP 429 - Too Many Requests

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Account is locked..." | 5+ failed login attempts | Wait 15 minutes or contact admin |
| "Too many requests" | Rate limit exceeded | Slow down requests |

### HTTP 500 - Internal Server Error

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Database error" | Database connection failed | Check database permissions |
| "SMTP error" | Email sending failed | Verify SMTP configuration |
| "Token generation failed" | JWT secret not configured | Set JWT_SECRET_KEY env variable |

---

## WebSocket Issues

### Issue: WebSocket Connection Refused (HTTP 403)

**Symptoms**:
```
websockets.exceptions.InvalidStatus: server rejected WebSocket connection: HTTP 403
```

**Causes**:

**A. Invalid Session ID Format**
- Session ID must be "adjective noun" format (with space, not underscore)
- Examples: `wise penguin`, `clever dolphin`

**Fix**:
```javascript
// Valid session ID
const sessionId = "wise penguin";  // ✓

// Invalid session IDs
const sessionId = "session123";     // ✗ Wrong format
const sessionId = "wise penguin";   // ✗ Space instead of underscore
```

**B. Authentication Token Invalid**
```javascript
// After connection, send auth_request
const authMessage = {
    type: "auth_request",
    token: accessToken,  // Must be valid JWT
    session_id: sessionId,
    subscribed_events: ["*"]
};

await websocket.send(JSON.stringify(authMessage));
```

**C. Wrong Auth Mode**
- Server expects JWT, client sends mock token

**Debug**:
```ini
# Check server configuration
grep "auth mode" /etc/lupin/lupin-app.ini
```

### Issue: "auth_error" Response

**Symptoms**:
```json
{
  "type": "auth_error",
  "message": "Token validation failed: ..."
}
```

**Debug Steps**:

1. **Check Token Type**
```javascript
const payload = JSON.parse(atob(token.split('.')[1]));
console.log('Token type:', payload.type);  // Should be "access"
```

2. **Check Token Expiration**
```javascript
const payload = JSON.parse(atob(token.split('.')[1]));
const expired = payload.exp < (Date.now() / 1000);
console.log('Token expired:', expired);
```

3. **Refresh Token if Needed**
```javascript
if (expired) {
    await authService.refreshAccessToken();
    // Reconnect WebSocket with new token
}
```

---

## Database Issues

### Issue: Database Locked

**Symptoms**:
```
sqlite3.OperationalError: database is locked
```

**Causes**:
- Multiple write operations simultaneously
- Long-running transactions
- WAL mode not enabled

**Solutions**:

**A. Enable WAL Mode**
```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;  -- 5 seconds
```

**B. Check Long Transactions**
```bash
# Check processes accessing database
lsof /var/lib/lupin/auth.db
```

**C. Restart Service**
```bash
sudo systemctl restart lupin-fastapi
```

### Issue: Database Corruption

**Symptoms**:
```
sqlite3.DatabaseError: database disk image is malformed
```

**Diagnosis**:
```bash
sqlite3 /var/lib/lupin/auth.db "PRAGMA integrity_check;"
# Expected: ok
# If error: database is corrupted
```

**Recovery**:
```bash
# 1. Stop service
sudo systemctl stop lupin-fastapi

# 2. Restore from backup
cp /var/backups/lupin/auth_latest.db.gz .
gunzip auth_latest.db.gz
cp auth_latest.db /var/lib/lupin/auth.db

# 3. Verify integrity
sqlite3 /var/lib/lupin/auth.db "PRAGMA integrity_check;"

# 4. Start service
sudo systemctl start lupin-fastapi
```

---

## Email Issues

### Issue: Email Not Sending

**Symptoms**:
- No verification/reset emails received
- SMTP errors in logs

**Debug Steps**:

**1. Check SMTP Configuration**
```ini
# lupin-app.ini
smtp host = smtp.gmail.com
smtp port = 587
smtp use tls = True
send email enabled = True  # Must be True!
```

**2. Test SMTP Connection**
```python
import smtplib
smtp = smtplib.SMTP('smtp.gmail.com', 587)
smtp.starttls()
smtp.login('your_username', 'your_password')
print('SMTP connection successful!')
smtp.quit()
```

**3. Check Gmail Settings** (if using Gmail):
- Enable "Less secure app access" OR
- Use App-Specific Password

**4. Check Firewall**
```bash
# Test port 587 connectivity
telnet smtp.gmail.com 587
# Should connect successfully
```

### Issue: Emails Go to Spam

**Solutions**:
- Add SPF record to DNS
- Configure DKIM signing
- Use reputable SMTP service
- Add unsubscribe link

---

## FAQ

### Q1: How do I reset a user's password (admin)?

**A:** Generate password reset token and send to user manually:

```python
from cosa.rest.email_token_service import generate_password_reset_token
from cosa.rest.user_service import get_user_by_email

# Get user
user = get_user_by_email("user@example.com")

# Generate reset token
success, message, token = generate_password_reset_token(user["id"])

# Send token to user (secure channel)
print(f"Reset URL: https://your-domain.com/reset-password?token={token}")
```

### Q2: How do I make a user an admin?

**A:**
```sql
-- Update user roles
UPDATE users
SET roles = '["admin", "user"]'
WHERE email = 'user@example.com';
```

### Q3: Can I increase token expiration time?

**A:** Yes, configure in `lupin-app.ini`:
```ini
jwt access token expiration seconds = 3600  # 1 hour instead of 30 min
jwt refresh token expiration days = 30  # 30 days instead of 7
```

**Note**: Longer expiration = higher security risk if token stolen

### Q4: How do I bulk delete old audit logs?

**A:**
```sql
-- Delete logs older than 90 days
DELETE FROM auth_audit_log
WHERE created_at < datetime('now', '-90 days');

-- Reclaim space
VACUUM;
```

### Q5: Token refresh fails immediately after login?

**A:** This usually means:
1. Refresh token not stored properly
2. Token hash mismatch

**Debug**:
```sql
-- Check if refresh token exists
SELECT COUNT(*) FROM refresh_tokens WHERE user_id = 1;
-- Should be > 0 after login
```

### Q6: WebSocket disconnects after 30 seconds?

**A:** This is nginx proxy timeout. Update nginx config:
```nginx
location /ws/ {
    proxy_pass http://localhost:7999;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;  # 1 hour timeout
    proxy_send_timeout 3600s;
}
```

### Q7: How do I revoke all tokens for a user?

**A:**
```python
from cosa.rest.refresh_token_service import revoke_all_user_tokens

# Revoke all refresh tokens
count = revoke_all_user_tokens(user_id=123)
print(f"Revoked {count} tokens")

# User must re-login
```

### Q8: Can I use JWT tokens from other services?

**A:** Only if they share the same JWT secret key. Not recommended for security.

Better: Implement OAuth2/OIDC integration (future feature).

### Q9: Rate limiting too strict for my users?

**A:** Adjust configuration:
```ini
# More lenient rate limiting
auth max failed attempts = 10  # Default: 5
auth lockout duration minutes = 5  # Default: 15
```

### Q10: How do I export all user data (GDPR)?

**A:**
```python
from cosa.rest.user_service import get_user_by_email

user = get_user_by_email("user@example.com")

# Export all user data
import json
export_data = {
    "user": user,
    "audit_logs": get_audit_logs_for_user(user["id"]),
    "tokens": get_tokens_for_user(user["id"])
}

with open(f"user_export_{user['id']}.json", "w") as f:
    json.dump(export_data, f, indent=2)
```

---

## Quick Diagnostic Commands

**Check System Health**:
```bash
# Service status
sudo systemctl status lupin-fastapi

# Recent errors
sudo journalctl -u lupin-fastapi -p err -n 20

# Database size
du -h /var/lib/lupin/auth.db

# User count
sqlite3 /var/lib/lupin/auth.db "SELECT COUNT(*) FROM users;"

# Failed login attempts
sqlite3 /var/lib/lupin/auth.db "SELECT COUNT(*) FROM failed_login_attempts WHERE attempted_at > datetime('now', '-1 hour');"
```

**Test Authentication Endpoints**:
```bash
# Health check
curl http://localhost:7999/api/health

# Register
curl -X POST http://localhost:7999/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"Test123!"}'

# Login
curl -X POST http://localhost:7999/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"Test123!"}'
```

---

## Getting Help

**1. Check Logs First**:
```bash
sudo journalctl -u lupin-fastapi -n 200 --no-pager
```

**2. Review Documentation**:
- [API Reference](api-reference.md)
- [Integration Guide](integration-guide.md)
- [Security Guide](security-guide.md)
- [Operations Guide](operations-guide.md)

**3. Search GitHub Issues**:
```
https://github.com/yourproject/lupin/issues?q=is%3Aissue+auth
```

**4. Enable Debug Mode**:
```ini
app_debug = True
app_verbose = True
```

**5. Create Issue Report**:
Include:
- Error message (full stack trace)
- Steps to reproduce
- Configuration (redact secrets!)
- Log excerpts
- System information (OS, Python version)

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Support Team
