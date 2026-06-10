// Fleet-Status panel (read-only operator view) — P2 frontend unit tests.
//
// Design: src/rnd/v0.1.8/2026.06.09-fleet-status-table-notifications-client/01-design.md
//   §5 (six columns) · §6 (fetch/render/poll + states) · §7 (hierarchy model) · §8 (tests).
//
// Mirrors the established notifications.js harness (manager_badge_strip.test.ts):
// load the class via vm.runInThisContext (sliced before the DOM-ready init),
// Object.create the prototype to skip the constructor, hand-set the few fields
// the methods read, then drive the methods directly under happy-dom.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/fleet_status_panel.test.ts
// Coverage (c8):
//   npx c8 --include='src/lupin_app/static/js/notifications.js' --reporter=text \
//       npx tsx --test src/tests/unit/notifications_js/fleet_status_panel.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  // Pass `filename` so V8 script coverage maps to the real source path and c8 can
  // attribute it (the line-prefix slice preserves original line numbers).
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type FleetUI = Record<string, unknown> & {
  fetchFleetState: () => Promise<Record<string, unknown>>;
  groupFleetByManager: ( sessions: unknown ) => { totalCount: number; groups: GroupModel[] };
  _splitFleetByLiveness: ( sessions: unknown ) => { live: Record<string, unknown>[]; offline: Record<string, unknown>[] };
  _fleetOfflineToggleHtml: ( offlineCount: number, showOffline: boolean ) => string;
  toggleFleetShowOffline: () => void;
  fleetShowOffline: boolean;
  _lastFleetComposite: unknown;
  _fleetLabelOf: ( session: unknown ) => string;
  _fleetLivenessTooltip: ( liveness: unknown ) => string;
  _formatWindowSize: ( windowSize: number | null | undefined ) => string;
  _formatConsumptionPct: ( pct: number | null | undefined ) => string;
  _fleetVerdictClass: ( verdict: unknown ) => string;
  _fleetPctClass: ( pct: number | null | undefined ) => string;
  renderFleetStatusTable: ( model: { groups: GroupModel[] }, personas?: Record<string, unknown> ) => string;
  _renderFleetRow: ( session: Record<string, unknown>, indented: boolean, personas?: Record<string, unknown> ) => string;
  renderFleetStatus: ( composite: unknown ) => void;
  _formatFleetTimestamp: ( date: Date, ianaZone: string | null | undefined ) => string;
  _stampFleetStatusUpdated: ( ianaZone: string | null | undefined ) => void;
  refreshFleetStatus: () => Promise<void>;
  startFleetStatusPolling: () => void;
  stopFleetStatusPolling: () => void;
  authedFetch: ( url: string ) => Promise<unknown>;
  _fleetStatusFetchInFlight: boolean;
  fleetStatusPollIntervalHandle: ReturnType<typeof setInterval> | null;
  FLEET_STATUS_POLL_INTERVAL_MS: number;
};

type GroupModel = {
  managerPersona: string | null;
  manager: Record<string, unknown> | null;
  isUnmanaged: boolean;
  workers: Record<string, unknown>[];
};

function newUI(): FleetUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as FleetUI;
  ui.debug                         = false;
  ui.log                           = (): void => {};
  ui._fleetStatusFetchInFlight     = false;
  ui.fleetStatusPollIntervalHandle = null;
  ui.FLEET_STATUS_POLL_INTERVAL_MS = 60000;
  return ui;
}

function buildPanelDOM(): void {
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.id = "section-fleet-status";
  section.innerHTML = `
    <h3>Fleet Status: <span id="fleet-status-count">0</span>
        <span id="fleet-status-updated"></span></h3>
    <div id="fleet-status-container"></div>`;
  document.body.appendChild( section );
}

// Minimal Response-like stub for authedFetch fakes.
function fakeResponse( status: number, ok: boolean, jsonBody: unknown ): unknown {
  return { status, ok, json: async () => jsonBody };
}

// Representative session rows (the locked §4 contract shape).
const TIBERIUS = { session_id: "d9e65cd8", persona: "Tiberius", state: "working", holding_on: "none",
                   stuck: false, role: "manager", manager: null,
                   liveness: { bridge_age_s: 4, event_age_s: 2100, commons_age_s: null,
                               idle_prompt_age_s: null, freshest_age_s: 4, verdict: "LIVE" } };
const RIO      = { session_id: "110ff47d", persona: "Rio", state: "working", holding_on: "none",
                   stuck: false, role: "worker", manager: "Tiberius",
                   liveness: { bridge_age_s: 10, event_age_s: 30, commons_age_s: 5,
                               idle_prompt_age_s: 60, freshest_age_s: 5, verdict: "LIVE" } };
