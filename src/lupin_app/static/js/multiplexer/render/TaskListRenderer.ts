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
import { ApiError } from "../api/ApiClient";
import { formatFleetTimestamp, type FleetComposite } from "./fleetModel";
import {
  activeReassignTargets,
  groupTasksByOwner,
  isOpenStatus,
  type TaskItem,
  type TaskListComposite,
} from "./taskListModel";
import type { TaskMutation, TaskPatchFields } from "../stores/TaskListStore";
import { renderTaskListTable } from "./templates/taskListTable";
import { loadCollapsedOwners, saveCollapsedOwners, toggleCollapsedOwner } from "./taskListCollapse";

export interface TaskListStoreLike {
  composite(): TaskListComposite | null;
  refresh(): Promise<void>;
  // Phase 2 — optimistic write surface (priority/owner edit + drop). Both return
  // a `{ restoreState, done }` handle the renderer drives (JobsPaneRenderer flow).
  patchTask( id: string, fields: TaskPatchFields ): TaskMutation;
  dropTask( id: string, reason: string ): TaskMutation;
}

// The fleet store the owner-reassignment roster is sourced from (Phase 2 — the
// SAME source the fleet-status card consumes). Only `composite()` is needed.
export interface TaskListFleetLike {
  composite(): FleetComposite | null;
}

export interface TaskListRendererStores {
  taskList : TaskListStoreLike;
  // Optional so read-only / legacy constructions still mount; when absent the
  // owner-reassignment roster is empty (the select shows only the current owner).
  fleet?   : TaskListFleetLike;
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

  // Phase 2 — keys of in-flight edits ("<id>:priority" / "<id>:owner" / "<id>:drop")
  // so a rapid second activation on the same control+row is a no-op until the
  // first settles (clears in the .finally of the mutation chain). Mirrors
  // JobsPaneRenderer.deleteInFlight.
  private readonly editInFlight: Set<string> = new Set();

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

