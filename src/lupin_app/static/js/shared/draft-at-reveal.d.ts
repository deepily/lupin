// Type declaration for the shared draft-at-reveal module.
//
// The implementation is plain JS because it must also load as a browser module on the
// classic-script notifications page, which has no build step. multiplexer/render/templates/actionRequiredDraft.ts
// imports these names, so the TypeScript bundle uses the same file rather than a second copy.

/** The draft the seen route takes: the wire string of the answer so far. */
export interface DraftAtReveal {
    value : string;
}

/** What a client read off a card's controls. */
export interface DraftParts {
    text  : string;
    batch : ReadonlyArray< readonly [ string, string ] >;
    saved : Readonly< Record< string, string | ReadonlyArray< string > > >;
    shown : { header: string; value: string | ReadonlyArray< string > } | null | undefined;
}

/** The server's limit on a draft, counted in characters of its JSON text. */
export const DRAFT_MAX_CHARS: number;
/** Counts a draft the way the route does, as Python's json.dumps writes it. */
export function routeLength( draft: DraftAtReveal ): number;
/** Says what a card's answer would be if submitted now, or null when no answer is held. */
export function buildDraft( responseType: string | undefined, parts: DraftParts ): DraftAtReveal | null;
/** Puts the surface on a window object as `LUPIN_DRAFT_AT_REVEAL`. */
export function publishOnWindow( win: object ): void;
