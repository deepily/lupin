/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
/**
 * Lupin Navigation Bar — TypeScript port of the legacy `lupin-nav.js` IIFE.
 *
 * Behaviour-preserving port: reads auth state from a `StorageLike` (the
 * browser's `localStorage` in production) and injects a fixed top nav bar
 * into `document.body`. No dependency on auth.js.
 *
 * Design (mirrors the multiplexer port convention): all side-effecting seams
 * — storage, the active pathname, and navigation — are passed in as explicit
 * arguments rather than read from globals inside the pure logic. This keeps
 * every branch deterministically testable (c8 --100 lines/branches/funcs).
 * The thin composition root in `boot.ts` binds these seams to the real
 * `document` / `window` / `localStorage`.
 *
 * Ported: 2026-06-18 (Tiffany 💍). Additive — the legacy lupin-nav.js stays
 * the live script across the 16 pages until this .ts is wired + proven.
 */

// ===========================================================================
// Types
// ===========================================================================

/** Minimal slice of the Web Storage API this module depends on. */
export interface StorageLike {
    getItem( key: string ): string | null;
    removeItem( key: string ): void;
}

/** Navigation seam — production binds this to `win.location.href = url`. */
export type Navigate = ( url: string ) => void;

/** Zero-arg mount callback used by {@link scheduleMount}. */
export type MountFn = () => void;

/** Shape of the persisted `user_data` blob (only the fields we read). */
export interface UserData {
    role?  : string;
    email? : string;
    [ key: string ]: unknown;
}

/** A single nav entry. `icon` is constrained to a known sprite name. */
export interface NavItem {
    label  : string;
    url    : string;
    icon   : IconName;
    auth   : boolean;
    admin  : boolean;
    testid : string;
}

/** Computed, render-ready auth/route state. */
export interface NavState {
    authenticated : boolean;
    admin         : boolean;
    email         : string | null;
    pathname      : string;
}

// ===========================================================================
// SVG icon sprites (inline to avoid extra network requests)
// ===========================================================================

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
    menu   : '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>',
} satisfies Record<string, string>;

/** Valid sprite names — derived from {@link ICONS} so the two never drift. */
export type IconName = keyof typeof ICONS;

// ===========================================================================
// Nav items — data-driven so adding pages is a one-line change
// ===========================================================================

export const NAV_ITEMS: readonly NavItem[] = [
    { label : "Home",          url : "/app",                       icon : "home",   auth : false, admin : false, testid : "nav-home-link"           },
    { label : "Notifications", url : "/app/notifications",         icon : "bell",   auth : true,  admin : false, testid : "nav-notifications-link"  },
    { label : "Profile",       url : "/app/auth/profile",          icon : "user",   auth : true,  admin : false, testid : "nav-profile-link"        },
    { label : "Admin",         url : "/app/admin",                 icon : "shield", auth : true,  admin : true,  testid : "nav-admin-link"          },
    { label : "Users",         url : "/app/admin/users",           icon : "users",  auth : true,  admin : true,  testid : "nav-admin-users-link"    },
    { label : "Snapshots",     url : "/app/admin/snapshots",       icon : "camera", auth : true,  admin : true,  testid : "nav-admin-snapshots-link"},
    { label : "Ratification",  url : "/app/admin/proxy-ratify",    icon : "check",  auth : true,  admin : true,  testid : "nav-admin-ratify-link"   },
    { label : "Trust",         url : "/app/admin/proxy-dashboard", icon : "chart",  auth : true,  admin : true,  testid : "nav-admin-trust-link"    },
    { label : "Dev Tools",     url : "/app/admin/dev-tools",       icon : "wrench", auth : true,  admin : true,  testid : "nav-admin-devtools-link" },
];

// ===========================================================================
// Auth helpers — read the injected storage directly (no auth.js dependency)
// ===========================================================================

export function getToken( storage: StorageLike ): string | null {
    return storage.getItem( "lupin_access_token" );
}

export function getUserData( storage: StorageLike ): UserData | null {
    try {
        const raw = storage.getItem( "user_data" );
        return raw ? ( JSON.parse( raw ) as UserData ) : null;
    } catch {
        return null;
    }
}

export function isAuthenticated( storage: StorageLike ): boolean {
    return !!getToken( storage );
}

export function isAdmin( storage: StorageLike ): boolean {
    const user = getUserData( storage );
    return user !== null && user.role === "admin";
}

export function getUserEmail( storage: StorageLike ): string | null {
    const user = getUserData( storage );
    return user ? ( user.email ?? null ) : null;
}

// ===========================================================================
// Active page detection
// ===========================================================================

export function isActivePage( itemUrl: string, pathname: string ): boolean {
    // Exact match for /app (landing) — startsWith would wrongly light it up
    // on every /app/* sub-page.
    if ( itemUrl === "/app" ) {
        return pathname === "/app" || pathname === "/app/";
    }
    // startsWith for all other pages
    return pathname.startsWith( itemUrl );
}

// ===========================================================================
// State + visibility
// ===========================================================================

