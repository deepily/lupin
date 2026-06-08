// Integration — reap → focus-bar badge drop (2026-06-05).
//
// Proves Rick's headline requirement end-to-end on the multiplexer side:
// with focus mode ON and a sender pinned, when a `session_reaped` event
// arrives for a *different* (non-pinned) worker, that worker's persona badge
// disappears from the focus tray — the visual confirmation the reap landed.
//
// Wires the REAL SenderStore + REAL FocusTrayRenderer on a shared EventBus
// (no stubs): notification_queue_update{type:session_reaped} → SenderStore
// removes the sender + emits store_senders_changed{removed} → FocusTrayRenderer
// reconciles → the tray row vanishes.
//
// Run via:
//   npx tsx --test src/tests/unit/multiplexer/render/sender_reap_focus_tray_integration.test.ts
// See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSenderStore } from "../../../../lupin_app/static/js/multiplexer/stores/SenderStore";
import { createFocusTrayRenderer } from "../../../../lupin_app/static/js/multiplexer/render/FocusTrayRenderer";

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

type Bus = ReturnType<typeof createEventBusForTesting>;

function emit(bus: Bus, notification: Record<string, unknown>): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification },
    source  : "test",
    ts      : 0,
  });
}

function makeRoot(): { root: HTMLElement; toggleEl: HTMLButtonElement; trayEl: HTMLElement } {
  const root = document.createElement("main");
  const toggle = document.createElement("button");
  toggle.id = "focus-mode-toggle";
  toggle.setAttribute("hidden", "");
  root.appendChild(toggle);
  const tray = document.createElement("aside");
  tray.id = "focus-tray";
  tray.setAttribute("hidden", "");
  root.appendChild(tray);
  document.body.appendChild(root);
  return {
    root,
    toggleEl : root.querySelector("#focus-mode-toggle") as HTMLButtonElement,
    trayEl   : root.querySelector("#focus-tray")        as HTMLElement,
  };
}

test("reap drops the worker's badge from the focus tray (real SenderStore + FocusTrayRenderer)", () => {
  const bus    = createEventBusForTesting();
  const store  = createSenderStore({ bus, nowFn: () => 1_000_000 });
  const ui     = makeRoot();
  const tray   = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  tray.mount(ui.root);

  // Two known senders: "manager" (will be pinned) + "worker" (will be reaped).
  emit(bus, { type: "task", sender_id: "manager@x", timestamp: "2026-06-05T10:00:00Z" });
  emit(bus, { type: "task", sender_id: "worker@x",  timestamp: "2026-06-05T10:01:00Z" });

  // Pin the manager (conversation-mode), then turn focus mode ON via the toggle.
  emit(bus, { type: "conversation_mode_changed", sender_id: "manager@x", payload: { active: true } });
  ui.toggleEl.click();

  // Focus mode hides non-pinned senders into the tray — the worker shows as a badge row.
  let workerRow = ui.trayEl.querySelector('.focus-tray-row[data-sender-id="worker@x"]');
  assert.ok(workerRow, "precondition: worker badge present in focus tray");

  // Reap the worker.
  emit(bus, { type: "session_reaped", sender_id: "worker@x" });

  // Its badge is gone — visual confirmation the reap landed.
  workerRow = ui.trayEl.querySelector('.focus-tray-row[data-sender-id="worker@x"]');
  assert.equal(workerRow, null, "worker badge removed from focus tray after reap");
  assert.equal(store.get("worker@x"), undefined, "worker removed from SenderStore");

  // The pinned manager is untouched.
  assert.ok(store.get("manager@x"), "pinned manager still tracked");

  tray.unmount();
});

test("reaping the PINNED/focused sender exits focus mode cleanly (no stuck state)", () => {
  // Tiberius review failure-mode #1 (highest user-visible): when the focused
  // anchor itself is harvested, focus mode must not strand the user — the
  // toggle would otherwise be disabled (no pin) AND stuck ON. Mirrors the
  // legacy `_removeStripIcon` auto-exit.
  const bus    = createEventBusForTesting();
  const store  = createSenderStore({ bus, nowFn: () => 1_000_000 });
  const ui     = makeRoot();
  const tray   = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  tray.mount(ui.root);

  emit(bus, { type: "task", sender_id: "boss@x",   timestamp: "2026-06-05T10:00:00Z" });
  emit(bus, { type: "task", sender_id: "worker@x", timestamp: "2026-06-05T10:01:00Z" });
  emit(bus, { type: "conversation_mode_changed", sender_id: "boss@x", payload: { active: true } });
  ui.toggleEl.click();
  assert.equal(ui.toggleEl.getAttribute("aria-pressed"), "true", "precondition: focus mode ON");

  // Reap the PINNED sender.
  emit(bus, { type: "session_reaped", sender_id: "boss@x" });

  // Focus mode must have exited — not stranded ON with a disabled toggle.
  assert.equal(ui.toggleEl.getAttribute("aria-pressed"), "false", "focus mode exited after pinned sender reaped");
  assert.ok(ui.trayEl.hasAttribute("hidden"), "tray hidden after auto-exit");
  assert.equal(store.get("boss@x"), undefined, "pinned sender removed from store");

  tray.unmount();
});

test("double-reap of the same sender is idempotent (second reap is a no-op)", () => {
  // Tiberius review failure-mode #2: producer emits nothing on the 2nd reap,
  // but if a duplicate ever reaches the consumer it must be a clean no-op.
  const bus    = createEventBusForTesting();
  const store  = createSenderStore({ bus, nowFn: () => 1_000_000 });
  const removed: string[] = [];
  bus.on("store_senders_changed", (e: { payload: { changeKind: string; sender_id: string } }) => {
    if (e.payload.changeKind === "removed") removed.push(e.payload.sender_id);
  });

  emit(bus, { type: "task", sender_id: "dupe@x", timestamp: "2026-06-05T10:00:00Z" });
  emit(bus, { type: "session_reaped", sender_id: "dupe@x" });
  emit(bus, { type: "session_reaped", sender_id: "dupe@x" });   // duplicate

  assert.equal(store.get("dupe@x"), undefined, "sender gone");
  assert.equal(removed.length, 1, "only ONE removed emission across the double reap");
});
