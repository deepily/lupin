#!/usr/bin/env python3
"""
The reuse-review gating flag and the report-or-reject decision that reads it.

The reuse-reviewer skill (`.claude/skills/reuse-reviewer/`) collects findings from the linters.
One key in the main configuration file, `reuse review gating`, sets whether a finding blocks.
It ships `false` and stays false until Rick sets a recall bar.

    - false: the skill reports every finding and rejects nothing.
    - true: the skill rejects the diff when any finding remains.

The value is read fresh from the file on each call. The configuration manager is a
process-lifetime singleton and would keep a stale answer.

An absent key, an unreadable file or a value that is not true or false reads as false.
It prints a line tagged `[REUSE-REVIEW-GATE]` to stderr. A gate that cannot be read must not
block work.
"""
import argparse
import json
import os
import sys

from lupin_mcp import fleet_cap_ini_io, fleet_size_cap

GATING_KEY   = "reuse review gating"
INI_OVERRIDE = "LUPIN_REUSE_REVIEW_INI"
LOG_TAG      = "[REUSE-REVIEW-GATE]"


def ini_path():
    """
    Name the configuration file the flag is read from.

    Ensures:
        - returns the env override when it is set, so tests never touch the live file
        - otherwise returns the main checkout's configuration file
    """
    override = os.environ.get( INI_OVERRIDE )
    if override: return override
    return fleet_size_cap.main_checkout_ini_path()


def _say( detail ):
    """Print one tagged line to stderr."""
    print( f"{LOG_TAG} {detail}", file=sys.stderr, flush=True )


def read_gating( path=None, quiet=False ):
    """
    Read the flag fresh from the configuration file.

    Requires:
        - path is a file path, or None for the default file
    Ensures:
        - returns True only for a clean `true`
        - returns False for `false`, and for an absent, doubled, unreadable or garbled key
        - every answer that is not a clean boolean prints one tagged line, unless quiet
    """
    target = path if path is not None else ini_path()
    raw    = fleet_cap_ini_io.read_value_from_disk( target, GATING_KEY )     # a fresh disk read: ConfigurationManager is a process-lifetime singleton and would keep a stale value
    if raw is None:
        if not quiet: _say( f"could not read `{GATING_KEY}` from {target}; gating reads as false (report only)." )
        return False
    lowered = raw.strip().lower()
    if lowered in ( "true", "false" ): return lowered == "true"
    if not quiet: _say( f"`{GATING_KEY}` holds {raw!r}, which is not true or false; gating reads as false (report only)." )
    return False


def evaluate( findings, gating ):
    """
    Decide report-only or reject for a list of findings.

    Requires:
        - findings is a list of finding dicts or strings from the linters and the reuse rulings
        - gating is a bool, normally from read_gating
    Ensures:
        - returns { mode, reject, count, findings }
        - mode is "reject" when gating is true and "report-only" otherwise
        - reject is true only when gating is true and at least one finding remains
        - the findings are returned in both modes, so a report-only run loses nothing
    """
    return { "mode": "reject" if gating else "report-only", "reject": bool( gating and findings ),
             "count": len( findings ), "findings": list( findings ) }


def main( argv=None, out=None ):
    """
    Command line: print the decision for a JSON list of findings.

    Requires:
        - --findings names a JSON file holding a list
    Ensures:
        - prints the decision as JSON on `out`
        - returns 1 when the diff is rejected, else 0
    """
    ap = argparse.ArgumentParser( description="Report or reject, by the `reuse review gating` flag." )
    ap.add_argument( "--findings", required=True )
    ap.add_argument( "--ini" )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    with open( a.findings, encoding="utf-8" ) as handle: findings = json.load( handle )
    verdict = evaluate( findings, read_gating( a.ini ) )
    print( json.dumps( verdict, indent=2 ), file=out )
    return 1 if verdict[ "reject" ] else 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
