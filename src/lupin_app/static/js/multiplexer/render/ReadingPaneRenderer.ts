/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer WP4 + WP5 — ReadingPaneRenderer (master-detail parity, 2026-06-10).
//
// DOM owner for the master-detail Reading Pane. ReadingPaneStore holds the pure
// logical state; this renderer owns every DOM-coupled concern:
//
//   - open/close/back/bust-out pane chrome                  (WP4)
//   - abstract markdown rendering + doc-link iframe embed   (WP4)
//   - parent-owned iframe link interception                 (WP4)
//   - abstract-indicator click → pane (+ second-click toggle-closed)  (WP4)
//   - doc-link click delegation → pane                      (WP4)
//   - draggable splitter + persisted split ratio            (WP4)
//   - toolbar centering (--toolbar-center-x)                (WP4)
//   - center-column scroll-position preservation            (WP4)
//   - layout-mode toggle (vertical ⇄ horizontal)            (WP4)
//   - action-required widget lifted into the pane @50/50    (WP5)
//
// Ports `notifications.js:10889-11496` semantics into the multiplexer
// store/renderer split. The renderer pushes user gestures + AR-store changes
// INTO the store; the store emits `store_reading_pane_changed`; the renderer
// repaints in `applyState()`. Event-driven only — no RAF, no polling.

import type { EventBus } from "../shared/EventBus";
import type {
  ContentPaneEntry,
  LayoutMode,
  StoreActionRequiredChangedPayload,
  StoreReadingPaneChangedPayload,
} from "../shared/types";
import { html } from "./html";
import { renderMarkdown } from "./markdown";

// Store surface this renderer drives (subset of ReadingPaneStore).
export interface ReadingPaneStoreLike {
  getLayoutMode(): LayoutMode;
  getSplitRatio(): number;
  currentEntry(): ContentPaneEntry | null;
  isPaneOpen(): boolean;
  isActionRequiredInPane(): boolean;
  canGoBack(): boolean;
  isAbstractShown(abstract: string): boolean;
  open(type: ContentPaneEntry["type"], payload: string, title: string): boolean;
  close(): void;
  back(): boolean;
  toggleLayoutMode(): LayoutMode;
  setSplitRatio(ratio: number): void;
  enterActionRequiredPane(): boolean;
  exitActionRequiredPane(): boolean;
}

// WP5 lift/drain reads each item's `state` — ActionRequiredStore.list() retains
// responded/expired/cancelled items in a TERMINAL state (it never removes
// them), so a raw `.length` never drains. We filter to the still-blocking
// states (pending / submitting / failed).
export interface ActionRequiredItemLike {
  state: string;
}
export interface ActionRequiredCountLike {
  list(): ReadonlyArray<ActionRequiredItemLike>;
}

// Minimal window surface for bust-out (dependency-injected for testing).
export interface WindowLike {
  open(url?: string, target?: string, features?: string): WindowDocLike | null;
}
export interface WindowDocLike {
  document: {
    open(): void;
    write(html: string): void;
    close(): void;
  };
}

export interface ReadingPaneRenderer {
  /** Attach to the `.content-shell` root (must contain the full pane DOM). */
  mount( root: HTMLElement ): void;
  /** Detach: unsubscribe + remove DOM listeners owned by this renderer. */
  unmount(): void;
  /** Test helper — synchronously repaint from current store state. */
  forceRenderForTesting(): void;
}

export interface ReadingPaneRendererOptions {
  eventBus : EventBus;
  stores   : {
    readingPane    : ReadingPaneStoreLike;
    actionRequired : ActionRequiredCountLike;
  };
  /** Bust-out target window (defaults to the global `window`). */
  windowRef? : WindowLike;
}

// Loopback-host prefix strip — lets doc-links resolve when the dev server is
// reached from a remote host. Ports `notifications.js:10970`.
const LOOPBACK_PREFIX_RE = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/;
const DOC_LINK_PREFIX    = "/app/docs?path=";
const NAV_OFFSET_PX      = 100;   // nav strip height (legacy `:11140`)
const TITLE_MAX          = 60;
const BUSTOUT_BASE_CSS   =
  "body{max-width:900px;margin:0 auto;padding:24px 28px;font-size:14px;line-height:1.6;color:#212529;}";

interface ScrollAnchor { el: Element; top: number; }

