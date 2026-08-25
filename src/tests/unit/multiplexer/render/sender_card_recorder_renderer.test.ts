// Multiplexer F5 lane — SenderCardRecorderRenderer tests (MATCH-LEGACY rebuild).
//
// The voice-input ROW is now STATIC structure rendered by senderCard.ts; this
// renderer is the BEHAVIOR layer (delegated clicks + recording state on the
// existing row). These tests build the same static row senderCard.ts emits
// (mirrored in `makeVoiceInput`) and drive the mic / send / conv-mode controls.
// Network paths (send POST, conv-mode POST) are smoke-tier (c8-ignored in src);
// the DOM/state + F5 caret-splice paths are unit-covered here. 100% L/B/F.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSenderCardRecorderRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SenderCardRecorderRenderer";
import { recordingManager } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  if (globalThis.document !== undefined) {
    document.body.replaceChildren();
  }
});

// Build the static `.cc-voice-input` > `.cc-voice-input-row` row exactly as
// senderCard.ts emits it (conv-mode + mic + input + send). `active` reflects
// the conversation-mode is-active class senderCard.ts derives.
function makeVoiceInput( senderId: string, opts: { active?: boolean; withInput?: boolean } = {} ): HTMLElement {
  const sessionHash = senderId.includes("#") ? senderId.split("#")[1]! : senderId;
  const active      = opts.active ?? false;
  const withInput   = opts.withInput ?? true;
  const vi = document.createElement("div");
  vi.className = "cc-voice-input";
  vi.setAttribute("data-session-hash", sessionHash);
  vi.setAttribute("data-sender-id", senderId);
  const convClass = active ? "sender-conversation-mode-btn is-active" : "sender-conversation-mode-btn";
  const inputHtml = withInput
    ? `<input type="text" class="cc-session-msg-input" id="cc-session-input-${sessionHash}" />`
    : "";
  vi.innerHTML = `
    <div class="cc-voice-input-row">
      <button type="button" class="${convClass}" data-session-id="${sessionHash}" title="t">${active ? "🔊" : "🤭"}</button>
      <button type="button" class="stt-button cc-session-stt" id="cc-session-stt-${sessionHash}" title="t">🎤</button>
      ${inputHtml}
      <button type="button" class="response-submit-button cc-session-send" id="cc-session-send-${sessionHash}">Send</button>
    </div>`;
  return vi;
}

function makeCard( senderId: string, opts: { active?: boolean; withInput?: boolean } = {} ): HTMLElement {
  const card = document.createElement("div");
  card.className = "sender-card";
  card.setAttribute("data-sender-id", senderId);
  card.appendChild( makeVoiceInput( senderId, opts ) );
  return card;
}

function makeRootWithCards( senderIds: string[] ): HTMLElement {
  const root = document.createElement("div");
  root.id = "sender-cards-container";
  for (const id of senderIds) root.appendChild( makeCard( id ) );
  document.body.appendChild(root);
  return root;
}

function mic( vi: Element ): HTMLButtonElement   { return vi.querySelector(".cc-session-stt")  as HTMLButtonElement; }
function send( vi: Element ): HTMLButtonElement  { return vi.querySelector(".cc-session-send") as HTMLButtonElement; }
function conv( vi: Element ): HTMLButtonElement  { return vi.querySelector(".sender-conversation-mode-btn") as HTMLButtonElement; }
function input( vi: Element ): HTMLInputElement  { return vi.querySelector(".cc-session-msg-input") as HTMLInputElement; }

type StartStub = ( o: { onComplete?: ( t: string, b: Blob ) => void; onError?: ( e: { type: string; message: string; originalError: unknown } ) => void; onCancel?: () => void } ) => Promise<void>;

function stubStart( fn: StartStub ): () => void {
  const original = recordingManager.startRecording.bind(recordingManager);
  ( recordingManager as unknown as { startRecording: StartStub } ).startRecording = fn;
  return () => { ( recordingManager as unknown as { startRecording: typeof original } ).startRecording = original; };
}

function stubTranscription( text: string | undefined ): () => void {
  return stubStart( async (opts) => { opts.onComplete?.( text as string, new Blob() ); } );
}

