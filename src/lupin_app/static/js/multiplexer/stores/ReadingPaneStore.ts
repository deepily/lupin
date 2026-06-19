/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer WP4 — ReadingPaneStore (master-detail parity, 2026-06-10).
//
// Pure logical state for the master-detail Reading Pane. NO DOM: every
// DOM-coupled concern (iframe embedding, scroll-anchor preservation, splitter
// drag, toolbar centering) lives in ReadingPaneRenderer. This store owns:
//
//   - layout mode      ("vertical" | "horizontal"), persisted
//   - split ratio      (left column's share, [0.30, 0.85]), persisted
//   - history stack    (depth-capped at 10; { type, payload, title } entries)
//   - action-required-in-pane flag + the prior split ratio it stashed
//
// Ports the legacy `notifications.js` behavior verbatim in semantics:
//   _openContentPane / _closeContentPane / _backContentPane           → open/close/back
//   _toggleLayoutMode                                                 → toggleLayoutMode
//   _applyPaneSplitRatio (the ratio VALUE; DOM apply is the renderer)  → getSplitRatio/setSplitRatio
//   _enterActionRequiredPaneMode / _exitActionRequiredPaneMode (state) → enter/exitActionRequiredPane
//   _abstractAlreadyShown                                             → isAbstractShown
// Legacy source: `notifications.js:10889-11496`, state init `:181-205`, `:295-300`.
//
// Action-driven (not bus-subscribed): the renderer calls these methods in
// response to user gestures and AR-store changes; the store emits
// `store_reading_pane_changed` so the renderer repaints. Persistence flows
// through StorageService (the DC2 "no raw localStorage" invariant).

import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type {
  ContentPaneEntry,
  LayoutMode,
  ReadingPaneChangeKind,
  StoreReadingPaneChangedPayload,
} from "../shared/types";

// Persistence keys (StorageService prepends the "lupin:" prefix) + schema
// versions. Each persisted scalar gets its own envelope.
const LAYOUT_MODE_KEY    = "reading_pane_layout_mode";
const LAYOUT_MODE_SCHEMA = 1;
const SPLIT_RATIO_KEY    = "reading_pane_split_ratio";
const SPLIT_RATIO_SCHEMA = 1;

// Geometry constants — mirror legacy `notifications.js:184, :203, :11223, :11469-11470`.
const HISTORY_CAP        = 10;
const DEFAULT_SPLIT_RATIO = 0.667;   // pane = 1/3 (the historical abstract width)
const MIN_SPLIT_RATIO     = 0.30;
const MAX_SPLIT_RATIO     = 0.85;
const AR_SPLIT_RATIO      = 0.5;      // forced 50/50 while AR owns the pane

interface LayoutModeEnvelope { mode: LayoutMode }
interface SplitRatioEnvelope { ratio: number }

export interface ReadingPaneStore {
  /** Current layout mode (persisted). */
  getLayoutMode(): LayoutMode;
  /** Current divider ratio — left column's share of the shell width. */
  getSplitRatio(): number;
  /** Immutable copy of the history stack (oldest → newest). */
  getHistory(): ReadonlyArray<ContentPaneEntry>;
  /** Newest history entry (the one currently shown), or null when empty. */
  currentEntry(): ContentPaneEntry | null;
  /** True when the pane should be visible: has content OR AR owns it. */
  isPaneOpen(): boolean;
  /** True while the live action-required widget is lifted into the pane. */
  isActionRequiredInPane(): boolean;
  /** True when Back is meaningful (more than one entry on the stack). */
  canGoBack(): boolean;
  /**
   * Toggle predicate: is the pane open showing EXACTLY this abstract? Drives
   * the abstract-indicator second-click-closes toggle. Returns false while AR
   * owns the pane (a fall-through to open(), which AR then suppresses).
   */
  isAbstractShown(abstract: string): boolean;

