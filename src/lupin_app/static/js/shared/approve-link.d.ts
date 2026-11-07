// Type declaration for the shared one-click approve-link module.
//
// The implementation is plain JS because it must also load as a browser module on the
// classic-script notifications page, which has no build step. multiplexer/render/approveLink.ts
// re-exports these names, so the TypeScript bundle uses the same file rather than a second copy.

/** The part of a task row these links read. */
export interface ApproveLinkRow {
    title?          : string;
    status?         : string;
    priority?       : string;
    owner_persona?  : string;
    body?           : string;
}

/** What a send answers: ok, or the server's own words. It never throws. */
export type ApproveSendResult = { ok: true } | { ok: false; message: string };

/** The one call the click handlers need. */
export interface ApproveSender {
    transitionTask( id: string, toStatus: string, extras: Record<string, string | null> ): Promise<ApproveSendResult>;
}

/** Reads one row for the 📋 link and the redraw check; null when the read failed. */
export type TaskReader = ( id: string ) => Promise<ApproveLinkRow | null>;

/** Shows text the way the abstract 📋 does: in the Reading Pane or the tooltip, by layout. */
export type AbstractShower = ( anchor: Element, abstract: string, title: string ) => void;

/** What a priority link names: the row and the level it admits the row at. */
export interface PriorityLink { rowId: string; priority: string }

/** What a batch link asks for: the ids, the move, and the reason a drop carries. */
export interface BatchLink { ids: string[]; move: "queued" | "dropped"; reason: string | null }

/** Every approve link starts here, after loopback normalization. */
export declare const APPROVE_LINK_PREFIX: string;
/** A priority link ends with this and a level. */
export declare const PRIORITY_LINK_PARAM: string;
/** Every 📋 view link starts here. */
export declare const VIEW_LINK_PREFIX: string;
/** Every batch approve link starts here. */
export declare const BATCH_APPROVE_PREFIX: string;
/** Every batch view link starts here. */
export declare const BATCH_VIEW_PREFIX: string;
/** What a disabled, already-approved link reads. */
export declare const APPROVED_TEXT: string;

/** The href without a loopback origin, or null for a null or empty href. */
export declare function normalizeDocLinkHref( href: string | null ): string | null;
/** The row id an approve-link href names, or null. */
export declare function approveRowId( href: string | null ): string | null;
/** The row and level a priority-link href names, or null. */
export declare function approvePriorityLink( href: string | null ): PriorityLink | null;
/** The row id a 📋 view-link href names, or null. */
export declare function viewRowId( href: string | null ): string | null;
/** A comma list of full row ids as an array, or null when the list cannot be trusted. */
export declare function parseBatchIds( list: string | null ): string[] | null;
/** What a batch approve-link href asks for, or null when it is not one or cannot be trusted. */
export declare function batchLinkOf( href: string | null ): BatchLink | null;
/** The ids a batch 📋 view-link href names, or null. */
export declare function batchViewIds( href: string | null ): string[] | null;
/** One block of text: a row's title, priority, owner, status and body. */
export declare function taskOverlayText( row: ApproveLinkRow ): string;
/** The reader built on an api client's `get`. Any failure reads as null. */
export declare function taskReaderFor( api: { get<T>( path: string ): Promise<T> } ): TaskReader;
/** Checks every unchecked approve link under the roots, one read per distinct row id. */
export declare function markApproveLinks( roots: Iterable<Element>, reader: TaskReader ): Promise<void>;
/** Checks the links under root now and each batch drawn later. Returns a stop function. */
export declare function observeApproveLinks( root: Element, reader: TaskReader ): () => void;
/** Applies one move to every listed row; one line per row. */
export declare function applyBatch( link: BatchLink, sender: ApproveSender ): Promise<string[]>;
/** Handles a click on an approve link; true when it claimed the click. */
export declare function handleApproveLinkClick( ev: Event, target: Element, sender: ApproveSender ): boolean;
/** Handles a click on a priority link; true when it claimed the click. */
export declare function handleApprovePriorityLinkClick( ev: Event, target: Element, sender: ApproveSender ): boolean;
/** Handles a click on a 📋 view link; true when it claimed the click. */
export declare function handleViewLinkClick( ev: Event, target: Element, reader: TaskReader, show: AbstractShower ): boolean;
/** Handles a click on a batch approve link; true when it claimed the click. */
export declare function handleBatchApproveLinkClick( ev: Event, target: Element, sender: ApproveSender ): boolean;
/** Handles a click on a batch 📋 view link; true when it claimed the click. */
export declare function handleBatchViewLinkClick( ev: Event, target: Element, reader: TaskReader, show: AbstractShower ): boolean;

/** Puts the surface on a window object as `LUPIN_APPROVE_LINK`. */
export declare function publishOnWindow( win: object ): void;
