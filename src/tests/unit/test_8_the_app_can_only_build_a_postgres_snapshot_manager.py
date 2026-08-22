"""Step 8 — the app refuses to start on any snapshot backend but Postgres.

WHY STEP 8 IS A GUARD AND NOT A BUILD. The step is "write-back per Rick's ruling — reuse
the path that already exists", and measured on the branch there was nothing left to
build. Its other two properties were already in place AND already pinned:

  * a non-`done` outcome is never written back — `test_v2_flow.py:1150`;
  * the two exclusion lists agree — `resolve()` returns `snapshotable=False` on the CRUD
    fork (`registry.py:358`), pinned red by `test_registry_voice_binding.py:142`. That
    closes the mismatch the plan flagged, where the registry claimed a command was
    cacheable about a class the queue refuses to serialize.

ONE LINK HAD NOTHING CHECKING IT. The reuse ruling is only safe because the queue's write
and the brain's read reach the SAME store, and what makes that true is `main.py` refusing
to build anything but the Postgres manager. That refusal was verified by reading the
source during the cascade review — never by a test — and the plan records how easily that
same reading goes wrong: THREE classes carry a `save_snapshot` method, and a grep for it
finds the DEPRECATED file-based one first, whose docstring says it saves to files. The
reviewer read that docstring, believed it, and raised a false alarm that the queue and the
brain were writing to different places. The refusal in `main.py` is what makes the right
answer the only possible one.

WHY A STATIC CHECK, AND WHAT IT CANNOT CLAIM. The refusal lives inline in `lifespan`,
which cannot be driven without booting the app. So this reads the code — but it reads it
as a PARSE TREE, not as text: it finds the `if manager_type.lower() == "postgres"`
statement and asserts its `else` raises. A substring search would pass on a build where
the raise had been commented out and the words merely survived — the failure Pocholo
demonstrated on 290f6831's third falsifier, where a literal-string assertion stayed green
while the guard under it was gutted. The last test here proves the checker can actually
fail, which is what stops "nothing was found" and "nothing was looked at" producing the
same green.

Stated plainly so nobody over-reads it: this pins the SHAPE of the refusal, not that a
running server rejects a bad value. The end-to-end claim would need a boot.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import ast
import configparser
import os

import pytest


def _repo_root():
    """The checkout this test file lives in — three levels up from src/tests/unit."""
    here = os.path.dirname( os.path.abspath( __file__ ) )
    return os.path.dirname( os.path.dirname( os.path.dirname( here ) ) )


def _main_source():
    with open( os.path.join( _repo_root(), "src", "lupin_app", "main.py" ), errors="ignore" ) as fh:
        return fh.read()


def _postgres_branch( source ):
    """The `if manager_type.lower() == "postgres":` statement, or None.

    Matched on the SHAPE of the test — a call to `.lower()` on `manager_type` compared
    against the literal "postgres" — rather than on the text of the line, so reformatting
    it, renaming nothing, or moving it does not break the check.
    """
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, ast.If ) or not isinstance( node.test, ast.Compare ):
            continue
        left = node.test.left
        if not ( isinstance( left, ast.Call ) and isinstance( left.func, ast.Attribute )
                 and left.func.attr == "lower" ):
            continue
        if not ( isinstance( left.func.value, ast.Name ) and left.func.value.id == "manager_type" ):
            continue
        comparators = node.test.comparators
        if len( comparators ) == 1 and getattr( comparators[ 0 ], "value", None ) == "postgres":
            return node
    return None


def _else_raises( branch ):
    """Whether the branch's `else` arm reaches a `raise` — the refusal itself."""
    return any( isinstance( node, ast.Raise ) for stmt in branch.orelse for node in ast.walk( stmt ) )


def test_any_snapshot_backend_but_postgres_is_refused_at_startup():
    """
    THE REFUSAL. `main.py` builds the Postgres manager or raises; there is no third path,
    and no silent fallback to the deprecated file-based backend.

    This is what makes the write-back reuse ruling safe: one store, so a snapshot the
    queue saves at completion is a snapshot the brain's cache can read back.

    RED ON REVERT: restore the commented-out file-based arm — or replace the raise with a
    default, a warning, or a pass — and the `else` stops raising, which is exactly the
    change that would silently split the write and the read across two stores.
    """
    branch = _postgres_branch( _main_source() )
    assert branch is not None, (
        "main.py no longer selects the snapshot manager with an `if manager_type.lower() "
        "== 'postgres'` test. If the selection moved, move this guard with it — do not "
        "delete it: it is the only thing asserting the queue and the brain share a store."
    )
    assert _else_raises( branch ), (
        "the non-postgres arm of main.py's snapshot-manager selection no longer raises. "
        "Anything but a refusal there means the app can boot on a second backend, and the "
        "queue's completion write would stop being visible to the brain's cache."
    )


def test_the_shipped_config_asks_for_the_backend_the_app_accepts():
    """
    THE OTHER HALF, and it is the one that actually bit before. A refusal at startup only
    protects a box whose config asks for something legal; the record in the code says the
    else-arm once rejected every value but "lancedb", which would have failed the server
    on its next bounce and was latent only because reload was off.

    So: every section of the shipped INI that names a snapshot-manager type names one the
    app will accept.

    RED ON REVERT: set any section back to `file_based` and this names the section.
    """
    parser = configparser.ConfigParser()
    parser.read( os.path.join( _repo_root(), "src", "conf", "lupin-app.ini" ) )

    key    = "solution snapshots manager type"
    stated = { name: parser[ name ][ key ] for name in parser.sections() if key in parser[ name ] }

    assert stated, (
        f"no section of lupin-app.ini sets {key!r} any more. The default in main.py is "
        f"'file_based', which the app refuses — so an unset key is a server that will not boot."
    )
    wrong = { name: value for name, value in stated.items() if value.strip().lower() != "postgres" }
    assert not wrong, (
        f"these sections ask for a snapshot backend the app refuses to build: {wrong}. "
        f"The server would raise at startup on its next bounce."
    )


@pytest.mark.parametrize( "mutation, why", [
    (
        'if manager_type.lower() == "postgres":\n    config = {}\nelse:\n    config = {}\n',
        "the else arm silently falls back instead of refusing",
    ),
    (
        'if manager_type.lower() == "postgres":\n    config = {}\nelse:\n    pass\n',
        "the else arm does nothing at all",
    ),
    (
        'if manager_type.lower() == "postgres":\n    config = {}\n',
        "there is no else arm — every other value falls straight through",
    ),
] )
def test_the_check_can_actually_fail( mutation, why ):
    """
    THE CONTROL. A guard that has never been seen to fail is an untested assertion about
    an untested assertion — and a check that silently stops finding the branch would
    report the same green as one that found it and was satisfied.

    Each case is a source that SHOULD be rejected. If any of them passes, the check above
    is not checking what its name says.
    """
    branch = _postgres_branch( mutation )
    assert branch is not None, "the fixture no longer parses as the selection branch"
    assert not _else_raises( branch ), f"the check accepted a build where {why}"


def test_the_check_accepts_a_refusal_it_should_accept():
    """
    THE OTHER HALF OF THE CONTROL: a check that rejected everything would also make the
    first test's failure meaningless. This is the shape that must pass.
    """
    accepted = ( 'if manager_type.lower() == "postgres":\n'
                 '    config = {}\n'
                 'else:\n'
                 '    raise ValueError( "the only supported value is \'postgres\'" )\n' )
    branch = _postgres_branch( accepted )
    assert branch is not None and _else_raises( branch ), (
        "the check rejects a genuine refusal — it would fail on correct code"
    )
