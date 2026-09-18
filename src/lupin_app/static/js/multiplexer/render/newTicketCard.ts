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
  type NewTicketDictateContext,
  type NewTicketPayload,
  type NewTicketTransportResult,
} from "../../shared/task-create.js";
import { insertTranscriptionText } from "./insertTranscriptionText";
import type { TaskRowRecorderLike } from "./taskRowController";

export interface NewTicketButtonOptions {
  /** Sends the POST. In production, `apiPostTicket( apiClient.post )`. */
  postTicket : ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult>;
  /** Read at CLICK time, so the roster is current when the card opens. */
  assignees  : () => string[];
  /** What to show once the row exists. */
  onCreated  : ( row: Record<string, unknown> ) => void;
  /** Supply this and Title and Details get mics; omit it and neither does. */
  recorder?     : TaskRowRecorderLike;
  /** The bearer token the dictation upload carries. */
  getAuthToken? : () => string | null;
}

/** The recording context one field of the card dictates under. */
export function newTicketMicContextId( field: string ): string {
  return `new-ticket-${field}`;
}

/**
 * The card's dictation hook for THIS client.
 *
 * 🔴 WHY THE CARD TAKES A HOOK AND NOT A RECORDER. The classic page's recorder is
 * `startRecording( contextId, button, input, options )` and writes into the element
 * itself; this one takes an options object and hands the transcription back through
 * `onComplete` for the caller to splice. Two shapes, one card — so the card renders the
 * button and says WHICH field and WHICH element, and each client supplies the rest.
 *
 * ⚠️ IT NEVER LOOKS THE ELEMENT UP. `handleReasonMicClick` resolves its box by scope
 * because a row renders on two panes and an id lookup once filled the copy Rick could
 * not see (bc77cd79). Here the card hands over the element it built, so there is no
 * lookup to get wrong — do not "improve" this into a querySelector.
 *
 * Ensures:
 *   - each field records under its own context id, so Title and Details never collide
 *   - a click while THIS field is recording stops it and marks the mic `processing`;
 *     a click while it is processing is ignored
 *   - the transcription is spliced at the caret the box held when recording began
 *   - every outcome — complete, error, cancel — returns the mic to idle and frees the
 *     context, so the same mic can be used again
 */
export function makeNewTicketDictationHook(
  recorder     : TaskRowRecorderLike,
  getAuthToken : ( () => string | null ) | undefined,
): ( ctx: NewTicketDictateContext ) => void {
  // Contexts whose stop has been asked for and whose transcription has not arrived.
  // Mirrors TaskRowController.micProcessing — a click in that window does nothing.
  const processing = new Set<string>();

  return ( { field, button, input } ) => {
    const contextId = newTicketMicContextId( field );
    if ( processing.has( contextId ) ) return;

    if ( recorder.getActiveContextId() === contextId ) {
      processing.add( contextId );
      button.classList.remove( "recording" );
      button.classList.add( "processing" );
      void recorder.stopRecording( contextId );
      return;
    }

    const stash  = { text: input.value, selStart: input.selectionStart, selEnd: input.selectionEnd };
    const settle = (): void => {
      processing.delete( contextId );
      button.classList.remove( "recording", "processing" );
    };
    button.classList.add( "recording" );
    void recorder.startRecording( {
      contextId,
      authToken  : getAuthToken === undefined ? null : getAuthToken(),
      onComplete : ( transcription ) => {
        settle();
        const spliced = insertTranscriptionText( stash.text, stash.selStart, stash.selEnd, transcription );
        input.value = spliced.value;
        if ( spliced.caret !== null ) input.setSelectionRange( spliced.caret, spliced.caret );
      },
      onError    : settle,
      onCancel   : settle,
    } );
  };
}

/**
 * The "＋ New" button for the Task List header.
 *
 * Ensures:
 *   - one button, carrying `data-testid="multiplexer-task-list-new-ticket"`
 *   - a click opens the shared card with the multiplexer's test-id prefix and the
 *     roster as it stands at that moment
 *   - with a recorder, the card's Title and Details carry mics; without one, neither
 *     does and the card is exactly what it was
 */
export function renderNewTicketButton( opts: NewTicketButtonOptions ): HTMLButtonElement {
  const button = document.createElement( "button" );
  button.type = "button";
  button.className = "task-list-new-ticket";
  button.setAttribute( "data-testid", "multiplexer-task-list-new-ticket" );
  button.setAttribute( "title", "Create a new ticket" );
  button.textContent = "＋ New";
  const onDictate = opts.recorder === undefined
    ? undefined
    : makeNewTicketDictationHook( opts.recorder, opts.getAuthToken );
  button.addEventListener( "click", () => {
    openNewTicketCard( {
      postTicket   : opts.postTicket,
      assignees    : opts.assignees(),
      onCreated    : opts.onCreated,
      testidPrefix : "multiplexer-new-ticket",
      ...( onDictate === undefined ? {} : { onDictate } ),
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
