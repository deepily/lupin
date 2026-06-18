// Lupin nav-bar composition root (boot.ts) — coverage test.
//
// Importing boot.ts runs its single side-effecting statement against the real
// global document/window/localStorage. Isolated in its own file because that
// import mounts the nav once into the shared global document.
//
// Run via: npx tsx --test src/tests/unit/nav/lupin_nav_boot.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

before(() => {
    if ( typeof globalThis.document === "undefined" ) {
        GlobalRegistrator.register();
    }
});

test( "boot mounts #lupin-nav against the real document", async () => {
    document.body.replaceChildren();

    // Import executes `scheduleMount( document, () => mountNav(...) )`. Drive the
    // arrow regardless of happy-dom's reported readyState: if the document was
    // already ready the mount ran synchronously on import; otherwise dispatch
    // DOMContentLoaded to fire the deferred listener.
    await import( "../../../lupin_app/static/js/nav/boot" );

    if ( document.getElementById( "lupin-nav" ) === null ) {
        document.dispatchEvent( new Event( "DOMContentLoaded" ) );
    }

    assert.ok( document.getElementById( "lupin-nav" ), "boot should inject #lupin-nav" );
} );
