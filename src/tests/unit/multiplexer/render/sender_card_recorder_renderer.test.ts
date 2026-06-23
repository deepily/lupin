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

type StartStub = ( o: { onComplete?: ( t: string, b: Blob ) => void; onError?: ( e: { type: string; message: string; originalError: unknown } ) => void } ) => Promise<void>;

function stubStart( fn: StartStub ): () => void {
  const original = recordingManager.startRecording.bind(recordingManager);
  ( recordingManager as unknown as { startRecording: StartStub } ).startRecording = fn;
  return () => { ( recordingManager as unknown as { startRecording: typeof original } ).startRecording = original; };
}

function stubTranscription( text: string | undefined ): () => void {
  return stubStart( async (opts) => { opts.onComplete?.( text as string, new Blob() ); } );
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
  // No throw + no recording started; the POST itself is the smoke-tier path.
  conv(vi).click();
  assert.equal(recordingManager.getActiveContextId(), null);
});
