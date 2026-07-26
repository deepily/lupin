"""
hooks/lib sibling-import discipline — the missing detector, not a live defect.

WHY THIS EXISTS
---------------
Building the HWM janitor (row 8758d0b1) I opened it with a bare
`from heartbeat_hold import ...`. That resolves ONLY when
`src/lupin_cli/claude_code/hooks/lib` is on `sys.path` — true when a hook script
runs, and true in my own suite, which inserted the directory. So **27 tests
passed against an import graph production never uses**, and the failure appeared
only when the arbiter imported the module by its package path:

    ModuleNotFoundError: No module named 'heartbeat_hold'

⇒ The general shape: **a test environment more forgiving than production grades a
module that does not ship.**

MEASURED STATE, 2026-07-26 (María 🌸 + confirmed here at 33 modules)
--------------------------------------------------------------------
Bare sibling imports across the whole lib: **ZERO.** Every module already uses
the full `lupin_cli.claude_code.hooks.lib.<name>` path. My module was the only
outlier and it is fixed.

⇒ So this file guards a **hazard condition that is currently unexercised**. That
is deliberate and worth stating plainly: the thing that made the bug bite (a bare
import) is at zero, while the thing that HIDES it (a suite that repairs
`sys.path`) still exists. A future bare import would pass its own suite and die
at arbiter collection exactly as mine did. This test is the detector that was
missing, not a fix for something broken.

⚠️ ON COUNTING THE FORGIVING SUITES — the number is predicate-dependent and this
file deliberately does NOT assert one. Measured three ways: suites naming
`hooks/lib` AND doing `sys.path` surgery → 2 (one of which is a FALSE POSITIVE,
matching only on comment prose); any `sys.path` surgery anywhere under
`src/tests/` → 175, nearly all the ordinary `src/` bootstrap; surgery whose
target mentions "hook" → 7, mostly that same bootstrap. Pinning any of those
numbers would pin an artifact of the pattern that produced it. **What is worth
asserting is the import graph itself, which is unambiguous.**

Venue: :7999-eligible. Reads source text only — no imports executed, no network.
"""
import os
import pathlib
import re

import pytest


LIB = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/lupin_cli/claude_code/hooks/lib"

# `from <sibling> import x` / `import <sibling>` at the start of a line. Deliberately
# anchored with re.M rather than parsed: a bare import inside a function body is the
# same defect as one at module scope, and both are caught by this.
#
# The trailing `.*` captures the REST OF THE LINE so a failure names the whole
# statement. The first version stopped at the module name and reported
# "from heartbeat_hold" — enough to fail, not enough to fix, and it took the
# detector's own negative control going red to notice.
_BARE_IMPORT = re.compile( r"^[ \t]*(?:from|import)[ \t]+([a-z_][a-z0-9_]*)\b.*", re.M )


def _sibling_names():
    """
    Every module name that lives in hooks/lib.

    Ensures:
        - returns a non-empty set; an empty one would make the scan below pass
          vacuously, which is the failure mode this whole file is about
    """
    names = { p.stem for p in LIB.glob( "*.py" ) if p.stem != "__init__" }
    assert names, f"no modules found under {LIB} — the scan would pass vacuously"
    return names


def _bare_sibling_imports( text, module_stem, siblings ):
    """
    Bare (non-package-qualified) sibling imports in one module's source.

    Requires:
        - text is the module source; siblings is the set of names in the package

    Ensures:
        - returns a list of the offending import lines
        - a module importing ITSELF by name is not reported (it cannot happen, and
          excluding it keeps the rule about cross-module coupling)
        - stdlib and third-party imports are never reported, because a name only
          counts when it matches a FILE in this directory
    """
    out = [ ]
    for m in _BARE_IMPORT.finditer( text ):
        name = m.group( 1 )
        if name in siblings and name != module_stem:
            out.append( m.group( 0 ).strip() )
    return out


def test_no_module_in_hooks_lib_imports_a_sibling_by_bare_name():
    """
    THE GUARD. A bare sibling import works under hook execution and under any
    suite that inserts this directory — and explodes the moment the arbiter, or
    anything else, imports the module by its package path.

    The remedy is always the same and every one of the 33 modules already does it:

        from lupin_cli.claude_code.hooks.lib.<sibling> import <thing>
    """
    siblings  = _sibling_names()
    offenders = { }
    for path in sorted( LIB.glob( "*.py" ) ):
        hits = _bare_sibling_imports( path.read_text(), path.stem, siblings )
        if hits:
            offenders[ path.name ] = hits

    assert not offenders, (
        f"bare sibling import(s) in hooks/lib: {offenders}. These resolve only when "
        f"{LIB} is on sys.path — true for a hook script and for a test that inserts "
        f"it, FALSE when the arbiter imports by package path. Use the full "
        f"lupin_cli.claude_code.hooks.lib.<name> form, as all other modules do."
    )


# ── the detector must be able to fail ─────────────────────────────────────

def test_the_detector_DOES_flag_a_bare_sibling_import():
    """
    NEGATIVE CONTROL. The guard above is green only because the lib is clean; this
    proves it would go red otherwise, rather than passing because the regex
    silently stopped matching.

    Without this arm, deleting the regex's body would leave a permanently-green
    test — the exact class of defect (a control that never fires) that this whole
    row kept running into.
    """
    siblings = _sibling_names()
    assert "heartbeat_hold" in siblings, "fixture assumes heartbeat_hold is a real sibling"

    hits = _bare_sibling_imports(
        "import os\nfrom heartbeat_hold import _resolve_base_dir\n", "some_module", siblings
    )
    assert hits == [ "from heartbeat_hold import _resolve_base_dir" ]


def test_the_detector_also_catches_the_plain_import_form():
    """`import heartbeat_hold` fails identically to the `from ... import` form."""
    hits = _bare_sibling_imports( "import heartbeat_hold\n", "some_module", _sibling_names() )
    assert hits == [ "import heartbeat_hold" ]


def test_the_detector_does_NOT_flag_the_correct_package_form():
    """
    The discriminator. If the fully-qualified form were also flagged, the guard
    would be unsatisfiable and someone would delete it rather than obey it.
    """
    good = "from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir\n"
    assert _bare_sibling_imports( good, "some_module", _sibling_names() ) == [ ]


def test_the_detector_does_NOT_flag_stdlib_or_third_party():
    """
    A name is only an offender when it matches a FILE in this directory. Without
    this, `from pathlib import Path` reads as a sibling import — the exact false
    positive that produced a wrong count of 36 before the predicate was corrected
    (María, 2026-07-26). A number from a wrong pattern is indistinguishable from
    a real finding.
    """
    text = "import os\nimport json\nfrom pathlib import Path\nfrom typing import Optional\n"
    assert _bare_sibling_imports( text, "some_module", _sibling_names() ) == [ ]


def test_the_sibling_set_is_populated_and_includes_known_modules():
    """
    Pins that the scan is actually looking at the right directory. A typo in LIB
    would yield an empty set, and every assertion above would pass on nothing —
    which is why _sibling_names() asserts non-empty and this names real files.
    """
    siblings = _sibling_names()
    for known in ( "heartbeat_hold", "dm_inbox_reconcile", "dm_inbox_hwm_janitor" ):
        assert known in siblings, f"{known} missing — LIB is pointed at the wrong directory"
