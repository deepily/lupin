// Legacy client: a finished podcast starts in the Play Here player by itself.
//
// The rules, from Rick's ruling on the row: the INI setting can turn it off; audio already playing is never cut off; two
// podcasts finishing together play one after the other. The wiring that listens for the player page's messages is
// run for real (`_initMasterDetailLayout`), once for the file, and events are dispatched on the real window.
//
// Run: npx tsx --test src/tests/unit/notifications_js/podcast_autoplay.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import "../../../lupin_app/static/js/shared/approve-link.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type AutoUI = Record<string, unknown> & {
  podcastAutoPlayHereOnFinish: boolean;
  _initMasterDetailLayout: () => void;
  handleNotificationUpdate: ( envelope: unknown ) => Promise<void>;
  _firstPlayHereLink: ( abstract: unknown ) => string | null;
  _podcastAuto?: unknown;
};

let UI: AutoUI;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  UI = Object.create( Ctor.prototype ) as AutoUI;
  UI.debug = false;
  UI.log   = (): void => {};
  UI._initMasterDetailLayout();      // wires the click and message listeners on the real document and window, once
} );

beforeEach( () => {
  document.body.replaceChildren();
  UI._podcastAuto = undefined;
  UI.podcastAutoPlayHereOnFinish = true;
} );

const PLAY_A = "/app/audio?path=%2Fio%2Fa.mp3&title=First&embed=1";
const PLAY_B = "/app/audio?path=%2Fio%2Fb.mp3&title=Second&embed=1";

function abstractWith( play: string ): string {
  return `**Podcast Activity Report**\n\n**English**: [📝 Script](/api/io/file?path=a.md) | [▶️ Play Here](${play}) | [🎧 Listen](/app/audio?path=%2Fio%2Fa.mp3)`;
}

// The notification_queue_update frame the server sends for a finished podcast job.
function arrival( id: string, play: string | null ) {
  return { notification: { id_hash: id, type: "notification", message: "Podcast complete.", abstract: play === null ? "no link here" : abstractWith( play ) } };
}

// Run the real handler. It calls the auto-play first, then carries on into card painting, which this bare instance
// has no state for and which throws; that later throw is not what these tests are about, so it is swallowed here
// and every assertion reads the overlay the auto-play left in the document.
async function deliver( envelope: unknown ): Promise<void> {
  try { await UI.handleNotificationUpdate( envelope ); } catch { /* the card painting after the auto-play has no state to run on */ }
}

function overlayFrameSrc(): string | null {
  const frame = document.querySelector( "#podcast-overlay iframe" ) as HTMLIFrameElement | null;
  return frame === null ? null : frame.getAttribute( "src" );
}

function fromPlayer( event: string, origin: string = window.location.origin, source = "lupin-audio-player" ): void {
  window.dispatchEvent( new MessageEvent( "message", { data: { source, event }, origin } ) );
}

test("a finished podcast starts in the Play Here overlay at once, with autoplay on", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  assert.equal( overlayFrameSrc(), PLAY_A + "&autoplay=1" );
  assert.equal( ( document.querySelector( ".podcast-overlay-title" ) as HTMLElement ).textContent, "First" );
});

test("with the setting off a finished podcast does nothing", async () => {
  UI.podcastAutoPlayHereOnFinish = false;
  await deliver( arrival( "n1", PLAY_A ) );
  assert.equal( overlayFrameSrc(), null );
});

test("a notification with no Play Here link, or only a Listen link, does nothing", async () => {
  await deliver( arrival( "n1", null ) );
  await deliver( { notification: { id_hash: "n2", message: "x", abstract: "[Listen](/app/audio?path=a.mp3)" } } );
  assert.equal( overlayFrameSrc(), null );
  assert.equal( UI._firstPlayHereLink( undefined ), null );
});

test("the same notification arriving twice starts it once", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  await deliver( arrival( "n1", PLAY_B ) );
  assert.equal( overlayFrameSrc(), PLAY_A + "&autoplay=1", "the replay of n1 did not replace the player" );
});

test("a podcast finishing while another plays waits, never cutting it off, then starts when the audio ends", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  await deliver( arrival( "n2", PLAY_B ) );
  assert.equal( overlayFrameSrc(), PLAY_A + "&autoplay=1", "the first keeps playing" );
  fromPlayer( "ended" );
  assert.equal( overlayFrameSrc(), PLAY_B + "&autoplay=1", "the second starts when the first ends" );
});

test("an ended player left on the page is free: the next podcast starts at once", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  fromPlayer( "ended" );
  await deliver( arrival( "n2", PLAY_B ) );
  assert.equal( overlayFrameSrc(), PLAY_B + "&autoplay=1" );
});

test("a player that reports playing is busy again, so a later podcast waits", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  fromPlayer( "ended" );
  fromPlayer( "playing" );
  await deliver( arrival( "n2", PLAY_B ) );
  assert.equal( overlayFrameSrc(), PLAY_A + "&autoplay=1" );
});

test("dismissing the player starts the next waiting podcast", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  await deliver( arrival( "n2", PLAY_B ) );
  ( document.querySelector( ".podcast-overlay-dismiss" ) as HTMLElement ).click();
  assert.equal( overlayFrameSrc(), PLAY_B + "&autoplay=1" );
  ( document.querySelector( ".podcast-overlay-dismiss" ) as HTMLElement ).click();
  assert.equal( overlayFrameSrc(), null, "nothing was waiting, so nothing starts" );
});

test("messages from another origin, another source, or about another event are ignored", async () => {
  await deliver( arrival( "n1", PLAY_A ) );
  await deliver( arrival( "n2", PLAY_B ) );
  fromPlayer( "ended", "http://evil.example" );
  fromPlayer( "ended", window.location.origin, "somebody-else" );
  fromPlayer( "blocked" );
  window.dispatchEvent( new MessageEvent( "message", { data: "ended", origin: window.location.origin } ) );
  window.dispatchEvent( new MessageEvent( "message", { data: null, origin: window.location.origin } ) );
  assert.equal( overlayFrameSrc(), PLAY_A + "&autoplay=1" );
});

test("the page reads the setting from /api/config/client and leaves it off when the fetch fails", () => {
  const source = readFileSync( NOTIFICATIONS_JS, "utf8" );
  assert.ok( source.includes( "this.podcastAutoPlayHereOnFinish = config.podcast_auto_play_here_on_finish === true;" ), "the answer sets it" );
  assert.ok( source.includes( "this.podcastAutoPlayHereOnFinish = false;" ), "a failed fetch leaves it off" );
});
