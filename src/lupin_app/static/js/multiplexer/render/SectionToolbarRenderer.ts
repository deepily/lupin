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
//   - collapse-all / expand-all: REMOVED 2026-09-15 with the buttons themselves,
//     on Rick's ruling that the pair comes off both toolbars. The store's
//     requestBulkAccordionCollapse() and the NotificationsListRenderer
//     subscriber that applies its event both remain, with no caller.
//   - on mount: re-apply persisted section visibility (dim button + hide
//     section for each persisted-hidden id).
//   - showing a section scrolls it into view through the shared scroll-reveal
//     helper, as legacy's toggleSectionVisibility does (parity A-2 #1). Hiding
//     one does not scroll, and neither does the mount reconcile.
//
// NO inline onclick (mux idiom + eslint no-globals): one delegated click
// listener on the toolbar root. Lifecycle mirrors MissedBadgeRenderer (throw on
// double-mount; idempotent unmount).

import {
  renderSectionToolbar,
  SECTION_TOGGLES,
  type SectionToggleSpec,
} from "./templates/sectionToolbar";
import { scrollRevealElement } from "./scrollReveal";

// Minimal store surface this renderer needs (subset of ViewStateStore) — keeps
// the unit test free to inject a fake.
//
// `hasSectionPreference` came OFF this surface on 2026-09-23 with the
// cold-hidden default it served: with no cold default to override, "no
// preference" and "persisted visible" want the same answer, and
// `isSectionVisible` already gives it. The method remains on ViewStateStore
// itself and now has no production caller.
export interface ViewStateStoreLike {
  isSectionVisible(sectionId: string): boolean;
  setSectionVisible(sectionId: string, visible: boolean): void;
  getHiddenSectionIds(): string[];
}

export interface SectionToolbarRendererStores {
  viewState : ViewStateStoreLike;
}

export interface SectionToolbarRenderer {
  /** Mount onto `root`. Throws on a second mount without unmount(). */
  mount( root: HTMLElement ): void;
  /** Detach: drop the click listener + clear children. Idempotent. */
  unmount(): void;
  /**
   * Programmatic reveal (parity A-2 #2b): if the section is hidden, un-hide it,
   * save the visibility and re-light its button. A no-op when already visible,
   * as legacy saves only when it un-hid. Does not scroll — the caller does, after
   * any expand of its own. Works before mount, when there is no button to light.
   */
  showSection( sectionId: string ): void;
}

export interface SectionToolbarRendererOptions {
  stores : SectionToolbarRendererStores;
  // The document to query for section elements. Defaults to the ambient
  // `document`; tests inject a happy-dom document for isolation. (The section
  // panes live OUTSIDE the toolbar root, so the renderer resolves them against
  // the owning document rather than `root`.)
  doc?   : Document;
  // The toggle specs to render and reconcile. Defaults to SECTION_TOGGLES; tests
  // pass a short list so a case can name every section it set up.
  toggles?: ReadonlyArray<SectionToggleSpec>;
}

class SectionToolbarRendererImpl implements SectionToolbarRenderer {
  private readonly stores : SectionToolbarRendererStores;
  private readonly doc    : Document;
  private readonly toggles: ReadonlyArray<SectionToggleSpec>;

  private root        : HTMLElement | null = null;
  private toolbar     : HTMLElement | null = null;
  private clickHandler: ((e: Event) => void) | null = null;
  private mounted     = false;

  constructor( opts: SectionToolbarRendererOptions ) {
    this.stores = opts.stores;
    /* c8 ignore next */ // defensive default: production always has ambient `document`; tests pass an explicit doc.
    this.doc    = opts.doc ?? document;
    this.toggles = opts.toggles ?? SECTION_TOGGLES;
  }

