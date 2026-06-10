// Multiplexer WP4 + WP5 — ReadingPaneRenderer unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/reading_pane_renderer.test.ts`.
//
// Target: 100% lines / branches / functions on ReadingPaneRenderer.ts per the
// project 100% COVERAGE MANDATE. Uses happy-dom + the page-loaded marked/
// DOMPurify globals (the renderEntry abstract path calls renderMarkdown).

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type { StorageService } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import type { ReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type {
  ReadingPaneRenderer,
  WindowLike,
  WindowDocLike,
} from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type { StoreActionRequiredChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";

// ---------------------------------------------------------------------------
// happy-dom registration + per-test reset + marked/DOMPurify stubs
// ---------------------------------------------------------------------------

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
  // renderMarkdown reuses window.marked + window.DOMPurify. Stub both — we
  // only need deterministic, sanitized-enough HTML for the pane body.
  const w = globalThis as unknown as {
    marked    : { parse(s: string): string };
    DOMPurify : { sanitize(s: string): string };
    scrollBy  : (x: number, y: number) => void;
  };
  w.marked    = { parse: (s: string): string => `<p>${s}</p>` };
  w.DOMPurify = { sanitize: (s: string): string => s };
  // restoreCenterScrollAnchor (pane-closed branch) calls globalThis.scrollBy.
  w.scrollBy  = (): void => {};
});

let activeRenderer: ReadingPaneRenderer | null = null;

beforeEach(() => {
  document.body.replaceChildren();
  document.documentElement.removeAttribute("style");
  document.body.removeAttribute("data-layout-mode");
});

