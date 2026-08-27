"""
Guard — no hardcoded GCP project identifier on any EXECUTABLE tracked surface.

WHY THIS FILE EXISTS (and why it replaces its predecessor)
----------------------------------------------------------
`test_cloud_run_parameterization.test_no_hardcoded_sandbox_project` grepped a
hardcoded three-item list (`CLOUD_RUN_SCRIPTS`). It therefore could only ever find
offenders in the three places someone had remembered to list — while 28 tracked
files carried the literal. It passed vacuously and was cited as proof that the rule
was "mechanically enforced, forever."

    A hardcoded allowlist is a BOUNDED check.
    "Forever" is a COMPLETENESS claim, and a bounded check cannot make one.

This guard INVERTS the question. Instead of asking "are the files I listed clean?"
it asks "what does git actually track, and is ALL of it clean?" A newly added
script cannot escape it, because nobody has to remember to add anything.

WHY THIS IS NOT HYGIENE
-----------------------
`GOOGLE_CLOUD_PROJECT` and `GCLOUD_PROJECT` OUTRANK `ANTHROPIC_VERTEX_PROJECT_ID`
for Vertex clients, and `GOOGLE_APPLICATION_CREDENTIALS` outranks all three. A
literal project id on any executable path can therefore silently redirect metered
Vertex traffic to the wrong project — the session runs, bills real money, and every
project guard still reports green.

Venue: :7999-eligible — pure `git ls-files` + file reads. No network, no mutation.
"""
import ast
import hashlib
import os
import re
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

# The sandbox project id this repo must never hardcode on an executable path.
SANDBOX_PROJECT_ID = "hello-world-foo-423219"

# Suffixes that can supply a value to a running process. Markdown is deliberately
# absent: a .md file is an inert record and cannot hand a project id to anything.
EXECUTABLE_SUFFIXES = (
    ".sh", ".bash", ".py", ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg",
    ".bats", ".tf", ".tfvars", ".hcl", ".ts", ".tsx", ".js", ".jsx", ".env", ".example",
)

# Extensionless files that are nonetheless executable surfaces.
EXECUTABLE_STEMS = ( "Dockerfile", "Makefile" )

# EXEMPTIONS — every entry carries a written reason. There is exactly ONE: this guard,
# which must NAME the forbidden id in order to FORBID it. No other file on an executable
# surface is exempt, because every exemption re-opens the bounded-check hole this guard
# exists to close.
#
# (src/terraform/tests/modules.bats was the second exemption until 2026-07-13. It was a
# bats guard that had NEVER RUN — bats is not installed and nothing invoked it — and its
# project-id grep was bounded to `--include="*.tf"`, blind to .tfvars/.hcl/.example. Its
# 15 assertions are ported to src/tests/unit/test_terraform_invariants.py, where they
# actually execute; the file is retired, so the exemption is gone rather than inherited.)
EXEMPT = {
    "src/tests/unit/test_no_hardcoded_gcp_identifiers.py":
        "This guard itself — it must contain the literal in order to grep for it.",
}

# The legacy bounded list this guard supersedes. Retained ONLY so we can assert the
# new scanned set is a strict superset — i.e. prove we never regress to a hand-list.
LEGACY_BOUNDED_ALLOWLIST = (
    "src/scripts/cloud-run-build.sh",
    "src/scripts/cloud-run-setup-secrets.sh",
    "src/scripts/cloud-run-validate.sh",
)

# The script the Vertex toggle modifies. It was NOT in the legacy list; its absence is
# precisely the hole that motivated this guard, so its coverage is asserted explicitly.
VERTEX_TOGGLE_SCRIPT = "src/scripts/start-cc-with-tmux.sh"


def _tracked_files():
    """Every path git tracks, repo-relative. The inversion: ask git, not a human."""
    result = subprocess.run(
        [ "git", "ls-files" ], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    )
    return [ line for line in result.stdout.splitlines() if line ]


def _is_executable_surface( rel_path ):
    """True when the file can supply a value to a running process (docs cannot)."""
    if os.path.basename( rel_path ).startswith( EXECUTABLE_STEMS ): return True
    return rel_path.endswith( EXECUTABLE_SUFFIXES )


def scanned_files():
    """The guard's scope: every tracked executable surface that is not exempted."""
    return [ f for f in _tracked_files() if _is_executable_surface( f ) and f not in EXEMPT ]


def _read( rel_path ):
    with open( os.path.join( PROJECT_ROOT, rel_path ), "r", errors="replace" ) as f:
        return f.read()


def _strip_shell_comment( line ):
    """
    Return `line` with any trailing shell comment removed.

    A `#` inside quotes is not a comment, so quote state is tracked rather than
    splitting on the first `#` — otherwise a legitimate string containing `#`
    would truncate the line and hide a real assignment after it.
    """
    in_single = in_double = False
    for i, ch in enumerate( line ):
        if   ch == "'" and not in_double: in_single = not in_single
        elif ch == '"' and not in_single: in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[ i - 1 ] in " \t": return line[ :i ]
    return line


