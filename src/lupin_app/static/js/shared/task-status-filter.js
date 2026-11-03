/* c8 ignore next */ // tsx phantom-branch artifact on the file-header line, same as AudioTransport.ts.
/**
 * The status filter for the live task list: one table, one place to change it.
 *
 * The list bar has an All button, selected by default, and four additive chips: Parked,
 * Blocked, In progress and Queued. Selected chips show the union of their statuses.
 * All four selected is the same view as All, and clearing the last chip returns to All.
 *
 * The table below is the whole policy. Nothing else in the page or the tests names a status.
 *
 * Provisional, until Rick rules: claimed and review are open statuses that All shows and
 * that no chip named. They are mapped to In progress, which is Mr. Radio's recommendation.
 * Rick's answer is a one-line change to the statuses of the chip concerned.
 * Held not_approved rows are not in the table, because the board query never returns them.
 */

export const TASK_STATUS_CHIPS = [
    { key: "parked",      label: "Parked",      statuses: [ "parked" ] },
    { key: "blocked",     label: "Blocked",     statuses: [ "blocked" ] },
    { key: "in_progress", label: "In progress", statuses: [ "in_progress", "claimed", "review" ] },   // claimed and review are provisional
    { key: "queued",      label: "Queued",      statuses: [ "queued" ] },
];

const CHIP_KEYS = TASK_STATUS_CHIPS.map( ( chip ) => chip.key );

/**
 * The chips that are really filtering, as a list of keys in table order.
 *
 * @param {string[]} selected
 * @returns {string[]}
 *
 * Requires:
 *     - selected is an array of chip keys; unknown keys are ignored
 * Ensures:
 *     - an empty list means All: nothing selected, or every chip selected
 */
export function activeChips( selected ) {
    const chosen = CHIP_KEYS.filter( ( key ) => selected.includes( key ) );
    return chosen.length === CHIP_KEYS.length ? [] : chosen;
}

/**
 * The selection after a click on one chip.
 *
 * @param {string[]} selected
 * @param {string} key
 * @returns {string[]}
 *
 * Ensures:
 *     - a new array; the input is not changed
 *     - clicking a selected chip removes it, an unselected one adds it
 *     - selecting the last unselected chip collapses to [] (All)
 *     - clearing the last chip gives [] (All), never an empty view
 *     - an unknown key leaves the selection as it was
 */
export function toggleChip( selected, key ) {
    if ( !CHIP_KEYS.includes( key ) ) return activeChips( selected );
    const current = activeChips( selected );
    const next    = current.includes( key ) ? current.filter( ( k ) => k !== key ) : [ ...current, key ];
    return activeChips( next );
}

/**
 * The rows the selection shows.
 *
 * Ensures:
 *     - All (no active chips) returns every row, in order
 *     - otherwise only rows whose status belongs to a selected chip, in order
 *
 * @template {{ status?: string | null }} T
 * @param {T[]} tasks
 * @param {string[]} selected
 * @returns {T[]}
 */
export function filterTasksByChips( tasks, selected ) {
    const active = activeChips( selected );
    if ( active.length === 0 ) return tasks;
    /** @type {Set<string | null | undefined>} */
    const wanted = new Set( TASK_STATUS_CHIPS.filter( ( chip ) => active.includes( chip.key ) ).flatMap( ( chip ) => chip.statuses ) );
    return tasks.filter( ( task ) => wanted.has( ( task || {} ).status ) );
}

/**
 * Puts the surface on a window object for the classic-script page.
 *
 * @param {any} win
 *
 * Requires:
 *     - win is an object (a window, or a stand-in in a test)
 * Ensures:
 *     - win.LUPIN_TASK_STATUS_FILTER carries the table and the three functions
 */
export function publishOnWindow( win ) {
    win.LUPIN_TASK_STATUS_FILTER = { TASK_STATUS_CHIPS, activeChips, toggleChip, filterTasksByChips };
}

// The classic-script bridge: notifications.js reads the global when it is called.
// The declaration is in window-globals.d.ts.
// globalThis is the window in a browser, so publishing needs no environment check.
/* c8 ignore next */ // tsx adds an empty never-run range at the file tail; the publish line itself is run and asserted.
publishOnWindow( globalThis );
