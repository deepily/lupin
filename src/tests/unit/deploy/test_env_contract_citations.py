"""
env-contract.tsv note citations must point at a line that names the variable.

THE SHAPE (row a859646f)
------------------------
`env-contract.tsv` calls itself "the ONE in-repo authority" for Lupin's
environment variables, and its `note` column carries `<compose>.yml:<line>`
citations as evidence for each row's declared surface and requirement. Preflight
A1 and C6 both read this file, and C6 now DERIVES its assertion tier from the
compose file and COMPARES it against these rows — so a note that points at the
wrong line sends the next reader to the wrong evidence for a claim two checks
depend on.

Nothing checked them. Measured 2026-07-27, two of eleven citations were stale:

    GH_TOKEN                 "(:204, :312)"        -> :312 is a volume mount
    LUPIN_MODEL_SERVER_TAG   "cloud-test.yml:143"  -> :143 is a network alias

Both are off by the drift of an edited compose file, and both had been sitting in
the authority reading as evidence.

WHAT THIS ASSERTS, EXACTLY
--------------------------
For every citation of an IN-REPO compose file, the cited line must mention the
row's own variable name.

⚠️ It asserts the citation LANDS, not that the note's prose is true. A line that
names the var but is quoted for the wrong reason still passes here.

⚠️ THE PREDICATE MUST BE ABOUT THE CITATION, NOT ABOUT ANY `:digits`. The notes
also contain `:7998`, `:0` and `:1` — ports and GPU indices. A naive colon-digits scan
swallows those and asserts a compose file has a line 7998. So bare `:N` is
accepted ONLY inside a note that has already named a compose file, and only when
N is within that file's length; everything else must carry its own filename.

`cloud-gpu.env:31` is deliberately NOT checked: that file lives on the VM (mode
600), not in the repo. Skipping it is recorded here rather than left silent —
this suite cannot speak to it, and a reader must not read a green as coverage of
that citation.

Venue: :7999-eligible. Pure file reads; no docker, no VM, no network.
"""
import os
import pathlib
import re

import pytest


LUPIN_ROOT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] )
CONTRACT   = LUPIN_ROOT / "src/conf/env-contract.tsv"

# Basenames used in the notes → the repo file they name.
COMPOSE_ALIASES = {
    "cloud-gpu.yml"          : "docker-compose.cloud-gpu.yml",
    "cloud-test.yml"         : "docker-compose.cloud-test.yml",
    "docker-compose.yml"     : "docker-compose.yml",
}

_FILENAMES = "|".join( re.escape( k ) for k in sorted( COMPOSE_ALIASES, key=len, reverse=True ) )

# ONE left-to-right scan, so a bare `:204` can be attributed to whichever file the
# note named most recently — whether or not that mention carried its own line
# number. Two separate scans is what the first version of this file did, and it
# SILENTLY DROPPED both GH_TOKEN citations: the note names `docker-compose.yml`
# with no attached number, so the file-anchor never got set and `:204, :312` were
# never checked. The count assertion below still read 11 and looked healthy.
CITATION = re.compile(
    r"\b(?P<file>" + _FILENAMES + r")(?::(?P<lines>\d+(?:,\d+)*))?"
    r"|(?<![\w.]):(?P<bare>\d+)\b"
)


def _contract_rows():
    """
    Parse the contract into ( name, note ) pairs.

    Ensures:
        - '#' comments and blank lines are dropped
        - raises rather than returning empty: an empty parse would make every
          assertion below pass vacuously, which is this directory's recurring
          failure mode
    """
    rows = []
    for line in CONTRACT.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith( "#" ):
            continue
        fields = line.split( "\t" )
        if len( fields ) >= 6:
            rows.append( ( fields[ 0 ], fields[ 5 ] ) )
    assert rows, "parsed ZERO contract rows — every citation assertion would pass vacuously"
    return rows


def _citations( name, note ):
    """
    Extract ( var_name, compose_path, line_no ) for every in-repo citation.

    Ensures:
        - named citations resolve through COMPOSE_ALIASES
        - a BARE `:N` is attributed to the LAST file named earlier in the note,
          and only when N is within that file's length — this is what keeps
          `:7998` (a port) and `:0` (a GPU index) out of the result set
        - off-repo citations (cloud-gpu.env) are not returned
    """
    out       = []
    last_file = None
    for m in CITATION.finditer( note ):
        if m.group( "file" ):
            last_file = LUPIN_ROOT / COMPOSE_ALIASES[ m.group( "file" ) ]
            if m.group( "lines" ):
                for n in m.group( "lines" ).split( "," ):
                    out.append( ( name, last_file, int( n ) ) )
        elif last_file is not None:
            n = int( m.group( "bare" ) )
            # The range guard is what keeps `:7998` (a port in the
            # LUPIN_MODEL_SERVER_URL note) from being claimed as a line number.
            if 1 <= n <= len( last_file.read_text().splitlines() ):
                out.append( ( name, last_file, n ) )
    return out


ALL_CITATIONS = [ c for name, note in _contract_rows() for c in _citations( name, note ) ]


def test_the_scan_FOUND_citations_to_check():
    """
    The instrument before the reading. A regex that matched nothing would make
    every parametrised case below disappear and the file report green.
    """
    assert len( ALL_CITATIONS ) >= 10, f"only {len(ALL_CITATIONS)} citations found — the scan is not reaching the notes"


def test_a_PORT_is_not_mistaken_for_a_line_citation():
    """
    The control, and it is exercised: `LUPIN_MODEL_SERVER_URL`'s note names
    `cloud-gpu.yml:193` and then carries a `:7998` port inside a URL. Without the
    range guard the scanner would claim cloud-gpu.yml has a line 7998 and the
    suite would be measuring noise.

    Asserted against the note that actually contains it, not against the corpus
    at large — an absence proves nothing if the token was never in range.
    """
    note = next( n for name, n in _contract_rows() if name == "LUPIN_MODEL_SERVER_URL" )
    assert ":7998" in note, "the note this control depends on no longer contains a port — the control is now vacuous"
    assert 7998 not in { n for _, _, n in _citations( "LUPIN_MODEL_SERVER_URL", note ) }


@pytest.mark.parametrize(
    "var,path,line",
    ALL_CITATIONS,
    ids=[ f"{v}@{p.name}:{n}" for v, p, n in ALL_CITATIONS ],
)
def test_every_citation_lands_on_a_line_naming_its_variable( var, path, line ):
    """
    A citation is a claim. It must point at a line that mentions the variable it
    is offered as evidence for.
    """
    lines = path.read_text().splitlines()
    assert 1 <= line <= len( lines ), f"{path.name} has {len(lines)} lines; the note cites :{line}"
    text = lines[ line - 1 ]
    assert var in text, (
        f"{var}'s note cites {path.name}:{line}, but that line does not mention {var}.\n"
        f"  cited line: {text.strip()!r}"
    )
