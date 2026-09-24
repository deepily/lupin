/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-7 — the Direct TTS Test pane, ported from legacy's section at
// notifications.html:1375-1390 and the four handlers it wires.
//
// LEGACY BEING MIRRORED, by symbol:
//   - the listener wiring   notifications.js:1772 · :1790 · :1794 · :1798
//   - `directTTSTest()`     notifications.js:4235
//   - `testTTS( mode )`     notifications.js:~4275
//   - `playTTS`'s cache arm notifications.js:4290-4305
//   - `stopAudio()`         notifications.js:5067
//
// 🔴 THE POINT OF THE PANE IS THE BYPASS (D4). A cache HIT plays the blob here
// and now, with no POST and no `/ws/audio` round trip — no Q&A, no job
// completion, no queue. That is the one behaviour a reviewer should check first,
// because a "working" pane that quietly went through the socket would look and
// sound identical and would be measuring the server, not the cache.
//
// ⚠️ AND THE SPEC SENTENCE READS MORE ABSOLUTE THAN LEGACY IS. B-7's D4 says
// "bypassing Q&A, job completion and every WebSocket event", but both TTS doors
// stream PCM back over `/ws/audio`, so a cache MISS cannot avoid the socket in
// either client. Legacy settles it: the hit bypasses everything, the miss goes
// through `playInstantTTS`/`playReliableTTS` and uses the socket like any other
// playback. Mr. Radio ruled follow-legacy, 2026-09-23.
//
// 🔴 THE MODE IS READ FROM THE STORE, NEVER FROM `#tts-mode`. Legacy reads the
// select element because the select and the reader live in one object. Here the
// select is built by the Q&A pane (B-1), and a pane that is not mounted has no
// element — so reading the DOM would make this pane's behaviour depend on
// whether an unrelated pane happens to be on the page. `AudioStore.ttsMode()`
// is the same value with an owner.
//
// ⚠️ THE DEBUG WRITERS ARE INJECTED, NOT IMPORTED. D2 refuses an empty input
// "into the debug log and console", and that log is B-6, which is not merged at
// this branch's base. Injection is the right shape regardless — it is what lets
// a test read the refusal — and it means boot passes `console` today and
// debugSink's `log`/`error` the day B-6 lands, with one line changing.

import {
  renderSectionHeader,
  wireSectionCollapse,
} from "./templates/sectionHeader";
import type { TtsMode } from "../stores/AudioStore";

/** Legacy's placeholder, verbatim (notifications.html:1384). */
export const DIRECT_TTS_PLACEHOLDER = "Type text to speak directly...";

/** Legacy's refusal, verbatim (notifications.js:4241). */
export const DIRECT_TTS_EMPTY_REFUSAL = "Please enter text to speak";

/**
 * The test sentence, built from the MODE VALUE — legacy's `testTTS` concatenates
 * `mode` rather than holding two strings (notifications.js:~4276), so the two
 * buttons cannot drift apart and a third mode would need no new copy.
 */
export const directTtsTestText = ( mode: TtsMode ): string =>
  `This is a test of the text-to-speech system in ${ mode } mode.`;

/** What the pane needs of the page-wide audio state. */
export interface DirectTtsAudioSurface {
  ttsMode(): TtsMode;
  stop(): void;
}

/** What the pane needs to play a cached blob with no server round trip (D4). */
export interface DirectTtsCache {
  checkCache( text: string ): Promise<Blob | null>;
}

export interface DirectTtsRendererOptions {
  /** The page-wide audio state — the mode to speak in, and the halt (D3, D8). */
  audio        : DirectTtsAudioSurface;
  /** The TTS audio cache. Legacy checks it before every play; so does this (D4). */
  cache        : DirectTtsCache;
  /** Play a cached blob directly. Resolves when playback ends or fails. */
  playBlob     : ( blob: Blob ) => Promise<void>;
  /** The cache-MISS path — the ordinary request that streams over the socket. */
  speak        : ( text: string, mode: TtsMode ) => Promise<void>;
  /** Everything else this pane must halt (D8) — see the header on the mapping. */
  haltAll      : () => void;
  /** Legacy `log` — the debug panel plus the console. Injected; see the header. */
  logFn        : ( message: string ) => void;
  /** Legacy `error` — the refusal channel, because there is no inline status (D2). */
  errorFn      : ( message: string ) => void;
}

