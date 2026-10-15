---
capability: heartbeat-wait-graph
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.dependency_graph.build_graph@83a8e5fa1c
  - cosa.agents.heartbeat_arbiter.dependency_graph.build_store_blocked_item_index@954977fe98
  - cosa.agents.heartbeat_arbiter.dependency_graph.build_store_wait_edges@6ecf3ca864
  - cosa.agents.heartbeat_arbiter.dependency_graph.build_wait_edges@487e447659
  - cosa.agents.heartbeat_arbiter.dependency_graph.cycle_is_store_backed@f0a50dd9c1
  - cosa.agents.heartbeat_arbiter.dependency_graph.edge_is_store_backed@39e228eb30
  - cosa.agents.heartbeat_arbiter.dependency_graph.find_deadlock_cycles@258946b60f
  - cosa.agents.heartbeat_arbiter.dependency_graph.hold_contradicts_peer_edge@77f366fc84
  - cosa.agents.heartbeat_arbiter.dependency_graph.hold_is_stale@c5b8f97dba
  - cosa.agents.heartbeat_arbiter.dependency_graph.session_is_stale@348fcc75c1
---
# Heartbeat wait graph

Builds the who-waits-on-whom graph from the fleet view and finds deadlock rings. It is pure and never raises. [[heartbeat-arbiter]] escalates a ring to a person and never breaks one itself.

## What it does
- `build_wait_edges` turns each session's `holding_on` value of the form `peer:X` into a holder to awaited edge. It keeps only the first persona name, so prose after it cannot mint a phantom peer.
- It drops edges from holders in `stale_holders`, and from sessions older than the alive threshold when `now` and the threshold are given. If a holder appears twice, the last edge wins.
- `find_deadlock_cycles` walks that graph and returns each ring as a list of personas, smallest name first. A self-loop is a ring of one.
- `build_graph` returns the edges and the rings together, with the same filters applied.
- `hold_is_stale` is true for a readable hold that is expired, declared not owed, or past its `next_chase`. A missing hold is not stale.
- `hold_contradicts_peer_edge` is true when a fresh hold's `awaiting` names no peer, or a different one, than the derived edge.
- `session_is_stale` is true only when the session's own last activity is older than the threshold. A missing or unparseable time keeps the edge.
- `build_store_wait_edges` builds owner to owner edges from the task store's `blocked_by` refs. User refs and self-edges are ignored. A blocker the poll cannot resolve is left out.
- `build_store_blocked_item_index` maps each owner pair to the blocked task ids, which the blocker announcement key needs.
- `cycle_is_store_backed` and `edge_is_store_backed` say whether the store backs every ring edge, or one edge.

## Invariants
- Every filter only removes edges. When evidence is missing the edge is kept, except `edge_is_store_backed`, which returns false without a store edge.
- A derived ring escalates only when the store backs it. A self-cycle is never backed.
