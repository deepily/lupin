/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Finished Tasks — the DOM builders (row 470b7509, multiplexer port).
//
// Three builders, all pure with respect to state: the controls bar (pills +
// window slider), the rows table, and the one-line sentinel. The renderer
// decides WHICH of these to paint; this file decides what each one looks like.
//
// 🔴 CLASS NAMES ARE SHARED WITH THE LEGACY PANE ON PURPOSE, AND THAT IS NOT
// THE CODE REUSE RICK RULED AGAINST (row 87812328). `css/task-list.css` is
// linked by BOTH clients (multiplexer.html:37, notifications.html:17), and
// matching class names are how the Layout-Parity Oracle measures one shape
// across the two — the same reason templates/sectionHeader.ts copies legacy's
// `.section-header` contract verbatim. No JS or TS module crosses the boundary;
// a stylesheet both pages already load is not a module.
//
// ⚠️ EVERY CONTROL BELOW BELONGS IN `.section-content`, NEVER IN
// `.section-header`. The header collapses the section on click, and
// `headerClickShouldCollapse` exempts only controls sitting in the header's own
// action slot — a slider dropped into the header would collapse the panel on
// every drag. The renderer places this bar inside the body, and a test asserts
// both directions rather than trusting this comment.

import { html } from "../html";
import {
  FINISHED_STATUSES,
  FINISHED_UNMEASURED,
  FINISHED_WINDOW_MIN_DAYS,
  FINISHED_WINDOW_MAX_DAYS,
  actorPersona,
  relativeAge,
  transitionTarget,
  type FinishedTaskEvent,
} from "../finishedTasksModel";
import { taskStatusClass } from "../taskListModel";
import { ownLookup } from "../../shared/ownLookup";

/** Pill face per status: glyph, label, tooltip. One table, so a fourth terminal
 *  status is one row here rather than three edits scattered through a builder. */
interface PillFace { icon: string; label: string; title: string }

const PILL_FACES: Readonly<Record<string, PillFace>> = {
  done     : { icon: "✅", label: "Done",      title: "Rows that reached done. The only success terminal — there is no separate 'fixed' status." },
  dropped  : { icon: "🗑️", label: "Dropped",   title: "Rows closed as dropped." },
  wont_fix : { icon: "🚫", label: "Won't-fix", title: "Rows closed as won't-fix. Terminal, and deliberately NOT part of the default view." },
};

/**
 * The id a status's pill carries.
 *
 * `wont_fix` renders as `wont-fix` because the legacy pane's id is
 * `finished-pill-wont-fix`, and observational equivalence includes the selector
 * a person or an E2E reaches for.
 */
export function pillIdFor( status: string ): string {
  return `finished-pill-${ status.replace( /_/g, "-" ) }`;
}

export interface FinishedControlsOptions {
  /** Currently-lit statuses (POSITIVE polarity — these are the SHOWN ones). */
  shown      : ReadonlyArray<string>;
  /** Slider position, in days. */
  windowDays : number;
}

/**
 * The controls bar: three pills, then the window slider.
 *
 * Ensures:
 *   - one pill per FINISHED_STATUSES entry, in that order, each carrying
 *     `data-status` and `aria-pressed`
 *   - `aria-pressed="true"` means SHOWN — positive polarity, the same sense the
 *     persisted key uses, so there is no point in this feature where the DOM
 *     and the stored value disagree about which way the flag points
 *   - every pill's count starts at the em dash; a pill whose status was never
 *     successfully measured KEEPS it rather than showing 0
 *   - a zero-count pill is DIMMED, NOT HIDDEN, and stays clickable. "Zero is a
 *     claim, not a default": a pill that vanishes at zero turns "nothing was
 *     refused today" into "this feature does not exist", and makes the control
 *     bar change width as the day goes on
 *   - the slider is a WIDTH control (Rick's keypress ruling, 2026-09-07): it
 *     widens how far back the pane looks. It is NOT a day stepper, and this
 *     function deliberately builds no stepper beside it
 */
