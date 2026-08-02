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
import {
  renderSectionHeader,
  setSectionCollapsed,
  type SectionHeaderHandle,
} from "./templates/sectionHeader";

// Narrowed NotificationStore surface this renderer consumes (the production
// NotificationStore satisfies it structurally).
export interface NotificationsHeaderStoreLike {
  list(): ReadonlyArray<Notification>;
  history(): ReadonlyArray<Notification>;
  visibleEntries(): ReadonlyArray<Notification>;
  removeByIdHashes(idHashes: ReadonlyArray<string>): void;
}

// Narrowed api surface — the generic delete<T> (clear-all) plus the managed
// bounce (row 1b4211ac R2). Production passes the canonical ApiClient, which
// satisfies both structurally.
export interface NotificationDeleteApiLike {
  delete<T>(path: string): Promise<T>;
  // Managed dev-server bounce. On 202 the host-side watcher was handed the job;
  // a 409/503 is thrown as an error carrying a numeric `status`.
  bounceDevServer(): Promise<{ status: string; detail?: string; timestamp: string }>;
}

// Narrowed sys_time_update payload (server clock loop, main.py:265 →
// {date, env_label}). Both fields optional — the renderer degrades to empty.
export interface SysTimeUpdatePayload {
  date?      : string;
  env_label? : string;
}

export interface NotificationsHeaderRendererOptions {
  eventBus  : EventBus;
  store     : NotificationsHeaderStoreLike;
  api       : NotificationDeleteApiLike;
  // Test injection — production uses globalThis.confirm. Returns the user's
  // yes/no to the "cannot be undone" guard.
  confirmFn?: (message: string) => boolean;
  // Managed dev-server bounce (row 1b4211ac R2). All test-injectable; production
  // uses globalThis.fetch to poll /health across the ~20s restart window.
  fetchFn?      : typeof fetch;
  bouncePollMs? : number;   // health poll interval (default 1500)
  bounceWaitMs? : number;   // give-up timeout      (default 90000)
  bounceGraceMs?: number;   // accept ok after this even if no down-blip was seen (default 25000)
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
  private readonly fetchFn      : typeof fetch;
  private readonly bouncePollMs : number;
  private readonly bounceWaitMs : number;
  private readonly bounceGraceMs: number;

  private mounted      = false;
  private root         : HTMLElement | null        = null;
  private countEl      : HTMLElement | null        = null;
  private clearBtn     : HTMLButtonElement | null   = null;
  private bounceBtn    : HTMLButtonElement | null   = null;
  private historyBtn   : HTMLButtonElement | null   = null;
  private historyPanel : HTMLElement | null        = null;
  private statusEl     : HTMLElement | null        = null;
  private envLabelEl   : HTMLElement | null        = null;
  private clockEl      : HTMLElement | null        = null;
  // Lane 0a — the section-header handle + the collapse click-listener (the
  // notifications body pane is a SEPARATE mount, so collapse targets the sibling
  // #notifications-pane rather than a child .section-content).
  private header       : SectionHeaderHandle | null = null;
  private headerClick  : ( ( e: Event ) => void ) | null = null;
  private historyOpen  = false;

  private readonly unsubscribers : Array<() => void> = [];

  constructor(opts: NotificationsHeaderRendererOptions) {
    if (!opts.store) throw new Error("NotificationsHeaderRenderer requires a store");
    this.bus       = opts.eventBus;
    this.store     = opts.store;
    this.api       = opts.api;
    /* c8 ignore next */ // production-default fallback: globalThis.confirm is the runtime guard; tests always inject confirmFn.
    this.confirmFn = opts.confirmFn ?? ((m) => globalThis.confirm(m));
    /* c8 ignore next */ // production-default fallback: globalThis.fetch is the runtime health poll; tests always inject fetchFn.
    this.fetchFn       = opts.fetchFn ?? globalThis.fetch.bind(globalThis);
    this.bouncePollMs  = opts.bouncePollMs  ?? 1500;
    this.bounceWaitMs  = opts.bounceWaitMs  ?? 90000;
    this.bounceGraceMs = opts.bounceGraceMs ?? 25000;
  }

