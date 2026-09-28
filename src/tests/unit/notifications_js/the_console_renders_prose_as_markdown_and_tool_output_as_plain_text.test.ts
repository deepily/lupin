// Legacy notifications.js — B4.13 / B4.14 and OSQ-7: the console's render rule.
//
// Row 27760534, phase 2, slice 8. Plan §3 (the render rule) and §4.
//
// FOUR ARMS PLUS A FALLBACK, and each one is a decision somebody ruled on:
//
//     text                      -> MARKDOWN, not folded
//     thinking                  -> plain text, FOLDED     (OSQ-7, Mr. Radio Option A)
//     tool_call, tool_result    -> plain text, folded      (ruling Q2)
//     anything else             -> plain text, not folded, NEVER DROPPED
//
// ───────────────────────── THE HAZARD IS MANGLING ─────────────────────────
//
// Not injection. `markdown.ts` is `marked` plus a DOMPurify allowlist and is already
// guarded elsewhere. The problem with pushing tool output through a markdown renderer is
// that it renders WRONG: `#` becomes a heading, `*` a list, an indented line a code block,
// `__x__` bold. A diff, a config file or a shell transcript comes out mangled — in the one
// surface whose entire job is to show you what actually happened.
//
// ─────────────── WHY `thinking` IS AN EXPLICIT ARM AND NOT THE DEFAULT ───────────────
//
// Its rendered result would be IDENTICAL if it fell through to the plain-text default.
// That is precisely why the ruling has to be visible in the code: OSQ-7 decided thinking is
// folded and expandable, and a ruling that leaves no trace is one the next reader re-opens.
// It also makes B4.14 meaningful — that AC tests the UNRECOGNISED arm with a kind invented
// for the test, which only says something if the known kinds are genuinely recognised.
//
// ─────────────── WHY THE DEFAULT ARM MUST RENDER RATHER THAN DROP ───────────────
//
// The mapper is deliberately open-ended (§2 item 1a) and may gain a fifth kind. A switch
// with no fallback renders NOTHING for it, silently, in a live console. Plain text is the
// safe fallback: it cannot mangle and it cannot execute.
//
// Coverage (B4.10b): notifications.js cannot be instrumented by c8 — these tests load it by
// slicing the source through `vm.runInThisContext`, outside c8's import graph. Its real gate
// is behavioural: this tier plus E2E rows B4.7/B4.8. A named exclusion, not silence.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const THINKING_FIXTURE = resolve( HERE, "../../fixtures/cc_transcript/thinking.jsonl" );

type Plan = { path: string; folded: boolean; recognised: boolean };

let planFor      : ( kind: unknown ) => Plan;
let shouldRender : ( block: unknown ) => boolean;

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );

  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) +
    "\n;globalThis.__ccConsoleRenderPlanFor = ccConsoleRenderPlanFor;" +
    "\n;globalThis.__ccConsoleShouldRender  = ccConsoleShouldRender;"
  );

  const g      = globalThis as Record<string, unknown>;
  planFor      = g.__ccConsoleRenderPlanFor as typeof planFor;
  shouldRender = g.__ccConsoleShouldRender  as typeof shouldRender;

  assert.equal( typeof planFor,      "function", "ccConsoleRenderPlanFor loaded" );
  assert.equal( typeof shouldRender, "function", "ccConsoleShouldRender loaded" );
} );


// ── prose is the ONLY markdown path ──────────────────────────────────────────

test( "assistant prose renders as markdown, unfolded", () => {
  const plan = planFor( "text" );
  assert.equal( plan.path,       "markdown" );
  assert.equal( plan.folded,     false, "prose must not start folded — it is the readable content" );
  assert.equal( plan.recognised, true );
} );

test( "no tool kind renders as markdown", () => {
  for ( const kind of [ "tool_call", "tool_result" ] ) {
    assert.equal(
      planFor( kind ).path, "plain",
      `${kind} renders through the MARKDOWN path. A tool payload carrying '#', '*' or an ` +
      `indented line comes out mangled — a heading where there was a comment, a list ` +
      `where there was a bullet of output, a code block where there was indentation.`
    );
  }
} );


// ── thinking is an EXPLICIT arm, per OSQ-7 ───────────────────────────────────

test( "thinking is RECOGNISED, not left to the default arm", () => {
  const plan = planFor( "thinking" );
  assert.equal(
    plan.recognised, true,
    "`thinking` is falling through to the unrecognised default. Its rendered output would " +
    "look identical, which is exactly why this matters: OSQ-7 RULED that thinking is " +
    "folded and expandable, and a ruling that leaves no trace in the code is one the next " +
    "reader re-litigates. It also makes B4.14 vacuous — that AC tests the unrecognised arm, " +
    "which says nothing if a known kind lands there too."
  );
} );

