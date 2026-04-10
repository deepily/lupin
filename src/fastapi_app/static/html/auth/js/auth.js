/**
 * Authentication Utilities for Lupin JWT Authentication.
 *
 * Handles token management, API calls, and auth state.
 */

// ============================================================================
// Token Management
// ============================================================================

/**
 * Get access token from localStorage.
 * @returns {string|null} Access token or null if not found
 */
function getAccessToken() {
    return localStorage.getItem( 'lupin_access_token' );
}

/**
 * Get refresh token from localStorage.
 * @returns {string|null} Refresh token or null if not found
 */
function getRefreshToken() {
    return localStorage.getItem( 'lupin_refresh_token' );
}

/**
 * Store tokens in localStorage.
 * @param {string} accessToken - JWT access token
 * @param {string} refreshToken - JWT refresh token
 */
function setTokens( accessToken, refreshToken ) {
    localStorage.setItem( 'lupin_access_token', accessToken );
    localStorage.setItem( 'lupin_refresh_token', refreshToken );
}

/**
 * Clear all tokens from localStorage (logout).
 */
function clearTokens() {
    localStorage.removeItem( 'lupin_access_token' );
    localStorage.removeItem( 'lupin_refresh_token' );
    localStorage.removeItem( 'user_data' );
}

/**
 * Store user data in localStorage.
 * @param {object} userData - User information
 */
function setUserData( userData ) {
    localStorage.setItem( 'user_data', JSON.stringify( userData ) );
}

/**
 * Get user data from localStorage.
 * @returns {object|null} User data or null if not found
 */
function getUserData() {
    const data = localStorage.getItem( 'user_data' );
    return data ? JSON.parse( data ) : null;
}

// ============================================================================
// Token Validation (Proactive Refresh — Pattern A)
// ============================================================================

/**
 * Check if a JWT access token is expired or near-expiry.
 *
 * Decodes the JWT payload and compares the `exp` claim (Unix seconds) to
 * Date.now() with a safety buffer. Returns true on any failure — missing,
 * malformed, no exp claim, or past exp. Treating "unsure" as "expired" is
 * the safe default for a proactive refresh check.
 *
 * @param {string|null} token - JWT access token (or null/undefined)
 * @param {number} bufferSeconds - Refresh threshold in seconds (default 30)
 * @returns {boolean} True if token should be refreshed before use
 */
function isTokenExpired( token, bufferSeconds = 30 ) {
    if ( !token ) return true;
    try {
        const parts = token.split( '.' );
        if ( parts.length !== 3 ) return true;
        const payload = JSON.parse( atob( parts[ 1 ] ) );
        if ( !payload.exp ) return true;
        const now = Math.floor( Date.now() / 1000 );
        return ( payload.exp - bufferSeconds ) <= now;
    } catch ( e ) {
        return true;
    }
}

/**
 * Ensure the current access token is valid, proactively refreshing if expired.
 *
 * Call this before any authenticated fetch to eliminate stale-token 401s.
 * Safe to call when no token exists — returns false without throwing, and
 * the caller's fetch will then fail with 401 and the reactive retry path
 * in apiCall() will handle the redirect-to-login flow.
 *
 * @returns {Promise<boolean>} True if a valid token is now available,
 *                              false if no token exists or refresh failed
 */
async function ensureValidToken() {
    const token = getAccessToken();
    if ( !token ) {
        // No token — nothing to refresh. Let the caller's fetch fail with 401
        // and the reactive retry path handle the redirect.
        return false;
    }
    if ( !isTokenExpired( token ) ) {
        // Fast path — token still valid
        return true;
    }
    console.log( '⚠️ Access token near expiry — refreshing proactively' );
    const refreshed = await refreshAccessToken();
    if ( !refreshed ) {
        console.error( '🛑 Proactive refresh failed — will fall through to reactive retry' );
        return false;
    }
    return true;
}

// ============================================================================
// API Calls
// ============================================================================

/**
 * Make API call with automatic token refresh.
 * @param {string} endpoint - API endpoint (e.g., '/auth/login')
 * @param {string} method - HTTP method (GET, POST, PUT, DELETE)
 * @param {object|null} data - Request body data
 * @param {boolean} includeAuth - Include Authorization header (default: true)
 * @param {number} retryCount - Internal retry counter (default: 0)
 * @returns {Promise<object>} Response data
 */
