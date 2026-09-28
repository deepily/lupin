// Row 47759aa3 — the section toolbar binds SECTION toggles, not every button that borrows
// its class. Tiberius found this on the 📂 roots button (2026-09-27).
//
// `initToolbar` selected `.toolbar-btn` inside `#section-toolbar` and bound every
// match to `toggleSectionVisibility( btn.dataset.section )`. The 📂 button is a
// `.toolbar-btn` with NO `data-section`, so each click called it with `undefined`, fell
// through `if ( !section )`, and logged `Section not found: undefined`.
//
// 🔴 THE MARKUP'S OWN COMMENT VOUCHED FOR A PROTECTION IT DID NOT HAVE. Beside the 📂
// button it reads "NO data-section: this is not a section toggle, so the delegated section
// handler must not claim it — same shape as the layout-mode button above." The layout-mode
// button is safe because it uses a DIFFERENT CLASS (`layout-mode-btn`); the 📂 button kept
// `toolbar-btn` for its styling, which is the exact class the handler selects. The sentence
// described the neighbour's protection and read as a statement about this button. A wrong
// instruction gets caught the first time someone follows it; a wrong reassurance disarms
// the reader who would have caught it — so this file guards BOTH buttons.
//
// ⚠️ THE ERROR LOG WAS NOT THE ONLY DAMAGE, AND IT IS THE QUIETER HALF THAT PERSISTS.
// `saveSectionVisibility` ran the same unfiltered selector — `document.querySelectorAll(
// '.toolbar-btn' )`, not even scoped to the toolbar — and wrote `visibility[ undefined ]`,
// which JSON stores as the literal key "undefined". That key then lives in localStorage
// across reloads, and nothing ever removes it. Case 4 is about the stored object, not the
// console.
//
// ⚠️ A FIX THAT BINDS NOTHING WOULD PASS EVERY "no error" ASSERTION HERE. Case 2 is the
// positive control: a real section toggle still toggles, and the mount asserts the number
// of buttons it actually bound before anything is clicked. An assertion satisfiable by
// more than one path cannot tell you which one ran.
//
// ENTERED THROUGH `initToolbar`, the real registration site, rather than by calling
// `toggleSectionVisibility( undefined )` directly. The defect was in a SELECTOR, and a test
// that calls the inner method itself can never see which elements the selector chose.
//
// Run: npx tsx --test src/tests/unit/notifications_js/section_toolbar_ignores_a_button_with_no_section.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const VISIBILITY_KEY = "lupin_section_visibility_test";

let errors : string[] = [];
let ui     : Record<string, unknown>;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  // The file's last section constructs a NotificationsUI against collaborators this test
  // does not load, so the class is evaluated and the bottom-of-file init is not — the same
  // cut `doc_link_opens_in_app_in_every_layout.test.ts` makes.
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

beforeEach( () => {
  errors = [];
  localStorage.clear();
  buildDOM();
} );

/**
 * The toolbar as the page ships it: two real section toggles, plus the two buttons that
 * live in the toolbar and are NOT section toggles.
 *
 * The 📂 button carries `toolbar-btn` and no `data-section` — the shape that broke. The
 * layout-mode button carries neither, and is here so a fix that keys on something other
 * than `data-section` cannot pass by accident.
 *
 * ⚠️ THE STRAY BUTTON OUTSIDE THE TOOLBAR IS NOT DECORATION. `saveSectionVisibility` used
 * `document.querySelectorAll`, unscoped, so it would have saved any `.toolbar-btn` anywhere
 * on the page. Every `.toolbar-btn` in `notifications.html` happens to live inside
 * `#section-toolbar` today, which means a fixture built only from the real page cannot tell
 * the scoped selector from the unscoped one — the mutant would survive with nothing to
 * catch it. This element is what makes the scope load-bearing.
 */
function buildDOM(): void {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.innerHTML = `
    <div class="section-toolbar" id="section-toolbar">
      <button class="layout-mode-btn" id="layout-mode-toggle" type="button">⇆</button>
      <button class="toolbar-btn" id="doc-roots-toggle" type="button">📂</button>
      <button class="toolbar-btn active" data-section="tts-queue-section" type="button">🔊</button>
      <button class="toolbar-btn active" data-section="time-saved-section" type="button">⏱️</button>
    </div>
    <div id="tts-queue-section">the tts queue</div>
    <div id="time-saved-section">the dashboard</div>
    <div id="somewhere-else">
      <button class="toolbar-btn active" data-section="stray-section" type="button">🙈</button>
    </div>
    <div id="stray-section">not the toolbar's business</div>`;
  document.body.appendChild( host );
}