def _is_inert_error_message( line, idx ):
    """
    True when the literal at `idx` sits inside a `${VAR:?...}` expansion.

    `:?` is the ABORT-WITH-MESSAGE form — the text after it is printed and the
    shell exits; it can never become the parameter's value. `:-` and `:=` are the
    DEFAULT-VALUE forms and are the opposite: they hand the literal to the running
    process, which is exactly the defect this guard exists to catch. Distinguishing
    them is the whole point — collapsing both to "inside ${...}" would create the
    silent-default hole while looking like a fix.
    """
    open_at = line.rfind( "${", 0, idx )
    if open_at == -1: return False
    close_at = line.find( "}", idx )
    if close_at == -1: return False
    return ":?" in line[ open_at:idx ]


def supplying_occurrences( text ):
    """
    Lines where the literal appears in a position that can SUPPLY IT TO A PROCESS.

    Requires:
        - text is the full contents of an executable surface

    Ensures:
        - returns [ (lineno, line) ] for value-supplying occurrences only
        - comments never match: prose describing the id is a record, not a use
        - `${VAR:?...}` error text never matches — it aborts, it does not assign
        - `${VAR:-...}` / `${VAR:=...}` DO match: they are silent defaults
        - anything else containing the literal is treated as supplying, so a new
          syntax nobody anticipated fails CLOSED rather than sailing through

    KNOWN HOLE — LINE-BASED, SO IT CANNOT SEE A MULTI-LINE STRING. Quote state is
    tracked WITHIN one line and only `#` is stripped, so the body of a Python
    triple-quoted block reads as code and its prose lands as a hit. That is why
    `.py` is routed to `_py_supplying_occurrences` below instead of here. Every
    other suffix still uses this function and still has the hole; it has simply
    never bitten, because no `.yml`/`.json`/`.tf` file in this tree writes prose
    about the project id inside a multi-line scalar. If one ever does, teach the
    parser for that suffix — do NOT add an exemption.
    """
    hits = []
    for lineno, raw in enumerate( text.splitlines(), start=1 ):
        code = _strip_shell_comment( raw )
        idx  = code.find( SANDBOX_PROJECT_ID )
        if idx == -1: continue
        if _is_inert_error_message( code, idx ): continue
        hits.append( ( lineno, raw.strip() ) )
    return hits


# Positions in which a string constant CANNOT hand its value to anything: an
# `in`/`==` test, an assert's message, and a bare string expression statement (a
# docstring). Deliberately an INERT list rather than a SUPPLYING list — everything
# not named here is treated as supplying, so an ast node nobody anticipated fails
# CLOSED, exactly as the line-based predicate does.
PY_INERT_PARENTS = ( ast.Compare, ast.Assert, ast.Expr )


# PINNED PROSE — the multi-line strings in a SUPPLYING position that are known to
# be paragraphs about the id rather than uses of it. Keyed on (file, the line the
# literal sits on) and pinned to a hash of THAT LINE, so editing the prose breaks
# the pin and somebody has to look again.
#
# WHY PIN RATHER THAN SKIP (Mr Radio's ruling, 2026-08-26): "a multi-line string is
# inert" is a blanket hole, and the two things it would wave through are not exotic
# — an embedded YAML blob and a `gcloud` command line are how a project id actually
# gets supplied from Python. Collect them and check them against what we already
# know instead.
#
# THIS IS NOT THE BOUNDED ALLOWLIST THIS GUARD REPLACED. That one was bounded on
# WHERE IT LOOKED — three remembered filenames, so a new script escaped by existing.
# This is bounded only on WHAT IT ALREADY KNOWS: every tracked file is still
# scanned, every new occurrence is still an offender, and the inventory can only
# shrink the answer for a line whose exact text someone already justified.
PINNED_PROSE = {
    ( "src/cosa/agents/presentation_generator/gemini_client.py", 47 ):
        # "(hello-world-foo-423219). models.get returns 404 NOT_FOUND for both"
        # The LOUD NOTICE banner printed to stderr — it must NAME the project that
        # 404s, which is the banner's whole job. Approved standing exception,
        # 2026-08-16; the notice is `print`ed, never passed to any client.
        "e2efc259dcd7f1c43f505afc93123ae708fa80d713175c628d68481fa89f11ad",
}


def _line_pin( line ):
    """The pin for one source line: a hash of its exact text, whitespace included."""
    return hashlib.sha256( line.encode() ).hexdigest()


def _is_pinned_prose( rel_path, lineno, raw_line, value ):
    """
    True only for a KNOWN multi-line prose occurrence — all four facts must agree.

    Requires:
        - rel_path/lineno locate the literal; raw_line is that source line verbatim
        - value is the full string constant the literal was found in

    Ensures:
        - a SINGLE-LINE value is never pinned, whatever the inventory says: pinning
          is a claim about prose, and a one-line string is a value. Without this the
          inventory would quietly become the exemption mechanism the guard's header
          rules out
        - the pin must match on FILE and LINE and the line's EXACT TEXT, so the same
          prose moved, copied, or reworded is a new occurrence and is caught
    """
    if "\n" not in value: return False
    return PINNED_PROSE.get( ( rel_path, lineno ) ) == _line_pin( raw_line )


