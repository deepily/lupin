// P0 (Rick's broadcast a090b845, 2026-09-10) — the multiplexer's TTS preview limiter.
//
// truncateAtBoundary / computeTtsPreview are ports of legacy notifications.js
// `_truncateAtBoundary` / `_computeTTSPreview`. The truncation cases are legacy's own
// `_tts_quick_self_test` inputs and predicates, carried over verbatim so the port is
// checked against the producer's fixtures, not new ones written to fit.
//
// Run: npx tsx --test src/tests/unit/multiplexer/tts_preview.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { computeTtsPreview, truncateAtBoundary } from "../../../lupin_app/static/js/multiplexer/shared/ttsPreview";
import {
  DEFAULT_TTS_FRACTION,
  LEGACY_TTS_FRACTION_KEY,
  resolveLiveFraction,
} from "../../../lupin_app/static/js/multiplexer/render/TtsPreviewSliderRenderer";

// ---------------------------------------------------------------------------
// truncateAtBoundary — legacy _tts_quick_self_test, verbatim
// ---------------------------------------------------------------------------

const LIST = "Affected modules below:\nrunning_fifo_queue\ntodo_fifo_queue\nqueue_consumer\nagentic_job_factory\napi_resource_manager";

const LEGACY_CASES: Array<{ name: string; input: string; frac: number; expect: ( got: string ) => boolean }> = [
  { name: "Newline boundary — punctuation-free list cuts at a newline", input: LIST, frac: 0.25,
    expect: ( got ) => got === "Affected modules below:\nrunning_fifo_queue" },
  { name: "Sentence terminal — prose cuts at a period",
    input: "First sentence here. Second sentence here. Third sentence here. Fourth one here.", frac: 0.25,
    expect: ( got ) => got.endsWith( "." ) && got.length < 80 },
  { name: "Decimal is not a false boundary",
    input: "The value of pi is 3.14159 and it matters here. Next part follows after now.", frac: 0.25,
    expect: ( got ) => got.includes( "3.14159" ) },
  { name: "Em-dash is a boundary",
    input: "Alpha beta gamma delta — epsilon zeta eta theta iota kappa lambda mu now.", frac: 0.25,
    expect: ( got ) => got.endsWith( "—" ) },
  { name: "Hyphen-minus is NOT a boundary",
    input: "The bug-fix-queue and end-to-end pipeline ran fine. Second sentence here now.", frac: 0.1,
    expect: ( got ) => got.indexOf( "-" ) !== -1 && got.endsWith( "." ) },
  { name: "Abbreviation period is not a false boundary",
    input: "Mr. Radio reviewed the plan. Then the team shipped it after lunch today.", frac: 0.1,
    expect: ( got ) => got.startsWith( "Mr. Radio" ) },
  { name: "No-boundary run-on falls back to a word boundary",
    input: "one two three four five six seven eight nine ten eleven twelve thirteen", frac: 0.25,
    expect: ( got ) => got.split( " " ).length >= 2 && got.length < 30 && !/\s$/.test( got ) },
  { name: "Fraction >= 1 returns the whole text", input: "Alpha. Beta. Gamma.", frac: 1,
    expect: ( got ) => got === "Alpha. Beta. Gamma." },
];

test( "the legacy self-test runs all 8 cases", () => {
  assert.equal( LEGACY_CASES.length, 8 );
} );

for ( const c of LEGACY_CASES ) {
  test( `truncateAtBoundary — legacy case: ${c.name}`, () => {
    const got = truncateAtBoundary( c.input, c.frac );
    assert.ok( c.expect( got ), `got ${JSON.stringify( got )}` );
  } );
}

test( "truncateAtBoundary — empty text is empty", () => {
  assert.equal( truncateAtBoundary( "", 0.5 ), "" );
} );

test( "truncateAtBoundary — no boundary and no later space returns the whole (trimmed) text", () => {
  assert.equal( truncateAtBoundary( "supercalifragilistic ", 0.9 ), "supercalifragilistic" );
  assert.equal( truncateAtBoundary( "one two threefourfivesix", 0.5 ), "one two threefourfivesix" );
} );

test( "truncateAtBoundary — a terminal at the very end counts as a boundary", () => {
  assert.equal( truncateAtBoundary( "alpha beta gamma delta!", 0.5 ), "alpha beta gamma delta!" );
} );

// ---------------------------------------------------------------------------
// computeTtsPreview — legacy _computeTTSPreview stages
// ---------------------------------------------------------------------------

const LONG = "First sentence of a long agent report. Second sentence carries more detail. "
           + "Third sentence goes on further still. Fourth sentence closes it out now.";

test( "computeTtsPreview — slider at 0 skips, checked before the feature flag", () => {
  assert.deepEqual( computeTtsPreview( LONG, { fraction: 0, enabled: false, minChars: 100 } ), { stage: "skip", text: "" } );
  assert.deepEqual( computeTtsPreview( LONG, { fraction: 0, enabled: true,  minChars: 100 } ), { stage: "skip", text: "" } );
} );

test( "computeTtsPreview — disabled, 100%, or too short plays in full", () => {
  assert.deepEqual( computeTtsPreview( LONG, { fraction: 0.25, enabled: false, minChars: 100 } ), { stage: "full", text: LONG } );
  assert.deepEqual( computeTtsPreview( LONG, { fraction: 1,    enabled: true,  minChars: 100 } ), { stage: "full", text: LONG } );
  assert.deepEqual( computeTtsPreview( "Short one. Two.", { fraction: 0.25, enabled: true, minChars: 100 } ),
                    { stage: "full", text: "Short one. Two." } );
} );

test( "computeTtsPreview — a partial slider on long text plays the boundary cut", () => {
  // LONG is 148 chars; 25% puts the scan at index 37, which is the first period.
  assert.deepEqual( computeTtsPreview( LONG, { fraction: 0.25, enabled: true, minChars: 100 } ),
                    { stage: "preview", text: "First sentence of a long agent report." } );
} );

test( "computeTtsPreview — a cut that reaches the end plays in full", () => {
  const oneSentence = "This single sentence is deliberately long enough to pass the minimum character gate easily.";
  assert.deepEqual( computeTtsPreview( oneSentence, { fraction: 0.5, enabled: true, minChars: 10 } ),
                    { stage: "full", text: oneSentence } );
} );

// ---------------------------------------------------------------------------
// resolveLiveFraction — which slider value is in force at an arrival
// ---------------------------------------------------------------------------

function sharedWith( raw: string | null ) {
  return { getItem: ( k: string ) => ( k === LEGACY_TTS_FRACTION_KEY ? raw : null ), setItem: () => {} };
}

test( "resolveLiveFraction — the legacy page's shared key wins, including 0", () => {
  assert.equal( resolveLiveFraction( sharedWith( "0" ), 1, 1, 1 ), 0 );
  assert.equal( resolveLiveFraction( sharedWith( "0.125" ), 0.5, 0.75, 1 ), 0.125 );
} );

test( "resolveLiveFraction — then the mounted slider, then the stored override, then the INI default", () => {
  assert.equal( resolveLiveFraction( sharedWith( null ), 0.5, 0.75, 1 ), 0.5 );
  assert.equal( resolveLiveFraction( null, null, 0.75, 1 ), 0.75 );
  assert.equal( resolveLiveFraction( null, null, undefined, 0.3 ), 0.3 );
  assert.equal( resolveLiveFraction( null, null, undefined, "junk" ), DEFAULT_TTS_FRACTION );
} );
