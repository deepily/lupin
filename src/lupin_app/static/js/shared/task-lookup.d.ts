// Type declaration for the shared ticket-lookup module.
//
// The implementation is plain JS (not TS) because it must ALSO load as a browser
// module on the classic-script notifications page, which has no build step. This
// declaration lets the TypeScript multiplexer bundle import the same file rather
// than keeping a second copy of the classifier — the drift `taskVerbs.ts` is the
// standing receipt for.

export declare const MIN_TASK_REF_PREFIX_LEN: number;

export declare const TASK_REF_FULL: "full";
export declare const TASK_REF_PREFIX: "prefix";
export declare const TASK_REF_INVALID: "invalid";

// What `classifyTaskRef` answers.
//
// 🔴 A DISCRIMINATED UNION, NOT `{ kind, value: string | null }`. "`value` is
// null exactly when `kind` is invalid" is an invariant, and writing it as a
// comment over a widened type leaves every caller to remember a null check. As
// a union the checker narrows `value` to `string` the moment the invalid arm is
// ruled out — so the invariant is enforced rather than described.
export type TaskRefClassification =
    | { kind: "full" | "prefix"; value: string }
    | { kind: "invalid";         value: null };

export declare function classifyTaskRef( ref: unknown ): TaskRefClassification;

/** `"/api/tasks/<normalized>"`, or null when the ref will not classify. */
export declare function taskLookupPath( ref: unknown ): string | null;

export declare function taskRefRefusalMessage(): string;

/** The one wording both clients use for a 401. See the .js for why it is shared. */
export declare const TASK_LOOKUP_AUTH_REQUIRED_MESSAGE: string;

/** The one wording both clients use when the store did not answer. */
export declare const TASK_LOOKUP_UNREACHABLE_MESSAGE: string;

// The classic-script bridge. notifications.js is not a module and cannot
// `import`, so the implementation publishes these on `window`; this declares the
// assignments so the .js typechecks under checkJs instead of erroring with
// "Property 'LUPIN_TASK_LOOKUP_PATH' does not exist on type 'Window'".
//
// Optional (`?`) on purpose, and it is NOT defensive habit: the property
// genuinely may be absent, because the classic page loads this file with a
// separate <script> tag that can fail independently of the page. That is the
// case notifications.js renders as its own deploy-defect state rather than
// throwing on a missing global — the same shape `LUPIN_TASK_LIST_QUERY` already
// uses one file over.
declare global {
    interface Window {
        LUPIN_CLASSIFY_TASK_REF?        : ( ref: unknown ) => TaskRefClassification;
        LUPIN_TASK_LOOKUP_PATH?         : ( ref: unknown ) => string | null;
        LUPIN_TASK_REF_REFUSAL_MESSAGE? : () => string;
        LUPIN_MIN_TASK_REF_PREFIX_LEN?  : number;
        LUPIN_TASK_LOOKUP_AUTH_REQUIRED_MESSAGE? : string;
        LUPIN_TASK_LOOKUP_UNREACHABLE_MESSAGE?   : string;
    }
}
