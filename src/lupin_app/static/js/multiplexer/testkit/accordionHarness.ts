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

import type { EpicStories } from "../render/epicBoardModel";

/** The accordion scenario's shape, as read from the canonical fixture. */
interface AccordionScenario {
  app_timezone? : string | null;
  task_list     : { tasks: unknown };
  holding_area  : { tasks: unknown };
  epic_stories? : EpicStories;
}

interface AccordionHarnessWindow {
  __accordionHarnessReady? : boolean;
  __accordionMount?        : ( scenario: AccordionScenario ) => number;
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

const w = window as unknown as AccordionHarnessWindow;
w.__accordionMount        = mount;
w.__accordionHarnessReady = true;
console.log( "[accordion-harness] ready" );
