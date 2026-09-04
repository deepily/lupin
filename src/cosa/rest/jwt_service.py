"""
JWT Token Service for Lupin Authentication.

This module provides JWT token generation, validation, and management
using PyJWT library with HS256 algorithm.

Responsibilities:
- Generate access tokens (short-lived, 30 min)
- Generate refresh tokens (long-lived, 7 days)
- Validate token signatures and expiration
- Decode token claims
- Handle token revocation checking
"""

import jwt
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
from cosa.config.configuration_manager import ConfigurationManager

# Initialize configuration
config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

# Load JWT configuration.
#
# There is NO built-in signing secret, in any environment. The previous form raised only
# when ENVIRONMENT == "production" — which no service sets — so every other deployment fell
# through to a fixed string literal committed to this file. A default that is identical in
# every checkout is a shared secret: anyone reading the repository could forge a token for
# any user_id, email and role against any deployment still using it. The two warning prints
# that accompanied it were a hope, not a control; nothing refused to run.
#
# Unset now fails here, before the module finishes importing, so a missing secret is a boot
# failure rather than tokens signed with a value anyone can read. Row adce3547.
def _missing_tree_hint( here=None ):
    """
    Name the missing TREE when the refusal above is really a worktree-provisioning gap.

    THE DEFECT THIS ADDRESSES (row dde8b87a). The repo-root `.env` is gitignored, so it
    is present in the main checkout and absent from EVERY worktree. It carries
    JWT_SECRET_KEY, so `import lupin_app.main` REFUSES at import inside a worktree — and
    the refusal names a missing VARIABLE, which reads as a configuration mistake the
    reader made. It is not: it is a file that `git worktree add` could not have produced.

    🔴 THE FILE IS NOT PROVISIONED AND MUST NOT BE. It also carries POSTGRES_PASSWORD.
    A venv is a build artifact; this is a secret, and the ruling on `src/conf/keys/**`
    (Mr. Radio, 2026-09-01) is the same ruling. So the remedy for this member is a
    message that tells the truth about WHY the variable is absent, not a symlink.

    ⚠️ NO SUBPROCESS, NO CONFIG, NO `LUPIN_ROOT`. This runs during a module import that
    is already failing; anything that can itself fail would replace a clear refusal with
    an obscure one. The repo root comes from this file's own location — the tree that is
    actually running — and a worktree announces itself by having a `.git` FILE rather
    than a directory, whose `gitdir:` line names the main checkout.

    Requires:
        - here is a repo root path, or None to use this file's own tree. The parameter
          exists so the branches below can be driven against real temporary trees; the
          import-time caller never passes it

    Ensures:
        - returns a sentence naming this tree and the main checkout when this is a
          worktree whose `.env` is absent while the main checkout has one
        - returns "" in every other case, including any error — a hint that cannot be
          computed must never turn a legible refusal into a traceback
        - never raises

    Returns:
        str
    """
    try:
        if here is None:
            here = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
        if os.path.exists( os.path.join( here, ".env" ) ): return ""

        git_marker = os.path.join( here, ".git" )
        if not os.path.isfile( git_marker ): return ""          # main checkout, or no repo

        with open( git_marker ) as f: marker = f.read().strip()
        if not marker.startswith( "gitdir:" ): return ""
        # ".../<main>/.git/worktrees/<name>" -> "<main>"
        gitdir = marker.split( ":", 1 )[ 1 ].strip()
        main   = os.path.dirname( os.path.dirname( os.path.dirname( gitdir ) ) )
        if not os.path.exists( os.path.join( main, ".env" ) ): return ""

        return (
            f" THIS IS A MISSING TREE, NOT A MISSING SETTING: you are in the worktree {here}, "
            f"which has no .env because .env is gitignored and `git worktree add` cannot produce one. "
            f"The main checkout {main} has one. It is NOT provisioned into worktrees on purpose — it "
            f"also carries POSTGRES_PASSWORD, and a secret is not a build artifact. Export "
            f"JWT_SECRET_KEY into this shell instead, or run from the main checkout."
        )
    except Exception:
        return ""