def _py_literal_lineno( node, idx ):
    """
    The line the literal actually sits on, not the line the string STARTS on.

    A triple-quoted constant reports `node.lineno` at its opening quotes, which for
    a 28-line banner is nowhere near the id. Reading a failure message that names a
    line the literal is not on is how someone concludes the guard is broken.

    Requires:
        - node is an ast.Constant holding a str
        - idx is the index of the literal inside node.value

    Ensures:
        - returns node.lineno plus the number of newlines preceding idx
    """
    return node.lineno + node.value[ :idx ].count( "\n" )


def _py_supplying_occurrences( rel_path, text ):
    """
    Lines where the literal appears in a Python position that can SUPPLY it.

    The line-based predicate cannot see a multi-line string, so a prose banner
    assigned to a constant reads as an assignment. POSITION alone does not separate
    the two either: a banner assigned to `_IMAGE_GEN_NOTICE` is an assignment RHS, the same
    position as a real `PROJECT_ID = "<id>"`. Two properties are needed.

    Requires:
        - text is the full contents of a .py file

    Ensures:
        - a literal in an inert position never matches (see PY_INERT_PARENTS)
        - a literal in a MULTI-LINE string matches UNLESS its (file, line) is in
          PINNED_PROSE and the line still hashes to the pinned value — collect and
          check, never skip wholesale
        - a literal in a single-line string DOES match and can NEVER be pinned —
          assignment RHS, keyword argument, call argument, dict value, os.environ
          subscript, and an f-string fragment, which is how a real id is embedded
          in a URL
        - a file that does not parse falls back to the line-based predicate rather
          than returning [], so a syntax error cannot silently disarm the guard

    Raises:
        - nothing; SyntaxError is caught and degraded to the line-based path
    """
    try:
        tree = ast.parse( text )
    except SyntaxError:
        return supplying_occurrences( text )

    parents = {}
    for node in ast.walk( tree ):
        for child in ast.iter_child_nodes( node ): parents[ child ] = node

    lines = text.splitlines()
    hits  = []
    for node in ast.walk( tree ):
        if not ( isinstance( node, ast.Constant ) and isinstance( node.value, str ) ): continue
        idx = node.value.find( SANDBOX_PROJECT_ID )
        if idx == -1: continue
        if isinstance( parents.get( node ), PY_INERT_PARENTS ): continue
        lineno = _py_literal_lineno( node, idx )
        raw    = lines[ lineno - 1 ] if lineno - 1 < len( lines ) else ""
        # A multi-line string is a CANDIDATE, not an exemption: it clears only by
        # matching prose we already looked at, line and exact text.
        if _is_pinned_prose( rel_path, lineno, raw, node.value ): continue
        hits.append( ( lineno, raw.strip() ) )
    return sorted( hits )


def supplying_occurrences_for( rel_path, text ):
    """
    Route a file to the predicate that can actually read it.

    Ensures:
        - `.py` is parsed with ast; every other suffix keeps the line-based path
        - the return shape is identical either way: [ (lineno, line) ]
    """
    if rel_path.endswith( ".py" ): return _py_supplying_occurrences( rel_path, text )
    return supplying_occurrences( text )


def test_no_hardcoded_gcp_project_id_on_any_executable_surface():
    """
    THE GUARD. Scans what git tracks — not what someone remembered to list.

    NARROWED 2026-07-27 (row 5bf28e07 follow-up). It used to test
    `SANDBOX_PROJECT_ID in _read( f )` — a raw substring over the whole file. That
    matched a COMMENT and a `${VAR:?...}` error-message example in
    `src/scripts/lupin-vm.sh`, neither of which assigns or bills anything, and it
    blocked the wired gate on prose. A predicate that matches a DESCRIPTION of the
    project id is not a predicate about the project id.

    The remedy is a narrower predicate, NOT an exemption for that file: an
    exemption fixes one script and re-arms the guard for the next one, and it
    would have silently exempted a real assignment added to it later.
    """
    offenders = { f: supplying_occurrences_for( f, _read( f ) ) for f in scanned_files() }
    offenders = { f: hits for f, hits in offenders.items() if hits }
    assert not offenders, (
        f"{len( offenders )} tracked executable file(s) hardcode the sandbox project id "
        f"'{SANDBOX_PROJECT_ID}'. GOOGLE_CLOUD_PROJECT/GCLOUD_PROJECT outrank "
        f"ANTHROPIC_VERTEX_PROJECT_ID — a literal here can silently bill the wrong "
        f"project while every guard reports green. Offenders (file: line): "
        + "; ".join( f"{f}: {[ n for n, _ in hits ]}" for f, hits in offenders.items() )
    )


