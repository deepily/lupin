/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The row's INTERACTIVE content — detail affordance and the actions controls.
//
// 🔴 WHY THIS FILE EXISTS: THE DISCLOSED ROW COULD ONLY CARRY STRINGS.
//
// `renderControlsRow` renders each disclosed field as a label span plus a VALUE
// span built from `textContent`. That is right for `blocked`, `chase`,
// `accountable`, `filer` and `project`, which really are formatted strings. It
// is WRONG for the two fields on line 3: in the JS card `parts.detail.html` and
// `parts.actions.html` are MARKUP — an interactive 📄 affordance and the whole
// priority / owner / verb control group. Measured at notifications.js:10086-10089,
// where `detail` takes `detailHtml` and `actions` takes `_taskActionsCell( task )`.
//
// ⚠️ So a disclosed row built from strings alone renders the word "—" where the
// legacy card renders NINE CONTROLS, and it does not look broken — the row is
// the right shape, the labels are right, and the controls are simply not there.
//
// The content builders live HERE rather than in taskListTable.ts so both the
// flat cell (`renderActionsCell` wraps this in a <td>) and the disclosed field
// (`renderDisclosedRow` drops it into the value span) can use ONE implementation.
// Two derivations of one control group agree until somebody edits one of them.
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §5a
// Source of truth: notifications.js `_rowFieldParts` / `_taskActionsCell`.

import {
  EDITABLE_PRIORITIES,
  taskBodyIsEmpty,
  taskIdLabel,
  taskPriorityClass,
  type TaskItem,
} from "../taskListModel";
import { verbLegality } from "../taskVerbs";

/**
 * The 📄 detail affordance — the CONTENT of the detail field, without a cell.
 *
 * Requires:
 *   - task is a TaskItem; `body` may be absent, empty or whitespace
 *
 * Ensures:
 *   - an EMPTY body → `.task-detail-emoji.task-detail-empty`, aria-disabled,
 *     title "No detail", and NO role/tabindex — there is nothing to open
 *   - a non-empty body → role="button", tabindex="0", title "View detail", and
 *     the body + id on datasets so the renderer's delegated handler can open it
 *   - the glyph is 📄 in both branches
 */
export function renderDetailContent( task: TaskItem ): HTMLSpanElement {
  const emoji = document.createElement( "span" );
  emoji.textContent = "📄";
  if ( taskBodyIsEmpty( task ) ) {
    emoji.className = "task-detail-emoji task-detail-empty";
    emoji.setAttribute( "aria-disabled", "true" );
    emoji.setAttribute( "title", "No detail" );
  } else {
    emoji.className = "task-detail-emoji";
    emoji.setAttribute( "role", "button" );
    emoji.setAttribute( "tabindex", "0" );
    emoji.setAttribute( "title", "View detail" );
    // In this branch taskBodyIsEmpty(task) is false → body is a non-empty string.
    emoji.dataset.taskBody = task.body as string;
    emoji.dataset.taskId   = taskIdLabel( task );
  }
  return emoji;
}

/**
 * The verb select + shared reason input + Submit, given the row's status.
 *
 * The legality lives in `taskVerbs.verbLegality` and NOT here. Two derivations
 * of one rule agree until the day they do not, and the day they do not the cell
 * offers a move the server refuses — which reads to the operator as the board
 * being broken rather than as the move being illegal.
 *
 * Requires:
 *   - task carries `id` (possibly absent) and `status` (possibly absent)
 * Ensures:
 *   - returns a fragment of exactly four controls — select, 🎤 mic, reason input,
 *     Submit — each carrying `data-task-id`
 *   - the select leads with an un-chosen "Choose an action…" placeholder, then
 *     the five verbs in `TASK_VERBS` order — greyed, never removed, when illegal
 *   - a greyed option carries the reason in its OWN label plus `aria-disabled`
 *     and `task-action-disabled` (a disabled <option> has no tooltip to put it in)
 *   - a terminal row disables the select, the mic, the reason box and Submit themselves
 */