const RADIO    = { session_id: "aa11bb22", persona: "Mr. Radio", state: "stuck", holding_on: "peer:Rio",
                   stuck: true, role: "worker", manager: "Tiberius",
                   liveness: { bridge_age_s: 720, event_age_s: 720, commons_age_s: 720,
                               idle_prompt_age_s: 720, freshest_age_s: 720, verdict: "stale 12m" } };
const MARIA    = { session_id: "cc33dd44", persona: "María", state: "idle", holding_on: "none",
                   stuck: false, role: "worker", manager: null,
                   liveness: { bridge_age_s: 360, event_age_s: 360, commons_age_s: 360,
                               idle_prompt_age_s: 360, freshest_age_s: 360, verdict: "quiet 6m" } };
// A days-stale dead session (the graveyard D6/§5.1 filters out by default).
const OFFLINE  = { session_id: "ee55ff66", persona: "Krishna", state: "idle", holding_on: "none",
                   stuck: false, role: "worker", manager: "Tiberius",
                   liveness: { bridge_age_s: null, event_age_s: 300000, commons_age_s: null,
                               idle_prompt_age_s: null, freshest_age_s: 300000, verdict: "offline" } };

// The context_pressure.personas map (keyed by persona) joined into the table for the
// "% Window" + "Window" columns. Tiberius rides a 1M window; Rio a 200K window; María
// is present but unmeasured (idle → null consumption). Mr. Radio is intentionally absent
// (no record) to exercise the missing-persona → "—" path.
const CONTEXT_PERSONAS = {
  "Tiberius" : { window_size: 1000000, consumption_pct_of_window: 21.9 },
  "Rio"      : { window_size: 200000,  consumption_pct_of_window: 8.4 },
  "María"    : { window_size: 1000000, consumption_pct_of_window: null },
};

beforeEach( () => { document.body.replaceChildren(); } );

// ─────────────────────────── groupFleetByManager (pure, §7) ───────────────────────────

test( "groupFleetByManager nests workers under their manager and sorts by persona", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( [ RADIO, TIBERIUS, RIO ] );
  assert.equal( model.totalCount, 3 );
  assert.equal( model.groups.length, 1, "one manager group, no unmanaged" );
  const g = model.groups[ 0 ];
  assert.equal( g.isUnmanaged, false );
  assert.equal( g.managerPersona, "Tiberius" );
  assert.equal( g.workers.length, 2 );
  // workers sorted by label: "Mr. Radio" < "Rio"
  assert.deepEqual( g.workers.map( w => w.persona ), [ "Mr. Radio", "Rio" ] );
} );

test( "groupFleetByManager puts manager-less workers in an Unmanaged group, placed LAST", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( [ TIBERIUS, RIO, MARIA ] );
  assert.equal( model.groups.length, 2 );
  const last = model.groups[ model.groups.length - 1 ];
  assert.equal( last.isUnmanaged, true );
  assert.equal( last.managerPersona, null );
  assert.deepEqual( last.workers.map( w => w.persona ), [ "María" ] );
} );

test( "groupFleetByManager: worker whose manager has no matching manager-group falls to Unmanaged (never mis-parented)", () => {
  const ui = newUI();
  const orphan = { ...RIO, manager: "GhostManager" };  // no GhostManager in the set
  const model = ui.groupFleetByManager( [ TIBERIUS, orphan ] );
  // Tiberius group has zero workers; orphan landed in Unmanaged.
  const mgrGroup = model.groups.find( g => g.managerPersona === "Tiberius" )!;
  assert.equal( mgrGroup.workers.length, 0 );
  const unmanaged = model.groups.find( g => g.isUnmanaged )!;
  assert.deepEqual( unmanaged.workers.map( w => w.persona ), [ "Rio" ] );
} );

test( "groupFleetByManager: empty input → no groups", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( [] );
  assert.equal( model.totalCount, 0 );
  assert.deepEqual( model.groups, [] );
} );

test( "groupFleetByManager: non-array input is treated as empty", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( null );
  assert.equal( model.totalCount, 0 );
  assert.deepEqual( model.groups, [] );
} );

test( "groupFleetByManager: a manager with no workers still renders as a group", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( [ TIBERIUS ] );
  assert.equal( model.groups.length, 1 );
  assert.equal( model.groups[ 0 ].managerPersona, "Tiberius" );
  assert.equal( model.groups[ 0 ].workers.length, 0 );
} );