# ---------------------------------------------------------------------------
# CONTROLS for the narrowed predicate. Without these, a predicate that returned
# [] unconditionally would pass the guard above on any tree — the failure mode
# the narrowing itself could introduce.
# ---------------------------------------------------------------------------

def test_a_real_assignment_is_still_caught():
    """CONTROL THAT MUST FAIL when the narrowing is over-eager."""
    text = f'export GOOGLE_CLOUD_PROJECT="{SANDBOX_PROJECT_ID}"\n'
    assert supplying_occurrences( text ) == [ ( 1, text.strip() ) ]


def test_a_bare_default_expansion_is_still_caught():
    """
    `${VAR:-<id>}` SUPPLIES the literal when VAR is unset — the silent-billing
    case. It must stay caught even though `${VAR:?...}` does not, and this is the
    arm that fails if someone "simplifies" the check to ignore all `${...}`.
    """
    text = f'PROJECT="${{LUPIN_GCP_PROJECT_ID:-{SANDBOX_PROJECT_ID}}}"\n'
    assert len( supplying_occurrences( text ) ) == 1

    assign_text = f'PROJECT="${{LUPIN_GCP_PROJECT_ID:={SANDBOX_PROJECT_ID}}}"\n'
    assert len( supplying_occurrences( assign_text ) ) == 1


def test_a_comment_is_not_an_offender():
    """Prose describing the id is a record of it, not a use of it."""
    assert supplying_occurrences( f"# e.g. {SANDBOX_PROJECT_ID}\n" ) == []
    assert supplying_occurrences( f"VAR=x   # e.g. {SANDBOX_PROJECT_ID}\n" ) == []


def test_an_abort_message_expansion_is_not_an_offender():
    """`${VAR:?...}` prints and exits — it can never become the value."""
    text = f': "${{LUPIN_GCP_PROJECT_ID:?Set it (e.g. export LUPIN_GCP_PROJECT_ID={SANDBOX_PROJECT_ID})}}"\n'
    assert supplying_occurrences( text ) == []


def test_a_hash_inside_quotes_does_not_truncate_the_line():
    """
    A naive `split('#')[0]` would drop everything after a quoted `#` and hide a
    real assignment sitting behind it. This is that hole, asserted shut.
    """
    text = f'echo "tag#1" && export GOOGLE_CLOUD_PROJECT={SANDBOX_PROJECT_ID}\n'
    assert len( supplying_occurrences( text ) ) == 1


def test_the_live_offenders_are_exactly_the_two_prose_hits_in_lupin_vm():
    """
    Pins WHY the tree is green: `lupin-vm.sh` still CONTAINS the literal twice,
    and both are inert. If someone adds a real assignment there, the guard above
    goes red and this test documents that the file was never literal-free.
    """
    text = _read( "src/scripts/lupin-vm.sh" )
    assert SANDBOX_PROJECT_ID in text, "premise gone — the file no longer names the id at all"
    assert supplying_occurrences( text ) == [], "a supplying occurrence appeared in lupin-vm.sh"


# ---------------------------------------------------------------------------
# CONTROLS for the .py predicate (row e2099400 follow-up, 2026-08-26). The
# line-based predicate flagged two prose hits in gemini_client.py and its test.
# POSITION alone does not clear them — the banner is an assignment RHS, the same
# position as a real assignment — so the .py path tests position AND shape. These
# controls exist because a predicate that returned [] for every .py file would
# make THE GUARD pass on any tree, which is the failure this narrowing can cause.
# ---------------------------------------------------------------------------

_PY_BANNER = (
    "_IMAGE_GEN_NOTICE = \"\"\"\n"
    "LOUD NOTICE\n"
    "Imagen is not reachable on the GCP project\n"
    f"({SANDBOX_PROJECT_ID}). models.get returns 404.\n"
    "\"\"\"\n"
)


def test_an_unpinned_prose_banner_is_still_an_offender():
    """
    PIN, DON'T SKIP. This banner is prose in an assignment RHS — the same shape as
    the live one — but it is not in PINNED_PROSE, so it is an offender. A blanket
    "multi-line is inert" rule would wave it through, and would wave through the
    two cases below with it.
    """
    assert len( _py_supplying_occurrences( "a/b.py", _PY_BANNER ) ) == 1


@pytest.mark.parametrize( "source,label", [
    ( f'CFG = """\nproject_id: {SANDBOX_PROJECT_ID}\nregion: us-central1\n"""\n',
      "embedded YAML blob" ),
    ( f'CMD = """\ngcloud run deploy svc \\\n  --project {SANDBOX_PROJECT_ID}\n"""\n',
      "gcloud command line" ),
    ( f'URL = f"""\nhttps://x/projects/{SANDBOX_PROJECT_ID}/\nmodels"""\n',
      "multi-line f-string URL" ),
] )
def test_a_multiline_string_that_really_supplies_the_id_is_caught( source, label ):
    """
    The cases the blanket skip would have lost. These are not exotic — a YAML blob
    and a `gcloud` line are how a project id actually gets supplied from Python.
    """
    assert len( _py_supplying_occurrences( "a/b.py", source ) ) == 1, f"{label} slipped through"


