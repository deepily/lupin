// Multiplexer Phase 5 — senderCard template tests.
// AC5 floor: ≥3 tests.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderSenderCard, hexToRgbTriplet } from "../../../../lupin_app/static/js/multiplexer/render/templates/senderCard";
import type { SenderRecord, Notification, VoicePersona } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = {
    parse: (s: string) => `<p>${s}</p>`,
  };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = {
    sanitize: (s: string) => s,
  };
});

function makePersona(over: Partial<VoicePersona> = {}): VoicePersona {
  return {
    name     : "Tiberius",
    voice_id : "vid_42",
    icon     : "🦊",
    color    : "#ab1234",
    borrowed : false,
    ...over,
  };
}

function makeSender(over: Partial<SenderRecord> = {}): SenderRecord {
  return {
    sender_id                : "sess_42",
    display_name             : "Test Sender",
    last_active_ts           : Date.UTC(2026, 4, 5, 14, 7),
    unread_count             : 3,
    conversation_mode_active : false,
    ...over,
  };
}

function makeNotification(id: string, ts: number): Notification {
  return {
    id_hash         : id,
    ts,
    sender_id       : "sess_42",
    message         : `msg-${id}`,
    action_required : false,
  };
}

// ---------------------------------------------------------------------------

test("senderCard: data-id-hash matches sender_id (F12); legacy data-sender-id mirrored", () => {
  const card = renderSenderCard(makeSender(), [], { appTimezone: "UTC" });
  assert.equal(card.getAttribute("data-id-hash"), "sess_42");
  assert.equal(card.getAttribute("data-sender-id"), "sess_42");
  assert.ok(card.classList.contains("sender-card"));
});

test("senderCard: voice_persona color applied via style.setProperty (NOT inline style attr)", () => {
  const persona = makePersona({ color: "#ab1234", icon: "🦊" });
  const card = renderSenderCard(makeSender({ voice_persona: persona }), [], { appTimezone: "UTC" });
  assert.equal(card.style.getPropertyValue("--persona-color"), "#ab1234");
  // Phase 6c Node A Step A1: badge is now glyph-only (no inline name);
  // the name surfaces via the persona-popover modal triggered by popovertarget.
  const badge = card.querySelector(".sender-persona-badge");
  assert.notEqual(badge, null);
  assert.equal(badge!.textContent, "🦊");
  assert.equal(badge!.tagName.toLowerCase(), "button", "Phase 6c Node A: chip is now a <button> with popovertarget");
  assert.match(badge!.getAttribute("popovertarget") ?? "", /^persona-popover-sess_42/);
});

test("senderCard: groups notifications by date descending; multi-date produces multiple .date-accordion children", () => {
  const ts1 = Date.UTC(2026, 4, 5, 14, 0);   // 2026-05-05
  const ts2 = Date.UTC(2026, 4, 4, 14, 0);   // 2026-05-04
  const card = renderSenderCard(
    makeSender(),
    [ makeNotification("n1", ts1), makeNotification("n2", ts2) ],
    { appTimezone: "UTC" },
  );
  const dates = card.querySelectorAll(".date-accordion");
  assert.equal(dates.length, 2);
  assert.equal(dates[0]!.getAttribute("data-date-key"), "2026-05-05");   // newest first
  assert.equal(dates[1]!.getAttribute("data-date-key"), "2026-05-04");
});

test("senderCard: unread_count > 0 renders .sender-new-count badge with the number", () => {
  const card = renderSenderCard(makeSender({ unread_count: 7 }), [], { appTimezone: "UTC" });
  const badge = card.querySelector(".sender-new-count");
  assert.notEqual(badge, null);
  assert.equal(badge!.textContent, "7");
});

// ---------------------------------------------------------------------------
// Branch-coverage close-out tests (added 2026-05-06 for the 100% c8 mandate).
// ---------------------------------------------------------------------------