export function renderVerbControl( task: TaskItem ): DocumentFragment {
  const frag = document.createDocumentFragment();
  const id   = task.id ?? "";
  const legality = verbLegality( task.status );
  // A row is terminal exactly when nothing is legal on it. Derived from the same
  // table the options are, rather than re-asking the status a second time.
  const isTerminal = legality.every( ( e ) => !e.enabled );

  const select = document.createElement( "select" );
  select.className = "task-verb-select";
  select.setAttribute( "aria-label", "Action" );
  select.dataset.taskId = id;

  const placeholder = document.createElement( "option" );
  placeholder.value = "";
  placeholder.textContent = "Choose an action…";
  placeholder.selected = true;
  select.appendChild( placeholder );

  for ( const entry of legality ) {
    const opt = document.createElement( "option" );
    opt.value = entry.verb;
    if ( entry.enabled ) {
      opt.textContent = entry.label;
    } else {
      opt.textContent = `${entry.label} — ${entry.why}`;
      opt.disabled = true;
      opt.className = "task-action-disabled";
      opt.setAttribute( "aria-disabled", "true" );
    }
    select.appendChild( opt );
  }
  frag.appendChild( select );

  // 🎤 THE MIC SITS IMMEDIATELY BEFORE THE FIELD IT FILLS (legacy `_taskActionsCell`,
  // Phase 2 A8 T7). It carries `data-task-id` for the row error stripe only: the
  // controller resolves the box it writes into by SCOPE, never by id, because a row
  // shown in two panes carries one id twice.
  const mic = document.createElement( "button" );
  mic.type = "button";
  mic.className = "stt-button task-reason-stt";
  mic.textContent = "🎤";
  mic.setAttribute( "title", REASON_MIC_TITLE );
  mic.setAttribute( "aria-label", "Dictate reason" );
  mic.dataset.taskId = id;
  frag.appendChild( mic );

  const reasonInput = document.createElement( "input" );
  reasonInput.type = "text";
  reasonInput.className = "task-action-input task-reason-input";
  reasonInput.setAttribute( "placeholder", "reason…" );
  reasonInput.setAttribute( "aria-label", "Reason" );
  reasonInput.dataset.taskId = id;
  frag.appendChild( reasonInput );

  const submitBtn = document.createElement( "button" );
  submitBtn.type = "button";
  submitBtn.className = "task-action-btn task-submit-button";
  submitBtn.textContent = "Submit";
  submitBtn.dataset.taskId = id;
  frag.appendChild( submitBtn );

  if ( isTerminal ) {
    for ( const el of [ select, mic, reasonInput, submitBtn ] ) {
      el.disabled = true;
      el.setAttribute( "aria-disabled", "true" );
    }
  }

  return frag;
}

/** The Update button's tooltip while the chosen priority equals the painted one. Carbon copy. */
export const PRIORITY_UPDATE_IDLE_TITLE = "Choose a different priority to enable";

/** The row mic's tooltip. Carbon copy of notifications.js `_taskActionsCell`. */
export const REASON_MIC_TITLE = "Dictate the reason (click to record, click again to stop)";

/** The page-wide datalist the reason box borrows while Drop is chosen. Carbon copy of notifications.html. */
export const DROP_REASON_DATALIST_ID = "task-drop-reason-suggestions";

/** The four canned drop reasons, in the legacy markup's order. */
export const DROP_REASON_SUGGESTIONS: ReadonlyArray<string> = Object.freeze( [
  "Overtaken by events",
  "Duplicate of an existing row",
  "Filed against the wrong repo",
  "No longer reproducible",
] );

/**
 * Put the ONE drop-reason datalist on the page, if it is not there already.
 *
 * ⚠️ ONE PER DOCUMENT, NOT ONE PER ROW. Every row's reason box refers to it by id,
 * and a second copy with the same id would make that reference ambiguous. Both panes
 * call this at mount, so it is idempotent by construction rather than by care.
 *
 * 🔴 LEGACY PAINTS THIS LIST AND NOTHING READS IT. The per-verb `drop reason` box
 * carried `list=` until 9298715c folded five boxes into one, and the attribute did
 * not survive the fold. Mr. Radio ruled 2026-09-16 that the multiplexer attaches it
 * while Drop is chosen — see TaskRowController.handleVerbSelectChange.
 *
 * Ensures:
 *   - exactly one `datalist#task-drop-reason-suggestions` under `doc.body`
 *   - its options are DROP_REASON_SUGGESTIONS, in order
 *   - returns that element
 */
export function ensureDropReasonDatalist( doc: Document ): HTMLDataListElement {
  const existing = doc.getElementById( DROP_REASON_DATALIST_ID );
  if ( existing !== null ) return existing as HTMLDataListElement;
  const list = doc.createElement( "datalist" );
  list.id = DROP_REASON_DATALIST_ID;
  for ( const reason of DROP_REASON_SUGGESTIONS ) {
    const opt = doc.createElement( "option" );
    opt.value = reason;
    list.appendChild( opt );
  }
  doc.body.appendChild( list );
  return list;
}

/**
 * The staged priority edit: a select plus the Update button it arms.
 *
 * 🔴 UPDATE STARTS DISABLED AND STAYS DISABLED UNTIL THE VALUE MOVES (Rick, on the
 * classic page: "the update button would only be enabled if I had chosen a different
 * value to update"). The comparison is against `data-original`, the priority the row
 * was PAINTED with, because the row repaints on every poll and state held anywhere but
 * the element does not survive that.
 *
 * Requires:
 *   - task carries `id` (possibly absent) and `priority` (possibly absent)
 * Ensures:
 *   - the select carries `data-task-id` and `data-original` (the trimmed stored value)
 *   - one option per EDITABLE_PRIORITIES entry, the current one selected; an unset row
 *     leads with a selected "—" option, and an unrecognised stored value gets its own
 *     leading selected option rather than being shown as something it is not
 *   - the Update button renders disabled with aria-disabled and the idle tooltip
 *   - a terminal row disables the select as well
 *   - the heat class from taskPriorityClass tints the select
 */
