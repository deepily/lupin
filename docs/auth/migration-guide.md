# Mock to JWT Migration Guide

**Version**: 1.0
**Last Updated**: 2025.10.04
**Target Audience**: DevOps Engineers, Team Leads

---

## Table of Contents

1. [Migration Overview](#migration-overview)
2. [Pre-Migration Checklist](#pre-migration-checklist)
3. [Migration Procedures](#migration-procedures)
4. [User Data Migration](#user-data-migration)
5. [Testing Migration](#testing-migration)
6. [Rollback Procedures](#rollback-procedures)
7. [Post-Migration Validation](#post-migration-validation)

---

## Migration Overview

### What Changes

**From Mock Authentication** (Development):
```python
# Mock tokens: mock_token_email_ricardo@example.com
# No real security, any format accepted
# No password storage
# User data dynamically generated
```

**To JWT Authentication** (Production):
```python
# JWT tokens: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
# Cryptographic signature validation
# bcrypt password hashing
# Database-backed user storage
# Token expiration and rotation
```

### Migration Strategy

**Zero-Downtime Migration** (Recommended):
1. Deploy JWT system alongside mock system
2. Configure dual authentication mode (mock + JWT)
3. Gradually migrate users
4. Switch to JWT-only mode
5. Deprecate mock authentication

**Hard Cutover** (Faster, requires downtime):
1. Schedule maintenance window
2. Deploy JWT system
3. Migrate all users
4. Force re-login for all users
5. Switch to JWT-only mode

---

## Pre-Migration Checklist

### Environment Preparation

- [ ] **Backup Current System**
  ```bash
  # Backup current database
  cp /var/lib/lupin/app.db /var/lib/lupin/app.db.backup.$(date +%Y%m%d)

  # Backup configuration
  cp /etc/lupin/env /etc/lupin/env.backup
  ```

- [ ] **Generate JWT Secret Key**
  ```bash
  # Generate 32-byte hex key
  openssl rand -hex 32 > /etc/lupin/jwt_secret.key
  chmod 600 /etc/lupin/jwt_secret.key
  export JWT_SECRET_KEY=$(cat /etc/lupin/jwt_secret.key)
  ```

- [ ] **Configure SMTP for Email**
  ```bash
  export SMTP_USERNAME="your-smtp-username"
  export SMTP_PASSWORD="your-smtp-password"
  export SMTP_FROM_EMAIL="noreply@your-domain.com"
  export APP_BASE_URL="https://your-domain.com"
  ```

- [ ] **Initialize Auth Database**
  ```bash
  # Run server once to create auth.db
  python -m fastapi_app.main
  # Verify auth.db created
  ls -lh /var/lib/lupin/auth.db
  ```

- [ ] **Test SMTP Connection**
  ```python
  python -c "
  import smtplib
  from email.mime.text import MIMEText

  smtp = smtplib.SMTP('smtp.gmail.com', 587)
  smtp.starttls()
  smtp.login('${SMTP_USERNAME}', '${SMTP_PASSWORD}')
  print('SMTP connection successful')
  smtp.quit()
  "
  ```

- [ ] **Review Configuration Changes**
  ```ini
  # Before (mock mode)
  auth mode = mock

  # After (JWT mode)
  auth mode = jwt
  jwt secret key = ${JWT_SECRET_KEY}
  send email enabled = True
  ```

---

## Migration Procedures

### Option 1: Zero-Downtime Migration

**Phase 1: Deploy JWT System (Dual Mode)**

```ini
# lupin-app.ini - Enable dual authentication
auth mode = dual  # Accepts both mock and JWT tokens
```

```python
# auth.py - Dual mode verification
async def verify_token(token: str) -> Dict:
    if auth_mode == "dual":
        # Try JWT first
        try:
            return await verify_jwt_token(token)
        except:
            # Fallback to mock
            return await verify_mock_token(token)
```

**Phase 2: Create User Migration Script**

```python
#!/usr/bin/env python
# migrate_mock_users.py

from cosa.rest.user_service import register_user
from cosa.rest.password_service import hash_password

# List of mock users to migrate
MOCK_USERS = [
    {"email": "ricardo@example.com", "password": "Temp123!", "roles": ["admin", "user"]},
    {"email": "alice@example.com", "password": "Temp123!", "roles": ["user"]},
    {"email": "bob@example.com", "password": "Temp123!", "roles": ["user"]},
]

print("Migrating mock users to JWT authentication...")

for user_data in MOCK_USERS:
    email = user_data["email"]
    password = user_data["password"]  # Temporary password

    # Register user
    success, message, user = register_user(email, password)

    if success:
        print(f"✓ Migrated: {email}")

        # If admin role needed, update database directly
        if "admin" in user_data["roles"]:
            from cosa.rest.auth_database import get_auth_db_connection
            conn = get_auth_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET roles = ? WHERE email = ?",
                ('["admin", "user"]', email)
            )
            conn.commit()
            conn.close()
            print(f"  → Admin role granted to {email}")

    else:
        print(f"✗ Failed: {email} - {message}")

print("\\nMigration complete!")
print("\\n⚠️  IMPORTANT: Notify users to change their temporary passwords!")
```

**Run Migration**:
```bash
cd /opt/lupin
python scripts/migrate_mock_users.py
```

**Phase 3: Notify Users**

**Email Template**:
```
Subject: Action Required: Update Your Lupin Password

Hi [User],

We've upgraded our authentication system for enhanced security.

Your temporary password: Temp123!

Please login at https://your-domain.com/login and change your password immediately at https://your-domain.com/change-password

Thank you,
The Lupin Team
```

**Phase 4: Monitor Adoption**

```sql
-- Check user migration status
SELECT
    COUNT(*) as total_users,
    SUM(CASE WHEN last_login_at IS NOT NULL THEN 1 ELSE 0 END) as logged_in_users,
    SUM(CASE WHEN last_login_at IS NULL THEN 1 ELSE 0 END) as pending_users
FROM users;

-- Recent logins
SELECT email, last_login_at
FROM users
WHERE last_login_at > datetime('now', '-24 hours')
ORDER BY last_login_at DESC;
```

**Phase 5: Switch to JWT-Only Mode**

```ini
# After 100% adoption (or deadline reached)
auth mode = jwt  # Disable mock authentication
```

**Restart Service**:
```bash
sudo systemctl restart lupin-fastapi
```

---

### Option 2: Hard Cutover (Maintenance Window)

**Preparation** (1 week before):
- [ ] Announce maintenance window
- [ ] Send password reset instructions
- [ ] Prepare rollback plan

**Execution** (Maintenance Day):

**1. Stop Services** (Start of window)
```bash
sudo systemctl stop lupin-fastapi
sudo systemctl stop nginx  # Prevent user access
```

**2. Backup Everything**
```bash
/opt/lupin/scripts/backup_all.sh
```

**3. Migrate Configuration**
```bash
# Update configuration
sed -i 's/auth mode = mock/auth mode = jwt/' /etc/lupin/lupin-app.ini

# Set JWT secret
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)" >> /etc/lupin/env
```

**4. Run User Migration**
```bash
python /opt/lupin/scripts/migrate_mock_users.py
```

**5. Start Services**
```bash
sudo systemctl start lupin-fastapi
sudo systemctl start nginx
```

**6. Verify**
```bash
# Health check
curl https://your-domain.com/api/health

# Test login
curl -X POST https://your-domain.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"ricardo@example.com","password":"Temp123!"}'
```

**7. Monitor Logs**
```bash
sudo journalctl -u lupin-fastapi -f
```

---

## User Data Migration

### Migration Script Details

**Complete Migration Script** (`scripts/migrate_mock_users.py`):
```python
#!/usr/bin/env python
"""
Mock User Migration Script

Migrates users from mock authentication to JWT authentication.

Usage:
    python scripts/migrate_mock_users.py [--dry-run] [--generate-passwords]

Options:
    --dry-run: Show what would be migrated without making changes
    --generate-passwords: Generate random passwords instead of Temp123!
"""

import sys
import os
import secrets
import string

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT not set. Export it to your project root:\n"
        "  export LUPIN_ROOT=/path/to/your/project"
    )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable - use canonical patterns
import cosa.utils.util as du
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.user_service import register_user, get_user_by_email
from cosa.rest.auth_database import get_auth_db_connection

# For any other paths, use du.get_project_root()
project_root = du.get_project_root()

# Mock users to migrate
MOCK_USERS = [
    {
        "email": "ricardo@example.com",
        "roles": ["admin", "user"],
        "name": "Ricardo Ruiz"
    },
    {
        "email": "alice@example.com",
        "roles": ["user"],
        "name": "Alice Smith"
    },
    {
        "email": "bob@example.com",
        "roles": ["user"],
        "name": "Bob Johnson"
    },
]

def generate_password(length=12):
    """Generate secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        # Ensure password meets requirements
        if (any(c.islower() for c in password) and
            any(c.isupper() for c in password) and
            any(c.isdigit() for c in password) and
            any(c in "!@#$%^&*" for c in password)):
            return password

def migrate_user(user_data, use_random_password=False, dry_run=False):
    """Migrate a single mock user to JWT auth."""
    email = user_data["email"]
    roles = user_data["roles"]
    name = user_data.get("name", email.split("@")[0])

    # Check if user already exists
    existing = get_user_by_email(email)
    if existing:
        print(f"⚠️  User already exists: {email}")
        return None

    # Generate password
    if use_random_password:
        password = generate_password()
    else:
        password = "Temp123!"  # Default temporary password

    if dry_run:
        print(f"[DRY RUN] Would migrate: {email} with roles {roles}")
        return {"email": email, "password": password}

    # Register user
    success, message, user = register_user(email, password)

    if not success:
        print(f"✗ Failed to migrate {email}: {message}")
        return None

    print(f"✓ Created user: {email}")

    # Update roles if needed (admin role)
    if "admin" in roles:
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET roles = ? WHERE email = ?",
            (str(roles).replace("'", '"'), email)  # Convert to JSON
        )
        conn.commit()
        conn.close()
        print(f"  → Granted admin role to {email}")

    return {"email": email, "password": password}

def main():
    """Run migration."""
    import argparse

    parser = argparse.ArgumentParser(description="Migrate mock users to JWT")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated")
    parser.add_argument("--generate-passwords", action="store_true", help="Generate random passwords")
    args = parser.parse_args()

    print("="*60)
    print("Mock User to JWT Migration")
    print("="*60)

    if args.dry_run:
        print("\\n🔍 DRY RUN MODE - No changes will be made\\n")

    # Migrate users
    results = []
    for user_data in MOCK_USERS:
        result = migrate_user(user_data, args.generate_passwords, args.dry_run)
        if result:
            results.append(result)

    print("\\n" + "="*60)
    print(f"Migration Summary: {len(results)}/{len(MOCK_USERS)} users")
    print("="*60)

    if results and not args.dry_run:
        print("\\n📧 User Credentials (send to users securely):\\n")
        for user in results:
            print(f"  Email: {user['email']}")
            print(f"  Temporary Password: {user['password']}")
            print()

        print("\\n⚠️  IMPORTANT:")
        print("  1. Send credentials to users via secure channel")
        print("  2. Instruct users to change password immediately")
        print("  3. Consider enabling email verification")
        print("  4. Monitor failed login attempts")

if __name__ == "__main__":
    main()
```

**Usage**:
```bash
# Dry run (see what would happen)
python scripts/migrate_mock_users.py --dry-run

# Migrate with default password (Temp123!)
python scripts/migrate_mock_users.py

# Migrate with random passwords
python scripts/migrate_mock_users.py --generate-passwords
```

---

## Testing Migration

### Pre-Migration Testing

**1. Test JWT System in Isolation**
```bash
# Start server in JWT mode on different port
LUPIN_CONFIG_MGR_CLI_ARGS="--block-name=Lupin: Testing" \
    uvicorn fastapi_app.main:app --port 8000

# Test registration
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test123!"}'

# Test login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test123!"}'
```

**2. Run Integration Tests**
```bash
python -m pytest src/tests/integration/ -v
# Expected: 8/8 tests passing
```

**3. Test WebSocket Authentication**
```bash
# Start WebSocket client
wscat -c ws://localhost:8000/ws/queue/test_session

# Send auth request with JWT
{"type":"auth_request","token":"eyJ...",  "session_id":"test_session","subscribed_events":["*"]}

# Expected: {"type":"auth_success",...}
```

### Post-Migration Testing

**Smoke Test Checklist**:
- [ ] Register new user
- [ ] Login with migrated user
- [ ] Access protected endpoint
- [ ] Change password
- [ ] Request password reset
- [ ] WebSocket connection with JWT
- [ ] Admin user has admin role
- [ ] Rate limiting works

**Automated Smoke Test**:
```bash
#!/bin/bash
# smoke_test_jwt.sh

BASE_URL="https://your-domain.com"

# Test 1: Register
echo "Test 1: Register new user"
curl -X POST ${BASE_URL}/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"smoketest@example.com","password":"Smoke123!"}' \
  | jq .

# Test 2: Login
echo "\\nTest 2: Login"
TOKEN=$(curl -s -X POST ${BASE_URL}/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"smoketest@example.com","password":"Smoke123!"}' \
  | jq -r .tokens.access_token)

echo "Token: ${TOKEN:0:20}..."

# Test 3: Protected endpoint
echo "\\nTest 3: Access protected endpoint"
curl -H "Authorization: Bearer ${TOKEN}" \
  ${BASE_URL}/auth/me \
  | jq .

echo "\\n✅ Smoke test complete"
```

---

## Rollback Procedures

### When to Rollback

**Critical Issues**:
- Unable to login (all users locked out)
- Database corruption
- Token generation failures
- Email service failures (password resets impossible)

### Rollback Steps

**1. Stop Services**
```bash
sudo systemctl stop lupin-fastapi
```

**2. Restore Configuration**
```bash
# Restore mock mode
cp /etc/lupin/env.backup /etc/lupin/env
cp /etc/lupin/lupin-app.ini.backup /etc/lupin/lupin-app.ini
```

**3. Restore Database (if needed)**
```bash
# Restore app.db
cp /var/lib/lupin/app.db.backup.YYYYMMDD /var/lib/lupin/app.db

# Remove auth.db if corrupted
rm /var/lib/lupin/auth.db
```

**4. Restart Services**
```bash
sudo systemctl start lupin-fastapi
```

**5. Verify Rollback**
```bash
# Test mock authentication
curl -H "Authorization: Bearer mock_token_ricardo" \
  http://localhost:7999/api/auth-test
```

**6. Communicate with Users**
```
Subject: Maintenance Update

We've temporarily reverted to the previous authentication system
due to technical issues. Your mock tokens will continue to work.

We'll schedule a new migration window soon.

Thank you for your patience.
```

---

## Post-Migration Validation

### Validation Checklist

**Day 1**:
- [ ] Monitor error logs for auth failures
- [ ] Check failed login rate (should be normal)
- [ ] Verify email sending works
- [ ] Check database growth (audit logs)
- [ ] Monitor token refresh rate

**Week 1**:
- [ ] Review audit logs for suspicious activity
- [ ] Check user adoption rate (logins per day)
- [ ] Monitor password reset requests
- [ ] Verify backup procedures working
- [ ] Check performance metrics

**Month 1**:
- [ ] Security audit
- [ ] Review rate limiting effectiveness
- [ ] Analyze failed login patterns
- [ ] User feedback collection
- [ ] Plan for next security enhancements

### Metrics to Monitor

```sql
-- Daily active users
SELECT DATE(last_login_at) as date, COUNT(*) as users
FROM users
WHERE last_login_at > datetime('now', '-30 days')
GROUP BY DATE(last_login_at)
ORDER BY date DESC;

-- Authentication success rate
SELECT
    DATE(created_at) as date,
    COUNT(CASE WHEN event_type = 'login_success' THEN 1 END) as successes,
    COUNT(CASE WHEN event_type = 'login_failure' THEN 1 END) as failures,
    ROUND(100.0 * COUNT(CASE WHEN event_type = 'login_success' THEN 1 END) /
          COUNT(*), 2) as success_rate
FROM auth_audit_log
WHERE event_type IN ('login_success', 'login_failure')
  AND created_at > datetime('now', '-7 days')
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- Password changes (user engagement)
SELECT COUNT(*) as password_changes
FROM auth_audit_log
WHERE event_type = 'password_changed'
  AND created_at > datetime('now', '-7 days');
```

---

## Next Steps

- **[Operations Guide](operations-guide.md)** - Ongoing maintenance procedures
- **[Security Guide](security-guide.md)** - Post-migration security hardening
- **[Troubleshooting](troubleshooting.md)** - Common migration issues

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Migration Team
