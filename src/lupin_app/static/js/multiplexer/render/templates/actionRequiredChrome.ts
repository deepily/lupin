/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity A-2 #2m (row 2ebf322f) — the chrome legacy draws around an Action
// Required card's prompt.
//
// Legacy builds all of this inline in `renderActionRequiredNotification`
// (notifications.js:23292-23330). Five pieces, and every one is absent-tolerant
// there — the field is missing, the markup is the empty string:
//
//   - the [PROJECT] badge, from `sender_id` via getProjectFromSenderId (:23299-23303),
//     suppressed when the parse yields "UNKNOWN"
//   - the persona badge, straight off the notification envelope (:23311)
//   - the 📋 abstract indicator, only when `abstract` is non-blank (:23315-23317)
//   - the inline abstract block, markdown-rendered (:23293-23295)
//   - the prediction hint (:23297)
//
// The pieces live here rather than in the renderer so each is testable on its
// own and so the two that already exist elsewhere in the multiplexer are reused
// rather than re-cut: `renderPredictionVoteControls` (templates/predictionVoteControls.ts)
// and the project parse, which moves to `render/senderProject.ts` in this change
// so the notifications list and this card read one implementation.

import { html } from "../html";
import { renderMarkdown } from "../markdown";
import { projectFromSenderId } from "../senderProject";
import { renderPredictionVoteControls } from "./predictionVoteControls";
import type { PredictionVoteIntegration } from "./predictionVoteControls";
import type { VoicePersona, PredictionHint, ContextForecastPayload } from "../../shared/types";
import { ownLookup } from "../../shared/ownLookup";

/**
 * Build the `[PROJECT]` badge for a card, or null when the sender id names no project.
 *
 * The project is parsed from the sender id. A missing id or an `UNKNOWN` project gives null, as in the legacy client.
 */
export function projectBadge( senderId: string | undefined ): HTMLElement | null {
  if ( senderId === undefined ) return null;
  const project = projectFromSenderId( senderId );
  if ( project === "UNKNOWN" ) return null;
  const el = document.createElement( "span" );
  el.className   = "mc-project-badge";
  el.textContent = `[${ project }]`;
  return el;
}

// Legacy's `_renderPersonaBadgeHTML` (notifications.js:16096) inserted as the
// first child of `.action-required-timer-controls` (:23310-23311). The borrowed
// flag rides as a class, matching senderCard.ts's `.sender-persona-badge borrowed`.
// 🔴 `== null`, NOT `=== undefined` — the server spells "no persona" as JSON `null`, and
// this guard used to miss it. `notification_fifo_queue.py` serialises
// `"voice_persona": self.voice_persona`, which is `None` whenever the sender-id suffix has
// no session-bridge entry; `ActionRequiredStore` then admitted it (its own guard tested
// `!== undefined` too), so `persona` arrived here as `null`, sailed through an
// `=== undefined` check, and `persona.borrowed` on the next line threw
// `TypeError: Cannot read properties of null (reading 'borrowed')`.
//
// That throw was SILENT: EventBus wraps every listener in try/catch and re-emits as
// `listener_error`, so nothing reached the console. It landed inside
// ActionRequiredRenderer.reconcile() AFTER updateCount() wrote the header and BEFORE
// anything was painted — so the operator saw "⚠️ Action Required 1" over an EMPTY panel,
// with no card to answer and no error to explain it. Measured 2026-09-22 on :7999; it is
// what reddened the three ask/audio E2E tests.
//
// The predicate is "absent", and JavaScript spells absent two ways. `== null` is both.
// Behaviour on absent is unchanged and is the ratified one: OMIT the badge, render the
// card — same as senderCard.ts's F-Arnold-4 note ("the badge element is omitted entirely,
// not rendered as empty/stub").
/**
 * Build the persona badge for a card: the icon and name on the persona's color.
 *
 * Returns null when the persona is null or undefined, because the server sends no persona as JSON null. A borrowed persona gets the `borrowed` class.
 */
export function personaBadge( persona: VoicePersona | null | undefined ): HTMLElement | null {
  if ( persona == null ) return null;
  const el = document.createElement( "span" );
  el.className = persona.borrowed ? "persona-badge borrowed" : "persona-badge";
  el.style.setProperty( "--persona-color", persona.color );
  const icon = document.createElement( "span" );
  icon.className   = "persona-badge-icon";
  icon.textContent = persona.icon;
  const name = document.createElement( "span" );
  name.className   = "persona-badge-name";
  name.textContent = persona.name;
  el.append( icon, name );
  return el;
}

