/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Console tee — SessionTranscriptRenderer (row 27760534, plan §4, slice 7).
//
// Paints one watched seat's live CC console inside the reading pane, and owns the console's
// lifecycle there. Mounted on `#session-transcript-mount`, which sits beside the pane body
// and is shown INSTEAD of it while the pane's content axis is "console" (ReadingPaneStore).
//
// 🔴 PROSE AND TOOL CONTENT DO NOT SHARE A RENDERER (plan §3). `kind: text` renders as
// markdown; everything else — tool calls, tool results, thinking, and any kind this client
// does not recognise — renders as PLAIN TEXT through `textContent`. Markdown would mangle a
// file dump (`#` becomes a heading, `*` a list), and an unknown kind is shown, never dropped:
// the server's mapper is open-ended on purpose, and this surface exists to show everything.
//
// Newest at the BOTTOM (ruling OSQ-9). Auto-follow pins the bottom edge while the reader is
// there; scrolling up stops it, and "Jump to live" brings it back. "Load earlier" at the top
// pages backwards and prepends without moving what the reader is looking at.
//
// Lifecycle (plan §4, the four exits): open → `showConsole` then watch; close → the pane's
// content leaves "console" and this renderer UNWATCHES; switch seat → the store unwatches the
// old seat before watching the new; Back is disabled by the pane while the console shows, and
// bust-out POPS the console out to its own page (`/app/console`, Rick's ruling 2026-09-28),
// leaving the pane the way close does. Unmount unwatches too, so no path leaves a live watch
// behind.
//
// The sender card's console button TOGGLES, like a document's abstract indicator (Rick,
// 2026-09-28): `toggleSeat` is the one place that decides open, switch or close, and
// `showingSeat` is what the button reads to paint itself pressed.

import type { EventBus } from "../shared/EventBus";
import type { PaneContent } from "../shared/types";
import type { SessionTranscriptSnapshot, TranscriptBlock } from "../stores/SessionTranscriptStore";
import { html } from "./html";
import { renderMarkdown } from "./markdown";

export interface SessionTranscriptStoreLike {
  open( ccSessionId: string ): Promise<void>;
  close(): void;
  loadEarlier(): Promise<void>;
  snapshot(): SessionTranscriptSnapshot;
}

export interface ReadingPaneConsoleLike {
  getPaneContent(): PaneContent;
  showConsole( title: string ): boolean;
  /** Leave the console for the reading stack; false when there is nothing to leave. */
  showReading(): boolean;
}

export interface SessionTranscriptRenderer {
  mount( root: HTMLElement ): void;
  unmount(): void;
  /**
   * Open the console on a seat by its FULL stable id. Returns false — and watches nothing —
   * when the pane refuses (the action-required card owns it).
   */
  openSeat( ccSessionId: string, title: string ): boolean;
  /**
   * The console button's click. Closes the console when THIS seat is showing (the pane returns
   * to where it was, exactly as its close button leaves it); otherwise opens or switches to it.
   * Returns true when the seat is showing afterwards.
   */
  toggleSeat( ccSessionId: string, title: string ): boolean;
  /** The seat whose console the pane is showing now, or null when it shows none. */
  showingSeat(): string | null;
  /** True while the list is pinned to the live end. */
  isFollowing(): boolean;
  forceRenderForTesting(): void;
}

export interface SessionTranscriptRendererOptions {
  eventBus : EventBus;
  stores   : {
    transcript  : SessionTranscriptStoreLike;
    readingPane : ReadingPaneConsoleLike;
  };
}

/** Within this many pixels of the bottom counts as "at the live end". */
export const FOLLOW_SLACK_PX = 4;
/** A tool call's one-line chip shows at most this many characters of its first line. */
export const TOOL_CHIP_MAX   = 120;

// A Map, not an object literal: `kind in {…}` would answer true for "constructor" or
// "toString", and a kind is server-supplied, open-ended text.
const FOLDED_LABELS: ReadonlyMap<string, string> = new Map( [
  [ "tool_result", "tool result" ],
] );

class SessionTranscriptRendererImpl implements SessionTranscriptRenderer {
  private readonly bus         : EventBus;
  private readonly transcript  : SessionTranscriptStoreLike;
  private readonly readingPane : ReadingPaneConsoleLike;
  private readonly unsubscribers: Array<() => void> = [];

  private mounted     = false;
  private following   = true;
  // Distance from the bottom captured before a "load earlier", restored after the prepend.
  private prependAnchor : number | null = null;

  private root      !: HTMLElement;
  private list      !: HTMLElement;
  private earlier   !: HTMLButtonElement;
  private liveBar   !: HTMLElement;
  private jumpBtn   !: HTMLButtonElement;
  private stateEl   !: HTMLElement;