test( "groupFleetByManager: multiple managers are persona-sorted", () => {
  const ui = newUI();
  const zara = { session_id: "z1", persona: "Zara", role: "manager", manager: null };
  const abe  = { session_id: "a1", persona: "Abe",  role: "manager", manager: null };
  const model = ui.groupFleetByManager( [ zara, abe ] );
  assert.deepEqual( model.groups.map( g => g.managerPersona ), [ "Abe", "Zara" ] );
} );

test( "groupFleetByManager: a manager missing a persona forms a group but attracts no by-persona workers", () => {
  const ui = newUI();
  const namelessMgr = { session_id: "nomgr01", role: "manager", manager: null };  // no persona
  const worker      = { session_id: "w01", persona: "Solo", role: "worker", manager: null };
  const model = ui.groupFleetByManager( [ namelessMgr, worker ] );
  const mgrGroup = model.groups.find( g => !g.isUnmanaged )!;
  assert.equal( mgrGroup.managerPersona, null );
  assert.equal( mgrGroup.workers.length, 0 );
  assert.ok( model.groups.some( g => g.isUnmanaged ), "the persona-less worker lands in Unmanaged" );
} );

// ─────────────────────────── _fleetLabelOf (pure) ───────────────────────────

test( "_fleetLabelOf prefers persona, falls back to short sid, then unknown", () => {
  const ui = newUI();
  assert.equal( ui._fleetLabelOf( { persona: "Rio", session_id: "110ff47d3901" } ), "Rio" );
  assert.equal( ui._fleetLabelOf( { session_id: "110ff47d3901" } ), "110ff47d" );  // first 8 chars
  assert.equal( ui._fleetLabelOf( {} ), "unknown" );
  assert.equal( ui._fleetLabelOf( null ), "unknown" );
} );

// ─────────────────────────── _fleetLivenessTooltip (pure, §5) ───────────────────────────

test( "_fleetLivenessTooltip renders raw 4 ages with null → n/a", () => {
  const ui = newUI();
  const t = ui._fleetLivenessTooltip( RADIO.liveness );
  assert.match( t, /bridge 720s/ );
  assert.match( t, /freshest 720s/ );
  const t2 = ui._fleetLivenessTooltip( TIBERIUS.liveness );
  assert.match( t2, /commons n\/a/ );
  assert.match( t2, /idle_prompt n\/a/ );
} );

test( "_fleetLivenessTooltip handles missing liveness", () => {
  const ui = newUI();
  assert.equal( ui._fleetLivenessTooltip( null ), "no liveness data" );
} );

// ─────────────────────────── renderFleetStatusTable / _renderFleetRow (pure, §5/§7) ───────────────────────────

test( "renderFleetStatusTable emits a group header per manager, indented workers, Unmanaged last", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( [ TIBERIUS, RIO, RADIO, MARIA ] );
  const html = ui.renderFleetStatusTable( model );
  assert.match( html, /<table class="fleet-status-table">/ );
  assert.match( html, /Tiberius 👑/ );
  assert.match( html, /\(Unmanaged\)/ );
  assert.match( html, /fleet-row-worker/ );
  assert.match( html, /fleet-row-manager/ );
  // eight column headers present (six original + the two context columns)
  for ( const col of [ "Who", "Role", "State", "Holding on", "Stuck", "Liveness", "% Window", "Window" ] ) {
    assert.ok( html.includes( col ), `header "${col}" present` );
  }
  // group-header row now spans all eight columns
  assert.match( html, /colspan="8"/ );
  // Unmanaged header appears after the manager header
  assert.ok( html.indexOf( "Tiberius" ) < html.indexOf( "(Unmanaged)" ), "Unmanaged group renders last" );
} );

test( "renderFleetStatusTable: a manager group with no persona falls back to its sid label in the header", () => {
  const ui = newUI();
  const namelessMgr = { session_id: "nomgr01x", role: "manager", manager: null };  // no persona
  const model = ui.groupFleetByManager( [ namelessMgr ] );
  const html = ui.renderFleetStatusTable( model );
  // header uses the sid-based label (first 8 chars) via the `|| _fleetLabelOf` fallback
  assert.match( html, /nomgr01x 👑/ );
} );

test( "_renderFleetRow: holding 'none' → em-dash, stuck true → ✓ red class, tooltip carries raw ages", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( RADIO, true );
  assert.match( html, /fleet-row-worker/ );
  assert.match( html, /fleet-row-stuck/ );
  assert.match( html, /fleet-stuck-yes/ );
  assert.match( html, />✓</ );
  assert.match( html, /peer:Rio/ );           // holding_on rendered (not "none")
  assert.match( html, /title="[^"]*bridge 720s/ );
} );

