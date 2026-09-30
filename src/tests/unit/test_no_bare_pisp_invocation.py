"""
A lupin file must never hand a seat a planning-is-prompting command it cannot run.

🔴 THE DEFECT THIS CLOSES (row 0068d44b). CLAUDE.md § "A MEMENTO HAS TWO SLOTS" gave a
bare `memento_io.py write --slot root` as THE instruction for writing a memento. That
file lives in planning-is-prompting; a lupin seat cannot run it. NINE such sites were
found across four files, and the two worst were REMEDY STRINGS — text printed to a seat
at the moment it is already stuck, handing it a command that cannot work.

⚠️ THE FIX IS NOT A HABIT. Nine sites were repaired by hand; nothing stopped a tenth.
This guard is the control, because a rule that depends on remembering is not installed.
Its own provenance is the argument: an EARLIER draft of this file caught a ninth site a
careful manual pass had read past (`plan-memento.md:16`, an instruction buried
mid-sentence) — the instrument beat the human on exactly the case a human is worst at.

=== THE CORPUS RULE, AND WHY IT IS A RULE RATHER THAN AN EXCLUSION LIST ===

An exclusion list is a fudge factor: it grows every time a new R&D doc reddens the
guard, and a guard whose threshold gets tuned is one somebody deletes. So the corpus is
defined by a PROPERTY instead — does this file INSTRUCT a seat, or does it RECORD what
someone once did?

  INSTRUCTS (in scope)   CLAUDE.md · CLAUDE.local.md · .claude/** · src/docs/**
  RECORDS (out of scope) src/rnd/** · history/** · any path containing _archive/

🔴 THE RECORDS ARE EXCLUDED FOR A REASON THAT IS NOT CONVENIENCE. A file like
`src/rnd/v0.2.0/_archive/F/mementos/2026.08.24-john-84431ed3-memento.md` records what
somebody wrote on 2026-08-24. Editing it to satisfy this guard would FALSIFY A RECORD TO
MAKE A TEST PASS — strictly worse than the defect the test exists to catch. A record of
a bare command is evidence, not an instruction.

=== PYTHON IS HANDLED BY AST, NOT BY REGEX, AND THAT IS THE WHOLE TRICK ===

Three of the nine sites were Python: two remedy strings and one refusal message. But a
`.py` file also NAMES these commands constantly in docstrings and comments, and those
are prose — `memento_verify_tick.py:2` reads "The standing tick for `memento_io.py
verify`", which instructs nobody.

⇒ So for Python we walk the AST and inspect ONLY string literals that are NOT
docstrings. This is not a heuristic, it is a categorical separation:
  · comments never enter the AST at all, so they are excluded for free
  · docstrings are identifiable by position (first statement of module/class/function)
  · a remedy string returned to a caller is neither, so it IS inspected

Measured against the nine known sites: the AST rule admits all three Python offenders
and rejects all four Python prose mentions, with no exclusion list.

⚠️ f-strings are `ast.JoinedStr`, NOT `ast.Constant`. Every one of the three Python
sites is an f-string, so a walker that only handled Constant would have found ZERO of
them and passed clean. That is § A CLEAN EXIT IS NOT EVIDENCE waiting to happen, and it
is why `test_the_detector_finds_a_planted_bare_invocation` plants an f-string on purpose.
"""

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

# Real subcommands, read off `--help` on 2026-09-04 rather than guessed.
_SUBCOMMANDS = ( "write", "amend", "adopt", "resolve", "regenerate-pointer",
                 "migrate", "verify", "waivers" )

_INSTRUCTS = ( "CLAUDE.md", "CLAUDE.local.md" )
_INSTRUCT_DIRS = ( ".claude/", "src/docs/" )
_RECORD_DIRS   = ( "src/rnd/", "history/" )

# ⚠️ TESTS ARE EXCLUDED FOR A DIFFERENT REASON THAN RECORDS, so they are named
# separately rather than folded in. A test fixture is SYNTHETIC DATA — it instructs
# nobody, and a bare command inside one is a sample, not an order.
# Measured while scoping this guard: `src/tests/unit/test_reap_memento.py:356` builds a
# sample pointer carrying `python3 memento_io.py regenerate-pointer`. Every one of the 17
# REAL pointers on this box carries the QUALIFIED form, so that fixture has simply
# drifted from what the writer emits. Worth fixing on its own merits; not this guard's
# business, and forcing it in here would make the corpus rule un-statable.
_FIXTURE_DIRS  = ( "src/tests/", "src/cosa/tests/" )