  private onScroll  !: () => void;
  private onEarlier !: () => void;
  private onJump    !: () => void;

  constructor( opts: SessionTranscriptRendererOptions ) {
    this.bus         = opts.eventBus;
    this.transcript  = opts.stores.transcript;
    this.readingPane = opts.stores.readingPane;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) throw new Error( "SessionTranscriptRenderer.mount: already mounted" );
    this.root    = root;
    this.mounted = true;

    root.replaceChildren( html`
      <div class="session-transcript-bar session-transcript-top">
        <button type="button" class="session-transcript-earlier"
                data-testid="multiplexer-session-transcript-earlier">Load earlier</button>
      </div>
      <div class="session-transcript-list" data-testid="multiplexer-session-transcript-list"></div>
      <div class="session-transcript-bar session-transcript-bottom">
        <span class="session-transcript-state" data-testid="multiplexer-session-transcript-state"></span>
        <button type="button" class="session-transcript-jump"
                data-testid="multiplexer-session-transcript-jump">Jump to live</button>
      </div>` );
    this.earlier = root.querySelector( ".session-transcript-earlier" ) as HTMLButtonElement;
    this.list    = root.querySelector( ".session-transcript-list" ) as HTMLElement;
    this.liveBar = root.querySelector( ".session-transcript-bottom" ) as HTMLElement;
    this.jumpBtn = root.querySelector( ".session-transcript-jump" ) as HTMLButtonElement;
    this.stateEl = root.querySelector( ".session-transcript-state" ) as HTMLElement;

    this.onScroll  = (): void => { this.following = this.atLiveEnd(); this.paintChrome(); };
    this.onEarlier = (): void => this.handleLoadEarlier();
    this.onJump    = (): void => this.jumpToLive();
    this.list.addEventListener( "scroll", this.onScroll );
    this.earlier.addEventListener( "click", this.onEarlier );
    this.jumpBtn.addEventListener( "click", this.onJump );

    this.unsubscribers.push(
      this.bus.on( "store_session_transcript_changed", () => this.paint() ),
      this.bus.on( "store_reading_pane_changed",       () => this.onPaneChanged() ),
    );
    this.paint();
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    this.list.removeEventListener( "scroll", this.onScroll );
    this.earlier.removeEventListener( "click", this.onEarlier );
    this.jumpBtn.removeEventListener( "click", this.onJump );
    if ( this.transcript.snapshot().watchedCcSessionId !== null ) this.transcript.close();
    this.root.replaceChildren();
    this.mounted = false;
  }

  openSeat( ccSessionId: string, title: string ): boolean {
    if ( !this.readingPane.showConsole( title ) ) return false;
    this.following     = true;
    this.prependAnchor = null;
    void this.transcript.open( ccSessionId );
    return true;
  }

  toggleSeat( ccSessionId: string, title: string ): boolean {
    if ( this.showingSeat() !== ccSessionId ) return this.openSeat( ccSessionId, title );
    // The same exit as the pane's close button: the pane-changed listener below unwatches.
    this.readingPane.showReading();
    return false;
  }

  showingSeat(): string | null {
    if ( this.readingPane.getPaneContent() !== "console" ) return null;
    return this.transcript.snapshot().watchedCcSessionId;
  }

  isFollowing(): boolean { return this.following; }

  forceRenderForTesting(): void { this.paint(); }

  // ── lifecycle ────────────────────────────────────────────────────────────

  // The close exit, and every other way out of the console (opening a document, a switch
  // to vertical, a full pane close) lands here: the axis left "console", so unwatch.
  private onPaneChanged(): void {
    if ( this.readingPane.getPaneContent() === "console" ) return;
    if ( this.transcript.snapshot().watchedCcSessionId === null ) return;
    this.transcript.close();
  }

  // ── controls ─────────────────────────────────────────────────────────────

  private handleLoadEarlier(): void {
    this.prependAnchor = this.list.scrollHeight - this.list.scrollTop;
    void this.transcript.loadEarlier();
  }

  private jumpToLive(): void {
    this.following = true;
    this.scrollToLiveEnd();
    this.paintChrome();
  }

  private atLiveEnd(): boolean {
    return this.list.scrollHeight - this.list.scrollTop - this.list.clientHeight <= FOLLOW_SLACK_PX;
  }

  private scrollToLiveEnd(): void {
    this.list.scrollTop = this.list.scrollHeight;
  }

  // ── painting ─────────────────────────────────────────────────────────────

  private paint(): void {
    const snapshot = this.transcript.snapshot();
    this.list.replaceChildren( ...snapshot.blocks.map( ( block ) => renderTranscriptBlock( block ) ) );

    if ( this.following ) {
      this.scrollToLiveEnd();
    } else if ( this.prependAnchor !== null && !snapshot.loadingEarlier ) {
      // Keep the reader's view still: the same distance from the bottom as before the page.
      this.list.scrollTop = this.list.scrollHeight - this.prependAnchor;
      this.prependAnchor  = null;
    }
    this.paintChrome( snapshot );
  }

  private paintChrome( snapshot: SessionTranscriptSnapshot = this.transcript.snapshot() ): void {
    this.earlier.hidden   = !snapshot.canLoadEarlier;
    this.earlier.disabled = snapshot.loadingEarlier;
    this.jumpBtn.hidden   = this.following;
    this.stateEl.textContent = describeState( snapshot );
    this.liveBar.hidden   = this.following && this.stateEl.textContent === "";
  }
}