class ReadingPaneRendererImpl implements ReadingPaneRenderer {
  private readonly bus            : EventBus;
  private readonly store          : ReadingPaneStoreLike;
  private readonly actionRequired : ActionRequiredCountLike;
  private readonly win            : WindowLike;
  private readonly unsubscribers  : Array<() => void> = [];

  private mounted   : boolean = false;
  private root      : HTMLElement | null = null;
  // Pane DOM — assigned (non-null) at mount after the existence checks.
  private shell     !: HTMLElement;
  private leftColumn!: HTMLElement;
  private pane      !: HTMLElement;
  private body      !: HTMLElement;
  private titleEl   !: HTMLElement;
  private backBtn   !: HTMLButtonElement;
  private closeBtn  !: HTMLButtonElement;
  private bustBtn   !: HTMLButtonElement;
  private splitter  !: HTMLElement;
  private toggleBtn !: HTMLButtonElement;

  // AR lift bookkeeping (WP5) — DOM refs live here, not in the store.
  private arSection    : HTMLElement | null = null;
  private arHomeParent : Node | null = null;
  private arHomeNext   : Node | null = null;

  // Bound listeners (stable refs for add/removeEventListener symmetry).
  private onToggleClick    !: () => void;
  private onCloseClick     !: () => void;
  private onBackClick      !: () => void;
  private onBustClick      !: () => void;
  private onSplitterDown   !: ( ev: MouseEvent ) => void;
  private onDocClick       !: ( ev: MouseEvent ) => void;
  // Drag-session listeners (attached/detached per drag).
  private onDragMove       : ( ( ev: MouseEvent ) => void ) | null = null;
  private onDragUp         : ( () => void ) | null = null;
  private dragging         : boolean = false;

  constructor( opts: ReadingPaneRendererOptions ) {
    this.bus            = opts.eventBus;
    this.store          = opts.stores.readingPane;
    this.actionRequired = opts.stores.actionRequired;
    /* c8 ignore next */ // default-arg fallback to global window; tests always inject windowRef.
    this.win            = opts.windowRef ?? ( globalThis as unknown as { window: WindowLike } ).window;
  }

  // -------------------------------------------------------------------------
  // Mount / unmount
  // -------------------------------------------------------------------------

  mount( root: HTMLElement ): void {
    if (this.mounted) throw new Error("ReadingPaneRenderer.mount: already mounted");

    // `root` IS the `.content-shell` (boot mounts us on it); the rest are
    // descendants (left column, splitter, pane) or global ids (#content-pane*).
    this.shell      = root;
    this.leftColumn = req(root, ".left-column");
    this.pane       = reqId("content-pane");
    this.body       = reqId("content-pane-body");
    this.titleEl    = reqId("content-pane-title");
    this.backBtn    = reqId<HTMLButtonElement>("content-pane-back");
    this.closeBtn   = reqId<HTMLButtonElement>("content-pane-close");
    this.bustBtn    = reqId<HTMLButtonElement>("content-pane-bustout");
    this.splitter   = reqId("content-pane-splitter");
    this.toggleBtn  = reqId<HTMLButtonElement>("layout-mode-toggle");

    this.root    = root;
    this.mounted = true;

    // Bind chrome listeners.
    this.onToggleClick  = (): void => this.handleToggleLayout();
    this.onCloseClick   = (): void => this.handleCloseClick();
    this.onBackClick    = (): void => { this.store.back(); };
    this.onBustClick    = (): void => this.handleBustOut();
    this.onSplitterDown = (ev: MouseEvent): void => this.handleSplitterDown(ev);
    this.onDocClick     = (ev: MouseEvent): void => this.handleDocumentClick(ev);

    this.toggleBtn.addEventListener("click", this.onToggleClick);
    this.closeBtn.addEventListener("click", this.onCloseClick);
    this.backBtn.addEventListener("click", this.onBackClick);
    this.bustBtn.addEventListener("click", this.onBustClick);
    this.splitter.addEventListener("mousedown", this.onSplitterDown);
    document.addEventListener("click", this.onDocClick);

    this.updateToggleTooltip();

    // Store-change reactions.
    this.unsubscribers.push(
      this.bus.on<StoreReadingPaneChangedPayload>(
        "store_reading_pane_changed",
        () => this.applyState(),
      ),
    );
    this.unsubscribers.push(
      this.bus.on<StoreActionRequiredChangedPayload>(
        "store_action_required_changed",
        () => this.reconcileActionRequired(),
      ),
    );

    // Initial paint — honors persisted layout mode + any pre-mount AR state.
    this.reconcileActionRequired();
    this.applyState();
  }

