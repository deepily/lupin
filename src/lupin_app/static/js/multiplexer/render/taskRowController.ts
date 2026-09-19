/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The shared row-control dispatcher — every click, change and key a task row's
// controls produce, for every pane that paints the shared row (parity A-2 #0).
//
// 🔴 WHY THIS FILE EXISTS: THE ROW IS SHARED AND ITS HANDLERS WERE NOT.
// `taskRowDisclosed.renderDisclosedRow` paints one row for the Task List, the
// Holding Area and the Epic Board. Until A-2 #0 only TaskListRenderer wired the
// controls that row carries; the Holding Area painted the verbs, the ⋯ toggle,
// the 📄 and the id cell and had no listener for any of them
// (`HoldingAreaRenderer.ts`, click listener for the two batch buttons only).
// Legacy wires the same handlers into each pane by calling one function three
// times (`notifications.js` `_wireVerbSelects`, `_handleRowControlClick`); this is
// the multiplexer's one function.
//
// ⚠️ A PANE KEEPS WHAT IS ITS OWN. The accordion toggle, the request chips and
// the batch buttons are pane behaviour and stay in the pane: `handleClick`
// returns false for anything that is not a row control so the pane can route it.
//
// ⚠️ THE WRITE SEAM IS THE TASK LIST STORE'S SHAPE. `TaskRowWriter` returns a
// `TaskMutation` — an optimistic edit's `restoreState` plus a `done` promise.
// A pane whose store is not optimistic adapts to it with a no-op restore.
//
// Sources: notifications.js `_handleRowControlClick`, `_handleReasonSttClick`,
// `_handlePrioritySelectChange`, `_handlePriorityUpdateClick`,
// `_handleVerbSelectChange`, `_handleTaskSubmitClick`; ported through
// TaskListRenderer, where the pre-A-2 #0 comments below were first written.

import { ApiError } from "../api/ApiClient";
import { recordingManager, type RecordingManagerStartOptions } from "../audio/recordingManager";
import type { TaskMutation, TaskPatchFields } from "../stores/TaskListStore";
import { insertTranscriptionText } from "./insertTranscriptionText";
import {
  transitionExtras,
  type TransitionExtras,
  verbDateComplaint,
  verbLabel,
  verbNeeds,
  verbReasonComplaint,
} from "./taskVerbs";
import { renderRowError as paintRowError, toggleDisclosure } from "./templates/rowDisclosure";
import type { OperatorStateHandlers } from "./operatorState";
import {
  DROP_REASON_DATALIST_ID,
  PRIORITY_UPDATE_IDLE_TITLE,
  ensureDropReasonDatalist,
} from "./templates/taskRowControls";

/** The store calls a row control makes. Both return an optimistic-mutation handle. */
export interface TaskRowWriter {
  patchTask( id: string, fields: TaskPatchFields ): TaskMutation;
  transitionTask( id: string, toStatus: string, extras: TransitionExtras ): TaskMutation;
}

/** The slice of `recordingManager` the row mic drives. */
export interface TaskRowRecorderLike {
  startRecording( opts: RecordingManagerStartOptions ): Promise<void>;
  stopRecording( contextId: string ): Promise<void>;
  getActiveContextId(): string | null;
}

export interface TaskRowControllerOptions {
  /** The pane's persistent container — every lookup and every stripe is scoped to it. */
  container : HTMLElement;
  writer    : TaskRowWriter;
  /** The prefix on the one console line a scope-less control produces, e.g. "[task-list]". */
  logLabel  : string;
  /** Test injection — production uses the `recordingManager` singleton. */
  recorder?     : TaskRowRecorderLike;
  /** The bearer token the dictation upload carries. */
  getAuthToken? : () => string | null;
  /** Test injection — the timer for the ID click-to-copy flash. Defaults to `setTimeout`. */
  setTimeoutFn? : ( cb: () => void, ms: number ) => unknown;
  /** Runs after a transition settles as a success; `gone` is true for the 404. */
  onTransitionSettled? : ( id: string, toStatus: string, gone: boolean ) => void;
}

// How long the transient "copied" flash stays on the ID cell (F1 2026.07.01).
// Mirrors the notifications.js checkmark dwell (~1.2s).
export const COPIED_FLASH_MS = 1200;

/** The stripe a mic shows when its row has no reason box. Carbon copy of `_handleReasonSttClick`. */
export const MIC_NO_REASON_BOX = "No reason box found beside this mic — nothing to dictate into.";

