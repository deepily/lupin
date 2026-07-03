/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6b — TTS chrome template.
//
// AC2e safe-write invariant (per Pass 2 a1 in `09-phase6b-interactive-widgets-design.md`):
//   ALL DOM writes go through the `html` tagged template + `.textContent` / `.value`
//   only. NEVER use `.innerHTML =`, `rawHTML(`, or `.outerHTML =`.
//   This file is verified by AC2e grep test in templates_tts_chrome.test.ts.
//
// Per Q-B6 + Q-B7 + Q-B8 (design `09-phase6b-interactive-widgets-design.md`):
//   - 4 pane controls: Pause/Resume single toggle, Stop, Skip
//   - currentTrackName surfaced as `.tts-current-track` text
//   - queueLength surfaced as `.tts-queue-length` text
//   - `.is-playing-current` / `.is-paused-current` classes follow legacy
//     `notifications.css:4692-4712, 4718-4725` semantics
//
// WP3 (2026-07-02) — rich header transport (legacy `updateTTSQueueSection`):
//   - header text: "🔊 Playing: N" / "Paused: N" (manual pause) / "Paused: N
//     waiting" (focus mode); a `.paused` / `.focus-mode` modifier on the header
//   - Resume button (`.tts-btn-resume`) present ONLY in focus mode → onResume
//   - Clear-all button (`.tts-btn-clear-all`) disabled + hidden when N === 0,
//     else enabled → onClearAll
//   - the 6-state toggle/stop/skip matrix below is UNCHANGED
//
// desync-fix (2026-07-02, Tiberius ruling msg 193ae189): the "🔇 Nothing in the
// queue" empty panel is QUEUE-driven, NOT audio-idle-driven. renderTtsChrome
// short-circuits to the empty panel iff `opts.queueEmpty` (the renderer computes
// it as activeItem===null && pending empty). When the queue is NON-empty the
// chrome renders for ANY audio state — including `idle` (item queued but not yet
// speaking, the common state until the playback consumer 4f14d38f lands). This
// fixes the pre-fix bug where an idle-but-fed queue rendered the empty panel AND
// the cards at once (only latent because pre-F0-d the queue was always empty).
//
// State → control enable/disable matrix (drives HEADER/CONTROLS only; the
// empty-vs-populated decision is queueEmpty, above):
//   | state    | toggle | stop | skip |
//   |----------|--------|------|------|
//   | idle     |   ✗    |  ✗  |  ✗  |   (queue non-empty, nothing playing yet)
//   | decoding |   ✗    |  ✗  |  ✗  |
//   | playing  | "Pause"|  ✓  |  ✓  |
//   | paused   |"Resume"|  ✓  |  ✓  |
//   | ended    |   ✗    |  ✓  |  ✗  |
//   | error    |   ✗    |  ✓  |  ✗  |

import { html } from "../html";
import type { AudioPlaybackState } from "../../shared/types";

export interface TtsChromeHandlers {
  onPause()    : void;
  onResume()   : void;
  onStop()     : void;
  onSkip()     : void;
  // WP3 — empty the whole queue (Clear-all button). OPTIONAL: the button renders
  // count-gated regardless, but its click-listener is wired only when a handler
  // is supplied. WP4 provides it (→ TtsQueueStore.clear()); pre-WP4 callers omit
  // it, so the button is present but inert (never a misleading no-op call).
  onClearAll?(): void;
  // 70cbff3e — the focus Resume button (`.tts-btn-resume`, present only in focus
  // mode). DISTINCT from onResume: onResume unpauses the AUDIO (transport toggle);
  // onFocusResume exits FOCUS + rolls the queue (→ TtsQueueStore.resumeFocus()).
  // OPTIONAL, same inert-when-absent contract as onClearAll — pre-70cbff3e callers
  // never render the focus button (focusMode false) so they omit it harmlessly.
  onFocusResume?(): void;
}

export interface TtsChromeOpts {
  state              : AudioPlaybackState;
  queueLength        : number;
  // desync-fix — QUEUE-driven empty gate (activeItem===null && pending empty),
  // computed by the renderer. true → the empty panel; false → the chrome (for
  // ANY audio state). Decouples the empty-vs-populated decision from audio state.
  queueEmpty         : boolean;
  currentTrackName?  : string;
  // WP3 — focus mode: the queue is paused awaiting an action-required response.
  // The template is a PURE function of this flag; WHERE the flag lives (the §8.3
  // open question — TtsQueueStore vs a higher coordinator) is WP4's concern.
  focusMode?         : boolean;
}

