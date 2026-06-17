/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — TaskListRenderer (Step 4, store-canonical task mgmt).
//
// The DOM-touching orchestrator, mirroring FleetStatusRenderer. Owns its
// subtree: mount(root) builds the panel chrome (title · count · ⟳ refresh ·
// updated-stamp · container) and repaints the container on every
// `store_task_list_changed`. Pure model + formatters live in
// render/taskListModel.ts; the table/row DOM lives in
// templates/taskListTable.ts; fetch/poll state lives in TaskListStore.
//
// Four render states (mirroring fleet-status):
//   auth_required → sign-in banner          (don't show stale rows on auth loss)
//   unreachable   → "store unreachable" indicator + LAST-KNOWN rows (never blank)
//   empty         → "no open tasks" message
//   table         → owner-grouped table of OPEN (non-terminal) work
//
// The updated-stamp uses browser-local time: `/api/tasks` carries no timezone
// (unlike the fleet-state composite), so we format DST-aware in the browser's
// own zone.

import type { EventBus } from "../shared/EventBus";
import type { StoreTaskListChangedPayload } from "../shared/types";
import { formatFleetTimestamp } from "./fleetModel";
import {
  groupTasksByOwner,
  isOpenStatus,
  type TaskItem,
  type TaskListComposite,
} from "./taskListModel";
import { renderTaskListTable } from "./templates/taskListTable";
import { loadCollapsedOwners, saveCollapsedOwners, toggleCollapsedOwner } from "./taskListCollapse";

export interface TaskListStoreLike {
  composite(): TaskListComposite | null;
  refresh(): Promise<void>;
}

export interface TaskListRendererStores {
  taskList : TaskListStoreLike;
}

export interface TaskListRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface TaskListRendererOptions {
  eventBus   : EventBus;
  stores     : TaskListRendererStores;
  /** Test injection — the clock for the "updated" stamp. Defaults to `new Date()`. */
  nowDateFn? : () => Date;
}

function messageEl( className: string, text: string ): HTMLParagraphElement {
  const p = document.createElement( "p" );
  p.className = `task-list-message ${className}`;
  p.textContent = text;
  return p;
}

class TaskListRendererImpl implements TaskListRenderer {
  private readonly bus       : EventBus;
  private readonly stores    : TaskListRendererStores;
  private readonly nowDateFn : () => Date;
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  private mounted   = false;

  // Last successfully-fetched OPEN rows — replayed under the "store unreachable"
  // indicator so a transient outage degrades to stale-not-blank.
  private lastGoodTasks : TaskItem[] | null = null;

  constructor( opts: TaskListRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "TaskListRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    const header = document.createElement( "header" );
    header.className = "task-list-header";

    const title = document.createElement( "h2" );
    title.className = "task-list-title";
    title.textContent = "📋 Task List";
    header.appendChild( title );

    this.countEl = document.createElement( "span" );
    this.countEl.className = "task-list-count";
    this.countEl.setAttribute( "data-testid", "multiplexer-task-list-count" );
    this.countEl.textContent = "0";
    header.appendChild( this.countEl );

    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "task-list-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-task-list-refresh" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.stores.taskList.refresh() );
    header.appendChild( refreshBtn );

    // Per-persona accordion: collapse-all / expand-all. The JS card puts these in
    // its #section-toolbar; the multiplexer has no such toolbar, so they live in
    // the card header (parity is the persistence CONTRACT — shared localStorage
    // key + sentinel + default — not button location).
    const collapseAllBtn = document.createElement( "button" );
    collapseAllBtn.type = "button";
    collapseAllBtn.className = "task-list-collapse-all";
    collapseAllBtn.setAttribute( "data-testid", "multiplexer-task-list-collapse-all" );
    collapseAllBtn.setAttribute( "title", "Collapse all task owners" );
    collapseAllBtn.textContent = "⊟";
    collapseAllBtn.addEventListener( "click", () => this.collapseAll() );
    header.appendChild( collapseAllBtn );