export function computeNavState( storage: StorageLike, pathname: string ): NavState {
    return {
        authenticated : isAuthenticated( storage ),
        admin         : isAdmin( storage ),
        email         : getUserEmail( storage ),
        pathname,
    };
}

/** Filter nav items by the viewer's auth/admin state. */
export function visibleNavItems( items: readonly NavItem[], state: NavState ): NavItem[] {
    return items.filter( ( item ) => {
        if ( item.auth && !state.authenticated ) return false;
        if ( item.admin && !state.admin ) return false;
        return true;
    } );
}

// ===========================================================================
// Rendering
// ===========================================================================

/** Build the inner HTML of the nav bar for the given state. */
export function renderNavInnerHtml( state: NavState ): string {
    const visible = visibleNavItems( NAV_ITEMS, state );

    let html = '<div class="lupin-nav-inner">';

    // Brand
    html += '<a href="/app" class="lupin-nav-brand">Lupin</a>';

    // Hamburger toggle (mobile)
    html += '<button class="lupin-nav-toggle" aria-label="Toggle navigation" data-testid="nav-mobile-toggle-btn">' + ICONS.menu + '</button>';

    // Nav links
    html += '<div class="lupin-nav-links">';

    let adminSectionStarted = false;
    for ( const item of visible ) {
        // Separator before the first admin item
        if ( item.admin && !adminSectionStarted ) {
            adminSectionStarted = true;
            html += '<span class="lupin-nav-separator"></span>';
        }

        const active = isActivePage( item.url, state.pathname ) ? " lupin-nav-active" : "";
        html += '<a href="' + item.url + '" class="lupin-nav-link' + active + '" data-testid="' + item.testid + '">' + ICONS[ item.icon ] + '<span>' + item.label + '</span></a>';
    }

    html += '</div>'; // end .lupin-nav-links

    // Right side — user email + logout OR login
    html += '<div class="lupin-nav-right">';
    if ( state.authenticated && state.email ) {
        html += '<span class="lupin-nav-email" data-testid="nav-user-email">' + state.email + '</span>';
        html += '<button class="lupin-nav-logout" title="Logout" data-testid="nav-logout-btn">' + ICONS.logout + ' Logout</button>';
    } else {
        html += '<a href="/app/auth/login" class="lupin-nav-login" data-testid="nav-login-link">' + ICONS.login + ' Login</a>';
    }
    html += '</div>'; // end .lupin-nav-right

    html += '</div>'; // end .lupin-nav-inner

    return html;
}

/** Build the detached `<nav id="lupin-nav">` element for the given state. */
export function buildNavElement( doc: Document, state: NavState ): HTMLElement {
    const nav = doc.createElement( "nav" );
    nav.id        = "lupin-nav";
    nav.className = "lupin-nav";
    nav.innerHTML = renderNavInnerHtml( state );
    return nav;
}

// ===========================================================================
// Event wiring
// ===========================================================================

/** Wire logout + hamburger handlers onto an already-built nav element. */
export function wireEvents( nav: HTMLElement, storage: StorageLike, navigate: Navigate ): void {
    // Logout button
    const logoutBtn = nav.querySelector<HTMLButtonElement>( ".lupin-nav-logout" );
    if ( logoutBtn ) {
        logoutBtn.addEventListener( "click", () => {
            storage.removeItem( "lupin_access_token" );
            storage.removeItem( "lupin_refresh_token" );
            storage.removeItem( "user_data" );
            navigate( "/app/auth/login" );
        } );
    }

    // Hamburger toggle
    const toggleBtn = nav.querySelector<HTMLButtonElement>( ".lupin-nav-toggle" );
    const navLinks  = nav.querySelector<HTMLElement>( ".lupin-nav-links" );
    const navRight  = nav.querySelector<HTMLElement>( ".lupin-nav-right" );

    if ( toggleBtn && navLinks ) {
        toggleBtn.addEventListener( "click", () => {
            navLinks.classList.toggle( "lupin-nav-open" );
            if ( navRight ) navRight.classList.toggle( "lupin-nav-open" );
        } );
    }
}

// ===========================================================================
// Mount + schedule
// ===========================================================================

/** Compute state, build the nav, inject it at the top of body, and wire it. */
export function mountNav( doc: Document, win: Window, storage: StorageLike ): HTMLElement {
    const state = computeNavState( storage, win.location.pathname );
    const nav   = buildNavElement( doc, state );

    // Inject as first child of body
    doc.body.insertBefore( nav, doc.body.firstChild );

    // Add body padding to account for the fixed nav
    doc.body.style.paddingTop = "56px";

    // Wire up events (navigation seam bound to the real location here)
    wireEvents( nav, storage, ( url ) => { win.location.href = url; } );

    return nav;
}

/** Run `mount` now if the document is ready, else defer to DOMContentLoaded. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function scheduleMount( doc: Document, mount: MountFn ): void {
    if ( doc.readyState === "loading" ) {
        doc.addEventListener( "DOMContentLoaded", mount );
    } else {
        mount();
    }
}