def test_a_python_assertion_about_the_id_is_not_an_offender():
    """`assert "<id>" in err` tests the id, it does not supply it. Position, not shape."""
    text = f'def t( err ):\n    assert "{SANDBOX_PROJECT_ID}" in err, "must name it"\n'
    assert _py_supplying_occurrences( "a/b.py", text ) == []


def test_a_python_docstring_naming_the_id_is_not_an_offender():
    """A bare string expression statement is a record, like a `#` comment."""
    text = f'def t():\n    """See {SANDBOX_PROJECT_ID} for why."""\n    return 1\n'
    assert _py_supplying_occurrences( "a/b.py", text ) == []


@pytest.mark.parametrize( "source,label", [
    ( f'PROJECT_ID = "{SANDBOX_PROJECT_ID}"\n',                       "assignment RHS" ),
    ( f'client( project="{SANDBOX_PROJECT_ID}" )\n',                  "keyword argument" ),
    ( f'client( "{SANDBOX_PROJECT_ID}" )\n',                          "call argument" ),
    ( f'CFG = {{ "project": "{SANDBOX_PROJECT_ID}" }}\n',             "dict value" ),
    ( f'os.environ[ "GOOGLE_CLOUD_PROJECT" ] = "{SANDBOX_PROJECT_ID}"\n', "environ subscript" ),
    ( f'url = f"https://x/projects/{SANDBOX_PROJECT_ID}/models"\n',   "f-string fragment" ),
    ( f'PROJECT_ID: str = "{SANDBOX_PROJECT_ID}"\n',                  "annotated assignment" ),
    ( f'def f( project="{SANDBOX_PROJECT_ID}" ): pass\n',             "default argument" ),
    ( f'def f(): return "{SANDBOX_PROJECT_ID}"\n',                    "return value" ),
] )
def test_a_real_python_supply_is_still_caught( source, label ):
    """
    EVERY supplying position, one case each. If the narrowing is over-eager, the
    arm it broke is named rather than left to a single collapsed assertion.
    """
    assert len( _py_supplying_occurrences( "a/b.py", source ) ) == 1, f"{label} slipped through"


def test_a_pin_is_keyed_to_the_exact_line_so_editing_the_prose_breaks_it():
    """
    The pin's whole value. If the banner's wording changes, the hash stops matching
    and the line becomes an offender again — somebody has to look at it and re-pin
    deliberately, rather than inheriting a decision made about different text.
    """
    rel  = "src/cosa/agents/presentation_generator/gemini_client.py"
    text = _read( rel )
    assert _py_supplying_occurrences( rel, text ) == [], "premise: the live banner is pinned and clear"

    edited = text.replace( "). models.get returns 404 NOT_FOUND for both",
                           "). models.get returns 404 NOT FOUND for both" )
    assert edited != text, "premise gone — the pinned line no longer reads as expected"
    assert len( _py_supplying_occurrences( rel, edited ) ) == 1, (
        "editing the pinned line must break the pin; a pin that survives an edit is a skip"
    )


def test_a_pin_does_not_travel_to_another_file_or_another_line():
    """
    A pin is (file, line, text) — all three. The same prose in a different file, or
    at a different line, is a NEW occurrence and must be caught.
    """
    rel   = "src/cosa/agents/presentation_generator/gemini_client.py"
    text  = _read( rel )
    assert _py_supplying_occurrences( "src/cosa/agents/other.py", text ) != [], "pin travelled to another file"
    assert _py_supplying_occurrences( rel, "\n" + text ) != [],                "pin survived a line shift"


def test_a_single_line_supply_can_never_be_pinned():
    """
    Pinning is only ever a claim about PROSE. A one-line string is a value, and no
    inventory entry may clear one — otherwise the pin becomes the exemption
    mechanism this guard's header rules out.

    This asserts the ARM, not a scenario: it hands `_is_pinned_prose` a file, line
    and line-text that ALL match a real pin, and requires False purely because the
    value is single-line. Written this way after the scenario version failed to
    catch a mutation that dropped the single-line condition — every other fact
    agreed, so the mutant answered identically on any input the scenario could
    build.
    """
    ( rel, lineno ), pin = next( iter( PINNED_PROSE.items() ) )
    raw = _read( rel ).splitlines()[ lineno - 1 ]
    assert _line_pin( raw ) == pin, "premise: this line still matches its pin"

    assert _is_pinned_prose( rel, lineno, raw, "a\n" + raw ) is True, (
        "premise: with a multi-line value, this exact (file, line, text) IS pinned"
    )
    assert _is_pinned_prose( rel, lineno, raw, raw ) is False, (
        "a single-line value was pinned — the inventory has become an exemption list"
    )

    # WHITESPACE IS PART OF THE TEXT. Hashing the stripped line would let an
    # indented copy of the same prose inherit a pin justified about a different
    # place in the file. Caught as a surviving mutation, then asserted.
    assert _is_pinned_prose( rel, lineno, "    " + raw, "a\n" + raw ) is False, (
        "re-indenting the pinned line kept its pin — _line_pin must hash the exact text"
    )


