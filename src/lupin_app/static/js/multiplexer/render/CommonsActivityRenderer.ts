/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane D (WP3 + WP11, 2026-06-10) — CommonsActivityRenderer.
//
// Renders the commons "Recent Activity" panel. Subscribes to
// `store_commons_changed` (CommonsStore) and repaints the filtered entry list;
// wires the time-window selector, the 3-axis filter dropdowns (Direction /
// Kind / Persona), the manual refresh button, and the panel-collapse header.
// Mirrors the Phase 5/6 renderer lifecycle (mount / unmount /
// forceRenderForTesting + unsubscribers array + delegated click handler).
//
// WP11 / F4 — Show-more toggle: each entry's body is line-clamped to 2 lines by
// CSS; a per-entry Show-more toggle is revealed ONLY when the rendered content
// actually overflows. Because entries may be rendered while the panel body is
// collapsed (`display:none` → zero layout), a single rAF measure is unreliable:
// we measure on the next frame and, if the content still has no layout, watch
// it with a ResizeObserver and re-measure once it gains a non-zero height, then
// disconnect (verbatim port of `notifications.js:10816-10828`).
//
// Per the multiplexer no-globals / no-inline-onclick rule, toggle + header
// clicks are handled via delegation on the mount root, NOT inline handlers.

import type { EventBus } from "../shared/EventBus";
import type {
  CommonsActivityDirection,
  CommonsActivityEntry,
  CommonsActivityKind,
  StoreCommonsChangedPayload,
  LupinEvent,
} from "../shared/types";
import type { CommonsStore, CommonsHistoryApiClient } from "../stores/CommonsStore";
import { renderCommonsActivityEntry } from "./templates/commonsActivityEntry";

// ---------------------------------------------------------------------------
// ResizeObserver structural type (avoids a hard lib dependency; the global is
// read at measure-time so tests can stub `globalThis.ResizeObserver`).
// ---------------------------------------------------------------------------

interface ResizeObserverLike {
  observe(target: Element): void;
  disconnect(): void;
}
type ResizeObserverCtorLike = new (cb: () => void) => ResizeObserverLike;

// ---------------------------------------------------------------------------
// Public interfaces
// ---------------------------------------------------------------------------

export interface CommonsActivityApiClient extends CommonsHistoryApiClient {}

export interface CommonsActivityRendererStores {
  commons : CommonsStore;
}

export interface CommonsActivityRendererOptions {
  eventBus     : EventBus;
  stores       : CommonsActivityRendererStores;
  api          : CommonsActivityApiClient;
  appTimezone? : string;
  // Test injection — production defers the first overflow measure to the next
  // animation frame; tests pass a synchronous shim for determinism.
  rafFn?       : (cb: () => void) => void;
}

export interface CommonsActivityRenderer {
  /** Attach to a root node. Throws on a missing entries container or a 2nd mount. */
  mount(root: HTMLElement): void;
  /** Detach: unsubscribe, drop handlers, disconnect observers, clear entries. */
  unmount(): void;
  /** Test helper — synchronously trigger a full re-render. */
  forceRenderForTesting(): void;
}

// Pool snapshot shape (`GET /api/cosa-voice/voice-persona/pool`).
interface PersonaPoolEntry { name?: string; icon?: string; display_name?: string }
interface PersonaActiveSession { persona_name?: string }
interface PersonaPoolResponse {
  pool             ?: ReadonlyArray<PersonaPoolEntry>;
  active_sessions  ?: ReadonlyArray<PersonaActiveSession>;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

class CommonsActivityRendererImpl implements CommonsActivityRenderer {
  private readonly bus         : EventBus;
  private readonly store       : CommonsStore;
  private readonly api         : CommonsActivityApiClient;
  private readonly appTimezone : string | undefined;
  private readonly rafFn       : (cb: () => void) => void;

  private mounted        = false;
  private root           : HTMLElement | null = null;
  private bodyEl         : HTMLElement | null = null;
  private entriesEl      : HTMLElement | null = null;
  private emptyEl        : HTMLElement | null = null;
  private windowSel      : HTMLSelectElement | null = null;
  private directionSel   : HTMLSelectElement | null = null;
  private kindSel        : HTMLSelectElement | null = null;
  private personaSel     : HTMLSelectElement | null = null;
  private refreshBtn     : HTMLElement | null = null;
  private headerEl       : HTMLElement | null = null;

  private clickHandler   : ((e: Event) => void) | null = null;
  private changeHandler  : ((e: Event) => void) | null = null;
  private readonly unsubscribers : Array<() => void> = [];
  // Live ResizeObservers awaiting a layout pass; disconnected on unmount.
  private readonly observers : Set<ResizeObserverLike> = new Set();

