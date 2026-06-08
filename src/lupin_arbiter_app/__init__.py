"""
lupin-arbiter-app — the standalone, host-side, OUT-OF-BAND fleet watcher on :8001.

A separate uvicorn process whose uptime is independent of the dev (:7999) and
test (:8000) servers and any Claude Code session, so fleet vigilance survives a
dev bounce and a test-monopolization run (deploy doc §2 — a monitor must be
out-of-band from the monitored).

L1 (this scaffold): GET /health + a supervised systemd --user unit.
L2: Loop A (docker-inspect health watch). L3: Loop B (fleet-stall sweep, ported
from the v2.2 in-process arbiter) + the R0 in-process decommission. L4: GET
/state single pane + the :7999 reverse-proxy.

Design corpus:
  planning-is-prompting/src/rnd/2026.06.07-arbiter-deploy-architecture.md
  planning-is-prompting/src/rnd/2026.06.07-arbiter-r0-inprocess-decommission-spec.md
"""
__version__ = "0.1.0"
