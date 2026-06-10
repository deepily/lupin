/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP14 — prediction-hint vote controls template (F8).
//
// Ports legacy notifications.js:16903-16918 (`_buildPredictionVoteControls`)
// to a multiplexer-idiomatic safe-write template with DELEGATED listeners
// (the legacy used inline `onclick="window.notificationsUI.votePrediction(...)"`
// against the dead-ish global — the F8 spec mandates no inline onclick).
//
// Gate (parity): controls render ONLY when a notification id is present AND the
// hint confidence ≥ PREDICTION_VOTE_MIN_PCT (50%). Below threshold → null, so
// the user does not train on noise.
//
// The 👍🏼/👎🏼 use the medium-light skin tone (U+1F3FC — Rick's preference, NOT
// default yellow), matching the legacy glyphs verbatim.
//
// Safe-write invariant: ALL DOM writes via the `html` tagged template +
// `.textContent` only. NEVER `.innerHTML =`, `rawHTML(`, `.outerHTML =`.

import { html } from "../html";
import { PREDICTION_VOTE_MIN_PCT } from "../../stores/PredictionVoteStore";
import type { PredictionVoteDir } from "../../shared/types";

export interface PredictionVoteHandlers {
  onVote( dir: PredictionVoteDir ): void;
}

export interface PredictionVoteOpts {
  notificationId : string;
  confidencePct  : number;
  /** A previously-cast vote — highlights the chosen button + marks `.voted`. */
  castVote?      : PredictionVoteDir;
}

/**
 * Build the thumbs up/down vote controls for a prediction hint.
 *
 * Requires:
 *   - `handlers.onVote` is a function
 *
 * Ensures:
 *   - Returns null when `notificationId` is empty OR confidence < 50% (gate)
 *   - Otherwise returns an HTMLElement `.prediction-hint-vote` with two
 *     delegated-listener buttons (`.prediction-vote-up` / `.prediction-vote-down`)
 *   - When `castVote` is set, the root carries `.voted` and the matching button
 *     carries `.selected`
 *   - No inline onclick; all writes safe (no .innerHTML / rawHTML / .outerHTML)
 */
export function renderPredictionVoteControls(
  opts     : PredictionVoteOpts,
  handlers : PredictionVoteHandlers,
): HTMLElement | null {
  if ( !opts.notificationId ) return null;
  if ( Number( opts.confidencePct ) < PREDICTION_VOTE_MIN_PCT ) return null;

  const root = document.createElement( "div" );
  root.className = "prediction-hint-vote";
  root.setAttribute( "data-testid", "prediction-hint-vote" );
  if ( opts.castVote !== undefined ) root.classList.add( "voted" );

  /* c8 ignore next 8 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders the controls (ttsChrome.ts:105 precedent).
  const frag = html`
    <button type="button" class="prediction-vote-btn prediction-vote-up"
            data-testid="prediction-vote-up"
            title="Good prediction — reinforce it">👍🏼</button>
    <button type="button" class="prediction-vote-btn prediction-vote-down"
            data-testid="prediction-vote-down"
            title="Bad prediction — steer away from it">👎🏼</button>
  ` as DocumentFragment;
  root.appendChild( frag );

  const up   = root.querySelector<HTMLButtonElement>( ".prediction-vote-up" );
  const down = root.querySelector<HTMLButtonElement>( ".prediction-vote-down" );

  /* c8 ignore next */ // defensive: html`` always produces the up button.
  if ( up !== null ) {
    up.addEventListener( "click", () => handlers.onVote( "up" ) );
    if ( opts.castVote === "up" ) up.classList.add( "selected" );
  }
  /* c8 ignore next */ // defensive: html`` always produces the down button.
  if ( down !== null ) {
    down.addEventListener( "click", () => handlers.onVote( "down" ) );
    if ( opts.castVote === "down" ) down.classList.add( "selected" );
  }

  return root;
}
