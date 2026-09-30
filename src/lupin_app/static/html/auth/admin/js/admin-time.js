// ============================================================================
// admin-time.js — the ONE relative-time formatter the admin pages share.
//
// WHY THIS FILE EXISTS. Until 2026-09-15 proxy-dashboard.js:429-448 and
// proxy-ratify.js:744-763 each carried their own copy of formatRelativeTime,
// byte-identical (both ranges sha256 c212e07bca45935e935ffb5609166a49435bfef4
// edc2610e6f88d2b95c916e4c). Two copies of one rule agree until they do not,
// and nothing would have reported the day they stopped: each page renders its
// own table, so a divergence shows up as two admin screens disagreeing about
// what "2h ago" means, with no test in a position to see it.
//
// Consolidating rather than guarding both was a deliberate choice. A guard on
// two copies can only report divergence AFTER someone ships it; one owned copy
// makes the divergence unrepresentable. Neither page has ever wanted a
// different clock.
//
// LOADING. These are classic scripts, not modules — the admin pages load them
// with a plain <script src>, no type="module", no bundler. So this file must be
// listed BEFORE the page script that calls it, and the function is reachable as
// a global. test_admin_time_module.py asserts both halves: exactly one served
// definition, and every page whose script CALLS it also LOADS this file. That
// second assertion is the one that matters — the failure mode of this
// consolidation is deleting a copy and forgetting the script tag, which is a
// runtime ReferenceError that no amount of reading the JS would reveal.
// ============================================================================

/**
 * Format an ISO timestamp as a relative time ("5m ago", "2h ago").
 *
 * Requires:
 *     - isoString is an ISO-8601 string, or null/undefined/empty
 *
 * Ensures:
 *     - returns "—" for a falsy input
 *     - returns "just now" for a future timestamp or one under 60 seconds old
 *     - returns "Nm ago" under an hour, "Nh ago" under a day, "Nd ago" under a week
 *     - returns a locale date string at seven days and older
 *
 * NOTE for anyone writing a visual snapshot: every branch above except the last
 * returns a value that CHANGES BETWEEN RUNS. The last one does not, which is why
 * a page whose data happens to be older than a week looks stable and is not —
 * it starts drifting the moment the data is fresh. Both admin tables are
 * normalized before capture in src/tests/e2e_ui/test_visual_regression.py.
 */
function formatRelativeTime( isoString ) {
    if ( !isoString ) return "—";

    const date   = new Date( isoString );
    const now    = new Date();
    const diffMs = now - date;

    if ( diffMs < 0 ) return "just now";

    const diffSec  = Math.floor( diffMs / 1000 );
    const diffMin  = Math.floor( diffMs / 60000 );
    const diffHr   = Math.floor( diffMs / 3600000 );
    const diffDays = Math.floor( diffMs / 86400000 );

    if ( diffSec < 60 )  return "just now";
    if ( diffMin < 60 )  return diffMin + "m ago";
    if ( diffHr  < 24 )  return diffHr + "h ago";
    if ( diffDays < 7 )  return diffDays + "d ago";

    return date.toLocaleDateString();
}
