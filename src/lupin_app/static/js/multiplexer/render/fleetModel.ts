/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP12 — Fleet-Status pure model + formatters (F12).
//
// Ports the PURE (no-DOM) half of the legacy fleet-status block
// (notifications.js:8490-8617, 8718-8755, 8869-8894): hierarchy grouping,
// liveness split, label/tooltip resolution, and the context-window formatters.
// Kept DOM-free so the table template + store consume one source of truth and
// every branch is unit-testable in isolation.

// ---------------------------------------------------------------------------
// Wire shapes (all fields optional — rendered defensively)
// ---------------------------------------------------------------------------

export interface FleetLiveness {
  verdict?           : string;
  bridge_age_s?      : number | null;
  event_age_s?       : number | null;
  commons_age_s?     : number | null;
  idle_prompt_age_s? : number | null;
  freshest_age_s?    : number | null;
}

export interface FleetSession {
  persona?    : string;
  session_id? : string;
  role?       : string;   // "manager" | "worker" | …
  manager?    : string;   // manager persona this worker reports to
  state?      : string;
  holding_on? : string;
  stuck?      : boolean;
  liveness?   : FleetLiveness;
}

export interface FleetContextRecord {
  consumption_pct_of_window? : number | null;
  window_size?               : number | null;
}

export type FleetPersonaMap = Record<string, FleetContextRecord>;

export interface FleetGroup {
  managerPersona : string | null;
  manager        : FleetSession | null;
  isUnmanaged    : boolean;
  workers        : FleetSession[];
}

export interface FleetModel {
  totalCount : number;
  groups     : FleetGroup[];
}

export interface FleetComposite {
  status?           : string;
  app_timezone?     : string;
  fleet_arbiter?    : { sessions?: FleetSession[] } | null;
  context_pressure? : { personas?: FleetPersonaMap } | null;
}

// ---------------------------------------------------------------------------
// Label + tooltip
// ---------------------------------------------------------------------------

/**
 * Resolve the "Who" label: persona preferred, short session_id (first 8 chars)
 * fallback, "unknown" if neither present. Pure.
 */
export function fleetLabelOf( session: FleetSession | null | undefined ): string {
  if ( !session ) return "unknown";
  if ( session.persona ) return session.persona;
  if ( session.session_id ) return String( session.session_id ).slice( 0, 8 );
  return "unknown";
}

/**
 * Build the hover tooltip from the raw 4 ages (§5 — voluminous detail folds
 * into a tooltip). Null/undefined ages render "n/a". Pure.
 */
export function fleetLivenessTooltip( liveness: FleetLiveness | null | undefined ): string {
  if ( !liveness ) return "no liveness data";
  const fmt = ( v: number | null | undefined ): string =>
    ( v === null || v === undefined ) ? "n/a" : `${v}s`;
  return [
    `bridge ${fmt( liveness.bridge_age_s )}`,
    `event ${fmt( liveness.event_age_s )}`,
    `commons ${fmt( liveness.commons_age_s )}`,
    `idle_prompt ${fmt( liveness.idle_prompt_age_s )}`,
    `freshest ${fmt( liveness.freshest_age_s )}`,
  ].join( " · " );
}

// ---------------------------------------------------------------------------
// Hierarchy grouping + liveness split (accept `unknown` for defensive parity)
// ---------------------------------------------------------------------------

function asRows( sessions: unknown ): Array<FleetSession | null | undefined> {
  return Array.isArray( sessions ) ? ( sessions as Array<FleetSession | null | undefined> ) : [];
}

/**
 * Build the hierarchy model (§7): managers as top-level groups (persona-sorted),
 * workers attached to their manager's group or the single trailing "Unmanaged"
 * bucket (degrade-safe — a worker is NEVER mis-parented). Pure.
 */
export function groupFleetByManager( sessions: unknown ): FleetModel {
  const rows = asRows( sessions );

  const managers = rows.filter( ( s ) => !!s && s.role === "manager" ) as FleetSession[];
  const workers  = rows.filter( ( s ) => !s || s.role !== "manager" );

  const sortedManagers = managers
    .slice()
    .sort( ( a, b ) => fleetLabelOf( a ).localeCompare( fleetLabelOf( b ) ) );

  const groupByPersona = new Map<string, FleetGroup>();
  const managerGroups: FleetGroup[] = [];
  sortedManagers.forEach( ( mgr ) => {
    const group: FleetGroup = {
      managerPersona : mgr.persona ?? null,
      manager        : mgr,
      isUnmanaged    : false,
      workers        : [],
    };
    managerGroups.push( group );
    if ( mgr.persona ) groupByPersona.set( mgr.persona, group );
  } );

  const unmanaged: FleetSession[] = [];
  workers.forEach( ( w ) => {
    const mgrPersona = w && w.manager;
    if ( mgrPersona && groupByPersona.has( mgrPersona ) ) {
      groupByPersona.get( mgrPersona )!.workers.push( w as FleetSession );
    } else {
      // Falsy worker entries collapse to a defensive empty row in the Unmanaged
      // bucket (parity with legacy `!s || s.role !== "manager"` capture).
      unmanaged.push( ( w ?? {} ) as FleetSession );
    }
  } );

  const byLabel = ( a: FleetSession, b: FleetSession ): number =>
    fleetLabelOf( a ).localeCompare( fleetLabelOf( b ) );
  managerGroups.forEach( ( g ) => g.workers.sort( byLabel ) );
  unmanaged.sort( byLabel );

  const groups = managerGroups.slice();
  if ( unmanaged.length > 0 ) {
    groups.push( { managerPersona: null, manager: null, isUnmanaged: true, workers: unmanaged } );
  }

  return { totalCount: rows.length, groups };
}

