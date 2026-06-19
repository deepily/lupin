#!/usr/bin/env python3
"""
Unit tests for renderers/marp_text_renderer.py

Pure text transformation (PresentationModel → Marp Markdown). No external
boundaries — drive with real state models and assert on the emitted markdown.
"""

import pytest

from cosa.agents.presentation_generator.renderers.marp_text_renderer import (
    MarpTextRenderer,
    DEFAULT_THEME_CONFIG,
)
from cosa.agents.presentation_generator.state import (
    PresentationModel,
    SlideModel,
    PresenterNotes,
)

R = MarpTextRenderer


def _slide( **kw ):
    defaults = dict( number=1, arc_position="body", type="content", title="T" )
    defaults.update( kw )
    return SlideModel( **defaults )


# ---------------------------------------------------------------------------
# render (top-level)
# ---------------------------------------------------------------------------
class TestRenderTop:
    def test_full_three_slides( self ):
        pres = PresentationModel(
            title="Deck", speaker="Jane", date="2026-03-28", total_slides=3,
            slides=[
                _slide( number=1, type="title", title="Deck", subtitle="Sub" ),
                _slide( number=2, type="content", title="Body",
                        visual_type="diagram", visual_description="L1->L2",
                        content_bullets=[ "a", "b" ],
                        presenter_notes=PresenterNotes( transition="next", talking_points=[ "p" ],
                                                        timing_seconds=75, emphasis="here" ) ),
                _slide( number=3, type="conclusion", title="End", content_bullets=[ "z" ] ),
            ],
        )
        out = R.render( pres, DEFAULT_THEME_CONFIG )
        assert "marp: true" in out
        assert "# Deck" in out
        assert "Jane | 2026-03-28" in out
        assert "<!-- VISUAL: diagram | L1->L2 -->" in out
        assert "Transition: next" in out
        # 2 frontmatter --- + 2 separators between 3 slides
        assert [ l for l in out.split( "\n" ) if l.strip() == "---" ].__len__() == 4

    def test_empty_slides( self ):
        out = R.render( PresentationModel( title="Empty", total_slides=0 ), DEFAULT_THEME_CONFIG )
        assert "marp: true" in out
        # only the 2 frontmatter delimiters
        assert [ l for l in out.split( "\n" ) if l.strip() == "---" ].__len__() == 2


# ---------------------------------------------------------------------------
# _render_frontmatter
# ---------------------------------------------------------------------------
class TestFrontmatter:
    def test_with_class_header_footer_paginate_off( self ):
        cfg = {
            "theme": {
                "marp_theme": "gaia", "marp_class": "invert",
                "layout": {
                    "paginate": False,
                    "header_template": "{title}",
                    "footer_template": "{speaker} | {date}",
                },
                "colors": {}, "fonts": {},
            }
        }
        pres = PresentationModel( title="My Talk", speaker="Sam", date="2026-01-01" )
        fm = R._render_frontmatter( pres, cfg )
        assert "theme: gaia" in fm
        assert "class: invert" in fm
        assert "paginate: false" in fm
        assert 'header: "My Talk"' in fm
        assert 'footer: "Sam | 2026-01-01"' in fm
        assert "style: |" in fm

    def test_no_class_no_header_no_footer( self ):
        cfg = { "theme": { "layout": { "header_template": "", "footer_template": "" }, "colors": {}, "fonts": {} } }
        fm = R._render_frontmatter( PresentationModel( title="X" ), cfg )
        assert "class:" not in fm
        assert "header:" not in fm
        assert "footer:" not in fm
        assert "paginate: true" in fm   # default

    def test_empty_theme_config_defaults( self ):
        fm = R._render_frontmatter( PresentationModel( title="X" ), {} )
        assert "theme: default" in fm


# ---------------------------------------------------------------------------
# _generate_css
# ---------------------------------------------------------------------------
class TestCss:
    def test_defaults_when_empty( self ):
        css = R._generate_css( {} )
        assert "font-family: Inter" in css
        assert "color: #2563EB" in css
        assert "JetBrains Mono" in css

    def test_custom_colors_fonts( self ):
        cfg = { "theme": { "colors": { "primary": "#000000" }, "fonts": { "code": "Fira Code" } } }
        css = R._generate_css( cfg )
        assert "#000000" in css
        assert "Fira Code" in css


