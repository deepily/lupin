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
//   cancelled   | widget removed from DOM
//
// On submit click: dispatches store.respondAndAwait() — NOT the optimistic
// store.respond() — per Pass 2 A1. Errors from the awaited promise are
// silently swallowed at the click handler because the store fires a "failed"
// event that drives the failed-state visual transition.

import type { EventBus } from "../shared/EventBus";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
  LupinEvent,
  StoreActionRequiredChangedPayload,
} from "../shared/types";
import { renderActionRequiredInteractive } from "./templates/actionRequiredInteractive";
import { formatCountdown } from "./time";

// ---------------------------------------------------------------------------
// Public interfaces
// ---------------------------------------------------------------------------

export interface ActionRequiredStoreLike {
  list(): ReadonlyArray<ActionRequiredItem>;
  getById(idHash: string): ActionRequiredItem | undefined;
  respondAndAwait(idHash: string, response: ActionRequiredResponse): Promise<void>;
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
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class ActionRequiredRendererImpl implements ActionRequiredRenderer {
  private readonly bus    : EventBus;
  private readonly stores : ActionRequiredRendererStores;
  private readonly unsubscribers: Array<() => void> = [];

  private root: HTMLElement | null = null;
  private mounted = false;

  constructor(opts: ActionRequiredRendererOptions) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
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
    if (this.root !== null) {
      delete this.root.dataset.phase6bOwner;
      this.root.replaceChildren();
      this.root = null;
    }
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    if (this.mounted) this.renderAll();
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  private renderAll(): void {
    /* c8 ignore next */ // defensive: renderAll is only called after mount() sets root; null only after unmount, which detaches the subscription first.
    if (this.root === null) return;
    const items = this.stores.actionRequired.list();
    for (const item of items) {
      this.renderOrReplaceWidget(item);
    }
  }

  private renderOrReplaceWidget(item: ActionRequiredItem): void {
    /* c8 ignore next */ // defensive: caller flow always guards against null root before reaching here.
    if (this.root === null) return;
    const widget = this.buildWidgetFor(item);
    const existing = this.root.querySelector<HTMLElement>(`[data-id-hash="${cssEscape(item.id_hash)}"]`);
    if (existing !== null) {
      // Atomic swap — single MutationObserver childList entry per AC2c.
      existing.replaceWith(widget);
    } else {
      this.root.appendChild(widget);
    }
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

  private buildInteractiveWidget(item: ActionRequiredItem): HTMLElement {
    const widget = renderActionRequiredInteractive(item, {
      onSubmit: (response) => { void this.handleSubmit(item.id_hash, response); },
    });
    this.appendCountdown(widget, item.expires_at);
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
    // Cancelled widget is a tombstone — minimal surface for selector parity
    // (so cancel events leave a queryable element until a future cleanup pass).
    const widget = document.createElement("div");
    widget.className = "action-required-widget action-required-widget-cancelled";
    widget.setAttribute("data-id-hash", item.id_hash);
    widget.setAttribute("data-state", "cancelled");
    widget.setAttribute("data-testid", "multiplexer-action-required");
    widget.hidden = true;
    return widget;
  }

  private appendCountdown(widget: HTMLElement, expiresAt: number): void {
    const span = document.createElement("span");
    span.className = "action-required-countdown";
    span.setAttribute("data-countdown", String(expiresAt));
    const remaining = Math.max(0, expiresAt - Date.now());
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
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount BEFORE root is nulled.
    if (this.root === null) return;
    const { changeKind, id_hash, countdownMs } = e.payload;
    if (changeKind === "tick") {
      // Per Pass 2 a2 — countdown driven by store's 1Hz tick events; renderer
      // uses .textContent only, NEVER requestAnimationFrame.
      this.updateCountdown(id_hash, countdownMs ?? 0);
      return;
    }
    // Any other changeKind → re-fetch + rebuild.
    const item = this.stores.actionRequired.getById(id_hash);
    if (item === undefined) {
      // Item gone (post-cancellation cleanup or store-level eviction) — drop
      // the widget if still present in the DOM.
      this.removeWidget(id_hash);
      return;
    }
    this.renderOrReplaceWidget(item);
  }

  private updateCountdown(idHash: string, countdownMs: number): void {
    /* c8 ignore next */ // defensive: caller already guards root null.
    if (this.root === null) return;
    const widget = this.root.querySelector<HTMLElement>(`[data-id-hash="${cssEscape(idHash)}"]`);
    if (widget === null) return;   // tick for a widget that's not in the DOM (yet) — silently skip
    const countdown = widget.querySelector<HTMLElement>(".action-required-countdown");
    if (countdown === null) return; // widget exists but has no countdown (e.g. submitting/responded/expired states)
    countdown.textContent = `⏱ ${formatCountdown(countdownMs)}`;
  }

  private removeWidget(idHash: string): void {
    /* c8 ignore next */ // defensive: caller already guards root null.
    if (this.root === null) return;
    const widget = this.root.querySelector<HTMLElement>(`[data-id-hash="${cssEscape(idHash)}"]`);
    if (widget !== null) widget.remove();
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatResponse(response: ActionRequiredResponse | undefined): string {
  if (response === undefined) return "(no response recorded)";
  if (typeof response === "string") return response;
  if (Array.isArray(response)) return response.join(", ");
  // Record<string, string>
  return Object.entries(response).map(([k, v]) => `${k}: ${v}`).join("; ");
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
