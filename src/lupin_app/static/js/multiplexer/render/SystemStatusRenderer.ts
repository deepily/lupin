/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-5 — System Status, ported from legacy's section at
// notifications.html:1309-1373 and the five methods that drive it:
//   - `refreshAllStatus`        notifications.js:1460  ↻, in order, finally re-enable
//   - `refreshWebSocketStatus`  notifications.js:1504  the two socket pills (S1, S2)
//   - `refreshAuthStatus`       notifications.js:1537  auth + user (S3)
//   - `refreshSessionDisplay`   notifications.js:1576  the two session codes (S6)
//   - `checkWebSocketHealth`    notifications.js:1125  the health line (S7)
//   - `copyToClipboard`         notifications.js:1585  📋, and its no-op rule (S6)
//   - `reinitializeConfig`      notifications.js:1399  the Config row (S8, B-5L)
//
// 🔴 THE CONFIG RELOAD BUTTON IS NOT GATED, AND THAT IS A RULING THAT REVERSED
// AN EARLIER ONE. The build plan's §3 R8 says admin-only in both clients, and an
// earlier attempt (eadcf5ba) built it that way. Rick ruled on 2026-09-23 that the
// gate is a DIVERGENCE: legacy `reinitializeConfig` contains no admin check —
// `admin` matches zero lines in notifications.js:1399-1458 — so the multiplexer
// must not invent one. The later ruling governs. Do not "restore" the gate from
// the plan document without checking which ruling is current.
//
// ⚠️ AND THE ENDPOINT IS STILL OPEN EITHER WAY. `/api/init` carries no
// `Depends(get_current_user)`, so a gate on this button would stop neither a
// curl nor any direct request. Nothing here secures `/api/init`; that is server
// work and its own row. No claim in this file or its tests says otherwise.
//
// 🔴 WHAT THIS PANE DOES *NOT* RE-IMPLEMENT: legacy's 90-second watchdog pokes
// `channel._tickWatchdog()` to nudge a dead socket back to life. The
// multiplexer's `ConnectionStateMachine` owns reconnection itself, with its own
// backoff and circuit breaker, so poking it from here would be a second thing
// deciding when to reconnect. The 90s interval below is a READOUT refresh and
// nothing more — it re-derives the health line and touches no socket.

import type { AuthManager } from "../auth/AuthManager";
import type { EventBus } from "../shared/EventBus";
import type { ConnectionState, ConnectionStateChangePayload } from "../shared/types";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

/** The one thing this pane asks a transport: what state is it in right now. */
export interface TransportStateLike {
  readonly state: ConnectionState;
}

/** A status pill: the words, and the class that colours them. */
export interface StatusPill { text: string; cls: string }

/**
 * The multiplexer's six connection states mapped to legacy's pill words.
 *
 * 🔴 THE TWO CLIENTS HAVE DIFFERENT STATE MACHINES, AND THIS IS THE SEAM. Legacy
 * maps six WSChannel states (`DISCONNECTED`, `CONNECTING`, `AUTHENTICATING`,
 * `CONNECTED`, `BACKOFF`, `OPEN_CIRCUIT`) at notifications.js:1512. The
 * multiplexer's `ConnectionState` is a different six. The WORDS a user reads are
 * what parity is about, so they are matched here rather than the state names.
 *
 * ⚠️ TWO ASYMMETRIES, NAMED RATHER THAN SMOOTHED OVER:
 *   - legacy's `AUTHENTICATING` has NO multiplexer counterpart — this client
 *     does not surface a distinct authenticating state — so those words can
 *     never appear here. That is a gap in the mapping, not a bug in this table.
 *   - the multiplexer has BOTH `reconnecting` and `backoff` where legacy has one
 *     `BACKOFF`; both take legacy's single "Reconnecting..." because that is
 *     what the user is being told, and telling them two different things about
 *     one situation would be the divergence.
 */
export const CONNECTION_PILLS: Readonly<Record<ConnectionState, StatusPill>> = Object.freeze( {
  connecting   : { text: "Connecting...",   cls: "status-warning" },
  connected    : { text: "Connected",       cls: "status-good"    },
  reconnecting : { text: "Reconnecting...", cls: "status-warning" },
  backoff      : { text: "Reconnecting...", cls: "status-warning" },
  offline      : { text: "Disconnected",    cls: "status-error"   },
  failed       : { text: "Circuit open",    cls: "status-error"   },
} );

