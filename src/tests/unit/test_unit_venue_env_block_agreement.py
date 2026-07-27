"""
The UNIT VENUE's `LUPIN_ENV` and `config_block_id` must name the same environment.

THE SHAPE (row `76acde23`, Mr Radio's ruling 2026-07-27)
--------------------------------------------------------
Two knobs with similar names choose COUPLED facts:

    LUPIN_ENV        chooses the DATABASE   (development -> lupin_db_dev)
    config_block_id  chooses the INI BLOCK  (inside LUPIN_CONFIG_MGR_CLI_ARGS)

`src/tests/conftest.py` sets the second and not the first. The obvious backstop for
`76acde23` was to add `LUPIN_ENV=testing` beside it — and that was RULED AGAINST,
because it would place a SECOND STANDING AUTHORITY for one fact four lines from the
first with nothing comparing them. That is `2b20a6d6` exactly: the bug closed this
morning had four authorities for "which store backs this data" and broke server
startup because three of them were reconciled.

⇒ So: no second knob. A COMPARATOR instead — the check those authorities never had.
It is cheap, it holds whether or not anyone later adds the env var, and it fails
LOUDLY at the moment the two diverge rather than at the moment something writes to
the wrong database.

⚠️ I DEFENDED THE BACKSTOP WITH A PRECEDENT, AND THE PRECEDENT WAS NOT ONE
I argued `test_metadata_schema_drift.py` "does exactly this pairing." It does not,
and the difference is the whole point. Its `resolve_migration_built_database_url`
uses `mock.patch.dict( os.environ, {"LUPIN_ENV": "testing"} )` — a **scoped,
self-restoring** override inside a single call. It never coexists with the config
block as a standing pair, so there are never two authorities to disagree. Same for
the pin landed in `aa3bae1e`, which uses `monkeypatch.setenv`.

**A scoped override and a standing default are different shapes that read alike.**
Mr Radio was right to reject the defence; the reason is sharper than "the precedent
may be the same defect unexamined" — it is a different construct entirely.

RELATIONSHIP TO THE SHELL COMPARATOR
------------------------------------
`pfv_env_block_agree` (preflight C4b, `src/scripts/lib/preflight-vm-lib.sh:447`)
asks this question of a RUNNING CONTAINER, against compose files. It cannot see the
unit venue's process environment. This is the same rule at the tier that rule was
never applied to. The agreement semantics below are deliberately identical to it —
strip `Lupin:+`, take the segment before the first `-`, lowercase, compare — so the
two tiers cannot drift into disagreeing about what agreement means.

Venue: :7999-eligible. Pure environment reads; no database, no network, no docker.
"""
import os
import re

import pytest


BLOCK_ID_RE = re.compile( r"config_block_id=(\S+)" )


def env_block_agree( lupin_env, block_id ):
    """
    Do LUPIN_ENV and an INI block id name the same environment?

    Requires:
        - lupin_env is the env value (may be None/empty when unset)
        - block_id is the `config_block_id=` value (may be None/empty)

    Ensures:
        - returns True when they name the same environment
        - returns False when they name DIFFERENT environments
        - returns None when the comparison cannot be made (either side missing,
          or the block id lacks the `Lupin:+` prefix) — an UNDETERMINED result is
          never folded into agreement, which is the failure mode this row is about

    ⚠️ The suffix is deliberately ignored: `Lupin:+Testing-GCS` is a testing block
    with a storage variant, and treating the variant as a disagreement would make
    the check cry wolf on the shipped configuration. Semantics copied from
    `pfv_env_block_agree` so the two tiers cannot drift.

    Returns:
        bool | None
    """
    if not lupin_env or not block_id:
        return None
    if not block_id.startswith( "Lupin:+" ):
        return None
    head = block_id[ len( "Lupin:+" ) : ].split( "-" )[ 0 ].lower()
    return head == lupin_env.lower()


def unit_venue_block_id( environ=None ):
    """
    The `config_block_id` the unit venue resolves, or None.

    Ensures:
        - reads LUPIN_CONFIG_MGR_CLI_ARGS from `environ` (default os.environ)
        - returns the block id string, or None when absent/unparseable
    """
    environ = os.environ if environ is None else environ
    args    = environ.get( "LUPIN_CONFIG_MGR_CLI_ARGS", "" )
    match   = BLOCK_ID_RE.search( args )
    return match.group( 1 ) if match else None


