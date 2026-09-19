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

// Legacy suppresses the badge when the sender id does not parse into a project
// (:23301 — `project && project !== 'UNKNOWN'`).
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
export function personaBadge( persona: VoicePersona | undefined ): HTMLElement | null {
  if ( persona === undefined ) return null;
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

// Legacy gates the 📋 on a non-blank abstract (:23315 — `abstract.trim().length > 0`),
// and stores the text on the element for the popup to read. The multiplexer's
// ReadingPaneRenderer already delegates on `.abstract-indicator` and reads
// `data-abstract` (ReadingPaneRenderer.ts:424), so this card joins that seam by
// carrying the same class and attribute — no second handler.
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

// The inline block legacy caps at 200px in CSS (:23293-23295). Markdown-rendered,
// through the multiplexer's DOMPurify-backed `renderMarkdown` — the same sanitiser
// the notifications list uses, so an abstract cannot inject markup here either.
export function abstractBlock( abstract: string | undefined ): HTMLElement | null {
  if ( abstract === undefined || abstract.trim().length === 0 ) return null;
  const el = document.createElement( "div" );
  el.className = "action-required-abstract";
  el.appendChild( html`${ renderMarkdown( abstract ) }` );
  return el;
}

// Legacy's `buildPredictionHintSection` (notifications.js:23581-23656). Two shapes:
// a cold-start ghost box when the server sent no hint at all, and the warm box with
// the predicted value, the strategy label and — above the vote gate — the thumbs
// controls. The predicted value is rendered per response type, as legacy does
// (:23597-23635): yes_no title-cases the string, everything else prints it.
//
// `vote` is optional and follows this file's own idiom for the card's other
// integrations: boot supplies it, a storeless test omits it, and the controls then
// simply do not mount rather than mounting dead — this card is being built under a
// parity epic whose recurring defect is a painted control with no handler.
export function predictionHintBox(
  item : { id_hash: string; response_type: string; prediction_hint?: PredictionHint },
  vote : PredictionVoteIntegration | undefined,
): HTMLElement {
  const hint = item.prediction_hint;
  const root = document.createElement( "div" );
  if ( hint === undefined ) {
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
  const cast = vote?.getVote( item.id_hash );
  const controls = renderPredictionVoteControls(
    {
      notificationId : item.id_hash,
      confidencePct  : Math.round( hint.confidence * 100 ),
      ...( cast === undefined ? {} : { castVote: cast } ),
    },
    { onVote: ( dir ) => vote?.onVote( item.id_hash, dir ) },
  );
  if ( controls !== null ) root.appendChild( controls );
  return root;
}

// Legacy title-cases a yes_no prediction and prints every other type as-is
// (notifications.js:23597-23635).
/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line (notificationItem.ts:46 precedent).
function predictedText( responseType: string, value: unknown ): string {
  if ( responseType === "yes_no" && typeof value === "string" && value.length > 0 ) {
    return value.charAt( 0 ).toUpperCase() + value.slice( 1 );
  }
  return typeof value === "string" ? value : JSON.stringify( value ) ?? "";
}
