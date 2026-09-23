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
import { formatFleetTimestamp, type FleetComposite } from "./fleetModel";
import {
  activeReassignTargets,
  groupTasksByOwner,
  isOpenStatus,
  taskListCountText,
  type TaskItem,
  type TaskListComposite,
} from "./taskListModel";
import { holdingAreaHeaderCount, renderTruncationBanner } from "./templates/truncationBanner";
import { TASK_LIST_QUERY } from "../../shared/task-list-query.js";
import type { TaskMutation, TaskPatchFields } from "../stores/TaskListStore";
import type { TransitionExtras } from "./taskVerbs";
import { TaskRowController, type TaskRowRecorderLike } from "./taskRowController";
import { renderTaskLookupBox, type TaskLookupBoxHandle } from "./taskLookupBox";
import { renderNewTicketButton } from "./newTicketCard";
import {
  assigneeOptions,
  type NewTicketPayload,
  type NewTicketTransportResult,
} from "../../shared/task-create.js";
import { renderTaskListTable } from "./templates/taskListTable";
import { captureOperatorState, restoreOperatorState } from "./operatorState";
import { wireRequestPane, type RequestBoardStoreLike, type RequestPaneWiring } from "./requestChips";
import { wirePressHoldGuard, type PressHoldGuard } from "./pressHoldGuard";
import { BADGE_TASK_AREA } from "../../shared/task-request.js";
import { loadCollapsedOwners, saveCollapsedOwners, toggleCollapsedOwner } from "./taskListCollapse";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

export interface TaskListStoreLike {
  composite(): TaskListComposite | null;
  refresh(): Promise<void>;
  // 🔴 A DIFFERENT PRIMITIVE FROM `refresh()`, AND THE DIFFERENCE IS THE POINT.
  // `TaskListStore.refresh()` SKIPS when a read is already in flight, which is
  // right for the poll and for the ⟳ button — neither of them just wrote
  // anything. A caller that DID write needs a read that BEGAN after its write,
  // and that is this verb (measured at fcf2b6bc; see the store's own comment).
  refreshAfterWrite(): Promise<void>;
  // Phase 2 — optimistic write surface (priority/owner edit + drop). Both return
  // a `{ restoreState, done }` handle the renderer drives (JobsPaneRenderer flow).
  patchTask( id: string, fields: TaskPatchFields ): TaskMutation;
  // `string | null` because UN-PARK SENDS AN EXPLICIT null CHASE and is the only verb
  // that does. Rick ruled un-park clears the chase date; `transitionExtras` therefore
  // emits `next_chase_ts: null`, and an OMITTED key would leave the old chase standing
  // — "send nothing" and "send null" are different requests. Narrowing this back to
  // `Record<string, string>` silently reverses that ruling rather than fixing a type.
  // And an OBJECT, because Fixed sends `receipt_refs` (row 47377c92).
  transitionTask( id: string, toStatus: string, extras: TransitionExtras ): TaskMutation;
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
  /** Test injection — the timer for the ID click-to-copy flash. Defaults to `setTimeout`. */
  setTimeoutFn? : ( cb: () => void, ms: number ) => unknown;
  /**
   * Performs the single-row GET behind the "find ticket by id" box. In
   * production this is `apiClient.get<TaskItem>`, passed from boot.
   *
   * ⚠️ OPTIONAL, AND ITS ABSENCE MEANS "NO BOX" RATHER THAN A BROKEN ONE. A
   * caller with no API client cannot look anything up, and mounting an input
   * that could only ever fail is worse than not offering one. Both arms are
   * tested; there is no production-default to pragma away here, because there
   * is no sane default for a network call.
   */
  lookupFetch? : ( path: string ) => Promise<TaskItem>;
  /**
   * Sends the POST behind Rick's New Ticket card (row c9895403). In production this
   * is `apiPostTicket( apiClient.post )`, passed from boot.
   *
   * ⚠️ OPTIONAL, AND ITS ABSENCE MEANS "NO BUTTON" — the same reasoning as
   * `lookupFetch`: a card that could only ever fail to send is worse than none.
   */
  postTicket? : ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult>;
  /**
   * Row c9fafb9d — managers' demote requests. Supplies the badge beside the count chip and
   * the Approve/Deny behind each row's pending chip. Optional for tests only; boot passes it.
   */
  requestStore? : RequestBoardStoreLike;
  /** Test injection for the row mic — production uses the `recordingManager` singleton. */
  recorder?     : TaskRowRecorderLike;
  /** The bearer token the row mic's dictation upload carries. Boot passes the cached access token. */
  getAuthToken? : () => string | null;
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
  private readonly setTimeoutFn : ( cb: () => void, ms: number ) => unknown;
  // null → this construction cannot look tickets up, so no box is mounted.
  private readonly lookupFetch  : ( ( path: string ) => Promise<TaskItem> ) | null;
  // null → this construction cannot file tickets, so no New button is mounted.
  private readonly postTicket   : ( ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult> ) | null;
  private readonly requestStore : RequestBoardStoreLike | null;
  private requests : RequestPaneWiring | null = null;
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  /**
   * The PERSISTENT notices mount — a sibling of the container, never inside it.
   *
   * 🔴 INSIDE THE CONTAINER IS WHERE THIS WENT WRONG IN LEGACY, and the fix is
   * recorded at `_paintTaskListNotices` (notifications.js:12296): the banner was
   * concatenated onto the container's markup, every render replaces that whole
   * subtree, and on a 60-second polling pane a notice therefore survived seconds.
   * A sibling cannot be reached by the container's own re-render.
   */
  private noticesEl : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  // Lane 0a — section-header handle + collapse-listener teardown.
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private pressGuard : PressHoldGuard | null = null;
  private mounted   = false;

