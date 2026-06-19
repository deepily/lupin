#!/usr/bin/env python3
"""
Unit tests for the per-renderer visual-prompt builders:
  prompts/d2.py, prompts/visual.py (mermaid), prompts/matplotlib.py,
  prompts/image_gen.py, prompts/video_gen.py

All pure string builders + keyword-driven _suggest_* helpers. No external
boundaries — fully deterministic.
"""

import pytest

from cosa.agents.presentation_generator.prompts import d2, visual, matplotlib, image_gen, video_gen


# ---------------------------------------------------------------------------
# d2.py
# ---------------------------------------------------------------------------
class TestD2:
    def test_prompt_with_title_and_pattern( self ):
        p = d2.get_d2_prompt( "architecture", "system architecture overview", "Arch" )
        assert "Slide title: Arch" in p
        assert "Visual type: architecture" in p
        assert "containers with nested components" in p

    def test_prompt_without_title( self ):
        p = d2.get_d2_prompt( "flowchart_d2", "a simple flow", "" )
        assert "Slide title" not in p

    def test_suggest_keyword_match( self ):
        assert d2._suggest_d2_pattern( "sequence of API interactions" ) == "sequence diagram (shape: sequence_diagram)"
        # "pipeline" without "flow"/"process" so the pipeline hint wins (dict iteration order)
        assert d2._suggest_d2_pattern( "data pipeline left to right" ) == "left-to-right sequential nodes (direction: right)"

    def test_suggest_no_match_default( self ):
        assert d2._suggest_d2_pattern( "completely unrelated text" ) == d2.DEFAULT_D2_PATTERN

    def test_suggest_empty_and_none( self ):
        assert d2._suggest_d2_pattern( "" ) == d2.DEFAULT_D2_PATTERN
        assert d2._suggest_d2_pattern( None ) == d2.DEFAULT_D2_PATTERN


# ---------------------------------------------------------------------------
# visual.py (mermaid)
# ---------------------------------------------------------------------------
class TestMermaid:
    def test_prompt_with_title( self ):
        p = visual.get_mermaid_prompt( "flowchart", "process flow", "Flow" )
        assert "Flow" in p
        assert "flowchart TD" in p

    def test_prompt_without_title( self ):
        p = visual.get_mermaid_prompt( "flowchart", "process flow", "" )
        assert isinstance( p, str ) and p

    def test_suggest_keyword_and_default( self ):
        assert visual._suggest_diagram_type( "a sequence of requests" ) == "sequenceDiagram"
        assert visual._suggest_diagram_type( "pie distribution breakdown" ) == "pie"
        assert visual._suggest_diagram_type( "nothing matching here" ) == visual.DEFAULT_DIAGRAM_TYPE

    def test_suggest_empty( self ):
        assert visual._suggest_diagram_type( "" ) == visual.DEFAULT_DIAGRAM_TYPE
        assert visual._suggest_diagram_type( None ) == visual.DEFAULT_DIAGRAM_TYPE


# ---------------------------------------------------------------------------
# matplotlib.py
# ---------------------------------------------------------------------------
class TestMatplotlib:
    def test_prompt_with_title( self ):
        p = matplotlib.get_matplotlib_prompt( "chart", "bar comparison of values", "Chart" )
        assert "Chart" in p
        assert "bar chart" in p

    def test_prompt_without_title( self ):
        p = matplotlib.get_matplotlib_prompt( "chart", "line trend over time", "" )
        assert "line chart" in p

    def test_suggest_keyword_and_default( self ):
        assert matplotlib._suggest_chart_type( "growth over time" ) == "line chart"
        assert matplotlib._suggest_chart_type( "correlation scatter" ) == "scatter plot"
        assert matplotlib._suggest_chart_type( "radar spider plot" ) == "radar chart"
        assert matplotlib._suggest_chart_type( "no keyword present" ) == matplotlib.DEFAULT_CHART_TYPE

    def test_suggest_empty( self ):
        assert matplotlib._suggest_chart_type( "" ) == matplotlib.DEFAULT_CHART_TYPE
        assert matplotlib._suggest_chart_type( None ) == matplotlib.DEFAULT_CHART_TYPE


# ---------------------------------------------------------------------------
# image_gen.py
# ---------------------------------------------------------------------------
class TestImageGen:
    def test_known_type_with_title_and_no_text_directive( self ):
        # hero_image is in NO_TEXT_TYPES → no-text directive appended
        p = image_gen.get_image_prompt( "hero_image", "a mountain vista", "Cover" )
        assert image_gen.IMAGE_CONTEXT_PREFIX in p
        assert 'titled "Cover"' in p
        assert "a mountain vista" in p
        assert "photorealistic" in p   # hero_image style modifier
        assert "Do not include any text" in p
        assert "16:9" in p

    def test_unknown_type_default_style_no_directive( self ):
        p = image_gen.get_image_prompt( "infographic", "data chart", "" )
        # infographic NOT in NO_TEXT_TYPES → no no-text directive
        assert "Do not include any text" not in p
        assert "titled" not in p   # no slide title

    def test_unknown_visual_type_uses_default_modifier( self ):
        p = image_gen.get_image_prompt( "mystery_type", "", "" )
        assert image_gen.DEFAULT_STYLE_MODIFIER in p

    def test_empty_description_omitted( self ):
        p = image_gen.get_image_prompt( "icon", "", "Title" )
        # icon is no-text type
        assert "Do not include any text" in p


# ---------------------------------------------------------------------------
# video_gen.py
# ---------------------------------------------------------------------------
class TestVideoGen:
    def test_prompt_with_title_known_style( self ):
        p = video_gen.get_video_prompt( "title_video", "ambient pan", "Intro" )
        assert "titled 'Intro'" in p
        assert "Slow cinematic pan" in p
        assert "ambient pan" in p
        assert video_gen.VIDEO_SYSTEM_RULES in p

    def test_prompt_without_title_default_style( self ):
        p = video_gen.get_video_prompt( "unknown_type", "some motion", "" )
        assert video_gen.DEFAULT_STYLE_MODIFIER in p
        assert "titled" not in p

    def test_duration_known( self ):
        assert video_gen.get_video_duration( "title_video" )    == 5
        assert video_gen.get_video_duration( "flow_animation" ) == 6
        assert video_gen.get_video_duration( "process_video" )  == 8

    def test_duration_unknown_default( self ):
        assert video_gen.get_video_duration( "mystery" ) == video_gen.DEFAULT_VIDEO_DURATION


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