def _missing_secret_message( here=None ):
    """
    The whole refusal text: the standing advice, plus the missing-tree hint when one
    applies.

    ⚠️ IT IS A FUNCTION SO THE COMPOSITION CAN BE TESTED. The `raise` below runs at
    module-import time and only when the variable is unset, so under a tier that always
    sets it the line is unreachable — and a test that exercised `_missing_tree_hint`
    alone would pass whether or not the hint ever reaches a reader. A component can be
    correct, covered, and never wired in.

    Requires:
        - here is a repo root path, or None to use this file's own tree

    Ensures:
        - always contains the standing advice, in every tree
        - contains the missing-tree hint iff `_missing_tree_hint` produces one
        - never raises

    Returns:
        str
    """
    return (
        "JWT_SECRET_KEY environment variable must be set — there is no default signing secret. "
        "Set it in the untracked .env / host env file (never a tracked one); generate a value with "
        "python -c \"import secrets; print( secrets.token_urlsafe( 32 ) )\"."
        + _missing_tree_hint( here )
    )


SECRET_KEY = os.getenv( "JWT_SECRET_KEY" )
if not SECRET_KEY:
    raise ValueError( _missing_secret_message() )

ALGORITHM                     = config_mgr.get( "jwt algorithm", "HS256" )
ACCESS_TOKEN_EXPIRE_MINUTES   = config_mgr.get( "jwt access token expire minutes", 30, return_type="int" )
REFRESH_TOKEN_EXPIRE_DAYS     = config_mgr.get( "jwt refresh token expire days", 7, return_type="int" )


def create_access_token( user_id: str, email: str, roles: List[str] ) -> str:
    """
    Generate short-lived JWT access token.

    Requires:
        - user_id is a non-empty system ID string
        - email is a valid email address string
        - roles is a list of role strings (e.g., ["user", "admin"])
        - SECRET_KEY is configured

    Ensures:
        - Returns signed JWT string
        - Token includes sub, email, roles, exp, iat, jti claims
        - Token is valid for configured expiration time
        - Token can be decoded with same SECRET_KEY

    Raises:
        - ValueError if user_id or email is empty
        - jwt.PyJWTError if encoding fails

    Returns:
        str: Encoded JWT token
    """
    if not user_id or not email:
        raise ValueError( "user_id and email are required" )

    # Calculate expiration
    expire = datetime.now( timezone.utc ) + timedelta( minutes=ACCESS_TOKEN_EXPIRE_MINUTES )

    # Build payload
    payload = {
        "sub"   : user_id,
        "email" : email,
        "roles" : roles if roles else ["user"],
        "exp"   : expire,
        "iat"   : datetime.now( timezone.utc ),
        "jti"   : _generate_jti()  # Unique token ID
    }

    # Encode token
    token = jwt.encode( payload, SECRET_KEY, algorithm=ALGORITHM )

    return token


def create_refresh_token( user_id: str, email: str ) -> str:
    """
    Generate long-lived JWT refresh token.

    Requires:
        - user_id is a non-empty system ID string
        - email is a valid email address string
        - SECRET_KEY is configured

    Ensures:
        - Returns signed JWT string
        - Token includes sub, email, exp, iat, jti, token_type claims
        - Token is valid for configured expiration time
        - token_type claim is "refresh" (distinguishes from access tokens)

    Raises:
        - ValueError if user_id or email is empty
        - jwt.PyJWTError if encoding fails

    Returns:
        str: Encoded JWT refresh token
    """
    if not user_id or not email:
        raise ValueError( "user_id and email are required" )

    # Calculate expiration
    expire = datetime.now( timezone.utc ) + timedelta( days=REFRESH_TOKEN_EXPIRE_DAYS )

    # Build payload
    payload = {
        "sub"        : user_id,
        "email"      : email,
        "exp"        : expire,
        "iat"        : datetime.now( timezone.utc ),
        "jti"        : _generate_jti(),
        "token_type" : "refresh"  # Distinguish from access tokens
    }

    # Encode token
    token = jwt.encode( payload, SECRET_KEY, algorithm=ALGORITHM )

    return token


def decode_and_validate_token( token: str, expected_type: Optional[str] = None ) -> Dict:
    """
    Decode and validate JWT token.

    Requires:
        - token is a non-empty JWT string
        - SECRET_KEY matches the key used to sign token
        - expected_type is None, "access", or "refresh"

    Ensures:
        - Token signature is valid
        - Token is not expired
        - Token type matches expected_type (if specified)
        - Returns decoded payload as dictionary

    Raises:
        - jwt.ExpiredSignatureError if token expired
        - jwt.InvalidTokenError if signature invalid
        - ValueError if token_type doesn't match expected_type

    Returns:
        dict: Decoded token payload
    """
    # Decode token (validates signature and expiration automatically)
    payload = jwt.decode( token, SECRET_KEY, algorithms=[ALGORITHM] )

    # Validate token type if specified
    if expected_type:
        token_type = payload.get( "token_type" )

        if expected_type == "access" and token_type == "refresh":
            raise ValueError( "Refresh token cannot be used as access token" )

        if expected_type == "refresh" and token_type != "refresh":
            raise ValueError( "Expected refresh token, got access token" )

    return payload