async function apiCall( endpoint, method = 'GET', data = null, includeAuth = true, retryCount = 0 ) {
    const url = `http://localhost:7999${endpoint}`;

    const headers = {
        'Content-Type': 'application/json'
    };

    if ( includeAuth ) {
        // Proactive refresh (Pattern A) — catches expiry BEFORE the fetch.
        // Skipped on retries (retryCount > 0) because the retry was triggered
        // by the reactive path below which just refreshed the token.
        if ( retryCount === 0 ) {
            await ensureValidToken();
        }

        const token = getAccessToken();
        if ( token ) {
            headers[ 'Authorization' ] = `Bearer ${token}`;
            console.log( `🔑 API call to ${endpoint} - Token: ${token.substring( 0, 20 )}... (retry: ${retryCount})` );
        } else {
            console.warn( `⚠️ No access token found for ${endpoint}` );
        }
    }

    const options = {
        method: method,
        headers: headers
    };

    if ( data && ( method === 'POST' || method === 'PUT' || method === 'DELETE' ) ) {
        options.body = JSON.stringify( data );
    }

    try {
        const response = await fetch( url, options );
        const responseData = await response.json();

        if ( !response.ok ) {
            console.log( `❌ ${response.status} ${response.statusText} from ${endpoint}:`, responseData );

            // If 401 Unauthorized, try to refresh token
            if ( response.status === 401 && includeAuth ) {
                // Prevent infinite retry loop
                if ( retryCount >= 2 ) {
                    console.error( `🛑 Max retries (${retryCount}) exceeded for ${endpoint}` );
                    clearTokens();
                    window.location.href = '/app/auth/login';
                    throw new Error( 'Session expired. Please login again.' );
                }

                console.log( `🔄 Attempting token refresh (retry ${retryCount + 1}/2)...` );
                const refreshed = await refreshAccessToken();
                if ( refreshed ) {
                    // Retry original request with new token
                    return await apiCall( endpoint, method, data, includeAuth, retryCount + 1 );
                } else {
                    // Refresh failed, redirect to login
                    console.error( '🛑 Token refresh failed' );
                    clearTokens();
                    window.location.href = '/app/auth/login';
                    throw new Error( 'Session expired. Please login again.' );
                }
            }

            throw new Error( responseData.detail || responseData.message || 'API call failed' );
        }

        console.log( `✅ ${response.status} ${response.statusText} from ${endpoint}` );
        return responseData;

    } catch ( error ) {
        console.error( `API call failed: ${endpoint}`, error );
        throw error;
    }
}

/**
 * Refresh access token using refresh token.
 * @returns {Promise<boolean>} True if refresh succeeded, false otherwise
 */
async function refreshAccessToken() {
    const refreshToken = getRefreshToken();

    if ( !refreshToken ) {
        return false;
    }

    try {
        const response = await apiCall(
            '/auth/refresh',
            'POST',
            { refresh_token: refreshToken },
            false  // Don't include auth header
        );

        if ( response.tokens && response.tokens.access_token && response.tokens.refresh_token ) {
            // Update both tokens (token rotation for security)
            setTokens( response.tokens.access_token, response.tokens.refresh_token );
            console.log( '✓ Token refreshed successfully' );
            return true;
        }

        console.error( 'Invalid refresh response structure:', response );
        return false;

    } catch ( error ) {
        console.error( 'Token refresh failed:', error );
        return false;
    }
}

// ============================================================================
// Authentication State
// ============================================================================

/**
 * Check if user is authenticated.
 * @returns {boolean} True if user has valid tokens
 */
function isAuthenticated() {
    return !!getAccessToken();
}

/**
 * Get current user information.
 * @returns {Promise<object|null>} User data or null if not authenticated
 */
async function getCurrentUser() {
    if ( !isAuthenticated() ) {
        return null;
    }

    // Try to get from localStorage first
    let userData = getUserData();

    if ( userData ) {
        return userData;
    }

    // Fetch from API
    try {
        userData = await apiCall( '/auth/me', 'GET' );
        setUserData( userData );
        return userData;
    } catch ( error ) {
        console.error( 'Failed to get current user:', error );
        return null;
    }
}

/**
 * Check if current user has specific role.
 * @param {string} role - Role name to check (e.g., 'admin')
 * @returns {Promise<boolean>} True if user has the role
 */
async function hasRole( role ) {
    const user = await getCurrentUser();
    if ( !user || !user.roles ) {
        return false;
    }

    return user.roles.includes( role );
}

/**
 * Check if current user is admin.
 * @returns {Promise<boolean>} True if user has admin role
 */
async function isAdmin() {
    return await hasRole( 'admin' );
}

// ============================================================================
// Authentication Actions
// ============================================================================

/**
 * Login with email and password.
 * @param {string} email - User email
 * @param {string} password - User password
 * @returns {Promise<object>} Login response with tokens
 */
