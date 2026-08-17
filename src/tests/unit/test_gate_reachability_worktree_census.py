"""
The reachability census must not exclude itself when the project lives under an
excluded directory name.

Found 2026-08-17 by Clayton 😎 (bug 5e6e0680) while running the full unit sweep
from a git worktree. `.claude` is an EXCLUDED_PATH_PARTS component, and a
worktree lives at `<repo>/.claude/worktrees/<name>` — so every ABSOLUTE path
inside one contained `.claude`, and the census excluded every file it found.

Measured: 1,319 test files from the main checkout, ZERO from a worktree.
`find_unreferenced_test_files` then returned an empty list there, so the gate
reported perfectly clean in exactly the place new work is written.

The exclusions are about where a file sits WITHIN the project. Asking that
question of the absolute path lets the project's own location answer it.
"""

from pathlib import Path

from cosa.repo.gate_reachability import EXCLUDED_PATH_PARTS, find_test_file_population


def _make_project( root, extra_dirs=() ):
    """Build a minimal project tree with one reachable test file."""
    tests = root / "src" / "tests" / "unit"
    tests.mkdir( parents=True )
    ( tests / "test_example.py" ).write_text( "def test_x(): pass\n" )
    for name in extra_dirs:
        junk = root / "src" / name / "sub"
        junk.mkdir( parents=True )
        ( junk / "test_ignored.py" ).write_text( "def test_y(): pass\n" )
    return root


def test_census_finds_files_when_the_project_sits_under_an_excluded_name( tmp_path ):
    # The regression, stated as the shape that broke it: the project ROOT itself
    # is nested under a directory whose name is on the exclusion list.
    root = _make_project( tmp_path / ".claude" / "worktrees" / "wt-a" )

    population = find_test_file_population( root )

    assert "src/tests/unit/test_example.py" in population
    assert population, "the census excluded itself because of where the project lives"


def test_the_same_project_elsewhere_gives_the_same_answer( tmp_path ):
    # Location must not change the census. Two identical trees, one nested under
    # an excluded name — the results must match exactly.
    nested = _make_project( tmp_path / ".claude" / "worktrees" / "wt-b" )
    plain  = _make_project( tmp_path / "plain" )

    assert find_test_file_population( nested ) == find_test_file_population( plain )


def test_exclusions_still_apply_INSIDE_the_project( tmp_path ):
    # The fix must not win by excluding nothing. A `.venv` or `__pycache__`
    # WITHIN the project is still excluded.
    root = _make_project( tmp_path / "proj", extra_dirs=( ".venv", "__pycache__", "node_modules" ) )

    population = find_test_file_population( root )

    assert "src/tests/unit/test_example.py" in population
    for name in ( ".venv", "__pycache__", "node_modules" ):
        assert not any( name in path for path in population ), f"{name} leaked into the census"


def test_every_excluded_part_is_still_honored_inside_the_project( tmp_path ):
    # Asserted against the real constant, so adding an exclusion cannot silently
    # go unenforced.
    root = _make_project( tmp_path / "proj2", extra_dirs=EXCLUDED_PATH_PARTS )

    population = find_test_file_population( root )

    assert "src/tests/unit/test_example.py" in population
    for part in EXCLUDED_PATH_PARTS:
        assert not any( f"/{part}/" in f"/{path}" for path in population ), f"{part} not excluded"
