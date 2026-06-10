/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer WP2 (parity bridge, 2026-06-10) — SessionStripRenderer.
//
// Owns the CC-session strip DOM end-to-end (the always-on horizontal row of
// per-session persona icons ported from the legacy `notifications.js` client).
// Subscribes to `store_session_strip_changed`; keyed-merges icons into
// `#cc-strip-icons`; manages two strip toggles (focus + hide-inactive) and the
// per-icon focus/inactive attributes.
//
// Mount root must contain (as descendants):
//   - #cc-session-strip        — the container (hidden when no sessions)
//   - #cc-strip-icons          — keyed-merge target for icons
//   - #cc-strip-toggle         — focus-mode toggle (carries data-focus-active)
//   - #cc-hide-inactive-toggle — hide-inactive filter toggle
//
// Focus model (legacy parity): clicking an icon focuses that session
// (data-focused on the icon, data-focus-active on the toggle); clicking the
// focused icon again — or the toggle while focused — exits. When focus is
// active, non-focused `.sender-card`s get `data-focus-hidden="true"` and the
// focused card's height boost (WP10 / F3) keys off
// `#cc-strip-toggle[data-focus-active="true"]`.
//
// FOCUS OWNERSHIP (resolved 2026-06-10, Tiberius ruling): this strip is the
// SOLE writer of `data-focus-hidden`. The interim FocusTrayRenderer — which
// previously also wrote that attribute (keyed on conversation_mode_active) —
// was RETIRED when the strip was wired into boot (one-mechanism rule). The
// `.sender-card[data-focus-hidden]` display:none rule it defined survives in
// focus-tray.css (kept for the AC-B15 focus-flash SSOT) and is now driven only
// by this renderer's focus mode.
//
// Out of WP2 core (flagged follow-ons): per-session speakerphone "conv-mode"
// badge; localStorage persistence of focus + hide-inactive state; cold-reload
// hydration of manager lineage from /api/notifications/senders.
//
// Event-driven only — NO requestAnimationFrame, NO setInterval. `#mounted`
// guard prevents double-mount (Phase 6a F-26 idempotency pattern).

import type { EventBus } from "../shared/EventBus";
import type {
  LupinEvent,
  StoreSessionStripChangedPayload,
  StripSession,
} from "../shared/types";
import { keyedListMerge } from "./dom";
import {
  renderSessionStripIcon,
  updateSessionStripIcon,
} from "./templates/sessionStripIcon";

interface SessionStripStoreLike {
  list(): ReadonlyArray<StripSession>;
}

export interface SessionStripRenderer {
  /** Attach to a root containing the four strip elements (see file header). */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe + clean DOM state owned by this renderer. */
  unmount(): void;
  /** Test helper — synchronously reconcile from current store state. */
  forceRenderForTesting(): void;
}

export interface SessionStripRendererOptions {
  eventBus : EventBus;
  stores   : { strip: SessionStripStoreLike };
}

interface StripEntry {
  readonly idHash : string;
  readonly session: StripSession;
}

class SessionStripRendererImpl implements SessionStripRenderer {
  private readonly bus    : EventBus;
  private readonly stores : { strip: SessionStripStoreLike };
  private readonly unsubscribers: Array<() => void> = [];

  private root            : HTMLElement | null = null;
  private stripEl         : HTMLElement | null = null;
  private iconsEl         : HTMLElement | null = null;
  private focusToggleEl   : HTMLElement | null = null;
  private hideToggleEl    : HTMLElement | null = null;

  // Page-local UI state (in-memory, mirroring FocusTrayRenderer; persistence
  // is a flagged follow-on). Reset on unmount.
  private focusActive     : boolean = false;
  private focusedSenderId : string | null = null;
  private hideInactive    : boolean = false;
  private mounted         : boolean = false;

  private iconsClickHandler : ((e: Event) => void) | null = null;
  private focusToggleHandler: (() => void) | null = null;
  private hideToggleHandler : (() => void) | null = null;

  constructor(opts: SessionStripRendererOptions) {
    this.bus    = opts.eventBus;
    this.stores = opts.stores;
  }

