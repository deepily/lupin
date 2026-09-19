/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Epic-board card — EpicBoardRenderer (row 87812328).
//
// The pane's dispatch over templates/epicBoardTable.ts, plus its accordion.
//
// 🔴 IT SHARES THE TASK LIST'S STORE AND TAKES NO FETCH OF ITS OWN. That is the
// mechanism by which the two panes cannot show different clocks — the legacy
// client's own comment says it plainly, "no second fetch, no second timer", and
// a pane with its own timer reads as a bug the first time the two disagree. So
// this renderer subscribes to `store_task_list_changed` and reads the SAME
// composite the task list read.
//
// 🔴 THE COUNT IS EPICS, NOT ROWS — the macro unit, and the one place this pane
// deliberately disagrees with its two siblings. The holding area counts held
// rows and the task list counts open rows; this counts GROUPS. A port that
// "fixed" it into a row count would look right on every screen and answer a
// different question.
//
// ⚠️ THE OPEN-ROW FILTER IS THE TASK LIST'S, APPLIED HERE TOO, so the two panes
// can never disagree about which rows exist.
//
// ⚠️ NO TRUNCATION BANNER, DELIBERATELY: the pane above already carries one for
// the same rows. Repeating it would double-report one cap.
//
// 🔴 THE ROW CONTROLS ARE THE SHARED CONTROLLER'S, NOT THIS PANE'S (parity A-2 #9).
// Until A-2 #9 this pane painted every control the shared row carries — ⋯, 📄, id
// cell, verbs, priority, owner — and listened only for its accordion, so each one
// rendered and reached no handler. Legacy routes them through `_handleEpicBoardClick`
// and `_wireVerbSelects` (notifications.js:15182-15237); here the same
// `TaskRowController` the Task List and Holding Area mount takes every row click,
// change and key first, and only what it declines falls to the accordion. One verb
// table, one dispatcher — a second list here is how a pane drifts.

import type { EventBus } from "../shared/EventBus";
import type { StoreTaskListChangedPayload } from "../shared/types";
import type { TaskListComposite, TaskItem } from "./taskListModel";
import { isOpenStatus } from "./taskListModel";
import { formatFleetTimestamp } from "./fleetModel";
import { groupTasksByEpic, type EpicStories } from "./epicBoardModel";
import { loadEpicGroupState, saveEpicGroupState, toggleEpicCollapsed } from "./epicBoardCollapse";
import { renderEpicBoardTable } from "./templates/epicBoardTable";
import { closeDisclosedRowsIn, renderRowError as paintRowError } from "./templates/rowDisclosure";
import { captureOperatorState, restoreOperatorState, type OperatorState } from "./operatorState";
import { wirePressHoldGuard, type PressHoldGuard } from "./pressHoldGuard";
import { TaskRowController, type TaskRowRecorderLike } from "./taskRowController";
import type { TaskMutation, TaskPatchFields } from "../stores/TaskListStore";
import type { TransitionExtras } from "./taskVerbs";
import {
  renderSectionHeader,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

/**
 * The pane's messages. Carbon-copied from notifications.js `renderEpicBoard`.
 *
 * ⚠️ THE UNREACHABLE MESSAGE SAYS WHAT THE PANE IS DOING AND WHY — "showing
 * nothing rather than something stale". The epic board is a planning surface;
 * a stale epic invites a decision about work that has already moved.
 */
export const EPIC_BOARD_SIGNIN_MESSAGE = "🔒 Sign-in required.";
export const EPIC_BOARD_QUERY_UNAVAILABLE_MESSAGE =
  "🧩 Task-list query did not load — /static/js/shared/task-list-query.js is missing or failed to parse. This is a deploy problem, not a store outage.";
export const EPIC_BOARD_UNREACHABLE_MESSAGE = "⚠️ Store unreachable — showing nothing rather than something stale.";

export interface EpicBoardTaskStoreLike {
  composite(): TaskListComposite | null;
  refresh(): Promise<void>;
  /** The read after a row write — see TaskListRenderer `rowWrite` for why not `refresh()`. */
  refreshAfterWrite(): Promise<void>;
  /** The row writes (parity A-2 #9). The TASK LIST's store, so a write repaints both panes. */
  patchTask( id: string, fields: TaskPatchFields ): TaskMutation;
  transitionTask( id: string, toStatus: string, extras: TransitionExtras ): TaskMutation;
}

export interface EpicBoardRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  /** Repaint from the store WITHOUT stamping the updated-at time. For a source
   *  that changes what a render LOOKS UP rather than what the store HOLDS — the
   *  memoized epic-stories map, which lands after first paint. */
  repaint(): void;
  forceRenderForTesting(): void;
}

