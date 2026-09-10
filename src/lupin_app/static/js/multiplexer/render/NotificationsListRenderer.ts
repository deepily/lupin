/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile produces a fake branch on line 1 in c8's source-map view; no actual code on this line — it's a comment).
// Multiplexer Phase 5 — NotificationsListRenderer.
//
// Orchestrates the notifications-list pane — SENDER CARDS ONLY. The
// action-required section is owned wholesale by the separate
// ActionRequiredRenderer (mounted document-level in boot.ts); bug 56e422aa
// ripped this renderer's vestigial AR rendering post-Lane-0c.
//   - Subscribes to store_notifications_changed, store_senders_changed via EventBus
//   - Performs hybrid render (Q-B): hydrate=full, add/update/expire=keyed
//   - Renders sender cards into #sender-cards-container
//   - Empty-state per Q-K: <div data-testid="multiplexer-empty-state"> when
//     notificationStore.list() is empty
//   - Progress-group lazy-render per Q-G + F14: history materializes on first
//     toggle-expand click; expansion state preserved in `expandedGroups` Set
//     across re-renders so keyedListMerge stable elements get re-marked
//
// Per F12: every keyed-merge element carries `data-id-hash`.
// Per D-I: factory takes `stores: { notifications, senders }`
// (plural keys matching `StoreSet`).
// Per F13: renderer.mount() must be called BEFORE transports start; mount()
// reads notificationStore.list() once for the initial paint.

import type { EventBus } from "../shared/EventBus";
import type {
  Notification,
  SenderRecord,
  SenderSortComparator,
  PredictionVoteDir,
  StoreNotificationsChangedPayload,
  StorePredictionVoteChangedPayload,
  StoreViewStateChangedPayload,
  AudioPlaybackState,
} from "../shared/types";
import type { PredictionVoteContext } from "../stores/PredictionVoteStore";
import { html } from "./html";
import { keyedListMerge } from "./dom";
import { formatDateKey } from "./time";
import { openSessionNameEditModal } from "./sessionNameEditModal";
import { renderSenderCard } from "./templates/senderCard";
import { HISTORY_RETRY_EVENT } from "../stores/coldHistoryHydration";
import type { PredictionVoteIntegration } from "./templates/predictionVoteControls";

interface NotificationStoreLike {
  list(): ReadonlyArray<Notification>;
  // S2d/S3 (2026-09-10) — drop a sender's (or one date's) rows after the server
  // delete. Optional so harnesses that stub only list() keep compiling.
  removeByIdHashes?(idHashes: ReadonlyArray<string>): void;
  // B3 (01-C): the sender section renders from the FILTERED view; `list()` stays
  // the raw total (the header count reads it). `isFilterActive()` drives the
  // filter-aware empty-state copy. Both optional so pre-B3 unit harnesses (that
  // stub only `list()`) keep compiling — the renderer falls back to `list()`.
  visibleEntries?(): ReadonlyArray<Notification>;
  isFilterActive?(): boolean;
  // P0 5ebd2aff — cold-load hydration state drives the loading / failed empty
  // states. Optional so harnesses that stub only list() behave as "done".
  historyHydrationState?(): "idle" | "loading" | "done" | "failed";
  historyHydrationError?(): string | null;
}
interface SenderStoreLike {
  list(): ReadonlyArray<SenderRecord>;
  // S2b/S2c (2026-09-10) — persist a gist or a rename. Optional for the same
  // harness reason as removeByIdHashes; the production SenderStore has it.
  setSessionName?(senderId: string, name: string): void;
}
// WP14 (F8) — narrowed PredictionVoteStore surface this renderer consumes
// (getVote for the highlight, setContext + vote for the cast). The production
// PredictionVoteStore satisfies it structurally.
interface PredictionVoteStoreLike {
  getVote( notificationId: string ): PredictionVoteDir | undefined;
  setContext( notificationId: string, ctx: PredictionVoteContext ): void;
  vote( notificationId: string, dir: PredictionVoteDir ): Promise<boolean>;
}
// Section-toolbar / accordion-collapse parity (2026-06-23) — the per-accordion
// collapse state this renderer reads on render + writes on header-click. The
// production ViewStateStore satisfies it structurally. Optional in the stores
// bag: when absent (some unit harnesses) accordion clicks still toggle the DOM
// but the state is not persisted across re-renders/reloads.
interface ViewStateStoreLike {
  isAccordionCollapsed( accordionId: string ): boolean;
  setAccordionCollapsed( accordionId: string, collapsed: boolean ): void;
}
// B4 (01-D) — per-message active-TTS controls. THE F0 SEAM (Mr. Radio ruling,
// Option A refined): identity comes from this READ-ONLY, mutator-less interface.
// COND-2 (B4 makes ZERO TtsQueueStore mutator calls) is PROVABLE BY SHAPE — the
// renderer holds no handle to a queue mutator, so it structurally cannot call
// one. Real F0's TtsQueueStore (00b) satisfies this interface → zero driver
// change when it lands. `current()` = the actively-spoken message's id_hash, or
// null when nothing is playing.
interface TtsQueueStoreLike {
  current(): string | null;
}
// Narrow AudioStore surface this renderer consumes: the play/pause glyph + the
// mutators the corner ⏸/⏹ click branches drive. The production AudioStore
// satisfies it structurally. stop() = halt only (de-light happens when F0 clears
// current() reacting to store_audio_state_change{idle}; B4 never advances).
interface AudioControlsLike {
  state(): AudioPlaybackState;
  pause(): void;
  resume(): void;
  stop(): void;
}
// Narrow apiClient surface for the proxy-ratify-link acknowledge call (the
// page-open is a separate injected opener). The production ApiClient satisfies it.
interface ProxyRatifierLike {
  acknowledgeProxy(): Promise<unknown>;
}
// S2b/S2d/S3 (2026-09-10) — narrow api surface for the sender-card header
// controls: the ✨ gist POST, the × conversation DELETE, the per-date × DELETE.
// The production ApiClient satisfies it (auth header included).
interface SenderCardApiLike {
  post<T>(path: string, body: unknown): Promise<T>;
  delete<T>(path: string): Promise<T>;
}

