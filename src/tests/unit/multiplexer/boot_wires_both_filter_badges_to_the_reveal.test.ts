// Parity A-2 #11 (row d8ad4348) — boot must hand the SAME reveal to BOTH filter badges.
//
// ⚠️ WHAT THIS TEST IS: a SOURCE PIN, like boot_wires_action_required_to_reveal_through
// _the_toolbar. boot.ts runs bootMultiplexer() at import and exports nothing, so the
// wiring cannot be driven from node.
//
// 🔴 AND A SOURCE PIN IS ALL IT IS — WHICH IS WHY IT IS NOT THE WHOLE GUARD. The reveal's
// BEHAVIOUR was an inline arrow in boot until 2026-09-23, where a pin like this one was
// the only thing that could reach it, and a pin reads text: emptying the arrow's body
// left every character this file would have matched exactly where it was. That mutant
// survived (María 🌸). The body now lives in `render/filterSettingsReveal.ts` and is
// driven by `filter_settings_reveal.test.ts`. This file pins only the WIRING — which of
// the two things boot alone decides — and the split is deliberate.
//
// Why the wiring is worth pinning at all: `revealFilterSettings` is OPTIONAL on both
// renderers. A boot that passes it to one badge and forgets the other leaves a control
// that looks identical and does nothing, and NO renderer test can see it — each renderer
// is mounted alone and is perfectly happy without the option.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const BOOT_PATH = join(
  process.env.LUPIN_ROOT ?? process.cwd(),
  "src/lupin_app/static/js/multiplexer/boot.ts",
);
const BOOT_CODE = readFileSync(BOOT_PATH, "utf8")
  .split("\n")
  .filter((line) => !line.trimStart().startsWith("//"))
  .join("\n");

function onlyCall(factory: string): { body: string; index: number } {
  const calls = [ ...BOOT_CODE.matchAll(new RegExp(`${factory}\\(\\{([\\s\\S]*?)\\n\\s*\\}\\);`, "g")) ];
  assert.equal(calls.length, 1, `expected exactly one ${factory}({ … }) call, found ${calls.length}`);
  const m = calls[ 0 ] as RegExpMatchArray;
  return { body: `${m[ 1 ] as string}\n`, index: m.index as number };
}

test("the positive control: all three calls are found", () => {
  // Prove the instrument can locate what it claims to inspect. Without this, a renamed
  // factory makes every assertion below vacuous while the file still reports green.
  onlyCall("createNotificationsHeaderRenderer");
  onlyCall("createJobsPaneRenderer");
  onlyCall("createFilterSettingsReveal");
});

test("🔴 BOTH badge renderers are handed the reveal — one is a control that does nothing", () => {
  for (const factory of [ "createNotificationsHeaderRenderer", "createJobsPaneRenderer" ]) {
    const matches = [ ...onlyCall(factory).body.matchAll(/\brevealFilterSettings\b/g) ];
    assert.equal(matches.length, 1,
      `${factory} receives revealFilterSettings ${matches.length} times, expected exactly 1 — `
      + "a badge without it renders, takes the click, and silently does nothing");
  }
});

test("the reveal is built ONCE and shared, not written out twice", () => {
  // Legacy gives both badges one handler (showAndScrollToFilterPanel). Two constructions
  // here would be two behaviours that drift, which is the defect this pins against — and
  // `onlyCall` already fails if a second createFilterSettingsReveal({…}) appears.
  const built = [ ...BOOT_CODE.matchAll(/createFilterSettingsReveal\(/g) ];
  assert.equal(built.length, 1, `the reveal is constructed ${built.length} times, expected 1`);
});

test("the reveal reads the toolbar through a THUNK, not a captured reference", () => {
  // boot constructs the badge renderers BEFORE the section-toolbar renderer, so a
  // captured `sectionToolbarRenderer` would be read in its temporal dead zone. The
  // ordering assertion below is what makes this one load-bearing rather than stylistic.
  const body = onlyCall("createFilterSettingsReveal").body;
  assert.match(body, /toolbar\s*:\s*\(\)\s*=>\s*sectionToolbarRenderer\s*,?/);
});

test("🔴 the badge renderers really are constructed BEFORE the toolbar they reveal through", () => {
  // The premise of the thunk. If boot is ever reordered so the toolbar comes first, the
  // thunk stops being necessary — and, more to the point, if this ordering holds and
  // someone "simplifies" the thunk to a direct reference, the reveal reads a const in
  // its TDZ. This asserts the ordering that makes the thunk the correct shape.
  const toolbarIdx = onlyCall("createSectionToolbarRenderer").index;
  for (const factory of [ "createNotificationsHeaderRenderer", "createJobsPaneRenderer" ]) {
    assert.ok(onlyCall(factory).index < toolbarIdx,
      `${factory} is constructed AFTER the section toolbar — the reveal's toolbar thunk `
      + "can be simplified to a direct reference, and this test should be re-derived");
  }
});