test( "_renderFleetRow: a non-stuck row with holding 'none' renders an em-dash and no stuck class", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( RIO, true );
  assert.ok( !html.includes( "fleet-row-stuck" ), "no stuck class" );
  assert.match( html, /<td class="fleet-col-holding">—<\/td>/ );
  assert.match( html, />—</ );                 // stuck cell em-dash
} );

test( "_renderFleetRow: defensively fills missing fields (no role/state/liveness)", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( { session_id: "bare0001x" }, false );
  assert.match( html, /fleet-role-worker/ );   // role defaults to worker
  assert.match( html, />unknown</ );           // state + verdict default to unknown
  assert.match( html, /bare0001/ );            // short sid label
  assert.match( html, /title="no liveness data"/ );
} );

// ─────────────────────────── % Window + Window columns (context-pressure join) ───────────────────────────

test( "_formatWindowSize: 1000000 → 1M, 200000 → 200K, exact thousands → <n>K, other → integer, falsy → —", () => {
  const ui = newUI();
  assert.equal( ui._formatWindowSize( 1000000 ), "1M" );
  assert.equal( ui._formatWindowSize( 200000 ), "200K" );
  assert.equal( ui._formatWindowSize( 2000000 ), "2M" );
  assert.equal( ui._formatWindowSize( 128000 ), "128K" );
  assert.equal( ui._formatWindowSize( 1234 ), "1234" );   // not an exact thousand/million
  assert.equal( ui._formatWindowSize( null ), "—" );
  assert.equal( ui._formatWindowSize( undefined ), "—" );
  assert.equal( ui._formatWindowSize( 0 ), "—" );
  assert.equal( ui._formatWindowSize( -5 ), "—" );
} );

test( "_formatConsumptionPct: numeric → <pct>%, null/undefined → —", () => {
  const ui = newUI();
  assert.equal( ui._formatConsumptionPct( 21.9 ), "21.9%" );
  assert.equal( ui._formatConsumptionPct( 0 ), "0%" );    // a measured 0 is NOT em-dash
  assert.equal( ui._formatConsumptionPct( null ), "—" );
  assert.equal( ui._formatConsumptionPct( undefined ), "—" );
} );

test( "_renderFleetRow: joins % Window + Window from the personas map by persona", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( TIBERIUS, false, CONTEXT_PERSONAS );
  // 21.9% < 50 → the cell now carries the low heat-tint class (TASK 1)
  assert.match( html, /<td class="fleet-col-window-pct fleet-pct-low">21\.9%<\/td>/ );
  assert.match( html, /<td class="fleet-col-window">1M<\/td>/ );
  const rioHtml = ui._renderFleetRow( RIO, true, CONTEXT_PERSONAS );
  assert.match( rioHtml, /<td class="fleet-col-window-pct fleet-pct-low">8\.4%<\/td>/ );
  assert.match( rioHtml, /<td class="fleet-col-window">200K<\/td>/ );
} );

test( "_renderFleetRow: a measured window but null consumption → '—' pct, window still shown", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( MARIA, true, CONTEXT_PERSONAS );  // María: window 1M, consumption null
  assert.match( html, /<td class="fleet-col-window-pct">—<\/td>/ );
  assert.match( html, /<td class="fleet-col-window">1M<\/td>/ );
} );

test( "_renderFleetRow: a persona absent from the map → both context cells '—'", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( RADIO, true, CONTEXT_PERSONAS );  // Mr. Radio not in CONTEXT_PERSONAS
  assert.match( html, /<td class="fleet-col-window-pct">—<\/td>/ );
  assert.match( html, /<td class="fleet-col-window">—<\/td>/ );
} );

test( "_renderFleetRow: no personas arg (default {}) → both context cells '—' (never throws)", () => {
  const ui = newUI();
  const html = ui._renderFleetRow( TIBERIUS, false );
  assert.match( html, /<td class="fleet-col-window-pct">—<\/td>/ );
  assert.match( html, /<td class="fleet-col-window">—<\/td>/ );
} );

test( "renderFleetStatusTable: threads the personas map through to every rendered row", () => {
  const ui = newUI();
  const model = ui.groupFleetByManager( [ TIBERIUS, RIO ] );
  const html = ui.renderFleetStatusTable( model, CONTEXT_PERSONAS );
  assert.match( html, /21\.9%/ );   // Tiberius manager row
  assert.match( html, />1M</ );
  assert.match( html, /8\.4%/ );    // Rio worker row
  assert.match( html, />200K</ );
} );

