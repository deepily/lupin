/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (same as shared/agent-select.js:1; BRDA:1,6 zero-hit in every run, measured 2026-09-10).
/**
 * Rick's own New Ticket card — shared by both clients, form and all.
 *
 * HIS WORDS, 2026-09-10 (row c9895403): *"create a card that allows me to manually
 * create a new ticket without you having to file it for me ... every single ticket
 * that I create has to flow through you guys ... I can put it straight into your
 * live queue as a P0 for example."* And on the fields: *"not only does this editor
 * card need a title but it also needs a comments section ... details ... that allows
 * me to give you background material ... it needs all of the other editor fields
 * like who it's assigned to, priority, approved/disapproved by default approved."*
 *
 * 🟢 THE SERVER HALF ALREADY EXISTED. `POST /api/tasks` lets the operator's own
 * validated login create at P0 (`refusal_for_priority_create` returns None for
 * `caller_is_operator`), and an explicit `status` wins over the holding-area
 * default. Both measured at 97a65464. The one server change this card needed —
 * the operator skipping the ratio gate, logged — is Rick's ruling of the same day.
 *
 * WHY THE DOM BUILDER LIVES HERE TOO, not only the rules. Every facility has to land
 * on BOTH the notifications client and the multiplexer, and `taskVerbs.ts` is the
 * standing receipt for what two hand-written copies cost (row 507183ff). Sharing
 * only the payload rules would still leave two forms to drift — a field on one card
 * and not the other is exactly that defect. So both clients call ONE
 * `openNewTicketCard`, and each supplies only what genuinely differs: how the POST
 * travels, who can be assigned, and what to show once the row exists.
 *
 * ⚠️ A 2xx IS NOT ALWAYS "CREATED". A caller without the operator's login who asks
 * for P0 gets a 201 carrying a `petition` field: the row exists at P1 in the holding
 * area and nothing was granted. Rendering that as "created" is the 202-reads-as-
 * approval trap one status code over (row 8ed76594), so it is its own outcome.
 *
 * Loaded as an ES module by the multiplexer bundle, and by a <script type="module">
 * on the classic notifications page, which reads the `window` globals at call time.
 */

import {
    TASK_LOOKUP_AUTH_REQUIRED_MESSAGE,
} from "./task-lookup.js";

// No answer is not a no: a POST can time out AFTER the store saved the row, so the
// card says so rather than inviting a retry that files the same ticket twice.
export const NEW_TICKET_NO_ANSWER_MESSAGE =
    "The store did not answer, so this ticket may already be saved. Search Find for its title before you try again.";

export const NEW_TICKET_PRIORITIES = Object.freeze( [ "P0", "P1", "P2", "P3", "P4", "P5" ] );
export const NEW_TICKET_TYPES      = Object.freeze( [ "task", "bug", "decision" ] );

/**
 * Rick's defaults, by keypress 2026-09-10: P2, approved (live board).
 *
 * ⚠️ THE EPIC KEY DEFAULT IS NOT A RULING OF HIS, IT IS THE STORE'S. The create door's
 * epic-key guard is ENFORCING — measured 2026-09-10, a create with no `correlation_key`
 * answers 422 "no epic key". Its own message names "epic:unassigned" as the deliberate
 * answer for a row that belongs to no story. So the card PRE-FILLS it, visibly and
 * editably, rather than letting his first ticket bounce.
 */
export const NEW_TICKET_DEFAULTS = Object.freeze( {
    priority        : "P2",
    approved        : true,
    item_class      : "task",
    project         : "lupin",
    correlation_key : "epic:unassigned",
} );

/**
 * Every field the card offers, in display order. Both clients render exactly these,
 * because both render through `openNewTicketCard` — the parity test asserts it.
 */
export const NEW_TICKET_FIELDS = Object.freeze( [
    "title", "details", "owner_persona", "accountable_manager",
    "priority", "approved", "item_class", "correlation_key", "project",
] );

/**
 * The declared creator. The server writes `recorded_actor( declared, account )`, so
 * Rick's validated login becomes the identity whatever this says.
 *
 * ⚠️ IT IS JUST "rick", AND NOT "rick new-ticket-card", ON PURPOSE. An owned-work row
 * filed with no owner defaults its owner to `persona_from_created_by( created_by )`,
 * which strips only a trailing hex session id — so a door name here would become the
 * OWNER, a persona nobody is. Read in task_store_rules.py before this was chosen.
 */
