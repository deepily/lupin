// Tests for the job switch text rules (rows 063fc1a8, c38a49bd, c80ef763).
//
// They were the text rules of the Scheduled Jobs pane; the pane is gone and the jobs list draws the switch
// on a job's second line. The pure functions are tested here; the drawing and the flip are tested through
// the list in background_jobs_pane.test.ts.

import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import {
  CRON_JOBS_PATH, CRON_NOT_REPORTED, cronChangedText, cronFlipFailureText, cronFlipPath, cronInsideText, cronReadsText, cronStateText, refusalDetail,
} from "../../../lupin_app/static/js/multiplexer/jobs/cronFormat";
import type { CronJobRow } from "../../../lupin_app/static/js/multiplexer/jobs/cronFormat";

function row( job: string, over: Partial<CronJobRow> = {} ): CronJobRow {
  return {
    job, title : `Title of ${ job }`, schedule : "*/5 * * * *", key : `key-of-${ job }`,
    enabled : true, honoured : true, drift : false, last_changed_by : null, last_changed_at : null, ...over,
  };
}

test( "the text rules: state words, the changed line, the flip path", () => {
  assert.equal( cronStateText( true ), "ON" );
  assert.equal( cronStateText( false ), "OFF" );
  assert.equal( cronStateText( null ), "UNKNOWN" );
  assert.equal( cronChangedText( row( "a" ) ), CRON_NOT_REPORTED );
  assert.equal( cronChangedText( row( "a", { last_changed_by : "x", last_changed_at : null } ) ), CRON_NOT_REPORTED );
  assert.equal( cronChangedText( row( "a", { last_changed_by : null, last_changed_at : "2026-11-13T21:05:44-05:00" } ) ), CRON_NOT_REPORTED );
  assert.equal( cronChangedText( row( "a", { last_changed_by : "rick", last_changed_at : "2026-11-13T21:05:44-05:00" } ) ), "rick, 2026-11-13 21:05" );
  assert.equal( cronFlipPath( "duplicate-check" ), "/api/cron-jobs/duplicate-check/enabled" );
  assert.equal( cronFlipPath( "a b/c" ), "/api/cron-jobs/a%20b%2Fc/enabled" );
  assert.equal( CRON_JOBS_PATH, "/api/cron-jobs" );
} );

test( "each refusal gets its own sentence; a 409 or 422 detail wins over the generic line", () => {
  const refused = ( status: number, body: string ) => new ApiError( status, "/api/cron-jobs/x/enabled", body );
  assert.equal( cronFlipFailureText( new Error( "boom" ) ), "Flip failed: Error: boom" );
  assert.equal( cronFlipFailureText( refused( 403, "{}" ) ), "Only an administrator can flip a job's switch." );
  assert.equal( cronFlipFailureText( refused( 404, "{}" ) ), "The server does not know this job." );
  assert.equal( cronFlipFailureText( refused( 409, "{\"detail\":\"'x' does not read its switch yet\"}" ) ), "'x' does not read its switch yet" );
  assert.equal( cronFlipFailureText( refused( 409, "no body" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 409, "{\"detail\":\"\"}" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 409, "{\"detail\":7}" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 409, "{not json" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 422, "{\"detail\":\"bad body\"}" ) ), "bad body" );
  assert.equal( cronFlipFailureText( refused( 422, "{}" ) ), "The server refused this flip." );
  assert.equal( cronFlipFailureText( refused( 500, "{}" ) ), "Flip failed (HTTP 500)." );
  assert.equal( refusalDetail( refused( 422, "prefix {\"detail\":\"x\"}" ) ), "x", "the body may follow other text" );
} );

test( "the reads field picks the wording; without it the honoured flag decides", () => {
  assert.equal( cronReadsText( row( "a", { reads : "run" } ) ), "reads its switch at each run" );
  assert.equal( cronReadsText( row( "a", { reads : "tick" } ) ), "reads its switch every tick" );
  assert.equal( cronReadsText( row( "a", { reads : null } ) ), "reads its switch" );
  assert.equal( cronReadsText( row( "a", { reads : "other" } ) ), "reads its switch" );
  assert.equal( cronReadsText( row( "a", { honoured : false } ) ), "does not read its switch yet" );
} );

test( "the inside note shows only while the host job is off", () => {
  const jobs = [ row( "host", { enabled : false } ), row( "guest", { inside : "host" } ) ];
  assert.equal( cronInsideText( jobs[ 1 ]!, jobs ), "off while host is off" );
  assert.equal( cronInsideText( jobs[ 1 ]!, [ row( "host" ), jobs[ 1 ]! ] ), null, "host is on" );
  assert.equal( cronInsideText( jobs[ 1 ]!, [ jobs[ 1 ]! ] ), null, "host is not listed" );
  assert.equal( cronInsideText( row( "x" ), jobs ), null, "no inside field" );
  assert.equal( cronInsideText( row( "x", { inside : null } ), jobs ), null );
} );