/** The parts of the 📋 button a caller may change. */
export interface AbstractIndicatorOptions {
  /** The document to build in; defaults to the page's. */
  doc?       : Document;
  /** Extra classes added after `abstract-indicator`. */
  className? : string;
  /** The hover title; null leaves it off. Defaults to "View full abstract". */
  title?     : string | null;
  /** Written to `data-testid` when given. */
  testid?    : string;
}

/**
 * Build the 📋 button that opens a card's abstract, or null when the abstract is blank.
 *
 * The abstract text rides on the `data-abstract` attribute, which the reading pane reads when the button is clicked.
 * The options let the notification list and the jobs pane build the same button with their own class, title and test id.
 */
export function abstractIndicator( abstract: string | undefined, opts: AbstractIndicatorOptions = {} ): HTMLElement | null {
  if ( abstract === undefined || abstract.trim().length === 0 ) return null;
  const el = ( opts.doc ?? document ).createElement( "span" );
  el.className = opts.className === undefined ? "abstract-indicator" : `abstract-indicator ${ opts.className }`;
  el.setAttribute( "data-abstract", abstract );
  el.setAttribute( "role", "button" );
  el.setAttribute( "tabindex", "0" );
  const title = opts.title === undefined ? "View full abstract" : opts.title;
  if ( title !== null ) el.setAttribute( "title", title );
  el.textContent = "📋";
  if ( opts.testid !== undefined ) el.setAttribute( "data-testid", opts.testid );
  return el;
}

/**
 * Build the inline block that shows a card's abstract, or null when the abstract is blank.
 *
 * The abstract is rendered as markdown through the sanitizing renderer.
 */
export function abstractBlock( abstract: string | undefined ): HTMLElement | null {
  if ( abstract === undefined || abstract.trim().length === 0 ) return null;
  const el = document.createElement( "div" );
  el.className = "action-required-abstract";
  el.appendChild( html`${ renderMarkdown( abstract ) }` );
  return el;
}

/**
 * The card's bridge for the forecast fold: whether it was opened, and a call when it opens.
 *
 * The fold keeps no state of its own. The renderer holds which cards had it opened, so a repaint puts it back.
 */
export interface PredictionFoldIntegration {
  /** True when the fold of this card was opened earlier in the card's life. */
  isOpen( notificationId: string ): boolean;
  /** Called when the reader opens the fold. Closing it is not reported. */
  onOpen( notificationId: string ): void;
}

/** The text each state shows in the fold; a ready card shows the forecast instead. */
const HINT_STATE_TEXT: Record<string, string> = {
  insufficient_evidence : "Learning, no prediction yet",
  below_threshold       : "Forecast too uncertain to show",
  unavailable           : "Forecast unavailable",
};

/** The text of each Haiku forecast state; a ready forecast shows its value. */
const CONTEXT_STATE_TEXT: Record<string, string> = {
  forecasting        : "Haiku forecast: still forecasting",
  unavailable        : "Haiku forecast unavailable",
  forecast_timed_out : "Haiku forecast timed out",
};

/**
 * Build the line for a card's Haiku forecast, or null when it carries none.
 *
 * Requires:
 *   - forecast is the hint's `context_forecast`, or undefined while the display switch is off
 * Ensures:
 *   - the element has `data-testid="prediction-hint-context"` and `data-context-state` set to the state
 *   - a ready forecast reads "Haiku forecast: <value> (<confidence>%)", the value shown as the hint shows it
 */
export function contextForecastLine( responseType: string, forecast: ContextForecastPayload | undefined ): HTMLElement | null {
  if ( forecast === undefined ) return null;
  const line = document.createElement( "div" );
  line.className = "prediction-hint-context";
  line.setAttribute( "data-testid", "prediction-hint-context" );
  line.setAttribute( "data-context-state", forecast.state );
  line.textContent = forecast.state === "ready"
    ? `Haiku forecast: ${ predictedText( responseType, forecast.predicted_value ) } (${ Math.round( ( forecast.confidence ?? 0 ) * 100 ) }%)`
    : ownLookup<string>( CONTEXT_STATE_TEXT, forecast.state, "Haiku forecast unavailable" );
  return line;
}

