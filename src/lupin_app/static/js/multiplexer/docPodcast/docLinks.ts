/* c8 ignore next */ // tsx phantom branch.
// Doc viewer: relative links in a rendered markdown file (row e45c7c7b).
//
// The doc viewer page is the one page both clients show a document through, so fixing the links here fixes
// the reading pane, the legacy pane and the standalone page together. The page tells us which file it is
// showing (the same event and global the podcast button uses); we then rewrite each relative `href` in the
// rendered text to `/app/docs?path=<scope>/<resolved>` as soon as the page renders it. Rewriting the attribute
// rather than catching the click keeps middle-click, copy-link and both clients' own doc-link routing working.
import { rewriteRelativeDocLinks } from "../render/docLink";
import { FILE_EVENT, FILE_PATH_GLOBAL } from "./docPodcast";

/** The element the page renders the document into. */
export const TARGET_ID = "doc-viewer-target";

/** The window global the page sets when its event fired before this module loaded. */
export interface DocLinksWindowLike {
  [FILE_PATH_GLOBAL]?: string;
}

/**
 * Keep the relative links in the rendered document pointing at the viewer.
 *
 * Requires: `doc` holds an element with id {@link TARGET_ID} (the page's HTML always does).
 * Ensures: once the page announces a file, links already rendered are rewritten and so is anything rendered later.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (same as docLink.ts isPaneResidentAnchor); the body below is fully covered.
export function bindDocRelativeLinks( win: DocLinksWindowLike, doc: Document ): void {
  const startFor = ( docPath: string ): void => {
    const target = doc.getElementById( TARGET_ID )!;
    const rewrite = (): void => { rewriteRelativeDocLinks( target, docPath ); };
    new MutationObserver( rewrite ).observe( target, { childList: true, subtree: true } );
    rewrite();
  };
  doc.addEventListener( FILE_EVENT, ( ev: Event ) => startFor( ( ev as CustomEvent<{ path: string }> ).detail.path ) );
  if ( typeof win[ FILE_PATH_GLOBAL ] === "string" ) startFor( win[ FILE_PATH_GLOBAL ] );
}