  unmount(): void {
    for (const off of this.unsubscribers) off();
    this.unsubscribers.length = 0;

    this.toggleBtn.removeEventListener("click", this.onToggleClick);
    this.closeBtn.removeEventListener("click", this.onCloseClick);
    this.backBtn.removeEventListener("click", this.onBackClick);
    this.bustBtn.removeEventListener("click", this.onBustClick);
    this.splitter.removeEventListener("mousedown", this.onSplitterDown);
    document.removeEventListener("click", this.onDocClick);
    this.detachDragListeners();

    // Surrender any lifted AR widget back home so unmount leaves the DOM clean.
    this.moveArHome();

    this.root    = null;
    this.mounted = false;
  }

  forceRenderForTesting(): void {
    this.applyState();
  }

  // -------------------------------------------------------------------------
  // Central paint — reads store state, mutates the pane DOM. Idempotent.
  // -------------------------------------------------------------------------

  private applyState(): void {
    /* c8 ignore next */ // defensive: subscriptions are detached in unmount() before mounted flips false.
    if (!this.mounted) return;

    const mode = this.store.getLayoutMode();
    document.body.setAttribute("data-layout-mode", mode);

    const willOpen  = this.store.isPaneOpen();
    const wasOpen   = this.shell.classList.contains("pane-open");
    // Capture the center scroll anchor BEFORE the pane-open boundary flips
    // (only that transition hands off the scroll container — legacy `:11088`).
    const anchor: ScrollAnchor | null =
      (mode === "horizontal" && willOpen !== wasOpen) ? this.captureCenterScrollAnchor() : null;

    // WP5 — place the AR widget first; body content paint depends on it.
    if (this.store.isActionRequiredInPane()) {
      this.moveArIntoPane();
    } else {
      this.moveArHome();
      this.renderEntry(this.store.currentEntry());
    }

    this.pane.hidden = !willOpen;
    this.shell.classList.toggle("pane-open", willOpen);
    this.titleEl.textContent = this.store.isActionRequiredInPane()
      ? "Action Required"
      : (this.store.currentEntry()?.title ?? "");
    this.backBtn.disabled = !this.store.canGoBack();

    this.applyPaneSplitRatio();

    if (anchor !== null) this.restoreCenterScrollAnchor(anchor);
  }

  // -------------------------------------------------------------------------
  // Entry rendering (abstract markdown / doc iframe)
  // -------------------------------------------------------------------------

  private renderEntry( entry: ContentPaneEntry | null ): void {
    if (entry === null) {
      this.body.replaceChildren();
      return;
    }
    if (entry.type === "abstract") {
      const frag = html`${renderMarkdown(entry.payload)}`;
      this.body.replaceChildren(frag);
      // Strip any absolute-loopback anchor prefixes so they resolve remotely
      // (the document-level interceptor only catches /app/docs?path= forms).
      const anchors = this.body.querySelectorAll("a[href]");
      for (const a of Array.from(anchors)) {
        const raw  = a.getAttribute("href");
        const norm = this.normalizeDocLinkHref(raw);
        if (norm !== null && norm !== raw) a.setAttribute("href", norm);
      }
      return;
    }
    // entry.type === "doc"
    const frame = document.createElement("iframe");
    const src   = this.normalizeDocLinkHref(entry.payload);
    /* c8 ignore next */ // defensive: doc payloads are always non-empty hrefs from open(); the null arm guards a malformed push.
    frame.setAttribute("src", src ?? entry.payload);
    frame.setAttribute("title", entry.title || "Document");
    this.bindIframeLinkInterception(frame);
    this.body.replaceChildren(frame);
  }

  // -------------------------------------------------------------------------
  // WP5 — action-required lift / restore
  // -------------------------------------------------------------------------

  // Count prompts still demanding a response (non-terminal). The store keeps
  // responded/expired/cancelled items in `list()`, so we must filter by state —
  // a raw length would lift the pane and never drain it.
  private activeActionRequiredCount(): number {
    return this.actionRequired.list().filter(
      i => i.state === "pending" || i.state === "submitting" || i.state === "failed",
    ).length;
  }

  private reconcileActionRequired(): void {
    if (this.store.getLayoutMode() !== "horizontal") return;
    const count = this.activeActionRequiredCount();
    if (count > 0 && !this.store.isActionRequiredInPane()) {
      this.store.enterActionRequiredPane();
    } else if (count === 0 && this.store.isActionRequiredInPane()) {
      this.store.exitActionRequiredPane();
    }
  }

