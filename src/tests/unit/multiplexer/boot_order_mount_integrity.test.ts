// Multiplexer — boot-order mount-integrity integration test (bug 2826d65c).
//
// THE MISSING TEST CLASS. The Lane 0c boot regression slipped past 100%-green
// isolated unit tests because those tests built each renderer's root WITH its
// inner mount points as CHILDREN — masking the PRODUCTION multiplexer.html shape
// where #action-required-section is a SIBLING of #notifications-pane (extracted
// by Lane 0c), NOT a child. NotificationsListRenderer's old
// `querySelector("#action-required-section") ?? root` then MISSED and fell back
// to the whole pane, whose replaceChildren() wiped the sibling
// #sender-cards-container before boot.ts's recorder-mount lookup → boot crash.
//
// This test reproduces the FAITHFUL production DOM (the full 6-pane accordion
// layout, AR as a SIBLING) and mounts NotificationsListRenderer into
// #notifications-pane exactly as boot.ts does, asserting NOTHING outside the
// renderer's own pane content is touched — every static pane AND
// #sender-cards-container survive so boot.ts's later getElementById lookups all
// resolve. Plus the fail-loud contract (owned mount missing → throw).
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_order_mount_integrity.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsListRenderer } from "../../../lupin_app/static/js/multiplexer/render/NotificationsListRenderer";
import type { Notification, SenderRecord } from "../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// Empty stub stores — the mount-integrity contract is DOM-structural and holds
// regardless of content; empty lists keep the fixture minimal.
function makeEmptyStores() {
  return {
    notifications  : { list: () => [] as Notification[] },
    senders        : { list: () => [] as SenderRecord[] },
  };
}

// Faithful reproduction of the multiplexer.html accordion layout (the parts that
// matter for mount adjacency). Mirrors the real nesting: #action-required-section
// is a STANDALONE sibling (Lane 0c extraction); #notifications-header-mount lives
// in .notifications-header-region; #sender-cards-container is the ONLY child of
// #notifications-pane; the remaining accordion panes are dedicated + empty.
function buildMultiplexerLayout(): HTMLElement {
  const app = document.createElement("div");
  app.innerHTML = `
    <div id="action-required-section" data-testid="multiplexer-action-required-section"></div>
    <div class="notifications-header-region">
      <div id="notifications-header-mount"></div>
      <div id="tts-preview-slider-mount"></div>
    </div>
    <section id="notifications-pane" class="notifications-pane">
      <div id="sender-cards-container" data-testid="multiplexer-sender-cards"></div>
    </section>
    <section id="fleet-status-pane"></section>
    <section id="task-list-pane"></section>
    <section id="jobs-pane" hidden><div id="jobs-buckets-container"></div></section>
    <section id="tts-pane" data-phase6-pending="true"></section>
  `;
  return app;
}

// The static elements every downstream boot step (renderers + boot.ts
// getElementById lookups) depends on surviving.
const CRITICAL_STATIC_IDS = [
  "action-required-section",
  "notifications-header-mount",
  "sender-cards-container",
  "fleet-status-pane",
  "task-list-pane",
  "jobs-pane",
  "jobs-buckets-container",
  "tts-pane",
];

test("boot-order: mounting NotificationsListRenderer into #notifications-pane leaves ALL static panes + #sender-cards-container attached (bug 2826d65c)", () => {
  const app = buildMultiplexerLayout();
  document.body.appendChild(app);
  try {
    const bus  = createEventBusForTesting();
    const renderer = createNotificationsListRenderer({
      eventBus: bus,
      stores  : makeEmptyStores(),
      appTimezone: "UTC",
    });

    // Boot step: NotificationsListRenderer mounts into #notifications-pane
    // (boot.ts:285). Pre-fix this wiped #sender-cards-container via the `?? root`
    // AR fallback.
    const pane = document.getElementById("notifications-pane") as HTMLElement;
    renderer.mount(pane);

    // EVERY critical static element must still resolve via document lookup — this
    // is precisely what boot.ts's later getElementById calls (e.g. :400 for the
    // recorder mount) rely on.
    for (const id of CRITICAL_STATIC_IDS) {
      assert.notEqual(document.getElementById(id), null, `#${id} must survive the list-renderer mount`);
    }

    // The AR sibling section is untouched (still empty, still a sibling of the
    // pane — never adopted or wiped by the list renderer).
    const arSection = document.getElementById("action-required-section") as HTMLElement;
    assert.equal(arSection.parentElement!.id, "", "AR section stays a top-level sibling (not re-parented)");
    assert.equal(arSection.childElementCount, 0, "AR section untouched by the list renderer");

    // The renderer DID populate its OWN pane content (the empty-state marker), so
    // #sender-cards-container is the live mount, not a bystander.
    assert.notEqual(
      document.querySelector("#sender-cards-container [data-testid='multiplexer-empty-state']"),
      null,
      "renderer populated the surviving #sender-cards-container",
    );

    renderer.unmount();
  } finally {
    app.remove();
  }
});

test("boot-order fail-loud: list renderer mounted into a pane missing #sender-cards-container throws (no silent wipe path)", () => {
  const bus  = createEventBusForTesting();
  const renderer = createNotificationsListRenderer({
    eventBus: bus,
    stores  : makeEmptyStores(),
    appTimezone: "UTC",
  });
  // A pane WITHOUT the owned #sender-cards-container mount — must fail loudly at
  // mount rather than silently retargeting (the class of bug this guards).
  const pane = document.createElement("section");
  pane.id = "notifications-pane";
  assert.throws(() => renderer.mount(pane), /#sender-cards-container not found/);
});