# ── the guard ────────────────────────────────────────────────────────────────

def test_the_unit_venue_env_and_block_do_not_DISAGREE():
    """
    THE COMPARATOR. Today `LUPIN_ENV` is unset, which the app builder reads as
    `development` (`database.py:74`), and the block is `Lupin:+Development` — so
    they agree. The moment someone adds a standing `LUPIN_ENV=testing` to conftest
    without moving the block, this goes RED and names both values.

    ⚠️ An UNSET LUPIN_ENV is compared at its EFFECTIVE value, not skipped. Skipping
    when a knob is absent is how a default silently becomes an authority — the
    builder does not skip, it defaults, so neither does this.
    """
    block_id = unit_venue_block_id()
    assert block_id, (
        "no config_block_id in LUPIN_CONFIG_MGR_CLI_ARGS — this guard cannot see the "
        "venue it exists to check, so a green here would mean nothing"
    )

    # The builder's own default, not an assumption: database.py:74 reads
    # os.environ.get( "LUPIN_ENV", "development" ).
    effective_env = os.environ.get( "LUPIN_ENV" ) or "development"

    verdict = env_block_agree( effective_env, block_id )
    assert verdict is not None, (
        f"cannot compare LUPIN_ENV={effective_env!r} with config_block_id={block_id!r} "
        f"— an undetermined comparison is not agreement"
    )
    assert verdict, (
        f"THE UNIT VENUE'S TWO KNOBS DISAGREE: LUPIN_ENV={effective_env!r} chooses the "
        f"DATABASE while config_block_id={block_id!r} chooses the INI BLOCK. Nothing "
        f"crashes when these diverge — the suite reads one environment's config while "
        f"addressing another's database. Reconcile them in src/tests/conftest.py."
    )


# ── controls: the comparator must be able to say NO ──────────────────────────

@pytest.mark.parametrize(
    "lupin_env,block_id,expected",
    [
        ( "development", "Lupin:+Development", True  ),
        ( "testing",     "Lupin:+Testing",     True  ),
        ( "testing",     "Lupin:+Testing-GCS", True  ),   # variant suffix ignored
        ( "development", "Lupin:+Testing",     False ),   # the divergence that matters
        ( "testing",     "Lupin:+Development", False ),   # and its mirror
        ( "production",  "Lupin:+Development", False ),
    ],
)
def test_the_comparator_discriminates( lupin_env, block_id, expected ):
    """
    Without these, the guard above passes on a comparator that always returns
    True — precisely the vacuous-guard shape this row exists to remove.
    """
    assert env_block_agree( lupin_env, block_id ) is expected


@pytest.mark.parametrize(
    "lupin_env,block_id",
    [
        ( "",            "Lupin:+Development" ),
        ( "development", ""                   ),
        ( None,          "Lupin:+Development" ),
        ( "development", "Development"        ),   # no Lupin:+ prefix
    ],
)
def test_an_UNDETERMINED_comparison_is_not_agreement( lupin_env, block_id ):
    """
    None, never True. A comparator reporting agreement when it could not compare
    is worse than no comparator: it manufactures a green.
    """
    assert env_block_agree( lupin_env, block_id ) is None


def test_the_semantics_MATCH_the_shell_comparator():
    """
    The shell tier (`pfv_env_block_agree`, preflight C4b) asks this same question
    of a running container. If the two tiers disagreed about what agreement MEANS,
    a box could pass one and fail the other with nothing explaining why.

    Asserts against the rule as implemented in that function: strip `Lupin:+`,
    take the segment before the first `-`, lowercase, compare.
    """
    lib = os.path.join( os.environ[ "LUPIN_ROOT" ], "src/scripts/lib/preflight-vm-lib.sh" )
    with open( lib, encoding="utf-8" ) as handle:
        source = handle.read()

    assert "pfv_env_block_agree" in source, "the shell comparator has moved — re-verify the shared semantics"
    assert "block_id#Lupin:+" in source,    "the shell comparator no longer strips `Lupin:+` — semantics have drifted"
