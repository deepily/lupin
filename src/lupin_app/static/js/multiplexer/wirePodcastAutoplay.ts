/* c8 ignore next */ // tsx phantom branch on the header line, as in podcastLinks.ts.
//
// A finished podcast starts in the Play Here player by itself (row 802c94d3).
//
// NotificationStore emits `store_podcast_autoplay_intent` for a live arrival whose abstract carries a Play Here link
// (never for a history reload, which does not go through that path). This wire decides when to show it.
//
// The rules, from Rick's ruling on the row:
//   - the setting `podcast auto play here on finish` (read through /api/config/client) turns it off;
//   - audio that is already playing is never cut off: a podcast that finishes meanwhile waits in a queue;
//   - two podcasts finishing together play one after the other, never over each other;
//   - a browser's autoplay block is answered inside the player page with a visible Play button (audio-player.html).

import type { EventBus } from "./shared/EventBus";
import type { StorePodcastAutoplayIntentPayload } from "./shared/types";

/** The `source` the player page puts on every message it posts to the page that holds it. */
export const PLAYER_MESSAGE_SOURCE = "lupin-audio-player";

/** The player the controller drives: show a podcast, say whether the player is on the page. */
export interface PodcastPlayerPort {
  show   : ( embedUrl: string, title: string ) => void;
  isOpen : () => boolean;
}

/** One podcast waiting for the player. */
interface WaitingPodcast {
  embedUrl : string;
  title    : string;
}

/**
 * Decides, for each finished podcast, whether to start it now or queue it.
 *
 * A podcast is playing when the player is on the page and its audio has not ended.
 */
export class PodcastAutoplay {
  private readonly waiting : WaitingPodcast[] = [];
  private ended = false;

  constructor( private readonly player: PodcastPlayerPort, private readonly enabled: () => boolean ) {}

  /**
   * Offer a finished podcast.
   *
   * Ensures: nothing happens while the setting is off; the podcast starts now when no audio is playing, else it queues behind it.
   */
  offer( embedUrl: string, title: string ): void {
    if ( !this.enabled() ) return;
    if ( this.player.isOpen() && !this.ended ) { this.waiting.push( { embedUrl, title } ); return; }
    this.start( { embedUrl, title } );
  }

  /** Number of podcasts waiting behind the one playing. */
  queued(): number { return this.waiting.length; }

  /** The player says its audio is playing: whatever opened it, it is busy now. */
  onPlaying(): void { this.ended = false; }

  /** The player says its audio ended: the next podcast in the queue starts. */
  onEnded(): void {
    this.ended = true;
    this.startNext();
  }

  /** The player was dismissed: it is free, so the next podcast in the queue starts. */
  onClosed(): void {
    this.ended = false;
    this.startNext();
  }

  private startNext(): void {
    const next = this.waiting.shift();
    if ( next !== undefined ) this.start( next );
  }

  private start( podcast: WaitingPodcast ): void {
    this.ended = false;
    this.player.show( podcast.embedUrl, podcast.title );
  }
}

/** The browser pieces the wire listens on, injectable so a test can drive every one of them. */
export interface PodcastAutoplayWindow {
  origin              : string;
  addEventListener    : ( type: "message", fn: ( ev: MessageEvent ) => void ) => void;
  removeEventListener : ( type: "message", fn: ( ev: MessageEvent ) => void ) => void;
}

/**
 * Connect the store's podcast intent and the player page's messages to a PodcastAutoplay.
 *
 * Requires: bus is a live EventBus; autoplay is the controller; win is the page's window.
 * Ensures: each intent is offered.
 * A same-origin message from the player page with event `playing` or `ended` is passed on, and any other message is ignored.
 * Returns a function that stops both listeners.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as TtsQueueStore.ts:221).
export function wirePodcastAutoplay( bus: EventBus, autoplay: PodcastAutoplay, win: PodcastAutoplayWindow ): () => void {
  const offBus = bus.on<StorePodcastAutoplayIntentPayload>(
    "store_podcast_autoplay_intent",
    ( e ) => { autoplay.offer( e.payload.embedUrl, e.payload.title ); },
  );
  const onMessage = ( ev: MessageEvent ): void => {
    const data = ev.data as { source?: string; event?: string } | null;
    if ( ev.origin !== win.origin || data === null || typeof data !== "object" || data.source !== PLAYER_MESSAGE_SOURCE ) return;
    if ( data.event === "playing" ) autoplay.onPlaying();
    else if ( data.event === "ended" ) autoplay.onEnded();
  };
  win.addEventListener( "message", onMessage );
  return (): void => { offBus(); win.removeEventListener( "message", onMessage ); };
}