afterEach(() => {
  // Detach the document-level click listener so it can't leak across tests.
  if (activeRenderer !== null) {
    activeRenderer.unmount();
    activeRenderer = null;
  }
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// Fake AR-count store — only `.list().length` is consulted.
function makeArStore(count: number = 0) {
  let items = new Array(count).fill(0);
  return {
    store : { list: (): ReadonlyArray<unknown> => items },
    set   : (n: number): void => { items = new Array(n).fill(0); },
  };
}

// Recording window stub for bust-out.
function makeWindowStub(opts: { returnNull?: boolean } = {}): {
  win: WindowLike;
  opens: Array<{ url?: string; target?: string; features?: string }>;
  written: string[];
} {
  const opens: Array<{ url?: string; target?: string; features?: string }> = [];
  const written: string[] = [];
  const win: WindowLike = {
    open(url?: string, target?: string, features?: string): WindowDocLike | null {
      opens.push({ url, target, features });
      if (opts.returnNull) return null;
      return {
        document: {
          open() {},
          write(h: string) { written.push(h); },
          close() {},
        },
      };
    },
  };
  return { win, opens, written };
}

// Build the master-detail shell DOM matching multiplexer.html's WP4 additions.
function buildShell(): HTMLElement {
  const shell = document.createElement("div");
  shell.className = "content-shell";
  shell.innerHTML = `
    <div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <main class="container">
        <section id="notifications-pane">
          <div id="action-required-section"><div class="ar-widget">AR live widget</div></div>
          <div id="sender-cards-container">
            <div class="sender-card" data-sender-id="alice">
              <span class="message-text">Hello from Alice with a fairly long message body</span>
              <span class="abstract-indicator" data-abstract="${encodeURIComponent("**details**")}">📋</span>
            </div>
          </div>
        </section>
      </main>
    </div>
    <div id="content-pane-splitter" role="separator"></div>
    <aside class="content-pane" id="content-pane" hidden>
      <div class="content-pane-header">
        <button id="content-pane-back" type="button" disabled>←</button>
        <span id="content-pane-title"></span>
        <button id="content-pane-bustout" type="button">⤢</button>
        <button id="content-pane-close" type="button">×</button>
      </div>
      <div id="content-pane-body"></div>
    </aside>`;
  document.body.appendChild(shell);
  return shell;
}

interface Ctx {
  bus      : EventBus;
  storage  : StorageService;
  store    : ReadingPaneStore;
  renderer : ReadingPaneRenderer;
  shell    : HTMLElement;
  ar       : ReturnType<typeof makeArStore>;
  win      : ReturnType<typeof makeWindowStub>;
}

function setup(opts: {
  seed?       : (s: StorageService) => void;
  arCount?    : number;
  winReturnsNull?: boolean;
  mount?      : boolean;
} = {}): Ctx {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  if (opts.seed) opts.seed(storage);
  const store   = createReadingPaneStore({ bus, storage });
  const ar      = makeArStore(opts.arCount ?? 0);
  const win     = makeWindowStub({ returnNull: opts.winReturnsNull });
  const shell   = buildShell();
  const renderer = createReadingPaneRenderer({
    eventBus : bus,
    stores   : { readingPane: store, actionRequired: ar.store },
    windowRef: win.win,
  });
  if (opts.mount !== false) {
    renderer.mount(shell);
    activeRenderer = renderer;
  }
  return { bus, storage, store, renderer, shell, ar, win };
}

const HORIZ = (s: StorageService): void => s.setJSON("reading_pane_layout_mode", { mode: "horizontal" }, 1);

function $(sel: string): HTMLElement { return document.querySelector(sel) as HTMLElement; }
function clickEl(el: Element): void { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); }

// ===========================================================================
// 1 — Mount / unmount / guards
// ===========================================================================

test("mount: applies persisted layout mode to body, toggle tooltip set", () => {
  const { shell } = setup({ seed: HORIZ });
  assert.equal(document.body.getAttribute("data-layout-mode"), "horizontal");
  assert.equal(($("#layout-mode-toggle") as HTMLButtonElement).title, "Switch back to vertical layout");
  assert.equal(shell.querySelector("#content-pane")?.hasAttribute("hidden"), true);
});

test("mount: vertical default tooltip", () => {
  setup();
  assert.match(($("#layout-mode-toggle") as HTMLButtonElement).title, /Switch to horizontal/);
});

test("mount twice throws", () => {
  const { renderer, shell } = setup();
  assert.throws(() => renderer.mount(shell), /already mounted/);
});

test("mount throws when a shell selector is missing (req path)", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const store = createReadingPaneStore({ bus, storage });
  const ar = makeArStore();
  const bad = document.createElement("div");   // no .left-column descendant
  bad.className = "content-shell";
  document.body.appendChild(bad);
  const r = createReadingPaneRenderer({ eventBus: bus, stores: { readingPane: store, actionRequired: ar.store } });
  assert.throws(() => r.mount(bad), /\.left-column not found/);
});

test("mount throws when an id element is missing (reqId path)", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const store = createReadingPaneStore({ bus, storage });
  const ar = makeArStore();
  const shell = document.createElement("div");
  shell.className = "content-shell";
  shell.innerHTML = `<div class="left-column"></div>`;   // has .content-shell + .left-column but no #content-pane
  document.body.appendChild(shell);
  const r = createReadingPaneRenderer({ eventBus: bus, stores: { readingPane: store, actionRequired: ar.store } });
  assert.throws(() => r.mount(shell), /#content-pane not found/);
});

test("unmount detaches: post-unmount store change does not repaint", () => {
  const { renderer, store, shell } = setup({ seed: HORIZ });
  renderer.unmount();
  activeRenderer = null;
  store.open("abstract", "x", "t");   // emits, but renderer unsubscribed
  assert.equal(shell.querySelector("#content-pane")?.hasAttribute("hidden"), true);
});

// ===========================================================================
// 2 — open / close / back via store → applyState repaint
// ===========================================================================

test("open abstract: pane visible, body has rendered markdown, title set", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "hello world", "My Title");
  assert.equal($("#content-pane").hasAttribute("hidden"), false);
  assert.equal($(".content-shell").classList.contains("pane-open"), true);
  assert.equal($("#content-pane-title").textContent, "My Title");
  assert.match($("#content-pane-body").innerHTML, /hello world/);
});

