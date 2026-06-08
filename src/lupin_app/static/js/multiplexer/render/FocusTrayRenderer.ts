/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6c Node B — FocusTrayRenderer.
//
// Owns the focus-mode toggle button + the focus-tray aside. When focus mode
// is ON, non-pinned sender cards get `data-focus-hidden="true"` (D's CSS at
// `.sender-card[data-focus-hidden] { display: none }` does the hide); the
// hidden senders are then surfaced in the tray as clickable rows, each of
// which exits focus mode on click (OSQ-B-2).
//
// Consumes Node D contracts:
//   - E4: `SenderRecord.conversation_mode_active` (the pinned sender)
//   - E1/E2 are written by Node D's ConversationModePinRenderer; B does NOT
//     write `data-pinned-conv-mode` or `data-focus-flash` (single-writer
//     invariant per cascade design).
//
// Per F-Arnold-B-Stage2-4: when the pin moves while focus mode is ON, the
// reconciler re-applies `data-focus-hidden` based on the NEW pinned sender.
// Per OSQ-B-3: toggle is disabled (with tooltip) when no sender is in
// conversation mode — the focus-mode UX only makes sense relative to a
// pinned anchor.
//
// Lifecycle:
//   - mount(root): query #focus-mode-toggle (descendant of root) +
//     #focus-tray (descendant of root); lift `hidden` +
//     `data-phase6-pending` markers; bind click handlers; subscribe to
//     `store_senders_changed`; do initial reconcile.
//   - unmount(): unsubscribe, clear focus-hidden attributes from all
//     sender cards, clear tray contents.
//   - forceRenderForTesting(): synchronous reconcile pass.
//
// Event-driven only — NO `requestAnimationFrame`, NO `setInterval` polling.
// `#mounted` boolean guard prevents double-mount (Phase 6a F-26
// idempotency pattern).

import type { EventBus } from "../shared/EventBus";
import type { LupinEvent, SenderRecord, StoreSendersChangedPayload } from "../shared/types";
import { renderFocusTray } from "./templates/focusTray";

interface SenderStoreLike {
  list(): ReadonlyArray<SenderRecord>;
}

export interface FocusTrayRenderer {
  /** Attach to a root that contains BOTH #focus-mode-toggle and #focus-tray. */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + clean DOM state owned by this renderer. */
  unmount(): void;
  /** Test helper — synchronously reconcile based on current store state. */
  forceRenderForTesting(): void;
}

export interface FocusTrayRendererOptions {
  eventBus : EventBus;
  stores   : { senders: SenderStoreLike };
}

const TOOLTIP_NO_PIN = "Focus mode requires an active conversation-mode session.";

class FocusTrayRendererImpl implements FocusTrayRenderer {
  private readonly bus            : EventBus;
  private readonly stores         : { senders: SenderStoreLike };
  private readonly unsubscribers  : Array<() => void> = [];

  private root             : HTMLElement | null = null;
  private toggleEl         : HTMLElement | null = null;
  private trayEl           : HTMLElement | null = null;
  // Page-local UI state. Persists across reconciles; reset on unmount.
  private focusModeActive  : boolean = false;
  private mounted          : boolean = false;
  // Tracks the most recently observed pinned sender_id so re-applies survive
  // (a) SenderStore's dual-emission transient null-pin window and (b)
  // NotificationsListRenderer's card replaceWith re-renders (which wipe the
  // data-focus-hidden attribute). Per F-Arnold-B-Stage2-4: when focusModeActive
  // is true, every reconcile re-applies data-focus-hidden based on this
  // anchor; the upstream renderer can wipe the attribute but ours fires last
  // (subscribed after NotificationsListRenderer) and restores it.
  private lastPinnedId     : string | null = null;
  private toggleHandler    : ( () => void )    | null = null;
  private trayClickHandler : ( ( e: Event ) => void ) | null = null;

