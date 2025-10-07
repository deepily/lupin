# Authentication System - New Python Package Requirements

## Packages Installed for JWT/OAuth Authentication System

### Phase 1: JWT Service Foundation
1. **PyJWT==2.10.1**
   - Purpose: JWT token generation, validation, and management
   - Used in: `src/cosa/rest/jwt_service.py`
   - Installation: `pip install PyJWT`

### Phase 2: Password Security
2. **passlib==1.7.4**
   - Purpose: Secure password hashing with bcrypt
   - Used in: `src/cosa/rest/password_service.py`
   - Installation: `pip install "passlib[bcrypt]"`
   - Dependencies: bcrypt==3.2.2 (compatibility with passlib), cffi==2.0.0, pycparser==2.23

## Docker Requirements.txt Updates

Add the following lines to your Docker requirements.txt:

```
# JWT Authentication System
PyJWT==2.10.1
passlib==1.7.4
bcrypt==3.2.2
cffi==2.0.0
pycparser==2.23
```

## Verification Commands

```bash
# Verify PyJWT installation
python -c "import jwt; print(jwt.__version__)"

# Verify passlib installation (after Phase 2)
python -c "from passlib.context import CryptContext; print('passlib OK')"
```

## Dependencies Summary

| Package | Version | Purpose | Phase |
|---------|---------|---------|-------|
| PyJWT | 2.10.1 | JWT tokens | Phase 1 ✅ |
| passlib | 1.7.4 | Password hashing framework | Phase 2 ✅ |
| bcrypt | 3.2.2 | Bcrypt algorithm (passlib compatibility) | Phase 2 ✅ |
| cffi | 2.0.0 | C Foreign Function Interface (bcrypt dependency) | Phase 2 ✅ |
| pycparser | 2.23 | C parser (cffi dependency) | Phase 2 ✅ |

## Testing Dependencies

**File**: `requirements-test.txt` (project root)

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | 8.4.2 | Testing framework |
| pytest-asyncio | 1.2.0 | Async test support (WebSocket tests) |
| pytest-cov | >=2.12.0 | Coverage reporting (optional) |
| websockets | >=15.0.1 | WebSocket client for integration tests |
| requests | >=2.32.3 | HTTP client for API integration tests |

### Installation

```bash
# Install main dependencies
pip install -r src/cosa/requirements.txt

# Install test dependencies
pip install -r requirements-test.txt
```

### Running Tests

```bash
# Run all integration tests
python -m pytest src/tests/integration/

# Run with verbose output
python -m pytest -v src/tests/integration/

# Run with coverage
python -m pytest --cov=cosa.rest --cov-report=html src/tests/integration/
```

**Note**: Always use `python -m pytest` instead of just `pytest` to ensure the correct virtual environment is used.

Last updated: 2025.10.03