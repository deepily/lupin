// Unit tests — boot-time login bounce (WP0).
// Run via `npx tsx --test src/tests/unit/multiplexer/auth/auth_guard.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  redirectToLoginIfUnauthenticated,
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