  mount(root: HTMLElement): void {
    if (this.mounted) throw new Error("NotificationsHeaderRenderer already mounted");
    this.root    = root;
    this.mounted = true;

    // H2 (parity) — env-label prefix + live clock suffix, ported from legacy
    // notifications.html:80 `<h2><span id=env-label></span>Notifications <span id=clock></span></h2>`
    // + notifications.js:2793-2798 (both driven off the sys_time_update WS frame,
    // payload {date, env_label} from main.py:265). Empty until the first tick —
    // exactly like legacy, which also populates via that same WS event.
    this.envLabelEl = document.createElement("span");
    this.envLabelEl.className = "notifications-env-label";
    this.envLabelEl.id = "env-label";
    this.envLabelEl.setAttribute("data-testid", "multiplexer-notifications-env-label");

    this.clockEl = document.createElement("span");
    this.clockEl.className = "notifications-clock";
    this.clockEl.id = "clock";
    this.clockEl.setAttribute("data-testid", "multiplexer-notifications-clock");

    // History dropdown — toggle button + (initially hidden) panel.
    this.historyBtn = document.createElement("button");
    this.historyBtn.type = "button";
    this.historyBtn.className = "notifications-history-toggle";
    this.historyBtn.id = "history-dropdown-toggle";
    this.historyBtn.setAttribute("data-testid", "multiplexer-notifications-history-toggle");
    this.historyBtn.textContent = "History ▾";
    this.historyBtn.addEventListener("click", () => this.toggleHistory());

    // Clear-all.
    this.clearBtn = document.createElement("button");
    this.clearBtn.type = "button";
    this.clearBtn.className = "notifications-clear-all";
    this.clearBtn.id = "clear-all-notifications";
    this.clearBtn.setAttribute("data-testid", "multiplexer-notifications-clear-all");
    this.clearBtn.textContent = "Clear all";
    this.clearBtn.addEventListener("click", () => void this.onClearAll());

    // Managed dev-server bounce (row 1b4211ac R2) — the simplest access Rick asked
    // for, mirrored from the notification client's toolbar button.
    this.bounceBtn = document.createElement("button");
    this.bounceBtn.type = "button";
    this.bounceBtn.className = "notifications-bounce-server";
    this.bounceBtn.id = "bounce-dev-server";
    this.bounceBtn.setAttribute("data-testid", "multiplexer-bounce-dev-server");
    this.bounceBtn.title = "Bounce the dev server (:7999) — warns the fleet, then restarts (~20s)";
    this.bounceBtn.textContent = "🔄 Bounce server";
    this.bounceBtn.addEventListener("click", () => void this.onBounce());

    this.statusEl = document.createElement("span");
    this.statusEl.className = "notifications-header-status";
    this.statusEl.setAttribute("data-testid", "multiplexer-notifications-header-status");

    // Lane 0a — convert the bespoke `.notifications-header` into the uniform
    // `.section-header` bar (🔔 Notifications). The history-toggle + clear-all +
    // status move into `.section-header-actions`; the count uses the shared
    // `.section-header-count` chip (its legacy id + testid preserved so existing
    // selectors resolve). The env-label prefix + live clock are injected into the
    // h3 around the "🔔 Notifications" title (legacy parity).
    const header = renderSectionHeader({
      icon    : "🔔",
      title   : "Notifications",
      testid  : "multiplexer-notifications-header",
      actions : [ this.historyBtn, this.clearBtn, this.bounceBtn, this.statusEl ],
    });
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.id = "notifications-count";
    this.countEl.setAttribute("data-testid", "multiplexer-notifications-count");

    const h3 = header.header.querySelector("h3") as HTMLElement;
    // env-label BEFORE the icon/title; clock AFTER the title, before the count.
    h3.insertBefore(this.envLabelEl, h3.firstChild);
    h3.insertBefore(this.clockEl, this.countEl);

    this.historyPanel = document.createElement("div");
    this.historyPanel.className = "notifications-history-panel";
    this.historyPanel.id = "history-dropdown-container";
    this.historyPanel.setAttribute("data-testid", "multiplexer-notifications-history-panel");
    this.historyPanel.hidden = true;

    root.replaceChildren(header.header, this.historyPanel);

    // Session-only collapse — the notifications LIST lives in the sibling
    // #notifications-pane (a separate mount owned by NotificationsListRenderer),
    // so the chevron toggles `data-collapsed` on THAT pane (mux rule
    // `#notifications-pane[data-collapsed="true"]` hides it), not a child of this
    // header's mount. A click on a header control (button/etc.) does not collapse.
    this.headerClick = ( e: Event ): void => {
      const target = e.target as Element | null;
      /* c8 ignore next */ // defensive: a dispatched click always carries a target.
      if ( target === null ) return;
      if ( target.closest("button, a, input, select") !== null ) return;
      const pane = root.ownerDocument.getElementById("notifications-pane");
      if ( pane === null ) return;   // header-only context (no body pane): no-op
      const collapsed = pane.getAttribute("data-collapsed") === "true";
      setSectionCollapsed( pane, header, !collapsed );
    };
    header.header.addEventListener("click", this.headerClick);

    this.unsubscribers.push(
      this.bus.on<StoreNotificationsChangedPayload>(
        "store_notifications_changed",
        () => this.refresh(),
      ),
      // H2 (parity) — server clock/env broadcast (main.py clock loop). Legacy
      // notifications.js:2793-2798 updates #clock + #env-label off the same frame.
      this.bus.on<SysTimeUpdatePayload>(
        "sys_time_update",
        (e) => this.onSysTimeUpdate(e.payload),
      ),
    );

    this.refresh();
  }

