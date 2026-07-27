"""
`src/scripts/check_schema_at_head.py` — row `4aa2b9d5`, the schema-drift assertion.

THE GAP
-------
`main.py` migrates to head at startup, which closes the code-newer-than-schema window
BY CONSTRUCTION — for any path that goes through startup.

**`lupin-vm.sh push-bundle --checkout` does not go through startup.** Moving code
WITHOUT bouncing the servers is the entire point of that verb. So it is precisely a
path that lands new code on a box while skipping the startup migrate — and afterwards
the VM can run code that `SELECT`s a column its database does not have. The concrete
instance (commit `9fbb6258`) selects `body_changed_ts` from migration `38e025169a73`;
against a pre-migration schema that is a 500 on **every task query**.

Preflight had 31 assertions across 5 layers and **not one looked at the schema**. A
box could pass every one of them green while running two migrations behind, and the
green would have been honest about everything it actually asserted.

THREE OUTCOMES, NOT TWO
-----------------------
`0` AT_HEAD · `1` DRIFT · `2` CANNOT_DETERMINE. "The schema is behind" and "I could
not read the schema" have DIFFERENT REMEDIES — migrate versus fix connectivity — and
collapsing them would reproduce, inside this check, the defect class the surrounding
work exists to remove. Per the settled rule, a caller must treat `2` as BLOCKING:
the question is "does not-knowing make the action UNSAFE?", and here it does.

⚠️ THE NEGATIVE CONTROL THE ROW DEMANDED
-----------------------------------------
*"Point it at a box one migration behind and watch it FAIL. A schema check that has
only ever seen a matching pair has not been tested."*

Done, live, before this file existed — by injecting `DATABASE_URL` at a throwaway
SQLite database whose `alembic_version` row was written by hand, with every verdict
predicted first:

    sqlite stamped at head.down_revision  -> DRIFT             exit 1
    sqlite with no alembic_version table  -> DRIFT (unstamped) exit 1
    unreachable postgres (closed port)    -> CANNOT_DETERMINE  exit 2
    sqlite stamped at head                -> AT_HEAD           exit 0

The last arm is the control on the first: had `DATABASE_URL` been ignored, both would
have read the real database and both would have said AT_HEAD — so the DRIFT arm
failing to be DRIFT is what would have exposed a dead injection. The probe was also
run inside the live `lupin-rest-test` container (`AT_HEAD`, `38e025169a73`).

The tests below pin `classify()` — the decision — exhaustively and in-process. They
do NOT re-prove that alembic and SQLAlchemy work; that arm was the live run above.

Venue: :7999-eligible. Pure in-process; no DB, no docker, no network.
"""
import importlib.util
import os
import subprocess

import pytest

import cosa.utils.util as cu

PROBE_PATH = os.path.join( cu.get_project_root(), "src/scripts/check_schema_at_head.py" )


