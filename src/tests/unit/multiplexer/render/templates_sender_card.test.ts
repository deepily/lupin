// Multiplexer Phase 5 — senderCard template tests.
// AC5 floor: ≥3 tests.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderSenderCard, hexToRgbTriplet, senderStatusGlyph } from "../../../../lupin_app/static/js/multiplexer/render/templates/senderCard";
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

// ---------------------------------------------------------------------------
// Worker-badge silencing (Rick 2026-06-24, gap list §6 Decision A/B).
// A managed worker (is_worker=true) sets data-worker on the card and suppresses
// the numeric .sender-new-count (the shared sheet renders a faint pulse instead
// via .sender-stats-group::after). Root / manager sessions keep their count.
// ---------------------------------------------------------------------------

test("senderCard: WORKER (is_worker) sets data-worker on the card AND suppresses .sender-new-count", () => {
  const card = renderSenderCard(makeSender({ unread_count: 7, is_worker: true }), [], { appTimezone: "UTC" });
  assert.equal(card.getAttribute("data-worker"), "true", "card flagged worker for the shared pulse rule");
  assert.equal(card.querySelector(".sender-new-count"), null, "numeric count suppressed for worker");
  // Number-only suppression — the stats container (pulse anchor) still renders.
  assert.notEqual(card.querySelector(".sender-stats-group"), null);
});

test("senderCard: ROOT (is_worker false) keeps the count and carries NO data-worker", () => {
  const card = renderSenderCard(makeSender({ unread_count: 7, is_worker: false }), [], { appTimezone: "UTC" });
  assert.equal(card.getAttribute("data-worker"), null, "root card not flagged");
  const badge = card.querySelector(".sender-new-count");
  assert.notEqual(badge, null);
  assert.equal(badge!.textContent, "7");
});

test("senderCard: is_worker undefined (no lineage signal) behaves like a non-worker — count shown", () => {
  const card = renderSenderCard(makeSender({ unread_count: 4 }), [], { appTimezone: "UTC" });
  assert.equal(card.getAttribute("data-worker"), null);
  assert.equal(card.querySelector(".sender-new-count")!.textContent, "4");
});

test("senderCard: WORKER with zero unread still flags data-worker (pulse needs it) and shows no count", () => {
  const card = renderSenderCard(makeSender({ unread_count: 0, is_worker: true }), [], { appTimezone: "UTC" });
  assert.equal(card.getAttribute("data-worker"), "true");
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

test("senderCard: empty display_name falls back to sender_id in header (.sender-project-name)", () => {
  const card = renderSenderCard(
    makeSender({ display_name: "", sender_id: "sess_99" }),
    [],
    { appTimezone: "UTC" },
  );
  // WS4/G4 rename-seam closure: the project-label slot is now .sender-project-name
  // (was the mux-only .sender-display-name); content is still display_name.
  const nameEl = card.querySelector(".sender-project-name");
  assert.notEqual(nameEl, null);
  assert.equal(nameEl!.textContent, "sess_99");
  // The old mux-only class must be gone (rename, not add-alongside).
  assert.equal(card.querySelector(".sender-display-name"), null);
});

// ---------------------------------------------------------------------------
// WS4/G4 (Clayton 2026-06-22) — CC-session sender-card HEADER CHROME.
// senderCard.ts now emits the legacy-parity header chrome (status / project-name
// / session block / delete / toggle) in mux idioms (NO inline onclick). Oracle
// proof: this ticks Tier-1 STRUCTURE nodes MISSING→PRESENT without regressing
// the (green) Tier-3 header geometry. The cc-voice-input residual (the real
// ~51px Tier-3 gap) is a SEPARATE slice (coordinated with Rachel/oracle).
// ---------------------------------------------------------------------------

test("senderCard: header emits the always-present chrome (status / project-name / delete / toggle)", () => {
  const card = renderSenderCard(makeSender(), [], { appTimezone: "UTC" });
  const header = card.querySelector(".sender-card-header");
  assert.notEqual(header, null);
  assert.notEqual(header!.querySelector(".sender-status"), null, ".sender-status present");
  assert.notEqual(header!.querySelector(".sender-project-name"), null, ".sender-project-name present");
  assert.notEqual(header!.querySelector(".sender-delete-btn"), null, ".sender-delete-btn present");
  assert.notEqual(header!.querySelector(".sender-toggle"), null, ".sender-toggle present");
  // Mux idiom: NO inline onclick anywhere in the emitted chrome.
  assert.equal(card.querySelector("[onclick]"), null, "no inline onclick (mux idiom)");
});

test("senderCard: CC session (sender_id with '#') emits the session block", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "claude.code@lupin.deepily.ai#parity01" }),
    [],
    { appTimezone: "UTC" },
  );
  // V10a: the redundant `#<sessionHash>` span (.sender-session-id) was dropped —
  // the copy button still exposes the session id; the visible duplicate is gone.
  assert.equal(card.querySelector(".sender-session-id"), null, ".sender-session-id dropped (V10a redundant #id)");
  assert.notEqual(card.querySelector(".sender-session-copy"), null, ".sender-session-copy present");
  assert.notEqual(card.querySelector(".sender-gist-btn"), null, ".sender-gist-btn present");
  assert.notEqual(card.querySelector(".sender-session-name"), null, ".sender-session-name present (empty until rename lands)");
});

test("senderCard: non-CC sender (no '#') omits the session block (legacy parity)", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "lupin-arbiter-app-8001" }),
    [],
    { appTimezone: "UTC" },
  );
  assert.equal(card.querySelector(".sender-session-copy"), null);
  assert.equal(card.querySelector(".sender-gist-btn"), null);
  assert.equal(card.querySelector(".sender-session-name"), null);
});

