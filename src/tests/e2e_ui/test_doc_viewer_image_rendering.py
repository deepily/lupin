"""
E2E UI tests for the doc-viewer's image-MIME rendering branch.

Validates that `/app/docs?path=<project>/<image>.png` renders inline via
an `<img>` tag (per the 2026-05-21 Lupin+CoSA joint patch). Closes the
verification gap from the original PNG support landing — the backend
smoke tests at src/tests/smoke/test_docs_files_endpoint.py cover the
API layer, but only Playwright can verify the SPA's MIME-dispatch
branch actually puts an `<img>` element into the DOM.

Driven by Rachel's git_loc_delta plotter use case (CoSA session
e13fed4f). Bug history: Rick's first attempt on 2026-05-21 saw raw
PNG bytes rendered as text because his browser cached the pre-image-
dispatch HTML. Hard-refresh fixed it; the Cache-Control: no-cache
header (commit bf04e9a) prevents the same trap going forward.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit
with `test_types: "e2e"` + `pytest_args: "-k doc_viewer_image"`).
Can also run locally against :7999 via:
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/e2e_ui/test_doc_viewer_image_rendering.py -v

Requires:
    - Test server running (port 8000 default; LUPIN_TEST_BASE_URL overrides)
    - The Firefox plugin's `microphone-48.png` icon exists at
      `src/lupin-plugin-firefox/icons/microphone-48.png` (used as the
      test fixture — small, version-controlled, always present)
    - The aggressive-400 + image-MIME + cache-control CoSA changes are
      loaded in the running server (bounce required after pages.py and
      docs_files.py edits land in the CoSA submodule)
"""

from .conftest import BASE_URL


# A version-controlled PNG that's always present in the Lupin tree.
# Used because creating temp PNGs from a Playwright test would require
# fixture setup; using a pre-existing one keeps the test self-contained.
_FIXTURE_IMAGE_PATH = "lupin/src/lupin-plugin-firefox/icons/microphone-48.png"


class TestDocViewerImageRendering:
    """Browser-rendered image dispatch tests for the SPA's image/* branch."""

    def test_png_renders_as_img_tag( self, logged_in_page ):
        """
        Loading a PNG via the doc viewer puts an `<img>` element in the
        doc-viewer-target container, with a blob: URL as its src.
        """
        url = f"{BASE_URL}/app/docs?path={_FIXTURE_IMAGE_PATH}"
        logged_in_page.goto( url )
        logged_in_page.wait_for_load_state( "networkidle" )

        # The SPA's image branch creates an <img> inside the target div.
        img = logged_in_page.locator( "#doc-viewer-target img" )
        img.wait_for( state="attached", timeout=5000 )

        src = img.get_attribute( "src" )
        assert src is not None, "img.src missing"
        assert src.startswith( "blob:" ), \
            f"src should be a blob URL, got: {src[ :60 ]}"

    def test_png_target_gets_image_class( self, logged_in_page ):
        """
        Image branch sets className to 'doc-viewer-content doc-viewer-image'
        on the target container — used by CSS for image-specific layout.
        """
        url = f"{BASE_URL}/app/docs?path={_FIXTURE_IMAGE_PATH}"
        logged_in_page.goto( url )
        logged_in_page.wait_for_load_state( "networkidle" )

        target = logged_in_page.locator( "#doc-viewer-target" )
        target.wait_for( state="attached", timeout=5000 )

        class_attr = target.get_attribute( "class" ) or ""
        assert "doc-viewer-image" in class_attr, \
            f"target missing doc-viewer-image class; got: {class_attr!r}"

    def test_png_rendered_with_nonzero_dimensions( self, logged_in_page ):
        """
        End-to-end check: the <img> actually loaded and the browser knows
        its natural dimensions. naturalWidth > 0 is the canonical signal
        that an image successfully decoded.
        """
        url = f"{BASE_URL}/app/docs?path={_FIXTURE_IMAGE_PATH}"
        logged_in_page.goto( url )
        logged_in_page.wait_for_load_state( "networkidle" )

        img = logged_in_page.locator( "#doc-viewer-target img" )
        img.wait_for( state="attached", timeout=5000 )

        # Wait for the image to actually load (browser parses bytes,
        # determines dimensions). 5s is generous for a 1740-byte PNG.
        natural_width = logged_in_page.evaluate(
            "() => document.querySelector('#doc-viewer-target img')?.naturalWidth ?? 0"
        )
        # microphone-48.png is 48x48, but we just check non-zero to keep
        # the test resilient to fixture swaps.
        assert natural_width > 0, \
            f"image didn't decode; naturalWidth={natural_width}"

    def test_text_file_still_renders_as_markdown_not_img( self, logged_in_page ):
        """
        Regression guard: existing text/markdown branch must not be
        disturbed by the image branch addition.
        """
        # Use the Lupin README — version-controlled root-level markdown.
        url = f"{BASE_URL}/app/docs?path=lupin/CLAUDE.md"
        logged_in_page.goto( url )
        logged_in_page.wait_for_load_state( "networkidle" )

        # Markdown branch renders headings + paragraphs inside the target.
        target = logged_in_page.locator( "#doc-viewer-target" )
        target.wait_for( state="attached", timeout=5000 )

        # An <img> in #doc-viewer-target would indicate the wrong branch fired.
        img_count = logged_in_page.locator( "#doc-viewer-target img" ).count()
        assert img_count == 0, \
            f"text/markdown path produced {img_count} <img>(s) — image branch leaked"

        # And the markdown branch should produce SOME rendered HTML.
        # (Headers are the most common element across our markdown files.)
        rendered_text = target.inner_text()
        assert len( rendered_text ) > 100, \
            f"markdown branch produced no/minimal text; got {len( rendered_text )} chars"