export interface NotificationsListRendererStores {
  notifications  : NotificationStoreLike;
  senders        : SenderStoreLike;
  // WP14 (F8) — optional. Prediction-hint controls RENDER from pure data
  // (notification.prediction_hint) regardless; this store makes them
  // INTERACTIVE (cast-vote highlight + click → POST + reconcile). Absent (some
  // unit harnesses) → controls render but are inert. Boot always wires it.
  predictionVote?: PredictionVoteStoreLike;
  // Section-toolbar / accordion-collapse parity (2026-06-23). Optional — see
  // ViewStateStoreLike. Boot always wires it (stores.viewState).
  viewState?     : ViewStateStoreLike;
  // B4 (01-D) — active-TTS identity (the F0 seam) + audio controls. Both
  // optional: some unit harnesses omit them (the driver then clears + the click
  // branches no-op). Boot wires ttsQueue=F0 TtsQueueStore + audio=AudioStore.
  ttsQueue?      : TtsQueueStoreLike;
  audio?         : AudioControlsLike;
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
  eventBus              : EventBus;
  stores                : NotificationsListRendererStores;
  appTimezone?          : string;
  // Phase 6c Node D Step D3 — sender-level sort comparator. Defaults to
  // most-recent-activity-first (preserves Phase 5 behavior). Boot wiring
  // injects the Phase 6c override that hoists conversation-mode-pinned
  // senders above activity-based ordering. Per F-Arnold-D3: signature is
  // sender-level, NOT entry-level.
  senderSortComparator? : SenderSortComparator;
  // B4 (01-D) — proxy-ratify-link wiring. `proxyRatifier` is the apiClient
  // acknowledge surface (optional — harness may omit); `proxyRatifyOpener` opens
  // the ratify admin page renderer-side (F-Sam-BD3), defaulted to window.open.
  proxyRatifier?        : ProxyRatifierLike;
  proxyRatifyOpener?    : () => void;
  // S2a–d / S3 (2026-09-10) — sender-card header controls. `api` absent (some
  // harnesses) → gist / delete-all / per-date delete are inert. `getUserEmail`
  // is read at click time for the DELETE paths (boot: AuthManager). The other
  // three are test seams with browser defaults: globalThis.confirm,
  // navigator.clipboard.writeText, and console.error + alert for failures.
  api?                  : SenderCardApiLike;
  getUserEmail?         : () => string | null;
  confirmFn?            : (message: string) => boolean;
  clipboardWrite?       : (text: string) => Promise<void>;
  reportFailure?        : (message: string) => void;
}

// Default sender sort: most-recent-activity-first. Preserves the Phase 5
// behavior when no `senderSortComparator` is supplied via options.
const DEFAULT_SENDER_SORT: SenderSortComparator = (a, b) => b.last_active_ts - a.last_active_ts;

class NotificationsListRendererImpl implements NotificationsListRenderer {
  private readonly bus                  : EventBus;
  private readonly stores               : NotificationsListRendererStores;
  private readonly appTimezone          : string | undefined;
  private readonly senderSortComparator : SenderSortComparator;
  private readonly unsubscribers        : Array<() => void> = [];
  // Map: progress_group_id → expanded?  (preserved across re-renders so the
  // post-render fix-up step re-marks expanded groups). Per F14.
  private readonly expandedGroups : Set<string> = new Set();
  // Lazy-rendered history fragments cached per progress_group_id.
  private readonly historyCache   : Map<string, DocumentFragment> = new Map();

  private root                : HTMLElement | null = null;
  private senderCardsMount    : HTMLElement | null = null;
  private clickHandler        : ((e: Event) => void) | null = null;

  // WP14 (F8) — prediction-vote orchestration. `predictionVoteStore` is the
  // injected store (undefined in storeless harnesses); `predictionVoteIntegration`
  // is the bridge threaded into the sender-card render path (undefined → controls
  // render inert). Built once in the constructor.
  private readonly predictionVoteStore       : PredictionVoteStoreLike | undefined;
  private readonly predictionVoteIntegration : PredictionVoteIntegration | undefined;
  // Section-toolbar / accordion-collapse parity (2026-06-23).
  private readonly viewState                 : ViewStateStoreLike | undefined;
  // B4 (01-D) — active-TTS seam + audio controls + proxy-ratify wiring.
  private readonly ttsQueue                  : TtsQueueStoreLike | undefined;
  private readonly audio                     : AudioControlsLike | undefined;
  private readonly proxyRatifier             : ProxyRatifierLike | undefined;
  private readonly proxyRatifyOpener         : () => void;
  // S2a–d / S3 (2026-09-10) — sender-card header controls.
  private readonly api                       : SenderCardApiLike | undefined;
  private readonly getUserEmail              : () => string | null;
  private readonly confirmFn                 : (message: string) => boolean;
  private readonly clipboardWrite            : (text: string) => Promise<void>;
  private readonly reportFailure             : (message: string) => void;
  // Senders whose ✨ request is in flight. Re-painted after every render: a
  // re-render replaces the card, and with it the button showing ⏳.
  private readonly gistPending               : Set<string> = new Set();
  private closeRenameModal                   : (() => void) | null = null;

