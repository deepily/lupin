# Integration Tests for Lupin

This directory contains integration tests that validate complete user flows end-to-end across multiple system components.

## Overview

Integration tests differ from unit tests and smoke tests by testing the entire system working together:
- **Unit Tests**: Test individual functions in isolation
- **Smoke Tests**: Quick sanity checks that modules load and run
- **Integration Tests**: Test complete user workflows across API, database, and authentication

## Test Suite

### 43 Comprehensive Integration Tests

**Authentication Tests** (8 tests in `test_auth_integration.py`)

1. **`test_complete_registration_flow()`**
   - Tests full user registration from API call to database storage to login
   - Validates: Registration → DB persistence → Login → Protected endpoint access
   - **Runtime**: ~500ms

2. **`test_login_with_valid_credentials()`**
   - Tests authentication with existing user credentials
   - Validates: Login → JWT token generation → Token validation → User data retrieval
   - **Runtime**: ~300ms

3. **`test_failed_login_rate_limiting()`**
   - Tests account lockout after multiple failed login attempts
   - Validates: 5 failed attempts → Account locked → Correct password also fails when locked
   - **Runtime**: ~1000ms (multiple requests)

4. **`test_token_refresh_flow()`**
   - Tests JWT token refresh mechanism with rotation
   - Validates: Initial login → Refresh tokens → Token rotation → New token works
   - **Runtime**: ~400ms

5. **`test_password_change_flow()`**
   - Tests password change functionality
   - Validates: Login → Change password → Old password fails → New password works
   - **Runtime**: ~600ms

6. **`test_email_verification_flow()`**
   - Tests email verification process (mocks SMTP)
   - Validates: User unverified → Request verification → Extract token → Verify → User verified
   - **Runtime**: ~400ms

7. **`test_password_reset_flow()`**
   - Tests password reset process (mocks SMTP)
   - Validates: Request reset → Extract token → Reset password → Old password fails → New password works
   - **Runtime**: ~600ms

8. **`test_websocket_jwt_authentication()`**
   - Tests WebSocket authentication with JWT tokens
   - Validates: Login → Connect to WebSocket → Auth with JWT → Receive auth_success → Session active
   - **Runtime**: ~500ms
   - **Note**: Async test using pytest-asyncio

**Admin User Management Tests** (23 tests in `test_admin_users.py`)
- User listing, searching, filtering
- User creation, updates, deletions
- Role management (promote/demote admin)
- Admin permission enforcement

**Queue Filtering Tests** (12 tests in `test_queue_filtering_integration.py`)
- User-filtered queue access
- Admin wildcard access
- Multi-queue validation
- Response format validation

**Claude Code Dispatcher Tests** (42 tests across 3 files)

*SDK Validation* (11 tests in `test_sdk_validation.py`)
- SDK import verification
- ClaudeAgentOptions construction
- ClaudeSDKClient instantiation
- SDK connection tests (E2E)

*Dispatcher E2E* (23 tests in `test_dispatcher_e2e.py`)
- Option A bounded tasks
- Option B interactive sessions
- MCP voice tool integration
- Streaming message callbacks
- Session lifecycle tracking

*Bidirectional Control* (8 tests in `test_dispatcher_bidirectional.py`)
- inject() message injection
- interrupt() session control
- Active session tracking
- Error handling for non-existent sessions

### Total Runtime
Expected: **~30-60 seconds** for all 85+ tests (auth + queue + dispatcher)

## Prerequisites

### Required Dependencies

Install with pip:
```bash
pip install pytest pytest-asyncio websockets requests
```

### ⚠️ Common Pitfall: Running Tests with Dev Server Active

**CRITICAL**: Stop development FastAPI server before running integration tests!

**Why this is required**:
- Integration tests manage their own server instance on port 7999
- Development server also uses port 7999
- Port conflict causes test runner to fail immediately
- Tests require `[Lupin: Testing]` config block (test database)
- Dev server uses `[Lupin: Development]` config block (production database)

**Symptoms of this issue**:
```
ERROR: Development Server Running

Port 7999 is already in use (likely the development FastAPI server).
```