def test_the_pinned_inventory_cannot_grow_silently():
    """
    Mirrors the exemption-set control. Every pin is a decision someone made; the
    count is asserted so a new one arrives with a reviewer rather than in a diff
    nobody read.
    """
    assert len( PINNED_PROSE ) == 1, (
        f"PINNED_PROSE changed size ({len( PINNED_PROSE )}). Each entry waves through a real "
        f"multi-line occurrence — add one only with a written reason, the same bar as EXEMPT."
    )
    for ( rel, lineno ), pin in PINNED_PROSE.items():
        line = _read( rel ).splitlines()[ lineno - 1 ]
        assert SANDBOX_PROJECT_ID in line, f"{rel}:{lineno} no longer contains the id — stale pin"
        assert _line_pin( line ) == pin,   f"{rel}:{lineno} text changed — re-justify, then re-pin"


def test_the_reported_line_is_where_the_literal_sits_not_where_the_string_starts():
    """
    ast reports a triple-quoted constant at its OPENING QUOTES. For the live banner
    that is ten lines above the id. A failure message naming a line the literal is
    not on is how a reader concludes the guard is broken and stops trusting it.

    The expectation is DERIVED FROM THE SOURCE rather than computed by hand — a
    hand-computed offset is a second thing that can be wrong, and it was on the
    first draft of this test.
    """
    source = 'X = """a\nb\nc' + SANDBOX_PROJECT_ID + '"""\n'
    expected = next( n for n, line in enumerate( source.splitlines(), start=1 )
                       if SANDBOX_PROJECT_ID in line )

    node = ast.parse( source ).body[ 0 ].value
    assert node.lineno == 1, "premise: the constant opens on line 1"
    assert expected    == 3, "premise: the id sits two lines below that"
    assert _py_literal_lineno( node, node.value.find( SANDBOX_PROJECT_ID ) ) == expected

    one = ast.parse( f'X = "{SANDBOX_PROJECT_ID}"\n' ).body[ 0 ].value
    assert _py_literal_lineno( one, one.value.find( SANDBOX_PROJECT_ID ) ) == 1


def test_the_live_banner_would_report_the_line_the_id_is_actually_on():
    """
    The real file, not a fixture: gemini_client.py's banner constant opens at 37
    while the id sits at 47 — the ten-line gap this offset exists to close. It is
    also the line PINNED_PROSE is keyed on, so the offset being right is what makes
    the pin land on the right line at all.
    """
    src  = _read( "src/cosa/agents/presentation_generator/gemini_client.py" )
    node = next( n for n in ast.walk( ast.parse( src ) )
                   if isinstance( n, ast.Constant ) and isinstance( n.value, str )
                   and SANDBOX_PROJECT_ID in n.value )
    actual = next( n for n, line in enumerate( src.splitlines(), start=1 )
                     if SANDBOX_PROJECT_ID in line )
    assert node.lineno < actual, "premise gone — the constant no longer opens above the id"
    assert _py_literal_lineno( node, node.value.find( SANDBOX_PROJECT_ID ) ) == actual
    assert ( "src/cosa/agents/presentation_generator/gemini_client.py", actual ) in PINNED_PROSE


def test_an_unparseable_python_file_falls_back_rather_than_disarming():
    """
    A SyntaxError must not return [] — that would let a broken file hide a real
    assignment. It degrades to the line-based predicate, which still catches it.
    """
    text = f'def broken( :\nPROJECT_ID = "{SANDBOX_PROJECT_ID}"\n'
    assert len( _py_supplying_occurrences( "a/b.py", text ) ) == 1


def test_the_dispatcher_sends_python_to_ast_and_everything_else_to_the_line_scanner():
    """The routing itself, asserted — not assumed from the two predicates passing."""
    rel  = "src/cosa/agents/presentation_generator/gemini_client.py"
    text = _read( rel )
    assert supplying_occurrences_for( rel, text ) == [], "the .py path must clear the pinned banner"
    assert supplying_occurrences( text ) != [], (
        "the line-based path must still see the banner — that is the hole .py routing exists to close"
    )


def test_the_live_python_files_are_inert_and_still_name_the_id():
    """
    Pins WHY the tree is green, the same way the lupin-vm.sh control does. If
    someone adds a real assignment to either file the guard goes red, and this
    test documents that neither file was ever literal-free.
    """
    for rel in ( "src/cosa/agents/presentation_generator/gemini_client.py",
                 "src/cosa/tests/unit/agents/presentation_generator/test_gemini_client.py" ):
        text = _read( rel )
        assert SANDBOX_PROJECT_ID in text, f"premise gone — {rel} no longer names the id"
        assert supplying_occurrences_for( rel, text ) == [], f"a supplying occurrence appeared in {rel}"
        assert supplying_occurrences( text ) != [], (
            f"premise gone — {rel} no longer trips the LINE-based predicate, so it no "
            f"longer demonstrates why the .py path is needed"
        )


