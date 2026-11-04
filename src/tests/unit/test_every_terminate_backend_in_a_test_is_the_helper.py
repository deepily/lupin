"""
No test file ends database sessions with its own unfiltered terminate statement.

The helper in tests/helpers/template_database.py owns the statement that closes sessions on a scratch
database. Run as the restricted test login, an unfiltered copy is refused by Postgres. One superuser
session on the database is enough, and the drop behind the statement then fails. Twelve test files carried such a copy
when this guard was written; the helper fixed the statement once, so a copy keeps the old defect.

This guard counts the tracked files under src/tests that name pg_terminate_backend outside the helper. A file may
appear only in the allowlist below, with the count it holds. The allowlist is a debt list and it is empty,
because every file now calls the helper.

Venue: :7999 (unit tier). Reads tracked files only.
"""

import subprocess

import cosa.utils.util as cu

NEEDLE  = "pg_terminate_backend"
HELPER  = "src/tests/helpers/template_database.py"
# The smoke file below holds the unfiltered text on purpose, as the control arm that proves the refusal.
EXEMPT_FILES = {
    HELPER,
    "src/tests/smoke/test_scratch_database_terminate_real_postgres.py",
    "src/tests/unit/test_template_database_helper.py",
    "src/tests/unit/test_every_terminate_backend_in_a_test_is_the_helper.py",
}
# path : number of lines naming the needle. Empty now; an entry is a debt and the list must stay empty.
ALLOWED = { }


def _tracked_test_files():
    root = cu.get_project_root()
    out  = subprocess.run( [ "git", "ls-files", "src/tests" ], cwd=root, capture_output=True, text=True, check=True ).stdout
    return root, [ p for p in out.splitlines() if p.endswith( ".py" ) ]


def _holders():
    """Return path to line count for each tracked test file that names the needle."""
    root, paths = _tracked_test_files()
    assert paths, "the file listing found no test files, so the census below would pass on nothing"
    found = { }
    for path in paths:
        if path in EXEMPT_FILES: continue
        with open( f"{root}/{path}", encoding="utf-8" ) as f:
            count = sum( 1 for line in f if NEEDLE in line )
        if count: found[ path ] = count
    return found


def test_the_instrument_sees_the_helper_and_the_exempt_files():
    root, paths = _tracked_test_files()
    for path in EXEMPT_FILES:
        assert path in paths, f"{path} is not a tracked test file, so the exemption names nothing"
        with open( f"{root}/{path}", encoding="utf-8" ) as f:
            assert NEEDLE in f.read(), f"{path} no longer names {NEEDLE}, so the exemption is stale"


def test_no_unfiltered_terminate_backend_in_test_teardowns():
    found = _holders()
    new   = { p: c for p, c in found.items() if p not in ALLOWED }
    grown = { p: ( ALLOWED[ p ], c ) for p, c in found.items() if p in ALLOWED and c != ALLOWED[ p ] }
    assert not new, f"a test names {NEEDLE} outside the helper; call td.terminate_sessions_sql instead: {sorted( new )}"
    assert not grown, f"a debt-list file changed its count (allowed, found); lower the entry when it is cleaned: {grown}"


def test_the_debt_list_holds_only_files_that_still_carry_the_copy():
    stale = sorted( set( ALLOWED ) - set( _holders() ) )
    assert not stale, f"these files no longer name {NEEDLE}; delete their entries: {stale}"
