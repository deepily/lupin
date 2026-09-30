"""
THE GATE — an e2e test may only reach through `window.__multiplexerTestHook` by a name the hook
actually exposes. Row `47759aa3`.

WHY IT EXISTS (measured 2026-09-28, ts-a5c25121)
------------------------------------------------
Two e2e files called `window.__multiplexerTestHook.bus.emit( … )`. The hook publishes `eventBus`,
never `bus`, so the call threw `TypeError: Cannot read properties of undefined (reading 'emit')`
in the test's own SETUP — three reds across both layouts that read like a product regression on
Rick's doc-link path and were nothing of the kind. The failure surfaced only on :8000, after a
full e2e half; this gate names it in the unit tier, which needs no browser to read two strings.

WHAT IT CHECKS, AND WHAT IT DOES NOT
------------------------------------
It reads the keys of the object literal `boot.ts` assigns to `__multiplexerTestHook`, then every
`__multiplexerTestHook.<name>` in a tracked e2e file, and refuses any name not in that set. It
checks the FIRST segment only: `stores.readingPane` is not verified past `stores`.
"""
import re, subprocess

import cosa.utils.util as cu

BOOT_TS       = "src/lupin_app/static/js/multiplexer/boot.ts"
HOOK_ASSIGN   = re.compile( r"__multiplexerTestHook\s*=\s*\{(?P<body>[^}]*)\}", re.S )
HOOK_KEY      = re.compile( r"^\s*(?P<key>[A-Za-z_$][\w$]*)\s*(?:[:,]|$)", re.M )
HOOK_USE      = re.compile( r"__multiplexerTestHook\.(?P<name>[A-Za-z_$][\w$]*)" )


def hook_keys( boot_source ):
    """
    Requires:
        - boot_source is the text of boot.ts

    Ensures:
        - returns the set of top-level keys in the literal assigned to __multiplexerTestHook

    Raises:
        - AssertionError if the assignment cannot be found (the gate must not pass over nothing)
    """
    match = HOOK_ASSIGN.search( boot_source )
    assert match is not None, f"no `__multiplexerTestHook = {{ … }}` assignment found in {BOOT_TS}"
    return { m.group( "key" ) for m in HOOK_KEY.finditer( match.group( "body" ) ) }


def unknown_uses( text, keys ):
    """
    Requires:
        - text is test source, keys is the set returned by hook_keys

    Ensures:
        - returns the sorted names used through the hook that the hook does not expose
    """
    return sorted( { m.group( "name" ) for m in HOOK_USE.finditer( text ) } - keys )


def _root():
    return cu.get_project_root()


def _e2e_files():
    out = subprocess.run( [ "git", "ls-files", "src/tests/e2e_ui/*.py" ],
                          cwd=_root(), capture_output=True, text=True, check=True ).stdout
    return [ p for p in out.splitlines() if p ]


def _keys():
    with open( f"{_root()}/{BOOT_TS}", encoding="utf-8" ) as fh:
        return hook_keys( fh.read() )


def test_every_hook_name_an_e2e_test_uses_is_one_the_hook_exposes():
    """
    Ensures:
        - no tracked e2e file reaches through the hook by a name boot.ts does not publish
        - the failure names each file and each unknown name
    """
    keys    = _keys()
    files   = _e2e_files()
    users   = 0
    offence = {}
    for rel in files:
        with open( f"{_root()}/{rel}", encoding="utf-8" ) as fh:
            text = fh.read()
        if HOOK_USE.search( text ): users += 1
        bad = unknown_uses( text, keys )
        if bad: offence[ rel ] = bad

    assert users > 0, "no e2e file uses __multiplexerTestHook — the sweep read nothing, so it proves nothing"
    assert not offence, (
        f"e2e tests reach through __multiplexerTestHook by names it does not expose "
        f"(it exposes {sorted( keys )}):\n"
        + "\n".join( f"  {rel}: {bad}" for rel, bad in sorted( offence.items() ) ) )


def test_the_hook_exposes_the_names_the_suite_depends_on():
    """
    Ensures:
        - the key parse is not vacuous: the two names most e2e files use are found
    """
    keys = _keys()
    assert { "eventBus", "stores" } <= keys, f"hook key parse returned {sorted( keys )}"


def test_the_gate_refuses_the_shape_that_shipped():
    """
    Ensures:
        - the exact call that reached :8000 on 2026-09-27 is refused, and the corrected one is not
    """
    keys = _keys()
    assert unknown_uses( "window.__multiplexerTestHook.bus.emit( {} )", keys ) == [ "bus" ]
    assert unknown_uses( "window.__multiplexerTestHook.eventBus.emit( {} )", keys ) == []