async function login( email, password ) {
    const response = await apiCall(
        '/auth/login',
        'POST',
        { email: email, password: password },
        false  // Don't include auth header for login
    );

    if ( response.tokens && response.tokens.access_token && response.tokens.refresh_token ) {
        setTokens( response.tokens.access_token, response.tokens.refresh_token );

        // Fetch and store user data
        const userData = await getCurrentUser();

        return response;
    }

    throw new Error( 'Invalid login response' );
}

/**
 * Logout current user.
 * @returns {Promise<void>}
 */
async function logout() {
    const refreshToken = getRefreshToken();

    if ( refreshToken ) {
        try {
            await apiCall(
                '/auth/logout',
                'POST',
                { refresh_token: refreshToken }
            );
        } catch ( error ) {
            console.error( 'Logout API call failed:', error );
            // Continue with local logout even if API fails
        }
    }

    clearTokens();
    window.location.href = '/app/auth/login';
}

/**
 * Register new user.
 * @param {string} email - User email
 * @param {string} password - User password
 * @returns {Promise<object>} Registration response
 */
async function register( email, password ) {
    return await apiCall(
        '/auth/register',
        'POST',
        { email: email, password: password },
        false  // Don't include auth header for registration
    );
}

/**
 * Change user password.
 * @param {string} currentPassword - Current password
 * @param {string} newPassword - New password
 * @returns {Promise<object>} Response
 */
async function changePassword( currentPassword, newPassword ) {
    return await apiCall(
        '/auth/change-password',
        'PUT',
        {
            current_password: currentPassword,
            new_password: newPassword
        }
    );
}

// ============================================================================
// Redirect Handling
// ============================================================================

/**
 * Get safe redirect URL from query parameter.
 * Validates that redirect path is internal (/static/html/*) to prevent open redirect vulnerabilities.
 *
 * @returns {string} Safe redirect URL or default profile page
 */
function getSafeRedirectUrl() {
    const params = new URLSearchParams( window.location.search );
    const redirect = params.get( 'redirect' );

    // Validate redirect parameter — accept both /app/* and legacy /static/html/* paths
    if ( redirect && ( redirect.startsWith( '/app' ) || redirect.startsWith( '/static/html/' ) ) ) {
        console.log( `✓ Valid redirect parameter: ${redirect}` );
        return redirect;
    }

    if ( redirect ) {
        console.warn( `⚠️ Invalid redirect parameter (must start with /app or /static/html/): ${redirect}` );
    }

    // Default to landing page
    return '/app';
}

// ============================================================================
// UI Helpers
// ============================================================================

/**
 * Show error message in designated element.
 * @param {string} elementId - ID of error display element
 * @param {string} message - Error message to display
 */
function showError( elementId, message ) {
    const errorEl = document.getElementById( elementId );
    if ( errorEl ) {
        errorEl.textContent = message;
        errorEl.style.display = 'block';
    }
}

/**
 * Hide error message.
 * @param {string} elementId - ID of error display element
 */
function hideError( elementId ) {
    const errorEl = document.getElementById( elementId );
    if ( errorEl ) {
        errorEl.textContent = '';
        errorEl.style.display = 'none';
    }
}

/**
 * Show success message in designated element.
 * @param {string} elementId - ID of success display element
 * @param {string} message - Success message to display
 */
function showSuccess( elementId, message ) {
    const successEl = document.getElementById( elementId );
    if ( successEl ) {
        successEl.textContent = message;
        successEl.style.display = 'block';
    }
}

/**
 * Hide success message.
 * @param {string} elementId - ID of success display element
 */
function hideSuccess( elementId ) {
    const successEl = document.getElementById( elementId );
    if ( successEl ) {
        successEl.textContent = '';
        successEl.style.display = 'none';
    }
}

/**
 * Show loading spinner/indicator.
 * @param {string} elementId - ID of loading indicator element
 */
function showLoading( elementId ) {
    const loadingEl = document.getElementById( elementId );
    if ( loadingEl ) {
        loadingEl.style.display = 'block';
    }
}

/**
 * Hide loading spinner/indicator.
 * @param {string} elementId - ID of loading indicator element
 */
function hideLoading( elementId ) {
    const loadingEl = document.getElementById( elementId );
    if ( loadingEl ) {
        loadingEl.style.display = 'none';
    }
}

// ============================================================================
// Page Protection
// ============================================================================

/**
 * Require authentication for current page.
 * Redirects to login if not authenticated.
 */
function requireAuth() {
    if ( !isAuthenticated() ) {
        window.location.href = '/app/auth/login';
    }
}

/**
 * Require admin role for current page.
 * Redirects to login or shows error if not admin.
 */
async function requireAdmin() {
    requireAuth();

    const admin = await isAdmin();
    if ( !admin ) {
        alert( 'Access denied. Admin privileges required.' );
        window.location.href = '/app/auth/profile';
    }
}

console.log( 'Auth utilities loaded successfully' );
