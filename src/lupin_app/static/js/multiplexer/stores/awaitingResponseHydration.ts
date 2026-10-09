/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line.
// Multiplexer — draw the response cards that were filed before the page opened (row 4ca5776c).
//
// A card reaches ActionRequiredStore by a live `notification_queue_update`, so a card filed while the page
// was closed was never drawn (io/tmp/2026.10.09-pocholo-check-legacy-page-draws-no-card-at-load.md). This
// runner asks the server for the cards still waiting and hands them to the store, which adds each one the way
// a push adds it. It speaks nothing and rings nothing: audio belongs to the push path, not the store.

import type { ServerNotificationFields } from "./ActionRequiredStore";

export const AWAITING_RESPONSE_PATH = "/api/notifications/awaiting-response";

// Narrowed ApiClient surface — production passes the canonical ApiClient.
export interface AwaitingResponseApiLike {
  get<T>(path: string): Promise<T>;
}

export interface AwaitingResponseStores {
  actionRequired: { hydrateAwaiting(cards: ReadonlyArray<ServerNotificationFields>): number };
}

export interface AwaitingResponseHydrationOptions {
  api    : AwaitingResponseApiLike;
  stores : AwaitingResponseStores;
}

export interface AwaitingResponseHydration {
  /** Fetch the waiting cards and add them. Never rejects. */
  run(): Promise<number>;
}

/**
 * Build the runner.
 *
 * Ensures:
 *   - run() asks AWAITING_RESPONSE_PATH once and returns how many cards the store added
 *   - a failed request, or an answer without a `notifications` list, adds nothing, logs the cause, and returns 0
 *   - run() never rejects
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the factory declaration line.
export function createAwaitingResponseHydration(opts: AwaitingResponseHydrationOptions): AwaitingResponseHydration {
  return {
    async run(): Promise<number> {
      try {
        const answer = await opts.api.get<{ notifications: ServerNotificationFields[] }>(AWAITING_RESPONSE_PATH);
        return opts.stores.actionRequired.hydrateAwaiting(answer.notifications);
      } catch (err) {
        console.warn("[multiplexer] waiting response cards not loaded:", err);
        return 0;
      }
    },
  };
}
