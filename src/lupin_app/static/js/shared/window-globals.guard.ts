// A COMPILE-TIME GUARD OVER `window-globals.d.ts`, IN A FILE THE CHECKER ACTUALLY READS.
//
// 🔴 WHY IT IS A `.ts` AND ITS SUBJECT IS A `.d.ts` — THAT IS THE ENTIRE POINT.
// `tsconfig.json:13` sets `skipLibCheck: true`, so nothing written in a declaration file
// is type-checked. `window-globals.d.ts` records that measurement in full; this file is
// the control it asks for, and it turns that comment into something that can fail.
//
// ⚠️ ONLY THE MUX PROJECT NEEDS IT. `tsconfig.nav.json` and `tsconfig.diagnostic.json` do
// not include `shared/`, so neither one sees the declaration OR this guard — measured with
// `--listFiles`: 1 hit under `tsconfig.json`, 0 under the other two. A guard placed for all
// three would have been two-thirds ceremony.
//
// 🔴 WHAT IS ALREADY CAUGHT WITHOUT THIS FILE, so it does not take credit for it: drift is
// caught in the common case by `task-verbs.js:147-148`, whose publication lines assign to
// these window properties under `checkJs`. Rename an export alone and THAT breaks.
//
// ⇒ THE HOLE IS THE CO-RENAME — export and publication renamed TOGETHER, leaving the
// declaration naming a member that is gone while everything still compiles.
//
// ===========================================================================
// EVERY ASSERTION BELOW WAS WATCHED FAIL — none is here on argument. Five arms at
// `b3d17502`, tree clean and zero markers after each, each aimed at ONE mechanism:
//
//   ARM 1  co-rename `TASK_VERB_SPECS` + its publication
//            guard ABSENT  -> 0 errors      <- the hole, reproduced
//            guard PRESENT -> TS2694 on the `ModuleSpecs` line, plus `declarationsStillDiffer`
//   ARM 2  declare `LUPIN_TASK_VERBS?: string` where the module exports `string[]`
//            -> `verbsMatchesModule` fires. (ALSO caught by task-verbs.js:148 on its own —
//               said out loud, because a guard that only duplicates an existing check is
//               ceremony wearing a receipt. This leg earns its place on ARM 1, not here.)
//   ARM 3  declare from a module that does not exist  -> `declarationsStillDiffer` fires ALONE
//   ARM 4  declare a member that never existed        -> `declarationsStillDiffer` fires ALONE
//   ARM 5  the symmetric case of ARM 2, on the SPECS side
//            -> `specsMatchesModule` fires. Run because symmetry is an argument, not a
//               receipt: without it that one assertion would have been the only line in
//               this file nobody had seen fail.
//
// 🔴 AND TWO ASSERTIONS WERE DELETED FOR FAILING THAT TEST. An earlier cut carried
// `IsAny< … > = false` legs under a confident paragraph calling them essential — "without
// this the guard is blind". They fired in NONE of the four arms: a declaration that stops
// naming something degrades to an ERROR type, not to `any`, so the idiom never triggers.
// They were removed rather than kept as insurance, because an assertion nobody has watched
// fail is a comment with a semicolon.
// ===========================================================================
//
// ⚠️ NOT A `skipLibCheck` CHANGE. Turning it off checks every `.d.ts` in the tree including
// vendored ones — a blast-radius question and somebody's ruling, not a drive-by here.
//
// Emits nothing at runtime and is imported by nobody: esbuild bundles from entry points, so
// an unimported module never reaches a bundle. This file exists to be COMPILED.

/** True only when A and B are mutually assignable — i.e. the same type. */
type Exact< A, B > = [ A ] extends [ B ] ? ( [ B ] extends [ A ] ? true : false ) : false;

// ------------------------------------------- the two sides, named from OPPOSITE places

/**
 * From the MODULE, named in a checked `.ts`.
 *
 * 🔴 THESE TWO LINES ARE THE ONES THAT CLOSE THE HOLE. Naming the export here is what makes
 * a co-rename a compile error, because this file is checked and the declaration file is not.
 * Measured: with the guard absent the co-rename is 0 errors; with it present the error lands
 * on this line as TS2694.
 */
type ModuleSpecs = typeof import( "./task-verbs.js" ).TASK_VERB_SPECS;
type ModuleVerbs = typeof import( "./task-verbs.js" ).TASK_VERBS;

/** From the DECLARATION, which the checker skips. This is the side under suspicion. */
type WindowSpecs = NonNullable< Window[ "LUPIN_TASK_VERB_SPECS" ] >;
type WindowVerbs = NonNullable< Window[ "LUPIN_TASK_VERBS" ] >;

// -------------------------------------------------------------------- the assertions

/** The declaration says exactly what the module exports. Reddens on a type drift (ARM 2). */
export const specsMatchesModule: Exact< WindowSpecs, ModuleSpecs > = true;
export const verbsMatchesModule: Exact< WindowVerbs, ModuleVerbs > = true;

