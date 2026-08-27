/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (same as shared/agent-select.js:1).
/**
 * The Q&A card's inline argument interview (2026.08.22 plan §5.2, phase 4).
 *
 * WHAT THIS REPLACES. A submit card is a form asking for `query` / `prompt` / `source`
 * up front. The v2 flow already asks for exactly those, one at a time, from the same
 * contract — it just does it in the RESPONSE instead of in HTML. This module renders
 * that question inline in the Q&A card and posts the answer to /api/v2/resume, so the
 * card inherits every agent's argument interview at once, including agents nobody has
 * built a card for. That is what leaves the submit cards with no job left.
 *
 * WHY A MODULE, again: notifications.js is a classic script and cannot be imported by
 * a test, so a render living inside it is reachable only through a live browser. Same
 * contract as shared/agent-select.js and shared/task-list-query.js.
 *
 * SCOPE — claim A only, and the plan now says so in §7a. This module carries "the card
 * can take an argument interview to completion". Whether the QUEUE then drains the
 * resulting job is claim B, a different claim on a different venue, sequenced behind
 * row 7451bebe. See src/rnd/v0.2.0/2026.08.22-qa-card-phase-4-observation-method.md.
 */

/**
 * The response bodies this module reads.
 *
 * Transcribed from `AskResponse` and `ResumeRequest` in
 * `src/cosa/rest/routers/v2_ask.py` rather than guessed: `Optional[str]` is written
 * `string|null`, which is what a Pydantic optional serialises to, and `websocket_id`
 * is nullable there for the same reason it is nullable at the call site —
 * notifications.js initialises `this.queueSessionId` to null and fills it when the
 * queue socket connects.
 *
 * @typedef {Object} FlowResult
 * @property {string} [path]
 * @property {string} [status]
 * @property {string|null} [answer]
 * @property {string|null} [pending_id]
 * @property {string[]} [args_missing]
 */

/**
 * A FlowResult that isAnswerable has said yes to — the question text and the
 * pending id are both present, which is precisely what that check verifies.
 *
 * @typedef {FlowResult & { answer: string, pending_id: string }} AnswerableResult
 */


/**
 * Is this response a question the user can actually answer?
 *
 * 🔴 THE DISTINCTION THAT MATTERS: `path === "needs_input"` is NOT enough. The flow
 * emits that path in three states and only one of them is answerable:
 *
 *   · status "parked"      — interactive ask; a pending_id exists → ANSWERABLE
 *   · status "needs_input" — the submit door's non-parking refusal. Nothing was
 *                            stored and there is no pending_id, deliberately: there
 *                            is no human behind a submit to answer it
 *   · status "expired"     — the pending entry is gone; resuming it would 404 again
 *
 * Rendering an answer box for the last two would give the user an input whose submit
 * cannot succeed — a dead box that looks live. So the test is the PENDING ID, which is
 * the thing resume actually needs, rather than the path or a status allow-list that
 * would need editing every time a status is added.
 *
 * Requires:
 *     - result is an /api/v2/ask, /api/v2/submit or /api/v2/resume response body
 *
 * Ensures:
 *     - true only when the flow asked a question AND left something to resume
 *     - never throws on a missing or malformed result
 *
 * Declared as a type predicate because that is the same statement the Ensures clause
 * above already makes — a true here means the answer text and the pending id are both
 * there — and it is what lets renderArgQuestion read them without a cast.
 *
 * @param {FlowResult|null|undefined} result
 * @returns {result is AnswerableResult}
 */
export function isAnswerable( result ) {
    if ( !result ) return false;
    return result.path === "needs_input" && Boolean( result.pending_id ) && Boolean( result.answer );
}

