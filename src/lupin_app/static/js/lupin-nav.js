/**
 * Lupin Navigation Bar — self-contained IIFE.
 *
 * Reads auth state from localStorage (lupin_access_token, user_data)
 * and injects a top nav bar into every page. No dependency on auth.js.
 *
 * Generated on: 2026-02-21
 */
( function () {
    "use strict";

    // ========================================================================
    // Nav items — data-driven so adding pages is a one-line change
    // ========================================================================

    const NAV_ITEMS = [
        { label : "Home",            url : "/app",                       icon : "home",   auth : false, admin : false, testid : "nav-home-link"           },
        { label : "Notifications",   url : "/app/notifications",         icon : "bell",   auth : true,  admin : false, testid : "nav-notifications-link"  },
        { label : "Profile",         url : "/app/auth/profile",          icon : "user",   auth : true,  admin : false, testid : "nav-profile-link"        },
        { label : "Admin",           url : "/app/admin",                 icon : "shield", auth : true,  admin : true,  testid : "nav-admin-link"          },
        { label : "Users",           url : "/app/admin/users",           icon : "users",  auth : true,  admin : true,  testid : "nav-admin-users-link"    },
        { label : "Snapshots",       url : "/app/admin/snapshots",       icon : "camera", auth : true,  admin : true,  testid : "nav-admin-snapshots-link"},
        { label : "Ratification",    url : "/app/admin/proxy-ratify",    icon : "check",  auth : true,  admin : true,  testid : "nav-admin-ratify-link"   },
        { label : "Trust",           url : "/app/admin/proxy-dashboard", icon : "chart",  auth : true,  admin : true,  testid : "nav-admin-trust-link"    },
        { label : "Dev Tools",       url : "/app/admin/dev-tools",       icon : "wrench", auth : true,  admin : true,  testid : "nav-admin-devtools-link" }
    ];

    // ========================================================================
    // SVG icon sprites (inline to avoid extra network requests)
    // ========================================================================

    const ICONS = {
        home   : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>',
        bell   : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>',
        user   : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
        shield : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
        users  : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>',
        camera : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.35-4.35"></path></svg>',
        check  : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><path d="m9 12 2 2 4-4"></path></svg>',
        chart  : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path></svg>',
        wrench : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>',
        logout : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>',
        login  : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path><polyline points="10 17 15 12 10 7"></polyline><line x1="15" y1="12" x2="3" y2="12"></line></svg>',
        menu   : '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>'
    };

    // ========================================================================
    // Auth helpers — read localStorage directly (no auth.js dependency)
    // ========================================================================

    function getToken() {
        return localStorage.getItem( "lupin_access_token" );
    }

    function getUserData() {
        try {
            const raw = localStorage.getItem( "user_data" );
            return raw ? JSON.parse( raw ) : null;
        } catch ( e ) {
            return null;
        }
    }

    /**
     * Decode one base64url segment to a UTF-8 string, or null on malformed input.
     *
     * 🔴 SECOND DECODER — SEE THE BANNER NOTE BELOW. Constructed to be behaviourally
     * identical to `decodeSegment` in multiplexer/auth/jwt.ts, line for line.
     */
    function decodeJwtSegment( segment ) {
        const base64    = segment.replace( /-/g, "+" ).replace( /_/g, "/" );
        const remainder = base64.length % 4;
        if ( remainder === 1 ) return null;   // not a valid base64 length
        const padded = remainder === 0 ? base64 : base64 + "=".repeat( 4 - remainder );
        let binary;
        try {
            binary = atob( padded );
        } catch ( e ) {
            return null;                      // non-base64 characters
        }
        const bytes = Uint8Array.from( binary, function ( ch ) { return ch.charCodeAt( 0 ); } );
        return new TextDecoder().decode( bytes );
    }

    /** Claims payload of a JWT, or null when it is not a well-formed three-segment JWT. */
    function decodeJwtClaims( token ) {
        const segments = token.split( "." );
        if ( segments.length !== 3 ) return null;
        const json = decodeJwtSegment( segments[ 1 ] );
        if ( json === null ) return null;
        let parsed;
        try {
            parsed = JSON.parse( json );
        } catch ( e ) {
            return null;
        }
        if ( typeof parsed !== "object" || parsed === null ) return null;
        return parsed;
    }

    /**
     * Access-token expiry as ms-epoch, or null if absent/malformed.
     *
     * 🔴 THIS IS A SECOND COPY OF `jwtExpiryMs` FROM multiplexer/auth/jwt.ts, AND THE
     * DUPLICATION IS DELIBERATE AND APPROVED (2026-09-04). This file is loaded by 17
     * pages as a classic `<script defer>` and is self-contained by design, so it cannot
     * import an ES module. The alternatives were converting all 17 script tags to
     * `type="module"`, or introducing a new global loaded ahead of the nav on all 17.
     *
     * ⚠️ WHAT HOLDS THE TWO TOGETHER IS NOT CARE, IT IS A TEST. Two derivations of one
     * value that agree only by careful copying diverge the first time somebody edits
     * one of them. `src/tests/unit/nav/the_live_nav_iife_must_not_vouch_for_a_token_the_server_refuses.test.ts`
     * runs a 17-token corpus through BOTH decoders and fails the moment their answers
     * differ. If you edit either copy, that guard is the thing that tells you.
     */
    function jwtExpiryMs( token ) {
        const claims = decodeJwtClaims( token );
        if ( claims === null ) return null;
        if ( typeof claims.exp !== "number" ) return null;
        return claims.exp * 1000;
    }

    /**
     * Is the stored access token one the server will still accept?
     *
     * 🔴 THIS WAS `return !!getToken();` — A PRESENCE CHECK ON A STRING (row ef16e88d).
     * It never decoded the token, never read `exp` and never asked the server, while
     * driving the rendered "email + Logout" half of the bar. Measured by Maya in Rick's
     * own browser: a syntactically valid JWT with `exp` 86,400s in the past returned
     * TRUE here while the SAME string came back 401 from the server.
     *
     * ⚠️ That is why his row 9d3a975e report read as a contradiction — "a 401 even when
     * my account is authenticated and listed as logged in". Both halves were true of one
     * token at one instant, and the nav is the half that was lying. The access token
     * lives 30 minutes and the refresh token a week, so localStorage legitimately holds
     * an expired access token for hours: the ordinary case, not an edge one.
     *
     * ⚠️ AND A UI THAT SAYS "logged in" IS A REASSURANCE, WHICH IS THE EXPENSIVE KIND OF
     * WRONG — it does not merely misinform, it stops the reader checking.
     *
     * Fails CLOSED. An undecodable token, or one carrying no `exp`, is not vouched for:
     * the whole defect was a predicate that said yes when it did not know.
     */
    function isAuthenticated() {
        const token = getToken();
        if ( !token ) return false;
        const expiryMs = jwtExpiryMs( token );
        if ( expiryMs === null ) return false;
        return Date.now() < expiryMs;
    }

    function isAdmin() {
        const user = getUserData();
        return user && user.role === "admin";
    }

    function getUserEmail() {
        const user = getUserData();
        return user ? user.email : null;
    }

    // ========================================================================
    // Active page detection
    // ========================================================================

    function isActivePage( itemUrl ) {
        const path = window.location.pathname;

        // Exact match for /app (landing)
        if ( itemUrl === "/app" ) {
            return path === "/app" || path === "/app/";
        }

        // startsWith for all other pages
        return path.startsWith( itemUrl );
    }

    // ========================================================================
    // Build and inject the nav bar
    // ========================================================================

    function buildNav() {
        const authenticated = isAuthenticated();
        const admin         = isAdmin();
        const email         = getUserEmail();

        // Filter nav items by auth/admin state
        const visibleItems = NAV_ITEMS.filter( function ( item ) {
            if ( item.auth && !authenticated ) return false;
            if ( item.admin && !admin ) return false;
            return true;
        } );

        // Build HTML
        const nav = document.createElement( "nav" );
        nav.id = "lupin-nav";
        nav.className = "lupin-nav";

        let html = '<div class="lupin-nav-inner">';

        // Brand
        html += '<a href="/app" class="lupin-nav-brand">Lupin</a>';

        // Hamburger toggle (mobile)
        html += '<button class="lupin-nav-toggle" aria-label="Toggle navigation" data-testid="nav-mobile-toggle-btn">' + ICONS.menu + '</button>';

        // Nav links
        html += '<div class="lupin-nav-links">';

        // Admin separator flag
        let adminSectionStarted = false;

        visibleItems.forEach( function ( item ) {
            // Add separator before first admin item
            if ( item.admin && !adminSectionStarted ) {
                adminSectionStarted = true;
                html += '<span class="lupin-nav-separator"></span>';
            }

            const active = isActivePage( item.url ) ? " lupin-nav-active" : "";
            const icon   = ICONS[ item.icon ] || "";
            html += '<a href="' + item.url + '" class="lupin-nav-link' + active + '" data-testid="' + item.testid + '">' + icon + '<span>' + item.label + '</span></a>';
        } );

        html += '</div>'; // end .lupin-nav-links

        // Right side — user email + logout OR login
        html += '<div class="lupin-nav-right">';
        if ( authenticated && email ) {
            html += '<span class="lupin-nav-email" data-testid="nav-user-email">' + email + '</span>';
            html += '<button class="lupin-nav-logout" title="Logout" data-testid="nav-logout-btn">' + ICONS.logout + ' Logout</button>';
        } else {
            html += '<a href="/app/auth/login" class="lupin-nav-login" data-testid="nav-login-link">' + ICONS.login + ' Login</a>';
        }
        html += '</div>'; // end .lupin-nav-right

        html += '</div>'; // end .lupin-nav-inner

        nav.innerHTML = html;

        // Inject as first child of body
        document.body.insertBefore( nav, document.body.firstChild );

        // Add body padding to account for fixed nav
        document.body.style.paddingTop = "56px";

        // Wire up events
        wireEvents( nav );
    }

    // ========================================================================
    // Event handlers
    // ========================================================================

    function wireEvents( nav ) {
        // Logout button
        const logoutBtn = nav.querySelector( ".lupin-nav-logout" );
        if ( logoutBtn ) {
            logoutBtn.addEventListener( "click", function () {
                localStorage.removeItem( "lupin_access_token" );
                localStorage.removeItem( "lupin_refresh_token" );
                localStorage.removeItem( "user_data" );
                window.location.href = "/app/auth/login";
            } );
        }

        // Hamburger toggle
        const toggleBtn = nav.querySelector( ".lupin-nav-toggle" );
        const navLinks  = nav.querySelector( ".lupin-nav-links" );
        const navRight  = nav.querySelector( ".lupin-nav-right" );

        if ( toggleBtn && navLinks ) {
            toggleBtn.addEventListener( "click", function () {
                navLinks.classList.toggle( "lupin-nav-open" );
                if ( navRight ) navRight.classList.toggle( "lupin-nav-open" );
            } );
        }
    }

    // ========================================================================
    // Initialize on DOM ready
    // ========================================================================

    if ( document.readyState === "loading" ) {
        document.addEventListener( "DOMContentLoaded", buildNav );
    } else {
        buildNav();
    }

} )();
