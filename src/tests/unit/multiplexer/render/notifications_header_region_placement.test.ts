// Multiplexer B2 (01-B) — TTS-preview slider placement DOM-contract (T1).
//
// PLACEMENT-ONLY relocation: #tts-preview-slider-mount moves out of its orphan
// sibling spot into Sam's B3 section-header region as a SIBLING of (NOT a child
// of) #notifications-header-mount. The header renderer owns #notifications-header
// -mount via root.replaceChildren(header, historyPanel) (NotificationsHeaderRenderer
// .ts:135) — so a slider placed INSIDE that mount would be wiped on every render.
// The region wrapper makes the slider a child of the header REGION while keeping
// it a sibling of the header mount, so the renderer never touches it.
//
// Static-HTML structural assertion via ordered index checks on the raw markup —
// the same house pattern as the Python single-source HTML test (which DOM-parses
// nothing). A full happy-dom parse of multiplexer.html hangs (it eagerly loads the
// page's external script/link assets), and B2 changes no production TS (ids stay
// byte-stable → boot.ts mounts both by getElementById, position-independent → zero
// renderer/boot change), so there is no net-new coverable source — placement is a
// pure DOM-contract gate.
//
// Wrapper class/order locked with Sam (B3 author, thread 20762ed1): class
// `.notifications-header-region`; slider AFTER the header-mount; B5 owns the
// right-alignment CSS (margin-left:auto) — B2 stays structure-only.

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

// ---------------------------------------------------------------------------
// Region wrapper presence
// ---------------------------------------------------------------------------

test("B2: the .notifications-header-region wrapper exists (class + test id)", () => {
  assert.ok(markup.includes(REGION_CLASS), "section-header region wrapper class is absent");
  assert.ok(markup.includes(REGION_TESTID), "section-header region wrapper data-testid is absent");
});

// ---------------------------------------------------------------------------
// Both mounts sit INSIDE the region wrapper, in order: region opens, then the
// header-mount, then the slider-mount (slider is a child of the region, not a
// standalone sibling — the structural AC).
// ---------------------------------------------------------------------------

test("B2: header-mount then slider-mount both follow the region wrapper open tag", () => {
  const iRegion = markup.indexOf(REGION_CLASS);
  const iHeader = markup.indexOf(HEADER_MOUNT);
  const iSlider = markup.indexOf(SLIDER_MOUNT);
  assert.ok(iRegion >= 0, "region wrapper missing");
  assert.ok(iHeader >= 0, "#notifications-header-mount missing");
  assert.ok(iSlider >= 0, "#tts-preview-slider-mount missing");
  assert.ok(iRegion < iHeader, "header-mount must be inside (after) the region wrapper open tag");
  assert.ok(iRegion < iSlider, "slider-mount must be inside (after) the region wrapper open tag");
});

test("B2: slider-mount comes AFTER the header-mount (Sam's order ruling)", () => {
  const iHeader = markup.indexOf(HEADER_MOUNT);
  const iSlider = markup.indexOf(SLIDER_MOUNT);
  assert.ok(iHeader < iSlider, "slider-mount must come AFTER the header-mount");
});

// ---------------------------------------------------------------------------
// Wipe-safety: the slider is a SIBLING of the header-mount, never nested inside
// it (the renderer's replaceChildren only wipes #notifications-header-mount's own
// children). The header-mount is an empty div, so nothing is between its open and
// its first closing tag.
// ---------------------------------------------------------------------------

test("B2: slider-mount is NOT nested inside #notifications-header-mount (wipe-safe)", () => {
  const iHeader = markup.indexOf(HEADER_MOUNT);
  const headerClose = markup.indexOf("</div>", iHeader);
  assert.ok(headerClose > iHeader, "header-mount closing tag not found");
  const headerInner = markup.slice(iHeader, headerClose);
  assert.ok(
    !headerInner.includes("tts-preview-slider-mount"),
    "slider-mount must NOT be nested inside #notifications-header-mount (replaceChildren wipe)",
  );
});

// ---------------------------------------------------------------------------
// Move-don't-duplicate + legacy section order (region above the list pane).
// ---------------------------------------------------------------------------

test("B2: exactly ONE #tts-preview-slider-mount exists (moved, not duplicated)", () => {
  const occurrences = markup.split(SLIDER_MOUNT).length - 1;
  assert.equal(occurrences, 1, "slider-mount must be moved (single occurrence), not recreated");
});

test("B2: the header region sits ABOVE the notifications-list pane (legacy order)", () => {
  const iRegion = markup.indexOf(REGION_CLASS);
  const iPane = markup.indexOf(LIST_PANE);
  const iSlider = markup.indexOf(SLIDER_MOUNT);
  assert.ok(iPane >= 0, "#notifications-pane missing");
  assert.ok(iRegion < iPane, "the section-header region must precede #notifications-pane");
  assert.ok(iSlider < iPane, "the relocated slider must sit above the list pane (legacy order)");
});