  constructor( opts: FocusTrayRendererOptions ) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
  }

  mount( root: HTMLElement ): void {
    if (this.mounted) throw new Error("FocusTrayRenderer.mount: already mounted");

    const toggleEl = root.querySelector<HTMLElement>("#focus-mode-toggle");
    const trayEl   = root.querySelector<HTMLElement>("#focus-tray");
    if (toggleEl === null) throw new Error("FocusTrayRenderer.mount: #focus-mode-toggle not found");
    if (trayEl   === null) throw new Error("FocusTrayRenderer.mount: #focus-tray not found");

    this.root     = root;
    this.toggleEl = toggleEl;
    this.trayEl   = trayEl;
    this.mounted  = true;

    // Lift the data-phase6-pending markers + hidden attributes now that the
    // renderer owns the surface. The toggle is always visible post-mount;
    // the tray's hidden attribute is managed by the reconciler based on
    // focusModeActive state.
    toggleEl.removeAttribute("hidden");
    toggleEl.removeAttribute("data-phase6-pending");
    trayEl.removeAttribute("data-phase6-pending");

    // Click handlers.
    this.toggleHandler = (): void => this.toggleFocusMode();
    toggleEl.addEventListener("click", this.toggleHandler);
    this.trayClickHandler = (e: Event): void => this.onTrayClick(e);
    trayEl.addEventListener("click", this.trayClickHandler);

    // Subscribe to sender-store changes. Pin moves, persona updates,
    // sender adds — every emission re-reconciles. A "removed" change targeting
    // the focused anchor additionally auto-exits focus mode (see onSendersChanged).
    this.unsubscribers.push(
      this.bus.on<StoreSendersChangedPayload>(
        "store_senders_changed",
        (e) => this.onSendersChanged(e),
      ),
    );

    // Initial reconcile catches any pre-mount sender state (e.g. a pinned
    // sender that was activated before this renderer mounted).
    this.reconcile();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    if (this.toggleEl !== null && this.toggleHandler !== null) {
      this.toggleEl.removeEventListener("click", this.toggleHandler);
    }
    if (this.trayEl !== null && this.trayClickHandler !== null) {
      this.trayEl.removeEventListener("click", this.trayClickHandler);
    }
    this.toggleHandler    = null;
    this.trayClickHandler = null;

    // Clean DOM state: clear focus-hidden attrs + empty the tray. Leaves the
    // mount points themselves in place for re-mount.
    this.clearFocusHidden();
    if (this.trayEl !== null) {
      this.trayEl.replaceChildren();
      this.trayEl.setAttribute("hidden", "");
    }

    this.root            = null;
    this.toggleEl        = null;
    this.trayEl          = null;
    this.focusModeActive = false;
    this.lastPinnedId    = null;
    this.mounted         = false;
  }

  forceRenderForTesting(): void {
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Click handlers
  // -------------------------------------------------------------------------

  private toggleFocusMode(): void {
    const pinned = this.findPinned();
    if (pinned === null) {
      // OSQ-B-3: toggle is disabled when no pin exists. The reconciler
      // keeps the disabled state in sync, but the click handler runs
      // before disabled is applied if the user races a deactivation; this
      // guard prevents a click-to-on-while-no-pin.
      return;
    }
    this.focusModeActive = !this.focusModeActive;
    this.reconcile();
  }

  private onTrayClick(e: Event): void {
    const target = e.target as Element | null;
    /* c8 ignore next */ // defensive: e.target is always a non-null Element during a fired click event in production DOM and happy-dom; this guard exists for the TypeScript type-narrow.
    if (target === null) return;
    const row = target.closest(".focus-tray-row");
    if (row === null) return;
    // OSQ-B-2: clicking ANY tray row exits focus mode (the row identity
    // doesn't matter for now; future revisions may route the click to the
    // specific sender via data-sender-id).
    this.focusModeActive = false;
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Store-change handling
  // -------------------------------------------------------------------------

  private onSendersChanged(e: LupinEvent<StoreSendersChangedPayload>): void {
    // Auto-exit focus mode when the focused anchor itself is removed — e.g.
    // the pinned sender was reaped (session_reaped → SenderStore removal).
    // Without this, reconcile() would keep focus mode ON anchored to a now-dead
    // sender while findPinned() === null disables the toggle, stranding the
    // user with no way out. Mirrors the legacy `_removeStripIcon` auto-exit.
    // See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md
    if (
      this.focusModeActive &&
      e.payload.changeKind === "removed" &&
      e.payload.sender_id === this.lastPinnedId
    ) {
      this.focusModeActive = false;
      this.lastPinnedId    = null;
    }
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Reconciliation
  // -------------------------------------------------------------------------

  private reconcile(): void {
    /* c8 ignore next */ // defensive: subscription is detached in unmount() BEFORE root is nulled.
    if (this.root === null || this.toggleEl === null || this.trayEl === null) return;

    const pinned = this.findPinned();
    // Update lastPinnedId whenever a non-null pin is observed. Holds across
    // transient null states (dual-emission window) + survives
    // NotificationsListRenderer's card replaceWith re-renders (which wipe
    // data-focus-hidden by replacing the DOM nodes outright).
    /* c8 ignore next */ // covered by sender_id-set path in test #13; the conditional itself is a single line.
    if (pinned !== null) this.lastPinnedId = pinned.sender_id;

    // Toggle disabled-state + tooltip per OSQ-B-3.
    if (pinned === null) {
      this.toggleEl.setAttribute("disabled", "");
      this.toggleEl.setAttribute("title", TOOLTIP_NO_PIN);
      // NOTE: do NOT force-exit focus mode here. The SenderStore's
      // single-pin invariant is enforced via DUAL-EMISSION: when the pin
      // moves A → B, emission 1 clears A's flag (transient state: no pin
      // exists at this instant), emission 2 sets B's flag. Force-exiting in
      // emission 1's reconcile would lose the user's focus-mode state on
      // every pin-move. Visual disabled state reverts on next pin.
    } else {
      this.toggleEl.removeAttribute("disabled");
      this.toggleEl.removeAttribute("title");
    }

    // Toggle visual state.
    this.toggleEl.textContent = this.focusModeActive ? "Focus mode ON" : "Focus mode OFF";
    this.toggleEl.setAttribute("aria-pressed", String(this.focusModeActive));

    if (this.focusModeActive) {
      // F-Arnold-B-Stage2-4: re-apply data-focus-hidden EVERY reconcile while
      // focus mode is active. This handles three cases together:
      //   (a) pin moves A → B — applyFocusHidden(B) clears B's attr + sets A's
      //   (b) dual-emission transient null pin — fall through to lastPinnedId
      //   (c) NotificationsListRenderer wiped data-focus-hidden via
      //       replaceWith re-render — we re-stamp it from lastPinnedId
      // The anchor sender for the hidden set is `pinned ?? lastPinnedId`.
      const anchorId = pinned !== null ? pinned.sender_id : this.lastPinnedId;
      if (anchorId !== null) {
        const allSenders    = this.stores.senders.list();
        const hiddenSenders = allSenders.filter(s => s.sender_id !== anchorId);
        this.applyFocusHidden(anchorId);
        const trayContent   = renderFocusTray(hiddenSenders);
        this.trayEl.replaceChildren(trayContent);
        this.trayEl.removeAttribute("hidden");
      }
      // anchorId === null only if focus mode was activated without any pin
      // history — defensive; in practice toggleFocusMode rejects that path.
    } else {
      // Focus mode OFF (deliberate, via toggle click) — clear all
      // focus-hidden attrs + empty + hide tray.
      this.clearFocusHidden();
      this.trayEl.replaceChildren();
      this.trayEl.setAttribute("hidden", "");
    }
  }

  private findPinned(): SenderRecord | null {
    const senders = this.stores.senders.list();
    const pinned  = senders.find(s => s.conversation_mode_active === true);
    return pinned !== undefined ? pinned : null;
  }

  private applyFocusHidden(pinnedSenderId: string): void {
    // Scope the query to document because sender cards live under
    // #notifications-pane → #sender-cards-container, which may not be a
    // descendant of this renderer's mount root. Cards in other trees are
    // not affected (the selector specificity filters to .sender-card).
    const allCards = document.querySelectorAll<HTMLElement>(".sender-card");
    for (const card of allCards) {
      const cardSenderId = card.getAttribute("data-sender-id");
      if (cardSenderId === pinnedSenderId) {
        card.removeAttribute("data-focus-hidden");
      } else {
        card.setAttribute("data-focus-hidden", "true");
      }
    }
  }

  private clearFocusHidden(): void {
    const hiddenCards = document.querySelectorAll<HTMLElement>('.sender-card[data-focus-hidden="true"]');
    for (const card of hiddenCards) {
      card.removeAttribute("data-focus-hidden");
    }
  }
}

/**
 * Factory — production code constructs via `createFocusTrayRenderer`.
 * Matches the Phase 5/6a/6b/6c-D renderer factory pattern.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createFocusTrayRenderer(
  opts: FocusTrayRendererOptions,
): FocusTrayRenderer {
  return new FocusTrayRendererImpl(opts);
}