def _repo_root():
    root = os.environ.get( "LUPIN_ROOT" )
    return Path( root ) if root else Path( __file__ ).resolve().parents[ 3 ]


def _pisp_script_names():
    """
    The p-is-p script basenames, read OFF DISK so a new script is covered without
    anyone remembering to add it here.

    Ensures:
        - returns a sorted list, or [] when planning-is-prompting is not on this box
    """
    root = os.environ.get( "PLANNING_IS_PROMPTING_ROOT" )
    if not root: return []
    scripts = Path( root ) / "workflow" / "scripts"
    if not scripts.is_dir(): return []
    return sorted( p.name for p in scripts.iterdir()
                   if p.is_file() and p.suffix in ( ".py", ".sh" ) )


def _in_scope( rel ):
    """
    Does this path INSTRUCT a seat (in scope) or RECORD what one did (out of scope)?

    Ensures:
        - a record path is out of scope even when it also matches an instruct prefix
        - `_archive/` anywhere in the path is a record
    """
    if "_archive/" in rel: return False
    if any( rel.startswith( d ) for d in _RECORD_DIRS ): return False
    if any( rel.startswith( d ) for d in _FIXTURE_DIRS ): return False
    if rel in _INSTRUCTS: return True
    if any( rel.startswith( d ) for d in _INSTRUCT_DIRS ): return True
    return rel.endswith( ".py" )          # Python anywhere — AST-filtered below


def _pattern( names ):
    alt  = "|".join( re.escape( n ) for n in names )
    subs = "|".join( re.escape( s ) for s in _SUBCOMMANDS )
    return re.compile( rf"(?<![/\w.-])({alt})\s+(?:(?:{subs})\b|--?\w)" )


def _bare_in_text( text, pat ):
    return [ ( i, m.group( 0 ).strip() )
             for i, line in enumerate( text.splitlines(), start=1 )
             for m in pat.finditer( line ) ]


def _docstring_nodes( tree ):
    """Every string node that IS a docstring — the set we must NOT inspect."""
    out = set()
    for node in ast.walk( tree ):
        if not isinstance( node, ( ast.Module, ast.ClassDef,
                                   ast.FunctionDef, ast.AsyncFunctionDef ) ):
            continue
        body = getattr( node, "body", [] )
        if body and isinstance( body[ 0 ], ast.Expr ) and \
           isinstance( body[ 0 ].value, ast.Constant ) and \
           isinstance( body[ 0 ].value.value, str ):
            out.add( id( body[ 0 ].value ) )
    return out


def _bare_in_python( text, pat ):
    """
    Bare invocations inside NON-DOCSTRING string literals only.

    Ensures:
        - comments are excluded (they are not in the AST)
        - docstrings are excluded (identified by position)
        - f-strings ARE inspected — they are JoinedStr, and every real offender is one
        - a file that will not parse yields [] rather than raising
    """
    try:
        tree = ast.parse( text )
    except SyntaxError:
        return []
    skip = _docstring_nodes( tree )

    # ⚠️ AN f-STRING'S LITERAL CHUNKS ARE ALSO ast.Constant NODES, and `ast.walk` yields
    # BOTH the JoinedStr and each Constant inside it. Counting both double-reports every
    # f-string offender. Measured: the AST arm returned 2 hits for one planted remedy
    # before this skip existed, and the sweep listed :333 and :338 twice each.
    # ⇒ The positive control caught this, which is the entire argument for running it
    #   FIRST — an inflated count in the sweep alone would have read as "more offenders"
    #   rather than as a broken instrument.
    for node in ast.walk( tree ):
        if isinstance( node, ast.JoinedStr ):
            for v in node.values:
                if isinstance( v, ast.Constant ): skip.add( id( v ) )

    hits = []
    for node in ast.walk( tree ):
        if isinstance( node, ast.Constant ) and isinstance( node.value, str ):
            if id( node ) in skip: continue
            chunks = [ node.value ]
        elif isinstance( node, ast.JoinedStr ):
            chunks = [ v.value for v in node.values
                       if isinstance( v, ast.Constant ) and isinstance( v.value, str ) ]
        else:
            continue
        for chunk in chunks:
            for m in pat.finditer( chunk ):
                hits.append( ( getattr( node, "lineno", 0 ), m.group( 0 ).strip() ) )
    return sorted( set( hits ) )


@pytest.fixture( scope="module" )
def pat():
    names = _pisp_script_names()
    if not names:
        pytest.skip( "PLANNING_IS_PROMPTING_ROOT unset or its scripts dir absent — this "
                     "guard has nothing to search FOR, which is NOT the same as finding "
                     "nothing. Skipping loudly beats reporting a clean zero." )
    return _pattern( names )


