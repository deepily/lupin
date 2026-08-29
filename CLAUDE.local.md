## THE USER IS NEVER A TESTER

The user is (1) the architect/designer and (2) the end user. They are
NEVER the tester. Before declaring any piece of work "done" — or inviting
the user to try the software — YOU must:

1. Execute every verification layer yourself: py_compile, unit, smoke,
   WebSocket smoke, E2E UI, integration, and any protocol E2E written
   into a design doc.

2. Report results, not requests. A "done" claim without executed and
   passing verification is a bug.

3. "Manual E2E" in any doc means "not yet in pytest" — it does NOT mean
   "the user does it." You execute protocol E2Es via the dev :7999 server's
   API (submit via /api/push, poll /api/get-queue/done, read
   /api/queue/pool-status, observe WebSocket events).

4. If a step genuinely requires human judgment (visual pixel comparison
   in a subjective sense, UX intent), name that explicitly and ASK —
   do not silently defer.

5. The :8000 test-server protocol is SEPARATE from "user is never a
   tester" — it's MONOPOLIZE-MODE COLLISION AVOIDANCE, not tester duty
   and not budget approval. Rules:
   - :7999 (dev) — unrestricted. AI runs smoke, regressions, ad-hoc
     probes without asking.
   - :8000 (test) — monopolize mode, one job at a time. A verified-IDLE
     :8000 (nothing running, nothing scheduled) is bounce-then-schedule
     SELF-AUTHORIZED (2026-06-06) — the user is NO LONGER a gate.
     VERIFY IDLE with `PYTHONPATH=src python3 -m cosa.rest.venue_idle
     --port 8000` and read its EXIT CODE (0 IDLE / 1 BUSY / 2 UNKNOWN) —
     NOT pool-status, and NOT the queue listings alone. Row e6b8fe56,
     measured 2026-08-25: monopolize_id only moves for a monopolize job
     that has already STARTED — it names WHICH job holds the slot, an
     identity question, and says nothing about queued or inline work.
     The listings are user-filtered (403 on user_filter=* for this
     account), so a peer's queued job is invisible in them. This rule
     already told you to read the queue; the command below is the one
     reliable way to do that. UNKNOWN IS NOT IDLE.
     Then place it: empty queue → bounce + schedule + run now;
     something already scheduled → place yours AFTER it (never jump an
     expected-next run); something RUNNING → queue behind, no bounce.
     Only KILLING a live in-flight job needs the user's word. NEVER inject
     via ad-hoc API / curl / CLI (side-door collides with scheduled runs
     and poisons both). Submit ONLY via /api/test-suite/submit.

## Technology Warnings
- Flask Is deprecated. DO NOT use, ever!

## Session Initialization
- The first thing you should do when you start a session is read the global Claude configuration file And follow its instructions.

## Project Identifiers
- This rep SHORT_PROJECT_PREFIX Is [LUPIN]

## Project Repositories
- The project includes a repository named `genie-plugin-firefox` which is part of the larger project, but must be managed separately from this main repository