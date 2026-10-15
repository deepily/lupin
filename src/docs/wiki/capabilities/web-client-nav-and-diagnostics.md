---
capability: web-client-nav-and-diagnostics
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.diagnostic.boot.createBrowserDeps@5a806f7c47
  - src.lupin_app.static.js.diagnostic.boot.wireDiagnostic@b7a1f6d4c3
  - src.lupin_app.static.js.diagnostic.websocketDiagnostic.WebSocketDiagnosticTool@7cb54d0d14
  - src.lupin_app.static.js.nav.lupinNav.getToken@980d1d275b
  - src.lupin_app.static.js.nav.lupinNav.getUserData@7b5904c4b7
  - src.lupin_app.static.js.nav.lupinNav.isAuthenticated@cc57208847
  - src.lupin_app.static.js.nav.lupinNav.isAdmin@9892d4ae4d
  - src.lupin_app.static.js.nav.lupinNav.getUserEmail@4a38b6d3d1
  - src.lupin_app.static.js.nav.lupinNav.isActivePage@ff32866100
  - src.lupin_app.static.js.nav.lupinNav.computeNavState@440ecfdd17
  - src.lupin_app.static.js.nav.lupinNav.visibleNavItems@5d128b0b1b
  - src.lupin_app.static.js.nav.lupinNav.renderNavInnerHtml@573e2689e1
  - src.lupin_app.static.js.nav.lupinNav.buildNavElement@13419cd599
  - src.lupin_app.static.js.nav.lupinNav.wireEvents@be4d22470d
  - src.lupin_app.static.js.nav.lupinNav.mountNav@19164425c6
  - src.lupin_app.static.js.nav.lupinNav.scheduleMount@a6c394230d
  - src.lupin_app.static.js.websocket-diagnostic.WebSocketDiagnosticTool@9ca61b50d3
  - src.lupin_app.static.js.websocket-diagnostic.startDiagnosticTest@5a4a9caf29
  - src.lupin_app.static.js.websocket-diagnostic.stopDiagnosticTest@a80eee4c2e
  - src.lupin_app.static.js.websocket-diagnostic.clearDiagnosticLogs@9f401579f0
---
# Web client navigation and diagnostics

The shared navigation bar and the WebSocket diagnostic pages. [[web-client-transport-and-auth]] describes the sockets they probe. `boot.ts` imports `websocketDiagnostic.ts`.

## What it does
- `boot.ts`. `createBrowserDeps`: Build the diagnostic tool's dependencies from the real browser globals. `wireDiagnostic`: Wire the DOMContentLoaded bootstrap + the global onclick handlers onto the given doc/target using the provided tool factory. Pure (injected seams) so it is unit-tested directly.
- `websocketDiagnostic.ts`. `WebSocketDiagnosticTool`: Diagnostic controller that opens monitored WebSockets and watches the audio they carry.
- `lupinNav.ts`. `getToken`: Read the stored access token. `getUserData`: Read the stored `user_data` blob. `isAuthenticated`: Say whether the stored access token is present, decodable and not yet expired. `isAdmin`: Say whether the stored user has the admin role. `getUserEmail`: Read the stored user's email address. `isActivePage`: Say whether a nav item's URL is the page the viewer is on. `computeNavState`: Gather what the nav bar needs to render into one state object. `visibleNavItems`: Filter nav items by the viewer's auth/admin state. `renderNavInnerHtml`: Build the inner HTML of the nav bar for the given state. `buildNavElement`: Build the detached `<nav id="lupin-nav">` element for the given state. `wireEvents`: Wire logout + hamburger handlers onto an already-built nav element. `mountNav`: Compute state, build the nav, inject it at the top of body, and wire it. `scheduleMount`: Run `mount` now if the document is ready, else defer to DOMContentLoaded.
- `websocket-diagnostic.js`. `WebSocketDiagnosticTool`: WebSocket Audio Diagnostic Tool. `startDiagnosticTest`: Starts the diagnostic test from the page button, if the tool has been created. `stopDiagnosticTest`: Stops the running diagnostic test, if the tool has been created. `clearDiagnosticLogs`: Clears the diagnostic console, if the tool has been created.
