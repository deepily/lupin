/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile artifact in c8's source-map view; no actual code on this line).
// Multiplexer Phase 6c Node D — ConversationModePinRenderer.
//
// Applies the conversation-mode pin attribute (`data-pinned-conv-mode="true"`)
// and the pin-move focus-flash attribute (`data-focus-flash="true"`) to
// sender cards based on `SenderStore` state. CSS rules at
// `/static/css/multiplexer/conversation-mode-pin.css` consume these
// attributes for the pin-glow visual. B-CSS owns the `@keyframes focus-flash`
// declaration as SSOT per AC-B15 — D-CSS has ZERO `@keyframes focus-flash`
// declarations; AC-B15 grep-gate enforces this at Node B code-write time.
//
// Path δ scope reduction (Rick 2026-05-19): this renderer handles the
// pin-glow + focus-flash mechanics only. The mic-monopoly indicator
// (`data-mic-monopoly` attribute writing) was DEFERRED via Path δ
// ratification — see TODO.md "Phase 6c follow-on: mic-monopoly indicator"
// for the system-wide-semantic question gating re-scope.
//
// Lifecycle:
//   - mount(root): subscribe to `store_senders_changed`, scan current senders,
//     apply attributes to matching cards (initial paint catches pre-mount state)
//   - unmount(): unsubscribe + clear in-flight focus-flash timers; leaves
//     attribute state in place so subsequent renderer instances can re-mount
//   - forceRenderForTesting(): synchronously trigger one reconciliation pass
//
// Event-driven only. NO `requestAnimationFrame`, NO `setInterval` polling.
// `setTimeout` is used solely for the 1.2s focus-flash auto-remove (and is
// injection-point-overridable for deterministic tests). The `#mounted`
// boolean guard prevents double-mount per the Phase 6a F-26 idempotency
// pattern.
//
// Single-pin invariant: the upstream `SenderStore.handleConversationModeUpdate`
// reducer enforces the invariant atomically via dual-emission (prior-pinned
// cleared FIRST, new-pinned set SECOND). This renderer reads store state on
// every `store_senders_changed` emission and reconciles DOM attributes to
// match. Per F-Rio-D1: `lastPinned` updates ONLY when a NEW card receives
// the pin attribute (NOT cleared during the intermediate unpinned state of
// the dual-emission swap), so focus-flash fires only on true pin-MOVES
// (lastPinned !== currentPinned) and not on first-time activations or on
// re-activations of the same session.

import type { EventBus } from "../shared/EventBus";
import type { SenderRecord, StoreSendersChangedPayload } from "../shared/types";

interface SenderStoreLike {
  list(): ReadonlyArray<SenderRecord>;
}

export interface ConversationModePinRenderer {
  /** Attach to a root DOM node and start subscribing to store events. */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + cancel in-flight focus-flash timers. */
  unmount(): void;
  /** Test helper — synchronously trigger an attribute reconciliation pass. */
  forceRenderForTesting(): void;
}

export interface ConversationModePinRendererOptions {
  eventBus         : EventBus;
  stores           : { senders: SenderStoreLike };
  /** Override for tests; production default is 1200 ms. */
  flashDurationMs? : number;
  /** Injection points for deterministic test scheduling. Production wiring
   *  uses `globalThis.setTimeout` / `globalThis.clearTimeout`. */
  setTimeoutFn?    : (cb: () => void, ms: number) => unknown;
  clearTimeoutFn?  : (id: unknown) => void;
}

const DEFAULT_FLASH_DURATION_MS = 1200;

class ConversationModePinRendererImpl implements ConversationModePinRenderer {
  private readonly bus             : EventBus;
  private readonly stores          : { senders: SenderStoreLike };
  private readonly flashDurationMs : number;
  private readonly setTimeoutFn    : (cb: () => void, ms: number) => unknown;
  private readonly clearTimeoutFn  : (id: unknown) => void;
  private readonly unsubscribers   : Array<() => void> = [];
  private readonly flashTimers     : Map<string, unknown> = new Map();

  private root        : HTMLElement | null = null;
  // Most recently-pinned sender_id (per F-Rio-D1 — updates ONLY when a new
  // card receives the pin attribute, NOT cleared during the dual-emission
  // intermediate unpinned state). Used to discriminate pin-MOVES from
  // first-time activations so focus-flash fires only on moves.
  private lastPinned  : string | null = null;
  private mounted     : boolean = false;

  constructor( opts: ConversationModePinRendererOptions ) {
    this.bus             = opts.eventBus;
    this.stores          = opts.stores;
    this.flashDurationMs = opts.flashDurationMs ?? DEFAULT_FLASH_DURATION_MS;
    this.setTimeoutFn    = opts.setTimeoutFn   ?? ((cb, ms) => globalThis.setTimeout(cb, ms));
    this.clearTimeoutFn  = opts.clearTimeoutFn ?? ((id)     => globalThis.clearTimeout(id as ReturnType<typeof globalThis.setTimeout>));
  }

  mount( root: HTMLElement ): void {
    if (this.mounted) {
      throw new Error("ConversationModePinRenderer.mount: already mounted");
    }
    this.root    = root;
    this.mounted = true;

    this.unsubscribers.push(
      this.bus.on<StoreSendersChangedPayload>(
        "store_senders_changed",
        () => this.reconcile(),
      ),
    );

    // Initial paint — handles any sender that was already pinned BEFORE
    // this renderer mounted. Empty store ⇒ no-op.
    this.reconcile();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    for (const id of this.flashTimers.values()) {
      this.clearTimeoutFn(id);
    }
    this.flashTimers.clear();

    this.root       = null;
    this.lastPinned = null;
    this.mounted    = false;
  }