export const NEW_TICKET_CREATED_BY = "rick";

export const NEW_TICKET_TITLE_REQUIRED_MESSAGE = "A title is required.";
export const NEW_TICKET_OVERLAY_ID             = "new-ticket-overlay";

/**
 * Trimmed string, or "" for anything that is not a string.
 *
 * @param {unknown} value
 * @returns {string}
 */
function clean( value ) {
    return typeof value === "string" ? value.trim() : "";
}

/**
 * Turn what the form holds into the POST body, or say why it cannot be sent.
 *
 * Requires:
 *   - `fields` is an object (any keys may be missing)
 *
 * Ensures:
 *   - a blank title → `{ ok: false, error }`, and no payload at all
 *   - an unknown priority or type → `{ ok: false, error }` naming the value
 *   - otherwise `{ ok: true, payload }` where:
 *       · `status` is "queued" when approved, "not_approved" when not — the create
 *         whitelist admits both, so "not approved" is a real choice, not a default
 *       · `body` carries Details; it and the two people fields are OMITTED when
 *         blank, so the server's own defaults apply rather than an empty string
 *       · a blank project or epic key falls back to its default — the epic key is
 *         never omitted, because the store refuses a create without one
 *   - pure; never throws
 *
 * @param {Record<string, unknown>} fields
 * @returns {{ ok: true, payload: Record<string, string> } | { ok: false, error: string }}
 */
export function buildNewTicketPayload( fields ) {
    const title = clean( fields.title );
    if ( !title ) return { ok: false, error: NEW_TICKET_TITLE_REQUIRED_MESSAGE };

    const priority = clean( fields.priority ) || NEW_TICKET_DEFAULTS.priority;
    if ( !NEW_TICKET_PRIORITIES.includes( priority ) ) {
        return { ok: false, error: `Unknown priority "${ priority }".` };
    }
    const itemClass = clean( fields.item_class ) || NEW_TICKET_DEFAULTS.item_class;
    if ( !NEW_TICKET_TYPES.includes( itemClass ) ) {
        return { ok: false, error: `Unknown ticket type "${ itemClass }".` };
    }

    /** @type {Record<string, string>} */
    const payload = {
        item_class : itemClass,
        title,
        project    : clean( fields.project ) || NEW_TICKET_DEFAULTS.project,
        created_by : NEW_TICKET_CREATED_BY,
        priority,
        status          : fields.approved === false ? "not_approved" : "queued",
        correlation_key : clean( fields.correlation_key ) || NEW_TICKET_DEFAULTS.correlation_key,
    };
    const details = clean( fields.details );
    if ( details ) payload.body = details;
    for ( const key of [ "owner_persona", "accountable_manager" ] ) {
        const value = clean( fields[ key ] );
        if ( value ) payload[ key ] = value;
    }
    return { ok: true, payload };
}

/**
 * The server's `detail`, from a response body that may be JSON text, an object, or
 * nothing useful.
 *
 * Ensures:
 *   - a string `detail` passes through verbatim — the refusals on this door are
 *     written to be read, and they name the rule that fired
 *   - a pydantic list of errors becomes their `msg` fields joined with "; "
 *   - non-JSON text comes back trimmed; anything else comes back ""
 *   - never throws
 *
 * @param {unknown} bodyOrText
 * @returns {string}
 */
export function detailFrom( bodyOrText ) {
    let parsed = bodyOrText;
    if ( typeof bodyOrText === "string" ) {
        try {
            parsed = JSON.parse( bodyOrText );
        } catch {
            return bodyOrText.trim();
        }
    }
    if ( parsed === null || typeof parsed !== "object" ) return "";
    const detail = /** @type {{ detail?: unknown }} */ ( parsed ).detail;
    if ( typeof detail === "string" ) return detail;
    if ( Array.isArray( detail ) ) {
        return detail
            .map( ( e ) => ( e && typeof e.msg === "string" ) ? e.msg : JSON.stringify( e ) )
            .join( "; " );
    }
    return "";
}

