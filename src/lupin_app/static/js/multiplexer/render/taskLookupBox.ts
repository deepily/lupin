/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Paste a hash, get the ticket — the multiplexer half of Rick's findability P0.
//
// HIS WORDS, 2026-09-09: *"Every time someone refers to a row for a ticket by #
// I have no idea what they're talking about."* Three seats broke the
// lead-with-the-title convention in a single evening — including the one
// carrying that rule in permanent memory — so the convention is measured, not
// assumed, to be unreliable. A box works the same at 03:00 as at noon.
//
// 🔴 IT MUST HIT `/api/tasks/<ref>`, NEVER `/api/tasks?id_prefix=<ref>`.
// The query form chains `_apply_owed_filter` after the prefix match, so it hides
// holding-area rows: measured 2026-09-09, exactly 1 of 23 held rows was findable
// that way. The single-row endpoint applies no visibility filter and returns
// held rows — proven over HTTP the same day. The URL is built by
// `shared/task-lookup.js`, whose own tests pin this; do not inline a path here.
//
// WHY A RESULT CARD AND NOT "SCROLL TO THE ROW". The hashes Rick is handed are
// most often for rows that are NOT on his board — held, parked, or terminal. A
// reveal-and-highlight would work only for the rows he could already see, which
// is precisely the set that never needed a lookup.
//
// ⚠️ THE STATUS IS PART OF THE ANSWER, NOT DECORATION. A held row rendered
// without its status reads as an ordinary live ticket, and the difference
// between "it is queued" and "it is sitting in your holding area" is usually the
// whole reason he is asking.

import {
  classifyTaskRef,
  taskLookupPath,
  taskRefRefusalMessage,
  TASK_LOOKUP_AUTH_REQUIRED_MESSAGE,
  TASK_LOOKUP_UNREACHABLE_MESSAGE,
} from "../../shared/task-lookup.js";
import type { TaskItem } from "./taskListModel";

/** What the box needs from the outside world. Injected so it is testable. */
export interface TaskLookupBoxOptions {
  /** Performs the GET. In production this is `ApiClient.get<TaskItem>`. */
  fetchTask : ( path: string ) => Promise<TaskItem>;
  /**
   * Hand the found row UP so the list can show it — the whole point of the box.
   *
   * 🔴 RICK REJECTED THE FIRST BUILD FOR NOT HAVING THIS, and he was right:
   * *"it doesn't display it it only puts the title up in green text… what do you
   * think search does? Not confirm that it can find it but find it and then
   * display it. It's like a filter… hide all of the other tickets in the task
   * list and only display the 1 that was found."*
   *
   * His original ask said so too — *"I need the search capacity to FILTER OUT THE
   * TASK LIST so I can find exactly what someone is talking about"* — and the
   * first cut answered "does this id exist?" instead. A sentence naming the row
   * is a receipt, not a result; it leaves him to find the row himself, which is
   * the thing he could not do.
   */
  onFound?   : ( task: TaskItem ) => void | LookupFilterOutcome;
  /** Drop the filter and put the whole list back. */
  onCleared? : () => void;
  /**
   * What this box searches, for the refusal sentence when a row is found but
   * does not belong to the mounting pane. Defaults to "task list".
   */
  scopeLabel? : string;
  /**
   * Prefix for every `data-testid` this control emits. Defaults to
   * `multiplexer-task-lookup`, which is what the task list's box has always used.
   *
   * 🔴 IT IS A PARAMETER BECAUSE THERE ARE NOW TWO BOXES ON ONE PAGE. The
   * holding area got its own on 2026-09-09, and a second control emitting the
   * SAME ids would make every `querySelector` on the page resolve to whichever
   * pane happens to render first. Tests would pass while asserting against the
   * wrong control — the failure mode that does not announce itself, because a
   * green suite pointed at the wrong element looks exactly like a green suite.
   */
  testidPrefix? : string;
}

/**
 * What the mounting pane did with the row the box handed it.
 *
 * 🔴 THIS EXISTS BECAUSE A PANE CAN LEGITIMATELY REFUSE A ROW IT FOUND. The
 * holding area shows only `not_approved` rows; the single-row endpoint the box
 * uses is deliberately visibility-free and will happily return a queued one.
 * Pinning that into the holding area would render a row as HELD that is not
 * held — the pane's own meaning is "these are waiting on triage", so putting a
 * non-held row inside it is a false statement made by the layout rather than by
 * any sentence.
 *
 * ⇒ Returning nothing means "filtered" — the task list's behaviour, unchanged.
 * Returning `{ applied: false }` means "I found it and it is not mine to show",
 * and the box then says so INSTEAD of claiming a filter it never applied.
 */
export interface LookupFilterOutcome {
  /** Did the pane actually filter to this row? */
  applied  : boolean;
  /** The sentence to show when it did not. */
  message? : string;
  /** The `data-state` token to show when it did not. */
  state?   : string;
}

