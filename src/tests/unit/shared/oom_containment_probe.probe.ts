// CONTAINMENT PROBE — deliberately reproduces the 2026-08-23 allocator.
// NOT a test. The `.probe.ts` suffix keeps it out of the `*.test.ts` glob.
// Run ONLY through the capped lane; it is designed to die.
import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { test } from "node:test";
import assert from "node:assert";

GlobalRegistrator.register();

test( "a FAILING assertion holding a DOM node — the conjunction that kills", () => {
    const el = document.createElement( "div" );
    el.textContent = "probe";
    // node:assert builds its failure diff by deep-inspecting `actual`; on a
    // happy-dom element that walk goes element -> ownerDocument -> defaultView
    // -> the whole Window graph and never terminates.
    assert.deepStrictEqual( el, { notADomNode: true } );
} );