  unmount(): void {
    if (!this.mounted) return;
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;
    if (this.header !== null && this.headerClick !== null) {
      this.header.header.removeEventListener("click", this.headerClick);
    }
    this.headerClick = null;
    this.header = null;
    if (this.root !== null) this.root.replaceChildren();
    this.root = this.countEl = this.clearBtn = null;
    this.bounceBtn = null;
    this.historyBtn = null;
    this.historyPanel = this.statusEl = null;
    this.envLabelEl = this.clockEl = null;
    this.historyOpen = false;
    this.mounted = false;
  }

  // -------------------------------------------------------------------------
  // H2 — env-label + live clock (sys_time_update WS frame → header)
  // -------------------------------------------------------------------------

  private onSysTimeUpdate(payload: SysTimeUpdatePayload): void {
    /* c8 ignore next */ // defensive: fires only between mount and unmount, when the els are set.
    if (this.envLabelEl === null || this.clockEl === null) return;
    // Legacy: `[${env_label}]: ` prefix + the server-formatted date string.
    this.envLabelEl.textContent = payload.env_label ? `[${payload.env_label}]: ` : "";
    this.clockEl.textContent    = payload.date ?? "";
  }

  // -------------------------------------------------------------------------
  // Count + clear-all enablement
  // -------------------------------------------------------------------------

  private refresh(): void {
    /* c8 ignore next */ // defensive: refresh only fires between mount and unmount, when countEl/clearBtn are set.
    if (this.countEl === null || this.clearBtn === null) return;
    // Lane 0a — the section-header count = the active-list TOTAL. RULED
    // 2026-07-02 (Tiberius, from legacy ground truth: notifications.js:14417-14428
    // updateTotalNotificationsCount() sums group.totalCount into
    // #notifications-count → TOTAL). 07 §3.A F-Clay-A4's "UNREAD" was a
    // transcription error (corrected in-file with a ⚠️ marker); this matches
    // legacy AND the pre-cascade F-Sam-BC3 intent (list().length).
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

  // -------------------------------------------------------------------------
  // Managed dev-server bounce (row 1b4211ac R2)
  // -------------------------------------------------------------------------

  private setBounceStatus(text: string): void {
    if (this.statusEl !== null) this.statusEl.textContent = text;
  }

  private async onBounce(): Promise<void> {
    /**
     * Trigger the managed bounce and reflect the ~20s outage honestly.
     *
     * The endpoint does not restart inline — it hands off to the host-side watcher
     * (warn → restart → the server self-emits the all-clear). A 202 means the bounce
     * was accepted; a 409 (already bouncing) or 503 (watcher down) is surfaced as a
     * plain reason instead of a false "in progress". We disable the button until
     * /health confirms the server is actually back, so it never looks dead while
     * working or alive while down.
     */
    if (this.bounceBtn === null) return;
    if (!this.confirmFn("Bounce the dev server (:7999)? The fleet is warned first, then it restarts (~20s). In-flight notifications will drop.")) return;

    this.bounceBtn.disabled = true;
    this.setBounceStatus("Bouncing… (~20s)");

    try {
      await this.api.bounceDevServer();
    } catch (err) {
      const status = (err as { status?: number }).status;
      const reason =
        status === 409 ? "A dev-server bounce is already running — wait for the all-clear."
      : status === 503 ? "Bounce watcher is not running on the host."
      : (err as Error).message;
      this.setBounceStatus(`Bounce not started: ${reason}`);
      this.bounceBtn.disabled = false;
      return;
    }

    // 202 — the bounce is running. Wait for the server to come back before we
    // re-enable, so a re-press can't race the restart.
    const back = await this.waitForServerBack();
    this.setBounceStatus(back ? "Server back up ✓" : "Bounce triggered — not yet confirmed healthy; check logs.");
    if (this.bounceBtn !== null) this.bounceBtn.disabled = false;
  }

  private async waitForServerBack(): Promise<boolean> {
    /**
     * Resolve true once /health returns ok after the bounce, allowing for the
     * server to go DOWN and return in between. We accept an ok only after either a
     * down blip was observed (the restart we asked for) or a grace has elapsed —
     * a fast restart whose down-edge we miss between polls must still re-enable.
     * Returns false on timeout.
     */
    const start = Date.now();
    let sawDown = false;
    while (Date.now() - start < this.bounceWaitMs) {
      await new Promise((r) => setTimeout(r, this.bouncePollMs));
      try {
        const r = await this.fetchFn("/health", { cache: "no-store" });
        if (r.ok) {
          if (sawDown || (Date.now() - start) > this.bounceGraceMs) return true;
        } else {
          sawDown = true;
        }
      } catch {
        sawDown = true;   // connection refused during the restart window
      }
    }
    return false;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the factory declaration line.
export function createNotificationsHeaderRenderer(
  opts: NotificationsHeaderRendererOptions,
): NotificationsHeaderRenderer {
  return new NotificationsHeaderRendererImpl(opts);
}