  mount( root: HTMLElement ): void {
    if ( this.mounted ) {
      throw new Error( "SectionToolbarRenderer already mounted" );
    }
    this.mounted = true;
    this.root    = root;

    const toolbar = renderSectionToolbar( this.toggles );
    this.toolbar  = toolbar;
    root.replaceChildren( toolbar );

    this.reconcileSectionVisibility();

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

    // Per-section visibility toggle. The collapse-all / expand-all branches that
    // stood here were removed on 2026-09-15 with their buttons (Rick's ruling).
    const btn = target.closest( ".toolbar-btn" ) as HTMLElement | null;
    if ( btn === null ) return;   // covered by click-outside-button test
    const sectionId = btn.dataset["section"];
    /* c8 ignore next */ // defensive: every `.toolbar-btn` the template emits carries data-section; an attribute-less toolbar button cannot arise from renderSectionToolbar.
    if ( sectionId === undefined ) return;
    this.toggleSection( sectionId, btn );
  }

  showSection( sectionId: string ): void {
    if ( this.stores.viewState.isSectionVisible( sectionId ) ) return;
    this.stores.viewState.setSectionVisible( sectionId, true );
    const btn = this.toolbar === null
      ? null
      : this.toolbar.querySelector<HTMLElement>( `.toolbar-btn[data-section="${sectionId}"]` );
    this.applyVisibilityToDom( sectionId, btn, true );
  }

  private toggleSection( sectionId: string, btn: HTMLElement ): void {
    const nextVisible = !this.stores.viewState.isSectionVisible( sectionId );
    this.stores.viewState.setSectionVisible( sectionId, nextVisible );
    const section = this.applyVisibilityToDom( sectionId, btn, nextVisible );
    if ( nextVisible && section !== null ) {
      void scrollRevealElement( section );
    }
  }

  // -------------------------------------------------------------------------
  // Visibility model — ONE question, asked of the store
  // -------------------------------------------------------------------------
  //
  // `isSectionVisible` IS the effective answer: it returns true unless the user
  // explicitly hid the section, which is exactly the rule now that no section
  // cold-starts hidden. The `currentEffectiveVisible` helper that stood here
  // resolved a precedence — persisted preference over cold default — between
  // two rules where only one survives, so it had become a restatement of the
  // store's own default. Restating a rule the store already owns is how two
  // pieces of code come to decide one thing and drift (2026-09-23, cec9dd43).

  // Apply a visibility decision to the DOM: the button `.active` state, the
  // `.section-hidden` class, AND the HTML `hidden` attribute. The `hidden`
  // attribute is managed in lockstep so a persisted-VISIBLE choice actually
  // reveals a section that arrived carrying `hidden` — clearing
  // `.section-hidden` alone would leave `hidden` still hiding it. The
  // pane element may be absent (e.g. a toolbar-managed section not present in a
  // given page/test) — the button is always flipped, the section only if found.
  // Returns the section element it found, or null, so the toggle can scroll it.
  // `btn` is null when showSection runs before mount.
  private applyVisibilityToDom( sectionId: string, btn: HTMLElement | null, visible: boolean ): HTMLElement | null {
    if ( btn !== null ) btn.classList.toggle( "active", visible );
    const section = this.doc.getElementById( sectionId );
    if ( section !== null ) {
      section.classList.toggle( "section-hidden", !visible );
      section.hidden = !visible;
    }
    return section;
  }

  // -------------------------------------------------------------------------
  // Reconcile (mount) — apply every toolbar section's visibility so the button
  // state + pane visibility agree with what the user persisted. Every section
  // with no stored preference comes up visible, which is also how the template
  // paints it, so a cold start touches nothing and cannot flash.
  // -------------------------------------------------------------------------

  private reconcileSectionVisibility(): void {
    /* c8 ignore next */ // defensive: reconcileSectionVisibility runs only from mount(), after this.toolbar is set.
    if ( this.toolbar === null ) return;
    for ( const spec of this.toggles ) {
      const btn = this.toolbar.querySelector(
        `.toolbar-btn[data-section="${spec.sectionId}"]`,
      ) as HTMLElement | null;
      /* c8 ignore next */ // the template renders exactly one button per SECTION_TOGGLES spec, so this querySelector always resolves; guarded defensively.
      if ( btn === null ) continue;
      this.applyVisibilityToDom( spec.sectionId, btn, this.stores.viewState.isSectionVisible( spec.sectionId ) );
    }
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createSectionToolbarRenderer(
  opts: SectionToolbarRendererOptions,
): SectionToolbarRenderer {
  return new SectionToolbarRendererImpl( opts );
}