export interface DirectTtsRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
}

interface Wiring { el: HTMLElement; type: string; fn: EventListener }

class DirectTtsRendererImpl implements DirectTtsRenderer {
  private readonly opts : DirectTtsRendererOptions;

  private root        : HTMLElement | null = null;
  private inputEl     : HTMLInputElement | null = null;
  private wirings     : Wiring[] = [];
  private collapseOff : ( () => void ) | null = null;
  private mounted     = false;

  constructor( opts: DirectTtsRendererOptions ) {
    this.opts = opts;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "DirectTtsRenderer already mounted" );

    // B7 — the header is static: "🔧 Direct TTS Test (Bypass Q&A)", no count, no
    // stamp, no actions. Legacy's `<h3>` carries the glyph inline, so the glyph
    // goes in `icon` rather than into the title string.
    const header = renderSectionHeader( {
      icon   : "🔧",
      title  : "Direct TTS Test (Bypass Q&A)",
      testid : "multiplexer-direct-tts-header",
    } );

    const body = document.createElement( "div" );
    body.className = "section-content direct-tts-body";

    // 🔴 LEGACY'S CLASS, AND ONLY LEGACY'S CLASS. The first cut carried
    // `audio-controls direct-tts-controls` — legacy's name for the parity
    // oracle plus a scoped one of my own for the sheet to hang off. The pane's
    // own link guard caught it: nothing in any sheet the multiplexer links
    // defines `.audio-controls`, so the token legacy actually uses shipped
    // UNSTYLED while a token legacy has never heard of carried the rules. A
    // second class name is a second thing to keep in step for no gain.
    const controls = document.createElement( "div" );
    controls.className = "audio-controls";

    // B10 — the input and all four buttons are present from the first paint.
    // None of them is added on demand and none is hidden: legacy's markup ships
    // the five controls and never touches their presence.
    this.inputEl = document.createElement( "input" );
    this.inputEl.type        = "text";
    this.inputEl.id          = "direct-tts-input";
    this.inputEl.placeholder = DIRECT_TTS_PLACEHOLDER;
    this.inputEl.setAttribute( "data-testid", "multiplexer-direct-tts-input" );

    const speakBtn    = this.button( "direct-tts-button",  "multiplexer-direct-tts-btn",         "🔊 Speak Now" );
    const instantBtn  = this.button( "test-instant-tts",   "multiplexer-test-instant-tts-btn",   "Test Instant TTS" );
    const reliableBtn = this.button( "test-reliable-tts",  "multiplexer-test-reliable-tts-btn",  "Test Reliable TTS" );
    const stopBtn     = this.button( "stop-audio",         "multiplexer-stop-audio-btn",         "Stop Audio" );

    controls.append( this.inputEl, speakBtn, instantBtn, reliableBtn, stopBtn );
    body.appendChild( controls );
    root.replaceChildren( header.header, body );

    // D9 — guard the wiring. Legacy calls `getElementById(...).addEventListener`
    // with no null check, so a markup change takes the whole init block down with
    // a TypeError and every listener after it is silently never attached. This
    // client owns its subtree, so the elements are the ones just built — the
    // guard that matters here is the OPPOSITE one: every listener is recorded so
    // unmount can remove it, because a pane that is torn down and re-mounted
    // otherwise fires its handlers twice.
    this.wire( speakBtn,    "click", () => { void this.speakFromInput(); } );
    this.wire( instantBtn,  "click", () => { void this.speakTest( "instant" ); } );
    this.wire( reliableBtn, "click", () => { void this.speakTest( "reliable" ); } );
    this.wire( stopBtn,     "click", () => { this.stopAudio(); } );

    // D1 — NO Enter handler. Legacy wires `keydown` on `#qa-input` and not on
    // this one (notifications.js:1808), so Enter here does nothing. Stated
    // because its absence is the behaviour, and an absence is what a later
    // "improvement" adds without noticing it is a divergence.