def test_guard_covers_the_vertex_toggle_script():
    """The script the Vertex design edits must be IN scope. It was absent from the legacy list."""
    assert VERTEX_TOGGLE_SCRIPT in scanned_files(), (
        f"{VERTEX_TOGGLE_SCRIPT} is not covered by the guard — the exact gap that let the "
        f"legacy three-item allowlist claim 'enforced forever' while ignoring it."
    )


def test_guard_is_a_strict_superset_of_the_legacy_bounded_allowlist():
    """Anti-regression: prove we never shrink back to a hand-maintained list."""
    scanned = set( scanned_files() )
    missing = [ f for f in LEGACY_BOUNDED_ALLOWLIST if f not in scanned ]
    assert not missing, f"guard no longer covers legacy-listed scripts: {missing}"
    assert len( scanned ) > len( LEGACY_BOUNDED_ALLOWLIST ), (
        "guard scans no more than the legacy bounded list — the inversion has been undone"
    )


def test_every_exemption_is_justified_and_still_needed():
    """
    An exemption must (a) name a real tracked file, (b) carry a written reason, and
    (c) still actually contain the id. A STALE exemption is itself a bounded-check
    smell — it silently widens the hole long after the reason evaporated.
    """
    tracked = set( _tracked_files() )
    for rel_path, reason in EXEMPT.items():
        assert rel_path in tracked, f"exemption names an untracked file: {rel_path}"
        assert reason.strip(), f"exemption without a written reason: {rel_path}"
        assert SANDBOX_PROJECT_ID in _read( rel_path ), (
            f"STALE EXEMPTION — {rel_path} no longer contains the id; delete the exemption "
            f"rather than leaving the hole open."
        )


def test_the_exemption_set_cannot_grow_silently():
    """
    T1 (Rio, stage-3 review) — the CLOSE for the one hole this guard still had.

    `test_every_exemption_is_justified_and_still_needed` validates each entry, but it
    validates whatever is THERE. Add a file carrying the id plus a plausible-sounding
    reason and every other test in this module still passes: the exemption list could
    grow silently, and "the only file that may name the sandbox id is the one that
    forbids it" was true today and enforced by nothing tomorrow.

    Pinning the SET makes growth a visible, deliberate diff to THIS assertion — you
    cannot widen the hole without editing the line that says the hole is one wide.
    """
    assert set( EXEMPT ) == { "src/tests/unit/test_no_hardcoded_gcp_identifiers.py" }, (
        f"the exemption set changed: {sorted( EXEMPT )}. Exactly ONE file may name the "
        f"sandbox project id — this guard, which must contain the literal to grep for it. "
        f"Every additional exemption re-opens the bounded-check hole this guard exists to "
        f"close. If a new exemption is genuinely warranted, changing this line is the "
        f"deliberate act that says so."
    )


def test_no_silent_default_for_the_project_id_in_shell_scripts():
    """
    `${LUPIN_GCP_PROJECT_ID:-<anything>}` is a SILENT default — it hands a caller a
    project without the caller choosing one. The doctrine (and cloud-run-config.sh)
    is fail-loud `${LUPIN_GCP_PROJECT_ID:?...}`. Assert no script reintroduces `:-`.
    """
    offenders = [
        f for f in scanned_files()
        if f.endswith( (".sh", ".bash") ) and "${LUPIN_GCP_PROJECT_ID:-" in _read( f )
    ]
    assert not offenders, (
        "silent `:-` default for LUPIN_GCP_PROJECT_ID (use fail-loud `:?`): " + ", ".join( offenders )
    )


def test_every_script_touching_the_project_id_fails_loud_or_sources_the_resolver():
    """
    Unbounded companion to the `:-` check: ANY shell script that references
    LUPIN_GCP_PROJECT_ID must either source the shared resolver (which carries the
    fail-loud `:?`) or use the `:?` form itself. Adding a new script cannot opt out.
    """
    offenders = []
    for rel_path in scanned_files():
        if not rel_path.endswith( (".sh", ".bash") ): continue
        body = _read( rel_path )
        if "LUPIN_GCP_PROJECT_ID" not in body: continue
        sources_resolver = "cloud-run-config.sh" in body
        fails_loud       = "${LUPIN_GCP_PROJECT_ID:?" in body
        if not ( sources_resolver or fails_loud ): offenders.append( rel_path )
    assert not offenders, (
        "script references LUPIN_GCP_PROJECT_ID without fail-loud `:?` and without sourcing "
        "cloud-run-config.sh: " + ", ".join( offenders )
    )


# The env vars that OUTRANK ANTHROPIC_VERTEX_PROJECT_ID for Vertex clients. A literal
# assignment to any of these can silently redirect metered traffic to the wrong project
# — the session runs, bills real money, and every project guard still reports green.
PRECEDENCE_STEALERS = ( "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS" )