/**
 * Which outcome a create produced, as a state token plus the sentence to show.
 *
 * Ensures:
 *   - 2xx with a `petition` field → "petition": the row exists but is NOT on the
 *     board and was NOT granted its priority
 *   - any other 2xx → "created", naming the short id and which pile the row landed
 *     in, and handing the row back
 *   - 401 → "auth_required", in the lookup box's words (one condition, one wording)
 *   - 403 → "refused" · 422 → "invalid", each with the server's detail
 *   - no answer at all (status 0: a timeout or a network throw) → "unreachable", and
 *     the sentence warns the row may already exist — a POST that timed out after the
 *     store saved it would otherwise be filed twice by an honest retry
 *   - any other status (404, 409, 429, 5xx) → "failed", naming the status and the
 *     server's own words, so a real cause is never replaced by "try again"
 *
 * @param {number} status
 * @param {unknown} bodyOrText
 * @returns {{ state: string, text: string, row: Record<string, unknown> | null }}
 */
export function describeNewTicketResult( status, bodyOrText ) {
    if ( status >= 200 && status < 300 ) {
        const row = ( bodyOrText !== null && typeof bodyOrText === "object" )
            ? /** @type {Record<string, unknown>} */ ( bodyOrText ) : {};
        const shortId = typeof row.id === "string" ? row.id.slice( 0, 8 ) : "";
        if ( row.petition ) {
            return {
                state : "petition",
                text  : `Filed ${ shortId } in the holding area and sent for approval — it is not on the board yet.`,
                row,
            };
        }
        const pile = row.status === "queued" ? "on the board" : "in the holding area";
        return { state: "created", text: `Created ${ shortId } — ${ pile }.`, row };
    }
    if ( status === 401 ) return { state: "auth_required", text: TASK_LOOKUP_AUTH_REQUIRED_MESSAGE, row: null };
    if ( status === 403 ) {
        return { state: "refused", text: detailFrom( bodyOrText ) || "The store refused this ticket.", row: null };
    }
    if ( status === 422 ) {
        return { state: "invalid", text: detailFrom( bodyOrText ) || "The store could not accept this ticket.", row: null };
    }
    if ( status === 0 ) return { state: "unreachable", text: NEW_TICKET_NO_ANSWER_MESSAGE, row: null };
    const detail = detailFrom( bodyOrText );
    return {
        state : "failed",
        text  : detail ? `The store answered ${ status }: ${ detail }` : `The store answered ${ status } and gave no reason.`,
        row   : null,
    };
}

/**
 * The names offered under "Assigned to": every non-blank string across the given
 * lists, once each, sorted.
 *
 * @param {...unknown[]} lists
 * @returns {string[]}
 */
export function assigneeOptions( ...lists ) {
    const seen = new Set();
    for ( const list of lists ) {
        for ( const name of list ) {
            const value = clean( name );
            if ( value ) seen.add( value );
        }
    }
    return [ ...seen ].sort();
}

/**
 * The Escape / Ctrl+Enter listener of the open card, so closing can detach it.
 *
 * @type {( ( e: KeyboardEvent ) => void ) | null}
 */
let activeKeyListener = null;

/**
 * Remove the open card, if any, and its document key listener. Idempotent.
 */
export function closeNewTicketCard() {
    if ( activeKeyListener !== null ) {
        document.removeEventListener( "keydown", activeKeyListener );
        activeKeyListener = null;
    }
    document.getElementById( NEW_TICKET_OVERLAY_ID )?.remove();
}

/**
 * Build one labelled row of the form.
 *
 * @param {string} tid
 * @param {string} field
 * @param {string} label
 * @param {HTMLElement} control
 */
function formRow( tid, field, label, control ) {
    const row = document.createElement( "div" );
    row.className = `new-ticket-row new-ticket-row-${ field }`;
    const labelEl = document.createElement( "label" );
    labelEl.className = "new-ticket-label";
    labelEl.textContent = label;
    labelEl.htmlFor = `${ tid }-${ field }`;
    control.id = `${ tid }-${ field }`;
    control.setAttribute( "data-field", field );
    control.setAttribute( "data-testid", `${ tid }-${ field }` );
    row.append( labelEl, control );
    return row;
}

