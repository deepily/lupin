// Lupin nav-bar TS port — unit tests.
//
// TS port of `src/lupin_app/static/js/lupin-nav.js`. Drives the auth helpers,
// active-page detection, visibility filter, HTML render, element build, event
// wiring (logout + hamburger), mount, and the DOM-ready scheduler — all
// deterministically via injected seams (storage / pathname / navigate).
// Target: c8 --100 lines/branches/functions on the new .ts.
//
// Run via: npx tsx --test src/tests/unit/nav/lupin_nav_port.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
    NAV_ITEMS,
    getToken,
    getUserData,
    isAuthenticated,
    isAdmin,
    getUserEmail,
    isActivePage,
    computeNavState,
    visibleNavItems,
    renderNavInnerHtml,
    buildNavElement,
    wireEvents,
    mountNav,
    scheduleMount,
    type NavState,
    type StorageLike,
} from "../../../lupin_app/static/js/nav/lupinNav";

before(() => {
    if ( typeof globalThis.document === "undefined" ) {
        GlobalRegistrator.register();
    }
});

beforeEach(() => {
    if ( globalThis.document !== undefined ) {
        document.body.replaceChildren();
        document.body.removeAttribute( "style" );
    }
});

// ---------------------------------------------------------------------------
// Test doubles / helpers
// ---------------------------------------------------------------------------

interface SpyStorage extends StorageLike {
    removed: string[];
}

function makeStorage( data: Record<string, string> = {} ): SpyStorage {
    const store: Record<string, string> = { ...data };
    const removed: string[] = [];
    return {
        getItem    : ( k ) => ( k in store ? store[ k ]! : null ),
        removeItem : ( k ) => { removed.push( k ); delete store[ k ]; },
        removed,
    };
}

const ADMIN_USER = JSON.stringify( { role: "admin", email: "boss@lupin.ai" } );
const PLAIN_USER = JSON.stringify( { role: "user", email: "user@lupin.ai" } );
const NO_EMAIL_USER = JSON.stringify( { role: "admin" } );

function state( over: Partial<NavState> = {} ): NavState {
    return { authenticated: false, admin: false, email: null, pathname: "/app", ...over };
}

// ===========================================================================
// Auth helpers
// ===========================================================================

test( "getToken returns the stored token or null", () => {
    assert.equal( getToken( makeStorage( { lupin_access_token: "tok-123" } ) ), "tok-123" );
    assert.equal( getToken( makeStorage() ), null );
} );

test( "getUserData parses valid JSON, returns null for absent, swallows corrupt JSON", () => {
    assert.deepEqual( getUserData( makeStorage( { user_data: PLAIN_USER } ) ), { role: "user", email: "user@lupin.ai" } );
    assert.equal( getUserData( makeStorage() ), null );                              // raw is null → null
    assert.equal( getUserData( makeStorage( { user_data: "{not json" } ) ), null );  // JSON.parse throws → catch → null
} );

/**
 * A syntactically real JWT expiring 30 minutes from now.
 *
 * 🔴 THE FIXTURES HERE USED THE LITERAL STRING "x", which is not a JWT at all. That was
 * invisible while `isAuthenticated` was a presence check — any non-empty string satisfied
 * it. Row ef16e88d made the predicate consult `exp`, "x" is correctly refused as
 * undecodable, and three tests here went red.
 *
 * ⚠️ THEY WERE NOT CATCHING A BREAK, and the distinction is worth keeping. Two of them
 * (`computeNavState integrates…`, `mountNav injects…`) never meant to assert anything
 * about tokens — they needed A LOGGED-IN STORAGE and reached for the shortest string that
 * used to produce one. The FIXTURE was carrying the old contract, not the assertion.
 * Updating it corrects the test's model of the world; it does not weaken it.
 *
 * The signature is junk on purpose — the client never verifies one, so demanding a real
 * signature would measure the server instead of the nav. Construction is kept identical to
 * the sibling guard's `jwtExpiringIn()` so the two files cannot drift into disagreeing
 * about what a valid token looks like.
 */