  forceRenderForTesting(): void {
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Attribute reconciliation
  // -------------------------------------------------------------------------

  private reconcile(): void {
    /* c8 ignore next */ // defensive: store-event subscription is detached in unmount() BEFORE root is nulled, so this branch is unreachable in normal flow.
    if (this.root === null) return;

    // Find the currently-pinned sender in store. Single-pin invariant
    // (enforced atomically by SenderStore.handleConversationModeUpdate via
    // dual-emission) guarantees at most one record has
    // conversation_mode_active === true under steady state. If a transient
    // race produced multiple, the first match wins this pass and the next
    // emission reconciles the rest.
    const senders      = this.stores.senders.list();
    const pinnedRecord = senders.find(s => s.conversation_mode_active === true);
    const currentPinned: string | null = pinnedRecord ? pinnedRecord.sender_id : null;

    // Clear data-pinned-conv-mode from any DOM-pinned card that is no longer
    // the currentPinned (covers deactivate + pin-MOVE prior-clear cases).
    const pinnedCards = this.root.querySelectorAll<HTMLElement>('[data-pinned-conv-mode="true"]');
    for (const card of pinnedCards) {
      const cardSenderId = card.getAttribute("data-sender-id");
      if (cardSenderId !== currentPinned) {
        card.removeAttribute("data-pinned-conv-mode");
      }
    }

    // Apply data-pinned-conv-mode to the currentPinned card if not already
    // set. Trigger focus-flash only on a pin MOVE (lastPinned was a
    // different sender) — first-time activations and re-activations of the
    // same session do NOT flash, per F-Rio-D1 + cascade design.
    if (currentPinned !== null) {
      const target = this.findCardForSender(currentPinned);
      if (target !== null) {
        const alreadyPinned = target.getAttribute("data-pinned-conv-mode") === "true";
        if (!alreadyPinned) {
          target.setAttribute("data-pinned-conv-mode", "true");
          if (this.lastPinned !== null && this.lastPinned !== currentPinned) {
            this.startFocusFlash(target, currentPinned);
          }
          this.lastPinned = currentPinned;
        }
      }
    }
  }

  private findCardForSender(senderId: string): HTMLElement | null {
    /* c8 ignore next */ // defensive: root null-guard in reconcile() short-circuits before reaching here.
    if (this.root === null) return null;
    // CSS-escape the sender_id to handle special chars in the legacy
    // `claude.code@lupin.deepily.ai#suffix` sender_id format.
    return this.root.querySelector<HTMLElement>(`[data-sender-id="${cssEscape(senderId)}"]`);
  }

  private startFocusFlash(card: HTMLElement, senderId: string): void {
    // Cancel any in-flight flash for this same sender (rare: re-pin within
    // the 1.2s window). New flash supersedes old.
    const existing = this.flashTimers.get(senderId);
    if (existing !== undefined) {
      this.clearTimeoutFn(existing);
    }

    // Restart-animation pattern: clear → reflow → set. Forces the CSS
    // engine to treat the re-set as a fresh state change (otherwise a
    // back-to-back re-pin within the same animation frame would silently
    // continue the prior animation). Legacy precedent:
    // `notifications.js:9482-9487` (`_flashFocusedCard` reflow trick).
    card.removeAttribute("data-focus-flash");
    /* c8 ignore next */ // pure DOM-engine reflow side-effect read; not testable behavior in happy-dom (which doesn't run layout).
    void card.offsetWidth;
    card.setAttribute("data-focus-flash", "true");

    const id = this.setTimeoutFn(() => {
      card.removeAttribute("data-focus-flash");
      this.flashTimers.delete(senderId);
    }, this.flashDurationMs);
    this.flashTimers.set(senderId, id);
  }
}

// CSS.escape polyfill for selectors in legacy / Node / older browser contexts
// (mirror of NotificationsListRenderer.ts:423-428 — same util locally scoped
// rather than imported to keep this module self-contained; if a third copy
// surfaces, hoist to a shared helper).
function cssEscape(value: string): string {
  if (typeof globalThis !== "undefined" && typeof (globalThis as { CSS?: { escape?: (s: string) => string } }).CSS?.escape === "function") {
    return (globalThis as { CSS: { escape: (s: string) => string } }).CSS.escape(value);
  }
  /* c8 ignore next */ // polyfill fallback for legacy / Node / pre-2017 browser runtimes lacking globalThis.CSS.escape; unreachable in happy-dom test env and modern browsers.
  return value.replace(/[^a-zA-Z0-9_-]/g, (m) => "\\" + m);
}

/**
 * Factory — production code constructs via `createConversationModePinRenderer`.
 * Matches the Phase 5/6a/6b renderer factory pattern (createNotificationsListRenderer,
 * createJobsPaneRenderer, etc.).
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript return-type erasure produces a fake branch in c8's source-map view; the function body is always entered when called).
export function createConversationModePinRenderer(
  opts: ConversationModePinRendererOptions,
): ConversationModePinRenderer {
  return new ConversationModePinRendererImpl(opts);
}