/**
 * @param {readonly string[]} values
 * @param {string} selected
 * @param {Record<string, string>} [labels]
 */
function selectOf( values, selected, labels = {} ) {
    const select = document.createElement( "select" );
    select.className = "new-ticket-select";
    for ( const value of values ) {
        const option = document.createElement( "option" );
        option.value = value;
        option.textContent = labels[ value ] ?? value;
        select.append( option );
    }
    select.value = selected;
    return select;
}

/** @param {string} placeholder */
function textInput( placeholder ) {
    const input = document.createElement( "input" );
    input.type = "text";
    input.className = "new-ticket-input";
    input.placeholder = placeholder;
    return input;
}

/**
 * Open the New Ticket card over the page.
 *
 * Requires:
 *   - a DOM is available
 *   - `opts.postTicket` resolves `{ status, body }` on 2xx and `{ status, text }`
 *     otherwise; a rejection is treated as "the store did not answer"
 *
 * Ensures:
 *   - exactly one card is open: a second call replaces the first
 *   - every field in NEW_TICKET_FIELDS is rendered once, each carrying `data-field`
 *   - defaults are Rick's: P2, approved, task, lupin
 *   - Escape, Cancel or a click on the backdrop closes without sending anything
 *   - Ctrl+Enter (or Cmd+Enter) and Create both submit
 *   - a blank title is refused WITHOUT a request
 *   - a second submit while one is in flight sends nothing
 *   - "created" closes the card and hands the row to `onCreated`; every other outcome
 *     keeps the card open with the typed values intact and says what happened
 *   - never throws out of `submit`
 *
 * @param {{
 *   postTicket : ( payload: Record<string, string> ) => Promise<{ status: number, body?: unknown, text?: string }>,
 *   assignees? : string[],
 *   onCreated? : ( row: Record<string, unknown> ) => void,
 *   testidPrefix? : string,
 * }} opts
 */
