/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP12 — FleetStatusRenderer (F12).
//
// The DOM-touching orchestrator. Ports legacy renderFleetStatus
// (notifications.js:8801-8910): the four §6.4 render states (sign-in /
// unreachable / empty / table), the live-only count, and the "updated
// HH:MM:SS TZ" stamp. Pure model + formatters live in render/fleetModel.ts;
// the table/row/toggle DOM lives in templates/fleetStatusTable.ts; fetch/poll/
// toggle state lives in FleetStatusStore.
//
// Unlike the legacy (which dispatched into pre-existing #fleet-status-*
// elements), this renderer OWNS its subtree: mount(root) builds the panel
// chrome (title · count · ⟳ refresh · updated-stamp · container) and repaints
// the container on every `store_fleet_status_changed`. Mirrors the
// JobsPaneRenderer "renderer owns its DOM" convention.
//
// Parity A-2 #5 (row 18d06df7) — the fleet-size-cap dial, ported from legacy
// notifications.html:735-752 (markup) and notifications.js:9242-9393 (paint +
// wiring). It is built ONCE at mount, between the header and the table container,
// and repainted in place on `store_fleet_size_cap_changed`; the table repaint never
// touches it, so a drag is never interrupted by a poll.

import type { EventBus } from "../shared/EventBus";
import type { StoreFleetSizeCapChangedPayload, StoreFleetStatusChangedPayload } from "../shared/types";
import type { FleetSizeCap } from "../stores/FleetStatusStore";
import {
  groupFleetByManager,
  splitFleetByLiveness,
  formatFleetTimestamp,
  type FleetComposite,
  type FleetPersonaMap,
} from "./fleetModel";
import {
  renderFleetStatusTable,
  renderFleetOfflineToggle,
} from "./templates/fleetStatusTable";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

export interface FleetStoreLike {
  composite(): FleetComposite | null;
  showOfflineFlag(): boolean;
  refresh(): Promise<void>;
  toggleShowOffline(): void;
  sizeCap(): FleetSizeCap | null;
  sizeCapSaving(): number | null;
  setSizeCap( cap: number ): Promise<void>;
}

export interface FleetStatusRendererStores {
  fleet : FleetStoreLike;
}

export interface FleetStatusRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface FleetStatusRendererOptions {
  eventBus   : EventBus;
  stores     : FleetStatusRendererStores;
  /** Test injection — the clock for the "updated" stamp. Defaults to `new Date()`. */
  nowDateFn? : () => Date;
}

interface SizeCapEls {
  root   : HTMLDivElement;
  slider : HTMLInputElement;
  value  : HTMLOutputElement;
  status : HTMLSpanElement;
}

/**
 * Build the dial cluster: hidden, with no `max` and no `value`.
 *
 * ⚠️ BOTH ARE PAINTED FROM THE SERVER. A control parked at HTML defaults renders
 * identically whether it works or not, which is why the cluster stays hidden until a
 * real payload arrives, and why the ceiling is read on every paint rather than baked
 * into markup (legacy html:731-736, :9264-9266).
 *
 * It carries `.section-content` and is mounted as a direct child of the pane root, so
 * the shared `[data-collapsed="true"] > .section-content` rule collapses it with the
 * table. Not in the header bar: that bar toggles the section, so a range input there
 * would collapse the pane on every drag (legacy notifications.css comment at the rule).
 */
function buildSizeCapControls(): SizeCapEls {
  const root = document.createElement( "div" );
  root.className = "section-content fleet-size-cap-controls";
  root.setAttribute( "data-testid", "multiplexer-fleet-size-cap-controls" );
  root.hidden = true;

  const field = document.createElement( "span" );
  field.className = "fleet-size-cap-field";

  const label = document.createElement( "label" );
  label.htmlFor = "multiplexer-fleet-size-cap";
  label.append( "Fleet cap " );

  const value = document.createElement( "output" );
  value.setAttribute( "data-testid", "multiplexer-fleet-size-cap-value" );
  value.textContent = "—";
  label.append( value );

  const slider = document.createElement( "input" );
  slider.type = "range";
  slider.id = "multiplexer-fleet-size-cap";
  slider.setAttribute( "data-testid", "multiplexer-fleet-size-cap" );
  slider.min = "1";
  slider.step = "1";
  slider.title = "The fleet-wide session cap the spawn path enforces — EVERY session counts, managers included. "
    + "Over cap refuses new spawns and reaps nobody. Drag and release to set it: the value is written to "
    + "`cc session fleet size cap` in the configuration file and survives a restart. The slider's maximum is "
    + "`cc session fleet size cap maximum`.";

  field.append( label, slider );

  const status = document.createElement( "span" );
  status.className = "fleet-size-cap-status";
  status.setAttribute( "data-testid", "multiplexer-fleet-size-cap-status" );

  root.append( field, status );
  return { root, slider, value, status };
}

