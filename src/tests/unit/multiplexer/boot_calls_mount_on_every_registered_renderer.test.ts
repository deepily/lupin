// Row 5918ec60 — the guard for WIRED-TO-NOTHING.
//
// 🔴 A RENDERER CAN BE COMPLETE, CORRECT, 100% COVERED AND NEVER MOUNTED. Measured
// 2026-09-26 (Krishna, row 8033756c): with ListenerErrorRenderer's mount deleted from
// boot.ts the suite went 33/33 green. The id sweeps in
// boot_mounts_every_pane_the_page_declares ask whether boot's ids exist in the page and
// whether the page's panes are looked up — neither asks whether boot CALLS `.mount()`.
//
// THE POPULATION is the real registry: every `create*` factory exported from
// render/index.ts. Nothing here is hand-listed. Each factory's module is read to learn
// whether it has a `mount` at all (a factory with none is declared, not assumed), and
// boot.ts is read for the binding and the call.
//
// ⚠️ CEILING — SOURCE TEXT, NOT A RUN. `bootMultiplexer` is unexported and starts the
// real transports, so this tree has no test that drives it (see
// boot_wires_requests_into_both_boards). This guard therefore proves a `.mount(` call
// with the right receiver EXISTS in boot.ts outside comments. It cannot prove the line
// is reached: a mount left in dead code or after an early return still passes.
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_calls_mount_on_every_registered_renderer.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Resolved from THIS file, never from LUPIN_ROOT.
const MUX = resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../lupin_app/static/js/multiplexer" );

/**
 * Drops `/* … *\/` blocks (single- or multi-line) first, then whole-line `//` comments.
 * ⚠️ A `//` TRAILING code on the same line is kept on purpose: cutting at `//` would also cut
 * every `"http://…"` string. A mount hidden after a trailing `//` therefore still counts —
 * a named ceiling, the same family as the dead-code one above.
 */
export const stripComments = ( src: string ): string =>
  src.replace( /\/\*[\s\S]*?\*\//g, "" )
     .split( "\n" ).filter( ( line ) => !line.trimStart().startsWith( "//" ) ).join( "\n" );

const BOOT_CODE = stripComments( readFileSync( resolve( MUX, "boot.ts" ), "utf8" ) );

interface Registered { factory: string; module: string }

/** Every `create*` factory the barrel exports, with the module it comes from. */
function registry( indexSource: string ): Registered[] {
  const out: Registered[] = [];
  for ( const block of indexSource.matchAll( /export \{([^}]*)\} from "\.\/([^"]+)"/g ) ) {
    for ( const name of block[ 1 ]!.matchAll( /\b(create\w+)\b/g ) ) {
      out.push( { factory: name[ 1 ]!, module: block[ 2 ]! } );
    }
  }
  return out;
}

