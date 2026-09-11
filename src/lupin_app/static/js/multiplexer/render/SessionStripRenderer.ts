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
// focused icon again does nothing, and the toggle while focused exits (row
// d04ff119 — legacy `_handleStripIconClick`, notifications.js:16554). When focus is
// active, non-focused `.sender-card`s get `data-focus-hidden="true"` and the
// focused card's height boost (WP10 / F3) keys off
// `#cc-strip-toggle[data-focus-active="true"]`.
//
// FOCUS OWNERSHIP (resolved 2026-06-10, Tiberius ruling): this strip is the
// SOLE DECIDER of `data-focus-hidden`. P0 8cb5c22e (2026-09-10): the list
// renderer also STAMPS the flag on a card it is about to insert, by asking
// `isCardFocusHidden()` — legacy flags a card at creation
// (notifications.js:19004), and a card inserted visible then hidden later is
// the flicker Rick reported. The strip still decides; it re-walks every card
// when focus itself changes. The interim FocusTrayRenderer — which
// previously also wrote that attribute (keyed on conversation_mode_active) —
// was RETIRED when the strip was wired into boot (one-mechanism rule). The
// `.sender-card[data-focus-hidden]` display:none rule it defined survives in
// focus-tray.css (kept for the AC-B15 focus-flash SSOT) and is now driven only
// by this renderer's focus mode.
//
// Row d04ff119 (2026-09-11) — two more legacy behaviors:
//   - UNREAD BADGE. While focus is on, a message from a hidden session bumps a
//     count on its icon and restarts the pulse (legacy `_markStripIconActivity`,
//     notifications.js:16310). Workers pulse without a number.
//   - PERSISTENCE, under legacy's own localStorage keys and JSON shape, so focus
//     set in one client is the focus the other restores on the same browser.
//
// Out of WP2 core (flagged follow-ons): per-session speakerphone "conv-mode"
// badge; cold-reload hydration of manager lineage from /api/notifications/senders.
//
// Event-driven only — NO requestAnimationFrame, NO setInterval. `#mounted`
// guard prevents double-mount (Phase 6a F-26 idempotency pattern).

