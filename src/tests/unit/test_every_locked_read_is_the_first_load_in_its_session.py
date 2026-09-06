#!/usr/bin/env python3
"""
No `get_by_id_for_update` call may be preceded by a load of the SAME row in the
same session — derived from the tree, not from a list somebody maintains.

⚠️ THE FILENAME SAYS "first load in its session" AND THAT IS THE FIRST CUT'S
WORDING, KEPT ONLY BECAUSE RENAMING A FILE MID-REVIEW COSTS MORE THAN IT BUYS.
The predicate is narrower and this docstring, not the filename, is the contract.

WHY THIS EXISTS. `TaskRepository.get_by_id_for_update` now calls
`.populate_existing()`, which under autoflush=False (both session factories:
db/database.py:245-249 and :280) OVERWRITES a pending unflushed in-memory edit
with the database row. That is correct for load-validate-write and would be
silent data loss for a caller re-reading a row it had already edited. The
method's Requires clause says so; this makes the saying checkable.

THE CENSUS THAT PROMPTED IT. The docstring used to read "all four current
callers take it as their first statement in a fresh session, so none is
exposed" — a count taken at one moment, written in the tense that closes the
question. Tiberius (seat 36bf20bb) reported a FIFTH call site on his branch at
src/cosa/rest/task_promotion_resolver.py:433, absent from this tree. His
suggestion, taken here: make it a PREDICATE that enumerates from the tree, so a
sixth cannot arrive unnoticed.

⚠️ AND DELIBERATELY NOT A COUNT. Asserting "there are four" would be an
enumeration standing in for a predicate — the same defect one level down. It
would redden on every legitimate new caller while saying nothing about whether
that caller is safe. What is asserted is the PROPERTY.

⚠️ AND THE PROPERTY WAS NARROWED ONCE ALREADY, IN THE ACCUSING DIRECTION.
The first cut asserted "nothing may precede the locked read", which is stricter
than safety needs; Tiberius 👑 showed it would falsely accuse his resolver, which
loads OTHER rows first and never that one. A guard that accuses safe code gets
deleted, and then it guards nothing. See _loads_the_same_identity.

⚠️ WHAT THIS DOES NOT COVER, said rather than implied. It can judge a call site
whose session is opened in the same function by `with get_db()`. A caller handed
a session from OUTSIDE — a resolver sweeping rows, which is exactly the shape
Tiberius's site has — can be dirty before this function is ever entered, and no
AST walk of the call site can see that. Such a call site is REPORTED here rather
than passed over, so it cannot arrive silently.

🔴 A COMPANION EXISTS AND IT IS STRICTER, AND THE PAIR IS THE POINT — Tiberius
👑's ruling, and it settles what looked like a contradiction. His
task_promotion_resolver.py carries a RUNTIME check that raises if the session's
identity map is NON-EMPTY before the first read. That is a WHOLE-SESSION
emptiness check, not a per-row one, and it fires before anything is loaded.

⇒ It is the runtime form of THIS FILE'S FIRST CUT — the strict version he made
me narrow. Both positions are right, and which one is right depends on WHO OWNS
THE SESSION:

    strict "nothing loaded yet"   ✅ correct as a RUNTIME invariant an author
                                     asserts about a session HE controls
                                  🔴 wrong as a STATIC accusation against every
                                     call site in the tree, because it reddens
                                     safe code and a guard that does that gets
                                     deleted

⇒ SO HIS IS A COMPANION, NOT A REPLACEMENT, AND THIS FILE IS NOT A REPLACEMENT
FOR HIS. His checks the real property on one session and cannot be fooled by two
expressions naming one row; this one checks an approximation of it across the
whole tree and cannot see runtime identity at all. Neither subsumes the other.

:7999-eligible: pure AST over the tree, no import of the code under test, no
server, milliseconds.
"""
import ast
import os
import sys
from pathlib import Path

_lupin_root = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
_src        = _lupin_root / "src"
if str( _src ) not in sys.path:
    sys.path.insert( 0, str( _src ) )

METHOD = "get_by_id_for_update"


def _python_files():
    """
    Every .py under src/cosa, minus vendored trees.

    src/cosa/.venv is 92% of any disk-derived sweep of this repo (CLAUDE.md,
    measured 2026-08-30), so walking it would be slow and would report on an
    interpreter this project does not run.
    """
    skip = { ".venv", "node_modules", "site-packages", "__pycache__" }
    for path in ( _src / "cosa" ).rglob( "*.py" ):
        if skip.isdisjoint( path.parts ): yield path