    // Delegation: ONE set of listeners on the persistent container (its children
    // are replaced each render, the element is not), so every handler survives
    // re-render with no per-row re-binding. Click dispatches the drop-button
    // BEFORE the accordion toggle (the drop button lives inside a .task-row, not
    // a header, so it never matches the toggle anyway — but dispatching it first
    // keeps the intent explicit, mirroring JobsPaneRenderer F23). The `change`
    // listener handles the priority + owner selects.
    this.container.addEventListener( "click", ( e ) => this.handleContainerClick( e.target ) );
    this.container.addEventListener( "change", ( e ) => this.handleControlChange( e.target ) );
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
      this.container.replaceChildren( renderTaskListTable( model, undefined, loadCollapsedOwners(), this.reassignTargets() ) );
    }

    if ( stampUpdated ) this.stampUpdated();
  }

  // The owner-reassignment roster: active personas (Sam excluded) from the SAME
  // fleet source the fleet-status card consumes. Empty when no fleet store is
  // wired (optional construction) or no fleet data is cached yet (null composite).
  private reassignTargets(): string[] {
    return activeReassignTargets( this.stores.fleet?.composite() ?? null );
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
      this.container.replaceChildren( indicator, renderTaskListTable( model, undefined, loadCollapsedOwners(), this.reassignTargets() ) );
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
  // Per-row editing (Phase 2) — delegated change/click → optimistic store call
  // -------------------------------------------------------------------------

  /**
   * Container click dispatch. The drop-button path fires BEFORE the accordion
   * toggle (mirrors JobsPaneRenderer F23 — query by class, dispatch the active
   * control first). A non-drop click falls through to the accordion toggle.
   */
  private handleContainerClick( target: EventTarget | null ): void {
    const dropButton = ( target as Element ).closest( ".task-drop-button" );
    if ( dropButton !== null ) {
      this.handleDropClick( dropButton );
      return;
    }
    this.handleAccordionToggle( target );
  }

  /**
   * `change` on a priority or owner select → optimistic patch. Resolves the
   * target task id from the row's `data-task-id`; an empty id (a row whose
   * server row carried no id) is a defensive no-op.
   */
  private handleControlChange( target: EventTarget | null ): void {
    const select = ( target as Element ).closest<HTMLSelectElement>(
      "select.task-priority-select, select.task-owner-select",
    );
    if ( select === null ) return;
    const id = this.taskIdOf( select );
    if ( id === "" ) return;   // defensive: a row without an id cannot be mutated
    const value = select.value;
    if ( select.classList.contains( "task-priority-select" ) ) {
      this.commitMutation( `${id}:priority`, id, () => this.stores.taskList.patchTask( id, { priority: value } ) );
    } else {
      this.commitMutation( `${id}:owner`, id, () => this.stores.taskList.patchTask( id, { owner_persona: value } ) );
    }
  }

  /**
   * Drop-button click → read the sibling inline reason input, enforce the
   * non-blank reason the `→dropped` transition requires (inline error stripe
   * when blank — no api call), then optimistic drop.
   */
  private handleDropClick( dropButton: Element ): void {
    const row = dropButton.closest<HTMLElement>( ".task-row" );
    /* c8 ignore next */ // defensive: the drop button only ever lives inside a .task-row per the template invariant.
    if ( row === null ) return;
    const id = this.rowId( row );
    if ( id === "" ) return;   // defensive: idless row cannot be dropped
    const input  = row.querySelector<HTMLInputElement>( ".task-drop-reason" );
    /* c8 ignore next */ // defensive: renderActionsCell always renders a `.task-drop-reason` input in every row, so `input` is never null and `.value` is always a string — the `?? ""` guards a template-invariant violation that cannot occur.
    const reason = ( input?.value ?? "" ).trim();
    if ( reason === "" ) {
      this.renderRowError( id, "A drop reason is required." );
      return;
    }
    this.commitMutation( `${id}:drop`, id, () => this.stores.taskList.dropTask( id, reason ) );
  }

  // Resolve a control's owning task id from its `.task-row[data-task-id]`.
  private taskIdOf( el: Element ): string {
    const row = el.closest<HTMLElement>( ".task-row" );
    /* c8 ignore next */ // defensive: every editable control is rendered inside a .task-row per the template invariant.
    if ( row === null ) return "";
    return this.rowId( row );
  }

  // Read a row's task id. renderTaskRow ALWAYS sets `data-task-id` (to "" when
  // the server row carried no id), so getAttribute never returns null here.
  private rowId( row: HTMLElement ): string {
    /* c8 ignore next */ // defensive: data-task-id is always set by renderTaskRow (template invariant), so getAttribute never returns null and the `?? ""` RHS is unreachable.
    return row.getAttribute( "data-task-id" ) ?? "";
  }

  /**
   * Shared optimistic-mutation driver (clones JobsPaneRenderer.handleDeleteClick):
   * in-flight dedupe on `key`, invoke the store mutation (optimistic local edit +
   * `done` promise), and on settle —
   *   - 2xx → keep the optimistic edit;
   *   - ApiError 404 → treat as success (the row is already gone server-side);
   *   - any other error → `restoreState()` + an inline row error stripe.
   */
  private commitMutation( key: string, id: string, run: () => TaskMutation ): void {
    if ( this.editInFlight.has( key ) ) return;   // rapid re-activation is a no-op until settle
    this.editInFlight.add( key );
    const { restoreState, done } = run();
    done
      .then( () => { /* success — optimistic state stands */ } )
      .catch( ( err: unknown ) => {
        if ( err instanceof ApiError && err.status === 404 ) return;   // gone → success
        restoreState();
        this.renderRowError( id, deriveEditErrorMessage( err ) );
      } )
      .finally( () => { this.editInFlight.delete( key ); } );
  }

  /**
   * Append an inline error stripe to the row for `id`. After a `restoreState()`
   * the store's synchronous re-emit has already repainted the table, so this
   * targets the freshly-rendered row (the dataset lookup sidesteps id-escape
   * concerns). A no-matching-row lookup is a benign no-op.
   */
  private renderRowError( id: string, message: string ): void {
    /* c8 ignore next */ // defensive: renderRowError only runs while mounted (container set); the listeners detach in unmount before container is nulled.
    if ( this.container === null ) return;
    let target: HTMLElement | null = null;
    for ( const row of Array.from( this.container.querySelectorAll<HTMLElement>( ".task-row" ) ) ) {
      if ( row.dataset.taskId === id ) { target = row; break; }
    }
    /* c8 ignore next */ // defensive: the row is always in the DOM here (drop-blank path: unchanged DOM; failure path: restoreState repainted it).
    if ( target === null ) return;
    const existing = target.querySelector( ".task-row-error-stripe" );
    if ( existing !== null ) existing.remove();   // replace any prior stripe (no stacking)
    const stripe = document.createElement( "td" );
    stripe.className = "task-row-error-stripe";
    stripe.setAttribute( "role", "alert" );
    stripe.setAttribute( "aria-live", "polite" );
    stripe.textContent = message;
    target.appendChild( stripe );
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

// ---------------------------------------------------------------------------
// Helpers (module-private)
// ---------------------------------------------------------------------------

function deriveEditErrorMessage( err: unknown ): string {
  if ( err instanceof ApiError ) return `Edit failed (HTTP ${err.status})`;
  if ( err instanceof Error )    return `Edit failed: ${err.message}`;
  /* c8 ignore next */ // defensive: ApiClient always rejects with Error subclasses; this is a safety net for non-Error throws.
  return "Edit failed";
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTaskListRenderer( opts: TaskListRendererOptions ): TaskListRenderer {
  return new TaskListRendererImpl( opts );
}