/** What a socket row reads when no transport was wired at all (legacy's else-leg). */
export const NOT_INITIALIZED_PILL: StatusPill = Object.freeze( { text: "Not initialized", cls: "status-error" } );

/**
 * The seeded values (B10) — what every row reads before the first refresh.
 *
 * ⚠️ THESE ARE THE SPEC, NOT PLACEHOLDERS SOMEBODY PICKED. "Disconnected" before
 * a socket has tried is a claim, and it is legacy's claim; changing it to
 * "Unknown" would be more honest and would also be a divergence.
 */
export const SEEDED = Object.freeze( {
  socket  : "Disconnected",
  auth    : "Not authenticated",
  user    : "Loading...",
  health  : "Initializing...",
  session : "-",
} );

/** The health line's four texts (S7), verbatim from notifications.js:1125-1160. */
export const HEALTH_MONITORING = "Monitoring (90s interval)";
export const HEALTH_STOPPED    = "Stopped";
export const HEALTH_CIRCUIT    = "Circuit open — click Retry-now";

/** The readout interval. Legacy's watchdog cadence, and its words say so. */
export const HEALTH_INTERVAL_MS = 90_000;

/** How long the 📋 shows its checkmark before reverting (notifications.js:1607). */
export const COPY_FEEDBACK_MS = 1_200;

export interface SystemStatusRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  /** Test helper — run the same pass the ↻ runs, and await it. */
  refreshForTesting(): Promise<void>;
}

export interface SystemStatusRendererOptions {
  eventBus : EventBus;
  auth     : Pick<AuthManager, "getToken" | "getCurrentUserEmail" | "isCurrentUserAdmin">;
  /** The two transports, read for their current state exactly as legacy reads `channel.state`. */
  transports: {
    queue?: TransportStateLike;
    audio?: TransportStateLike;
  };
  /** The session ids boot handed the two transports. */
  sessionIds: { queue: string | null; audio: string | null };
  /** `GET /api/init` — the Config row's door. Injected so a test can drive both outcomes. */
  reinitConfig: () => Promise<{ status?: string; message?: string }>;
  /** Test injection — where a refresh failure is reported. Defaults to the console. */
  logFn?          : ( message: string ) => void;
  // Test injection.
  nowDateFn?      : () => Date;
  clipboardFn?    : ( text: string ) => Promise<void>;
  setTimeoutFn?   : ( cb: () => void, ms: number ) => number;
  clearTimeoutFn? : ( handle: number ) => void;
  setIntervalFn?  : ( cb: () => void, ms: number ) => number;
  clearIntervalFn?: ( handle: number ) => void;
}

interface Row { labelText: string; valueEl: HTMLElement; root: HTMLElement }

function statusRow( label: string, testid: string, seeded: string, seededCls: string ): Row {
  const root = document.createElement( "div" );
  root.className = "status-item";

  const strong = document.createElement( "strong" );
  strong.textContent = `${ label }:`;

  const value = document.createElement( "span" );
  value.setAttribute( "data-testid", testid );
  value.className = seededCls;
  value.textContent = seeded;

  root.append( strong, value );
  return { labelText: label, valueEl: value, root };
}

class SystemStatusRendererImpl implements SystemStatusRenderer {
  private readonly bus         : EventBus;
  private readonly auth        : SystemStatusRendererOptions[ "auth" ];
  private readonly transports  : SystemStatusRendererOptions[ "transports" ];
  private readonly sessionIds  : SystemStatusRendererOptions[ "sessionIds" ];
  private readonly reinitConfig: SystemStatusRendererOptions[ "reinitConfig" ];
  private readonly logFn       : ( message: string ) => void;
  private readonly nowDateFn   : () => Date;
  private readonly clipboardFn : ( text: string ) => Promise<void>;
  private readonly setTimeoutFn   : ( cb: () => void, ms: number ) => number;
  private readonly clearTimeoutFn : ( handle: number ) => void;
  private readonly setIntervalFn  : ( cb: () => void, ms: number ) => number;
  private readonly clearIntervalFn: ( handle: number ) => void;

  private readonly unsubscribers: Array<() => void> = [];