  constructor(opts: NotificationsListRendererOptions) {
    this.bus                  = opts.eventBus;
    this.stores               = opts.stores;
    this.appTimezone          = opts.appTimezone;
    this.senderSortComparator = opts.senderSortComparator ?? DEFAULT_SENDER_SORT;
    this.predictionVoteStore  = opts.stores.predictionVote;
    this.viewState            = opts.stores.viewState;
    this.ttsQueue             = opts.stores.ttsQueue;
    this.audio                = opts.stores.audio;
    this.proxyRatifier        = opts.proxyRatifier;
    this.proxyRatifyOpener    = opts.proxyRatifyOpener ?? defaultProxyRatifyOpener;
    this.api                  = opts.api;
    this.getUserEmail         = opts.getUserEmail ?? (() => null);
    /* c8 ignore next */ // production-default fallback: globalThis.confirm is the runtime guard; tests always inject confirmFn.
    this.confirmFn            = opts.confirmFn ?? ((m) => globalThis.confirm(m));
    /* c8 ignore next */ // production-default fallback: the browser clipboard; tests always inject clipboardWrite.
    this.clipboardWrite       = opts.clipboardWrite ?? ((t) => navigator.clipboard.writeText(t));
    this.reportFailure        = opts.reportFailure ?? defaultReportFailure;
    this.predictionVoteIntegration = this.predictionVoteStore === undefined
      ? undefined
      : {
          getVote : (id) => this.predictionVoteStore!.getVote(id),
          onVote  : (id, dir) => this.castPredictionVote(id, dir),
        };
  }

  mount(root: HTMLElement): void {
    if (this.root !== null) {
      throw new Error("NotificationsListRenderer.mount: already mounted");
    }
    this.root = root;
    // Mount-point resolution — SENDER CARDS ONLY (bug 56e422aa AR-rip). This
    // renderer owns ONLY #sender-cards-container; #action-required-section is
    // owned wholesale by the separate ActionRequiredRenderer (mounted
    // document-level in boot.ts), so this renderer never resolves or touches it.
    //
    // #sender-cards-container is OWNED here + guaranteed by the page contract →
    // resolve strictly; THROW LOUDLY if absent (boot.ts:328 models this fail-fast;
    // the former silent `?? root` fallback wiped this node — the 2826d65c crash).
    const senderCardsEl = root.querySelector("#sender-cards-container") as HTMLElement | null;
    if (senderCardsEl === null) {
      throw new Error("NotificationsListRenderer.mount: required #sender-cards-container not found in root");
    }
    this.senderCardsMount = senderCardsEl;

    this.attachClickDelegation();
    this.subscribe();

    // Initial paint per F13: read store.list() once at mount, before any
    // transport activity. If a notification arrives between createStores and
    // mount, it's already in the list (synchronous reducer); the initial
    // paint catches it.
    this.renderSenderSection();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    if (this.clickHandler !== null && this.senderCardsMount !== null) {
      this.senderCardsMount.removeEventListener("click", this.clickHandler);
    }
    this.clickHandler = null;

    if (this.senderCardsMount !== null) this.senderCardsMount.replaceChildren();

    this.expandedGroups.clear();
    this.historyCache.clear();
    this.gistPending.clear();
    if (this.closeRenameModal !== null) this.closeRenameModal();
    this.closeRenameModal = null;
    this.root = null;
    this.senderCardsMount = null;
  }

  forceRenderForTesting(): void {
    this.renderSenderSection();
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
    // WP14 (F8) — reconcile prediction-vote highlight to authoritative store
    // state. The store emits this after a vote is RECORDED (POST 2xx), so a
    // re-render paints the cast-vote `.selected` from getVote() (idempotent with
    // the optimistic click highlight). A failed/rejected cast does NOT emit;
    // castPredictionVote re-renders explicitly to revert in that case.
    this.unsubscribers.push(
      this.bus.on<StorePredictionVoteChangedPayload>(
        "store_prediction_vote_changed",
        () => this.renderSenderSection(),
      ),
    );
    // Section-toolbar collapse-all / expand-all (2026-06-23). The toolbar drives
    // ViewStateStore.requestBulkAccordionCollapse, which emits this; the
    // renderer (sole owner of the accordion DOM) flips every accordion.
    this.unsubscribers.push(
      this.bus.on<StoreViewStateChangedPayload>(
        "store_view_state_changed",
        (e) => this.applyBulkAccordionCollapse(e.payload.changeKind === "collapse-all"),
      ),
    );
    // B4 (01-D) — active-TTS class driver, TWO subscriptions reconciled by ONE
    // pass (F-Sam-BD2): store_tts_queue_changed = IDENTITY (which bubble, from
    // the F0 seam current()); store_audio_state_change = id-blind GLYPH authority
    // (playing/paused), so a pause/resume that does NOT move current() (e.g. the
    // global TTS-chrome-bar pause) still refreshes the current bubble's glyph.
    this.unsubscribers.push(
      this.bus.on("store_tts_queue_changed", () => this.refreshActiveTts()),
    );
    this.unsubscribers.push(
      this.bus.on("store_audio_state_change", () => this.refreshActiveTts()),
    );
  }

  // -------------------------------------------------------------------------
  // Render — hybrid (Q-B): hydrate=full, add/update/expire=keyed, tick=text-only
  // -------------------------------------------------------------------------

