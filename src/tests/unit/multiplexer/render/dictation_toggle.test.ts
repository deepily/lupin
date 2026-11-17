// toggleDictation — the click logic the three dictation mics share (row 9cc37a94 item 32).
//
// Each test reads one option of the helper against a recorder double that records what it was told.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/dictation_toggle.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { toggleDictation, type DictationRecorderLike } from "../../../../lupin_app/static/js/multiplexer/render/dictationToggle";
import type { RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function rig( active: string | null ) {
  const calls: string[] = [];
  let started: RecordingManagerStartOptions | null = null;
  const recorder: DictationRecorderLike = {
    getActiveContextId : () => active,
    stopRecording      : async ( id ) => { calls.push( `stop:${ id }` ); },
    startRecording     : async ( opts ) => { calls.push( `start:${ opts.contextId }` ); started = opts; },
  };
  const button = document.createElement( "button" );
  const input  = document.createElement( "input" );
  return { calls, recorder, button, input, opts: () => started! };
}

test( "a first click starts recording under the context, reads the token once, and shows recording", () => {
  const r = rig( null );
  let reads = 0;
  toggleDictation( { recorder: r.recorder, authToken: () => { reads++; return "tok"; }, contextId: "c1", button: r.button, input: r.input } );
  assert.deepEqual( r.calls, [ "start:c1" ] );
  assert.equal( reads, 1 );
  assert.equal( r.opts().authToken, "tok" );
  assert.ok( r.button.classList.contains( "recording" ) );
} );

test( "a click while this context records stops it and marks the button processing", () => {
  const r = rig( "c1" );
  r.button.classList.add( "recording" );
  toggleDictation( { recorder: r.recorder, authToken: () => null, contextId: "c1", button: r.button, input: r.input } );
  assert.deepEqual( r.calls, [ "stop:c1" ] );
  assert.ok( r.button.classList.contains( "processing" ) && !r.button.classList.contains( "recording" ) );
} );

test( "without a processing set, the processing class is the guard", () => {
  const r = rig( "c1" );
  r.button.classList.add( "processing" );
  toggleDictation( { recorder: r.recorder, authToken: () => null, contextId: "c1", button: r.button, input: r.input } );
  assert.deepEqual( r.calls, [] );
} );

test( "with a processing set, the set is the guard, filled on stop and emptied on every outcome", () => {
  const r = rig( "c1" );
  const processing = new Set<string>();
  toggleDictation( { recorder: r.recorder, authToken: () => null, contextId: "c1", button: r.button, input: r.input, processing } );
  assert.ok( processing.has( "c1" ) );
  toggleDictation( { recorder: r.recorder, authToken: () => null, contextId: "c1", button: r.button, input: r.input, processing } );
  assert.deepEqual( r.calls, [ "stop:c1" ], "second click is ignored" );

  const r2 = rig( null );
  processing.add( "c2" );
  toggleDictation( { recorder: r2.recorder, authToken: () => null, contextId: "c2", button: r2.button, input: r2.input, processing: new Set() } );
  processing.add( "c3" );
  const p2 = new Set<string>( [ "c3" ] );
  toggleDictation( { recorder: r2.recorder, authToken: () => null, contextId: "c3", button: r2.button, input: r2.input, processing: p2 } );
  assert.deepEqual( r2.calls, [ "start:c2" ], "c3 was waiting, so only c2 started" );
  r2.opts().onCancel!();
  assert.ok( !r2.button.classList.contains( "recording" ) );
} );

test( "stopOther stops the other context and starts nothing; without it recording starts anyway", () => {
  const withIt = rig( "other" );
  toggleDictation( { recorder: withIt.recorder, authToken: () => null, contextId: "c1", button: withIt.button, input: withIt.input, stopOther: true } );
  assert.deepEqual( withIt.calls, [ "stop:other" ] );
  const without = rig( "other" );
  toggleDictation( { recorder: without.recorder, authToken: () => null, contextId: "c1", button: without.button, input: without.input } );
  assert.deepEqual( without.calls, [ "start:c1" ] );
} );

test( "default splice uses the caret held when recording began; the words arrive without an input event", () => {
  const r = rig( null );
  r.input.value = "ab";
  r.input.setSelectionRange( 1, 1 );
  let fired = 0;
  r.input.addEventListener( "input", () => { fired++; } );
  toggleDictation( { recorder: r.recorder, authToken: () => null, contextId: "c1", button: r.button, input: r.input } );
  r.input.value = "zzzz";
  r.input.setSelectionRange( 4, 4 );
  r.opts().onComplete!( "X" );
  assert.equal( r.input.value, "aXb" );
  assert.equal( fired, 0 );
  assert.ok( !r.button.classList.contains( "recording" ) );
} );

test( "liveCaret splices at the caret held when the words arrive, and fires an input event", () => {
  const r = rig( null );
  r.input.value = "ab";
  let fired = 0;
  r.input.addEventListener( "input", () => { fired++; } );
  toggleDictation( { recorder: r.recorder, authToken: () => null, contextId: "c1", button: r.button, input: r.input, liveCaret: true } );
  r.input.setSelectionRange( 2, 2 );
  r.opts().onComplete!( "X" );
  assert.equal( r.input.value, "abX" );
  assert.equal( fired, 1 );
} );

test( "an error resets the button and calls onError when given; without onError it only resets", () => {
  const seen: string[] = [];
  const a = rig( null );
  toggleDictation( { recorder: a.recorder, authToken: () => null, contextId: "c1", button: a.button, input: a.input, onError: ( e ) => seen.push( e.message ) } );
  a.opts().onError!( { type: "t", message: "boom", originalError: null } );
  assert.deepEqual( seen, [ "boom" ] );
  assert.ok( !a.button.classList.contains( "recording" ) );
  const b = rig( null );
  toggleDictation( { recorder: b.recorder, authToken: () => null, contextId: "c1", button: b.button, input: b.input } );
  b.opts().onError!( { type: "t", message: "boom", originalError: null } );
  assert.ok( !b.button.classList.contains( "recording" ) );
} );