    // B3 — session-only collapse. Persistence exists since A-2 #6; legacy does
    // not persist this section, so its absence here is a decision.
    this.collapseOff = wireSectionCollapse( root, header );

    this.root    = root;
    this.mounted = true;
  }

  unmount(): void {
    for ( const w of this.wirings ) w.el.removeEventListener( w.type, w.fn );
    this.wirings = [];
    if ( this.collapseOff !== null ) this.collapseOff();
    this.collapseOff = null;
    if ( this.root !== null ) this.root.replaceChildren();
    this.root    = null;
    this.inputEl = null;
    this.mounted = false;
  }

  /**
   * 🔊 Speak Now. Legacy `directTTSTest` (notifications.js:4235).
   *
   * Ensures:
   *   - an empty or whitespace-only input is REFUSED through `errorFn` and
   *     nothing is spoken — there is no inline status element in either client (D2)
   *   - the mode comes from the store, read at press time (D3)
   *   - the input is cleared only AFTER the play resolves (D5)
   */
  private async speakFromInput(): Promise<void> {
    /* c8 ignore next */ // defensive: a click cannot arrive while unmounted — the listener is removed there.
    if ( this.inputEl === null ) return;
    const text = this.inputEl.value.trim();

    if ( text === "" ) {
      this.opts.errorFn( DIRECT_TTS_EMPTY_REFUSAL );
      return;
    }

    const mode = this.opts.audio.ttsMode();
    this.opts.logFn( `🔊 Direct TTS Test: "${ text }" in ${ mode } mode (bypassing Q&A)` );

    await this.play( text, mode );

    // 🔴 AFTER THE AWAIT, NOT BEFORE. Legacy clears here and the ordering is the
    // behaviour: a clear before the play would wipe the operator's text even
    // when the play throws, losing what they typed to a failure they did not
    // cause. Kept as a named ordering rather than a line that happens to be last.
    this.inputEl.value = "";
  }

  /** Test Instant / Test Reliable. Legacy `testTTS` (notifications.js:~4275). */
  private async speakTest( mode: TtsMode ): Promise<void> {
    const text = directTtsTestText( mode );
    this.opts.logFn( `Testing TTS in ${ mode } mode: ${ text }` );
    await this.play( text, mode );
  }

  /**
   * The cache-first play. Legacy `playTTS`'s opening arm (notifications.js:4290).
   *
   * Ensures:
   *   - a cache HIT plays the blob and RETURNS — no POST, no socket (D4)
   *   - a cache MISS falls through to the ordinary request
   *   - a throw from either is logged and swallowed, as legacy's catch does
   */
  private async play( text: string, mode: TtsMode ): Promise<void> {
    try {
      const cached = await this.opts.cache.checkCache( text );
      if ( cached !== null ) {
        this.opts.logFn( `🎯 Cache hit! Playing cached audio for: "${ text.substring( 0, 30 ) }..."` );
        await this.opts.playBlob( cached );
        return;
      }
      this.opts.logFn( `❌ Cache miss - generating TTS for: "${ text.substring( 0, 30 ) }..."` );
      await this.opts.speak( text, mode );
    } catch {
      // Legacy's `playTTS` catch logs and returns — a failed test play must not
      // take the page down, and there is no status element to write to.
      this.opts.errorFn( `TTS playback failed in ${ mode } mode` );
    }
  }

  /** Stop Audio. Legacy `stopAudio` (notifications.js:5067). */
  private stopAudio(): void {
    this.opts.logFn( "🔴 stopAudio() CALLED" );
    this.opts.audio.stop();
    this.opts.haltAll();
    this.opts.logFn( "Audio playback stopped" );
  }

  private button( id: string, testid: string, label: string ): HTMLButtonElement {
    const btn = document.createElement( "button" );
    btn.type        = "button";
    btn.id          = id;
    btn.textContent = label;
    btn.setAttribute( "data-testid", testid );
    return btn;
  }

  private wire( el: HTMLElement, type: string, fn: EventListener ): void {
    el.addEventListener( type, fn );
    this.wirings.push( { el, type, fn } );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function createDirectTtsRenderer( opts: DirectTtsRendererOptions ): DirectTtsRenderer {
  return new DirectTtsRendererImpl( opts );
}