test("open doc: body holds an iframe with normalized src", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("doc", "http://localhost:7999/app/docs?path=lupin/x.md", "Doc X");
  const iframe = $("#content-pane-body").querySelector("iframe") as HTMLIFrameElement;
  assert.ok(iframe);
  assert.equal(iframe.getAttribute("src"), "/app/docs?path=lupin/x.md");
  assert.equal(iframe.getAttribute("title"), "Doc X");
});

test("open doc with empty title: iframe title falls back to 'Document'", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("doc", "/app/docs?path=lupin/x.md", "");
  const iframe = $("#content-pane-body").querySelector("iframe") as HTMLIFrameElement;
  assert.equal(iframe.getAttribute("title"), "Document");
});

test("open abstract: loopback anchor href is normalized in rendered body", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", '<a href="http://localhost:7999/app/docs?path=lupin/y.md">y</a>', "t");
  const a = $("#content-pane-body").querySelector("a") as HTMLAnchorElement;
  assert.equal(a.getAttribute("href"), "/app/docs?path=lupin/y.md");
});

test("close: pane hidden + body cleared", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "x", "t");
  store.close();
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
  assert.equal($("#content-pane-body").innerHTML, "");
  assert.equal($("#content-pane-title").textContent, "");
});

test("back: button disabled at depth 1, enabled at depth 2, repaints prior", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "first", "T1");
  assert.equal(($("#content-pane-back") as HTMLButtonElement).disabled, true);
  store.open("abstract", "second", "T2");
  assert.equal(($("#content-pane-back") as HTMLButtonElement).disabled, false);
  clickEl($("#content-pane-back"));
  assert.equal($("#content-pane-title").textContent, "T1");
  assert.match($("#content-pane-body").innerHTML, /first/);
});

// ===========================================================================
// 3 — layout-mode toggle
// ===========================================================================

test("toggle click: vertical → horizontal updates body attr + tooltip", () => {
  setup();   // vertical default
  clickEl($("#layout-mode-toggle"));
  assert.equal(document.body.getAttribute("data-layout-mode"), "horizontal");
  assert.equal(($("#layout-mode-toggle") as HTMLButtonElement).title, "Switch back to vertical layout");
});

test("toggle click: horizontal → vertical closes an open pane", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "x", "t");
  clickEl($("#layout-mode-toggle"));   // → vertical
  assert.equal(document.body.getAttribute("data-layout-mode"), "vertical");
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
});

test("toggle to horizontal WITH action-required active lifts AR into pane", () => {
  const { store } = setup({ arCount: 2 });   // vertical start, AR pending
  assert.equal(store.isActionRequiredInPane(), false);
  clickEl($("#layout-mode-toggle"));   // → horizontal, AR count > 0 → lift
  assert.equal(store.isActionRequiredInPane(), true);
  assert.equal($("#content-pane-title").textContent, "Action Required");
  assert.ok($("#content-pane-body").querySelector(".ar-widget"));
});

// ===========================================================================
// 4 — WP5 action-required lift / drain
// ===========================================================================

test("AR change to count>0 in horizontal lifts the live section into the pane", () => {
  const { bus, ar, store } = setup({ seed: HORIZ, arCount: 0 });
  ar.set(1);
  bus.emit<StoreActionRequiredChangedPayload>({
    type: "store_action_required_changed",
    payload: { changeKind: "added", id_hash: "p1" },
    source: "test", ts: 0,
  });
  assert.equal(store.isActionRequiredInPane(), true);
  assert.ok($("#content-pane-body").querySelector(".ar-widget"));
  assert.equal($("#content-pane-body .ar-widget").parentElement?.id, "action-required-section");
  assert.equal($("#action-required-section").classList.contains("in-reading-pane"), true);
});

