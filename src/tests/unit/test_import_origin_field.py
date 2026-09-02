"""
Guard — the run says which CHECKOUT its code was imported from, and names a split as a split.

WHY THIS EXISTS. `[tree-state]` reports the git state of the directory you are standing in and
knows nothing about what Python loaded. Measured 2026-09-01 (Rio ⚡, CLAUDE.md § A TIER RUN
FROM A WORKTREE…): a run pinned on `LUPIN_ROOT` but not `PYTHONPATH` assembles `lupin_app.*`
from the worktree and `cosa.*` from the main repo, and two guards written for a real defect
reported `6 passed` against a mutation that was never loaded. Nothing in the output said so.

⚠️ THE SPLIT IS THE FINDING. The first cut of the module checked `cosa` alone against
`LUPIN_ROOT`; Rio caught that this sees a symptom rather than the disease. Two modules that
agree with each other are a coherent tree — wrong, perhaps, but honest. Two that disagree are
an application assembled from two checkouts, and only that can produce a green about code that
exists in neither. The two get different words, and these tests pin that they do.

Venue: :7999-eligible — pure functions over injected fakes, no network, no mutation. One arm
does spawn a short pytest subprocess to read the real line; it stays well inside two minutes.
"""
import os
import sys

from cosa.utils.import_origin import import_origin_field


class _Mod:
    """A stand-in with a `__file__`, so every arm is drivable without touching real imports."""
    def __init__( self, path ): self.__file__ = path


WT   = "/repos/lupin-wt-rio"
MAIN = "/repos/lupin"

# The real depths: cosa/utils/x.py is 2 below src; lupin_app/main.py is 1.
def _cosa( root ):      return ( "cosa",      _Mod( f"{root}/src/cosa/utils/import_origin.py" ), 2 )
def _lupin_app( root ): return ( "lupin_app", _Mod( f"{root}/src/lupin_app/main.py" ),           1 )


def test_the_measured_split_is_reported_as_a_split_and_names_both_checkouts():
    """
    THE ARM THAT MATTERS — Rio's measurement, in the shape it actually occurred: `lupin_app`
    from the worktree, `cosa` from the main repo. A field that called this merely "foreign"
    would let the reader think they had the wrong tree, when they have no single tree at all.
    """
    field = import_origin_field( [ _lupin_app( WT ), _cosa( MAIN ) ], WT )
    assert "SPLIT ACROSS 2 CHECKOUTS" in field
    assert f"lupin_app <- {WT}/src" in field, "the reader must be told WHICH module came from where"
    assert f"cosa <- {MAIN}/src" in field
    assert "exists in no single tree" in field


def test_a_coherent_foreign_tree_is_not_called_a_split():
    """
    Both modules agree with each other and disagree with `LUPIN_ROOT`. That is a real,
    self-consistent checkout — the wrong one, but an honest result. Collapsing it into the
    split wording would put two different severities under one alarm.
    """
    field = import_origin_field( [ _lupin_app( MAIN ), _cosa( MAIN ) ], WT )
    assert "SPLIT" not in field
    assert "coherent but NOT $LUPIN_ROOT" in field
    assert f"{MAIN}/src" in field, "the foreign path is the whole finding — it must be named"


def test_the_agreeing_case_is_stated_rather_than_left_silent():
    """
    A field that appears only when something is wrong is indistinguishable from a field that
    was never computed — the rule `tree_state._run_span` follows when it prints `unmoved`.
    """
    assert import_origin_field( [ _lupin_app( WT ), _cosa( WT ) ], WT ) == "imports=same-tree"


def test_a_symlinked_root_is_not_reported_as_a_foreign_tree( tmp_path ):
    """
    A false alarm here is expensive: it trains readers to ignore the field. Paths are
    real-path resolved, so reaching the same tree through a link still reads as same-tree.
    """
    real = tmp_path / "real";           ( real / "src" / "cosa" / "utils" ).mkdir( parents=True )
    ( real / "src" / "lupin_app" ).mkdir( parents=True )
    link = tmp_path / "link";           link.symlink_to( real )

    modules = [ ( "cosa",      _Mod( str( real / "src" / "cosa" / "utils" / "import_origin.py" ) ), 2 ),
                ( "lupin_app", _Mod( str( link / "src" / "lupin_app" / "main.py" ) ),               1 ) ]
    assert import_origin_field( modules, str( link ) ) == "imports=same-tree"


def test_one_located_module_is_never_called_same_tree():
    """
    🔴 THE DEFECT RIO CAUGHT IN THE SHIPPED VERSION (ada5b1c1), and this test used to assert
    it. The first cut returned `same-tree` here and this arm PINNED that, so the suite
    endorsed the overclaim rather than merely missing it.

    `same-tree` asserts the modules AGREE. One module cannot agree with anything — a split is
    undetectable from a sample of one. The tail did name the absent module, but a reader skims
    the verdict and not the parenthetical, which is precisely the narrowed-population defect
    this field exists to catch. It was live on every cosa-tier run: 8,813 tests, `lupin_app`
    never loaded, `same-tree` printed off a single module.
    """
    field = import_origin_field( [ _cosa( WT ), ( "lupin_app", None, 1 ) ], WT )
    assert "same-tree" not in field, "one module cannot agree with anything"
    assert "single-module cosa in $LUPIN_ROOT" in field, "it still says what it DID find"
    assert "a split cannot be detected from one module" in field, "and what it could not rule out"
    assert "could not locate lupin_app: not loaded by this run" in field


