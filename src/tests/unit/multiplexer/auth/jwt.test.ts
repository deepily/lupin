// Unit tests — JWT claim decoding (WP0/WP1 token-key migration).
// Run via `npx tsx --test src/tests/unit/multiplexer/auth/jwt.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  decodeJwtClaims,
  jwtExpiryMs,
  jwtEmail,
} from "../../../../lupin_app/static/js/multiplexer/auth/jwt";

// Build a JWT-shaped string `header.payload.sig` with a base64url-encoded
// payload. `payload` may be any JSON value (used to exercise the non-object
// guard) or a raw string segment (used to exercise the decode/parse failures).
function jwtWith( payload: unknown ): string {
  const header  = Buffer.from( JSON.stringify( { alg: "HS256", typ: "JWT" } ) ).toString( "base64url" );
  const body    = Buffer.from( JSON.stringify( payload ) ).toString( "base64url" );
  return `${header}.${body}.sig`;
}

test( "decodeJwtClaims returns the payload object for a well-formed token", () => {
  const token = jwtWith( { sub: "u1", email: "a@b.com", exp: 123, roles: [ "admin" ] } );
  const claims = decodeJwtClaims( token );
  assert.deepEqual( claims, { sub: "u1", email: "a@b.com", exp: 123, roles: [ "admin" ] } );
} );

test( "decodeJwtClaims returns null when the token is not three segments", () => {
  assert.equal( decodeJwtClaims( "only.two" ), null );
  assert.equal( decodeJwtClaims( "a.b.c.d" ), null );
} );

test( "decodeJwtClaims returns null when the payload segment is not valid base64 (bad length)", () => {
  // A single base64 character is length%4===1 — an impossible base64 length.
  const token = "header.x.sig";
  assert.equal( decodeJwtClaims( token ), null );
} );

test( "decodeJwtClaims returns null when the payload segment has non-base64 characters", () => {
  // "@@@@" is length%4===0 but atob() throws on the non-base64 '@' chars.
  const token = "header.@@@@.sig";
  assert.equal( decodeJwtClaims( token ), null );
} );

test( "decodeJwtClaims returns null when the decoded payload is not valid JSON", () => {
  const badJson = Buffer.from( "{not json" ).toString( "base64url" );
  const token = `header.${badJson}.sig`;
  assert.equal( decodeJwtClaims( token ), null );
} );

test( "decodeJwtClaims returns null when the payload is valid JSON but not an object", () => {
  assert.equal( decodeJwtClaims( jwtWith( 42 ) ), null );
  assert.equal( decodeJwtClaims( jwtWith( "a string" ) ), null );
  assert.equal( decodeJwtClaims( jwtWith( null ) ), null );
} );

test( "decodeJwtClaims decodes UTF-8 (non-ASCII) claim values", () => {
  const token = jwtWith( { email: "tëst@exämple.com" } );
  assert.equal( decodeJwtClaims( token )?.email, "tëst@exämple.com" );
} );

test( "jwtExpiryMs returns exp claim in milliseconds", () => {
  const token = jwtWith( { exp: 1_700_000_000 } );
  assert.equal( jwtExpiryMs( token ), 1_700_000_000_000 );
} );

test( "jwtExpiryMs returns null when claims cannot be decoded", () => {
  assert.equal( jwtExpiryMs( "garbage" ), null );
} );

test( "jwtExpiryMs returns null when exp is missing or not a number", () => {
  assert.equal( jwtExpiryMs( jwtWith( { email: "a@b.com" } ) ), null );
  assert.equal( jwtExpiryMs( jwtWith( { exp: "soon" } ) ), null );
} );

test( "jwtEmail returns the email claim", () => {
  assert.equal( jwtEmail( jwtWith( { email: "user@lupin.ai" } ) ), "user@lupin.ai" );
} );

test( "jwtEmail returns null when claims cannot be decoded", () => {
  assert.equal( jwtEmail( "garbage" ), null );
} );

test( "jwtEmail returns null when email is missing, empty, or not a string", () => {
  assert.equal( jwtEmail( jwtWith( { exp: 1 } ) ), null );
  assert.equal( jwtEmail( jwtWith( { email: "" } ) ), null );
  assert.equal( jwtEmail( jwtWith( { email: 12345 } ) ), null );
} );
