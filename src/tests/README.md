# Lupin Testing Strategy

Comprehensive testing approach with three tiers of validation to ensure code quality, reliability, and security.

## Test Hierarchy

### 1. Unit Tests (`src/tests/unit/`)

**Purpose**: Test individual functions and methods in isolation

**Characteristics**:
- Very fast execution (1-10ms per test)
- Test single function behavior
- Use mocks/stubs for dependencies
- Test both success and failure paths
- High coverage of edge cases

**Coverage**:
- `jwt_service.py` - 14 tests for JWT token operations
- `password_service.py` - Password hashing and validation
- `user_service.py` - User CRUD operations
- `rate_limiter.py` - Rate limiting logic
- Additional service modules

**Run Command**:
```bash
# Run all unit tests
pytest src/tests/unit/

# Run with verbose output
pytest -v src/tests/unit/

# Run specific test file
pytest src/tests/unit/test_jwt_service.py

# Run specific test
pytest src/tests/unit/test_jwt_service.py::test_create_access_token_valid_user
```

**Example**:
```python
def test_create_access_token_valid_user():
    """Test creating JWT access token with valid user data."""
    token = create_access_token(
        user_id="test_user_123",
        email="test@example.com",
        roles=["user"]
    )

    assert token is not None
    assert len( token.split( '.' ) ) == 3  # JWT format
```

---

### 2. Smoke Tests (Inline `quick_smoke_test()` Functions)

**Purpose**: Quick sanity checks that modules load and basic functionality works

**Characteristics**:
- Fast execution (10-100ms per module)
- Module-level validation
- Test core functions exist and can be called
- Minimal dependencies
- Run during development

**Coverage**:
- All major REST modules (`jwt_service`, `auth`, `user_service`, etc.)
- Agent modules (math, calendar, todos, etc.)
- ~50 smoke tests across codebase

**Run Command**:
```bash
# Run smoke test for specific module
python -m cosa.rest.jwt_service

# Run smoke test for auth module
python -m cosa.rest.auth

# Run all smoke tests (custom script needed)
./src/scripts/run-all-smoke-tests.sh
```

**Example**:
```python
def quick_smoke_test():
    """JWT service smoke test - validates basic functionality."""
    print( "Testing JWT token creation..." )

    token = create_access_token( "test_user", "test@example.com" )
    if token and len( token.split( '.' ) ) == 3:
        print( "✓ JWT creation working" )
    else:
        print( "✗ JWT creation failed" )
```

---

### 3. Integration Tests (`src/tests/integration/`)

**Purpose**: Test complete user flows end-to-end across multiple components

**Characteristics**:
- Slower execution (100-1000ms per test)
- Test full system interaction
- Use real HTTP requests (not mocked)
- Verify database state changes
- Test error paths and edge cases

**Coverage**:
- 8 comprehensive authentication flow tests:
  1. Complete registration flow
  2. Login with valid credentials
  3. Failed login rate limiting
  4. Token refresh flow
  5. Password change flow
  6. Email verification flow
  7. Password reset flow
  8. WebSocket JWT authentication

**Run Command**:
```bash
# Ensure FastAPI server is running first!
src/scripts/run-fastapi-lupin.sh

# Run all integration tests
pytest src/tests/integration/

# Run specific integration test
pytest src/tests/integration/test_auth_integration.py::test_complete_registration_flow

# Run with verbose output
pytest -v src/tests/integration/
```

**Example**:
```python
def test_complete_registration_flow( test_user_credentials ):
    """Test full user registration from API to database to login."""
    # Register user via API
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200

    # Verify in database
    user = get_user_by_email( email )
    assert user is not None

    # Login with new credentials
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )
    assert "tokens" in login_response.json()
```

---

### 4. WebSocket Smoke Tests (`src/tests/websocket_smoke/`)

**Purpose**: Validate WebSocket functionality and event handling

**Characteristics**:
- Medium execution time
- Tests WebSocket connections
- Validates event subscription and delivery
- Tests both queue and audio WebSocket endpoints

**Coverage**:
- 50 WebSocket tests
- Connection, authentication, event delivery

**Run Command**:
```bash
# Run WebSocket smoke tests
src/scripts/run-websocket-smoke-tests.sh

# Run specific WebSocket test scenario
python src/tests/websocket_smoke/test_basic_connection.py
```