  mount(root: HTMLElement): void {
    if (this.mounted) throw new Error("SessionStripRenderer.mount: already mounted");

    const stripEl       = root.querySelector<HTMLElement>("#cc-session-strip");
    const iconsEl       = root.querySelector<HTMLElement>("#cc-strip-icons");
    const focusToggleEl = root.querySelector<HTMLElement>("#cc-strip-toggle");
    const hideToggleEl  = root.querySelector<HTMLElement>("#cc-hide-inactive-toggle");
    if (stripEl       === null) throw new Error("SessionStripRenderer.mount: #cc-session-strip not found");
    if (iconsEl       === null) throw new Error("SessionStripRenderer.mount: #cc-strip-icons not found");
    if (focusToggleEl === null) throw new Error("SessionStripRenderer.mount: #cc-strip-toggle not found");
    if (hideToggleEl  === null) throw new Error("SessionStripRenderer.mount: #cc-hide-inactive-toggle not found");

    this.root          = root;
    this.stripEl       = stripEl;
    this.iconsEl       = iconsEl;
    this.focusToggleEl = focusToggleEl;
    this.hideToggleEl  = hideToggleEl;
    this.mounted       = true;

    // Lift the data-phase6-pending markers now that the renderer owns the
    // surface (strip visibility is driven by the reconciler).
    stripEl.removeAttribute("data-phase6-pending");
    focusToggleEl.removeAttribute("data-phase6-pending");
    hideToggleEl.removeAttribute("data-phase6-pending");

    this.iconsClickHandler  = (e: Event): void => this.onIconsClick(e);
    this.focusToggleHandler = (): void => this.onFocusToggleClick();
    this.hideToggleHandler  = (): void => this.onHideToggleClick();
    iconsEl.addEventListener("click", this.iconsClickHandler);
    focusToggleEl.addEventListener("click", this.focusToggleHandler);
    hideToggleEl.addEventListener("click", this.hideToggleHandler);

    this.unsubscribers.push(
      this.bus.on<StoreSessionStripChangedPayload>(
        "store_session_strip_changed",
        (e) => this.onStripChanged(e),
      ),
    );

    this.reconcile();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    if (this.iconsEl !== null && this.iconsClickHandler !== null) {
      this.iconsEl.removeEventListener("click", this.iconsClickHandler);
    }
    if (this.focusToggleEl !== null && this.focusToggleHandler !== null) {
      this.focusToggleEl.removeEventListener("click", this.focusToggleHandler);
    }
    if (this.hideToggleEl !== null && this.hideToggleHandler !== null) {
      this.hideToggleEl.removeEventListener("click", this.hideToggleHandler);
    }
    this.iconsClickHandler  = null;
    this.focusToggleHandler = null;
    this.hideToggleHandler  = null;

    // Clean DOM state owned here: clear focus-hidden on cards + empty icons.
    this.clearCardFocus();
    if (this.iconsEl !== null) this.iconsEl.replaceChildren();

    this.root            = null;
    this.stripEl         = null;
    this.iconsEl         = null;
    this.focusToggleEl   = null;
    this.hideToggleEl    = null;
    this.focusActive     = false;
    this.focusedSenderId = null;
    this.hideInactive    = false;
    this.mounted         = false;
  }

