// Multiplexer Phase 5 — dateAccordion template tests.
// AC5 floor: ≥3 tests.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderDateAccordion } from "../../../../fastapi_app/static/js/multiplexer/render/templates/dateAccordion";
import type { Notification } from "../../../../fastapi_app/static/js/multiplexer/shared/types";

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

function makeNotification(id: string, ts: number = Date.UTC(2026, 4, 5)): Notification {
  return {
    id_hash         : id,
    ts,
    sender_id       : "sess_42",
    message         : `msg-${id}`,
    action_required : false,
  };
}

// ---------------------------------------------------------------------------

test("dateAccordion: header carries date-text + count + toggle; root has data-id-hash=dateKey", () => {
  const items = [makeNotification("n1"), makeNotification("n2")];
  const el = renderDateAccordion("2026-05-05", items, { appTimezone: "UTC" });
  assert.equal(el.getAttribute("data-id-hash"), "2026-05-05");
  assert.equal(el.getAttribute("data-date-key"), "2026-05-05");
  assert.equal(el.getAttribute("data-collapsed"), "false");
  assert.equal(el.querySelector(".date-text")!.textContent, "2026-05-05");
  assert.equal(el.querySelector(".date-count")!.textContent, "(2)");
  assert.equal(el.querySelector(".date-toggle")!.textContent, "▼");
});

test("dateAccordion: messages container holds rendered .sender-message items in input order", () => {
  const items = [makeNotification("n1"), makeNotification("n2"), makeNotification("n3")];
  const el = renderDateAccordion("2026-05-05", items, { appTimezone: "UTC" });
  const messages = el.querySelectorAll(".sender-message");
  assert.equal(messages.length, 3);
  assert.equal(messages[0]!.getAttribute("data-id-hash"), "n1");
  assert.equal(messages[1]!.getAttribute("data-id-hash"), "n2");
  assert.equal(messages[2]!.getAttribute("data-id-hash"), "n3");
});

test("dateAccordion: empty notifications still renders chrome (count = 0)", () => {
  const el = renderDateAccordion("2026-05-05", [], { appTimezone: "UTC" });
  assert.equal(el.querySelector(".date-count")!.textContent, "(0)");
  assert.equal(el.querySelectorAll(".sender-message").length, 0);
});