# ---------------------------------------------------------------------------
# _render_slide dispatch
# ---------------------------------------------------------------------------
class TestSlideDispatch:
    def test_title_dispatch( self ):
        pres = PresentationModel( title="P", speaker="S", date="D" )
        md = R._render_slide( _slide( type="title", title="Hi" ), pres )
        assert "<!-- _class: lead -->" in md
        assert "# Hi" in md

    def test_unknown_type_falls_back_to_content( self ):
        pres = PresentationModel( title="P" )
        md = R._render_slide( _slide( type="mystery", title="Body" ), pres )
        assert "# Body" in md

    def test_visual_and_notes_appended( self ):
        pres = PresentationModel( title="P" )
        slide = _slide( type="content", title="B", visual_type="chart", visual_description="d",
                        presenter_notes=PresenterNotes( talking_points=[ "x" ], timing_seconds=30 ) )
        md = R._render_slide( slide, pres )
        assert "<!-- VISUAL: chart | d -->" in md
        assert "Talking points:" in md

    def test_empty_notes_not_appended( self ):
        # presenter_notes rendering to "" (timing 0, nothing else) → no notes block appended
        pres = PresentationModel( title="P" )
        slide = _slide( type="content", title="B", presenter_notes=PresenterNotes( timing_seconds=0 ) )
        md = R._render_slide( slide, pres )
        assert "<!--" not in md   # neither visual (text_only) nor notes appended


# ---------------------------------------------------------------------------
# slide type renderers
# ---------------------------------------------------------------------------
class TestSlideRenderers:
    def test_title_with_subtitle_and_speaker_date( self ):
        pres = PresentationModel( title="P", speaker="Sam", date="2026" )
        md = R._render_title_slide( _slide( type="title", title="Hi", subtitle="Sub" ), pres )
        assert "## Sub" in md
        assert "Sam | 2026" in md

    def test_title_no_subtitle_no_speaker_date( self ):
        pres = PresentationModel( title="P" )   # no speaker/date
        md = R._render_title_slide( _slide( type="title", title="Hi" ), pres )
        assert "## " not in md
        assert "|" not in md

    def test_content_with_subtitle_and_bullets( self ):
        md = R._render_content_slide( _slide( title="C", subtitle="Sub", content_bullets=[ "a", "b" ] ) )
        assert "## Sub" in md
        assert "- a" in md and "- b" in md

    def test_content_no_subtitle_no_bullets( self ):
        md = R._render_content_slide( _slide( title="C" ) )
        assert "# C" in md
        assert "## " not in md
        assert "- " not in md

    def test_section_divider_with_and_without_subtitle( self ):
        with_sub = R._render_section_divider_slide( _slide( title="Sec", subtitle="Sub" ) )
        assert "<!-- _class: lead -->" in with_sub and "## Sub" in with_sub
        no_sub = R._render_section_divider_slide( _slide( title="Sec" ) )
        assert "## " not in no_sub

    def test_conclusion_delegates_to_content( self ):
        md = R._render_conclusion_slide( _slide( title="End", content_bullets=[ "z" ] ) )
        assert "# End" in md and "- z" in md


# ---------------------------------------------------------------------------
# _render_presenter_notes
# ---------------------------------------------------------------------------
class TestPresenterNotes:
    def test_none_notes( self ):
        assert R._render_presenter_notes( None ) == ""

    def test_empty_notes_returns_empty( self ):
        # all-default notes: no transition, no talking points, timing 60 (>0 → included)
        out = R._render_presenter_notes( PresenterNotes() )
        assert out.startswith( "<!--" )
        assert "Timing: 60s" in out

    def test_zero_timing_no_content_returns_empty( self ):
        # timing 0 and nothing else → fully empty → ""
        assert R._render_presenter_notes( PresenterNotes( timing_seconds=0 ) ) == ""

    def test_all_fields( self ):
        notes = PresenterNotes( transition="t", talking_points=[ "p1", "p2" ], timing_seconds=45, emphasis="e" )
        out = R._render_presenter_notes( notes )
        assert "Transition: t" in out
        assert "Talking points:" in out and "- p1" in out
        assert "Timing: 45s" in out
        assert "Emphasis: e" in out

    def test_trailing_empty_line_stripped( self ):
        # transition (appends a trailing "") + timing 0 → trailing blank popped by the while loop
        out = R._render_presenter_notes( PresenterNotes( transition="t", timing_seconds=0 ) )
        assert out == "<!--\nTransition: t\n-->"


# ---------------------------------------------------------------------------
# _render_visual_placeholder
# ---------------------------------------------------------------------------
class TestVisualPlaceholder:
    def test_text_only_empty( self ):
        assert R._render_visual_placeholder( _slide( visual_type="text_only" ) ) == ""

    def test_with_description( self ):
        out = R._render_visual_placeholder( _slide( visual_type="diagram", visual_description="flow" ) )
        assert out == "<!-- VISUAL: diagram | flow -->"

    def test_no_description_default( self ):
        out = R._render_visual_placeholder( _slide( visual_type="chart" ) )
        assert "(no description provided)" in out


# ---------------------------------------------------------------------------
# _interpolate_template
# ---------------------------------------------------------------------------
class TestInterpolate:
    def test_empty_template( self ):
        assert R._interpolate_template( "", PresentationModel( title="X" ) ) == ""

    def test_replaces_all_placeholders( self ):
        pres = PresentationModel( title="T", speaker="S", date="D" )
        assert R._interpolate_template( "{title}-{speaker}-{date}", pres ) == "T-S-D"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
