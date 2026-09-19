/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6b — ActionRequiredRenderer.
//
// Owns the action-required pane after Phase 5's read-only handoff. On mount,
// claims the section via `root.dataset.phase6bOwner = "true"` (per Pass 2 A3
// Path A) so Phase 5's `NotificationsListRenderer.renderActionRequiredSection`
// short-circuits via the dataset guard.
//
// Lifecycle:
//   - mount(root) sets ownership FIRST, then renders interactive widgets for
//     each item in `actionRequiredStore.list()`. Existing read-only widgets
//     (carrying [data-id-hash]) are atomically replaced via element.replaceWith()
//     — single MutationObserver childList entry per widget (per AC2c).
//   - subscribes to `store_action_required_changed`:
//       * "tick" → updates `.action-required-countdown` text via `.textContent`
//                  ONLY (NO renderer-side RAF per Pass 2 a2; relies on store's
//                  1Hz setInterval at ActionRequiredStore.ts:291).
//       * any other changeKind → re-fetches item, rebuilds widget, atomic swap.
//   - unmount() unsubscribes, clears `dataset.phase6bOwner`, and is idempotent.
//
// State machine (renderer-side visual states, driven by store events):
//   pending     | full interactive widget + countdown
//   submitting  | controls disabled + "Submitting..." indicator
//   responded   | response read-back display
//   failed      | re-enabled interactive widget + .action-required-error-stripe
//   expired     | controls disabled + "Expired — default applied" message
//   cancelled   | "✓ Responded in another session" (360de81b; was a hidden tombstone)
// Every finished state is shown only for the store's grace period; the store then removes the item.
//
// 360de81b — ONE CARD AT A TIME (legacy renderActionRequiredNotification :22825). The body is an
// active slot holding ONE full widget — the store's first item — and a pending queue of minimized
// rows with #N badges for the rest (templates/actionRequiredQueueRow.ts). A change to a QUEUED item
// repaints the rows only, so a half-made choice in the active card survives. The multiple_choice
// stepper's position and saved answers are kept here per id, so a rebuild (submitting → failed)
// reopens the same question with the same ticks; they are forgotten when the item leaves the store.
//
// On submit click: dispatches store.respondAndAwait(), which is now the store's
// ONLY answer path — the optimistic store.respond() this note used to contrast
// against was DELETED (bcf15f08): it swallowed a rejected answer and left the UI
// reading "responded". Errors from the awaited promise are deliberately swallowed
// AT THE CLICK HANDLER, and that is not the same defect: the store fires a
// "failed" event which drives the failed-state visual, so the user-facing signal
// lives in the DOM rather than in the exception.

