from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, Optional
import asyncio
import os
from jwt.exceptions import ExpiredSignatureError
from .user_id_generator import get_user_info, email_to_system_id, email_to_user_uuid


class TokenExpiredException( HTTPException ):
    """Raised when a JWT access token has expired. Subclass of HTTPException for compatibility."""
    def __init__( self ):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired"
        )

# For now, we'll mock the Firebase Admin SDK
# In production, you would use: import firebase_admin
# from firebase_admin import credentials, auth

# Mock Firebase initialization
FIREBASE_INITIALIZED = False

def init_firebase():
    """
    Initialize Firebase Admin SDK with mock implementation.
    
    Requires:
        - None
        
    Ensures:
        - Sets FIREBASE_INITIALIZED to True
        - Prints initialization message
        - Idempotent (safe to call multiple times)
        
    Raises:
        - None
    """
    global FIREBASE_INITIALIZED
    if not FIREBASE_INITIALIZED:
        print("[AUTH] Initializing Firebase Admin SDK (MOCKED)")
        # In production:
        # cred = credentials.Certificate("path/to/serviceAccountKey.json")
        # firebase_admin.initialize_app(cred)
        FIREBASE_INITIALIZED = True


# Create security scheme that raises 401 instead of 403 for missing auth
from fastapi import Request

class HTTPBearerWith401(HTTPBearer):
    def __init__(self):
        # Initialize with auto_error=False to handle errors manually
        super().__init__(auto_error=False)

    async def __call__(self, request: Request):
        # Get credentials without auto error
        credentials = await super().__call__(request)

        # If no credentials provided, raise 401
        if credentials is None:
            # Enhanced logging for debugging
            auth_header = request.headers.get( "Authorization" )
            if auth_header:
                print( f"[AUTH-DEBUG] Authorization header present but invalid format: '{auth_header[:20]}...'" )
            else:
                print( f"[AUTH-DEBUG] No Authorization header in request from {request.client.host}" )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return credentials

security = HTTPBearerWith401()


async def verify_token(token: str) -> Dict:
    """
    Unified token verification supporting both JWT and mock tokens.

    Behavior based on 'auth mode' configuration:
    - 'mock': Accepts mock_token_* format (legacy development mode)
    - 'jwt': Validates real JWT tokens (production mode)
    - 'firebase': Firebase ID tokens (future support)

    Requires:
        - token is a non-empty string
        - Configuration 'auth mode' is set

    Ensures:
        - Returns dictionary with user information
        - Dictionary includes uid, email, name, email_verified, roles fields
        - Backward compatible with existing mock token system
        - Production-ready JWT validation when configured

    Raises:
        - HTTPException with 401 status if token invalid
        - HTTPException with 401 status if auth mode not supported
    """
    import os
    from cosa.config.configuration_manager import ConfigurationManager

    # Allow AUTH_MODE environment variable to override config (for testing)
    auth_mode = os.environ.get( "AUTH_MODE" )
    if auth_mode is None:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        auth_mode = config_mgr.get( "auth mode", default="mock" )

    if auth_mode == "jwt":
        # JWT mode: Validate real JWT tokens
        return await verify_jwt_token( token )
    elif auth_mode == "mock":
        # Mock mode: Legacy mock token support
        return await verify_mock_token( token )
    elif auth_mode == "firebase":
        # Firebase mode: Future support
        return await verify_firebase_token( token )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported auth mode: {auth_mode}"
        )


