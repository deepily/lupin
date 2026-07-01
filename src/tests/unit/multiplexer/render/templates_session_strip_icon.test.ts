// Multiplexer WP2 (parity bridge) — session strip icon template unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/templates_session_strip_icon.test.ts`.
//
// Coverage target: 100% lines + branches + functions.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  personaInitial,
  applyManagerBadge,
  renderSessionStripIcon,
  updateSessionStripIcon,
  stripAllocStatus,
  applyAllocStatus,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/sessionStripIcon";
import type { ManagerPersona, StripSession, VoicePersona } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function vp(over: Partial<VoicePersona> = {}): VoicePersona {
  return { name: "Krishna", voice_id: "v", icon: "🦚", color: "#1DE9B6", borrowed: false, ...over };
}

function session(over: Partial<StripSession> = {}): StripSession {
  return { sender_id: "s1", voice_persona: vp(), assigned_at: 1000, active: true, ...over };
}

const MANAGER: ManagerPersona = { name: "Tiberius", icon: "👑", color: "#FFD700" };

// ===========================================================================
// personaInitial
// ===========================================================================

test("personaInitial: first char uppercased", () => {
  assert.equal(personaInitial("krishna"), "K");
  assert.equal(personaInitial("Rio"), "R");
});

test("personaInitial: leading whitespace trimmed", () => {
  assert.equal(personaInitial("  zeke"), "Z");
});

test("personaInitial: empty and whitespace-only → '?'", () => {
  assert.equal(personaInitial(""), "?");
  assert.equal(personaInitial("   "), "?");
});

// ===========================================================================
// renderSessionStripIcon
// ===========================================================================

test("renderSessionStripIcon: base attributes + initial span", () => {
  const el = renderSessionStripIcon(session());
  assert.equal(el.tagName, "BUTTON");
  assert.equal(el.className, "cc-strip-icon");
  assert.equal(el.getAttribute("data-id-hash"), "s1");
  assert.equal(el.getAttribute("data-sender-id"), "s1");
  assert.equal(el.getAttribute("data-active"), "true");
  assert.equal(el.getAttribute("title"), "Krishna");
  assert.equal(el.style.getPropertyValue("--persona-color"), "#1DE9B6");
  const initial = el.querySelector(".cc-strip-initial");
  assert.ok(initial);
  assert.equal(initial!.textContent, "K");
});

test("renderSessionStripIcon: empty persona name → title falls back to sender_id", () => {
  const el = renderSessionStripIcon(session({ voice_persona: vp({ name: "" }) }));
  assert.equal(el.getAttribute("title"), "s1");
  assert.equal(el.querySelector(".cc-strip-initial")!.textContent, "?");
});

test("renderSessionStripIcon: empty color → no --persona-color set", () => {
  const el = renderSessionStripIcon(session({ voice_persona: vp({ color: "" }) }));
  assert.equal(el.style.getPropertyValue("--persona-color"), "");
});

test("renderSessionStripIcon: inactive session → data-active false", () => {
  const el = renderSessionStripIcon(session({ active: false }));
  assert.equal(el.getAttribute("data-active"), "false");
});

test("renderSessionStripIcon: with manager → lineage badge present", () => {
  const el = renderSessionStripIcon(session({ manager_persona: MANAGER }));
  const badge = el.querySelector(".cc-strip-manager-badge");
  assert.ok(badge);
  assert.equal(badge!.textContent, "T");
  assert.equal(el.getAttribute("data-has-manager"), "true");
});

test("renderSessionStripIcon: without manager → no lineage badge", () => {
  const el = renderSessionStripIcon(session());
  assert.equal(el.querySelector(".cc-strip-manager-badge"), null);
  assert.equal(el.getAttribute("data-has-manager"), null);
});

// ===========================================================================
// applyManagerBadge
// ===========================================================================

test("applyManagerBadge: applies badge with color, title, derived initial", () => {
  const btn = renderSessionStripIcon(session());
  applyManagerBadge(btn, MANAGER);
  const badge = btn.querySelector(".cc-strip-manager-badge") as HTMLElement;
  assert.ok(badge);
  assert.equal(badge.textContent, "T");
  assert.equal(badge.getAttribute("title"), "Spawned by Tiberius");
  assert.equal(badge.style.getPropertyValue("--manager-color"), "#FFD700");
  assert.equal(btn.getAttribute("data-has-manager"), "true");
});

test("applyManagerBadge: null clears badge + data-has-manager", () => {
  const btn = renderSessionStripIcon(session({ manager_persona: MANAGER }));
  applyManagerBadge(btn, null);
  assert.equal(btn.querySelector(".cc-strip-manager-badge"), null);
  assert.equal(btn.getAttribute("data-has-manager"), null);
});

test("applyManagerBadge: idempotent — re-apply keeps exactly one badge", () => {
  const btn = renderSessionStripIcon(session());
  applyManagerBadge(btn, MANAGER);
  applyManagerBadge(btn, { name: "Rio", icon: "⚡", color: "#abc" });
  const badges = btn.querySelectorAll(".cc-strip-manager-badge");
  assert.equal(badges.length, 1);
  assert.equal(badges[0]!.textContent, "R");
});