  private renderSenderSection(): void {
    /* c8 ignore next */ // defensive: senderCardsMount is set in mount() and only nulled in unmount(); store-event subscriptions are detached in unmount BEFORE this null happens, so this branch is unreachable in normal flow.
    if (this.senderCardsMount === null) return;
    // Filter out action-required notifications — those render in the
    // #action-required-section per D-L mount routing + legacy behavior
    // (legacy `processNewNotification` routes action-required to its own
    // pane, not to the notifications-list). Sender section shows only
    // regular notifications.
    // B3 (01-C): render from the FILTERED view (visibleEntries) so the active
    // filter mode scopes the sender section. Pre-B3 harnesses that stub only
    // list() fall back to the raw list (filter inert).
    const store             = this.stores.notifications;
    const allNotifications  = store.visibleEntries ? store.visibleEntries() : store.list();
    const notifications     = allNotifications.filter(n => !n.action_required);
    const senders           = this.stores.senders.list();

    // Empty-state (Q-K): paint when the active (non-action-required) view is
    // empty. B3: when a filter is active AND the filtered view is empty, the
    // copy distinguishes "nothing matches the filter" from the unfiltered empty.
    if (notifications.length === 0) {
      const filterActive = store.isFilterActive ? store.isFilterActive() : false;
      this.paintEmptyState(filterActive);
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

    // Sort via the configurable sender-level comparator (Phase 6c Node D
    // Step D3 + F-Arnold-D3). Default: most-recent-activity-first; Phase 6c
    // boot override hoists conversation-mode-pinned senders to the top.
    entries.sort((a, b) => this.senderSortComparator(a.sender, b.sender));

    // WP14 (F8): thread the vote integration into the card render path so
    // prediction-hint notifications mount interactive controls (senderCard →
    // dateAccordion → notificationItem).
    const cardOpts = { appTimezone: this.appTimezone, predictionVote: this.predictionVoteIntegration };
    // S4 (2026-09-10) — exactly ONE card is active: the sender with the greatest
    // last_active_ts among the rendered cards (legacy `group.isActive` = the most
    // recent sender). Decided here because only the renderer sees every card; a
    // tie goes to the card sorted first. Every matched card is re-created below,
    // so a change of active sender repaints both the old and the new card.
    let activeId: string | null = null;
    let activeTs = Number.NEGATIVE_INFINITY;
    for (const e of entries) {
      if (e.sender.last_active_ts > activeTs) {
        activeId = e.idHash;
        activeTs = e.sender.last_active_ts;
      }
    }
    const optsFor = (idHash: string) => ({ ...cardOpts, isActive: idHash === activeId });
    keyedListMerge({
      parent  : this.senderCardsMount,
      entries,
      create  : (e) => renderSenderCard(e.sender, e.notifications, optsFor(e.idHash)),
      // On match, re-create-and-replace is the simplest correct strategy for
      // Phase 5 (sender card chrome may have changed: persona, unread count,
      // last_active). Phase 6 may optimize.
      update  : (existing, e) => {
        const fresh = renderSenderCard(e.sender, e.notifications, optsFor(e.idHash));
        existing.replaceWith(fresh);
      },
    });

    // Re-mark expanded progress groups after the render (state preserved
    // across re-renders per F14).
    this.reapplyExpandedGroups();
    // Re-apply persisted accordion-collapse state (sender cards + date
    // accordions) so a user's collapse survives keyed re-renders + reloads
    // (2026-06-23 section-toolbar/accordion parity).
    this.reapplyAccordionCollapse();
    // B4 (01-D) — re-light the actively-spoken bubble after a keyed re-render
    // rebuilds the DOM (the active classes/glyph live on freshly-created nodes).
    this.refreshActiveTts();
    // S2b — a ✨ request still in flight keeps its ⏳ on the fresh button.
    for (const senderId of this.gistPending) this.paintGistButton(senderId, true);
  }

  // -------------------------------------------------------------------------
  // WP14 (F8) — prediction-vote cast orchestration. Invoked by the integration
  // bridge when a vote button is clicked (the template already painted the
  // optimistic highlight synchronously). Stashes the hint context the server
  // does not persist (parity with legacy `_predictionVoteContext`), POSTs the
  // vote, and reconciles: a recorded vote re-renders via the store event
  // subscription (keeps the highlight); a rejected/thrown cast re-renders here
  // to REVERT (getVote → undefined → control paints unselected).
  // -------------------------------------------------------------------------

  private castPredictionVote(id: string, dir: PredictionVoteDir): void {
    const store = this.predictionVoteStore;
    /* c8 ignore next */ // defensive: the integration (sole caller) exists only when the store does.
    if (store === undefined) return;
    const notification = this.stores.notifications.list().find((n) => n.id_hash === id);
    /* c8 ignore next */ // defensive: the control is painted only for an in-list prediction_hint row.
    if (notification?.prediction_hint === undefined) return;
    const hint = notification.prediction_hint;
    store.setContext(id, {
      question        : notification.message,
      predicted_value : hint.predicted_value,
      category        : hint.category,
      response_type   : notification.response_type ?? "",
    });
    void store.vote(id, dir).then((ok) => {
      if (!ok) this.renderSenderSection();
    }).catch(() => {
      this.renderSenderSection();
    });
  }

  // -------------------------------------------------------------------------
  // Empty-state (Q-K) — 4 transitions per F18:
  //   (a) hydrate-with-zero, (b) hydrate-with-N,
  //   (c) post-expired-to-zero, (d) post-added-from-zero
  // -------------------------------------------------------------------------

  private paintEmptyState(filterActive: boolean): void {
    /* c8 ignore next */ // defensive: senderCardsMount post-mount is always set; renderSenderSection's null-guard would have already returned.
    if (this.senderCardsMount === null) return;
    /* c8 ignore next */ // defensive: idempotency check — empty-state is only painted from renderSenderSection's notifications.length === 0 branch which calls paintEmptyState exactly once before bailing out. Re-entry from a re-render with the same empty-state already painted is the case this guards against, but renderSenderSection's flow ensures the existing element is removed via removeEmptyState before re-paint in the non-empty branch.
    // P0 5ebd2aff — the empty state distinguishes "still loading" and "could not
    // load" from a genuinely empty inbox. A cold-load hydration that is pending
    // or has failed has measured nothing, so it must never read "No notifications
    // yet." (measured 2026-09-10: that sentence sat over a 52.8 s fetch the client
    // had abandoned at 10 s). Harnesses without the hydration surface behave as done.
    const store     = this.stores.notifications;
    const hydration = store.historyHydrationState ? store.historyHydrationState() : "done";
    const state     = hydration === "loading" || hydration === "failed"
      ? hydration
      : (filterActive ? "filtered" : "empty");
    const existing = this.senderCardsMount.querySelector(`[data-testid="multiplexer-empty-state"]`);
    if (existing !== null && existing.getAttribute("data-empty-state") === state) return;

    if (state === "failed") {
      const reason  = store.historyHydrationError ? store.historyHydrationError() : null;
      const message = `Couldn't load notification history${reason ? ` (${reason})` : ""}. Nothing was measured — this is not an empty inbox.`;
      const frag = html`
        <div data-testid="multiplexer-empty-state" class="notifications-empty-state" data-empty-state="failed">
          <span class="notifications-empty-state-message">${message}</span>
          <button type="button" class="notifications-history-retry" data-testid="multiplexer-notifications-history-retry">Retry</button>
        </div>
      ` as DocumentFragment;
      this.senderCardsMount.replaceChildren(frag);
      // Direct listener, not the delegated click handler: the button only exists
      // while this state is painted, and replaceChildren drops it with its node.
      const retry = this.senderCardsMount.querySelector("button.notifications-history-retry");
      retry?.addEventListener("click", () => {
        this.bus.emit({ type: HISTORY_RETRY_EVENT, payload: {}, source: "NotificationsListRenderer", ts: Date.now() });
      });
      return;
    }

    // B3 (01-C): filter-aware copy — keyed on isFilterActive() so it works for
    // whatever axis the filter uses (currently the "own" default vs others/all).
    const message = state === "loading"
      ? "Loading notification history…"
      : (state === "filtered" ? "No notifications match this filter." : "No notifications yet.");
    const frag = html`
      <div data-testid="multiplexer-empty-state" class="notifications-empty-state" data-empty-state="${state}">
        ${message}
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

      // 0. B4 (01-D) — per-message active-TTS corner controls + proxy-ratify-link.
      //    The corner buttons live in the .sender-message BODY, so the collapse
      //    closest() lookups below resolve null for these clicks — NO
      //    stopPropagation needed (F-Krishna-BD4). All early-return.
      const pauseBtn = target.closest(".notification-corner-pause-btn");
      if (pauseBtn !== null) {
        // Toggle via AudioStore; the active-TTS driver (store_audio_state_change
        // subscription) owns the resulting class/glyph flip (single authority).
        if (this.audio !== undefined) {
          if (this.audio.state() === "paused") this.audio.resume();
          else this.audio.pause();
        }
        return;
      }
      const stopBtn = target.closest(".notification-corner-stop-btn");
      if (stopBtn !== null) {
        // Halt only — de-light happens when F0 clears current() reacting to
        // store_audio_state_change{idle} (COND-2: NO advance, NO queue mutator).
        this.audio?.stop();
        return;
      }
      const ratifyLink = target.closest(".proxy-ratify-link");
      if (ratifyLink !== null) {
        e.preventDefault();   // <a href="#"> — suppress hash navigation
        // Acknowledge call (apiClient) + page-open (renderer-side), per
        // F-Krishna-BD3 / F-Sam-BD3. Fire-and-forget; legacy swallows errors too.
        if (this.proxyRatifier !== undefined) {
          void this.proxyRatifier.acknowledgeProxy().catch(() => { /* swallow — non-blocking acknowledge */ });
        }
        this.proxyRatifyOpener();
        return;
      }

      // 1. Progress-group lazy-expand toggle (Q-G + F14).
      const toggle = target.closest(".progress-group-toggle") as HTMLElement | null;
      if (toggle !== null) {
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
        return;
      }

      // 2a. S3 (2026-09-10) — per-date × soft delete. Checked BEFORE the date
      //     header toggle: the button sits inside that header, and its click
      //     must never collapse the accordion.
      const dateDeleteBtn = target.closest(".date-delete-btn");
      if (dateDeleteBtn !== null) {
        void this.softDeleteDate(dateDeleteBtn);
        return;
      }

      // 2. Date-accordion header click → collapse/expand that date group
      //    (carbon-copy of legacy toggleDateAccordion). The header's one control
      //    (the × above) has already returned, so any other click in it toggles.
      const dateHeader = target.closest(".date-accordion-header");
      if (dateHeader !== null) {
        this.toggleDateAccordion(dateHeader);
        return;
      }

      // 3. Sender-card header click → collapse/expand the whole sender card
      //    (carbon-copy of legacy toggleSenderCard). The header ALSO holds
      //    interactive controls (persona badge, copy/gist/rename, delete) — a
      //    click on any of those is owned by its own handler, NOT a collapse.
      const senderHeader = target.closest(".sender-card-header");
      if (senderHeader !== null) {
        // S2a–d (2026-09-10) — the header's own controls: 📋 copy, ✨ gist,
        // click-to-rename, × delete-all. The persona badge is a native
        // popovertarget <button> and falls through to the guard below.
        const control = target.closest(".sender-session-copy, .sender-gist-btn, .sender-session-name, .sender-delete-btn") as HTMLElement | null;
        if (control !== null) {
          this.onSenderHeaderControl(control);
          return;
        }
        if (target.closest("button, .copy-btn, .sender-session-name") !== null) return;
        this.toggleSenderCard(senderHeader);
        return;
      }
    };
    this.senderCardsMount.addEventListener("click", this.clickHandler);
  }

  // -------------------------------------------------------------------------
  // Accordion collapse (sender card + date accordion) — section-toolbar parity
  // (2026-06-23). Carbon-copy of legacy toggleSenderCard / toggleDateAccordion
  // re-expressed via `data-collapsed` (the mux idiom; the hide CSS already
  // exists in the shared sheet for date accordions + the mux list sheet for
  // sender cards). State persists in ViewStateStore (when wired) so it survives
  // keyed re-renders + reloads.
  // -------------------------------------------------------------------------

  private toggleDateAccordion(header: Element): void {
    const accordion = header.closest(".date-accordion") as HTMLElement | null;
    /* c8 ignore next */ // defensive: a .date-accordion-header is always inside a .date-accordion by template.
    if (accordion === null) return;
    const next = accordion.getAttribute("data-collapsed") !== "true";
    this.applyCollapsed(accordion, next, ".date-toggle");
    const id = this.dateAccordionId(accordion);
    if (id !== null) this.viewState?.setAccordionCollapsed(id, next);
  }

  private toggleSenderCard(header: Element): void {
    const card = header.closest(".sender-card") as HTMLElement | null;
    /* c8 ignore next */ // defensive: a .sender-card-header is always inside a .sender-card by template.
    if (card === null) return;
    const next = card.getAttribute("data-collapsed") !== "true";
    this.applyCollapsed(card, next, ".sender-toggle");
    const senderId = card.dataset["senderId"];
    if (senderId !== undefined) this.viewState?.setAccordionCollapsed(`sender::${senderId}`, next);
  }

  // Apply a collapsed flag to an accordion element + flip its toggle glyph
  // (▼ expanded / ▶ collapsed). `toggleSelector` finds the header chevron.
  private applyCollapsed(el: HTMLElement, collapsed: boolean, toggleSelector: string): void {
    el.setAttribute("data-collapsed", collapsed ? "true" : "false");
    const toggle = el.querySelector(toggleSelector) as HTMLElement | null;
    /* c8 ignore next */ // defensive: the chevron span is emitted by the template for every accordion header.
    if (toggle !== null) toggle.textContent = collapsed ? "▶" : "▼";
  }

  // Stable persistence id for a date accordion: `date::<sender_id>::<date_key>`.
  private dateAccordionId(accordion: HTMLElement): string | null {
    const card     = accordion.closest(".sender-card") as HTMLElement | null;
    const senderId = card?.dataset["senderId"];
    const dateKey  = accordion.dataset["dateKey"];
    if (senderId === undefined || dateKey === undefined) return null;
    return `date::${senderId}::${dateKey}`;
  }

  // Walk every accordion currently in the mount — each sender card (id
  // `sender::<sender_id>`, chevron `.sender-toggle`) and each date accordion
  // within it (id from dateAccordionId, chevron `.date-toggle`). The per-id
  // guard branches (a card without `data-sender-id`, an accordion without a
  // resolvable id) live HERE only, so both reapply + bulk share one coverage
  // surface.
  private forEachAccordion(fn: (el: HTMLElement, id: string, toggleSel: string) => void): void {
    /* c8 ignore next */ // defensive: callers (reapply via render, bulk via bus) both run while mounted; subscriptions detach before senderCardsMount is nulled.
    if (this.senderCardsMount === null) return;
    for (const card of Array.from(this.senderCardsMount.querySelectorAll<HTMLElement>(".sender-card"))) {
      const senderId = card.dataset["senderId"];
      if (senderId !== undefined) fn(card, `sender::${senderId}`, ".sender-toggle");
      for (const acc of Array.from(card.querySelectorAll<HTMLElement>(".date-accordion"))) {
        const id = this.dateAccordionId(acc);
        if (id !== null) fn(acc, id, ".date-toggle");
      }
    }
  }

  // Re-apply persisted collapse state to every accordion after a render. Reads
  // the store; a no-op when no store is wired.
  private reapplyAccordionCollapse(): void {
    const store = this.viewState;
    if (store === undefined) return;
    this.forEachAccordion((el, id, sel) => this.applyCollapsed(el, store.isAccordionCollapsed(id), sel));
  }

  // Collapse-all / expand-all (toolbar-driven). Flips EVERY accordion (sender
  // cards AND date accordions) + persists each (when a store is wired).
  private applyBulkAccordionCollapse(collapsed: boolean): void {
    const store = this.viewState;
    this.forEachAccordion((el, id, sel) => {
      this.applyCollapsed(el, collapsed, sel);
      store?.setAccordionCollapsed(id, collapsed);
    });
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
  // B4 (01-D) — active-TTS class driver. CLEAR-PRIOR-THEN-SET (F-Sam-BD1) so
  // EXACTLY ONE bubble ever lights. Identity (which bubble) comes from the F0
  // seam `ttsQueue.current()` (READ-ONLY — COND-2 provable by shape); the
  // playing/paused glyph comes from the id-blind `audio.state()`. Legacy analog:
  // notifications.js:14903-14971.
  // -------------------------------------------------------------------------

  private refreshActiveTts(): void {
    /* c8 ignore next */ // defensive: senderCardsMount set post-mount; subscriptions detach before it is nulled in unmount.
    if (this.senderCardsMount === null) return;
    // CLEAR-PRIOR — strip the active classes from EVERY lit bubble + reset its
    // pause glyph, so a stale bubble never lingers across a current() transition.
    const lit = this.senderCardsMount.querySelectorAll<HTMLElement>(
      ".sender-message.tts-playing, .sender-message.is-playing-current, .sender-message.is-paused-current",
    );
    for (const el of Array.from(lit)) {
      el.classList.remove("tts-playing", "is-playing-current", "is-paused-current");
      this.setPauseGlyph(el, false);
    }
    // SET — light exactly the bubble whose id_hash === current(). current()===null
    // (or no ttsQueue wired) leaves everything cleared.
    const activeId = this.ttsQueue?.current() ?? null;
    if (activeId === null) return;
    const bubble = this.senderCardsMount.querySelector<HTMLElement>(
      `.sender-message[data-id-hash="${cssEscape(activeId)}"]`,
    );
    if (bubble === null) return;   // active message not currently in the DOM (collapsed/filtered/not-yet-rendered)
    bubble.classList.add("tts-playing", "is-playing-current");
    const paused = this.audio?.state() === "paused";
    if (paused) bubble.classList.add("is-paused-current");
    this.setPauseGlyph(bubble, paused);
  }

  // Flip a bubble's corner pause button between ⏸ (playing) and ▶ (paused),
  // keeping data-paused + title + aria-label in sync. No-op when the bubble has
  // no pause button (e.g. an outgoing/response bubble).
  private setPauseGlyph(bubble: Element, paused: boolean): void {
    const btn = bubble.querySelector<HTMLButtonElement>(".notification-corner-pause-btn");
    if (btn === null) return;
    btn.dataset.paused = paused ? "true" : "false";
    btn.textContent    = paused ? "▶" : "⏸";
    btn.title          = paused ? "Resume this notification's playback" : "Pause this notification's playback";
    btn.setAttribute("aria-label", paused ? "Resume notification audio" : "Pause notification audio");
  }

  // -------------------------------------------------------------------------
  // S2a–d / S3 (2026-09-10) — sender-card header controls + per-date delete.
  // Ports of legacy copySenderSessionId / generateSessionGist / editSessionName /
  // deleteSenderConversation / softDeleteByDate (notifications.js:1634, 18383,
  // 18015, 20376, 19304), reached through the delegated click handler instead of
  // inline onclick. Failures go to `reportFailure` — legacy only logged them.
  // -------------------------------------------------------------------------

  private onSenderHeaderControl(control: HTMLElement): void {
    const card     = control.closest(".sender-card") as HTMLElement | null;
    /* c8 ignore next 2 */ // defensive: every header control sits inside a .sender-card carrying data-sender-id, by template.
    const senderId = card?.dataset["senderId"];
    if (senderId === undefined) return;
    if (control.classList.contains("sender-session-copy")) this.copySessionId(senderId, control);
    else if (control.classList.contains("sender-gist-btn")) void this.generateGist(senderId);
    else if (control.classList.contains("sender-session-name")) this.openRename(senderId, control.ownerDocument);
    else void this.deleteSenderConversation(senderId);
  }

  // 📋 — copy the hex session id WITHOUT the '#', then flash ✅ for 1200 ms.
  private copySessionId(senderId: string, btn: HTMLElement): void {
    const hex = senderId.slice(senderId.indexOf("#") + 1);
    void this.clipboardWrite(hex).then(() => {
      btn.textContent = "✅";
      setTimeout(() => { btn.textContent = "📋"; }, COPY_FLASH_MS);
    }).catch(() => {
      this.reportFailure("Could not copy the session ID to the clipboard.");
    });
  }

  // ✨ — ask the server for a short gist of this sender's messages + abstracts
  // and make it the session name. The button is disabled / `working` / ⏳ while
  // the request is out, and back to ✨ however it ends.
  private async generateGist(senderId: string): Promise<void> {
    if (this.api === undefined || this.gistPending.has(senderId)) return;
    const mine      = this.stores.notifications.list().filter(n => n.sender_id === senderId);
    const messages  = mine.map(n => n.message).filter(Boolean);
    const abstracts = mine.map(n => n.abstract).filter(Boolean);
    if (messages.length === 0 && abstracts.length === 0) return;

    this.gistPending.add(senderId);
    this.paintGistButton(senderId, true);
    try {
      const data = await this.api.post<{ gist?: unknown } | null>("/api/notifications/generate-gist", { messages, abstracts });
      const gist = typeof data?.gist === "string" ? data.gist.trim() : "";
      if (gist === "") throw new Error("the server returned no gist");
      this.stores.senders.setSessionName?.(senderId, gist);
    } catch (err) {
      this.reportFailure(`Could not generate a session gist: ${(err as Error).message}`);
    } finally {
      this.gistPending.delete(senderId);
      this.paintGistButton(senderId, false);
    }
  }

  private paintGistButton(senderId: string, working: boolean): void {
    const btn = this.senderCardsMount?.querySelector<HTMLButtonElement>(
      `.sender-card[data-sender-id="${cssEscape(senderId)}"] .sender-gist-btn`,
    );
    if (!btn) return;   // unmounted, or the card is gone (deleted / filtered out)
    btn.disabled    = working;
    btn.classList.toggle("working", working);
    btn.textContent = working ? "⏳" : "✨";
  }

  // Click on the session name — open the Rename Session modal prefilled with the
  // current name. Save goes through SenderStore, whose change event re-renders.
  private openRename(senderId: string, doc: Document): void {
    const record = this.stores.senders.list().find(s => s.sender_id === senderId);
    this.closeRenameModal = openSessionNameEditModal({
      doc,
      currentName : record?.session_name ?? "",
      onSave      : (name) => this.stores.senders.setSessionName?.(senderId, name),
    });
  }

  // × on the sender header — confirm, DELETE the whole conversation server-side,
  // then drop this sender's rows from the store (the card goes on re-render).
  // Legacy removes the card EVEN WHEN the server call fails (notifications.js:
  // 20411-20430). Mirrored, but the failure is reported rather than swallowed:
  // the rows are gone from this view while the server may still hold them.
  private async deleteSenderConversation(senderId: string): Promise<void> {
    if (this.api === undefined) return;
    const ids     = this.stores.notifications.list().filter(n => n.sender_id === senderId).map(n => n.id_hash);
    const count   = ids.length;
    const noun    = count === 1 ? "message" : "messages";
    const project = projectFromSenderId(senderId);
    if (!this.confirmFn(`Delete all ${count} ${noun} from ${project}? This cannot be undone.`)) return;

    let failure: string | null = null;
    const email = this.getUserEmail();
    if (!email) {
      failure = "no signed-in user email";
    } else {
      try {
        await this.api.delete(`/api/notifications/conversation/${encodeURIComponent(senderId)}/${encodeURIComponent(email)}`);
      } catch (err) {
        failure = (err as Error).message;
      }
    }
    this.stores.notifications.removeByIdHashes?.(ids);
    if (failure !== null) {
      this.reportFailure(`Removed ${count} ${noun} from ${project} in this view, but the server delete failed (${failure}); they may come back on reload.`);
    }
  }

  // × on a date header — confirm, soft-delete that day server-side, and ONLY on
  // success drop that day's rows from the store. Legacy softDeleteByDate removes
  // nothing on failure either (notifications.js:19341-19349).
  private async softDeleteDate(btn: Element): Promise<void> {
    if (this.api === undefined) return;
    const accordion = btn.closest(".date-accordion") as HTMLElement | null;
    const card      = btn.closest(".sender-card") as HTMLElement | null;
    /* c8 ignore next 3 */ // defensive: the × is emitted inside a .date-accordion (data-date-key) inside a .sender-card (data-sender-id), by template.
    const dateKey   = accordion?.dataset["dateKey"];
    const senderId  = card?.dataset["senderId"];
    if (dateKey === undefined || senderId === undefined) return;
    if (!this.confirmFn(`Hide all notifications from ${dateKey}?`)) return;

    const email = this.getUserEmail();
    if (!email) {
      this.reportFailure(`Could not hide notifications from ${dateKey}: no signed-in user email.`);
      return;
    }
    try {
      await this.api.delete(`/api/notifications/date/${encodeURIComponent(senderId)}/${encodeURIComponent(email)}/${encodeURIComponent(dateKey)}`);
    } catch (err) {
      this.reportFailure(`Could not hide notifications from ${dateKey}: ${(err as Error).message}`);
      return;
    }
    // The same date key the card grouped by, so exactly that accordion's rows go.
    const ids = this.stores.notifications.list()
      .filter(n => n.sender_id === senderId && formatDateKey(n.ts, this.appTimezone) === dateKey)
      .map(n => n.id_hash);
    this.stores.notifications.removeByIdHashes?.(ids);
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

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
      sender_id                : senderId,
      display_name             : senderId,
      last_active_ts           : last,
      unread_count             : notifs.length,
      conversation_mode_active : false,
    };
  }
}

// S2a — how long the 📋 button shows ✅ after a copy (legacy notifications.js:1652).
const COPY_FLASH_MS = 1200;

// S2d — the project label in the delete-all confirm, verbatim to legacy
// getProjectFromSenderId (notifications.js:15535): the upper-cased project of a
// `claude.code@<project>.deepily.ai[#session]` id, else "UNKNOWN".
function projectFromSenderId(senderId: string): string {
  const project = senderId.match(/^claude\.code@([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\.deepily\.ai/)?.[1];
  return project === undefined ? "UNKNOWN" : project.toUpperCase();
}

// S2a–d / S3 — default failure surface: the console for the record, and an alert
// so the operator actually sees it. Tests inject a recording reportFailure.
/* c8 ignore next 4 */ // production-default browser surface; never exercised under node:test.
function defaultReportFailure(message: string): void {
  console.error(`[NotificationsListRenderer] ${message}`);
  globalThis.alert(message);
}

// B4 (01-D) — default proxy-ratify page opener. Opens (or focuses) the single
// ratify admin tab, verbatim to legacy notifications.js:7203. Tests inject a
// recording opener via options.proxyRatifyOpener (mirrors ApiClient.fetcher).
/* c8 ignore next 3 */ // production-default browser page-open; never exercised under node:test (a recording opener is injected).
function defaultProxyRatifyOpener(): void {
  window.open("/app/admin/proxy-ratify", "lupin-proxy-ratify");
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
