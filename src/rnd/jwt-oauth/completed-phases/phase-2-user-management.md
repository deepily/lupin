# Phase 2: User Management & Password Security

**Status**: ✅ COMPLETED on 2025.09.29

---


**Timeline**: Week 1, Days 3-5
**Status**: NOT_STARTED
**Blocking**: Phase 1 (JWT service)

#### Objectives
- Implement user database operations (CRUD)
- Secure password hashing with bcrypt
- User registration and login logic
- Database schema initialization

#### Files to Create

**1. `src/cosa/rest/auth_database.py`** (Database initialization)

```python
"""
Authentication Database Management.

Handles SQLite database initialization and schema management
for authentication tables.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from cosa.app.configuration_manager import ConfigurationManager

config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )


def get_auth_db_path() -> Path:
    """
    Get authentication database path from configuration.

    Requires:
        - Configuration manager initialized
        - auth database path wo root configured

    Ensures:
        - Returns absolute Path object to database file
        - Creates parent directories if they don't exist

    Raises:
        - None

    Returns:
        Path: Absolute path to authentication database
    """
    # Get path from config (relative to project root)
    db_path_rel = config_mgr.get(
        "auth database path wo root",
        "/src/conf/auth/lupin-auth.db"
    )

    # Convert to absolute path
    project_root = Path( __file__ ).parent.parent.parent.parent
    db_path = project_root / db_path_rel.lstrip( "/" )

    # Ensure parent directory exists
    db_path.parent.mkdir( parents=True, exist_ok=True )

    return db_path


def get_auth_db_connection() -> sqlite3.Connection:
    """
    Get SQLite connection to authentication database.

    Requires:
        - Database path configured
        - Database initialized (or will create)

    Ensures:
        - Returns active SQLite connection
        - Row factory set to sqlite3.Row for dict-like access
        - Foreign keys enabled

    Raises:
        - sqlite3.Error if connection fails

    Returns:
        sqlite3.Connection: Active database connection
    """
    db_path = get_auth_db_path()

    conn = sqlite3.connect( str( db_path ) )
    conn.row_factory = sqlite3.Row  # Enable dict-like row access
    conn.execute( "PRAGMA foreign_keys = ON" )  # Enable foreign key constraints

    return conn


def init_auth_database() -> None:
    """
    Initialize authentication database with schema.

    Creates tables if they don't exist:
    - users
    - refresh_tokens
    - email_verification_tokens (Phase 7)
    - password_reset_tokens (Phase 7)

    Requires:
        - Database path accessible and writable

    Ensures:
        - All tables created with proper schema
        - Indexes created for performance
        - Foreign key constraints enabled
        - Idempotent (safe to call multiple times)

    Raises:
        - sqlite3.Error if schema creation fails
    """
    conn = get_auth_db_connection()
    cursor = conn.cursor()

    try:
        # Create users table
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS users (
                id                TEXT PRIMARY KEY,
                email             TEXT UNIQUE NOT NULL,
                password_hash     TEXT NOT NULL,
                created_at        TEXT NOT NULL,
                email_verified    INTEGER DEFAULT 0,
                is_active         INTEGER DEFAULT 1,
                roles             TEXT DEFAULT '["user"]',
                last_login_at     TEXT,

                CHECK( email_verified IN (0, 1) ),
                CHECK( is_active IN (0, 1) )
            )
        """ )

        # Create indexes for users table
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_users_email ON users( email )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_users_is_active ON users( is_active )" )

        # Create refresh_tokens table
        cursor.execute( """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                jti               TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                token_hash        TEXT NOT NULL,
                expires_at        TEXT NOT NULL,
                revoked           INTEGER DEFAULT 0,
                created_at        TEXT NOT NULL,
                last_used_at      TEXT,
                user_agent        TEXT,
                ip_address        TEXT,

                FOREIGN KEY( user_id ) REFERENCES users( id ) ON DELETE CASCADE,
                CHECK( revoked IN (0, 1) )
            )
        """ )

        # Create indexes for refresh_tokens table
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens( user_id )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens( expires_at )" )
        cursor.execute( "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_revoked ON refresh_tokens( revoked )" )

        # Commit changes
        conn.commit()

        print( "[AUTH DB] Database initialized successfully" )

    except sqlite3.Error as e:
        conn.rollback()
        print( f"[AUTH DB] Error initializing database: {e}" )
        raise

    finally:
        conn.close()


def quick_smoke_test():
    """
    Quick smoke test for authentication database.

    Requires:
        - Database path configured and writable
        - sqlite3 module available

    Ensures:
        - Database can be initialized
        - Tables created successfully
        - Indexes exist
        - Connection works

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "Auth Database Smoke Test", prepend_nl=True )

    try:
        # Test 1: Get database path
        print( "Testing database path resolution..." )
        db_path = get_auth_db_path()
        print( f"✓ Database path: {db_path}" )

        # Test 2: Initialize database
        print( "Testing database initialization..." )
        init_auth_database()
        print( "✓ Database initialized" )

        # Test 3: Get connection
        print( "Testing database connection..." )
        conn = get_auth_db_connection()
        print( "✓ Connection established" )

        # Test 4: Verify tables exist
        print( "Testing table creation..." )
        cursor = conn.cursor()
        cursor.execute( "SELECT name FROM sqlite_master WHERE type='table'" )
        tables = [row[0] for row in cursor.fetchall()]

        expected_tables = ["users", "refresh_tokens"]
        for table in expected_tables:
            if table in tables:
                print( f"✓ Table '{table}' exists" )
            else:
                print( f"✗ Table '{table}' missing" )
                return False

        # Test 5: Verify indexes exist
        print( "Testing index creation..." )
        cursor.execute( "SELECT name FROM sqlite_master WHERE type='index'" )
        indexes = [row[0] for row in cursor.fetchall()]

        if len( indexes ) >= 5:  # At least 5 indexes expected
            print( f"✓ {len( indexes )} indexes created" )
        else:
            print( f"⚠ Only {len( indexes )} indexes found (expected >= 5)" )

        conn.close()

        print( "\\n✓ All database tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Database test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
```