/** Factories whose module declares no `mount`: nothing to call, so nothing is owed. */
function hasMount( module: string ): boolean {
  return /\bmount\s*\(/.test( readFileSync( resolve( MUX, "render", `${ module }.ts` ), "utf8" ) );
}

/**
 * Factories whose instance boot hands to ANOTHER renderer that does the mounting.
 * Declared, and each entry is itself checked below against both files — an exemption
 * that nothing verifies is an enumeration in hiding.
 */
const MOUNTED_BY_PARENT: Record<string, { parentModule: string; option: string; parentCall: string }> = {
  createBroadcastAckTallyRenderer : { parentModule: "BroadcastCardRenderer", option: "ackTally", parentCall: "this.ackTally.mount(" },
};

/**
 * The mount a boot-level factory call is owed, as a checker result.
 * "bound" = `x = factory(` then `x.mount(`; "inline" = `factory(...).mount(`.
 */
export function mountEvidence( factory: string, bootCode: string ): { kind: "bound" | "inline" | "none"; receiver?: string } {
  const bound = new RegExp( `(?:const\\s+|^\\s*)(\\w+)\\s*=\\s*${ factory }\\(`, "m" ).exec( bootCode );
  if ( bound !== null ) {
    const receiver = bound[ 1 ]!;
    return new RegExp( `\\b${ receiver }\\.mount\\(` ).test( bootCode ) ? { kind: "bound", receiver } : { kind: "none", receiver };
  }
  return new RegExp( `${ factory }\\([^;]*?\\)\\.mount\\(`, "s" ).test( bootCode ) ? { kind: "inline" } : { kind: "none" };
}

const REGISTERED = registry( readFileSync( resolve( MUX, "render/index.ts" ), "utf8" ) );

test( "the registry sweep reaches a real population, and every factory is built by boot", () => {
  console.log( `[boot-mount guard] denominator: ${ REGISTERED.length } create* factories exported from render/index.ts` );
  assert.ok( REGISTERED.length >= 30, `registry sweep found ${ REGISTERED.length } factories, below the floor of 30 (31 when re-derived 2026-09-29) — the barrel regex stopped matching, or exports were removed` );
  assert.equal( new Set( REGISTERED.map( ( r ) => r.factory ) ).size, REGISTERED.length, "duplicate factory export" );
  for ( const { factory } of REGISTERED ) {
    assert.ok( BOOT_CODE.includes( `${ factory }(` ), `${ factory } is exported but boot.ts never builds it` );
  }
  // Positive control on the instrument: it must see a mount where one plainly exists,
  // and must NOT see one in text that has none.
  assert.equal( mountEvidence( "createNavBarRenderer", BOOT_CODE ).kind, "bound" );
  assert.equal( mountEvidence( "createTimeSavedRenderer", BOOT_CODE ).kind, "inline" );
  assert.equal( mountEvidence( "createNavBarRenderer", BOOT_CODE.replace( /navBarRenderer\.mount\(/g, "navBarRenderer.nothing(" ) ).kind, "none" );
});

test( "a commented-out mount reads as missing, whichever comment form hides it", () => {
  const live = "  const x = createNavBarRenderer({});\n  navBarRenderer.mount( el );\n";
  const src  = "const navBarRenderer = createNavBarRenderer({});\n";
  const variants: Record<string, string> = {
    "whole-line //"     : src + "// navBarRenderer.mount( el );\n",
    "single-line /* */" : src + "/* navBarRenderer.mount( el ); */\n",
    "multi-line /* */"  : src + "/*\n  navBarRenderer.mount( el );\n*/\n",
  };
  // Positive control: the same shape with the mount LIVE is seen, so the three "none"s below
  // are the comment stripping at work and not a receiver the regex could never find.
  assert.equal( mountEvidence( "createNavBarRenderer", stripComments( src + "navBarRenderer.mount( el );\n" ) ).kind, "bound", live );
  for ( const [ form, text ] of Object.entries( variants ) ) {
    assert.equal( mountEvidence( "createNavBarRenderer", stripComments( text ) ).kind, "none", `${ form } mount was counted as a call` );
  }
});

test( "a // in the middle of a line is kept: a string holding a URL is not cut, and a mount on that line still counts", () => {
  const urlLine = 'const base = "http://localhost:7999"; navBarRenderer.mount( el );';
  assert.equal( stripComments( urlLine ), urlLine );
  const text = `const navBarRenderer = createNavBarRenderer({});\n${ urlLine }\n`;
  assert.equal( mountEvidence( "createNavBarRenderer", stripComments( text ) ).kind, "bound" );
  // ...whereas the same line as a WHOLE-line comment is dropped, so the control discriminates.
  assert.equal( stripComments( "// " + urlLine ), "" );
});

for ( const { factory, module } of REGISTERED ) {
  test( `boot calls mount() on ${ factory }`, () => {
    if ( !hasMount( module ) ) return; // declared by its own source: no mount() exists to call
    const parent = MOUNTED_BY_PARENT[ factory ];
    if ( parent !== undefined ) {
      const bound = mountEvidence( factory, BOOT_CODE );
      assert.equal( bound.kind, "none", `${ factory } is declared mounted-by-parent but boot also mounts it` );
      assert.match( BOOT_CODE, new RegExp( `${ parent.option }\\s*:\\s*${ bound.receiver }\\b` ), `boot no longer hands ${ factory } to its parent as ${ parent.option }` );
      const parentSrc = readFileSync( resolve( MUX, "render", `${ parent.parentModule }.ts` ), "utf8" );
      assert.ok( parentSrc.includes( parent.parentCall ), `${ parent.parentModule } no longer calls ${ parent.parentCall }` );
      return;
    }
    const evidence = mountEvidence( factory, BOOT_CODE );
    assert.notEqual( evidence.kind, "none", `${ factory }: boot.ts builds it${ evidence.receiver ? ` as ${ evidence.receiver }` : "" } but never calls .mount() on it` );
  } );
}

test( "the exemptions are a strict subset of the registry and each is still needed", () => {
  const names = new Set( REGISTERED.map( ( r ) => r.factory ) );
  for ( const key of Object.keys( MOUNTED_BY_PARENT ) ) assert.ok( names.has( key ), `${ key } exempted but not in the registry` );
  // Sanity on the mount-less set: must be non-empty only if it is real — today exactly one.
  const mountless = REGISTERED.filter( ( r ) => !hasMount( r.module ) ).map( ( r ) => r.factory );
  assert.deepEqual( mountless, [ "createFilterSettingsReveal" ] );
});