import type { EventBus } from "../shared/EventBus";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
  LupinEvent,
  StoreActionRequiredChangedPayload,
} from "../shared/types";
import {
  renderActionRequiredInteractive,
  type MultipleChoiceStep,
} from "./templates/actionRequiredInteractive";
import { renderActionRequiredQueueRow } from "./templates/actionRequiredQueueRow";
import { renderActionRequiredEmpty } from "./templates/actionRequiredReadOnly";
import { formatCountdown } from "./time";
import {
  renderSectionHeader,
  setSectionCollapsed,
  wireSectionCollapse,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";
import { scrollRevealElement } from "./scrollReveal";
import { createActionRequiredMic, type ActionRequiredMicHandler, type ActionRequiredRecorderLike } from "./actionRequiredMic";
import { recordingManager } from "../audio/recordingManager";
import { cancelResponseFor, countLiveActionRequired, isAwaitingActivation } from "../stores/ActionRequiredStore";
import { projectBadge, personaBadge, abstractIndicator, abstractBlock, predictionHintBox } from "./templates/actionRequiredChrome";
import type { PredictionVoteIntegration } from "./templates/predictionVoteControls";

// ---------------------------------------------------------------------------
// Public interfaces
// ---------------------------------------------------------------------------

export interface ActionRequiredStoreLike {
  /** Arrival order: the first item is the active card, the rest are queued. */
  list(): ReadonlyArray<ActionRequiredItem>;
  getById(idHash: string): ActionRequiredItem | undefined;
  respondAndAwait(idHash: string, response: ActionRequiredResponse): Promise<void>;
  /** A-2 #2f — the ⏸️; returns true when the card is now paused. */
  togglePause(idHash: string): boolean;
  /** A-1c2 — the stepper position lives on the store's item, so a repaint and a reload keep it. */
  recordStep(idHash: string, step: MultipleChoiceStep): void;
}

// Parity A-2 #2f — carbon copies of legacy's card header (`renderActionRequiredNotification`,
// `updatePauseButtonUI`, `showGracePeriodMessage`). The "(P)" names the key A-2 #2h wires.
export const AR_PAUSE_GLYPH    = "\u23F8\uFE0F";
export const AR_RESUME_GLYPH   = "\u25B6\uFE0F";
export const AR_PAUSE_TITLE    = "Pause timer and audio (P)";
export const AR_RESUME_TITLE   = "Resume timer and audio (P)";
export const AR_PAUSED_MESSAGE = "\u23F8\uFE0F Paused \u2013 5-minute grace period added";
// Parity A-2 #2g — the ✕. "(Esc)" names the key A-2 #2h wires.
export const AR_CANCEL_TITLE   = "Cancel and use default (Esc)";

/**
 * A-2 #2e — the share of the timeout still left, as legacy's `startCountdownTimer` draws it.
 *
 * Ensures:
 *   - returns `remainingMs / timeoutMs * 100` clamped to 0..100
 *   - returns 0 when `timeoutMs` is not positive, so the bar never divides by zero
 */
export function arProgressPercent(remainingMs: number, timeoutMs: number): number {
  if (timeoutMs <= 0) return 0;
  return Math.min(100, Math.max(0, (remainingMs / timeoutMs) * 100));
}

export interface ActionRequiredRendererStores {
  actionRequired: ActionRequiredStoreLike;
}

export interface ActionRequiredRenderer {
  /**
   * Mount onto `root`. Sets `root.dataset.phase6bOwner = "true"` BEFORE any
   * DOM write so Phase 5's NotificationsListRenderer short-circuits its
   * read-only path (Pass 2 A3 ownership claim).
   *
   * Throws Error("ActionRequiredRenderer already mounted") on second call
   * without intervening unmount() (mirrors Phase 6a F-26 contract).
   */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe all listeners + clear ownership flag. Idempotent. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

export interface ActionRequiredRendererOptions {
  eventBus : EventBus;
  stores   : ActionRequiredRendererStores;
  // Parity A-2 #2b: un-hide the section through the toolbar, which saves the
  // visibility and re-lights the ⚠️ button. Boot passes the toolbar renderer's
  // showSection; a test that does not care about the toolbar omits it.
  revealSection? : () => void;
  // Parity A-2 #2j/#2k/#2l — the card 🎤s. Production uses the recordingManager singleton and
  // boot's cached token; a test injects a recorder double.
  recorder?      : ActionRequiredRecorderLike;
  getAuthToken?  : () => string | null;
  // Parity A-2 #2m — the thumbs-vote bridge for the card's prediction hint. Boot
  // threads the PredictionVoteStore in; a storeless harness omits it and the vote
  // controls do not mount, rather than mounting with no handler.
  predictionVote? : PredictionVoteIntegration;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class ActionRequiredRendererImpl implements ActionRequiredRenderer {
  private readonly bus    : EventBus;
  private readonly stores : ActionRequiredRendererStores;
  private readonly revealSection : ( () => void ) | undefined;
  private readonly onMic         : ActionRequiredMicHandler;
  // Typed text per card, keyed by each field's `data-draft`. Legacy never rebuilds a card on a
  // failed submit; it re-enables the controls in place (submitResponse's catch,
  // notifications.js:24481-24488), so what the operator typed is still there to retry. Here the
  // card is rebuilt for "submitting" and again for "failed", so the text is saved when a card is
  // swapped out and put back when the same card is rebuilt interactive. Without it a retry sent
  // the open_ended DEFAULT, which #2k puts in the box, instead of the typed answer.
  private readonly drafts = new Map<string, Record<string, string>>();
  private readonly unsubscribers: Array<() => void> = [];

  private root    : HTMLElement | null = null;
  // Lane 0a: the `.section-content` body wrapper (all widget DOM lands here, so
  // the persistent `.section-header` bar survives repaints) + the header handle
  // (count chip) + the collapse-listener teardown.
  private content : HTMLElement | null = null;
  private header  : SectionHeaderHandle | null = null;
  private collapseOff: ( () => void ) | null = null;
  private mounted = false;
  // 360de81b — the two halves of `content`. The stepper position lives on the store's item (A-1c2).
  private slot    : HTMLElement | null = null;
  private queue   : HTMLElement | null = null;
  private readonly predictionVote : PredictionVoteIntegration | undefined;
  // A-2 #2h — the detach for the document-level Y/N/C/P/Esc shortcuts, or null when
  // they are not attached. Doubles as legacy's `keyboardListenerActive` latch.
  private keyboardOff : (() => void) | null = null;

  constructor(opts: ActionRequiredRendererOptions) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
    this.revealSection = opts.revealSection;
    this.predictionVote = opts.predictionVote;
    this.onMic = createActionRequiredMic(
      /* c8 ignore next */ // production-default fallback: the recordingManager singleton; tests inject a recorder double.
      opts.recorder ?? recordingManager,
      opts.getAuthToken ?? (() => null),
    );
  }

  mount(root: HTMLElement): void {
    if (this.mounted) {
      throw new Error("ActionRequiredRenderer already mounted");
    }
    this.mounted = true;
    this.root = root;
    // Pass 2 A3 — claim ownership BEFORE any DOM write so a concurrent Phase 5
    // renderActionRequiredSection() call sees the flag and bails.
    root.dataset.phase6bOwner = "true";
    this.attachKeyboardListener();

    // Lane 0a — the uniform `.section-header` bar (legacy: "⚠️ Action Required:
    // <count>", notifications.html:565) + a `.section-content` body wrapper. The
    // header is a persistent sibling; every render targets `this.content`.
    const header = renderSectionHeader( {
      icon   : "⚠️",
      title  : "Action Required",
      testid : "multiplexer-action-required-header",
    } );
    this.header  = header;
    const content = document.createElement( "div" );
    content.className = "section-content";
    content.setAttribute( "data-testid", "multiplexer-action-required-content" );
    const slot = document.createElement( "div" );
    slot.className = "action-required-active-slot";
    slot.setAttribute( "data-testid", "multiplexer-action-required-active-slot" );
    const queue = document.createElement( "div" );
    queue.className = "action-required-pending-queue";
    queue.setAttribute( "data-testid", "multiplexer-action-required-pending-queue" );
    // Absorb any pre-existing Phase-5 read-only widgets (rendered directly into
    // the section before 6b claimed ownership) INTO the active slot, so the
    // subsequent renderAll swaps the active one in place via replaceWith (AC2c
    // atomic read-only→interactive swap) rather than discarding + re-appending it.
    slot.append( ...Array.from( root.childNodes ) );
    content.append( slot, queue );
    this.content = content;
    this.slot    = slot;
    this.queue   = queue;
    root.replaceChildren( header.header, content );
    // Session-only collapse on the section root (07 §3.A U-A3).
    this.collapseOff = wireSectionCollapse( root, header );

    this.renderAll();

    this.unsubscribers.push(
      this.bus.on<StoreActionRequiredChangedPayload>(
        "store_action_required_changed",
        (e) => this.onChange(e),
      ),
    );
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;
    // A-2 #2h — the document-level shortcuts go with the mount that attached them.
    // Legacy never detaches (its `keyboardListenerActive` latch is one-way, and the
    // page owns the listener for its lifetime); the multiplexer mounts and unmounts,
    // so a listener left behind would answer keys for a torn-down card.
    if (this.keyboardOff !== null) {
      this.keyboardOff();
      this.keyboardOff = null;
    }
    if (this.collapseOff !== null) {
      this.collapseOff();
      this.collapseOff = null;
    }
    if (this.root !== null) {
      delete this.root.dataset.phase6bOwner;
      // L2 (mux MVP-finish): unmount-at-0 boundary edge. Once ownership is
      // released, Phase-5 read-only will NOT repaint until the next AR event,
      // so if the section is empty at teardown the outgoing Phase-6b path owns
      // painting `#action-required-empty` — never leave a blank panel. Lane 0a:
      // the whole section (header + content) is cleared on teardown so ownership
      // returns cleanly to the Phase-5 read-only path.
      if (this.stores.actionRequired.list().length === 0) {
        this.root.replaceChildren(renderActionRequiredEmpty());
      } else {
        this.root.replaceChildren();
      }
      this.root = null;
    }
    this.content = null;
    this.header  = null;
    this.slot    = null;
    this.queue   = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if (this.mounted) this.renderAll();
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  private renderAll(): void {
    this.reconcile(null);
  }

  // 360de81b — paint the section from the store: the first item in the active slot, the rest as
  // queued rows. `changedId` is the item a store event named, or null for a full render; the
  // active card is rebuilt only when it is new or it is the item that changed.
  private reconcile(changedId: string | null): void {
    /* c8 ignore next */ // defensive: reconcile runs only while mounted; content/slot/queue are set in mount() and nulled in unmount() after the subscription is detached.
    if (this.content === null || this.slot === null || this.queue === null) return;
    const items = this.stores.actionRequired.list();
    // A card that has left the store takes its typed text with it.
    for (const id of Array.from(this.drafts.keys())) {
      if (!items.some((it) => it.id_hash === id)) this.drafts.delete(id);
    }
    // Parity A-2 #2c — only cards still owed an answer; a finished card lingering for its
    // grace period is on screen but no longer waiting. The empty panel still keys on the
    // whole list, so a lingering card is shown rather than replaced by "No pending actions".
    this.updateCount(countLiveActionRequired(items));
    // L2 (mux MVP-finish): count===0 → the shared `✓ No pending actions` panel.
    if (items.length === 0) {
      this.slot.replaceChildren();
      this.content.replaceChildren(renderActionRequiredEmpty());
      return;
    }
    // Leaving the empty state: put the slot and the queue back (this also drops the empty panel).
    if (this.slot.parentNode !== this.content) this.content.replaceChildren(this.slot, this.queue);

    // Parity A-2 #2d — a first card waiting for TTS is not active yet: the slot stays empty and it
    // shows as queued row #1, as legacy's deferred arrival does (renderMinimizedNotificationDOM
    // at position 1, notifications.js:21782-21784).
    if (isAwaitingActivation(items[0]!)) {
      this.slot.replaceChildren();
      this.queue.replaceChildren(...items.map((item, i) => renderActionRequiredQueueRow(item, i + 1)));
      return;
    }
    const active  = items[0]!;
    const current = this.slot.firstElementChild as HTMLElement | null;
    if (changedId === null || changedId === active.id_hash || current?.dataset.idHash !== active.id_hash) {
      const existing = this.slot.querySelector<HTMLElement>(`[data-id-hash="${cssEscape(active.id_hash)}"]`);
      if (existing !== null) this.saveDrafts(active.id_hash, existing);
      const widget   = this.buildWidgetFor(active);
      if (existing !== null) {
        // Atomic swap — single MutationObserver childList entry per AC2c.
        existing.replaceWith(widget);
      } else {
        this.slot.appendChild(widget);
      }
      for (const child of Array.from(this.slot.children)) {
        if (child !== widget) child.remove();
      }
      // Parity A-2 #2k — voice first: a card that has just taken the slot focuses its 🎤, as
      // legacy's render does (notifications.js:23424-23425). A rebuild of the same card does not.
      if (current?.dataset.idHash !== active.id_hash) {
        widget.querySelector<HTMLElement>("[data-autofocus]")?.focus({ preventScroll: true });
      }
    }
    this.queue.replaceChildren(...items.slice(1).map((item, i) => renderActionRequiredQueueRow(item, i + 1)));
  }

  // Lane 0a — the header count chip reflects the number of action-required items.
  private updateCount(n: number): void {
    /* c8 ignore next */ // defensive: header is set/nulled in lockstep with content, so it is non-null whenever renderAll/onChange run.
    if (this.header !== null) this.header.setCount(n);
  }

  private buildWidgetFor(item: ActionRequiredItem): HTMLElement {
    switch (item.state) {
      case "pending":
      case "failed":
        return this.buildInteractiveWidget(item);
      case "submitting":
        return this.buildSubmittingWidget(item);
      case "responded":
        return this.buildRespondedWidget(item);
      case "expired":
        return this.buildExpiredWidget(item);
      case "cancelled":
        return this.buildCancelledWidget(item);
    }
  }

  /** Save the typed text of `widget`'s draft fields, unless it has none (a submitting card). */
  private saveDrafts(idHash: string, widget: HTMLElement): void {
    const fields = Array.from(widget.querySelectorAll<HTMLInputElement>("[data-draft]"));
    if (fields.length === 0) return;
    const saved: Record<string, string> = {};
    for (const field of fields) saved[field.dataset.draft!] = field.value;
    this.drafts.set(idHash, saved);
  }

  /**
   * Put a card's saved text back into its rebuilt fields.
   *
   * Ensures:
   *   - each field whose key was saved gets that value and an `input` event, so validation
   *     (open_ended Submit) sees it
   *   - a restored non-blank comment reopens its row, so no hidden text rides with the answer
   */
  private restoreDrafts(idHash: string, widget: HTMLElement): void {
    const saved = this.drafts.get(idHash);
    if (saved === undefined) return;
    for (const field of Array.from(widget.querySelectorAll<HTMLInputElement>("[data-draft]"))) {
      const value = saved[field.dataset.draft!];
      if (value === undefined) continue;
      field.value = value;
      field.dispatchEvent(new Event("input", { bubbles: true }));
      if (value.trim().length > 0) field.closest(".yes-no-comment-container")?.classList.add("expanded");
    }
  }

  private buildInteractiveWidget(item: ActionRequiredItem): HTMLElement {
    const widget = renderActionRequiredInteractive(item, {
      onSubmit : (response) => { void this.handleSubmit(item.id_hash, response); },
      onStep   : (step) => { this.stores.actionRequired.recordStep(item.id_hash, step); },
      onMic    : this.onMic,
    }, item.step);
    this.restoreDrafts(item.id_hash, widget);
    // A-2 #2f — the header legacy's card opens with: the ✕, then the ⏸️ and the timer
    // right-aligned in `.action-required-timer-controls`. The chrome badges (A-2 #2m) join it.
    const header   = document.createElement("div");
    header.className = "action-required-header";
    // A-2 #2g — the ✕ opens the header and answers with the default through the ordinary
    // answer path, so a refusal lands in "failed" and the card stays retryable.
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "action-required-cancel-btn";
    cancelBtn.title = AR_CANCEL_TITLE;
    cancelBtn.textContent = "\u2715";
    cancelBtn.addEventListener("click", () => { void this.handleSubmit(item.id_hash, cancelResponseFor(item)); });
    header.appendChild(cancelBtn);
    const controls = document.createElement("div");
    controls.className = "action-required-timer-controls";
    // A-2 #2m — legacy's right-cluster opens with the 📋 then the persona badge,
    // both BEFORE the ⏸️ (notifications.js:23321-23325). Each returns null when the
    // server omitted its field, and a null is simply not appended.
    const indicator = abstractIndicator(item.abstract);
    if (indicator !== null) controls.appendChild(indicator);
    const persona = personaBadge(item.voice_persona);
    if (persona !== null) controls.appendChild(persona);
    const pauseBtn = document.createElement("button");
    pauseBtn.type = "button";
    pauseBtn.className = "action-required-pause-btn";
    pauseBtn.addEventListener("click", () => { this.stores.actionRequired.togglePause(item.id_hash); });
    controls.appendChild(pauseBtn);
    header.appendChild(controls);
    widget.prepend(header);
    // The active card has always been activated by the store, so its expiry is set.
    /* c8 ignore next */ // defensive: since A-2 #2d an unstarted pending card draws as a queue row (reconcile), and only a card in the slot can be answered into submitting/failed, so a null expiry never reaches here.
    const expiresAt = item.expires_at ?? Date.now() + item.timeout_seconds * 1000;
    const pausedAt  = item.paused_at ?? null;
    const asOf      = pausedAt === null ? Date.now() : pausedAt;
    this.appendCountdown(controls, expiresAt, asOf);
    // A-2 #2e — legacy's draining bar sits under the message and above the answer controls.
    // Every interactive template opens with the prompt, so the bar always has its anchor.
    const bar = document.createElement("div");
    bar.className = "action-required-progress-bar";
    bar.setAttribute("data-timeout-ms", String(item.timeout_seconds * 1000));
    const fill = document.createElement("div");
    fill.className = "action-required-progress-fill";
    bar.appendChild(fill);
    // A-2 #2m — the [PROJECT] badge prefixes legacy's title (notifications.js:23327).
    // The multiplexer's card has no separate title element: the prompt IS the title,
    // so the badge goes in front of its text rather than into a title div that does
    // not exist here.
    const promptEl = widget.querySelector(".action-required-prompt")!;
    const badge    = projectBadge(item.sender_id);
    if (badge !== null) promptEl.prepend(badge, " ");
    // A-2 #2m — the inline abstract block sits under the prompt, and legacy's
    // prediction hint under that (notifications.js:23293-23297). Both land before the
    // draining bar is inserted, so the bar keeps its position directly above the
    // answer controls (A-2 #2e).
    const absBlock = abstractBlock(item.abstract);
    if (absBlock !== null) promptEl.after(absBlock);
    (absBlock ?? promptEl).after(predictionHintBox(item, this.predictionVote));
    promptEl.after(bar);
    paintProgress(bar, Math.max(0, expiresAt - asOf));
    applyPausedUi(widget, pausedAt !== null);
    if (item.state === "failed") {
      this.appendErrorStripe(widget);
    }
    return widget;
  }

  private buildSubmittingWidget(item: ActionRequiredItem): HTMLElement {
    const widget = document.createElement("div");
    widget.className = "action-required-widget action-required-widget-submitting";
    widget.setAttribute("data-id-hash", item.id_hash);
    widget.setAttribute("data-state", "submitting");
    widget.setAttribute("data-testid", "multiplexer-action-required");
    const prompt = document.createElement("div");
    prompt.className = "action-required-prompt";
    prompt.textContent = item.prompt;
    widget.appendChild(prompt);
    const msg = document.createElement("div");
    msg.className = "action-required-submitting-msg";
    msg.textContent = "Submitting...";
    widget.appendChild(msg);
    return widget;
  }

  private buildRespondedWidget(item: ActionRequiredItem): HTMLElement {
    const widget = document.createElement("div");
    widget.className = "action-required-widget action-required-widget-responded";
    widget.setAttribute("data-id-hash", item.id_hash);
    widget.setAttribute("data-state", "responded");
    widget.setAttribute("data-testid", "multiplexer-action-required");
    const prompt = document.createElement("div");
    prompt.className = "action-required-prompt";
    prompt.textContent = item.prompt;
    widget.appendChild(prompt);
    const msg = document.createElement("div");
    msg.className = "action-required-responded-msg";
    msg.textContent = `Responded: ${formatResponse(item.response)}`;
    widget.appendChild(msg);
    return widget;
  }

  private buildExpiredWidget(item: ActionRequiredItem): HTMLElement {
    const widget = document.createElement("div");
    widget.className = "action-required-widget action-required-widget-expired";
    widget.setAttribute("data-id-hash", item.id_hash);
    widget.setAttribute("data-state", "expired");
    widget.setAttribute("data-testid", "multiplexer-action-required");
    const prompt = document.createElement("div");
    prompt.className = "action-required-prompt";
    prompt.textContent = item.prompt;
    widget.appendChild(prompt);
    const msg = document.createElement("div");
    msg.className = "action-required-expired-msg";
    msg.textContent = "Expired — default applied";
    widget.appendChild(msg);
    return widget;
  }

  private buildCancelledWidget(item: ActionRequiredItem): HTMLElement {
    // 360de81b: answered in another session — shown for the store's 1.5 s grace period, then the
    // store removes the item (legacy handleNotificationResponded :24519-24560). Legacy appends the
    // other session's answer; this card does not (named in the parity doc).
    const widget = document.createElement("div");
    widget.className = "action-required-widget action-required-widget-cancelled";
    widget.setAttribute("data-id-hash", item.id_hash);
    widget.setAttribute("data-state", "cancelled");
    widget.setAttribute("data-testid", "multiplexer-action-required");
    const prompt = document.createElement("div");
    prompt.className = "action-required-prompt";
    prompt.textContent = item.prompt;
    widget.appendChild(prompt);
    const msg = document.createElement("div");
    msg.className = "action-required-cancelled-msg";
    msg.textContent = "✓ Responded in another session";
    widget.appendChild(msg);
    return widget;
  }

  // `asOf` is now for a running card and the pause instant for a paused one, whose time is frozen.
  private appendCountdown(widget: HTMLElement, expiresAt: number, asOf: number): void {
    const span = document.createElement("span");
    span.className = "action-required-countdown";
    span.setAttribute("data-countdown", String(expiresAt));
    const remaining = Math.max(0, expiresAt - asOf);
    span.textContent = `⏱ ${formatCountdown(remaining)}`;
    widget.appendChild(span);
  }

  private appendErrorStripe(widget: HTMLElement): void {
    const stripe = document.createElement("div");
    stripe.className = "action-required-error-stripe";
    stripe.setAttribute("role", "alert");
    stripe.textContent = "Submit failed — please retry";
    widget.appendChild(stripe);
  }

  // -------------------------------------------------------------------------
  // Submit handler — Pass 2 A1: respondAndAwait, NOT optimistic respond
  // -------------------------------------------------------------------------

  private async handleSubmit(idHash: string, response: ActionRequiredResponse): Promise<void> {
    try {
      await this.stores.actionRequired.respondAndAwait(idHash, response);
      // Success: store fires "responded" event → onChange() rebuilds the widget.
    } catch {
      // Failure: store fires "failed" event → onChange() rebuilds with the
      // failed visual (re-enabled controls + error stripe). The thrown error
      // is intentionally swallowed here to avoid an unhandled rejection at
      // the click-handler boundary; the user-facing signal lives in the DOM.
    }
  }

  // -------------------------------------------------------------------------
  // Store event handler
  // -------------------------------------------------------------------------

  private onChange(e: LupinEvent<StoreActionRequiredChangedPayload>): void {
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount BEFORE content is nulled.
    if (this.content === null) return;
    const { changeKind, id_hash, countdownMs } = e.payload;
    if (changeKind === "tick") {
      // Per Pass 2 a2 — countdown driven by store's 1Hz tick events; renderer
      // uses .textContent only, NEVER requestAnimationFrame. (No count change.)
      this.updateCountdown(id_hash, countdownMs ?? 0);
      return;
    }
    if (changeKind === "paused" || changeKind === "resumed") {
      // A-2 #2f — toggled IN PLACE, as legacy's updatePauseButtonUI does. A rebuild would
      // discard a half-typed answer, and a pause is exactly when an operator stops to type.
      const widget = this.activeWidget(id_hash);
      if (widget === null) return;
      applyPausedUi(widget, changeKind === "paused");
      this.updateCountdown(id_hash, countdownMs ?? 0);
      return;
    }
    // Any other changeKind → repaint. The stepper position rides on the store's item (A-1c2), so an
    // item that left the store took it along, and the same id arriving again starts at question 1.
    this.reconcile(id_hash);
    if (changeKind === "added") this.autoReveal(id_hash);
    else if (changeKind === "activated") void scrollRevealElement(this.root);
  }

  // Parity A-2 #2b (Phase 2 A3 B6). Legacy's ensureActionRequiredExpanded
  // (notifications.js:21552-21576) runs on every arrival: un-hide (saving the
  // visibility and re-lighting the toolbar button) and un-collapse. The scroll
  // follows legacy's render of the ACTIVE card (:23204-23210), so a prompt that
  // queues behind another does not move the page; "activated" scrolls when it
  // later takes the slot. The scroll goes through the shared helper (plan §1).
  private autoReveal(idHash: string): void {
    if (this.revealSection !== undefined) this.revealSection();
    setSectionCollapsed(this.root!, this.header!, false);
    // A-2 #2d — a card waiting for TTS is not the active card yet; its "activated" scrolls.
    const head = this.stores.actionRequired.list()[0];
    if (head?.id_hash === idHash && !isAwaitingActivation(head)) void scrollRevealElement(this.root);
  }

  // A-2 #2h — legacy's document-level shortcuts (notifications.js:25892-25947).
  // Two listeners, because Escape does not raise `keypress` in many browsers:
  //   keypress — P toggles pause for any response type; then, on the OLDEST card
  //              only and only when it is yes_no: C toggles the comment row, Y and
  //              N answer.
  //   keydown  — Escape cancels the active card.
  // Both are suppressed while the operator is typing: legacy tests
  // `activeElement.tagName` against INPUT/TEXTAREA (:25902, :25937), so a keystroke
  // meant for the comment box or the open_ended field never answers the card.
  //
  // EVERY SHORTCUT CLICKS THE CARD'S OWN CONTROL rather than calling the store or
  // rebuilding a response. That is deliberate: the yes_no buttons carry the comment
  // into the answer through `withComment` (#2j, and b51dc7ea fixed a retry that lost
  // it), so a keyboard path that built its own `{ value }` would silently drop a typed
  // comment — the same defect, re-introduced one keystroke to the left. One mechanism
  // per verb means the key and the click cannot disagree.
  private attachKeyboardListener(): void {
    /* c8 ignore next */ // defensive: mount() throws on a second mount, so the latch cannot already be set.
    if (this.keyboardOff !== null) return;

    const typing = (): boolean => {
      const el = document.activeElement;
      return el !== null && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
    };
    // Legacy reads the FIRST (oldest) card, not the focused one (:25912-25913).
    const headWidget = (): { item: ActionRequiredItem; el: HTMLElement } | null => {
      const item = this.stores.actionRequired.list()[0];
      if (item === undefined) return null;
      const el = this.activeWidget(item.id_hash);
      return el === null ? null : { item, el };
    };
    const click = (el: HTMLElement, selector: string): void => {
      el.querySelector<HTMLElement>(selector)?.click();
    };

    const onKeyPress = (e: KeyboardEvent): void => {
      if (typing()) return;
      const head = headWidget();
      if (head === null) return;
      const key = e.key.toLowerCase();
      // P is the one shortcut legacy runs for every response type, before the
      // yes_no narrowing below (:25905-25909).
      if (key === "p") {
        e.preventDefault();
        click(head.el, ".action-required-pause-btn");
        return;
      }
      if (head.item.response_type !== "yes_no") return;
      if (key === "c") {
        e.preventDefault();
        // The hint IS the toggle (#2j wires it), so C and a click share one path.
        click(head.el, ".yes-no-comment-hint");
        return;
      }
      if (key === "y") click(head.el, ".action-required-btn-yes");
      else if (key === "n") click(head.el, ".action-required-btn-no");
    };

    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      // Legacy lets Escape out of a text input reach the recorder instead (:25936-25939).
      if (typing()) return;
      const head = headWidget();
      if (head === null) return;
      e.preventDefault();
      click(head.el, ".action-required-cancel-btn");
    };

    document.addEventListener("keypress", onKeyPress);
    document.addEventListener("keydown", onKeyDown);
    this.keyboardOff = () => {
      document.removeEventListener("keypress", onKeyPress);
      document.removeEventListener("keydown", onKeyDown);
    };
  }

  /** The active slot's card for `idHash`, or null when that card is not in the slot. */
  private activeWidget(idHash: string): HTMLElement | null {
    /* c8 ignore next */ // defensive: callers run past onChange's content-null guard; slot is set/nulled in lockstep with content.
    if (this.slot === null) return null;
    return this.slot.querySelector<HTMLElement>(`[data-id-hash="${cssEscape(idHash)}"]`);
  }

  private updateCountdown(idHash: string, countdownMs: number): void {
    // Only the active card counts down, so only the slot is searched; a queued row has no countdown.
    const widget = this.activeWidget(idHash);
    if (widget === null) return;   // tick for a card that is not in the slot — silently skip
    const countdown = widget.querySelector<HTMLElement>(".action-required-countdown");
    if (countdown === null) return; // widget exists but has no countdown (e.g. submitting/responded/expired states)
    countdown.textContent = `⏱ ${formatCountdown(countdownMs)}`;
    // The bar is built beside the countdown, so a card with one has the other.
    paintProgress(widget.querySelector<HTMLElement>(".action-required-progress-bar")!, countdownMs);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Drain a card's progress bar — legacy `startCountdownTimer`'s progress half.
 *
 * Ensures:
 *   - the fill's width is `arProgressPercent` of the bar's `data-timeout-ms`
 *   - the fill carries `.danger` at ≤ 25%, else `.warning` at ≤ 50%, else neither
 */
function paintProgress(bar: HTMLElement, remainingMs: number): void {
  const fill    = bar.firstElementChild as HTMLElement;
  const percent = arProgressPercent(remainingMs, Number(bar.getAttribute("data-timeout-ms")));
  fill.style.width = `${percent}%`;
  fill.classList.toggle("danger", percent <= 25);
  fill.classList.toggle("warning", percent > 25 && percent <= 50);
}

/**
 * Paint a card paused or running — legacy `updatePauseButtonUI`, `updatePausedTimerDisplay`
 * and `showGracePeriodMessage` in one place, so a rebuild and an in-place toggle agree.
 *
 * Ensures:
 *   - the ⏸️ button reads ▶️ / "Resume…" when paused and ⏸️ / "Pause…" otherwise, and carries
 *     `.paused` iff paused; the countdown and the card carry `.paused` iff paused
 *   - exactly one `.grace-period-message` sits straight after the header iff paused
 *   - a card without the header (a submitting/finished card) only toggles its own class
 */
function applyPausedUi(widget: HTMLElement, paused: boolean): void {
  widget.classList.toggle("paused", paused);
  widget.querySelector(".action-required-countdown")?.classList.toggle("paused", paused);
  widget.querySelector(".action-required-progress-fill")?.classList.toggle("paused", paused);
  const btn = widget.querySelector<HTMLButtonElement>(".action-required-pause-btn");
  if (btn !== null) {
    btn.textContent = paused ? AR_RESUME_GLYPH : AR_PAUSE_GLYPH;
    btn.title       = paused ? AR_RESUME_TITLE : AR_PAUSE_TITLE;
    btn.classList.toggle("paused", paused);
  }
  const existing = widget.querySelector(".grace-period-message");
  if (!paused) {
    existing?.remove();
    return;
  }
  const header = widget.querySelector(".action-required-header");
  if (existing !== null || header === null) return;
  const msg = document.createElement("div");
  msg.className = "grace-period-message";
  msg.textContent = AR_PAUSED_MESSAGE;
  header.after(msg);
}

function formatResponse(response: ActionRequiredResponse | undefined): string {
  if (response === undefined) return "(no response recorded)";
  if (typeof response === "string") return response;
  // { answers: { <header>: value } } — multiple_choice / open_ended_batch
  return Object.entries(response.answers)
    .map(([header, value]) => `${header}: ${typeof value === "string" ? value : value.join(", ")}`)
    .join("; ");
}

/* c8 ignore start */ // CSS.escape polyfill — defensive cross-environment helper (production browsers + happy-dom + Node). c8 reports phantom branches inside the regex character class + the optional-chaining short-circuits which depend on the runtime CSS provider; the cssEscape-fallback test exercises both arms but c8's V8 instrumentation of regex/optional-chaining branches is implementation-dependent. Mirrors NotificationsListRenderer.ts:423 (same defensive helper, same ignore).
function cssEscape(value: string): string {
  if (typeof globalThis !== "undefined" && typeof (globalThis as { CSS?: { escape?: (s: string) => string } }).CSS?.escape === "function") {
    return (globalThis as { CSS: { escape: (s: string) => string } }).CSS.escape(value);
  }
  return value.replace(/[^a-zA-Z0-9_-]/g, (m) => "\\" + m);
}
/* c8 ignore stop */

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createActionRequiredRenderer(opts: ActionRequiredRendererOptions): ActionRequiredRenderer {
  return new ActionRequiredRendererImpl(opts);
}