**⚠️ SNEAKY SYMPTOM**: If the test runner somehow bypasses the port check, tests will mysteriously fail:
- Authentication tests get **401 Unauthorized** errors (should be 200)
- API key validation appears broken (it's not - wrong database!)
- Tests hit dev server with production database
- Test fixtures create data in test database but requests query production database
- **Solution**: Always stop dev server BEFORE running tests, don't try to work around it

**Solution**:
```bash
# Find process on port 7999
lsof -Pi :7999 -sTCP:LISTEN

# Kill the development server
kill <PID>

# Then run tests (automated runner handles server)
./src/tests/run-integration-tests.sh -v
```

**Why the automated runner is strongly recommended**:
- ✅ Checks port availability and gives clear error message
- ✅ Starts server with correct Testing config automatically
- ✅ Cleans up server on exit (even if tests fail)
- ✅ Prevents accidental production database access

### Running Tests - Two Options

#### Option 1: Automated Test Runner (Recommended)

**One command does everything**:

```bash
# From project root
./src/tests/run-integration-tests.sh -v
```

**Features**:
- ✅ Checks port 7999 availability
- ✅ Starts FastAPI server automatically with Testing config
- ✅ Waits for health check
- ✅ Runs pytest with your arguments
- ✅ Cleans up server on exit
- ✅ Returns pytest exit code (CI/CD friendly)

**Usage Examples**:
```bash
./src/tests/run-integration-tests.sh           # Run all tests
./src/tests/run-integration-tests.sh -v        # Verbose
./src/tests/run-integration-tests.sh -v -s     # Very verbose (show prints)
./src/tests/run-integration-tests.sh test_auth_integration.py  # Specific file
```

#### Option 2: Manual (For Debugging)

**Start server manually with Testing config block**:

```bash
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
./src/scripts/run-fastapi-lupin.sh
```

Then run tests in separate terminal:
```bash
pytest src/tests/integration/ -v
```

**Why Testing Config Block?**
- Uses isolated test database (`/src/conf/long-term-memory/test-lupin-auth.db`)
- Dual safety validation prevents accidental production database modification
- Both server AND pytest process use same configuration (from environment variable)
- Tests call database functions directly (no API overhead)

**Dual Safety Mechanism**:
1. Configuration flag: `app_testing=true` (from Testing block)
2. Path validation: Database path must contain "test"

Both checks must pass or operations fail with safety violation error.

### 🔒 Configuration Safety: Why Testing Config Block Matters

Integration tests use `[Lupin: Testing]` config block for critical safety:

**Dual Safety Mechanism Explained**:

1. **ConfigurationManager loads Testing block** (via environment variable)
2. **`app_testing=true` enables test mode**
3. **`sqlite_database_path` points to test database** (`test-lupin-auth.db`)
4. **Both checks validated on EVERY database operation**

**Configuration Comparison**:

```ini
[Lupin: Development]
app_testing = false
sqlite_database_path = /src/conf/long-term-memory/lupin-auth.db  # ⚠️ PRODUCTION

[Lupin: Testing]
app_testing = true
sqlite_database_path = /src/conf/long-term-memory/test-lupin-auth.db  # ✅ TEST
```

**What could go wrong without this safety**:
- ❌ Tests might access production database
- ❌ `clean_test_db` fixture could wipe production user accounts
- ❌ Integration test failures could corrupt real data
- ❌ Multiple test runs could interfere with active users

**How automated runner prevents this** (`src/tests/run-integration-tests.sh:72`):

```bash
# Sets environment variable BEFORE Python starts
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"

# Then starts server - ConfigurationManager singleton locks in Testing config
python -m lupin_app.main
```

**Safety Verification** (`src/cosa/rest/sqlite_database.py:18-79`):

```python
def get_auth_db_path():
    # Safety Check #1: app_testing flag must be True
    if config_mgr.get( "app_testing" ):
        # Safety Check #2A: If test mode, path MUST contain "test"
        if "test" not in db_path:
            raise ValueError( "SAFETY VIOLATION: app_testing=true but path missing 'test'" )
    else:
        # Safety Check #2B: If path contains "test", MUST be in test mode
        if "test" in db_path:
            raise ValueError( "SAFETY VIOLATION: app_testing=false but path contains 'test'" )
```

**Result**: IMPOSSIBLE to accidentally access production database during tests.

**Timing is critical**:
- Environment variable set BEFORE Python starts
- ConfigurationManager singleton created on first import
- Once created, configuration CANNOT change
- All subsequent database operations use locked-in config

### Configuration

Ensure `lupin-app.ini` has:
```ini
auth mode = jwt
```

## Quick Start

**Simplest way** (automated):
```bash
./src/tests/run-integration-tests.sh -v
```

**Manual way** (for debugging - see "Running Tests" section below)

### Run Specific Test

```bash
# With automated runner
./src/tests/run-integration-tests.sh test_auth_integration.py::test_complete_registration_flow

# Manual (if server already running)
pytest src/tests/integration/test_auth_integration.py::test_complete_registration_flow
```

## Test Structure

### Fixtures (conftest.py)

**Environment Fixtures** (session-level):
- `verify_test_environment` - One-time validation that server is running with Testing config block (runs automatically)

**Database Fixtures** (function-level):
- `clean_test_db` - Reinitializes test database by calling `init_sqlite_database()` directly before each test

**User Fixtures**:
- `test_user_credentials` - Standard test user credentials
- `test_admin_credentials` - Admin user credentials
- `create_test_user` - Creates test user via API and returns user data + tokens
- `create_test_admin` - Creates admin user via API (with database role elevation)

**Auth Fixtures**:
- `auth_headers` - Pre-authenticated headers with JWT token

**Helper Functions**:
- `register_user(email, password)` - Register via API
- `login_user(email, password)` - Login via API
- `get_auth_header(access_token)` - Create auth headers from token

**Configuration**:
- `BASE_URL = "http://localhost:7999"` - Live server endpoint

### Test Isolation

Each test runs in complete isolation:
- **Fresh database** reinitialized by direct function calls (`init_sqlite_database()`) before each test
- **Automatic cleanup** - database deleted after each test
- **No state sharing** between tests
- **Can run in any order** (no dependencies)
- **Tests use requests library** to make real HTTP calls to live server
- **Server manages all infrastructure** (queues, WebSocket, database)
- **Dual safety** validates test mode before every database operation

## What Gets Tested

### API Endpoints

**Authentication**:
- `POST /auth/register` - User registration
- `POST /auth/login` - User login
- `POST /auth/refresh` - Token refresh
- `POST /auth/logout` - User logout
- `GET /auth/me` - Get current user
- `PUT /auth/change-password` - Change password
- `POST /auth/request-verification` - Request email verification
- `POST /auth/verify-email` - Verify email with token
- `POST /auth/request-password-reset` - Request password reset
- `POST /auth/reset-password` - Reset password with token
- `WS /ws/queue/{session_id}` - WebSocket with JWT auth

**Admin User Management**:
- `GET /admin/users` - List all users
- `GET /admin/users/{user_id}` - Get user by ID
- `POST /admin/users` - Create new user
- `PUT /admin/users/{user_id}` - Update user
- `DELETE /admin/users/{user_id}` - Delete user
- `POST /admin/users/{user_id}/promote` - Promote to admin
- `POST /admin/users/{user_id}/demote` - Demote from admin

**Queue Filtering**:
- `GET /api/get-queue/{queue_name}?user_filter=<uid|*>` - Get filtered queue
- `POST /api/push` - Push job to queue

**System**:
- Health and status endpoints

### Database Operations
- User creation and retrieval
- Password hashing and validation
- Token storage and validation
- Failed login attempt tracking
- Email verification status updates
- Password reset token management

### Security Features
- JWT token generation and validation
- Password strength validation
- Rate limiting and account lockout
- Token rotation on refresh
- Secure password storage (bcrypt)
- Email verification workflow
- Password reset workflow

## Common Issues

### Server Not Running

**Error**: `Cannot connect to test server at http://localhost:7999`

**Solution**: Use the automated test runner (it starts the server automatically):
```bash
./src/tests/run-integration-tests.sh -v
```

**Or** start server manually:
```bash
export LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing"
./src/scripts/run-fastapi-lupin.sh
```

### Port Already in Use

**Error**: `Port 7999 is already in use`

**Solution**:
- Kill the existing process: `lsof -Pi :7999 -sTCP:LISTEN` then `kill <PID>`
- Or use a different port (requires code changes)

### Dual Safety Violation

**Error**: `ValueError: SAFETY VIOLATION: app_testing=true but database path missing 'test'`

**Solution**: This error indicates a configuration mismatch. Ensure:
1. Server started with `config_block_id=Lupin:+Testing`
2. Testing config block has `app_testing=true` and test database path

### WebSocket Test Timeout

**Error**: `asyncio.TimeoutError` in `test_websocket_jwt_authentication`

**Solution**:
- Verify server is running
- Check WebSocket endpoint is accessible
- Increase timeout in test if needed

### Import Errors

**Error**: `ModuleNotFoundError: No module named 'cosa'`

**Solution**: Run tests from project root, not from tests directory

## Debugging Tests

### Enable Verbose Output

```bash
# Show detailed test output
pytest -v -s src/tests/integration/
```

### Run Single Failing Test

```bash
# Focus on specific failure
pytest -v -s src/tests/integration/test_auth_integration.py::test_failed_login_rate_limiting
```

### Add Debug Breakpoints

```python
# In test code
import pdb; pdb.set_trace()
```

### Check Test Database

```bash
# Manually inspect test database (during debugging)
sqlite3 src/tests/integration/test_auth.db
.tables
SELECT * FROM users;
```

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio websockets requests
      - name: Run integration tests
        run: ./src/tests/run-integration-tests.sh -v
```

## Maintenance

### Adding New Tests

1. Write test function in `test_auth_integration.py`
2. Use existing fixtures from `conftest.py`
3. Follow naming convention: `test_<feature>_flow()`
4. Document test purpose in docstring
5. Ensure test cleans up after itself

### Updating Fixtures

Modify `conftest.py` to add new fixtures or update existing ones. Ensure backward compatibility with existing tests.

## Related Documentation

- **Unit Tests**: `src/tests/unit/README.md` (if exists)
- **Smoke Tests**: Inline `quick_smoke_test()` functions in modules
- **Main Testing README**: `src/tests/README.md`
- **JWT Auth Design**: `src/rnd/2025.09.29-jwt-oauth/README.md`

## Questions?

For issues or questions about integration tests:
1. Check test output for detailed error messages
2. Review this README for common issues
3. Check test database state if tests fail unexpectedly
4. Ensure server is running and accessible
