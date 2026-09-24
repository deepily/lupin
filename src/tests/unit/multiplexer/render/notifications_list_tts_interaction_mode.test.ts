// PARITY-CLAIM: A-2 #4
// Parity A-2 #4 — the TTS interaction mode reaches the multiplexer, LATE, and the
// conversation-mode buttons repaint.
//
// The same shape as row 0e5bfa0e's app-timezone wire, deliberately: the value lives in
// /api/config/client (system.py:855), legacy reads it from there
// (`fetchClientConfig`, notifications.js:901), boot is SYNCHRONOUS and that fetch is not — so the renderer
// has to take the value late, and taking it is only half the job.
//
// 🔴 THREE CACHES EXIST TO AVOID RE-RENDERING A CARD WHOSE INPUTS HAVE NOT MOVED, and
// the mode is not one of their inputs. A setter that only assigned the field would
// leave `cardInputs` reporting "unchanged", `cardSignatures` matching the stale markup
// and `historyCache` replaying old fragments: the mode adopted, the setter returning
// cleanly, and NOTHING on screen moving. A solo host would show chorus glyphs for the
// life of the page with no error and no failed fetch to notice.
//
// ⇒ So every assertion below reads the RENDERED GLYPH, never the stored value.
//
// WHY THE WRONG GLYPH MATTERS. The two sets describe different questions. In chorus the
// button asks "does this session speak aloud?"; in solo it asks "does this session HOLD
// the line?" — a monopoly other sessions queue behind. The tooltip differs the same way.
//
// ⚠️ THE SENDER HERE CARRIES A `#`. The voice-input row — and therefore the
// conversation-mode button — renders only for CC senders (legacy parity), so the
// app-timezone sibling's `sess_42` fixture would give these tests nothing to assert on
// and they would pass by finding null. The instrument check below exists for that.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/notifications_list_tts_interaction_mode.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createNotificationsListRenderer,
  type NotificationsListRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render";
import type { Notification, SenderRecord } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
});

const TS        = Date.UTC(2026, 4, 5, 4, 0);
const CC_SENDER = "claude.code@lupin.deepily.ai#parity01";

interface Setup {
  sCards   : HTMLElement;
  renderer : NotificationsListRenderer;
}

function setup(): Setup {
  const bus     = createEventBusForTesting();
  const notifs  : Notification[] = [
    { id_hash: "n1", ts: TS, sender_id: CC_SENDER, message: "hi", action_required: false },
  ];
  const senders : SenderRecord[] = [
    { sender_id: CC_SENDER, display_name: "S", last_active_ts: TS, unread_count: 1,
      conversation_mode_active: true },
  ];

  const renderer = createNotificationsListRenderer({
    eventBus : bus,
    stores   : { notifications: { list: () => notifs }, senders: { list: () => senders } },
  });

  const root      = document.createElement("section");
  const arSection = document.createElement("div");
  arSection.id    = "action-required-section";
  const sCards    = document.createElement("div");
  sCards.id       = "sender-cards-container";
  root.appendChild(arSection);
  root.appendChild(sCards);
  renderer.mount(root);

  return { sCards, renderer };
}

/** The conversation-mode button's glyph as an operator sees it, or null if absent. */
function glyph(s: Setup): string | null {
  const btn = s.sCards.querySelector(".sender-conversation-mode-btn");
  return btn === null ? null : btn.textContent;
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

// ===========================================================================

test("instrument check: the fixture really renders a conversation-mode button", () => {
  // Without this, every assertion below could be comparing null to null and passing.
  const s = setup();
  assert.notEqual(glyph(s), null, "no conversation-mode button rendered — the fixture is not a CC sender");
  s.renderer.unmount();
});

test("before the config answers, the card paints CHORUS — legacy's `|| 'chorus'` default", () => {
  const s = setup();
  assert.equal(glyph(s), "🔊", "the page painted something other than the chorus default");
  s.renderer.unmount();
});

test("🔴 a LATE solo mode actually repaints the button — not just adopts the value", async () => {
  // THE TEST THIS FILE EXISTS FOR. It fails against a setter that assigns the field and
  // skips the cache drop, which is the version that looks correct and does nothing.
  const s = setup();
  assert.equal(glyph(s), "🔊", "precondition: chorus before the handover");

  s.renderer.setTtsInteractionMode("solo");
  await settle();

  assert.equal(glyph(s), "📞", "the mode was adopted but the card never repainted — the caches held the stale glyph");
  s.renderer.unmount();
});

test("the handover is reversible — solo back to chorus repaints too", async () => {
  // A cache drop that only ran on the first change would pass the test above and strand
  // every later change, which is harder to notice than never working at all.
  const s = setup();
  s.renderer.setTtsInteractionMode("solo");
  await settle();
  assert.equal(glyph(s), "📞", "precondition: solo landed");

  s.renderer.setTtsInteractionMode("chorus");
  await settle();
  assert.equal(glyph(s), "🔊", "a second change did not repaint");
  s.renderer.unmount();
});

test("an unchanged mode is a no-op — a refetch that changes nothing costs nothing", async () => {
  const s = setup();
  s.renderer.setTtsInteractionMode("solo");
  await settle();
  assert.equal(glyph(s), "📞");

  s.renderer.setTtsInteractionMode("solo");   // same value again
  await settle();
  assert.equal(glyph(s), "📞", "the glyph moved on a no-op handover");
  s.renderer.unmount();
});

test("undefined resets to the chorus default rather than sticking on solo", async () => {
  // A failed refetch hands over undefined. Sticking on solo would keep monopoly
  // iconography up on the strength of a config read that has since stopped answering.
  const s = setup();
  s.renderer.setTtsInteractionMode("solo");
  await settle();
  assert.equal(glyph(s), "📞", "precondition: solo landed");

  s.renderer.setTtsInteractionMode(undefined);
  await settle();
  assert.equal(glyph(s), "🔊", "undefined did not fall back to chorus");
  s.renderer.unmount();
});