interface ControlState {
  toggleEnabled : boolean;
  toggleLabel   : "Pause" | "Resume" | "—";
  toggleAction  : "pause" | "resume" | "noop";
  stopEnabled   : boolean;
  skipEnabled   : boolean;
}

// desync-fix: the empty panel is now QUEUE-driven (queueEmpty short-circuit), so
// these helpers see the FULL AudioPlaybackState — `idle` is reachable here when
// the queue is non-empty but nothing is speaking yet. idle → all three transport
// controls disabled (matrix row idle = ✗✗✗).
function deriveControlState(state: AudioPlaybackState): ControlState {
  switch (state) {
    case "idle":
      return { toggleEnabled: false, toggleLabel: "—",      toggleAction: "noop",   stopEnabled: false, skipEnabled: false };
    case "playing":
      return { toggleEnabled: true,  toggleLabel: "Pause",  toggleAction: "pause",  stopEnabled: true,  skipEnabled: true  };
    case "paused":
      return { toggleEnabled: true,  toggleLabel: "Resume", toggleAction: "resume", stopEnabled: true,  skipEnabled: true  };
    case "ended":
      return { toggleEnabled: false, toggleLabel: "—",      toggleAction: "noop",   stopEnabled: true,  skipEnabled: false };
    case "error":
      return { toggleEnabled: false, toggleLabel: "—",      toggleAction: "noop",   stopEnabled: true,  skipEnabled: false };
    case "decoding":
      return { toggleEnabled: false, toggleLabel: "—",      toggleAction: "noop",   stopEnabled: false, skipEnabled: false };
  }
}

function rootClass(state: AudioPlaybackState): string {
  // Per Q-B8 — port .is-playing-current / .is-paused-current verbatim.
  const base = "tts-chrome";
  if (state === "playing") return `${base} is-playing-current`;
  if (state === "paused")  return `${base} is-paused-current`;
  return base;
}

/**
 * The empty-state panel — legacy parity for `🔇 Nothing in the queue`
 * (`notifications.html:589+`, class `.tts-queue-empty-state`). desync-fix:
 * QUEUE-driven (rendered iff the item queue is empty), not audio-idle-driven.
 * Carries `data-state="idle"` (an empty queue means nothing is playing) + the
 * shared `data-testid` so E2E observability is uniform.
 */
function renderTtsEmpty(): HTMLElement {
  const root = document.createElement("div");
  root.className = "tts-chrome tts-chrome-empty";
  root.setAttribute("data-testid", "multiplexer-tts-chrome");
  root.setAttribute("data-state", "idle");
  root.appendChild(html`<div class="tts-queue-empty-state">🔇 Nothing in the queue</div>` as DocumentFragment);
  return root;
}

/**
 * Build the TTS chrome (pane controls + current-track + queue indicator).
 *
 * Requires:
 *   - `opts.state` is one of the six AudioPlaybackState values
 *   - `opts.queueLength` is non-negative
 *   - `handlers.onPause / onResume / onStop / onSkip` are functions
 *
 * Ensures:
 *   - Returned HTMLElement carries `.tts-chrome` (+ optional state class)
 *   - Toggle button reflects state-driven label/disabled per the matrix above
 *   - Header text follows the WP3 state machine (Playing / Paused / focus) with
 *     a `.paused` / `.focus-mode` modifier; Resume renders only in focus mode;
 *     Clear-all is disabled + hidden when the queue is empty
 *   - currentTrackName renders inside `.tts-current-track` only when present
 *   - All writes are safe per AC2e (no .innerHTML / rawHTML / .outerHTML)
 */