export function renderPriorityControl( task: TaskItem ): DocumentFragment {
  const frag    = document.createDocumentFragment();
  const id      = task.id ?? "";
  const current = ( task.priority ?? "" ).trim();
  const isTerminal = verbLegality( task.status ).every( ( e ) => !e.enabled );

  const select    = document.createElement( "select" );
  const prioClass = taskPriorityClass( task.priority );
  select.className = "task-priority-select" + ( prioClass ? ` ${prioClass}` : "" );
  select.setAttribute( "aria-label", "Set priority" );
  select.dataset.taskId   = id;
  select.dataset.original = current;

  const values = current === "" || EDITABLE_PRIORITIES.includes( current )
    ? EDITABLE_PRIORITIES
    : [ current, ...EDITABLE_PRIORITIES ];
  if ( current === "" ) {
    const blank = document.createElement( "option" );
    blank.value = "";
    blank.textContent = "—";
    blank.selected = true;
    select.appendChild( blank );
  }
  for ( const p of values ) {
    const opt = document.createElement( "option" );
    opt.value = p;
    opt.textContent = p;
    if ( p === current ) opt.selected = true;
    select.appendChild( opt );
  }
  frag.appendChild( select );

  const update = document.createElement( "button" );
  update.type = "button";
  update.className = "task-action-btn task-priority-update";
  update.textContent = "Update";
  update.dataset.taskId = id;
  update.disabled = true;
  update.setAttribute( "aria-disabled", "true" );
  update.setAttribute( "title", PRIORITY_UPDATE_IDLE_TITLE );
  frag.appendChild( update );

  if ( isTerminal ) {
    select.disabled = true;
    select.setAttribute( "aria-disabled", "true" );
  }
  return frag;
}

/**
 * The actions control group — the CONTENT of the actions field, without a cell.
 *
 * `.task-priority-select` is a STAGED edit here, as it is on the classic page
 * (`notifications.js`, symbol `_priorityCell`): the select is paired with a
 * `.task-priority-update` button that stays disabled until the value differs from
 * `data-original`, and the PATCH is sent only on the click (parity A-2 #0, Phase 2
 * A8 T9 — the lead wins). Until A-2 #0 the multiplexer committed on `change`.
 *
 * Guard: src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts
 *
 * Ensures:
 *   - `.task-priority-select` + `.task-priority-update` — see renderPriorityControl
 *   - `.task-owner-select` — reassignment roster (active personas, INCLUDING the
 *     'Sam' overflow persona — Q5); the current owner is pre-selected (prepended
 *     if not already a target so the select reflects reality); an unassigned task
 *     leads with a disabled "(unassigned)" placeholder
 *   - `.task-verb-select` + `.task-reason-input` + `.task-submit-button`
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderActionsContent(
  task            : TaskItem,
  reassignTargets : ReadonlyArray<string>,
): DocumentFragment {
  const frag = document.createDocumentFragment();

  frag.appendChild( renderPriorityControl( task ) );

  // Owner-reassignment select. The current owner is pre-selected; an unassigned
  // task gets a disabled placeholder so the control isn't blank.
  const ownerSelect = document.createElement( "select" );
  ownerSelect.className = "task-owner-select";
  ownerSelect.setAttribute( "aria-label", "Reassign owner" );
  const currentOwner = task.owner_persona ?? "";
  if ( !currentOwner ) {
    const placeholder = document.createElement( "option" );
    placeholder.value = "";
    placeholder.textContent = "(unassigned)";
    placeholder.disabled = true;
    placeholder.selected = true;
    ownerSelect.appendChild( placeholder );
  }
  const seen = new Set<string>();
  const ordered = currentOwner ? [ currentOwner, ...reassignTargets ] : reassignTargets;
  for ( const persona of ordered ) {
    if ( !persona || seen.has( persona ) ) continue;
    seen.add( persona );
    const opt = document.createElement( "option" );
    opt.value = persona;
    opt.textContent = persona;
    if ( persona === currentOwner ) opt.selected = true;
    ownerSelect.appendChild( opt );
  }
  frag.appendChild( ownerSelect );

  // The one-select row control (2026.09.02). What stood here was a single verb —
  // a bare "drop reason…" box and a Drop button — because Drop was the only
  // transition this card had ever offered. Rick's ruling brings the other four
  // with it: one select carrying all five verbs, one shared reason field, one
  // Submit. The date input is NOT built here; the renderer inserts it on the
  // verb change, for the two verbs that ask for a date, so a row shows a date
  // box only when a date is the thing being asked for.
  frag.appendChild( renderVerbControl( task ) );

  return frag;
}