/**
 * Partition sessions into live vs offline (D6 / §5.1). OFFLINE only when
 * `liveness.verdict === "offline"`; rows without a verdict stay LIVE. Pure.
 */
export function splitFleetByLiveness(
  sessions: unknown,
): { live: FleetSession[]; offline: FleetSession[] } {
  const rows = asRows( sessions );
  const isOffline = ( s: FleetSession | null | undefined ): boolean =>
    !!( s && s.liveness && s.liveness.verdict === "offline" );
  return {
    live    : rows.filter( ( s ) => !isOffline( s ) ).map( ( s ) => ( s ?? {} ) as FleetSession ),
    offline : rows.filter( ( s ) => isOffline( s ) ) as FleetSession[],
  };
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

/**
 * Compact context-window size: exact-million → "<n>M", exact-thousand → "<n>K",
 * else integer string; falsy/non-positive → "—". Pure.
 */
export function formatWindowSize( windowSize: number | null | undefined ): string {
  if ( !windowSize || windowSize <= 0 ) return "—";
  if ( windowSize % 1000000 === 0 ) return `${windowSize / 1000000}M`;
  if ( windowSize % 1000 === 0 ) return `${windowSize / 1000}K`;
  return String( windowSize );
}

/**
 * "% of context window consumed": numeric → "<pct>%"; null/undefined → "—".
 * Pure (backend pre-rounds to 1 decimal).
 */
export function formatConsumptionPct( pct: number | null | undefined ): string {
  if ( pct === null || pct === undefined ) return "—";
  return `${pct}%`;
}

// ---------------------------------------------------------------------------
// Color-coding helpers (WP12 color follow-on — mirror legacy _fleetVerdictClass
// + _fleetPctClass, commit f2733cf). Color is ALWAYS redundant with the verdict
// WORD / numeric % in the rendered cell (WCAG 1.4.1); these only pick a class.
// ---------------------------------------------------------------------------

/**
 * Map a liveness verdict to its status-dot + row-accent color class. Pure.
 *
 * Requires:
 *   - verdict is a string (e.g. "live", "quiet (idle)"), or null/undefined
 * Ensures:
 *   - keys on the FIRST whitespace-delimited word, trimmed + lowercased:
 *     "live"→fleet-verdict-live, "quiet …"→…-quiet, "stale …"→…-stale,
 *     "offline"→…-offline
 *   - anything else (empty / non-string / unrecognized) → fleet-verdict-unknown
 *   - never throws
 */
export function fleetVerdictClass( verdict: string | null | undefined ): string {
  const tokens = typeof verdict === "string" ? verdict.trim().split( /\s+/ ) : [];
  const word   = ( tokens.shift() ?? "" ).toLowerCase();
  if ( word === "live" )    return "fleet-verdict-live";
  if ( word === "quiet" )   return "fleet-verdict-quiet";
  if ( word === "stale" )   return "fleet-verdict-stale";
  if ( word === "offline" ) return "fleet-verdict-offline";
  return "fleet-verdict-unknown";
}

/**
 * Map a "% of context window consumed" to its heat-tint cell class. Pure.
 *
 * Requires:
 *   - pct is a number, or null/undefined for unmeasured
 * Ensures:
 *   - low  : pct < 50        → "fleet-pct-low"   (green — healthy headroom; 0% tints low)
 *   - mid  : 50 ≤ pct < 80   → "fleet-pct-mid"   (amber — watch)
 *   - high : pct ≥ 80        → "fleet-pct-high"  (red + bold — pressure)
 *   - null/undefined/non-number/NaN → "" (the em-dash cell stays UNTINTED)
 *   - never throws
 */
export function fleetHeatClass( pct: number | null | undefined ): string {
  if ( pct === null || pct === undefined || typeof pct !== "number" || Number.isNaN( pct ) ) return "";
  if ( pct < 50 ) return "fleet-pct-low";
  if ( pct < 80 ) return "fleet-pct-mid";
  return "fleet-pct-high";
}

/**
 * Format a Date as "HH:MM:SS TZ" in the configured IANA zone via
 * Intl.DateTimeFormat (DST-aware). Invalid/absent zone → browser-local. Pure.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (try/catch default-param interplay).
export function formatFleetTimestamp( date: Date, ianaZone: string | null | undefined ): string {
  const opts: Intl.DateTimeFormatOptions = {
    hour12       : false,
    hour         : "2-digit",
    minute       : "2-digit",
    second       : "2-digit",
    timeZoneName : "short",
  };
  if ( ianaZone ) {
    try {
      return new Intl.DateTimeFormat( undefined, { ...opts, timeZone: ianaZone } ).format( date );
    } catch {
      // Invalid IANA zone — degrade to browser-local (never throw).
    }
  }
  return new Intl.DateTimeFormat( undefined, opts ).format( date );
}
