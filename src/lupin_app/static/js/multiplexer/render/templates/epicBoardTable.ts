/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Epic-board card — table template (row 87812328).
//
// The DOM half of the epic board, mirroring taskListTable.ts: one <tbody
// class="epic-group"> per section, each a clickable accordion bar plus that
// section's rows, plus the epic's one-line story when there is one. Built via
// document.createElement — NO innerHTML — for the reasons taskListTable.ts
// gives: table-section parsing rules drop stray <tr>/<td> outside a <table>
// ancestor, and createElement is safe-write for store-sourced strings.
//
// SECTION ORDER MIRRORS THE BOARD GENERATOR: ⏳ Waiting on Rick FIRST, then the
// per-epic groups, then 🔴 Drift last.
//
// 🔴 WAITING-ON-RICK IS A HIGHLIGHT, NOT A MOVE. Those rows appear in that
// section AND under their own epic, deliberately — a port that removes them from
// their group empties epics that are not empty. The section's own story line
// says so to the reader, which is why it is not optional decoration.
//
// 🔴 THE DRIFT GROUP RENDERS EVEN WHEN EMPTY, AS A GREEN ALL-CLEAR. A section
// that vanishes when it is satisfied cannot be distinguished from a section that
// failed to render, and drift is exactly the thing a reader needs to be able to
// confirm is ZERO. This is the same defect as a silent empty search result: the
// absence and the failure print the same page.
//
// ⚠️ THE ROW IS THE SHARED ONE, tagged pane "epic-board" so it carries the
// legacy `epic-row` class. Cell-for-cell row identity across the three panes is
// a behavioural requirement Rick asked for — moving between the board and the
// task list must not mean re-parsing the layout.

import type { EpicBoardModel, EpicStories } from "../epicBoardModel";
import { epicTitleLabel, epicStoryText } from "../epicBoardModel";
import {
  EPIC_ON_RICK_KEY,
  EPIC_DRIFT_KEY,
  epicGroupIdSlug,
  epicGroupIsExpanded,
  type EpicGroupState,
} from "../epicBoardCollapse";
import type { TaskItem } from "../taskListModel";
import { rowWidth } from "../rowSchema";
import { renderRowTableHead } from "./rowDisclosure";
import { renderDisclosedRow } from "./taskRowDisclosed";

/** The highlight section's header label. Carbon copy of notifications.js. */
export const EPIC_ON_RICK_LABEL = "⏳ Waiting on Rick";

/**
 * The highlight section's story line. Carbon copy.
 *
 * ⚠️ THIS SENTENCE IS THE ONLY THING TELLING THE READER THE ROWS ARE DUPLICATED.
 * Without it a row appearing twice reads as a rendering defect.
 */
export const EPIC_ON_RICK_STORY = "Highlighted, not moved — each of these also appears under its own epic below.";

/** The drift section's header label when there IS drift. Carbon copy. */
export const EPIC_DRIFT_LABEL = "🔴 Drift — rows carrying no epic";

/** The drift section's header label when there is none. Carbon copy. */
export const EPIC_NO_DRIFT_LABEL = "✅ No drift";

/** The drift section's story line, shown only when there IS drift. Carbon copy. */
export const EPIC_DRIFT_STORY = "Each was either minted without a correlation_key, or had its epic key overwritten. Stamp one.";

interface SectionSpec {
  epicKey    : string;
  label      : string;
  tasks      : ReadonlyArray<TaskItem>;
  extraClass : string;
  story      : string;
}

function renderGroupHeader( spec: SectionSpec, isCollapsed: boolean, idSlug: string ): HTMLTableRowElement {
  const row = document.createElement( "tr" );
  row.className = "epic-group-header" + ( spec.extraClass ? ` ${ spec.extraClass }-header` : "" );
  row.setAttribute( "role", "button" );
  row.setAttribute( "tabindex", "0" );
  row.setAttribute( "aria-expanded", String( !isCollapsed ) );
  row.setAttribute( "aria-controls", idSlug );

  const cell = document.createElement( "td" );
  cell.colSpan = rowWidth();

  const chevron = document.createElement( "span" );
  chevron.className = "epic-group-chevron";
  chevron.setAttribute( "aria-hidden", "true" );
  chevron.textContent = isCollapsed ? "▸" : "▾";
  cell.appendChild( chevron );

  const label = document.createElement( "span" );
  label.className   = "epic-group-label";
  label.textContent = spec.label;
  cell.appendChild( label );

  const count = document.createElement( "span" );
  count.className   = "epic-group-count";
  count.textContent = String( spec.tasks.length );
  cell.appendChild( count );

  row.appendChild( cell );
  return row;
}