  constructor(opts: CommonsActivityRendererOptions) {
    // Fail fast at construction if the store is missing (Pass 2 F4 pattern).
    if (!opts.stores || !opts.stores.commons) {
      throw new Error("CommonsActivityRenderer requires stores.commons to be initialized");
    }
    this.bus         = opts.eventBus;
    this.store       = opts.stores.commons;
    this.api         = opts.api;
    this.appTimezone = opts.appTimezone;
    /* c8 ignore next */ // production-default fallback: requestAnimationFrame is the runtime frame scheduler; tests inject a synchronous shim.
    this.rafFn       = opts.rafFn ?? ((cb) => requestAnimationFrame(cb));
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  mount(root: HTMLElement): void {
    if (this.mounted) {
      throw new Error("CommonsActivityRenderer already mounted");
    }
    const entriesEl = root.querySelector("#commons-activity-entries") as HTMLElement | null;
    if (entriesEl === null) {
      throw new Error("CommonsActivityRenderer.mount: #commons-activity-entries not found inside root");
    }
    this.root         = root;
    this.entriesEl    = entriesEl;
    this.bodyEl       = root.querySelector("#commons-activity-body") as HTMLElement | null;
    this.emptyEl      = root.querySelector("#commons-activity-empty") as HTMLElement | null;
    this.windowSel    = root.querySelector("#commons-activity-window") as HTMLSelectElement | null;
    this.directionSel = root.querySelector("#commons-activity-filter-direction") as HTMLSelectElement | null;
    this.kindSel      = root.querySelector("#commons-activity-filter-kind") as HTMLSelectElement | null;
    this.personaSel   = root.querySelector("#commons-activity-filter-persona") as HTMLSelectElement | null;
    this.refreshBtn   = root.querySelector("#commons-activity-refresh") as HTMLElement | null;
    this.headerEl     = root.querySelector("#commons-activity-header") as HTMLElement | null;
    this.mounted      = true;

    // Restore control values from persisted store state.
    this.syncControlsFromStore();

    this.attachDelegation();
    this.subscribe();
    this.renderAll();

    // Eager hydration — float the promise so mount() returns immediately
    // (JobsPaneRenderer Q-A7 pattern). A rejection is logged, not thrown.
    this.store.hydrate(this.api).catch((err: unknown) => {
      console.warn("CommonsActivityRenderer: hydrate rejected:", err);
    });
    this.populatePersonaDropdown();
  }

  unmount(): void {
    if (!this.mounted) return;   // idempotent

    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    if (this.clickHandler !== null && this.root !== null) {
      this.root.removeEventListener("click", this.clickHandler);
    }
    if (this.changeHandler !== null && this.root !== null) {
      this.root.removeEventListener("change", this.changeHandler);
    }
    this.clickHandler  = null;
    this.changeHandler = null;

    for (const ro of this.observers) ro.disconnect();
    this.observers.clear();

    if (this.entriesEl !== null) this.entriesEl.replaceChildren();
    this.root = this.bodyEl = this.entriesEl = this.emptyEl = null;
    this.windowSel = this.directionSel = this.kindSel = this.personaSel = null;
    this.refreshBtn = this.headerEl = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    this.renderAll();
  }

  // -------------------------------------------------------------------------
  // Control sync
  // -------------------------------------------------------------------------

  private syncControlsFromStore(): void {
    const f = this.store.getFilter();
    if (this.windowSel    !== null) this.windowSel.value    = this.store.getWindow();
    if (this.directionSel !== null) this.directionSel.value = f.direction ?? "";
    if (this.kindSel      !== null) this.kindSel.value      = f.kind;
    if (this.personaSel   !== null) this.personaSel.value   = f.persona ?? "";
  }

  // -------------------------------------------------------------------------
  // Subscriptions + delegation
  // -------------------------------------------------------------------------

  private subscribe(): void {
    this.unsubscribers.push(
      this.bus.on<StoreCommonsChangedPayload>("store_commons_changed", (e) => this.onCommonsChanged(e)),
    );
    // WP7 (Tiberius-arbitrated 2026-06-10): the CC-session strip is the canonical
    // recipient-change signal. When Lane B's SessionStripStore adds/removes an
    // icon it emits `store_session_strip_changed`; we re-run the persona filter
    // dropdown so a freshly-spawned / just-reaped peer appears/disappears in the
    // filter without a reload. No-op until Lane B's emitter merges (the event
    // simply never fires until then).
    this.unsubscribers.push(
      this.bus.on("store_session_strip_changed", () => this.populatePersonaDropdown()),
    );
  }

  private attachDelegation(): void {
    /* c8 ignore next */ // defensive: root is set in mount() before this runs.
    if (this.root === null) return;

    this.clickHandler = (e: Event): void => {
      const target = e.target as Element | null;
      /* c8 ignore next */ // defensive: browser click events always carry a target.
      if (target === null) return;

      // Per-entry Show-more toggle.
      const toggle = target.closest(".commons-activity-entry-body-toggle") as HTMLElement | null;
      if (toggle !== null) {
        this.onToggleClick(toggle);
        return;
      }
      // Manual refresh.
      if (this.refreshBtn !== null && target.closest("#commons-activity-refresh") !== null) {
        this.onRefresh();
        return;
      }
      // Panel-collapse header (ignore clicks that originated on a control inside it).
      if (this.headerEl !== null && target.closest("#commons-activity-header") !== null
          && target.closest(".commons-activity-controls") === null) {
        this.onHeaderToggle();
      }
    };
    this.root.addEventListener("click", this.clickHandler);

    this.changeHandler = (e: Event): void => {
      const target = e.target as HTMLSelectElement | null;
      /* c8 ignore next */ // defensive: change events on a <select> always carry a target.
      if (target === null) return;
      if (target.id === "commons-activity-window") {
        this.store.hydrate(this.api, target.value).catch((err: unknown) => {
          console.warn("CommonsActivityRenderer: window-change hydrate rejected:", err);
        });
      } else if (target.id === "commons-activity-filter-direction") {
        this.store.setDirection((target.value || null) as CommonsActivityDirection);
      } else if (target.id === "commons-activity-filter-kind") {
        this.store.setKind((target.value || "all") as CommonsActivityKind);
      } else if (target.id === "commons-activity-filter-persona") {
        this.store.setPersona(target.value || null);
      }
    };
    this.root.addEventListener("change", this.changeHandler);
  }

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  private onCommonsChanged(e: LupinEvent<StoreCommonsChangedPayload>): void {
    const { changeKind } = e.payload;
    if (changeKind === "prepended") {
      // Live single-row insert — only touch the DOM when the entry passes the
      // active filter (it's already cached either way for a later re-render).
      if (e.payload.matchesFilter === true) {
        const entry = this.store.entries()[0];
        /* c8 ignore next */ // defensive: a "prepended" event always follows an unshift, so entries()[0] is present.
        if (entry !== undefined) this.prependRow(entry);
      } else {
        this.updateEmptyState();
      }
      return;
    }
    // "hydrated" + "filter-changed" → full re-render from the (filtered) cache.
    this.renderAll();
  }

  private onToggleClick(toggle: HTMLElement): void {
    const row = toggle.closest(".commons-activity-entry");
    /* c8 ignore next */ // defensive: the toggle only ever lives inside a row per the template invariant.
    if (row === null) return;
    const content = row.querySelector(".commons-activity-entry-body-content");
    /* c8 ignore next */ // defensive: every row carries a body-content per the template invariant.
    if (content === null) return;
    const expanded = content.classList.toggle("expanded");
    toggle.textContent = expanded ? "Show less ▴" : "Show more ▾";
  }

  private onRefresh(): void {
    this.store.hydrate(this.api, this.store.getWindow()).catch((err: unknown) => {
      console.warn("CommonsActivityRenderer: refresh hydrate rejected:", err);
    });
    this.populatePersonaDropdown();
  }

  private onHeaderToggle(): void {
    /* c8 ignore next */ // defensive: header handler only fires when bodyEl exists alongside headerEl in the scaffold.
    if (this.bodyEl === null) return;
    this.bodyEl.classList.toggle("collapsed");
  }

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  private renderAll(): void {
    /* c8 ignore next */ // defensive: entriesEl is set on mount; renderAll only runs while mounted.
    if (this.entriesEl === null) return;

    // Pane-level disabled hiding (server kill-switch). The mount root IS the
    // commons pane section, so hiding it hides the whole panel.
    /* c8 ignore next */ // defensive: root is set on mount; renderAll only runs while mounted.
    if (this.root !== null) this.root.hidden = this.store.isDisabled();

    const entries = this.store.visibleEntries();
    const rows = entries.map(entry => renderCommonsActivityEntry(entry, this.threadOpts()));
    this.entriesEl.replaceChildren(...rows);
    for (const row of rows) this.measureRowToggle(row);

    this.setEmptyHidden(entries.length > 0);
    this.updateEmptyState();
  }

  private prependRow(entry: CommonsActivityEntry): void {
    /* c8 ignore next */ // defensive: prependRow only runs while mounted (entriesEl set).
    if (this.entriesEl === null) return;
    const row = renderCommonsActivityEntry(entry, this.threadOpts());
    if (this.entriesEl.firstChild !== null) {
      this.entriesEl.insertBefore(row, this.entriesEl.firstChild);
    } else {
      this.entriesEl.appendChild(row);
    }
    this.measureRowToggle(row);
    this.setEmptyHidden(true);
  }

  private threadOpts(): { appTimezone?: string } {
    return this.appTimezone !== undefined ? { appTimezone: this.appTimezone } : {};
  }

  private setEmptyHidden(hidden: boolean): void {
    if (this.emptyEl !== null) this.emptyEl.hidden = hidden;
  }

  // Swap empty-state copy between the time-window default and the filter-active
  // variant (port of `notifications.js:_updateEmptyStateCopy`).
  private updateEmptyState(): void {
    if (this.emptyEl === null) return;
    this.emptyEl.textContent = this.store.isFilterActive()
      ? "No activity matches the current filter."
      : "No activity in window.";
  }

  // -------------------------------------------------------------------------
  // WP11 / F4 — Show-more overflow measurement
  // -------------------------------------------------------------------------

  private measureRowToggle(row: HTMLElement): void {
    const content = row.querySelector(".commons-activity-entry-body-content") as HTMLElement | null;
    const toggle  = row.querySelector(".commons-activity-entry-body-toggle") as HTMLElement | null;
    /* c8 ignore next */ // defensive: both are guaranteed by the entry template.
    if (content === null || toggle === null) return;

    const reveal = (): boolean => {
      if (content.clientHeight === 0) return false;   // not laid out — cannot measure
      if (content.scrollHeight > content.clientHeight + 1) toggle.hidden = false;
      return true;
    };

    this.rafFn(() => {
      if (reveal()) return;
      const ROCtor = (globalThis as unknown as { ResizeObserver?: ResizeObserverCtorLike }).ResizeObserver;
      if (ROCtor === undefined) return;
      const ro: ResizeObserverLike = new ROCtor(() => {
        if (reveal()) {
          ro.disconnect();
          this.observers.delete(ro);
        }
      });
      this.observers.add(ro);
      ro.observe(content);
    });
  }

  // -------------------------------------------------------------------------
  // Persona filter dropdown population (sticky-when-valid)
  // -------------------------------------------------------------------------

  private populatePersonaDropdown(): void {
    const dropdown = this.personaSel;
    if (dropdown === null) return;

    const previous = dropdown.value || (this.store.getFilter().persona ?? "");

    this.api.get<PersonaPoolResponse>("/api/cosa-voice/voice-persona/pool")
      .then((body) => {
        /* c8 ignore next */ // defensive: renderer may unmount mid-fetch; null-guard the late resolve.
        if (this.personaSel === null) return;
        const pool     = body.pool ?? [];
        const sessions = body.active_sessions ?? [];

        const poolByName = new Map<string, PersonaPoolEntry>();
        for (const p of pool) poolByName.set((p.name ?? "").toLowerCase(), p);

        dropdown.replaceChildren();
        const anyOpt = document.createElement("option");
        anyOpt.value       = "";
        anyOpt.textContent = "Any persona";
        dropdown.appendChild(anyOpt);

        const valid = new Set<string>();
        for (const s of sessions) {
          const name  = s.persona_name ?? "";
          const lower = name.toLowerCase();
          if (!lower) continue;
          valid.add(lower);
          // Past the !lower guard, `name` is a non-empty string.
          const meta    = poolByName.get(lower) ?? {};
          const icon    = meta.icon ?? "";
          const display = meta.display_name ?? name;
          const opt = document.createElement("option");
          opt.value       = lower;
          opt.textContent = icon ? `${icon} ${display}` : display;
          dropdown.appendChild(opt);
        }

        // Sticky-when-valid: restore the previous selection if still present;
        // otherwise clear it (write-through to the store filter).
        if (previous && valid.has(previous)) {
          dropdown.value = previous;
        } else if (previous) {
          this.store.setPersona(null);
        }
      })
      .catch((err: unknown) => {
        console.warn("CommonsActivityRenderer: persona-pool fetch rejected:", err);
      });
  }
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createCommonsActivityRenderer(opts: CommonsActivityRendererOptions): CommonsActivityRenderer {
  return new CommonsActivityRendererImpl(opts);
}