export interface EpicBoardRendererOptions {
  eventBus   : EventBus;
  /** The TASK LIST's store — shared on purpose; this pane never fetches. */
  store      : EpicBoardTaskStoreLike;
  /** The memoized `GET /api/epic-stories` map, or a fn returning it. */
  storiesFn? : () => EpicStories;
  nowDateFn? : () => Date;
  /** Test injection — the timer behind the press-hold guard's deferred release and the id-copy flash. Defaults to `setTimeout`. */
  setTimeoutFn? : ( cb: () => void, ms: number ) => unknown;
  /** Test injection for the row mic — production uses the `recordingManager` singleton. */
  recorder?     : TaskRowRecorderLike;
  /** The bearer token the row mic's dictation upload carries. Boot passes the cached access token. */
  getAuthToken? : () => string | null;
}

function messageEl( className: string, text: string ): HTMLParagraphElement {
  const p = document.createElement( "p" );
  p.className = `task-list-message ${ className }`;
  p.textContent = text;
  return p;
}

class EpicBoardRendererImpl implements EpicBoardRenderer {
  private readonly bus       : EventBus;
  private readonly store     : EpicBoardTaskStoreLike;
  private readonly storiesFn : () => EpicStories;
  private readonly nowDateFn : () => Date;
  private readonly setTimeoutFn : ( ( cb: () => void, ms: number ) => unknown ) | undefined;
  private readonly recorder     : TaskRowRecorderLike | undefined;
  private readonly getAuthToken : ( () => string | null ) | undefined;
  private readonly unsubscribers: Array<() => void> = [];
  // Parity A-2 #9 — the shared row controls. Null while unmounted.
  private rows : TaskRowController | null = null;

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private pressGuard : PressHoldGuard | null = null;
  private mounted   = false;

