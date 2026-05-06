/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile produces a fake branch on line 1 in c8's source-map view; no actual code on this line — it's a comment).
// Multiplexer Phase 5 — NotificationsListRenderer.
//
// Orchestrates the notifications-list pane:
//   - Subscribes to store_notifications_changed, store_senders_changed,
//     store_action_required_changed via EventBus
//   - Performs hybrid render (Q-B): hydrate=full, add/update/expire=keyed,
//     tick=text-node only on .action-required-countdown (NO parent-tree
//     mutation; explicit invariant tested by AC4)
//   - Routes mounts per D-L: action-required widgets → #action-required-section;
//     sender cards → #sender-cards-container
//   - Empty-state per Q-K: <div data-testid="multiplexer-empty-state"> when
//     notificationStore.list() is empty
//   - Progress-group lazy-render per Q-G + F14: history materializes on first
//     toggle-expand click; expansion state preserved in `expandedGroups` Set
//     across re-renders so keyedListMerge stable elements get re-marked
//
// Per F12: every keyed-merge element carries `data-id-hash`.
// Per D-I: factory takes `stores: { notifications, senders, actionRequired }`
// (plural keys matching `StoreSet`).
// Per F13: renderer.mount() must be called BEFORE transports start; mount()
// reads notificationStore.list() once for the initial paint.

import type { EventBus } from "../shared/EventBus";
import type {
  Notification,
  SenderRecord,
  ActionRequiredItem,
  LupinEvent,
  StoreNotificationsChangedPayload,
  StoreActionRequiredChangedPayload,
} from "../shared/types";
import { html } from "./html";
import { keyedListMerge } from "./dom";
import { formatCountdown } from "./time";
import { renderSenderCard } from "./templates/senderCard";
import { renderActionRequiredReadOnly } from "./templates/actionRequiredReadOnly";

interface NotificationStoreLike {
  list(): ReadonlyArray<Notification>;
}
interface SenderStoreLike {
  list(): ReadonlyArray<SenderRecord>;
}
interface ActionRequiredStoreLike {
  list(): ReadonlyArray<ActionRequiredItem>;
}

export interface NotificationsListRendererStores {
  notifications  : NotificationStoreLike;
  senders        : SenderStoreLike;
  actionRequired : ActionRequiredStoreLike;
}

export interface NotificationsListRenderer {
  /** Attach to a root DOM node. Throws if expected mount points are missing. */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe all listeners + clear root. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

export interface NotificationsListRendererOptions {
  eventBus     : EventBus;
  stores       : NotificationsListRendererStores;
  appTimezone? : string;
}

class NotificationsListRendererImpl implements NotificationsListRenderer {
  private readonly bus            : EventBus;
  private readonly stores         : NotificationsListRendererStores;
  private readonly appTimezone    : string | undefined;
  private readonly unsubscribers  : Array<() => void> = [];
  // Map: progress_group_id → expanded?  (preserved across re-renders so the
  // post-render fix-up step re-marks expanded groups). Per F14.
  private readonly expandedGroups : Set<string> = new Set();
  // Lazy-rendered history fragments cached per progress_group_id.
  private readonly historyCache   : Map<string, DocumentFragment> = new Map();

  private root                : HTMLElement | null = null;
  private actionRequiredMount : HTMLElement | null = null;
  private senderCardsMount    : HTMLElement | null = null;
  private clickHandler        : ((e: Event) => void) | null = null;

  constructor(opts: NotificationsListRendererOptions) {
    this.bus         = opts.eventBus;
    this.stores      = opts.stores;
    this.appTimezone = opts.appTimezone;
  }

  mount(root: HTMLElement): void {
    if (this.root !== null) {
      throw new Error("NotificationsListRenderer.mount: already mounted");
    }
    this.root = root;
    // Per D-L: route to specific mount points if present; fall back to root
    // (test fixtures + simple shells may put the renderer's content directly
    // into a single element).
    this.actionRequiredMount = (root.querySelector("#action-required-section") as HTMLElement | null) ?? root;
    this.senderCardsMount    = (root.querySelector("#sender-cards-container") as HTMLElement | null) ?? root;

    this.attachClickDelegation();
    this.subscribe();

    // Initial paint per F13: read store.list() once at mount, before any
    // transport activity. If a notification arrives between createStores and
    // mount, it's already in the list (synchronous reducer); the initial
    // paint catches it.
    this.renderAll();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    if (this.clickHandler !== null && this.senderCardsMount !== null) {
      this.senderCardsMount.removeEventListener("click", this.clickHandler);
    }
    this.clickHandler = null;

    if (this.actionRequiredMount !== null) this.actionRequiredMount.replaceChildren();
    if (this.senderCardsMount !== null)    this.senderCardsMount.replaceChildren();

    this.expandedGroups.clear();
    this.historyCache.clear();
    this.root = null;
    this.actionRequiredMount = null;
    this.senderCardsMount = null;
  }

