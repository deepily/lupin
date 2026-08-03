// Multiplexer Lane C (v0.1.9 focus-bar parity) — BroadcastCardRenderer tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/broadcast_card_renderer.test.ts`.
//
// Coverage target: 100% lines/branches/functions on BroadcastCardRenderer.ts.
// Uses the REAL BroadcastStore + EventBus + in-memory StorageService, a stub
// ApiClient, and an INJECTED fake recorder so STT onComplete/onError/toggle
// paths are deterministic (the rafFn/fetcher injection idiom).

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createBroadcastStore } from "../../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import { createBroadcastCardRenderer } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastCardRenderer";
import type {
  BroadcastCardRenderer,
  BroadcastCardApiClient,
  BroadcastRecorderLike,
} from "../../../../lupin_app/static/js/multiplexer/render/BroadcastCardRenderer";
import type { BroadcastStore, BroadcastRecipient } from "../../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import type { BroadcastRequest, BroadcastResult } from "../../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

afterEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

const RECIPIENTS: BroadcastRecipient[] = [
  { session_id: "s1", persona_name: "Tiberius", persona_icon: "👑", persona_color: "#fff" },
  { session_id: "s2", persona_name: "Krishna",  persona_icon: "🦚", persona_color: "#1DE9B6" },
];

const RESULT_OK: BroadcastResult = {
  broadcast_id      : "abcdef12-3456-4789-abcd-ef0123456789",
  recipients        : 2,
  failed_recipients : [],
  filtered_out      : [],
  status            : "ok",
};