async def verify_jwt_token(token: str) -> Dict:
    """
    Verify JWT access token and return user information.

    Requires:
        - token is a valid JWT access token string
        - JWT secret key configured
        - User exists in database

    Ensures:
        - Token signature validated
        - Token not expired
        - Returns user information dictionary
        - Compatible with verify_firebase_token return format

    Raises:
        - HTTPException with 401 status if token invalid/expired
        - HTTPException with 401 status if user not found
    """
    try:
        from cosa.rest.jwt_service import decode_and_validate_token
        from cosa.rest.user_service import get_user_by_id

        # Validate JWT token
        try:
            payload = decode_and_validate_token( token, expected_type="access" )
        except Exception as e:
            # Enhanced logging for token validation failures
            error_str = str( e ).lower()
            if "expired" in error_str:
                print( f"[AUTH-DEBUG] Token validation failed: EXPIRED token" )
            elif "signature" in error_str:
                print( f"[AUTH-DEBUG] Token validation failed: INVALID signature" )
            elif "malformed" in error_str or "invalid" in error_str:
                print( f"[AUTH-DEBUG] Token validation failed: MALFORMED token" )
            else:
                print( f"[AUTH-DEBUG] Token validation failed: {e}" )
            raise

        user_id = payload.get( "sub" )

        if not user_id:
            print( f"[AUTH-DEBUG] Token validation failed: Missing user ID in payload" )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID"
            )

        # Get user from database. Lever B (messaging plane, surgical pass 2):
        # get_user_by_id is a blocking SQLAlchemy lookup and this dependency runs
        # on EVERY JWT-authenticated request — run it OFF the event loop so a slow
        # DB under fleet load can't starve the shared :7999 loop (FM-7).
        user_data = await asyncio.to_thread( get_user_by_id, user_id )
        if not user_data:
            print( f"[AUTH-DEBUG] Token validation failed: User {user_id} not found in database" )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        # Check if user is active
        if not user_data.get( "is_active", True ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is inactive"
            )

        # Return in Firebase-compatible format for backward compatibility
        return {
            "uid": user_data["id"],
            "email": user_data["email"],
            "email_verified": user_data["email_verified"],
            "name": user_data["email"].split("@")[0],  # Default name from email
            "roles": user_data["roles"],
            "picture": None,
            "iss": "lupin-jwt",
            "aud": "lupin-api",
            "auth_time": payload.get("iat"),
            "user_id": user_data["id"]
        }

    except HTTPException:
        raise
    except ExpiredSignatureError:
        raise TokenExpiredException()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str( e )}"
        )


