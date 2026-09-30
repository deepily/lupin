// THE NAV'S "LOGGED IN" INDICATOR, MEASURED AGAINST WHAT THE SERVER WILL ACCEPT.
//
// Row 9d3a975e (P0), broadcast leg. Rick, verbatim: "the send of the broadcast to
// all CC sessions is issuing a 401 when I attempt to hit send. Even when my account
// is authenticated and listed as logged in."
//
// BOTH HALVES OF THAT SENTENCE ARE TRUE AT THE SAME INSTANT, OF THE SAME TOKEN, AND
// THAT IS THE DEFECT. `isAuthenticated()` is a PRESENCE CHECK on a string —
// `!!storage.getItem("lupin_access_token")` — with no decode, no `exp` check and no
// server round-trip. It drives `computeNavState` -> the rendered "email + Logout"
// half of the bar. So a token that is present and long past `exp` renders as logged
// in, and 401s on the next request.
//
// MEASURED 2026-09-04 in Rick's own browser (tab 90940002, real token backed up and
// restored). A JWT with `exp` 86,400s in the past:
//     nav predicate                                     -> true  ("email + Logout")
//     the same string sent to /api/commons/active-sessions -> 401
//
// ⚠️ WHAT THIS FILE IS NOT. It is not a test of the broadcast panel and not a test
// of the endpoint. `broadcast-panel.js` reads the same key raw and never refreshes,
// which is a SECOND route to the same 401 and wants its own guard. This file pins
// the one thing that makes Rick's sentence possible: the indicator must not vouch
// for a credential the server will refuse. § A WRONG REASSURANCE DISARMS THE READER —
// a UI that says "logged in" is exactly such a reassurance.
//
// 🔴 HOW IT REDDENS: put the predicate back to a bare presence check and
// `an_expired_token_is_not_logged_in` fails. The `+30 minutes` arm is the
// discriminator — without it, a predicate hard-wired to `false` would pass.
//
// Run via: npx tsx --test src/tests/unit/nav/the_logged_in_indicator_must_not_accept_a_token_the_server_refuses.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { isAuthenticated, type StorageLike } from "../../../lupin_app/static/js/nav/lupinNav";

const TOKEN_KEY = "lupin_access_token";

/** A storage seam holding exactly one key — the one both the nav and the panel read. */
function storageHolding( token: string | null ): StorageLike {
    return {
        getItem( key: string ): string | null { return key === TOKEN_KEY ? token : null; },
        removeItem( _key: string ): void { /* not exercised here */ },
    };
}

/**
 * A syntactically real JWT whose `exp` sits `offsetSeconds` from now.
 *
 * The signature is deliberately junk. That is not a shortcut — it is the point:
 * the client never verifies a signature, so a guard that needed a real one would be
 * measuring the server instead of the indicator. What is real here is the SHAPE and
 * the `exp` claim, which is everything the client can legitimately act on.
 */
function jwtExpiringIn( offsetSeconds: number ): string {
    const b64 = ( o: object ): string =>
        Buffer.from( JSON.stringify( o ) ).toString( "base64url" );
    const exp = Math.floor( Date.now() / 1000 ) + offsetSeconds;
    return [
        b64( { alg: "HS256", typ: "JWT" } ),
        b64( { sub: "0cf47e2d-d5a1-4cd4-addf-79810fd32b15",
               email: "ricardo.felipe.ruiz@gmail.com",
               roles: [ "user", "admin" ],
               exp,
               iat: exp - 1800 } ),
        "notarealsignature",
    ].join( "." );
}

// ---------------------------------------------------------------------------

test( "no token at all is not logged in", () => {
    // Control. Green before and after the fix — it says the predicate is wired to
    // the key at all, so a later arm's `false` means something.
    assert.equal( isAuthenticated( storageHolding( null ) ), false );
    assert.equal( isAuthenticated( storageHolding( "" ) ),   false );
} );

test( "a live token IS logged in", () => {
    // 🔴 THE DISCRIMINATOR, AND IT IS NOT OPTIONAL. Without it, `return false` passes
    // every other arm in this file and the nav would show Rick permanently logged out.
    assert.equal( isAuthenticated( storageHolding( jwtExpiringIn( 30 * 60 ) ) ), true );
} );

test( "an EXPIRED token is not logged in", () => {
    // 🔴 THE ONE THIS FILE EXISTS FOR. Rick's exact state: a token that is present,
    // well-formed, and past `exp`. The server answers 401 for it (measured); the bar
    // must not answer "logged in".
    const stale = jwtExpiringIn( -86400 );
    assert.equal(
        isAuthenticated( storageHolding( stale ) ),
        false,
        "the nav reports LOGGED IN for a token 24h past exp — the server refuses this " +
        "same string with 401, which is Rick's report on row 9d3a975e verbatim. " +
        "`isAuthenticated` is a presence check; it must consult the `exp` claim " +
        "(`decodeJwtClaims` / `jwtExpiryMs` already exist in multiplexer/auth/jwt.ts).",
    );
} );

test( "a token that cannot be decoded at all is not logged in", () => {
    // A string the server cannot possibly accept must not read as logged in either.
    // Fail-closed: when the bar knows least, it must not claim most.
    assert.equal( isAuthenticated( storageHolding( "not-a-jwt" ) ), false );
    assert.equal( isAuthenticated( storageHolding( "a.b" ) ),       false );
} );
