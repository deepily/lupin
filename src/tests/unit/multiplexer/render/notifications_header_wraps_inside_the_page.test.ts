// Row 98305d96 — the notifications header bar must WRAP, or the admin Mine switch pushes it
// past the page.
//
// Measured in Chrome as admin, bundle 78cc06b7250b: with the switch in the bar the section ran
// 141px past main.container and the title stacked to three lines; hiding only the switch
// brought it back inside. With these rules the section ends 20px inside, the title is one
// line, the badge sits 8px after the title, and the controls are right-aligned on row two.
// Wrap alone was measured too: it fits, but flings the badge 250px from the title.
//
// ⚠️ THE UNIT TIER HAS NO LAYOUT ENGINE, so this cannot measure the overflow. It pins the rules
// that fix it, and that they stay SCOPED to this region: the shared .section-header in
// shared/notifications-surface.css also dresses legacy and every other pane.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Resolved from THIS FILE, so it reads the tree the test lives in.
const HERE   = dirname( fileURLToPath( import.meta.url ) );
const HEADER = resolve( HERE, "../../../../lupin_app/static/css/multiplexer/notifications-header.css" );
const SHARED = resolve( HERE, "../../../../lupin_app/static/css/shared/notifications-surface.css" );

// Comments out, so a note that MENTIONS a rule can never satisfy the assertion for it.
const stripComments = ( css: string ): string => css.replace( /\/\*[\s\S]*?\*\//g, "" );

// The declaration block for an exact selector, or null. The selector must run straight into
// the brace, so `.section-header` cannot match the start of `.section-header-actions`.
function blockFor( css: string, selector: RegExp ): string | null {
  const m = new RegExp( `(?:^|\\})\\s*${ selector.source }\\s*\\{([^}]*)\\}` ).exec( css );
  return m === null ? null : m[ 1 ];
}

const BAR     = /\.notifications-header-region \.section-header/;
const ACTIONS = /\.notifications-header-region \.section-header-actions/;

test( "the notifications header bar wraps and packs left, so the badge stays beside the title", () => {
  const css = stripComments( readFileSync( HEADER, "utf8" ) );
  // Positive control on the corpus: the file was read and is the one we mean.
  assert.ok( css.includes( ".notifications-header-region" ), "read the wrong file, or it is empty" );

  const bar = blockFor( css, BAR );
  assert.notEqual( bar, null, "no rule for .notifications-header-region .section-header" );
  assert.match( bar as string, /flex-wrap\s*:\s*wrap\s*;/, "the bar does not wrap" );
  assert.match( bar as string, /justify-content\s*:\s*flex-start\s*;/, "the bar does not pack left; the badge drifts away from the title" );
} );

test( "the header's controls wrap and stay right-aligned on their own row", () => {
  const css = stripComments( readFileSync( HEADER, "utf8" ) );
  const actions = blockFor( css, ACTIONS );
  assert.notEqual( actions, null, "no rule for .notifications-header-region .section-header-actions" );
  assert.match( actions as string, /flex-wrap\s*:\s*wrap\s*;/, "the controls do not wrap" );
  assert.match( actions as string, /margin-inline-start\s*:\s*auto\s*;/, "the controls are not pushed right" );
} );

test( "the shared .section-header, which legacy and every pane use, is left alone", () => {
  const shared = stripComments( readFileSync( SHARED, "utf8" ) );
  assert.ok( shared.includes( ".section-header" ), "read the wrong shared sheet, or it is empty" );
  const bare = blockFor( shared, /\.section-header/ );
  assert.notEqual( bare, null, "the shared .section-header rule moved; re-check the scope claim" );
  assert.doesNotMatch( bare as string, /flex-wrap/, "the shared bar wraps now, which changes every pane" );
  assert.match( bare as string, /justify-content\s*:\s*space-between/, "the shared bar's packing changed" );
} );

test( "the block finder is not vacuous: it finds a rule that exists and misses one that does not", () => {
  assert.match( blockFor( ".notifications-header-region .section-header { flex-wrap : wrap; }", BAR ) as string, /flex-wrap/ );
  // A longer selector that merely starts the same way is a different rule.
  assert.equal( blockFor( ".notifications-header-region .section-header-actions { flex-wrap : wrap; }", BAR ), null );
  // A comment naming the rule is not the rule.
  assert.equal( blockFor( stripComments( "/* .notifications-header-region .section-header { flex-wrap : wrap; } */" ), BAR ), null );
} );
