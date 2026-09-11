/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Row 83c3ff74 — the jobs pane's Mine / Not Mine / All Users rules (Rick, 2026-09-10 ~17:40 EDT).
//
// ONE mode, shared with the notifications pane: it lives in NotificationStore under legacy's
// raw key. These two functions turn that mode plus the signed-in identity into (1) the
// /api/job-history filter and (2) whether a live job is shown. Both are ports of legacy
// notifications.js:
//   - updateQueueLists (:6245-6262): own → no param, others → '!self', all → '*'.
//     /api/job-history differs from /api/get-queue in one place — with no param it gives an
//     ADMIN every user's jobs (queues.py get_job_history) — so an admin's "Mine" names the
//     admin's own uid, which the server's authorizer allows anyone to ask for.
//   - handleJobStateTransition (:5274-5283): compare metadata.user_email with the signed-in
//     email; an event with no email is not filtered.

import type { Job, NotificationFilterMode } from "../shared/types";

export interface JobViewer {
  isAdmin   : boolean;
  // The shared mode. Callers pass "own" for a non-admin, whatever is stored: legacy's switch is
  // admin-only, and a Not Mine left in the shared key must not narrow a regular user's view.
  mode      : NotificationFilterMode;
  userId    : string | null;
  userEmail : string | null;
}

/**
 * The `user_filter` to send with a job-history REPLACE.
 *
 * Requires:
 *   - viewer.mode is the shared mode (already "own" for a non-admin)
 * Ensures:
 *   - undefined for a non-admin (no param — the server scopes them to their own jobs)
 *   - "*" for an admin in all, "!self" for an admin in others
 *   - the admin's uid for an admin in own
 * Raises:
 *   - Error naming the missing user id when an admin in own has none. Sending no param instead
 *     would show that admin EVERY user's jobs under a badge reading "Mine".
 */
export function jobHistoryUserFilter(viewer: JobViewer): string | undefined {
  if (!viewer.isAdmin) return undefined;
  if (viewer.mode === "all") return "*";
  if (viewer.mode === "others") return "!self";
  if (viewer.userId === null) {
    throw new Error("cannot show only your jobs: your user id is missing from the sign-in token");
  }
  return viewer.userId;
}

/**
 * Whether a job in a bucket is shown in the current mode.
 *
 * Ensures:
 *   - a job whose meta carries no non-empty string user_email is shown in every mode
 *   - own: shown iff user_email equals the signed-in email
 *   - others: shown iff user_email differs from the signed-in email
 *   - all: shown
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function isJobVisibleTo(viewer: JobViewer, job: Job): boolean {
  const email = job.meta["user_email"];
  if (typeof email !== "string" || email === "") return true;
  if (viewer.mode === "own") return email === viewer.userEmail;
  if (viewer.mode === "others") return email !== viewer.userEmail;
  return true;
}