// ─────────────────────────── liveness + %-window color-coding (TASK 1) ───────────────────────────

test( "_fleetVerdictClass: maps each verdict band to its row class (age-bearing verdicts key off the first token)", () => {
  const ui = newUI();
  assert.equal( ui._fleetVerdictClass( "LIVE" ),       "fleet-verdict-live" );
  assert.equal( ui._fleetVerdictClass( "quiet 6m" ),   "fleet-verdict-quiet" );
  assert.equal( ui._fleetVerdictClass( "stale 12m" ),  "fleet-verdict-stale" );
  assert.equal( ui._fleetVerdictClass( "offline" ),    "fleet-verdict-offline" );
  assert.equal( ui._fleetVerdictClass( "live" ),       "fleet-verdict-live" );   // case-insensitive
} );

test( "_fleetVerdictClass: an unrecognized string and a non-string both fall back to unknown", () => {
  const ui = newUI();
  assert.equal( ui._fleetVerdictClass( "bananas" ),  "fleet-verdict-unknown" );  // recognized-none string
  assert.equal( ui._fleetVerdictClass( undefined ),  "fleet-verdict-unknown" );  // non-string (ternary false branch)
  assert.equal( ui._fleetVerdictClass( null ),       "fleet-verdict-unknown" );
  assert.equal( ui._fleetVerdictClass( 42 as unknown as string ), "fleet-verdict-unknown" );
} );

test( "_fleetPctClass: green <50, amber 50–79, red ≥80; unmeasured → '' (all OR-guards exercised)", () => {
  const ui = newUI();
  // each guard operand, in order: null → undefined → non-number → NaN
  assert.equal( ui._fleetPctClass( null ),      "" );
  assert.equal( ui._fleetPctClass( undefined ), "" );
  assert.equal( ui._fleetPctClass( "60" as unknown as number ), "" );
  assert.equal( ui._fleetPctClass( NaN ),       "" );
  // bands (incl. the boundaries + a measured 0)
  assert.equal( ui._fleetPctClass( 0 ),    "fleet-pct-low" );
  assert.equal( ui._fleetPctClass( 49.9 ), "fleet-pct-low" );
  assert.equal( ui._fleetPctClass( 50 ),   "fleet-pct-mid" );
  assert.equal( ui._fleetPctClass( 79.9 ), "fleet-pct-mid" );
  assert.equal( ui._fleetPctClass( 80 ),   "fleet-pct-high" );
  assert.equal( ui._fleetPctClass( 99.9 ), "fleet-pct-high" );
} );

test( "_renderFleetRow: the <tr> carries the verdict class and the Liveness cell leads with a status dot", () => {
  const ui = newUI();
  const live = ui._renderFleetRow( TIBERIUS, false );          // verdict LIVE
  assert.match( live, /<tr class="fleet-row fleet-row-manager fleet-verdict-live">/ );
  assert.match( live, /<td class="fleet-col-liveness" title="[^"]*"><span class="fleet-liveness-dot"><\/span>LIVE<\/td>/ );
  const stale = ui._renderFleetRow( RADIO, true );             // verdict "stale 12m"
  assert.match( stale, /fleet-verdict-stale/ );
  const off = ui._renderFleetRow( OFFLINE, true );             // verdict offline
  assert.match( off, /fleet-verdict-offline/ );
  const bare = ui._renderFleetRow( { session_id: "bare0002x" }, true );  // no liveness
  assert.match( bare, /fleet-verdict-unknown/ );
  assert.match( bare, /<span class="fleet-liveness-dot"><\/span>/ );      // dot always present
} );

test( "_renderFleetRow: % Window cell gets the heat-tint class by band; unmeasured stays untinted", () => {
  const ui = newUI();
  const personas = {
    "Tiberius" : { window_size: 1000000, consumption_pct_of_window: 85.0 },  // high
    "Rio"      : { window_size: 200000,  consumption_pct_of_window: 62.0 },  // mid
    "María"    : { window_size: 1000000, consumption_pct_of_window: null },  // unmeasured
  };
  const hi = ui._renderFleetRow( TIBERIUS, false, personas );
  assert.match( hi, /<td class="fleet-col-window-pct fleet-pct-high">85%<\/td>/ );
  const mid = ui._renderFleetRow( RIO, true, personas );
  assert.match( mid, /<td class="fleet-col-window-pct fleet-pct-mid">62%<\/td>/ );
  const none = ui._renderFleetRow( MARIA, true, personas );
  assert.match( none, /<td class="fleet-col-window-pct">—<\/td>/ );     // null → no class, no tint
  assert.ok( !none.includes( "fleet-pct-" ), "unmeasured cell carries no heat-tint class" );
} );