  constructor( opts: EpicBoardRendererOptions ) {
    this.bus   = opts.eventBus;
    this.store = opts.store;
    /* c8 ignore next */ // production-default fallback: an unwired stories source is an empty map (de-slugged names, no story rows).
    this.storiesFn = opts.storiesFn ?? ( () => ( {} ) );
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
    this.setTimeoutFn = opts.setTimeoutFn;
    this.recorder     = opts.recorder;
    this.getAuthToken = opts.getAuthToken;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "EpicBoardRenderer already mounted" );
    }
    this.mounted = true;
    this.root = root;

    const refreshBtn = document.createElement( "button" );
    refreshBtn.type = "button";
    refreshBtn.className = "epic-board-refresh";
    refreshBtn.setAttribute( "data-testid", "multiplexer-epic-board-refresh" );
    refreshBtn.textContent = "⟳";
    refreshBtn.addEventListener( "click", () => void this.store.refresh() );

    this.updatedEl = document.createElement( "span" );
    this.updatedEl.className = "epic-board-updated";
    this.updatedEl.setAttribute( "data-testid", "multiplexer-epic-board-updated" );

    // The header's bulk pair (parity A-2 #9, legacy notifications.html:1103-1110).
    // Legacy carries it IN THIS PANE'S header, not a shared toolbar, and so does this.
    const collapseAllBtn = document.createElement( "button" );
    collapseAllBtn.type = "button";
    collapseAllBtn.className = "epic-board-collapse-all";
    collapseAllBtn.setAttribute( "data-testid", "multiplexer-epic-board-collapse-all" );
    collapseAllBtn.setAttribute( "title", "Collapse all epics" );
    collapseAllBtn.textContent = "⊟";
    collapseAllBtn.addEventListener( "click", () => this.setAllEpicsCollapsed( true ) );

    const expandAllBtn = document.createElement( "button" );
    expandAllBtn.type = "button";
    expandAllBtn.className = "epic-board-expand-all";
    expandAllBtn.setAttribute( "data-testid", "multiplexer-epic-board-expand-all" );
    expandAllBtn.setAttribute( "title", "Expand all epics" );
    expandAllBtn.textContent = "⊞";
    expandAllBtn.addEventListener( "click", () => this.setAllEpicsCollapsed( false ) );

    const header = renderSectionHeader( {
      icon    : "🗺️",
      title   : "Epic Board",
      testid  : "multiplexer-epic-board-header",
      actions : [ refreshBtn, collapseAllBtn, expandAllBtn, this.updatedEl ],
    } );
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.setAttribute( "data-testid", "multiplexer-epic-board-count" );
    this.countEl.textContent = "0";

    this.container = document.createElement( "div" );
    this.container.className = "section-content epic-board-container";
    this.container.setAttribute( "data-testid", "multiplexer-epic-board-container" );

    // ONE delegated listener on the persistent container — its children are
    // replaced each render, the element is not — so the accordion survives every
    // repaint with no per-section re-binding.
    //
    // ⚠️ ROW CONTROLS FIRST, THEN THE ACCORDION — legacy's order
    // (`_handleEpicBoardClick`, notifications.js:15182-15211). A control click that
    // fell through would open the row's form and collapse its group in one gesture.
    const rows = new TaskRowController( {
      container    : this.container,
      logLabel     : "[epic-board]",
      recorder     : this.recorder,
      getAuthToken : this.getAuthToken,
      setTimeoutFn : this.setTimeoutFn,
      writer       : {
        patchTask      : ( id, fields ) => this.rowWrite( this.store.patchTask( id, fields ) ),
        transitionTask : ( id, toStatus, extras ) => this.rowWrite( this.store.transitionTask( id, toStatus, extras ) ),
      },
    } );
    this.rows = rows;
    this.container.addEventListener( "click", ( e ) => {
      if ( rows.handleClick( e.target ) ) return;
      this.handleAccordionActivate( e.target );
    } );
    // Legacy `_wireVerbSelects( container )` — the verb, priority and owner selects.
    this.container.addEventListener( "change", ( e ) => rows.handleChange( e.target ) );
    this.container.addEventListener( "keydown", ( e ) => {
      const ke = e as KeyboardEvent;
      // Enter/Space on a focused 📄 or id cell is the controller's; on a group header it is this pane's.
      if ( rows.handleKeydown( ke ) ) return;
      if ( ke.key !== "Enter" && ke.key !== " " && ke.key !== "Spacebar" ) return;
      if ( !( e.target as Element ).closest( ".epic-group-header" ) ) return;
      e.preventDefault();   // Space must act, not scroll the page
      this.handleAccordionActivate( e.target );
    } );

    root.replaceChildren( header.header, this.container );
    this.collapseOff = wireSectionCollapse( root, header );
    this.pressGuard  = wirePressHoldGuard( this.container, { setTimeoutFn: this.setTimeoutFn } );

    this.renderFromStore( false );

    this.unsubscribers.push(
      this.bus.on<StoreTaskListChangedPayload>(
        "store_task_list_changed",
        ( e ) => this.renderFromStore( e.payload.stampUpdated ),
      ),
    );
  }

  unmount(): void {
    this.rows?.dispose();
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
    this.updatedEl = null;
    this.header = null;
    this.mounted = false;
  }

  /**
   * Repaint from the store, leaving the updated-at stamp alone.
   *
   * `stampUpdated` is FALSE deliberately and the difference is not cosmetic:
   * the stamp answers "when was this data last fetched", and the epic-stories
   * map is not this pane's data — it is a lookup the render consults. Stamping
   * here would move a clock that measures the task-list composite, which has
   * not moved.
   *
   * Ensures:
   *   - repaints iff mounted; a no-op before mount and after unmount
   */
  repaint(): void {
    if ( this.mounted ) this.renderFromStore( false );
  }

  forceRenderForTesting(): void {
    if ( this.mounted ) this.renderFromStore( true );
  }

  // -------------------------------------------------------------------------
  // Dispatch (the four states — the SAME four the task list carries, so the two
  // panes degrade identically)
  // -------------------------------------------------------------------------

  private renderFromStore( stampUpdated: boolean ): void {
    /* c8 ignore next */ // defensive: subscriptions detach in unmount BEFORE container is nulled.
    if ( this.container === null ) return;
    // A press in flight holds the paint (parity A-1b): replacing the pressed node would
    // swallow the click. The release replays this call, reading the store afresh.
    if ( this.pressGuard!.hold( () => this.renderFromStore( stampUpdated ) ) ) return;
    const composite = this.store.composite();

    if ( composite && composite.status === "auth_required" ) {
      this.container.replaceChildren( messageEl( "task-list-signin", EPIC_BOARD_SIGNIN_MESSAGE ) );
      this.setCount( 0 );
      return;
    }

    if ( composite && composite.status === "query_unavailable" ) {
      this.container.replaceChildren(
        messageEl( "task-list-query-unavailable", EPIC_BOARD_QUERY_UNAVAILABLE_MESSAGE ) );
      this.setCount( 0 );
      return;
    }

    if ( !composite || composite.status === "unreachable" || !Array.isArray( composite.tasks ) ) {
      // ⚠️ THE COUNT IS DELIBERATELY LEFT ALONE HERE, matching the legacy pane.
      // Zeroing it would ASSERT there are no epics; leaving it says the last
      // known figure is the last thing anyone measured. The message beside it
      // already says the rows are not being shown.
      this.container.replaceChildren( messageEl( "task-list-unreachable", EPIC_BOARD_UNREACHABLE_MESSAGE ) );
      return;
    }

    // The SAME open-row filter the task list applies, so the two panes can never
    // disagree about which rows exist.
    const openTasks: TaskItem[] = composite.tasks.filter( ( t ) => isOpenStatus( ( t ?? {} as TaskItem ).status ) );
    const model = groupTasksByEpic( openTasks );

    // 🔴 EPICS, NOT ROWS — see the file header.
    this.setCount( model.groups.length );

    this.paintTable( renderEpicBoardTable( model, loadEpicGroupState(), this.storiesFn() ) );

    if ( stampUpdated ) this.stampUpdated();
  }

  /**
   * Replace the board WITHOUT destroying the operator's unsubmitted work (parity A-1a).
   * Legacy wraps this pane's repaint in `_captureOperatorState` / `_restoreOperatorState`
   * (notifications.js:14995-14997), pane-wide; this is that pair, through the shared module.
   *
   * 🔴 CAPTURED AND RESTORED PER GROUP, NOT PER PANE — THE ONE WAY THIS PANE DIFFERS FROM
   * ITS SIBLINGS. A row waiting on Rick is painted twice here, under ⏳ Waiting on Rick
   * and under its own epic, and the module's lookups take the first match in the scope
   * they are given. Pane-wide, a reason typed in the epic copy came back in the
   * Waiting-on-Rick copy, and the epic copy's Submit then refused for want of a reason:
   * the poll changed what the click did. Each group is keyed by its `data-epic`, which is
   * unique per board, compared as an attribute and never put in a selector.
   *
   * ⚠️ A GROUP THE FRESH PAINT NO LONGER HAS IS RESTORED PANE-WIDE, NOT DROPPED. Its
   * rows may still be on screen in another group — an epic re-keyed, a row Rick just
   * unblocked — and the spec's rule is "destroy nothing that is still on screen". Those go
   * FIRST, so a group that still exists restores exactly and has the last word.
   *
   * Only the table paint goes through here, as on the Task List: the message paints have
   * no rows to restore into.
   *
   * Ensures:
   *   - each group's state is read off the old markup, the table replaces it, and the
   *     state is restored into the fresh group carrying the same `data-epic`
   *   - a vanished group's state is restored into the pane, before the others; a row
   *     that is gone everywhere stays gone (spec §5)
   *   - a restored refusal is painted in the stripe of the scope it was restored into
   */
  private paintTable( table: HTMLTableElement ): void {
    /* c8 ignore next */ // defensive: the only caller is past renderFromStore's container-null guard.
    if ( this.container === null ) return;
    const captured: Array<[ string, OperatorState ]> = this.groups().map(
      ( g ) => [ g.dataset.epic as string, captureOperatorState( g ) ] );
    this.container.replaceChildren( table );
    const fresh    = this.groups();
    const handlers = this.rows!.operatorStateHandlers();
    const scoped   = captured.map( ( [ key, state ] ): [ ParentNode | undefined, OperatorState ] =>
      [ fresh.find( ( g ) => g.dataset.epic === key ), state ] );
    const pane     = this.container;
    const restore  = ( scope: ParentNode, state: OperatorState ): void => restoreOperatorState( scope, state, {
      ...handlers,
      renderRowError : ( id, message ) => paintRowError( scope, id, message ),
    } );
    for ( const [ group, state ] of scoped ) if ( group === undefined ) restore( pane, state );
    for ( const [ group, state ] of scoped ) if ( group !== undefined ) restore( group, state );
  }

  /** Every rendered epic group, in paint order. */
  private groups(): HTMLElement[] {
    return Array.from( this.container!.querySelectorAll<HTMLElement>( "tbody.epic-group[data-epic]" ) );
  }

  // -------------------------------------------------------------------------
  // The accordion
  // -------------------------------------------------------------------------

  private handleAccordionActivate( target: EventTarget | null ): void {
    /* c8 ignore next */ // defensive: the listener lives on the container, which is non-null while mounted.
    if ( this.container === null || target === null ) return;
    const header = ( target as Element ).closest( ".epic-group-header" );
    if ( header === null ) return;

    const tbody = header.closest( "tbody.epic-group" ) as HTMLElement | null;
    /* c8 ignore next */ // defensive: the template always nests the header inside its group tbody.
    if ( tbody === null ) return;
    const epicKey = tbody.dataset.epic;
    /* c8 ignore next */ // defensive: the template always sets data-epic on the group tbody.
    if ( !epicKey ) return;

    // ⚠️ THE PERSISTED CHOICE IS THE SOURCE OF TRUTH, AND THE DOM FOLLOWS IT —
    // not the other way round. Reading the current state off the class would
    // make a repaint that arrives mid-click flip the wrong way.
    //
    // 🔴 toggleEpicCollapsed RETURNS THE NEW **COLLAPSED** BOOLEAN, NOT
    // "EXPANDED". Its own docstring calls inverting it "the polarity trap this
    // file exists to hold the line on" — and the first cut of this handler
    // named it `nowExpanded` and used it as such, inverting the class, the
    // aria-expanded and the chevron all at once. Nothing about that looks
    // broken in a screenshot: the section still opens and closes, just the
    // wrong way round from the persisted choice. Three tests caught it.
    this.applyGroupCollapseState( tbody, toggleEpicCollapsed( epicKey ) );
  }

  /**
   * Reflect one group's collapsed state into its rendered DOM, without a repaint.
   * Port of notifications.js `_applyEpicGroupCollapseState` (:15015-15036).
   *
   * Ensures:
   *   - the tbody's `collapsed` class, its header's `aria-expanded` and its chevron
   *     all match `collapsed`
   *   - collapsing closes every row disclosed inside the group and clears its stripe
   *     (legacy `_closeDisclosedRowsIn`, :13078) — expanding opens none
   */
  private applyGroupCollapseState( tbody: HTMLElement, collapsed: boolean ): void {
    tbody.classList.toggle( "collapsed", collapsed );
    if ( collapsed ) closeDisclosedRowsIn( tbody );
    const header = tbody.querySelector( ".epic-group-header" );
    /* c8 ignore next */ // defensive: the template always paints the header inside its group tbody.
    if ( header !== null ) header.setAttribute( "aria-expanded", String( !collapsed ) );
    const chevron = tbody.querySelector( ".epic-group-chevron" );
    if ( chevron !== null ) chevron.textContent = collapsed ? "▸" : "▾";
  }

  /**
   * The header's ⊟ / ⊞: one choice for every RENDERED group, persisted and painted
   * in place. Port of notifications.js `collapseAllEpics` / `expandAllEpics`
   * (:15254-15282).
   *
   * 🔴 AN EXPLICIT CHOICE PER KEY, NOT A CLEARED MAP. Clearing would hand every group
   * back its default, and ⏳ Waiting on Rick defaults OPEN — so ⊟ would leave it open.
   * Writing `false` for each rendered key overrides the default, as legacy does.
   *
   * Ensures:
   *   - every rendered `data-epic` key is recorded as `!collapsed`; keys not on screen keep
   *     their recorded choice
   *   - every rendered group's DOM reflects the state, and a collapse closes its disclosed rows
   */
  private setAllEpicsCollapsed( collapsed: boolean ): void {
    /* c8 ignore next */ // defensive: the header buttons exist only while mounted (container set).
    if ( this.container === null ) return;
    const groups = this.groups();
    const state  = loadEpicGroupState();
    for ( const tbody of groups ) state[ tbody.dataset.epic as string ] = !collapsed;
    saveEpicGroupState( state );
    for ( const tbody of groups ) this.applyGroupCollapseState( tbody, collapsed );
  }

  /**
   * A row write, followed by a read that is guaranteed to see it.
   *
   * ⚠️ `refreshAfterWrite`, NOT `refresh` — the same reason as TaskListRenderer's
   * `rowWrite`: a poll already in flight would otherwise answer for this write.
   * The store is the Task List's, so the read repaints both panes.
   *
   * Ensures:
   *   - `done` resolves only after the read has; it still rejects with the store's
   *     error, so the controller's rollback is unaffected
   */
  private rowWrite( mutation: TaskMutation ): TaskMutation {
    const done = mutation.done.then( () => this.store.refreshAfterWrite() );
    return { restoreState: mutation.restoreState, done };
  }

  private setCount( n: number ): void {
    if ( this.countEl !== null ) this.countEl.textContent = String( n );
  }

  private stampUpdated(): void {
    /* c8 ignore next */ // defensive: stampUpdated only runs from renderFromStore past its container-null guard; updatedEl is set/nulled in lockstep with container.
    if ( this.updatedEl === null ) return;
    this.updatedEl.textContent = `updated ${ formatFleetTimestamp( this.nowDateFn(), undefined ) }`;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line — c8 reports ONE location for this "branch" (the identifier itself) where a real conditional carries two, and the factory is called by every test in the suite.
export function createEpicBoardRenderer( opts: EpicBoardRendererOptions ): EpicBoardRenderer {
  return new EpicBoardRendererImpl( opts );
}
