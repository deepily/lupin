/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line.
// Multiplexer B3 (01-C) — NotificationsHeaderRenderer.
//
// The section-header control cluster the mux lacked (doc 01 §2 "0 refs"):
//   - count span (#notifications-count) — the active-list TOTAL (list().length,
//     F-Sam-BC3), NOT unreadCount; matches legacy notifications.js:15229/15294.
//   - history-dropdown — a toggle button + panel listing NotificationStore
//     .history() (REUSE the existing data path; ports legacy UI intent).
//   - clear-all (#clear-all-notifications) — confirm() guard → server-durable
//     delete-by-id over visibleEntries() (DELETE /api/notifications/{id_hash})
//     → store.removeByIdHashes(SUCCESSES only). Filter-scoped + partial-failure
//     safe per the Mr. Radio 2026-06-29 ruling (OSQ-B3.6 preferred path).
//
// Chrome idiom mirrors TaskListRenderer/FleetStatusRenderer (BC1a): plain
// createElement + addEventListener (no inline onclick — mux no-globals rule).
//
// OWNERSHIP BOUNDARY: this renderer owns the clear-all ORCHESTRATION (confirm →
// API delete loop → partial-failure UX) + the count/history DOM. The STORE owns
// its data (filterMode/visibleEntries/removeByIdHashes). No cross-store leakage.
//
// DEFERRED per Rick's own-only scope (67fc18f0/a767e1ae): the filter-badge, the
// own/others/all toggle, and admin-gating are NOT built here.

import type { EventBus } from "../shared/EventBus";
import type { Notification, StoreNotificationsChangedPayload } from "../shared/types";

// Narrowed NotificationStore surface this renderer consumes (the production
// NotificationStore satisfies it structurally).
export interface NotificationsHeaderStoreLike {
  list(): ReadonlyArray<Notification>;
  history(): ReadonlyArray<Notification>;
  visibleEntries(): ReadonlyArray<Notification>;
  removeByIdHashes(idHashes: ReadonlyArray<string>): void;
}

// Narrowed api surface — only the generic delete<T> is needed (reused, not a
// new typed method); production passes the canonical ApiClient.
export interface NotificationDeleteApiLike {
  delete<T>(path: string): Promise<T>;
}

export interface NotificationsHeaderRendererOptions {
  eventBus  : EventBus;
  store     : NotificationsHeaderStoreLike;
  api       : NotificationDeleteApiLike;
  // Test injection — production uses globalThis.confirm. Returns the user's
  // yes/no to the "cannot be undone" guard.
  confirmFn?: (message: string) => boolean;
}

export interface NotificationsHeaderRenderer {
  mount(root: HTMLElement): void;
  unmount(): void;
}

const CLEAR_CONFIRM = "Clear all notifications? This cannot be undone.";

class NotificationsHeaderRendererImpl implements NotificationsHeaderRenderer {
  private readonly bus       : EventBus;
  private readonly store     : NotificationsHeaderStoreLike;
  private readonly api       : NotificationDeleteApiLike;
  private readonly confirmFn : (message: string) => boolean;

  private mounted      = false;
  private root         : HTMLElement | null        = null;
  private countEl      : HTMLElement | null        = null;
  private clearBtn     : HTMLButtonElement | null   = null;
  private historyBtn   : HTMLButtonElement | null   = null;
  private historyPanel : HTMLElement | null        = null;
  private statusEl     : HTMLElement | null        = null;
  private historyOpen  = false;

  private readonly unsubscribers : Array<() => void> = [];

  constructor(opts: NotificationsHeaderRendererOptions) {
    if (!opts.store) throw new Error("NotificationsHeaderRenderer requires a store");
    this.bus       = opts.eventBus;
    this.store     = opts.store;
    this.api       = opts.api;
    /* c8 ignore next */ // production-default fallback: globalThis.confirm is the runtime guard; tests always inject confirmFn.
    this.confirmFn = opts.confirmFn ?? ((m) => globalThis.confirm(m));
  }

