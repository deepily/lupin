# Authentication Operations Guide

**Version**: 1.0
**Last Updated**: 2025.10.04
**Target Audience**: DevOps Engineers, System Administrators

---

## Table of Contents

1. [Deployment Procedures](#deployment-procedures)
2. [Configuration Reference](#configuration-reference)
3. [Monitoring & Logging](#monitoring--logging)
4. [Backup & Recovery](#backup--recovery)
5. [Maintenance Tasks](#maintenance-tasks)
6. [Performance Tuning](#performance-tuning)
7. [Troubleshooting Common Issues](#troubleshooting-common-issues)

---

## Deployment Procedures

### Initial Production Deployment

#### Pre-Deployment Checklist

- [ ] **Environment Variables Set**
  ```bash
  export LUPIN_CONFIG_MGR_CLI_ARGS="--block-name=Lupin: Production"
  export JWT_SECRET_KEY=$(openssl rand -hex 32)
  export SMTP_USERNAME="your_smtp_user"
  export SMTP_PASSWORD="your_smtp_password"
  ```

- [ ] **Database Initialized**
  ```bash
  # Run FastAPI server once to initialize database
  python -m lupin_app.main
  # Check auth.db created
  ls -lh /path/to/auth.db
  ```

- [ ] **HTTPS Configured**
  ```bash
  # Verify SSL certificate
  sudo certbot certificates

  # Test HTTPS
  curl -I https://your-domain.com
  ```

- [ ] **Security Headers Verified**
  ```bash
  curl -I https://your-domain.com/auth/me | grep -E "(X-Frame|HSTS|X-Content)"
  ```

#### Deployment Steps

**1. Stop Existing Service** (if updating):
```bash
sudo systemctl stop lupin-fastapi
```

**2. Backup Database**:
```bash
cp /var/lib/lupin/auth.db /var/lib/lupin/auth.db.backup.$(date +%Y%m%d_%H%M%S)
```

**3. Deploy New Code**:
```bash
cd /opt/lupin
git pull origin main
```

**4. Install Dependencies**:
```bash
source /opt/lupin/venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-auth.txt  # Auth-specific packages
```

**5. Run Database Migrations** (if needed):
```bash
# Currently auto-initialized on startup
# Future: Use Alembic for migrations
python -m src.cosa.rest.sqlite_database  # Verify tables
```

**6. Start Service**:
```bash
sudo systemctl start lupin-fastapi
sudo systemctl status lupin-fastapi
```

**7. Verify Deployment**:
```bash
# Health check
curl https://your-domain.com/api/health

# Auth endpoints accessible
curl https://your-domain.com/auth/register

# WebSocket connection
wscat -c wss://your-domain.com/ws/queue/test_session
```

#### Post-Deployment Validation

```bash
# Check logs for errors
sudo journalctl -u lupin-fastapi -n 100 --no-pager

# Verify database writeable
sqlite3 /var/lib/lupin/auth.db "SELECT COUNT(*) FROM users;"

# Test authentication flow
curl -X POST https://your-domain.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser@example.com","password":"TestP@ss123!"}'
```

---

### Systemd Service Configuration

**Create Service File** (`/etc/systemd/system/lupin-fastapi.service`):
```ini
[Unit]
Description=Lupin FastAPI Authentication Service
After=network.target

[Service]
Type=simple
User=lupin
Group=lupin
WorkingDirectory=/opt/lupin
Environment="LUPIN_CONFIG_MGR_CLI_ARGS=--block-name=Lupin: Production"
Environment="JWT_SECRET_KEY=your-secret-key-from-env"
Environment="SMTP_USERNAME=your-smtp-user"
Environment="SMTP_PASSWORD=your-smtp-password"
ExecStart=/opt/lupin/venv/bin/python -m uvicorn lupin_app.main:app --host 0.0.0.0 --port 7999 --workers 4
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Enable and Start**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable lupin-fastapi
sudo systemctl start lupin-fastapi
sudo systemctl status lupin-fastapi
```

---

## Configuration Reference

### lupin-app.ini - Authentication Section

**Complete Auth Configuration**:
```ini
[Lupin: Production]
# Inherits from Lupin: Baseline

# ===================================================================
# Authentication Configuration
# ===================================================================

# Authentication Mode
auth mode = jwt
# Options: mock (dev only), jwt (production), firebase (future)

# JWT Settings
jwt secret key = ${JWT_SECRET_KEY}
# IMPORTANT: Use environment variable, never hardcode
# Generate: openssl rand -hex 32

jwt algorithm = HS256
# Algorithm for JWT signing (HS256 recommended)

jwt access token expiration seconds = 1800
# Access token lifetime (default: 30 minutes = 1800 seconds)

jwt refresh token expiration days = 7
# Refresh token lifetime (default: 7 days)

# Password Security
password min length = 8
# Minimum password length

password require uppercase = True
# Require at least one uppercase letter

password require lowercase = True
# Require at least one lowercase letter

password require digit = True
# Require at least one number

password require special = True
# Require at least one special character

bcrypt rounds = 12
# bcrypt hashing rounds (10-12 recommended, 12 = ~250ms)

# Rate Limiting
auth max failed attempts = 5
# Maximum failed login attempts before lockout

auth lockout duration minutes = 15
# Account lockout duration after max failed attempts

# SMTP Email Configuration
smtp host = smtp.gmail.com
# SMTP server hostname

smtp port = 587
# SMTP server port (587 for TLS, 465 for SSL)

smtp username = ${SMTP_USERNAME}
# SMTP username (use environment variable)

smtp password = ${SMTP_PASSWORD}
# SMTP password (use environment variable)

smtp from email = noreply@lupin.ai
# "From" address for outgoing emails

smtp use tls = True
# Use TLS for SMTP connection

send email enabled = True
# Enable/disable email sending (False for dev/test)

app base url = https://your-domain.com
# Base URL for email links (verification, password reset)

# Email Token Settings
email verification token expiration hours = 24
# Email verification token validity (default: 24 hours)

password reset token expiration hours = 1
# Password reset token validity (default: 1 hour)

# Database Configuration
auth database path = /var/lib/lupin/auth.db
# Path to SQLite authentication database

# WebSocket Configuration
websocket heartbeat interval seconds = 30
# WebSocket heartbeat check interval

websocket cleanup interval hours = 1
# WebSocket session cleanup interval

websocket session max age hours = 24
# Maximum WebSocket session age before cleanup

# Audit Logging
auth audit enabled = True
# Enable audit logging for all auth events

auth audit retain days = 90
# Audit log retention period (default: 90 days)
```

---

### Environment Variables

**Required Environment Variables**:
```bash
# Configuration block selection
export LUPIN_CONFIG_MGR_CLI_ARGS="--block-name=Lupin: Production"

# JWT secret key (CRITICAL - rotate regularly)
export JWT_SECRET_KEY="generated-secret-key-32-bytes-hex"

# SMTP credentials
export SMTP_USERNAME="your-smtp-username"
export SMTP_PASSWORD="your-smtp-password"
```

**Optional Environment Variables**:
```bash
# Override specific config values
export AUTH_MODE="jwt"
export JWT_ACCESS_TOKEN_EXPIRATION_SECONDS="1800"
export AUTH_MAX_FAILED_ATTEMPTS="5"
```

**Environment File** (`/etc/lupin/env`):
```bash
LUPIN_CONFIG_MGR_CLI_ARGS="--block-name=Lupin: Production"
JWT_SECRET_KEY="your-generated-secret-key"
SMTP_USERNAME="smtp-user@example.com"
SMTP_PASSWORD="smtp-password"
```

**Load in Service**:
```ini
[Service]
EnvironmentFile=/etc/lupin/env
```

---

## Monitoring & Logging

### Application Logs

**View Logs**:
```bash
# Real-time logs
sudo journalctl -u lupin-fastapi -f

# Last 100 lines
sudo journalctl -u lupin-fastapi -n 100 --no-pager

# Logs since specific time
sudo journalctl -u lupin-fastapi --since "2025-10-04 10:00:00"

# Filter by priority
sudo journalctl -u lupin-fastapi -p err  # Errors only
```

**Log Rotation** (configure systemd journal):
```ini
# /etc/systemd/journald.conf
[Journal]
SystemMaxUse=500M
SystemKeepFree=1G
MaxRetentionSec=1month
```

### Database Audit Logs

**Query Recent Auth Events**:
```sql
-- Recent logins
SELECT user_id, email, event_type, ip_address, user_agent, created_at
FROM auth_audit_log
WHERE event_type IN ('login_success', 'login_failure')
  AND created_at > datetime('now', '-24 hours')
ORDER BY created_at DESC;

-- Failed login attempts by IP
SELECT ip_address, COUNT(*) as failed_attempts
FROM auth_audit_log
WHERE event_type = 'login_failure'
  AND created_at > datetime('now', '-1 hour')
GROUP BY ip_address
HAVING failed_attempts > 5
ORDER BY failed_attempts DESC;

-- Recent password changes
SELECT user_id, email, created_at
FROM auth_audit_log
WHERE event_type = 'password_changed'
  AND created_at > datetime('now', '-7 days')
ORDER BY created_at DESC;
```

**Cleanup Old Audit Logs**:
```sql
-- Delete logs older than 90 days
DELETE FROM auth_audit_log
WHERE created_at < datetime('now', '-90 days');

-- Vacuum database to reclaim space
VACUUM;
```

**Automated Cleanup Script** (`/opt/lupin/scripts/cleanup_audit_logs.sh`):
```bash
#!/bin/bash
DB_PATH="/var/lib/lupin/auth.db"
RETENTION_DAYS=90

echo "Cleaning audit logs older than ${RETENTION_DAYS} days..."

sqlite3 "${DB_PATH}" <<EOF
DELETE FROM auth_audit_log
WHERE created_at < datetime('now', '-${RETENTION_DAYS} days');
VACUUM;
EOF

echo "Audit log cleanup complete"
```

**Cron Schedule**:
```cron
# Run daily at 2 AM
0 2 * * * /opt/lupin/scripts/cleanup_audit_logs.sh >> /var/log/lupin/audit_cleanup.log 2>&1
```

### Metrics & Monitoring

**Key Metrics to Monitor**:

1. **Authentication Success Rate**
   ```sql
   SELECT
       COUNT(CASE WHEN event_type = 'login_success' THEN 1 END) as successes,
       COUNT(CASE WHEN event_type = 'login_failure' THEN 1 END) as failures,
       ROUND(100.0 * COUNT(CASE WHEN event_type = 'login_success' THEN 1 END) /
             COUNT(*), 2) as success_rate
   FROM auth_audit_log
   WHERE event_type IN ('login_success', 'login_failure')
     AND created_at > datetime('now', '-1 hour');
   ```

2. **Active Users**
   ```sql
   SELECT COUNT(DISTINCT user_id) as active_users
   FROM auth_audit_log
   WHERE event_type = 'login_success'
     AND created_at > datetime('now', '-24 hours');
   ```

3. **Failed Login Rate** (suspicious activity)
   ```sql
   SELECT
       strftime('%Y-%m-%d %H:00:00', created_at) as hour,
       COUNT(*) as failed_attempts
   FROM auth_audit_log
   WHERE event_type = 'login_failure'
     AND created_at > datetime('now', '-24 hours')
   GROUP BY hour
   ORDER BY hour;
   ```

4. **Database Size**
   ```bash
   du -h /var/lib/lupin/auth.db
   ```

---

## Backup & Recovery

### Database Backup Strategy

**Automated Backup Script** (`/opt/lupin/scripts/backup_auth_db.sh`):
```bash
#!/bin/bash
set -e

# Configuration
DB_PATH="/var/lib/lupin/auth.db"
BACKUP_DIR="/var/backups/lupin/auth"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/auth_${TIMESTAMP}.db"

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# SQLite backup (hot backup, safe while database is in use)
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

# Verify backup
if [ -f "${BACKUP_FILE}" ]; then
    echo "Backup created: ${BACKUP_FILE}"
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "Backup size: ${SIZE}"
else
    echo "ERROR: Backup failed!" >&2
    exit 1
fi

# Compress backup
gzip "${BACKUP_FILE}"
echo "Backup compressed: ${BACKUP_FILE}.gz"

# Encrypt backup (optional - recommended for production)
# gpg --encrypt --recipient admin@yourcompany.com "${BACKUP_FILE}.gz"
# rm "${BACKUP_FILE}.gz"

# Clean old backups
find "${BACKUP_DIR}" -name "auth_*.db.gz" -mtime +${RETENTION_DAYS} -delete
echo "Cleaned backups older than ${RETENTION_DAYS} days"

echo "Backup complete!"
```

**Cron Schedule**:
```cron
# Daily backup at 3 AM
0 3 * * * /opt/lupin/scripts/backup_auth_db.sh >> /var/log/lupin/backup.log 2>&1

# Weekly backup to remote storage
0 4 * * 0 rsync -avz /var/backups/lupin/ backup-server:/backups/lupin/
```

### Restore Procedures

**Restore from Backup**:
```bash
#!/bin/bash
# restore_auth_db.sh

BACKUP_FILE="$1"
DB_PATH="/var/lib/lupin/auth.db"

if [ -z "${BACKUP_FILE}" ]; then
    echo "Usage: $0 <backup_file.db.gz>"
    exit 1
fi

# Stop service
sudo systemctl stop lupin-fastapi

# Backup current database (safety)
cp "${DB_PATH}" "${DB_PATH}.before_restore.$(date +%Y%m%d_%H%M%S)"

# Decompress and restore
gunzip -c "${BACKUP_FILE}" > "${DB_PATH}"

# Verify integrity
sqlite3 "${DB_PATH}" "PRAGMA integrity_check;"

# Start service
sudo systemctl start lupin-fastapi

echo "Restore complete. Please verify functionality."
```

### Disaster Recovery

**Complete System Failure**:
1. **Provision new server**
2. **Install dependencies**
3. **Restore configuration** (`/etc/lupin/env`)
4. **Restore database** (from backup)
5. **Restore application code** (from git)
6. **Start services**
7. **Verify functionality**

**Data Corruption**:
1. **Stop service immediately**
2. **Identify corruption scope** (sqlite3 integrity_check)
3. **Restore from most recent good backup**
4. **Replay audit logs if needed** (manual verification)
5. **Investigate root cause**

---

## Maintenance Tasks

### Routine Maintenance Schedule

**Daily**:
- [ ] Monitor error logs
- [ ] Check disk space
- [ ] Review failed login alerts

**Weekly**:
- [ ] Review audit logs for suspicious activity
- [ ] Check backup success
- [ ] Database integrity check

**Monthly**:
- [ ] Rotate JWT secret key (if policy requires)
- [ ] Review and update security patches
- [ ] Performance analysis
- [ ] Test disaster recovery procedures

**Quarterly**:
- [ ] Security audit
- [ ] Review access controls
- [ ] Update dependencies
- [ ] Test backup restore procedures

### Database Maintenance

**Integrity Check**:
```bash
sqlite3 /var/lib/lupin/auth.db "PRAGMA integrity_check;"
# Expected output: ok
```

**Optimize Database**:
```sql
-- Rebuild database to reclaim space and optimize
VACUUM;

-- Analyze database for query optimization
ANALYZE;
```

**Database Statistics**:
```sql
-- Table sizes
SELECT
    name as table_name,
    (SELECT COUNT(*) FROM users) as users,
    (SELECT COUNT(*) FROM refresh_tokens) as refresh_tokens,
    (SELECT COUNT(*) FROM failed_login_attempts) as failed_attempts,
    (SELECT COUNT(*) FROM auth_audit_log) as audit_logs,
    (SELECT COUNT(*) FROM email_verification_tokens) as verification_tokens,
    (SELECT COUNT(*) FROM password_reset_tokens) as reset_tokens;
```

### Token Cleanup

**Expired Token Cleanup Script**:
```python
# cleanup_expired_tokens.py
from cosa.rest.refresh_token_service import cleanup_expired_refresh_tokens
from cosa.rest.email_token_service import cleanup_expired_tokens

# Run cleanup
refresh_count = cleanup_expired_refresh_tokens()
email_count = cleanup_expired_tokens()

print(f"Cleaned {refresh_count} expired refresh tokens")
print(f"Cleaned {email_count} expired email tokens")
```

**Cron Schedule**:
```cron
# Daily cleanup at 1 AM
0 1 * * * cd /opt/lupin && /opt/lupin/venv/bin/python scripts/cleanup_expired_tokens.py
```

---

## Performance Tuning

### Application Performance

**Uvicorn Workers**:
```bash
# Number of worker processes (recommendation: 2-4 * CPU cores)
uvicorn lupin_app.main:app --workers 4 --host 0.0.0.0 --port 7999
```

**Worker Configuration**:
```ini
# systemd service
ExecStart=/opt/lupin/venv/bin/uvicorn lupin_app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --host 0.0.0.0 \
    --port 7999 \
    --timeout-keep-alive 65
```

### Database Performance

**SQLite Optimizations** (lupin-app.ini):
```ini
# Enable WAL mode for better concurrency
sqlite wal mode = True

# Cache size (pages * page_size = total cache)
sqlite cache size = 10000  # ~40MB with 4KB pages
```

**Connection Pooling** (future enhancement):
```python
# Use SQLAlchemy connection pool
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    'sqlite:///auth.db',
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20
)
```

### Rate Limiting Tuning

**Adjust for Load**:
```ini
# Higher traffic - stricter limits
auth max failed attempts = 3
auth lockout duration minutes = 30

# Lower traffic - lenient limits
auth max failed attempts = 10
auth lockout duration minutes = 5
```

---

## Troubleshooting Common Issues

### Service Won't Start

**Check Logs**:
```bash
sudo journalctl -u lupin-fastapi -n 50 --no-pager
```

**Common Causes**:
1. **Port already in use**
   ```bash
   sudo lsof -i :7999
   # Kill conflicting process
   ```

2. **Missing environment variables**
   ```bash
   # Check environment
   sudo systemctl show lupin-fastapi | grep Environment
   ```

3. **Database permissions**
   ```bash
   ls -lh /var/lib/lupin/auth.db
   # Should be owned by lupin:lupin with 600 permissions
   ```

### High CPU Usage

**Investigate**:
```bash
# Top processes
top -u lupin

# Worker processes
ps aux | grep uvicorn
```

**Possible Causes**:
- Too many workers (reduce from 4 to 2)
- Database lock contention (enable WAL mode)
- Bcrypt rounds too high (reduce from 12 to 10)

### Database Locked Errors

**Solutions**:
```sql
-- Enable WAL mode (Write-Ahead Logging)
PRAGMA journal_mode=WAL;

-- Increase busy timeout
PRAGMA busy_timeout=5000;  -- 5 seconds
```

### Email Sending Failures

**Check SMTP Configuration**:
```bash
# Test SMTP connection
python -c "
import smtplib
smtp = smtplib.SMTP('smtp.gmail.com', 587)
smtp.starttls()
smtp.login('user', 'password')
print('SMTP connection successful')
"
```

**Common Fixes**:
- Enable "Less secure app access" for Gmail
- Use app-specific password for Gmail
- Check firewall rules (port 587/465)

---

## Next Steps

- **[Security Guide](security-guide.md)** - Security best practices and hardening
- **[Troubleshooting](troubleshooting.md)** - Detailed troubleshooting procedures
- **[Monitoring Dashboard Setup](#)** - Configure Grafana/Prometheus (future)

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Operations Team
