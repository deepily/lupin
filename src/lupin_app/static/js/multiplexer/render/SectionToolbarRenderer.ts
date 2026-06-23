/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer section-toolbar parity (2026-06-23, Rachel 🕊️ / Mr. Radio lane).
//
// Owns the `#section-toolbar` DOM + the top-level section panes it shows/hides.
// Carbon-copy of the legacy `toggleSectionVisibility` / `saveSectionVisibility`
// behavior (notifications.js:9967-10073) in the mux store/renderer split:
//
//   - per-section toggle: click a `.toolbar-btn[data-section]` → flip the
//     target section's `.section-hidden` class + the button's `.active` state
//     + persist via ViewStateStore.setSectionVisible.
//   - collapse-all / expand-all: click `#section-toolbar-collapse-all` /
//     `-expand-all` → ViewStateStore.requestBulkAccordionCollapse(true/false),
//     which emits the bulk intent NotificationsListRenderer applies to every
//     accordion.
//   - on mount: re-apply persisted section visibility (dim button + hide
//     section for each persisted-hidden id).
//
// NO inline onclick (mux idiom + eslint no-globals): one delegated click
// listener on the toolbar root. Lifecycle mirrors MissedBadgeRenderer (throw on
// double-mount; idempotent unmount).

import { renderSectionToolbar, COLLAPSE_ALL_ID, EXPAND_ALL_ID } from "./templates/sectionToolbar";

// Minimal store surface this renderer needs (subset of ViewStateStore) — keeps
// the unit test free to inject a fake.
export interface ViewStateStoreLike {
  isSectionVisible(sectionId: string): boolean;
  setSectionVisible(sectionId: string, visible: boolean): void;
  getHiddenSectionIds(): string[];
  requestBulkAccordionCollapse(collapsed: boolean): void;
}

export interface SectionToolbarRendererStores {
  viewState : ViewStateStoreLike;
}

export interface SectionToolbarRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: drop the click listener + clear children. Idempotent. */
  unmount(): void;
}

export interface SectionToolbarRendererOptions {
  stores : SectionToolbarRendererStores;
  // The document to query for section elements. Defaults to the ambient
  // `document`; tests inject a happy-dom document for isolation. (The section
  // panes live OUTSIDE the toolbar root, so the renderer resolves them against
  // the owning document rather than `root`.)
  doc?   : Document;
}

class SectionToolbarRendererImpl implements SectionToolbarRenderer {
  private readonly stores : SectionToolbarRendererStores;
  private readonly doc    : Document;

  private root        : HTMLElement | null = null;
  private toolbar     : HTMLElement | null = null;
  private clickHandler: ((e: Event) => void) | null = null;
  private mounted     = false;

  constructor( opts: SectionToolbarRendererOptions ) {
    this.stores = opts.stores;
    /* c8 ignore next */ // defensive default: production always has ambient `document`; tests pass an explicit doc.
    this.doc    = opts.doc ?? document;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "SectionToolbarRenderer already mounted" );
    }
    this.mounted = true;
    this.root    = root;

    const toolbar = renderSectionToolbar();
    this.toolbar  = toolbar;
    root.replaceChildren( toolbar );

    this.applyPersistedSectionVisibility();

    this.clickHandler = ( e: Event ): void => this.onClick( e );
    toolbar.addEventListener( "click", this.clickHandler );
  }

  unmount(): void {
    if ( this.toolbar !== null && this.clickHandler !== null ) {
      this.toolbar.removeEventListener( "click", this.clickHandler );
    }
    this.clickHandler = null;
    this.toolbar      = null;
    if ( this.root !== null ) {
      this.root.replaceChildren();
      this.root = null;
    }
    this.mounted = false;
  }

  // -------------------------------------------------------------------------
  // Click dispatch
  // -------------------------------------------------------------------------

  private onClick( e: Event ): void {
    const target = e.target as Element | null;
    if ( target === null ) return;   // covered by null-target test

    // Accordion-action buttons first (distinct ids, no data-section).
    const collapseAll = target.closest( `#${COLLAPSE_ALL_ID}` );
    if ( collapseAll !== null ) {
      this.stores.viewState.requestBulkAccordionCollapse( true );
      return;
    }
    const expandAll = target.closest( `#${EXPAND_ALL_ID}` );
    if ( expandAll !== null ) {
      this.stores.viewState.requestBulkAccordionCollapse( false );
      return;
    }

    // Per-section visibility toggle.
    const btn = target.closest( ".toolbar-btn" ) as HTMLElement | null;
    if ( btn === null ) return;   // covered by click-outside-button test
    const sectionId = btn.dataset["section"];
    /* c8 ignore next */ // defensive: every `.toolbar-btn` the template emits carries data-section; an attribute-less toolbar button cannot arise from renderSectionToolbar.
    if ( sectionId === undefined ) return;
    this.toggleSection( sectionId, btn );
  }

  private toggleSection( sectionId: string, btn: HTMLElement ): void {
    const nextVisible = !this.stores.viewState.isSectionVisible( sectionId );
    this.stores.viewState.setSectionVisible( sectionId, nextVisible );
    btn.classList.toggle( "active", nextVisible );

    const section = this.doc.getElementById( sectionId );
    if ( section !== null ) {
      section.classList.toggle( "section-hidden", !nextVisible );
    }
  }

  // -------------------------------------------------------------------------
  // Persisted-state replay (mount)
  // -------------------------------------------------------------------------

  private applyPersistedSectionVisibility(): void {
    /* c8 ignore next */ // defensive: applyPersistedSectionVisibility runs only from mount(), after this.toolbar is set.
    if ( this.toolbar === null ) return;
    for ( const sectionId of this.stores.viewState.getHiddenSectionIds() ) {
      const btn = this.toolbar.querySelector(
        `.toolbar-btn[data-section="${sectionId}"]`,
      ) as HTMLElement | null;
      if ( btn !== null ) btn.classList.remove( "active" );

      const section = this.doc.getElementById( sectionId );
      if ( section !== null ) section.classList.add( "section-hidden" );
    }
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSectionToolbarRenderer(
  opts: SectionToolbarRendererOptions,
): SectionToolbarRenderer {
  return new SectionToolbarRendererImpl( opts );
}
