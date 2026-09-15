// Unit tests — boot-time login bounce (WP0).
// Run via `npx tsx --test src/tests/unit/multiplexer/auth/auth_guard.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  redirectToLoginIfUnauthenticated,
  bounceToLoginOnDeadSession,
  logout,
  LOGIN_PATH,
  type RedirectTarget,
} from "../../../../lupin_app/static/js/multiplexer/auth/authGuard";
import {
  createAuthManager,
  ChainMutexLockManager,
  REFRESH_MISSING_ERROR,
  REFRESH_REJECTED_ERROR,
} from "../../../../lupin_app/static/js/multiplexer/auth/AuthManager";
import {
  createStorageServiceForTesting,
  InMemoryStorage,
} from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  createEventBusForTesting,
  type EventBus,
} from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { RefreshFailedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

function makeStorage() {
  return createStorageServiceForTesting( createEventBusForTesting() );
}

function makeTarget( pathname: string ): RedirectTarget {
  return { pathname, href: pathname };
}

test( "redirects to login (with encoded redirect-back) when no access token is present", () => {
  const storage = makeStorage();
  const target  = makeTarget( "/app/multiplexer" );
  const redirected = redirectToLoginIfUnauthenticated( storage, target );
  assert.equal( redirected, true );
  assert.equal( target.href, "/app/auth/login?redirect=%2Fapp%2Fmultiplexer" );
} );

test( "does not redirect when an access token is present", () => {
  const storage = makeStorage();
  storage.setTokens( "access-jwt", "refresh-jwt" );
  const target  = makeTarget( "/app/multiplexer" );
  const redirected = redirectToLoginIfUnauthenticated( storage, target );
  assert.equal( redirected, false );
  assert.equal( target.href, "/app/multiplexer", "href left untouched" );
} );

// ---------------------------------------------------------------------------
// logout (F-K-D1 — load-bearing auth fix): the OUTCOME must be the PERSISTED
// tokens GONE, not merely "a clear method was called". A wiring-only assertion
// would false-pass the exact bug this replaces (clearing only in-memory state).
// ---------------------------------------------------------------------------

test( "logout clears the PERSISTED tokens (post-condition: keys absent) and redirects to login", () => {
  const storage = makeStorage();
  storage.setTokens( "access-jwt", "refresh-jwt" );
  // Pre-condition: both persisted tokens present.
  assert.equal( storage.getAccessToken(), "access-jwt" );
  assert.equal( storage.getRefreshToken(), "refresh-jwt" );

  const target = makeTarget( "/app/multiplexer" );
  logout( storage, target );

  // OUTCOME (the real proof): the persisted tokens are GONE — any token-reading
  // path (authGuard / API / WS) now sees no token, so the user is logged out.
  assert.equal( storage.getAccessToken(), null, "persisted access token cleared" );
  assert.equal( storage.getRefreshToken(), null, "persisted refresh token cleared" );
  // AND the redirect lands on the login page (clean, no redirect-back param).
  assert.equal( target.href, LOGIN_PATH );
} );

// ---------------------------------------------------------------------------
// bounceToLoginOnDeadSession (row 645a7da5, 2026-09-15). Before it, a failed
// refresh emitted `refresh_failed` to nobody and the multiplexer sat on an empty
// inbox. The OUTCOME asserted is the one the user sees: tokens gone + login page.
// ---------------------------------------------------------------------------

function emitRefreshFailed( bus: EventBus, error: string ): void {
  bus.emit<RefreshFailedPayload>( {
    type    : "refresh_failed",
    payload : { error, willRetry: false },
    source  : "AuthManager",
    ts      : Date.now(),
  } );
}

for ( const error of [ REFRESH_MISSING_ERROR, REFRESH_REJECTED_ERROR ] ) {
  test( `a dead session (${error}) clears the persisted tokens and bounces to login with a redirect-back`, () => {
    const bus     = createEventBusForTesting();
    const storage = createStorageServiceForTesting( bus );
    storage.setTokens( "access-jwt", "refresh-jwt" );
    const target  = makeTarget( "/app/multiplexer" );

    bounceToLoginOnDeadSession( bus, storage, target );
    emitRefreshFailed( bus, error );

    assert.equal( storage.getAccessToken(), null, "cleared, or the login page redirects straight back" );
    assert.equal( storage.getRefreshToken(), null );
    assert.equal( target.href, "/app/auth/login?redirect=%2Fapp%2Fmultiplexer" );
  } );
}

for ( const error of [ "timeout", "network is down", "refresh failed: HTTP 500", "refresh failed: HTTP 503" ] ) {
  test( `a transient refresh failure (${error}) leaves the tokens and the page alone`, () => {
    const bus     = createEventBusForTesting();
    const storage = createStorageServiceForTesting( bus );
    storage.setTokens( "access-jwt", "refresh-jwt" );
    const target  = makeTarget( "/app/multiplexer" );

    bounceToLoginOnDeadSession( bus, storage, target );
    emitRefreshFailed( bus, error );

    assert.equal( storage.getAccessToken(), "access-jwt" );
    assert.equal( storage.getRefreshToken(), "refresh-jwt" );
    assert.equal( target.href, "/app/multiplexer" );
  } );
}

test( "the returned closure unsubscribes: a dead-session event after it changes nothing", () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  storage.setTokens( "access-jwt", "refresh-jwt" );
  const target  = makeTarget( "/app/multiplexer" );

  const unsubscribe = bounceToLoginOnDeadSession( bus, storage, target );
  unsubscribe();
  emitRefreshFailed( bus, REFRESH_REJECTED_ERROR );

  assert.equal( storage.getAccessToken(), "access-jwt" );
  assert.equal( target.href, "/app/multiplexer" );
} );

test( "end to end with a real AuthManager: the half session measured in Rick's Chrome lands on login, not an empty inbox", async () => {
  const bus     = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting( bus, backend );
  // Boot guard passes (an access token is present) but the refresh token is gone.
  storage.setTokens( "expired-access", "gone" );
  backend.removeItem( "lupin_refresh_token" );
  const target = makeTarget( "/app/multiplexer" );
  assert.equal( redirectToLoginIfUnauthenticated( storage, target ), false, "precondition: presence-only guard lets it boot" );

  bounceToLoginOnDeadSession( bus, storage, target );
  const auth = createAuthManager( {
    refreshUrl       : "/auth/refresh",
    defaultTimeoutMs : 5000,
    storage,
    bus,
    locks            : new ChainMutexLockManager(),
    fetcher          : () => Promise.reject( new Error( "no fetch expected" ) ),
  } );

  await assert.rejects( auth.getToken() );
  assert.equal( storage.getAccessToken(), null );
  assert.equal( target.href, "/app/auth/login?redirect=%2Fapp%2Fmultiplexer" );
} );

test( "logout is safe when no tokens are present (idempotent clear) and still redirects", () => {
  const storage = makeStorage();
  const target  = makeTarget( "/app/multiplexer" );
  assert.doesNotThrow( () => logout( storage, target ) );
  assert.equal( storage.getAccessToken(), null );
  assert.equal( storage.getRefreshToken(), null );
  assert.equal( target.href, LOGIN_PATH );
} );
