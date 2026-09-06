/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Epic-board card — EpicStoriesStore (row 87812328).
//
// The hand-maintained epic titles and one-line stories, from
// `GET /api/epic-stories`.
//
// 🔴 MEMOIZED ONE-SHOT, NEVER POLLED, AND THE MEMO COVERS THE FAILURE CASE TOO.
// The endpoint serves a HAND-EDITED file, not live state, so a timer would ask
// the same question of the same static answer forever. And a DOWN endpoint must
// not be retried on every render — that is why `fetched` is set BEFORE the
// request rather than after a success. Carbon copy of notifications.js
// `fetchEpicStories`, whose docstring says exactly this.
//
// 🔴 EVERY FAILURE RESOLVES TO `{}`, NEVER A THROW AND NEVER A SENTINEL. A
// missing story is a NUDGE, not an error: the board renders de-slugged epic
// names and no story rows, which is a complete and readable board. Failing the
// pane over absent prose would take down the whole epic view for a file nobody
// has got round to editing.
//
// ⚠️ IT EMITS NO EVENT AND THE BOARD SUBSCRIBES TO NONE. The renderer reads
// this store through a `storiesFn` at paint time, so the first paint after the
// fetch resolves picks the titles up on the task list's own tick. Adding an
// event here would give the epic board a second thing to repaint on — the
// drift the shared composite exists to prevent.

import type { EpicStories } from "../render/epicBoardModel";

/** Narrowed ApiClient surface — this store only ever reads. */
export interface EpicStoriesApiClient {
  get<T>( path: string ): Promise<T>;
}

export const EPIC_STORIES_ENDPOINT = "/api/epic-stories";

export interface EpicStoriesStore {
  /** The map, `{}` until a fetch resolves and `{}` forever if one fails. */
  stories(): EpicStories;
  /** Fetch ONCE. Every later call is a no-op, success or failure. */
  load(): Promise<EpicStories>;
  /** True once a load has been attempted — success or failure. */
  hasAttempted(): boolean;
}

export interface EpicStoriesStoreOptions {
  api       : EpicStoriesApiClient;
  endpoint? : string;
  /** Test seam for the "epics render de-slugged" diagnostic. */
  logFn?    : ( message: string ) => void;
}

interface EpicStoriesBody {
  stories? : unknown;
}

class EpicStoriesStoreImpl implements EpicStoriesStore {
  private readonly api      : EpicStoriesApiClient;
  private readonly endpoint : string;
  private readonly logFn    : ( message: string ) => void;

  private cached  : EpicStories = {};
  private fetched = false;

  constructor( opts: EpicStoriesStoreOptions ) {
    this.api      = opts.api;
    /* c8 ignore next */ // production-default fallback: the endpoint constant; tests inject a path to assert it is the one asked for.
    this.endpoint = opts.endpoint ?? EPIC_STORIES_ENDPOINT;
    /* c8 ignore next */ // production-default fallback: a silent log; tests inject a collector.
    this.logFn    = opts.logFn ?? ( () => { /* silent by default */ } );
  }

  stories(): EpicStories {
    return this.cached;
  }

  hasAttempted(): boolean {
    return this.fetched;
  }

  async load(): Promise<EpicStories> {
    if ( this.fetched ) return this.cached;
    // 🔴 SET BEFORE THE AWAIT, NOT AFTER IT. Setting it on success would retry a
    // down endpoint on every render; setting it after the try/catch would let
    // two concurrent callers both fire a request.
    this.fetched = true;

    try {
      const body = await this.api.get<EpicStoriesBody>( this.endpoint );
      if ( body && body.stories && typeof body.stories === "object" ) {
        this.cached = body.stories as EpicStories;
      } else {
        this.logFn( "Epic stories body carried no stories map — epics render de-slugged" );
      }
    } catch ( error ) {
      this.logFn( `Epic stories fetch failed: ${ String( error ) } — epics render de-slugged` );
    }
    return this.cached;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line — c8 reports ONE location for this "branch" (the identifier) where a real conditional carries two.
export function createEpicStoriesStore( opts: EpicStoriesStoreOptions ): EpicStoriesStore {
  return new EpicStoriesStoreImpl( opts );
}