  private moveArIntoPane(): void {
    if (this.arSection !== null) return;   // already lifted
    const section = document.getElementById("action-required-section");
    if (section === null) return;
    this.arSection    = section;
    this.arHomeParent = section.parentNode;
    this.arHomeNext   = section.nextSibling;
    section.classList.add("in-reading-pane");
    this.body.replaceChildren(section);
  }

  private moveArHome(): void {
    if (this.arSection === null) return;   // nothing lifted
    const section = this.arSection;
    section.classList.remove("in-reading-pane");
    // arHomeParent is non-null: moveArIntoPane only lifts a section it found in
    // the DOM (so it had a parent). The cast encodes that invariant — no
    // defensive branch, per the no-silent-fallback mandate.
    (this.arHomeParent as Node).insertBefore(section, this.arHomeNext);
    this.arSection    = null;
    this.arHomeParent = null;
    this.arHomeNext   = null;
  }

  // -------------------------------------------------------------------------
  // Chrome handlers
  // -------------------------------------------------------------------------

  private handleToggleLayout(): void {
    const mode = this.store.toggleLayoutMode();
    // Switching TO horizontal with AR active → lift it (the store's toggle does
    // not know the AR count; that coordination is the renderer's, as in legacy).
    if (mode === "horizontal" && this.activeActionRequiredCount() > 0) {
      this.store.enterActionRequiredPane();
    }
    this.updateToggleTooltip();
  }

  private handleCloseClick(): void {
    // While AR owns the pane the response card is blocking — close is inert.
    if (this.store.isActionRequiredInPane()) return;
    this.store.close();
  }

  private handleBustOut(): void {
    const entry = this.store.currentEntry();
    if (entry === null) return;

    let win: WindowDocLike | null;
    if (entry.type === "doc") {
      const src = this.normalizeDocLinkHref(entry.payload);
      /* c8 ignore next */ // defensive: doc payloads are non-empty; the null arm guards a malformed entry.
      win = this.win.open(src ?? entry.payload, "_blank");
    } else {
      win = this.win.open("", "_blank");
      if (win !== null) {
        const safeTitle = (entry.title || "Abstract").replace(
          /[&<>"]/g,
          (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c] as string),
        );
        // Body is sanitized by renderMarkdown's DOMPurify pass; title is escaped above.
        const bodyHtml = this.renderMarkdownToString(entry.payload);
        win.document.open();
        win.document.write(
          "<!DOCTYPE html><html><head><meta charset=\"utf-8\">" +
          "<title>" + safeTitle + "</title>" +
          "<link rel=\"stylesheet\" href=\"/static/css/lupin-base.css\">" +
          "<style>" + BUSTOUT_BASE_CSS + "</style>" +
          "</head><body>" + bodyHtml + "</body></html>",
        );
        win.document.close();
      }
    }
    // Only collapse the pane if the tab actually opened.
    if (win !== null) this.store.close();
  }

  // Render markdown to an HTML string for bust-out (renderMarkdown returns a
  // RawValue carrying the sanitized HTML).
  private renderMarkdownToString( text: string ): string {
    const value = renderMarkdown(text) as { __raw: string };
    return value.__raw;
  }

  private updateToggleTooltip(): void {
    this.toggleBtn.title = this.store.getLayoutMode() === "horizontal"
      ? "Switch back to vertical layout"
      : "Switch to horizontal layout (Reading Pane on right). Best at viewports ≥ 1200px wide.";
  }

  // -------------------------------------------------------------------------
  // Document-level click delegation — abstract indicators + doc-links
  // -------------------------------------------------------------------------