test("applyManagerBadge: empty manager name → label 'manager', initial '?'", () => {
  const btn = renderSessionStripIcon(session());
  applyManagerBadge(btn, { name: "", icon: "", color: "" });
  const badge = btn.querySelector(".cc-strip-manager-badge") as HTMLElement;
  assert.equal(badge.getAttribute("title"), "Spawned by manager");
  assert.equal(badge.textContent, "?");
});

test("applyManagerBadge: empty manager color → no --manager-color set", () => {
  const btn = renderSessionStripIcon(session());
  applyManagerBadge(btn, { name: "Rio", icon: "", color: "" });
  const badge = btn.querySelector(".cc-strip-manager-badge") as HTMLElement;
  assert.equal(badge.style.getPropertyValue("--manager-color"), "");
});

// ===========================================================================
// updateSessionStripIcon
// ===========================================================================

test("updateSessionStripIcon: refreshes active, title, color, initial, badge", () => {
  const el = renderSessionStripIcon(session());
  updateSessionStripIcon(el, session({
    active: false,
    voice_persona: vp({ name: "Rio", color: "#222" }),
    manager_persona: MANAGER,
  }));
  assert.equal(el.getAttribute("data-active"), "false");
  assert.equal(el.getAttribute("title"), "Rio");
  assert.equal(el.style.getPropertyValue("--persona-color"), "#222");
  assert.equal(el.querySelector(".cc-strip-initial")!.textContent, "R");
  assert.ok(el.querySelector(".cc-strip-manager-badge"));
});

test("updateSessionStripIcon: empty color removes --persona-color; empty name → title=sender_id", () => {
  const el = renderSessionStripIcon(session());
  updateSessionStripIcon(el, session({ voice_persona: vp({ name: "", color: "" }) }));
  assert.equal(el.style.getPropertyValue("--persona-color"), "");
  assert.equal(el.getAttribute("title"), "s1");
  assert.equal(el.querySelector(".cc-strip-initial")!.textContent, "?");
});

test("updateSessionStripIcon: tolerates a button missing the initial span", () => {
  const bare = document.createElement("button");
  bare.className = "cc-strip-icon";
  // No .cc-strip-initial child — exercise the null-guard branch.
  assert.doesNotThrow(() => updateSessionStripIcon(bare, session()));
  assert.equal(bare.getAttribute("data-active"), "true");
});

// ===========================================================================
// V9 — allocation-status indicator (stripAllocStatus / applyAllocStatus)
// ===========================================================================

test("stripAllocStatus: borrowed persona → 'borrowed' (precedence over active)", () => {
  assert.equal(stripAllocStatus(session({ voice_persona: vp({ borrowed: true }), active: true  })), "borrowed");
  assert.equal(stripAllocStatus(session({ voice_persona: vp({ borrowed: true }), active: false })), "borrowed");
});

test("stripAllocStatus: not borrowed + inactive → 'inactive'", () => {
  assert.equal(stripAllocStatus(session({ active: false })), "inactive");
});

test("stripAllocStatus: not borrowed + active → null (no indicator, the negative case)", () => {
  assert.equal(stripAllocStatus(session({ active: true })), null);
});

test("renderSessionStripIcon: borrowed → data-alloc-status='borrowed'", () => {
  const el = renderSessionStripIcon(session({ voice_persona: vp({ borrowed: true }) }));
  assert.equal(el.getAttribute("data-alloc-status"), "borrowed");
});

test("renderSessionStripIcon: inactive → data-alloc-status='inactive'", () => {
  const el = renderSessionStripIcon(session({ active: false }));
  assert.equal(el.getAttribute("data-alloc-status"), "inactive");
});

test("renderSessionStripIcon: normal active own-persona → no data-alloc-status attr", () => {
  const el = renderSessionStripIcon(session());
  assert.equal(el.getAttribute("data-alloc-status"), null);
});

test("applyAllocStatus: set then clear across re-application", () => {
  const el = renderSessionStripIcon(session({ voice_persona: vp({ borrowed: true }) }));
  assert.equal(el.getAttribute("data-alloc-status"), "borrowed");
  // Re-apply with a normal session → attribute removed (the removeAttribute branch).
  applyAllocStatus(el, session());
  assert.equal(el.getAttribute("data-alloc-status"), null);
});

test("updateSessionStripIcon: refreshes data-alloc-status on re-assignment", () => {
  const el = renderSessionStripIcon(session());
  assert.equal(el.getAttribute("data-alloc-status"), null);
  updateSessionStripIcon(el, session({ voice_persona: vp({ borrowed: true }) }));
  assert.equal(el.getAttribute("data-alloc-status"), "borrowed");
  updateSessionStripIcon(el, session());
  assert.equal(el.getAttribute("data-alloc-status"), null);
});
