/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane E WP14 — PredictionVoteStore (F8).
//
// Owns the thumbs up/down training signal cast on a prediction hint. Ports
// legacy notifications.js:16877-16956 (`_predictionVoteContext` + `votePrediction`).
//
// Two responsibilities:
//   1. Context stash — the prediction hint is NOT persisted server-side, so the
//      client supplies what was voted on (question / predicted_value / category /
//      response_type) at POST time. The notification-item renderer calls
//      `setContext(id, ctx)` when it paints a hint.
//   2. vote(id, dir) — POSTs `/api/notify/prediction-vote/{id}` with the stashed
//      context and records the cast direction so the controls highlight it.
//      `up` → reinforce; `down` → steer away.

import type { EventBus } from "../shared/EventBus";
import type {
  PredictionVoteDir,
  StorePredictionVoteChangedPayload,
} from "../shared/types";

/** The slice of the API client the store needs: a `post` that returns the body. */
export interface PredictionVoteApiClient {
  post<T>( path: string, body: unknown ): Promise<T>;
}

/** The hint context the renderer supplies at paint time, echoed back on a vote. */
export interface PredictionVoteContext {
  question        : string;
  predicted_value : unknown;
  category        : string;
  response_type   : string;
}

/** The lowest confidence, in percent, at which the vote controls are shown. */
export const PREDICTION_VOTE_MIN_PCT = 50;

/** The path prefix of the prediction vote endpoint. */
export const PREDICTION_VOTE_ENDPOINT_PREFIX = "/api/notify/prediction-vote/";

/** The path prefix of the endpoint that records a hint was rendered or its fold opened. */
export const PREDICTION_SEEN_ENDPOINT_PREFIX = "/api/notify/prediction-seen/";

/** The two client events the seen route records. */
export type PredictionSeenEvent = "rendered" | "fold_opened";

/** The hint context of each notification and the vote cast on it, and the call that votes. */
export interface PredictionVoteStore {
  /** Stash the hint context for a notification id (renderer paint-time call). */
  setContext( notificationId: string, ctx: PredictionVoteContext ): void;
  /** The cast vote for a notification id, or undefined if none cast. */
  getVote( notificationId: string ): PredictionVoteDir | undefined;
  /**
   * Cast a vote. Returns true iff the vote was recorded (valid dir + known
   * context + successful POST). Rejects only on a thrown POST (propagated to
   * the caller, which swallows it — the control stays unhighlighted for retry).
   */
  vote( notificationId: string, dir: PredictionVoteDir ): Promise<boolean>;
  /** True when the fold of this notification's hint was opened. */
  isFoldOpen( notificationId: string ): boolean;
  /**
   * Report a render or a fold-open of a hint.
   *
   * Each event is sent once per notification and a repeat is dropped. A fold-open is also
   * remembered for `isFoldOpen`. A failed call is forgotten, so the next report retries, and
   * it never throws.
   *
   * A fold-open carries `draft_at_reveal` when a draft is given, and a render never does. No draft, or null,
   * sends the call as it was, so an empty answer is never sent as an empty value.
   * The first fold-open's draft is the one kept. A retry sends it again, never a draft read after the forecast showed.
   */
  reportSeen( notificationId: string, event: PredictionSeenEvent, draft?: { value: string } | null ): Promise<void>;
  /** Test/cleanup helper. */
  disposeForTesting(): void;
}

/** Options for `createPredictionVoteStore`: the bus, the API client and a clock for tests. */
export interface PredictionVoteStoreOptions {
  bus    : EventBus;
  api    : PredictionVoteApiClient;
  nowFn? : () => number;
}

/**
 * Models thumbs up and down votes on predictions, keyed by notification ID.
 */
class PredictionVoteStoreImpl implements PredictionVoteStore {
  private readonly bus   : EventBus;
  private readonly api   : PredictionVoteApiClient;
  private readonly nowFn : () => number;

  private readonly contexts = new Map<string, PredictionVoteContext>();
  private readonly votes    = new Map<string, PredictionVoteDir>();
  // Which seen events were sent, keyed "<id>|<event>". A fold-open is kept even when the
  // call fails, because the reader did open it and the card must stay open on a repaint.
  private readonly seenSent  = new Set<string>();
  private readonly foldOpens = new Set<string>();
  // The draft taken at each card's first fold-open, kept so a retry after a failed call sends it and not a later one.
  private readonly firstDrafts = new Map<string, { value: string } | null>();

