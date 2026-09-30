/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-7 — the cached-blob playback path, ported from legacy `playAudioBlob`
// at notifications.js:5000.
//
// 🔴 :5000, NOT :4321 — THERE ARE TWO DEFINITIONS OF `playAudioBlob` IN ONE
// CLASS BODY AND THE FIRST IS DEAD. Measured 2026-09-23. The later definition
// wins in a JS class, so :4321 never runs. It matters because the two differ on
// the one line that decides whether anything is audible:
//
//     :4321 (DEAD)  audio.src = audioUrl          // the argument is a Blob
//     :5000 (LIVE)  URL.createObjectURL( blob )   // "cache now returns Blobs, not URLs"
//
// `HTMLMediaElement.src` is a DOMString, so assigning a Blob stringifies it to
// "[object Blob]", which resolves as a relative URL and fires `onerror`. A port
// taken from :4321 would ship a cache-hit path that is SILENT on every hit —
// and silent in the worst way, because the hit arm `return`s, so it never falls
// back to the server and the reject is swallowed by `playTTS`'s catch.
//
// ⚠️ THAT IS NOT A DEFECT IN LEGACY. Legacy runs :5000 and works. It is a trap
// for whoever ports it, and grep hands you :4321 first because it is first.
//
// 🔴 THIS FILE IS ALSO THE MULTIPLEXER'S `currentAudio`. Legacy's `stopAudio`
// (notifications.js:5067) tears down an HTMLAudioElement that `playAudioBlob`
// parks on `this.currentAudio`. Nothing in the multiplexer had such an element,
// because nothing had ever played a blob — `SequentialAudioManager` makes object
// URLs but only for streamed chunks, and `AudioStore` owns Web Audio sources.
// So the handle is built here, next to the only thing that creates it, rather
// than bolted onto a store that would then own a lifetime it never starts.

/** The subset of `HTMLAudioElement` this path uses — injectable for tests. */
export interface DirectAudioElement {
  src      : string;
  play(): Promise<void>;
  pause(): void;
  currentTime : number;
  onended     : ( () => void ) | null;
  onerror     : ( () => void ) | null;
}

export interface DirectTtsPlayerOptions {
  /** Test injection — the element factory. Production: `new Audio( url )`. */
  audioFactory?    : ( url: string ) => DirectAudioElement;
  createObjectURL? : ( blob: Blob ) => string;
  revokeObjectURL? : ( url: string ) => void;
}

export interface DirectTtsPlayer {
  /**
   * Play a cached blob, resolving when playback ENDS.
   *
   * Ensures:
   *   - the blob is wrapped in an object URL (never assigned raw — see header)
   *   - the URL is revoked on end, on error, and on stop — exactly once
   *   - resolves rather than rejects when the browser REFUSES autoplay, because
   *     legacy resolves there too: the audio is loaded and ready, and a rejected
   *     promise would be reported as a TTS failure that never happened
   *   - a second play stops the first, so two blobs never overlap
   */
  play( blob: Blob ): Promise<void>;
  /** Halt whatever is playing and release its URL. Legacy's `currentAudio` leg of D8. */
  stop(): void;
  /** True while an element is parked here — what `stop()` acts on. */
  isPlaying(): boolean;
}

class DirectTtsPlayerImpl implements DirectTtsPlayer {
  private readonly audioFactory    : ( url: string ) => DirectAudioElement;
  private readonly createObjectURL : ( blob: Blob ) => string;
  private readonly revokeObjectURL : ( url: string ) => void;

  private current    : DirectAudioElement | null = null;
  private currentUrl : string | null = null;

  constructor( opts: DirectTtsPlayerOptions ) {
    /* c8 ignore next 3 */ // production-default fallbacks: the real browser APIs; tests inject all three.
    this.audioFactory    = opts.audioFactory    ?? (( url ) => new Audio( url ) as unknown as DirectAudioElement);
    this.createObjectURL = opts.createObjectURL ?? (( blob ) => URL.createObjectURL( blob ));
    this.revokeObjectURL = opts.revokeObjectURL ?? (( url ) => { URL.revokeObjectURL( url ); });
  }

  play( blob: Blob ): Promise<void> {
    // A second play with the first still running would leave the first element
    // audible AND unreachable — `stop()` only holds one handle. Legacy has the
    // same single slot; stopping first is what keeps the slot honest.
    this.stop();

    const url = this.createObjectURL( blob );
    const el  = this.audioFactory( url );
    this.current    = el;
    this.currentUrl = url;

    return new Promise<void>( ( resolve ) => {
      // 🔴 RELEASE EXACTLY ONCE. `onended` and `onerror` are mutually exclusive
      // in practice but not by contract, and `stop()` can fire between either of
      // them and the microtask that resolves. Revoking twice is harmless;
      // resolving twice is not, and a leaked URL pins the blob for the page's
      // lifetime — so the guard covers both.
      let settled = false;
      const settle = (): void => {
        if ( settled ) return;
        settled = true;
        this.release( el, url );
        resolve();
      };

      el.onended = settle;
      el.onerror = settle;

      void el.play().catch( () => {
        // Autoplay refused. Legacy resolves here — "audio is ready to play" —
        // rather than reporting a failure the TTS path did not cause. The
        // element stays parked so `stop()` can still release it, and `settle`
        // will run on the eventual end or error.
      } );
    } );
  }

  stop(): void {
    if ( this.current === null ) return;
    this.current.pause();
    this.current.currentTime = 0;
    const el  = this.current;
    const url = this.currentUrl;
    this.release( el, url );
  }

  isPlaying(): boolean {
    return this.current !== null;
  }

  private release( el: DirectAudioElement, url: string | null ): void {
    el.onended = null;
    el.onerror = null;
    if ( url !== null ) this.revokeObjectURL( url );
    // Only clear the slot if THIS element still holds it — a `stop()` followed
    // by a new `play()` must not have the old element's late `onended` wipe the
    // new one's handle.
    if ( this.current === el ) {
      this.current    = null;
      this.currentUrl = null;
    }
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function createDirectTtsPlayer( opts: DirectTtsPlayerOptions = {} ): DirectTtsPlayer {
  return new DirectTtsPlayerImpl( opts );
}
