// Row c9fafb9d — boot hands the request store to BOTH boards and starts its poll (Tiffany F1).
//
// 🔴 WHY A SOURCE-LEVEL CHECK. No test in this tree boots `bootMultiplexer` — it is unexported
// and reaches every transport — so the established guard for boot wiring reads boot.ts, as
// boot_gives_each_socket_its_own_session_id does. That is weaker than driving the app: it
// restates the wiring rather than exercising it. What it buys is the three mutants Tiffany
// measured surviving every other test (W1 no poll, W2/W3 a board without the store):
//
//   W2/W3 are the worst of them. The shared row draws a pending chip whether or not the pane
//   was given a store, so a pane built without one shows Approve and Deny that do nothing.
//
// Each check anchors on ONE renderer's construction block, found by its factory name, so a
// `requestStore` line in the wrong block cannot satisfy it.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Resolved from THIS file, never from LUPIN_ROOT: an inherited root names the main checkout,
// and from a worktree this test would then read — and pass or fail on — another tree's boot.ts.
const BOOT_CODE = readFileSync(
  resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../lupin_app/static/js/multiplexer/boot.ts" ), "utf8",
).split( "\n" ).filter( ( line ) => !line.trimStart().startsWith( "//" ) ).join( "\n" );

/** The text of `const x = <factory>({ … });`, located by the factory name, exactly once. */
function constructionBlock( factory: string ): { text: string; end: number } {
  const starts = [ ...BOOT_CODE.matchAll( new RegExp( `${ factory }\\(\\{`, "g" ) ) ];
  assert.equal( starts.length, 1, `expected exactly one ${ factory }({ in boot.ts, found ${ starts.length }` );
  const start = starts[ 0 ]!.index!;
  const end   = BOOT_CODE.indexOf( "});", start );
  assert.ok( end > start, `${ factory } block has no end` );
  return { text: BOOT_CODE.slice( start, end ), end };
}

/** Where `<name>.mount(` is called, exactly once. */
function mountAt( renderer: string ): number {
  const hits = [ ...BOOT_CODE.matchAll( new RegExp( `${ renderer }\\.mount\\(`, "g" ) ) ];
  assert.equal( hits.length, 1, `expected exactly one ${ renderer }.mount( call` );
  return hits[ 0 ]!.index!;
}

const WIRED = /requestStore\s*:\s*stores\.taskRequests\s*,/;

test( "positive control: the block finder reads real blocks, and the pattern can fail", () => {
  const taskList = constructionBlock( "createTaskListRenderer" ).text;
  assert.ok( taskList.includes( "lookupFetch" ), "the task list block was not found" );
  assert.equal( WIRED.test( "requestStore : stores.taskList," ), false, "the pattern matches the wrong store" );
} );

test( "the task list is built WITH the request store (W3)", () => {
  assert.match( constructionBlock( "createTaskListRenderer" ).text, WIRED );
} );

test( "the holding area is built WITH the request store (W2)", () => {
  assert.match( constructionBlock( "createHoldingAreaRenderer" ).text, WIRED );
} );

test( "the badge poll starts, once, AFTER both boards mount (W1)", () => {
  const polls = [ ...BOOT_CODE.matchAll( /stores\.taskRequests\.startPolling\(\);/g ) ];
  assert.equal( polls.length, 1, "the request store's poll is not started exactly once" );
  const at = polls[ 0 ]!.index!;
  assert.ok( at > mountAt( "taskListRenderer" ),    "the poll starts before the task list mounts" );
  assert.ok( at > mountAt( "holdingAreaRenderer" ), "the poll starts before the holding area mounts" );
} );
