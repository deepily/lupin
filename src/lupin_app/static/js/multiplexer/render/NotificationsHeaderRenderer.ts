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
// Row 98305d96 (Rick 2026-09-10 ~15:57, "port legacy user filter") reverses the
// 67fc18f0/a767e1ae deferral: the filter badge and the Mine / Not Mine / All Users
// switch are built here, admin-only. The store owns the mode; coldHistoryHydration
// reloads for it.
//
// Rick's 2026-09-10 ruling 3 (P0 5ebd2aff, "legacy title, slider inline"): the bar
// reads "Claude Code Notifications: N" and carries the TTS preview slider INSIDE
// it, as legacy notifications.html:481-513 does. This renderer creates the empty
// slot (#tts-preview-slider-mount); TtsPreviewSliderRenderer mounts into it.

import type { EventBus } from "../shared/EventBus";
import type { Notification, NotificationFilterMode, StoreNotificationsChangedPayload } from "../shared/types";
import type { HistoryWindow } from "../stores/historyWindow";
import { createHistoryWindowDropdown, type HistoryWindowDropdownHandle } from "./historyWindowDropdown";
import {
  headerClickShouldCollapse,
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
  // Rick's ruling 1 (2026-09-10) — the history-window picker reads and sets the window.
  historyWindow(): HistoryWindow;
  setHistoryWindow(w: HistoryWindow): void;
  // Row 98305d96 — the admin Mine switch reads and sets the mode.
  filterMode(): NotificationFilterMode;
  setFilterMode(mode: NotificationFilterMode): void;
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
  // Row 98305d96 — whether to show the admin-only filter badge and switch. Production
  // passes AuthManager.isCurrentUserAdmin; omitted means hidden, as for every non-admin.
  isAdmin?  : () => boolean;
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

// Row 98305d96 — legacy's labels, verbatim (notifications.js setFilterMode modeConfig).
const FILTER_MODES: ReadonlyArray<{ mode: NotificationFilterMode; icon: string; label: string }> = [
  { mode: "own",    icon: "👤", label: "Mine" },
  { mode: "others", icon: "🚫", label: "Not Mine" },
  { mode: "all",    icon: "👥", label: "All Users" },
];

class NotificationsHeaderRendererImpl implements NotificationsHeaderRenderer {
  private readonly bus       : EventBus;
  private readonly store     : NotificationsHeaderStoreLike;
  private readonly api       : NotificationDeleteApiLike;
  private readonly confirmFn : (message: string) => boolean;
  private readonly isAdmin   : () => boolean;
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
  private ttsSlot      : HTMLElement | null        = null;
  private filterBadgeEl  : HTMLElement | null      = null;
  private filterSwitchEl : HTMLElement | null      = null;
  private readonly filterButtons : Map<NotificationFilterMode, HTMLButtonElement> = new Map();
  private historyWindowDropdown : HistoryWindowDropdownHandle | null = null;
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
    this.isAdmin   = opts.isAdmin ?? ((): boolean => false);
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

    // Ruling 3 — the TTS preview slider's slot, first among the actions (legacy
    // order: TTS · history window · Clear All · toggle). Nothing re-renders it:
    // replaceChildren runs only in mount() and unmount(), never in refresh(), so a
    // slider mounted here survives every store change. It swallows clicks so a
    // drag never collapses the section (legacy `onclick="event.stopPropagation()"`).
    this.ttsSlot = document.createElement("div");
    this.ttsSlot.className = "notifications-tts-slot";
    this.ttsSlot.id = "tts-preview-slider-mount";
    this.ttsSlot.setAttribute("data-testid", "multiplexer-tts-preview-slider-mount");
    this.ttsSlot.addEventListener("click", (e) => e.stopPropagation());

    // Rick's ruling 1 (2026-09-10) — legacy's history-window picker, right after
    // the TTS control as in legacy notifications.html:514. The store owns the
    // value and the reload; the picker only reads and sets it.
    this.historyWindowDropdown = createHistoryWindowDropdown(this.store, root.ownerDocument);

    // Row 98305d96 — legacy's admin-only filter: a badge naming the mode (legacy puts it in
    // the section header) and the Mine / Not Mine / All Users switch. Hidden for everyone
    // else, as legacy hides it (initializeFilterUI). Mount only READS the mode: setting it
    // here would reload the history on every page load, which is exactly legacy's
    // doubled-count bug (row b670b76c).
    this.filterBadgeEl = document.createElement("span");
    this.filterBadgeEl.className = "filter-mode-badge";
    this.filterBadgeEl.id = "notifications-filter-badge";
    this.filterBadgeEl.setAttribute("data-testid", "multiplexer-notifications-filter-badge");
    this.filterSwitchEl = document.createElement("div");
    this.filterSwitchEl.className = "notifications-filter-switch";
    this.filterSwitchEl.setAttribute("role", "group");
    this.filterSwitchEl.setAttribute("aria-label", "Show notifications from whose jobs");
    this.filterSwitchEl.setAttribute("data-testid", "multiplexer-notifications-filter-switch");
    for (const { mode, icon, label } of FILTER_MODES) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "notifications-filter-btn";
      btn.setAttribute("data-mode", mode);
      btn.setAttribute("data-testid", `multiplexer-notifications-filter-${mode}-btn`);
      btn.textContent = `${icon} ${label}`;
      btn.addEventListener("click", () => this.onFilterClick(mode));
      this.filterButtons.set(mode, btn);
      this.filterSwitchEl.appendChild(btn);
    }
    const admin = this.isAdmin();
    this.filterBadgeEl.hidden  = !admin;
    this.filterSwitchEl.hidden = !admin;

    // History dropdown — toggle button + (initially hidden) panel.
    this.historyBtn = document.createElement("button");
    this.historyBtn.type = "button";
    this.historyBtn.className = "notifications-history-toggle";
    this.historyBtn.id = "history-dropdown-toggle";
    this.historyBtn.setAttribute("data-testid", "multiplexer-notifications-history-toggle");
    // Rick's ruling (2026-09-10 ~15:57, row 98305d96): keep this multiplexer-only button, which
    // lists EXPIRED notifications, and rename it so it no longer reads as a second history control
    // beside the history-window picker.
    this.historyBtn.textContent = "Expired ▾";
    this.historyBtn.addEventListener("click", () => this.toggleHistory());

    // Clear-all.
    this.clearBtn = document.createElement("button");
    this.clearBtn.type = "button";
    this.clearBtn.className = "notifications-clear-all";
    this.clearBtn.id = "clear-all-notifications";
    this.clearBtn.setAttribute("data-testid", "multiplexer-notifications-clear-all");
    // H6 (2026-09-10) — legacy label, verbatim.
    this.clearBtn.textContent = "🗑️ Clear All";
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
    // h3 around the title (legacy parity). Ruling 3: the title is legacy's
    // "Claude Code Notifications:" with no icon, so the count reads as its value.
    const header = renderSectionHeader({
      icon    : "",
      title   : "Claude Code Notifications:",
      testid  : "multiplexer-notifications-header",
      actions : [ this.ttsSlot, this.historyWindowDropdown.element, this.filterSwitchEl, this.historyBtn, this.clearBtn, this.bounceBtn, this.statusEl ],
    });
    this.header  = header;
    this.countEl = header.countEl;
    this.countEl.id = "notifications-count";
    this.countEl.setAttribute("data-testid", "multiplexer-notifications-count");

    const h3 = header.header.querySelector("h3") as HTMLElement;
    // env-label BEFORE the title; clock AFTER the count (ruling 3 — "Claude Code
    // Notifications: N" stays one phrase; env label + clock stay in the bar).
    h3.insertBefore(this.envLabelEl, h3.firstChild);
    h3.appendChild(this.clockEl);
    // Row 98305d96 — the filter badge sits where legacy puts it (notifications.html:481-483): the
    // h3's next sibling, OUTSIDE both the h3 (ruling 3 fixed it as env-label · title · count ·
    // clock) and the actions (ruling 3 keeps the TTS slot first, ruling 1 the picker second).
    header.header.insertBefore(this.filterBadgeEl, header.actionsEl);

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
      // The SHARED predicate — see sectionHeader.ts. This was a second
      // hand-written copy of the same rule, and when the chevron became a real
      // <button> (Rick's divergence #5) the copy swallowed its clicks while the
      // original did not: the bar still collapsed and the CHEVRON stopped
      // working. A rule living in two places is a rule that gets half-changed.
      if ( !headerClickShouldCollapse( e.target as Element | null, header.toggleEl ) ) return;
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
    this.ttsSlot = null;
    this.filterBadgeEl = this.filterSwitchEl = null;
    this.filterButtons.clear();
    /* c8 ignore next */ // defensive: mount() always sets the picker, and unmount() has already returned when not mounted.
    if (this.historyWindowDropdown !== null) this.historyWindowDropdown.dispose();
    this.historyWindowDropdown = null;
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
    if (this.countEl === null || this.clearBtn === null || this.historyWindowDropdown === null) return;
    // Ruling 1 — the picker follows the store's window (a change repaints its label).
    this.historyWindowDropdown.sync();
    this.syncFilter();
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
  // Row 98305d96 — the admin Mine switch
  // -------------------------------------------------------------------------

  private syncFilter(): void {
    /* c8 ignore next */ // defensive: refresh only runs between mount and unmount, when the badge is set.
    if (this.filterBadgeEl === null) return;
    const current = this.store.filterMode();
    const config  = FILTER_MODES.find(m => m.mode === current) as (typeof FILTER_MODES)[number];
    this.filterBadgeEl.textContent = `${config.icon} ${config.label}`;
    this.filterBadgeEl.setAttribute("data-mode", config.mode);
    for (const [mode, btn] of this.filterButtons) {
      btn.classList.toggle("active", mode === current);
      btn.setAttribute("aria-pressed", String(mode === current));
    }
  }

  private onFilterClick(mode: NotificationFilterMode): void {
    if (mode === this.store.filterMode()) return;   // already showing it: nothing to reload
    this.store.setFilterMode(mode);
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
