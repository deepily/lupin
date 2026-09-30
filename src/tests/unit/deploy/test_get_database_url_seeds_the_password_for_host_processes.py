"""
Row 19c30893. The postgres password left the tree on row baac2474 (commit 765e7145,
2026-08-31). That commit gave TWO of three consumers a route to the untracked .env —
containers via docker-compose, pytest via a seeder in src/conftest.py — and missed the
third: HOST-RUN PROCESSES, which are neither.

The CC notification listener is one. From 2026-08-31 23:58 to 2026-09-05 it raised
"fe_sendauth: no password supplied" on every gist it attempted, 166 times in five days,
and emitted a five-word prefix of the user's own text instead. That reads in the UI as a
short paraphrase, so it stayed invisible for five days while being logged loudly.

🔴 WHY THIS FILE ENTERS AT get_database_url() AND NOT AT THE SEEDER.
There is already a guard on the seeder itself (test_db_password_seeded_from_dotenv.py,
8 tests). It passed throughout the outage and would pass again if this fix were reverted,
because the seeder was never broken — it was simply unreachable from anything but pytest.
A helper-level receipt and a path-level receipt are different claims, and only the second
is about this incident. The incident entered at a process building a database URL with a
blank DB_PASSWORD, so these tests enter there.

🔴 TWO CASES MARÍA 🌸 MADE REQUIREMENTS (2026-09-05), because both PASS a naive unit rung
and FAIL in production — see the last two tests:
  · WHICH ROOT the seeder resolves .env from. A worktree has no .env by standing ruling,
    so a resolve that stops at the worktree misses every listener running from one.
  · BLANK VS ABSENT. An exported-but-EMPTY DB_PASSWORD must be treated as absent, or the
    seed is skipped and the process lands back on fe_sendauth.

⚠️ Every case below uses a DISTINCTIVE dummy value, and the .env value DIFFERS from the
exported one, so an implementation that ignored its input or preferred the wrong source
would produce a DIFFERENT observation rather than the same one.
"""

import importlib
import os

import pytest


DOTENV_VALUE   = "dotenv-pw-19c30893"
EXPORTED_VALUE = "exported-pw-19c30893"


def _write_env( directory, value ):
    with open( os.path.join( directory, ".env" ), "w" ) as fh:
        fh.write( f"JWT_SECRET_KEY=irrelevant\nPOSTGRES_PASSWORD={value}\n" )


@pytest.fixture
def database_module( monkeypatch ):
    """Hand back the URL builder with the environment under the test's control."""
    monkeypatch.setenv( "LUPIN_ENV", "development" )
    monkeypatch.delenv( "LUPIN_CLOUD_BACKED", raising=False )

    import cosa.rest.db.database as database
    return database


def _seed_from( root ):
    """The real seeder, pointed at a throwaway root instead of the repo's own .env."""
    real = importlib.import_module( "cosa.utils.dotenv_password" ).seed_db_password_from_dotenv
    return lambda _root=None: real( root=str( root ) )


def test_a_host_process_with_no_db_password_still_gets_one_into_the_url( database_module, tmp_path, monkeypatch ):
    """
    THE INCIDENT. A process with a blank DB_PASSWORD must not build the URL that
    produced "fe_sendauth: no password supplied" for five days.
    """
    _write_env( str( tmp_path ), DOTENV_VALUE )
    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    monkeypatch.setattr( database_module, "seed_db_password_from_dotenv", _seed_from( tmp_path ) )

    url = database_module.get_database_url()

    assert DOTENV_VALUE in url, f"the .env password never reached the URL: {url!r}"
    assert ":@" not in url, f"blank-password URL — this is the shape that raises fe_sendauth: {url!r}"


def test_an_exported_password_still_wins_over_the_dotenv( database_module, tmp_path, monkeypatch ):
    """
    THE NEGATIVE CONTROL, and it is not optional. A fix that ALWAYS read the .env would
    satisfy the test above and would silently override the value a container is given at
    create time. The two values differ, so preferring the wrong source is observable.
    """
    _write_env( str( tmp_path ), DOTENV_VALUE )
    monkeypatch.setenv( "DB_PASSWORD", EXPORTED_VALUE )
    monkeypatch.setattr( database_module, "seed_db_password_from_dotenv", _seed_from( tmp_path ) )

    url = database_module.get_database_url()

    assert EXPORTED_VALUE in url, f"the exported password lost to the .env: {url!r}"
    assert DOTENV_VALUE not in url, f"the .env overrode an exported value: {url!r}"