/**
 * The status line under the list.
 *
 * Ensures:
 *   - "" while the stream is simply live, so the bar can hide
 */
export function describeState( snapshot: SessionTranscriptSnapshot ): string {
  if ( snapshot.repairing )               return "Catching up…";
  if ( snapshot.streamState === "ended" ) return "Session ended";
  return "";
}

/**
 * One block → one element, by kind (plan §3's render rule).
 *
 * Ensures:
 *   - `text` renders as sanitised markdown
 *   - `tool_call` is a collapsed one-line chip whose full text is plain text
 *   - `tool_result` is folded, expandable, plain text
 *   - a `thinking` block WITH text is shown INLINE, under a dim label, as plain text — never
 *     folded (Rick, 2026-09-29, row 2742f945). Claude Code hands over reasoning text on only
 *     ~6% of blocks and what it does hand over reads as a short outcome summary, so a fold
 *     made the rare visible text look as missing as the rest
 *   - a `thinking` block with no text is a plain, dim, non-expandable label — Claude Code
 *     records most thinking as a signature with EMPTY text, and a toggle that opens onto
 *     nothing looks broken (Rick, 2026-09-28)
 *   - ANY other kind renders its text as plain text, visibly — never dropped, never thrown on
 *   - a block the server cut to budget says so
 */
export function renderTranscriptBlock( block: TranscriptBlock ): HTMLElement {
  const el   = document.createElement( "div" );
  const text = block.text ?? "";
  el.className = "session-transcript-block";
  el.setAttribute( "data-kind", block.kind );
  if ( block.role ) el.setAttribute( "data-role", block.role );

  if ( block.kind === "text" ) {
    el.appendChild( html`${ renderMarkdown( text ) }` );
  } else if ( block.kind === "thinking" && text.trim() === "" ) {
    el.appendChild( unrecordedThinking() );
  } else if ( block.kind === "thinking" ) {
    el.appendChild( inlineThinking( text ) );
  } else if ( block.kind === "tool_call" ) {
    el.appendChild( folded( chipLine( text ), text ) );
  } else if ( FOLDED_LABELS.has( block.kind ) ) {
    el.appendChild( folded( FOLDED_LABELS.get( block.kind ) as string, text ) );
  } else {
    el.appendChild( plain( text ) );
  }

  if ( block.truncated ) {
    const note = document.createElement( "div" );
    note.className   = "session-transcript-truncated";
    note.textContent = "… truncated";
    el.appendChild( note );
  }
  return el;
}

function chipLine( text: string ): string {
  const first = text.split( "\n", 1 )[ 0 ] as string;
  return first.length > TOOL_CHIP_MAX ? `${ first.slice( 0, TOOL_CHIP_MAX ) }…` : first;
}

function plain( text: string ): HTMLElement {
  const pre = document.createElement( "pre" );
  pre.textContent = text;
  return pre;
}

export const UNRECORDED_THINKING_LABEL = "💭 thinking (not recorded)";

function unrecordedThinking(): HTMLElement {
  const label = document.createElement( "div" );
  label.className   = "session-transcript-unrecorded";
  label.textContent = UNRECORDED_THINKING_LABEL;
  return label;
}

export const THINKING_LABEL = "💭 thinking";

function inlineThinking( text: string ): HTMLElement {
  const wrap  = document.createElement( "div" );
  const label = document.createElement( "div" );
  wrap.className    = "session-transcript-thinking";
  label.className   = "session-transcript-thinking-label";
  label.textContent = THINKING_LABEL;
  wrap.append( label, plain( text ) );
  return wrap;
}

function folded( label: string, text: string ): HTMLElement {
  const details = document.createElement( "details" );
  const summary = document.createElement( "summary" );
  summary.textContent = label;
  details.append( summary, plain( text ) );
  return details;
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line.
export function createSessionTranscriptRenderer( opts: SessionTranscriptRendererOptions ): SessionTranscriptRenderer {
  return new SessionTranscriptRendererImpl( opts );
}
