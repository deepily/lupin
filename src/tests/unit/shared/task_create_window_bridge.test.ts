// The classic notifications page reaches the New Ticket card through `window` (row c9895403).
//
// 🔴 WHY THIS IS ITS OWN FILE. The bridge runs only when the module is evaluated WITH a
// window present, which is the page's case. Any file that imports task-create.js statically
// evaluates it before `before()` registers happy-dom, so the bridge is skipped there and a
// test in that file can only ever fail — measured twice in task_create.test.ts, including a
// `?query` re-import that returned the same cached instance. Here the module is imported for
// the FIRST time, dynamically, after registration. Each test file runs in its own process,
// so nothing else can have evaluated it first.
//
// Run: npx tsx --test src/tests/unit/shared/task_create_window_bridge.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

test( "a module evaluated with a window publishes the card, its closer and the roster helper", async () => {
  assert.equal( window.LUPIN_OPEN_NEW_TICKET_CARD, undefined, "nothing may have published it before this import" );
  const mod = await import( "../../../lupin_app/static/js/shared/task-create.js" );
  assert.equal( window.LUPIN_OPEN_NEW_TICKET_CARD, mod.openNewTicketCard );
  assert.equal( window.LUPIN_CLOSE_NEW_TICKET_CARD, mod.closeNewTicketCard );
  assert.equal( window.LUPIN_NEW_TICKET_ASSIGNEES, mod.assigneeOptions );
} );
