/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane L4 — top nav bar template (PORT of lupin-nav.js buildNav()).
//
// Ports the legacy nav DOM (static/js/lupin-nav.js:98-165) to a safe-write
// template. MVP scope (Rick 2026-06-30, OQ-1): the 3 core NAV_ITEMS (Home /
// Notifications / Profile) + auth-gating + brand + hamburger toggle + the
// right-side email+Logout OR Login. The 6 legacy admin items are DEFERRED
// post-MVP (see NavBarRenderer.ts TODO — roles-claim shape unverified).
//
// Safe-write invariant (mirrors missedBadge.ts / ttsChrome.ts): all DOM writes
// go through the `html` tagged template (auto-escaping text/attrs). The static
// inline SVG icon sprites are the one sanctioned `raw()` opt-out — they are
// developer-authored constants with zero interpolation, never user input.

import { html, raw } from "../html";
import { LOGIN_PATH } from "../../auth/authGuard";

// Inline SVG sprites — ported verbatim from lupin-nav.js:33-44. Only the six
// the MVP nav renders (home / bell / user for the core items, logout / login /
// menu for the right side + hamburger). Avoids an extra network round-trip.
const ICONS = {
  home   : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>',
  bell   : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>',
  user   : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
  logout : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>',
  login  : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path><polyline points="10 17 15 12 10 7"></polyline><line x1="15" y1="12" x2="3" y2="12"></line></svg>',
  menu   : '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>',
} as const;

type IconKey = keyof typeof ICONS;

export interface NavItem {
  label  : string;
  url    : string;
  icon   : IconKey;
  auth   : boolean;   // true → shown only when authenticated
  testid : string;
}

// MVP nav items — Home (public) + Notifications + Profile (auth-gated). The
// "Notifications" label is kept verbatim (OQ-1 RESOLVED — Rick 2026-06-30:
// KEEP "Notifications", do NOT relabel "Multiplexer").
const NAV_ITEMS: readonly NavItem[] = [
  { label : "Home",          url : "/app",               icon : "home", auth : false, testid : "nav-home-link"          },
  { label : "Notifications", url : "/app/notifications", icon : "bell", auth : true,  testid : "nav-notifications-link" },
  { label : "Profile",       url : "/app/auth/profile",  icon : "user", auth : true,  testid : "nav-profile-link"       },
];

export interface NavBarData {
  authenticated : boolean;
  email         : string | null;
  activePath    : string;   // window.location.pathname
}

export interface NavBarHandlers {
  /** Logout button click. */
  onLogout(): void;
}

// Active-page test — ported from lupin-nav.js:82-92. Exact match for the /app
// landing (with/without trailing slash); startsWith for every deeper page.
export function isActivePage( itemUrl: string, currentPath: string ): boolean {
  if ( itemUrl === "/app" ) {
    return currentPath === "/app" || currentPath === "/app/";
  }
  return currentPath.startsWith( itemUrl );
}

/**
 * Build the top nav bar element.
 *
 * Requires:
 *   - `handlers.onLogout` is a function
 *
 * Ensures:
 *   - Returns a `<nav.lupin-nav>` element (id `lupin-nav`)
 *   - auth-gated items (`item.auth`) appear only when `data.authenticated`
 *   - the right side shows the email + Logout button when authenticated AND
 *     `data.email` is non-null; otherwise the Login link
 *   - the Logout button (when present) is wired to `handlers.onLogout`
 *   - the hamburger toggles `.lupin-nav-open` on the links + right regions
 *   - all writes are safe (icons via `raw()`; every other value auto-escaped)
 */
export function renderNavBar( data: NavBarData, handlers: NavBarHandlers ): HTMLElement {
  const nav = document.createElement( "nav" );
  nav.id = "lupin-nav";
  nav.className = "lupin-nav";

  const visibleItems = NAV_ITEMS.filter( ( item ) => ( item.auth ? data.authenticated : true ) );

  const linkNodes = visibleItems.map( ( item ) => {
    const linkClass = isActivePage( item.url, data.activePath )
      ? "lupin-nav-link lupin-nav-active"
      : "lupin-nav-link";
    return html`<a href="${item.url}" class="${linkClass}" data-testid="${item.testid}">${raw( ICONS[ item.icon ] )}<span>${item.label}</span></a>`;
  } );

  const rightSide =
    data.authenticated && data.email !== null
      ? html`<span class="lupin-nav-email" data-testid="nav-user-email">${data.email}</span><button type="button" class="lupin-nav-logout" title="Logout" data-testid="nav-logout-btn">${raw( ICONS.logout )}<span>Logout</span></button>`
      : html`<a href="${LOGIN_PATH}" class="lupin-nav-login" data-testid="nav-login-link">${raw( ICONS.login )}<span>Login</span></a>`;

  /* c8 ignore next 8 */ // tagged-template literal: c8 reports phantom branches on $-interpolations (${linkNodes} / ${rightSide}); the runtime path is straight-line and exercised by every test that renders the bar — the rightSide fragment reaches line 108 in BOTH the authenticated (email+logout) and unauthenticated (login) shapes (missedBadge.ts:48 precedent).
  nav.appendChild( html`
    <div class="lupin-nav-inner">
      <a href="/app" class="lupin-nav-brand">Lupin</a>
      <button type="button" class="lupin-nav-toggle" aria-label="Toggle navigation" data-testid="nav-mobile-toggle-btn">${raw( ICONS.menu )}</button>
      <div class="lupin-nav-links">${linkNodes}</div>
      <div class="lupin-nav-right">${rightSide}</div>
    </div>
  ` );

  // Wire logout — present ONLY in the authenticated+email branch. When absent
  // (login state) the null arm is exercised too, so both branches are covered.
  const logoutBtn = nav.querySelector<HTMLButtonElement>( ".lupin-nav-logout" );
  if ( logoutBtn !== null ) {
    logoutBtn.addEventListener( "click", () => handlers.onLogout() );
  }

  // Wire the mobile hamburger toggle (pure visual class-toggle; ported from
  // lupin-nav.js:184-193). The toggle button + both regions are ALWAYS produced
  // by the template above.
  const toggleBtn = nav.querySelector<HTMLButtonElement>( ".lupin-nav-toggle" );
  const navLinks  = nav.querySelector<HTMLElement>( ".lupin-nav-links" );
  const navRight  = nav.querySelector<HTMLElement>( ".lupin-nav-right" );
  /* c8 ignore next */ // defensive: html`` always produces the toggle button + both nav regions; the null arm is unreachable.
  if ( toggleBtn !== null && navLinks !== null && navRight !== null ) {
    toggleBtn.addEventListener( "click", () => {
      navLinks.classList.toggle( "lupin-nav-open" );
      navRight.classList.toggle( "lupin-nav-open" );
    } );
  }

  return nav;
}