  private handleDocumentClick( ev: MouseEvent ): void {
    if (this.store.getLayoutMode() !== "horizontal") return;
    const target = ev.target as Element | null;
    /* c8 ignore next */ // defensive: a fired click always has a non-null Element target in DOM + happy-dom.
    if (target === null) return;

    const indicator = target.closest(".abstract-indicator");
    if (indicator !== null) {
      ev.stopPropagation();
      // Read data-abstract RAW — the mux writer stores it raw via setAttribute
      // (no encode), so the reader must be raw too (within-mux write/read
      // symmetry). A prior decodeURIComponent here threw URIError on any bare
      // `%` in prose (e.g. "100% done") → ~10% of clicks failed silently.
      // Do NOT "match legacy": legacy ENCODES both sides (notifications.js
      // write :7230+ / read :10022); matching it would mean ADDING
      // encodeURIComponent to BOTH mux writer + reader — the opposite of this
      // fix. The raw/raw symmetry is the intended end-state.
      const abstract = indicator.getAttribute("data-abstract") ?? "";
      // Second click on the SAME abstract toggles the pane closed (97bfb8c).
      if (this.store.isAbstractShown(abstract)) {
        this.store.close();
        return;
      }
      this.store.open("abstract", abstract, this.deriveIndicatorTitle(indicator));
      return;
    }

    const anchor = target.closest("a[href]");
    if (anchor === null) return;
    const normalized = this.normalizeDocLinkHref(anchor.getAttribute("href"));
    if (normalized === null || !normalized.startsWith(DOC_LINK_PREFIX)) return;
    ev.preventDefault();
    this.store.open("doc", normalized, anchor.textContent || "Doc");
  }

  private deriveIndicatorTitle( indicator: Element ): string {
    const card    = indicator.closest(".sender-card, .notification-message, .conversation-pair");
    const titleEl = card !== null ? card.querySelector(".message-text") : null;
    if (titleEl === null) return "Notification details";
    /* c8 ignore next */ // Element.textContent is never null at runtime; the ?? "" guards the DOM type only.
    const text = titleEl.textContent ?? "";
    return text.trim().slice(0, TITLE_MAX);
  }

  // -------------------------------------------------------------------------
  // Iframe link interception (parent-owned, same-origin)
  // -------------------------------------------------------------------------

  private bindIframeLinkInterception( frame: HTMLIFrameElement ): void {
    frame.addEventListener("load", () => this.handleIframeLoad(frame));
  }

  /* c8 ignore start */ // iframe.contentDocument is unavailable in happy-dom; the load-time wiring shell is exercised only in a real browser (E2E smoke). The inner click logic is unit-tested directly via handleIframeLinkClick().
  private handleIframeLoad( frame: HTMLIFrameElement ): void {
    let idoc: Document | null;
    try { idoc = frame.contentDocument; } catch (_e) { idoc = null; }
    if (idoc === null) return;
    idoc.addEventListener("click", (ev) => this.handleIframeLinkClick(ev as MouseEvent));
  }
  /* c8 ignore stop */

  // Pure-ish iframe click handler — extracted so it is unit-testable without a
  // live same-origin iframe document (which happy-dom cannot provide).
  private handleIframeLinkClick( ev: MouseEvent ): void {
    const target = ev.target as Element | null;
    const a = target !== null ? target.closest("a[href]") : null;
    if (a === null) return;
    const norm = this.normalizeDocLinkHref(a.getAttribute("href"));
    if (norm === null) return;
    if (norm.startsWith(DOC_LINK_PREFIX)) {
      ev.preventDefault();
      this.store.open("doc", norm, a.textContent || "Doc");
    } else if (/^https?:\/\//.test(norm)) {
      ev.preventDefault();
      this.win.open(norm, "_blank", "noopener,noreferrer");
    }
    // else: same-origin non-doc relative link — let the iframe navigate.
  }

  // -------------------------------------------------------------------------
  // Split ratio + toolbar centering
  // -------------------------------------------------------------------------

  private applyPaneSplitRatio(): void {
    this.applyRatioToDom(this.store.getSplitRatio());
  }

  // Apply a ratio to the flex geometry + toolbar var WITHOUT touching the store
  // (used live during a drag; the store commit happens on mouseup).
  private applyRatioToDom( ratio: number ): void {
    this.leftColumn.style.flexGrow  = (ratio * 100).toFixed(2);
    this.leftColumn.style.flexBasis = "0";
    this.pane.style.flexGrow        = ((1 - ratio) * 100).toFixed(2);
    this.pane.style.flexBasis       = "0";
    this.updateToolbarPosition(ratio);
  }

  private updateToolbarPosition( ratio: number ): void {
    const docEl = document.documentElement;
    if (this.store.getLayoutMode() !== "horizontal") {
      docEl.style.removeProperty("--toolbar-center-x");
      return;
    }
    const paneOpen  = this.shell.classList.contains("pane-open");
    const centerPct = paneOpen ? (ratio / 2) * 100 : 50;
    docEl.style.setProperty("--toolbar-center-x", `${centerPct.toFixed(2)}%`);
  }

  // -------------------------------------------------------------------------
  // Splitter drag
  // -------------------------------------------------------------------------