export interface TaskLookupBoxHandle {
  /** The whole control — input + button + result region. Mount this. */
  root   : HTMLElement;
  input  : HTMLInputElement;
  /** The result / refusal region. Its textContent is the user-visible answer. */
  result : HTMLElement;
  /** Runs a lookup for whatever is currently typed. Awaitable for tests. */
  submit : () => Promise<void>;
  /** Clears the box and the filter it applied. Awaitable-free; sync. */
  clear  : () => void;
}

/**
 * What the box says once the LIST is carrying the answer.
 *
 * Deliberately not a description of the row: the row is on screen. This line
 * exists only to make the filtered state legible — a list showing one row with
 * no explanation reads as "the board is nearly empty", which is its own lie.
 */
const FILTER_ACTIVE_TEXT = "Showing the one matching ticket — ✕ to see the whole list.";

/** Shape of the server's error body; `detail` is FastAPI's convention. */
interface ErrorLike {
  status?  : number;
  detail?  : string;
  message? : string;
}

// `describeFoundTask` lived here and is GONE (2026-09-09). It composed a one-line
// sentence naming the found row — title, status, owner, priority — under the box.
// Rick rejected exactly that: "it doesn't display it it only puts the title up in
// green text… what do you think search does? Not confirm that it can find it but
// find it and then display it." The row now renders IN THE LIST through the normal
// table renderer, so a second, parallel way of describing a row would be both dead
// weight and a drift risk. Its two real guarantees — the title leads, and the
// STATUS is always shown because "which pile is it in" is usually the actual
// question — are now properties of the rendered row, asserted against the list.

/**
 * Turn a failed lookup into a sentence that says which of the failures happened.
 *
 * 🔴 THE FOUR OUTCOMES MUST STAY DISTINGUISHABLE. A 404 and a 422 both mean
 * "you did not get a ticket" and they call for opposite next moves — type more
 * characters, versus that ticket does not exist. Collapsing them into one
 * "not found" is the same defect as a status code shared by several conditions,
 * which this repo has already paid for once on the api-key staircase.
 *
 * 🔴 401 IS THE ONE THAT IS NOT ABOUT THE TICKET AT ALL. It says the SESSION
 * expired, and the remedy is on the user's side — refresh and sign back in.
 * Routed to the catch-all it renders as "Lookup failed: ...", which reads as a
 * store outage: the reader retypes the hash, gets the same sentence, and goes
 * to triage an outage that is not happening. This arm shipped in the
 * notifications client (`state: "auth_required"`) and was MISSING here, so the
 * two clients answered one condition differently — caught in review, and the
 * exact one-sided delivery the parity guard exists to prevent.
 *
 * Ensures:
 *   - 404 → says nothing matched, and echoes what was typed
 *   - 422 → passes the server's own detail through, because for an ambiguous
 *     prefix that detail NAMES every candidate id and is more useful than
 *     anything this function could compose
 *   - 401 → says the session expired, WORD FOR WORD as the notifications client
 *     says it, because one condition with two wordings is the same drift in a
 *     smaller costume
 *   - anything else → says the store did not answer, in the SAME words the
 *     notifications client uses, and does not surface the transport's own
 *     message (which is "HTTP 500", not something a reader can act on)
 */
export function describeLookupFailure( typed: string, error: ErrorLike ): string {
  const status = typeof error.status === "number" ? error.status : 0;
  if ( status === 404 ) return `No ticket matches "${ typed }".`;
  if ( status === 422 ) return error.detail ?? `"${ typed }" is not a usable ticket reference.`;
  if ( status === 401 ) return TASK_LOOKUP_AUTH_REQUIRED_MESSAGE;
  // NOT `error.message` — that is "HTTP 500" or a stack fragment. See the shared
  // constant for why the 422 arm passes detail through and this one does not.
  return TASK_LOOKUP_UNREACHABLE_MESSAGE;
}

/**
 * Which OUTCOME a failed lookup is, as a machine-readable token.
 *
 * 🔴 THE SENTENCE WAS NOT THE WHOLE DIVERGENCE. Before this, every failure
 * stamped `data-state="missing"` — so a signed-out session, an ambiguous prefix
 * and a dead store were indistinguishable to tests, to CSS and to anything
 * reading the DOM, while the notifications client named all four. The docstring
 * above promising "four distinct sentences" was true and beside the point: the
 * STATE is the part other code branches on, and it said "missing" for all of it.
 *
 * The vocabulary is the notifications client's, deliberately — parity means the
 * same word for the same condition, not merely a word each.
 *
 * Ensures:
 *   - 404 → "missing" · 422 → "ambiguous" · 401 → "auth_required"
 *   - anything else, including a network throw → "unreachable"
 */
export function lookupFailureState( error: ErrorLike ): string {
  const status = typeof error.status === "number" ? error.status : 0;
  if ( status === 404 ) return "missing";
  if ( status === 422 ) return "ambiguous";
  if ( status === 401 ) return "auth_required";
  return "unreachable";
}

