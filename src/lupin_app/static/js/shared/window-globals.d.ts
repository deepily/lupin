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
// Each surface is DERIVED from the module rather than re-typed by hand — `Omit<…,
// "publishOnWindow">` is exactly what each publishOnWindow writes — so the declaration is
// WRITTEN TO TRACK the assignment it describes.
//
// 🔴 IT IS NOT ENFORCED, AND THIS SENTENCE USED TO SAY IT WAS. It read "so the
// declaration CANNOT drift from the assignment it describes", which is false for every
// property in this file. `skipLibCheck: true` (tsconfig.json:13) skips .d.ts files
// wholesale, so NOTHING written here is type-checked at all.
//
// Measured 2026-09-08 at dad08900, three arms, tree clean and zero markers after each:
//
//   rename the export only                   -> TS2304 at task-verbs.js:148
//   rename the export AND its publication    -> 0 errors, this file still naming it
//   declare a member that NEVER existed      -> 0 errors
//
// The rival explanation was ruled out rather than dismissed: the never-existed probe
// against a .TS module (`./ownLookup`) also compiled clean, so this is not a JS-versus-TS
// effect. Flip the one variable, `--skipLibCheck false`, and it fires by name:
//   window-globals.d.ts(29,68): error TS2694: Namespace 'task-verbs' has no exported
//   member 'TOTALLY_MADE_UP'.
//
// ⇒ WHAT ACTUALLY CATCHES DRIFT IS THE MODULE'S OWN PUBLICATION LINE under `checkJs` —
// task-verbs.js:147-148 assign to `window.LUPIN_TASK_VERB_SPECS` / `window.LUPIN_TASK_VERBS`,
// and renaming an export breaks THAT. So drift is caught in the common case, by a
// different file than the one you are reading. It goes UNDETECTED when an export and its
// publication are renamed together: this file then declares a member that is gone, and
// nothing complains.
//
// ⇒ Keep the derived FORM — it is still the right way to write these, and it is what makes
// the declaration correct on the day someone does check it. Do not read it as a guarantee.

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
    // Row c9fafb9d: the promote/demote request chip and verdict body, for the legacy page.
    LUPIN_TASK_REQUEST?: Pick< typeof import( "./task-request.js" ),
        "REQUEST_BADGES_PATH" | "BADGE_HOLDING_AREA" | "BADGE_TASK_AREA" | "VERDICT_APPROVED" |
        "VERDICT_DENIED" | "TRIAGE_DATE_LABEL" | "requestVerdictPath" | "requestAge" |
        "pendingRequestChip" | "requestVerdictBody" | "requestBadgeText" >;
}