  forceRenderForTesting(): void {
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Store-change handling
  // -------------------------------------------------------------------------

  private onStripChanged(e: LupinEvent<StoreSessionStripChangedPayload>): void {
    // Auto-exit focus when the focused session itself is removed (reaped),
    // mirroring the legacy `_removeStripIcon` auto-exit so the user isn't
    // stranded in focus mode anchored to a dead session.
    if (
      this.focusActive &&
      e.payload.changeKind === "removed" &&
      e.payload.sender_id === this.focusedSenderId
    ) {
      this.focusActive     = false;
      this.focusedSenderId = null;
    }
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Click handlers
  // -------------------------------------------------------------------------

  private onIconsClick(e: Event): void {
    const target = e.target as Element | null;
    /* c8 ignore next */ // defensive: e.target is always a non-null Element during a fired click in production DOM + happy-dom; guard exists for the TS type-narrow.
    if (target === null) return;
    const icon = target.closest(".cc-strip-icon");
    if (icon === null) return;
    const senderId = icon.getAttribute("data-sender-id");
    if (senderId === null) return;
    // Click focused icon → exit; otherwise focus the clicked session.
    if (this.focusActive && this.focusedSenderId === senderId) {
      this.exitFocus();
    } else {
      this.enterFocus(senderId);
    }
  }

  private onFocusToggleClick(): void {
    if (this.focusActive) {
      this.exitFocus();
      return;
    }
    // Enter on the previously-focused session if it's still present (legacy
    // restores the persisted focused_sender_id), else the leftmost
    // (chronologically first) session. No-op when there are none.
    const sorted = this.sortedSessions();
    if (sorted.length === 0) return;
    const target = this.focusedSenderId !== null && sorted.some(s => s.sender_id === this.focusedSenderId)
      ? this.focusedSenderId
      : sorted[0]!.sender_id;
    this.enterFocus(target);
  }

  private onHideToggleClick(): void {
    this.hideInactive = !this.hideInactive;
    this.reconcile();
  }

  private enterFocus(senderId: string): void {
    this.focusActive     = true;
    this.focusedSenderId = senderId;
    this.reconcile();
  }

  private exitFocus(): void {
    // Retain focusedSenderId (legacy persists it) so the next focus toggle can
    // restore the last-focused session. Only the auto-exit-on-reap path clears
    // it (the focused session is gone). The icon focus visual keys on
    // `focusActive && focused === senderId`, so nothing shows focused while
    // focusActive is false even though the id is retained.
    this.focusActive = false;
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Reconciliation
  // -------------------------------------------------------------------------

  private reconcile(): void {
    /* c8 ignore next */ // defensive: subscription is detached in unmount() BEFORE the element refs are nulled.
    if (this.stripEl === null || this.iconsEl === null || this.focusToggleEl === null || this.hideToggleEl === null) return;

    const sorted  = this.sortedSessions();
    const entries: StripEntry[] = sorted.map(session => ({ idHash: session.sender_id, session }));

    keyedListMerge<StripEntry>({
      parent : this.iconsEl,
      entries,
      create : (entry) => renderSessionStripIcon(entry.session),
      update : (el, entry) => updateSessionStripIcon(el as HTMLElement, entry.session),
    });

    // Strip visibility: hidden when there are no sessions.
    if (sorted.length === 0) {
      this.stripEl.setAttribute("hidden", "");
    } else {
      this.stripEl.removeAttribute("hidden");
    }

    this.applyIconStates();
    this.applyToggleVisuals();
    this.applyCardFocus();
  }

  private sortedSessions(): StripSession[] {
    // Chronological by assigned_at (legacy chronological-locked ordering);
    // sender_id breaks ties deterministically.
    return this.stores.strip.list()
      .slice()
      .sort((a, b) => (a.assigned_at - b.assigned_at) || a.sender_id.localeCompare(b.sender_id));
  }

  private applyIconStates(): void {
    // `iconsEl` is non-null here — reconcile() guards before calling.
    const icons = this.iconsEl!.querySelectorAll<HTMLElement>(".cc-strip-icon");
    for (const icon of icons) {
      const senderId = icon.getAttribute("data-sender-id");

      if (this.focusActive && senderId === this.focusedSenderId) {
        icon.setAttribute("data-focused", "true");
      } else {
        icon.removeAttribute("data-focused");
      }

      const inactive = icon.getAttribute("data-active") === "false";
      if (this.hideInactive && inactive) {
        icon.setAttribute("data-inactive-hidden", "true");
      } else {
        icon.removeAttribute("data-inactive-hidden");
      }
    }
  }

  private applyToggleVisuals(): void {
    this.focusToggleEl!.setAttribute("data-focus-active", String(this.focusActive));
    this.focusToggleEl!.textContent = this.focusActive ? "👁 Focus: ON" : "👁 Focus";

    this.hideToggleEl!.setAttribute("data-hide-inactive", String(this.hideInactive));
    this.hideToggleEl!.textContent = this.hideInactive ? "👁 Active" : "👁 All";
  }

  private applyCardFocus(): void {
    // ⚠️ Writes data-focus-hidden — see the INTEGRATION CONTRACT note in the
    // file header. Scoped to document because sender cards live under
    // #sender-cards-container, not necessarily under this renderer's root.
    if (this.focusActive && this.focusedSenderId !== null) {
      const anchor = this.focusedSenderId;
      const cards  = document.querySelectorAll<HTMLElement>(".sender-card");
      for (const card of cards) {
        if (card.getAttribute("data-sender-id") === anchor) {
          card.removeAttribute("data-focus-hidden");
        } else {
          card.setAttribute("data-focus-hidden", "true");
        }
      }
    } else {
      this.clearCardFocus();
    }
  }

  private clearCardFocus(): void {
    const hidden = document.querySelectorAll<HTMLElement>('.sender-card[data-focus-hidden="true"]');
    for (const card of hidden) card.removeAttribute("data-focus-hidden");
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSessionStripRenderer(opts: SessionStripRendererOptions): SessionStripRenderer {
  return new SessionStripRendererImpl(opts);
}