// global.fetch stub (peer pattern — JobsPaneRenderer / ApiClient tests stub
// globalThis.fetch the same way). Returns a restore fn; ALWAYS restore in a
// finally so a stub never leaks into the next test.
type FetchStub = ( input: string, init?: RequestInit ) => Promise<Response>;

function stubFetch( fn: FetchStub ): () => void {
  const original = ( globalThis as { fetch?: unknown } ).fetch;
  ( globalThis as unknown as { fetch: FetchStub } ).fetch = fn;
  return () => { ( globalThis as unknown as { fetch: unknown } ).fetch = original; };
}

// Minimal Response stand-in carrying only the fields the renderer reads
// (ok / status / text). `text` defaults to resolving "" — pass a REJECTING impl
// to exercise the `.text().catch(() => "")` arm (→ "" → "HTTP <status>").
function fakeResp( opts: { ok: boolean; status?: number; text?: () => Promise<string> } ): Response {
  return {
    ok     : opts.ok,
    status : opts.status ?? ( opts.ok ? 200 : 500 ),
    text   : opts.text ?? ( async () => "" ),
  } as unknown as Response;
}

// Drain the microtask queue so a fire-and-forget `void this.handle*Click()` (the
// onClick delegate does not await the network handlers) settles before asserts.
function flush(): Promise<void> {
  return new Promise( res => setTimeout( res, 0 ) );
}

// ---------------------------------------------------------------------------
// Mount / lifecycle
// ---------------------------------------------------------------------------

test("mount sets data-recorder-state='idle' on every static row", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc", "user@x#def" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  for (const vi of root.querySelectorAll(".cc-voice-input")) {
    assert.equal(vi.getAttribute("data-recorder-state"), "idle");
  }
});

test("mount leaves the static row's controls in place (mic / input / send / conv-mode)", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  assert.notEqual(mic(vi), null);
  assert.notEqual(input(vi), null);
  assert.notEqual(send(vi), null);
  assert.notEqual(conv(vi), null);
});

test("double mount throws", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  assert.throws(() => r.mount(root), /already mounted/);
});

test("unmount removes click handler and clears state", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  r.unmount();
  // After unmount, clicking the mic has no effect (renderer detached).
  mic( root.querySelector(".cc-voice-input")! ).click();
  assert.equal(root.querySelector(".cc-voice-input")!.getAttribute("data-recorder-state"), "idle");
});

test("forceRenderForTesting re-applies idle state on all rows", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  root.querySelector(".cc-voice-input")!.removeAttribute("data-recorder-state");
  r.forceRenderForTesting();
  assert.equal(root.querySelector(".cc-voice-input")!.getAttribute("data-recorder-state"), "idle");
});

// ---------------------------------------------------------------------------
// Click delegation — no-op + each control
// ---------------------------------------------------------------------------

test("click outside the three controls is a no-op", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  (root.querySelector(".sender-card") as HTMLElement).click();
  assert.equal(root.querySelector(".cc-voice-input")!.getAttribute("data-recorder-state"), "idle");
});

test("mic click with empty data-session-hash is ignored (early return)", () => {
  const bus  = createEventBusForTesting();
  const root = document.createElement("div");
  root.id = "sender-cards-container";
  const card = document.createElement("div");
  card.className = "sender-card";
  const vi = makeVoiceInput("user@x#abc");
  vi.removeAttribute("data-session-hash");   // force the empty-hash early return
  card.appendChild(vi);
  root.appendChild(card);
  document.body.appendChild(root);

  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  mic(vi).click();   // sessionHash "" → early return, no recording started
  assert.equal(recordingManager.getActiveContextId(), null);
});

// ---------------------------------------------------------------------------
// Mic — record → onComplete (F5 splice) + onError
// ---------------------------------------------------------------------------

test("mic click → onComplete splices the transcription into the input + idle", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  const restore = stubTranscription("hello world");
  try { mic(vi).click(); } finally { restore(); }

  assert.equal(vi.getAttribute("data-recorder-state"), "idle");
  assert.equal(input(vi).value, "hello world");
  assert.equal(mic(vi).classList.contains("recording"), false);
});