def test_the_url_builder_actually_calls_the_seeder( database_module, monkeypatch ):
    """
    THE WIRING. The two cases above would also pass if the seeder ran once at module
    import — and an import-time call is dead for any consumer that imports the module
    before the .env is reachable. This asserts the call site itself, so deleting it from
    get_database_url() is visible rather than silent.
    """
    calls = []
    monkeypatch.setenv( "DB_PASSWORD", EXPORTED_VALUE )
    monkeypatch.setattr( database_module, "seed_db_password_from_dotenv", lambda root=None: calls.append( root ) )

    database_module.get_database_url()

    assert calls, "get_database_url() did not call seed_db_password_from_dotenv()"


def test_an_exported_but_EMPTY_db_password_is_treated_as_absent( database_module, tmp_path, monkeypatch ):
    """
    MARÍA'S REQUIREMENT 2 — BLANK VS ABSENT.

    `DB_PASSWORD=""` is what a launcher that exports an unset variable produces, and it
    is exactly the state get_database_url()'s own `os.environ.get( "DB_PASSWORD", "" )`
    default lands on. A seeder guarded with `"DB_PASSWORD" in os.environ` would treat it
    as provisioned, skip the seed, and hand back the blank-password URL that raises
    fe_sendauth — a fix that passes every other test in this file and changes nothing in
    production.
    """
    _write_env( str( tmp_path ), DOTENV_VALUE )
    monkeypatch.setenv( "DB_PASSWORD", "" )
    monkeypatch.setattr( database_module, "seed_db_password_from_dotenv", _seed_from( tmp_path ) )

    url = database_module.get_database_url()

    assert DOTENV_VALUE in url, f"an empty exported DB_PASSWORD blocked the seed: {url!r}"
    assert ":@" not in url, f"blank-password URL survived: {url!r}"


def test_a_listener_running_from_a_WORKTREE_reaches_the_main_checkouts_dotenv( database_module, tmp_path, monkeypatch ):
    """
    MARÍA'S REQUIREMENT 1 — WHICH ROOT.

    A worktree has NO .env: it is untracked and gitignored, so it exists only in the main
    checkout, and CLAUDE.md forbids symlinking one in. Most of this fleet's seats run from
    worktrees, so a resolve that stops at the tree it is standing in passes in the main
    checkout and misses every worktree listener — green here, fe_sendauth there.

    A worktree's `.git` is a FILE reading "gitdir: <main>/.git/worktrees/<name>". This
    builds that exact layout, puts the .env ONLY in the main checkout, and asserts the
    seeder walks across.
    """
    main     = tmp_path / "main-checkout"
    worktree = tmp_path / "some-worktree"
    ( main / ".git" / "worktrees" / "some-worktree" ).mkdir( parents=True )
    worktree.mkdir()

    _write_env( str( main ), DOTENV_VALUE )                       # ONLY the main checkout has it
    assert not ( worktree / ".env" ).exists(), "fixture bug: the worktree must have no .env"

    with open( worktree / ".git", "w" ) as fh:
        fh.write( f"gitdir: {main}/.git/worktrees/some-worktree\n" )

    monkeypatch.delenv( "DB_PASSWORD", raising=False )
    monkeypatch.setattr( database_module, "seed_db_password_from_dotenv", _seed_from( worktree ) )

    url = database_module.get_database_url()

    assert DOTENV_VALUE in url, f"a worktree never reached the main checkout's .env: {url!r}"
    assert ":@" not in url, f"blank-password URL from a worktree: {url!r}"


def test_the_seeder_is_importable_outside_the_test_tree():
    """
    THE REACHABILITY, which is the whole defect in one line. While the seeder lived in
    src/conftest.py it was a pytest plugin loaded by path — reachable by the test tree and
    by nothing else. A host process cannot import a conftest.
    """
    from cosa.utils.dotenv_password import seed_db_password_from_dotenv

    assert callable( seed_db_password_from_dotenv )