### 5. Interactive Proxy Tests (`src/tests/smoke/test_proxy_integration.py`)

**Purpose**: Automated interactive testing with notification proxy auto-answer

**Characteristics**:
- Tests full agent pipelines including notification-driven user interactions
- Notification proxy auto-answers expediter questions and CRUD confirmations
- 12 scenarios across 3 agent groups (Calculator, CRUD, Expediter)
- Validates submit-and-poll pipelines, arg resolution, and proxy auto-confirmation

**Coverage**:
- Calculator: 3 scenarios (unit conversion, mortgage, price comparison)
- CRUD: 5 scenarios (add/list/delete for todo + calendar)
- Expediter: 4 scenarios (deep research, podcast, research-to-podcast, full args)

**Run Command**:
```bash
# Full integration (requires LUPIN_INTERACTIVE_TESTS=true for expediter)
LUPIN_INTERACTIVE_TESTS=true \
python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm

# Calculator only (no proxy needed)
python src/tests/smoke/test_proxy_integration.py --group calculator --no-confirm

# Via pytest
pytest src/tests/smoke/test_proxy_integration.py -v
```

**Full Guide**: See [`src/docs/automated-interactive-testing.md`](../docs/automated-interactive-testing.md)

---

## Test Comparison Matrix

| Test Type | Count | Speed | Scope | Dependencies | Purpose |
|-----------|-------|-------|-------|--------------|---------|
| **Unit** | 14+ | Very Fast (1-10ms) | Single function | Mocked | Function validation |
| **Smoke** | ~50 | Fast (10-100ms) | Single module | Minimal | Module sanity check |
| **Integration** | 8 | Medium (100-1000ms) | Full flow | Real (API, DB) | End-to-end validation |
| **WebSocket** | 50 | Medium | WebSocket layer | Real (WS server) | WebSocket functionality |
| **Interactive Proxy** | 12 | Slow (5-60s) | Full pipeline | Server + Proxy + LLM | Interactive agent validation |

---

## Testing Anti-Patterns

| Anti-Pattern | Why It's Prohibited | Use Instead |
|-------------|---------------------|-------------|
| Manual `curl` to `/api/push` + polling | Non-repeatable, no validation, no reporting | `LivePipelineTestBase` or `InteractiveSmokeTest` |
| Bespoke shell scripts with curl | Unmaintainable, no framework integration | Automated smoke test scripts |
| Copy-paste curl from API docs into tests | Fragile, no auth lifecycle management | Test base classes handle auth, submit, poll, validate |

**Acceptable curl usage**: API reference documentation, deployment health checks (`curl /health`), one-off debugging (never committed).

---

## Running All Tests

### Run Everything

```bash
# Run all pytest tests (unit + integration)
pytest src/tests/

# Run with coverage
pytest --cov=cosa.rest --cov-report=html src/tests/

# View coverage report
open htmlcov/index.html
```

### Run by Type

```bash
# Unit tests only
pytest src/tests/unit/

# Integration tests only (requires server running!)
pytest src/tests/integration/

# Smoke tests (run individually)
python -m cosa.rest.jwt_service
python -m cosa.rest.auth
python -m cosa.rest.user_service

# WebSocket tests
src/scripts/run-websocket-smoke-tests.sh
```

### Verbose Output

```bash
# Show detailed output
pytest -v src/tests/

# Show print statements too
pytest -v -s src/tests/

# Stop at first failure
pytest -x src/tests/
```

---

## Test Coverage Summary

### Current Coverage (Phase 9)

| Module | Unit Tests | Smoke Tests | Integration Tests |
|--------|-----------|-------------|-------------------|
| `jwt_service.py` | ✅ 14 tests | ✅ Yes | ✅ All flows |
| `password_service.py` | ✅ Yes | ✅ Yes | ✅ Change flow |
| `user_service.py` | ✅ Yes | ✅ Yes | ✅ CRUD flows |
| `auth.py` | ✅ Yes | ✅ Yes | ✅ Auth flows |
| `rate_limiter.py` | ✅ Yes | ✅ Yes | ✅ Lockout test |
| WebSocket auth | ⚠️ Partial | ✅ Yes | ✅ JWT auth test |