function flush(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

// --- Fake recorder -----------------------------------------------------------
class FakeRecorder implements BroadcastRecorderLike {
  lastStart: RecordingManagerStartOptions | null = null;
  stopped: string[] = [];
  startRecording(opts: RecordingManagerStartOptions): Promise<void> {
    this.lastStart = opts;
    return Promise.resolve();
  }
  stopRecording(id: string): Promise<void> {
    this.stopped.push(id);
    return Promise.resolve();
  }
}

// --- Stub api ----------------------------------------------------------------
interface ApiOpts {
  sessions?   : BroadcastRecipient[] | Error;
  sendResult? : BroadcastResult | Error | string;   // string → non-Error rejection
}
function makeApi(opts: ApiOpts): { api: BroadcastCardApiClient; sent: BroadcastRequest[]; getCalls: () => number } {
  const sent: BroadcastRequest[] = [];
  let getCount = 0;
  const api: BroadcastCardApiClient = {
    get<T>(_path: string): Promise<T> {
      getCount++;
      const s = opts.sessions;
      if (s instanceof Error) return Promise.reject(s);
      return Promise.resolve({ sessions: s ?? [] } as T);
    },
    broadcastToCcSessions(req: BroadcastRequest): Promise<BroadcastResult> {
      sent.push(req);
      const r = opts.sendResult;
      if (r instanceof Error) return Promise.reject(r);
      if (typeof r === "string") return Promise.reject(r);
      return Promise.resolve(r ?? RESULT_OK);
    },
  };
  return { api, sent, getCalls: () => getCount };
}

// A controllable fake scheduler — captures pending timers without firing them so
// debounce coalescing + teardown-clear are deterministic (no real 250ms waits).
interface FakeScheduler {
  setTimeoutFn   : ( cb: () => void, ms: number ) => unknown;
  clearTimeoutFn : ( id: unknown ) => void;
  pending        : Array<{ id: number; cb: () => void; ms: number; cleared: boolean }>;
  flushTimers    : () => void;   // run every not-yet-cleared pending timer
}
function makeScheduler(): FakeScheduler {
  const pending: Array<{ id: number; cb: () => void; ms: number; cleared: boolean }> = [];
  let nextId = 1;
  return {
    pending,
    setTimeoutFn   : ( cb, ms ) => { const id = nextId++; pending.push( { id, cb, ms, cleared: false } ); return id; },
    clearTimeoutFn : ( id ) => { const e = pending.find( ( p ) => p.id === id ); if ( e !== undefined ) e.cleared = true; },
    flushTimers    : () => { for ( const e of pending ) { if ( !e.cleared ) { e.cleared = true; e.cb(); } } },
  };
}

interface Harness {
  renderer : BroadcastCardRenderer;
  root     : HTMLElement;
  store    : BroadcastStore;
  bus      : EventBus;
  recorder : FakeRecorder;
  sent     : BroadcastRequest[];
  getCalls : () => number;
}

interface SetupExtra {
  debounceMs? : number;        // default 0 → event-driven refresh fires within flush()
  sched?      : FakeScheduler; // inject a controllable scheduler (else real globalThis timers)
}

async function setup(apiOpts: ApiOpts = { sessions: RECIPIENTS }, extra: SetupExtra = {}): Promise<Harness> {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting();
  const store    = createBroadcastStore({ storage });
  const recorder = new FakeRecorder();
  const { api, sent, getCalls } = makeApi(apiOpts);
  const renderer = createBroadcastCardRenderer( {
    eventBus: bus, store, api, recorder, getAuthToken: () => "tok",
    recipientsRefreshDebounceMs : extra.debounceMs ?? 0,
    setTimeoutFn                : extra.sched?.setTimeoutFn,
    clearTimeoutFn              : extra.sched?.clearTimeoutFn,
  } );
  const root = document.createElement("div");
  document.body.appendChild(root);
  renderer.mount(root);
  await flush();   // let the initial performRefresh() hydrate resolve
  return { renderer, root, store, bus, recorder, sent, getCalls };
}

// Convenience element getters.
const $ = (root: HTMLElement, sel: string): HTMLElement => root.querySelector(sel) as HTMLElement;
const ta = (root: HTMLElement): HTMLTextAreaElement => root.querySelector("#broadcast-textarea") as HTMLTextAreaElement;
const sendBtn = (root: HTMLElement): HTMLButtonElement => root.querySelector("#broadcast-send-button") as HTMLButtonElement;
const chips = (root: HTMLElement): HTMLElement[] => Array.from(root.querySelectorAll(".broadcast-chip"));

function typeMessage(root: HTMLElement, text: string): void {
  const t = ta(root);
  t.value = text;
  t.dispatchEvent(new Event("input"));
}

// ---------------------------------------------------------------------------
// Construction + lifecycle
// ---------------------------------------------------------------------------

test("constructor throws without a store", () => {
  const bus = createEventBusForTesting();
  const { api } = makeApi({});
  assert.throws(
    () => createBroadcastCardRenderer({ eventBus: bus, store: undefined as unknown as BroadcastStore, api }),
    /requires a store/,
  );
});

test("mount builds the card; a 2nd mount throws", async () => {
  const { renderer, root } = await setup();
  assert.notEqual(root.querySelector("#broadcast-submit-card"), null);
  assert.throws(() => renderer.mount(root), /already mounted/);
});

test("unmount clears the root + is idempotent", async () => {
  const { renderer, root } = await setup();
  renderer.unmount();
  assert.equal(root.querySelector("#broadcast-submit-card"), null);
  renderer.unmount();   // 2nd call is a no-op
});

test("forceRenderForTesting re-renders chips + send state", async () => {
  const { renderer, root } = await setup();
  renderer.forceRenderForTesting();
  // 2 recipients + @all chip rendered.
  assert.equal(chips(root).length, 3);
});

// B1 (01-A, F-Sam-BA1) — the re-nested commons "Recent Activity" chrome is a
// SIBLING of #broadcast-recipients-row (not a child), so it survives the
// recipientsRow.replaceChildren() that runs on every recipient refresh.
test("B1: nested commons chrome survives a recipient-row refresh (F-Sam-BA1)", async () => {
  const { root } = await setup();
  // Present after the initial mount + first performRefresh().
  assert.notEqual(root.querySelector("#commons-activity-pane"), null);
  assert.notEqual(root.querySelector("#commons-activity-entries"), null);

  // Trigger an explicit recipient refresh → renderChips → recipientsRow.replaceChildren().
  $(root, "#broadcast-recipients-refresh").click();
  await flush();

  // The recipients row was wiped + rebuilt, but the commons subtree is untouched.
  const commons = root.querySelector("#commons-activity-pane");
  assert.notEqual(commons, null);
  assert.notEqual(root.querySelector("#commons-activity-entries"), null);
  // And it genuinely lives OUTSIDE the recipients row.
  assert.equal($(root, "#broadcast-recipients-row").contains(commons), false);
});

// ---------------------------------------------------------------------------
// Recipients
// ---------------------------------------------------------------------------

test("initial hydrate renders @all + per-recipient chips", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  const labels = chips(root).map((c) => c.textContent);
  assert.ok(labels.some((l) => l?.includes("@all")));
  assert.ok(labels.some((l) => l?.includes("Tiberius")));
  assert.ok(labels.some((l) => l?.includes("Krishna")));
});