def test_one_located_module_in_a_foreign_tree_does_not_claim_coherence_either():
    """
    The same overclaim wearing the other polarity. `coherent but NOT $LUPIN_ROOT` says the
    modules agree with each other while disagreeing with the root — a two-module finding.
    From one module, only the disagreement is established.
    """
    field = import_origin_field( [ _cosa( MAIN ), ( "lupin_app", None, 1 ) ], WT )
    assert "coherent" not in field, "coherence is a claim about two modules"
    assert f"⚠️ {MAIN}/src" in field
    assert "only cosa was observed" in field
    assert "a split cannot be ruled out either" in field


def test_two_agreeing_modules_still_earn_the_word_same_tree():
    """
    The control for the two tests above — without it they would pass on a field that had
    simply deleted `same-tree` altogether, which would be a different overclaim in reverse:
    refusing to state agreement that WAS established.
    """
    assert import_origin_field( [ _lupin_app( WT ), _cosa( WT ) ], WT ) == "imports=same-tree"


def test_a_module_without_a_dunder_file_is_a_distinct_reason_from_an_absent_one():
    """
    Namespace packages and some frozen imports have no `__file__`. That is a different failure
    from an import that never happened, and collapsing the two hides which one you hit.
    """
    field = import_origin_field( [ ( "cosa", _Mod( "" ), 2 ), ( "lupin_app", None, 1 ) ], WT )
    assert "cosa: no __file__" in field
    assert "lupin_app: not loaded by this run" in field
    assert field.startswith( "imports=UNKNOWN" ), "nothing was located, so there is no verdict to give"


def test_an_unset_lupin_root_reports_the_tree_it_found_instead_of_claiming_agreement():
    """
    "Could not look" must never launder into "looked and agreed" — the rule
    `capture_start_sha` follows when it returns UNKNOWN rather than None. With no root to
    compare against, the honest answer names the one checkout it did find.
    """
    field = import_origin_field( [ _lupin_app( WT ), _cosa( WT ) ], None )
    assert "same-tree" not in field, "agreement with nothing is not agreement"
    assert f"one-tree {WT}/src" in field
    assert "LUPIN_ROOT is not set" in field


def test_the_field_actually_reaches_the_test_env_line_a_human_reads():
    """
    WIRING, asserted by RUNNING pytest and reading the line — not by a regex over the source.
    Both alternatives have already failed in this exact file: a `[^)]*` regex stopped at the
    first close-paren and would have passed on a conftest that never wired the value through,
    and a test that imported "the conftest" by name got `src/tests/unit/conftest.py`, the
    nearest one, and measured the wrong module.

    A field computed correctly and never printed is worth nothing, and that is the failure a
    unit test over the pure function cannot see.
    """
    import subprocess
    root = os.environ[ "LUPIN_ROOT" ]
    done = subprocess.run(
        [ sys.executable, "-m", "pytest", "src/tests/unit/test_import_origin_field.py",
          "-q", "-k", "test_the_agreeing_case_is_stated_rather_than_left_silent" ],
        cwd=root, capture_output=True, text=True, timeout=180,
        env={ **os.environ, "LUPIN_ROOT" : root, "PYTHONPATH" : os.path.join( root, "src" ) } )

    env_lines = [ l for l in done.stdout.splitlines() if l.startswith( "[test-env]" ) ]
    assert len( env_lines ) == 1, f"expected exactly one [test-env] line, got {env_lines}"
    assert "imports=" in env_lines[ 0 ], f"the field never reached the line: {env_lines[ 0 ]}"
    assert "network=" in env_lines[ 0 ], "the pre-existing fields must survive the addition"


def test_the_real_modules_in_this_very_run_resolve_to_one_tree():
    """
    THE LIVE ARM. Every test above drives fakes; this one asks the question of the actual
    interpreter running it, so the depths encoded at the call site are checked against the real
    layout rather than against my belief about it.

    ⚠️ IT PASSES BOTH REAL MODULES, and that is not incidental. Its first cut passed `cosa`
    alone and asserted `same-tree` — so the ONE test aimed at reality was also the test that
    hard-coded the single-module overclaim Rio caught. The two depths differ (2 for
    `cosa/utils/x.py`, 1 for `lupin_app/x.py`), and only a live arm can catch one of them
    being wrong; a fake proves nothing about the real layout.
    """
    import cosa.utils.import_origin as real_cosa
    import lupin_app.bootstrap_helpers as real_app
    field = import_origin_field(
        [ ( "cosa", real_cosa, 2 ), ( "lupin_app", real_app, 1 ) ],
        os.environ.get( "LUPIN_ROOT" ) )
    assert field == "imports=same-tree", f"this run is not standing where it thinks: {field}"
