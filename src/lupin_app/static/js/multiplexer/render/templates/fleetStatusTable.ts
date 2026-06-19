/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP12 — Fleet-Status table template (F12).
//
// Ports the DOM half of the legacy fleet-status block
// (notifications.js:8619-8716, 8757-8799). Built entirely via
// document.createElement + .textContent / .setAttribute — NO innerHTML and NO
// `html` tagged template, because table-section parsing rules drop stray
// <tr>/<td> when a fragment is parsed outside a <table> ancestor. createElement
// sidesteps that AND is inherently safe-write (verified by the grep guard in
// templates_fleet_status_table.test.ts).
//
// Delegated listeners only (the legacy offline toggle used inline
// `onclick="window.notificationsUI.toggleFleetShowOffline()"` against the
// dead-ish global — the multiplexer wires a real click listener instead).
//
// Eight columns: Who · Role · State · Holding on · Stuck · Liveness (raw-4-ages
// hover tooltip) · % Window · Window.

import {
  fleetHeatClass,
  fleetLabelOf,
  fleetLivenessTooltip,
  fleetVerdictClass,
  formatConsumptionPct,
  formatWindowSize,
  type FleetModel,
  type FleetPersonaMap,
  type FleetSession,
} from "../fleetModel";

const FLEET_COLSPAN = 8;

function td( className: string, text: string ): HTMLTableCellElement {
  const cell = document.createElement( "td" );
  cell.className = className;
  cell.textContent = text;
  return cell;
}

export interface FleetOfflineToggleHandlers {
  onToggle(): void;
}

/**
 * Build the "Show/Hide offline (N)" view-toggle (read-only — changes what the
 * table shows, never fleet state). Delegated click → handlers.onToggle.
 *
 * Ensures:
 *   - Returns a `.fleet-offline-toggle` div wrapping a `.fleet-offline-toggle-btn`
 *   - Label is "Hide offline (N)" when showOffline, else "Show offline (N)"
 */
export function renderFleetOfflineToggle(
  offlineCount : number,
  showOffline  : boolean,
  handlers     : FleetOfflineToggleHandlers,
): HTMLElement {
  const wrap = document.createElement( "div" );
  wrap.className = "fleet-offline-toggle";
  const btn = document.createElement( "button" );
  btn.type = "button";
  btn.className = "fleet-offline-toggle-btn";
  btn.setAttribute( "data-testid", "multiplexer-fleet-offline-toggle" );
  btn.textContent = showOffline
    ? `Hide offline (${offlineCount})`
    : `Show offline (${offlineCount})`;
  btn.addEventListener( "click", () => handlers.onToggle() );
  wrap.appendChild( btn );
  return wrap;
}

/**
 * Render a single session row (<tr>) with the eight columns.
 *
 * Ensures:
 *   - "none"/empty holding_on → "—"; stuck → "✓" else "—"
 *   - Liveness cell carries the raw-4-ages tooltip via title= AND a leading
 *     `.fleet-liveness-dot` span color-keyed by the row's verdict class
 *   - % Window + Window joined per-persona from `personas`; unmeasured/missing → "—"
 *   - indented=true adds .fleet-row-worker, else .fleet-row-manager; stuck adds .fleet-row-stuck
 *   - the row carries a `fleet-verdict-*` class (verdict→color); the % Window cell
 *     carries a `fleet-pct-*` heat class when measured (unmeasured "—" stays untinted).
 *     Color is redundant with the verdict WORD / % text (WCAG 1.4.1).
 */