test("empty active-session list renders the no-active-sessions pill", async () => {
  const { root } = await setup({ sessions: [] });
  const pill = root.querySelector(".broadcast-chip.no-recipients");
  assert.notEqual(pill, null);
  assert.equal(pill?.textContent, "no active sessions");
});

test("hydrate failure renders the error pill", async () => {
  const { root } = await setup({ sessions: new Error("network down") });
  const pill = root.querySelector(".broadcast-chip.no-recipients");
  assert.notEqual(pill, null);
  assert.ok(pill?.textContent?.includes("failed to load: network down"));
});

test("↻ refresh re-fetches the recipient list", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  $(root, "#broadcast-recipients-refresh").click();
  await flush();
  assert.equal(chips(root).length, 3);
});

test("store_session_strip_changed triggers a (debounced) recipient refresh", async () => {
  const { root, bus, getCalls } = await setup({ sessions: [] });   // debounceMs 0 → fires within flush()
  assert.notEqual(root.querySelector(".broadcast-chip.no-recipients"), null);
  const before = getCalls();   // 1 from the initial mount hydrate
  // A peer appears; the burst-path scheduleRefresh runs its trailing fetch.
  bus.emit({ type: "store_session_strip_changed", payload: { changeKind: "added" }, source: "test", ts: 0 });
  // Two macrotask ticks: the first lets the real setTimeout(0) debounce fire
  // (→ performRefresh + the hydrate GET), the second lets the hydrate .then
  // repaint the chips.
  await flush();
  await flush();
  assert.equal(getCalls(), before + 1);
  assert.notEqual(root.querySelector(".broadcast-chip.no-recipients"), null);
});

test("a burst of store_session_strip_changed events coalesces into ONE refresh", async () => {
  const sched = makeScheduler();
  const { bus, getCalls } = await setup({ sessions: RECIPIENTS }, { debounceMs: 250, sched });
  const before = getCalls();   // 1 from the initial mount hydrate (immediate, not scheduled)
  // Five lifecycle events in one tick — first schedules a timer, each subsequent
  // one clears the prior + reschedules (the debounce coalesce).
  for (let i = 0; i < 5; i++) {
    bus.emit({ type: "store_session_strip_changed", payload: { changeKind: "added" }, source: "test", ts: i });
  }
  // Four of the five timers were cleared; exactly one survives.
  assert.equal(sched.pending.filter((p) => !p.cleared).length, 1);
  assert.equal(getCalls(), before);          // nothing fetched yet (still debouncing)
  sched.flushTimers();
  await flush();
  assert.equal(getCalls(), before + 1);      // the burst collapsed to a single GET
});

test("unmount cancels a pending debounce timer (no fetch after teardown)", async () => {
  const sched = makeScheduler();
  const { renderer, bus, getCalls } = await setup({ sessions: RECIPIENTS }, { debounceMs: 250, sched });
  const before = getCalls();
  bus.emit({ type: "store_session_strip_changed", payload: { changeKind: "added" }, source: "test", ts: 0 });
  assert.equal(sched.pending.filter((p) => !p.cleared).length, 1);   // one armed
  renderer.unmount();
  assert.equal(sched.pending.filter((p) => !p.cleared).length, 0);   // cleared by unmount
  sched.flushTimers();   // even if something fired, the renderer is gone
  await flush();
  assert.equal(getCalls(), before);   // no post-teardown fetch
});