function liveJwt(): string {
    const b64 = ( o: object ): string =>
        Buffer.from( JSON.stringify( o ) ).toString( "base64url" );
    const exp = Math.floor( Date.now() / 1000 ) + 1800;
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

test( "isAuthenticated accepts a LIVE token and refuses a stale or absent one", () => {
    // ⚠️ RENAMED FROM "reflects token presence" — which named the defect. Presence is
    // exactly what it must NOT reflect: a stored string the server refuses. The expiry
    // and undecodable arms live in their own guard
    // (the_logged_in_indicator_must_not_accept_a_token_the_server_refuses.test.ts).
    assert.equal( isAuthenticated( makeStorage( { lupin_access_token: liveJwt() } ) ), true );
    assert.equal( isAuthenticated( makeStorage( { lupin_access_token: "x" } ) ), false,
        "a non-JWT string is not a session — the defect row ef16e88d fixed" );
    assert.equal( isAuthenticated( makeStorage() ), false );
} );

test( "isAdmin is true only for an admin-role user", () => {
    assert.equal( isAdmin( makeStorage( { user_data: ADMIN_USER } ) ), true );
    assert.equal( isAdmin( makeStorage( { user_data: PLAIN_USER } ) ), false );  // user present, role != admin
    assert.equal( isAdmin( makeStorage() ), false );                            // user null
} );

test( "getUserEmail returns email, or null when absent / no user", () => {
    assert.equal( getUserEmail( makeStorage( { user_data: PLAIN_USER } ) ), "user@lupin.ai" );
    assert.equal( getUserEmail( makeStorage( { user_data: NO_EMAIL_USER } ) ), null );  // user present, email undefined → null
    assert.equal( getUserEmail( makeStorage() ), null );                                // user null → null
} );

// ===========================================================================
// Active page detection
// ===========================================================================

test( "isActivePage exact-matches /app and startsWith for the rest", () => {
    assert.equal( isActivePage( "/app", "/app" ), true );
    assert.equal( isActivePage( "/app", "/app/" ), true );
    assert.equal( isActivePage( "/app", "/app/notifications" ), false );          // /app does NOT light up on sub-pages
    assert.equal( isActivePage( "/app/admin", "/app/admin/users" ), true );       // startsWith
    assert.equal( isActivePage( "/app/admin", "/app/notifications" ), false );
} );

// ===========================================================================
// State + visibility
// ===========================================================================

test( "computeNavState integrates auth/admin/email/pathname", () => {
    const s = computeNavState( makeStorage( { lupin_access_token: liveJwt(), user_data: ADMIN_USER } ), "/app/admin" );
    assert.deepEqual( s, { authenticated: true, admin: true, email: "boss@lupin.ai", pathname: "/app/admin" } );
} );

test( "visibleNavItems hides auth items for anonymous users", () => {
    const visible = visibleNavItems( NAV_ITEMS, state( { authenticated: false, admin: false } ) );
    assert.deepEqual( visible.map( ( i ) => i.label ), [ "Home" ] );
} );

test( "visibleNavItems shows non-admin items for an authenticated non-admin", () => {
    const visible = visibleNavItems( NAV_ITEMS, state( { authenticated: true, admin: false } ) );
    assert.deepEqual( visible.map( ( i ) => i.label ), [ "Home", "Notifications", "Profile" ] );
} );

test( "visibleNavItems shows every item for an authenticated admin", () => {
    const visible = visibleNavItems( NAV_ITEMS, state( { authenticated: true, admin: true } ) );
    assert.equal( visible.length, NAV_ITEMS.length );
} );

// ===========================================================================
// Rendering
// ===========================================================================

test( "renderNavInnerHtml (admin) shows separator, admin links, active class, email + logout", () => {
    const html = renderNavInnerHtml( state( { authenticated: true, admin: true, email: "boss@lupin.ai", pathname: "/app/admin" } ) );
    assert.match( html, /lupin-nav-brand/ );
    assert.match( html, /lupin-nav-separator/ );                                  // admin separator emitted
    assert.match( html, /data-testid="nav-admin-link"/ );                         // admin link present
    assert.match( html, /class="lupin-nav-link lupin-nav-active" data-testid="nav-admin-link"/ );  // Admin is active on /app/admin
    assert.match( html, /data-testid="nav-user-email">boss@lupin\.ai/ );          // email span
    assert.match( html, /data-testid="nav-logout-btn"/ );                         // logout button
    assert.doesNotMatch( html, /nav-login-link/ );                               // no login link when authed+email
} );

test( "renderNavInnerHtml (anonymous) shows only Home + login, no admin/logout", () => {
    const html = renderNavInnerHtml( state( { authenticated: false, admin: false, email: null, pathname: "/app" } ) );
    assert.match( html, /data-testid="nav-home-link"/ );
    assert.doesNotMatch( html, /lupin-nav-separator/ );                           // no admin items → no separator
    assert.doesNotMatch( html, /data-testid="nav-notifications-link"/ );          // auth item hidden
    assert.match( html, /data-testid="nav-login-link"/ );                         // login link
    assert.doesNotMatch( html, /nav-logout-btn/ );
} );

test( "renderNavInnerHtml (authed, non-admin) shows logout but no admin separator", () => {
    const html = renderNavInnerHtml( state( { authenticated: true, admin: false, email: "user@lupin.ai", pathname: "/app/notifications" } ) );
    assert.match( html, /data-testid="nav-logout-btn"/ );
    assert.doesNotMatch( html, /lupin-nav-separator/ );                           // adminSectionStarted never set
    assert.match( html, /class="lupin-nav-link lupin-nav-active" data-testid="nav-notifications-link"/ );  // active on its page
} );

test( "renderNavInnerHtml (authed, NO email) falls back to the login link", () => {
    // authenticated true but email null → `authenticated && email` is false → else branch.
    const html = renderNavInnerHtml( state( { authenticated: true, admin: false, email: null, pathname: "/app/notifications" } ) );
    assert.match( html, /data-testid="nav-login-link"/ );
    assert.doesNotMatch( html, /nav-logout-btn/ );
} );

test( "buildNavElement returns a configured <nav> element", () => {
    const nav = buildNavElement( document, state( { authenticated: true, admin: true, email: "boss@lupin.ai", pathname: "/app/admin" } ) );
    assert.equal( nav.tagName, "NAV" );
    assert.equal( nav.id, "lupin-nav" );
    assert.equal( nav.className, "lupin-nav" );
    assert.ok( nav.querySelector( ".lupin-nav-brand" ) );
    assert.ok( nav.querySelector( '[data-testid="nav-logout-btn"]' ) );
} );

// ===========================================================================
// Event wiring
// ===========================================================================

test( "wireEvents: logout clears tokens and navigates to login", () => {
    const storage = makeStorage( { lupin_access_token: "x", lupin_refresh_token: "y", user_data: ADMIN_USER } );
    const nav = buildNavElement( document, state( { authenticated: true, admin: true, email: "boss@lupin.ai", pathname: "/app/admin" } ) );
    const navigated: string[] = [];
    wireEvents( nav, storage, ( url ) => navigated.push( url ) );

    ( nav.querySelector<HTMLButtonElement>( ".lupin-nav-logout" ) )!.click();

    assert.deepEqual( storage.removed, [ "lupin_access_token", "lupin_refresh_token", "user_data" ] );
    assert.deepEqual( navigated, [ "/app/auth/login" ] );
} );

test( "wireEvents: hamburger toggles open class on links and right rail", () => {
    const nav = buildNavElement( document, state( { authenticated: true, admin: true, email: "boss@lupin.ai", pathname: "/app/admin" } ) );
    wireEvents( nav, makeStorage(), () => {} );

    const toggle = nav.querySelector<HTMLButtonElement>( ".lupin-nav-toggle" )!;
    const links  = nav.querySelector<HTMLElement>( ".lupin-nav-links" )!;
    const right  = nav.querySelector<HTMLElement>( ".lupin-nav-right" )!;

    assert.equal( links.classList.contains( "lupin-nav-open" ), false );
    toggle.click();
    assert.equal( links.classList.contains( "lupin-nav-open" ), true );
    assert.equal( right.classList.contains( "lupin-nav-open" ), true );
    toggle.click();
    assert.equal( links.classList.contains( "lupin-nav-open" ), false );
    assert.equal( right.classList.contains( "lupin-nav-open" ), false );
} );

test( "wireEvents: anonymous nav has no logout button (no-op branch)", () => {
    const nav = buildNavElement( document, state( { authenticated: false, admin: false, email: null, pathname: "/app" } ) );
    // No logout button exists → the logoutBtn branch is skipped; must not throw.
    assert.doesNotThrow( () => wireEvents( nav, makeStorage(), () => {} ) );
    assert.ok( nav.querySelector( ".lupin-nav-logout" ) === null );
} );

test( "wireEvents: missing toggle/links short-circuits the hamburger wiring", () => {
    const bare = document.createElement( "nav" );  // no toggle, no links
    assert.doesNotThrow( () => wireEvents( bare, makeStorage(), () => {} ) );
} );

test( "wireEvents: toggle present but no right rail → inner navRight guard is false", () => {
    const nav = document.createElement( "nav" );
    nav.innerHTML =
        '<button class="lupin-nav-toggle"></button>' +
        '<div class="lupin-nav-links"></div>';  // deliberately NO .lupin-nav-right
    wireEvents( nav, makeStorage(), () => {} );

    const toggle = nav.querySelector<HTMLButtonElement>( ".lupin-nav-toggle" )!;
    const links  = nav.querySelector<HTMLElement>( ".lupin-nav-links" )!;
    toggle.click();
    assert.equal( links.classList.contains( "lupin-nav-open" ), true );  // links still toggles; navRight guard skipped
} );

// ===========================================================================
// Mount
// ===========================================================================

test( "mountNav injects the nav as body's first child, pads the body, and wires navigation", () => {
    const sentinel = document.createElement( "main" );
    document.body.appendChild( sentinel );

    const storage = makeStorage( { lupin_access_token: liveJwt(), user_data: ADMIN_USER } );
    const fakeWin = { location: { pathname: "/app/admin", href: "" } } as unknown as Window;

    const nav = mountNav( document, fakeWin, storage );

    assert.ok( document.body.firstChild === nav );           // injected at the top
    assert.equal( nav.id, "lupin-nav" );
    assert.equal( document.body.style.paddingTop, "56px" );  // body padded

    // The production navigate seam writes win.location.href — exercise it via logout.
    ( nav.querySelector<HTMLButtonElement>( ".lupin-nav-logout" ) )!.click();
    assert.equal( ( fakeWin as unknown as { location: { href: string } } ).location.href, "/app/auth/login" );
    assert.deepEqual( storage.removed, [ "lupin_access_token", "lupin_refresh_token", "user_data" ] );
} );

// ===========================================================================
// Scheduler
// ===========================================================================

test( "scheduleMount defers to DOMContentLoaded while the document is loading", () => {
    let mounted = 0;
    const listeners: Array<{ ev: string; fn: unknown }> = [];
    const fakeDoc = {
        readyState       : "loading",
        addEventListener : ( ev: string, fn: unknown ) => listeners.push( { ev, fn } ),
    } as unknown as Document;

    scheduleMount( fakeDoc, () => { mounted++; } );

    assert.equal( mounted, 0 );                       // not mounted yet
    assert.equal( listeners.length, 1 );
    assert.equal( listeners[ 0 ]!.ev, "DOMContentLoaded" );
} );

test( "scheduleMount mounts immediately when the document is already ready", () => {
    let mounted = 0;
    const fakeDoc = { readyState: "complete" } as unknown as Document;

    scheduleMount( fakeDoc, () => { mounted++; } );

    assert.equal( mounted, 1 );
} );