// ─────────────────────────── renderFleetStatus (DOM dispatch, §6.4) ───────────────────────────

test( "renderFleetStatus: auth_required → sign-in message, count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "auth_required" } );
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /Sign-in required/ );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "0" );
} );

test( "renderFleetStatus: unreachable → Arbiter offline banner", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "unreachable", fleet_arbiter: null } );
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /Arbiter offline/ );
} );

test( "renderFleetStatus: fleet_arbiter null (status ok) → Arbiter offline banner", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "ok", fleet_arbiter: null } );
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /Arbiter offline/ );
} );

test( "renderFleetStatus: null composite → Arbiter offline banner (no throw)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( null );
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /Arbiter offline/ );
} );

test( "renderFleetStatus: empty sessions → No active sessions, count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "ok", app_timezone: "America/New_York", fleet_arbiter: { sessions: [] } } );
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /No active sessions/ );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "0" );
} );

test( "renderFleetStatus: populated → grouped table, count set, last-updated stamped", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( {
    status: "ok", app_timezone: "America/New_York",
    fleet_arbiter: { sessions: [ TIBERIUS, RIO, MARIA ] }
  } );
  const container = document.getElementById( "fleet-status-container" )!;
  assert.match( container.innerHTML, /fleet-status-table/ );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "3" );
  assert.match( document.getElementById( "fleet-status-updated" )!.textContent, /updated \d{2}:\d{2}:\d{2}/ );
} );

test( "renderFleetStatus: joins the context_pressure section → % Window + Window cells populated", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( {
    status: "ok", app_timezone: "America/New_York",
    fleet_arbiter: { sessions: [ TIBERIUS, RIO ] },
    context_pressure: { personas: CONTEXT_PERSONAS }
  } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.match( html, /21\.9%/ );   // Tiberius (1M window)
  assert.match( html, />1M</ );
  assert.match( html, /8\.4%/ );    // Rio (200K window)
  assert.match( html, />200K</ );
} );

test( "renderFleetStatus: no context_pressure section → context cells degrade to '—' (no throw)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( {
    status: "ok", app_timezone: "America/New_York",
    fleet_arbiter: { sessions: [ TIBERIUS, RIO ] }
    // context_pressure intentionally absent (arbiter has not published it yet)
  } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.match( html, /<td class="fleet-col-window-pct">—<\/td>/ );
  assert.match( html, /<td class="fleet-col-window">—<\/td>/ );
} );

test( "renderFleetStatus: context_pressure section present but personas key absent → cells degrade to '—'", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( {
    status: "ok", app_timezone: "America/New_York",
    fleet_arbiter: { sessions: [ TIBERIUS ] },
    context_pressure: { status: "awaiting" }   // section exists, no personas map yet
  } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.match( html, /<td class="fleet-col-window-pct">—<\/td>/ );
  assert.match( html, /<td class="fleet-col-window">—<\/td>/ );
} );

test( "renderFleetStatus: sessions key absent → treated as empty (count 0)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "ok", fleet_arbiter: {} } );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "0" );
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /No active sessions/ );
} );

test( "renderFleetStatus: no container in DOM → no-op (no throw)", () => {
  const ui = newUI();
  document.body.replaceChildren();   // no panel
  ui.renderFleetStatus( { status: "ok", fleet_arbiter: { sessions: [] } } );  // must not throw
} );

test( "renderFleetStatus: auth_required with no count element → no throw", () => {
  const ui = newUI();
  document.body.replaceChildren();
  const c = document.createElement( "div" );
  c.id = "fleet-status-container";
  document.body.appendChild( c );   // container but NO count element
  ui.renderFleetStatus( { status: "auth_required" } );
  assert.match( c.innerHTML, /Sign-in required/ );
} );

test( "renderFleetStatus: unreachable with container but no count element → no throw", () => {
  const ui = newUI();
  document.body.replaceChildren();
  const c = document.createElement( "div" );
  c.id = "fleet-status-container";
  document.body.appendChild( c );
  ui.renderFleetStatus( { status: "unreachable", fleet_arbiter: null } );
  assert.match( c.innerHTML, /Arbiter offline/ );
} );

// ─────────────────────────── timestamp formatting (§4.1 / D4) ───────────────────────────

test( "_formatFleetTimestamp: configured IANA zone renders HH:MM:SS + short TZ", () => {
  const ui = newUI();
  const d = new Date( "2026-06-09T18:32:07Z" );
  const out = ui._formatFleetTimestamp( d, "America/New_York" );
  assert.match( out, /^\d{2}:\d{2}:\d{2}\s+\w/ );   // "14:32:07 EDT"
  assert.match( out, /14:32:07/ );                  // EDT = UTC-4 in June
} );

