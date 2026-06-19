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

// Narrowed ApiClient surface (Pass 2 F4 idiom). Production ApiClient satisfies
// this structurally.
export interface PredictionVoteApiClient {
  post<T>( path: string, body: unknown ): Promise<T>;
}

// Hint context supplied by the renderer at paint time (the server does not
// persist the hint, so the client echoes it back on vote).
export interface PredictionVoteContext {
  question        : string;
  predicted_value : unknown;
  category        : string;
  response_type   : string;
}

// Confidence gate (percent) — mirrors INI
// "prediction hint vote min confidence threshold" = 0.50. Below this the
// controls are not shown, so the user does not train on noise.
export const PREDICTION_VOTE_MIN_PCT = 50;

export const PREDICTION_VOTE_ENDPOINT_PREFIX = "/api/notify/prediction-vote/";

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

export interface PredictionVoteStoreOptions {
  bus    : EventBus;
  api    : PredictionVoteApiClient;
  nowFn? : () => number;
}

class PredictionVoteStoreImpl implements PredictionVoteStore {
  private readonly bus   : EventBus;
  private readonly api   : PredictionVoteApiClient;
  private readonly nowFn : () => number;

  private readonly contexts = new Map<string, PredictionVoteContext>();
  private readonly votes    = new Map<string, PredictionVoteDir>();

  constructor( opts: PredictionVoteStoreOptions ) {
    this.bus = opts.bus;
    this.api = opts.api;
    /* c8 ignore next */ // production-default fallback: Date.now() is the runtime clock; tests inject a deterministic nowFn().
    this.nowFn = opts.nowFn ?? ( () => Date.now() );
  }

  setContext( notificationId: string, ctx: PredictionVoteContext ): void {
    if ( !notificationId ) return;
    this.contexts.set( notificationId, ctx );
  }

  getVote( notificationId: string ): PredictionVoteDir | undefined {
    return this.votes.get( notificationId );
  }

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

  /* c8 ignore start */ // Test-only cleanup helper; not exercised in production wiring.
  disposeForTesting(): void {
    this.contexts.clear();
    this.votes.clear();
  }
  /* c8 ignore stop */
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createPredictionVoteStore(
  opts: PredictionVoteStoreOptions,
): PredictionVoteStore {
  return new PredictionVoteStoreImpl( opts );
}
