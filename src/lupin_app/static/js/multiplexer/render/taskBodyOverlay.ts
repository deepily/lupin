/* c8 ignore next */ // tsx phantom-branch artifact, file header.
// The shared task-body overlay.
//
// The task list's 📄 and a card's 📋 view link both open it.
// It was a private method of TaskRowController and moved here unchanged.
// The card link and the task list open the same overlay, so the two cannot drift.

/** The document-level Escape listener for the open overlay; null when none is open. */
let overlayKeyListener : ( ( e: KeyboardEvent ) => void ) | null = null;

/**
 * Show a small overlay with a task's text, built with createElement and textContent.
 *
 * Requires:
 *   - bodyText is the text to show (set as textContent, never as HTML)
 *   - idLabel is the short id for the header (may be "")
 *
 * Ensures:
 *   - any prior overlay is removed first (single instance)
 *   - the overlay carries an id header + the text in a <pre> (whitespace kept)
 *   - a backdrop click or Escape removes the overlay and detaches its keydown listener
 */
export function openTaskBodyOverlay( bodyText: string, idLabel: string ): void {
  dismissTaskBodyOverlay();

  const overlay = document.createElement( "div" );
  overlay.id        = "task-body-overlay";
  overlay.className = "task-body-overlay";

  const panel = document.createElement( "div" );
  panel.className = "task-body-overlay-content";

  const header = document.createElement( "div" );
  header.className = "task-body-overlay-header";
  header.textContent = idLabel ? `Task ${idLabel}` : "Task detail";

  const pre = document.createElement( "pre" );
  pre.className = "task-body-overlay-body";
  pre.textContent = bodyText;

  panel.appendChild( header );
  panel.appendChild( pre );
  overlay.appendChild( panel );

  overlay.addEventListener( "click", () => dismissTaskBodyOverlay() );
  panel.addEventListener( "click", ( e ) => e.stopPropagation() );

  overlayKeyListener = ( e: KeyboardEvent ): void => {
    if ( e.key === "Escape" ) dismissTaskBodyOverlay();
  };
  document.addEventListener( "keydown", overlayKeyListener );

  document.body.appendChild( overlay );
}

/** Remove the body overlay and its Esc listener. Idempotent. */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line.
export function dismissTaskBodyOverlay(): void {
  if ( overlayKeyListener !== null ) {
    document.removeEventListener( "keydown", overlayKeyListener );
    overlayKeyListener = null;
  }
  const existing = document.getElementById( "task-body-overlay" );
  if ( existing !== null ) existing.remove();
}
