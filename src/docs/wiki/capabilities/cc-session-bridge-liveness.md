---
capability: cc-session-bridge-liveness
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_dead_sessions@ad6c28e5f2
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_bridge_mtime@681d5820fe
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_bridge_touch_failure_count@365d0e6864
  - lupin_cli.claude_code.hooks.lib.session_bridge.prune_dead_persona_bridges@0f582c3bd3
  - lupin_mcp.bridge_liveness_middleware.BridgeLivenessMiddleware@9aa910aa7c
---
# Claude Code session bridge liveness
Readers and cleanup that tell whether a seat is still running, based on its bridge file. Layout and the live-bridge rules are in [[cc-session-bridge]].
## What it does
- `find_dead_sessions()` takes candidate ids and returns those whose bridge is found and whose filename, listener and Claude pids are all confirmed dead.
- A candidate with no readable bridge is not dead, because absence is not death. Inside a container the function returns an empty set.
- `get_bridge_mtime()` returns a bridge file's mtime in epoch seconds, or `None`. The arbiter shows it as an honest age, not a boolean.
- `get_bridge_touch_failure_count()` counts failures that `touch_bridge_mtime()` swallowed in this process. It only means something in a long-lived process.
- `prune_dead_persona_bridges()` sets `voice_persona` to null on bridges whose host pid is dead and returns how many it changed.
- The prune runs at SessionStart on the host, so leftover personas from earlier days do not exhaust the allocation pool.
- `BridgeLivenessMiddleware` is the cosa-voice server's stamp. Its `on_call_tool` calls `touch_bridge_mtime()` before every inbound tool call, then returns the tool result unchanged. A busy seat that never reaches a stop hook still shows a fresh mtime.
## Don't
- Do not run the prune inside a container. Host pids are invisible there, so every bridge would look dead.
## Invariants
- The middleware has no guard of its own. It relies on `touch_bridge_mtime()` never raising. If that catch is narrowed, the middleware needs its own try block, because the stamp runs before every tool.
- None of these raises. Death checks lean toward alive.