def test_the_detector_finds_a_planted_bare_invocation( pat ):
    """
    🔴 THE POSITIVE CONTROL, AND IT RUNS FIRST.

    An empty result is two different failures wearing one face — a clean corpus, or a
    broken search — and nothing in a zero says which. So the detector is shown returning
    a POSITIVE on planted text before any zero below is allowed to mean anything, and
    shown staying SILENT on the forms that must not trip it.
    """
    assert _bare_in_text( "memento_io.py write --slot root\n", pat ), \
        ( "the detector missed a DELIBERATELY PLANTED bare invocation — every clean "
          "result this file reports is therefore worthless" )

    assert not _bare_in_text(
        "python3 $PLANNING_IS_PROMPTING_ROOT/workflow/scripts/memento_io.py write\n", pat ), \
        ( "the detector flagged the QUALIFIED form — it would redden on the fix itself, "
          "and a guard that cannot be made green is a guard somebody deletes" )

    # PYTHON ARM — an f-string remedy is caught; a docstring and a comment are not.
    src = (
        '"""The standing tick for `memento_io.py verify` — a docstring, not an order."""\n'
        '# a comment mentioning memento_io.py verify\n'
        'def f( repo ):\n'
        '    return f"run by hand: memento_io.py verify --repo {repo}"\n'
    )
    hits = _bare_in_python( src, pat )
    assert len( hits ) == 1, (
        f"the AST arm found {len( hits )} hit(s), expected exactly 1 — it must catch the "
        f"f-string REMEDY and ignore the docstring and the comment. f-strings are "
        f"JoinedStr, not Constant; a walker handling only Constant finds ZERO here and "
        f"passes clean, which is the failure this arm exists to prevent. Got: {hits}" )
    assert "verify" in hits[ 0 ][ 1 ]


def test_the_corpus_rule_admits_instructions_and_excludes_records():
    """
    The scope is a RULE, not an exclusion list — so the rule itself is asserted.

    ⚠️ A record is excluded because editing one to satisfy a guard would FALSIFY IT.
    That is a stronger claim than "it is noisy", and it deserves its own arm.
    """
    assert _in_scope( "CLAUDE.md" )
    assert _in_scope( ".claude/commands/plan-memento.md" )
    assert _in_scope( "src/docs/anything.md" )
    assert _in_scope( "src/lupin_mcp/memento_slot.py" )

    assert not _in_scope( "src/rnd/v0.2.0/2026.08.29-memento-header-drift-root-cause.md" )
    assert not _in_scope( "history/2026-08-14-to-20-history.md" )
    assert not _in_scope( "src/rnd/v0.2.0/_archive/F/mementos/2026.08.24-john-memento.md" )
    assert not _in_scope( "src/tests/unit/test_reap_memento.py" )


def test_no_instructing_file_hands_a_seat_an_unrunnable_pisp_command( pat ):
    """
    The sweep.

    Ensures:
        - no in-scope file invokes a p-is-p script with no path in front of it
        - the corpus SIZE is asserted, so a sweep that searched nothing cannot pass
    """
    root  = _repo_root()
    out   = subprocess.run( [ "git", "ls-files" ], cwd=root, capture_output=True,
                            text=True, check=True ).stdout
    files = [ f for f in out.splitlines() if f and _in_scope( f ) ]

    # THE DENOMINATOR, ASSERTED. A loop over nothing passes every assertion inside it.
    assert len( files ) > 500, (
        f"only {len( files )} in-scope files under {root} — this guard is reporting on a "
        f"corpus that cannot be the lupin repo, so its clean result means nothing" )

    offenders = []
    for rel in files:
        p = root / rel
        try:
            text = p.read_text( encoding="utf-8", errors="ignore" )
        except ( OSError, UnicodeDecodeError ):
            continue
        found = _bare_in_python( text, pat ) if rel.endswith( ".py" ) \
                else _bare_in_text( text, pat )
        offenders += [ f"{rel}:{ln}: {m}" for ln, m in found ]

    assert not offenders, (
        f"{len( offenders )} place(s) hand a lupin seat a planning-is-prompting command "
        f"with no path in front of it (corpus: {len( files )} in-scope files):\n  "
        + "\n  ".join( offenders )
        + "\n\nFix: prefix with $PLANNING_IS_PROMPTING_ROOT/workflow/scripts/ — the env "
          "var is documented in the global CLAUDE.md under Environment Configuration." )
