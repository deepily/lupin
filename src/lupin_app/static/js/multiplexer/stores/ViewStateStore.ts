/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer section-toolbar + accordion-collapse parity (2026-06-23, Rachel
// 🕊️ / Mr. Radio lane).
//
// Pure logical state for the user's view preferences — NO DOM. Two persisted
// maps:
//   - sectionVisibility   : sectionId → visible?   (default: visible)
//   - accordionCollapsed   : accordionId → collapsed? (default: expanded)
//
// Carbon-copy of the legacy notifications client's section-visibility +
// accordion-collapse behavior (notifications.js: saveSectionVisibility /
// toggleSectionVisibility :9967-10073, toggleDateAccordion :13671,
// toggleSenderCard :14074) re-expressed in the multiplexer store/renderer
// split. Persistence flows through StorageService (the DC2 "no raw
// localStorage" invariant), one schema-versioned envelope per map.
//
// EMISSION POLICY (deliberate): per-section + per-accordion setters persist
// SILENTLY — the owning renderer (SectionToolbarRenderer for sections,
// NotificationsListRenderer for accordions) applies the DOM directly, so a
// store emit would be redundant. The ONLY emit is the cross-renderer bulk
// intent `requestBulkAccordionCollapse(collapsed)` → `store_view_state_changed`
// (collapse-all / expand-all), which NotificationsListRenderer consumes to flip
// every accordion at once. This avoids an N-emit storm on bulk.

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type { StoreViewStateChangedPayload } from "../shared/types";

// Persistence keys (StorageService prepends the "lupin:" prefix) + schema
// versions. One envelope per map.
const SECTION_VISIBILITY_KEY    = "view_state_section_visibility";
const SECTION_VISIBILITY_SCHEMA = 1;
const ACCORDION_COLLAPSED_KEY    = "view_state_accordion_collapsed";
const ACCORDION_COLLAPSED_SCHEMA = 1;

// A boolean map (id → flag). JSON-round-trippable; the store coerces any
// non-boolean value defensively at hydrate time.
type FlagMap = Record<string, boolean>;

interface SectionVisibilityEnvelope { sections: FlagMap }
interface AccordionCollapsedEnvelope { accordions: FlagMap }

export interface ViewStateStore {
  /** True unless the section was explicitly hidden. Default: visible. */
  isSectionVisible(sectionId: string): boolean;
  /** Set a section's visibility + persist. Silent (no emit). */
  setSectionVisible(sectionId: string, visible: boolean): void;
  /** The sectionIds explicitly recorded as hidden (visible === false). */
  getHiddenSectionIds(): string[];
  /**
   * True when the section carries an EXPLICIT persisted preference (visible OR
   * hidden). Lets the toolbar distinguish "no preference → use the cold-start
   * default (HTML `hidden`)" from "user explicitly showed/hid it" — the
   * precedence rule (F-Clay-A3): a persisted choice overrides the cold default.
   */
  hasSectionPreference(sectionId: string): boolean;

  /** True only when the accordion was explicitly collapsed. Default: expanded. */
  isAccordionCollapsed(accordionId: string): boolean;
  /** Set an accordion's collapsed state + persist. Silent (no emit). */
  setAccordionCollapsed(accordionId: string, collapsed: boolean): void;

  /**
   * Broadcast a bulk collapse/expand intent to every accordion. Emits
   * `store_view_state_changed` (the ONE cross-renderer signal);
   * NotificationsListRenderer subscribes, iterates its accordion DOM, and
   * persists + applies each via setAccordionCollapsed. The store itself holds
   * no "all" flag — bulk is a one-shot over the currently-rendered accordions
   * (parity with legacy collapse-all/expand-all, which iterate live DOM).
   */
  requestBulkAccordionCollapse(collapsed: boolean): void;
}

export interface ViewStateStoreOptions {
  bus     : EventBus;
  storage : StorageService;
}

class ViewStateStoreImpl implements ViewStateStore {
  private readonly bus     : EventBus;
  private readonly storage : StorageService;

  private sectionVisibility : FlagMap = {};
  private accordionCollapsed: FlagMap = {};

  constructor( opts: ViewStateStoreOptions ) {
    this.bus     = opts.bus;
    this.storage = opts.storage;
    this.hydrate();
  }

  // -------------------------------------------------------------------------
  // Hydration — replay persisted maps. A corrupt / absent envelope falls back
  // to empty (all sections visible, all accordions expanded). StorageService
  // already emitted storage_corrupt for the corrupt case.
  // -------------------------------------------------------------------------

  private hydrate(): void {
    const secEnv = this.storage.getJSON<SectionVisibilityEnvelope>(
      SECTION_VISIBILITY_KEY, SECTION_VISIBILITY_SCHEMA,
    );
    if (secEnv !== null) {
      this.sectionVisibility = coerceFlagMap(secEnv.sections);
    }
    const accEnv = this.storage.getJSON<AccordionCollapsedEnvelope>(
      ACCORDION_COLLAPSED_KEY, ACCORDION_COLLAPSED_SCHEMA,
    );
    if (accEnv !== null) {
      this.accordionCollapsed = coerceFlagMap(accEnv.accordions);
    }
  }

  // -------------------------------------------------------------------------
  // Section visibility
  // -------------------------------------------------------------------------

  isSectionVisible(sectionId: string): boolean {
    // Default visible: only an explicit `false` hides a section.
    return this.sectionVisibility[sectionId] !== false;
  }

  setSectionVisible(sectionId: string, visible: boolean): void {
    this.sectionVisibility[sectionId] = visible;
    this.storage.setJSON<SectionVisibilityEnvelope>(
      SECTION_VISIBILITY_KEY, { sections: this.sectionVisibility }, SECTION_VISIBILITY_SCHEMA,
    );
  }

  getHiddenSectionIds(): string[] {
    return Object.keys(this.sectionVisibility).filter(id => this.sectionVisibility[id] === false);
  }

  hasSectionPreference(sectionId: string): boolean {
    return Object.prototype.hasOwnProperty.call(this.sectionVisibility, sectionId);
  }

  // -------------------------------------------------------------------------
  // Accordion collapse
  // -------------------------------------------------------------------------

  isAccordionCollapsed(accordionId: string): boolean {
    // Default expanded: only an explicit `true` collapses an accordion.
    return this.accordionCollapsed[accordionId] === true;
  }

  setAccordionCollapsed(accordionId: string, collapsed: boolean): void {
    this.accordionCollapsed[accordionId] = collapsed;
    this.storage.setJSON<AccordionCollapsedEnvelope>(
      ACCORDION_COLLAPSED_KEY, { accordions: this.accordionCollapsed }, ACCORDION_COLLAPSED_SCHEMA,
    );
  }

  // -------------------------------------------------------------------------
  // Bulk intent (the only emit)
  // -------------------------------------------------------------------------

  requestBulkAccordionCollapse(collapsed: boolean): void {
    this.bus.emit<StoreViewStateChangedPayload>({
      type    : "store_view_state_changed",
      payload : { changeKind: collapsed ? "collapse-all" : "expand-all" },
      source  : "ViewStateStore",
      ts      : Date.now(),
    });
  }
}

// Defensive coercion: keep only genuine boolean entries from a persisted map.
// A tampered / partially-corrupt envelope (non-object values) degrades to the
// safe default rather than poisoning the in-memory map.
function coerceFlagMap(raw: unknown): FlagMap {
  const out: FlagMap = {};
  // A tampered envelope can carry a non-object / null `sections`/`accordions`
  // value (getJSON returns whatever the payload held) — degrade to empty.
  if (typeof raw !== "object" || raw === null) return out;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof v === "boolean") out[k] = v;
  }
  return out;
}

/**
 * Construct a ViewStateStore.
 *
 * Requires:
 *   - opts.bus is the production EventBus (or a test instance)
 *   - opts.storage is a configured StorageService
 *
 * Ensures:
 *   - persisted section-visibility + accordion-collapse maps are replayed at
 *     construction; the store is immediately usable on return
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createViewStateStore( opts: ViewStateStoreOptions ): ViewStateStore {
  return new ViewStateStoreImpl(opts);
}
