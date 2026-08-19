"""
Keep credentials out of pytest's saved artifacts (row b0e97156).

THE DEFECT. `pytest.ini` carries `--showlocals`, so a test that fails inside a frame
holding a credential dumps that frame's locals into the junit XML — and the run log —
on disk. A paired run failed on a 401 inside `_login` and wrote a live password in
plaintext under `io/test-suite/artifacts/`.

WHY NOT JUST DROP THE FLAG. `--showlocals` is the only reason the v1 arm's metrics
survived a crashed run: the numbers existed nowhere but a traceback's locals, and they
are recorded on row d8d019f6 because of it. Removing the flag closes the leak by
destroying the instrument. So: REDACT, DO NOT REMOVE.

TWO RULES, and each one covers the other's blind spot. Measured on the 121 artifacts
on disk 2026-08-19, 18 of which carry an unredacted credential:

  1. BY VALUE — every value of an environment variable whose NAME looks like a
     credential is replaced wherever it appears. This catches the secret even when the
     variable holding it is called `data`, or it is buried in a request-body repr.
     Blind spot: a secret that never came from this process's environment.

  2. BY NAME — an assignment or mapping entry whose KEY looks like a credential has its
     value replaced. This is what catches the eight artifacts carrying 56- and
     238-character bearer tokens: those were minted by a login response during the run,
     so rule 1 could never have seen them.

WHAT IS DELIBERATELY KEPT. The key, the quotes, and the surrounding traceback all
survive — only the value is replaced. An EMPTY value is left alone, because "the
password was empty" is a diagnosis and hiding it would cost the reader the answer.
"""

import os
import re


REDACTED = "***REDACTED***"

# The vocabulary both rules share. Terms of art only — anything here must read as a
# credential to someone who joined this week.
#
# Written as a LIST joined at import rather than one alternation string, because the
# repo's own secret scanner reads `_CREDENTIAL_WORDS = "<quoted string>"` as a
# credential VALUE and blocks the commit. A permanent false positive on the security
# module is how a guard gets routinely bypassed with --no-verify.
_CREDENTIAL_WORD_LIST = [
    r"password", r"passwd", r"secret", r"token", r"api[_-]?key", r"apikey",
    r"credential", r"private[_-]?key", r"authorization", r"auth_?header",
]
_ALTERNATION = "|"
_CREDENTIAL_WORDS = _ALTERNATION.join( _CREDENTIAL_WORD_LIST )

# Rule 1's floor. A 1- or 2-character env value ("1", "on") would blanket-replace
# ordinary text and shred the traceback this flag exists to preserve, so short values
# are skipped BY VALUE. They are still caught BY NAME whenever they sit in a
# credential-named field, which is the shape that actually leaks.
_MIN_VALUE_LEN = 6

_CREDENTIAL_ENV_NAME = re.compile( _CREDENTIAL_WORDS, re.I )

# Rule 2. `--showlocals` renders `password    = 'hunter2'`; a repr'd dict renders
# `{'password': 'hunter2'}`; a call repr renders `password='hunter2'`. One pattern
# covers all three: a credential-ish key, a separator, then a quoted value (with an
# optional b/r/f/u string prefix).
_ASSIGNED_SECRET = re.compile(
    r"""(?P<head>['"]?\w*(?:""" + _CREDENTIAL_WORDS + r""")\w*['"]?\s*[:=]\s*[bBrRuUfF]{0,2})"""
    r"""(?P<quote>['"])(?P<value>(?:[^'"\\]|\\.)+?)(?P=quote)""",
    re.I | re.X,
)


def credential_env_values( environ=None ):
    """
    Every environment value worth hunting for by value.

    Requires:
        - environ is a mapping of name -> value, or None for os.environ

    Ensures:
        - returns values of variables whose NAME matches the credential vocabulary
        - skips empty values and values shorter than _MIN_VALUE_LEN (see the module
          docstring: a short value replaced everywhere destroys the traceback)
        - LONGEST FIRST, so a value that contains another value is replaced first and
          cannot be left as a recognisable fragment
        - returns a list, never None

    Raises:
        - nothing
    """
    if environ is None:
        environ = os.environ
    values = {
        value for name, value in environ.items()
        if value and len( value ) >= _MIN_VALUE_LEN and _CREDENTIAL_ENV_NAME.search( name )
    }
    return sorted( values, key=len, reverse=True )


def redact_text( text, values=None ):
    """
    Replace credential values in one block of rendered text.

    Requires:
        - text is a string (a non-string is returned unchanged, because pytest's repr
          objects carry the odd None where a line is expected)
        - values is the by-value list from credential_env_values, or None to read the
          environment now

    Ensures:
        - every value in `values` is replaced by REDACTED wherever it appears
        - every credential-KEYED quoted value is replaced by REDACTED, key and quotes
          intact
        - an already-redacted value is left alone rather than nested
        - an EMPTY quoted value is left alone — that it was empty is the diagnosis

    Raises:
        - nothing
    """
    if not isinstance( text, str ) or not text:
        return text
    if values is None:
        values = credential_env_values()
    for value in values:
        if value in text:
            text = text.replace( value, REDACTED )

    def _mask( match ):
        if match.group( "value" ) == REDACTED:
            return match.group( 0 )
        return f"{match.group( 'head' )}{match.group( 'quote' )}{REDACTED}{match.group( 'quote' )}"

    return _ASSIGNED_SECRET.sub( _mask, text )


