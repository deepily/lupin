---
capability: rest-core-transcript-tee
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.cc_transcript_mapper.map_record@46e3f2404a
  - cosa.rest.cc_transcript_mapper.remember_tool_name@4612076658
  - cosa.rest.cc_transcript_tailer.load_settings@89f9dfa374
  - cosa.rest.cc_transcript_tailer.epoch_for_path@d0d24a21b6
---
# Console tee: transcript mapping and tailer settings

The console tee shows a seat's Claude Code transcript live. The mapper turns transcript lines into display blocks and the tailer polls the file; the seat's transcript and bridge are on [[session-transcript-console]] and [[cc-session-bridge]].

## Mapper
- `map_record( record, budget, tool_names )` returns zero or more blocks of `{ts, role, kind, text, truncated}`. A tool call and a result whose call was seen also carry `name`.
- It returns `[]` for a non-dict, an unrecognised record type and a record with no recognised content block. Most transcript records are not messages.
- `budget` is a byte cap per block, and `0` means unbounded.
- `remember_tool_name( tool_names, tool_use_id, name )` records which tool an id belongs to. It evicts the oldest pairing beyond 4096, keeps a repeated id's place with the new name, and ignores non-string or empty input.
- A result whose call is not in the index carries no name. The mapper never guesses one.

## Tailer
- `load_settings( config_mgr )` returns five dials from `cc transcript *` INI keys: poll interval, watcher grace seconds, coalesce window, backlog tail bytes and block budget. A missing config manager gives the defaults, and a manager whose `get` raises propagates the error; 0.25 s, 30 s, 300 ms, 65,536 and 8,192.
- `epoch_for_path( transcript_path )` is the file name without its extension, the per-session id Claude Code writes, or `""` for an empty path.
- The epoch scopes a byte offset. A new epoch, as after a `/clear`, means the old offset no longer applies.

## Don't
- Don't build a new `tool_names` dict for each poll. Keep one per seat across polls, or results lose their names.