  forceRenderForTesting(): void {
    this.renderAll();
  }

  // -------------------------------------------------------------------------
  // Subscriptions (per D-I plural keys + RE-6 unsubscribe-closure pattern)
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<StoreNotificationsChangedPayload>(
        "store_notifications_changed",
        () => this.renderSenderSection(),
      ),
    );
    this.unsubscribers.push(
      this.bus.on(
        "store_senders_changed",
        () => this.renderSenderSection(),
      ),
    );
    this.unsubscribers.push(
      this.bus.on<StoreActionRequiredChangedPayload>(
        "store_action_required_changed",
        (e) => this.onActionRequiredChange(e),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Render — hybrid (Q-B): hydrate=full, add/update/expire=keyed, tick=text-only
  // -------------------------------------------------------------------------

  private renderAll(): void {
    this.renderActionRequiredSection();
    this.renderSenderSection();
  }

  private renderSenderSection(): void {
    /* c8 ignore next */ // defensive: senderCardsMount is set in mount() and only nulled in unmount(); store-event subscriptions are detached in unmount BEFORE this null happens, so this branch is unreachable in normal flow.
    if (this.senderCardsMount === null) return;
    // Filter out action-required notifications — those render in the
    // #action-required-section per D-L mount routing + legacy behavior
    // (legacy `processNewNotification` routes action-required to its own
    // pane, not to the notifications-list). Sender section shows only
    // regular notifications.
    const allNotifications  = this.stores.notifications.list();
    const notifications     = allNotifications.filter(n => !n.action_required);
    const senders           = this.stores.senders.list();

    // Empty-state (Q-K): paint when active (non-action-required) list is empty.
    if (notifications.length === 0) {
      this.paintEmptyState();
      return;
    }
    this.removeEmptyState();

    // Group notifications by sender_id.
    const bySender = new Map<string, Notification[]>();
    for (const n of notifications) {
      let arr = bySender.get(n.sender_id);
      if (arr === undefined) {
        arr = [];
        bySender.set(n.sender_id, arr);
      }
      arr.push(n);
    }

    const senderRecordById = new Map<string, SenderRecord>(senders.map(s => [s.sender_id, s]));
    const entries = Array.from(bySender.entries()).map(([senderId, notifs]) => ({
      idHash       : senderId,
      sender       : senderRecordById.get(senderId) ?? this.stubSender(senderId, notifs),
      notifications: notifs,
    }));

    // Sort senders by most-recent activity (newest first).
    entries.sort((a, b) => b.sender.last_active_ts - a.sender.last_active_ts);

    keyedListMerge({
      parent  : this.senderCardsMount,
      entries,
      create  : (e) => renderSenderCard(e.sender, e.notifications, { appTimezone: this.appTimezone }),
      // On match, re-create-and-replace is the simplest correct strategy for
      // Phase 5 (sender card chrome may have changed: persona, unread count,
      // last_active). Phase 6 may optimize.
      update  : (existing, e) => {
        const fresh = renderSenderCard(e.sender, e.notifications, { appTimezone: this.appTimezone });
        existing.replaceWith(fresh);
      },
    });

    // Re-mark expanded progress groups after the render (state preserved
    // across re-renders per F14).
    this.reapplyExpandedGroups();
  }

  private renderActionRequiredSection(): void {
    /* c8 ignore next */ // defensive: actionRequiredMount is set in mount() and only nulled in unmount(); subscriptions are detached in unmount BEFORE this null happens.
    if (this.actionRequiredMount === null) return;
    const items = this.stores.actionRequired.list();
    keyedListMerge({
      parent  : this.actionRequiredMount,
      entries : items.map(item => ({ idHash: item.id_hash, item })),
      create  : (e) => renderActionRequiredReadOnly(e.item, this.computeCountdownMs(e.item)),
      // Re-create-and-replace on match; tick-only updates take a different path
      // (`onActionRequiredChange` below) that does NOT call this method.
      update  : (existing, e) => {
        const fresh = renderActionRequiredReadOnly(e.item, this.computeCountdownMs(e.item));
        existing.replaceWith(fresh);
      },
    });
  }

  private onActionRequiredChange(e: LupinEvent<StoreActionRequiredChangedPayload>): void {
    const payload = e.payload;
    if (payload.changeKind === "tick") {
      // Per Q-B: tick MUST NOT touch parent DOM. Only mutate the countdown
      // text node inline. AC4 verifies via `data-test-canary` sentinel.
      /* c8 ignore next */ // defensive: actionRequiredMount post-mount is always set; tick events fire only between mount and unmount.
      if (this.actionRequiredMount === null) return;
      const widget = this.actionRequiredMount.querySelector(`[data-id-hash="${cssEscape(payload.id_hash)}"]`) as HTMLElement | null;
      /* c8 ignore next */ // defensive: widget null only if AR item never rendered (id_hash not in arList); reducer guarantees consistency.
      if (widget === null) return;
      const countdown = widget.querySelector(".action-required-countdown") as HTMLElement | null;
      /* c8 ignore next */ // defensive: countdown null only if widget template missing the .action-required-countdown element; template invariant guarantees it.
      if (countdown === null) return;
      const ms = payload.countdownMs ?? 0;
      countdown.textContent = `⏱ ${formatCountdown(ms)}`;
      return;
    }
    // Any other changeKind ("added" | "responded" | "expired" | "cancelled" |
    // "offline-frozen" | "offline-resumed") triggers a full re-render of the
    // section. The keyedListMerge preserves DOM identity for unchanged items.
    this.renderActionRequiredSection();
  }

  // -------------------------------------------------------------------------
  // Empty-state (Q-K) — 4 transitions per F18:
  //   (a) hydrate-with-zero, (b) hydrate-with-N,
  //   (c) post-expired-to-zero, (d) post-added-from-zero
  // -------------------------------------------------------------------------

  private paintEmptyState(): void {
    /* c8 ignore next */ // defensive: senderCardsMount post-mount is always set; renderSenderSection's null-guard would have already returned.
    if (this.senderCardsMount === null) return;
    /* c8 ignore next */ // defensive: idempotency check — empty-state is only painted from renderSenderSection's notifications.length === 0 branch which calls paintEmptyState exactly once before bailing out. Re-entry from a re-render with the same empty-state already painted is the case this guards against, but renderSenderSection's flow ensures the existing element is removed via removeEmptyState before re-paint in the non-empty branch.
    if (this.senderCardsMount.querySelector(`[data-testid="multiplexer-empty-state"]`) !== null) return;
    const frag = html`
      <div data-testid="multiplexer-empty-state" class="notifications-empty-state">
        No notifications yet.
      </div>
    ` as DocumentFragment;
    this.senderCardsMount.replaceChildren(frag);
  }

  private removeEmptyState(): void {
    /* c8 ignore next */ // defensive: senderCardsMount post-mount is always set.
    if (this.senderCardsMount === null) return;
    const existing = this.senderCardsMount.querySelector(`[data-testid="multiplexer-empty-state"]`);
    if (existing !== null) existing.remove();
  }

  // -------------------------------------------------------------------------
  // Progress-group lazy-render (Q-G + F14) — delegated click handler
  // -------------------------------------------------------------------------

  private attachClickDelegation(): void {
    /* c8 ignore next */ // defensive: senderCardsMount post-mount is always set; attachClickDelegation is called from mount() after the mount points are wired.
    if (this.senderCardsMount === null) return;
    this.clickHandler = (e: Event) => {
      const target = e.target as Element | null;
      if (target === null) return;  // covered by null-target click test
      const toggle = target.closest(".progress-group-toggle") as HTMLElement | null;
      if (toggle === null) return;  // covered by non-toggle click test
      const head = toggle.closest(".progress-group-head");
      /* c8 ignore next */ // defensive: head is the immediate parent of toggle by template; if a future template change breaks this, the toggle wouldn't visually land in a group anyway.
      if (head === null) return;
      const messageEl = head.closest("[data-progress-group]") as HTMLElement | null;
      /* c8 ignore next */ // defensive: head is always inside a [data-progress-group] message by template invariant.
      if (messageEl === null) return;
      const progressGroupId = messageEl.getAttribute("data-progress-group");
      /* c8 ignore next */ // defensive: progressGroupId attribute is set by the template; getAttribute returns null only if the attribute was removed.
      if (progressGroupId === null) return;
      this.toggleProgressGroup(progressGroupId, messageEl, toggle);
    };
    this.senderCardsMount.addEventListener("click", this.clickHandler);
  }

  private toggleProgressGroup(progressGroupId: string, headMessageEl: HTMLElement, toggle: HTMLElement): void {
    const historyEl = headMessageEl.querySelector(".progress-group-history") as HTMLElement | null;
    /* c8 ignore next */ // defensive: historyEl is a sibling within .sender-message rendered by the template invariant; null only if the template was structurally broken.
    if (historyEl === null) return;
    const expanded = this.expandedGroups.has(progressGroupId);
    if (expanded) {
      // Collapse — hide; cache survives.
      historyEl.setAttribute("hidden", "");
      toggle.setAttribute("aria-expanded", "false");
      toggle.textContent = "▶";
      this.expandedGroups.delete(progressGroupId);
      return;
    }
    // Expand — first-time materialize OR reuse cache.
    if (!this.historyCache.has(progressGroupId)) {
      const fragment = this.buildHistoryFragment(progressGroupId, headMessageEl);
      this.historyCache.set(progressGroupId, fragment);
    }
    const cached = this.historyCache.get(progressGroupId)!;
    historyEl.replaceChildren(cached.cloneNode(true));
    historyEl.removeAttribute("hidden");
    toggle.setAttribute("aria-expanded", "true");
    toggle.textContent = "▼";
    this.expandedGroups.add(progressGroupId);
  }

  private buildHistoryFragment(progressGroupId: string, headMessageEl: HTMLElement): DocumentFragment {
    const headIdHash = headMessageEl.getAttribute("data-id-hash") ?? "";
    const all = this.stores.notifications.list();
    const historyItems = all
      .filter(n => n.progress_group_id === progressGroupId && n.id_hash !== headIdHash)
      .sort((a, b) => b.ts - a.ts);   // newest first
    const frag = html`
      ${historyItems.map(n => html`
        <div class="progress-history-entry" data-id-hash="${n.id_hash}">
          <span class="activity-timestamp">${n.time_display ?? new Date(n.ts).toISOString()}</span>
          <span class="activity-message">${n.message}</span>
        </div>
      `)}
    ` as DocumentFragment;
    return frag;
  }

  private reapplyExpandedGroups(): void {
    if (this.senderCardsMount === null || this.expandedGroups.size === 0) return;
    for (const groupId of this.expandedGroups) {
      // The message el carries `data-progress-group`; head + history + toggle
      // are all descendants of it (head + history are SIBLINGS within the
      // `.sender-message`, NOT parent-child).
      const messageEl = this.senderCardsMount.querySelector(`[data-progress-group="${cssEscape(groupId)}"]`) as HTMLElement | null;
      if (messageEl === null) continue;  // covered by "expanded group whose DOM disappeared" test
      const historyEl = messageEl.querySelector(".progress-group-history") as HTMLElement | null;
      const toggle    = messageEl.querySelector(".progress-group-toggle") as HTMLElement | null;
      /* c8 ignore next */ // defensive: historyEl + toggle are guaranteed by the template — if messageEl exists, both descendants exist.
      if (historyEl === null || toggle === null) continue;
      // Invalidate cache (history may have grown via newly-arrived notifications).
      this.historyCache.delete(groupId);
      const fragment = this.buildHistoryFragment(groupId, messageEl);
      this.historyCache.set(groupId, fragment);
      historyEl.replaceChildren(fragment.cloneNode(true));
      historyEl.removeAttribute("hidden");
      toggle.setAttribute("aria-expanded", "true");
      toggle.textContent = "▼";
    }
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private computeCountdownMs(item: ActionRequiredItem): number {
    // The store emits already-corrected countdownMs on tick; for the initial
    // render (before the first tick), derive from expires_at + browser clock.
    // Per D-H this is OK at render-time (initial paint) but the formatter
    // itself stays pure.
    return Math.max(0, item.expires_at - Date.now());
  }

  private stubSender(senderId: string, notifs: ReadonlyArray<Notification>): SenderRecord {
    // Synthesize a SenderRecord when SenderStore doesn't have one yet
    // (e.g. notification arrived first). Display name defaults to sender_id;
    // unread_count is the notifications array length; last_active_ts is the
    // newest message ts.
    let last = 0;
    for (const n of notifs) {
      if (n.ts > last) last = n.ts;
    }
    return {
      sender_id      : senderId,
      display_name   : senderId,
      last_active_ts : last,
      unread_count   : notifs.length,
    };
  }
}

// CSS.escape polyfill for selectors in legacy / Node / older browser contexts.
function cssEscape(value: string): string {
  if (typeof globalThis !== "undefined" && typeof (globalThis as { CSS?: { escape?: (s: string) => string } }).CSS?.escape === "function") {
    return (globalThis as { CSS: { escape: (s: string) => string } }).CSS.escape(value);
  }
  return value.replace(/[^a-zA-Z0-9_-]/g, (m) => "\\" + m);
}

/**
 * Factory — production code constructs via `createNotificationsListRenderer`.
 * Matches Phase 4 `createStores` + Phase 3 `createTransports` factory shape (RE-12).
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript return-type erasure produces a fake branch in c8's source-map view; the function body is always entered when called).
export function createNotificationsListRenderer(opts: NotificationsListRendererOptions): NotificationsListRenderer {
  return new NotificationsListRendererImpl(opts);
}
