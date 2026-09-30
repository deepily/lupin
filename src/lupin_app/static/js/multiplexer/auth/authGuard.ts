/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — boot-time login bounce (WP0).
//
// Parity with notifications.js: a user landing on /app/multiplexer with no
// access token is bounced to the login page with a redirect back to where they
// were. Mirrors auth.js `isAuthenticated()` (presence-only) — an EXPIRED token
// still proceeds to boot, where AuthManager refreshes it (or the WS/API 401
// path re-auths). The window side-effect is isolated behind an injectable
// `RedirectTarget` so the decision logic stays unit-testable.

import { REFRESH_MISSING_ERROR, REFRESH_REJECTED_ERROR } from "./AuthManager";
import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type { RefreshFailedPayload } from "../shared/types";

// The minimal `window.location` surface the guard touches. `Location` satisfies
// this structurally, so boot passes `window.location` directly.
export interface RedirectTarget {
  readonly pathname : string;
  href              : string;
}

// Canonical login path. Exported so the NAV login-link href (templates/navBar.ts)
// and logout() below single-source it instead of duplicating the literal.
export const LOGIN_PATH = "/app/auth/login";

// Returns true when a redirect was issued — the caller MUST halt boot. Returns
// false (boot proceeds) when an access token is present.
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function redirectToLoginIfUnauthenticated(
  storage : StorageService,
  target  : RedirectTarget,
): boolean {
  if ( storage.getAccessToken() !== null ) return false;
  target.href = `${LOGIN_PATH}?redirect=${encodeURIComponent( target.pathname )}`;
  return true;
}

// Mid-session login bounce. The boot guard above checks token PRESENCE only, so
// a page holding an access token but a dead refresh token boots, fails its first
// refresh, and — until this existed — sat on an empty inbox forever: AuthManager
// emitted `refresh_failed` and nothing listened (measured in Rick's Chrome
// 2026-09-15: "no refresh token available", 0 cards, reload did not recover,
// while the legacy client in the same browser showed 21). Legacy's
// handleAuthFailure() clears both tokens and redirects; this is the same move.
//
// Only a DEAD session bounces: no refresh token, or the server rejecting it (401).
// A timeout, network error or 5xx is transient and leaves the user where they are.
// The clear is required, not tidy-up: the login page redirects straight back when
// any access token is present, so a redirect without it loops.
//
// The clear is also DANGEROUS: tokens are shared across tabs, and another tab may
// have stored a live refresh token after our attempt was rejected. So it clears
// only when storage still holds exactly the token that failed (or nothing); if a
// different token is stored, the session is alive elsewhere and the page reloads
// to pick it up (review of 65db061d, Tiffany 2026-09-15).
//
// Returns the unsubscribe closure.
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function bounceToLoginOnDeadSession(
  bus     : EventBus,
  storage : StorageService,
  target  : RedirectTarget,
): () => void {
  return bus.on<RefreshFailedPayload>( "refresh_failed", ( event ) => {
    const { error, sentRefresh } = event.payload;
    if ( error !== REFRESH_MISSING_ERROR && error !== REFRESH_REJECTED_ERROR ) return;
    const stored = storage.getRefreshToken();
    if ( stored !== null && stored !== sentRefresh ) {
      target.href = target.pathname;
      return;
    }
    storage.clearTokens();
    target.href = `${LOGIN_PATH}?redirect=${encodeURIComponent( target.pathname )}`;
  } );
}

// Log out: clear the PERSISTED tokens, then redirect to the login page. The
// load-bearing auth fix (F-K-D1): the clear MUST go through
// StorageService.clearTokens(), which removes the persisted
// `lupin_access_token` / `lupin_refresh_token` keys — NOT AuthManager.clearToken(),
// which nulls only the in-memory XState context and leaves the persisted token
// on disk. A "logout" that cleared only in-memory state would leave the user
// STILL LOGGED IN: authGuard / ApiClient / the WS transports all re-read the
// persisted token. No `?redirect=` back-param — logout returns to a clean login.
// `window.location` satisfies RedirectTarget structurally (boot passes it).
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function logout( storage: StorageService, target: RedirectTarget ): void {
  storage.clearTokens();
  target.href = LOGIN_PATH;
}