test("mic click → onComplete with undefined transcription leaves the input empty", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  const restore = stubTranscription(undefined);
  try { mic(vi).click(); } finally { restore(); }

  assert.equal(input(vi).value, "");
  assert.equal(vi.getAttribute("data-recorder-state"), "idle");
});

test("mic click → onError reverts to idle and renders the error", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  const restore = stubStart( async (opts) => { opts.onError?.({ type: "permission_denied", message: "mic blocked", originalError: null }); } );
  try { mic(vi).click(); } finally { restore(); }

  assert.equal(vi.getAttribute("data-recorder-state"), "idle");
  assert.equal(mic(vi).classList.contains("recording"), false);
  const err = vi.querySelector(".cc-voice-input-error");
  assert.notEqual(err, null);
  assert.match(err!.textContent ?? "", /mic blocked/);
});

test("recordingManager onCancel resets the mic row to idle and preserves the pre-record text", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  // The user has a draft in the input, starts a record (stash captures it), then
  // cancels (ESC) — AudioRecorder.cancel() fires neither onComplete nor onError,
  // so without the onCancel hook the mic would stay stuck red. Capture the opts
  // and drive onCancel directly (the real cancel path is the smoke tier).
  input(vi).value = "draft note";
  let captured: { onCancel?: () => void } | null = null;
  const restore = stubStart( async (opts) => { captured = opts; } );
  try { mic(vi).click(); } finally { restore(); }
  assert.equal(vi.getAttribute("data-recorder-state"), "recording");
  assert.equal(mic(vi).classList.contains("recording"), true);

  captured!.onCancel!();
  assert.equal(vi.getAttribute("data-recorder-state"), "idle");
  assert.equal(mic(vi).classList.contains("recording"), false);
  assert.equal(input(vi).value, "draft note");   // DOM input untouched by cancel

  // The draft survives a card re-paint: reapplyVoiceInput restores states.value
  // (set from the pre-record stash) onto the row.
  input(vi).value = "clobbered";
  bus.emit({ type: "store_senders_changed", payload: {}, source: "test", ts: 3 });
  assert.equal(input(vi).value, "draft note");
});

test("recording state persists across a re-paint (store_senders_changed) — mic stays 'recording'", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  // Start a record that never completes (stub resolves without onComplete) →
  // state stays recording:true.
  const restore = stubStart( async () => { /* no callback */ } );
  try { mic(vi).click(); } finally { restore(); }
  assert.equal(vi.getAttribute("data-recorder-state"), "recording");
  assert.equal(mic(vi).classList.contains("recording"), true);

  // Simulate the card replace by re-emitting store_senders_changed; the SAME
  // (still-mounted) row must re-show the recording state from the states Map.
  vi.removeAttribute("data-recorder-state");
  mic(vi).classList.remove("recording");
  bus.emit({ type: "store_senders_changed", payload: {}, source: "test", ts: 1 });
  assert.equal(vi.getAttribute("data-recorder-state"), "recording");
  assert.equal(mic(vi).classList.contains("recording"), true);
});

test("a completed transcription is restored onto a re-created row via store_senders_changed", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  let vi = root.querySelector(".cc-voice-input")!;

  const restore = stubTranscription("persisted text");
  try { mic(vi).click(); } finally { restore(); }
  assert.equal(input(vi).value, "persisted text");

  // Replace the card (as NotificationsListRenderer does) with a fresh empty row,
  // then emit store_senders_changed: the recorder restores the input value.
  const freshCard = makeCard("user@x#abc");
  root.querySelector(".sender-card")!.replaceWith(freshCard);
  bus.emit({ type: "store_senders_changed", payload: {}, source: "test", ts: 2 });
  vi = root.querySelector(".cc-voice-input")!;
  assert.equal(input(vi).value, "persisted text");
});

// ---------------------------------------------------------------------------
// F5 caret-splice (insert-at-caret on re-record) — the folded WP6 contract
// ---------------------------------------------------------------------------

