// Multiplexer Lane L4 — NavBarRenderer + navBar template unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// The 3 branchy assertions (OD-1) are OUTCOME-based, not "wired":
//   (1) Logout OUTCOME — after clicking the nav Logout button wired to the REAL
//       authGuard.logout(), the PERSISTED tokens are GONE (a "logout was wired"
//       assertion would false-pass the very clearToken-only bug we fixed).
//   (2) Email BOTH arms — email present renders it; null renders login, no throw.
//   (3) Auth-state TRANSITION — auth_state_change re-renders logged-in ↔ out.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createNavBarRenderer,
  type NavAuthPort,
} from "../../../../lupin_app/static/js/multiplexer/render/NavBarRenderer";
import {
  renderNavBar,
  isActivePage,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/navBar";
import {
  logout,
  LOGIN_PATH,
  type RedirectTarget,
} from "../../../../lupin_app/static/js/multiplexer/auth/authGuard";
import {
  createStorageServiceForTesting,
} from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type {
  AuthState,
  AuthStateChangePayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

interface FakePort extends NavAuthPort {
  setAuthenticated(v: boolean): void;
  setEmail(e: string | null): void;
  logoutCalls: number;
}

function makePort(opts: { authenticated?: boolean; email?: string | null } = {}): FakePort {
  let authenticated = opts.authenticated ?? true;
  let email = opts.email !== undefined ? opts.email : "user@example.com";
  const port: FakePort = {
    logoutCalls         : 0,
    isAuthenticated     : () => authenticated,
    getCurrentUserEmail : () => email,
    logout              : () => { port.logoutCalls += 1; },
    setAuthenticated    : (v) => { authenticated = v; },
    setEmail            : (e) => { email = e; },
  };
  return port;
}

function emitAuthChange(bus: ReturnType<typeof createEventBusForTesting>, state: AuthState): void {
  bus.emit<AuthStateChangePayload>({
    type    : "auth_state_change",
    payload : { state },
    source  : "test",
    ts      : 0,
  });
}

function noopHandlers() {
  return { onLogout: () => { /* noop */ } };
}

// ===========================================================================
// Template — renderNavBar
// ===========================================================================

test("template: authenticated + email renders 3 items, the email, and the Logout button", () => {
  const nav = renderNavBar(
    { authenticated: true, email: "a@b.com", activePath: "/app" },
    noopHandlers(),
  );
  assert.equal(nav.querySelectorAll(".lupin-nav-link").length, 3);
  assert.equal(nav.querySelector('[data-testid="nav-user-email"]')?.textContent, "a@b.com");
  assert.ok(nav.querySelector(".lupin-nav-logout"));
  assert.equal(nav.querySelector(".lupin-nav-login"), null);
  // activePath "/app" → Home active (first === operand); the others inactive.
  assert.ok(nav.querySelector('[data-testid="nav-home-link"]')?.classList.contains("lupin-nav-active"));
  assert.equal(nav.querySelector('[data-testid="nav-notifications-link"]')?.classList.contains("lupin-nav-active"), false);
});

test("template: unauthenticated hides the auth-gated items and shows the Login link", () => {
  const nav = renderNavBar(
    { authenticated: false, email: null, activePath: "/app" },
    noopHandlers(),
  );
  // Only Home (auth:false) survives the filter.
  assert.equal(nav.querySelectorAll(".lupin-nav-link").length, 1);
  assert.ok(nav.querySelector('[data-testid="nav-home-link"]'));
  assert.equal(nav.querySelector('[data-testid="nav-notifications-link"]'), null);
  assert.ok(nav.querySelector(".lupin-nav-login"));
  assert.equal(nav.querySelector(".lupin-nav-logout"), null);
  assert.equal(nav.querySelector('[data-testid="nav-user-email"]'), null);
});

test("template: authenticated but email===null renders the Login link, no throw (D2 email-null arm)", () => {
  const nav = renderNavBar(
    { authenticated: true, email: null, activePath: "/app" },
    noopHandlers(),
  );
  // authenticated && email!==null → false via the email arm → login side.
  assert.ok(nav.querySelector(".lupin-nav-login"));
  assert.equal(nav.querySelector(".lupin-nav-logout"), null);
  // Auth-gated items still show (authenticated === true).
  assert.equal(nav.querySelectorAll(".lupin-nav-link").length, 3);
});

test("template: /app/ (trailing slash) marks Home active (second === operand)", () => {
  const nav = renderNavBar(
    { authenticated: true, email: "a@b.com", activePath: "/app/" },
    noopHandlers(),
  );
  assert.ok(nav.querySelector('[data-testid="nav-home-link"]')?.classList.contains("lupin-nav-active"));
});

test("template: a deeper path marks that item active via startsWith, Home inactive", () => {
  const nav = renderNavBar(
    { authenticated: true, email: "a@b.com", activePath: "/app/notifications" },
    noopHandlers(),
  );
  assert.ok(nav.querySelector('[data-testid="nav-notifications-link"]')?.classList.contains("lupin-nav-active"));
  assert.equal(nav.querySelector('[data-testid="nav-home-link"]')?.classList.contains("lupin-nav-active"), false);
  assert.equal(nav.querySelector('[data-testid="nav-profile-link"]')?.classList.contains("lupin-nav-active"), false);
});

test("template: Logout button click invokes onLogout", () => {
  let calls = 0;
  const nav = renderNavBar(
    { authenticated: true, email: "a@b.com", activePath: "/app" },
    { onLogout: () => { calls += 1; } },
  );
  const btn = nav.querySelector<HTMLButtonElement>(".lupin-nav-logout");
  assert.ok(btn);
  btn.click();
  assert.equal(calls, 1);
});

test("template: hamburger toggle toggles .lupin-nav-open on links + right regions", () => {
  const nav = renderNavBar(
    { authenticated: true, email: "a@b.com", activePath: "/app" },
    noopHandlers(),
  );
  const toggle = nav.querySelector<HTMLButtonElement>(".lupin-nav-toggle");
  const links  = nav.querySelector(".lupin-nav-links");
  const right  = nav.querySelector(".lupin-nav-right");
  assert.ok(toggle && links && right);
  assert.equal(links.classList.contains("lupin-nav-open"), false);
  toggle.click();
  assert.equal(links.classList.contains("lupin-nav-open"), true);
  assert.equal(right.classList.contains("lupin-nav-open"), true);
  toggle.click();
  assert.equal(links.classList.contains("lupin-nav-open"), false);
  assert.equal(right.classList.contains("lupin-nav-open"), false);
});

// ---------------------------------------------------------------------------
// isActivePage — direct branch lock
// ---------------------------------------------------------------------------

test("isActivePage: /app exact + trailing-slash true; deeper /app path false", () => {
  assert.equal(isActivePage("/app", "/app"), true);
  assert.equal(isActivePage("/app", "/app/"), true);
  assert.equal(isActivePage("/app", "/app/notifications"), false);
});

test("isActivePage: deeper item uses startsWith", () => {
  assert.equal(isActivePage("/app/notifications", "/app/notifications"), true);
  assert.equal(isActivePage("/app/notifications", "/app"), false);
});

// ===========================================================================
// Renderer — NavBarRenderer
// ===========================================================================

test("mount renders the nav into the root (authenticated)", () => {
  const bus = createEventBusForTesting();
  const r = createNavBarRenderer({ eventBus: bus, auth: makePort(), getActivePath: () => "/app" });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".lupin-nav"));
  assert.ok(root.querySelector(".lupin-nav-logout"));
});