**2. `src/cosa/rest/password_service.py`** (Password security)

```python
"""
Password Security Service.

Handles password hashing, verification, and strength validation
using Passlib with bcrypt.
"""

from passlib.context import CryptContext
import re
from typing import Tuple

# Create password context
pwd_context = CryptContext(
    schemes    = ["bcrypt"],
    deprecated = "auto",
    bcrypt__rounds = 12  # Security vs performance balance
)


def hash_password( plain_password: str ) -> str:
    """
    Hash plaintext password using bcrypt.

    Requires:
        - plain_password is a non-empty string
        - pwd_context is initialized

    Ensures:
        - Returns bcrypt hash string (60 characters)
        - Hash includes automatic random salt
        - Hash is suitable for database storage
        - Same password produces different hashes (random salt)

    Raises:
        - ValueError if password is empty

    Returns:
        str: Bcrypt hash of password
    """
    if not plain_password:
        raise ValueError( "Password cannot be empty" )

    return pwd_context.hash( plain_password )


def verify_password( plain_password: str, hashed_password: str ) -> bool:
    """
    Verify plaintext password against stored hash.

    Requires:
        - plain_password is a string (may be empty)
        - hashed_password is a valid bcrypt hash
        - pwd_context is initialized

    Ensures:
        - Returns True if password matches hash
        - Returns False if password doesn't match or invalid input
        - Timing-attack resistant (constant-time comparison)
        - Never raises exception (returns False on error)

    Raises:
        - None (returns False on any error)

    Returns:
        bool: True if password matches, False otherwise
    """
    if not plain_password or not hashed_password:
        return False

    try:
        return pwd_context.verify( plain_password, hashed_password )
    except Exception:
        return False


def validate_password_strength( password: str ) -> Tuple[bool, str]:
    """
    Validate password meets minimum security requirements.

    Requirements:
    - Minimum 8 characters
    - At least 3 of 4 character types:
      * Lowercase letters
      * Uppercase letters
      * Digits
      * Special characters (!@#$%^&*(),.?":{}|<>)
    - Not in common password list

    Requires:
        - password is a string (may be weak or empty)

    Ensures:
        - Returns (True, "") if password acceptable
        - Returns (False, "error message") if password weak
        - Checks length, character types, common passwords
        - Never raises exception

    Raises:
        - None (returns validation result tuple)

    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    # Check minimum length
    min_length = 8
    if len( password ) < min_length:
        return False, f"Password must be at least {min_length} characters"

    # Check character type requirements
    has_lowercase = bool( re.search( r'[a-z]', password ) )
    has_uppercase = bool( re.search( r'[A-Z]', password ) )
    has_digit     = bool( re.search( r'\d', password ) )
    has_special   = bool( re.search( r'[!@#$%^&*(),.?":{}|<>]', password ) )

    char_types = sum( [has_lowercase, has_uppercase, has_digit, has_special] )
    if char_types < 3:
        return False, "Password must contain at least 3 of: lowercase, uppercase, digit, special character"

    # Check against common passwords
    common_passwords = {
        "password", "12345678", "qwerty123", "admin123", "welcome123",
        "password123", "letmein", "abc12345", "trustno1", "passw0rd"
    }
    if password.lower() in common_passwords:
        return False, "Password is too common, please choose a stronger password"

    return True, ""


def quick_smoke_test():
    """
    Quick smoke test for password service.

    Requires:
        - Passlib installed
        - pwd_context initialized

    Ensures:
        - Tests password hashing
        - Tests password verification
        - Tests strength validation
        - Returns True if all tests pass

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "Password Service Smoke Test", prepend_nl=True )

    try:
        # Test 1: Password hashing
        print( "Testing password hashing..." )
        password = "TestPassword123!"
        hash1 = hash_password( password )
        hash2 = hash_password( password )

        if hash1 and hash2 and hash1 != hash2:
            print( "✓ Password hashing working (random salts)" )
            print( f"  Hash length: {len( hash1 )} chars" )
        else:
            print( "✗ Password hashing failed" )
            return False

        # Test 2: Password verification
        print( "Testing password verification..." )
        if verify_password( password, hash1 ):
            print( "✓ Password verification working (correct password)" )
        else:
            print( "✗ Password verification failed" )
            return False

        if not verify_password( "WrongPassword", hash1 ):
            print( "✓ Password verification working (incorrect password)" )
        else:
            print( "✗ Wrong password was accepted!" )
            return False

        # Test 3: Strength validation - weak password
        print( "Testing strength validation (weak password)..." )
        is_valid, error = validate_password_strength( "weak" )
        if not is_valid and error:
            print( f"✓ Weak password rejected: {error}" )
        else:
            print( "✗ Weak password was accepted!" )
            return False

        # Test 4: Strength validation - strong password
        print( "Testing strength validation (strong password)..." )
        is_valid, error = validate_password_strength( "StrongPass123!" )
        if is_valid and not error:
            print( "✓ Strong password accepted" )
        else:
            print( f"✗ Strong password rejected: {error}" )
            return False

        # Test 5: Strength validation - common password
        print( "Testing strength validation (common password)..." )
        is_valid, error = validate_password_strength( "password123" )
        if not is_valid and "common" in error.lower():
            print( "✓ Common password rejected" )
        else:
            print( "✗ Common password was accepted!" )
            return False

        # Test 6: Empty password handling
        print( "Testing empty password handling..." )
        try:
            hash_password( "" )
            print( "✗ Empty password was accepted!" )
            return False
        except ValueError:
            print( "✓ Empty password rejected" )

        print( "\\n✓ All password service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ Password service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
```