/**
 * The two declared surfaces are still DIFFERENT types — `TASK_VERB_SPECS` is an object and
 * `TASK_VERBS` is a string array.
 *
 * 🔴 IT DOES TWO JOBS AND ONLY ONE OF THEM IS THE OBVIOUS ONE. At baseline it proves `Exact`
 * can still answer `false`, so the four assertions above are not passing because the
 * comparator degenerated into saying `true` to everything. Under a broken declaration it also
 * DETECTS: when one side stops naming something real, the two collapse into mutual
 * assignability and this flips to `true`. It fired on arms 1, 3 and 4.
 *
 * ⚠️ SO DO NOT READ ITS FAILURE AS "THE CONTROL BROKE" — on arms 3 and 4 it was the ONLY
 * thing that fired, and it was right.
 */
export const declarationsStillDiffer: Exact< WindowSpecs, WindowVerbs > = false;

// =========================================================================================
// THE TWO `Omit`-SHAPED GLOBALS — A DIFFERENT SHAPE, AND A DIFFERENT HOLE.
//
// `LUPIN_AGENT_SELECT` and `LUPIN_ARG_INTERVIEW` are declared as
// `Omit< typeof import( … ), "publishOnWindow" >` — a WHOLE MODULE SURFACE minus one key,
// not a named export. Assuming they behave like the pair above is exactly what this guard
// exists to refuse, so the shape was MEASURED before a line was written. Three arms at
// `d56ab9ad`, green baseline first, each restored and sha-verified:
//
//   H1  rename `publishOnWindow` itself (export + call site)
//         -> ALREADY CAUGHT. TS2741 at agent-select.js:320. `Omit< T, K >` takes
//            `K extends keyof any`, so omitting a key that no longer exists is legal and
//            silently a no-op — but the omitted member then becomes REQUIRED, and the
//            object literal `publishOnWindow` writes does not have it.
//         ⚠️ THIS FALSIFIED THE PREDICTION, which said 0 errors. Recorded because the
//            arm is why the leg below was NOT written for this case.
//   H2  add an export the literal does not publish
//         -> ALREADY CAUGHT, same mechanism. TS2741, 'CHEECH_NEW_THING' is missing.
//   H3  co-rename a MEMBER in the module and in the published literal together
//         -> 0 ERRORS. THE HOLE.
//
// 🔴 AND THE HOLE IS END-TO-END, NOT THEORETICAL. The sole consumer of both globals is
// `notifications.js` (`const agentSelect = window.LUPIN_AGENT_SELECT;` then `.isAutoRoute`),
// and it is in NONE of the three projects — measured with `--listFiles`: 0 hits under
// `tsconfig.json`, `tsconfig.nav.json` and `tsconfig.diagnostic.json` alike. So a co-renamed
// member breaks the page at runtime and there is no second line of defence anywhere.
//
// 🔴 THE OBVIOUS ASSERTION IS A TAUTOLOGY AND IS DELIBERATELY ABSENT.
// `Exact< NonNullable< Window[ "LUPIN_AGENT_SELECT" ] >, Omit< typeof import( … ), … > >`
// derives BOTH sides from the same module by the same route, so they move together and it
// can never disagree — an identity wearing an assertion's clothes. What is written instead
// pins one side to a HAND-WRITTEN literal the module cannot move.
//
// ⚠️ AND NO LEG IS WRITTEN FOR H1 OR H2. They are already caught by the publication line,
// and a guard that only duplicates an existing check is ceremony wearing a receipt — the
// same test that deleted the two `IsAny` legs above.
//
// EACH LEG WAS WATCHED FAIL, AND WATCHED STAY SILENT:
//   ARM A  co-rename `isAutoRoute`      -> `agentSelectSurfaceIsExactlyThese`  ONLY
//   ARM B  co-rename `clearArgQuestion` -> `argInterviewSurfaceIsExactlyThese` ONLY
//   ARM C  ARM A's rename with these legs REMOVED -> 0 errors, the hole reproduced
// The silence is half the proof: a leg that reddened on both renames would be measuring
// nothing about which module drifted.
// =========================================================================================

/** The published surface, written BY HAND. A rename must change this line or go red. */
type AgentSelectMembers  = "AGENTS_ENDPOINT" | "buildAgentSelectOptions" | "renderAgentSelect"
                         | "isAutoRoute" | "argsForCommand";
type ArgInterviewMembers = "isAnswerable" | "resumeBody" | "renderArgQuestion" | "clearArgQuestion";

/** From the DECLARATION — the side under suspicion, reached through the `Omit`. */
type WindowAgentSelect  = NonNullable< Window[ "LUPIN_AGENT_SELECT"  ] >;
type WindowArgInterview = NonNullable< Window[ "LUPIN_ARG_INTERVIEW" ] >;

export const agentSelectSurfaceIsExactlyThese:  Exact< keyof WindowAgentSelect,  AgentSelectMembers  > = true;
export const argInterviewSurfaceIsExactlyThese: Exact< keyof WindowArgInterview, ArgInterviewMembers > = true;
