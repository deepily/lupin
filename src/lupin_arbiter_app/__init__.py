"""
lupin-arbiter-app, the standalone host-side out-of-band fleet watcher on :8001.

A separate uvicorn process whose uptime is independent of the dev (:7999) and
test (:8000) servers and any Claude Code session. Fleet vigilance therefore
survives a dev bounce and a test-monopolization run.
A monitor must be out-of-band from the monitored.

It provides GET /health with a supervised systemd --user unit and the
docker-inspect health watch. It also runs the fleet-stall sweep, ported from the
in-process arbiter, and serves GET /state, the single pane read by the
:7999 reverse-proxy.

Design corpus:
  planning-is-prompting/src/rnd/2026.06.07-arbiter-deploy-architecture.md
  planning-is-prompting/src/rnd/2026.06.07-arbiter-r0-inprocess-decommission-spec.md
"""
__version__ = "0.1.0"