  /**
   * Push a new entry and show it. No-op (returns false) while AR owns the pane
   * — the response widget is blocking (legacy `_openContentPane` AR guard).
   */
  open(type: ContentPaneEntry["type"], payload: string, title: string): boolean;
  /** Clear the history stack and hide the pane. */
  close(): void;
  /** Pop one entry; show the prior one. No-op (returns false) at depth ≤ 1. */
  back(): boolean;
  /** Flip vertical ⇄ horizontal (persisted). Returns the new mode. */
  toggleLayoutMode(): LayoutMode;
  /** Clamp to [0.30, 0.85], persist, emit. Used by the splitter drag-end. */
  setSplitRatio(ratio: number): void;
  /**
   * Lift the AR widget into the pane @ 50/50. Stashes the prior ratio.
   * No-op (returns false) in vertical mode or when already lifted.
   */
  enterActionRequiredPane(): boolean;
  /**
   * Restore the stashed prior ratio + clear the lifted flag. No-op (returns
   * false) when AR does not own the pane.
   */
  exitActionRequiredPane(): boolean;
}

export interface ReadingPaneStoreOptions {
  bus     : EventBus;
  storage : StorageService;
}

class ReadingPaneStoreImpl implements ReadingPaneStore {
  private readonly bus     : EventBus;
  private readonly storage : StorageService;

  private layoutMode  : LayoutMode = "vertical";
  private splitRatio  : number     = DEFAULT_SPLIT_RATIO;
  private history     : ContentPaneEntry[] = [];
  private arInPane    : boolean    = false;
  // Split ratio stashed by enterActionRequiredPane() so exit restores the
  // divider faithfully (the 498e98e 50/50-leak fix). Null when not lifted.
  private arPriorRatio: number | null = null;

  constructor( opts: ReadingPaneStoreOptions ) {
    this.bus     = opts.bus;
    this.storage = opts.storage;
    this.hydrate();
  }

  // -------------------------------------------------------------------------
  // Hydration — replay persisted layout mode + split ratio. A corrupt / absent
  // envelope falls back to the defaults (StorageService already emitted
  // storage_corrupt for the corrupt case).
  // -------------------------------------------------------------------------

  private hydrate(): void {
    const modeEnv = this.storage.getJSON<LayoutModeEnvelope>(LAYOUT_MODE_KEY, LAYOUT_MODE_SCHEMA);
    if (modeEnv !== null && (modeEnv.mode === "horizontal" || modeEnv.mode === "vertical")) {
      this.layoutMode = modeEnv.mode;
    }
    const ratioEnv = this.storage.getJSON<SplitRatioEnvelope>(SPLIT_RATIO_KEY, SPLIT_RATIO_SCHEMA);
    if (ratioEnv !== null && this.isValidRatio(ratioEnv.ratio)) {
      this.splitRatio = ratioEnv.ratio;
    }
  }

  private isValidRatio(r: number): boolean {
    // A NaN (which JSON can't carry anyway) fails the range comparison, so an
    // explicit Number.isNaN guard would be an unreachable branch — omitted.
    return typeof r === "number" && r >= MIN_SPLIT_RATIO && r <= MAX_SPLIT_RATIO;
  }

  // -------------------------------------------------------------------------
  // Reads
  // -------------------------------------------------------------------------

  getLayoutMode(): LayoutMode { return this.layoutMode; }
  getSplitRatio(): number     { return this.splitRatio; }

  getHistory(): ReadonlyArray<ContentPaneEntry> {
    // Defensive copy — callers must not mutate internal state.
    return this.history.map(e => ({ ...e }));
  }

  currentEntry(): ContentPaneEntry | null {
    if (this.history.length === 0) return null;
    const top = this.history[this.history.length - 1] as ContentPaneEntry;
    return { ...top };
  }

  isPaneOpen(): boolean {
    return this.history.length > 0 || this.arInPane;
  }

  isActionRequiredInPane(): boolean { return this.arInPane; }

  canGoBack(): boolean { return this.history.length > 1; }

  isAbstractShown(abstract: string): boolean {
    if (this.arInPane) return false;
    const current = this.currentEntry();
    return current !== null && current.type === "abstract" && current.payload === abstract;
  }

