# Auth Testing Quick Reference

## ⚠️ CRITICAL: Know Your Testing Context

### Destructive vs Non-Destructive Testing

| Test Type | Database | Safe to Run Anytime? |
|-----------|----------|---------------------|
| Smoke tests | Development (lupin_db_dev) | ✅ YES - non-destructive |
| Unit tests | Development (lupin_db_dev) | ✅ YES - non-destructive |
| Manual curl | Development (lupin_db_dev) | ✅ YES - non-destructive |
| Integration tests | Test DB (lupin_db_test) | ⚠️ Destructive - use runner script |

### Running Integration Tests (Destructive)

```bash
# ONLY way to run integration tests - uses Testing config block
./src/tests/run-integration-tests.sh -v
```

This script:
- Sets `config_block_id=Lupin:+Testing` BEFORE Python starts
- Uses test database (lupin_db_test)
- Drops/recreates tables for each test

### Dual Safety Mechanism

The Testing config uses **dual validation** to prevent accidental production data destruction:

```python
# Safety Check #1: app_testing flag must be True
# Safety Check #2: Database path must contain "test"
# BOTH must match or ValueError is raised - test aborts before DB access
```

### For More Details

See: `src/rnd/2025.10.17-integration-test-database-safety-proof.md`

---

## Credential Unification (Session 267)

All smoke tests, proxy tests, and pipeline tests now use the unified `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*`
prefix. This ensures the test runner and notification proxy authenticate as the same user (same WebSocket
channel), preventing "Operation cancelled" failures caused by credential mismatch.

---

## Non-Destructive Testing (Manual/Smoke/Unit)

### Python - Login and Get Token

```python
import os
import requests

BASE_URL = "http://localhost:7999"

# Get credentials from environment variables (NEVER hardcode passwords)
email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

if not email or not password:
    raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables" )

# Login with existing user (development database)
login_resp = requests.post( f"{BASE_URL}/auth/login",
    json={"email": email, "password": password} )
token = login_resp.json()["tokens"]["access_token"]

# Use token for authenticated requests
headers = {"Authorization": f"Bearer {token}"}
response = requests.get( f"{BASE_URL}/api/protected-endpoint", headers=headers )
```

### Curl Patterns — Reference Only

The curl examples below document HTTP authentication flows for understanding and one-off debugging.
**Do NOT use curl for pipeline or integration testing.** Use the automated test infrastructure instead:

- **Non-interactive agents**: `LivePipelineTestBase` — see `src/tests/smoke/test_calculator_live_pipeline.py`
- **Interactive agents**: `InteractiveSmokeTest` — see `src/tests/smoke/test_proxy_integration.py`
- **Integration tests**: `./src/tests/run-integration-tests.sh -v`

### CURL - One-Liner Pattern

```bash
# First, set credentials via environment variables (NEVER embed passwords in scripts)
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"

# Login and extract token
TOKEN=$(curl -s -X POST "http://localhost:7999/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL\", \"password\": \"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD\"}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['tokens']['access_token'])")

# Use token for authenticated requests
curl -H "Authorization: Bearer $TOKEN" http://localhost:7999/api/your-endpoint
```

### CURL - Two-Step (Easier to Debug)

```bash
# Set credentials via environment variables
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"

# Step 1: Login
curl -X POST "http://localhost:7999/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL\", \"password\": \"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD\"}"

# Step 2: Copy access_token from response, then:
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" http://localhost:7999/api/your-endpoint
```

### Security Best Practice

⚠️ **NEVER embed passwords as string literals in code or scripts.**

Always use environment variables:
```bash
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
```

In Python:
```python
import os
email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
```

---

## Integration Test Fixtures (Destructive Context Only)

These fixtures are ONLY for use with `./src/tests/run-integration-tests.sh`:

| Fixture | What it provides | ⚠️ Destructive |
|---------|------------------|----------------|
| `clean_test_db` | Fresh DB schema | YES - drops all tables |
| `create_test_user` | Registers + logs in | YES - writes to DB |
| `auth_headers` | Bearer token headers | Depends on create_test_user |

### Helper Functions

```python
from tests.integration.conftest import login_user, get_auth_header

# Login existing user
resp = login_user( "existing@email.com", "Password123!" )
token = resp.json()["tokens"]["access_token"]

# Create headers
headers = get_auth_header( token )
```

---

## Key Documentation Files

| File | What It Explains |
|------|------------------|
| `src/tests/integration/README.md` | Dual safety mechanism, common pitfalls |
| `src/rnd/2025.10.17-integration-test-database-safety-proof.md` | Technical proof of safety mechanism |
| `src/tests/run-integration-tests.sh` | Why port conflicts matter, config setup |
| `src/conf/lupin-app.ini` (lines 324-337) | Testing block definition |