// ---------------------------------------------------------------------------
// F5 lane (Cheech 2026-06-22) — inline voice-input row (MATCH-LEGACY rebuild).
// CC sessions emit `.cc-voice-input` > `.cc-voice-input-row` (conv-mode + mic +
// input + send) BETWEEN the header and `.sender-card-dates`; non-CC omit it.
// The static structure is what the component-isolation parity harness sees, so
// the Tier-3 voice-region carve can lift. SenderCardRecorderRenderer adds only
// behavior on top.
// ---------------------------------------------------------------------------

test("senderCard: CC session emits the inline voice-input row with all four legacy controls", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "claude.code@lupin.deepily.ai#parity01" }),
    [],
    { appTimezone: "UTC" },
  );
  const vi = card.querySelector(".cc-voice-input");
  assert.notEqual(vi, null, ".cc-voice-input present for a CC session");
  assert.equal(vi!.getAttribute("data-session-hash"), "parity01");
  assert.equal(vi!.getAttribute("data-sender-id"), "claude.code@lupin.deepily.ai#parity01");
  const row = vi!.querySelector(".cc-voice-input-row");
  assert.notEqual(row, null, ".cc-voice-input-row present");
  // The four legacy-verbatim controls.
  assert.notEqual(row!.querySelector(".sender-conversation-mode-btn"), null, "conv-mode toggle present");
  assert.notEqual(row!.querySelector(".stt-button.cc-session-stt"), null, "mic present");
  const msgInput = row!.querySelector("input.cc-session-msg-input") as HTMLInputElement | null;
  assert.notEqual(msgInput, null, "text input present");
  assert.equal(msgInput!.getAttribute("id"), "cc-session-input-parity01", "input id composed with the session hash");
  assert.equal(msgInput!.getAttribute("placeholder"), "Send voice/text to CC session...");
  assert.notEqual(row!.querySelector(".response-submit-button.cc-session-send"), null, "send present");
  // Mux idiom: NO inline onclick anywhere in the row.
  assert.equal(vi!.querySelector("[onclick]"), null, "no inline onclick (mux idiom)");
});

test("senderCard: voice-input row sits BETWEEN the header and the dates region (legacy position)", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "claude.code@lupin.deepily.ai#parity01" }),
    [],
    { appTimezone: "UTC" },
  );
  const kids = [ ...card.children ].map(el => el.className);
  const headerIdx = kids.findIndex(c => c.includes("sender-card-header"));
  const voiceIdx  = kids.findIndex(c => c.includes("cc-voice-input"));
  const datesIdx  = kids.findIndex(c => c.includes("sender-card-dates"));
  assert.ok(headerIdx >= 0 && voiceIdx >= 0 && datesIdx >= 0, "all three regions present");
  assert.ok(headerIdx < voiceIdx && voiceIdx < datesIdx,
    `expected header < voice-input < dates; got ${headerIdx}/${voiceIdx}/${datesIdx}`);
});

test("senderCard: conversation_mode_active=true marks the toggle is-active with the 🔊 glyph", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "claude.code@lupin.deepily.ai#parity01", conversation_mode_active: true }),
    [],
    { appTimezone: "UTC" },
  );
  const btn = card.querySelector(".sender-conversation-mode-btn")!;
  assert.ok(btn.classList.contains("is-active"), "is-active when conversation mode is on");
  assert.equal(btn.textContent, "🔊");
  assert.equal(btn.getAttribute("data-session-id"), "parity01");
});

test("senderCard: conversation_mode_active=false omits is-active and uses the 🤭 glyph", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "claude.code@lupin.deepily.ai#parity01", conversation_mode_active: false }),
    [],
    { appTimezone: "UTC" },
  );
  const btn = card.querySelector(".sender-conversation-mode-btn")!;
  assert.ok(!btn.classList.contains("is-active"), "no is-active when conversation mode is off");
  assert.equal(btn.textContent, "🤭");
});

test("senderCard: non-CC sender (no '#') omits the voice-input row entirely (legacy parity)", () => {
  const card = renderSenderCard(
    makeSender({ sender_id: "lupin-arbiter-app-8001" }),
    [],
    { appTimezone: "UTC" },
  );
  assert.equal(card.querySelector(".cc-voice-input"), null, "no voice row for a non-CC sender");
  assert.equal(card.querySelector(".cc-voice-input-row"), null);
});

test("senderCard: injected opts.now drives the status glyph deterministically", () => {
  const ts  = Date.UTC(2026, 4, 5, 14, 0);
  // now == 30 min after last activity → active (🟢).
  const card = renderSenderCard(makeSender({ last_active_ts: ts }), [], { appTimezone: "UTC", now: ts + 30 * 60_000 });
  assert.equal(card.querySelector(".sender-status")!.textContent, "🟢");
});

// senderStatusGlyph — direct coverage of every recency branch.
test("senderStatusGlyph: no activity (<=0) → ⚪", () => {
  assert.equal(senderStatusGlyph(0, 1_000), "⚪");
  assert.equal(senderStatusGlyph(-5, 1_000), "⚪");
});

test("senderStatusGlyph: within the last hour → 🟢", () => {
  const ts = 10_000_000;
  assert.equal(senderStatusGlyph(ts, ts + 59 * 60_000), "🟢");
});

test("senderStatusGlyph: within the last day → 🟡", () => {
  const ts = 10_000_000;
  assert.equal(senderStatusGlyph(ts, ts + 5 * 3_600_000), "🟡");
});

test("senderStatusGlyph: older than a day → ⚪", () => {
  const ts = 10_000_000;
  assert.equal(senderStatusGlyph(ts, ts + 48 * 3_600_000), "⚪");
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