/** Every section id this fixture owns, in a fixed order. */
const SECTIONS = [ "tts-queue-section", "time-saved-section" ] as const;

/** Which of this fixture's sections are hidden right now. */
function hidden(): string[] {
  return SECTIONS.filter(
    id => document.getElementById( id )!.classList.contains( "section-hidden" ) );
}

/** The saved visibility object, or null when nothing has been written. */
function saved(): Record<string, unknown> | null {
  const raw = localStorage.getItem( VISIBILITY_KEY );
  return raw === null ? null : JSON.parse( raw ) as Record<string, unknown>;
}

/**
 * A bare instance with the toolbar's click handlers REALLY registered.
 *
 * Returns how many buttons the toolbar's own selector bound, so a case can state that the
 * loop found something before it asserts anything about what the loop did.
 */
function mountToolbar(): number {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug                 = false;
  ui.log                   = (): void => {};
  ui.error                 = ( ...parts: unknown[] ): void => { errors.push( parts.join( " " ) ); };
  ui.SECTION_VISIBILITY_KEY = VISIBILITY_KEY;
  ui.sectionVisibility      = null;   // nothing saved yet, so applySectionVisibility returns early
  // Siblings the toggle calls on its way out; each has its own guards and its own tests.
  ui.updateTTSQueueSection   = (): void => {};
  ui.scrollIntoViewIfNeeded  = (): void => {};

  let bound = 0;
  const realAdd = HTMLElement.prototype.addEventListener;
  HTMLElement.prototype.addEventListener = function ( this: HTMLElement, ...args: unknown[] ) {
    if ( ( this as HTMLElement ).closest?.( "#section-toolbar" ) ) bound += 1;
    return ( realAdd as ( ...a: unknown[] ) => void ).apply( this, args );
  } as typeof realAdd;
  try {
    ( ui as unknown as { initToolbar(): void } ).initToolbar();
  } finally {
    HTMLElement.prototype.addEventListener = realAdd;
  }
  return bound;
}

/** Click a button by id and return the errors logged during that click. */
function click( id: string ): string[] {
  const before = errors.length;
  document.getElementById( id )!.dispatchEvent(
    new MouseEvent( "click", { bubbles: true, cancelable: true } ) );
  return errors.slice( before );
}

/** Click the section toggle for `sectionId`, inside the toolbar. */
function clickToggle( sectionId: string ): string[] {
  const before = errors.length;
  document.querySelector<HTMLElement>(
    `#section-toolbar .toolbar-btn[data-section="${sectionId}"]` )!
    .dispatchEvent( new MouseEvent( "click", { bubbles: true, cancelable: true } ) );
  return errors.slice( before );
}


test( "47759aa3 the toolbar binds only its section toggles, and the fixture has non-toggles to skip", () => {
  const bound = mountToolbar();

  assert.equal( bound, SECTIONS.length,
    `the toolbar bound ${bound} buttons; this fixture has exactly ${SECTIONS.length} section ` +
    "toggles, plus a 📂 button and a layout button that must not be bound" );
  // The denominator, stated: if the fixture ever stops carrying a non-toggle, every
  // assertion below would be about a population with nothing to exclude.
  assert.equal( document.querySelectorAll( "#section-toolbar .toolbar-btn" ).length, 3,
    "the fixture must hold three .toolbar-btn elements, one of them without a data-section" );
  assert.equal(
    document.querySelectorAll( "#section-toolbar .toolbar-btn:not([data-section])" ).length, 1,
    "exactly one .toolbar-btn without a data-section — the shape that broke" );
  assert.equal(
    document.querySelectorAll( ".toolbar-btn[data-section]" ).length, SECTIONS.length + 1,
    "one .toolbar-btn[data-section] must sit OUTSIDE the toolbar, or the scoped and " +
    "unscoped selectors are indistinguishable here" );
} );


