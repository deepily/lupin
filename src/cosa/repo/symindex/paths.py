"""
Where the index and the reuse-review data live.

The index root is the git working tree being asked about (never LUPIN_ROOT). The data
directory is per repository: fleet_data_root( index_root ) / the `reuse review data subdir` key. A worktree
resolves to its parent checkout, so every seat of one repository shares one data directory
and a reap never deletes it.
"""
import pathlib

from cosa.repo.symindex.candidates import storage_paths
from cosa.repo.symindex.spec import is_lupin_tree


def data_dir( index_root ):
    """
    Return the reuse-review data directory of the repository that index_root belongs to.

    Requires:
        - index_root is a repository root
    Ensures:
        - returns <fleet data root of that repo>/<data subdir key> as a pathlib.Path (not created)
        - the INI default of the key is today's folder name, so existing receipts stay where they are
    Raises:
        - CandidateError STORAGE_KEY_MISSING when the key and its override variable are both absent
    """
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    return pathlib.Path( fleet_data_root( pathlib.Path( index_root ) ) ) / storage_paths.data_subdir()


def default_out_dir( index_root ):
    """
    Return the directory a generated index is written to by default.

    Ensures:
        - a lupin tree writes its generated index to <root>/src/docs/index (gitignored)
        - any other root writes to <data dir>/index/<repo name>, so a read-only tree such as
          lupin-mobile is never dirtied
    """
    root = pathlib.Path( index_root )
    if is_lupin_tree( root ): return root / "src" / "docs" / "index"
    return data_dir( root ) / "index" / root.name


def registered_repo_names( config=None ):
    """
    Return the repo names the INI registers as scopes.

    Requires:
        - config is a ConfigurationManager, or None to build one

    Ensures:
        - returns the `external repos` list, the same registry the doc viewer reads
    """
    manager = config if config is not None else storage_paths.build_config()
    return [ n.strip() for n in manager.get( "external repos", default=[], return_type="list-string" ) if n.strip() ]


def index_readable( root, names=None ):
    """
    Say whether the reuse tools may answer for a repository.

    This is the one test every NOT_LUPIN_TREE site shares.

    Requires:
        - root is a repository root
        - names is None to read the INI registry, or a collection of registered repo names

    Ensures:
        - True for a lupin tree, whose index is built on demand
        - True for any other repo only when its name (a worktree counts as its parent checkout) is registered
          and a built index is published at default_out_dir( root )
        - False otherwise, so an unregistered repo, or a registered one with no built index, is refused
    """
    from cosa.repo.symindex.build import current_generation                  # imported here: build imports this module
    root = pathlib.Path( root )
    if is_lupin_tree( root ): return True
    registered = names if names is not None else registered_repo_names()
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    if pathlib.Path( fleet_data_root( root ) ).name not in registered: return False
    return current_generation( default_out_dir( root ) ) is not None
