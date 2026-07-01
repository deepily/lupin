/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane L4 — NavBarRenderer (PORT of lupin-nav.js → mux-TS).
//
// Owns the top nav bar's lifecycle: mount into a host element, render the bar
// from the injected NavAuthPort, and RE-RENDER on `auth_state_change` (F-K-D4:
// the mux is an SPA that does NOT full-reload on login/expiry, so a one-shot
// render would show a stale/absent email or the wrong login/logout affordance).
// Mirrors the MissedBadgeRenderer lifecycle contract (atomic replaceChildren;
// throw on double-mount; idempotent unmount).
//
// The renderer depends on a NARROW NavAuthPort (not AuthManager/StorageService
// directly) so it stays unit-testable with a fake port. boot.ts wires the
// production adapter: isAuthenticated ← persisted access token; email ←
// AuthManager.getCurrentUserEmail() (null-guarded, F-K-D2); logout ← the
// exported authGuard.logout() (clears the PERSISTED tokens + redirects, F-K-D1).
//
// TODO(post-MVP): the legacy lupin-nav.js NAV_ITEMS also carries 6 ADMIN items
// (Admin /app/admin, Users /app/admin/users, Snapshots /app/admin/snapshots,
// Ratification /app/admin/proxy-ratify, Trust /app/admin/proxy-dashboard, Dev
// Tools /app/admin/dev-tools) gated on the user role. They are DEFERRED from
// this MVP: the mux has no `user_data` blob, so admin status must come from the
// JWT `roles` claim — and that roles-claim shape is UNVERIFIED against the
// server. Verify against jwt_service.create_access_token before porting
// admin-gating (do not build role-gating on an unverified client-only claim).

import type { EventBus } from "../shared/EventBus";
import type { AuthStateChangePayload } from "../shared/types";
import { renderNavBar } from "./templates/navBar";

// Narrow auth surface the nav needs. boot.ts supplies the production adapter;
// tests inject a fake.
export interface NavAuthPort {
  /** True when a persisted access token is present (legacy presence-semantics). */
  isAuthenticated(): boolean;
  /** Current-user email from the access-token claim, or null (missing/malformed). */
  getCurrentUserEmail(): string | null;
  /** Clear the PERSISTED tokens + redirect to login (F-K-D1). */
  logout(): void;
}

export interface NavBarRendererOptions {
  eventBus      : EventBus;
  auth          : NavAuthPort;
  /** Active-path source; production passes `() => window.location.pathname`. */
  getActivePath : () => string;
}

export interface NavBarRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + clear children. Idempotent. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

class NavBarRendererImpl implements NavBarRenderer {
  private readonly bus           : EventBus;
  private readonly auth          : NavAuthPort;
  private readonly getActivePath : () => string;
  private readonly unsubscribers : Array<() => void> = [];

  private root    : HTMLElement | null = null;
  private mounted = false;

  constructor( opts: NavBarRendererOptions ) {
    this.bus           = opts.eventBus;
    this.auth          = opts.auth;
    this.getActivePath = opts.getActivePath;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "NavBarRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    this.renderNow();
    // F-K-D4 — re-render on auth-state transitions (login → ready → expired):
    // the SPA does not reload, so the email + login/logout affordance must
    // react to AuthManager's `auth_state_change` (emitted at AuthManager.ts:194).
    this.unsubscribers.push(
      this.bus.on<AuthStateChangePayload>(
        "auth_state_change",
        () => this.renderNow(),
      ),
    );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if ( this.mounted ) this.renderNow();
  }

  private renderNow(): void {
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount BEFORE root is nulled, so renderNow never runs with a null root.
    if ( this.root === null ) return;
    const nav = renderNavBar(
      {
        authenticated : this.auth.isAuthenticated(),
        email         : this.auth.getCurrentUserEmail(),
        activePath    : this.getActivePath(),
      },
      { onLogout : (): void => this.auth.logout() },
    );
    this.root.replaceChildren( nav );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createNavBarRenderer( opts: NavBarRendererOptions ): NavBarRenderer {
  return new NavBarRendererImpl( opts );
}
