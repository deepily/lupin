"""
Where the index and the reuse-review data live.

The index root is the git working tree being asked about (never LUPIN_ROOT). The data
directory is per repository: fleet_data_root( index_root ) / "reuse-review". A worktree
resolves to its parent checkout, so every seat of one repository shares one data directory
and a reap never deletes it.
"""
import pathlib

from cosa.repo.symindex.spec import is_lupin_tree


def data_dir( index_root ):
    """
    Requires:
        - index_root is a repository root
    Ensures:
        - returns <fleet data root of that repo>/reuse-review as a pathlib.Path (not created)
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return pathlib.Path( fleet_data_root( pathlib.Path( index_root ) ) ) / "reuse-review"


def default_out_dir( index_root ):
    """
    Ensures:
        - a lupin tree writes its generated index to <root>/src/docs/index (gitignored)
        - any other root writes to <data dir>/index/<repo name>, so a read-only tree such as
          lupin-mobile is never dirtied
    """
    root = pathlib.Path( index_root )
    if is_lupin_tree( root ): return root / "src" / "docs" / "index"
    return data_dir( root ) / "index" / root.name