/** The recording-context id one row's mic records under. */
export function reasonMicContextId( id: string ): string {
  return `task-reason-${id}`;
}

export class TaskRowController {
  private readonly container : HTMLElement;
  private readonly writer    : TaskRowWriter;
  private readonly logLabel  : string;
  private readonly recorder  : TaskRowRecorderLike;
  private readonly getAuthToken : () => string | null;
  private readonly setTimeoutFn : ( cb: () => void, ms: number ) => unknown;
  private readonly onTransitionSettled : ( id: string, toStatus: string, gone: boolean ) => void;

  // Keys of in-flight edits ("<id>:priority" / "<id>:owner" / "<id>:<verb>") so a
  // rapid second activation on the same control+row is a no-op until the first
  // settles. Mirrors JobsPaneRenderer.deleteInFlight.
  private readonly editInFlight : Set<string> = new Set();

  // Recording contexts whose stop has been asked for and whose transcription has
  // not arrived. A click in that window is ignored, as legacy ignores one while
  // `recordingManager.isProcessing()`.
  private readonly micProcessing : Set<string> = new Set();

  // The document-level Esc listener for the body overlay (null when closed).
  private overlayKeyListener : ( ( e: KeyboardEvent ) => void ) | null = null;

  constructor( opts: TaskRowControllerOptions ) {
    this.container = opts.container;
    this.writer    = opts.writer;
    this.logLabel  = opts.logLabel;
    /* c8 ignore next */ // production-default fallback: the recordingManager singleton; tests inject a fake recorder.
    this.recorder  = opts.recorder ?? recordingManager;
    this.getAuthToken = opts.getAuthToken ?? ( () => null );
    /* c8 ignore next */ // production-default fallback: `setTimeout` is the runtime timer; tests inject a controllable fn.
    this.setTimeoutFn = opts.setTimeoutFn ?? ( ( cb, ms ) => globalThis.setTimeout( cb, ms ) );
    this.onTransitionSettled = opts.onTransitionSettled ?? ( () => {} );
    ensureDropReasonDatalist( opts.container.ownerDocument );
  }

  /**
   * The handlers operator-state restore replays a poll's captured work through (A-1a).
   *
   * Ensures:
   *   - `onVerbChange` re-shapes the row for the restored verb (placeholder, date box, list=)
   *   - `onPriorityChange` only re-arms Update — it never commits, which is what makes a
   *     pending priority safe to restore on every poll
   *   - `renderRowError` re-shows a refusal in this pane
   */
  operatorStateHandlers(): OperatorStateHandlers {
    return {
      onVerbChange     : ( select ) => this.handleVerbSelectChange( select ),
      onPriorityChange : ( select ) => this.handlePrioritySelectChange( select ),
      renderRowError   : ( id, message ) => this.renderRowError( id, message ),
    };
  }

  /** Close the body overlay, if one is open. Call from the pane's unmount. */
  dispose(): void {
    this.dismissTaskBodyOverlay();
  }

  // -------------------------------------------------------------------------
  // Dispatch
  // -------------------------------------------------------------------------

  /**
   * A click inside the pane → the row control it landed on.
   *
   * Ensures:
   *   - returns true when a row control consumed the click, so the pane does not
   *     also route it to its own accordion
   *   - the 📄 is tried first, then the mic, Update, Submit, the ⋯ toggle and the
   *     id cell; a dimmed 📄 consumes the click and does nothing
   */
  handleClick( target: EventTarget | null ): boolean {
    const el = target as Element;
    const emoji = el.closest( ".task-detail-emoji" );
    if ( emoji !== null ) {
      if ( !emoji.classList.contains( "task-detail-empty" ) ) {
        const span = emoji as HTMLElement;
        this.openTaskBodyOverlay( span.dataset.taskBody ?? "", span.dataset.taskId ?? "" );
      }
      return true;
    }
    // The mic is routed before the submit-shaped buttons and does not carry
    // `.task-action-btn`: it fills the box a verb reads, it is not a verb.
    const mic = el.closest<HTMLButtonElement>( ".task-reason-stt" );
    if ( mic !== null ) { this.handleReasonMicClick( mic ); return true; }
    const update = el.closest<HTMLButtonElement>( ".task-priority-update" );
    if ( update !== null ) { this.handlePriorityUpdateClick( update ); return true; }
    const submitButton = el.closest<HTMLButtonElement>( ".task-submit-button" );
    if ( submitButton !== null ) { this.handleSubmitClick( submitButton ); return true; }
    // GROUP-SCOPED, not just pane-scoped: a row shown in two panes has two controls rows
    // carrying the same `data-controls-for`, and so does a row the Epic Board paints twice
    // (under ⏳ Waiting on Rick AND under its own epic). A pane-wide lookup opened the
    // first copy whichever ⋯ was pressed.
    const discloseButton = el.closest<HTMLElement>( ".task-disclose-button" );
    if ( discloseButton !== null ) { toggleDisclosure( this.groupScope( discloseButton ), discloseButton ); return true; }
    // An em-dash (idless) cell still matches; handleIdCopy no-ops on the empty id.
    const idCell = el.closest<HTMLElement>( ".task-col-id" );
    if ( idCell !== null ) { this.handleIdCopy( idCell ); return true; }
    return false;
  }

