"""
Which TREE the run's code was IMPORTED from — the half `[tree-state]` cannot see.

`[tree-state]` reports the git state of the directory you are standing in. It says nothing
about where Python actually loaded the code from, and on this fleet those are routinely two
different checkouts — sometimes within a single run.

THE DEFECT THIS NAMES (CLAUDE.md § A TIER RUN FROM A WORKTREE…, measured 2026-09-01 by
Rio ⚡). Every seat's shell exports `PYTHONPATH=/…/lupin/src`. A run pinned on `LUPIN_ROOT`
but NOT on `PYTHONPATH` assembles `lupin_app.*` from your worktree and `cosa.*` from the main
repo:

    main module file : /…/lupin-wt-rio-routeaudit/src/lupin_app/main.py   <- WORKTREE
    tasks module file: /…/lupin/src/cosa/rest/routers/tasks.py            <- MAIN REPO

The assembled application exists in NO checkout, and the receipt is what it cost: two guards
written for a real route-shadowing defect reported `6 passed` against a mutation that had
never been loaded. Pin both and the same arm gives `2 failed`.

⚠️ THE SPLIT IS THE FINDING, NOT "ONE MODULE IS FOREIGN" — Rio's correction to this module's
first cut, which checked `cosa` alone against `LUPIN_ROOT`. Two modules that agree with each
other are a coherent tree even when it is not the one you meant; two that disagree are a tree
that exists nowhere, and only the second can produce a green about code nobody has. Checking
one module can see a symptom; comparing two is what names the disease.

⚠️ `run-span=unmoved` STILL PRINTS ON SUCH A RUN, correctly, because it describes the
worktree's git state and knows nothing about what was imported. That is why this is a separate
field rather than a clause of the tree-state line: two questions, two instruments.

WHY A VERDICT AND NOT TWO BARE PATHS. The paths differ in one segment out of eight and run to
~60 characters each; comparing them by eye is the failure mode this exists to catch, and it has
cost this fleet hours more than once. The reader is told `same-tree`, or handed the specific
disagreement — never two long strings to diff themselves.

Kept standard-library only and dependency-free: the root conftest imports it early, alongside
`cosa.utils.tree_state` and `cosa.utils.secret_redaction`.

Venue: :7999-eligible — no subprocess, no network, no mutation.
"""
import os


def _checkout_of( module ):
    """
    The `src` a module was loaded through, or a reason it could not be determined.

    Returns `( path, None )` on success and `( None, reason )` on failure, so the caller can
    distinguish "could not look" from "looked and agreed" — which is this family's whole point.

    Compared at the `src` level rather than the package level because the question is WHICH
    CHECKOUT, not which directory. `…/src/cosa/utils/import_origin.py` and
    `…/src/lupin_app/main.py` sit at different depths below their package roots, so each
    caller passes a module whose depth it knows; see `import_origin_field`.
    """
    if module is None:                       return ( None, "not loaded by this run" )
    origin = getattr( module, "__file__", None )
    if not origin:                           return ( None, "no __file__" )
    return ( origin, None )


def _src_root( origin, depth ):
    """The `src` directory `depth` levels above a module file, real-path resolved."""
    return os.path.realpath( os.path.join( os.path.dirname( origin ), *( [ ".." ] * depth ) ) )