test("production defaults: a rapid burst clears the prior real timer (default timer wiring)", async () => {
  const bus   = createEventBusForTesting();
  const store = createBroadcastStore({ storage: createStorageServiceForTesting() });
  const { api, getCalls } = makeApi({ sessions: RECIPIENTS });
  // Construct with NO recipientsRefreshDebounceMs / setTimeoutFn / clearTimeoutFn
  // overrides → exercises the production defaults (250 ms window +
  // globalThis.setTimeout / globalThis.clearTimeout closures).
  const renderer = createBroadcastCardRenderer( { eventBus: bus, store, api, recorder: new FakeRecorder(), getAuthToken: () => "tok" } );
  const root = document.createElement("div");
  document.body.appendChild(root);
  renderer.mount(root);
  await flush();
  const before = getCalls();   // 1 from the mount hydrate
  // Two events in one tick: the 2nd clears the 1st's real timer (default
  // clearTimeoutFn). Neither fires within a single flush (the 250 ms window
  // has not elapsed) — so the burst is still pending, no trailing fetch yet.
  bus.emit({ type: "store_session_strip_changed", payload: {}, source: "test", ts: 0 });
  bus.emit({ type: "store_session_strip_changed", payload: {}, source: "test", ts: 1 });
  await flush();
  assert.equal(getCalls(), before);   // still debouncing
  renderer.unmount();                 // cancels the pending real timer (clean teardown)
});

// --- Out-of-order response guard (last-request-wins token) ------------------

// Build an api whose GETs resolve/reject on demand so we can force out-of-order
// completion. gets[0] is the mount hydrate; gets[1] the next refresh, etc.
function makeDeferredApi(): {
  api  : BroadcastCardApiClient;
  gets : Array<{ resolve: (s: BroadcastRecipient[]) => void; reject: (e: unknown) => void }>;
} {
  const gets: Array<{ resolve: (s: BroadcastRecipient[]) => void; reject: (e: unknown) => void }> = [];
  const api: BroadcastCardApiClient = {
    get<T>(_path: string): Promise<T> {
      return new Promise<T>((res, rej) => {
        gets.push({ resolve: (s) => res({ sessions: s } as T), reject: (e) => rej(e) });
      });
    },
    broadcastToCcSessions(): Promise<BroadcastResult> { return Promise.resolve(RESULT_OK); },
  };
  return { api, gets };
}

async function deferredHarness(): Promise<{ root: HTMLElement; bus: EventBus; gets: ReturnType<typeof makeDeferredApi>["gets"] }> {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting();
  const store   = createBroadcastStore({ storage });
  const { api, gets } = makeDeferredApi();
  const renderer = createBroadcastCardRenderer({
    eventBus: bus, store, api, recorder: new FakeRecorder(), getAuthToken: () => "tok",
    recipientsRefreshDebounceMs: 0,
  });
  const root = document.createElement("div");
  document.body.appendChild(root);
  renderer.mount(root);   // performRefresh #1 → gets[0] pending (NOT awaited)
  return { root, bus, gets };
}

test("a stale (out-of-order) hydrate resolve does NOT clobber the freshest render", async () => {
  const { root, bus, gets } = await deferredHarness();
  // Refresh #2 (the ↻ button) starts while #1 is still in flight.
  $(root, "#broadcast-recipients-refresh").click();   // performRefresh #2 → gets[1] pending
  assert.equal(gets.length, 2);
  // Resolve the NEWER request first → it paints 2 recipients (3 chips w/ @all).
  gets[1].resolve(RECIPIENTS);
  await flush();
  assert.equal(chips(root).length, 3);
  // Now the OLDER request resolves with a DIFFERENT (1-recipient) list — its
  // paint must be dropped by the refresh-token guard.
  gets[0].resolve([{ session_id: "stale-only" }]);
  await flush();
  assert.equal(chips(root).length, 3);   // unchanged — stale resolve was guarded out
  assert.equal(root.querySelector(".broadcast-chip")?.textContent?.includes("stale-only"), false);
});

test("a stale (out-of-order) hydrate REJECTION does NOT paint an error over the fresh list", async () => {
  const { root, bus, gets } = await deferredHarness();
  $(root, "#broadcast-recipients-refresh").click();   // performRefresh #2 → gets[1]
  assert.equal(gets.length, 2);
  gets[1].resolve(RECIPIENTS);   // newer succeeds → list painted
  await flush();
  assert.equal(chips(root).length, 3);
  gets[0].reject(new Error("late failure"));   // older rejects AFTER → must be guarded
  await flush();
  assert.equal(root.querySelector(".broadcast-chip.no-recipients"), null);   // no error pill
  assert.equal(chips(root).length, 3);
});

