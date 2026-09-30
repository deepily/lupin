// THE NAV THAT ALL 17 PAGES ACTUALLY LOAD, MEASURED AGAINST WHAT THE SERVER ACCEPTS.
//
// Row ef16e88d. The sibling guard in this directory
// (`the_logged_in_indicator_must_not_accept_a_token_the_server_refuses.test.ts`)
// pins `nav/lupinNav.ts`. 🔴 NOTHING LOADS THAT FILE. The 2026.06.18 port doc defers
// the wiring deliberately, so the .ts is a completed port sitting beside the running
// system — CLAUDE.md § IMPLEMENTED BUT NOT INSTALLED. What Rick's browser executes is
// the 206-line classic-script IIFE `static/js/lupin-nav.js`, loaded by 17 pages
// (notifications.html:1198 among them) as `<script defer>`.
//
// So this file exists because a green sibling guard says nothing about the defect
// Rick can hit. It drives THE SHIPPED SOURCE TEXT of the live file.
//
// HOW IT REACHES A PRIVATE FUNCTION. The IIFE is self-contained by design ("No
// dependency on auth.js") and auto-runs `buildNav` on DOM ready, so it can be neither
// imported nor evaluated whole under `node --test`. This guard SLICES the auth-helpers
// block out of the file by its two banner comments — asserting each anchor matches
// EXACTLY ONCE, so a rename fails loudly here instead of silently measuring nothing —
// and evaluates that block with an injected `localStorage`. § A COORDINATE IS NOT A
// REFERENCE: the anchors are content, not line numbers.
//
// 🔴 THERE ARE NOW TWO JWT DECODERS IN THIS REPO, AND THAT IS DELIBERATE.
// `multiplexer/auth/jwt.ts` is an ES module; a classic script cannot import it, and
// the alternatives both cost 17 HTML edits. The duplication is approved (María,
// 2026-09-04) ON THE CONDITION THAT IT CANNOT DRIFT — which is what
// `the two decoders agree on every token in the corpus` below is for. That test is
// not decoration: it is the entire reason a second decoder was allowed to exist.
//
// Run via: npx tsx --test src/tests/unit/nav/the_live_nav_iife_must_not_vouch_for_a_token_the_server_refuses.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { jwtExpiryMs } from "../../../lupin_app/static/js/multiplexer/auth/jwt";

const NAV_JS = new URL( "../../../lupin_app/static/js/lupin-nav.js", import.meta.url );

// The two banner comments bracketing the auth helpers in the live file. Content
// anchors, deliberately — a line number would land wherever the file has drifted to.
const BLOCK_START = "// Auth helpers — read localStorage directly (no auth.js dependency)";
const BLOCK_END   = "// Active page detection";

interface NavAuthApi {
    getToken        : () => string | null;
    isAuthenticated : () => boolean;
    jwtExpiryMs     : ( token: string ) => number | null;
}

/**
 * Evaluate the live IIFE's auth-helpers block against an injected storage.
 *
 * Requires:
 *     - lupin-nav.js carries both banner anchors EXACTLY once
 *
 * Ensures:
 *     - returns the block's own functions, evaluated from the shipped source text
 *     - throws with a named reason when either anchor is missing or duplicated,
 *       so a rename can never degrade this guard into measuring nothing
 */
function liveNavAuth( token: string | null ): NavAuthApi {
    const src = readFileSync( NAV_JS, "utf8" );

    // § AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE. A slice that
    // silently found nothing would eval an empty body and every arm below would pass.
    const starts = src.split( BLOCK_START ).length - 1;
    const ends   = src.split( BLOCK_END ).length - 1;
    assert.equal( starts, 1, `lupin-nav.js: start anchor matched ${starts}x, expected exactly 1` );
    assert.equal( ends,   1, `lupin-nav.js: end anchor matched ${ends}x, expected exactly 1` );

    const body = src.split( BLOCK_START )[ 1 ]!.split( BLOCK_END )[ 0 ]!;
    const make = new Function(
        "localStorage",
        // `typeof` rather than a bare reference: BEFORE the fix the block has no
        // `jwtExpiryMs` at all, and a ReferenceError here would take the CONTROL arms
        // down with it — a control that cannot run in both arms is not a control.
        `${body}\n; return { getToken, isAuthenticated,\n`
        + `  jwtExpiryMs: typeof jwtExpiryMs === "function" ? jwtExpiryMs : undefined };`,
    ) as ( storage: { getItem: ( key: string ) => string | null } ) => NavAuthApi;

    return make( {
        getItem( key: string ): string | null {
            return key === "lupin_access_token" ? token : null;
        },
    } );
}

