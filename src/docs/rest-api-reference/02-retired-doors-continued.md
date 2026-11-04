> Part 2 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): retired doors continued: resume, Claude Code, survivors.

**The two resume doors retired**. Rick ruled: "build v2 resume, then retire".
They rebuild a job from server-side state, which a `SubmitRequest` cannot express. They needed a verb of their own: `POST /api/v2/resume-job`.
One body serves both kinds:

```json
{ "resume_from": "<job id_hash | tfe id | plan path | description>",
  "lead_model_override": "?", "worker_model_override": "?", "thinking_effort": "?" }
```

A job-id-shaped `resume_from` (not `tfe-`) goes straight to the factory, as door 6 did.
Anything else goes through the TFE resolver, as door 7 did, including its `ambiguous` answer.

**The direct path checks ownership**. The caller must own the job or be an admin.
Ownership is the owner on the `job_history` row, never the id string's suffix.
A non-owner, an unknown id and a row with no owner all get the same 404, so the answer does not reveal which ids exist.

**The Claude Code pair retired, and the upgrade is what made that possible**.
`/api/claude-code/submit` and its alias `/api/claude-code/queue/submit` (one handler) both answer 410 naming `/api/v2/submit`.
Rick ruled that the Claude Code job be upgraded to the front door rather than left to die.
The tombstone is the second half of that ruling, not a contradiction of it.
The work still runs, through `{"command": "agent router go to claude code", "args": {…}}`.

**One more route is a permanent survivor, not a door awaiting its turn**.
`/api/upload-and-transcribe-mp3` was in the retirement table and came back out the same day.
It is not a queue door. It accepts base64 MP3, transcribes with Whisper and runs the result through `MultiModalMunger`.
It queues only on the `munger.is_agent()` branch. The other branch returns the transcription and queues nothing.
`/api/v2/ask` takes text and cannot accept audio.
Retiring the route would take browser dictation, the admin snapshot search and the multiplexer's insert-at-cursor down with it, and offer them nothing in exchange.

Its enqueue branch has already moved. The `is_agent()` path calls `ask_flow.ask(...)` in-process and refuses without a signed-in user (`routers/speech.py`).
No `push_job` is left on this route.
Rick's framing: there are two ways to ask, post your text or speak it, and both end at the same flow.
Nothing further is owed here, and the route is not scheduled for removal.
It was checked against `RETIRED_DOORS`, which does not list it.

**Two separately-managed repos still call the retired doors**: `src/lupin-mobile` and `src/lupin-plugin-firefox`.
Neither can be edited from this repo. Their cutover is owed work in each repo.
The 410 body names the replacement, so the fix is discoverable from the failure. That is the whole mitigation.

Warning: **`/api/v2/ask` is not a drop-in for `/api/push`**.
`push` queued the job and returned `{status: "queued", job_id, …}` for the WebSocket to follow up on.
`ask` answers synchronously and returns an `AskResponse`.
It also validates with a Pydantic model, so a malformed body comes back **422, not 400**.
A caller cutting over changes how it reads the result, not only where it posts.
`AskResponse.queue_position` is the one v1 field with a v2 counterpart.
It is the todo queue's size right after a queued job was pushed: a snapshot, not a live position.
It is null on every path that queued nothing.

`AskRequest.parent_id_hash` is optional.
It is the id of the monopolizing job on whose behalf the ask is made, with the same meaning as on `/api/v2/submit`.
Under `v2 executor = queued` the executor stamps it on the job as `spawned_by_id_hash`.
The consumer's intake hold then admits the job as a lineage child instead of deferring it as foreign.
Absent, nothing changes.

The test-suite runner exports its id as `LUPIN_TEST_MONOPOLIZE_PARENT_ID`, which `v2_eval.py` echoes.
A fresh user who is not an admin, the test account or the parent's owner can still carry the claim.
They send the per-run suite token in the `X-Lupin-Lineage-Token` header, on either door, while that run holds the monopoly slot.
The server accepts the token only where `v2 parent stamp token enabled = true` (Development and Testing).

A refused claim drops the stamp with a reason word in `parent_id_hash_dropped`.
One case answers **403** instead, on either door, with the reason word in the body (`detail.error` is `parent_id_hash_refused`).
That case is a claim naming the test-suite job that holds the monopoly slot right now.
The 403 stops a suite's own child waiting behind the suite for the whole run.
The token is never logged, traced or echoed.

**Table of record**: `src/cosa/rest/routers/_retired_doors.py`. **Test**:
`src/tests/unit/test_retired_queue_doors_410.py`.

---
