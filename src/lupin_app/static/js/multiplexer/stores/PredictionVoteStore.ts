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
   * Clears all saved contexts and votes; used by tests.
   */
  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    this.contexts.clear();
    this.votes.clear();
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
