// Multiplexer Lane D (WP3) — commonsActivityEntry template unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/templates_commons_activity_entry.test.ts`.
//
// Coverage target: 100% lines/branches/functions.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderCommonsActivityEntry } from "../../../../lupin_app/static/js/multiplexer/render/templates/commonsActivityEntry";
import type { CommonsActivityEntry } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// Minimal marked + DOMPurify shims (mirror markdown.test.ts).
beforeEach(() => {
  const w = globalThis as unknown as {
    marked   ?: { parse: (s: string, opts?: unknown) => string };
    DOMPurify?: { sanitize: (s: string, cfg?: unknown) => string };
  };
  w.marked = {
    parse: (s: string): string => `<p>${s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")}</p>`,
  };
  w.DOMPurify = {
    sanitize: (s: string): string => s.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, ""),
  };
});

function makeEntry(over: Partial<CommonsActivityEntry> = {}): CommonsActivityEntry {
  return {
    ts            : "2026-06-10T14:05:00+00:00",
    topic         : "build-status",
    topic_kind    : "free-form",
    persona_name  : "Tiberius",
    persona_icon  : "👑",
    persona_color : "#FFD600",
    body          : "shipped **it**",
    metadata      : {},
    ...over,
  };
}

const TZ = "America/New_York";   // deterministic, TZ-independent assertions

test("renders the full row structure with persona icon/name and markdown body", () => {
  const row = renderCommonsActivityEntry(makeEntry(), { appTimezone: TZ });
  assert.equal(row.className, "commons-activity-entry");
  assert.equal(row.querySelector(".commons-activity-entry-icon")?.textContent, "👑");
  assert.equal(row.querySelector(".commons-activity-entry-name")?.textContent, "Tiberius");
  const body = row.querySelector(".commons-activity-entry-body-content");
  assert.ok(body?.innerHTML.includes("<strong>it</strong>"));
});

test("persona_color is applied as the --persona-color CSS var", () => {
  const row = renderCommonsActivityEntry(makeEntry({ persona_color: "#123456" }), { appTimezone: TZ });
  assert.equal(row.style.getPropertyValue("--persona-color"), "#123456");
});

test("missing persona_color leaves the CSS var unset", () => {
  const row = renderCommonsActivityEntry(makeEntry({ persona_color: null }), { appTimezone: TZ });
  assert.equal(row.style.getPropertyValue("--persona-color"), "");
});

test("free-form topic renders a visible chip with the topic text", () => {
  const row = renderCommonsActivityEntry(makeEntry({ topic: "build-status", topic_kind: "free-form" }), { appTimezone: TZ });
  const chip = row.querySelector(".commons-activity-entry-topic-chip") as HTMLElement;
  assert.equal(chip.hidden, false);
  assert.equal(chip.textContent, "build-status");
});

test("reserved topic hides the chip", () => {
  const row = renderCommonsActivityEntry(makeEntry({ topic: "broadcasts", topic_kind: "reserved" }), { appTimezone: TZ });
  const chip = row.querySelector(".commons-activity-entry-topic-chip") as HTMLElement;
  assert.equal(chip.hidden, true);
});

test("dm- topic collapses to @<suffix> in the chip", () => {
  const row = renderCommonsActivityEntry(makeEntry({ topic: "dm-rachel", topic_kind: "free-form" }), { appTimezone: TZ });
  assert.equal(row.querySelector(".commons-activity-entry-topic-chip")?.textContent, "@rachel");
});

test("broadcast-acks body is reshaped to descriptive phrasing", () => {
  const row = renderCommonsActivityEntry(makeEntry({ topic: "broadcast-acks", body: "completed" }), { appTimezone: TZ });
  assert.ok(row.querySelector(".commons-activity-entry-body-content")?.textContent?.includes("received broadcast"));
});

test("unknown broadcast-acks body passes through unchanged", () => {
  const row = renderCommonsActivityEntry(makeEntry({ topic: "broadcast-acks", body: "weird-status" }), { appTimezone: TZ });
  assert.ok(row.querySelector(".commons-activity-entry-body-content")?.textContent?.includes("weird-status"));
});

test("missing persona name/icon fall back to em-dash / middot", () => {
  const row = renderCommonsActivityEntry(makeEntry({ persona_name: null, persona_icon: null }), { appTimezone: TZ });
  assert.equal(row.querySelector(".commons-activity-entry-name")?.textContent, "—");
  assert.equal(row.querySelector(".commons-activity-entry-icon")?.textContent, "·");
});

test("empty body renders an empty content node (no crash)", () => {
  const row = renderCommonsActivityEntry(makeEntry({ body: null }), { appTimezone: TZ });
  assert.equal(row.querySelector(".commons-activity-entry-body-content")?.textContent, "");
});

test("Show-more toggle starts hidden", () => {
  const row = renderCommonsActivityEntry(makeEntry(), { appTimezone: TZ });
  const toggle = row.querySelector(".commons-activity-entry-body-toggle") as HTMLButtonElement;
  assert.equal(toggle.hidden, true);
  assert.equal(toggle.getAttribute("type"), "button");
});

test("valid ts formats to HH:MM in the configured timezone", () => {
  // 2026-06-10T14:05:00Z → 10:05 in America/New_York (EDT, UTC-4)
  const row = renderCommonsActivityEntry(makeEntry({ ts: "2026-06-10T14:05:00+00:00" }), { appTimezone: TZ });
  assert.equal(row.querySelector(".commons-activity-entry-time")?.textContent, "10:05");
});

test("absent ts renders the --:-- placeholder", () => {
  const row = renderCommonsActivityEntry(makeEntry({ ts: null }), { appTimezone: TZ });
  assert.equal(row.querySelector(".commons-activity-entry-time")?.textContent, "--:--");
});

test("renders with default options (no appTimezone) without throwing", () => {
  const row = renderCommonsActivityEntry(makeEntry());
  assert.ok(row.querySelector(".commons-activity-entry-time")?.textContent);
});

test("missing topic string is handled (empty chip, no dm collapse)", () => {
  const entry = { topic_kind: "free-form", body: "x", ts: "2026-06-10T14:05:00+00:00" } as unknown as CommonsActivityEntry;
  const row = renderCommonsActivityEntry(entry, { appTimezone: TZ });
  assert.equal(row.querySelector(".commons-activity-entry-topic-chip")?.textContent, "");
});