  /**
   * Stores the bus and API client and the clock, which defaults to the current time.
   */
  constructor( opts: PredictionVoteStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
  }

  /**
   * Remembers the prediction details of a notification so it can be voted on.
   */
  setContext( notificationId: string, ctx: PredictionVoteContext ): void {
    if ( !notificationId ) return;
    this.contexts.set( notificationId, ctx );
  }

  /**
   * Returns the vote cast for the notification, or undefined when none was.
   */
  getVote( notificationId: string ): PredictionVoteDir | undefined {
    return this.votes.get( notificationId );
  }

  /**
   * Posts an up or down vote and records it when the request succeeds.
   */
  async vote( notificationId: string, dir: PredictionVoteDir ): Promise<boolean> {
    if ( !notificationId ) return false;
    if ( dir !== "up" && dir !== "down" ) return false;
    const ctx = this.contexts.get( notificationId );
    if ( ctx === undefined ) return false;   // no hint context — cannot vote

    const resp = await this.api.post<unknown>(
      PREDICTION_VOTE_ENDPOINT_PREFIX + encodeURIComponent( notificationId ),
      {
        vote            : dir,
        question        : ctx.question,
        predicted_value : ctx.predicted_value,
        category        : ctx.category,
        response_type   : ctx.response_type,
      },
    );
    // ApiClient throws on non-2xx, so reaching here means the vote landed. The
    // resolved body is unused (parity with legacy, which only logs it).
    void resp;

    this.votes.set( notificationId, dir );
    this.bus.emit<StorePredictionVoteChangedPayload>( {
      type    : "store_prediction_vote_changed",
      payload : { notificationId, vote: dir },
      source  : "PredictionVoteStore",
      ts      : this.nowFn(),
    } );
    return true;
  }

  /**
   * Returns true when the fold of the notification's hint was opened.
   */
  isFoldOpen( notificationId: string ): boolean {
    return this.foldOpens.has( notificationId );
  }

  /**
   * Sends one seen event per notification and forgets it when the call fails.
   */
  async reportSeen( notificationId: string, event: PredictionSeenEvent, draft?: { value: string } | null ): Promise<void> {
    if ( !notificationId ) return;
    if ( event === "fold_opened" ) {
      this.foldOpens.add( notificationId );
      if ( !this.firstDrafts.has( notificationId ) ) this.firstDrafts.set( notificationId, draft ?? null );
      draft = this.firstDrafts.get( notificationId );
    }
    const key = `${ notificationId }|${ event }`;
    if ( this.seenSent.has( key ) ) return;
    this.seenSent.add( key );
    try {
      await this.api.post<unknown>(
        PREDICTION_SEEN_ENDPOINT_PREFIX + encodeURIComponent( notificationId ),
        event === "rendered" ? { rendered: true } : draft ? { fold_opened: true, draft_at_reveal: draft } : { fold_opened: true },
      );
    } catch ( _err ) {
      this.seenSent.delete( key );
    }
  }

  /**
   * Clears all saved contexts and votes; used by tests.
   */
  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    this.contexts.clear();
    this.votes.clear();
    this.seenSent.clear();
    this.foldOpens.clear();
    this.firstDrafts.clear();
  }
  /* c8 ignore stop */
}

/** Build the store. It makes no request until a vote is cast. */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createPredictionVoteStore(
  opts: PredictionVoteStoreOptions,
): PredictionVoteStore {
  return new PredictionVoteStoreImpl( opts );
}

/**
 * Stash a card's hint context, cast the vote, and call `revert` when it is not recorded.
 *
 * Shared by the notification list and the Action Required card.
 *
 * Requires:
 *   - store is a PredictionVoteStore, or a test double of its setContext and vote
 *
 * Ensures:
 *   - the context is set before the vote is sent
 *   - `revert` runs once when the vote is refused or the call throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function castPredictionVote(
  store  : Pick<PredictionVoteStore, "setContext" | "vote">,
  id     : string,
  dir    : PredictionVoteDir,
  ctx    : PredictionVoteContext,
  revert : () => void,
): void {
  store.setContext( id, ctx );
  void store.vote( id, dir ).then( ( ok ) => { if ( !ok ) revert(); } ).catch( revert );
}