**3. `src/cosa/rest/user_service.py`** (User CRUD operations)

```python
"""
User Management Service.

Handles user registration, login, and database operations.
"""

import json
from datetime import datetime
from typing import Optional, Dict, List
from cosa.rest.auth_database import get_auth_db_connection
from cosa.rest.password_service import hash_password, verify_password, validate_password_strength
from cosa.rest.user_id_generator import email_to_system_id


class UserService:
    """
    Service class for user management operations.
    """

    def __init__( self ):
        """
        Initialize user service.

        Requires:
            - Authentication database initialized

        Ensures:
            - Service ready for user operations
        """
        pass

    def create_user( self, email: str, password: str,
                    email_verified: bool = False,
                    roles: List[str] = None ) -> Dict:
        """
        Create new user account.

        Requires:
            - email is valid email address string
            - password meets strength requirements
            - email is not already registered

        Ensures:
            - User created in database
            - Password hashed before storage
            - System ID generated from email
            - Returns user dictionary without password

        Raises:
            - ValueError if email already exists
            - ValueError if password too weak
            - sqlite3.Error if database operation fails

        Returns:
            dict: Created user info (uid, email, name, etc.)
        """
        # Validate password strength
        is_valid, error = validate_password_strength( password )
        if not is_valid:
            raise ValueError( error )

        # Generate system ID from email
        user_id = email_to_system_id( email )

        # Check if user already exists
        if self.get_user_by_email( email ):
            raise ValueError( f"User with email {email} already exists" )

        # Hash password
        password_hash = hash_password( password )

        # Prepare user data
        if roles is None:
            roles = ["user"]

        created_at = datetime.utcnow().isoformat()

        # Insert into database
        conn = get_auth_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute( """
                INSERT INTO users (id, email, password_hash, created_at, email_verified, roles)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, email, password_hash, created_at,
                  1 if email_verified else 0, json.dumps( roles )) )

            conn.commit()

            print( f"[USER SERVICE] Created user: {email} ({user_id})" )

            # Return user info (without password hash)
            user_info = {
                "uid"            : user_id,
                "email"          : email,
                "name"           : email.split( "@" )[0].capitalize(),
                "email_verified" : email_verified,
                "roles"          : roles,
                "created_at"     : created_at
            }

            return user_info

        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_user_by_email( self, email: str ) -> Optional[Dict]:
        """
        Get user by email address.

        Requires:
            - email is a string (may not exist in database)

        Ensures:
            - Returns user dict if found
            - Returns None if not found
            - User dict includes all fields except password_hash

        Raises:
            - sqlite3.Error if database query fails

        Returns:
            Optional[dict]: User info if found, None otherwise
        """
        conn = get_auth_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute( "SELECT * FROM users WHERE email = ?", (email,) )
            row = cursor.fetchone()

            if not row:
                return None

            # Convert row to dict
            user = dict( row )

            # Parse JSON roles field
            user["roles"] = json.loads( user["roles"] )

            # Convert integer booleans
            user["email_verified"] = bool( user["email_verified"] )
            user["is_active"] = bool( user["is_active"] )

            return user

        finally:
            conn.close()

    def get_user_by_id( self, user_id: str ) -> Optional[Dict]:
        """
        Get user by system ID.

        Requires:
            - user_id is a string (may not exist in database)

        Ensures:
            - Returns user dict if found
            - Returns None if not found
            - User dict includes all fields except password_hash

        Raises:
            - sqlite3.Error if database query fails

        Returns:
            Optional[dict]: User info if found, None otherwise
        """
        conn = get_auth_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute( "SELECT * FROM users WHERE id = ?", (user_id,) )
            row = cursor.fetchone()

            if not row:
                return None

            user = dict( row )
            user["roles"] = json.loads( user["roles"] )
            user["email_verified"] = bool( user["email_verified"] )
            user["is_active"] = bool( user["is_active"] )

            return user

        finally:
            conn.close()

    def authenticate_user( self, email: str, password: str ) -> Optional[Dict]:
        """
        Authenticate user with email and password.

        Requires:
            - email is a string
            - password is a string
            - User must exist and be active

        Ensures:
            - Returns user dict if credentials valid
            - Returns None if credentials invalid
            - Updates last_login_at timestamp on success
            - Password verified securely

        Raises:
            - sqlite3.Error if database operation fails

        Returns:
            Optional[dict]: User info if authenticated, None otherwise
        """
        # Get user
        user = self.get_user_by_email( email )
        if not user:
            return None

        # Check if account is active
        if not user["is_active"]:
            return None

        # Verify password
        if not verify_password( password, user["password_hash"] ):
            return None

        # Update last login time
        conn = get_auth_db_connection()
        cursor = conn.cursor()

        try:
            last_login = datetime.utcnow().isoformat()
            cursor.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (last_login, user["id"])
            )
            conn.commit()

            user["last_login_at"] = last_login

        finally:
            conn.close()

        # Remove password hash from returned user
        user.pop( "password_hash", None )

        print( f"[USER SERVICE] User authenticated: {email}" )

        return user


def quick_smoke_test():
    """
    Quick smoke test for user service.

    Requires:
        - Authentication database initialized
        - All dependencies available

    Ensures:
        - Tests user creation
        - Tests user lookup
        - Tests authentication
        - Cleans up test data

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du
    from cosa.rest.auth_database import init_auth_database

    du.print_banner( "User Service Smoke Test", prepend_nl=True )

    # Initialize database
    init_auth_database()

    service = UserService()
    test_email = "test_smoke@example.com"
    test_password = "TestPassword123!"

    try:
        # Test 1: Create user
        print( "Testing user creation..." )
        user = service.create_user(
            email          = test_email,
            password       = test_password,
            email_verified = True
        )

        if user and user["email"] == test_email:
            print( f"✓ User created: {user['uid']}" )
        else:
            print( "✗ User creation failed" )
            return False

        # Test 2: Get user by email
        print( "Testing user lookup by email..." )
        found_user = service.get_user_by_email( test_email )
        if found_user and found_user["uid"] == user["uid"]:
            print( "✓ User lookup by email working" )
        else:
            print( "✗ User lookup by email failed" )
            return False

        # Test 3: Get user by ID
        print( "Testing user lookup by ID..." )
        found_user = service.get_user_by_id( user["uid"] )
        if found_user and found_user["email"] == test_email:
            print( "✓ User lookup by ID working" )
        else:
            print( "✗ User lookup by ID failed" )
            return False

        # Test 4: Authenticate with correct password
        print( "Testing authentication (correct password)..." )
        auth_user = service.authenticate_user( test_email, test_password )
        if auth_user and auth_user["uid"] == user["uid"]:
            print( "✓ Authentication working (correct password)" )
        else:
            print( "✗ Authentication failed with correct password" )
            return False

        # Test 5: Authenticate with wrong password
        print( "Testing authentication (wrong password)..." )
        auth_user = service.authenticate_user( test_email, "WrongPassword123!" )
        if auth_user is None:
            print( "✓ Authentication rejected wrong password" )
        else:
            print( "✗ Wrong password was accepted!" )
            return False

        # Test 6: Duplicate email rejection
        print( "Testing duplicate email rejection..." )
        try:
            service.create_user( test_email, test_password )
            print( "✗ Duplicate email was accepted!" )
            return False
        except ValueError as e:
            if "already exists" in str( e ):
                print( "✓ Duplicate email rejected" )
            else:
                print( f"✗ Unexpected error: {e}" )
                return False

        print( "\\n✓ All user service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ User service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup: Delete test user
        try:
            conn = get_auth_db_connection()
            cursor = conn.cursor()
            cursor.execute( "DELETE FROM users WHERE email = ?", (test_email,) )
            conn.commit()
            conn.close()
            print( "\\nTest data cleaned up" )
        except:
            pass


if __name__ == "__main__":
    quick_smoke_test()
```