    const expandAllBtn = document.createElement( "button" );
    expandAllBtn.type = "button";
    expandAllBtn.className = "task-list-expand-all";
    expandAllBtn.setAttribute( "data-testid", "multiplexer-task-list-expand-all" );
    expandAllBtn.setAttribute( "title", "Expand all task owners" );
    expandAllBtn.textContent = "⊞";
    expandAllBtn.addEventListener( "click", () => this.expandAll() );
    header.appendChild( expandAllBtn );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "task-list-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-task-list-updated" );
    header.appendChild( this.updatedEl );

    this.container = document.createElement( "div" );
    this.container.className = "task-list-container";
    this.container.setAttribute( "data-testid", "multiplexer-task-list-container" );

    // Accordion delegation: ONE click+keyboard listener on the persistent
    // container (its children are replaced each render, the element is not), so a
    // header toggle survives every re-render with no per-row re-binding.
    this.container.addEventListener( "click", ( e ) => this.handleAccordionToggle( e.target ) );
    this.container.addEventListener( "keydown", ( e ) => {
      const ke = e as KeyboardEvent;
      if ( ke.key !== "Enter" && ke.key !== " " && ke.key !== "Spacebar" ) return;
      const header = ( e.target as Element ).closest( ".task-group-header" );
      if ( !header ) return;
      e.preventDefault();   // Space must toggle the group, not scroll the page
      this.handleAccordionToggle( e.target );
    } );

    root.replaceChildren( header, this.container );

    // Initial paint (composite may be null until the first poll resolves).
    this.renderFromStore( false );

    this.unsubscribers.push(
      this.bus.on<StoreTaskListChangedPayload>(
        "store_task_list_changed",
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
  // Dispatch (the four states)
  // -------------------------------------------------------------------------

  private renderFromStore( stampUpdated: boolean ): void {
    /* c8 ignore next */ // defensive: subscriptions detach in unmount BEFORE container is nulled.
    if ( this.container === null ) return;
    const composite = this.stores.taskList.composite();

    if ( composite && composite.status === "auth_required" ) {
      this.container.replaceChildren( messageEl( "task-list-signin", "🔒 Sign-in required." ) );
      this.setCount( 0 );
      return;
    }

    if ( !composite || composite.status === "unreachable" || !Array.isArray( composite.tasks ) ) {
      this.renderUnreachable();
      return;
    }

    const openTasks = composite.tasks.filter( ( t ) => isOpenStatus( t.status ) );
    this.lastGoodTasks = openTasks;
    this.setCount( openTasks.length );

    if ( openTasks.length === 0 ) {
      this.container.replaceChildren( messageEl( "task-list-empty", "✅ No open tasks." ) );
    } else {
      const model = groupTasksByOwner( openTasks );
      this.container.replaceChildren( renderTaskListTable( model, undefined, loadCollapsedOwners() ) );
    }

    if ( stampUpdated ) this.stampUpdated();
  }

  /**
   * Store-unreachable / pre-first-poll branch. Shows a "store unreachable"
   * indicator and, when a prior good fetch exists, replays its last-known rows
   * beneath it (graceful degradation — never blank). Does NOT re-stamp (no
   * fresh data) and does NOT overwrite `lastGoodTasks`.
   */
  private renderUnreachable(): void {
    /* c8 ignore next */ // defensive: only reached from renderFromStore past its container-null guard.
    if ( this.container === null ) return;
    const indicator = messageEl( "task-list-unreachable", "⚠️ Store unreachable." );

    if ( this.lastGoodTasks !== null && this.lastGoodTasks.length > 0 ) {
      const model = groupTasksByOwner( this.lastGoodTasks );
      this.container.replaceChildren( indicator, renderTaskListTable( model, undefined, loadCollapsedOwners() ) );
      this.setCount( this.lastGoodTasks.length );
    } else {
      this.container.replaceChildren( indicator, messageEl( "task-list-empty", "No tasks loaded yet." ) );
      this.setCount( 0 );
    }
  }

  private setCount( n: number ): void {
    if ( this.countEl !== null ) this.countEl.textContent = String( n );
  }

  private stampUpdated(): void {
    /* c8 ignore next */ // defensive: stampUpdated only runs from renderFromStore past its container-null guard; updatedEl is set/nulled in lockstep with container. Belt-and-suspenders.
    if ( this.updatedEl === null ) return;
    this.updatedEl.textContent = `updated ${formatFleetTimestamp( this.nowDateFn(), undefined )}`;
  }

  // -------------------------------------------------------------------------
  // Per-persona accordion
  // -------------------------------------------------------------------------

  /**
   * Toggle the owner group whose header was activated (click or Enter/Space):
   * flip + persist its collapsed state, then re-render from the cached composite
   * (no re-fetch) so the new collapse state paints. No-op outside a header.
   */
  private handleAccordionToggle( target: EventTarget | null ): void {
    // target is the listener's e.target — always an Element for click/keydown.
    const header = ( target as Element ).closest( ".task-group-header" );
    if ( header === null ) return;
    const tbody = header.closest<HTMLElement>( "tbody.task-group" );
    /* c8 ignore next */ // defensive: a rendered header always sits inside its group <tbody data-owner>.
    if ( tbody === null || tbody.dataset.owner === undefined ) return;
    toggleCollapsedOwner( tbody.dataset.owner );
    this.renderFromStore( false );
  }

  /** Collapse every currently-rendered owner group; persist + repaint. */
  private collapseAll(): void {
    /* c8 ignore next */ // defensive: the control only exists while mounted (container set).
    if ( this.container === null ) return;
    const owners = Array.from( this.container.querySelectorAll<HTMLElement>( "tbody.task-group[data-owner]" ) )
      .map( ( el ) => el.dataset.owner as string );
    saveCollapsedOwners( new Set( owners ) );
    this.renderFromStore( false );
  }

  /** Expand every owner group: clear the persisted set + repaint. */
  private expandAll(): void {
    saveCollapsedOwners( new Set() );
    this.renderFromStore( false );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTaskListRenderer( opts: TaskListRendererOptions ): TaskListRenderer {
  return new TaskListRendererImpl( opts );
}
