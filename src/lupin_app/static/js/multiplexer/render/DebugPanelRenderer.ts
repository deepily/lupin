/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Parity B-6 — the Debug Information panel, ported from legacy's section at
// notifications.html:1392-1400 and `addDebugMessage` (notifications.js:21171).
//
// The three writers live in `shared/debugSink.ts`; this is the surface they
// paint into. It registers itself as the sink at mount and clears it at unmount.
//
// 🔴 NEWEST FIRST — `insertBefore(div, firstChild)`, the OPPOSITE of a console
// (G4). Somebody reading this panel has just seen something go wrong and wants
// the last line, not the first; a console scrolls, a 300px box does not.
//
// 🔴 CAPPED AT 20, ENFORCED AFTER EVERY INSERT (G5). With ~629 writer calls in
// legacy, twenty lines is roughly the last second of a busy load — which is the
// honest characterisation of this panel and is why it is a companion to the
// console rather than a replacement for it (G6, G7).
//
// ⚠️ IT NEVER REVEALS ITSELF, NOT EVEN ON AN ERROR (B6). An explicit owed match:
// a panel that popped open on error would move the page under the operator at
// the exact moment they were reading something else.
//
// ⚠️ NO `.debug-info.error` RULE SHIPS, so error lines look identical to info
// lines (G8). That is legacy's state and styling them would be a visible change
// from the lead — see the note in css/multiplexer/debug-panel.css.

import {
  setDebugPanel,
  type DebugPanelSink,
} from "../shared/debugSink";
import {
  renderSectionHeader,
  wireSectionCollapse,
} from "./templates/sectionHeader";

/** The cap, enforced after every insert (G5). */
export const DEBUG_LOG_CAP = 20;

/** The one line the markup ships, which COUNTS toward the cap (B10). */
export const DEBUG_SEEDED_LINE = "System starting up...";

/** The class every line carries. Legacy `addDebugMessage` (notifications.js:21175). */
export const DEBUG_LINE_CLASS = "debug-info";

/**
 * The seeded line's class — BARE, with no type token, verbatim from legacy's
 * markup (notifications.html:1401). Every other line appends a type.
 */
export const DEBUG_SEEDED_CLASS = DEBUG_LINE_CLASS;

export interface DebugPanelRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
}

export interface DebugPanelRendererOptions {
  /** Test injection — the clock for each line's timestamp. */
  nowDateFn? : () => Date;
}

class DebugPanelRendererImpl implements DebugPanelRenderer, DebugPanelSink {
  private readonly nowDateFn : () => Date;

  private root        : HTMLElement | null = null;
  private logEl       : HTMLElement | null = null;
  private collapseOff : ( () => void ) | null = null;
  private mounted     = false;

  constructor( opts: DebugPanelRendererOptions ) {
    /* c8 ignore next */ // production-default fallback: `new Date()` is the runtime clock; tests inject a fixed-date fn.
    this.nowDateFn = opts.nowDateFn ?? ( () => new Date() );
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "DebugPanelRenderer already mounted" );

    // B7 — "Debug Information", the ONE section header with no leading emoji.
    // An empty icon is a supported value of the shared builder precisely so a
    // header like this does not need its own template.
    // B8 — no refresh, no Clear, no copy/export: the actions array is empty.
    const header = renderSectionHeader( {
      icon    : "",
      title   : "Debug Information",
      testid  : "multiplexer-debug-panel-header",
    } );

    const body = document.createElement( "div" );
    body.className = "section-content debug-panel-body";

    this.logEl = document.createElement( "div" );
    this.logEl.className = "debug-log-scrollable";
    this.logEl.setAttribute( "data-testid", "multiplexer-debug-log" );

    // B10 — the seeded line, built through the SAME path every other line takes,
    // so it counts toward the same cap and is trimmed away by the same rule.
    // Legacy ships it as markup; building it here is the same fact expressed by
    // a client that owns its own subtree.
    //
    // 🔴 ITS CLASS IS BARE `debug-info`, WITH NO TYPE TOKEN — that is legacy's
    // markup verbatim (notifications.html:1401), and it is the ONE line in the
    // panel written by a hand rather than by `addDebugMessage`, which always
    // appends a type. Emitting `debug-info info` here would have been tidier and
    // would have differed from the lead by one class token on one div, which is
    // exactly the kind of drift the Layout-Parity Oracle exists to catch.
    this.logEl.appendChild( this.lineEl( DEBUG_SEEDED_LINE, DEBUG_SEEDED_CLASS ) );

    body.appendChild( this.logEl );
    root.replaceChildren( header.header, body );

    // B3 — session-only collapse. Persistence exists since A-2 #6; legacy does
    // not persist this section, so its absence here is a decision.
    this.collapseOff = wireSectionCollapse( root, header );

    this.root    = root;
    this.mounted = true;
    setDebugPanel( this );
  }

  unmount(): void {
    // 🔴 DEREGISTER FIRST. A writer firing between the teardown of the DOM and
    // the clearing of the sink would paint into a detached node — invisible, and
    // it would keep a torn-down pane alive through the module-level reference.
    setDebugPanel( null );
    if ( this.collapseOff !== null ) this.collapseOff();
    this.collapseOff = null;
    if ( this.root !== null ) this.root.replaceChildren();
    this.root    = null;
    this.logEl   = null;
    this.mounted = false;
  }

  /**
   * Paint one line. Legacy `addDebugMessage` (notifications.js:21171).
   *
   * Requires:
   *   - message is a string; type picks the second class
   *
   * Ensures:
   *   - the line reads `[<toLocaleTimeString()>] <message>`, written through
   *     `textContent` — so markup in a message is TEXT, never parsed (G3)
   *   - it is inserted FIRST, not appended (G4)
   *   - the log is trimmed to DEBUG_LOG_CAP from the oldest end, after every
   *     insert (G5)
   *   - a no-op when the panel is not mounted
   */
  addDebugMessage( message: string, type: "info" | "error" ): void {
    /* c8 ignore next */ // defensive: the sink is deregistered in unmount BEFORE logEl is nulled, so a call cannot arrive here unmounted.
    if ( this.logEl === null ) return;

    this.logEl.insertBefore(
      this.lineEl( message, `${ DEBUG_LINE_CLASS } ${ type }` ),
      this.logEl.firstChild,
    );

    // A `while`, not an `if`: one insert can only overflow by one today, but a
    // cap that assumes that is a cap that breaks the day anything bulk-inserts.
    while ( this.logEl.children.length > DEBUG_LOG_CAP ) {
      this.logEl.removeChild( this.logEl.lastChild! );
    }
  }

  /**
   * One line's div. Takes the FULL class string rather than a type, because the
   * seeded line's class is bare `debug-info` and every other line's carries a
   * type token — a difference of legacy's markup, not of this renderer's logic.
   */
  private lineEl( message: string, className: string ): HTMLElement {
    const div = document.createElement( "div" );
    div.className = className;
    div.textContent = `[${ this.nowDateFn().toLocaleTimeString() }] ${ message }`;
    return div;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function createDebugPanelRenderer( opts: DebugPanelRendererOptions = {} ): DebugPanelRenderer {
  return new DebugPanelRendererImpl( opts );
}