  // Last successfully-fetched OPEN rows — replayed under the "store unreachable"
  // indicator so a transient outage degrades to stale-not-blank.
  private lastGoodTasks : TaskItem[] | null = null;

  /**
   * The one row the lookup filtered to, or null when the list is unfiltered.
   *
   * 🔴 IT IS THE FETCHED ROW, NOT AN ID TO FILTER BY, and that is the load-bearing
   * choice. The row Rick pastes a hash for is usually NOT on the board — that is
   * the whole reason the lookup uses the visibility-free single-row endpoint. An
   * id filter over `composite.tasks` would answer "no such ticket" for exactly
   * the held rows he is most often asked about, which is worse than no search.
   * So the fetched row is rendered on its own terms, board membership or not.
   *
   * ⚠️ IT MUST SURVIVE POLLING. The store re-renders on every fetch; without this
   * being checked in the render path, the filter would vanish a second or two
   * after he applied it and look like a bug in the box.
   */
  private pinnedTask : TaskItem | null = null;
  private lookupBox  : TaskLookupBoxHandle | null = null;

  private readonly recorder     : TaskRowRecorderLike | undefined;
  private readonly getAuthToken : ( () => string | null ) | undefined;
  // Parity A-2 #0 — every row control's click/change/key is dispatched here, the
  // same controller the holding area mounts. Null while unmounted.
  private rows : TaskRowController | null = null;

  constructor( opts: TaskListRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
    /* c8 ignore next */ // production-default fallback: `setTimeout` is the runtime timer; tests inject a controllable fn.
    this.setTimeoutFn = opts.setTimeoutFn ?? ( ( cb, ms ) => globalThis.setTimeout( cb, ms ) );
    this.lookupFetch  = opts.lookupFetch ?? null;
    this.postTicket   = opts.postTicket ?? null;
    this.requestStore = opts.requestStore ?? null;
    this.recorder     = opts.recorder;
    this.getAuthToken = opts.getAuthToken;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "TaskListRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "task-list-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-task-list-refresh" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.stores.taskList.refresh() );

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

    const expandAllBtn = document.createElement( "button" );
    expandAllBtn.type = "button";
    expandAllBtn.className = "task-list-expand-all";
    expandAllBtn.setAttribute( "data-testid", "multiplexer-task-list-expand-all" );
    expandAllBtn.setAttribute( "title", "Expand all task owners" );
    expandAllBtn.textContent = "⊞";
    expandAllBtn.addEventListener( "click", () => this.expandAll() );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "task-list-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-task-list-updated" );

