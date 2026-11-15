/* c8 ignore next */ // tsx phantom branch on the header line, as in podcastLinks.ts.
//
// The Play Here link of a finished podcast, read out of its notification's abstract (row 802c94d3).
//
// podcast_generator's play_links.py writes `[▶️ Play Here](/app/audio?path=…&embed=1)` once per language.
// The first one is the first language the job produced, and it is the one that starts by itself.

import { isEmbeddedAudioHref, podcastUrlTitle } from "../render/podcastLinks";

const AUDIO_LINK_RE = /\]\((\/app\/audio\?[^)\s]*)\)/g;

/**
 * The first Play Here URL in a markdown abstract.
 *
 * Requires: abstract is the notification's abstract text, or null or undefined.
 * Ensures: returns the `/app/audio?path=…` URL that carries `embed=1`, else null; a plain Listen link (no `embed=1`) never counts.
 */
export function firstPlayHereLink( abstract: string | null | undefined ): string | null {
  if ( typeof abstract !== "string" ) return null;
  for ( const match of abstract.matchAll( AUDIO_LINK_RE ) ) {
    if ( isEmbeddedAudioHref( match[ 1 ] as string ) ) return match[ 1 ] as string;
  }
  return null;
}

/**
 * The title a Play Here URL carries, else "Podcast".
 *
 * Requires: url is the URL firstPlayHereLink returned.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as TtsQueueStore.ts:221).
export function playHereTitle( url: string ): string {
  return podcastUrlTitle( url ) ?? "Podcast";
}

/**
 * The identity of the podcast a Play Here URL plays: its `path=` value, else the whole URL.
 *
 * One finished podcast reaches the page as two notifications (the job's own and the queue's "Podcast complete!"), with different ids
 * and the same link. The `path` is what they share, and URL-encoding it differently (`%40` against `@`) does not change it.
 *
 * Requires: url is the URL firstPlayHereLink returned.
 * Ensures: two URLs for one audio file give the same key; a URL with no `path=` is its own key.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as playHereTitle above).
export function playHereKey( url: string ): string {
  return new URLSearchParams( url.split( "?" )[ 1 ] ?? "" ).get( "path" ) ?? url;
}