test("AR drain to count 0 restores the section home + clears pane", () => {
  const { bus, ar, store } = setup({ seed: HORIZ, arCount: 1 });
  // first paint already lifted (initial reconcile). Confirm:
  assert.equal(store.isActionRequiredInPane(), true);
  ar.set(0);
  bus.emit<StoreActionRequiredChangedPayload>({
    type: "store_action_required_changed",
    payload: { changeKind: "responded", id_hash: "p1" },
    source: "test", ts: 0,
  });
  assert.equal(store.isActionRequiredInPane(), false);
  // Section moved back under #notifications-pane.
  assert.equal($("#action-required-section").parentElement?.id, "notifications-pane");
  assert.equal($("#action-required-section").classList.contains("in-reading-pane"), false);
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
});

test("AR change ignored in vertical mode (no lift)", () => {
  const { bus, ar, store } = setup({ arCount: 1 });   // vertical
  bus.emit<StoreActionRequiredChangedPayload>({
    type: "store_action_required_changed",
    payload: { changeKind: "added", id_hash: "p1" },
    source: "test", ts: 0,
  });
  assert.equal(store.isActionRequiredInPane(), false);
});

test("AR change with count already matching state is a no-op (neither branch)", () => {
  const { bus, ar, store } = setup({ seed: HORIZ, arCount: 0 });
  // count 0 + not-in-pane → neither enter nor exit.
  bus.emit<StoreActionRequiredChangedPayload>({
    type: "store_action_required_changed",
    payload: { changeKind: "responded", id_hash: "p1" },
    source: "test", ts: 0,
  });
  assert.equal(store.isActionRequiredInPane(), false);
  void ar;
});

test("close click is inert while AR owns the pane", () => {
  const { store } = setup({ seed: HORIZ, arCount: 1 });
  assert.equal(store.isActionRequiredInPane(), true);
  clickEl($("#content-pane-close"));
  assert.equal(store.isActionRequiredInPane(), true);
  assert.equal($("#content-pane").hasAttribute("hidden"), false);
});

test("moveArIntoPane is idempotent (second lift no-op)", () => {
  const { store, renderer } = setup({ seed: HORIZ, arCount: 1 });
  assert.equal(store.isActionRequiredInPane(), true);
  renderer.forceRenderForTesting();   // re-applyState while still lifted
  assert.equal($("#content-pane-body .ar-widget").parentElement?.id, "action-required-section");
});

test("AR lift tolerates a missing #action-required-section", () => {
  const { store, shell } = setup({ seed: HORIZ, arCount: 0 });
  shell.querySelector("#action-required-section")?.remove();
  store.enterActionRequiredPane();   // emits ar-enter → moveArIntoPane finds nothing
  assert.equal($("#content-pane-body").innerHTML, "");
});

// ===========================================================================
// 5 — close button (non-AR) + bust-out
// ===========================================================================

test("close button (no AR) closes the pane", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "x", "t");
  clickEl($("#content-pane-close"));
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
});

test("bust-out doc: opens normalized url in a new tab + closes pane", () => {
  const { store, win } = setup({ seed: HORIZ });
  store.open("doc", "http://localhost:7999/app/docs?path=lupin/x.md", "Doc");
  clickEl($("#content-pane-bustout"));
  assert.deepEqual(win.opens[0], { url: "/app/docs?path=lupin/x.md", target: "_blank", features: undefined });
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
});

test("bust-out abstract: writes sanitized HTML + escaped title, closes pane", () => {
  const { store, win } = setup({ seed: HORIZ });
  store.open("abstract", "body text", 'Tom & <Jerry> "quote"');
  clickEl($("#content-pane-bustout"));
  assert.equal(win.opens[0]?.url, "");
  const html = win.written[0] ?? "";
  assert.match(html, /Tom &amp; &lt;Jerry&gt; &quot;quote&quot;/);
  assert.match(html, /body text/);
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
});

test("bust-out abstract with empty title falls back to 'Abstract'", () => {
  const { store, win } = setup({ seed: HORIZ });
  store.open("abstract", "b", "");
  clickEl($("#content-pane-bustout"));
  assert.match(win.written[0] ?? "", /<title>Abstract<\/title>/);
});

test("bust-out when window.open returns null leaves the pane open", () => {
  const { store } = setup({ seed: HORIZ, winReturnsNull: true });
  store.open("abstract", "b", "t");
  clickEl($("#content-pane-bustout"));
  assert.equal($("#content-pane").hasAttribute("hidden"), false);
});

