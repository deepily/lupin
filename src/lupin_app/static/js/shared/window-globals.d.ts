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

// ⚠️ task-verbs.js publishes TWO NAMED EXPORTS rather than a whole surface, so it is
// derived per-property instead of by `Omit`. It gets NO sibling `task-verbs.d.ts` for the
// reason given above: a sibling declaration wins module resolution, and the TS side reads
// that module's real source under `checkJs` today. Optional (`?`) like its neighbours —
// the publication is guarded by `typeof window !== "undefined"`, so on a non-browser
// import the properties genuinely are absent.
interface Window {
    LUPIN_AGENT_SELECT?: Omit< typeof import( "./agent-select.js" ), "publishOnWindow" >;
    LUPIN_ARG_INTERVIEW?: Omit< typeof import( "./arg-interview.js" ), "publishOnWindow" >;
    LUPIN_TASK_VERB_SPECS?: typeof import( "./task-verbs.js" ).TASK_VERB_SPECS;
    LUPIN_TASK_VERBS?: typeof import( "./task-verbs.js" ).TASK_VERBS;
}