def _generate_jti() -> str:
    """
    Generate unique JWT ID for token tracking.

    Requires:
        - None

    Ensures:
        - Returns unique identifier string
        - Format: UUID4 (e.g., "7f3a9c2e-4b1d-4f8e-9d6c-1a2b3c4d5e6f")
        - Suitable for database primary key

    Raises:
        - None

    Returns:
        str: Unique token identifier
    """
    import uuid
    return str( uuid.uuid4() )


def quick_smoke_test():
    """
    Quick smoke test for JWT service functionality.

    Requires:
        - jwt library installed
        - SECRET_KEY configured
        - All JWT functions available

    Ensures:
        - Tests access token generation
        - Tests refresh token generation
        - Tests token validation
        - Tests expiration handling
        - Tests invalid token rejection
        - Returns True if all tests pass

    Raises:
        - None (catches all exceptions)
    """
    import cosa.utils.util as du

    du.print_banner( "JWT Service Smoke Test", prepend_nl=True )

    try:
        # Test 1: Access token generation
        print( "Testing access token generation..." )
        access_token = create_access_token(
            user_id = "test_user_123",
            email   = "test@example.com",
            roles   = ["user", "admin"]
        )
        if access_token and len( access_token ) > 100:
            print( f"✓ Access token generated ({len( access_token )} chars)" )
        else:
            print( "✗ Access token generation failed" )
            return False

        # Test 2: Access token validation
        print( "Testing access token validation..." )
        payload = decode_and_validate_token( access_token, expected_type="access" )
        if payload["sub"] == "test_user_123" and payload["email"] == "test@example.com":
            print( "✓ Access token validated correctly" )
        else:
            print( "✗ Access token validation failed" )
            return False

        # Test 3: Refresh token generation
        print( "Testing refresh token generation..." )
        refresh_token = create_refresh_token(
            user_id = "test_user_123",
            email   = "test@example.com"
        )
        if refresh_token and len( refresh_token ) > 100:
            print( f"✓ Refresh token generated ({len( refresh_token )} chars)" )
        else:
            print( "✗ Refresh token generation failed" )
            return False

        # Test 4: Refresh token validation
        print( "Testing refresh token validation..." )
        payload = decode_and_validate_token( refresh_token, expected_type="refresh" )
        if payload["sub"] == "test_user_123" and payload["token_type"] == "refresh":
            print( "✓ Refresh token validated correctly" )
        else:
            print( "✗ Refresh token validation failed" )
            return False

        # Test 5: Invalid token rejection
        print( "Testing invalid token rejection..." )
        try:
            decode_and_validate_token( "invalid.token.string" )
            print( "✗ Invalid token was accepted (security issue!)" )
            return False
        except jwt.InvalidTokenError:
            print( "✓ Invalid token rejected correctly" )

        # Test 6: Expired token detection
        print( "Testing expired token detection..." )
        # Create token that expired in the past
        past_expire = datetime.now( timezone.utc ) - timedelta( minutes=1 )
        expired_payload = {
            "sub"   : "test_user",
            "email" : "test@example.com",
            "exp"   : past_expire,
            "iat"   : datetime.now( timezone.utc ) - timedelta( minutes=2 )
        }
        expired_token = jwt.encode( expired_payload, SECRET_KEY, algorithm=ALGORITHM )

        try:
            decode_and_validate_token( expired_token )
            print( "✗ Expired token was accepted (security issue!)" )
            return False
        except jwt.ExpiredSignatureError:
            print( "✓ Expired token rejected correctly" )

        # Test 7: Token type validation
        print( "Testing token type validation..." )
        try:
            decode_and_validate_token( refresh_token, expected_type="access" )
            print( "✗ Refresh token accepted as access token (security issue!)" )
            return False
        except ValueError:
            print( "✓ Token type validation working" )

        print( "\n✓ All JWT service tests passed!" )
        return True

    except Exception as e:
        print( f"✗ JWT service test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()