test("senderCard: unread_count === 0 renders no .sender-new-count badge", () => {
  const card = renderSenderCard(makeSender({ unread_count: 0 }), [], { appTimezone: "UTC" });
  assert.equal(card.querySelector(".sender-new-count"), null);
});

test("senderCard: borrowed persona gets the 'borrowed' class on .sender-persona-badge", () => {
  const card = renderSenderCard(
    makeSender({ voice_persona: makePersona({ borrowed: true }) }),
    [],
    { appTimezone: "UTC" },
  );
  const badge = card.querySelector(".sender-persona-badge");
  assert.notEqual(badge, null);
  assert.ok(badge!.classList.contains("borrowed"));
});

test("senderCard: non-borrowed persona omits the 'borrowed' class", () => {
  const card = renderSenderCard(
    makeSender({ voice_persona: makePersona({ borrowed: false }) }),
    [],
    { appTimezone: "UTC" },
  );
  const badge = card.querySelector(".sender-persona-badge");
  assert.notEqual(badge, null);
  assert.ok(!badge!.classList.contains("borrowed"));
});

test("senderCard: last_active_ts === 0 renders empty .sender-last-activity", () => {
  const card = renderSenderCard(makeSender({ last_active_ts: 0 }), [], { appTimezone: "UTC" });
  const lastEl = card.querySelector(".sender-last-activity");
  assert.notEqual(lastEl, null);
  assert.equal(lastEl!.textContent, "");
});

test("senderCard: empty display_name falls back to sender_id in header", () => {
  const card = renderSenderCard(
    makeSender({ display_name: "", sender_id: "sess_99" }),
    [],
    { appTimezone: "UTC" },
  );
  const nameEl = card.querySelector(".sender-display-name");
  assert.notEqual(nameEl, null);
  assert.equal(nameEl!.textContent, "sess_99");
});

// ---------------------------------------------------------------------------
// CSS-parity 2026-06-17: --persona-color-rgb is set alongside --persona-color
// so the header gradient, card box-shadow ring, and .sender-message.incoming
// gradient pick up the persona tint instead of the neutral fallback.
// ---------------------------------------------------------------------------

test("senderCard: valid persona color sets --persona-color-rgb triplet", () => {
  const card = renderSenderCard(
    makeSender({ voice_persona: makePersona({ color: "#ab1234" }) }),
    [],
    { appTimezone: "UTC" },
  );
  assert.equal(card.style.getPropertyValue("--persona-color"), "#ab1234");
  assert.equal(card.style.getPropertyValue("--persona-color-rgb"), "171, 18, 52");
});

test("senderCard: unparseable persona color skips --persona-color-rgb (hex var still set)", () => {
  const card = renderSenderCard(
    makeSender({ voice_persona: makePersona({ color: "tomato" }) }),
    [],
    { appTimezone: "UTC" },
  );
  // --persona-color still carries the raw value; the rgb triplet is omitted so
  // the stylesheet falls back to its neutral default.
  assert.equal(card.style.getPropertyValue("--persona-color"), "tomato");
  assert.equal(card.style.getPropertyValue("--persona-color-rgb"), "");
});

// hexToRgbTriplet — direct unit coverage of every branch.
test("hexToRgbTriplet: 6-digit hex with leading #", () => {
  assert.equal(hexToRgbTriplet("#FFD600"), "255, 214, 0");
});

test("hexToRgbTriplet: 6-digit hex without leading # (trimmed)", () => {
  assert.equal(hexToRgbTriplet("  00ff80 "), "0, 255, 128");
});

test("hexToRgbTriplet: 3-digit shorthand expands to full channels", () => {
  assert.equal(hexToRgbTriplet("#0f8"), "0, 255, 136");
});

test("hexToRgbTriplet: wrong-length input returns null", () => {
  assert.equal(hexToRgbTriplet("#abcd"), null);
});

test("hexToRgbTriplet: non-hex characters return null", () => {
  assert.equal(hexToRgbTriplet("#gggggg"), null);
});
