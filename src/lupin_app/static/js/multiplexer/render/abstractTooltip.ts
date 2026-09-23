/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Vertical-layout abstract tooltip — the 📋 popover the multiplexer never had.
//
// Row fff605be (Rick, 2026-09-23): in VERTICAL layout a card's 📋 indicator did
// nothing. ReadingPaneRenderer's click delegation returns early unless the layout
// is horizontal, and the "popover handler attaches in Phase 6" noted in
// templates/notificationItem.ts never landed — so every abstract, and every doc
// link carried in one, was unreachable in vertical mode.
//
// This is the port of legacy notifications.js initAbstractTooltip's VERTICAL
// branch: one floating container on <body>, markdown-rendered content, positioned
// below the indicator (flipped above when it would clip), closed by its × button,
// a click outside it, or Escape. In HORIZONTAL layout it stands aside —
// ReadingPaneRenderer owns the indicator there and opens the Reading Pane.
//
// Styles: `.abstract-tooltip*` in css/shared/notifications-surface.css (moved
// there from notifications.css so both clients read one source).

import { html } from "./html";
import { renderMarkdown } from "./markdown";
import type { LayoutMode } from "../shared/types";

export const ABSTRACT_TOOLTIP_ID = "abstract-tooltip";

/** Gap between the indicator and the tooltip, and the minimum viewport margin (legacy values). */
const GAP_PX    = 8;
const MARGIN_PX = 10;

export interface Rect { top: number; bottom: number; left: number; width: number; }
export interface Size { width: number; height: number; }

export interface AbstractTooltipDeps {
  /** The live layout mode; the tooltip acts only when this is not "horizontal". */
  getLayoutMode(): LayoutMode;
  /** Defers measurement one frame so the :has()-driven size tiers apply first. Defaults to requestAnimationFrame. */
  schedule?: ( fn: () => void ) => void;
}

export interface AbstractTooltip {
  mount(): void;
  unmount(): void;
}

/**
 * Where to place the tooltip — the legacy arithmetic, extracted so it can be tested without layout.
 *
 * Requires:
 *   - indicator is the indicator's viewport rect; tip is the tooltip's rendered size
 *   - viewport is the window's inner size
 *
 * Ensures:
 *   - top is GAP_PX below the indicator, or GAP_PX above it when below would clip the
 *     viewport bottom (never less than MARGIN_PX)
 *   - left centres the tooltip on the indicator, clamped MARGIN_PX inside both edges
 */
export function computeTooltipPosition( indicator: Rect, tip: Size, viewport: Size ): { top: number; left: number } {
  let top = indicator.bottom + GAP_PX;
  if ( top + tip.height > viewport.height - MARGIN_PX ) {
    top = Math.max( MARGIN_PX, indicator.top - tip.height - GAP_PX );
  }
  let left = indicator.left + ( indicator.width / 2 ) - ( tip.width / 2 );
  left = Math.max( MARGIN_PX, Math.min( left, viewport.width - tip.width - MARGIN_PX ) );
  return { top, left };
}

class AbstractTooltipImpl implements AbstractTooltip {
  private tooltip  : HTMLElement | null = null;
  private readonly schedule : ( fn: () => void ) => void;

  private readonly onDocClick = ( ev: MouseEvent ): void => this.handleClick( ev );
  private readonly onKeyDown  = ( ev: KeyboardEvent ): void => {
    if ( ev.key === "Escape" ) this.hide();
  };

  constructor( private readonly deps: AbstractTooltipDeps ) {
    this.schedule = deps.schedule ?? ( ( fn ) => { requestAnimationFrame( fn ); } );
  }

  mount(): void {
    if ( this.tooltip !== null ) return;
    const frag = html`<div id="${ABSTRACT_TOOLTIP_ID}" class="abstract-tooltip" role="dialog" aria-label="Notification details"><div class="abstract-tooltip-header"><span>📋 Details</span><button type="button" class="abstract-tooltip-close" title="Close">×</button></div><div class="abstract-tooltip-content"></div></div>`;
    const tooltip = frag.firstElementChild as HTMLElement;
    ( tooltip.querySelector( ".abstract-tooltip-close" ) as HTMLElement ).addEventListener( "click", () => this.hide() );
    document.body.appendChild( tooltip );
    this.tooltip = tooltip;
    document.addEventListener( "click", this.onDocClick );
    document.addEventListener( "keydown", this.onKeyDown );
  }

  unmount(): void {
    if ( this.tooltip === null ) return;
    document.removeEventListener( "click", this.onDocClick );
    document.removeEventListener( "keydown", this.onKeyDown );
    this.tooltip.remove();
    this.tooltip = null;
  }

  private handleClick( ev: MouseEvent ): void {
    const target = ev.target as Element | null;
    /* c8 ignore next */ // defensive: a fired click always has a non-null Element target in DOM + happy-dom.
    if ( target === null ) return;

    const indicator = target.closest( ".abstract-indicator" );
    if ( indicator !== null ) {
      // Horizontal layout belongs to ReadingPaneRenderer — it opens the pane.
      if ( this.deps.getLayoutMode() === "horizontal" ) return;
      // The mux writes data-abstract RAW (setAttribute, no encoding), so it is read raw.
      this.show( indicator, indicator.getAttribute( "data-abstract" ) ?? "" );
      return;
    }

    if ( target.closest( ".abstract-tooltip" ) === null ) this.hide();
  }

  private show( indicator: Element, abstract: string ): void {
    const tooltip = this.tooltip as HTMLElement;
    const content = tooltip.querySelector( ".abstract-tooltip-content" ) as HTMLElement;
    content.replaceChildren( html`${renderMarkdown( abstract )}` );

    // Show it hidden first so the :has() size tiers take effect, then measure and place it.
    tooltip.style.visibility = "hidden";
    tooltip.classList.add( "visible" );
    this.schedule( () => {
      const tipRect = tooltip.getBoundingClientRect();
      const { top, left } = computeTooltipPosition(
        indicator.getBoundingClientRect(),
        { width: tipRect.width, height: tipRect.height },
        { width: window.innerWidth, height: window.innerHeight },
      );
      tooltip.style.top        = `${top}px`;
      tooltip.style.left       = `${left}px`;
      tooltip.style.visibility = "visible";
    } );
  }

  private hide(): void {
    if ( this.tooltip !== null ) this.tooltip.classList.remove( "visible" );
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createAbstractTooltip( deps: AbstractTooltipDeps ): AbstractTooltip {
  return new AbstractTooltipImpl( deps );
}
