// Layout-Parity Oracle — component-isolation harness for the FOUR-PANE
// INNER ACCORDIONS (task list · holding area · epic board).
//
// A SIBLING of parityHarness.ts, not an extension of it. The sender-card
// harness mounts `.sender-card`s into `#sender-cards-container` and Tier 1
// asserts `count === 2` there; widening that mount to carry these panes would
// make one surface's assertion answer for another, so a failure would no
// longer name the surface that broke. This entry owns its OWN root
// (`#accordion-panes-container`) and its own mount function.
//
// SCOPE — the INVARIANT half only. The 13 inner-accordion contract rows in
// LAYOUT-CONTRACT.md ("The inner accordions — IN the contract") are settled:
// both clients render them with the same class vocabulary and the same chevron
// glyphs. The SECTION-LEVEL chrome (`.section-header` / `.toggle-button` /
// `.collapsed` ∪ `[data-collapsed]`) is NOT mounted or walked here — five
// measured divergences on it are with Rick, and its walker predicate depends on
// how he rules. Building to either predicate now would encode a definition of
// "exactly" that is still open.
//
// Fleet status contributes NO row: it renders a flat table with no inner
// grouping in either client, so it has no inner accordion to contract. Three
// panes mount here, not four — and that difference is a property of the pane.
//
// Exposed test surface:
//   window.__accordionHarnessReady  : true once the mount fn is wired
//   window.__accordionMount(s)      : mounts the three panes; returns pane count

import { groupTasksByOwner }    from "../render/taskListModel";
import { groupHeldRowsByFiler } from "../render/holdingAreaModel";
import { groupTasksByEpic }     from "../render/epicBoardModel";

import { renderTaskListTable }     from "../render/templates/taskListTable";
import { renderHoldingAreaGroups } from "../render/templates/holdingAreaTable";
import { renderEpicBoardTable }    from "../render/templates/epicBoardTable";

import { createTaskListRenderer }    from "../render/TaskListRenderer";
import { createHoldingAreaRenderer } from "../render/HoldingAreaRenderer";
import { createEpicBoardRenderer }   from "../render/EpicBoardRenderer";
import { createEventBusForTesting }  from "../shared/EventBus";

import type { EpicStories }       from "../render/epicBoardModel";
import type { TaskListComposite } from "../render/taskListModel";
import type { TaskMutation }      from "../stores/TaskListStore";

/** The accordion scenario's shape, as read from the canonical fixture. */
interface AccordionScenario {
  app_timezone? : string | null;
  task_list     : { tasks: unknown };
  holding_area  : { tasks: unknown };
  epic_stories? : EpicStories;
}

interface AccordionHarnessWindow {
  __accordionHarnessReady?  : boolean;
  __accordionMount?         : ( scenario: AccordionScenario ) => number;
  __accordionMountRenderers?: ( scenario: AccordionScenario ) => number;
}

/** Fresh pane root, replacing any prior render so re-mounts are idempotent. */
function paneRoot( container: HTMLElement, id: string ): HTMLDivElement {
  const pane = document.createElement( "div" );
  pane.className = "accordion-pane";
  pane.id        = id;
  container.appendChild( pane );
  return pane;
}

function mount( scenario: AccordionScenario ): number {
  const container = document.getElementById( "accordion-panes-container" );
  /* c8 ignore next */ // defensive: the harness page always provides the mount node.
  if ( container === null ) throw new Error( "accordion-harness: #accordion-panes-container not found" );

  container.replaceChildren();

  const zone    = scenario.app_timezone ?? null;
  const stories = scenario.epic_stories ?? {};

  // TASK LIST — collapsedOwners left EMPTY on purpose: the pane's first-load
  // default is every owner group EXPANDED (chevron ▾, aria-expanded="true").
  paneRoot( container, "pane-task-list" ).appendChild(
    renderTaskListTable( groupTasksByOwner( scenario.task_list.tasks ), zone ),
  );

  // HOLDING AREA — one `.holding-area-group` per filer, in model order.
  paneRoot( container, "pane-holding-area" ).appendChild(
    renderHoldingAreaGroups( groupHeldRowsByFiler( scenario.holding_area.tasks ), zone ),
  );

  // EPIC BOARD — `state` left UNDEFINED on purpose: with no recorded viewer
  // choice every group takes epicDefaultExpanded(), which is COLLAPSED for
  // everything except the waiting-on-Rick highlight. The opposite default to
  // the task list's, and that asymmetry is deliberate in both clients.
  paneRoot( container, "pane-epic-board" ).appendChild(
    renderEpicBoardTable( groupTasksByEpic( scenario.task_list.tasks ), undefined, stories, zone ),
  );

  return container.querySelectorAll( ":scope > .accordion-pane" ).length;
}

