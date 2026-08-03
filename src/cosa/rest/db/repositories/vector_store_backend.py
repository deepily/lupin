"""
Vector-store backend selector — the §6 migration-window flag seam.

The `vector store backend` config key (INI `[Lupin: Baseline]`, values ``lancedb``
| ``postgres``) selects which storage backend the ``cosa/memory/*`` classes read
from. This module is the ONE place that reads + validates that flag; Lane C's
call-site dispatch consumes ``is_postgres_backend()`` / ``get_vector_store_backend()``.

Feature-flag doctrine (feedback_feature_flag_preserves_old_path): BOTH paths stay
first-class — the flag defaults to ``lancedb`` and is flipped to ``postgres`` only
on a watched cutover, and can be flipped BACK for rollback (§6). Nothing here
touches storage; it only resolves the flag.

Created: 2026-07-01 (Lane B · Tiffany 💍) · v0.2.0
"""

from typing import Optional

from cosa.config.configuration_manager import ConfigurationManager


# The two valid backend values — single source of truth for the enum.
LANCEDB  = "lancedb"
POSTGRES = "postgres"

VALID_BACKENDS = ( LANCEDB, POSTGRES )

# Default preserves the OLD path until the watched cutover (§6).
_DEFAULT_BACKEND = LANCEDB

_CONFIG_KEY = "vector store backend"


def get_vector_store_backend( config_mgr: Optional[ConfigurationManager] = None ) -> str:
    """
    Resolve the active vector-store backend from the `vector store backend` flag.

    Requires:
        - config_mgr is a ConfigurationManager, or None (a default one is built)

    Ensures:
        - returns exactly one of VALID_BACKENDS ("lancedb" | "postgres")
        - the raw config value is lower-cased + stripped before validation
        - defaults to "lancedb" when the key is absent (old path preserved)

    Raises:
        - ValueError if the configured value is not a valid backend (fail-loud;
          NO silent fallback — a typo'd flag must surface, not degrade)
    """
    if config_mgr is None:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    raw     = config_mgr.get( _CONFIG_KEY, default=_DEFAULT_BACKEND )
    backend = str( raw ).strip().lower()

    if backend not in VALID_BACKENDS:
        raise ValueError(
            f"Invalid '{_CONFIG_KEY}' = {raw!r}; expected one of {VALID_BACKENDS}"
        )

    return backend


def is_postgres_backend( config_mgr: Optional[ConfigurationManager] = None ) -> bool:
    """
    Convenience predicate — True iff the active backend is Postgres+pgvector.

    Requires:
        - config_mgr is a ConfigurationManager, or None (a default one is built)

    Ensures:
        - returns True iff get_vector_store_backend(...) == POSTGRES
        - propagates ValueError from get_vector_store_backend on an invalid flag
    """
    return get_vector_store_backend( config_mgr ) == POSTGRES


def resolve_lancedb_path( db_path, caller: str, config_mgr: Optional[ConfigurationManager] = None ):
    """
    Gate a caller-supplied LanceDB path on the active backend — the ONE seam
    every path-taking store calls before it stores or connects.

    Before this existed, a store accepted a `db_path`, echoed it back on the
    attribute, and ignored it whenever the postgres path was active — so a
    caller (test or production) believing it had redirected the store was in
    fact reading and writing the shared one, silently. Bug `d621b111`; Rick's
    2026-07-27 ruling on decision `2b20a6d6` closed it at the source.

    Requires:
        - caller is a non-empty string naming the construction site, used
          verbatim in the raised message

    Ensures:
        - returns db_path unchanged when the LanceDB backend is active
        - returns None when the postgres backend is active AND db_path is None
          (nothing was promised, so nothing is broken)

    Raises:
        - ValueError when the postgres backend is active and db_path is not
          None — the caller asked for a path that would never be honored, and
          a silently-ignored path is the defect this seam exists to kill
    """
    if not is_postgres_backend( config_mgr ):
        return db_path

    if db_path is not None:
        raise ValueError(
            f"{caller}: a db_path was supplied ({db_path!r}) but '{_CONFIG_KEY}' is "
            f"'{POSTGRES}', so the path would be silently ignored and the SHARED "
            f"postgres store used instead. Build the LanceDB path only under the "
            f"'{LANCEDB}' backend (see routers/system.py for the reference form), or "
            f"flip '{_CONFIG_KEY}' to '{LANCEDB}' if a real LanceDB store is intended."
        )

    return None