// ---------------------------------------------------------------------------
// Chip → @mention injection
// ---------------------------------------------------------------------------

test("clicking a recipient chip injects @persona at the caret", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  const tib = chips(root).find((c) => c.textContent?.includes("Tiberius")) as HTMLElement;
  tib.click();
  assert.equal(ta(root).value, "@Tiberius ");
});

test("clicking @all injects @all", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  const all = chips(root).find((c) => c.textContent?.includes("@all")) as HTMLElement;
  all.click();
  assert.equal(ta(root).value, "@all ");
});

test("a chip with no data-token attribute is a no-op", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  const row = $(root, "#broadcast-recipients-row");
  const bad = document.createElement("button");
  bad.className = "broadcast-chip";   // NO data-token → getAttribute() returns null
  row.appendChild(bad);
  bad.click();
  assert.equal(ta(root).value, "");
});

test("chip fallbacks: a recipient with no persona fields renders session_id + default icon", async () => {
  const { root } = await setup({ sessions: [{ session_id: "s3" }] });
  const chip = chips(root).find((c) => c.textContent?.includes("s3")) as HTMLElement;
  assert.notEqual(chip, null);
  assert.ok(chip.textContent?.includes("👤"));
  assert.equal(chip.style.borderColor, "");   // no persona_color → no border
});

test("chip ultimate fallback: an empty session_id renders the 'session' label", async () => {
  const { root } = await setup({ sessions: [{ session_id: "" }] });
  const chip = chips(root).find((c) => c.textContent?.includes("session")) as HTMLElement;
  assert.notEqual(chip, undefined);
});

// ---------------------------------------------------------------------------
// Send-button enablement + collapse
// ---------------------------------------------------------------------------

test("send button enables only with body AND recipients", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  assert.equal(sendBtn(root).disabled, true);     // empty body
  typeMessage(root, "hello");
  assert.equal(sendBtn(root).disabled, false);    // body + recipients
  typeMessage(root, "   ");
  assert.equal(sendBtn(root).disabled, true);     // whitespace-only body
});

test("send button stays disabled with body but no recipients", async () => {
  const { root } = await setup({ sessions: [] });
  typeMessage(root, "hello");
  assert.equal(sendBtn(root).disabled, true);
  assert.equal(sendBtn(root).title, "no active sessions to broadcast to");
});

test("header click toggles the card open/closed + persists", async () => {
  const { root, store } = await setup();
  assert.equal(store.isCardOpen(), true);
  $(root, "#broadcast-submit-header").click();
  assert.equal(store.isCardOpen(), false);
  assert.equal($(root, "#broadcast-submit-card").getAttribute("data-card-open"), "false");
  assert.equal($(root, "#broadcast-submit-toggle").textContent, "▶");
  $(root, "#broadcast-submit-header").click();
  assert.equal(store.isCardOpen(), true);
  assert.equal($(root, "#broadcast-submit-toggle").textContent, "▼");
});

// ---------------------------------------------------------------------------
// 🎤 STT
// ---------------------------------------------------------------------------

test("mic click starts recording (mic class + stash) and onComplete splices", async () => {
  const { root, recorder } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "pre ");
  ta(root).setSelectionRange(4, 4);   // caret at end
  $(root, "#broadcast-stt-button").click();
  assert.notEqual(recorder.lastStart, null);
  assert.equal($(root, "#broadcast-stt-button").classList.contains("recording"), true);
  // Drive the transcription completion.
  recorder.lastStart?.onComplete?.("dictated", new Blob());
  assert.equal(ta(root).value, "pre dictated");
  assert.equal($(root, "#broadcast-stt-button").classList.contains("recording"), false);
});

test("onComplete with an undefined transcription splices an empty string", async () => {
  const { root, recorder } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "kept");
  ta(root).setSelectionRange(4, 4);
  $(root, "#broadcast-stt-button").click();
  recorder.lastStart?.onComplete?.(undefined as unknown as string, new Blob());
  assert.equal(ta(root).value, "kept");
});

