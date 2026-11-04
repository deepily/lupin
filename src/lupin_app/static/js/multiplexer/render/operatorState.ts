/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Operator-state capture/restore — parity row A-1a.
//
// THE SPECIFICATION IS the R&D write-up "operator state preservation spec",
// not this header. Ported from legacy `_captureOperatorState` / `_restoreOperatorState`
// / `_operatorInputKey` / `_operatorInputByKey` (notifications.js).
//
// 🔴 THE PROPERTY: a poll tick landing between an operator's keystroke and their
// click must not change what that click does. The Task List and Holding Area repaint
// with `replaceChildren`, so every node is new after a poll and the operator's
// half-finished work — a typed reason, the chosen verb, an open controls row, a shown
// refusal, the caret — is gone unless it is read off the old markup first and written
// into the new markup after.
//
// Six categories (spec §1), in this module's field names:
//   inputs     — typed `.task-action-input` values, under two keying schemes (§2)
//   selects    — the chosen `.task-verb-select` value
//   priorities — a PENDING `.task-priority-select` edit, feature-detected on
//                `data-original` (spec ruling 1). A-2 #0 put `data-original` on the
//                multiplexer select, so this category is live on every pane that paints it.
//   stripes    — a shown `.task-row-error-stripe`
//   disclosed  — an open `.task-controls-row`
//   focus      — which input had focus, with its caret
//
// ⚠️ THREE DIVERGENCES FROM LEGACY, ALL RULED OR MEASURED:
//   1. NO ID EVER ENTERS A SELECTOR. Legacy builds `[data-task-id="${CSS.escape(id)}"]`;
//      happy-dom rejects the valid escape (measured twice in this tree). Every lookup
//      selects by a code-controlled class and compares the attribute in JavaScript.
//   2. THE TEXT STEP SKIPS A DISABLED BOX. The multiplexer's verb handler clears the
//      reason box when the verb takes no reason; restoring the text after the verb
//      would write the reason back into a box the verb just emptied (spec §3 step 1).
//   3. `.task-request-triage` IS NOT VALUE-SWEPT (spec ruling 5, measured). The request
//      chip controller already remembers that date keyed by `taskId@request_ts`; a
//      task-id key here would write an old request's date into a new request's chip.
//      Focus may still land on it — focus writes no value.
//
// A row the fresh data no longer contains is LEFT GONE (spec §5): every restore step
// ends in "no element → skip", never re-creates a row and never throws.

/** The NUL separator inside an input key. Written as an escape, never a raw byte. */
export const KEY_SEP = "\0";

const TRIAGE_CLASS = "task-request-triage";

/**
 * What the operator had in a pane before a repaint.
 *
 * It holds typed values, chosen verbs, pending priorities, shown refusals, open control rows and the focused input with its caret.
 */
export interface OperatorState {
  inputs     : Array<[ string, string ]>;
  selects    : Array<[ string, string ]>;
  priorities : Array<[ string, string ]>;
  stripes    : Array<[ string, string ]>;
  disclosed  : string[];
  focusKey   : string | null;
  selStart   : number;
  selEnd     : number;
}

/**
 * The pane-owned behaviour restore must reuse rather than re-implement.
 *
 * ⚠️ A HANDLER IS OPTIONAL WHERE THE PANE HAS NONE. The Holding Area has no verb
 * listener today; restoring its verb then puts the value back and reshapes nothing,
 * which is exactly what the operator had.
 */
export interface OperatorStateHandlers {
  /** The pane's own verb-change handler: builds or removes the date box, disables the reason. */
  onVerbChange?     : ( select: HTMLSelectElement ) => void;
  /**
   * The pane's own priority-change handler, which RECOMPUTES the Update button.
   * 🔴 Never pass a handler that commits: without it a captured priority is not restored.
   */
  onPriorityChange? : ( select: HTMLSelectElement ) => void;
  /** Re-show a refusal stripe for a row, pane-scoped. */
  renderRowError    : ( taskId: string, message: string ) => void;
}

/** The first class that names WHICH input this is — shared by key-build and key-parse. */
function whichClass( el: Element ): string | undefined {
  return Array.from( el.classList )
    .find( ( c ) => c !== "task-action-input" && ( c.startsWith( "task-" ) || c.startsWith( "holding-" ) ) );
}

/**
 * The key an operator input is captured under: `"<attr>\0<owner>\0<whichClass>"`.
 *
 * Ensures:
 *   - `attr` is `data-task-id` when that attribute is non-empty, else `data-filer`
 *   - null when neither owner attribute is non-empty, or no naming class exists
 */
export function operatorInputKey( el: Element ): string | null {
  const taskId = el.getAttribute( "data-task-id" ) ?? "";
  const filer  = el.getAttribute( "data-filer" ) ?? "";
  const owner  = taskId || filer;
  if ( owner === "" ) return null;
  const attr  = taskId ? "data-task-id" : "data-filer";
  const which = whichClass( el );
  return which === undefined ? null : [ attr, owner, which ].join( KEY_SEP );
}

/** Resolve a key in fresh markup — class selector, attribute compared in JS. */
export function operatorInputByKey( container: ParentNode, key: string ): HTMLInputElement | null {
  const parts = key.split( KEY_SEP );
  if ( parts.length !== 3 ) return null;
  const [ attr, owner, which ] = parts as [ string, string, string ];
  return Array.from( container.querySelectorAll<HTMLInputElement>( `.${ which }` ) )
    .find( ( el ) => el.getAttribute( attr ) === owner ) ?? null;
}

