# Authentication Integration Guide

**Version**: 1.0
**Last Updated**: 2025.10.04
**Target Audience**: Frontend developers, API consumers

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [REST API Integration](#rest-api-integration)
4. [WebSocket Authentication](#websocket-authentication)
5. [Token Storage Best Practices](#token-storage-best-practices)
6. [Frontend Framework Examples](#frontend-framework-examples)
7. [Testing Your Integration](#testing-your-integration)

---

## Overview

This guide covers practical integration of the Lupin Authentication API into web applications. You'll learn:

- How to implement complete authentication flows
- Best practices for token management
- WebSocket authentication patterns
- Security considerations for frontend applications

**Prerequisites**:
- Basic JavaScript knowledge
- Understanding of HTTP requests and responses
- Familiarity with Promises/async-await

---

## Quick Start

### Minimal Authentication Setup

```javascript
// Configuration
const API_BASE_URL = 'http://localhost:7999';

// 1. Register new user
async function registerUser( email, password ) {
  const response = await fetch( `${API_BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });

  if ( !response.ok ) throw new Error( await response.json().detail );
  return await response.json();
}

// 2. Login and store tokens
async function login( email, password ) {
  const response = await fetch( `${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });

  if ( !response.ok ) throw new Error( await response.json().detail );

  const data = await response.json();
  localStorage.setItem( 'access_token', data.tokens.access_token );
  localStorage.setItem( 'refresh_token', data.tokens.refresh_token );
  return data;
}

// 3. Make authenticated requests
async function getProfile() {
  const token = localStorage.getItem( 'access_token' );

  const response = await fetch( `${API_BASE_URL}/auth/me`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });

  if ( response.status === 401 ) {
    // Token expired - refresh
    await refreshToken();
    return getProfile(); // Retry
  }

  return await response.json();
}

// 4. Refresh expired tokens
async function refreshToken() {
  const refresh = localStorage.getItem( 'refresh_token' );

  const response = await fetch( `${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh })
  });

  if ( !response.ok ) {
    // Refresh failed - redirect to login
    window.location.href = '/login';
    return;
  }

  const data = await response.json();
  localStorage.setItem( 'access_token', data.tokens.access_token );
  localStorage.setItem( 'refresh_token', data.tokens.refresh_token );
}
```

---

## REST API Integration

### Complete Auth Utility Class

```javascript
/**
 * Authentication utility for Lupin JWT system.
 * Handles login, registration, token refresh, and authenticated requests.
 */
class AuthService {
  constructor( baseURL = 'http://localhost:7999' ) {
    this.baseURL = baseURL;
    this.accessTokenKey = 'access_token';
    this.refreshTokenKey = 'refresh_token';
    this.refreshInProgress = null; // Prevent multiple simultaneous refreshes
  }

  /**
   * Register new user account.
   */
  async register( email, password ) {
    return await this._apiCall( '/auth/register', 'POST', { email, password }, false );
  }

  /**
   * Login and store tokens.
   */
  async login( email, password ) {
    const data = await this._apiCall( '/auth/login', 'POST', { email, password }, false );

    // Store tokens
    localStorage.setItem( this.accessTokenKey, data.tokens.access_token );
    localStorage.setItem( this.refreshTokenKey, data.tokens.refresh_token );

    return data;
  }

  /**
   * Logout and clear tokens.
   */
  async logout() {
    const refreshToken = localStorage.getItem( this.refreshTokenKey );

    // Revoke refresh token on server
    await this._apiCall( '/auth/logout', 'POST', { refresh_token: refreshToken }, true );

    // Clear local storage
    localStorage.removeItem( this.accessTokenKey );
    localStorage.removeItem( this.refreshTokenKey );
  }

  /**
   * Get current user profile.
   */
  async getCurrentUser() {
    return await this._apiCall( '/auth/me', 'GET', null, true );
  }

  /**
   * Change user password.
   */
  async changePassword( currentPassword, newPassword ) {
    return await this._apiCall( '/auth/change-password', 'PUT', {
      current_password: currentPassword,
      new_password: newPassword
    }, true );
  }

  /**
   * Request password reset email.
   */
  async requestPasswordReset( email ) {
    return await this._apiCall( '/auth/request-password-reset', 'POST', { email }, false );
  }

  /**
   * Reset password with token.
   */
  async resetPassword( token, newPassword ) {
    return await this._apiCall( '/auth/reset-password', 'POST', {
      token: token,
      new_password: newPassword
    }, false );
  }

  /**
   * Request email verification.
   */
  async requestEmailVerification() {
    return await this._apiCall( '/auth/request-verification', 'POST', null, true );
  }

  /**
   * Verify email with token.
   */
  async verifyEmail( token ) {
    return await this._apiCall( '/auth/verify-email', 'POST', { token }, false );
  }

  /**
   * Check if user is authenticated.
   */
  isAuthenticated() {
    return !!localStorage.getItem( this.accessTokenKey );
  }

  /**
   * Get access token.
   */
  getAccessToken() {
    return localStorage.getItem( this.accessTokenKey );
  }

  /**
   * Refresh access token using refresh token.
   */
  async refreshAccessToken() {
    // Prevent multiple simultaneous refresh attempts
    if ( this.refreshInProgress ) {
      return this.refreshInProgress;
    }

    this.refreshInProgress = (async () => {
      try {
        const refreshToken = localStorage.getItem( this.refreshTokenKey );
        if ( !refreshToken ) {
          throw new Error( 'No refresh token available' );
        }

        const response = await fetch( `${this.baseURL}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken })
        });

        if ( !response.ok ) {
          throw new Error( 'Refresh failed' );
        }

        const data = await response.json();

        // Store new tokens (rotation)
        localStorage.setItem( this.accessTokenKey, data.tokens.access_token );
        localStorage.setItem( this.refreshTokenKey, data.tokens.refresh_token );

        return data.tokens.access_token;

      } catch ( error ) {
        // Refresh failed - clear tokens and redirect to login
        localStorage.removeItem( this.accessTokenKey );
        localStorage.removeItem( this.refreshTokenKey );
        window.location.href = '/login';
        throw error;

      } finally {
        this.refreshInProgress = null;
      }
    })();

    return this.refreshInProgress;
  }

  /**
   * Internal API call helper with automatic token refresh.
   */
  async _apiCall( endpoint, method, body = null, authenticate = false, retryCount = 0 ) {
    const url = `${this.baseURL}${endpoint}`;
    const headers = { 'Content-Type': 'application/json' };

    // Add authentication header if required
    if ( authenticate ) {
      const token = localStorage.getItem( this.accessTokenKey );
      if ( token ) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    }

    const options = {
      method: method,
      headers: headers
    };

    if ( body ) {
      options.body = JSON.stringify( body );
    }

    const response = await fetch( url, options );

    // Handle 401 Unauthorized (token expired)
    if ( response.status === 401 && authenticate && retryCount < 2 ) {
      // Try to refresh token
      await this.refreshAccessToken();

      // Retry request with new token (max 2 retries)
      return this._apiCall( endpoint, method, body, authenticate, retryCount + 1 );
    }

    // Handle errors
    if ( !response.ok ) {
      const error = await response.json();
      throw new Error( error.detail || 'API request failed' );
    }

    return await response.json();
  }
}

// Global instance
const authService = new AuthService();
```

### Usage Examples

**Registration**:
```javascript
try {
  const result = await authService.register(
    'newuser@example.com',
    'SecureP@ssw0rd!'
  );
  console.log( 'Registration successful:', result );
  // Redirect to login
  window.location.href = '/login';
} catch ( error ) {
  console.error( 'Registration failed:', error.message );
}
```

**Login**:
```javascript
try {
  const result = await authService.login(
    'user@example.com',
    'SecureP@ssw0rd!'
  );
  console.log( 'Login successful:', result );
  // Redirect to dashboard
  window.location.href = '/dashboard';
} catch ( error ) {
  console.error( 'Login failed:', error.message );
}
```

**Get Current User** (with automatic token refresh):
```javascript
try {
  const user = await authService.getCurrentUser();
  console.log( 'Current user:', user );
  // Update UI with user info
  document.getElementById( 'username' ).textContent = user.email;
} catch ( error ) {
  console.error( 'Failed to get user:', error.message );
}
```

**Change Password**:
```javascript
try {
  await authService.changePassword(
    'OldP@ssw0rd!',
    'NewSecureP@ss123!'
  );
  console.log( 'Password changed successfully' );
} catch ( error ) {
  console.error( 'Password change failed:', error.message );
}
```

---

## WebSocket Authentication

### WebSocket Connection with JWT

WebSocket connections use the same JWT tokens for authentication:

```javascript
/**
 * Authenticated WebSocket connection for real-time updates.
 */
class AuthenticatedWebSocket {
  constructor( endpoint, sessionId ) {
    this.baseURL = 'ws://localhost:7999'; // WebSocket URL
    this.endpoint = endpoint; // e.g., '/ws/queue'
    this.sessionId = sessionId;
    this.websocket = null;
    this.authenticated = false;
    this.eventHandlers = new Map();
  }

  /**
   * Connect and authenticate WebSocket.
   */
  async connect() {
    const wsURL = `${this.baseURL}${this.endpoint}/${this.sessionId}`;

    return new Promise( (resolve, reject) => {
      this.websocket = new WebSocket( wsURL );

      this.websocket.onopen = async () => {
        console.log( '[WS] Connected, sending auth request...' );

        // Send authentication request with JWT token
        const accessToken = authService.getAccessToken();

        const authMessage = {
          type: 'auth_request',
          token: accessToken,
          session_id: this.sessionId,
          subscribed_events: ['*'] // Subscribe to all events
        };

        this.websocket.send( JSON.stringify( authMessage ) );
      };

      this.websocket.onmessage = ( event ) => {
        const message = JSON.parse( event.data );

        // Handle authentication response
        if ( message.type === 'auth_success' ) {
          console.log( '[WS] Authentication successful' );
          this.authenticated = true;
          resolve();
        } else if ( message.type === 'auth_error' ) {
          console.error( '[WS] Authentication failed:', message.message );
          reject( new Error( message.message ) );
        } else {
          // Normal message - dispatch to handlers
          this._handleMessage( message );
        }
      };

      this.websocket.onerror = ( error ) => {
        console.error( '[WS] WebSocket error:', error );
        reject( error );
      };

      this.websocket.onclose = () => {
        console.log( '[WS] WebSocket closed' );
        this.authenticated = false;
      };
    });
  }

  /**
   * Subscribe to event type.
   */
  on( eventType, handler ) {
    if ( !this.eventHandlers.has( eventType ) ) {
      this.eventHandlers.set( eventType, [] );
    }
    this.eventHandlers.get( eventType ).push( handler );
  }

  /**
   * Send message to server.
   */
  send( message ) {
    if ( !this.authenticated ) {
      throw new Error( 'WebSocket not authenticated' );
    }
    this.websocket.send( JSON.stringify( message ) );
  }

  /**
   * Disconnect WebSocket.
   */
  disconnect() {
    if ( this.websocket ) {
      this.websocket.close();
      this.websocket = null;
    }
  }

  /**
   * Internal message dispatcher.
   */
  _handleMessage( message ) {
    const eventType = message.type;

    // Call specific event handlers
    if ( this.eventHandlers.has( eventType ) ) {
      this.eventHandlers.get( eventType ).forEach( handler => {
        handler( message );
      });
    }

    // Call wildcard handlers
    if ( this.eventHandlers.has( '*' ) ) {
      this.eventHandlers.get( '*' ).forEach( handler => {
        handler( message );
      });
    }
  }
}
```

### WebSocket Usage Example

```javascript
async function initializeWebSocket() {
  // Generate or retrieve session ID
  const sessionId = localStorage.getItem( 'session_id' ) || generateSessionId();
  localStorage.setItem( 'session_id', sessionId );

  // Create WebSocket connection
  const ws = new AuthenticatedWebSocket( '/ws/queue', sessionId );

  // Subscribe to events
  ws.on( 'queue_update', ( message ) => {
    console.log( 'Queue updated:', message.data );
    updateQueueUI( message.data );
  });

  ws.on( 'notification', ( message ) => {
    console.log( 'Notification received:', message.text );
    showNotification( message.text );
  });

  ws.on( '*', ( message ) => {
    console.log( 'WebSocket message:', message );
  });

  try {
    // Connect and authenticate
    await ws.connect();
    console.log( 'WebSocket connected and authenticated!' );

    // Send ping to keep alive
    setInterval( () => {
      ws.send({ type: 'sys_ping' });
    }, 30000 );

  } catch ( error ) {
    console.error( 'WebSocket connection failed:', error );
  }
}

// Helper: Generate session ID
function generateSessionId() {
  const adjectives = ['wise', 'clever', 'happy', 'brave', 'calm'];
  const nouns = ['penguin', 'dolphin', 'eagle', 'fox', 'owl'];
  const adj = adjectives[Math.floor( Math.random() * adjectives.length )];
  const noun = nouns[Math.floor( Math.random() * nouns.length )];
  return `${adj}_${noun}`;
}

// Initialize on page load
document.addEventListener( 'DOMContentLoaded', () => {
  if ( authService.isAuthenticated() ) {
    initializeWebSocket();
  }
});
```

---

## Token Storage Best Practices

### Option 1: localStorage (Development - Current)

**Pros**:
- Simple to implement
- Persists across browser sessions
- Easy to access from JavaScript

**Cons**:
- Vulnerable to XSS attacks
- Not secure for production

**Implementation**:
```javascript
// Store
localStorage.setItem( 'access_token', token );

// Retrieve
const token = localStorage.getItem( 'access_token' );

// Remove
localStorage.removeItem( 'access_token' );
```

### Option 2: HttpOnly Cookies (Production Recommended)

**Pros**:
- Not accessible from JavaScript (XSS protection)
- Automatically included in requests
- More secure

**Cons**:
- Requires server-side cookie handling
- CSRF protection needed

**Backend Changes Required**:
```python
# Set tokens as httpOnly cookies instead of returning in response
response.set_cookie(
    key="access_token",
    value=access_token,
    httponly=True,
    secure=True,  # HTTPS only
    samesite="Strict",
    max_age=1800  # 30 minutes
)
```

**Frontend**:
```javascript
// No manual token management needed
// Cookies automatically included in requests

// Just make authenticated requests
const response = await fetch( '/auth/me', {
  credentials: 'include'  // Include cookies
});
```

### Option 3: Hybrid Approach

**Implementation**:
- Access token: httpOnly cookie (most secure)
- Refresh token: Secure storage or encrypted localStorage
- Token refresh: Automatic via interceptor

---

## Frontend Framework Examples

### React Integration

**Auth Context Provider**:
```javascript
import React, { createContext, useState, useContext, useEffect } from 'react';
import { authService } from './authService';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [user, setUser] = useState( null );
  const [loading, setLoading] = useState( true );

  useEffect( () => {
    // Load user on mount
    if ( authService.isAuthenticated() ) {
      authService.getCurrentUser()
        .then( setUser )
        .catch( () => setUser( null ) )
        .finally( () => setLoading( false ) );
    } else {
      setLoading( false );
    }
  }, []);

  const login = async ( email, password ) => {
    const result = await authService.login( email, password );
    setUser( result.user );
    return result;
  };

  const logout = async () => {
    await authService.logout();
    setUser( null );
  };

  const value = {
    user,
    login,
    logout,
    isAuthenticated: authService.isAuthenticated(),
    loading
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext( AuthContext );
}
```

**Protected Route**:
```javascript
import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';

export function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();

  if ( loading ) {
    return <div>Loading...</div>;
  }

  return isAuthenticated ? children : <Navigate to="/login" />;
}
```

**Login Component**:
```javascript
import { useState } from 'react';
import { useAuth } from './AuthContext';
import { useNavigate } from 'react-router-dom';

export function LoginPage() {
  const [email, setEmail] = useState( '' );
  const [password, setPassword] = useState( '' );
  const [error, setError] = useState( '' );
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async ( e ) => {
    e.preventDefault();
    setError( '' );

    try {
      await login( email, password );
      navigate( '/dashboard' );
    } catch ( err ) {
      setError( err.message );
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail( e.target.value )}
        placeholder="Email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword( e.target.value )}
        placeholder="Password"
        required
      />
      {error && <div className="error">{error}</div>}
      <button type="submit">Login</button>
    </form>
  );
}
```

### Vue.js Integration

**Auth Store (Pinia)**:
```javascript
import { defineStore } from 'pinia';
import { authService } from './authService';

export const useAuthStore = defineStore( 'auth', {
  state: () => ({
    user: null,
    loading: false
  }),

  getters: {
    isAuthenticated: (state) => !!state.user
  },

  actions: {
    async login( email, password ) {
      this.loading = true;
      try {
        const result = await authService.login( email, password );
        this.user = result.user;
        return result;
      } finally {
        this.loading = false;
      }
    },

    async logout() {
      await authService.logout();
      this.user = null;
    },

    async loadUser() {
      if ( authService.isAuthenticated() ) {
        this.loading = true;
        try {
          this.user = await authService.getCurrentUser();
        } catch {
          this.user = null;
        } finally {
          this.loading = false;
        }
      }
    }
  }
});
```

---

## Testing Your Integration

### Manual Testing Checklist

- [ ] Register new user with valid credentials
- [ ] Attempt registration with weak password (should fail)
- [ ] Attempt registration with duplicate email (should fail)
- [ ] Login with valid credentials
- [ ] Login with invalid password (should fail after 5 attempts)
- [ ] Access protected endpoint with valid token
- [ ] Wait for token to expire and verify automatic refresh
- [ ] Change password successfully
- [ ] Request password reset email
- [ ] Reset password with token
- [ ] Request email verification
- [ ] Verify email with token
- [ ] Logout and verify tokens are cleared
- [ ] Connect WebSocket and verify authentication

### Automated Testing Example

```javascript
describe( 'Authentication Flow', () => {
  it( 'should register, login, and access protected endpoint', async () => {
    // Register
    const email = `test${Date.now()}@example.com`;
    const password = 'TestP@ssw0rd!';

    const registerResult = await authService.register( email, password );
    expect( registerResult.user.email ).toBe( email );

    // Login
    const loginResult = await authService.login( email, password );
    expect( loginResult.tokens.access_token ).toBeDefined();

    // Get profile
    const user = await authService.getCurrentUser();
    expect( user.email ).toBe( email );
  });
});
```

---

## Next Steps

- **[API Reference](api-reference.md)** - Detailed endpoint documentation
- **[Security Guide](security-guide.md)** - Production security best practices
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions

---

**Version**: 1.0
**Last Updated**: 2025.10.04
**Maintained By**: Lupin Development Team