// ---------------------------------------------------------------------------
// THE RENDERER MOUNT — the layer the CLICK lives at.
//
// 🔴 THE TEMPLATE MOUNT ABOVE CAN NEVER TOGGLE, AND ITS SILENCE IS NOT A
// FINDING. Each pane's accordion is ONE DELEGATED listener installed by the
// RENDERER on its own container (`TaskListRenderer.ts:204`,
// `EpicBoardRenderer.ts:138`) — the templates install nothing. Measured
// 2026-09-06: a click probe against the template mount reported the mux inert
// through two clicks while the real page toggled correctly. A harness that
// enters below the layer a behaviour lives at cannot speak to that behaviour.
//
// So this second mount drives the REAL renderers over the same fixture, which
// makes the click assertions falsifiable FROM THIS TREE rather than only
// against a served page nobody here can mutate.
//
// ⚠️ THE STORES ARE FAKES; THE RENDERERS, THE BUS AND THE WIRING ARE REAL. The
// fake's whole job is to hand back the fixture composite — it makes no decision
// the assertions read, so it cannot be the thing that satisfies them.
// ---------------------------------------------------------------------------

/**
 * A settled mutation handle.
 *
 * ⚠️ UNREACHABLE FROM THIS HARNESS BY DESIGN, and that is why it is pragma'd
 * rather than driven. The write seams exist ONLY to satisfy `TaskListStoreLike`,
 * which the renderers demand at construction; an ACCORDION click never drives a
 * patch or a transition, and the refresh seams — the ones this harness does
 * reach — are exercised by a test rather than assumed. Driving a row control
 * here to chase the last three lines would add a write path this harness has no
 * business having, which is a worse trade than a stated gap.
 */
/* c8 ignore start */ // never reached: the accordion path performs no write; the seam exists for the store interface alone.
function inertMutation(): TaskMutation {
  return { restoreState: () => {}, done: Promise.resolve() };
}
/* c8 ignore stop */

function fakeTaskStore( composite: TaskListComposite ) {
  return {
    composite      : () => composite,
    refresh        : () => Promise.resolve(),
    /* c8 ignore next 2 */ // write seams: required by TaskListStoreLike, never driven by an accordion click.
    patchTask      : () => inertMutation(),
    transitionTask : () => inertMutation(),
  };
}

// ⚠️ A SEPARATE FAKE, BECAUSE THE TWO SEAMS GENUINELY DIFFER. The holding pane's
// `transitionTask` resolves to a RESULT and never rejects (a batch is a loop, and
// a throwing body abandons every row after the first refusal), and it carries
// `refreshAfterWrite` — a read guaranteed to have STARTED after the write, which
// `refresh()` cannot promise. Collapsing them into one fake would erase a
// distinction the seam exists to make.
function fakeHoldingStore( composite: TaskListComposite ) {
  return {
    composite         : () => composite,
    refresh           : () => Promise.resolve(),
    refreshAfterWrite : () => Promise.resolve(),
    /* c8 ignore next */ // write seam: required by HoldingAreaStoreLike, never driven by an accordion click.
    transitionTask    : () => Promise.resolve( { ok: true } ),
  };
}

function compositeOf( tasks: unknown, zone: string | null ): TaskListComposite {
  const rows = Array.isArray( tasks ) ? tasks : [];
  return {
    status       : "ok",
    tasks        : rows,
    count        : rows.length,
    total        : rows.length,
    has_more     : false,
    warnings     : [],
    app_timezone : zone,
  } as unknown as TaskListComposite;
}

function mountRenderers( scenario: AccordionScenario ): number {
  const container = document.getElementById( "accordion-panes-container" );
  /* c8 ignore next */ // defensive: the harness page always provides the mount node.
  if ( container === null ) throw new Error( "accordion-harness: #accordion-panes-container not found" );

  container.replaceChildren();

  const zone    = scenario.app_timezone ?? null;
  const stories = scenario.epic_stories ?? {};
  const bus     = createEventBusForTesting();

  const taskComposite = compositeOf( scenario.task_list.tasks, zone );
  const heldComposite = compositeOf( scenario.holding_area.tasks, zone );

  createTaskListRenderer( { eventBus: bus, stores: { taskList: fakeTaskStore( taskComposite ) } } )
    .mount( paneRoot( container, "pane-task-list" ) );

  createHoldingAreaRenderer( { eventBus: bus, store: fakeHoldingStore( heldComposite ) } )
    .mount( paneRoot( container, "pane-holding-area" ) );

  // The epic board shares the TASK LIST's store on purpose — it never fetches.
  createEpicBoardRenderer( { eventBus: bus, store: fakeTaskStore( taskComposite ),
                             storiesFn: () => stories } )
    .mount( paneRoot( container, "pane-epic-board" ) );

  return container.querySelectorAll( ":scope > .accordion-pane" ).length;
}

const w = window as unknown as AccordionHarnessWindow;
w.__accordionMount          = mount;
w.__accordionMountRenderers = mountRenderers;
w.__accordionHarnessReady   = true;
console.log( "[accordion-harness] ready" );