test( "_formatFleetTimestamp: invalid zone falls back to browser-local (no throw)", () => {
  const ui = newUI();
  const out = ui._formatFleetTimestamp( new Date( "2026-06-09T18:32:07Z" ), "Not/AZone" );
  assert.match( out, /^\d{2}:\d{2}:\d{2}/ );
} );

test( "_formatFleetTimestamp: absent zone uses browser-local", () => {
  const ui = newUI();
  const out = ui._formatFleetTimestamp( new Date( "2026-06-09T18:32:07Z" ), null );
  assert.match( out, /^\d{2}:\d{2}:\d{2}/ );
} );

test( "_stampFleetStatusUpdated: no span → no-op (no throw)", () => {
  const ui = newUI();
  document.body.replaceChildren();
  ui._stampFleetStatusUpdated( "America/New_York" );  // must not throw
} );

// ─────────────────────────── fetchFleetState (auth + degradation) ───────────────────────────

test( "fetchFleetState: 200 ok → parsed composite", async () => {
  const ui = newUI();
  const body = { status: "ok", fleet_arbiter: { sessions: [] } };
  ui.authedFetch = async () => fakeResponse( 200, true, body );
  const out = await ui.fetchFleetState();
  assert.deepEqual( out, body );
} );

test( "fetchFleetState: 401 → auth_required", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 401, false, null );
  const out = await ui.fetchFleetState();
  assert.deepEqual( out, { status: "auth_required" } );
} );

test( "fetchFleetState: non-ok (500) → unreachable", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 500, false, null );
  const out = await ui.fetchFleetState();
  assert.deepEqual( out, { status: "unreachable", fleet_arbiter: null } );
} );

test( "fetchFleetState: network throw → unreachable (never throws)", async () => {
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "ECONNREFUSED" ); };
  const out = await ui.fetchFleetState();
  assert.deepEqual( out, { status: "unreachable", fleet_arbiter: null } );
} );

// ─────────────────────────── refreshFleetStatus (debounce) ───────────────────────────

test( "refreshFleetStatus: fetches and renders", async () => {
  const ui = newUI();
  buildPanelDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { status: "ok", fleet_arbiter: { sessions: [] } } );
  await ui.refreshFleetStatus();
  assert.match( document.getElementById( "fleet-status-container" )!.innerHTML, /No active sessions/ );
  assert.equal( ui._fleetStatusFetchInFlight, false, "guard reset in finally" );
} );

test( "refreshFleetStatus: in-flight guard short-circuits a concurrent call", async () => {
  const ui = newUI();
  buildPanelDOM();
  let calls = 0;
  ui.authedFetch = async () => { calls++; return fakeResponse( 200, true, { status: "ok", fleet_arbiter: { sessions: [] } } ); };
  ui._fleetStatusFetchInFlight = true;   // simulate a fetch already in progress
  await ui.refreshFleetStatus();
  assert.equal( calls, 0, "no fetch fired while one is in flight" );
} );

// ─────────────────────────── start/stop polling ───────────────────────────

test( "startFleetStatusPolling sets a handle + immediate refresh; stop clears it", async () => {
  const ui = newUI();
  buildPanelDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { status: "ok", fleet_arbiter: { sessions: [] } } );
  ui.startFleetStatusPolling();
  assert.ok( ui.fleetStatusPollIntervalHandle, "interval handle set" );
  ui.stopFleetStatusPolling();
  assert.equal( ui.fleetStatusPollIntervalHandle, null, "handle cleared" );
} );

test( "stopFleetStatusPolling is a no-op when not polling", () => {
  const ui = newUI();
  ui.fleetStatusPollIntervalHandle = null;
  ui.stopFleetStatusPolling();   // must not throw
  assert.equal( ui.fleetStatusPollIntervalHandle, null );
} );

test( "startFleetStatusPolling is idempotent (clears a prior interval first)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { status: "ok", fleet_arbiter: { sessions: [] } } );
  ui.startFleetStatusPolling();
  const first = ui.fleetStatusPollIntervalHandle;
  ui.startFleetStatusPolling();
  const second = ui.fleetStatusPollIntervalHandle;
  assert.notEqual( first, second, "a fresh interval replaced the old one" );
  ui.stopFleetStatusPolling();
} );

// ─────────────────────────── D6 / §5.1 live-only filter + offline toggle ───────────────────────────

