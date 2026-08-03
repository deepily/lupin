/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — boot-time login bounce (WP0).
//
// Parity with notifications.js: a user landing on /app/multiplexer with no
// access token is bounced to the login page with a redirect back to where they
// were. Mirrors auth.js `isAuthenticated()` (presence-only) — an EXPIRED token
// still proceeds to boot, where AuthManager refreshes it (or the WS/API 401
// path re-auths). The window side-effect is isolated behind an injectable
// `RedirectTarget` so the decision logic stays unit-testable.

import type { StorageService } from "../shared/StorageService";

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