function messageEl( className: string, text: string ): HTMLParagraphElement {
  const p = document.createElement( "p" );
  p.className = `fleet-status-message ${className}`;
  p.textContent = text;
  return p;
}

class FleetStatusRendererImpl implements FleetStatusRenderer {
  private readonly bus       : EventBus;
  private readonly stores    : FleetStatusRendererStores;
  private readonly nowDateFn : () => Date;
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  private sizeCapEls: SizeCapEls | null = null;
  // Lane 0a — section-header handle + collapse-listener teardown.
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted   = false;

  constructor( opts: FleetStatusRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "FleetStatusRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    // Build the panel chrome once. The container is repainted per render.
    // Lane 0a — convert the bespoke `.fleet-status-header` into the uniform
    // `.section-header` bar (🛰️ Fleet Status). The refresh control + updated
    // stamp move into the header's `.section-header-actions` slot; the live
    // count uses the shared `.section-header-count` chip (its legacy testid is
    // preserved so E2E selectors keep resolving).
    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "fleet-status-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-fleet-status-refresh" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.stores.fleet.refresh() );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "fleet-status-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-fleet-status-updated" );

    const header = renderSectionHeader( {
      icon    : "🛰️",
      title   : "Fleet Status",
      testid  : "multiplexer-fleet-status-header",
      actions : [ refreshBtn, this.updatedEl ],
    } );
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.setAttribute( "data-testid", "multiplexer-fleet-status-count" );
    this.countEl.textContent = "0";

    this.container = document.createElement( "div" );
    // The container IS the collapsible body — carries `.section-content` so the
    // shared `[data-collapsed="true"] > .section-content` rule hides it.
    this.container.className = "section-content fleet-status-container";
    this.container.setAttribute( "data-testid", "multiplexer-fleet-status-container" );

    this.sizeCapEls = buildSizeCapControls();
    this.wireSizeCap( this.sizeCapEls );

    root.replaceChildren( header.header, this.sizeCapEls.root, this.container );
    this.collapseOff = wireSectionCollapse( root, header );

    // Initial paint (composite may be null until the first poll resolves).
    this.renderFromStore( false );
    this.paintSizeCap();

    this.unsubscribers.push(
      this.bus.on<StoreFleetStatusChangedPayload>(
        "store_fleet_status_changed",
        ( e ) => this.renderFromStore( e.payload.stampUpdated ),
      ),
      this.bus.on<StoreFleetSizeCapChangedPayload>(
        "store_fleet_size_cap_changed",
        () => this.paintSizeCap(),
      ),
    );
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    if ( this.collapseOff !== null ) {
      this.collapseOff();
      this.collapseOff = null;
    }
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.container = null;
    this.countEl = null;
    this.updatedEl = null;
    this.sizeCapEls = null;
    this.header = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if ( this.mounted ) this.renderFromStore( true );
  }

  // -------------------------------------------------------------------------
  // Dispatch (the four §6.4 states)
  // -------------------------------------------------------------------------

  private renderFromStore( stampUpdated: boolean ): void {
    /* c8 ignore next */ // defensive: subscriptions detach in unmount BEFORE container is nulled.
    if ( this.container === null ) return;
    const composite = this.stores.fleet.composite();

    if ( composite && composite.status === "auth_required" ) {
      this.container.replaceChildren( messageEl( "fleet-status-signin", "🔒 Sign-in required." ) );
      this.setCount( 0 );
      return;
    }

    if ( !composite || composite.status === "unreachable" || !composite.fleet_arbiter ) {
      this.container.replaceChildren( messageEl( "fleet-status-offline", "🛰️ Arbiter offline — last known: none." ) );
      this.setCount( 0 );
      return;
    }

    const sessions    = composite.fleet_arbiter.sessions || [];
    const showOffline = this.stores.fleet.showOfflineFlag();
    const { live, offline } = splitFleetByLiveness( sessions );
    const visible     = showOffline ? sessions : live;

    this.setCount( visible.length );

    const children: Node[] = [];
    if ( offline.length > 0 ) {
      children.push( renderFleetOfflineToggle( offline.length, showOffline, {
        onToggle: () => this.stores.fleet.toggleShowOffline(),
      } ) );
    }

    if ( sessions.length === 0 ) {
      children.push( messageEl( "fleet-status-empty", "No active sessions." ) );
    } else if ( visible.length === 0 ) {
      // Sessions exist but every one is offline and currently hidden.
      children.push( messageEl( "fleet-status-empty", "No live sessions." ) );
    } else {
      const model    = groupFleetByManager( visible );
      const personas : FleetPersonaMap =
        ( composite.context_pressure && composite.context_pressure.personas ) || {};
      children.push( renderFleetStatusTable( model, personas ) );
    }

    this.container.replaceChildren( ...children );

    if ( stampUpdated ) this.stampUpdated( composite.app_timezone );
  }

  // -------------------------------------------------------------------------
  // The fleet-size-cap dial (Parity A-2 #5)
  // -------------------------------------------------------------------------

  /**
   * Bind the dial's handlers. Called once, at mount, on elements this renderer built,
   * so there is no second paint that could add a second listener — legacy needed a
   * `data-wired` flag because it bound from the paint (legacy :9357-9370).
   *
   * 🔴 THE WRITE IS ON `change`, NOT `input`. A range input fires `input`
   * continuously while the handle moves: a drag from 4 to 18 would be fourteen PUTs,
   * each a file write. `change` fires once, on release (legacy :9363-9366).
   */
  private wireSizeCap( els: SizeCapEls ): void {
    els.slider.addEventListener( "input", () => {
      els.value.textContent = `${els.slider.value} / ${els.slider.max}`;
    } );
    els.slider.addEventListener( "change", () => {
      void this.stores.fleet.setSizeCap( Number( els.slider.value ) );
    } );
  }

  private paintSizeCap(): void {
    /* c8 ignore next */ // defensive: the subscription detaches in unmount BEFORE sizeCapEls is nulled.
    if ( this.sizeCapEls === null ) return;
    const els    = this.sizeCapEls;
    const saving = this.stores.fleet.sizeCapSaving();

    if ( saving !== null ) {
      // Disabled while the PUT is in flight, so a second drag cannot race the first,
      // and said in TEXT, not by the dimmed handle alone (legacy :9379-9380).
      els.slider.disabled = true;
      els.status.textContent = `saving ${saving}…`;
      return;
    }

    const payload = this.stores.fleet.sizeCap();
    const cap     = payload?.cap;
    const ceiling = payload?.ceiling;
    if ( !Number.isFinite( cap ) || !Number.isFinite( ceiling ) ) {
      els.root.hidden = true;
      return;
    }

    // 🔴 THE CEILING IS THE KEY'S VALUE, VERBATIM — never clamped to the persona pool
    // or the live count, or the dial would disagree with the key (legacy :9257-9262).
    els.root.hidden        = false;
    els.slider.min         = "1";
    els.slider.max         = String( ceiling );
    els.slider.value       = String( cap );
    els.value.textContent  = `${cap} / ${ceiling}`;
    els.slider.disabled    = false;

    const live = ( payload as FleetSizeCap ).live;   // non-null: both numbers were finite
    els.status.textContent = ( live && Number.isFinite( live.total ) )
      ? `${live.total} live — ${live.managers} manager(s), ${live.workers} worker(s)`
      : "";
  }

  private setCount( n: number ): void {
    if ( this.countEl !== null ) this.countEl.textContent = String( n );
  }

  private stampUpdated( ianaZone: string | undefined ): void {
    /* c8 ignore next */ // defensive: stampUpdated only runs from renderFromStore past its container-null guard; updatedEl is set/nulled in lockstep with container, so it is non-null here. Belt-and-suspenders.
    if ( this.updatedEl === null ) return;
    this.updatedEl.textContent = `updated ${formatFleetTimestamp( this.nowDateFn(), ianaZone )}`;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFleetStatusRenderer( opts: FleetStatusRendererOptions ): FleetStatusRenderer {
  return new FleetStatusRendererImpl( opts );
}