/**
 * A syntactically real JWT whose `exp` sits `offsetSeconds` from now.
 *
 * Constructed identically to the sibling guard's `jwtExpiringIn()` on purpose: two
 * guards that disagree about what a valid token looks like are two guards measuring
 * two different things. The signature is junk because the client never verifies one —
 * a guard needing a real signature would be measuring the server.
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

/** A JWT-shaped token whose payload is exactly `payload`, with no `exp` massaging. */
function jwtWithPayload( payload: object ): string {
    const b64 = ( o: object ): string =>
        Buffer.from( JSON.stringify( o ) ).toString( "base64url" );
    return [ b64( { alg: "HS256", typ: "JWT" } ), b64( payload ), "notarealsignature" ].join( "." );
}

// ---------------------------------------------------------------------------
// The predicate the 17 live pages run
// ---------------------------------------------------------------------------

test( "the live IIFE exposes the helpers this guard measures", () => {
    // 🔴 ASSERT THE CONTROL EXISTS BEFORE ASSERTING WHAT IT DOES. Every arm below
    // evaluates a sliced block; if the slice produced nothing, `new Function` would
    // still return an object and each `=== false` would pass on `undefined()`-free
    // paths. This arm is what makes the others' verdicts mean something.
    const api = liveNavAuth( null );
    assert.equal( typeof api.isAuthenticated, "function" );
    assert.equal( typeof api.getToken,        "function" );
    assert.equal( typeof api.jwtExpiryMs,     "function",
        "lupin-nav.js must expose its own jwtExpiryMs — the parity test below is the " +
        "only thing licensing a second decoder, and it cannot run without this." );
} );

test( "no token at all is not logged in", () => {
    // Control. GREEN IN BOTH ARMS — before the fix and after — so it says the
    // predicate is wired to the storage key at all. Without it, a later `false`
    // would be indistinguishable from a predicate that reads nothing.
    assert.equal( liveNavAuth( null ).isAuthenticated(), false );
    assert.equal( liveNavAuth( "" ).isAuthenticated(),   false );
} );

test( "a live token IS logged in", () => {
    // 🔴 THE DISCRIMINATOR. Without it `return false` satisfies every other arm and
    // the bar would show Rick permanently logged out. Green in both arms.
    assert.equal( liveNavAuth( jwtExpiringIn( 30 * 60 ) ).isAuthenticated(), true );
} );

test( "an EXPIRED token is not logged in", () => {
    // 🔴 THE ONE THIS FILE EXISTS FOR, on the copy that actually ships. Rick's state:
    // a token present, well-formed, and past `exp`. The access token lives 30 minutes
    // and the refresh token a week, so localStorage legitimately holds an expired
    // access token for hours — the ordinary case, not an edge one.
    assert.equal(
        liveNavAuth( jwtExpiringIn( -86400 ) ).isAuthenticated(),
        false,
        "lupin-nav.js reports LOGGED IN for a token 24h past exp. The server answers " +
        "401 for that same string — Rick's row 9d3a975e report verbatim. This is the " +
        "file all 17 pages load; fixing nav/lupinNav.ts does not reach it.",
    );
} );

test( "a token that cannot be decoded at all is not logged in", () => {
    // Fail closed: when the bar knows least it must not claim most. `"x"` is the
    // string three port-suite fixtures used to seed a "logged in" storage — it is
    // not a JWT and never was.
    assert.equal( liveNavAuth( "x" ).isAuthenticated(),         false );
    assert.equal( liveNavAuth( "not-a-jwt" ).isAuthenticated(), false );
    assert.equal( liveNavAuth( "a.b" ).isAuthenticated(),       false );
} );

test( "a decodable token carrying no exp is not logged in", () => {
    // A well-formed JWT with nothing to check is still nothing to check.
    assert.equal( liveNavAuth( jwtWithPayload( { email: "x@y.z" } ) ).isAuthenticated(), false );
} );

// ---------------------------------------------------------------------------
// The parity that licenses the duplication
// ---------------------------------------------------------------------------

/**
 * A token whose payload segment provably contains BOTH base64url substitution
 * characters, `-` and `_`.
 *
 * 🔴 THE FIRST VERSION OF THIS FIXTURE WAS NAMED FOR A PROPERTY IT DID NOT HAVE.
 * It was `{ email: "a+b/c?d=e", n: 0xfbf0 }`, whose payload encodes to
 * `eyJlbWFpbCI6ImErYi9jP2Q9ZSIsIm4iOjY0NDk2fQ` — not one `-`, not one `_`. Chosen
 * because `+` and `/` appear in the plaintext, which is not where base64url
 * substitution happens. With it in place, deleting the `-`/`_` translation from the
 * IIFE decoder left this whole file GREEN: a real drift, unseen. § COVERAGE MEASURES
 * WHETHER A LINE RAN, NEVER WHETHER THE TEST COULD HAVE NOTICED IT RUNNING WRONG.
 *
 * The assertion below is not ceremony — it is what stops that recurring.
 */
