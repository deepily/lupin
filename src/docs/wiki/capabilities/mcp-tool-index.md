---
capability: mcp-tool-index
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.cosa_voice_mcp.SessionIdUnavailable@dffa40682f
  - lupin_mcp.cosa_voice_mcp.ask_open_ended_batch@872579d2a8
  - lupin_mcp.cosa_voice_mcp.commons_ask_async@5445a75f25
  - lupin_mcp.cosa_voice_mcp.commons_ask_sync@c46d565ba7
  - lupin_mcp.cosa_voice_mcp.commons_post@36eb90ac0a
  - lupin_mcp.cosa_voice_mcp.commons_read@b4d1432934
  - lupin_mcp.cosa_voice_mcp.commons_who@3177ce9d51
  - lupin_mcp.cosa_voice_mcp.disable_speakerphone@030b98092f
  - lupin_mcp.cosa_voice_mcp.dismiss_sessions@255fd53eeb
  - lupin_mcp.cosa_voice_mcp.enable_speakerphone@350b511185
  - lupin_mcp.cosa_voice_mcp.get_session_info@1e77edc0fc
  - lupin_mcp.cosa_voice_mcp.list_spawned_sessions@0a73688883
  - lupin_mcp.cosa_voice_mcp.notify@c08eb71a9d
  - lupin_mcp.cosa_voice_mcp.podcast_for_rick@b486e62b05
  - lupin_mcp.cosa_voice_mcp.self_respin@2857736ee0
  - lupin_mcp.cosa_voice_mcp.set_session_topic@7b22719296
  - lupin_mcp.cosa_voice_mcp.spawn_sessions@2e3e6c1741
  - lupin_mcp.cosa_voice_mcp.strip_fenced_code_blocks@262bae0501
  - lupin_mcp.cosa_voice_mcp.task_amend@651b9f05e9
  - lupin_mcp.cosa_voice_mcp.task_ask_unpark@ee0fc22ee2
  - lupin_mcp.cosa_voice_mcp.task_correlate@94721b7c8e
  - lupin_mcp.cosa_voice_mcp.task_create@54294c6ded
  - lupin_mcp.cosa_voice_mcp.task_edit@77122497e9
  - lupin_mcp.cosa_voice_mcp.task_get@4c2bfffd9b
  - lupin_mcp.cosa_voice_mcp.task_promotion_status@e98ba15e4e
  - lupin_mcp.cosa_voice_mcp.task_query@8463cd92b8
  - lupin_mcp.cosa_voice_mcp.task_request@3bafc3740a
---
# MCP tool index
Which tool of the cosa-voice server ([[cosa-voice-mcp-server]]) does what, and where the detail is. All are defined in `cosa_voice_mcp.py`.
- Voice: `notify` announces without waiting, and `ask_open_ended_batch` asks several open questions on one card. `strip_fenced_code_blocks` removes code fences from a spoken message. `enable_speakerphone` and `disable_speakerphone` change conversation mode, on a user's instruction only.
- Session: `get_session_info` returns the ids, server URL, speakerphone flag, voice persona and skeleton crew state. `set_session_topic` stores the topic in the bridge file. `SessionIdUnavailable` is raised, not a hard exit, when no id resolved outside the MCP server.
- Peers: `commons_post`, `commons_read` and `commons_who` write, tail and list the blackboard. `commons_ask_async` posts a question and returns, and `commons_ask_sync` blocks for a reply ([[mcp-commons-and-dm]], [[mcp-commons-ask-async]]).
- Seats: `spawn_sessions`, `dismiss_sessions` and `list_spawned_sessions` start, end and list a manager's seats. `self_respin` schedules a `/clear` into the seat's own pane ([[mcp-session-spawn-and-reap]]).
- Task store: `task_create`, `task_query`, `task_get` and `task_promotion_status` write and read rows. `task_correlate` re-keys one, `task_amend` appends to its body, and `task_edit` changes five free-edit fields ([[mcp-task-store-tools]]).
- Rick: `task_request` and `task_ask_unpark` ask him to move a row and never move it. `podcast_for_rick` asks about a podcast of one file and starts it on a yes ([[mcp-server-plumbing]]).
