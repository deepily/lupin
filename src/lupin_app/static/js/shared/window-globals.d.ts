// The `window` properties the shared modules publish for the classic-script page.
//
// WHY THIS FILE EXISTS. notifications.js is a classic script and cannot `import`, so
// each shared module publishes its surface on `window` — that global IS the seam. Under
// `checkJs` those assignments fail with "Property 'LUPIN_AGENT_SELECT' does not exist on
// type 'Window'" unless the property is declared, which is the same reason
// task-list-query.d.ts carries its own `declare global` block.
//
// It is a SEPARATE file rather than a sibling `agent-select.d.ts` on purpose: a sibling
// declaration wins module resolution, so a `.d.ts` next to a `.js` must describe that
// module's whole export surface or every importer sees an empty module. This file
// declares only the globals and leaves both modules to be read from their own source.
//
// Each surface is derived from the module rather than re-typed by hand — `Omit<…,
// "publishOnWindow">` is exactly what each publishOnWindow writes, so the declaration
// cannot drift from the assignment it describes.

interface Window {
    LUPIN_AGENT_SELECT?: Omit< typeof import( "./agent-select.js" ), "publishOnWindow" >;
    LUPIN_ARG_INTERVIEW?: Omit< typeof import( "./arg-interview.js" ), "publishOnWindow" >;

    // task-verbs.js publishes INLINE rather than through a `publishOnWindow`, so
    // there is no function to `Omit` — the two exports are indexed directly. Same
    // rule though, and it is this file's own: the type is DERIVED from the module,
    // never re-typed here. Writing `unknown` (or a hand-copied shape) would make
    // this declaration a second, silently-drifting statement of what task-verbs.js
    // exports, which is the defect the header above exists to refuse.
    LUPIN_TASK_VERB_SPECS?: typeof import( "./task-verbs.js" )[ "TASK_VERB_SPECS" ];
    LUPIN_TASK_VERBS?     : typeof import( "./task-verbs.js" )[ "TASK_VERBS" ];
}