export function renderTtsChrome(
  opts     : TtsChromeOpts,
  handlers : TtsChromeHandlers,
): HTMLElement {
  // desync-fix: QUEUE-driven empty panel. Empty iff the item queue is empty
  // (activeItem===null && pending empty — computed by the renderer as
  // opts.queueEmpty), NOT iff audio is idle. A non-empty queue always renders the
  // chrome, even at idle (item queued, not yet speaking).
  if (opts.queueEmpty) return renderTtsEmpty();

  const ctl = deriveControlState(opts.state);
  const root = document.createElement("div");
  root.className = rootClass(opts.state);
  root.setAttribute("data-testid", "multiplexer-tts-chrome");
  root.setAttribute("data-state", opts.state);

  // currentTrackName line — rendered only when present (no element when absent
  // so empty/hidden state is observable via querySelector returning null).
  const trackBlock = opts.currentTrackName !== undefined && opts.currentTrackName !== ""
    ? html`<div class="tts-current-track">Playing: ${opts.currentTrackName}</div>`
    : html``;

  const queueStr = String(opts.queueLength);
  const focus    = opts.focusMode === true;

  // WP3 header state machine: focus mode → "Paused: N waiting" (queue held for an
  // action-required response); manual pause → "Paused: N"; else "🔊 Playing: N".
  // A `.focus-mode` / `.paused` modifier on the header carries the skin (WP7 CSS).
  // NOTE: focus rendering rides an ACTIVE state — the idle short-circuit above
  // still wins when nothing plays; that boundary + where `focusMode` is sourced
  // are the §8.3 open question WP4 resolves.
  const headerText = focus
    ? `Paused: ${queueStr} waiting`
    : opts.state === "paused"
      ? `Paused: ${queueStr}`
      : `🔊 Playing: ${queueStr}`;
  const headerClass = focus
    ? "tts-playing-header focus-mode"
    : opts.state === "paused"
      ? "tts-playing-header paused"
      : "tts-playing-header";

  // Focus Resume button — present ONLY in focus mode (querySelector null
  // otherwise, mirroring the currentTrackName idiom).
  const resumeBlock = focus
    ? html`<button type="button" class="tts-btn tts-btn-resume">Resume</button>`
    : html``;

  /* c8 ignore next 13 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every test that renders the chrome (Phase 6a jobCard.ts:251 precedent).
  const frag = html`
    <div class="${headerClass}">${headerText}</div>
    ${trackBlock}
    ${resumeBlock}
    <div class="tts-controls">
      <button type="button" class="tts-btn tts-btn-toggle" data-action="${ctl.toggleAction}">${ctl.toggleLabel}</button>
      <button type="button" class="tts-btn tts-btn-stop">Stop</button>
      <button type="button" class="tts-btn tts-btn-skip">Skip</button>
      <button type="button" class="tts-btn tts-btn-clear-all">Clear all</button>
    </div>
    <div class="tts-queue-length" data-queue-length="${queueStr}">Queued: ${queueStr}</div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const toggle = root.querySelector<HTMLButtonElement>(".tts-btn-toggle");
  const stop   = root.querySelector<HTMLButtonElement>(".tts-btn-stop");
  const skip   = root.querySelector<HTMLButtonElement>(".tts-btn-skip");

  // Apply enable/disable per state matrix.
  /* c8 ignore next */ // defensive: html`` always produces toggle button.
  if (toggle !== null) {
    toggle.disabled = !ctl.toggleEnabled;
    if (ctl.toggleAction === "pause")  toggle.addEventListener("click", () => handlers.onPause());
    if (ctl.toggleAction === "resume") toggle.addEventListener("click", () => handlers.onResume());
    // toggleAction === "noop": disabled, no listener attached.
  }
  /* c8 ignore next */ // defensive: html`` always produces stop button.
  if (stop !== null) {
    stop.disabled = !ctl.stopEnabled;
    if (ctl.stopEnabled) stop.addEventListener("click", () => handlers.onStop());
  }
  /* c8 ignore next */ // defensive: html`` always produces skip button.
  if (skip !== null) {
    skip.disabled = !ctl.skipEnabled;
    if (ctl.skipEnabled) skip.addEventListener("click", () => handlers.onSkip());
  }

  // 70cbff3e — focus Resume (present only in focus mode) → onFocusResume (exit
  // focus + roll the queue), DISTINCT from the transport toggle's onResume. Wired
  // only when a handler is supplied (inert-when-absent, mirroring onClearAll).
  const resume = root.querySelector<HTMLButtonElement>(".tts-btn-resume");
  if (resume !== null && handlers.onFocusResume !== undefined) {
    const onFocusResume = handlers.onFocusResume;
    resume.addEventListener("click", () => onFocusResume());
  }

  // WP3 + desync-fix — Clear-all: the chrome renders ONLY when the queue is
  // non-empty (queueEmpty short-circuits to the empty panel above), so Clear-all
  // is always enabled + shown here, and wired to onClearAll when supplied. (This
  // also fixes the old queueLength===0 gate, which wrongly disabled Clear-all for
  // an active-item-only queue — active head present, zero pending.)
  const clearAll = root.querySelector<HTMLButtonElement>(".tts-btn-clear-all");
  /* c8 ignore next */ // defensive: html`` always produces clear-all button.
  if (clearAll !== null) {
    clearAll.disabled = false;
    clearAll.hidden   = false;
    if (handlers.onClearAll !== undefined) {
      const onClearAll = handlers.onClearAll;
      clearAll.addEventListener("click", () => onClearAll());
    }
  }

  return root;
}
