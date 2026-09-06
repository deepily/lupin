// 🔴 THE DOM HALF AND THE CSS HALF MUST SHIP TOGETHER, AND NOTHING ELSE CHECKS THAT.
//
// The title is rendered WHOLE and bounded VISUALLY by a two-line clamp. That is
// two artifacts in two languages:
//
//   · taskRowDisclosed.ts must emit `<span class="task-title">`
//   · css/multiplexer/task-list.css must clamp that span
//
// Ship either half alone and the result is WORSE than before the change:
//   - span, no clamp  -> long titles render at full height and blow the row open
//   - clamp, no span  -> the clamp binds on nothing; `overflow: hidden` on the
//                        cell then cuts at whatever height the row happens to be.
//     The legacy stylesheet records exactly that failure — "an accidental bound
//     looks exactly like an intended one until you measure it".
//
// ⚠️ THE UNIT TIER HAS NO LAYOUT ENGINE. Every geometry value reads 0 under
// happy-dom, so whether the clamp actually BINDS is measurable only in a real
// browser. This guard asserts the two halves are both PRESENT — which is the
// strongest claim this tier can honestly make, and it is the one that catches a
// half-shipped change.
//
// ⚠️ The duplication of this rule from static/css/task-list.css is DELIBERATE
// and PROVISIONAL — María's ruling 2026-09-05, taken so that sharing a
// stylesheet would not silently answer Rick's open question about whether "no
// code reuse between the clients" reaches CSS.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

// Resolved from THIS FILE, not from an env var — so it reads the tree the test
// actually lives in rather than whichever repo LUPIN_ROOT happens to name.
const HERE  = dirname( fileURLToPath( import.meta.url ) );
const CSS   = resolve( HERE, "../../../../lupin_app/static/css/multiplexer/task-list.css" );

test( "the TS card's stylesheet clamps .task-title — the CSS half", () => {
  const css = readFileSync( CSS, "utf8" );

  // POSITIVE CONTROL on the corpus: prove the file was read and is the one we mean.
  assert.ok( css.includes( ".task-col-title" ), "read the wrong file, or it is empty" );

  const clampBlock = css.split( /\.task-row \.task-col-title \.task-title\s*,/ )[ 1 ];
  assert.ok( clampBlock, "no clamp rule targeting .task-title" );
  const head = clampBlock.slice( 0, 400 );

  for ( const decl of [ "-webkit-line-clamp", "-webkit-box-orient", "display", "overflow" ] ) {
    assert.ok( head.includes( decl ), `clamp rule is missing ${ decl }` );
  }
  // Two lines, matching the JS card. A different number is a parity change.
  assert.ok( /-webkit-line-clamp\s*:\s*2/.test( head ), "clamp is not two lines" );

  // The epic board shares the row renderer, so it must share the clamp.
  // ⚠️ ANCHORED, NOT `includes`. A substring check passes on
  // `.task-title-ANYTHING` — measured: a mutation renaming the selector to
  // `.task-title-NOPE` SURVIVED an includes() assertion, because the original
  // is a prefix of the mutant. The class name must END here.
  assert.ok( /\.epic-row \.task-col-title \.task-title(?![\w-])/.test( css ),
             "the epic-board pane is not covered by the clamp" );

  // And it must be the SAME rule as the task-list selector, not a second block
  // that could drift: the two selectors are comma-joined in one declaration.
  assert.ok( /\.task-row \.task-col-title \.task-title(?![\w-])\s*,\s*\.epic-row \.task-col-title \.task-title(?![\w-])\s*\{/.test( css ),
             "the two panes are clamped by two separate rules — they will drift" );

  // 🔴 AND THE CAP MUST BE GONE. nowrap + text-overflow on the title cell is the
  // one-line ellipsis mechanism the clamp REPLACES; leaving it would keep the
  // title on one line and make the clamp inert.
  const cellBlock = css.split( /\.task-row \.task-col-title \{/ )[ 1 ]?.split( "}" )[ 0 ] ?? "";
  // 🔴 THE CORPUS CONTROL, WITHOUT WHICH THE TWO ASSERTIONS BELOW ARE VACUOUS.
  // `split(…)[ 1 ]` is `undefined` when the selector is absent, `?? ""` turns
  // that into the empty string, and two `!includes` on "" are BOTH TRUE. So a
  // renamed or deleted title-cell rule made this block report "the cap is gone"
  // while the cap sat live in the stylesheet — the guard could not tell "the cap
  // is gone" from "I could not find the thing I was checking".
  //
  // Raised by Tiberius 👑 in adversarial review 2026-09-05 and reproduced here
  // independently before it was accepted, two arms, one variable (does the
  // selector exist), with the cap LIVE in both: selector present → correctly
  // FAILS; selector renamed → 🔴 PASSES on "". Arm A is what makes arm B mean
  // anything, or a green in B could just mean the guard never worked.
  //
  // ⚠️ THE FILE ALREADY DID THIS FIVE LINES ABOVE, for `clampBlock`. The habit
  // was there and the second corpus was simply not given the same treatment —
  // which is why the fix is a line and the lesson is that every derived corpus
  // needs its own control, not just the first one you thought of.
  assert.ok( cellBlock, "the title-cell rule is gone — this check would pass on nothing" );
  assert.ok( !cellBlock.includes( "white-space" ),   "the one-line rule is still on the cell" );
  assert.ok( !cellBlock.includes( "text-overflow" ), "the ellipsis rule is still on the cell" );
} );

test( "the renderer emits the span the clamp needs — the DOM half", async () => {
  const { renderDisclosedRow } = await import(
    "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed" );
  const host = document.createElement( "table" );
  host.appendChild( renderDisclosedRow( { id: "t1", title: "hello", status: "queued" },
                                        "task-list", "UTC" ) );
  assert.ok( host.querySelector( ".task-col-title .task-title" ),
             "the clamp target does not exist in the rendered row" );
} );