test("F5: re-record splices the new transcription at the caret, preserving edits", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#wp6" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  // First record fills the input.
  let restore = stubTranscription("first take");
  try { mic(vi).click(); } finally { restore(); }
  assert.equal(input(vi).value, "first take");

  // User edits + parks the caret after "edited " (index 7).
  input(vi).value = "edited first take";
  input(vi).focus();
  input(vi).setSelectionRange(7, 7);

  restore = stubTranscription("NEW ");
  try { mic(vi).click(); } finally { restore(); }

  assert.equal(input(vi).value, "edited NEW first take", "re-record caret-splices, never clobbers");
  assert.equal(input(vi).selectionStart, 7 + "NEW ".length, "caret lands after inserted text");
});

test("F5: re-record replaces ONLY a highlighted range", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#wp6" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  let restore = stubTranscription("Hello cruel world");
  try { mic(vi).click(); } finally { restore(); }

  input(vi).focus();
  input(vi).setSelectionRange(6, 11);   // select "cruel"

  restore = stubTranscription("brave");
  try { mic(vi).click(); } finally { restore(); }

  assert.equal(input(vi).value, "Hello brave world");
  assert.equal(input(vi).selectionStart, 6 + "brave".length);
});

test("F5: an errored re-record drops the stash (next record is a clean snapshot)", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#wp6" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;

  let restore = stubTranscription("first take");
  try { mic(vi).click(); } finally { restore(); }

  restore = stubStart( async (opts) => { opts.onError?.({ type: "x", message: "mic gone", originalError: null }); } );
  try { mic(vi).click(); } finally { restore(); }
  assert.equal(vi.getAttribute("data-recorder-state"), "idle");

  // After the error the input still holds the user text; a fresh record splices
  // the new transcription at the current caret (end), not from a stale stash.
  input(vi).focus();
  input(vi).setSelectionRange(input(vi).value.length, input(vi).value.length);
  restore = stubTranscription(" appended");
  try { mic(vi).click(); } finally { restore(); }
  assert.equal(input(vi).value, "first take appended");
});

// ---------------------------------------------------------------------------
// Send — validation surfaces (network path is smoke-tier)
// ---------------------------------------------------------------------------

test("send with a malformed sender_id (no '#') renders an error", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "malformed-no-hash" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  send(vi).click();
  await new Promise(res => setTimeout(res, 0));
  const err = vi.querySelector(".cc-voice-input-error");
  assert.notEqual(err, null);
  assert.match(err!.textContent ?? "", /malformed/i);
});

test("send with an empty message renders 'Message is empty.'", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  input(vi).value = "   ";   // whitespace-only trims to empty
  send(vi).click();
  await new Promise(res => setTimeout(res, 0));
  const err = vi.querySelector(".cc-voice-input-error");
  assert.notEqual(err, null);
  assert.match(err!.textContent ?? "", /empty/i);
});

// ---------------------------------------------------------------------------
// Conversation-mode toggle — delegation reaches the handler (POST is smoke-tier)
// ---------------------------------------------------------------------------

test("conv-mode click is routed to the handler (delegation branch)", () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  // Delegation only: routed to the handler, no recording started. The POST
  // shape + outcomes are covered by the conv-mode network tests below.
  conv(vi).click();
  assert.equal(recordingManager.getActiveContextId(), null);
});

// ---------------------------------------------------------------------------
// Send — network paths (global.fetch stubbed). These exercise the logic the
// prior whole-method c8-ignore masked: success / !resp.ok (with + without a
// body) / network rejection / token ±.
// ---------------------------------------------------------------------------

test("send success POSTs /api/notify with the legacy query shape + Bearer header, then clears the input", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x", getAuthToken: () => "tok123" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  input(vi).value = "hello team";

  let captured: { url: string; init?: RequestInit } | null = null;
  const restore = stubFetch( async (url, init) => { captured = { url, init }; return fakeResp({ ok: true }); } );
  try { send(vi).click(); await flush(); } finally { restore(); }

  assert.notEqual(captured, null);
  assert.match(captured!.url, /^\/api\/notify\?/);
  const qs = new URLSearchParams(captured!.url.split("?")[1] ?? "");
  assert.equal(qs.get("type"),        "user_initiated_message");
  assert.equal(qs.get("message"),     "hello team");
  assert.equal(qs.get("target_user"), "user@x");
  assert.equal(qs.get("sender_id"),   "me@x");
  assert.equal(qs.get("job_id"),      "abc");
  assert.equal(qs.get("priority"),    "medium");
  assert.equal(captured!.init?.method, "POST");
  assert.equal((captured!.init?.headers as Record<string, string>)["Authorization"], "Bearer tok123");
  assert.equal(input(vi).value, "");
  assert.ok( vi.querySelector(".cc-voice-input-error") === null );
});