  private root        : HTMLElement | null = null;
  private collapseOff : ( () => void ) | null = null;
  private queuePillEl : HTMLElement | null = null;
  private audioPillEl : HTMLElement | null = null;
  private authEl      : HTMLElement | null = null;
  private userEl      : HTMLElement | null = null;
  private queueCodeEl : HTMLElement | null = null;
  private audioCodeEl : HTMLElement | null = null;
  private healthEl    : HTMLElement | null = null;
  private configEl    : HTMLElement | null = null;
  private reinitBtn   : HTMLButtonElement | null = null;
  private refreshBtn  : HTMLButtonElement | null = null;
  private healthTimer : number | null = null;
  private mounted     = false;

  constructor( opts: SystemStatusRendererOptions ) {
    this.bus          = opts.eventBus;
    this.auth         = opts.auth;
    this.transports   = opts.transports;
    this.sessionIds   = opts.sessionIds;
    this.reinitConfig = opts.reinitConfig;
    /* c8 ignore start */ // production-default fallbacks: the console, runtime clock, clipboard and timers; tests inject all seven.
    this.logFn           = opts.logFn           ?? ( ( m ) => console.warn( m ) );
    this.nowDateFn       = opts.nowDateFn       ?? ( () => new Date() );
    this.clipboardFn     = opts.clipboardFn     ?? ( ( t ) => navigator.clipboard.writeText( t ) );
    this.setTimeoutFn    = opts.setTimeoutFn    ?? ( ( cb, ms ) => globalThis.setTimeout( cb, ms ) as unknown as number );
    this.clearTimeoutFn  = opts.clearTimeoutFn  ?? ( ( h ) => globalThis.clearTimeout( h ) );
    this.setIntervalFn   = opts.setIntervalFn   ?? ( ( cb, ms ) => globalThis.setInterval( cb, ms ) as unknown as number );
    this.clearIntervalFn = opts.clearIntervalFn ?? ( ( h ) => globalThis.clearInterval( h ) );
    /* c8 ignore stop */
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "SystemStatusRenderer already mounted" );