test( "47759aa3 clicking the 📂 roots button logs no error and moves no section", () => {
  mountToolbar();
  const was = hidden();

  const logged = click( "doc-roots-toggle" );

  assert.deepEqual( logged, [],
    `the 📂 click logged ${logged.length} error(s): ${JSON.stringify( logged )}` );
  assert.deepEqual( hidden(), was, "the 📂 click changed which sections are hidden" );
} );


test( "47759aa3 the positive control: a real section toggle still hides and shows its section", () => {
  mountToolbar();
  assert.deepEqual( hidden(), [], "the fixture must start with nothing hidden" );

  assert.deepEqual( clickToggle( "tts-queue-section" ), [] );
  assert.deepEqual( hidden(), [ "tts-queue-section" ], "the first click did not hide it" );

  assert.deepEqual( clickToggle( "tts-queue-section" ), [] );
  assert.deepEqual( hidden(), [], "the second click did not show it again" );
} );


test( "47759aa3 the saved visibility object carries no undefined key, and names both toggles", () => {
  mountToolbar();
  click( "doc-roots-toggle" );          // the click that used to pollute the save
  clickToggle( "time-saved-section" );  // a real toggle, so a save definitely happens

  const state = saved();
  assert.ok( state !== null, `nothing was saved under ${ VISIBILITY_KEY }` );
  assert.deepEqual( Object.keys( state! ).sort(), [ ...SECTIONS ].sort(),
    "the saved object's keys must be exactly this fixture's section ids — an 'undefined' " +
    `key means the unfiltered selector is still there: ${JSON.stringify( state )}` );
  assert.equal( "undefined" in state!, false, "the literal 'undefined' key was saved" );
} );


test( "47759aa3 the layout-mode button is bound by nothing here either", () => {
  mountToolbar();
  const was = hidden();

  const logged = click( "layout-mode-toggle" );

  assert.deepEqual( logged, [], `the layout button logged: ${JSON.stringify( logged )}` );
  assert.deepEqual( hidden(), was, "the layout button changed a section's visibility" );
} );


// ---------------------------------------------------------------------------
// The browsers that already clicked 📂 (Mr. Radio, 2026-09-27)
// ---------------------------------------------------------------------------
//
// The fix stops the key being WRITTEN. It does not reach the localStorage of anyone who
// clicked 📂 before it shipped, and that saved object outlives the deploy. These two cases
// are about the state already on disk, so they set `sectionVisibility` and enter at
// `applySectionVisibility` — the layer that reads it. Entering at `initToolbar`
// instead would exercise the early return, because a fresh fixture has nothing saved.

/** A save as an affected browser holds it: real entries plus the polluted key. */
const POLLUTED = { "tts-queue-section": false, "time-saved-section": true, "undefined": false };

test( "47759aa3 an existing save carrying an 'undefined' key restores without error", () => {
  mountToolbar();
  ui.sectionVisibility = { ...POLLUTED };
  assert.ok( "undefined" in ( ui.sectionVisibility as object ),
    "the fixture must actually carry the polluted key, or this case proves nothing" );

  ( ui as unknown as { applySectionVisibility(): void } ).applySectionVisibility();

  assert.deepEqual( errors, [], `restore logged: ${JSON.stringify( errors )}` );
  // The real entry is still honoured — the polluted key is ignored, not fatal, and not
  // an excuse to skip the rest of the object.
  assert.deepEqual( hidden(), [ "tts-queue-section" ],
    "the false entry beside the polluted key was not applied" );
} );


test( "47759aa3 the next save drops the 'undefined' key without any migration code", () => {
  mountToolbar();
  ui.sectionVisibility = { ...POLLUTED };
  localStorage.setItem( VISIBILITY_KEY, JSON.stringify( POLLUTED ) );
  assert.equal( "undefined" in saved()!, true, "the polluted key must be on disk to start" );

  clickToggle( "time-saved-section" );   // any real toggle rewrites the whole object

  const state = saved()!;
  assert.equal( "undefined" in state, false,
    `the rewritten save still carries the polluted key: ${JSON.stringify( state )}` );
  assert.deepEqual( Object.keys( state ).sort(), [ ...SECTIONS ].sort() );
} );