test("mic click while recording stops it", async () => {
  const { root, recorder } = await setup({ sessions: RECIPIENTS });
  $(root, "#broadcast-stt-button").click();   // start
  $(root, "#broadcast-stt-button").click();   // stop
  assert.deepEqual(recorder.stopped, ["broadcast"]);
});

test("onComplete with a null caret appends (no setSelectionRange)", async () => {
  const { root, recorder } = await setup({ sessions: RECIPIENTS });
  const t = ta(root);
  t.value = "base";
  // Force the no-caret path: a real element can expose a null selectionStart
  // (the legacy "source exposed no caret" append case). happy-dom coerces a
  // plain assignment back to 0, so redefine the accessor to return null.
  Object.defineProperty(t, "selectionStart", { value: null, configurable: true });
  Object.defineProperty(t, "selectionEnd", { value: null, configurable: true });
  $(root, "#broadcast-stt-button").click();
  recorder.lastStart?.onComplete?.("X", new Blob());
  assert.equal(t.value, "baseX");
});

test("onError surfaces a status message + clears the recording class", async () => {
  const { root, recorder } = await setup({ sessions: RECIPIENTS });
  $(root, "#broadcast-stt-button").click();
  recorder.lastStart?.onError?.({ type: "permission_denied", message: "mic blocked", originalError: null });
  assert.ok($(root, "#broadcast-submit-status").textContent?.includes("recording failed: mic blocked"));
  assert.equal($(root, "#broadcast-stt-button").classList.contains("recording"), false);
});

test("onCancel (ESC) resets the stuck mic state, leaving the textarea untouched", async () => {
  const { root, recorder } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "draft");
  $(root, "#broadcast-stt-button").click();
  assert.equal($(root, "#broadcast-stt-button").classList.contains("recording"), true);
  // AudioRecorder.cancel() fires neither onComplete nor onError — the new
  // onCancel hook must clear the recording class so the mic doesn't stay red.
  recorder.lastStart?.onCancel?.();
  assert.equal($(root, "#broadcast-stt-button").classList.contains("recording"), false);
  assert.equal(ta(root).value, "draft");   // cancel discards only the in-flight take
});

// ---------------------------------------------------------------------------
// Confirm modal + send
// ---------------------------------------------------------------------------

test("clicking a disabled send button does NOT open the modal", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  sendBtn(root).click();   // disabled (empty body)
  assert.equal(document.getElementById("broadcast-confirm-modal-overlay"), null);
});

test("send → confirm modal opens, Cancel removes it", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "hello world");
  sendBtn(root).click();
  const overlay = document.getElementById("broadcast-confirm-modal-overlay");
  assert.notEqual(overlay, null);
  assert.ok(overlay?.querySelector(".modal-preview")?.textContent?.includes("hello world"));
  (overlay?.querySelector(".btn-cancel") as HTMLButtonElement).click();
  assert.equal(document.getElementById("broadcast-confirm-modal-overlay"), null);
});

test("opening the confirm modal twice leaves only one overlay (no leak)", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "hi");
  sendBtn(root).click();
  sendBtn(root).click();   // a second open must drop the first overlay
  assert.equal(document.querySelectorAll("#broadcast-confirm-modal-overlay").length, 1);
});

test("modal backdrop click closes it; inner click does not", async () => {
  const { root } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "hi");
  sendBtn(root).click();
  const overlay = document.getElementById("broadcast-confirm-modal-overlay") as HTMLElement;
  // Click on the inner modal (target !== overlay) — stays open.
  (overlay.querySelector("#broadcast-confirm-modal") as HTMLElement).click();
  assert.notEqual(document.getElementById("broadcast-confirm-modal-overlay"), null);
  // Click on the overlay backdrop itself — closes.
  overlay.click();
  assert.equal(document.getElementById("broadcast-confirm-modal-overlay"), null);
});