**Total Test Count**: ~122 tests
- Unit: 14+
- Smoke: ~50
- Integration: 8
- WebSocket: 50

**Overall Coverage**: ~85-90% for authentication system

---

## When to Use Each Test Type

### Use Unit Tests When:
- Testing a specific function or method
- Need to test edge cases and error handling
- Want fast feedback during development
- Testing complex logic in isolation

### Use Smoke Tests When:
- Verifying a module loads and runs
- Quick sanity check after changes
- Testing during development
- Checking for import/dependency issues

### Use Integration Tests When:
- Testing complete user workflows
- Verifying system components work together
- Testing API endpoints with real database
- Validating security and authentication flows
- Before deploying to production

### Use WebSocket Tests When:
- Testing WebSocket connections
- Verifying event delivery
- Testing real-time features
- Validating WebSocket authentication

### Use Interactive Proxy Tests When:
- Testing agents that require user interaction (notifications)
- Validating expediter argument resolution end-to-end
- Testing CRUD operations that require delete confirmation
- Verifying the notification proxy auto-answer pipeline
- Running pre-merge integration validation for interactive agents

---

## Test Development Guidelines

### Writing New Unit Tests

1. Create test file in `src/tests/unit/test_<module>.py`
2. Use pytest fixtures for setup/teardown
3. Test one function per test
4. Include success and failure cases
5. Mock external dependencies

### Writing New Smoke Tests

1. Add `quick_smoke_test()` function to module
2. Test core functionality only
3. Print clear pass/fail indicators
4. Keep it fast (<100ms)
5. Handle exceptions gracefully

### Writing New Integration Tests

1. Add test to `src/tests/integration/test_auth_integration.py`
2. Use fixtures from `conftest.py`
3. Test complete user flow
4. Verify database state
5. Clean up after test (automatic via fixtures)
6. Document test purpose in docstring

---

## Continuous Integration

### Pre-Commit Checks

Before committing code, run:
```bash
# Fast validation
pytest src/tests/unit/
python -m cosa.rest.jwt_service  # Key module smoke test

# Full validation (requires server)
pytest src/tests/
```

### CI/CD Pipeline

Recommended test sequence for CI/CD:
1. **Unit tests** - Fast validation (1-2 seconds)
2. **Smoke tests** - Module validation (5-10 seconds)
3. **Integration tests** - Full validation (5-10 seconds, requires server)
4. **WebSocket tests** - Real-time feature validation (10-20 seconds)

**Total CI runtime**: ~30-45 seconds

---

## Troubleshooting

### Common Issues

**Tests fail with `ModuleNotFoundError`**
- Solution: Run from project root, ensure `PYTHONPATH` includes `src/`

**Integration tests fail with connection errors**
- Solution: Start FastAPI server: `src/scripts/run-fastapi-lupin.sh`

**Database permission errors in integration tests**
- Solution: Close any tools accessing test database

**Async WebSocket test timeouts**
- Solution: Ensure server is running and WebSocket endpoint accessible

### Getting Help

1. Check test output for detailed error messages
2. Review specific test type README:
   - Integration: `src/tests/integration/README.md`
   - Unit: Test files have inline documentation
3. Run with verbose output: `pytest -v -s`
4. Check server logs if integration tests fail

---

## Related Documentation

- **Integration Tests**: `src/tests/integration/README.md`
- **Interactive Proxy Tests**: [`src/docs/automated-interactive-testing.md`](../docs/automated-interactive-testing.md) — Comprehensive proxy testing guide
- **Smoke Tests**: [`src/tests/smoke/README.md`](smoke/README.md) — Quick-start guide for smoke tests
- **JWT Authentication**: `src/rnd/jwt-oauth/README.md`
- **API Documentation**: (Phase 10 - coming soon)
- **Project CLAUDE.md**: Development guidelines and testing section

---

## Test Philosophy

> **"Test the behavior, not the implementation"**

- Focus on what the code does, not how it does it
- Test user-facing functionality
- Validate security and error handling
- Ensure backward compatibility
- Make tests readable and maintainable

---

**Last Updated**: October 2025 (Phase 9 - Integration Tests Added)