  mount(root: HTMLElement): void {
    if (this.mounted) throw new Error("NotificationsHeaderRenderer already mounted");
    this.root    = root;
    this.mounted = true;

    const header = document.createElement("header");
    header.className = "notifications-header";
    header.setAttribute("data-testid", "multiplexer-notifications-header");

    const title = document.createElement("h2");
    title.className = "notifications-header-title";
    title.textContent = "🔔 Notifications";
    header.appendChild(title);

    this.countEl = document.createElement("span");
    this.countEl.className = "notifications-count";
    this.countEl.id = "notifications-count";
    this.countEl.setAttribute("data-testid", "multiplexer-notifications-count");
    header.appendChild(this.countEl);

    // History dropdown — toggle button + (initially hidden) panel.
    this.historyBtn = document.createElement("button");
    this.historyBtn.type = "button";
    this.historyBtn.className = "notifications-history-toggle";
    this.historyBtn.id = "history-dropdown-toggle";
    this.historyBtn.setAttribute("data-testid", "multiplexer-notifications-history-toggle");
    this.historyBtn.textContent = "History ▾";
    this.historyBtn.addEventListener("click", () => this.toggleHistory());
    header.appendChild(this.historyBtn);

    // Clear-all.
    this.clearBtn = document.createElement("button");
    this.clearBtn.type = "button";
    this.clearBtn.className = "notifications-clear-all";
    this.clearBtn.id = "clear-all-notifications";
    this.clearBtn.setAttribute("data-testid", "multiplexer-notifications-clear-all");
    this.clearBtn.textContent = "Clear all";
    this.clearBtn.addEventListener("click", () => void this.onClearAll());
    header.appendChild(this.clearBtn);

    this.statusEl = document.createElement("span");
    this.statusEl.className = "notifications-header-status";
    this.statusEl.setAttribute("data-testid", "multiplexer-notifications-header-status");
    header.appendChild(this.statusEl);

    this.historyPanel = document.createElement("div");
    this.historyPanel.className = "notifications-history-panel";
    this.historyPanel.id = "history-dropdown-container";
    this.historyPanel.setAttribute("data-testid", "multiplexer-notifications-history-panel");
    this.historyPanel.hidden = true;

    root.replaceChildren(header, this.historyPanel);

    this.unsubscribers.push(
      this.bus.on<StoreNotificationsChangedPayload>(
        "store_notifications_changed",
        () => this.refresh(),
      ),
    );

    this.refresh();
  }

  unmount(): void {
    if (!this.mounted) return;
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;
    if (this.root !== null) this.root.replaceChildren();
    this.root = this.countEl = this.clearBtn = null;
    this.historyBtn = null;
    this.historyPanel = this.statusEl = null;
    this.historyOpen = false;
    this.mounted = false;
  }

  // -------------------------------------------------------------------------
  // Count + clear-all enablement
  // -------------------------------------------------------------------------

  private refresh(): void {
    /* c8 ignore next */ // defensive: refresh only fires between mount and unmount, when countEl/clearBtn are set.
    if (this.countEl === null || this.clearBtn === null) return;
    // Count = raw active TOTAL (F-Sam-BC3), not the filtered view.
    this.countEl.textContent = String(this.store.list().length);
    // Clear-all clears the active filter scope — disabled when nothing visible.
    this.clearBtn.disabled = this.store.visibleEntries().length === 0;
    // Keep an open history panel in sync with the latest history().
    if (this.historyOpen) this.renderHistory();
  }

  // -------------------------------------------------------------------------
  // History dropdown
  // -------------------------------------------------------------------------

  private toggleHistory(): void {
    this.historyOpen = !this.historyOpen;
    /* c8 ignore next */ // defensive: historyPanel is set post-mount.
    if (this.historyPanel === null) return;
    this.historyPanel.hidden = !this.historyOpen;
    if (this.historyOpen) this.renderHistory();
  }

  private renderHistory(): void {
    /* c8 ignore next */ // defensive: historyPanel is set post-mount when this is reachable.
    if (this.historyPanel === null) return;
    const rows = this.store.history();
    if (rows.length === 0) {
      const empty = document.createElement("div");
      empty.className = "notifications-history-empty";
      empty.textContent = "No history.";
      this.historyPanel.replaceChildren(empty);
      return;
    }
    const frag = document.createDocumentFragment();
    for (const n of rows) {
      const row = document.createElement("div");
      row.className = "notifications-history-row";
      row.setAttribute("data-id-hash", n.id_hash);
      const when = document.createElement("span");
      when.className = "notifications-history-time";
      when.textContent = n.time_display ?? new Date(n.ts).toISOString();
      const msg = document.createElement("span");
      msg.className = "notifications-history-message";
      msg.textContent = n.message;
      row.appendChild(when);
      row.appendChild(msg);
      frag.appendChild(row);
    }
    this.historyPanel.replaceChildren(frag);
  }

  // -------------------------------------------------------------------------
  // Clear-all — filter-scoped, server-durable delete-by-id, partial-failure safe
  // -------------------------------------------------------------------------

  private async onClearAll(): Promise<void> {
    const ids = this.store.visibleEntries().map(n => n.id_hash);
    if (ids.length === 0) return;                 // nothing in scope (button also disabled)
    if (!this.confirmFn(CLEAR_CONFIRM)) return;   // user declined the "cannot be undone" guard

    const succeeded: string[] = [];
    let failed = 0;
    for (const id of ids) {
      try {
        await this.api.delete(`/api/notifications/${encodeURIComponent(id)}`);
        succeeded.push(id);
      } catch {
        failed++;   // N independent (non-atomic) deletes — track, do not abort the rest
      }
    }

    // Remove ONLY the server-durably-deleted ids; failed ids stay in the store
    // (re-rendered) so the UI never claims a clear it did not achieve.
    if (succeeded.length > 0) this.store.removeByIdHashes(succeeded);

    if (this.statusEl !== null) {
      this.statusEl.textContent = failed === 0
        ? `Cleared ${succeeded.length}.`
        : `Cleared ${succeeded.length}, ${failed} failed.`;
    }
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the factory declaration line.
export function createNotificationsHeaderRenderer(
  opts: NotificationsHeaderRendererOptions,
): NotificationsHeaderRenderer {
  return new NotificationsHeaderRendererImpl(opts);
}
