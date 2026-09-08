// 🔴 `html` DROPS A PREFIXED ATTRIBUTE HOLE, SILENTLY — AND THIS FILE PINS THE
// BEHAVIOUR SO A READER FINDS IT BEFORE A DEBUGGER DOES.
//
// FOUND THE EXPENSIVE WAY (Rio ⚡, 2026-09-07, row 470b7509). A finished-task
// row was written as
//
//     html`<tr class="finished-task-row ${ taskStatusClass( status ) }">`
//
// and its status class simply did not arrive. Nothing threw, nothing warned,
// and the row rendered — with `class="finished-task-row
// <!--lupin-html-child-0-->"`. A test asserting the class caught it; a test
// asserting "the row rendered" would not have, and the pane would have shipped
// with every terminal row untinted.
//
// ⚠️ THIS IS NOT A BUG REPORT AND THIS FILE DOES NOT ASSERT THE BEHAVIOUR IS
// RIGHT. `html.ts` says so at its own ATTR_NAME_REGEX: the pattern matches
// `<attr="` at the END of a segment, i.e. the hole must be the WHOLE attribute
// value. A prefixed hole leaves the parser mid-text rather than mid-attribute,
// so the value is treated as a CHILD and gets a child sentinel. That is a
// coherent design. What is missing is any signal at the call site.
//
// ⇒ So this file records TODAY'S behaviour, both directions, and exists to make
// a future change VISIBLE rather than to argue for one. Whether a prefixed hole
// should throw is an open ruling and is deliberately not asserted here.
//
// ⚠️ AND THE NEGATIVE LEG IS THE POINT. Asserting only that the bare form works
// would pass on an implementation that handled BOTH — it would not establish
// that the prefixed form is the one to avoid, which is the whole reason a
// reader is here.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/a_prefixed_attribute_hole_is_silently_dropped.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { html } from "../../../../lupin_app/static/js/multiplexer/render/html";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function render( frag: DocumentFragment ): string {
  const host = document.createElement( "div" );
  host.append( frag );
  return host.innerHTML;
}

test( "a WHOLE-VALUE attribute hole interpolates correctly — the positive control", () => {
  // Without this leg a failure below could mean "attribute holes do not work at
  // all", which is a different finding and would send a reader somewhere else.
  const out = render( html`<tr class="${ "task-status-wont-fix" }"></tr>` as DocumentFragment );
  assert.match( out, /class="task-status-wont-fix"/ );
  assert.ok( !out.includes( "lupin-html-child" ), "the positive control itself leaked a child sentinel" );
} );

test( "🔴 A PREFIXED ATTRIBUTE HOLE IS DROPPED, AND A CHILD SENTINEL LANDS IN THE ATTRIBUTE", () => {
  const out = render( html`<tr class="row ${ "task-status-wont-fix" }"></tr>` as DocumentFragment );

  assert.ok( !out.includes( "task-status-wont-fix" ),
    "the prefixed hole now interpolates — if that is a deliberate change to html.ts, " +
    "update this file and the comment in templates/finishedTasksTable.ts that cites it" );
  assert.match( out, /lupin-html-child/,
    "the prefixed hole neither interpolated NOR left a sentinel — html.ts changed in a third way" );
} );

test( "the same hazard applies to a SUFFIXED hole, so 'put the hole last' is not the workaround", () => {
  // Worth pinning: the natural reading of the finding above is "the hole must
  // come first". It must be the WHOLE value, and this leg is what separates the
  // two readings.
  const out = render( html`<tr class="${ "task-status-done" } row"></tr>` as DocumentFragment );
  assert.ok( !out.includes( "task-status-done row" ),
    "a suffixed hole interpolated — the rule is narrower than 'the hole must be the whole value'" );
} );

test( "the remedy compiles the value first, and it produces the class the row needs", () => {
  // This is exactly what templates/finishedTasksTable.ts does, so the remedy is
  // exercised here rather than only described in a comment.
  const rowClass = `finished-task-row ${ "task-status-wont-fix" }`;
  const out = render( html`<tr class="${ rowClass }"></tr>` as DocumentFragment );
  assert.match( out, /class="finished-task-row task-status-wont-fix"/ );
} );