# python:  os.environ["X"] = "literal"      shell:  export X=literal
# Assigning from a RESOLVED VARIABLE is fine (os.environ["X"] = project_id, export X="$FOO");
# baking in a literal is what steals precedence. So both patterns require a quote/word char
# that is not a `$` sigil.
_PY_LITERAL    = r"""os\.environ\[\s*["']{var}["']\s*\]\s*=\s*["'][^"'$]"""
_SHELL_LITERAL = r"""^\s*(?:export\s+)?{var}=(?!\s*["']?\$)["']?[A-Za-z0-9/._-]"""


def stealers_in( body ):
    """
    Which precedence-stealers does this file body assign to a LITERAL? (pure — no I/O)

    Extracted as a pure function on purpose. The offender-detection path is the ONE
    line in this guard that a clean tree never executes, so leaving it inline meant the
    only proof it worked was a falsification I ran once in /tmp and threw away. That is
    an unproven guard by my own definition. Pure + directly testable = the red path is
    re-proven on EVERY run, forever.
    """
    return [
        var for var in PRECEDENCE_STEALERS
        if re.search( _PY_LITERAL.format( var=re.escape( var ) ), body )
        or re.search( _SHELL_LITERAL.format( var=re.escape( var ) ), body, re.MULTILINE )
    ]


# Red-first fixtures, COMMITTED rather than discarded. Left column = injected code,
# right column = the stealers the guard must name. An empty list asserts the guard does
# NOT fire on the correct, variable-derived pattern — because a guard that cannot come
# out green on valid code is as broken as one that cannot come out red on bad code, and
# would simply get neutered by the next person it blocked.
_PRECEDENCE_FIXTURES = [
    ( 'os.environ["GOOGLE_CLOUD_PROJECT"] = "hello-world-foo-423219"', [ "GOOGLE_CLOUD_PROJECT" ] ),
    ( "os.environ[ 'GCLOUD_PROJECT' ] = 'some-other-project'",         [ "GCLOUD_PROJECT" ] ),
    ( "export GOOGLE_CLOUD_PROJECT=hello-world-foo-423219",            [ "GOOGLE_CLOUD_PROJECT" ] ),
    ( 'GCLOUD_PROJECT="hello-world-foo-423219"',                       [ "GCLOUD_PROJECT" ] ),
    ( "export GOOGLE_APPLICATION_CREDENTIALS=/home/me/keys/sa.json",   [ "GOOGLE_APPLICATION_CREDENTIALS" ] ),
    # ── the CORRECT patterns — derived from a variable, never a literal ──────────
    ( 'os.environ["GOOGLE_CLOUD_PROJECT"] = project_id',               [] ),
    ( 'export GOOGLE_CLOUD_PROJECT="$LUPIN_GCP_PROJECT_ID"',           [] ),
    ( "export GOOGLE_CLOUD_PROJECT=${LUPIN_GCP_PROJECT_ID:?set it}",   [] ),
    ( 'print( "nothing to see here" )',                                [] ),
]


@pytest.mark.parametrize( "body,expected", _PRECEDENCE_FIXTURES )
def test_precedence_guard_bites_on_literals_and_spares_derived_values( body, expected ):
    """
    RED-FIRST, AND COMMITTED. Proves the guard below could actually have come out
    otherwise — on a clean tree it reports green forever, and a green that could not
    have been red is the same defect as a red that could not have been green.
    """
    assert stealers_in( body ) == expected


def test_no_executable_surface_sets_a_vertex_precedence_stealer_to_a_literal():
    """
    THE INVERSION, APPLIED TO THE PRECEDENCE-STEALERS TOO.

    This test used to read ONE hardcoded path (src/tests/integration/conftest.py). That
    made it a BOUNDED check — armed only where it looked — sitting directly beneath an
    unbounded guard whose whole thesis is that a bounded check cannot support a
    completeness claim. It would have passed forever no matter what any OTHER file did:
    a new conftest, a new script, a new compose file could set GOOGLE_CLOUD_PROJECT to a
    literal tomorrow and this suite would stay green.

        I deleted modules.bats for being armed only where it looked, and then wrote a
        check that was armed only where IT looked, in the same commit.

    Same fix as the id guard: ask git what exists, not a human what to remember. The
    original conftest offender is still covered — it is simply no longer the ONLY thing
    covered.
    """
    offenders = [
        f"{rel_path} ({var})"
        for rel_path in scanned_files()
        for var in stealers_in( _read( rel_path ) )
    ]
    assert not offenders, (
        "a tracked executable surface assigns a LITERAL to a Vertex precedence-stealer "
        f"({'/'.join( PRECEDENCE_STEALERS )}). These OUTRANK ANTHROPIC_VERTEX_PROJECT_ID, so a "
        "literal here silently redirects metered Vertex traffic to the wrong project while every "
        "project guard reports green. Derive it from LUPIN_GCP_PROJECT_ID, or leave it to ADC. "
        "Offenders: " + ", ".join( offenders )
    )