test("send failure (!resp.ok) with a body surfaces the server error; no Bearer header when token absent; input retained", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });   // no getAuthToken → token null
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  input(vi).value = "boom";

  let captured: { init?: RequestInit } | null = null;
  const restore = stubFetch( async (_url, init) => { captured = { init }; return fakeResp({ ok: false, status: 500, text: async () => "server exploded" }); } );
  try { send(vi).click(); await flush(); } finally { restore(); }

  const err = vi.querySelector(".cc-voice-input-error");
  assert.notEqual(err, null);
  assert.match(err!.textContent ?? "", /server exploded/);
  assert.equal((captured!.init?.headers as Record<string, string>)["Authorization"], undefined);
  assert.equal(input(vi).value, "boom", "input is not cleared on failure");
});

test("send failure with no body falls back to 'HTTP <status>' (exercises the .text() catch arm)", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  input(vi).value = "boom";

  const restore = stubFetch( async () => fakeResp({ ok: false, status: 503, text: async () => { throw new Error("no body"); } }) );
  try { send(vi).click(); await flush(); } finally { restore(); }

  assert.match(vi.querySelector(".cc-voice-input-error")!.textContent ?? "", /HTTP 503/);
});

test("send network rejection is caught and surfaced", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  input(vi).value = "boom";

  const restore = stubFetch( async () => { throw new Error("offline"); } );
  try { send(vi).click(); await flush(); } finally { restore(); }

  assert.match(vi.querySelector(".cc-voice-input-error")!.textContent ?? "", /offline/);
});

// Build a one-card root, remove a data- attribute, return the row — for the
// missing-attribute early-return guards (mirrors the mic empty-hash test).
function mountRowMissing( attr: string ): HTMLElement {
  const bus  = createEventBusForTesting();
  const root = document.createElement("div");
  root.id = "sender-cards-container";
  const card = document.createElement("div");
  card.className = "sender-card";
  const vi = makeVoiceInput("user@x#abc");
  vi.removeAttribute(attr);
  card.appendChild(vi);
  root.appendChild(card);
  document.body.appendChild(root);
  createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" }).mount(root);
  return vi;
}

test("send with an empty data-session-hash early-returns (no POST, no error)", async () => {
  const vi = mountRowMissing("data-session-hash");
  input(vi).value = "hi";
  let called = false;
  const restore = stubFetch( async () => { called = true; return fakeResp({ ok: true }); } );
  try { send(vi).click(); await flush(); } finally { restore(); }
  assert.equal(called, false);
  assert.ok( vi.querySelector(".cc-voice-input-error") === null );
});

test("send with an empty data-sender-id early-returns (no POST, no error)", async () => {
  const vi = mountRowMissing("data-sender-id");
  input(vi).value = "hi";
  let called = false;
  const restore = stubFetch( async () => { called = true; return fakeResp({ ok: true }); } );
  try { send(vi).click(); await flush(); } finally { restore(); }
  assert.equal(called, false);
  assert.ok( vi.querySelector(".cc-voice-input-error") === null );
});

test("renderError keeps a single error element per row (replaces a prior one)", async () => {
  const bus  = createEventBusForTesting();
  const root = makeRootWithCards([ "user@x#abc" ]);
  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);
  const vi = root.querySelector(".cc-voice-input")!;
  // Two empty-message sends → two renderError calls; the second removes the
  // first (covers the `prior !== null` replace branch).
  send(vi).click(); await flush();
  send(vi).click(); await flush();
  assert.equal(vi.querySelectorAll(".cc-voice-input-error").length, 1);
});

// ---------------------------------------------------------------------------
// Conversation-mode toggle — network paths (global.fetch stubbed): empty-hash
// guard / active T+F (POST body {on:!active}) / token ± / !resp.ok (with +
// without a body) / network rejection.
// ---------------------------------------------------------------------------