test( "_splitFleetByLiveness partitions by verdict; rows without liveness are treated as live", () => {
  const ui = newUI();
  const noLive = { session_id: "nl01", persona: "NoLive", role: "worker" };  // no liveness block
  const { live, offline } = ui._splitFleetByLiveness( [ TIBERIUS, OFFLINE, noLive ] );
  assert.deepEqual( live.map( s => s.persona ), [ "Tiberius", "NoLive" ] );
  assert.deepEqual( offline.map( s => s.persona ), [ "Krishna" ] );
} );

test( "_splitFleetByLiveness: non-array input → empty partitions", () => {
  const ui = newUI();
  const { live, offline } = ui._splitFleetByLiveness( null );
  assert.deepEqual( live, [] );
  assert.deepEqual( offline, [] );
} );

test( "_fleetOfflineToggleHtml: 'Show offline (N)' when hidden, 'Hide offline (N)' when shown, wired to toggle", () => {
  const ui = newUI();
  const showHtml = ui._fleetOfflineToggleHtml( 7, false );
  assert.match( showHtml, /Show offline \(7\)/ );
  assert.match( showHtml, /window\.notificationsUI\.toggleFleetShowOffline\(\)/ );
  assert.match( showHtml, /fleet-offline-toggle/ );
  const hideHtml = ui._fleetOfflineToggleHtml( 7, true );
  assert.match( hideHtml, /Hide offline \(7\)/ );
} );

test( "renderFleetStatus: default HIDES offline sessions + shows 'Show offline (N)'; count is live-only", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( {
    status: "ok", app_timezone: "America/New_York",
    fleet_arbiter: { sessions: [ TIBERIUS, RIO, OFFLINE ] }
  } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.ok( !html.includes( "Krishna" ), "offline session hidden by default" );
  assert.match( html, /Show offline \(1\)/ );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "2" );  // live only
} );

test( "renderFleetStatus: fleetShowOffline=true REVEALS offline + shows 'Hide offline (N)'; count is all", () => {
  const ui = newUI();
  ui.fleetShowOffline = true;
  buildPanelDOM();
  ui.renderFleetStatus( {
    status: "ok", fleet_arbiter: { sessions: [ TIBERIUS, RIO, OFFLINE ] }
  } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.match( html, /Krishna/ );
  assert.match( html, /Hide offline \(1\)/ );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "3" );
} );

test( "renderFleetStatus: all sessions offline + hidden → 'No live sessions' + toggle, count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "ok", fleet_arbiter: { sessions: [ OFFLINE ] } } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.match( html, /No live sessions/ );
  assert.match( html, /Show offline \(1\)/ );
  assert.equal( document.getElementById( "fleet-status-count" )!.textContent, "0" );
} );

test( "renderFleetStatus: no offline sessions → no toggle rendered", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderFleetStatus( { status: "ok", fleet_arbiter: { sessions: [ TIBERIUS, RIO ] } } );
  const html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.ok( !html.includes( "fleet-offline-toggle" ), "no toggle when nothing offline" );
} );

test( "toggleFleetShowOffline flips state and re-renders from the cached composite (no re-fetch)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui._lastFleetComposite = { status: "ok", fleet_arbiter: { sessions: [ TIBERIUS, RIO, OFFLINE ] } };
  ui.fleetShowOffline = false;

  ui.toggleFleetShowOffline();
  assert.equal( ui.fleetShowOffline, true );
  let html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.match( html, /Krishna/ );             // offline now shown
  assert.match( html, /Hide offline \(1\)/ );

  ui.toggleFleetShowOffline();
  assert.equal( ui.fleetShowOffline, false );
  html = document.getElementById( "fleet-status-container" )!.innerHTML;
  assert.ok( !html.includes( "Krishna" ), "offline hidden again" );
} );

test( "toggleFleetShowOffline does NOT re-stamp the 'updated' label (a view-toggle is not a fetch)", () => {
  const ui = newUI();
  buildPanelDOM();
  let stamps = 0;
  ui._stampFleetStatusUpdated = () => { stamps++; };
  ui.renderFleetStatus( { status: "ok", fleet_arbiter: { sessions: [ TIBERIUS, RIO, OFFLINE ] } } );
  assert.equal( stamps, 1, "the real (fetch) render stamps once" );
  ui.toggleFleetShowOffline();   // pure view re-render from the cached composite
  assert.equal( stamps, 1, "the toggle re-render did NOT re-stamp freshness" );
} );

if ( typeof process !== "undefined" && process.argv.includes( "--run" ) ) { /* node --test entry */ }
