"""
The font-stack sweep reads declarations, never comments (row f0e00f01).

`declared_font_stacks` found `font-family` with a regex over the raw text of every tracked
CSS and HTML file, comments included. A comment in notifications-surface.css describing a
`<button>` reset — "… font-family:inherit / background from `--persona-color`, which
senderCard.ts sets inline)" — was therefore recorded as a font stack. The browser rejects
it, so the width guard measured it in whatever font the PREVIOUS stack had left on the
canvas: 402.91 while "Arial, sans-serif" sorted before it, 518.48 once the stylelint quote
fix (e79006be) re-sorted the keys and put a monospace stack there.

Venue: :7999-eligible — a throwaway git repo under tmp_path, no server, no browser.
"""

import subprocess

from tests.e2e_ui.font_stack_fingerprint import declared_font_stacks


CSS = """\
/* A reset that mentions a declaration: font-family:inherit / background from x */
.real { font-family: "Real Font", monospace; }
/* A comment across lines
   font-family: Ghost Font, serif; */
.also-real { font-family: Other Font, sans-serif; }
"""

HTML = """\
<html><head><style>
  /* font-family: Style Comment Ghost, serif; */
  .inline { font-family: Inline Font, serif; }
</style></head>
<body><!-- font-family: Markup Comment Ghost, serif; --></body></html>
"""


def _repo( tmp_path ):
    """A git repo holding one CSS and one HTML file where the sweep looks for them."""
    css_dir  = tmp_path / "src/lupin_app/static/css"
    html_dir = tmp_path / "src/lupin_app/static/html"
    css_dir.mkdir( parents=True )
    html_dir.mkdir( parents=True )
    ( css_dir / "a.css" ).write_text( CSS, encoding="utf-8" )
    ( html_dir / "b.html" ).write_text( HTML, encoding="utf-8" )
    subprocess.run( [ "git", "init", "-q", str( tmp_path ) ], check=True )
    subprocess.run( [ "git", "-C", str( tmp_path ), "add", "." ], check=True )
    return tmp_path


def test_the_sweep_returns_the_declarations_and_nothing_written_in_a_comment( tmp_path ):
    stacks = declared_font_stacks( _repo( tmp_path ) )

    # Positive control first: a sweep that found nothing would pass every absence below.
    assert stacks == ( '"Real Font", monospace', "Inline Font, serif", "Other Font, sans-serif" ), stacks
    for ghost in ( "inherit /", "Ghost Font", "Style Comment Ghost", "Markup Comment Ghost" ):
        assert not any( ghost in s for s in stacks ), f"a commented-out declaration was swept up: {ghost!r} in {stacks}"