/** First element of `selector` whose `attr` equals `value`, pane-scoped. */
function byAttr<T extends Element>( container: ParentNode, selector: string, attr: string, value: string ): T | null {
  return Array.from( container.querySelectorAll<T>( selector ) ).find( ( el ) => el.getAttribute( attr ) === value ) ?? null;
}

/**
 * Read the operator's in-progress state off markup that is about to be replaced.
 *
 * Requires:
 *   - called immediately BEFORE the `replaceChildren` that discards it
 *
 * Ensures:
 *   - every category of the spec §1 list, from inside `container` only
 *   - a pure read: nothing in the DOM changes
 */
export function captureOperatorState( container: ParentNode ): OperatorState {
  const state: OperatorState = {
    inputs: [], selects: [], priorities: [], stripes: [], disclosed: [], focusKey: null, selStart: 0, selEnd: 0,
  };
  const active = document.activeElement;

  for ( const el of Array.from( container.querySelectorAll<HTMLInputElement>( ".task-action-input" ) ) ) {
    const key = operatorInputKey( el );
    if ( key === null ) continue;
    if ( !el.classList.contains( TRIAGE_CLASS ) ) state.inputs.push( [ key, el.value ] );
    if ( el === active ) {
      state.focusKey = key;
      // A type that has no selection (date) reads null — default to the end of the value.
      state.selStart = el.selectionStart ?? el.value.length;
      state.selEnd   = el.selectionEnd   ?? el.value.length;
    }
  }
  for ( const el of Array.from( container.querySelectorAll<HTMLSelectElement>( ".task-verb-select" ) ) ) {
    const taskId = el.getAttribute( "data-task-id" );
    if ( taskId && el.value ) state.selects.push( [ taskId, el.value ] );
  }
  // 🔴 ONLY A PENDING EDIT, AND ONLY WHERE `data-original` MAKES "PENDING" DECIDABLE.
  // An untouched select re-asserted over a row somebody else re-prioritized would light
  // Update over an edit this operator never made (spec §4).
  for ( const el of Array.from( container.querySelectorAll<HTMLSelectElement>( ".task-priority-select" ) ) ) {
    const taskId   = el.getAttribute( "data-task-id" );
    const original = el.getAttribute( "data-original" );
    const chosen   = el.value.trim();
    if ( taskId && original !== null && chosen && chosen !== original ) state.priorities.push( [ taskId, chosen ] );
  }
  for ( const el of Array.from( container.querySelectorAll<HTMLElement>( ".task-row-error-stripe" ) ) ) {
    const taskId = el.getAttribute( "data-error-for" );
    if ( el.hidden || !taskId ) continue;
    state.stripes.push( [ taskId, el.querySelector( "td" )?.textContent ?? "" ] );
  }
  for ( const el of Array.from( container.querySelectorAll<HTMLElement>( ".task-controls-row" ) ) ) {
    const taskId = el.getAttribute( "data-controls-for" );
    if ( !el.hidden && taskId ) state.disclosed.push( taskId );
  }
  return state;
}

/**
 * Put captured state back into freshly painted markup, in the spec §3 order.
 *
 * Requires:
 *   - called AFTER the repaint and after the pane's request-chip hydrate
 *
 * Ensures, in this order, each step because the next depends on it:
 *   1. verbs, each handed to `onVerbChange` — the date box exists only once its verb does
 *   2. pending priorities with a matching `<option>`, each handed to `onPriorityChange`
 *   3. non-empty typed values into boxes that exist and are NOT disabled
 *   4. non-empty refusal stripes, through the pane's `renderRowError`
 *   5. controls rows opened ABSOLUTELY (never toggled) with `aria-expanded="true"`
 *   6. focus, without scrolling, then the caret — a type that refuses a range is tolerated
 *   - anything whose element is absent is skipped, never re-created, never a throw
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function restoreOperatorState( container: ParentNode, state: OperatorState, handlers: OperatorStateHandlers ): void {
  for ( const [ taskId, verb ] of state.selects ) {
    const sel = byAttr<HTMLSelectElement>( container, ".task-verb-select", "data-task-id", taskId );
    if ( sel === null ) continue;
    sel.value = verb;
    handlers.onVerbChange?.( sel );
  }
  if ( handlers.onPriorityChange !== undefined ) {
    for ( const [ taskId, priority ] of state.priorities ) {
      const sel = byAttr<HTMLSelectElement>( container, ".task-priority-select", "data-task-id", taskId );
      if ( sel === null || !Array.from( sel.options ).some( ( o ) => o.value === priority ) ) continue;
      sel.value = priority;
      handlers.onPriorityChange( sel );
    }
  }
  for ( const [ key, value ] of state.inputs ) {
    if ( value === "" ) continue;
    const el = operatorInputByKey( container, key );
    if ( el !== null && !el.disabled ) el.value = value;
  }
  for ( const [ taskId, message ] of state.stripes ) {
    if ( message !== "" ) handlers.renderRowError( taskId, message );
  }
  for ( const taskId of state.disclosed ) {
    const row = byAttr<HTMLElement>( container, ".task-controls-row", "data-controls-for", taskId );
    if ( row === null ) continue;
    row.hidden = false;
    byAttr<HTMLElement>( container, ".task-disclose-button", "data-task-id", taskId )?.setAttribute( "aria-expanded", "true" );
  }
  if ( state.focusKey !== null ) {
    const el = operatorInputByKey( container, state.focusKey );
    if ( el === null ) return;
    // A poll landing must never scroll the pane out from under the operator.
    el.focus( { preventScroll: true } );
    try {
      el.setSelectionRange( state.selStart, state.selEnd );
    } catch {
      // input types that refuse a selection range, e.g. date
    }
  }
}