def _load():
    """Import the probe by path — it lives in src/scripts/, which is not a package."""
    spec = importlib.util.spec_from_file_location( "check_schema_at_head", PROBE_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


csah = _load()

HEAD = "38e025169a73"
PREV = "53835fd51f1a"


# ── the decision: every outcome, each reachable and each distinct ─────────

def test_matching_revisions_are_AT_HEAD():
    code, verdict, _detail = csah.classify( HEAD, HEAD, None )
    assert ( code, verdict ) == ( csah.EXIT_AT_HEAD, "AT_HEAD" )


def test_a_database_one_migration_behind_is_DRIFT_and_names_BOTH_revisions():
    """
    THE ROW'S DEFECT. The detail must name both sides: "your schema is old" without
    saying which revision either side is on sends the reader to go find out, and the
    finding-out is the expensive part.
    """
    code, verdict, detail = csah.classify( HEAD, PREV, None )
    assert ( code, verdict ) == ( csah.EXIT_DRIFT, "DRIFT" )
    assert PREV in detail and HEAD in detail


def test_a_database_that_was_NEVER_STAMPED_is_DRIFT_not_CANNOT_DETERMINE():
    """
    ⚠️ A DELIBERATE ASYMMETRY, and the one place a reader is most likely to disagree.

    `current is None` looks like a failure to read. It is not: the read SUCCEEDED and
    returned "this database has no revision". That is a definite fact, it definitely
    is not head, and it takes DRIFT's remedy — the same migrate. Reporting it as
    CANNOT_DETERMINE would send an operator to debug connectivity that is already
    working.
    """
    code, verdict, detail = csah.classify( HEAD, None, None )
    assert ( code, verdict ) == ( csah.EXIT_DRIFT, "DRIFT" )
    assert "never stamped" in detail


def test_a_reason_ALWAYS_wins_and_is_never_folded_into_a_pass():
    """
    An error is never absorbed. Even with a revision pair that would otherwise agree,
    a reason present means the pair cannot be trusted to describe anything.
    """
    code, verdict, detail = csah.classify( HEAD, HEAD, "the DB was unreachable" )
    assert ( code, verdict ) == ( csah.EXIT_CANNOT_DETERMINE, "CANNOT_DETERMINE" )
    assert "unreachable" in detail


def test_a_tree_with_NO_head_cannot_claim_agreement():
    """
    If the tree reports no head, "at head" has no meaning — so agreement cannot be
    claimed, even against a database that also reports nothing. Two unknowns matching
    is not a measurement.
    """
    code, verdict, _d = csah.classify( None, None, None )
    assert ( code, verdict ) == ( csah.EXIT_CANNOT_DETERMINE, "CANNOT_DETERMINE" )


def test_the_three_exit_codes_are_pairwise_DISTINCT():
    """
    The discriminator. If DRIFT and CANNOT_DETERMINE ever collapsed, a caller could
    not tell "migrate this box" from "your probe could not connect" — and the
    preflight wires them to different remedies and different tiers.
    """
    at_head, _, _ = csah.classify( HEAD, HEAD, None )
    drift,   _, _ = csah.classify( HEAD, PREV, None )
    unknown, _, _ = csah.classify( HEAD, HEAD, "boom" )
    assert { at_head, drift, unknown } == {
        csah.EXIT_AT_HEAD, csah.EXIT_DRIFT, csah.EXIT_CANNOT_DETERMINE
    }, f"exit codes collapsed: {at_head} {drift} {unknown}"


# ── read_revisions: every failure surface reports WHICH half failed ───────

def _force_import_failure( monkeypatch, target, exc ):
    """Make one import inside read_revisions raise, leaving the others intact."""
    import builtins
    real = builtins.__import__

    def fake( name, *a, **kw ):
        if name == target:
            raise exc
        return real( name, *a, **kw )

    monkeypatch.setattr( builtins, "__import__", fake )


def test_an_unimportable_migration_stack_is_a_named_reason( monkeypatch ):
    _force_import_failure( monkeypatch, "alembic.script", ImportError( "no alembic" ) )
    head, current, reason = csah.read_revisions()
    assert ( head, current ) == ( None, None )
    assert "cannot import" in reason


def test_an_unreadable_tree_head_names_the_TREE_not_the_database( monkeypatch ):
    """
    "cannot read the tree's head" and "cannot read the database" send an operator to
    two different machines. A single generic "schema check failed" would make them
    guess.
    """
    import cosa.rest.db.auto_migrate as am
    monkeypatch.setattr( am, "build_alembic_config",
                         lambda *a, **kw: ( _ for _ in () ).throw( RuntimeError( "no scripts" ) ) )
    head, current, reason = csah.read_revisions()
    assert ( head, current ) == ( None, None )
    assert "tree's head revision" in reason


def test_an_unreachable_database_names_the_DATABASE( monkeypatch ):
    import cosa.rest.db.auto_migrate as am
    monkeypatch.setattr( am, "resolve_database_url",
                         lambda *a, **kw: ( _ for _ in () ).throw( RuntimeError( "refused" ) ) )
    head, current, reason = csah.read_revisions()
    assert ( head, current ) == ( None, None )
    assert "database's current revision" in reason


def test_a_healthy_read_returns_a_pair_and_no_reason( monkeypatch ):
    """
    CONTROL for the three failure tests above. Each of them asserts that a reason is
    PRESENT; if read_revisions always returned a reason — for any unrelated
    environmental cause — all three would pass while measuring nothing.

    ⚠️ PINNED TO THE TEST VENUE, NOT THE AMBIENT ONE (row `76acde23`).
    `read_revisions()` takes no URL and resolves through the app builder, so with
    `LUPIN_ENV` unset it defaulted to `development` and read **`lupin_db_dev`** —
    the live dev store (`database.py:74`, `:110`). Measured 2026-07-27: this was
    the ONLY test in `src/tests/unit/` doing so.

    Rick's standing rule (decision `2b20a6d6`): *"I absolutely do not want any
    test touching a live dev data store!"*

    The pin follows the pattern `test_metadata_schema_drift.py` already
    establishes — set the venue explicitly and neutralise the overrides that
    could retarget it — so the comparison cannot drift with whatever the
    developer's shell happens to carry. `DATABASE_URL` and `DB_NAME` are cleared
    for the same reason that file clears them: either one silently wins.

    ⚠️ THE CONTROL IS PRESERVED, NOT TRADED AWAY. This still calls the real
    `read_revisions()` on its real healthy path; only the venue moves. Making the
    database unreachable instead would have satisfied a rule that does not apply
    to `lupin_db_test` while destroying the vacuity guard three siblings depend
    on — Mr Radio ruled against exactly that (see the module note below).
    """
    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    monkeypatch.delenv( "DATABASE_URL", raising=False )
    monkeypatch.delenv( "DB_NAME",      raising=False )

    head, _current, reason = csah.read_revisions()
    assert reason is None, f"the healthy path is broken here, so the failure tests prove nothing: {reason}"
    assert head, "no head revision resolved from this tree"


def test_the_healthy_read_does_NOT_target_the_live_dev_store( monkeypatch ):
    """
    Regression lock for the pin above. Asserts the resolved venue under the
    test's own environment is the TEST database, not the dev one.

    CONTROL: the same resolver with `LUPIN_ENV` left at its ambient default must
    name a DIFFERENT database. Without that arm this passes on any builder that
    returns a constant, and would keep passing if the pin were deleted.
    """
    from cosa.rest.db.database import get_database_url

    monkeypatch.delenv( "DATABASE_URL", raising=False )
    monkeypatch.delenv( "DB_NAME",      raising=False )

    monkeypatch.setenv( "LUPIN_ENV", "testing" )
    pinned = get_database_url()

    monkeypatch.setenv( "LUPIN_ENV", "development" )
    ambient = get_database_url()

    assert "lupin_db_test" in pinned, f"the pin does not reach the test venue: {pinned}"
    assert "lupin_db_dev" not in pinned, f"the pinned venue is the LIVE DEV store: {pinned}"
    assert pinned != ambient, (
        "pinned and ambient resolve to the SAME database — the pin asserts nothing"
    )


# ── the bootstrap + the CLI contract ─────────────────────────────────────

def test_the_bootstrap_resolves_a_root_with_and_without_LUPIN_ROOT( monkeypatch ):
    """
    The probe runs INSIDE the container, where the environment is not the dev shell.
    Both paths have to work: LUPIN_ROOT present (compose sets it) and absent (a hand
    `docker exec` in a stripped shell).
    """
    monkeypatch.setenv( "LUPIN_ROOT", "/var/lupin" )
    assert csah._bootstrap_sys_path() == "/var/lupin"

    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    derived = csah._bootstrap_sys_path()
    assert derived and os.path.isdir( os.path.join( derived, "src" ) )


def test_the_probe_prints_a_PARSEABLE_record_and_exits_with_the_outcome():
    """
    preflight parses this stdout with `grep`/`cut`. If the field names or the KEY=VALUE
    shape drift, the check goes quiet rather than failing — the worst direction, since
    a preflight that stops reporting reads exactly like a preflight with nothing to
    report.
    """
    p = subprocess.run( [ "python", PROBE_PATH ], capture_output=True, text=True, timeout=120,
                        env={ **os.environ, "LUPIN_ROOT": cu.get_project_root() } )
    assert p.returncode in ( 0, 1, 2 ), p.stderr
    assert "HEAD_IN_TREE=" in p.stdout
    assert "CURRENT_IN_DB=" in p.stdout
    assert "VERDICT=" in p.stdout


def test_the_probe_reports_DRIFT_against_a_database_stamped_ONE_MIGRATION_BEHIND( tmp_path ):
    """
    ⚠️ THE NEGATIVE CONTROL, RE-ARMED IN THE SUITE. The row required it explicitly:
    a schema check that has only ever seen a matching pair has not been tested.

    A throwaway SQLite file with `alembic_version` written by hand to the head's
    `down_revision` — a database genuinely one migration behind — must FAIL.
    """
    import sqlite3
    from alembic.script import ScriptDirectory
    from cosa.rest.db.auto_migrate import build_alembic_config

    script = ScriptDirectory.from_config( build_alembic_config() )
    head   = script.get_current_head()
    prev   = script.get_revision( head ).down_revision
    if prev is None:
        pytest.skip( "only one migration in the tree — 'one behind' does not exist" )

    db = tmp_path / "behind.db"
    conn = sqlite3.connect( db )
    conn.execute( "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)" )
    conn.execute( "INSERT INTO alembic_version VALUES (?)", ( prev, ) )
    conn.commit(); conn.close()

    p = subprocess.run( [ "python", PROBE_PATH ], capture_output=True, text=True, timeout=120,
                        env={ **os.environ,
                              "LUPIN_ROOT": cu.get_project_root(),
                              "DATABASE_URL": f"sqlite:///{db}" } )
    assert p.returncode == csah.EXIT_DRIFT, f"a DB one migration behind did not FAIL:\n{p.stdout}{p.stderr}"
    assert "VERDICT=DRIFT" in p.stdout
    assert prev in p.stdout and head in p.stdout


def test_main_prints_every_field_and_returns_the_outcome_code( monkeypatch, capsys ):
    """
    `main()` IN-PROCESS. The subprocess tests above exercise it too, but from another
    interpreter — so coverage never sees it and a broken branch inside it could sit
    unmeasured while the file reported high coverage. Measuring the wrong process is
    its own small version of this lane's recurring defect.

    Driven through all three outcomes by injecting the revision read, so the printing
    is asserted independently of whatever the real database happens to be at today.
    """
    for head, current, reason, want_code, want_verdict in (
        ( HEAD, HEAD, None,    csah.EXIT_AT_HEAD,          "AT_HEAD"          ),
        ( HEAD, PREV, None,    csah.EXIT_DRIFT,            "DRIFT"            ),
        ( None, None, "boom",  csah.EXIT_CANNOT_DETERMINE, "CANNOT_DETERMINE" ),
    ):
        monkeypatch.setattr( csah, "read_revisions", lambda h=head, c=current, r=reason: ( h, c, r ) )
        assert csah.main() == want_code
        out = capsys.readouterr().out
        assert f"VERDICT={want_verdict}" in out
        assert "HEAD_IN_TREE=" in out and "CURRENT_IN_DB=" in out


def test_main_emits_EMPTY_not_the_word_None_for_an_unknown_revision( monkeypatch, capsys ):
    """
    preflight `cut -d= -f2-`s these fields. A literal "None" would parse as a revision
    string and could be compared, displayed, or logged as though it were one — a
    plausible-looking value standing in for an absent one.
    """
    monkeypatch.setattr( csah, "read_revisions", lambda: ( None, None, "unreachable" ) )
    csah.main()
    out = capsys.readouterr().out
    assert "HEAD_IN_TREE=\n"  in out
    assert "CURRENT_IN_DB=\n" in out
    assert "None" not in out.split( "DETAIL=" )[ 0 ]


def test_the_injected_DATABASE_URL_ACTUALLY_drives_the_verdict( tmp_path ):
    """
    CONTROL for the test above. If `DATABASE_URL` were ignored, that test would read
    the real database, and its DRIFT assertion would fail loudly — but only by luck of
    the real DB being at head. Make the dependence explicit: the SAME injection
    mechanism, pointed at a database stamped AT head, must produce the OPPOSITE
    verdict. One variable changed, opposite outcomes.
    """
    import sqlite3
    from alembic.script import ScriptDirectory
    from cosa.rest.db.auto_migrate import build_alembic_config

    head = ScriptDirectory.from_config( build_alembic_config() ).get_current_head()
    db   = tmp_path / "athead.db"
    conn = sqlite3.connect( db )
    conn.execute( "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)" )
    conn.execute( "INSERT INTO alembic_version VALUES (?)", ( head, ) )
    conn.commit(); conn.close()

    p = subprocess.run( [ "python", PROBE_PATH ], capture_output=True, text=True, timeout=120,
                        env={ **os.environ,
                              "LUPIN_ROOT": cu.get_project_root(),
                              "DATABASE_URL": f"sqlite:///{db}" } )
    assert p.returncode == csah.EXIT_AT_HEAD, (
        "the injected URL did not drive the verdict ⇒ the drift test above is vacuous"
    )