def _call_sites():
    """
    Every `.get_by_id_for_update(` call in the tree, with what preceded it.

    Requires:
        - $LUPIN_ROOT names the tree to judge (pin it from a worktree)

    Ensures:
        - returns one dict per call site: path, lineno, whether its enclosing
          `with` opens a session via get_db(), and the statements preceding it
          inside that block
        - a file that does not parse is skipped rather than failing this walk
    """
    found = []
    for path in _python_files():
        try:
            tree = ast.parse( path.read_text( encoding="utf-8" ) )
        except SyntaxError:
            continue

        for node in ast.walk( tree ):
            if not isinstance( node, ast.With ): continue

            opens_a_session = any(
                isinstance( item.context_expr, ast.Call )
                and getattr( item.context_expr.func, "id", None ) == "get_db"
                for item in node.items
            )
            for index, stmt in enumerate( node.body ):
                for inner in ast.walk( stmt ):
                    if ( isinstance( inner, ast.Call )
                         and isinstance( inner.func, ast.Attribute )
                         and inner.func.attr == METHOD ):
                        found.append( {
                            "path"      : path.relative_to( _lupin_root ).as_posix(),
                            "lineno"    : inner.lineno,
                            "in_get_db" : opens_a_session,
                            "preceding" : node.body[ :index ],
                            "id_arg"    : ast.dump( inner.args[ 0 ] ) if inner.args else "",
                        } )
    return found


def _loads_the_same_identity( stmt, id_arg_dump ):
    """
    Does this preceding statement read a row by the SAME id expression?

    THE PREDICATE NARROWED, AT TIBERIUS 👑's REQUEST AND HE WAS RIGHT. The first
    cut asserted "nothing at all may precede the locked read", which is stricter
    than safety needs and would have FALSELY ACCUSED his
    task_promotion_resolver.py:433 — a site that loads other rows first but
    never that one, and whose session additionally raises RuntimeError if its
    identity map is non-empty before the first read.

    ⇒ The hazard is not "the session did something". It is "the session already
    holds THIS row" — pocholo 📣's precondition is a LIVE REFERENCE TO THE ROW,
    and the identity map is weak, so loading a DIFFERENT row is harmless.

    ⚠️ AND THIS IS A STATIC APPROXIMATION OF A RUNTIME FACT, SAID PLAINLY.
    Identity is a value at runtime; an AST can only compare the id EXPRESSION.
    Two different expressions naming the same row read as different here, so
    this UNDER-reports. It is deliberately tuned that way: a guard that falsely
    accuses safe code gets deleted, and then it guards nothing at all.
    """
    if not isinstance( stmt, ast.Assign ): return False
    for inner in ast.walk( stmt ):
        if ( isinstance( inner, ast.Call )
             and isinstance( inner.func, ast.Attribute )
             and inner.func.attr.startswith( ( "get_by_id", "get_", "find_" ) )
             and inner.args
             and ast.dump( inner.args[ 0 ] ) == id_arg_dump ):
            return True
    return False


def test_the_walk_finds_the_call_sites_at_all():
    """
    POSITIVE CONTROL, and it is not ceremony: a walk that finds nothing passes
    every per-item assertion below, and this file would report a clean green
    over an empty corpus. Same defect as an empty grep read as a negative
    result — the failure and the success print identically.
    """
    sites = _call_sites()
    assert len( sites ) >= 3, (
        f"the walk found {len( sites )} call sites of {METHOD}; it is supposed "
        f"to find several. Either the method was renamed, or this walk no "
        f"longer reaches the tree — in both cases the guards below mean nothing."
    )


def test_no_locked_read_is_preceded_by_a_load_of_the_same_row():
    """
    THE PREDICATE. No statement before the locked read may load the SAME row in
    the same session. If one does, that session holds a live reference, and
    populate_existing then either discards an unflushed edit or hands back an
    object the caller had already read — which is the whole hazard.

    NOT "nothing may precede it". That was the first cut and it was wrong in the
    accusing direction; see _loads_the_same_identity for why and who caught it.
    """
    offenders = []
    for site in _call_sites():
        bad = [ ast.dump( stmt )[ :90 ] for stmt in site[ "preceding" ]
                if _loads_the_same_identity( stmt, site[ "id_arg" ] ) ]
        if bad:
            offenders.append( f"{site[ 'path' ]}:{site[ 'lineno' ]} preceded by {bad}" )

    assert not offenders, (
        f"{METHOD} must not be preceded by a load of the SAME row in the same "
        f"session — see its Requires clause. These call sites are:\n  "
        + "\n  ".join( offenders )
    )


def test_a_locked_read_outside_a_get_db_block_is_reported_not_ignored():
    """
    THE SHAPE THIS FILE CANNOT JUDGE, SURFACED RATHER THAN SKIPPED. A call site
    whose session comes from outside the function may already be dirty on entry,
    and no AST walk of the call site can see that. Reporting it is the honest
    outcome: a human then has to read that call site instead of inheriting a
    green.
    """
    unjudgeable = [ f"{site[ 'path' ]}:{site[ 'lineno' ]}" for site in _call_sites()
                    if not site[ "in_get_db" ] ]

    assert not unjudgeable, (
        f"{METHOD} is called where this guard cannot see whether the session is "
        f"already dirty (no `with get_db()` in the same function):\n  "
        + "\n  ".join( unjudgeable )
        + "\n\nThis is NOT automatically a bug. It means a human must read that "
          "call site and confirm the session it is handed holds no live "
          "reference to the row. If it is safe, say so at the call site and "
          "widen this guard deliberately."
    )
