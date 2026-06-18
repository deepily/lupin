"""
Unit tests locking in the Alembic TRUE-baseline chain invariants (D7 hybrid
ruling — TODO.md "Alembic TRUE baseline migration").

These are DB-FREE structural assertions read straight from the migration
scripts via Alembic's ``ScriptDirectory`` — they need no Postgres, so they run
in plain CI / the :7999 unit bucket. They guard the chain against the most
likely future regression: an accidentally re-introduced SECOND base (which is
exactly the broken state the baseline replaced), a fork in the chain, or a
silent un-rebasing of the post-baseline span.

The EMPIRICAL empty-DB ``alembic upgrade head`` proof (and the downgrade-base
round-trip + stamp-compatibility reconciliation) require a live Postgres and are
executed as an integration-tier step against the dev Postgres container — see
the lane's completion receipt. They are intentionally NOT inlined here because a
throwaway-DB create/drop is a stateful Postgres dependency, out of scope for a
DB-free unit test.
"""
import os

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config


# The TRUE baseline (migration zero) and the current head.
_BASELINE_REVISION = "000000000000"
_HEAD_REVISION     = "e5f6a7b8c9d0"

# The post-baseline span that MUST be preserved, base-first.
_POST_BASELINE_CHAIN = [
    "000000000000",   # true baseline (schema.sql origin)
    "f0a1b2c3d4e5",   # task_store tables (rebase anchor)
    "a1b2c3d4e5f6",   # fcm_tokens
    "b2c3d4e5f6a7",   # task_event_reason
    "c3d4e5f6a7b8",   # notification direction + DM fields
    "d4e5f6a7b8c9",   # is_protected
    "e5f6a7b8c9d0",   # proxy/trust/prediction/server_lifecycle tables + 5 notif cols (head)
]

# The eight pre-baseline revisions absorbed INTO the baseline — they must no
# longer exist as standalone scripts.
_ABSORBED_REVISIONS = [
    "210acf4d54dd", "275fb8d9c75c", "62ec6f256d27", "a3b4c5d6e7f8",
    "b5c6d7e8f9a0", "c7d8e9f0a1b2", "d8e9f0a1b2c3", "e9f0a1b2c3d4",
]


def _script_dir():
    """Build a ScriptDirectory over the project's migrations (no DB needed)."""
    config = build_alembic_config( database_url=None )
    return ScriptDirectory.from_config( config )


def test_single_base_is_true_baseline():
    """The chain has EXACTLY ONE base, and it is the true baseline 000000000000."""
    script = _script_dir()
    bases  = list( script.get_bases() )
    assert bases == [ _BASELINE_REVISION ], f"expected single base {_BASELINE_REVISION!r}, got {bases!r}"


def test_single_head():
    """The chain has EXACTLY ONE head (no forks / parallel branches)."""
    script = _script_dir()
    heads  = list( script.get_heads() )
    assert heads == [ _HEAD_REVISION ], f"expected single head {_HEAD_REVISION!r}, got {heads!r}"


def test_baseline_down_revision_is_none():
    """The baseline is migration ZERO — its down_revision is None."""
    script   = _script_dir()
    baseline = script.get_revision( _BASELINE_REVISION )
    assert baseline.down_revision is None


def test_post_baseline_chain_is_linear_and_preserved():
    """Walking base->head yields exactly the preserved linear post-baseline chain."""
    script = _script_dir()
    # iterate_revisions(head, "base") walks newest->oldest INCLUSIVE of the root;
    # reverse to base-first. ("base" is alembic's token for "down to the root".)
    walked = [ rev.revision for rev in script.iterate_revisions( _HEAD_REVISION, "base" ) ]
    walked.reverse()
    assert walked == _POST_BASELINE_CHAIN, f"chain drift: {walked!r}"


def test_task_store_rebased_onto_baseline():
    """f0a1b2c3d4e5 (task_store) is rebased directly onto the baseline."""
    script = _script_dir()
    rev    = script.get_revision( "f0a1b2c3d4e5" )
    assert rev.down_revision == _BASELINE_REVISION, (
        f"task_store down_revision must be {_BASELINE_REVISION!r} (the baseline), got {rev.down_revision!r}"
    )


def test_absorbed_revisions_are_gone():
    """The eight pre-baseline revisions are absorbed — no standalone scripts remain."""
    script        = _script_dir()
    all_revisions = { rev.revision for rev in script.walk_revisions() }
    leaked        = sorted( set( _ABSORBED_REVISIONS ) & all_revisions )
    assert not leaked, f"absorbed revisions still present as scripts: {leaked!r}"


def test_baseline_script_file_present():
    """The baseline script physically exists under versions/ (self-contained DDL)."""
    script = _script_dir()
    rev    = script.get_revision( _BASELINE_REVISION )
    assert rev.path.endswith( "000000000000_true_baseline_schema.py" )
    assert os.path.isfile( rev.path )