test("bust-out with empty history is a no-op", () => {
  const { win, renderer } = setup({ seed: HORIZ });
  void renderer;
  clickEl($("#content-pane-bustout"));
  assert.equal(win.opens.length, 0);
});

// ===========================================================================
// 6 — document-level click delegation
// ===========================================================================

test("abstract-indicator click in horizontal opens pane with derived title", () => {
  const { store } = setup({ seed: HORIZ });
  clickEl($(".abstract-indicator"));
  assert.equal(store.currentEntry()?.type, "abstract");
  assert.equal(store.currentEntry()?.payload, "**details**");
  // Title derived from the .message-text, truncated to 60 chars.
  assert.equal(store.currentEntry()?.title, "Hello from Alice with a fairly long message body".slice(0, 60));
});

test("abstract-indicator second click on same abstract toggles pane closed", () => {
  const { store } = setup({ seed: HORIZ });
  clickEl($(".abstract-indicator"));
  assert.equal(store.isPaneOpen(), true);
  clickEl($(".abstract-indicator"));   // same abstract → toggle close
  assert.equal(store.isPaneOpen(), false);
});

test("abstract-indicator click in VERTICAL mode does nothing (handler bails)", () => {
  const { store } = setup();   // vertical
  clickEl($(".abstract-indicator"));
  assert.equal(store.isPaneOpen(), false);
});

test("indicator title fallback when no .message-text is present", () => {
  const { store, shell } = setup({ seed: HORIZ });
  shell.querySelector(".message-text")?.remove();
  clickEl($(".abstract-indicator"));
  assert.equal(store.currentEntry()?.title, "Notification details");
});

test("indicator title fallback when indicator has no enclosing card", () => {
  const { store } = setup({ seed: HORIZ });
  const loose = document.createElement("span");
  loose.className = "abstract-indicator";
  loose.setAttribute("data-abstract", encodeURIComponent("loose"));
  document.body.appendChild(loose);
  clickEl(loose);
  assert.equal(store.currentEntry()?.title, "Notification details");
});

test("abstract-indicator with no data-abstract attribute opens empty abstract", () => {
  const { store } = setup({ seed: HORIZ });
  const ind = document.createElement("span");
  ind.className = "abstract-indicator";   // no data-abstract
  document.body.appendChild(ind);
  clickEl(ind);
  assert.equal(store.currentEntry()?.type, "abstract");
  assert.equal(store.currentEntry()?.payload, "");
});

test("doc-link anchor click opens the pane as a doc", () => {
  const { store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "/app/docs?path=lupin/z.md");
  a.textContent = "Zebra doc";
  document.body.appendChild(a);
  clickEl(a);
  assert.equal(store.currentEntry()?.type, "doc");
  assert.equal(store.currentEntry()?.payload, "/app/docs?path=lupin/z.md");
  assert.equal(store.currentEntry()?.title, "Zebra doc");
});

test("doc-link anchor with empty text uses 'Doc' fallback", () => {
  const { store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "/app/docs?path=lupin/z.md");
  document.body.appendChild(a);
  clickEl(a);
  assert.equal(store.currentEntry()?.title, "Doc");
});

test("non-doc anchor click is ignored", () => {
  const { store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "https://example.com/page");
  a.textContent = "External";
  document.body.appendChild(a);
  clickEl(a);
  assert.equal(store.isPaneOpen(), false);
});

test("anchor with empty href is ignored (normalize → null)", () => {
  const { store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "");
  document.body.appendChild(a);
  clickEl(a);
  assert.equal(store.isPaneOpen(), false);
});

test("click with no anchor + no indicator is ignored", () => {
  const { store } = setup({ seed: HORIZ });
  const div = document.createElement("div");
  document.body.appendChild(div);
  clickEl(div);
  assert.equal(store.isPaneOpen(), false);
});

// ===========================================================================
// 7 — iframe link interception (inner handler, tested directly)
// ===========================================================================