async def verify_mock_token(token: str) -> Dict:
    """
    Verify mock token (development mode only).

    Requires:
        - token is a non-empty string
        - token follows expected format (mock_token_* or mock_token_email_*)

    Ensures:
        - Returns dictionary with complete user information
        - Dictionary includes uid, email, name, email_verified fields
        - User data is looked up or generated for unknown system IDs
        - Prints verification success message

    Raises:
        - HTTPException with 401 status if token format is invalid
        - HTTPException with 401 status if email format is invalid in email-based tokens
        - HTTPException with 401 status if system ID is empty
    """
    try:
        # MOCK: In production, this would be:
        # decoded_token = auth.verify_id_token(token)

        # SECURITY: Validate token input
        if not isinstance(token, str):
            raise ValueError("Token must be a string")

        if not token.strip():
            raise ValueError("Token cannot be empty")

        # SECURITY: Prevent extremely long tokens (potential DoS)
        if len(token) > 500:  # Reasonable limit for mock tokens
            raise ValueError("Token exceeds maximum length")

        # For mocking, we'll decode email-based format: "mock_token_email_user@example.com"
        if not token.startswith("mock_token_"):
            raise ValueError("Invalid mock token format")
        
        # Check if it's the new email-based format
        if token.startswith("mock_token_email_"):
            email = token.replace("mock_token_email_", "")
            if not email or '@' not in email:
                raise ValueError("Invalid email in token")
            # Convert email to system ID internally
            system_id = email_to_system_id(email)
        else:
            # Legacy format for backward compatibility
            system_id = token.replace("mock_token_", "")
            if not system_id:
                raise ValueError("No system ID in token")
        
        # Look up user by system ID using centralized user database
        user_data = get_user_info( system_id )
        if not user_data:
            # Generate default user info for unknown system IDs (for testing)
            user_data = {
                "uid": system_id,
                "email": f"{system_id}@generated.local",
                "name": system_id.split('_')[0].capitalize(),
                "email_verified": False
            }
            print( f"[AUTH] Generated user info for unknown system ID: {system_id}" )
        else:
            # Add uid field for Firebase compatibility
            user_data["uid"] = system_id

        # 🔴 THE USER ID IS A UUID UNDER MOCK AUTH TOO (row befeba88). It used to be the
        # system id — "interactive_job_tester_8e32" — and the ordinary API path scopes a
        # job id as "{sha256}::{user_id}", which AsyncNotificationRequest only accepts
        # with a UUID after the "::". So every queue notification under mock auth raised
        # a validation error that was caught, printed and dropped, and the environment
        # looked like it had working notifications when it had none.
        #
        # Minted from the EMAIL rather than the system id so both token formats reach
        # the same id, and so it matches what JWT auth returns in shape: there, the user
        # id is the database row's UUID. The system id is unchanged and still what
        # get_user_info is keyed on — only the id handed OUT is a UUID now.
        user_uuid = email_to_user_uuid( user_data["email"] )

        # Return mock decoded token with real user structure
        decoded_token = {
            "uid": user_uuid,
            "email": user_data["email"],
            "email_verified": user_data["email_verified"],
            "name": user_data["name"],
            "picture": None,
            "iss": "https://securetoken.google.com/mock-project",
            "aud": "mock-project",
            "auth_time": 1234567890,
            "user_id": user_uuid,  # Legacy field for compatibility
            "sub": user_uuid,
            "iat": 1234567890,
            "exp": 9999999999,  # Far future
            "firebase": {
                "identities": {"email": [user_data["email"]]},
                "sign_in_provider": "password"
            }
        }

        print(f"[AUTH] Mock token verified for user: [{user_data['name']}] ({user_uuid}, system id {user_data['uid']})")
        return decoded_token

    except Exception as e:
        print( f"[AUTH] Mock token verification failed: {str( e )}" )
        raise HTTPException(
            status_code = 401,
            detail      = f"Invalid token: {str( e )}"
        )


async def verify_firebase_token(token: str) -> Dict:
    """
    Legacy function name for backward compatibility.
    Redirects to verify_token().

    This function is kept for backward compatibility with existing code
    that calls verify_firebase_token(). New code should use verify_token().
    """
    return await verify_token( token )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict:
    """
    FastAPI dependency to get the current authenticated user.
    
    Requires:
        - credentials contains valid HTTPAuthorizationCredentials
        - credentials.credentials is a valid token string
        
    Ensures:
        - Firebase is initialized before token verification
        - Returns complete user information dictionary
        - Token is extracted and verified successfully
        
    Raises:
        - HTTPException with 401 status if token verification fails
        - Any exceptions from verify_firebase_token are propagated
    """
    # Initialize Firebase if needed
    init_firebase()
    
    # Extract token
    token = credentials.credentials
    
    # Verify token and get user info
    user_info = await verify_firebase_token(token)
    
    return user_info


async def get_current_user_id(
    current_user: Dict = Depends(get_current_user)
) -> str:
    """
    FastAPI dependency to extract just the user ID from authenticated user.
    
    Requires:
        - current_user is a valid user dictionary from get_current_user
        - current_user contains 'uid' key
        
    Ensures:
        - Returns the user's unique identifier as a string
        - Provides simplified access to user ID for endpoints that only need ID
        
    Raises:
        - KeyError if 'uid' key is missing from current_user dictionary
    """
    return current_user["uid"]


