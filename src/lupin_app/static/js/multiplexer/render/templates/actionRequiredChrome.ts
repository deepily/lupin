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
import type { VoicePersona, PredictionHint } from "../../shared/types";

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

/**
 * Build the 📋 button that opens a card's abstract, or null when the abstract is blank.
 *
 * The abstract text rides on the `data-abstract` attribute, which the reading pane reads when the button is clicked.
 */
export function abstractIndicator( abstract: string | undefined ): HTMLElement | null {
  if ( abstract === undefined || abstract.trim().length === 0 ) return null;
  const el = document.createElement( "span" );
  el.className = "abstract-indicator";
  el.setAttribute( "data-abstract", abstract );
  el.setAttribute( "role", "button" );
  el.setAttribute( "tabindex", "0" );
  el.title       = "View full abstract";
  el.textContent = "📋";
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
 * Build the prediction hint box of a card. It is always returned.
 *
 * A missing hint gives a ghost box that reads "Learning, no prediction yet". Otherwise the box shows the predicted value and the strategy when there is one. It adds the vote controls when `vote` is given and the confidence passes the gate. Without `vote` the controls are not mounted. A control with no handler would be a painted button that does nothing.
 */
export function predictionHintBox(
  item : { id_hash: string; response_type: string; prediction_hint?: PredictionHint | null },
  vote : PredictionVoteIntegration | undefined,
): HTMLElement {
  const hint = item.prediction_hint;
  const root = document.createElement( "div" );
  // `== null`: absent is both spellings (row 759250e4). The store no longer admits a null, but the ghost box
  // is the ratified answer to "no hint" whichever way it is spelled, so this guard says so too.
  if ( hint == null ) {
    root.className = "prediction-hint prediction-hint-cold";
    const label = document.createElement( "div" );
    label.className   = "prediction-hint-label";
    label.textContent = "Learning, no prediction yet";
    root.appendChild( label );
    return root;
  }
  root.className = "prediction-hint";
  const label = document.createElement( "div" );
  label.className   = "prediction-hint-label";
  label.textContent = predictedText( item.response_type, hint.predicted_value );
  root.appendChild( label );
  if ( hint.strategy !== undefined ) {
    const strategy = document.createElement( "div" );
    strategy.className   = "prediction-hint-strategy";
    strategy.textContent = hint.strategy;
    root.appendChild( strategy );
  }
  if ( vote === undefined ) return root;
  const cast = vote.getVote( item.id_hash );
  const controls = renderPredictionVoteControls(
    {
      notificationId : item.id_hash,
      confidencePct  : Math.round( hint.confidence * 100 ),
      ...( cast === undefined ? {} : { castVote: cast } ),
    },
    { onVote: ( dir ) => vote.onVote( item.id_hash, dir ) },
  );
  if ( controls !== null ) root.appendChild( controls );
  return root;
}

// Legacy title-cases a yes_no prediction and prints every other type as-is
// (notifications.js:23597-23635).
/**
 * Returns the predicted answer as display text.
 *
 * A yes or no string is capitalized, other strings are shown as they are, and other values become JSON.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line (notificationItem.ts:46 precedent).
function predictedText( responseType: string, value: unknown ): string {
  if ( responseType === "yes_no" && typeof value === "string" && value.length > 0 ) {
    return value.charAt( 0 ).toUpperCase() + value.slice( 1 );
  }
  return typeof value === "string" ? value : JSON.stringify( value ) ?? "";
}
