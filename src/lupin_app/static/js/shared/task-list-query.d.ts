// Type declaration for the shared task-list query constant.
//
// The implementation is plain JS (not TS) because it must ALSO load as a
// browser module on the classic-script notifications page, which has no build
// step. This declaration lets the TypeScript multiplexer bundle import the same
// file rather than keeping a second copy of the string.
export declare const TASK_LIST_QUERY: string;

// The classic-script bridge. notifications.js is not a module and cannot
// `import`, so the implementation publishes the constant on `window`; this
// declares that assignment so the .js typechecks under checkJs instead of
// erroring with "Property 'LUPIN_TASK_LIST_QUERY' does not exist on type
// 'Window'". Optional (`?=`) on purpose: the property genuinely may be absent —
// that is precisely the case notifications.js guards for and renders as the
// `query_unavailable` deploy-defect state.
declare global {
    interface Window {
        LUPIN_TASK_LIST_QUERY?: string;
    }
}
