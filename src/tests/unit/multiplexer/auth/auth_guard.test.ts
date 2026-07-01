// Unit tests — boot-time login bounce (WP0).
// Run via `npx tsx --test src/tests/unit/multiplexer/auth/auth_guard.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  redirectToLoginIfUnauthenticated,
  logout,
  LOGIN_PATH,
  type RedirectTarget,
} from "../../../../lupin_app/static/js/multiplexer/auth/authGuard";
import {
  createStorageServiceForTesting,
} from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  createEventBusForTesting,
} from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";

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

test( "logout is safe when no tokens are present (idempotent clear) and still redirects", () => {
  const storage = makeStorage();
  const target  = makeTarget( "/app/multiplexer" );
  assert.doesNotThrow( () => logout( storage, target ) );
  assert.equal( storage.getAccessToken(), null );
  assert.equal( storage.getRefreshToken(), null );
  assert.equal( target.href, LOGIN_PATH );
} );
