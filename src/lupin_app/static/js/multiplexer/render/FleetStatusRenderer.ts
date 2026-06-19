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

import type { EventBus } from "../shared/EventBus";
import type { StoreFleetStatusChangedPayload } from "../shared/types";
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

export interface FleetStoreLike {
  composite(): FleetComposite | null;
  showOfflineFlag(): boolean;
  refresh(): Promise<void>;
  toggleShowOffline(): void;
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
    const header = document.createElement( "header" );
    header.className = "fleet-status-header";

    const title = document.createElement( "h2" );
    title.className = "fleet-status-title";
    title.textContent = "🛰️ Fleet Status";
    header.appendChild( title );

    this.countEl = document.createElement( "span" );
    this.countEl.className = "fleet-status-count";
    this.countEl.setAttribute( "data-testid", "multiplexer-fleet-status-count" );
    this.countEl.textContent = "0";
    header.appendChild( this.countEl );

    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "fleet-status-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-fleet-status-refresh" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.stores.fleet.refresh() );
    header.appendChild( refreshBtn );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "fleet-status-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-fleet-status-updated" );
    header.appendChild( this.updatedEl );

    this.container = document.createElement( "div" );
    this.container.className = "fleet-status-container";
    this.container.setAttribute( "data-testid", "multiplexer-fleet-status-container" );

    root.replaceChildren( header, this.container );

    // Initial paint (composite may be null until the first poll resolves).
    this.renderFromStore( false );

    this.unsubscribers.push(
      this.bus.on<StoreFleetStatusChangedPayload>(
        "store_fleet_status_changed",
        ( e ) => this.renderFromStore( e.payload.stampUpdated ),
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
    this.container = null;
    this.countEl = null;
    this.updatedEl = null;
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
