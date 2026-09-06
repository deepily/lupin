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

import type { EventBus } from "../shared/EventBus";
import type { StoreTaskListChangedPayload } from "../shared/types";
import type { TaskListComposite, TaskItem } from "./taskListModel";
import { isOpenStatus } from "./taskListModel";
import { formatFleetTimestamp } from "./fleetModel";
import { groupTasksByEpic, type EpicStories } from "./epicBoardModel";
import { loadEpicGroupState, toggleEpicCollapsed } from "./epicBoardCollapse";
import { renderEpicBoardTable } from "./templates/epicBoardTable";
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
}

export interface EpicBoardRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  forceRenderForTesting(): void;
}

export interface EpicBoardRendererOptions {
  eventBus   : EventBus;
  /** The TASK LIST's store — shared on purpose; this pane never fetches. */
  store      : EpicBoardTaskStoreLike;
  /** The memoized `GET /api/epic-stories` map, or a fn returning it. */
  storiesFn? : () => EpicStories;
  nowDateFn? : () => Date;
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
  private readonly unsubscribers: Array<() => void> = [];

  private root      : HTMLElement | null = null;
  private container : HTMLElement | null = null;
  private countEl   : HTMLElement | null = null;
  private updatedEl : HTMLElement | null = null;
  private header    : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted   = false;

  constructor( opts: EpicBoardRendererOptions ) {
    this.bus   = opts.eventBus;
    this.store = opts.store;
    /* c8 ignore next */ // production-default fallback: an unwired stories source is an empty map (de-slugged names, no story rows).
    this.storiesFn = opts.storiesFn ?? ( () => ( {} ) );
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
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

    const header = renderSectionHeader( {
      icon    : "🗺️",
      title   : "Epic Board",
      testid  : "multiplexer-epic-board-header",
      actions : [ refreshBtn, this.updatedEl ],
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
    this.container.addEventListener( "click", ( e ) => this.handleAccordionActivate( e.target ) );
    this.container.addEventListener( "keydown", ( e ) => {
      const ke = e as KeyboardEvent;
      if ( ke.key !== "Enter" && ke.key !== " " && ke.key !== "Spacebar" ) return;
      if ( !( e.target as Element ).closest( ".epic-group-header" ) ) return;
      e.preventDefault();   // Space must act, not scroll the page
      this.handleAccordionActivate( e.target );
    } );

    root.replaceChildren( header.header, this.container );
    this.collapseOff = wireSectionCollapse( root, header );

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
  // Dispatch (the four states — the SAME four the task list carries, so the two
  // panes degrade identically)
  // -------------------------------------------------------------------------

  private renderFromStore( stampUpdated: boolean ): void {
    /* c8 ignore next */ // defensive: subscriptions detach in unmount BEFORE container is nulled.
    if ( this.container === null ) return;
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

    this.container.replaceChildren(
      renderEpicBoardTable( model, loadEpicGroupState(), this.storiesFn() ) );

    if ( stampUpdated ) this.stampUpdated();
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
    const nowCollapsed = toggleEpicCollapsed( epicKey );
    tbody.classList.toggle( "collapsed", nowCollapsed );
    header.setAttribute( "aria-expanded", String( !nowCollapsed ) );

    const chevron = tbody.querySelector( ".epic-group-chevron" );
    if ( chevron !== null ) chevron.textContent = nowCollapsed ? "▸" : "▾";
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