  // -------------------------------------------------------------------------
  // Mutations
  // -------------------------------------------------------------------------

  open(type: ContentPaneEntry["type"], payload: string, title: string): boolean {
    // While AR owns the pane, abstract/doc opens are suppressed (the blocking
    // response card keeps the pane — legacy `_openContentPane` AR guard).
    if (this.arInPane) return false;
    this.history.push({ type, payload, title: title || "" });
    if (this.history.length > HISTORY_CAP) this.history.shift();
    this.emit("opened");
    return true;
  }

  close(): void {
    this.history = [];
    this.emit("closed");
  }

  back(): boolean {
    if (this.history.length <= 1) return false;
    this.history.pop();
    this.emit("back");
    return true;
  }

  toggleLayoutMode(): LayoutMode {
    const next: LayoutMode = this.layoutMode === "horizontal" ? "vertical" : "horizontal";
    this.layoutMode = next;
    this.storage.setJSON<LayoutModeEnvelope>(LAYOUT_MODE_KEY, { mode: next }, LAYOUT_MODE_SCHEMA);
    if (next === "vertical") {
      // Switching to vertical closes the pane and surrenders AR-in-pane: the
      // renderer moves the AR widget home on this change. Restore the stashed
      // ratio first so a later horizontal open isn't stuck at the AR 50/50.
      if (this.arInPane) {
        this.restoreArPriorRatio();
        this.arInPane = false;
      }
      this.history = [];
    }
    this.emit("layout-mode");
    return next;
  }

  setSplitRatio(ratio: number): void {
    let clamped = ratio;
    if (clamped < MIN_SPLIT_RATIO) clamped = MIN_SPLIT_RATIO;
    if (clamped > MAX_SPLIT_RATIO) clamped = MAX_SPLIT_RATIO;
    this.splitRatio = clamped;
    this.storage.setJSON<SplitRatioEnvelope>(SPLIT_RATIO_KEY, { ratio: clamped }, SPLIT_RATIO_SCHEMA);
    this.emit("ratio");
  }

  enterActionRequiredPane(): boolean {
    if (this.layoutMode !== "horizontal" || this.arInPane) return false;
    this.arPriorRatio = this.splitRatio;
    this.splitRatio   = AR_SPLIT_RATIO;   // transient — NOT persisted
    this.arInPane     = true;
    this.emit("ar-enter");
    return true;
  }

  exitActionRequiredPane(): boolean {
    if (!this.arInPane) return false;
    this.restoreArPriorRatio();
    this.arInPane = false;
    this.emit("ar-exit");
    return true;
  }

  // Restore the divider to the ratio stashed by enterActionRequiredPane().
  // Invariant: arPriorRatio is set non-null by enterActionRequiredPane()
  // BEFORE arInPane flips true, so every caller (which gates on arInPane) sees
  // a number here. The `as number` encodes that contract — no defensive
  // `?? fallback`, per the no-silent-fallback mandate.
  private restoreArPriorRatio(): void {
    this.splitRatio   = this.arPriorRatio as number;
    this.arPriorRatio = null;
  }

  // -------------------------------------------------------------------------
  // Emission
  // -------------------------------------------------------------------------

  private emit(changeKind: ReadingPaneChangeKind): void {
    this.bus.emit<StoreReadingPaneChangedPayload>({
      type    : "store_reading_pane_changed",
      payload : { changeKind },
      source  : "ReadingPaneStore",
      ts      : Date.now(),
    });
  }
}

/**
 * Construct a ReadingPaneStore.
 *
 * Requires:
 *   - opts.bus is the production EventBus (or a test instance)
 *   - opts.storage is a configured StorageService
 *
 * Ensures:
 *   - persisted layout-mode + split-ratio are replayed at construction
 *   - the store is immediately usable on return
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createReadingPaneStore( opts: ReadingPaneStoreOptions ): ReadingPaneStore {
  return new ReadingPaneStoreImpl(opts);
}