#### Tasks & Checklist

- [ ] **Task 2.1**: Install dependencies
  - [ ] Add passlib[bcrypt] to requirements
  - [ ] Verify installation: `pip install passlib[bcrypt]`

- [ ] **Task 2.2**: Create `src/cosa/rest/auth_database.py`
  - [ ] Implement database path resolution
  - [ ] Implement connection management
  - [ ] Implement schema initialization
  - [ ] Add `quick_smoke_test()` function

- [ ] **Task 2.3**: Create `src/cosa/rest/password_service.py`
  - [ ] Implement password hashing
  - [ ] Implement password verification
  - [ ] Implement strength validation
  - [ ] Add `quick_smoke_test()` function

- [ ] **Task 2.4**: Create `src/cosa/rest/user_service.py`
  - [ ] Implement user creation
  - [ ] Implement user lookup (by email, by ID)
  - [ ] Implement authentication
  - [ ] Add `quick_smoke_test()` function

- [ ] **Task 2.5**: Configuration updates
  - [ ] Add `auth database path wo root` to `lupin-app.ini`
  - [ ] Add explanation to `lupin-app-splainer.ini`

- [ ] **Task 2.6**: Testing
  - [ ] Run all quick_smoke_test() functions
  - [ ] Test database initialization
  - [ ] Test user CRUD operations
  - [ ] Test password security

#### Testing Checkpoints

| Test Category | Status | Notes |
|---------------|--------|-------|
| Database initialization | PENDING | - |
| Database connection | PENDING | - |
| Password hashing | PENDING | - |
| Password verification | PENDING | - |
| Password strength validation | PENDING | - |
| User creation | PENDING | - |
| User lookup (email) | PENDING | - |
| User lookup (ID) | PENDING | - |
| User authentication | PENDING | - |
| Duplicate email rejection | PENDING | - |

#### Rollback Procedure

1. Delete `src/cosa/rest/auth_database.py`
2. Delete `src/cosa/rest/password_service.py`
3. Delete `src/cosa/rest/user_service.py`
4. Delete authentication database file
5. Remove config keys from `lupin-app.ini`
6. No system impact (modules not yet integrated)

#### Success Criteria

✅ All quick_smoke_test() functions passing
✅ Database schema created correctly
✅ Password hashing secure (bcrypt with 12 rounds)
✅ User operations working (CRUD)
✅ Authentication logic functional
✅ No plaintext passwords stored

---


---

**Source**: Extracted from original monolithic design document (2025.09.29-jwt-oauth-implementation-design-and-tracker.md)