  private handleSplitterDown( ev: MouseEvent ): void {
    ev.preventDefault();
    this.dragging = true;
    this.splitter.classList.add("dragging");
    document.body.classList.add("splitter-dragging");
    this.onDragMove = (e: MouseEvent): void => this.handleDragMove(e);
    this.onDragUp   = (): void => this.handleDragUp();
    document.addEventListener("mousemove", this.onDragMove);
    document.addEventListener("mouseup", this.onDragUp);
  }

  private handleDragMove( ev: MouseEvent ): void {
    /* c8 ignore next */ // defensive: drag listeners are detached on mouseup, so a move with dragging=false can't fire in practice.
    if (!this.dragging) return;
    const rect = this.shell.getBoundingClientRect();
    if (rect.width <= 0) return;
    let ratio = (ev.clientX - rect.left) / rect.width;
    if (ratio < 0.30) ratio = 0.30;
    if (ratio > 0.85) ratio = 0.85;
    // Live DOM apply only — store commit deferred to drag-end (avoid churn).
    this.applyRatioToDom(ratio);
    this.lastDragRatio = ratio;
  }
  private lastDragRatio: number | null = null;

  private handleDragUp(): void {
    /* c8 ignore next */ // defensive: the mouseup listener is attached only during an active drag and detached here, so a !dragging call can't fire in practice.
    if (!this.dragging) return;
    this.dragging = false;
    this.splitter.classList.remove("dragging");
    document.body.classList.remove("splitter-dragging");
    if (this.lastDragRatio !== null) {
      this.store.setSplitRatio(this.lastDragRatio);
      this.lastDragRatio = null;
    }
    this.detachDragListeners();
  }

  private detachDragListeners(): void {
    if (this.onDragMove !== null) {
      document.removeEventListener("mousemove", this.onDragMove);
      this.onDragMove = null;
    }
    if (this.onDragUp !== null) {
      document.removeEventListener("mouseup", this.onDragUp);
      this.onDragUp = null;
    }
  }

  // -------------------------------------------------------------------------
  // Scroll-position preservation across the pane-open scroll-container handoff
  // -------------------------------------------------------------------------

  private captureCenterScrollAnchor(): ScrollAnchor | null {
    const container = this.leftColumn.querySelector(".container");
    if (container === null) return null;
    const cards = container.querySelectorAll(
      ".conversation-pair, .notification-message, .sender-card",
    );
    for (const el of Array.from(cards)) {
      const top = el.getBoundingClientRect().top;
      if (top >= NAV_OFFSET_PX) return { el, top };
    }
    return null;
  }

  private restoreCenterScrollAnchor( anchor: ScrollAnchor ): void {
    /* c8 ignore next */ // defensive: capture + restore run in the same synchronous applyState() pass, so the anchored card is always still connected at restore time.
    if (!anchor.el.isConnected) return;
    const delta    = anchor.el.getBoundingClientRect().top - anchor.top;
    const paneOpen = this.shell.classList.contains("pane-open");
    if (paneOpen) {
      this.leftColumn.scrollTop += delta;
    } else {
      ( globalThis as unknown as { scrollBy( x: number, y: number ): void } ).scrollBy(0, delta);
    }
  }

  // -------------------------------------------------------------------------
  // href normalization
  // -------------------------------------------------------------------------

  private normalizeDocLinkHref( href: string | null ): string | null {
    if (href === null || href === "") return null;
    return href.replace(LOOPBACK_PREFIX_RE, "");
  }
}

// Mount-time element resolvers — throw with a clear message when the required
// shell DOM is absent (mirrors the FocusTrayRenderer/PersonaModalRenderer
// pattern; after these run, every field is non-null at every use site).
function req<T extends HTMLElement>( root: HTMLElement, selector: string ): T {
  const el = root.querySelector<T>(selector);
  if (el === null) throw new Error(`ReadingPaneRenderer.mount: ${selector} not found`);
  return el;
}
function reqId<T extends HTMLElement = HTMLElement>( id: string ): T {
  const el = document.getElementById(id) as T | null;
  if (el === null) throw new Error(`ReadingPaneRenderer.mount: #${id} not found`);
  return el;
}

/**
 * Factory — production code constructs via `createReadingPaneRenderer`.
 * Matches the Phase 5/6 renderer factory pattern.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createReadingPaneRenderer(
  opts: ReadingPaneRendererOptions,
): ReadingPaneRenderer {
  return new ReadingPaneRendererImpl(opts);
}
