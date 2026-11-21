---
capability: preference-replay-scratch-db
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.scratch_db.scratch_session@ece12527cc
  - cosa.research.preference_replay.scratch_db.session_scope@176e3f4f5e
  - cosa.research.preference_replay.scratch_db.load_export@4b0d9af5c1
---
# Preference replay: the scratch database

A throwaway SQLite copy of the tables the extractor replay reads and writes ([[preference-replay-extractor-replay]]). The replay never touches the live database.

## What it does
- `scratch_session( path )` yields a session over copies of the tables: the notifications, forecast log, principles, evidence and arm forecasts. One connection is shared, so it works from any thread. The engine is disposed when the block ends.
- With no path the copy is empty and in memory. With a file path, a second call finds the rows the first call wrote, so a stopped run resumes ([[preference-replay-archive-stages]]).
- SQLite draws the two Postgres-only column types as plain text. A UUID made only of digits and the letter e reads back as a float.
- `session_scope( session )` wraps an open session as the context manager the extractor job's factory returns. It commits when the block ends cleanly.
- `load_export( session, export )` inserts every notification of a context export, each id once. It returns the count.
- Ids and the recipient become UUIDs, and every timestamp becomes an aware datetime. A key the table has no column for is dropped.

## Don't
- Don't point the replay at the live database. A load that meets a float-like id fails loudly and changes no row.
