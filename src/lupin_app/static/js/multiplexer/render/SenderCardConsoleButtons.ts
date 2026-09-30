/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Console tee — the live-console button in each sender card's title bar (row 27760534).
//
// Rick's placement ruling, 2026-09-28: the button sits in the persona's TITLE BAR in the
// notification history, immediately to the LEFT of the persona chip — not on the session
// strip's chip, which it overloaded. (It shipped on the strip first; that was wrong.)
//
// 🔴 CARDS ARE RE-RENDERED FROM A CACHE, SO THE BUTTON IS PAINTED FROM OUTSIDE AND REPAINTED
// ON EVERY CHANGE. NotificationsListRenderer swaps a card's header wholesale when its inputs
// move, which drops anything another renderer added. So this component watches the card
// container with a MutationObserver and repaints idempotently: a card whose seat resolves
// gets exactly one button, a card whose seat does not gets none. A repaint that changes
// nothing inserts nothing, so it cannot feed its own observer.
//
// The button is a real <button>, which the list renderer's delegated header handler already
// ignores (`target.closest( "button" )`), so a click opens the console and does NOT collapse
// the card.
//
// The button TOGGLES, like a document's abstract indicator (Rick, 2026-09-28). This component
// decides nothing about that: a click hands the seat to `affordance.open`, which boot wires to
// SessionTranscriptRenderer.toggleSeat — the one place open, switch and close are decided. What
// it does own is the PRESSED state, `aria-pressed` on the button whose seat is showing, and it
// repaints that on every pane or transcript change, so a console closed from the pane's own
// close button, or popped out to its tab, un-presses the button too.

import type { EventBus } from "../shared/EventBus";

export interface SenderCardConsoleAffordance {
  /** The seat's FULL stable id, or null when this card offers no console. */
  resolve( senderId: string, personaName: string | null ): string | null;
  /** The click. The host decides open, switch or close (a toggle); the button only reports it. */
  open( ccSessionId: string, title: string ): void;
  /** The seat whose console is showing now, or null. Absent: no button is ever pressed. */
  showing?(): string | null;
}

export interface SenderCardConsoleButtons {
  mount( container: HTMLElement ): void;
  unmount(): void;
  /** Test helper: repaint synchronously. */
  forceRenderForTesting(): void;
}

export interface SenderCardConsoleButtonsOptions {
  eventBus    : EventBus;
  affordance  : SenderCardConsoleAffordance;
  /** Injected for tests; defaults to the page's MutationObserver. */
  observerCtor? : typeof MutationObserver;
}

export const SENDER_CONSOLE_BUTTON_CLASS = "sender-console-btn";

class SenderCardConsoleButtonsImpl implements SenderCardConsoleButtons {
  private readonly bus          : EventBus;
  private readonly affordance   : SenderCardConsoleAffordance;
  private readonly observerCtor : typeof MutationObserver;
  private readonly unsubscribers: Array<() => void> = [];

  private container : HTMLElement | null = null;
  private observer  : MutationObserver | null = null;

  constructor( opts: SenderCardConsoleButtonsOptions ) {
    this.bus          = opts.eventBus;
    this.affordance   = opts.affordance;
    /* c8 ignore next */ // production-default fallback: the page's own MutationObserver; tests inject one.
    this.observerCtor = opts.observerCtor ?? globalThis.MutationObserver;
  }

  mount( container: HTMLElement ): void {
    if ( this.container !== null ) throw new Error( "SenderCardConsoleButtons.mount: already mounted" );
    this.container = container;
    this.observer  = new this.observerCtor( () => this.paint() );
    this.observer.observe( container, { childList : true, subtree : true } );
    this.unsubscribers.push(
      this.bus.on( "store_session_transcript_roster_changed", () => this.paint() ),
      // The pressed state follows the console, however it opened, switched or closed.
      this.bus.on( "store_reading_pane_changed",       () => this.paint() ),
      this.bus.on( "store_session_transcript_changed", () => this.paint() ),
    );
    this.paint();
  }

  unmount(): void {
    for ( const off of this.unsubscribers ) off();
    this.unsubscribers.length = 0;
    ( this.observer as MutationObserver ).disconnect();
    this.observer = null;
    for ( const btn of Array.from( ( this.container as HTMLElement ).querySelectorAll( `.${ SENDER_CONSOLE_BUTTON_CLASS }` ) ) ) btn.remove();
    this.container = null;
  }

  forceRenderForTesting(): void { this.paint(); }

  private paint(): void {
    /* c8 ignore next */ // defensive: the observer and the bus listener are both torn down in unmount() first.
    if ( this.container === null ) return;
    const showing = this.affordance.showing?.() ?? null;
    for ( const card of Array.from( this.container.querySelectorAll<HTMLElement>( ".sender-card[data-sender-id]" ) ) ) {
      this.paintCard( card, showing );
    }
  }

  private paintCard( card: HTMLElement, showing: string | null ): void {
    const header   = card.querySelector<HTMLElement>( ":scope > .sender-card-header" );
    if ( header === null ) return;
    const existing = header.querySelector<HTMLElement>( `.${ SENDER_CONSOLE_BUTTON_CLASS }` );
    const badge    = header.querySelector<HTMLElement>( ".sender-persona-badge" );
    const senderId = card.getAttribute( "data-sender-id" ) as string;
    const name     = badge?.querySelector( ".persona-badge-name" )?.textContent?.trim() || null;
    const seat     = this.affordance.resolve( senderId, name );

    if ( seat === null ) {
      if ( existing !== null ) existing.remove();
      return;
    }
    // Already there, already in place: change nothing, so the observer sees nothing. The
    // pressed state is an ATTRIBUTE, which the observer does not watch (childList only).
    if ( existing !== null && existing.dataset[ "seat" ] === seat && existing.nextElementSibling === badge ) {
      setPressed( existing, seat === showing );
      return;
    }
    if ( existing !== null ) existing.remove();

    const icon  = badge?.querySelector( ".persona-badge-icon" )?.textContent?.trim() ?? "";
    const title = `${ icon } ${ name ?? senderId } — console`.trim();
    const btn   = document.createElement( "button" );
    btn.type        = "button";
    btn.className   = SENDER_CONSOLE_BUTTON_CLASS;
    btn.title       = "Show or hide this seat's live console";
    btn.textContent = "▤";
    btn.dataset[ "seat" ]   = seat;
    btn.dataset[ "testid" ] = "multiplexer-sender-console";
    setPressed( btn, seat === showing );
    btn.addEventListener( "click", ( ev ) => {
      ev.stopPropagation();
      this.affordance.open( seat, title );
    } );

    // Immediately LEFT of the persona chip; with no chip, at the end of the title bar.
    if ( badge !== null ) badge.before( btn );
    else header.appendChild( btn );
  }
}

// Written only when it changes, so an idle repaint touches nothing at all.
function setPressed( btn: HTMLElement, pressed: boolean ): void {
  const value = pressed ? "true" : "false";
  if ( btn.getAttribute( "aria-pressed" ) !== value ) btn.setAttribute( "aria-pressed", value );
}

/* c8 ignore next */ // tsx phantom-branch artifact on the exported factory line.
export function createSenderCardConsoleButtons( opts: SenderCardConsoleButtonsOptions ): SenderCardConsoleButtons {
  return new SenderCardConsoleButtonsImpl( opts );
}
