/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-6 — the three debug writers, ported from legacy's `log`, `error` and
// `wsDiag` (notifications.js:21154, :21161, :21166) and the `addDebugMessage`
// they all funnel into (:21171).
//
// 🔴 EVERY CALL STILL WRITES TO THE CONSOLE. This is a TEE, not a redirect. The
// console is where a developer with devtools open actually reads, and the panel
// is strictly less informative than it — legacy's writers take `...args` and
// `addDebugMessage` drops them (G6), so a line that reads "playback failed" in
// the panel carries the error object only in the console. Routing a call away
// from the console would take information away from the person best placed to
// use it.
//
// ⚠️ THE PANEL IS A SINK THAT MAY NOT EXIST. Legacy's `addDebugMessage` looks up
// `#debug-log` on every call and no-ops when it is absent; this client's panel
// owns its own subtree, so it REGISTERS itself here at mount and deregisters at
// unmount. Before the panel mounts, and after it goes, these calls still reach
// the console and drop on the floor for the panel — which is legacy's behaviour,
// reached by a different mechanism.
//
// 🔴 THE DEBUG FLAG IS HARD-CODED ON (G2). Legacy gates `log()` behind
// `this.debug`, which nothing sets to false — no INI key, no UI control, no
// query param. It is written as a constant here rather than as a variable
// nobody assigns, because a variable implies a control that does not exist.

/** A line the panel can paint. `type` picks the second class on the div. */
export interface DebugLine {
  message: string;
  type   : "info" | "error";
}

/** What a panel must provide to receive lines. */
export interface DebugPanelSink {
  addDebugMessage( message: string, type: "info" | "error" ): void;
}

/**
 * 🔴 ON, AND NOT CONFIGURABLE — see the header. Legacy's `this.debug` is set
 * once and never cleared, so `log()` always writes in both clients.
 */
export const DEBUG_ENABLED = true;

let panel: DebugPanelSink | null = null;

/**
 * Register (or clear) the panel that receives lines.
 *
 * Requires:
 *   - sink is a panel, or null to clear
 *
 * Ensures:
 *   - subsequent writes reach this sink, replacing any previous one
 *   - null restores the console-only behaviour the page has before mount
 */
export function setDebugPanel( sink: DebugPanelSink | null ): void {
  panel = sink;
}

/** The sink currently registered — for a test to assert wiring without a panel. */
export function currentDebugPanel(): DebugPanelSink | null {
  return panel;
}

function toPanel( message: string, type: "info" | "error" ): void {
  if ( panel === null ) return;
  panel.addDebugMessage( message, type );
}

/**
 * An ordinary diagnostic line. Legacy `log` (notifications.js:21154).
 *
 * Ensures:
 *   - always writes to the console, with legacy's `[Notifications]` prefix
 *   - also reaches the panel, unprefixed, when one is registered
 *   - extra args reach the CONSOLE ONLY — the panel drops them (G6)
 */
export function log( message: string, ...args: unknown[] ): void {
  /* c8 ignore next */ // DEBUG_ENABLED is a hard-coded `true` (G2); the false arm is the control legacy does not have either.
  if ( !DEBUG_ENABLED ) return;
  console.log( `[Notifications] ${ message }`, ...args );
  toPanel( message, "info" );
}

/**
 * An error line. Legacy `error` (notifications.js:21161).
 *
 * 🔴 UNGATED BY THE DEBUG FLAG, unlike `log`. An error that only appeared when
 * debugging was on would be missing from exactly the session someone is trying
 * to explain afterwards.
 *
 * Ensures:
 *   - always writes to `console.error`
 *   - the panel line is prefixed `ERROR: ` and typed `error`
 */
export function error( message: string, ...args: unknown[] ): void {
  console.error( `[Notifications ERROR] ${ message }`, ...args );
  toPanel( `ERROR: ${ message }`, "error" );
}

/**
 * A WebSocket diagnostic. Legacy `wsDiag` (notifications.js:21166).
 *
 * ⚠️ PREFIXED `WS-DIAG:` IN THE PANEL BUT TYPED `info`, which is legacy's own
 * choice: a diagnostic is not an error, and colouring it like one would make a
 * healthy reconnect look like a failure.
 *
 * Ensures:
 *   - always writes to `console.log`, with legacy's `[WS-DIAG]` prefix
 *   - the panel line is prefixed `WS-DIAG: ` and typed `info`
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line — `log` and `error` above carry no conditional either and c8 reports them clean; only the file's LAST export gets it.
export function wsDiag( message: string, ...args: unknown[] ): void {
  console.log( `[WS-DIAG] ${ message }`, ...args );
  toPanel( `WS-DIAG: ${ message }`, "info" );
}