    // Lane 0a — convert the bespoke .task-list-header into the uniform
    // .section-header bar (📋 Task List). Refresh + collapse-all/expand-all +
    // updated stamp move into the .section-header-actions slot; the count uses
    // the shared .section-header-count chip (legacy testid preserved). NOTE: the
    // per-owner ROW collapse (collapseAll/expandAll → taskListCollapse.ts,
    // localStorage) is SEPARATE from the section-header's session-only collapse.
    // Rick's findability P0 (row 732151f2): paste the 8-hex token you were
    // handed in a DM and get the ticket. It sits in the header rather than the
    // body because the answer must be reachable when the board is collapsed —
    // and because the row you are asking about is usually NOT on the board.
    const lookupActions: HTMLElement[] = [];
    if ( this.lookupFetch !== null ) {
      const lookup = renderTaskLookupBox( {
        fetchTask : this.lookupFetch,
        onFound   : ( task ) => { this.pinnedTask = task; this.renderPinned(); },
        onCleared : () => { this.pinnedTask = null; this.renderFromStore( false ); },
      } );
      this.lookupBox = lookup;
      lookupActions.push( lookup.root );
    }
    // Rick's New Ticket card (row c9895403) — directly after Find, where he asked for
    // it: "within the task list bar right next to the find functionality".
    if ( this.postTicket !== null ) {
      lookupActions.push( renderNewTicketButton( {
        postTicket : this.postTicket,
        assignees  : () => assigneeOptions(
          this.reassignTargets(),
          ( this.lastGoodTasks ?? [] ).map( ( t ) => t.owner_persona ),
        ),
        onCreated  : ( row ) => this.showCreatedTicket( row ),
        // The card's Title and Details mics (row f9a449c3) ride the SAME recorder as
        // the row mic, so a pane wired for one is wired for both — a second recorder
        // here would be a second thing to forget to inject.
        ...( this.recorder === undefined ? {} : { recorder: this.recorder } ),
        ...( this.getAuthToken === undefined ? {} : { getAuthToken: this.getAuthToken } ),
      } ) );
    }

    const header = renderSectionHeader( {
      icon    : "📋",
      title   : "Task List",
      testid  : "multiplexer-task-list-header",
      actions : [ ...lookupActions, refreshBtn, collapseAllBtn, expandAllBtn, this.updatedEl ],
    } );
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.setAttribute( "data-testid", "multiplexer-task-list-count" );
    this.countEl.textContent = "0";

    this.container = document.createElement( "div" );
    // The container IS the collapsible body — carries `.section-content` so the
    // shared `[data-collapsed="true"] > .section-content` rule hides it.
    this.container.className = "section-content task-list-container";
    this.container.setAttribute( "data-testid", "multiplexer-task-list-container" );

    // The task list's badge counts DEMOTE requests: a row asking to be demoted is still on
    // this list, and the holding area's badge counts the other direction. Never summed.
    if ( this.requestStore !== null ) {
      const requests = wireRequestPane( {
        bus : this.bus, store : this.requestStore, countEl : this.countEl, container : this.container,
        badgeKey : BADGE_TASK_AREA, testid : "multiplexer-task-list-request-badge",
      } );
      this.requests = requests;
      this.unsubscribers.push( requests.dispose );
    }

    // Delegation: ONE set of listeners on the persistent container (its children
    // are replaced each render, the element is not), so every handler survives
    // re-render with no per-row re-binding. Row controls go to the shared
    // controller first; what it declines is this pane's own accordion.
    const rows = new TaskRowController( {
      container    : this.container,
      logLabel     : "[task-list]",
      recorder     : this.recorder,
      getAuthToken : this.getAuthToken,
      setTimeoutFn : this.setTimeoutFn,
      writer       : {
        patchTask      : ( id, fields ) => this.rowWrite( this.stores.taskList.patchTask( id, fields ) ),
        transitionTask : ( id, toStatus, extras ) => this.rowWrite( this.stores.taskList.transitionTask( id, toStatus, extras ) ),
      },
      onTransitionSettled : ( id, toStatus, gone ) => this.settlePinnedAfterVerb( id, toStatus, gone ),
    } );
    this.rows = rows;
    this.container.addEventListener( "click", ( e ) => {
      // A chip's Approve/Deny is not a row verb; it goes to the verdict door, never here.
      if ( this.requests !== null && this.requests.handleClick( e.target ) ) return;
      if ( rows.handleClick( e.target ) ) return;
      this.handleAccordionToggle( e.target );
    } );
    this.container.addEventListener( "change", ( e ) => rows.handleChange( e.target ) );
    this.container.addEventListener( "keydown", ( e ) => {
      const ke = e as KeyboardEvent;
      // Enter/Space on a focused 📄 or id cell is the controller's; on an accordion
      // header it is this pane's.
      if ( rows.handleKeydown( ke ) ) return;
      if ( ke.key !== "Enter" && ke.key !== " " && ke.key !== "Spacebar" ) return;
      if ( ( e.target as Element ).closest( ".task-group-header" ) === null ) return;
      e.preventDefault();   // Space must act, not scroll the page
      this.handleAccordionToggle( e.target );
    } );