export function openNewTicketCard( opts ) {
    closeNewTicketCard();
    const tid = opts.testidPrefix ?? "new-ticket";

    const overlay = document.createElement( "div" );
    overlay.id = NEW_TICKET_OVERLAY_ID;
    overlay.className = "task-body-overlay new-ticket-overlay";
    overlay.setAttribute( "data-testid", tid );

    const panel = document.createElement( "div" );
    panel.className = "task-body-overlay-content new-ticket-card";
    panel.setAttribute( "role", "dialog" );
    panel.setAttribute( "aria-modal", "true" );
    panel.setAttribute( "aria-label", "New ticket" );

    const header = document.createElement( "div" );
    header.className = "task-body-overlay-header new-ticket-header";
    header.textContent = "New ticket";

    const listId = `${ tid }-assignees`;
    const datalist = document.createElement( "datalist" );
    datalist.id = listId;
    for ( const name of opts.assignees ?? [] ) {
        const option = document.createElement( "option" );
        option.value = name;
        datalist.append( option );
    }

    const title = textInput( "What needs doing" );
    const details = document.createElement( "textarea" );
    details.className = "new-ticket-details";
    details.rows = 8;
    details.placeholder = "Background material — context, links, what you already know. Whoever picks this up starts here.";
    const owner = textInput( "Unassigned" );
    owner.setAttribute( "list", listId );
    const manager = textInput( "Optional" );
    manager.setAttribute( "list", listId );
    const priority = selectOf( NEW_TICKET_PRIORITIES, NEW_TICKET_DEFAULTS.priority );
    const approved = selectOf( [ "yes", "no" ], "yes", {
        yes : "Approved — live board",
        no  : "Not approved — holding area",
    } );
    const itemClass = selectOf( NEW_TICKET_TYPES, NEW_TICKET_DEFAULTS.item_class );
    const epic = textInput( "epic:…" );
    epic.value = NEW_TICKET_DEFAULTS.correlation_key;
    const project = textInput( NEW_TICKET_DEFAULTS.project );
    project.value = NEW_TICKET_DEFAULTS.project;

    const controls = {
        title, details, owner_persona: owner, accountable_manager: manager,
        priority, approved, item_class: itemClass, correlation_key: epic, project,
    };

    const form = document.createElement( "div" );
    form.className = "new-ticket-form";
    form.append(
        formRow( tid, "title", "Title", title ),
        formRow( tid, "details", "Details", details ),
        formRow( tid, "owner_persona", "Assigned to", owner ),
        formRow( tid, "accountable_manager", "Accountable manager", manager ),
        formRow( tid, "priority", "Priority", priority ),
        formRow( tid, "approved", "Approval", approved ),
        formRow( tid, "item_class", "Type", itemClass ),
        formRow( tid, "correlation_key", "Epic key", epic ),
        formRow( tid, "project", "Project", project ),
        datalist,
    );

    const result = document.createElement( "div" );
    result.className = "new-ticket-result";
    result.setAttribute( "role", "status" );
    result.setAttribute( "data-testid", `${ tid }-result` );

    const createButton = document.createElement( "button" );
    createButton.type = "button";
    createButton.className = "new-ticket-create";
    createButton.textContent = "Create";
    createButton.setAttribute( "data-testid", `${ tid }-create` );

    const cancelButton = document.createElement( "button" );
    cancelButton.type = "button";
    cancelButton.className = "new-ticket-cancel";
    cancelButton.textContent = "Cancel";
    cancelButton.setAttribute( "data-testid", `${ tid }-cancel` );

    const actions = document.createElement( "div" );
    actions.className = "new-ticket-actions";
    actions.append( result, cancelButton, createButton );

    panel.append( header, form, actions );
    overlay.append( panel );

    /** @param {string} text @param {string} state */
    const show = ( text, state ) => {
        result.textContent = text;
        result.setAttribute( "data-state", state );
    };

    const read = () => ( {
        title               : title.value,
        details             : details.value,
        owner_persona       : owner.value,
        accountable_manager : manager.value,
        priority            : priority.value,
        approved            : approved.value === "yes",
        item_class          : itemClass.value,
        correlation_key     : epic.value,
        project             : project.value,
    } );

    let inFlight = false;
    const submit = async () => {
        if ( inFlight ) return;
        const built = buildNewTicketPayload( read() );
        if ( !built.ok ) {
            show( built.error, "invalid-form" );
            title.focus();
            return;
        }
        inFlight = true;
        createButton.disabled = true;
        show( "Creating…", "pending" );
        let outcome;
        try {
            const response = await opts.postTicket( built.payload );
            outcome = describeNewTicketResult( response.status, response.body ?? response.text );
        } catch {
            outcome = describeNewTicketResult( 0, undefined );
        }
        inFlight = false;
        createButton.disabled = false;
        show( outcome.text, outcome.state );
        if ( outcome.state === "created" && outcome.row !== null ) {
            closeNewTicketCard();
            opts.onCreated?.( outcome.row );
        }
    };

    const close = () => closeNewTicketCard();

    overlay.addEventListener( "click", close );
    panel.addEventListener( "click", ( e ) => e.stopPropagation() );
    cancelButton.addEventListener( "click", close );
    createButton.addEventListener( "click", () => void submit() );

    activeKeyListener = ( /** @type {KeyboardEvent} */ e ) => {
        if ( e.key === "Escape" ) { close(); return; }
        if ( e.key === "Enter" && ( e.ctrlKey || e.metaKey ) ) {
            e.preventDefault();
            void submit();
        }
    };
    document.addEventListener( "keydown", activeKeyListener );

    document.body.append( overlay );
    title.focus();
    return { overlay, controls, result, createButton, submit, close };
}

// The classic-script bridge, same shape as task-lookup.js: notifications.js is not a
// module, so it reads these off `window` at call time.
if ( typeof window !== "undefined" ) {
    window.LUPIN_OPEN_NEW_TICKET_CARD  = openNewTicketCard;
    window.LUPIN_CLOSE_NEW_TICKET_CARD = closeNewTicketCard;
    window.LUPIN_NEW_TICKET_ASSIGNEES  = assigneeOptions;
/* c8 ignore next */ // tsx phantom on the bridge's closing brace: DA/BRDA zero-hit even in the bridge test's process, whose body ran (measured 2026-09-10); both paths are driven — no-window by task_create.test.ts, window by task_create_window_bridge.test.ts.
}