import type { EventBus } from "../shared/EventBus";
import type {
  LupinEvent,
  Notification,
  StoreNotificationsChangedPayload,
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
// Row d04ff119 — the notification store, read to find who sent an arrival.
interface NotificationLookupLike {
  list(): ReadonlyArray<Notification>;
}
type StorageLike = Pick<Storage, "getItem" | "setItem">;

// Row d04ff119 — legacy's keys, verbatim (notifications.js:214-215). The focus key
// holds JSON `{"enabled":…,"focused_sender_id":…}`; the other "true" / "false".
export const FOCUS_STATE_KEY   = "notifications_cc_focus_state";
export const HIDE_INACTIVE_KEY = "notifications_cc_hide_inactive_strip";

export interface SessionStripRenderer {
  /** Attach to a root containing the four strip elements (see file header). */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe + clean DOM state owned by this renderer. */
  unmount(): void;
  /** Test helper — synchronously reconcile from current store state. */
  forceRenderForTesting(): void;
  /**
   * True when focus mode is on and `senderId` is NOT the focused session — the
   * card for that sender must carry `data-focus-hidden="true"`. Read-only; the
   * list renderer calls it before inserting a card (P0 8cb5c22e).
   */
  isCardFocusHidden(senderId: string | null): boolean;
}

export interface SessionStripRendererOptions {
  eventBus : EventBus;
  // `notifications` is optional so harnesses without it still mount; without it
  // no arrival can be attributed, so the unread badge never counts.
  stores   : { strip: SessionStripStoreLike; notifications?: NotificationLookupLike };
  // Row d04ff119 — where focus and hide-inactive persist. Defaults to
  // globalThis.localStorage; tests inject a fake, or null for no persistence.
  storage? : StorageLike | null;
}

interface StripEntry {
  readonly idHash : string;
  readonly session: StripSession;
}

class SessionStripRendererImpl implements SessionStripRenderer {
  private readonly bus     : EventBus;
  private readonly stores  : { strip: SessionStripStoreLike; notifications?: NotificationLookupLike };
  private readonly storage : StorageLike | null;
  private readonly unsubscribers: Array<() => void> = [];

  private root            : HTMLElement | null = null;
  private stripEl         : HTMLElement | null = null;
  private iconsEl         : HTMLElement | null = null;
  private focusToggleEl   : HTMLElement | null = null;
  private hideToggleEl    : HTMLElement | null = null;

  // Page UI state. Focus and hide-inactive are also persisted (row d04ff119);
  // everything here resets on unmount.
  private focusActive     : boolean = false;
  private focusedSenderId : string | null = null;
  private hideInactive    : boolean = false;
  private mounted         : boolean = false;
  // Row d04ff119 — a persisted focus whose session is not in the strip yet. It is
  // applied the moment that session arrives (legacy `_maybeReapplyPersistedFocus`),
  // and dropped as soon as the user makes a focus choice of their own.
  private pendingFocusId  : string | null = null;
  // Row d04ff119 — unread arrivals per hidden session while focus is on.
  private readonly unreadCounts : Map<string, number> = new Map();

  private iconsClickHandler : ((e: Event) => void) | null = null;
  private focusToggleHandler: (() => void) | null = null;
  private hideToggleHandler : (() => void) | null = null;

  constructor(opts: SessionStripRendererOptions) {
    this.bus     = opts.eventBus;
    this.stores  = opts.stores;
    this.storage = opts.storage === undefined ? defaultStorage() : opts.storage;
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
    this.unsubscribers.push(
      this.bus.on<StoreNotificationsChangedPayload>(
        "store_notifications_changed",
        (e) => this.onNotificationsChanged(e),
      ),
    );

    this.restorePersisted();
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
    this.pendingFocusId  = null;
    this.unreadCounts.clear();
  }

  forceRenderForTesting(): void {
    this.reconcile();
  }

  // `null` = a card with no data-sender-id; it is not the focused card, so it hides.
  isCardFocusHidden(senderId: string | null): boolean {
    return this.focusActive && this.focusedSenderId !== null && senderId !== this.focusedSenderId;
  }

  // -------------------------------------------------------------------------
  // Store-change handling
  // -------------------------------------------------------------------------

  private onStripChanged(e: LupinEvent<StoreSessionStripChangedPayload>): void {
    // Auto-exit focus when the focused session itself is removed (reaped),
    // mirroring the legacy `_removeStripIcon` auto-exit so the user isn't
    // stranded in focus mode anchored to a dead session.
    //
    // Row d04ff119 — an AUTO-exit, so nothing is written: the saved focus stays,
    // and becomes pending again, so the session coming back restores it (legacy
    // `_exitFocusMode( false )` plus `_maybeReapplyPersistedFocus`). Like every
    // exit, it clears the unread counts.
    if (
      this.focusActive &&
      e.payload.changeKind === "removed" &&
      e.payload.sender_id === this.focusedSenderId
    ) {
      this.pendingFocusId  = this.focusedSenderId;
      this.focusActive     = false;
      this.focusedSenderId = null;
      this.unreadCounts.clear();
    }
    if (e.payload.changeKind === "removed" && e.payload.sender_id !== undefined) {
      this.unreadCounts.delete(e.payload.sender_id);
    }
    this.reconcile();
  }

  // Row d04ff119 — a message from a session hidden by focus bumps that session's
  // unread count. Skipped, as in legacy (notifications.js:18866-18881): progress-
  // group rows (tool-call noise) and outgoing rows (the user's own reply). Also
  // skipped: action-required rows, which legacy routes to their own pane rather
  // than a sender card, and senders with no icon (legacy returns without one).
  private onNotificationsChanged(e: LupinEvent<StoreNotificationsChangedPayload>): void {
    if (e.payload.changeKind !== "added" || e.payload.id_hash === undefined) return;
    if (!this.focusActive || this.focusedSenderId === null) return;
    const idHash = e.payload.id_hash;
    const row    = this.stores.notifications?.list().find(n => n.id_hash === idHash);
    if (row === undefined || row.sender_id === this.focusedSenderId) return;
    if (row.action_required || row.direction === "outgoing") return;
    if (typeof row.progress_group_id === "string" && row.progress_group_id.length > 0) return;
    const icon = this.iconFor(row.sender_id);
    if (icon === null) return;

    this.unreadCounts.set(row.sender_id, (this.unreadCounts.get(row.sender_id) ?? 0) + 1);
    // Restart the pulse for every message, not only the first: the animation runs
    // when data-unread is applied, so remove it, force a reflow, and set it again.
    icon.removeAttribute("data-unread");
    void icon.offsetWidth;
    this.paintUnread(icon, this.sessionFor(row.sender_id));
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
    // Row d04ff119 — clicking the focused icon does nothing (legacy); the toggle
    // is the only way out. Any other icon takes the focus.
    if (this.focusActive && this.focusedSenderId === senderId) return;
    this.enterFocus(senderId);
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
    this.writeStorage(HIDE_INACTIVE_KEY, String(this.hideInactive));
    this.reconcile();
  }

  private enterFocus(senderId: string): void {
    this.focusActive     = true;
    this.focusedSenderId = senderId;
    this.pendingFocusId  = null;
    this.unreadCounts.delete(senderId);   // visiting a session clears its badge
    this.saveFocus();
    this.reconcile();
  }

  private exitFocus(): void {
    // Retain focusedSenderId in memory so the next focus toggle can restore the
    // last-focused session. Only the auto-exit-on-reap path clears it (the focused
    // session is gone). The icon focus visual keys on
    // `focusActive && focused === senderId`, so nothing shows focused while
    // focusActive is false even though the id is retained.
    //
    // Row d04ff119 — what is SAVED is legacy's shape for a user exit,
    // `{enabled:false, focused_sender_id:null}` (notifications.js:16520), so a reload
    // in either client comes back unfocused. Exiting clears every unread count.
    this.focusActive    = false;
    this.pendingFocusId = null;
    this.unreadCounts.clear();
    this.saveFocus();
    this.reconcile();
  }

  // -------------------------------------------------------------------------
  // Row d04ff119 — persistence
  // -------------------------------------------------------------------------

  // Read what was saved, by this client or by legacy. A saved focus is not
  // applied here: reconcile applies it once its session is in the strip.
  // Anything unreadable is ignored, never thrown.
  private restorePersisted(): void {
    const raw = this.readStorage(FOCUS_STATE_KEY);
    if (raw !== null) {
      let saved: unknown = null;
      try {
        saved = JSON.parse(raw);
      } catch {
        saved = null;   // corrupt JSON: default state, as legacy's guarded re-read does
      }
      if (typeof saved === "object" && saved !== null) {
        const { enabled, focused_sender_id } = saved as { enabled?: unknown; focused_sender_id?: unknown };
        if (enabled === true && typeof focused_sender_id === "string" && focused_sender_id.length > 0) {
          this.pendingFocusId = focused_sender_id;
        }
      }
    }
    this.hideInactive = this.readStorage(HIDE_INACTIVE_KEY) === "true";
  }

  private saveFocus(): void {
    const state = this.focusActive
      ? { enabled: true,  focused_sender_id: this.focusedSenderId }
      : { enabled: false, focused_sender_id: null };
    this.writeStorage(FOCUS_STATE_KEY, JSON.stringify(state));
  }

  // Storage can throw (private windows, quota, blocked site data). The page keeps
  // working from its in-memory state either way.
  private readStorage(key: string): string | null {
    if (this.storage === null) return null;
    try {
      return this.storage.getItem(key);
    } catch {
      return null;
    }
  }

  private writeStorage(key: string, value: string): void {
    if (this.storage === null) return;
    try {
      this.storage.setItem(key, value);
    } catch {
      // nothing to do: the in-memory state still holds for this page
    }
  }

  // -------------------------------------------------------------------------
  // Reconciliation
  // -------------------------------------------------------------------------

  private reconcile(): void {
    /* c8 ignore next */ // defensive: subscription is detached in unmount() BEFORE the element refs are nulled.
    if (this.stripEl === null || this.iconsEl === null || this.focusToggleEl === null || this.hideToggleEl === null) return;

    const sorted  = this.sortedSessions();
    const entries: StripEntry[] = sorted.map(session => ({ idHash: session.sender_id, session }));

    // Row d04ff119 — a saved focus takes effect once its session is here.
    const pending = this.pendingFocusId;
    if (pending !== null && !this.focusActive && sorted.some(s => s.sender_id === pending)) {
      this.focusActive     = true;
      this.focusedSenderId = pending;
      this.pendingFocusId  = null;
    }

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

    this.applyIconStates(sorted);
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

  private applyIconStates(sessions: ReadonlyArray<StripSession>): void {
    // `iconsEl` is non-null here — reconcile() guards before calling.
    const byId  = new Map(sessions.map(s => [ s.sender_id, s ]));
    const icons = this.iconsEl!.querySelectorAll<HTMLElement>(".cc-strip-icon");
    for (const icon of icons) {
      const senderId = icon.getAttribute("data-sender-id");
      // Row d04ff119 — painted on every reconcile, so a fresh icon shows its count.
      this.paintUnread(icon, senderId === null ? undefined : byId.get(senderId));

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
      const cards = document.querySelectorAll<HTMLElement>(".sender-card");
      for (const card of cards) {
        if (this.isCardFocusHidden(card.getAttribute("data-sender-id"))) {
          card.setAttribute("data-focus-hidden", "true");
        } else {
          card.removeAttribute("data-focus-hidden");
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

  // Row d04ff119 — an icon's unread attributes from its count: `data-unread` while
  // the count is above zero, and `data-unread-count` = the count, except for a
  // managed worker, which pulses without a number (legacy `_isWorkerSender`: the
  // manager lineage is known).
  private paintUnread(icon: HTMLElement, session: StripSession | undefined): void {
    const senderId = icon.getAttribute("data-sender-id");
    const count    = senderId === null ? 0 : (this.unreadCounts.get(senderId) ?? 0);
    if (count === 0) {
      icon.removeAttribute("data-unread");
      icon.removeAttribute("data-unread-count");
      return;
    }
    icon.setAttribute("data-unread", "true");
    if (session?.manager_persona) icon.removeAttribute("data-unread-count");
    else icon.setAttribute("data-unread-count", String(count));
  }

  private iconFor(senderId: string): HTMLElement | null {
    for (const icon of this.iconsEl!.querySelectorAll<HTMLElement>(".cc-strip-icon")) {
      if (icon.getAttribute("data-sender-id") === senderId) return icon;
    }
    return null;
  }

  private sessionFor(senderId: string): StripSession | undefined {
    return this.stores.strip.list().find(s => s.sender_id === senderId);
  }
}

// Row d04ff119 — the browser's localStorage, or null where reading the property
// itself throws (some browsers do, with site data blocked).
function defaultStorage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSessionStripRenderer(opts: SessionStripRendererOptions): SessionStripRenderer {
  return new SessionStripRendererImpl(opts);
}
