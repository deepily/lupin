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
import {
  transitionExtras,
  verbDateComplaint,
  verbLabel,
  verbNeeds,
  verbReasonComplaint,
} from "./taskVerbs";
import { renderTaskListTable } from "./templates/taskListTable";
import { loadCollapsedOwners, saveCollapsedOwners, toggleCollapsedOwner } from "./taskListCollapse";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

export interface TaskListStoreLike {
  composite(): TaskListComposite | null;
  refresh(): Promise<void>;
  // Phase 2 — optimistic write surface (priority/owner edit + drop). Both return
  // a `{ restoreState, done }` handle the renderer drives (JobsPaneRenderer flow).
  patchTask( id: string, fields: TaskPatchFields ): TaskMutation;
  transitionTask( id: string, toStatus: string, extras: Record<string, string> ): TaskMutation;
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
}

// How long the transient "copied" flash stays on the ID cell (F1 2026.07.01).
// Mirrors the notifications.js checkmark dwell (~1.2s).
const COPIED_FLASH_MS = 1200;

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
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  // Lane 0a — section-header handle + collapse-listener teardown.
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted   = false;

  // Last successfully-fetched OPEN rows — replayed under the "store unreachable"
  // indicator so a transient outage degrades to stale-not-blank.
  private lastGoodTasks : TaskItem[] | null = null;

  // Phase 2 — keys of in-flight edits ("<id>:priority" / "<id>:owner" / "<id>:drop")
  // so a rapid second activation on the same control+row is a no-op until the
  // first settles (clears in the .finally of the mutation chain). Mirrors
  // JobsPaneRenderer.deleteInFlight.
  private readonly editInFlight: Set<string> = new Set();

  // Row redesign 2026.06.29 — the document-level Esc listener for the body
  // overlay, stored so dismissTaskBodyOverlay can detach it (null when closed).
  private taskBodyOverlayKeyListener: ( ( e: KeyboardEvent ) => void ) | null = null;

  constructor( opts: TaskListRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
    /* c8 ignore next */ // production-default fallback: `setTimeout` is the runtime timer; tests inject a controllable fn.
    this.setTimeoutFn = opts.setTimeoutFn ?? ( ( cb, ms ) => globalThis.setTimeout( cb, ms ) );
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
    const header = renderSectionHeader( {
      icon    : "📋",
      title   : "Task List",
      testid  : "multiplexer-task-list-header",
      actions : [ refreshBtn, collapseAllBtn, expandAllBtn, this.updatedEl ],
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
      // Enter/Space activates a focused detail 📄, an accordion header, OR an
      // interactive ID cell (F1 2026.07.01 — copy-to-clipboard). The ID cell is
      // only keyboard-operable when it carries [role="button"] (a real id).
      const emoji  = ( e.target as Element ).closest( ".task-detail-emoji" );
      const header = ( e.target as Element ).closest( ".task-group-header" );
      const idCell = ( e.target as Element ).closest( '.task-col-id[role="button"]' );
      if ( !emoji && !header && !idCell ) return;
      e.preventDefault();   // Space must act, not scroll the page
      this.handleContainerClick( e.target );
    } );

    root.replaceChildren( header.header, this.container );
    this.collapseOff = wireSectionCollapse( root, header );

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
    this.dismissTaskBodyOverlay();   // tear down any open body overlay + its Esc listener
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
    this.header = null;
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

  // The owner-reassignment roster: active personas (Sam INCLUDED — Q5) from the
  // SAME fleet source the fleet-status card consumes. Empty when no fleet store is
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
    // Detail 📄 (row redesign 2026.06.29) dispatches FIRST: a LIVE emoji opens the
    // body overlay; a DIMMED (empty-body) emoji is inert (no overlay, no toggle).
    const emoji = ( target as Element ).closest( ".task-detail-emoji" );
    if ( emoji !== null ) {
      if ( !emoji.classList.contains( "task-detail-empty" ) ) {
        const el = emoji as HTMLElement;
        this.openTaskBodyOverlay( el.dataset.taskBody ?? "", el.dataset.taskId ?? "" );
      }
      return;   // a detail-emoji click is never also a drop/accordion action
    }
    const submitButton = ( target as Element ).closest( ".task-submit-button" );
    if ( submitButton !== null ) {
      this.handleSubmitClick( submitButton as HTMLButtonElement );
      return;
    }
    // ID cell click-to-copy (F1 2026.07.01): a real-id cell copies its FULL uuid.
    // An em-dash (idless) cell has no [role="button"] but still matches .task-col-id;
    // handleIdCopy no-ops on the empty id, so the click is a harmless dead-end.
    const idCell = ( target as Element ).closest( ".task-col-id" );
    if ( idCell !== null ) {
      this.handleIdCopy( idCell as HTMLElement );
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
    const verbSelect = ( target as Element ).closest<HTMLSelectElement>( "select.task-verb-select" );
    if ( verbSelect !== null ) { this.handleVerbSelectChange( verbSelect ); return; }

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
   * A verb was chosen (or un-chosen) → re-shape the row's other two controls to
   * suit it.
   *
   * Three things move, and each of them is a different obligation the five verbs
   * used to carry separately:
   *   · the reason placeholder, so each verb still states its own ask;
   *   · the reason field's DISABLED state — Approve takes no input, and a live
   *     box beside a verb that discards its contents invites a justification
   *     nothing will ever read;
   *   · the date input, inserted only for the verbs that require one.
   *
   * 🔴 AND IT DISARMS SUBMIT. Won't-fix arms the button for a second click. An
   * armed button surviving a change of verb is worse than no arming at all: the
   * operator switches to Drop, clicks once expecting the usual single click, and
   * that click is swallowed by a confirmation for a verb they have left.
   *
   * Ensures:
   *   - the reason input is disabled iff the chosen verb takes no reason, and is
   *     cleared when disabled
   *   - a date input exists iff the verb requires one, labelled for THAT verb
   *   - Submit is returned to its unarmed label and state
   */
  private handleVerbSelectChange( select: HTMLSelectElement ): void {
    const cell = select.closest<HTMLElement>( ".task-col-actions" );
    /* c8 ignore next */ // defensive: the verb select only ever lives inside the actions cell per the template invariant.
    if ( cell === null ) return;

    const id    = this.taskIdOf( select );
    const needs = verbNeeds( select.value );
    const box   = cell.querySelector<HTMLInputElement>( ".task-reason-input" );
    const btn   = cell.querySelector<HTMLButtonElement>( ".task-submit-button" );

    if ( box !== null ) {
      box.disabled    = needs !== null && !needs.reason;
      box.placeholder = needs !== null ? needs.placeholder : "reason…";
      if ( box.disabled ) box.value = "";
    }

    const existing = cell.querySelector<HTMLInputElement>( ".task-chase-input" );
    if ( needs !== null && needs.date ) {
      const date = existing ?? document.createElement( "input" );
      date.type      = "date";
      date.className = "task-action-input task-chase-input";
      date.dataset.taskId = id;
      date.setAttribute( "aria-label", needs.dateLabel );
      date.setAttribute( "title", needs.dateLabel );
      if ( existing === null ) cell.insertBefore( date, btn );
    } else if ( existing !== null ) {
      existing.remove();
    }

    this.disarmSubmit( btn );
  }

  /**
   * Submit click → read the row's chosen verb, enforce what that verb requires,
   * then transition.
   *
   * ⚠️ Won't-fix takes TWO clicks and the confirmation is IN THE PAGE, on the
   * button's own label — Rick's ruling. A browser `confirm()` blocks the
   * extension's event loop, so the one control that closes a row for good cannot
   * be the one that freezes the board.
   *
   * Ensures:
   *   - no verb chosen → a stripe saying so, no api call
   *   - a required reason or date missing → that verb's OWN complaint, no api call
   *   - every refusal disarms Submit first, so a rejected confirm cannot be
   *     inherited by the next click
   *   - a terminal verb's FIRST click arms rather than submits
   *   - the posted body carries the verb's own extras (park under `park_reason`)
   */
  private handleSubmitClick( button: HTMLButtonElement ): void {
    const row = button.closest<HTMLElement>( ".task-row" );
    /* c8 ignore next */ // defensive: Submit only ever lives inside a .task-row per the template invariant.
    if ( row === null ) return;
    const id = this.rowId( row );
    if ( id === "" ) return;   // defensive: an idless row cannot be transitioned

    const select = row.querySelector<HTMLSelectElement>( ".task-verb-select" );
    /* c8 ignore next */ // defensive: Submit only ever renders in a cell that also renders the verb select.
    if ( select === null ) return;
    const verb  = select.value;
    const needs = verbNeeds( verb );
    if ( needs === null ) {
      this.disarmSubmit( button );
      this.renderRowError( id, "Choose an action first — the row does not know what you want done." );
      return;
    }

    const reason   = this.rowInputValue( row, "task-reason-input" );
    const chaseDay = this.rowInputValue( row, "task-chase-input" );

    if ( needs.reason && reason === "" ) {
      this.disarmSubmit( button );
      this.renderRowError( id, verbReasonComplaint( verb ) );
      return;
    }
    if ( needs.date && chaseDay === "" ) {
      this.disarmSubmit( button );
      this.renderRowError( id, verbDateComplaint( verb ) );
      return;
    }

    // ⚠️ THE DATE INPUT YIELDS A LOCAL CALENDAR DAY AND THE SERVER WANTS AN
    // INSTANT. `<input type="date">` gives "YYYY-MM-DD" with no time and no zone,
    // so this stamps 09:00 LOCAL and converts through the browser's own zone
    // rather than pasting the bare date and letting it be read as midnight UTC —
    // which lands the chase on the previous evening for anyone west of
    // Greenwich, i.e. everyone here.
    let chaseIso: string | null = null;
    if ( needs.date ) {
      const parsed = new Date( `${chaseDay}T09:00:00` );
      if ( isNaN( parsed.getTime() ) ) {
        this.disarmSubmit( button );
        this.renderRowError( id, `Date not understood: ${chaseDay}` );
        return;
      }
      chaseIso = parsed.toISOString();
    }

    if ( needs.terminal && button.dataset.armed !== "1" ) {
      button.dataset.armed = "1";
      button.classList.add( "task-submit-armed" );
      button.textContent = `Confirm ${verbLabel( verb ).toLowerCase()}`;
      this.renderRowError( id, "" );
      return;
    }

    const extras = transitionExtras( verb, reason, chaseIso );
    this.renderRowError( id, "" );
    this.disarmSubmit( button );
    this.commitMutation( `${id}:${verb}`, id, () => this.stores.taskList.transitionTask( id, needs.status, extras ) );
  }

  /**
   * Read one of a row's action inputs, trimmed, or "" when it is not rendered.
   *
   * Both outcomes are ordinary rather than defensive: the reason box is always
   * present, and the date box exists only while a verb that needs a date is
   * chosen — so a missing `.task-chase-input` is the normal state for the other
   * three verbs, not a template violation.
   */
  private rowInputValue( row: HTMLElement, className: string ): string {
    const el = row.querySelector<HTMLInputElement>( `.${className}` );
    return el === null ? "" : el.value.trim();
  }

  /**
   * Return Submit to its resting state: one click, one action.
   *
   * Ensures: no-op on a missing button; the armed flag is cleared and the label
   * reads "Submit" again.
   */
  private disarmSubmit( button: HTMLButtonElement | null ): void {
    /* c8 ignore next */ // defensive: every actions cell renders a Submit per the template invariant.
    if ( button === null ) return;
    delete button.dataset.armed;
    button.classList.remove( "task-submit-armed" );
    button.textContent = "Submit";
  }

  /**
   * ID-cell click / Enter / Space (F1 2026.07.01): copy the row's FULL id (the
   * uuid on `data-task-id`, not the visible 8-char prefix) to the clipboard, then
   * flash a transient no-reflow "copied" state on the cell.
   *
   * Guards (never throws):
   *   - idless row (data-task-id === "") → no-op (nothing to copy)
   *   - runtime without `navigator.clipboard` → graceful no-op (no feedback)
   *   - writeText rejection (permission denied) → swallowed, no flash
   */
  private handleIdCopy( idCell: HTMLElement ): void {
    const row = idCell.closest<HTMLElement>( ".task-row" );
    /* c8 ignore next */ // defensive: an ID cell only ever lives inside a .task-row per the template invariant.
    if ( row === null ) return;
    const fullId = this.rowId( row );
    if ( fullId === "" ) return;   // idless row → nothing to copy
    const clipboard = navigator.clipboard;
    if ( clipboard == null ) return;   // unsupported runtime → graceful no-op
    void clipboard.writeText( fullId )
      .then( () => this.flashCopied( idCell ) )
      .catch( () => { /* clipboard denied/failed → no feedback, no throw */ } );
  }

  /**
   * Flash the transient "copied" affordance on the ID cell: add `.task-id-copied`
   * (a same-width color/overlay change via CSS — NO text swap, so the row never
   * reflows and the visual snapshot is unaffected), then remove it after
   * COPIED_FLASH_MS. Mirrors the notifications.js checkmark dwell.
   */
  private flashCopied( idCell: HTMLElement ): void {
    idCell.classList.add( "task-id-copied" );
    this.setTimeoutFn( () => idCell.classList.remove( "task-id-copied" ), COPIED_FLASH_MS );
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
   * Append an inline error stripe to the row for `id`, or CLEAR the row's stripe
   * when `message` is empty. After a `restoreState()`
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
    // An EMPTY message CLEARS rather than paints. The submit path uses it to wipe
    // a previous refusal before acting, and a stripe carrying no text is still a
    // stripe: it survives in the DOM, matches every `.task-row-error-stripe`
    // selector a test or a stylesheet reaches for, and reads as an error that
    // says nothing.
    if ( message === "" ) return;
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

  // -------------------------------------------------------------------------
  // Body overlay (row redesign 2026.06.29 / D2 — renders the task `body`)
  // -------------------------------------------------------------------------

  /**
   * Show a small dismissible overlay rendering the task-store `body` (D2 — the
   * BODY field, NOT the notification abstract). All DOM via createElement +
   * textContent (no innerHTML — safe-write for the store-sourced body). Dismiss
   * on backdrop click or Escape.
   *
   * Ensures:
   *   - any prior overlay is removed first (single instance)
   *   - the overlay carries an id header + the body in a <pre> (whitespace kept)
   *   - a backdrop click OR Escape removes the overlay AND detaches its keydown listener
   */
  private openTaskBodyOverlay( bodyText: string, idLabel: string ): void {
    this.dismissTaskBodyOverlay();

    const overlay = document.createElement( "div" );
    overlay.id        = "task-body-overlay";
    overlay.className = "task-body-overlay";

    const panel = document.createElement( "div" );
    panel.className = "task-body-overlay-content";

    const header = document.createElement( "div" );
    header.className = "task-body-overlay-header";
    header.textContent = idLabel ? `Task ${idLabel}` : "Task detail";

    const pre = document.createElement( "pre" );
    pre.className = "task-body-overlay-body";
    pre.textContent = bodyText;   // textContent → no HTML injection from body

    panel.appendChild( header );
    panel.appendChild( pre );
    overlay.appendChild( panel );

    // Backdrop click dismisses; a click INSIDE the panel does not (stopPropagation).
    overlay.addEventListener( "click", () => this.dismissTaskBodyOverlay() );
    panel.addEventListener( "click", ( e ) => e.stopPropagation() );

    this.taskBodyOverlayKeyListener = ( e: KeyboardEvent ): void => {
      if ( e.key === "Escape" ) this.dismissTaskBodyOverlay();
    };
    document.addEventListener( "keydown", this.taskBodyOverlayKeyListener );

    document.body.appendChild( overlay );
  }

  /**
   * Tear down the body overlay if present: remove the element + the document
   * Esc listener. Idempotent (the open path calls it first to enforce a single
   * instance; unmount calls it to clean up).
   */
  private dismissTaskBodyOverlay(): void {
    if ( this.taskBodyOverlayKeyListener !== null ) {
      document.removeEventListener( "keydown", this.taskBodyOverlayKeyListener );
      this.taskBodyOverlayKeyListener = null;
    }
    const existing = document.getElementById( "task-body-overlay" );
    if ( existing !== null ) existing.remove();
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