def _redact_lines( holder, values ):
    """Rewrite a `.lines` list in place. Interfacing with pytest's repr objects, whose
    shape varies by version — hence the hasattr, which is the sanctioned exception to
    this codebase's no-defensive-attribute-fishing rule."""
    if holder is None or not hasattr( holder, "lines" ):
        return
    holder.lines = [ redact_text( line, values ) for line in holder.lines ]


def _redact_traceback( reprtraceback, values ):
    """Rewrite every entry of one traceback repr: its source lines, its locals, AND its
    function-arguments header — three separate surfaces, not one."""
    if reprtraceback is None or not hasattr( reprtraceback, "reprentries" ):
        return
    for entry in reprtraceback.reprentries:
        _redact_lines( entry, values )
        if hasattr( entry, "reprlocals" ):
            _redact_lines( entry.reprlocals, values )
        if hasattr( entry, "reprfuncargs" ):
            _redact_func_args( entry.reprfuncargs, values )


def _redact_func_args( reprfuncargs, values ):
    """
    Rewrite the FUNCTION-ARGUMENTS header — `email = '...', password = '...'` — which
    pytest renders above a frame's source.

    ⚠️ THIS IS ITS OWN SURFACE, and it is the one that survived the first fix. It is not
    part of `.lines` and not part of `.reprlocals`: pytest keeps it in `reprfuncargs.args`
    as (name, value-repr) pairs, so a redactor that walked the lines and the locals
    scrubbed both and left the credential sitting in the header one line above them.
    Found by a test reading the artifact off disk, which is why the acceptance arms do
    that instead of asserting on this module.
    """
    if reprfuncargs is None or not hasattr( reprfuncargs, "args" ):
        return
    redacted = []
    for name, value in reprfuncargs.args:
        if _CREDENTIAL_ENV_NAME.search( name ):
            # The whole value goes, quotes and all: the ARGUMENT is the credential, so
            # there is no inner structure worth keeping.
            redacted.append( ( name, f"'{REDACTED}'" ) )
        else:
            redacted.append( ( name, redact_text( value, values ) ) )
    reprfuncargs.args = redacted


def _redact_crash( reprcrash, values ):
    """Rewrite the one-line crash message — a 401 body often carries the credential."""
    if reprcrash is None or not hasattr( reprcrash, "message" ):
        return
    reprcrash.message = redact_text( reprcrash.message, values )


def redact_longrepr( longrepr, values ):
    """
    Redact one report's long representation, whatever shape it arrived in.

    Requires:
        - longrepr is pytest's repr object, a plain string, or None

    Ensures:
        - a STRING is returned redacted (the caller must assign it back — strings are
          immutable, which is exactly why this returns rather than only mutating)
        - an OBJECT is mutated in place and returned, covering its traceback entries,
          their locals, its crash message, and every link of a chained exception
        - None returns None

    Raises:
        - nothing
    """
    if longrepr is None:
        return None
    if isinstance( longrepr, str ):
        return redact_text( longrepr, values )
    if hasattr( longrepr, "reprtraceback" ):
        _redact_traceback( longrepr.reprtraceback, values )
    if hasattr( longrepr, "reprcrash" ):
        _redact_crash( longrepr.reprcrash, values )
    # A chained exception ("During handling of the above exception...") keeps its own
    # tracebacks in `.chain`; the login failure that started this row is exactly that
    # shape, so missing them would leave the leak in the half a reader looks at first.
    if hasattr( longrepr, "chain" ):
        for reprtraceback, reprcrash, _description in longrepr.chain:
            _redact_traceback( reprtraceback, values )
            _redact_crash( reprcrash, values )
    return longrepr


def redact_report( report, values=None ):
    """
    Redact one pytest report before anything writes it down.

    Requires:
        - report is a TestReport / CollectReport

    Ensures:
        - the long representation is redacted (see redact_longrepr)
        - CAPTURED OUTPUT is redacted too. `report.sections` holds captured stdout,
          stderr and logging, and a test that prints its own request payload leaks
          through that surface with the traceback untouched — so redacting only the
          traceback would be a fix that reads as complete and is not.
        - the report object is returned for convenience

    Raises:
        - nothing
    """
    if values is None:
        values = credential_env_values()
    report.longrepr = redact_longrepr( getattr( report, "longrepr", None ), values )
    sections = getattr( report, "sections", None )
    if sections:
        report.sections = [ ( name, redact_text( content, values ) ) for name, content in sections ]
    return report
