# Integration Tests for JWT Authentication

This directory contains integration tests that validate complete user flows end-to-end across multiple system components.

## Overview

Integration tests differ from unit tests and smoke tests by testing the entire system working together:
- **Unit Tests**: Test individual functions in isolation
- **Smoke Tests**: Quick sanity checks that modules load and run
- **Integration Tests**: Test complete user workflows across API, database, and authentication

## Test Suite

### 8 Comprehensive Integration Tests

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

### Total Runtime
Expected: **~4-6 seconds** for all 8 tests

## Prerequisites

### Required Dependencies

Install with pip:
```bash
pip install pytest pytest-asyncio websockets requests
```

### FastAPI Server

Tests require the FastAPI server running on `localhost:7999`:

```bash
# Start server (from project root)
src/scripts/run-fastapi-lupin.sh
```

**Important**: Tests use an isolated test database (`src/tests/integration/test_auth.db`) that is created fresh for each test and cleaned up automatically.

### Configuration

Ensure `lupin-app.ini` has:
```ini
auth mode = jwt
```

## Running Tests

### Run All Integration Tests

```bash
# From project root
pytest src/tests/integration/

# With verbose output
pytest -v src/tests/integration/

# With detailed output (shows print statements)
pytest -v -s src/tests/integration/
```

### Run Specific Test

```bash
# Run single test
pytest src/tests/integration/test_auth_integration.py::test_complete_registration_flow

# Run multiple specific tests
pytest src/tests/integration/test_auth_integration.py::test_login_with_valid_credentials \
       src/tests/integration/test_auth_integration.py::test_token_refresh_flow
```

### Run with Coverage

```bash
# Install coverage tool
pip install pytest-cov

# Run with coverage report
pytest --cov=cosa.rest --cov-report=html src/tests/integration/

# View coverage report
open htmlcov/index.html
```

## Test Structure

### Fixtures (conftest.py)

**Database Fixtures**:
- `test_db_path` - Path to isolated test database
- `clean_test_db` - Auto-cleanup before/after each test

**User Fixtures**:
- `test_user_credentials` - Standard test user credentials
- `test_admin_credentials` - Admin user credentials
- `create_test_user` - Creates test user in database
- `create_test_admin` - Creates admin user in database

**Auth Fixtures**:
- `auth_headers` - Pre-authenticated headers with JWT token
- `base_url` - Base URL for API requests

**Helper Functions**:
- `make_request()` - Generic HTTP request helper
- `register_user()` - Helper to register via API
- `login_user()` - Helper to login via API
- `get_auth_header()` - Create auth headers from token

### Test Isolation

Each test runs in complete isolation:
- **Fresh database** created before each test
- **Automatic cleanup** after each test
- **No state sharing** between tests
- **Can run in any order** (no dependencies)

## What Gets Tested

### API Endpoints
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

**Error**: `ConnectionRefusedError: [Errno 111] Connection refused`

**Solution**: Start FastAPI server:
```bash
src/scripts/run-fastapi-lupin.sh
```

### Database Permission Errors

**Error**: `PermissionError: Cannot delete test_auth.db`

**Solution**: Ensure no other processes have the test database open

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
      - name: Start FastAPI server
        run: |
          src/scripts/run-fastapi-lupin.sh &
          sleep 5  # Wait for server startup
      - name: Run integration tests
        run: pytest -v src/tests/integration/
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
- **JWT Auth Design**: `src/rnd/jwt-oauth/README.md`

## Questions?

For issues or questions about integration tests:
1. Check test output for detailed error messages
2. Review this README for common issues
3. Check test database state if tests fail unexpectedly
4. Ensure server is running and accessible