export function renderFinishedControls( opts: FinishedControlsOptions ): HTMLElement {
  const bar = document.createElement( "div" );
  bar.className = "finished-tasks-controls";
  bar.setAttribute( "data-testid", "multiplexer-finished-tasks-controls" );

  const pills = document.createElement( "span" );
  pills.className = "finished-tasks-pills";
  pills.setAttribute( "role", "group" );
  pills.setAttribute( "aria-label", "Terminal statuses to show" );

  for ( const status of FINISHED_STATUSES ) {
    // Read through the shared refusal, NOT `PILL_FACES[ status ]`. A bare index
    // answers for INHERITED keys, so a status named `toString` or `constructor`
    // would return a truthy Function, the `??` would not fire, and the pill would
    // render from a prototype member. FINISHED_STATUSES is a module constant today
    // so nothing can reach it — but that is a fact about the CALLER, not this site.
    const face = ownLookup<PillFace>( PILL_FACES, status, { icon: "•", label: status, title: status } );
    const pill = document.createElement( "button" );
    pill.type      = "button";
    pill.className = "finished-pill";
    pill.id        = pillIdFor( status );
    pill.setAttribute( "data-testid", `multiplexer-${ pillIdFor( status ) }` );
    pill.setAttribute( "data-status", status );
    pill.setAttribute( "aria-pressed", opts.shown.includes( status ) ? "true" : "false" );
    pill.title = face.title;

    const badge = document.createElement( "span" );
    badge.className = "finished-pill-count";
    badge.setAttribute( "data-testid", `multiplexer-finished-pill-count-${ status }` );
    badge.textContent = FINISHED_UNMEASURED;

    pill.append( `${ face.icon } ${ face.label } `, badge );
    pills.appendChild( pill );
  }
  bar.appendChild( pills );

  const field = document.createElement( "span" );
  field.className = "flow-ratio-field finished-tasks-window";

  const label  = document.createElement( "label" );
  label.setAttribute( "for", "finished-tasks-window" );
  const output = document.createElement( "output" );
  output.id = "finished-tasks-window-value";
  output.setAttribute( "data-testid", "multiplexer-finished-tasks-window-value" );
  output.textContent = `${ opts.windowDays }d`;
  label.append( "Window ", output );

  const slider = document.createElement( "input" );
  slider.type  = "range";
  slider.id    = "finished-tasks-window";
  slider.setAttribute( "data-testid", "multiplexer-finished-tasks-window" );
  slider.min   = String( FINISHED_WINDOW_MIN_DAYS );
  slider.max   = String( FINISHED_WINDOW_MAX_DAYS );
  slider.step  = "1";
  slider.value = String( opts.windowDays );
  slider.title = "Days back from now. Widens how far back this pane looks — it does not step back one day at a time.";

  field.append( label, slider );
  bar.appendChild( field );
  return bar;
}

/**
 * The rows table: WHEN / WHAT / WHO / WHY. Four columns, because at-a-glance
 * beats completeness.
 *
 * Ensures:
 *   - WHEN is RELATIVE with the absolute instant on hover — the pane's premise
 *     is recency, and relative saves the reader a subtraction
 *   - WHAT is the item title, which is the whole reason the event projection
 *     carries one
 *   - WHO is the persona only; the raw actor is "persona sessionid" and the
 *     session id is noise at a glance
 *   - WHY is clamped to one line by the sheet, with the full text on hover —
 *     `->done` events do carry reasons, and some are long enough to bury a row
 *   - each row carries `data-status` and the shared `task-status-*` class, so a
 *     terminal row is tinted the same way the task list tints it
 *   - every interpolation goes through `html`, which builds text nodes rather
 *     than concatenating strings — so a title or a reason has no seam to escape
 *     through, and there is no hand-written escaper to get wrong
 */
export function renderFinishedTasksTable(
  rows  : ReadonlyArray<FinishedTaskEvent>,
  nowMs : number,
): DocumentFragment {
  const body = rows.map( ( event ) => {
    const status = transitionTarget( event.transition );
    // 🔴 THE CLASS STRING IS COMPOSED HERE, NOT IN THE ATTRIBUTE, AND THAT IS A
    // REAL CONSTRAINT OF `html` RATHER THAN A STYLE CHOICE. Its attribute
    // interpolation only fires when the hole is the WHOLE attribute value —
    // `class="${ x }"` works, `class="a ${ x }"` does NOT, and it fails
    // SILENTLY: the second form renders `class="a <!--lupin-html-child-0-->"`,
    // so the class is simply absent and nothing throws. Measured, both forms,
    // and pinned by test_a_prefixed_attribute_hole_is_not_silently_dropped.
    const rowClass = `finished-task-row ${ taskStatusClass( status ) }`;
    return html`
      <tr class="${ rowClass }"
          data-testid="multiplexer-finished-task-row" data-status="${ status }">
        <td class="finished-when" title="${ event.ts ?? "" }">${ relativeAge( event.ts, nowMs ) }</td>
        <td class="finished-what">${ event.title ?? "(untitled)" }</td>
        <td class="finished-who">${ actorPersona( event.actor ) }</td>
        <td class="finished-why" title="${ event.reason ?? "" }">${ event.reason ?? "" }</td>
      </tr>` as DocumentFragment;
  } );

  return html`
    <table class="finished-tasks-table" data-testid="multiplexer-finished-tasks-table">
      <thead><tr><th>When</th><th>What</th><th>Who</th><th>Why</th></tr></thead>
      <tbody>${ body }</tbody>
    </table>` as DocumentFragment;
}

/**
 * A one-line sentinel.
 *
 * ⚠️ `variant` becomes the testid suffix, so each of the pane's states is
 * SEPARATELY selectable. Six states all rendering one testid would be six
 * states a test cannot tell apart — the same collapsing this pane exists to
 * avoid, one level down in the test surface.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line (return-type erasure).
export function renderFinishedSentinel( variant: string, text: string ): HTMLElement {
  const el = document.createElement( "div" );
  el.className = variant === "partial" ? "finished-tasks-partial" : "finished-tasks-empty";
  el.setAttribute( "data-testid", `multiplexer-finished-tasks-${ variant }` );
  el.textContent = text;
  return el;
}
