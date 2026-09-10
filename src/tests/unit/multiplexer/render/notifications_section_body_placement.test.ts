// P0 5ebd2aff (2026-09-10) — Rick's ruling 4, "move inside, like legacy".
// Run via `npx tsx --test src/tests/unit/multiplexer/render/notifications_section_body_placement.test.ts`.
//
// The broadcast card and the CC-session strip sit INSIDE the notifications
// section body (#notifications-pane), in legacy's order: broadcast card
// (notifications.html:540) → session strip (:658) → the list (:676). This
// reverses the Lane 0c page-chrome placement. The behavioural half — both
// survive the list renderer's mount into that pane — is in
// boot_order_mount_integrity.test.ts.
//
// Static-HTML assertions via ordered index checks on the raw markup — a full
// happy-dom parse of multiplexer.html hangs (it eagerly loads external assets).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const MUX_HTML = "src/lupin_app/static/html/multiplexer.html";

const PANE_OPEN = 'id="notifications-pane"';
const BROADCAST = 'id="broadcast-card-mount"';
const STRIP     = 'id="cc-session-strip"';
const CARDS     = 'id="sender-cards-container"';

let markup: string;
let paneStart: number;
let paneEnd: number;

before(() => {
  markup    = readFileSync(MUX_HTML, "utf8");
  paneStart = markup.indexOf(PANE_OPEN);
  paneEnd   = markup.indexOf("</section>", paneStart);
});

test("each of the three appears exactly once", () => {
  for (const id of [BROADCAST, STRIP, CARDS]) {
    assert.equal(markup.split(id).length - 1, 1, id);
  }
});

test("ruling 4: the broadcast card and the session strip are inside #notifications-pane", () => {
  assert.ok(paneStart >= 0 && paneEnd > paneStart, "#notifications-pane and its closing tag");
  for (const id of [BROADCAST, STRIP, CARDS]) {
    const i = markup.indexOf(id);
    assert.ok(i > paneStart && i < paneEnd, `${id} must sit inside #notifications-pane`);
  }
});

test("ruling 4: legacy order inside the body — broadcast card, then strip, then the sender cards", () => {
  const iBroadcast = markup.indexOf(BROADCAST);
  const iStrip     = markup.indexOf(STRIP);
  const iCards     = markup.indexOf(CARDS);
  assert.ok(iBroadcast < iStrip, "broadcast card before the strip");
  assert.ok(iStrip < iCards, "strip before the sender cards");
});
