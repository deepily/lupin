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
    """
    hits = []
    for lineno, raw in enumerate( text.splitlines(), start=1 ):
        code = _strip_shell_comment( raw )
        idx  = code.find( SANDBOX_PROJECT_ID )
        if idx == -1: continue
        if _is_inert_error_message( code, idx ): continue
        hits.append( ( lineno, raw.strip() ) )
    return hits


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
    offenders = { f: supplying_occurrences( _read( f ) ) for f in scanned_files() }
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
