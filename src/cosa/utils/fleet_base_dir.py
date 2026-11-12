#!/usr/bin/env python3
"""
One resolver for the fleet data folder of markers, receipts and samples.

The wake check, the self-respin observer and the marker writer each held a `_resolve_base_dir`.
Each returned the caller's directory when given, else `str( fleet_data_root() )`.
The marker writer keyed it on the seat's own repo. This is the one copy.

Hook-library code cannot import cosa, so `lupin_cli/claude_code/hooks/lib/heartbeat_hold.py`
keeps its own `_resolve_base_dir`, which returns a Path and creates the folder.
"""


def fleet_base_dir( base_dir=None, repo_root=None ):
    """
    Resolve the directory that markers, receipts and samples live under.

    Requires:
        - base_dir is a directory path, or None
        - repo_root is a repo root path, or None for the ambient root

    Ensures:
        - returns base_dir unchanged when it is not None, so tests and explicit callers win
        - otherwise returns str( fleet_data_root( repo_root ) ), called with no argument when repo_root is None; a worktree collapses to its parent checkout
        - the hook library is imported lazily, which keeps this module a leaf
    """
    if base_dir is not None: return base_dir
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return str( fleet_data_root() if repo_root is None else fleet_data_root( repo_root ) )