export function renderFleetRow(
  session  : FleetSession,
  indented : boolean,
  personas : FleetPersonaMap,
): HTMLTableRowElement {
  const role     = session.role || "worker";
  const state    = session.state || "unknown";
  const holdRaw  = session.holding_on;
  const holding  = ( !holdRaw || holdRaw === "none" ) ? "—" : holdRaw;
  const isStuck  = !!session.stuck;
  const liveness = session.liveness || {};
  const verdict  = liveness.verdict || "unknown";
  const ctx      = ( session.persona && personas[ session.persona ] ) || {};

  const verdictClass = fleetVerdictClass( verdict );

  const tr = document.createElement( "tr" );
  tr.className = "fleet-row"
    + ( indented ? " fleet-row-worker" : " fleet-row-manager" )
    + ( isStuck ? " fleet-row-stuck" : "" )
    + ` ${verdictClass}`;

  tr.appendChild( td( "fleet-col-who", fleetLabelOf( session ) ) );

  const roleCell = document.createElement( "td" );
  roleCell.className = "fleet-col-role";
  const badge = document.createElement( "span" );
  badge.className = `fleet-role-badge fleet-role-${role}`;
  badge.textContent = role;
  roleCell.appendChild( badge );
  tr.appendChild( roleCell );

  tr.appendChild( td( "fleet-col-state", state ) );
  tr.appendChild( td( "fleet-col-holding", holding ) );

  const stuckCell = td( "fleet-col-stuck" + ( isStuck ? " fleet-stuck-yes" : "" ), isStuck ? "✓" : "—" );
  tr.appendChild( stuckCell );

  // Status-dot prepended in the Liveness cell — color-keyed via the row's
  // `fleet-verdict-*` class (createElement keeps it safe-write; no innerHTML).
  const livenessCell = document.createElement( "td" );
  livenessCell.className = "fleet-col-liveness";
  const dot = document.createElement( "span" );
  dot.className = "fleet-liveness-dot";
  livenessCell.appendChild( dot );
  livenessCell.appendChild( document.createTextNode( verdict ) );
  livenessCell.setAttribute( "title", fleetLivenessTooltip( session.liveness ) );
  tr.appendChild( livenessCell );

  const heatClass = fleetHeatClass( ctx.consumption_pct_of_window );
  tr.appendChild( td(
    "fleet-col-window-pct" + ( heatClass ? ` ${heatClass}` : "" ),
    formatConsumptionPct( ctx.consumption_pct_of_window ),
  ) );
  tr.appendChild( td( "fleet-col-window", formatWindowSize( ctx.window_size ) ) );

  return tr;
}

/**
 * Render the grouped hierarchy model as a read-only `<table>`. Managers are
 * group headers; workers indented beneath; the Unmanaged group renders last.
 *
 * Requires:
 *   - model is the { totalCount, groups } shape from groupFleetByManager
 *   - personas is context_pressure.personas (persona → record), or {} if absent
 *
 * Ensures:
 *   - Returns a `.fleet-status-table` <table> element
 *   - Read-only: no action column, no mutating controls
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the default-parameter (`personas = {}`) function-declaration line; both omitted + supplied call paths are exercised by tests.
export function renderFleetStatusTable(
  model    : FleetModel,
  personas : FleetPersonaMap = {},
): HTMLTableElement {
  const table = document.createElement( "table" );
  table.className = "fleet-status-table";

  const thead = document.createElement( "thead" );
  const headRow = document.createElement( "tr" );
  const headers: ReadonlyArray<[string, string]> = [
    [ "fleet-col-who", "Who" ],
    [ "fleet-col-role", "Role" ],
    [ "fleet-col-state", "State" ],
    [ "fleet-col-holding", "Holding on" ],
    [ "fleet-col-stuck", "Stuck" ],
    [ "fleet-col-liveness", "Liveness" ],
    [ "fleet-col-window-pct", "% Window" ],
    [ "fleet-col-window", "Window" ],
  ];
  for ( const [ cls, label ] of headers ) {
    const th = document.createElement( "th" );
    th.className = cls;
    th.textContent = label;
    headRow.appendChild( th );
  }
  thead.appendChild( headRow );
  table.appendChild( thead );

  const tbody = document.createElement( "tbody" );
  for ( const group of model.groups ) {
    const headerLabel = group.isUnmanaged
      ? "(Unmanaged)"
      : `${group.managerPersona || fleetLabelOf( group.manager )} 👑`;

    const groupHeader = document.createElement( "tr" );
    groupHeader.className = "fleet-group-header" + ( group.isUnmanaged ? " fleet-group-unmanaged" : "" );
    const groupCell = document.createElement( "td" );
    groupCell.colSpan = FLEET_COLSPAN;
    groupCell.textContent = headerLabel;
    groupHeader.appendChild( groupCell );
    tbody.appendChild( groupHeader );

    if ( !group.isUnmanaged && group.manager ) {
      tbody.appendChild( renderFleetRow( group.manager, false, personas ) );
    }
    for ( const w of group.workers ) {
      tbody.appendChild( renderFleetRow( w, true, personas ) );
    }
  }
  table.appendChild( tbody );

  return table;
}
