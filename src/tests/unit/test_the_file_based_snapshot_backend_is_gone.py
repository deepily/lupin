"""Row 7a20a09d — the file-based snapshot backend is gone, and cannot come back quietly.

WHAT WENT AND WHY IT WENT. Rick ruled on 2026-08-21 (decision 6791ce47) that
`SolutionSnapshotManager`, `FileBasedSolutionManager` and the factory's `file_based` branch
be deleted once v2 landed. Unreachability was not the reason — `main.py` had already refused
to start on any backend but Postgres for some time. The reason is that they were a TRAP.

Three classes carried a `save_snapshot` method. A grep for `def save_snapshot` found the
DEPRECATED file-based one first, in the most obviously-named file
(`solution_snapshot_mgr.py`), whose docstring said it saved to files. A reviewer read that,
believed it, and raised a false alarm that the queue was writing to files while the brain
read Postgres — the write-back reuse ruling nearly came apart on it. Two of the three
classes could not be built at all; only the third could, and it was the last one found.

WHY A TEST AND NOT JUST A DELETE. Nothing stops the modules being re-added — by a revert, by
a merge that resurrects a branch, or by somebody who reads the old plan documents (which
still describe the file-based backend as a live option) and helpfully "restores" it. The
sweep below makes the absence a property rather than a fact about one afternoon.

⚠️ WHAT THE SWEEP CANNOT CLAIM: it checks the tree, not a running process. A module imported
dynamically by name assembled at runtime would slip past it — which is why the second half
drives the FACTORY and asserts the backend cannot be built, whatever the tree says.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import os
import re

import pytest

from cosa.memory.solution_manager_factory import ManagerType, SolutionSnapshotManagerFactory


# The modules deleted with the backend. Named rather than globbed: a glob would quietly stop
# covering a file whose name changed, and report the same green.
_DELETED_MODULES = (
    "cosa.memory.solution_snapshot_mgr",
    "cosa.memory.file_based_solution_manager",
)
_DELETED_CLASSES = ( "SolutionSnapshotManager", "FileBasedSolutionManager" )

_DELETED_FILES = (
    os.path.join( "src", "cosa", "memory", "solution_snapshot_mgr.py" ),
    os.path.join( "src", "cosa", "memory", "file_based_solution_manager.py" ),
    os.path.join( "src", "scripts", "baseline_solution_snapshot_performance.py" ),
)


def _repo_root():
    here = os.path.dirname( os.path.abspath( __file__ ) )
    return os.path.dirname( os.path.dirname( os.path.dirname( here ) ) )


def _python_sources( root=None ):
    """Every .py under `root`/src, scratch and vendored trees excluded.

    `root` is a parameter rather than a constant so the control below can sweep a planted
    fake tree with THIS function — a control that reimplemented the walk would prove its own
    copy works and say nothing about the one that runs.
    """
    root = _repo_root() if root is None else root
    for dirpath, dirnames, filenames in os.walk( os.path.join( root, "src" ) ):
        dirnames[ : ] = [ d for d in dirnames
                          if d not in ( "__pycache__", "tmp", ".git", "node_modules", ".venv" ) ]
        for name in filenames:
            if name.endswith( ".py" ):
                full = os.path.join( dirpath, name )
                yield os.path.relpath( full, root ), full


# WHAT COUNTS AS A REFERENCE, and it is narrower than "the name appears".
#
# Two lessons are baked in here. First, `SolutionSnapshotManagerInterface` and
# `SolutionSnapshotManagerFactory` are both alive and correct, and both CONTAIN the deleted
# class's name — a plain substring sweep accused eleven innocent files on its first run.
# Word boundaries fixed that. Second, even with boundaries it then accused four files that
# merely MENTION the class in a docstring or comment, which is prose about history, not a
# dependency. (Those four were reworded in the same commit, because prose naming a deleted
# class is its own small trap — but the sweep must not be what polices prose, or the next
# person to write an accurate historical note will be told they broke the build.)
#
# So the sweep looks for USE: an import statement, a dynamic import by module string, or a
# construction. That is exactly the failure row 7a20a09d names — "re-adding an import of the
# deleted class is caught".
_FORBIDDEN = (
    re.compile( r"^\s*import\s+cosa\.memory\.(solution_snapshot_mgr|file_based_solution_manager)\b",
                re.MULTILINE ),
    re.compile( r"^\s*from\s+cosa\.memory\.(solution_snapshot_mgr|file_based_solution_manager)\s+import",
                re.MULTILINE ),
    re.compile( r"[\"']cosa\.memory\.(solution_snapshot_mgr|file_based_solution_manager)[\"']" ),
    re.compile( r"\b(SolutionSnapshotManager|FileBasedSolutionManager)\s*\(" ),
)


def _sweep( root, skip=None ):
    """{ relative_path: [ what it names ] } for every file that references the deleted backend."""
    offenders = {}
    for relative_path, full in _python_sources( root ):
        if skip is not None and relative_path == skip:
            continue
        with open( full, errors="ignore" ) as fh:
            code = "\n".join( line for line in fh.read().splitlines()
                              if not line.strip().startswith( "#" ) )
        hit = [ pattern.search( code ).group( 0 ).strip() for pattern in _FORBIDDEN
                if pattern.search( code ) ]
        if hit:
            offenders[ relative_path ] = hit
    return offenders


@pytest.mark.parametrize( "relative_path", _DELETED_FILES )
def test_the_deleted_files_are_actually_gone( relative_path ):
    """
    THE FLOOR. Everything else here is about references; this is about the files. Without it
    a revert that restored the modules but left every caller alone would pass the sweep
    below — nothing would IMPORT them, and the trap would be back on disk exactly as before.
    """
    assert not os.path.exists( os.path.join( _repo_root(), relative_path ) ), (
        f"{relative_path} is back. It was deleted on 2026-08-21 (ruling 6791ce47) because a "
        f"grep for `def save_snapshot` finds it before the class the app actually builds."
    )


def test_no_module_imports_the_deleted_backend():
    """
    THE SWEEP. Nothing in the tree imports either deleted module, or names either deleted
    class — tests included, because a test that imports a module which no longer exists is a
    collection error, not a failure, and collection errors get triaged as rig problems.

    RED ON REVERT: add `from cosa.memory.file_based_solution_manager import
    FileBasedSolutionManager` anywhere under src/ and this names the file.
    """
    offenders = _sweep( _repo_root(), skip=os.path.relpath( os.path.abspath( __file__ ), _repo_root() ) )
    assert not offenders, (
        f"the deleted file-based snapshot backend is referenced again: {offenders}. If it is "
        f"genuinely needed, that is a decision to reopen with Rick (6791ce47), not a module "
        f"to restore quietly — the reason it went was that it MISLEADS readers, and it will "
        f"mislead them again."
    )


def test_the_factory_cannot_build_the_retired_backend():
    """
    THE HALF THE SWEEP CANNOT COVER. A static sweep reads the tree; this drives the factory.
    `file_based` is refused at the enum, so it fails the same way whether the module is
    absent, present-but-unimported, or resurrected under another name.

    This matters more than it looks: `main.py` still reads `file_based` as its DEFAULT when
    the config key is unset, so an unconfigured box arrives here. It must be refused rather
    than silently building a manager whose class is gone.

    RED ON REVERT: put FILE_BASED back on the enum.
    """
    with pytest.raises( ValueError ):
        ManagerType.from_string( "file_based" )

    with pytest.raises( ValueError ):
        SolutionSnapshotManagerFactory.create_manager( "file_based", { "path": "/anywhere" } )

    assert set( SolutionSnapshotManagerFactory.get_available_types() ) == { "postgres" }, (
        "the factory offers a backend other than postgres"
    )


def test_the_sweep_can_actually_fail( tmp_path ):
    """
    THE CONTROL. "Nothing was found" and "nothing was looked at" produce the same green, and
    this sweep walks a directory tree — the easiest thing in the world to point at the wrong
    place and never notice.

    It runs the REAL `_sweep` against a planted tree rather than reimplementing the walk: a
    control with its own copy of the logic proves the copy works and says nothing about the
    function that actually runs.
    """
    planted = tmp_path / "src" / "somewhere"
    planted.mkdir( parents=True )
    ( planted / "revived.py" ).write_text(
        "from cosa.memory.file_based_solution_manager import FileBasedSolutionManager\n"
    )
    ( planted / "innocent.py" ).write_text(
        "from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory\n"
    )

    offenders = _sweep( str( tmp_path ) )

    assert os.path.join( "src", "somewhere", "revived.py" ) in offenders, (
        f"the sweep missed a planted import of the deleted backend: {offenders}"
    )
    assert os.path.join( "src", "somewhere", "innocent.py" ) not in offenders, (
        f"the sweep accused the live factory, whose name merely CONTAINS the deleted one: "
        f"{offenders}"
    )


def test_the_splainer_does_not_offer_the_retired_backend():
    """
    THE OPERATOR-FACING HALF. The sweep above reads code; this reads the text a human reads
    BEFORE setting the key. Four docstrings were corrected when the backend was deleted and
    this line was missed, so it still told an operator that 'file_based' was selectable and
    was the Default — advice that now produces a ValueError at startup.

    It is deliberately NOT a ban on the string: the line is allowed — encouraged — to name
    'file_based' in order to say it is REFUSED. What it must never do again is present it as
    a choosable value or as the default.

    RED ON REVERT: restore "or 'file_based' (JSON files)" or "Default: file_based".
    """
    splainer = os.path.join( _repo_root(), "src", "conf", "lupin-app-splainer.ini" )
    with open( splainer ) as fh:
        line = [ ln for ln in fh if ln.startswith( "solution snapshots manager type" ) ]

    assert len( line ) == 1, f"expected exactly one splainer line for the key, found {len( line )}"
    line = line[ 0 ]

    assert "Default: postgres" in line, (
        "the splainer no longer advertises postgres as the default for "
        "'solution snapshots manager type'"
    )
    assert "Default: file_based" not in line, (
        "the splainer advertises the deleted file_based backend as the DEFAULT"
    )
    assert "or 'file_based'" not in line, (
        "the splainer offers 'file_based' as a selectable value alongside postgres"
    )
    assert "ONLY legal value" in line, (
        "the splainer no longer states that postgres is the only legal value"
    )


def test_main_does_not_default_to_the_retired_backend():
    """
    THE UNCONFIGURED-BOX PATH. `main.py` reads the key with a default, and that default was
    still the deleted name — so a box whose INI omits the key asked the factory for a backend
    whose classes are gone and died on a ValueError instead of doing the sane thing.

    Dead in practice (lupin-app.ini sets postgres at :15 and :473), which is exactly why no
    tier caught it. Asserted here rather than trusted to the config file.

    RED ON REVERT: put default="file_based" back at main.py:680.
    """
    main_py = os.path.join( _repo_root(), "src", "lupin_app", "main.py" )
    with open( main_py ) as fh:
        src = fh.read()

    assert 'config_mgr.get( "solution snapshots manager type", default="postgres" )' in src, (
        "main.py no longer defaults the snapshot-manager key to postgres"
    )
    assert 'default="file_based"' not in src, (
        "main.py still defaults some key to the deleted file_based backend"
    )
