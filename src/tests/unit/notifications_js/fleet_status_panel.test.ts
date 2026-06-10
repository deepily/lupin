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
  renderFleetStatusTable: ( model: { groups: GroupModel[] } ) => string;
  _renderFleetRow: ( session: Record<string, unknown>, indented: boolean ) => string;
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
  // six column headers present
  for ( const col of [ "Who", "Role", "State", "Holding on", "Stuck", "Liveness" ] ) {
    assert.ok( html.includes( col ), `header "${col}" present` );
  }
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