const BASE64URL_ALPHABET_TOKEN = jwtWithPayload( { exp: 1893456000, s: "\u03ff\u07ff" } );

/**
 * One corpus, run through both decoders. Every entry is a shape one decoder could
 * get right and the other wrong: segment counts, base64url alphabet, invalid base64
 * length, non-object payloads, and `exp` of the wrong type.
 */
const CORPUS: Array< [ string, string ] > = [
    [ "live token",                jwtExpiringIn( 30 * 60 ) ],
    [ "expired token",             jwtExpiringIn( -86400 ) ],
    [ "exp exactly now",           jwtExpiringIn( 0 ) ],
    [ "no exp claim",              jwtWithPayload( { email: "x@y.z" } ) ],
    [ "exp as a string",           jwtWithPayload( { exp: "1234567890" } ) ],
    [ "exp as null",               jwtWithPayload( { exp: null } ) ],
    [ "payload with base64url -_", BASE64URL_ALPHABET_TOKEN ],
    [ "empty string",              "" ],
    [ "one segment",               "abc" ],
    [ "two segments",              "a.b" ],
    [ "four segments",             "a.b.c.d" ],
    [ "payload is not base64",     "a.!!!!.c" ],
    [ "payload base64 len % 4 == 1", "a.YWJjZGU.c" ],
    [ "payload is a JSON number",  `a.${Buffer.from( "5" ).toString( "base64url" )}.c` ],
    [ "payload is a JSON string",  `a.${Buffer.from( '"hi"' ).toString( "base64url" )}.c` ],
    [ "payload is invalid JSON",   `a.${Buffer.from( "{nope" ).toString( "base64url" )}.c` ],
    [ "payload is a JSON array",   `a.${Buffer.from( "[1,2]" ).toString( "base64url" )}.c` ],
];

test( "the two decoders agree on every token in the corpus", () => {
    // 🔴 THE CONDITION THE SECOND DECODER WAS APPROVED UNDER. `multiplexer/auth/jwt.ts`
    // is an ES module and 17 pages load the nav as a classic script, so the IIFE cannot
    // import it. Two derivations of one value that agree only by careful copying
    // diverge the first time somebody edits one — CLAUDE.md § TWO SIDES THAT DERIVE ONE
    // VALUE BY DIFFERENT ROUTES ARE NOT AGREEING, THEY ARE COINCIDING. This arm is what
    // converts "they happen to match today" into "they cannot silently stop matching".
    const iife = liveNavAuth( null );
    for ( const [ name, token ] of CORPUS ) {
        assert.equal(
            iife.jwtExpiryMs( token ),
            jwtExpiryMs( token ),
            `the two JWT decoders DISAGREE on "${name}". lupin-nav.js said ` +
            `${iife.jwtExpiryMs( token )}, multiplexer/auth/jwt.ts said ` +
            `${jwtExpiryMs( token )}. They are a deliberate duplication held together ` +
            `by nothing but this assertion — reconcile them, do not weaken this test.`,
        );
    }
} );

test( "the base64url fixture actually carries the characters it is named for", () => {
    // 🔴 ASSERT THE FIXTURE HAS THE PROPERTY BEFORE TRUSTING WHAT IT MEASURES. Without
    // this arm, the corpus entry above silently stopped exercising the one line of the
    // decoder that translates the base64url alphabet — and mutation M2, which deletes
    // exactly that line, SURVIVED a green run of this file. Measured, 2026-09-04.
    const payload = BASE64URL_ALPHABET_TOKEN.split( "." )[ 1 ]!;
    assert.ok( payload.includes( "-" ), `fixture payload carries no "-": ${payload}` );
    assert.ok( payload.includes( "_" ), `fixture payload carries no "_": ${payload}` );
} );

test( "the corpus is big enough to be worth running", () => {
    // A loop over an empty corpus passes every assertion inside it.
    // § A COMPARISON WHOSE TWO SIDES COME FROM ONE SOURCE — state the denominator.
    assert.ok( CORPUS.length >= 15, `corpus holds ${CORPUS.length} tokens, expected >= 15` );
} );
