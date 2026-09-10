/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The multiplexer half of Rick's New Ticket card (row c9895403).
//
// HIS WORDS, 2026-09-10: *"within the task list bar right next to the find
// functionality ... let's put the button that spawns the editor to create a new
// ticket there."*
//
// 🔴 THE CARD ITSELF IS NOT HERE. Form, validation and outcome wording live in
// `shared/task-create.js`, which the notifications client renders too — so the two
// clients cannot offer different fields. This file owns only what is genuinely
// multiplexer-specific: the header button, and turning ApiClient's thrown ApiError
// back into the `{ status, text }` shape the shared card reads.

import {
  openNewTicketCard,
  type NewTicketPayload,
  type NewTicketTransportResult,
} from "../../shared/task-create.js";

export interface NewTicketButtonOptions {
  /** Sends the POST. In production, `apiPostTicket( apiClient.post )`. */
  postTicket : ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult>;
  /** Read at CLICK time, so the roster is current when the card opens. */
  assignees  : () => string[];
  /** What to show once the row exists. */
  onCreated  : ( row: Record<string, unknown> ) => void;
}

/**
 * The "＋ New" button for the Task List header.
 *
 * Ensures:
 *   - one button, carrying `data-testid="multiplexer-task-list-new-ticket"`
 *   - a click opens the shared card with the multiplexer's test-id prefix and the
 *     roster as it stands at that moment
 */
export function renderNewTicketButton( opts: NewTicketButtonOptions ): HTMLButtonElement {
  const button = document.createElement( "button" );
  button.type = "button";
  button.className = "task-list-new-ticket";
  button.setAttribute( "data-testid", "multiplexer-task-list-new-ticket" );
  button.setAttribute( "title", "Create a new ticket" );
  button.textContent = "＋ New";
  button.addEventListener( "click", () => {
    openNewTicketCard( {
      postTicket   : opts.postTicket,
      assignees    : opts.assignees(),
      onCreated    : opts.onCreated,
      testidPrefix : "multiplexer-new-ticket",
    } );
  } );
  return button;
}

/**
 * The body text inside an ApiError's message.
 *
 * ApiClient throws `new ApiError( status, url, text )`, whose message reads
 * `HTTP <status> <url>: <text>`. The server's refusal is the part after the first
 * ": " — a URL contains "://" but never ": ", so the split cannot land inside it.
 *
 * Ensures:
 *   - a non-string → ""
 *   - no ": " → the message unchanged
 */
export function bodyOfApiErrorMessage( message: unknown ): string {
  if ( typeof message !== "string" ) return "";
  const at = message.indexOf( ": " );
  return at >= 0 ? message.slice( at + 2 ) : message;
}

/**
 * Adapt ApiClient.post to the transport the shared card expects.
 *
 * ⚠️ A RESOLVED post IS REPORTED AS 201. ApiClient hands back the parsed body and
 * drops the status code; the create door answers 201 on success, and the shared card
 * reads every 2xx the same way — `petition` in the body is what separates a granted
 * create from a request for one, never the status.
 *
 * Ensures:
 *   - success → `{ status: 201, body }`
 *   - an error carrying a numeric `status` (ApiError) → `{ status, text }`
 *   - anything else (timeout, network) → `{ status: 0 }`, which the card reports as
 *     "the store did not answer"
 *   - never rejects
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (row 4163a015); no default parameters here to hide.
export function apiPostTicket(
  post: ( path: string, body: unknown ) => Promise<unknown>,
): ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult> {
  return async ( payload ) => {
    try {
      const body = await post( "/api/tasks", payload );
      return { status: 201, body };
    } catch ( err ) {
      const failure = ( err ?? {} ) as { status?: unknown; message?: unknown };
      if ( typeof failure.status !== "number" ) return { status: 0 };
      return { status: failure.status, text: bodyOfApiErrorMessage( failure.message ) };
    }
  };
}
