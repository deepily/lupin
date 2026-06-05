"""
Heartbeat Arbiter — pure consumer leaves (Tiffany 💍's lane, v2 fleet arbiter).

The arbiter (design: lupin src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md)
extends the agentic HeartbeatPokerJob to consume the fleet heartbeat-events
exhaust and drive auto-ping / idle-roster / dependency-graph behaviors. THIS
package holds the PURE, 100%-tested decision leaves the consumer composes:

    - dependency_graph : who-waits-on-whom cycle (deadlock) detection
    - ping_throttle    : per-edge backoff + global rate-cap decisions
    - idle_roster      : idle-roster assembly + trust labeling

Each leaf is pure + never-raises (the v1/v2 leaf pattern). The daemon
integration (poll loop, real commons DMs, manager surface) is the consumer's
lane (Rachel / the Poker), not here.
"""