function mountConvCard( opts: { active: boolean; token?: string } ): { vi: HTMLElement } {
  const bus  = createEventBusForTesting();
  const root = document.createElement("div");
  root.id = "sender-cards-container";
  root.appendChild( makeCard("user@x#abc", { active: opts.active }) );
  document.body.appendChild(root);
  const r = createSenderCardRecorderRenderer({
    eventBus: bus, currentUserEmail: "me@x",
    ...(opts.token !== undefined ? { getAuthToken: () => opts.token! } : {}),
  });
  r.mount(root);
  return { vi: root.querySelector(".cc-voice-input") as HTMLElement };
}

test("conv-mode with empty data-session-hash is ignored (early return, no POST)", async () => {
  const bus  = createEventBusForTesting();
  const root = document.createElement("div");
  root.id = "sender-cards-container";
  const card = document.createElement("div");
  card.className = "sender-card";
  const vi = makeVoiceInput("user@x#abc");
  vi.removeAttribute("data-session-hash");   // force the empty-hash early return
  card.appendChild(vi);
  root.appendChild(card);
  document.body.appendChild(root);

  const r = createSenderCardRecorderRenderer({ eventBus: bus, currentUserEmail: "me@x" });
  r.mount(root);

  let called = false;
  const restore = stubFetch( async () => { called = true; return fakeResp({ ok: true }); } );
  try { conv(vi).click(); await flush(); } finally { restore(); }
  assert.equal(called, false, "no POST when the session hash is empty");
});

test("conv-mode (inactive) POSTs {on:true} to the legacy speakerphone endpoint with Bearer header", async () => {
  const { vi } = mountConvCard({ active: false, token: "tokC" });

  let captured: { url: string; init?: RequestInit } | null = null;
  const restore = stubFetch( async (url, init) => { captured = { url, init }; return fakeResp({ ok: true }); } );
  try { conv(vi).click(); await flush(); } finally { restore(); }

  assert.equal(captured!.url, "/api/cosa-voice/speakerphone/abc");
  assert.equal(captured!.init?.method, "POST");
  assert.equal(JSON.parse(captured!.init?.body as string).on, true);
  assert.equal((captured!.init?.headers as Record<string, string>)["Authorization"], "Bearer tokC");
  assert.ok( vi.querySelector(".cc-voice-input-error") === null );
});

test("conv-mode (active) POSTs {on:false}; no Bearer header when token absent", async () => {
  const { vi } = mountConvCard({ active: true });   // no token

  let captured: { init?: RequestInit } | null = null;
  const restore = stubFetch( async (_url, init) => { captured = { init }; return fakeResp({ ok: true }); } );
  try { conv(vi).click(); await flush(); } finally { restore(); }

  assert.equal(JSON.parse(captured!.init?.body as string).on, false);
  assert.equal((captured!.init?.headers as Record<string, string>)["Authorization"], undefined);
});

test("conv-mode failure (!resp.ok) with a body surfaces the server error", async () => {
  const { vi } = mountConvCard({ active: false });

  const restore = stubFetch( async () => fakeResp({ ok: false, status: 500, text: async () => "speakerphone down" }) );
  try { conv(vi).click(); await flush(); } finally { restore(); }

  assert.match(vi.querySelector(".cc-voice-input-error")!.textContent ?? "", /speakerphone down/);
});

test("conv-mode failure with no body falls back to 'HTTP <status>'", async () => {
  const { vi } = mountConvCard({ active: false });

  const restore = stubFetch( async () => fakeResp({ ok: false, status: 502, text: async () => { throw new Error("no body"); } }) );
  try { conv(vi).click(); await flush(); } finally { restore(); }

  assert.match(vi.querySelector(".cc-voice-input-error")!.textContent ?? "", /HTTP 502/);
});

test("conv-mode network rejection is caught and surfaced", async () => {
  const { vi } = mountConvCard({ active: false });

  const restore = stubFetch( async () => { throw new Error("conv offline"); } );
  try { conv(vi).click(); await flush(); } finally { restore(); }

  assert.match(vi.querySelector(".cc-voice-input-error")!.textContent ?? "", /conv offline/);
});
