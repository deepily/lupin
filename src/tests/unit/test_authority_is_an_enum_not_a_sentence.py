#!/usr/bin/env python3
"""
`authority` is a String(32) enum column; `reason` is unbounded Text. Prose belongs
in the second, and a value that does not fit the first must fail here rather than at
the database.

🔴 THE DEFECT THIS EXISTS FOR. The transition door built its authority as
`f"{payload.authority} · {promotion_approval.authority_suffix()}"` — a descriptive
sentence appended to an already-validated enum, while `reason` was left NULL.

⚠️ AND THE PLACEMENT IS THE WHOLE LESSON: `payload.authority` IS validated against
`rules.VALID_AUTHORITIES` at the door. The concatenation happened DOWNSTREAM of that
check, so validation passed and the column still received 60+ characters. **A guard on
the input cannot see a field the code lengthens afterwards** — which is why the arms
below measure what is WRITTEN, not what was accepted.

The fix was NOT to widen the column. Widening would make the sentence fit and leave
`reason` empty, i.e. keep the prose in the enum column permanently.
"""

import re

from pathlib import Path

import pytest

from sqlalchemy import String

import cosa.rest.task_store_rules as rules
from cosa.rest.postgres_models import TaskEvent
from cosa.rest.task_promotion_gate import PromotionApproval


# HAND-WRITTEN, and that is the point: the model is the thing under test, so the
# expected side must not be read out of it. 32 is also the value Mr Radio ruled must
# not be widened — a silent widening is a change to that ruling and reddens here.
AUTHORITY_COLUMN_WIDTH = 32


def _strip_python_comments( source ):
    """
    `source` with its `#` comments removed, so an assertion is made about the CODE
    rather than about the prose describing it.

    🔴 THIS EXISTS BECAUSE THE GUARD BELOW CAUGHT ITS OWN DOCUMENTATION. The fix in
    `tasks.py` carries a comment quoting the line it replaced, and the regex matched
    the QUOTE — reporting a defect that had just been removed. The repo already names
    this trap for JavaScript (`strip_js_comments`, three instances in one sitting); it
    is the same trap in Python and it fired on this guard's first run.

    ⚠️ TOKENIZE, NOT A REGEX. A naive `#`-strip eats the character inside string
    literals, trading a false positive for a silent false negative — the worse
    direction.

    Ensures:
        - COMMENT tokens removed; string literals and code untouched
        - returns the source unchanged if it does not tokenize, so a syntax error
          surfaces as a real failure rather than as a vacuous pass
    """
    import io, tokenize
    try:
        toks = [ t for t in tokenize.generate_tokens( io.StringIO( source ).readline )
                 if t.type != tokenize.COMMENT ]
        return tokenize.untokenize( toks )
    except Exception:
        return source


def test_the_authority_column_is_still_thirty_two_and_was_not_widened():
    """Widening the column is the fix that was explicitly refused."""
    col = TaskEvent.__table__.c.authority
    assert isinstance( col.type, String ), f"authority is no longer a String: {col.type!r}"
    assert col.type.length == AUTHORITY_COLUMN_WIDTH, (
        f"the authority column is now String({col.type.length}), not String({AUTHORITY_COLUMN_WIDTH}). "
        f"Widening it makes a descriptive sentence FIT, which keeps prose in an enum "
        f"column and leaves `reason` — Text, unbounded — empty. That fix was refused."
    )


def test_the_reason_column_is_unbounded_so_prose_has_somewhere_to_go():
    """The other half of the contract: this is where a sentence belongs."""
    col = TaskEvent.__table__.c.reason
    assert getattr( col.type, "length", None ) is None, (
        f"reason is now length-bounded ({col.type!r}); the prose displaced out of "
        f"`authority` has nowhere to go and the defect comes back one column over"
    )


@pytest.mark.parametrize( "authority", rules.VALID_AUTHORITIES )
def test_every_legal_authority_fits_the_column( authority ):
    """A legal value that does not fit would be a defect in the enum, not in a caller."""
    assert len( authority ) <= AUTHORITY_COLUMN_WIDTH, (
        f"'{authority}' is {len( authority )} chars and cannot be stored in "
        f"String({AUTHORITY_COLUMN_WIDTH})"
    )


def test_the_promotion_note_would_OVERFLOW_if_it_were_ever_appended_again():
    """
    🔴 THE POSITIVE CONTROL, and without it the arm below proves nothing.

    Every arm here would pass over an empty set of notes, and a note that happened to
    be short would make the concatenation harmless — in which case a test forbidding
    it is guarding nothing. This asserts the hazard is real BEFORE asserting the code
    avoids it: every legal authority, combined with every note the gate can produce,
    exceeds the column.
    """
    notes = set()
    # Drive the real object rather than restating its strings here — a copy of the
    # wording in this file would agree with itself forever.
    import cosa.rest.task_promotion_gate as gate
    for source in ( gate.APPROVAL_DEFAULT, gate.APPROVAL_SELF, "keypress" ):
        approval = PromotionApproval( allowed=True, refusal=None, approval_source=source )
        notes.add( approval.authority_suffix() )

    assert len( notes ) >= 2, f"expected several distinct notes, got {notes!r} — nothing to overflow with"

    overflowing = [ ( a, n ) for a in rules.VALID_AUTHORITIES for n in notes
                    if len( f"{a} · {n}" ) > AUTHORITY_COLUMN_WIDTH ]
    assert len( overflowing ) == len( rules.VALID_AUTHORITIES ) * len( notes ), (
        f"only {len( overflowing )} of {len( rules.VALID_AUTHORITIES ) * len( notes )} "
        f"combinations overflow — the hazard this guard forbids is no longer universal, "
        f"so re-derive whether the ban still earns its place"
    )


def test_the_transition_door_does_not_append_prose_to_authority():
    """
    The arm that would have caught it. Reads the shipped router and requires that the
    value handed to `authority=` is not built by concatenation.

    ⚠️ SCOPED TO THE DOOR, not to the file. An unscoped search would match any f-string
    anywhere and pass or fail for reasons having nothing to do with this defect.
    """
    src  = Path( __file__ ).resolve().parents[ 2 ] / "cosa" / "rest" / "routers" / "tasks.py"
    text = _strip_python_comments( src.read_text( encoding="utf-8" ) )

    # POSITIVE CONTROL on the corpus: the door must actually be in the file we read.
    assert "transition_authority" in text, \
        "the transition door's authority variable is gone — this guard is reading the wrong file or a renamed door"

    offenders = re.findall( r"transition_authority\s*=\s*f?[\"'].*?[\"']", text )
    interpolated = [ o for o in offenders if "{" in o ]
    assert not interpolated, (
        f"the transition door builds `authority` by interpolation: {interpolated}. "
        f"`authority` is a String({AUTHORITY_COLUMN_WIDTH}) enum — anything appended to "
        f"a validated value bypasses the validation, because the check ran first. The "
        f"note belongs in `reason`."
    )

    # ...and the note must still be recorded SOMEWHERE, or the fix silently dropped
    # Rick's keypress-vs-default distinction instead of relocating it.
    assert "transition_reason" in text, \
        "the promotion note is no longer recorded at all — the distinction Rick required was dropped, not moved"
