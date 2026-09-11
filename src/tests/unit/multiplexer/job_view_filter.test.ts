// Row 83c3ff74 — the jobs pane's Mine / Not Mine / All Users rules, as pure functions.
// Run via `npx tsx --test src/tests/unit/multiplexer/job_view_filter.test.ts`.
//
// Two rules, both ported from legacy notifications.js:
//   1. WHICH HISTORY TO ASK FOR — updateQueueLists (:6245-6262) sends no param for own, '!self'
//      for others, '*' for all. /api/job-history differs in ONE place: with no param it gives an
//      admin EVERY user's jobs, so an admin's "Mine" must name the admin's own uid instead.
//   2. WHICH LIVE JOB TO SHOW — handleJobStateTransition (:5274-5283) compares the event's
//      metadata.user_email with the signed-in email, and lets an event with no email through.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  isJobVisibleTo,
  jobHistoryUserFilter,
  type JobViewer,
} from "../../../lupin_app/static/js/multiplexer/stores/jobViewFilter";
import type { Job } from "../../../lupin_app/static/js/multiplexer/shared/types";

const RICK = "rick@example.com";

function viewer(overrides: Partial<JobViewer> = {}): JobViewer {
  return { isAdmin: true, mode: "own", userId: "rick_6bdc", userEmail: RICK, ...overrides };
}

function job(meta: Record<string, unknown>): Job {
  return { id_hash: "j1", job_type: "claude_code", status: "running", created_at: 0, meta };
}

// ---------------------------------------------------------------------------
// 1. The history request
// ---------------------------------------------------------------------------

test("an admin's Mine asks for the admin's own uid, never the bare default (which is every user)", () => {
  assert.equal(jobHistoryUserFilter(viewer({ mode: "own" })), "rick_6bdc");
});

test("an admin's Not Mine asks for !self, and All Users asks for *", () => {
  assert.equal(jobHistoryUserFilter(viewer({ mode: "others" })), "!self");
  assert.equal(jobHistoryUserFilter(viewer({ mode: "all" })), "*");
});

test("a non-admin sends no filter in any stored mode — the server already scopes them to their own", () => {
  for (const mode of [ "own", "others", "all" ] as const) {
    assert.equal(jobHistoryUserFilter(viewer({ isAdmin: false, mode, userId: null })), undefined, mode);
  }
});

test("an admin in Mine whose uid cannot be read is REFUSED, not quietly shown every user's jobs", () => {
  assert.throws(
    () => jobHistoryUserFilter(viewer({ mode: "own", userId: null })),
    /user id/,
  );
});

test("an unreadable uid does not block Not Mine or All Users, which do not need it", () => {
  assert.equal(jobHistoryUserFilter(viewer({ mode: "others", userId: null })), "!self");
  assert.equal(jobHistoryUserFilter(viewer({ mode: "all",    userId: null })), "*");
});

// ---------------------------------------------------------------------------
// 2. The live buckets — one fixture per owner, checked in all three modes
// ---------------------------------------------------------------------------

const mine    = job({ user_email: RICK });
const theirs  = job({ user_email: "someone@example.com" });
const noEmail = job({ agent_type: "claude_code" });

test("another user's job is hidden in Mine and shown in Not Mine and All Users", () => {
  assert.equal(isJobVisibleTo(viewer({ mode: "own" }),    theirs), false);
  assert.equal(isJobVisibleTo(viewer({ mode: "others" }), theirs), true);
  assert.equal(isJobVisibleTo(viewer({ mode: "all" }),    theirs), true);
});

test("the admin's own job is shown in Mine and All Users and hidden in Not Mine", () => {
  assert.equal(isJobVisibleTo(viewer({ mode: "own" }),    mine), true);
  assert.equal(isJobVisibleTo(viewer({ mode: "others" }), mine), false);
  assert.equal(isJobVisibleTo(viewer({ mode: "all" }),    mine), true);
});

test("a job with no user_email is shown in every mode, as legacy lets such an event through", () => {
  for (const mode of [ "own", "others", "all" ] as const) {
    assert.equal(isJobVisibleTo(viewer({ mode }), noEmail), true, mode);
    assert.equal(isJobVisibleTo(viewer({ mode }), job({ user_email: "" })), true, `${mode}, empty email`);
    assert.equal(isJobVisibleTo(viewer({ mode }), job({ user_email: 42 })), true, `${mode}, non-string email`);
  }
});

test("with no signed-in email, Mine hides every owned job — legacy's `eventEmail !== currentUserEmail`", () => {
  assert.equal(isJobVisibleTo(viewer({ mode: "own", userEmail: null }), theirs), false);
  assert.equal(isJobVisibleTo(viewer({ mode: "own", userEmail: null }), noEmail), true);
});