/**
 * Build the lookup control.
 *
 * Requires:
 *   - a DOM is available (browser, or happy-dom in tests)
 *   - `opts.fetchTask` resolves with a row or rejects with something carrying a
 *     `status` (ApiError does)
 *
 * Ensures:
 *   - refuses an unusable reference WITHOUT a request, naming both rules
 *   - otherwise issues exactly one GET to the single-row endpoint
 *   - renders found / not-found / ambiguous / signed-out / unreachable as
 *     distinct sentences AND distinct `data-state` tokens — the state is what
 *     other code branches on, so a shared state is a real collapse even when
 *     the wording differs
 *   - never throws out of `submit` — a lookup box that explodes on a bad paste
 *     is worse than one that says no
 */
export function renderTaskLookupBox( opts: TaskLookupBoxOptions ): TaskLookupBoxHandle {
  const tid = opts.testidPrefix ?? "multiplexer-task-lookup";
  const root = document.createElement( "div" );
  root.className = "task-lookup";
  root.setAttribute( "data-testid", tid );

  const input = document.createElement( "input" );
  input.type = "search";
  input.className = "task-lookup-input";
  input.setAttribute( "data-testid", `${ tid }-input` );
  input.setAttribute( "placeholder", "Find ticket by id…" );
  input.setAttribute( "aria-label", "Find a ticket by its id" );

  const button = document.createElement( "button" );
  button.type = "button";
  button.className = "task-lookup-go";
  button.setAttribute( "data-testid", `${ tid }-go` );
  button.setAttribute( "title", "Look up a ticket by its id" );
  button.textContent = "🔎";

  const clearBtn = document.createElement( "button" );
  clearBtn.type = "button";
  clearBtn.className = "task-lookup-clear";
  clearBtn.setAttribute( "data-testid", `${ tid }-clear` );
  clearBtn.setAttribute( "title", "Show the whole task list again" );
  clearBtn.textContent = "✕";
  // Hidden until a filter is actually applied — a permanent "clear" on an
  // unfiltered list is a control that does nothing, which teaches the operator
  // to ignore it for the one moment it matters.
  clearBtn.hidden = true;

  const result = document.createElement( "div" );
  result.className = "task-lookup-result";
  result.setAttribute( "data-testid", `${ tid }-result` );
  // Announce results to a screen reader without stealing focus from the input.
  result.setAttribute( "role", "status" );

  const show = ( text: string, state: string ): void => {
    result.textContent = text;
    result.setAttribute( "data-state", state );
  };

  const submit = async (): Promise<void> => {
    const typed = input.value.trim();
    const path  = taskLookupPath( typed );

    if ( path === null ) {
      // No request. The server would refuse this too, and spending a round trip
      // to be told something we already know is a worse answer, later.
      show( taskRefRefusalMessage(), "refused" );
      return;
    }

    show( "Looking up…", "pending" );
    try {
      const task = await opts.fetchTask( path );
      // 🔴 THE ROW GOES TO THE LIST. The box's own text drops to a one-line
      // "showing 1 — clear" affordance, because the ANSWER is now the list
      // itself. Describing the row here as well would say the same thing twice
      // and re-create the thing Rick rejected: a receipt where a result belongs.
      const outcome = opts.onFound?.( task );
      // 🔴 A PANE THAT REFUSED THE ROW MUST NOT BE REPORTED AS FILTERED. The
      // clear control stays hidden too — offering "show everything again" when
      // nothing was hidden is the dead control this box already avoids on an
      // unfiltered list, and it would also imply the row IS in this pane.
      if ( outcome !== undefined && outcome !== null && outcome.applied === false ) {
        show(
          outcome.message ?? `"${ typed }" is not in the ${ opts.scopeLabel ?? "task list" }.`,
          outcome.state ?? "out-of-scope",
        );
        return;
      }
      show( FILTER_ACTIVE_TEXT, "filtered" );
      clearBtn.hidden = false;
    } catch ( err ) {
      const failure = ( err ?? {} ) as ErrorLike;
      // A failed lookup must NOT wipe the board — the list the operator was
      // reading is not the thing that went wrong.
      show( describeLookupFailure( typed, failure ), lookupFailureState( failure ) );
    }
  };

  const clear = (): void => {
    input.value = "";
    show( "", "" );
    clearBtn.hidden = true;
    opts.onCleared?.();
  };

  button.addEventListener( "click", () => void submit() );
  input.addEventListener( "keydown", ( e ) => {
    if ( ( e as KeyboardEvent ).key !== "Enter" ) return;
    e.preventDefault();
    void submit();
  } );

  clearBtn.addEventListener( "click", () => clear() );
  root.append( input, button, clearBtn, result );
  return { root, input, result, submit, clear };
}

/**
 * Which reference kind the box would send, without sending it.
 *
 * Exposed for the parity test that pins this client and the notifications client
 * to ONE classifier — the guard that stops the two panes disagreeing about what
 * counts as a ticket id, which is the `taskVerbs.ts` drift in advance.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function lookupKindFor( typed: string ): string {
  return classifyTaskRef( typed ).kind;
}
