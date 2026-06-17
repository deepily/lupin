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

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "task-list-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-task-list-updated" );
    header.appendChild( this.updatedEl );

    this.container = document.createElement( "div" );
    this.container.className = "task-list-container";
    this.container.setAttribute( "data-testid", "multiplexer-task-list-container" );

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
      this.container.replaceChildren( renderTaskListTable( model, undefined ) );
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
      this.container.replaceChildren( indicator, renderTaskListTable( model, undefined ) );
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
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createTaskListRenderer( opts: TaskListRendererOptions ): TaskListRenderer {
  return new TaskListRendererImpl( opts );
}