/**
 * One accordion section as a `<tbody>`: header bar, the epic's story when there
 * is one, then that section's rows.
 *
 * Ensures:
 *   - a collapsed section carries the `collapsed` class (CSS hides its rows,
 *     the bar stays), chevron ▸ and aria-expanded="false"; expanded ▾ / "true"
 *   - the tbody carries `data-epic` and the id the header's aria-controls names
 *   - the story rides INSIDE the group, so opening an epic answers "what is
 *     this?" in the same gesture that reveals its rows
 */
function renderSection(
  spec            : SectionSpec,
  state           : EpicGroupState | undefined,
  ianaZone        : string | null | undefined,
  reassignTargets : ReadonlyArray<string>,
): HTMLTableSectionElement {
  const isCollapsed = !epicGroupIsExpanded( spec.epicKey, state );
  const idSlug      = epicGroupIdSlug( spec.epicKey );

  const tbody = document.createElement( "tbody" );
  tbody.className = "epic-group"
    + ( spec.extraClass ? ` ${ spec.extraClass }` : "" )
    + ( isCollapsed ? " collapsed" : "" );
  tbody.id = idSlug;
  tbody.dataset.epic = spec.epicKey;

  tbody.appendChild( renderGroupHeader( spec, isCollapsed, idSlug ) );

  if ( spec.story ) {
    const storyRow  = document.createElement( "tr" );
    storyRow.className = "epic-story-row";
    const storyCell = document.createElement( "td" );
    storyCell.colSpan   = rowWidth();
    storyCell.textContent = spec.story;
    storyRow.appendChild( storyCell );
    tbody.appendChild( storyRow );
  }

  for ( const task of spec.tasks ) {
    tbody.appendChild( renderDisclosedRow( task, "epic-board", ianaZone, reassignTargets ) );
  }

  return tbody;
}

/**
 * The board's sections, in the generator's order. Exported so a test can assert
 * the ORDER and the MEMBERSHIP without going through the DOM.
 *
 * Ensures:
 *   - ⏳ Waiting on Rick first, and ONLY when it has rows — an empty highlight
 *     is noise, unlike drift, whose emptiness is the finding
 *   - then one section per epic, in the model's order
 *   - then 🔴 Drift LAST, ALWAYS, even at zero
 */
export function epicBoardSections( model: EpicBoardModel, stories: EpicStories = {} ): SectionSpec[] {
  const sections: SectionSpec[] = [];

  if ( model.onRick.length > 0 ) {
    sections.push( {
      epicKey    : EPIC_ON_RICK_KEY,
      label      : EPIC_ON_RICK_LABEL,
      tasks      : model.onRick,
      extraClass : "epic-group-on-rick",
      story      : EPIC_ON_RICK_STORY,
    } );
  }

  for ( const group of model.groups ) {
    sections.push( {
      epicKey    : group.epicKey,
      label      : epicTitleLabel( group.epicKey, stories ),
      tasks      : group.tasks,
      extraClass : "",
      story      : epicStoryText( group.epicKey, stories ),
    } );
  }

  // 🔴 ALWAYS, even at zero — see the file header. A drift section that
  // disappears when satisfied is indistinguishable from one that failed to
  // render, and zero drift is precisely what a reader comes here to confirm.
  const hasDrift = model.drift.length > 0;
  sections.push( {
    epicKey    : EPIC_DRIFT_KEY,
    label      : hasDrift ? EPIC_DRIFT_LABEL : EPIC_NO_DRIFT_LABEL,
    tasks      : model.drift,
    extraClass : "epic-group-drift",
    story      : hasDrift ? EPIC_DRIFT_STORY : "",
  } );

  return sections;
}

/**
 * Render the epic-grouped model as a `<table>`.
 *
 * Requires:
 *   - model is the { totalCount, onRick, groups, drift } shape from
 *     groupTasksByEpic
 *   - state is the choice map from loadEpicGroupState, or undefined
 *   - stories is the map from `GET /api/epic-stories`, or {} when unfetched
 * Ensures:
 *   - returns an `.epic-board-table` <table>
 *   - the <thead> is the SHARED ROW_SCHEMA header, so its cell count equals
 *     rowWidth() and cannot drift from the rows'
 *   - one <tbody class="epic-group"> per section, in the generator's order
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the multi-line exported function-declaration line; c8 reports ONE location for it where a real conditional carries two.
export function renderEpicBoardTable(
  model           : EpicBoardModel,
  state           : EpicGroupState | undefined,
  stories         : EpicStories = {},
  ianaZone        : string | null | undefined = undefined,
  reassignTargets : ReadonlyArray<string> = [],
): HTMLTableElement {
  const table = document.createElement( "table" );
  table.className = "epic-board-table";
  table.appendChild( renderRowTableHead() );

  for ( const spec of epicBoardSections( model, stories ) ) {
    table.appendChild( renderSection( spec, state, ianaZone, reassignTargets ) );
  }

  return table;
}
