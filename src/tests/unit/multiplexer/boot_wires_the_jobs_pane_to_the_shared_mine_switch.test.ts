// Row 83c3ff74 — boot must hand the jobs pane the SHARED Mine switch and the signed-in identity.
//
// ⚠️ WHAT THIS TEST IS: a SOURCE PIN, the same kind as boot_gives_each_socket_its_own_session_id.
// boot.ts runs bootMultiplexer() at import and exports nothing, so the wiring cannot be driven
// from node. The behaviour those options produce is tested with the real stores and renderers in
// the_jobs_pane_follows_the_shared_mine_switch.test.ts; this file pins only that boot passes them.
//
// Why a pin is worth having here: every option is OPTIONAL, and a jobs pane given none of them
// works — it simply shows every user's jobs to an admin, which is the defect Rick ruled out. No
// renderer test can see a boot that forgot to pass them.
//
// Every anchor must match EXACTLY ONCE inside the createJobsPaneRenderer({ … }) call.
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_wires_the_jobs_pane_to_the_shared_mine_switch.test.ts

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

function jobsRendererCall(): string {
  const calls = [ ...BOOT_CODE.matchAll(/createJobsPaneRenderer\(\{([\s\S]*?)\n\s*\}\);/g) ];
  assert.equal(calls.length, 1, `expected exactly one createJobsPaneRenderer({ … }) call, found ${calls.length}`);
  // The capture stops before the newline ahead of `});` — add it back so the last option ends like the rest.
  return `${(calls[ 0 ] as RegExpMatchArray)[ 1 ] as string}\n`;
}

function onlyOption(name: string): string {
  const matches = [ ...jobsRendererCall().matchAll(new RegExp(`\\b${name}\\s*:\\s*([^\\n]+?),?\\n`, "g")) ];
  assert.equal(matches.length, 1, `expected option ${name} exactly once, found ${matches.length}`);
  return ((matches[ 0 ] as RegExpMatchArray)[ 1 ] as string).trim().replace(/,$/, "");
}

test("the positive control: the call is found and carries an option every version has had", () => {
  assert.equal(onlyOption("api"), "apiClient");
});

test("the jobs pane reads and sets the mode on the SAME store as the notifications header", () => {
  assert.equal(onlyOption("filterStore"), "stores.notifications");
});

test("the jobs pane is told who is an admin the same way the notifications header is", () => {
  assert.equal(onlyOption("isAdmin"), "() => authManager.isCurrentUserAdmin()");
});

test("the jobs pane is given the signed-in user id and email from the auth manager", () => {
  assert.equal(onlyOption("getCurrentUserId"),    "() => authManager.getCurrentUserId()");
  assert.equal(onlyOption("getCurrentUserEmail"), "() => authManager.getCurrentUserEmail()");
});