/**
 * The body for the POST /api/v2/resume that answers this question.
 *
 * Ensures:
 *     - carries the pending_id the question came with, never one the caller invented
 *     - carries websocket_id so the resumed turn's TTS reaches the same session
 *
 * @param {FlowResult} result
 * @param {string} answer
 * @param {string|null} websocketId
 * @returns {{ pending_id: string|null|undefined, answer: string, websocket_id: string|null }}
 */
export function resumeBody( result, answer, websocketId ) {
    return { pending_id: result.pending_id, answer: answer, websocket_id: websocketId };
}

/**
 * Render the flow's question as an inline answer box inside `containerEl`.
 *
 * Requires:
 *     - containerEl is an element; result satisfies isAnswerable
 *
 * Ensures:
 *     - the container ends up holding EXACTLY this question — prior children are
 *       removed first, so a multi-argument interview replaces its question rather
 *       than stacking three dead boxes down the card
 *     - the container is made visible, and its `hidden` state is the single signal
 *       of whether an interview is in progress
 *     - returns { input, button } so the caller can wire submission without
 *       re-querying the DOM by id — there is no id to collide with
 *     - renders NOTHING and returns null when the result is not answerable, so a
 *       caller that forgets to check cannot produce a dead box
 *
 * @param {HTMLElement} containerEl
 * @param {FlowResult|null|undefined} result
 * @returns {{ input: HTMLInputElement, button: HTMLButtonElement }|null}
 */
export function renderArgQuestion( containerEl, result ) {
    if ( !isAnswerable( result ) ) {
        clearArgQuestion( containerEl );
        return null;
    }
    const doc = containerEl.ownerDocument;
    containerEl.replaceChildren();

    const question = doc.createElement( "div" );
    question.className   = "qa-arg-question";
    question.textContent = result.answer;

    const input = doc.createElement( "input" );
    input.type        = "text";
    input.className   = "qa-arg-input";
    input.placeholder = "Your answer…";
    input.setAttribute( "data-testid", "notifications-qa-arg-input" );
    // The argument being asked for, exposed for the tests and for anyone reading the
    // DOM to see WHICH argument stalled — args_missing[0] is the one the flow asked.
    if ( Array.isArray( result.args_missing ) && result.args_missing.length ) {
        // The cast states what the `.length` check on the line above already
        // guarantees; `noUncheckedIndexedAccess` types every array read as
        // possibly-undefined and cannot see that check.
        input.setAttribute( "data-arg", /** @type {string} */ ( result.args_missing[ 0 ] ) );
    }

    const button = doc.createElement( "button" );
    button.type        = "button";
    button.className   = "qa-arg-submit";
    button.textContent = "Answer";
    button.setAttribute( "data-testid", "notifications-qa-arg-submit-btn" );

    containerEl.appendChild( question );
    containerEl.appendChild( input );
    containerEl.appendChild( button );
    containerEl.hidden = false;
    return { input, button };
}

/**
 * Take the interview box down.
 *
 * Ensures:
 *     - the container is emptied AND hidden — an emptied-but-visible container leaves
 *       a stray bordered gap in the card that reads as a rendering bug
 *     - safe to call when nothing was ever rendered
 *
 * @param {HTMLElement|null|undefined} containerEl
 * @returns {void}
 */
export function clearArgQuestion( containerEl ) {
    if ( !containerEl ) return;
    containerEl.replaceChildren();
    containerEl.hidden = true;
}

/**
 * Publish for the classic-script consumer. See shared/agent-select.js:publishOnWindow
 * for why this is an exported function rather than a load-time `if ( typeof window )`.
 *
 * @param {(Window & typeof globalThis)|null|undefined} target
 * @returns {boolean}
 */
export function publishOnWindow( target ) {
    if ( !target ) return false;
    target.LUPIN_ARG_INTERVIEW = { isAnswerable, resumeBody, renderArgQuestion, clearArgQuestion };
    return true;
}

/* c8 ignore next */ // tsx phantom-branch artifact on a top-level call statement; the line has no branch in source.
publishOnWindow( globalThis.window );
