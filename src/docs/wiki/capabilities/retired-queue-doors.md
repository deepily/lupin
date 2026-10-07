---
capability: retired-queue-doors
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.routers._retired_doors.refusal_detail@28e39ec43b
  - cosa.rest.routers._retired_doors.gone@f7af6a87f6
  - cosa.rest.routers._retired_doors.tombstone_description@0b40abed5f
---
# Retired queue doors

The old routes that put work on the queue now answer `410 Gone` and name the door that replaced them. `cosa.rest.routers._retired_doors` holds the table and the one shared refusal. The replacements are in [[v2-ask-flow]]; the queue they fed is [[cj-flow-queue]].

## What it does
- `RETIRED_DOORS` maps each retired path to its replacement. It held 16 doors when counted on 2026-10-07: 3 go to `/api/v2/ask`, 11 to `/api/v2/submit` and 2 to `/api/v2/resume-job`.
- Question-shaped doors (`/api/push`, `/api/job-history/{job_id}/retry`, `/api/podcast-generator/submit`) point at `ask`. The two resume-from-checkpoint doors point at `resume-job`. Work whose command is already decided points at `submit`.
- `gone( path )` raises `HTTPException( 410 )`. `refusal_detail` builds its text: the path, the replacement, and `REMOVE BY 2026-12-31`. `tombstone_description` gives `/docs` a one-line description with the same replacement and date.
- Eleven router modules call `gone( ... )` from a handler: the queues router (five doors), the Claude Code pair, the three research doors, and one each for the podcast, presentation, SWE-team, bug-fix, mock-job and test-suite doors.

## Invariants
- A tombstone answers 410, not 404, and carries its removal date in the message. Callers in the two separately managed client repos will never read the source.
- No tombstone has an auth dependency. A stale client gets the same 410 as a signed-in one, and not a 401 that reads like a credentials problem. All 16 handlers take no parameters, and none of the eleven modules sets router-level dependencies.
- `refusal_detail` raises `KeyError` for a path that is not in the table. A typo cannot produce a refusal that names the wrong replacement.
- A door is retired only when its replacement can already build the work. A refusal that points at a door that answers "I do not understand" teaches a caller less than the handler it replaced.
- `/api/upload-and-transcribe-mp3` is not a tombstone. It still transcribes audio, and only its agent branch hands the text to the v2 ask flow.

## How to extend
- To retire a door: add its path and replacement to `RETIRED_DOORS`, replace the handler body with `gone( path )`, and use `tombstone_description( path )` as the route description. Move any guard the old handler carried into the job first.
- Give each retired path its own stub. `refusal_detail` has to know which path it is naming.
