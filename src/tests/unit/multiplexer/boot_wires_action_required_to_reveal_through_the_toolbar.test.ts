// Parity A-2 #2b (row 43338b1b) — boot must let an arriving prompt reveal Action Required
// through the section toolbar.
//
// ⚠️ WHAT THIS TEST IS: a SOURCE PIN, like boot_wires_the_jobs_pane_to_the_shared_mine_switch.
// boot.ts runs bootMultiplexer() at import and exports nothing, so the wiring cannot be driven
// from node. The behaviour is tested with the real renderers in action_required_auto_reveal and
// section_toolbar_renderer; this file pins only that boot connects them.
//
// Why a pin is worth having: `revealSection` is OPTIONAL. Without it an arrival still
// un-collapses and scrolls, but a section the operator hid stays hidden with a prompt waiting
// inside — the defect B6 names — and no renderer test can see a boot that forgot to pass it.

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

test("the positive control: both calls are found and the action-required one carries its store", () => {
  assert.match(onlyCall("createActionRequiredRenderer").body, /stores\s*:\s*\{\s*actionRequired: stores\.actionRequired\s*\}/);
  onlyCall("createSectionToolbarRenderer");
});

test("the action-required renderer reveals through the toolbar's showSection, naming its own section", () => {
  const matches = [ ...onlyCall("createActionRequiredRenderer").body.matchAll(/\brevealSection\s*:\s*([^\n]+?),?\n/g) ];
  assert.equal(matches.length, 1, `expected revealSection exactly once, found ${matches.length}`);
  assert.equal(
    ((matches[ 0 ] as RegExpMatchArray)[ 1 ] as string).trim().replace(/,$/, ""),
    '() => sectionToolbarRenderer.showSection("action-required-section")',
  );
});

test("the toolbar renderer is constructed before the action-required renderer that closes over it", () => {
  assert.ok(
    onlyCall("createSectionToolbarRenderer").index < onlyCall("createActionRequiredRenderer").index,
    "a prompt arriving during boot would hit the toolbar const in its temporal dead zone",
  );
});