    // Parity A-2 #7 — the notices mount, a SIBLING of the container so the
    // container's own re-render cannot reach it. It carries `.section-content`
    // as well, because the shared sheet hides `[data-collapsed="true"] >
    // .section-content`: without that class a collapsed pane would keep showing
    // a banner describing rows that are no longer on screen.
    // `role="status"` as legacy (notifications.html:931) — a screen reader hears
    // the banner appear without focus being stolen from the lookup box.
    this.noticesEl = document.createElement( "div" );
    this.noticesEl.className = "section-content task-list-notices";
    this.noticesEl.setAttribute( "data-testid", "multiplexer-task-list-notices" );
    this.noticesEl.setAttribute( "role", "status" );

    root.replaceChildren( header.header, this.noticesEl, this.container );
    this.collapseOff = wireSectionCollapse( root, header );
    this.pressGuard  = wirePressHoldGuard( this.container, { setTimeoutFn: this.setTimeoutFn } );

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
    this.rows?.dispose();   // tear down any open body overlay + its Esc listener
    this.rows = null;
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    this.pressGuard?.dispose();
    this.pressGuard = null;
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
    this.noticesEl = null;
    this.updatedEl = null;
    this.header = null;
    this.requests = null;
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
    // A press in flight holds the paint (parity A-1b): replacing the pressed node would
    // swallow the click. The release replays this call, reading the store afresh.
    if ( this.pressGuard!.hold( () => this.renderFromStore( stampUpdated ) ) ) return;
    const composite = this.stores.taskList.composite();

    // 🔴 EVERY FULL-PANEL STATE CLEARS THE NOTICES MOUNT EXPLICITLY. The notices
    // now live OUTSIDE the container, which is the point — and the cost is that
    // the container's re-render no longer removes them. A truncation banner left
    // hanging over a "Sign-in required" panel would describe a board that is not
    // on screen. Legacy pays the same cost the same way (notifications.js:12057).
    if ( composite && composite.status === "auth_required" ) {
      this.clearNotices();
      this.container.replaceChildren( messageEl( "task-list-signin", "🔒 Sign-in required." ) );
      this.setCountText( "Live: 0" );
      return;
    }

    if ( !composite || composite.status === "unreachable" || !Array.isArray( composite.tasks ) ) {
      this.clearNotices();
      this.renderUnreachable();
      return;
    }

    const openTasks = composite.tasks.filter( ( t ) => isOpenStatus( t.status ) );
    this.lastGoodTasks = openTasks;

    // A poll must not silently drop the operator's filter. Keep the fresh rows
    // in `lastGoodTasks` above — so clearing returns to CURRENT data, not to a
    // snapshot from whenever the filter was applied — then re-assert the pin.
    if ( this.pinnedTask !== null ) { this.renderPinned(); return; }

    this.setCountText( taskListCountText( openTasks ) );

    // Parity A-2 #7 — a query that came back short says so. Placed BEFORE the
    // rows are painted so the two never disagree about the same poll, and given
    // the Holding Area's header count so the "N waiting for your approval" note
    // is dropped when it merely repeats what that pane's own header already says.
    this.paintNotices( renderTruncationBanner( composite, TASK_LIST_QUERY, holdingAreaHeaderCount() ) );

    if ( openTasks.length === 0 ) {
      this.container.replaceChildren( messageEl( "task-list-empty", "✅ No open tasks." ) );
    } else {
      const model = groupTasksByOwner( openTasks );
      this.paintRows( renderTaskListTable( model, undefined, loadCollapsedOwners(), this.reassignTargets() ) );
    }