test( "thinking renders folded, as plain text", () => {
  const plan = planFor( "thinking" );
  assert.equal( plan.path,   "plain" );
  assert.equal( plan.folded, true, "OSQ-7: shown folded and expandable, like a tool result" );
} );

test( "tool output renders folded too, per ruling Q2", () => {
  for ( const kind of [ "tool_call", "tool_result" ] ) {
    assert.equal( planFor( kind ).folded, true, `${kind} must start collapsed` );
    assert.equal( planFor( kind ).path,   "plain" );
  }
} );


// ── B4.14: the unrecognised arm renders, and is proven to be watching ────────

test( "a kind invented for this test renders as plain text and is NOT dropped", () => {
  // B4.14's instruction in terms: prove it watches by sending a kind that cannot exist.
  const plan = planFor( "a_kind_invented_by_this_test" );
  assert.equal( plan.path,       "plain", "an unknown kind must render through the safe path" );
  assert.equal( plan.recognised, false,   "an unknown kind must not claim to be recognised" );
  assert.equal( plan.folded,     false,   "an unknown kind has no ruled fold behaviour" );
} );

test( "the unrecognised arm tolerates anything at all, without throwing", () => {
  for ( const junk of [ null, undefined, 42, "", { }, [ ], true ] ) {
    const plan = planFor( junk );
    assert.equal( plan.path,       "plain" );
    assert.equal( plan.recognised, false );
  }
} );


// ── emptiness is content; absence is not ─────────────────────────────────────

test( "an EMPTY block is still rendered", () => {
  // Measured 2026-09-27: every thinking block in primary.jsonl, and all 145 in its source
  // transcript, carry zero-length text. A "skip the empties" shortcut would drop the whole
  // thinking path while looking like a tidy-up.
  assert.equal( shouldRender( { kind : "thinking", text : "" } ), true );
  assert.equal( shouldRender( { kind : "text",     text : "" } ), true );
} );

test( "a dropped block and a block that never arrived must not be the same thing", () => {
  // The rule stated as the failure it prevents. Only a non-block is skipped.
  assert.equal( shouldRender( { kind : "text", text : "words" } ), true );
  assert.equal( shouldRender( null ),      false );
  assert.equal( shouldRender( undefined ), false );
} );


// ── driven over the CAPTURED fixture, not over invented kinds alone ──────────

test( "every kind in the captured fixture is recognised, and each gets its ruled path", () => {
  // The fixture is real, redacted transcript output (sha 97ae2607d). Reading the kinds off
  // it rather than listing them here means a mapper that starts emitting a new kind shows
  // up as an unrecognised one HERE, instead of silently rendering as plain text in
  // production. Its five blocks are: text, tool_call, tool_result, and thinking twice —
  // one empty, one 296 chars.
  const lines  = readFileSync( THINKING_FIXTURE, "utf8" ).split( "\n" ).filter( l => l.trim() );
  assert.ok( lines.length > 0, "the thinking fixture is empty — this test is measuring nothing" );

  const kinds = new Set<string>();
  for ( const line of lines ) {
    const record  = JSON.parse( line );
    const content = record?.message?.content;
    if ( !Array.isArray( content ) ) continue;
    for ( const cb of content ) {
      const wire = { text : "text", thinking : "thinking", tool_use : "tool_call",
                     tool_result : "tool_result" }[ cb?.type as string ];
      if ( wire ) kinds.add( wire );
    }
  }

  // Assert the loop found something BEFORE trusting what it found — a loop over nothing
  // passes every assertion inside it.
  assert.ok( kinds.size >= 4, `only found kinds ${[ ...kinds ].join( ", " )} in the fixture` );

  for ( const kind of kinds ) {
    assert.equal(
      planFor( kind ).recognised, true,
      `the fixture carries kind ${kind}, which this client does not recognise — it would ` +
      `render through the unrecognised fallback in production, correctly but unruled`
    );
  }
  assert.equal( planFor( "text" ).path, "markdown" );
  for ( const kind of [ "thinking", "tool_call", "tool_result" ] ) {
    assert.equal( planFor( kind ).path, "plain" );
  }
} );


// ── the populations are disjoint, so no kind takes two paths ─────────────────

test( "no kind is both a markdown kind and a folded kind", () => {
  const md     = planFor( "text" );
  assert.equal( md.path === "markdown" && md.folded, false,
    "a kind is both markdown-rendered and folded, which is two designs in one arm" );

  for ( const kind of [ "thinking", "tool_call", "tool_result" ] ) {
    assert.notEqual( planFor( kind ).path, "markdown" );
  }
} );