test("D1 OUTCOME: clicking the nav Logout button clears the PERSISTED tokens + redirects (via real authGuard.logout)", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(createEventBusForTesting());
  storage.setTokens("access-jwt", "refresh-jwt");
  const target: RedirectTarget = { pathname: "/app/multiplexer", href: "/app/multiplexer" };

  const r = createNavBarRenderer({
    eventBus : bus,
    auth : {
      isAuthenticated     : () => storage.getAccessToken() !== null,
      getCurrentUserEmail : () => "user@example.com",
      logout              : () => logout(storage, target),
    },
    getActivePath : () => "/app",
  });
  const root = document.createElement("div");
  r.mount(root);

  const btn = root.querySelector<HTMLButtonElement>(".lupin-nav-logout");
  assert.ok(btn);
  btn.click();

  // OUTCOME (the real proof, not "logout was called"): persisted tokens GONE.
  assert.equal(storage.getAccessToken(), null, "persisted access token cleared");
  assert.equal(storage.getRefreshToken(), null, "persisted refresh token cleared");
  assert.equal(target.href, LOGIN_PATH);
});

test("logout button click reaches the injected auth port", () => {
  const bus = createEventBusForTesting();
  const port = makePort();
  const r = createNavBarRenderer({ eventBus: bus, auth: port, getActivePath: () => "/app" });
  const root = document.createElement("div");
  r.mount(root);
  root.querySelector<HTMLButtonElement>(".lupin-nav-logout")?.click();
  assert.equal(port.logoutCalls, 1);
});

