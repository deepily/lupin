// Multiplexer notifications header region — the static page contract.
//
// HISTORY: B2 (01-B) moved #tts-preview-slider-mount out to a SIBLING of
// #notifications-header-mount so a header render could not wipe it, and this file
// pinned that layout. Rick's 2026-09-10 ruling 3 (P0 5ebd2aff, "legacy title,
// slider inline") reverses it: the slider sits INSIDE the header bar, as legacy
// notifications.html:489-513 does. NotificationsHeaderRenderer now creates the
// slot itself — its replaceChildren runs only on mount/unmount, never on refresh
// — so the static page must NOT declare it: a second copy would be a duplicate id
// that getElementById could resolve instead of the live slot.
//
// The behavioural half (slot inside the bar, first action, survives a refresh,
// swallows clicks) lives in notifications_header_renderer.test.ts.
//
// Static-HTML structural assertions via ordered index checks on the raw markup —
// a full happy-dom parse of multiplexer.html hangs (it eagerly loads the page's
// external script/link assets).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const MUX_HTML = "src/lupin_app/static/html/multiplexer.html";

const REGION_CLASS  = 'class="notifications-header-region"';
const REGION_TESTID = 'data-testid="multiplexer-notifications-header-region"';
const HEADER_MOUNT  = 'id="notifications-header-mount"';
const SLIDER_MOUNT  = 'id="tts-preview-slider-mount"';
const LIST_PANE     = 'id="notifications-pane"';

let markup: string;

before(() => {
  markup = readFileSync(MUX_HTML, "utf8");
});

test("the .notifications-header-region wrapper exists (class + test id)", () => {
  assert.ok(markup.includes(REGION_CLASS), "section-header region wrapper class is absent");
  assert.ok(markup.includes(REGION_TESTID), "section-header region wrapper data-testid is absent");
});

test("the header mount sits inside the region wrapper", () => {
  const iRegion = markup.indexOf(REGION_CLASS);
  const iHeader = markup.indexOf(HEADER_MOUNT);
  assert.ok(iRegion >= 0, "region wrapper missing");
  assert.ok(iHeader >= 0, "#notifications-header-mount missing");
  assert.ok(iRegion < iHeader, "header-mount must be inside (after) the region wrapper open tag");
});

test("ruling 3: the page declares NO #tts-preview-slider-mount — the header renderer produces it inside the bar", () => {
  assert.equal(markup.split(SLIDER_MOUNT).length - 1, 0, "a static slider mount would duplicate the header's own slot id");
});

test("the header region sits ABOVE the notifications-list pane (legacy order)", () => {
  const iRegion = markup.indexOf(REGION_CLASS);
  const iPane   = markup.indexOf(LIST_PANE);
  assert.ok(iPane >= 0, "#notifications-pane missing");
  assert.ok(iRegion < iPane, "the section-header region must precede #notifications-pane");
});
