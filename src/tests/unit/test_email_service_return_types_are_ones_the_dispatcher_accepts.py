"""
Every `return_type` string in email_service.py must be one the REAL dispatcher accepts.

WHY THIS FILE EXISTS. `email_service.py` passed `return_type="bool"` at two call sites
while passing `return_type="boolean"` at a third, three lines above. The dispatcher
(`ConfigurationManager._get_typed_value`) accepts `"boolean"` and RAISES `ValueError` on
`"bool"` — it matches neither `== "boolean"`, nor `startswith( "int" )`, nor
`startswith( "str" )`.

🔴 AND NOTHING IN THE SUITE COULD SEE IT. Every case in
`src/cosa/tests/unit/rest/test_email_service.py` patches
`cosa.rest.email_service.config_mgr`. A mock accepts `"bool"` exactly as happily as
`"boolean"`, so the argument was never validated by anything — the fixture answers the
same however the code behaves. Mocking the config manager is right for those tests; it
is precisely why this one must NOT mock it.

⇒ SO THIS GUARD DRIVES THE REAL ConfigurationManager, and it derives its corpus from the
source rather than listing the call sites. A hand-written list of "the type strings we
use" is the same artifact that failed here — correct for everything its author thought
of, silently wrong for everything else. Add a call site tomorrow with a typo and this
file fails without anybody remembering to update it.
"""

import ast
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager


_SOURCE = Path( cu.get_project_root() ) / "src" / "cosa" / "rest" / "email_service.py"

def _return_type_literals():
    """
    Every `return_type` string a CALL in email_service.py actually passes.

    🔴 PARSED, NOT GREPPED, AND THIS FILE LEARNED THAT THE HARD WAY. The first cut matched
    `return_type=\"...\"` with a regex over the raw source. A later commit added a comment
    to email_service.py explaining the very defect this guard exists for — and the comment
    contains the string `return_type=\"bool\"`. The regex could not tell a call site from
    prose ABOUT a call site, so the guard failed on its own documentation.

    ⇒ A HIT IS NOT A USE, firing on the guard written to enforce it. The question was never
    "which type strings appear in this file" — it is "which type strings does this file
    PASS". Only the parse tree knows the difference.

    Requires:
        - email_service.py parses as Python; a SyntaxError here is a real failure and is
          allowed to propagate rather than being swallowed into an empty corpus

    Ensures:
        - returns only literals passed as the `return_type` keyword of an actual CALL
        - a mention in a comment, a docstring or an error message is EXCLUDED
        - returns them sorted and de-duplicated, so a failure names the same string
          every run
    """
    found = set()
    for node in ast.walk( ast.parse( _SOURCE.read_text() ) ):
        if not isinstance( node, ast.Call ): continue
        for keyword in node.keywords:
            if keyword.arg != "return_type":                 continue
            if not isinstance( keyword.value, ast.Constant ): continue
            if isinstance( keyword.value.value, str ):
                found.add( keyword.value.value )
    return sorted( found )


RETURN_TYPE_LITERALS = _return_type_literals()


@pytest.fixture( scope="module" )
def dispatcher():
    """
    The REAL ConfigurationManager — the whole point of this file.

    A mock would accept every string, which is exactly the blindness that let
    `return_type="bool"` ship. The splainer is muted only to keep the output readable;
    nothing about the dispatch is stubbed.
    """
    manager              = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    manager.mute_splainer = True
    return manager


@pytest.mark.parametrize( "literal", RETURN_TYPE_LITERALS )
def test_every_return_type_written_in_email_service_is_one_the_dispatcher_accepts( dispatcher, literal ):
    """
    Drive the real dispatcher with each literal the file actually writes.

    A string it rejects raises ValueError at the call site, and the caller's broad
    `except` turns that into a False the smoke test then reports as a normal
    development condition — so an unaccepted literal is invisible in production and
    invisible in the suite. It is visible here.
    """
    try:
        dispatcher.get( "a key that does not exist so the default path is taken",
                        True, silent=True, return_type=literal )
    except ValueError as error:
        pytest.fail(
            f"email_service.py passes return_type={literal!r}, which the real "
            f"ConfigurationManager REJECTS: {error}. At the call site this raises, the "
            f"broad except turns it into a False, and the smoke test reports it as "
            f"'normal in development'. Use a literal the dispatcher accepts."
        )


def test_the_corpus_is_not_EMPTY_and_reaches_the_literals_we_know_are_written():
    """
    🔴 THE POSITIVE CONTROL, AND THE PARAMETRIZED ARMS ABOVE ARE WORTHLESS WITHOUT IT.
    A regex that matched nothing would generate zero cases, and a loop over nothing is
    green — the same shape as an empty search read as a negative rather than as a
    search that never ran.

    A FLOOR plus named members, not an exact set: an exact set is a hand-maintained
    enumeration wearing an assertion's clothes, and would fail on the next legitimate
    call site.
    """
    assert len( RETURN_TYPE_LITERALS ) >= 2, (
        f"the extraction found only {RETURN_TYPE_LITERALS}. It is reading the source "
        f"wrong, and every parametrized arm above is silently testing nothing."
    )
    assert "bool" not in RETURN_TYPE_LITERALS, (
        f"the corpus contains 'bool', which no CALL in email_service.py passes — it "
        f"appears only in a comment describing the original defect. The extraction is "
        f"reading text rather than parsing calls, and it will fail on its own "
        f"documentation. Corpus: {RETURN_TYPE_LITERALS}"
    )
    for known in ( "boolean", "int" ):
        assert known in RETURN_TYPE_LITERALS, (
            f"email_service.py writes return_type={known!r} and the extraction missed "
            f"it — so the corpus is narrower than the file it claims to cover"
        )


def test_the_dispatcher_REALLY_REJECTS_a_bad_literal( dispatcher ):
    """
    🔴 THE NEGATIVE CONTROL. Without it the arms above prove nothing: a dispatcher that
    accepted every string would report every literal as healthy.

    `"bool"` is the exact string that shipped, so this also pins the defect itself —
    if a later change makes the dispatcher tolerant, this file must be re-thought
    rather than quietly kept.
    """
    with pytest.raises( ValueError ):
        dispatcher.get( "a key that does not exist so the default path is taken",
                        True, silent=True, return_type="bool" )