// Helper to reach the private handler through a synthesized click on a doc
// iframe's internal anchor. We invoke the renderer's bound handler by
// dispatching a click whose target is an anchor, on a detached document — the
// renderer exposes the behavior through handleIframeLinkClick (private), so we
// drive it via a same-shaped MouseEvent dispatched at an anchor we hand it.
function fireIframeClick( renderer: ReadingPaneRenderer, anchor: Element ): void {
  // Access the private method through an index signature cast — unit-test seam.
  const impl = renderer as unknown as { handleIframeLinkClick( ev: MouseEvent ): void };
  const ev = new MouseEvent("click", { bubbles: true });
  Object.defineProperty(ev, "target", { value: anchor, enumerable: true });
  impl.handleIframeLinkClick(ev);
}

test("iframe link: doc-link routes through store.open as doc", () => {
  const { store, renderer } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "http://localhost:7999/app/docs?path=lupin/inner.md");
  a.textContent = "Inner";
  fireIframeClick(renderer, a);
  assert.equal(store.currentEntry()?.type, "doc");
  assert.equal(store.currentEntry()?.payload, "/app/docs?path=lupin/inner.md");
});

test("iframe link: external http link opens a new tab", () => {
  const { renderer, win } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "https://example.com/x");
  fireIframeClick(renderer, a);
  assert.deepEqual(win.opens.at(-1), { url: "https://example.com/x", target: "_blank", features: "noopener,noreferrer" });
});

test("iframe link: same-origin relative non-doc link lets navigation proceed (no action)", () => {
  const { renderer, win, store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "/app/other-page");
  fireIframeClick(renderer, a);
  assert.equal(win.opens.length, 0);
  assert.equal(store.isPaneOpen(), false);
});

test("iframe link: empty href ignored", () => {
  const { renderer, store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "");
  fireIframeClick(renderer, a);
  assert.equal(store.isPaneOpen(), false);
});

test("iframe link: click not on an anchor ignored", () => {
  const { renderer, store } = setup({ seed: HORIZ });
  const div = document.createElement("div");
  fireIframeClick(renderer, div);
  assert.equal(store.isPaneOpen(), false);
});

test("iframe link: null event target ignored (no anchor)", () => {
  const { renderer, store } = setup({ seed: HORIZ });
  const impl = renderer as unknown as { handleIframeLinkClick( ev: MouseEvent ): void };
  impl.handleIframeLinkClick(new MouseEvent("click"));   // target defaults to null
  assert.equal(store.isPaneOpen(), false);
});

test("iframe link: doc-link with empty anchor text uses 'Doc' fallback", () => {
  const { renderer, store } = setup({ seed: HORIZ });
  const a = document.createElement("a");
  a.setAttribute("href", "/app/docs?path=lupin/inner.md");   // no textContent
  fireIframeClick(renderer, a);
  assert.equal(store.currentEntry()?.title, "Doc");
});

// ===========================================================================
// 8 — split ratio + toolbar centering
// ===========================================================================

test("applyState sets flex-grow geometry from the split ratio", () => {
  const { store } = setup({ seed: (s) => { HORIZ(s); s.setJSON("reading_pane_split_ratio", { ratio: 0.6 }, 1); } });
  store.open("abstract", "x", "t");
  const left = $(".left-column");
  const pane = $("#content-pane");
  // happy-dom normalizes the numeric flex-grow ("60.00" → "60").
  assert.equal(parseFloat(left.style.flexGrow), 60);
  assert.equal(parseFloat(pane.style.flexGrow), 40);
});

test("toolbar-center-x: pane open → ratio/2, pane closed → 50%, vertical → removed", () => {
  const { store } = setup({ seed: (s) => { HORIZ(s); s.setJSON("reading_pane_split_ratio", { ratio: 0.6 }, 1); } });
  // closed in horizontal → 50%
  assert.equal(document.documentElement.style.getPropertyValue("--toolbar-center-x"), "50.00%");
  store.open("abstract", "x", "t");   // open → 0.6/2 = 30%
  assert.equal(document.documentElement.style.getPropertyValue("--toolbar-center-x"), "30.00%");
  store.toggleLayoutMode();           // → vertical → removed
  assert.equal(document.documentElement.style.getPropertyValue("--toolbar-center-x"), "");
});