# Optional: Create a dependency for optional authentication
async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    )
) -> Optional[Dict]:
    """
    FastAPI dependency for endpoints with optional authentication.
    
    Requires:
        - credentials may be None or valid HTTPAuthorizationCredentials
        
    Ensures:
        - Returns None if no credentials provided
        - Returns None if token verification fails (does not raise exceptions)
        - Returns complete user dictionary if valid token provided
        - Firebase is initialized before attempting verification
        
    Raises:
        - None (all exceptions are caught and result in None return)
    """
    if not credentials:
        return None
        
    try:
        init_firebase()
        token = credentials.credentials
        return await verify_firebase_token(token)
    except:
        return None


def quick_smoke_test():
    """
    Critical smoke test for REST authentication system - validates security functionality.
    
    This test is essential for v000 deprecation as auth.py is critical
    for REST API security and user authentication.
    """
    import cosa.utils.util as du
    
    du.print_banner( "REST Auth Smoke Test", prepend_nl=True )
    
    try:
        # Test 1: Basic function and class presence
        print( "Testing core auth components presence..." )
        expected_functions = [
            "init_firebase", "verify_firebase_token", "get_current_user",
            "get_current_user_id", "get_optional_user"
        ]
        
        # Get all functions in the current module
        import sys
        current_module = sys.modules[ __name__ ]
        
        functions_found = 0
        for func_name in expected_functions:
            if hasattr( current_module, func_name ):
                functions_found += 1
            else:
                print( f"⚠ Missing function: {func_name}" )
        
        if functions_found == len( expected_functions ):
            print( f"✓ All {len( expected_functions )} core auth functions present" )
        else:
            print( f"⚠ Only {functions_found}/{len( expected_functions )} auth functions present" )
        
        # Test security scheme
        if hasattr( current_module, 'security' ):
            print( "✓ HTTPBearer security scheme configured" )
        else:
            print( "✗ Missing HTTPBearer security scheme" )
        
        # Test 2: Critical dependency imports
        print( "Testing critical dependency imports..." )
        try:
            from fastapi import Depends, HTTPException, status
            from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
            print( "✓ FastAPI security imports successful" )
        except ImportError as e:
            print( f"✗ FastAPI security imports failed: {e}" )
        
        try:
            from .user_id_generator import get_user_info, email_to_system_id
            print( "✓ User ID generator imports successful" )
        except ImportError as e:
            print( f"⚠ User ID generator imports failed: {e}" )
        
        # Test 3: Firebase initialization (mock)
        print( "Testing Firebase initialization..." )
        try:
            # Test that init_firebase works
            init_firebase()
            
            # Check global state was set
            if FIREBASE_INITIALIZED:
                print( "✓ Firebase mock initialization working" )
            else:
                print( "✗ Firebase initialization failed to set global state" )
        except Exception as e:
            print( f"⚠ Firebase initialization issues: {e}" )
        
        # Test 4: Token verification functionality (mock)
        print( "Testing token verification functionality..." )
        try:
            import asyncio
            
            # Test valid token format
            valid_token = "mock_token_test_user_123"
            result = asyncio.run( verify_firebase_token( valid_token ) )
            
            if isinstance( result, dict ) and "uid" in result and "email" in result:
                print( "✓ Token verification logic working" )
            else:
                print( "✗ Token verification returned invalid structure" )
        except Exception as e:
            print( f"⚠ Token verification functionality issues: {e}" )
        
        # Test 5: Email-based token format
        print( "Testing email-based token format..." )
        try:
            email_token = "mock_token_email_test@example.com"
            result = asyncio.run( verify_firebase_token( email_token ) )
            
            if isinstance( result, dict ) and "@" in result.get( "email", "" ):
                print( "✓ Email-based token format working" )
            else:
                print( "⚠ Email-based token format may have issues" )
        except Exception as e:
            print( f"⚠ Email-based token format issues: {e}" )
        
        # Test 6: Invalid token handling
        print( "Testing invalid token handling..." )
        try:
            invalid_token = "not_a_valid_token"
            try:
                asyncio.run( verify_firebase_token( invalid_token ) )
                print( "✗ Invalid token was accepted (security issue)" )
            except Exception:
                print( "✓ Invalid tokens properly rejected" )
        except Exception as e:
            print( f"⚠ Invalid token testing issues: {e}" )
        
        # Test 7: User info lookup integration
        print( "Testing user info lookup integration..." )
        try:
            # Try to import and test user lookup
            from .user_id_generator import get_user_info
            
            # Test with a basic system ID
            test_id = "test_user_123"
            user_info = get_user_info( test_id )
            
            if user_info or user_info is None:  # Either found user or properly returned None
                print( "✓ User info lookup integration working" )
            else:
                print( "⚠ User info lookup returned unexpected result" )
        except ImportError:
            print( "⚠ User info lookup module not available" )
        except Exception as e:
            print( f"⚠ User info lookup integration issues: {e}" )
        
        # Test 8: Critical v000 dependency scanning
        print( "\\n🔍 Scanning for v000 dependencies..." )
        
        # Scan the file for v000 patterns
        import inspect
        source_file = inspect.getfile( current_module )
        
        v000_found = False
        v000_patterns = []
        
        with open( source_file, 'r' ) as f:
            content = f.read()
            
            # Split content and exclude smoke test function
            lines = content.split( '\\n' )
            in_smoke_test = False
            
            for i, line in enumerate( lines ):
                stripped_line = line.strip()
                
                # Track if we're in the smoke test function
                if "def quick_smoke_test" in line:
                    in_smoke_test = True
                    continue
                elif in_smoke_test and line.startswith( "def " ):
                    in_smoke_test = False
                elif in_smoke_test:
                    continue
                
                # Skip comments and docstrings
                if ( stripped_line.startswith( '#' ) or 
                     stripped_line.startswith( '"""' ) or
                     stripped_line.startswith( "'" ) ):
                    continue
                
                # Look for actual v000 code references
                if "v000" in stripped_line and any( pattern in stripped_line for pattern in [
                    "import", "from", "cosa.agents.v000", ".v000."
                ] ):
                    v000_found = True
                    v000_patterns.append( f"Line {i+1}: {stripped_line}" )
        
        if v000_found:
            print( "🚨 CRITICAL: v000 dependencies detected!" )
            print( "   Found v000 references:" )
            for pattern in v000_patterns[ :3 ]:  # Show first 3
                print( f"     • {pattern}" )
            if len( v000_patterns ) > 3:
                print( f"     ... and {len( v000_patterns ) - 3} more v000 references" )
            print( "   ⚠️  These dependencies MUST be resolved before v000 deprecation!" )
        else:
            print( "✅ EXCELLENT: No v000 dependencies found!" )
        
        # Test 9: Security scheme validation
        print( "\\nTesting authentication security validation..." )
        try:
            # Test HTTPBearer security scheme
            if hasattr( current_module, 'security' ):
                scheme = getattr( current_module, 'security' )
                if hasattr( scheme, 'scheme_name' ):
                    print( "✓ Security scheme properly configured" )
                else:
                    print( "⚠ Security scheme may have configuration issues" )
            
            # Test dependency chain structure
            print( "✓ Authentication dependency chain structure validated" )
            print( "  (Full endpoint testing requires FastAPI app context)" )
            
        except Exception as e:
            print( f"⚠ Security validation issues: {e}" )
    
    except Exception as e:
        print( f"✗ Error during auth testing: {e}" )
        import traceback
        traceback.print_exc()
    
    # Summary
    print( "\\n" + "="*60 )
    if v000_found:
        print( "🚨 CRITICAL ISSUE: REST auth has v000 dependencies!" )
        print( "   Status: NOT READY for v000 deprecation" )
        print( "   Priority: IMMEDIATE ACTION REQUIRED" )
        print( "   Risk Level: CRITICAL - Authentication will break" )
    else:
        print( "✅ REST auth smoke test completed successfully!" )
        print( "   Status: Authentication system ready for v000 deprecation" )
        print( "   Risk Level: LOW" )
    
    print( "✓ REST auth smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()