    // A <button>, so the shared header guard refuses to collapse on its click —
    // the structural equivalent of legacy's hand-written stopPropagation (B2).
    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "refresh-link system-status-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-status-refresh-btn" );
    refreshBtn.setAttribute( "title", "Refresh all status information" );
    refreshBtn.textContent = "↻";
    refreshBtn.addEventListener( "click", () => { void this.refreshAll(); } );
    this.refreshBtn = refreshBtn;

    const header = renderSectionHeader( {
      icon    : "📊",
      title   : "System Status",
      testid  : "multiplexer-system-status-header",
      actions : [ refreshBtn ],
    } );
    // B7 — static header, no count. There is no one number this pane counts.

    const body = document.createElement( "div" );
    body.className = "section-content system-status-body";

    const queueRow = statusRow( "Queue WebSocket", "multiplexer-ws-queue-status", SEEDED.socket, "status-warning" );
    const audioRow = statusRow( "Audio WebSocket", "multiplexer-ws-audio-status", SEEDED.socket, "status-warning" );
    const authRow  = statusRow( "Authentication",  "multiplexer-auth-status",     SEEDED.auth,   "status-warning" );
    const userRow  = statusRow( "User",            "multiplexer-user-display",    SEEDED.user,   "" );
    this.queuePillEl = queueRow.valueEl;
    this.audioPillEl = audioRow.valueEl;
    this.authEl      = authRow.valueEl;
    this.userEl      = userRow.valueEl;

    // The sessions row is the one with structure — two codes, each with its own
    // 📋. Built here rather than through statusRow() because it holds a list.
    const sessionsRoot = document.createElement( "div" );
    sessionsRoot.className = "status-item";
    const sessionsLabel = document.createElement( "strong" );
    sessionsLabel.textContent = "Sessions:";
    const sessionList = document.createElement( "div" );
    sessionList.className = "session-list";
    const queueEntry = this.sessionEntry( "Queue", "multiplexer-queue-session" );
    const audioEntry = this.sessionEntry( "Audio", "multiplexer-audio-session" );
    this.queueCodeEl = queueEntry.code;
    this.audioCodeEl = audioEntry.code;
    sessionList.append( queueEntry.root, audioEntry.root );
    sessionsRoot.append( sessionsLabel, sessionList );

    const healthRow = statusRow( "Health Monitor", "multiplexer-ws-health-status", SEEDED.health, "status-info" );
    this.healthEl = healthRow.valueEl;

    // --- the Config row (S8 / B-5L) -----------------------------------------
    const configRoot = document.createElement( "div" );
    configRoot.className = "status-item";
    const configLabel = document.createElement( "strong" );
    configLabel.textContent = "Config:";

    // 🔴 A PLAIN BUTTON. No admin check, no hidden state — Rick's 2026-09-23
    // ruling. Legacy's is plain too, and the earlier admin-gated build was ruled
    // a divergence.
    const reinitBtn = document.createElement( "button" );
    reinitBtn.type = "button";
    reinitBtn.className = "reinit-config-btn";
    reinitBtn.id = "reinit-config-btn";
    reinitBtn.setAttribute( "data-testid", "multiplexer-config-reload-btn" );
    reinitBtn.textContent = "↻ Reload";
    reinitBtn.addEventListener( "click", () => { void this.reinit(); } );
    this.reinitBtn = reinitBtn;

    const configStatus = document.createElement( "span" );
    configStatus.className = "config-status";
    configStatus.setAttribute( "data-testid", "multiplexer-config-status" );
    this.configEl = configStatus;

    configRoot.append( configLabel, reinitBtn, configStatus );

    body.append( queueRow.root, audioRow.root, authRow.root, userRow.root,
                 sessionsRoot, healthRow.root, configRoot );
    root.replaceChildren( header.header, body );

    // B3 — session-only collapse. Persistence is available since A-2 #6, so its
    // absence here is a decision: legacy does not persist this section either.
    this.collapseOff = wireSectionCollapse( root, header as SectionHeaderHandle );
    this.root    = root;
    this.mounted = true;

    // S1/S2 — the pills follow socket EVENTS, not only the ↻. A pane that
    // repainted only on demand would show a stale "Connected" through an
    // outage, which is the reading most likely to stop someone investigating.
    this.unsubscribers.push(
      this.bus.on<ConnectionStateChangePayload>( "connection_state_change", ( e ) => {
        this.paintSockets();
        this.paintHealth();
        void e;
      } ),
    );

    this.paintSockets();
    this.paintSessions();
    void this.refreshAuth();
    this.setHealth( HEALTH_MONITORING, "status-info" );
    this.healthTimer = this.setIntervalFn( () => this.paintHealth(), HEALTH_INTERVAL_MS );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.collapseOff !== null ) this.collapseOff();
    this.collapseOff = null;
    if ( this.healthTimer !== null ) {
      this.clearIntervalFn( this.healthTimer );
      this.healthTimer = null;
    }
    // The readout stopped, and the line says so rather than freezing on its
    // last reading — a stale "✓ Healthy" outliving the monitor is the failure
    // this string exists to prevent.
    this.setHealth( HEALTH_STOPPED, "status-warning" );
    if ( this.root !== null ) this.root.replaceChildren();
    this.root = null;
    this.queuePillEl = this.audioPillEl = this.authEl = this.userEl = null;
    this.queueCodeEl = this.audioCodeEl = this.healthEl = this.configEl = null;
    this.reinitBtn = this.refreshBtn = null;
    this.mounted = false;
  }

  refreshForTesting(): Promise<void> {
    return this.refreshAll();
  }

  // -------------------------------------------------------------------------

  private sessionEntry( label: string, testid: string ): { root: HTMLElement; code: HTMLElement } {
    const root = document.createElement( "div" );
    root.className = "session-entry";

    const name = document.createElement( "span" );
    name.className = "session-label";
    name.textContent = `${ label }:`;

    const code = document.createElement( "code" );
    code.setAttribute( "data-testid", testid );
    code.textContent = SEEDED.session;

    const copy = document.createElement( "button" );
    copy.type = "button";
    copy.className = "copy-btn";
    copy.setAttribute( "data-testid", `${ testid }-copy` );
    copy.setAttribute( "title", `Copy ${ label } session ID` );
    copy.textContent = "📋";
    copy.addEventListener( "click", () => { void this.copy( code, copy ); } );

    root.append( name, code, copy );
    return { root, code };
  }

  /**
   * ↻ — legacy `refreshAllStatus` (notifications.js:1460).
   *
   * Ensures:
   *   - the button is disabled and spinning for the duration
   *   - the four readouts run IN legacy's order
   *   - a throw anywhere in the pass is CAUGHT and logged, exactly as legacy's
   *     own try/catch does — 🔴 one readout failing must not abandon the others
   *     half-painted, leaving rows from two different moments side by side
   *   - the button is re-enabled in a `finally`, whatever happened (B8)
   *   - never rejects
   */
  private async refreshAll(): Promise<void> {
    const btn = this.refreshBtn;
    try {
      if ( btn !== null ) {
        btn.disabled = true;
        btn.classList.add( "spinning" );
      }
      this.paintSockets();
      await this.refreshAuth();
      this.paintSessions();
      this.paintHealth();
    } catch ( err ) {
      // Legacy: `catch ( error ) { this.error( "Status refresh error:", error ) }`
      // (notifications.js:1493). Without it a throwing auth read would reject out
      // of a click handler as an unhandled rejection, which surfaces nowhere the
      // operator can see.
      this.logFn( `SystemStatusRenderer: status refresh failed: ${ String( err ) }` );
    } finally {
      // 🔴 IN A `finally`. A refresh that threw and left the control disabled
      // would look like a hung pane, and the operator's only remedy would be a
      // page reload — which is exactly what they were trying to avoid.
      if ( btn !== null ) {
        btn.disabled = false;
        btn.classList.remove( "spinning" );
      }
    }
  }

  /** S1 + S2 — both socket pills, from the transports' own current state. */
  private paintSockets(): void {
    this.paintPill( this.queuePillEl, this.transports.queue );
    this.paintPill( this.audioPillEl, this.transports.audio );
  }

  private paintPill( el: HTMLElement | null, transport: TransportStateLike | undefined ): void {
    /* c8 ignore next */ // defensive: the pill elements are created at mount and nulled in unmount, in lockstep with `mounted`.
    if ( el === null ) return;
    const pill = transport === undefined ? NOT_INITIALIZED_PILL : CONNECTION_PILLS[ transport.state ];
    el.textContent = pill.text;
    el.className   = pill.cls;
  }

  /**
   * S3 — the auth row and the user row, legacy `refreshAuthStatus`.
   *
   * Ensures:
   *   - no usable token → "Not authenticated" / "Not logged in"
   *   - a token that cannot be refreshed → "Token expired", and the USER row is
   *     left alone, exactly as legacy returns early without touching it
   *   - otherwise "Authenticated", plus " (admin)" when the role is carried
   *   - 🔴 NEVER REJECTS, and that is load-bearing: `mount()` calls this
   *     fire-and-forget, so there is no caller to catch anything it throws
   */
  private async refreshAuth(): Promise<void> {
    // 🔴 THE WHOLE BODY IS GUARDED, NOT JUST THE `getToken()` AWAIT. `mount()`
    // calls this fire-and-forget, so a rejection here has no caller to catch it
    // and becomes an unhandled rejection — which surfaces nowhere the operator
    // can see. The first cut guarded only the await, and a throwing
    // `getCurrentUserEmail()` INSIDE the catch block escaped it; node's test
    // runner reported it as activity after the test ended, which is the one
    // place that failure is visible at all.
    try {
      let tokenOk = true;
      try {
        await this.auth.getToken();
      } catch {
        tokenOk = false;
      }

      if ( !tokenOk ) {
        // Legacy distinguishes "no token at all" from "refresh failed"; this
        // client's `getToken()` rejects for both, and the email claim is what
        // separates them — a stored-but-dead token still carries one.
        if ( this.auth.getCurrentUserEmail() !== null ) {
          this.setStatus( this.authEl, "Token expired", "status-error" );
        } else {
          this.setStatus( this.authEl, SEEDED.auth, "status-warning" );
          this.setStatus( this.userEl, "Not logged in", "" );
        }
        return;
      }

      const email   = this.auth.getCurrentUserEmail() ?? "Unknown";
      const isAdmin = this.auth.isCurrentUserAdmin();
      this.setStatus( this.userEl, email, "" );
      this.setStatus( this.authEl, `Authenticated${ isAdmin ? " (admin)" : "" }`, "status-good" );
    } catch ( err ) {
      this.logFn( `SystemStatusRenderer: auth readout failed: ${ String( err ) }` );
    }
  }

  /** S6 — both session codes, or legacy's `-` for an absent one. */
  private paintSessions(): void {
    this.setStatus( this.queueCodeEl, this.sessionIds.queue ?? SEEDED.session, "" );
    this.setStatus( this.audioCodeEl, this.sessionIds.audio ?? SEEDED.session, "" );
  }

  /**
   * S6 — 📋, legacy `copyToClipboard`.
   *
   * Ensures:
   *   - an empty value or the `-` placeholder copies NOTHING and gives no
   *     feedback — a checkmark over a copied dash is a lie about what happened
   *   - otherwise the text is copied and the button shows ✅ briefly
   */
  private async copy( code: HTMLElement, btn: HTMLElement ): Promise<void> {
    /* c8 ignore next */ // `textContent` is typed `string | null` but is never null for an Element; the ?? arm is unreachable, and a second element-null check would be a branch no test could enter either.
    const text = ( code.textContent ?? "" ).trim();
    if ( text === "" || text === SEEDED.session ) return;
    await this.clipboardFn( text );
    const original = btn.textContent;
    btn.textContent = "✅";
    this.setTimeoutFn( () => { btn.textContent = original; }, COPY_FEEDBACK_MS );
  }

  /**
   * S7 — the health line, legacy `checkWebSocketHealth`.
   *
   * ⚠️ A READOUT ONLY. Legacy also pokes each channel's watchdog here; this
   * client's `ConnectionStateMachine` owns reconnection, and a second nudge
   * would be a second thing deciding when to reconnect.
   */
  private paintHealth(): void {
    const queue = this.transports.queue?.state;
    const audio = this.transports.audio?.state;

    if ( queue === "connected" && audio === "connected" ) {
      this.setHealth( `✓ Healthy (checked ${ this.nowDateFn().toLocaleTimeString() })`, "status-success" );
    } else if ( queue === "failed" || audio === "failed" ) {
      this.setHealth( HEALTH_CIRCUIT, "status-error" );
    } else {
      this.setHealth( `Watchdog: queue=${ queue ?? "none" } audio=${ audio ?? "none" }`, "status-warning" );
    }
  }

  /**
   * S8 / B-5L — the Config reload, legacy `reinitializeConfig`.
   *
   * Ensures:
   *   - the button is disabled and dimmed for the duration
   *   - any previous message is cleared BEFORE the call, so a stale ✗ is never
   *     read as the result of this press
   *   - `status === "success"` writes a green ✓; anything else writes a red
   *     ✗ with the server's own message
   *   - a throw writes a red ✗ with the error's message, or "Network error"
   *   - the button is re-enabled in a `finally`, whatever happened
   *   - never rejects, and NOTHING here secures `/api/init`
   */
  private async reinit(): Promise<void> {
    const btn = this.reinitBtn;
    const out = this.configEl;
    try {
      if ( btn !== null ) {
        btn.disabled = true;
        btn.style.opacity = "0.6";
      }
      if ( out !== null ) {
        out.textContent = "";
        out.className = "config-status";
      }

      const data = await this.reinitConfig();
      if ( data.status === "success" ) {
        this.setStatus( out, "✓", "config-status config-status-ok" );
      } else {
        this.setStatus( out, `✗ ${ data.message ?? "" }`, "config-status config-status-error" );
      }
    } catch ( err ) {
      const message = err instanceof Error && err.message !== "" ? err.message : "Network error";
      this.setStatus( out, `✗ ${ message }`, "config-status config-status-error" );
    } finally {
      if ( btn !== null ) {
        btn.disabled = false;
        btn.style.opacity = "1";
      }
    }
  }

  private setStatus( el: HTMLElement | null, text: string, cls: string ): void {
    /* c8 ignore next */ // defensive: every element is created at mount and nulled in unmount, in lockstep with `mounted`.
    if ( el === null ) return;
    el.textContent = text;
    if ( cls !== "" ) el.className = cls;
  }

  private setHealth( text: string, cls: string ): void {
    this.setStatus( this.healthEl, text, cls );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function createSystemStatusRenderer( opts: SystemStatusRendererOptions ): SystemStatusRenderer {
  return new SystemStatusRendererImpl( opts );
}