test("confirm modal: single field-less recipient → '1 session' heading + session_id chip", async () => {
  const { root } = await setup({ sessions: [{ session_id: "s9" }] });
  typeMessage(root, "solo");
  sendBtn(root).click();
  const overlay = document.getElementById("broadcast-confirm-modal-overlay") as HTMLElement;
  assert.ok(overlay.querySelector("h4")?.textContent?.includes("1 session?"));
  const modalChip = overlay.querySelector(".modal-recipients .broadcast-chip");
  assert.ok(modalChip?.textContent?.includes("s9"));
  assert.ok(modalChip?.textContent?.includes("👤"));
});

test("confirm modal: an empty session_id falls back to the 'session' chip label", async () => {
  const { root } = await setup({ sessions: [{ session_id: "" }] });
  typeMessage(root, "x");
  sendBtn(root).click();
  const overlay = document.getElementById("broadcast-confirm-modal-overlay") as HTMLElement;
  const modalChip = overlay.querySelector(".modal-recipients .broadcast-chip");
  assert.ok(modalChip?.textContent?.includes("session"));
});

test("Confirm + Send posts the broadcast, clears the textarea, reflects recipients", async () => {
  const { root, sent } = await setup({ sessions: RECIPIENTS, sendResult: RESULT_OK });
  typeMessage(root, "ship it");
  sendBtn(root).click();
  const confirm = document.querySelector('[data-testid="multiplexer-broadcast-confirm-btn"]') as HTMLButtonElement;
  confirm.click();
  await flush();
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0], { message: "ship it", require_ack: true, include_originator: true });
  assert.equal(ta(root).value, "");
  assert.equal(document.getElementById("broadcast-confirm-modal-overlay"), null);
  assert.ok($(root, "#broadcast-submit-status").textContent?.includes("sent to 2 sessions"));
});

test("send status reflects a single recipient + filtered_out receipts", async () => {
  const result: BroadcastResult = {
    broadcast_id      : "11111111-2222-4333-8444-555566667777",
    recipients        : 1,
    failed_recipients : [],
    filtered_out      : [{ session_id: "deadbeefxxxx", reason: "stale_bridge_mtime" }],
    status            : "ok",
  };
  const { root } = await setup({ sessions: RECIPIENTS, sendResult: result });
  typeMessage(root, "one");
  sendBtn(root).click();
  (document.querySelector('[data-testid="multiplexer-broadcast-confirm-btn"]') as HTMLButtonElement).click();
  await flush();
  const status = $(root, "#broadcast-submit-status").textContent ?? "";
  assert.ok(status.includes("sent to 1 session"));
  assert.ok(status.includes("1 filtered out"));
  assert.ok(status.includes("stale_bridge_mtime: deadbeef"));
});

test("send failure re-enables Confirm + shows the error status (Error)", async () => {
  const { root } = await setup({ sessions: RECIPIENTS, sendResult: new Error("429 rate limited") });
  typeMessage(root, "boom");
  sendBtn(root).click();
  const confirm = document.querySelector('[data-testid="multiplexer-broadcast-confirm-btn"]') as HTMLButtonElement;
  confirm.click();
  await flush();
  assert.equal(confirm.disabled, false);
  assert.equal(confirm.textContent, "Confirm + Send");
  assert.notEqual(document.getElementById("broadcast-confirm-modal-overlay"), null);   // modal stays for retry
  assert.ok($(root, "#broadcast-submit-status").textContent?.includes("send failed: 429 rate limited"));
});

test("send failure with a non-Error rejection still surfaces a string status", async () => {
  const { root } = await setup({ sessions: RECIPIENTS, sendResult: "weird-string-error" });
  typeMessage(root, "boom");
  sendBtn(root).click();
  (document.querySelector('[data-testid="multiplexer-broadcast-confirm-btn"]') as HTMLButtonElement).click();
  await flush();
  assert.ok($(root, "#broadcast-submit-status").textContent?.includes("send failed: weird-string-error"));
});

test("unmount removes an open modal", async () => {
  const { renderer, root } = await setup({ sessions: RECIPIENTS });
  typeMessage(root, "hi");
  sendBtn(root).click();
  assert.notEqual(document.getElementById("broadcast-confirm-modal-overlay"), null);
  renderer.unmount();
  assert.equal(document.getElementById("broadcast-confirm-modal-overlay"), null);
});