/**
 * Build the forecast fold of a card. It is always returned.
 *
 * The hint sits inside a native `details` fold that starts closed. A missing hint, or a state other than `ready`, shows that state's own text. A ready hint shows the value, the confidence with its metric, the strategy and the always-yes rate on a yes/no card.
 * The vote controls are added inside the fold when `vote` is given and the confidence passes the gate. Without `vote` they are not mounted, because a control with no handler would do nothing.
 */
export function predictionHintBox(
  item : { id_hash: string; response_type: string; prediction_hint?: PredictionHint | null },
  vote : PredictionVoteIntegration | undefined,
  fold?: PredictionFoldIntegration,
): HTMLElement {
  const hint = item.prediction_hint;
  const root = document.createElement( "details" );
  // `== null`: absent is both spellings (row 759250e4). The store no longer admits a null, but the ghost box
  // is the ratified answer to "no hint" whichever way it is spelled, so this guard says so too.
  const state = hint == null ? "insufficient_evidence" : hint.state;
  root.className = state === "insufficient_evidence" ? "prediction-hint prediction-hint-cold" : "prediction-hint";
  root.setAttribute( "data-testid", "prediction-hint-fold" );
  root.setAttribute( "data-hint-state", state );
  if ( fold !== undefined && fold.isOpen( item.id_hash ) ) root.open = true;
  const summary = document.createElement( "summary" );
  summary.className   = "prediction-hint-summary";
  summary.textContent = "Forecast";
  root.appendChild( summary );
  if ( fold !== undefined ) {
    root.addEventListener( "toggle", () => { if ( root.open ) fold.onOpen( item.id_hash ); } );
  }
  const label = document.createElement( "div" );
  label.className = "prediction-hint-label";
  root.appendChild( label );
  const context = contextForecastLine( item.response_type, hint?.context_forecast );
  if ( hint == null || state !== "ready" ) {
    label.textContent = ownLookup<string>( HINT_STATE_TEXT, state, "Forecast unavailable" );
    if ( hint != null ) appendAlwaysYes( root, hint );
    if ( context !== null ) root.appendChild( context );
    return root;
  }
  label.textContent = predictedText( item.response_type, hint.predicted_value, hint.predicted_qualifier );
  const confidencePct = Math.round( ( hint.confidence ?? 0 ) * 100 );
  const confidence = document.createElement( "div" );
  confidence.className   = "prediction-hint-confidence";
  confidence.textContent = `Confidence ${ confidencePct }% (${ hint.retrieval_metric } similarity)`;
  root.appendChild( confidence );
  if ( hint.strategy !== undefined ) {
    const strategy = document.createElement( "div" );
    strategy.className   = "prediction-hint-strategy";
    strategy.textContent = hint.strategy;
    root.appendChild( strategy );
  }
  appendAlwaysYes( root, hint );
  if ( context !== null ) root.appendChild( context );
  if ( vote === undefined ) return root;
  const cast = vote.getVote( item.id_hash );
  const controls = renderPredictionVoteControls(
    {
      notificationId : item.id_hash,
      confidencePct,
      ...( cast === undefined ? {} : { castVote: cast } ),
    },
    { onVote: ( dir ) => vote.onVote( item.id_hash, dir ) },
  );
  if ( controls !== null ) root.appendChild( controls );
  return root;
}

/**
 * Adds the always-yes line when the hint has a rate.
 *
 * Example: "Always yes would be right 52 of 59 times".
 */
function appendAlwaysYes( root: HTMLElement, hint: PredictionHint ): void {
  const rate = hint.always_yes_rate;
  if ( rate === undefined ) return;
  const line = document.createElement( "div" );
  line.className   = "prediction-hint-always-yes";
  line.textContent = `Always yes would be right ${ rate.yes } of ${ rate.n } times`;
  root.appendChild( line );
}

// Legacy title-cases a yes_no prediction and prints every other type as-is
// (notifications.js:23597-23635).
/**
 * Returns the predicted answer as display text.
 *
 * A yes or no string is capitalized, with the qualifier after it when there is one. Other strings are shown as they are, and other values become JSON.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line (notificationItem.ts:46 precedent).
function predictedText( responseType: string, value: unknown, qualifier?: string ): string {
  if ( responseType === "yes_no" && typeof value === "string" && value.length > 0 ) {
    const shown = value.charAt( 0 ).toUpperCase() + value.slice( 1 );
    return qualifier === undefined || qualifier.length === 0 ? shown : `${ shown } — "${ qualifier }"`;
  }
  return typeof value === "string" ? value : JSON.stringify( value ) ?? "";
}