    if ( stampUpdated ) this.stampUpdated();
  }

  // The owner-reassignment roster: active personas (Sam INCLUDED — Q5) from the
  // SAME fleet source the fleet-status card consumes. Empty when no fleet store is
  // wired (optional construction) or no fleet data is cached yet (null composite).
  /**
   * Render the list as the ONE row the lookup found.
   *
   * Rick's rejection of the first build, verbatim: *"instead of displaying the
   * title in green text underneath of the search box you would hide all of the
   * other tickets in the task list and only display the 1 that was found —
   * that's how search or filtering would work."*
   *
   * Ensures:
   *   - the pinned row renders through the SAME table renderer as any other row,
   *     so its verbs, controls and accordion behave identically. A bespoke
   *     "search result" row would be a second rendering path to keep in step,
   *     which is the drift this codebase already pays for twice over
   *   - the count reflects what is ON SCREEN (1), not the board total, because a
   *     count that disagrees with the visible rows is how a filter reads as a
   *     data loss
   */
  private renderPinned(): void {
    const task = this.pinnedTask;
    if ( task === null || this.container === null ) return;

    const model = groupTasksByOwner( [ task ] );
    this.paintRows( renderTaskListTable( model, undefined, loadCollapsedOwners(), this.reassignTargets() ) );
    this.setCountText( "Live: 1" );
  }

  /**
   * Replace the pane's rows WITHOUT destroying the operator's unsubmitted work (parity A-1a).
   *
   * 🔴 EVERY ROW-BEARING PAINT GOES THROUGH HERE, AND CAPTURE SITS AT THE PAINT, NOT AT THE
   * TOP OF `renderFromStore`: three exits there delegate or paint a message, and a
   * capture/restore pair straddling a delegating return would be dead code that looks live.
   * The message-only paints (sign-in, empty) have no rows to restore into and skip it.
   *
   * Ensures:
   *   - state is read off the old markup, the new nodes replace it, the request chips are
   *     hydrated, and THEN state is restored — after hydrate, so focus lands on a chip
   *     box that exists (operator-state spec ruling 5)
   */
  private paintRows( ...nodes: Node[] ): void {
    /* c8 ignore next */ // defensive: every caller is past its own container-null guard.
    if ( this.container === null ) return;
    const state = captureOperatorState( this.container );
    this.container.replaceChildren( ...nodes );
    this.hydrateRequests();
    // Parity A-2 #0 — the handlers are the shared row controller's. Its priority change
    // only re-arms Update (the PATCH waits for the click), so a pending priority is now
    // restorable without re-sending an edit on every poll.
    restoreOperatorState( this.container, state, this.rows!.operatorStateHandlers() );
  }

  /** Fill the pending chips this paint built — filer, reason, and any refusal they carried. */
  private hydrateRequests(): void {
    if ( this.requests !== null && this.container !== null ) this.requests.hydrate( this.container );
  }

  /**
   * Make a row write settle on a READ, the way the holding area's does.
   *
   * 🔴 THE READ IS DECIDED HERE, NOT IN THE CONTROLLER. `TaskRowController` serves
   * both panes and contains zero `refresh` occurrences, so the entire difference
   * between a pane that goes stale after a mutation and one that does not is this
   * wrapper on the wiring line. Without it this pane showed the last poll's board
   * for up to a full poll interval after every owner change, priority update and
   * verb — three operator actions, all of them through these two verbs.
   *
   * ⚠️ `restoreState` IS PASSED THROUGH UNTOUCHED, and a rejection still rejects.
   * The store paints an optimistic row before the request is sent; the controller
   * rolls it back when `done` rejects, and chaining a `.then` leaves that path
   * exactly as it was — the read runs only on the success arm, where there is
   * something new to read.
   *
   * Ensures:
   *   - `done` resolves only after `refreshAfterWrite()` has resolved
   *   - `done` still rejects with the store's error, so rollback is unaffected
   *   - `restoreState` is the store's own restorer, not a new one
   */
  private rowWrite( mutation: TaskMutation ): TaskMutation {
    const done = mutation.done.then( () => this.stores.taskList.refreshAfterWrite() );
    return { restoreState: mutation.restoreState, done };
  }

  private reassignTargets(): string[] {
    return activeReassignTargets( this.stores.fleet?.composite() ?? null );
  }

  /**
   * After Rick files a ticket: refresh the board, and show him the row he just made.
   *
   * Ensures:
   *   - the store refreshes, so the new row joins the board on its next paint
   *   - when the Find box exists, the new row is looked up THROUGH it and pinned — the
   *     same filtered view with the same ✕ back to the whole list, rather than a second
   *     way of showing one row
   *   - a row with no string id is not looked up (there is nothing to find it by)
   */
  private showCreatedTicket( row: Record<string, unknown> ): void {
    // ⚠️ `refreshAfterWrite`, NOT `refresh` — a ticket filed while the poll happens
    // to be in flight would have its read SKIPPED, and the new row would not appear
    // until the tick after. Still fire-and-forget: the lookup below pins the row on
    // its own, and nothing here awaits the board.
    void this.stores.taskList.refreshAfterWrite();
    if ( this.lookupBox === null || typeof row.id !== "string" ) return;
    this.lookupBox.input.value = row.id;
    void this.lookupBox.submit();
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
      this.paintRows( indicator, renderTaskListTable( model, undefined, loadCollapsedOwners(), this.reassignTargets() ) );
      this.setCountText( taskListCountText( this.lastGoodTasks ) );
    } else {
      this.container.replaceChildren( indicator, messageEl( "task-list-empty", "No tasks loaded yet." ) );
      this.setCountText( "Live: 0" );
    }
  }

  private setCountText( text: string ): void {
    if ( this.countEl !== null ) this.countEl.textContent = text;
  }

  /** Replace the notices mount's children. Empty array clears it. */
  private paintNotices( lines: HTMLElement[] ): void {
    if ( this.noticesEl !== null ) this.noticesEl.replaceChildren( ...lines );
  }

  /**
   * Clear the notices mount.
   *
   * Its own verb rather than `paintNotices( [] )` at four call sites, because
   * the four full-panel states clear for a REASON — the banner would describe a
   * board that is not on screen — and a named verb carries that where an empty
   * array argument does not.
   */
  private clearNotices(): void {
    this.paintNotices( [] );
  }

  private stampUpdated(): void {
    /* c8 ignore next */ // defensive: stampUpdated only runs from renderFromStore past its container-null guard; updatedEl is set/nulled in lockstep with container. Belt-and-suspenders.
    if ( this.updatedEl === null ) return;
    this.updatedEl.textContent = `updated ${formatFleetTimestamp( this.nowDateFn(), undefined )}`;
  }

  // -------------------------------------------------------------------------
  // Per-row editing — dispatched by TaskRowController (parity A-2 #0)
  // -------------------------------------------------------------------------

  /**
   * After a verb lands on the row the Find box filtered to, decide what the filter
   * does next (Rick, row 700f0e1d: "whenever delete from a row filtered by the search
   * box takes place, the search card results should be cleared so that the whole
   * task list is displayed again").
   *
   * 🔴 THE PIN IS A FETCHED SNAPSHOT, so after ANY verb it shows the row as it was.
   * Keyed on where the row goes:
   *   - OFF the task list (drop, won't-fix, fixed, park, demote) → clear the filter
   *     and show the whole list, which is his ask;
   *   - STAYS on the list (un-park, approve → queued) → re-fetch the pin, so the
   *     filter he chose survives and shows the row's new state — UNLESS the server
   *     answered 404: the row is gone, so re-fetching would only report "not found"
   *     over a list that should simply come back (María's review, 27c1dc74).
   * Kept identical to the notifications client's `_settlePinnedRowAfterVerb`.
   *
   * Ensures:
   *   - no-op unless a row is pinned AND it is this row
   *   - "queued" on a 2xx re-runs the lookup; every other outcome clears the filter
   */
  private settlePinnedAfterVerb( id: string, toStatus: string, gone: boolean ): void {
    if ( this.pinnedTask === null || this.pinnedTask.id !== id ) return;
    /* c8 ignore next */ // defensive: a pin is only ever set by the lookup box's onFound, so a pinned row implies the box exists.
    if ( this.lookupBox === null ) return;
    if ( toStatus === "queued" && !gone ) { void this.lookupBox.submit(); return; }
    this.lookupBox.clear();
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
