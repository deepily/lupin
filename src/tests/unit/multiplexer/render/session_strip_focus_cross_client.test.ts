// Row d04ff119 — focus state round-trips between the two clients, byte for byte
// (Mr. Radio's condition on the plan).
//
// Both clients run on one origin, so they share localStorage: focus Rick sets in
// legacy is the focus the multiplexer must restore after a reload, and back. Each
// direction uses the OTHER client's real code — legacy's own save and restore
// methods, loaded from notifications.js — never a restatement of its format.
//
// Legacy is loaded the way worker_badge_silencing.test.ts loads it: the source up
// to its DOM-ready init, run in this context, instances made without the
// constructor (which needs the whole page).

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSessionStripRenderer,
  FOCUS_STATE_KEY,
  HIDE_INACTIVE_KEY,
} from "../../../../lupin_app/static/js/multiplexer/render/SessionStripRenderer";
import type { Notification, StripSession } from "../../../../lupin_app/static/js/multiplexer/shared/types";

const HERE             = dirname(fileURLToPath(import.meta.url));
const NOTIFICATIONS_JS = resolve(HERE, "../../../../lupin_app/static/js/notifications.js");

let legacySource = "";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
  legacySource = readFileSync(NOTIFICATIONS_JS, "utf8");
  const initIdx = legacySource.indexOf("// Initialize when DOM is ready");
  assert.ok(initIdx > 0, "bottom-of-file init marker must be found");
  vm.runInThisContext(legacySource.slice(0, initIdx) + "\n;globalThis.NotificationsUI = NotificationsUI;");
});

