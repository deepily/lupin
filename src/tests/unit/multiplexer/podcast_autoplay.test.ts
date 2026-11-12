// Row 802c94d3 — a finished podcast starts in the Play Here player by itself.
//
// Covers the link parser, the queue rules and the wire. The rules, from Rick's ruling on the row: the setting can turn it off;
// audio already playing is never cut off; two podcasts finishing together play one after the other.
//
// Run: npx tsx --test src/tests/unit/multiplexer/podcast_autoplay.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { firstPlayHereLink, playHereTitle } from "../../../lupin_app/static/js/multiplexer/shared/podcastAutoplayLink";
import { PodcastAutoplay, wirePodcastAutoplay, PLAYER_MESSAGE_SOURCE } from "../../../lupin_app/static/js/multiplexer/wirePodcastAutoplay";
import type { PodcastAutoplayWindow } from "../../../lupin_app/static/js/multiplexer/wirePodcastAutoplay";
import type { StorePodcastAutoplayIntentPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const PLAY = "/app/audio?path=%2Fio%2Fa.mp3&title=Release%20notes&embed=1";

// ── the link parser ──────────────────────────────────────────────────────────────────────────────────────
test("firstPlayHereLink: finds the Play Here URL among the card's links, skipping Listen and Download", () => {
  const abstract = `**English**: [Script](/api/io/file?path=a.md) | [Listen](/app/audio?path=a.mp3) | [▶️ Play Here](${PLAY}) | [⬇️ Download](/api/io/file?path=a.mp3&download=true)`;
  assert.equal( firstPlayHereLink( abstract ), PLAY );
});

test("firstPlayHereLink: with two languages it is the first language's link", () => {
  const second = "/app/audio?path=%2Fio%2Fb.mp3&embed=1";
  assert.equal( firstPlayHereLink( `[Play Here](${PLAY}) [Play Here](${second})` ), PLAY );
});

test("firstPlayHereLink: null for no abstract, no audio link, or an audio link without embed=1", () => {
  assert.equal( firstPlayHereLink( null ), null );
  assert.equal( firstPlayHereLink( undefined ), null );
  assert.equal( firstPlayHereLink( "just words" ), null );
  assert.equal( firstPlayHereLink( "[Listen](/app/audio?path=a.mp3)" ), null );
});

test("playHereTitle: the url's clean title, else Podcast for a missing or blank one", () => {
  assert.equal( playHereTitle( PLAY ), "Release notes" );
  assert.equal( playHereTitle( "/app/audio?path=a.mp3&embed=1" ), "Podcast" );
  assert.equal( playHereTitle( "/app/audio?path=a.mp3&title=%20%20&embed=1" ), "Podcast" );
  assert.equal( playHereTitle( "/app/audio" ), "Podcast" );
});

// ── the queue rules ──────────────────────────────────────────────────────────────────────────────────────
function rig( enabled = true ) {
  const shown: Array<[ string, string ]> = [];
  let open = false;
  const player = { show: ( url: string, title: string ) => { shown.push( [ url, title ] ); open = true; }, isOpen: () => open };
  const auto   = new PodcastAutoplay( player, () => enabled );
  return { shown, auto, close: () => { open = false; auto.onClosed(); } };
}

test("a podcast starts at once when the player is not on the page", () => {
  const r = rig();
  r.auto.offer( "u1", "One" );
  assert.deepEqual( r.shown, [ [ "u1", "One" ] ] );
});

test("with the setting off nothing starts and nothing queues", () => {
  const r = rig( false );
  r.auto.offer( "u1", "One" );
  assert.deepEqual( r.shown, [] );
  assert.equal( r.auto.queued(), 0 );
});

test("a second podcast finishing while the first plays waits, and never cuts the first off", () => {
  const r = rig();
  r.auto.offer( "u1", "One" );
  r.auto.offer( "u2", "Two" );
  r.auto.offer( "u3", "Three" );
  assert.deepEqual( r.shown, [ [ "u1", "One" ] ], "only the first is shown while it plays" );
  assert.equal( r.auto.queued(), 2 );
});

test("when the audio ends the next waiting podcast starts, in order, and an empty queue starts nothing", () => {
  const r = rig();
  r.auto.offer( "u1", "One" );
  r.auto.offer( "u2", "Two" );
  r.auto.offer( "u3", "Three" );
  r.auto.onEnded();
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1", "u2" ] );
  r.auto.onEnded();
  r.auto.onEnded();
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1", "u2", "u3" ] );
  assert.equal( r.auto.queued(), 0 );
});

test("an ended player left on the page is free: a new podcast starts at once", () => {
  const r = rig();
  r.auto.offer( "u1", "One" );
  r.auto.onEnded();
  r.auto.offer( "u2", "Two" );
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1", "u2" ] );
});

test("dismissing the player frees it: the next waiting podcast starts", () => {
  const r = rig();
  r.auto.offer( "u1", "One" );
  r.auto.offer( "u2", "Two" );
  r.close();
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1", "u2" ] );
});

test("a manual Play Here after one ended counts as busy again once it reports playing", () => {
  const r = rig();
  r.auto.offer( "u1", "One" );
  r.auto.onEnded();
  r.auto.onPlaying();
  r.auto.offer( "u2", "Two" );
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1" ], "u2 waits behind the player the user started" );
  assert.equal( r.auto.queued(), 1 );
});

// ── the wire ─────────────────────────────────────────────────────────────────────────────────────────────
function windowStub( origin = "http://lupin" ) {
  const listeners = new Set<( ev: MessageEvent ) => void>();
  const win: PodcastAutoplayWindow = {
    origin,
    addEventListener    : ( _t, fn ) => { listeners.add( fn ); },
    removeEventListener : ( _t, fn ) => { listeners.delete( fn ); },
  };
  const post = ( data: unknown, from = origin ) => { for ( const fn of [ ...listeners ] ) fn( { data, origin: from } as MessageEvent ); };
  return { win, post, count: () => listeners.size };
}

test("wire: an intent on the bus is offered; player messages drive playing and ended; foreign messages are ignored", () => {
  const bus  = createEventBusForTesting();
  const r    = rig();
  const w    = windowStub();
  const off  = wirePodcastAutoplay( bus, r.auto, w.win );
  bus.emit<StorePodcastAutoplayIntentPayload>( { type: "store_podcast_autoplay_intent", payload: { id_hash: "n1", embedUrl: "u1", title: "One" }, source: "test", ts: 0 } );
  bus.emit<StorePodcastAutoplayIntentPayload>( { type: "store_podcast_autoplay_intent", payload: { id_hash: "n2", embedUrl: "u2", title: "Two" }, source: "test", ts: 0 } );
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1" ] );

  w.post( { source: "somebody-else", event: "ended" } );          // wrong source
  w.post( { source: PLAYER_MESSAGE_SOURCE, event: "ended" }, "http://evil" );   // wrong origin
  w.post( null );                                                  // no data
  w.post( "ended" );                                               // not an object
  w.post( { source: PLAYER_MESSAGE_SOURCE, event: "blocked" } );  // a kind the page does not act on
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1" ], "none of those moved the queue" );

  w.post( { source: PLAYER_MESSAGE_SOURCE, event: "playing" } );
  w.post( { source: PLAYER_MESSAGE_SOURCE, event: "ended" } );
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1", "u2" ] );

  off();
  assert.equal( w.count(), 0, "the message listener is removed" );
  bus.emit<StorePodcastAutoplayIntentPayload>( { type: "store_podcast_autoplay_intent", payload: { id_hash: "n3", embedUrl: "u3", title: "Three" }, source: "test", ts: 0 } );
  assert.deepEqual( r.shown.map( s => s[ 0 ] ), [ "u1", "u2" ], "the bus subscription is removed" );
});
