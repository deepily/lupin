"""
Guard: websocket-architecture.md says "All methods are documented below". Hold
it to that, mechanically.

WHY. That sentence is a falsifiable universal claim, and on 2026-09-01 it was
false: FOUR public methods had ZERO mentions anywhere in the doc, and
`connect`'s documented signature was two parameters short. One of the missing
four was `emit_to_user_and_admins_sync` — the method its own docstring calls
canonical for every queue/job state change, and whose absence is the Session
248e740e defect (14 stale job cards stranded in an admin browser because a
caller used `emit_to_user_sync` alone). The doc could not have steered anyone
to the right method, because the right method was not in it.

`connect` was missing `roles` and `client_type` — and `client_type` is the
F-S6-1 platform marker whose BEHAVIOUR the same document describes two tables
higher up. The doc explained a parameter it did not list.

WHY THIS IS MECHANICAL AND NOT A CHECKLIST. Writing those four rows by hand,
this author inferred two signatures from their names and got both wrong:
`emit_to_admins_sync` takes no `user_id` at all, and
`emit_to_user_or_listener_sync` is a DUAL emit whose two sends fire
independently — not, as its `or` suggests, a fallback. A human reading the
method list will keep making that error. An AST comparison will not.

WHERE ELSE THIS CLAIM LIVES: NOWHERE. Swept all 35 docs under src/docs/ for a
completeness promise ("all methods are documented", "Complete API",
"exhaustive", "every method", "full list of"). The only hits are this doc's own
heading at :77 ("WebSocketManager — Complete API") and its sentence at :81 —
both held by this guard. The one other hit, test-fix-expediter-guide.md:330,
uses "exhaustive" about a test MODE, not about its own contents.

POSITIVE CONTROL for that sweep, and it caught a broken instrument: the first
pass returned ZERO — including the sentence I had just read with my own eyes.
The regex was fine (it matches 1 against the file directly); the PATHSPEC was
wrong. `git grep -- 'src/docs/**/*.md'` does not match a file sitting directly
in src/docs/, because git pathspecs are not shell globstar. A zero from a
pathspec that cannot reach the file reads exactly like a zero from a clean
tree. The corrected sweep names its population first (35 files) and returns the
known-true hit before any absence is believed.

NOT THE SAME RULE AS THE CLAUDE.md TOUCHPOINT. CLAUDE.md:1633 maps
websocket_manager.py -> websocket-architecture.md: change the code, update the
doc. That governs EDITING. This guard governs COMPLETENESS AT REST, and the two
come apart — the doc was touched repeatedly, satisfying the touchpoint rule
every time, and stayed four methods short throughout.

WHAT IS DELIBERATELY NOT ASSERTED. Not the prose, not the column layout, not
the return annotations, and not the descriptions — only that every public
method APPEARS, and that `connect`'s parameter list matches the code. A guard
that pinned the wording would fire on every honest edit and get deleted.
"""
import ast
from pathlib import Path

import pytest

import cosa.utils.util as cu


ROOT       = Path( cu.get_project_root() )
SOURCE     = ROOT / "src" / "cosa" / "rest" / "websocket_manager.py"
DOC        = ROOT / "src" / "docs" / "websocket-architecture.md"


def _public_methods():
    """
    Extract WebSocketManager's public method names from the source AST.

    Ensures:
        - returns a non-empty list of names, none starting with "_"

    Raises:
        - pytest.fail if the class or its methods cannot be found — an empty
          list would make every assertion below vacuously true
    """
    if not SOURCE.exists(): pytest.fail( f"source missing: {SOURCE}" )
    tree = ast.parse( SOURCE.read_text( encoding="utf-8" ) )
    cls  = next(
        ( n for n in tree.body if isinstance( n, ast.ClassDef ) and n.name == "WebSocketManager" ),
        None,
    )
    if cls is None: pytest.fail( "WebSocketManager class not found — the parser, not the doc, is broken" )

    names = [
        n.name for n in cls.body
        if isinstance( n, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and not n.name.startswith( "_" )
    ]
    if not names: pytest.fail( "zero public methods parsed — an empty population would pass every check below" )
    return names


def _connect_signature():
    """
    Ensures:
        - returns connect()'s parameter names in order, without `self`
    """
    tree = ast.parse( SOURCE.read_text( encoding="utf-8" ) )
    cls  = next( n for n in tree.body if isinstance( n, ast.ClassDef ) and n.name == "WebSocketManager" )
    fn   = next(
        ( n for n in cls.body
          if isinstance( n, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and n.name == "connect" ),
        None,
    )
    if fn is None: pytest.fail( "connect() not found on WebSocketManager" )
    return [ a.arg for a in fn.args.args if a.arg != "self" ]


def test_the_parser_finds_a_real_population():
    """
    Positive control. Every assertion below is an ABSENCE check, and an absence
    check over an empty population passes for the wrong reason.

    Ensures:
        - the parser returns a plausible number of methods
        - it finds a method known to exist
    """
    methods = _public_methods()
    assert len( methods ) > 15, f"only {len(methods)} methods parsed — suspiciously few"
    assert "emit_to_user" in methods


def test_every_public_method_appears_in_the_architecture_doc():
    """
    The doc's own claim, enforced.

    Ensures:
        - each public method name appears somewhere in websocket-architecture.md
    """
    doc     = DOC.read_text( encoding="utf-8" )
    missing = [ m for m in _public_methods() if m not in doc ]

    assert not missing, (
        f"websocket-architecture.md claims 'All methods are documented below' but omits: "
        f"{missing}. Add a row to the matching table — do not weaken this test. "
        f"Check the real signature with ast rather than inferring it from the name; "
        f"two of the four added on 2026-09-01 were guessed wrong that way."
    )


def test_the_documented_connect_signature_names_every_parameter():
    """
    Ensures:
        - every parameter of connect() appears inside its documented signature cell
    """
    doc = DOC.read_text( encoding="utf-8" )
    row = next( ( ln for ln in doc.splitlines() if ln.startswith( "| `connect` |" ) ), None )
    if row is None: pytest.fail( "no `connect` row found in the Connection Management table" )

    # Read the SIGNATURE CELL only, never the whole row. The row's description
    # also names `roles` and `client_type` in prose, so a whole-row search is
    # satisfied by the explanation and can no longer see the signature going
    # stale — measured: reverting the signature left a whole-row check GREEN.
    cells = [ c.strip() for c in row.split( "|" ) ]
    if len( cells ) < 3: pytest.fail( f"malformed connect row: {row!r}" )
    signature_cell = cells[ 2 ]

    absent = [ p for p in _connect_signature() if p not in signature_cell ]
    assert not absent, (
        f"the documented connect() signature omits {absent}. `client_type` in particular "
        f"is the F-S6-1 platform marker whose behaviour this same document describes in "
        f"the session_client_types attribute row — do not describe a parameter you do not list."
    )