beforeEach(() => {
  document.body.replaceChildren();
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// Legacy
// ---------------------------------------------------------------------------

type LegacyUI = Record<string, unknown> & {
  ccFocusState        : { enabled: boolean; focused_sender_id: string | null };
  ccHideInactiveStrip : boolean;
  ccStripUnreadCounts : Record<string, number>;
  _enterFocusMode              : (senderId: string) => void;
  _exitFocusMode               : (persist?: boolean) => void;
  _maybeReapplyPersistedFocus  : (senderId: string) => void;
  _setHideInactiveStrip        : (enabled: boolean) => void;
  _markStripIconActivity       : (senderId: string, options?: Record<string, unknown>) => void;
  _addStripIcon                : (senderId: string, project: string, persona: unknown, sessionId: string) => void;
  _stripIconIdFor              : (senderId: string) => string;
};

// The two keys, read from legacy's constructor source, so a rename there fails here.
function legacyKey(name: string): string {
  const m = legacySource.match(new RegExp(`this\\.${name}\\s*=\\s*'([^']+)'`));
  assert.ok(m, `legacy constructor no longer assigns ${name}`);
  return m![1]!;
}

function legacyUI(): LegacyUI {
  const Ctor = (globalThis as Record<string, unknown>).NotificationsUI as { prototype: object };
  const ui   = Object.create(Ctor.prototype) as LegacyUI;
  ui.debug                = false;
  ui.log                  = (): void => {};
  ui.error                = (): void => {};
  ui.CC_FOCUS_STATE_KEY   = legacyKey("CC_FOCUS_STATE_KEY");
  ui.CC_HIDE_INACTIVE_KEY = legacyKey("CC_HIDE_INACTIVE_KEY");
  ui.managerPersonaMap    = new Map();
  ui.conversationModes    = {};
  ui.ccFocusState         = { enabled: false, focused_sender_id: null };
  ui.ccHideInactiveStrip  = false;
  ui.ccStripUnreadCounts  = {};
  ui.senderGroups         = new Map();
  return ui;
}

// ---------------------------------------------------------------------------
// Multiplexer — mounted on the real localStorage, as boot mounts it
// ---------------------------------------------------------------------------

function session(id: string, assignedAt: number): StripSession {
  return { sender_id: id, voice_persona: { name: id, voice_id: "v", icon: "🙂", color: "#81D4FA", borrowed: false }, assigned_at: assignedAt, active: true };
}

const IDS = [ "claude.code@lupin.deepily.ai#aaaa1111", "claude.code@plan.deepily.ai#bbbb2222" ];

function mountMux(notifs: Notification[] = []) {
  const root = document.createElement("main");
  root.innerHTML = `<div id="cc-session-strip"><div id="cc-strip-icons"></div><button id="cc-strip-toggle"></button><button id="cc-hide-inactive-toggle"></button></div>`;
  document.body.appendChild(root);
  const bus = createEventBusForTesting();
  const r   = createSessionStripRenderer({
    eventBus : bus,
    stores   : { strip: { list: () => IDS.map((id, i) => session(id, i + 1)) }, notifications: { list: () => notifs } },
  });   // no `storage`: the localStorage default, the same object legacy writes to
  r.mount(root);
  const icon = (id: string) => root.querySelector<HTMLElement>(`#cc-strip-icons .cc-strip-icon[data-sender-id="${id}"]`)!;
  return {
    bus, r, root, icon,
    toggle : root.querySelector<HTMLElement>("#cc-strip-toggle")!,
    hide   : root.querySelector<HTMLElement>("#cc-hide-inactive-toggle")!,
  };
}

// ===========================================================================

test("the keys are legacy's own", () => {
  assert.equal(FOCUS_STATE_KEY,   legacyKey("CC_FOCUS_STATE_KEY"));
  assert.equal(HIDE_INACTIVE_KEY, legacyKey("CC_HIDE_INACTIVE_KEY"));
});

test("legacy saves a focus → the multiplexer restores it", () => {
  legacyUI()._enterFocusMode(IDS[1]!);
  const saved = localStorage.getItem(FOCUS_STATE_KEY);
  assert.ok(saved !== null, "legacy wrote nothing");

  const mux = mountMux();
  assert.equal(mux.toggle.getAttribute("data-focus-active"), "true");
  assert.equal(mux.icon(IDS[1]!).getAttribute("data-focused"), "true");
  assert.equal(localStorage.getItem(FOCUS_STATE_KEY), saved, "restoring changed the stored bytes");
  mux.r.unmount();
});

test("the multiplexer saves a focus → legacy restores it, and the bytes equal legacy's own save", () => {
  const mux = mountMux();
  mux.icon(IDS[1]!).dispatchEvent(new Event("click", { bubbles: true }));
  const muxBytes = localStorage.getItem(FOCUS_STATE_KEY);
  mux.r.unmount();

  const legacy = legacyUI();
  legacy._maybeReapplyPersistedFocus(IDS[1]!);   // legacy's real restore path
  assert.deepEqual(legacy.ccFocusState, { enabled: true, focused_sender_id: IDS[1] });

  localStorage.clear();
  legacyUI()._enterFocusMode(IDS[1]!);
  assert.equal(muxBytes, localStorage.getItem(FOCUS_STATE_KEY), "the two clients write different bytes for the same focus");
});

test("an exit round-trips too: the multiplexer's saved exit equals legacy's, and neither client restores focus from it", () => {
  const mux = mountMux();
  mux.icon(IDS[0]!).dispatchEvent(new Event("click", { bubbles: true }));
  mux.toggle.dispatchEvent(new Event("click", { bubbles: true }));
  const muxBytes = localStorage.getItem(FOCUS_STATE_KEY);
  mux.r.unmount();

  const legacy = legacyUI();
  legacy._maybeReapplyPersistedFocus(IDS[0]!);
  assert.equal(legacy.ccFocusState.enabled, false);

  localStorage.clear();
  const l2 = legacyUI();
  l2._enterFocusMode(IDS[0]!);
  l2._exitFocusMode();
  assert.equal(muxBytes, localStorage.getItem(FOCUS_STATE_KEY));

  const again = mountMux();
  assert.equal(again.toggle.getAttribute("data-focus-active"), "false");
  again.r.unmount();
});

test("hide-inactive: both clients write the same bytes, and the multiplexer restores legacy's", () => {
  for (const enabled of [ true, false ]) {
    localStorage.clear();
    legacyUI()._setHideInactiveStrip(!enabled);
    const legacyFlipped = localStorage.getItem(HIDE_INACTIVE_KEY);
    localStorage.clear();
    legacyUI()._setHideInactiveStrip(enabled);
    const legacyBytes = localStorage.getItem(HIDE_INACTIVE_KEY);

    const mux = mountMux();
    assert.equal(mux.hide.getAttribute("data-hide-inactive"), String(enabled), `restored the wrong state from legacy's ${legacyBytes}`);
    // One flip, so the stored value can only match if the multiplexer wrote it.
    mux.hide.dispatchEvent(new Event("click", { bubbles: true }));
    assert.equal(localStorage.getItem(HIDE_INACTIVE_KEY), legacyFlipped);
    mux.r.unmount();
  }
});

test("the badge: the same arrivals leave the same unread attributes on both clients' icons", () => {
  // Legacy: a strip icon from its own builder, then two activity marks in focus mode.
  const strip = document.createElement("div");
  strip.id = "cc-session-strip";
  const icons = document.createElement("div");
  icons.id = "cc-strip-icons";
  strip.appendChild(icons);
  document.body.appendChild(strip);
  const legacy = legacyUI();
  legacy._addStripIcon(IDS[0]!, "lupin", null, "aaaa1111");
  legacy._addStripIcon(IDS[1]!, "plan", null, "bbbb2222");
  legacy.ccFocusState = { enabled: true, focused_sender_id: IDS[0]! };
  legacy._markStripIconActivity(IDS[1]!);
  legacy._markStripIconActivity(IDS[1]!);
  const legacyIcon = document.getElementById(legacy._stripIconIdFor(IDS[1]!))!;
  const legacyAttrs = [ legacyIcon.getAttribute("data-unread"), legacyIcon.getAttribute("data-unread-count") ];
  strip.remove();

  const notifs: Notification[] = [];
  const mux = mountMux(notifs);
  mux.icon(IDS[0]!).dispatchEvent(new Event("click", { bubbles: true }));
  for (const idHash of [ "x1", "x2" ]) {
    notifs.push({ id_hash: idHash, ts: 0, sender_id: IDS[1]!, message: "m", action_required: false });
    mux.bus.emit({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: idHash }, source: "test", ts: 0 });
  }
  const muxIcon = mux.icon(IDS[1]!);
  assert.deepEqual([ muxIcon.getAttribute("data-unread"), muxIcon.getAttribute("data-unread-count") ], legacyAttrs);
  assert.deepEqual(legacyAttrs, [ "true", "2" ], "precondition: legacy counted both");
  mux.r.unmount();
});
