// 🔴 A STATE NOBODY CAN SEE IS NOT A CONTROL.
//
// RICK, 2026-09-03: "it is permanently disabled. No change in value re-enables the update
// button." He was right. So were the tests. They were measuring different things.
//
// MEASURED IN HIS BROWSER, through the extension, on the live page: an ENABLED
// `.task-priority-update` and a DISABLED one returned identical computed style —
// opacity 1 on both, same background, same colour, and `cursor: pointer` on BOTH. The
// button flips `disabled` correctly on every change. Nothing on screen ever said so.
//
// ⚠️ EVERY GUARD WE HAD READ THE PROPERTY. Seven arms in row_control_redesign, twelve
// per-pane arms, and my own repaint file all assert `button.disabled`, watch it flip, and
// go green. Not one asked whether a human could SEE the difference. That is the whole
// defect: `disabled` is a fact about the DOM, and the operator's evidence is pixels.
//
// ⇒ SO THIS FILE ASSERTS THE VISIBLE DIFFERENCE, AND NOTHING ELSE. It deliberately does
// not check `.disabled` — that property is already covered to death, and adding it here
// would let this file pass on the strength of the assertion that failed us.
//
// ⚠️ AND WHY THE STYLESHEET IS PARSED RATHER THAN GREPPED. happy-dom does not apply an
// external stylesheet, so a plain `getComputedStyle` in this harness returns the same
// answer whatever the CSS says — the exact blindness this file exists to remove. The
// rules are read out of the real stylesheet and matched against the real rendered
// markup, so the assertion is about the two artifacts that ship, not about a string.
//
// Run: npx tsx --test src/tests/unit/notifications_js/a_disabled_control_must_LOOK_disabled.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const TASK_LIST_CSS    = resolve( HERE, "../../../lupin_app/static/css/task-list.css" );

/** The declarations of one CSS rule, by exact selector. Returns null when absent. */
function ruleFor( css: string, selector: string ): Record<string, string> | null {
  // ⚠️ COMMENTS ARE STRIPPED FIRST, AND THAT IS NOT TIDINESS. The selector capture is
  // "everything between the previous `}` and this `{`", which SWALLOWS a preceding
  // comment block. Every rule in this stylesheet is documented, so without this the
  // lookup missed `.task-action-btn:disabled` and the guard reported the rule absent
  // WHILE IT WAS SITTING IN THE FILE — a fixture defect wearing the costume of the
  // defect under test, caught only because the fix was already applied when it fired.
  const stripped = css.replace( /\/\*[\s\S]*?\*\//g, "" );
  // Selectors in this file are written with spaces inside parens; normalise whitespace
  // so the lookup does not depend on formatting.
  const norm = ( s: string ): string => s.replace( /\s+/g, " " ).trim();
  for ( const m of stripped.matchAll( /([^{}]+)\{([^{}]*)\}/g ) ) {
    if ( norm( m[ 1 ] ) !== norm( selector ) ) continue;
    const decls: Record<string, string> = {};
    for ( const d of m[ 2 ].split( ";" ) ) {
      const i = d.indexOf( ":" );
      if ( i < 0 ) continue;
      decls[ norm( d.slice( 0, i ) ) ] = norm( d.slice( i + 1 ) );
    }
    return decls;
  }
  return null;
}

let css: string;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  css = readFileSync( TASK_LIST_CSS, "utf8" );
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

let host: HTMLElement;

beforeEach( () => {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui: any = Object.create( Ctor.prototype );
  ui.debug = false; ui.log = (): void => {}; ui.error = (): void => {};
  ui.TASK_TITLE_TRUNCATE_LEN = 60; ui.queueSessionId = "test-session";

  host = document.createElement( "div" );
  host.innerHTML = ui._taskActionsCell( {
    id: "aaaa1111-2222-3333-4444-555566667777", item_class: "task",
    title: "row", status: "queued", priority: "P0", project: "lupin",
  } );
} );

test( "POSITIVE CONTROL: the stylesheet parses and this harness can find a known rule", () => {
  assert.ok( ruleFor( css, ".task-action-btn" ),
    "the base .task-action-btn rule was not found — the parser or the file moved, and " +
    "every 'rule is missing' assertion below would then be reporting on my regex rather " +
    "than on the stylesheet" );
  assert.equal( ruleFor( css, ".this-selector-does-not-exist" ), null,
    "the lookup returns a rule for a selector that is not in the file — it matches too " +
    "loosely, so a present-rule assertion proves nothing" );
  // 🔴 THE ARM THAT CAUGHT THIS HARNESS BEING WRONG. Every rule here is documented, and
  // the selector capture swallows a preceding comment unless they are stripped. Without
  // this control the guard reports a rule missing while it is plainly in the file — and
  // it reports it in exactly the words of the real defect, so nobody would look twice.
  assert.ok( ruleFor( css, ".task-verb-select:disabled" ),
    "a rule that sits directly under a comment block was not found — the parser is " +
    "including the comment in the selector, so EVERY documented rule reads as absent" );
} );

test( "🔴 THE UPDATE BUTTON MUST LOOK DIFFERENT WHEN IT IS DISABLED", () => {
  const button = host.querySelector( ".task-priority-update" ) as HTMLButtonElement;
  assert.ok( button, "no Update button rendered — nothing below is about anything" );
  assert.equal( button.disabled, true, "it renders disabled; the question is whether that SHOWS" );

  const rule = ruleFor( css, ".task-action-btn:disabled" );
  assert.ok( rule, (
    "there is NO `.task-action-btn:disabled` rule in task-list.css, so a disabled Update " +
    "button renders identically to a live one — measured in a real browser: opacity 1 on " +
    "both, same colour, same background, `cursor: pointer` on both. The operator has no " +
    "way to tell the control woke up, which is exactly what was reported as a button that " +
    "never enables. Its two siblings in the same cell, .task-action-input:disabled and " +
    ".task-verb-select:disabled, both carry one."
  ) );

  assert.ok( Number( rule![ "opacity" ] ) < 1,
    `the disabled rule exists but does not dim it (opacity ${rule!["opacity"]}) — a rule ` +
    `that changes nothing visible is the same defect with a stylesheet entry over it` );
  assert.equal( rule![ "cursor" ], "not-allowed",
    "the disabled button still advertises `cursor: pointer`, which invites the click that " +
    "does nothing — the interaction that was reported" );
} );

test( "THE WHOLE CELL IS CONSISTENT — every control in it says when it is unavailable", () => {
  // The bug was one control being left out of a convention the others followed. Assert
  // the convention across the cell rather than re-asserting the one member that broke it,
  // so the next control added here is held to the same rule.
  const conventions = [ ".task-action-input:disabled", ".task-verb-select:disabled",
                        ".task-action-btn:disabled" ];
  const missing = conventions.filter( sel => ruleFor( css, sel ) === null );
  assert.deepEqual( missing, [],
    `these controls give no visible sign of being unavailable: ${missing.join( ", " )}. ` +
    `Every interactive control in the actions cell must dim and refuse the cursor when ` +
    `disabled — a control that looks live and does nothing is worse than one that is absent.` );

  for ( const sel of conventions ) {
    const r = ruleFor( css, sel )!;
    assert.ok( Number( r[ "opacity" ] ) < 1, `${sel} does not dim (opacity ${r["opacity"]})` );
    assert.equal( r[ "cursor" ], "not-allowed", `${sel} does not refuse the cursor` );
  }
} );
