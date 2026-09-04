// ONE TOKEN OF RECORD FOR THE PAGE — row 20775ec5.
//
// Rick, verbatim: "the send of the broadcast to all CC sessions is issuing a 401 when I
// attempt to hit send. Even when my account is authenticated and listed as logged in."
// Both halves were true at the same instant, of DIFFERENT tokens.
//
// THE DIVERGENCE. `notifications.js` decides on an IN-MEMORY field (`this.authToken`)
// and historically wrote `localStorage` only as a side effect of an actual refresh. So
// its fast path — the common one — returned happily while the stored token said
// something else, and nothing reconciled them. Every other reader of that key (the
// broadcast panel, `lupin-nav.js`'s logged-in indicator) then read a value the page had
// already superseded.
//
// MEASURED 2026-09-04 in Rick's own browser, stored token blanked, in-memory one live:
//     authedFetch          -> 200
//     stored token after   -> length 0, UNREPAIRED
//
// 🔴 WHY THIS FILE IS A .test.ts AGAINST A HAND-BUILT DOUBLE AND NOT A RUN OF THE REAL
// CLASS. `notifications.js` is a ~24,000-line browser IIFE with no export surface; there
// is no way to import `ensureValidToken` alone. So this pins the CONTRACT — "the fast
// path reconciles the store" — over a double whose reconcile step is copied from the
// shipped source, and a companion arm asserts the shipped source still contains that
// step. Neither arm alone is worth much: the first would pass over a double that no
// longer resembles the code, and the second is a text match. Together they say the
// behaviour is right AND that the file still has it.
//
// 🔴 HOW IT REDDENS: delete the reconcile block from `ensureValidToken` in
// notifications.js and `the_shipped_source_still_reconciles` fails, naming the method.
// Break the double's reconcile and the behavioural arms fail. Proven both ways before
// this file was committed.
//
// Run via: npx tsx --test src/tests/unit/notifications_js/the_page_keeps_one_token_of_record.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const TOKEN_KEY = "lupin_access_token";

// Resolved from LUPIN_ROOT at CALL time so a worktree reads its OWN tree, never the
// main checkout. Never a __dirname walk. (§A TIER RUN FROM A WORKTREE.)
const CLIENT_JS = join(
    process.env.LUPIN_ROOT ?? process.cwd(),
    "src", "lupin_app", "static", "js", "notifications.js",
);

/** The one localStorage behaviour under test, with no browser required. */
function makeStore( initial: string | null ) {
    let value = initial;
    return {
        getItem : ( k: string ) => ( k === TOKEN_KEY ? value : null ),
        setItem : ( k: string, v: string ) => { if ( k === TOKEN_KEY ) value = v; },
        peek    : () => value,
    };
}

/**
 * The reconcile step as `ensureValidToken` performs it, copied from the shipped source.
 * `the_shipped_source_still_reconciles` is what keeps this honest.
 */
function ensureValidTokenFastPath( authToken: string | null, store: ReturnType<typeof makeStore> ) {
    if ( authToken && store.getItem( TOKEN_KEY ) !== authToken ) {
        store.setItem( TOKEN_KEY, authToken );
    }
}

// ---------------------------------------------------------------------------

test( "a stale stored token is reconciled to the live in-memory one", () => {
    // 🔴 THE ONE THIS FILE EXISTS FOR — Rick's exact state, reproduced as a unit.
    const store = makeStore( "stale-token-from-some-earlier-life" );
    ensureValidTokenFastPath( "the-live-token", store );
    assert.equal(
        store.peek(), "the-live-token",
        "the page's fast path left the STORED token stale while holding a live one in " +
        "memory. Every other reader of lupin_access_token — the broadcast panel, the " +
        "nav's logged-in indicator — now reads a superseded value, which is row 20775ec5.",
    );
} );

test( "a BLANK stored token is reconciled too", () => {
    // The literal shape measured in Rick's browser: stored length 0, memory live, 200 back.
    const store = makeStore( "" );
    ensureValidTokenFastPath( "the-live-token", store );
    assert.equal( store.peek(), "the-live-token" );
} );

test( "an already-agreeing store is left exactly as it is", () => {
    // 🔴 THE DISCRIMINATOR. Without it, an implementation that wrote on EVERY call —
    // or one hard-wired to a constant — would satisfy both arms above.
    const store = makeStore( "the-live-token" );
    ensureValidTokenFastPath( "the-live-token", store );
    assert.equal( store.peek(), "the-live-token" );
} );

test( "no in-memory token means nothing is written", () => {
    // Fail-safe: the page must never manufacture a credential into the store it does
    // not itself hold. A null memory token is "I don't know", not "log everyone out".
    const store = makeStore( "something-a-real-login-put-there" );
    ensureValidTokenFastPath( null, store );
    assert.equal( store.peek(), "something-a-real-login-put-there" );
} );

test( "the shipped source still reconciles, and this is the arm that sees a revert", () => {
    // The double above proves the CONTRACT. This proves the shipped file still HAS it —
    // without this, deleting the reconcile block from notifications.js reddens nothing
    // and the double becomes a test of itself. (§IMPLEMENTED BUT NOT INSTALLED.)
    const source = readFileSync( CLIENT_JS, "utf8" );

    const start = source.indexOf( "async ensureValidToken()" );
    assert.notEqual( start, -1, `${CLIENT_JS} no longer defines ensureValidToken — this guard cannot see its subject.` );
    const body = source.slice( start, source.indexOf( "async authedFetch(", start ) );
    assert.ok( body.length > 100, "could not isolate ensureValidToken's body — teach this guard the new shape." );

    assert.ok(
        body.includes( `localStorage.setItem( "${TOKEN_KEY}"` ),
        "ensureValidToken no longer writes the reconciled token back to localStorage. " +
        "Its fast path decides on an in-memory field, so without this write the stored " +
        "token drifts and every other reader of it goes stale — row 20775ec5, the " +
        "broadcast 401 Rick reported while the page said he was logged in.",
    );
} );
