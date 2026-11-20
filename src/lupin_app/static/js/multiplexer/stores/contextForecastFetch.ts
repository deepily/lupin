/* c8 ignore next */
// Late fetch: a fold opened late reads the card's Haiku forecast.
//
// A client that missed the frame, or opened its fold before the job finished, still ends up with the stored result.
// The call is made only for a card still showing "forecasting", and a failed call changes nothing.

import type { ContextForecastPayload } from "../shared/types";

/** The route that serves a card's current Haiku forecast payload. */
export const PREDICTION_HINT_ENDPOINT_PREFIX = "/api/notify/prediction-hint/";

/** The part of the API client the fetch needs. */
export interface ContextForecastApiClient {
  get<T>( path: string ): Promise<T>;
}

/** The part of the action-required store the fetch needs. */
export interface ContextForecastTarget {
  getById( idHash: string ): { prediction_hint?: { context_forecast?: ContextForecastPayload } } | undefined;
  applyContextForecast( idHash: string, forecast: ContextForecastPayload ): void;
}

/**
 * Build the function that refreshes one card's Haiku forecast from the server.
 *
 * Requires:
 *   - api reads JSON by path; target is the action-required store
 * Ensures:
 *   - returns fetch( id ), which asks only when the card's forecast is in the forecasting state
 *   - a reply with a forecast replaces the card's; a null forecast (display off) or a failed call leaves it as it was
 *   - it never throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (PredictionVoteStore.ts precedent).
export function createContextForecastFetcher( api: ContextForecastApiClient, target: ContextForecastTarget ): ( idHash: string ) => Promise<void> {
  return async ( idHash: string ): Promise<void> => {
    if ( target.getById( idHash )?.prediction_hint?.context_forecast?.state !== "forecasting" ) return;
    try {
      const reply = await api.get<{ context_forecast: ContextForecastPayload | null }>( PREDICTION_HINT_ENDPOINT_PREFIX + encodeURIComponent( idHash ) );
      if ( reply.context_forecast ) target.applyContextForecast( idHash, reply.context_forecast );
    } catch ( _err ) {
      // The card keeps the text it has; the next open asks again.
    }
  };
}