def import_origin_field( modules, lupin_root ):
    """
    The `imports=` field: one verdict about where this run's code actually came from.

    Requires:
        - modules is a sequence of `( name, module_or_None, depth )`, where `depth` is how
          many directories separate the module's file from its `src` root. Injected rather
          than imported here so every arm is drivable by a test that does not own the
          interpreter's real import state — the same reason `tree_state` injects its git
          reader.
          ⚠️ THE CALLER READS `sys.modules`; THIS NEVER IMPORTS ANYTHING. A diagnostic that
          imports is a diagnostic that changes the run it describes — and worse here than
          usual, since importing a module would CREATE the very resolution it claims to be
          observing. `None` therefore means "this run never loaded it", which is a fact
          about the run and not a fact about the module.
        - lupin_root is the run's `LUPIN_ROOT`, or None/"" when unset.

    Ensures:
        - returns a single `imports=…` token, ALWAYS. A field that goes quiet when it cannot
          answer is indistinguishable from one that was never computed — the rule
          `tree_state._run_span` follows when it prints `unmoved` rather than nothing
        - REPORTS A SPLIT AS A SPLIT, naming every distinct checkout and which module came
          from which. This is the finding; a single module disagreeing with `LUPIN_ROOT` is
          only a symptom of it (Rio ⚡, correcting the first cut)
        - DISTINGUISHES A COHERENT FOREIGN TREE FROM A SPLIT ONE. Both modules agreeing with
          each other but not with `LUPIN_ROOT` is a real, self-consistent checkout — wrong
          tree, honest result. A split is an application assembled from two, and only that
          one can produce a green about code that exists nowhere. Different severities, so
          they get different words
        - SAYS WHICH MODULES IT COULD NOT LOCATE, rather than silently judging on the rest.
          A verdict reached over a subset, presented as a verdict over the whole, is the
          narrowed-population defect this repo documents at length
        - NEVER SAYS `same-tree` OFF A SINGLE MODULE. One module cannot agree with anything,
          so a split is UNDETECTABLE from a sample of one and the verdict says so
          (`single-module …`) rather than borrowing a word that means agreement. The tail
          already named the absent module, but a reader skims the verdict and not the
          parenthetical — which is how this field committed, in its first shipped form, the
          exact defect it was written to catch
        - COMPARES REAL PATHS, so a worktree reached through a symlink does not read as
          foreign. A false alarm here is expensive: it trains readers to ignore the field

    Raises:
        - nothing. Every operand is checked before use, and `os.path.realpath` does not raise
          for a path that does not exist.
    """
    located  = {}
    unknowns = []
    for name, module, depth in modules:
        origin, why = _checkout_of( module )
        if origin is None: unknowns.append( f"{name}: {why}" )
        else:              located[ name ] = _src_root( origin, depth )

    if not located:
        return "imports=UNKNOWN — " + "; ".join( unknowns )

    roots = sorted( set( located.values() ) )
    tail  = f" (could not locate {'; '.join( unknowns )})" if unknowns else ""

    if len( roots ) > 1:
        where = ", ".join( f"{n} <- {located[ n ]}" for n in sorted( located ) )
        return ( f"imports=⚠️ SPLIT ACROSS {len( roots )} CHECKOUTS — {where}. "
                 f"This run assembled code that exists in no single tree{tail}" )

    # One checkout among what was LOCATED. Two questions remain, and they are separate:
    # is it the tree the run meant, and was a split even DETECTABLE from this sample?
    #
    # 🔴 ONE MODULE CANNOT AGREE WITH ANYTHING (Rio ⚡, correcting the shipped ada5b1c1 —
    # the second time on this module he caught the verdict claiming more than the evidence).
    # `same-tree` asserts that the modules agree. With a single module located there is no
    # agreement to assert: a split is UNDETECTABLE from a sample of one, and the word said
    # otherwise. The tail did disclose the missing module, but a reader skims the verdict and
    # not the parenthetical — which is this repo's own narrowed-population defect, committed
    # by the very field written to prevent it. Measured: every cosa-tier run (8,813 tests,
    # `lupin_app` never loaded) printed `same-tree` off one module.
    only     = roots[ 0 ]
    agreeing = len( located ) > 1
    seen     = ", ".join( sorted( located ) )

    if not lupin_root:
        return f"imports=one-tree {only} (LUPIN_ROOT is not set, so nothing to compare against){tail}"

    wanted = os.path.realpath( os.path.join( lupin_root, "src" ) )
    if only == wanted:
        if agreeing: return f"imports=same-tree{tail}"
        return ( f"imports=single-module {seen} in $LUPIN_ROOT — a split cannot be detected "
                 f"from one module{tail}" )

    if agreeing:
        return ( f"imports=⚠️ {only} — coherent but NOT $LUPIN_ROOT ({wanted}); "
                 f"this run measured another checkout{tail}" )
    return ( f"imports=⚠️ {only} — NOT $LUPIN_ROOT ({wanted}); only {seen} was observed, "
             f"so a split cannot be ruled out either{tail}" )
