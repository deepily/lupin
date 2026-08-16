"""Snapshot-table isolation guard for the CJ Flow v2 paired eval.

WHY THIS EXISTS. The v2 flow writes snapshots back when `v2 snapshot writeback
enabled` is True (lupin-app.ini). The write lands in whatever table the ORM's
`SolutionSnapshot.__tablename__` names — today the SHARED `solution_snapshots`
table. A paired v1-vs-v2 run must NOT write that shared store (the standing
no-test-touches-a-live-dev-data-store rule) and must not let v1's writes warm
v2's cold pass (design §4). So before the paired bridge runs anything with
writeback on, it calls this guard, which REFUSES unless the app's ACTUAL write
target is a dedicated, configured, isolated table.

THE PREDICATE (resolved from the app's own runtime sources — never a hardcoded
table name, so a table rename moves the guard with it):
  · `writeback`  = config `v2 snapshot writeback enabled` (the app's own key).
  · `write_target` = `SolutionSnapshot.__tablename__` — the exact attribute the
    ORM writes through, read live. This is what the app WILL write, not what a
    config key CLAIMS.
  · `isolated_cfg` = config `v2 snapshot table` — the intended isolated table.

REFUSE when writeback is on AND either:
  (a) no `v2 snapshot table` is configured, or
  (b) the app's live write target is not that configured isolated table —
      i.e. the isolation is not actually WIRED (bug 080821da). A config key that
      the ORM does not honor is exactly the false-isolation this rejects.

This is deliberately not a name-comparison against a constant: it checks that the
thing the app writes through has been rebound to the isolated table. A guard that
trusts a config key the code ignores would pass while the writes still hit the
shared store.
"""

from __future__ import annotations

from typing import Any, Optional


class IsolationNotConfigured( RuntimeError ):
    """Raised to REFUSE a paired run whose writes would hit the shared snapshot store."""


def resolve_write_target() -> str:
    """
    Return the table the v2 write-back ORM actually writes through, read live.

    Ensures:
        - returns SolutionSnapshot.__tablename__ — the same attribute SQLAlchemy
          uses to route the insert, so this tracks a rename automatically.
    """
    from cosa.rest.db.vector_store_models import SolutionSnapshot
    return SolutionSnapshot.__tablename__


def require_isolated_snapshot_table( config_mgr: Any, *, write_target: Optional[ str ]=None ) -> Optional[ str ]:
    """
    Refuse a paired run unless the v2 write-back is provably isolated from the shared store.

    Requires:
        - config_mgr exposes .get( key, default, return_type ) for the v2 keys.
        - write_target, when passed, is the table the app writes through (injected
          for unit tests); when None it is resolved live via resolve_write_target().

    Ensures:
        - returns None when writeback is OFF — no write happens, so no isolation is needed.
        - returns the configured isolated table name when writeback is ON AND the app's
          live write target equals that configured table (isolation is wired).
        - raises IsolationNotConfigured otherwise, naming the exact mismatch, so the
          paired bridge declines LOUDLY rather than writing the shared store.
    """
    writeback = config_mgr.get( "v2 snapshot writeback enabled", default=False, return_type="boolean" )
    if not writeback:
        return None

    target       = write_target if write_target is not None else resolve_write_target()
    isolated_cfg = config_mgr.get( "v2 snapshot table", default=None, return_type="string" ) or None

    if not isolated_cfg:
        raise IsolationNotConfigured(
            f"v2 snapshot writeback is ON but no 'v2 snapshot table' is configured — a paired run "
            f"would write the shared '{target}' table. Configure an isolated table and wire the ORM "
            f"to it (bug 080821da) before running the paired eval."
        )
    if target != isolated_cfg:
        raise IsolationNotConfigured(
            f"'v2 snapshot table' is configured as '{isolated_cfg}' but the app writes through "
            f"'{target}' — the isolation is NOT wired, so writes still hit the shared store "
            f"(bug 080821da). Refusing the paired run."
        )
    return isolated_cfg
