// Type declaration for the shared New Ticket card module.
//
// The implementation is plain JS because it must also load as a browser module on
// the classic-script notifications page, which has no build step. This declaration
// lets the TypeScript multiplexer bundle import the same file — form included —
// instead of keeping a second card that can drift from the first.

/** The priorities the card accepts, P0 to P5. */
export declare const NEW_TICKET_PRIORITIES: readonly string[];
/** The ticket types the card accepts, sent as `item_class`. */
export declare const NEW_TICKET_TYPES: readonly string[];
/**
 * The values each field starts with.
 *
 * Priority P2, approved, type task, project lupin and epic key `epic:unassigned`.
 */
export declare const NEW_TICKET_DEFAULTS: Readonly<{
    priority   : string;
    approved   : boolean;
    item_class      : string;
    project         : string;
    correlation_key : string;
}>;
/** Every field the card renders, in display order. */
export declare const NEW_TICKET_FIELDS: readonly string[];
/** The two fields that get a mic when `onDictate` is supplied, Title and Details. */
export declare const NEW_TICKET_DICTATED_FIELDS: readonly string[];
/** The creator name sent as `created_by` on every ticket the card files. */
export declare const NEW_TICKET_CREATED_BY: string;
/** The refusal shown, with no request sent, when the title is blank. */
export declare const NEW_TICKET_TITLE_REQUIRED_MESSAGE: string;
/** The sentence shown when the POST got no answer; the ticket may already be saved. */
export declare const NEW_TICKET_NO_ANSWER_MESSAGE: string;
/** The DOM id of the card's overlay element. */
export declare const NEW_TICKET_OVERLAY_ID: string;

/** The POST body. Optional keys are omitted when blank. */
export type NewTicketPayload = Record<string, string>;

/**
 * The result of building the POST body.
 *
 * It holds the payload when the fields are valid, or the reason they are not.
 */
export type NewTicketBuild =
    | { ok: true;  payload: NewTicketPayload }
    | { ok: false; error: string };

/** What a client's transport hands back: the parsed body on 2xx, raw text otherwise. */
export interface NewTicketTransportResult {
    status : number;
    body?  : unknown;
    text?  : string;
}

/**
 * How a create attempt ended.
 *
 * `state` is a token such as "created", "petition", "refused", "invalid", "unreachable" or "failed".
 * `text` is the sentence to show, and `row` is the stored row when the store answered 2xx.
 */
export interface NewTicketOutcome {
    state : string;
    text  : string;
    row   : Record<string, unknown> | null;
}

/**
 * What the card knows and the recorder does not: which field was clicked, the button
 * whose `recording`/`processing` classes the recorder toggles, and the very element to
 * write into — handed over directly, so no client has to look it up and get it wrong.
 */
export interface NewTicketDictateContext {
    field  : string;
    button : HTMLButtonElement;
    input  : HTMLInputElement | HTMLTextAreaElement;
}

/**
 * What a client hands to `openNewTicketCard`.
 *
 * `postTicket` carries the POST, `assignees` fills the "Assigned to" list, and `onCreated` receives the new row.
 * `testidPrefix` namespaces the test ids, and `onDictate` adds the mics.
 */
export interface NewTicketCardOptions {
    postTicket    : ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult>;
    assignees?    : string[];
    onCreated?    : ( row: Record<string, unknown> ) => void;
    testidPrefix? : string;
    /** Supply this and Title and Details each get a mic; omit it and neither does. */
    onDictate?    : ( ctx: NewTicketDictateContext ) => void;
}

/**
 * The open card's elements and actions.
 *
 * A caller or a test reads the fields from it and calls `submit` or `close`.
 */
export interface NewTicketCardHandle {
    overlay      : HTMLElement;
    controls     : {
        title               : HTMLInputElement;
        details             : HTMLTextAreaElement;
        owner_persona       : HTMLInputElement;
        accountable_manager : HTMLInputElement;
        priority            : HTMLSelectElement;
        approved            : HTMLSelectElement;
        item_class          : HTMLSelectElement;
        correlation_key     : HTMLInputElement;
        project             : HTMLInputElement;
    };
    /** The two mics, or nulls when no `onDictate` was supplied. */
    mics         : {
        title   : HTMLButtonElement | null;
        details : HTMLButtonElement | null;
    };
    result       : HTMLElement;
    createButton : HTMLButtonElement;
    submit       : () => Promise<void>;
    close        : () => void;
}

/** Turn the form's fields into the POST body, or return the reason they cannot be sent. */
export declare function buildNewTicketPayload( fields: Record<string, unknown> ): NewTicketBuild;
/**
 * Read the server's `detail` from a response body or text as one string.
 *
 * A string `detail` comes back unchanged and an error list has its messages joined.
 * Text that is not JSON comes back trimmed. Anything else gives "".
 */
export declare function detailFrom( bodyOrText: unknown ): string;
/** Turn a create response's status and body into an outcome state and the sentence to show. */
export declare function describeNewTicketResult( status: number, bodyOrText: unknown ): NewTicketOutcome;
/** Merge name lists into the sorted, de-duplicated names offered under "Assigned to". */
export declare function assigneeOptions( ...lists: unknown[][] ): string[];
/** Remove the open card and its key listener, if any. */
export declare function closeNewTicketCard(): void;
/** Open the New Ticket card over the page, replacing any card already open. */
export declare function openNewTicketCard( opts: NewTicketCardOptions ): NewTicketCardHandle;

// The classic-script bridge. Optional because the page loads this with its own
// <script> tag, which can fail independently — notifications.js renders that as a
// deploy-defect state instead of throwing on a missing global.
declare global {
    interface Window {
        LUPIN_OPEN_NEW_TICKET_CARD?  : ( opts: NewTicketCardOptions ) => NewTicketCardHandle;
        LUPIN_CLOSE_NEW_TICKET_CARD? : () => void;
        LUPIN_NEW_TICKET_ASSIGNEES?  : ( ...lists: unknown[][] ) => string[];
    }
}
