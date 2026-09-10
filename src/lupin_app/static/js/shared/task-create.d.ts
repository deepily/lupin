// Type declaration for the shared New Ticket card module.
//
// The implementation is plain JS because it must also load as a browser module on
// the classic-script notifications page, which has no build step. This declaration
// lets the TypeScript multiplexer bundle import the same file — form included —
// instead of keeping a second card that can drift from the first.

export declare const NEW_TICKET_PRIORITIES: readonly string[];
export declare const NEW_TICKET_TYPES: readonly string[];
export declare const NEW_TICKET_DEFAULTS: Readonly<{
    priority   : string;
    approved   : boolean;
    item_class      : string;
    project         : string;
    correlation_key : string;
}>;
export declare const NEW_TICKET_FIELDS: readonly string[];
export declare const NEW_TICKET_CREATED_BY: string;
export declare const NEW_TICKET_TITLE_REQUIRED_MESSAGE: string;
export declare const NEW_TICKET_NO_ANSWER_MESSAGE: string;
export declare const NEW_TICKET_OVERLAY_ID: string;

/** The POST body. Optional keys are omitted when blank. */
export type NewTicketPayload = Record<string, string>;

export type NewTicketBuild =
    | { ok: true;  payload: NewTicketPayload }
    | { ok: false; error: string };

/** What a client's transport hands back: the parsed body on 2xx, raw text otherwise. */
export interface NewTicketTransportResult {
    status : number;
    body?  : unknown;
    text?  : string;
}

export interface NewTicketOutcome {
    state : string;
    text  : string;
    row   : Record<string, unknown> | null;
}

export interface NewTicketCardOptions {
    postTicket    : ( payload: NewTicketPayload ) => Promise<NewTicketTransportResult>;
    assignees?    : string[];
    onCreated?    : ( row: Record<string, unknown> ) => void;
    testidPrefix? : string;
}

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
    result       : HTMLElement;
    createButton : HTMLButtonElement;
    submit       : () => Promise<void>;
    close        : () => void;
}

export declare function buildNewTicketPayload( fields: Record<string, unknown> ): NewTicketBuild;
export declare function detailFrom( bodyOrText: unknown ): string;
export declare function describeNewTicketResult( status: number, bodyOrText: unknown ): NewTicketOutcome;
export declare function assigneeOptions( ...lists: unknown[][] ): string[];
export declare function closeNewTicketCard(): void;
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