  /**
   * Enter / Space on a keyboard-operable row control → the same action a click takes.
   *
   * Ensures:
   *   - true (and the default prevented, so Space does not scroll) for a focused 📄
   *     or an id cell carrying [role="button"]; false for anything else
   */
  handleKeydown( e: KeyboardEvent ): boolean {
    if ( e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar" ) return false;
    const el = e.target as Element;
    if ( el.closest( ".task-detail-emoji" ) === null && el.closest( '.task-col-id[role="button"]' ) === null ) return false;
    e.preventDefault();
    return this.handleClick( e.target );
  }

  /**
   * `change` inside the pane → the verb reshape, the priority staging, or the
   * owner reassignment. Anything else is ignored.
   */
  handleChange( target: EventTarget | null ): void {
    const el = target as Element;
    const verbSelect = el.closest<HTMLSelectElement>( "select.task-verb-select" );
    if ( verbSelect !== null ) { this.handleVerbSelectChange( verbSelect ); return; }

    const prio = el.closest<HTMLSelectElement>( "select.task-priority-select" );
    if ( prio !== null ) { this.handlePrioritySelectChange( prio ); return; }

    // The owner select is NOT staged: it has no Update button on either client's
    // row, and commits on change as it always has.
    const owner = el.closest<HTMLSelectElement>( "select.task-owner-select" );
    if ( owner === null ) return;
    const id = this.taskIdOf( owner );
    if ( id === "" ) return;   // defensive: a row without an id cannot be mutated
    const value = owner.value;
    this.commitMutation( `${id}:owner`, id, owner, () => this.writer.patchTask( id, { owner_persona: value } ) );
  }

  // -------------------------------------------------------------------------
  // Priority — a staged edit (Phase 2 A8 T9)
  // -------------------------------------------------------------------------

  /**
   * Enable Update only when the chosen priority DIFFERS from the painted one.
   *
   * ⚠️ AGAINST `data-original`, NOT A REMEMBERED VALUE: the row repaints on every
   * poll, so the original has to travel on the element that survives the repaint.
   *
   * Ensures:
   *   - Update is enabled iff the select's value differs from data-original
   *   - `aria-disabled` and the tooltip track `disabled`
   *   - a select with no Update beside it is a no-op
   */
  private handlePrioritySelectChange( select: HTMLSelectElement ): void {
    const button = this.priorityUpdateFor( select );
    if ( button === null ) return;
    const moved = select.value !== ( select.dataset.original ?? "" );
    button.disabled = !moved;
    button.setAttribute( "aria-disabled", moved ? "false" : "true" );
    button.setAttribute( "title", moved ? `Set priority to ${select.value}` : PRIORITY_UPDATE_IDLE_TITLE );
  }

  /**
   * Update click → PATCH the staged priority.
   *
   * 🔴 RE-CHECKED HERE, NOT TRUSTED FROM THE BUTTON'S STATE. `disabled` is a DOM
   * property a repaint or a script can change; the guard that matters is the one on
   * the path to the request.
   *
   * Ensures:
   *   - no request when the value has not moved, the row has no id, or no select
   *     sits beside the button
   *   - otherwise one PATCH carrying only `priority`
   */
  private handlePriorityUpdateClick( button: HTMLButtonElement ): void {
    const id = this.taskIdOf( button );
    if ( id === "" ) return;
    const select = button.parentElement?.querySelector<HTMLSelectElement>( ".task-priority-select" ) ?? null;
    if ( select === null ) return;
    const chosen = select.value.trim();
    if ( chosen === "" || chosen === ( select.dataset.original ?? "" ) ) return;
    this.commitMutation( `${id}:priority`, id, button, () => this.writer.patchTask( id, { priority: chosen } ) );
  }

  /** The Update button painted beside a priority select — its next sibling of that class. */
  private priorityUpdateFor( select: HTMLSelectElement ): HTMLButtonElement | null {
    return select.parentElement?.querySelector<HTMLButtonElement>( ".task-priority-update" ) ?? null;
  }

  // -------------------------------------------------------------------------
  // The reason mic (Phase 2 A8 T7)
  // -------------------------------------------------------------------------

  /**
   * The row mic: dictate straight into THIS row's reason box, in THIS pane.
   *
   * 🔴 IT RESOLVES THE BOX BY SCOPE, NEVER BY ID. A row on two panes carries one
   * `data-task-id` twice; an id lookup returns the first copy, which is how an
   * operator on the classic page once had a Won't-fix read the OTHER pane's empty
   * box (bc77cd79). The scope is the clicked button's own row.
   *
   * Toggle semantics match every other mic: click to record, click again to stop,
   * Esc to cancel — all of it owned by the recorder. The transcription is spliced
   * at the caret the box had when recording began.
   *
   * Ensures:
   *   - no-op without a task id
   *   - a stripe, and no recording, when no reason box shares the mic's row
   *   - a click while this row records STOPS it and marks the mic `processing`;
   *     a click while it is processing is ignored
   *   - the mic carries `recording` while recording; every outcome clears it
   *   - a recording failure reaches the row stripe in the recorder's words
   */
  private handleReasonMicClick( button: HTMLButtonElement ): void {
    const id = button.dataset.taskId ?? "";
    if ( id === "" ) return;
    const contextId = reasonMicContextId( id );
    if ( this.micProcessing.has( contextId ) ) return;

    const scope = this.controlScope( button );
    const input = scope?.querySelector<HTMLInputElement>( ".task-reason-input" ) ?? null;
    if ( input === null ) { this.rowError( button, id, MIC_NO_REASON_BOX ); return; }

    if ( this.recorder.getActiveContextId() === contextId ) {
      this.micProcessing.add( contextId );
      button.classList.remove( "recording" );
      button.classList.add( "processing" );
      void this.recorder.stopRecording( contextId );
      return;
    }

    const stash = { text: input.value, selStart: input.selectionStart, selEnd: input.selectionEnd };
    const settle = (): void => {
      this.micProcessing.delete( contextId );
      button.classList.remove( "recording", "processing" );
    };
    button.classList.add( "recording" );
    void this.recorder.startRecording( {
      contextId,
      authToken  : this.getAuthToken(),
      onComplete : ( transcription ) => {
        settle();
        const spliced = insertTranscriptionText( stash.text, stash.selStart, stash.selEnd, transcription );
        input.value = spliced.value;
        if ( spliced.caret !== null ) input.setSelectionRange( spliced.caret, spliced.caret );
      },
      onError    : ( err ) => {
        settle();
        this.rowError( button, id, `Dictation failed: ${err.message}` );
      },
      onCancel   : settle,
    } );
  }

  // -------------------------------------------------------------------------
  // The verb select + Submit
  // -------------------------------------------------------------------------

  /**
   * A verb was chosen (or un-chosen) → re-shape the row's other controls to suit it.
   *
   * Four things move:
   *   · the reason placeholder, so each verb still states its own ask;
   *   · the reason field's DISABLED state — Approve takes no input;
   *   · the drop-reason suggestions, offered only while Drop is chosen (Mr. Radio's
   *     ruling on T8, 2026-09-16 — legacy's list is painted and referenced by nothing);
   *   · the date input, inserted only for the verbs that require one.
   *
   * 🔴 AND IT DISARMS SUBMIT. An armed Won't-fix surviving a change of verb would
   * swallow the next verb's single click as a confirmation for a verb they left.
   *
   * Ensures:
   *   - the reason input is disabled iff the chosen verb takes no reason, and is
   *     cleared when disabled
   *   - the reason input carries `list="task-drop-reason-suggestions"` iff the verb is Drop
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
      if ( select.value === "drop" ) box.setAttribute( "list", DROP_REASON_DATALIST_ID );
      else box.removeAttribute( "list" );
    }

    const existing = cell.querySelector<HTMLInputElement>( ".task-chase-input" );
    if ( needs !== null && needs.date ) {
      const date = existing ?? document.createElement( "input" );
      date.type      = "date";
      date.className = "task-action-input task-chase-input";
      date.dataset.taskId = id;
      date.setAttribute( "aria-label", needs.dateLabel );
      date.setAttribute( "title", needs.dateLabel );
      // 🔴 INSERT BESIDE SUBMIT, NOT INTO THE SCOPE. `insertBefore` needs a DIRECT
      // child, and `.task-col-actions` is the disclosed FIELD WRAPPER — Submit lives
      // one level down. Anchoring on Submit's own parent is correct at either depth.
      if ( existing === null ) {
        const anchorParent = btn?.parentNode ?? cell;
        anchorParent.insertBefore( date, btn ?? null );
      }
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
   * button's own label — a browser `confirm()` blocks the extension's event loop.
   *
   * Ensures:
   *   - no verb chosen → a stripe saying so, no api call
   *   - a required reason or date missing → that verb's OWN complaint, no api call
   *   - every refusal disarms Submit first
   *   - a terminal verb's FIRST click arms rather than submits
   *   - the posted body carries the verb's own extras
   */
  private handleSubmitClick( button: HTMLButtonElement ): void {
    // 🔴 THE SCOPE IS THE CONTROLS ROW, NOT THE VISIBLE ROW: the verb select, the
    // reason box, the date box and Submit all live in the sibling `.task-controls-row`.
    const row = this.controlScope( button );
    /* c8 ignore next */ // defensive: Submit only ever lives inside one of the two row elements.
    if ( row === null ) return;
    const id = this.taskIdOf( button );
    if ( id === "" ) return;   // defensive: an idless row cannot be transitioned

    const select = row.querySelector<HTMLSelectElement>( ".task-verb-select" );
    /* c8 ignore next */ // defensive: Submit only ever renders in a cell that also renders the verb select.
    if ( select === null ) return;
    const verb  = select.value;
    const needs = verbNeeds( verb );
    if ( needs === null ) {
      this.disarmSubmit( button );
      this.rowError( button, id, "Choose an action first — the row does not know what you want done." );
      return;
    }

    const reason   = this.rowInputValue( row, "task-reason-input" );
    const chaseDay = this.rowInputValue( row, "task-chase-input" );

    if ( needs.reason && reason === "" ) {
      this.disarmSubmit( button );
      this.rowError( button, id, verbReasonComplaint( verb ) );
      return;
    }
    if ( needs.date && chaseDay === "" ) {
      this.disarmSubmit( button );
      this.rowError( button, id, verbDateComplaint( verb ) );
      return;
    }

    // ⚠️ THE DATE INPUT YIELDS A LOCAL CALENDAR DAY AND THE SERVER WANTS AN INSTANT.
    // Stamp 09:00 LOCAL rather than letting a bare date read as midnight UTC, which
    // lands the chase on the previous evening for anyone west of Greenwich.
    let chaseIso: string | null = null;
    if ( needs.date ) {
      const parsed = new Date( `${chaseDay}T09:00:00` );
      if ( isNaN( parsed.getTime() ) ) {
        this.disarmSubmit( button );
        this.rowError( button, id, `Date not understood: ${chaseDay}` );
        return;
      }
      chaseIso = parsed.toISOString();
    }

    if ( needs.terminal && button.dataset.armed !== "1" ) {
      button.dataset.armed = "1";
      button.classList.add( "task-submit-armed" );
      button.textContent = `Confirm ${verbLabel( verb ).toLowerCase()}`;
      this.rowError( button, id, "" );
      return;
    }

    const extras = transitionExtras( verb, reason, chaseIso );
    this.rowError( button, id, "" );
    this.disarmSubmit( button );
    this.commitMutation(
      `${id}:${verb}`, id, button,
      () => this.writer.transitionTask( id, needs.status, extras ),
      ( gone ) => this.onTransitionSettled( id, needs.status, gone ),
    );
  }

  /** One of a row's action inputs, trimmed, or "" when it is not rendered (the date box usually is not). */
  private rowInputValue( row: HTMLElement, className: string ): string {
    const el = row.querySelector<HTMLInputElement>( `.${className}` );
    return el === null ? "" : el.value.trim();
  }

  /** Return Submit to its resting state: one click, one action. */
  private disarmSubmit( button: HTMLButtonElement | null ): void {
    /* c8 ignore next */ // defensive: every actions cell renders a Submit per the template invariant.
    if ( button === null ) return;
    delete button.dataset.armed;
    button.classList.remove( "task-submit-armed" );
    button.textContent = "Submit";
  }

  // -------------------------------------------------------------------------
  // The id cell
  // -------------------------------------------------------------------------

  /**
   * ID-cell click / Enter / Space (F1 2026.07.01): copy the row's FULL id, then
   * flash a transient no-reflow "copied" state.
   *
   * Guards (never throws): an idless row, a runtime without `navigator.clipboard`,
   * and a rejected write are all silent no-ops.
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
      .then( () => {
        idCell.classList.add( "task-id-copied" );
        this.setTimeoutFn( () => idCell.classList.remove( "task-id-copied" ), COPIED_FLASH_MS );
      } )
      .catch( () => { /* clipboard denied/failed → no feedback, no throw */ } );
  }

  // -------------------------------------------------------------------------
  // Scope + id resolution
  // -------------------------------------------------------------------------

  /**
   * The element that CONTAINS one row's controls.
   *
   * ⚠️ THE CONTROLS ROW MUST BE TRIED FIRST: `.task-controls-row` is a SIBLING of
   * `.task-row`, not a child.
   *
   * 🔴 FAIL LOUDLY — CENTRALISING THE LOOKUP MUST NOT CENTRALISE THE SILENCE
   * (María's condition on approving this helper). A null here means the row shape
   * moved and every caller is about to no-op, so it says so once, naming the control.
   */
  private controlScope( el: Element ): HTMLElement | null {
    const scope = el.closest<HTMLElement>( ".task-controls-row" ) ?? el.closest<HTMLElement>( ".task-row" );
    if ( scope === null ) {
      console.error(
        `${this.logLabel} a control resolved NO row scope — the row shape moved and its handlers ` +
        // `|| el.tagName` is UNREACHABLE: every door into this helper selects BY CLASS
        // in this file, so nothing classless can arrive. If you widen a selector to
        // admit a classless element, delete this pragma.
        /* c8 ignore next */ // unreachable: every call site selects by class (see above)
        "are about to no-op silently. Control:", ( el as HTMLElement ).className || el.tagName,
      );
    }
    return scope;
  }

  /**
   * Resolve a control's owning task id.
   *
   * 🔴 ASK THE CONTROL FIRST, THEN THE ROW. The controls live in the sibling
   * `.task-controls-row`, so a bare `closest( ".task-row" )` walks past them; and
   * the owner select carries no `data-task-id` of its own, so the controls row's
   * `data-controls-for` is the durable answer. Anything still on the visible line
   * goes through the loud scope helper.
   */
  private taskIdOf( el: Element ): string {
    const own = ( el as HTMLElement ).dataset?.taskId;
    if ( own !== undefined && own !== "" ) return own;

    const controlsRow = el.closest<HTMLElement>( ".task-controls-row" );
    if ( controlsRow !== null ) return controlsRow.getAttribute( "data-controls-for" ) ?? "";

    const row = this.controlScope( el );
    if ( row === null ) return "";
    return this.rowId( row );
  }

  // renderTaskRow ALWAYS sets `data-task-id` (to "" when the server row carried no id).
  private rowId( row: HTMLElement ): string {
    /* c8 ignore next */ // defensive: data-task-id is always set by renderTaskRow (template invariant), so the `?? ""` RHS is unreachable.
    return row.getAttribute( "data-task-id" ) ?? "";
  }

  // -------------------------------------------------------------------------
  // Writes + the row stripe
  // -------------------------------------------------------------------------

  /**
   * Shared optimistic-mutation driver: in-flight dedupe on `key`, run the store
   * call, and on settle —
   *   - 2xx → keep the optimistic edit;
   *   - ApiError 404 → treat as success (the row is already gone server-side);
   *   - any other error → `restoreState()` + an inline row error stripe.
   * `onSuccess` runs on both success outcomes, told which: `gone` is true for the 404.
   * `control` is the element that was pressed; its group is where the stripe goes.
   */
  private commitMutation( key: string, id: string, control: Element, run: () => TaskMutation, onSuccess?: ( gone: boolean ) => void ): void {
    if ( this.editInFlight.has( key ) ) return;   // rapid re-activation is a no-op until settle
    this.editInFlight.add( key );
    const { restoreState, done } = run();
    done
      .then( () => { onSuccess?.( false ); } )
      .catch( ( err: unknown ) => {
        if ( err instanceof ApiError && err.status === 404 ) { onSuccess?.( true ); return; }
        restoreState();
        this.rowError( control, id, deriveEditErrorMessage( err ) );
      } )
      .finally( () => { this.editInFlight.delete( key ); } );
  }

  /**
   * Show (or, with an empty message, clear) the refusal stripe for `id` in THIS pane.
   * The mechanism is `templates/rowDisclosure.renderRowError`, shared by every pane
   * (operator-state spec ruling 6).
   */
  renderRowError( id: string, message: string ): void {
    paintRowError( this.container, id, message );
  }

  /** A pressed control's refusal, painted in the stripe of the copy that was pressed. */
  private rowError( control: Element, id: string, message: string ): void {
    paintRowError( this.groupScope( control ), id, message );
  }

  /**
   * The element a row lookup is confined to: the pressed control's own group `<tbody>`.
   *
   * 🔴 THE PANE IS TOO WIDE A SCOPE ON THE EPIC BOARD. A row waiting on Rick is painted
   * twice there, under ⏳ Waiting on Rick and under its own epic, so every by-id lookup
   * across the pane found the Waiting-on-Rick copy first: the epic copy's ⋯ opened the
   * other copy, and its refusal landed under the other copy. Measured on 95794538.
   * The Task List and Holding Area paint each task once, so this changes nothing there.
   *
   * ⚠️ A REFUSAL ARRIVES AFTER THE WRITE SETTLES, and the store may have repainted in
   * between, leaving the pressed control's `<tbody>` detached. The same group is then
   * re-found in the fresh paint by its `data-*` key (`data-epic`, `data-owner`); a group
   * with no key falls back to the pane, which is what every lookup did before.
   *
   * Ensures:
   *   - the control's own `<tbody>` while it is still in this pane
   *   - else the fresh `<tbody>` carrying the same `data-*` key/values
   *   - else the pane container — never a detached node, which would swallow a refusal
   */
  private groupScope( control: Element ): ParentNode {
    const group = control.closest<HTMLElement>( "tbody" );
    if ( group === null ) return this.container;
    if ( this.container.contains( group ) ) return group;
    const identity = Object.entries( group.dataset );
    if ( identity.length === 0 ) return this.container;
    return Array.from( this.container.querySelectorAll<HTMLElement>( "tbody" ) )
      .find( ( t ) => identity.every( ( [ k, v ] ) => t.dataset[ k ] === v ) ) ?? this.container;
  }

  // -------------------------------------------------------------------------
  // Body overlay (row redesign 2026.06.29 / D2 — renders the task `body`)
  // -------------------------------------------------------------------------

  /**
   * Show a small dismissible overlay rendering the task-store `body`. All DOM via
   * createElement + textContent. Dismiss on backdrop click or Escape.
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
    pre.textContent = bodyText;

    panel.appendChild( header );
    panel.appendChild( pre );
    overlay.appendChild( panel );

    overlay.addEventListener( "click", () => this.dismissTaskBodyOverlay() );
    panel.addEventListener( "click", ( e ) => e.stopPropagation() );

    this.overlayKeyListener = ( e: KeyboardEvent ): void => {
      if ( e.key === "Escape" ) this.dismissTaskBodyOverlay();
    };
    document.addEventListener( "keydown", this.overlayKeyListener );

    document.body.appendChild( overlay );
  }

  /** Remove the body overlay and its Esc listener. Idempotent. */
  private dismissTaskBodyOverlay(): void {
    if ( this.overlayKeyListener !== null ) {
      document.removeEventListener( "keydown", this.overlayKeyListener );
      this.overlayKeyListener = null;
    }
    const existing = document.getElementById( "task-body-overlay" );
    if ( existing !== null ) existing.remove();
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
function deriveEditErrorMessage( err: unknown ): string {
  if ( err instanceof ApiError ) return `Edit failed (HTTP ${err.status})`;
  if ( err instanceof Error )    return `Edit failed: ${err.message}`;
  /* c8 ignore next */ // defensive: ApiClient always rejects with Error subclasses; this is a safety net for non-Error throws.
  return "Edit failed";
}