test("D3 TRANSITION: auth_state_change re-renders logged-in → logged-out (Logout → Login swap)", () => {
  const bus = createEventBusForTesting();
  const port = makePort({ authenticated: true, email: "user@example.com" });
  const r = createNavBarRenderer({ eventBus: bus, auth: port, getActivePath: () => "/app" });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".lupin-nav-logout"));

  // Token expires → AuthManager emits auth_state_change; the SPA does not reload.
  port.setAuthenticated(false);
  port.setEmail(null);
  emitAuthChange(bus, "expired");

  assert.equal(root.querySelector(".lupin-nav-logout"), null, "Logout gone after logout transition");
  assert.ok(root.querySelector(".lupin-nav-login"), "Login link appears after logout transition");
});

test("second mount without unmount throws", () => {
  const bus = createEventBusForTesting();
  const r = createNavBarRenderer({ eventBus: bus, auth: makePort(), getActivePath: () => "/app" });
  r.mount(document.createElement("div"));
  assert.throws(() => r.mount(document.createElement("div")), /already mounted/);
});

test("unmount unsubscribes (no repaint) + clears the root; re-mount OK", () => {
  const bus = createEventBusForTesting();
  const port = makePort({ authenticated: true, email: "user@example.com" });
  const r = createNavBarRenderer({ eventBus: bus, auth: port, getActivePath: () => "/app" });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".lupin-nav"));

  r.unmount();
  assert.equal(root.querySelector(".lupin-nav"), null);

  // After unmount, an auth_state_change must NOT repaint into the old root.
  port.setAuthenticated(false);
  emitAuthChange(bus, "expired");
  assert.equal(root.querySelector(".lupin-nav"), null);

  assert.doesNotThrow(() => r.mount(root));
  assert.ok(root.querySelector(".lupin-nav"));
});

test("unmount before mount is a no-op (idempotent)", () => {
  const bus = createEventBusForTesting();
  const r = createNavBarRenderer({ eventBus: bus, auth: makePort(), getActivePath: () => "/app" });
  assert.doesNotThrow(() => r.unmount());
  assert.doesNotThrow(() => r.unmount());
});

test("forceRenderForTesting before mount is a no-op", () => {
  const bus = createEventBusForTesting();
  const r = createNavBarRenderer({ eventBus: bus, auth: makePort(), getActivePath: () => "/app" });
  assert.doesNotThrow(() => r.forceRenderForTesting());
});

test("forceRenderForTesting after mount repaints from current port state", () => {
  const bus = createEventBusForTesting();
  const port = makePort({ authenticated: true, email: "user@example.com" });
  const r = createNavBarRenderer({ eventBus: bus, auth: port, getActivePath: () => "/app" });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".lupin-nav-logout"));

  port.setAuthenticated(false);
  port.setEmail(null);
  r.forceRenderForTesting();
  assert.equal(root.querySelector(".lupin-nav-logout"), null);
  assert.ok(root.querySelector(".lupin-nav-login"));
});