// ===========================================================================
// 9 — splitter drag
// ===========================================================================

function stubRect( el: HTMLElement, rect: Partial<DOMRect> ): void {
  el.getBoundingClientRect = (): DOMRect => ({
    left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0,
    toJSON: () => ({}), ...rect,
  } as DOMRect);
}

test("splitter drag: move computes clamped ratio, mouseup commits to store", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "x", "t");
  stubRect($(".content-shell"), { left: 0, width: 1000 });
  $("#content-pane-splitter").dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  assert.equal(document.body.classList.contains("splitter-dragging"), true);
  // clientX 600 → ratio 0.60 (in range)
  document.dispatchEvent(new MouseEvent("mousemove", { clientX: 600 }));
  document.dispatchEvent(new MouseEvent("mouseup"));
  assert.equal(store.getSplitRatio(), 0.6);
  assert.equal(document.body.classList.contains("splitter-dragging"), false);
});

test("splitter drag: ratio clamps below 0.30 and above 0.85", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "x", "t");
  stubRect($(".content-shell"), { left: 0, width: 1000 });
  $("#content-pane-splitter").dispatchEvent(new MouseEvent("mousedown"));
  document.dispatchEvent(new MouseEvent("mousemove", { clientX: 50 }));    // 0.05 → 0.30
  document.dispatchEvent(new MouseEvent("mousemove", { clientX: 990 }));   // 0.99 → 0.85
  document.dispatchEvent(new MouseEvent("mouseup"));
  assert.equal(store.getSplitRatio(), 0.85);
});

test("splitter drag: zero-width shell aborts the move (no ratio change)", () => {
  const { store } = setup({ seed: HORIZ });
  store.open("abstract", "x", "t");
  const before = store.getSplitRatio();
  stubRect($(".content-shell"), { left: 0, width: 0 });
  $("#content-pane-splitter").dispatchEvent(new MouseEvent("mousedown"));
  document.dispatchEvent(new MouseEvent("mousemove", { clientX: 600 }));
  document.dispatchEvent(new MouseEvent("mouseup"));
  assert.equal(store.getSplitRatio(), before);   // unchanged (no move committed)
});

// ===========================================================================
// 10 — scroll-anchor preservation
// ===========================================================================

test("scroll anchor: a card below the nav offset is captured + restored (pane open)", () => {
  const { store } = setup({ seed: HORIZ });
  const card = $(".sender-card");
  stubRect(card, { top: 150 });
  // open crosses the closed→open boundary in horizontal → capture + restore.
  store.open("abstract", "x", "t");
  // leftColumn.scrollTop adjusted by delta (0 here) — assert no throw + pane open.
  assert.equal($("#content-pane").hasAttribute("hidden"), false);
});

test("scroll anchor: close crosses open→closed boundary (window scroll branch)", () => {
  const { store } = setup({ seed: HORIZ });
  const card = $(".sender-card");
  stubRect(card, { top: 150 });
  store.open("abstract", "x", "t");
  store.close();   // open→closed boundary → restore via globalThis.scrollBy
  assert.equal($("#content-pane").hasAttribute("hidden"), true);
});

test("scroll anchor: no qualifying card (all above nav offset) → no anchor", () => {
  const { store } = setup({ seed: HORIZ });
  // default rects have top 0 (< NAV_OFFSET) → loop finds none → null anchor.
  store.open("abstract", "x", "t");
  assert.equal($("#content-pane").hasAttribute("hidden"), false);
});

test("scroll anchor: missing .container in left column → null anchor", () => {
  const { store, shell } = setup({ seed: HORIZ });
  shell.querySelector(".container")?.remove();
  store.open("abstract", "x", "t");
  assert.equal($("#content-pane").hasAttribute("hidden"), false);
});
