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
