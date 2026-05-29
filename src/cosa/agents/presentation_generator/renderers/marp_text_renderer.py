#!/usr/bin/env python3
"""
Marp Text Renderer — Converts PresentationModel to Marp Markdown.

Pure text transformation: PresentationModel + theme config dict in,
Marp-compatible markdown string out. No file I/O, no async, no state.

Marp format reference:
  - YAML frontmatter between --- delimiters (first block)
  - Slide separators: --- on its own line
  - Presenter notes: <!-- comment blocks -->
  - Per-slide directives: <!-- _class: lead --> etc.

Phase 7 visual placeholders use: <!-- VISUAL: type | description -->
"""

from typing import Optional


# =============================================================================
# Default theme fallback (used when theme YAML file is missing)
# =============================================================================

DEFAULT_THEME_CONFIG = {
    "theme" : {
        "name"       : "default",
        "marp_theme" : "default",
        "marp_class" : "",
        "colors" : {
            "primary"         : "#2563EB",
            "secondary"       : "#1E40AF",
            "accent"          : "#F59E0B",
            "background"      : "#FFFFFF",
            "text"            : "#1F2937",
            "code_background" : "#F3F4F6",
        },
        "fonts" : {
            "heading" : "Inter",
            "body"    : "Inter",
            "code"    : "JetBrains Mono",
        },
        "layout" : {
            "title_alignment"  : "center",
            "bullet_style"     : "dash",
            "code_block_theme" : "github",
            "paginate"         : True,
            "header_template"  : "",
            "footer_template"  : "{speaker} | {date}",
        },
        "branding" : {
            "logo_path"     : None,
            "logo_position" : "bottom-right",
            "footer_text"   : None,
            "watermark"     : None,
        },
    }
}


# =============================================================================
# Slide type dispatch table
# =============================================================================

# Maps slide.type to render method name suffix
_SLIDE_TYPE_DISPATCH = {
    "title"           : "_render_title_slide",
    "content"         : "_render_content_slide",
    "key_point"       : "_render_content_slide",
    "evidence"        : "_render_content_slide",
    "hook"            : "_render_content_slide",
    "agenda"          : "_render_content_slide",
    "section_divider" : "_render_section_divider_slide",
    "conclusion"      : "_render_conclusion_slide",
    "summary"         : "_render_conclusion_slide",
    "cta"             : "_render_conclusion_slide",
    "qa"              : "_render_conclusion_slide",
}


# =============================================================================
# MarpTextRenderer
# =============================================================================

class MarpTextRenderer:
    """
    Stateless renderer that converts PresentationModel to Marp Markdown.

    All methods are @staticmethod — no constructor, no instance state.
    This is a pure function namespace for text transformation.

    Requires:
        - presentation is a valid PresentationModel
        - theme_config is a dict matching the theme YAML schema

    Ensures:
        - Returns a valid Marp Markdown string
        - Output contains YAML frontmatter, slide separators, presenter notes
        - Slide count in output matches len( presentation.slides )
    """

    @staticmethod
    def render( presentation, theme_config: dict ) -> str:
        """
        Render a PresentationModel to Marp Markdown.

        Requires:
            - presentation is a PresentationModel instance
            - theme_config is a dict with "theme" key containing config

        Ensures:
            - Returns complete Marp Markdown string
            - First block is YAML frontmatter with marp: true
            - Slides separated by --- on own line
            - Presenter notes in <!-- --> comment blocks

        Returns:
            str: Complete Marp Markdown document
        """
        sections = []

        # 1. Frontmatter
        sections.append( MarpTextRenderer._render_frontmatter( presentation, theme_config ) )

        # 2. Slides
        for i, slide in enumerate( presentation.slides ):
            slide_md = MarpTextRenderer._render_slide( slide, presentation )
            if i > 0:
                # Slide separator before every slide after the first
                sections.append( "---" )
            sections.append( slide_md )

        return "\n\n".join( sections ) + "\n"

    # =========================================================================
    # Frontmatter
    # =========================================================================

    @staticmethod
    def _render_frontmatter( presentation, theme_config: dict ) -> str:
        """
        Generate Marp YAML frontmatter block.

        Requires:
            - presentation has title, speaker, date fields
            - theme_config has theme.marp_theme, theme.layout, theme.colors, theme.fonts

        Ensures:
            - Returns string starting and ending with ---
            - Contains marp: true
            - CSS style block generated from theme config

        Returns:
            str: YAML frontmatter block
        """
        theme  = theme_config.get( "theme", {} )
        layout = theme.get( "layout", {} )

        lines = [ "---" ]
        lines.append( "marp: true" )
        lines.append( f'theme: {theme.get( "marp_theme", "default" )}' )

        # Only emit class if non-empty
        marp_class = theme.get( "marp_class", "" )
        if marp_class:
            lines.append( f"class: {marp_class}" )

        # Paginate
        paginate = layout.get( "paginate", True )
        lines.append( f"paginate: {'true' if paginate else 'false'}" )

        # Header (only if non-empty after interpolation)
        header = MarpTextRenderer._interpolate_template(
            layout.get( "header_template", "" ), presentation
        )
        if header:
            lines.append( f'header: "{header}"' )

        # Footer (only if non-empty after interpolation)
        footer = MarpTextRenderer._interpolate_template(
            layout.get( "footer_template", "" ), presentation
        )
        if footer:
            lines.append( f'footer: "{footer}"' )

        # CSS style block
        css = MarpTextRenderer._generate_css( theme_config )
        if css:
            lines.append( "style: |" )
            for css_line in css.split( "\n" ):
                lines.append( f"  {css_line}" )

        lines.append( "---" )
        return "\n".join( lines )

    # =========================================================================
    # CSS Generation
    # =========================================================================

    @staticmethod
    def _generate_css( theme_config: dict ) -> str:
        """
        Generate CSS from theme color and font settings.

        Requires:
            - theme_config has theme.colors and theme.fonts dicts

        Ensures:
            - Returns CSS string with section, heading, code, and accent rules

        Returns:
            str: CSS rules for Marp style block
        """
        theme  = theme_config.get( "theme", {} )
        colors = theme.get( "colors", {} )
        fonts  = theme.get( "fonts", {} )

        primary         = colors.get( "primary", "#2563EB" )
        secondary       = colors.get( "secondary", "#1E40AF" )
        accent          = colors.get( "accent", "#F59E0B" )
        background      = colors.get( "background", "#FFFFFF" )
        text_color      = colors.get( "text", "#1F2937" )
        code_background = colors.get( "code_background", "#F3F4F6" )

        heading_font = fonts.get( "heading", "Inter" )
        body_font    = fonts.get( "body", "Inter" )
        code_font    = fonts.get( "code", "JetBrains Mono" )

        css_parts = [
            f"section {{",
            f"  font-family: {body_font}, sans-serif;",
            f"  color: {text_color};",
            f"  background-color: {background};",
            f"}}",
            f"h1, h2, h3 {{",
            f"  font-family: {heading_font}, sans-serif;",
            f"  color: {primary};",
            f"}}",
            f"h2 {{",
            f"  color: {secondary};",
            f"}}",
            f"code {{",
            f"  font-family: {code_font}, monospace;",
            f"  background-color: {code_background};",
            f"}}",
            f"em {{",
            f"  color: {accent};",
            f"}}",
        ]

        return "\n".join( css_parts )

    # =========================================================================
    # Slide Dispatch
    # =========================================================================

    @staticmethod
    def _render_slide( slide, presentation ) -> str:
        """
        Dispatch slide rendering by slide.type.

        Requires:
            - slide is a SlideModel instance
            - presentation is the parent PresentationModel

        Ensures:
            - Returns markdown for the slide including presenter notes
            - Unknown slide types fall back to content-style rendering

        Returns:
            str: Markdown for one slide
        """
        method_name = _SLIDE_TYPE_DISPATCH.get( slide.type, "_render_content_slide" )
        method      = getattr( MarpTextRenderer, method_name )

        # Title slide needs presentation context (speaker, date)
        if method_name == "_render_title_slide":
            slide_md = method( slide, presentation )
        else:
            slide_md = method( slide )

        # Append visual placeholder if needed
        visual_placeholder = MarpTextRenderer._render_visual_placeholder( slide )
        if visual_placeholder:
            slide_md += "\n\n" + visual_placeholder

        # Append presenter notes
        notes_md = MarpTextRenderer._render_presenter_notes( slide.presenter_notes )
        if notes_md:
            slide_md += "\n\n" + notes_md

        return slide_md

    # =========================================================================
    # Slide Type Renderers
    # =========================================================================

    @staticmethod
    def _render_title_slide( slide, presentation ) -> str:
        """
        Render a title slide with centered layout.

        Requires:
            - slide.title is a non-empty string
            - presentation has speaker and date fields

        Returns:
            str: Markdown for title slide
        """
        lines = [
            "<!-- _class: lead -->",
            "<!-- _paginate: skip -->",
            "",
            f"# {slide.title}",
        ]

        if slide.subtitle:
            lines.append( f"## {slide.subtitle}" )

        # Speaker / date line
        speaker_date_parts = []
        if presentation.speaker:
            speaker_date_parts.append( presentation.speaker )
        if presentation.date:
            speaker_date_parts.append( presentation.date )
        if speaker_date_parts:
            lines.append( "" )
            lines.append( " | ".join( speaker_date_parts ) )

        return "\n".join( lines )

    @staticmethod
    def _render_content_slide( slide ) -> str:
        """
        Render a standard content slide with title and bullets.

        Requires:
            - slide.title is a non-empty string

        Returns:
            str: Markdown for content slide
        """
        lines = [ f"# {slide.title}" ]

        if slide.subtitle:
            lines.append( f"## {slide.subtitle}" )

        if slide.content_bullets:
            lines.append( "" )
            for bullet in slide.content_bullets:
                lines.append( f"- {bullet}" )

        return "\n".join( lines )

    @staticmethod
    def _render_section_divider_slide( slide ) -> str:
        """
        Render a section divider with centered heading.

        Returns:
            str: Markdown for section divider slide
        """
        lines = [
            "<!-- _class: lead -->",
            "",
            f"# {slide.title}",
        ]

        if slide.subtitle:
            lines.append( f"## {slide.subtitle}" )

        return "\n".join( lines )

    @staticmethod
    def _render_conclusion_slide( slide ) -> str:
        """
        Render a conclusion/summary/CTA/Q&A slide.

        Same structure as content slide — distinction exists for
        future customization (e.g., different background color).

        Returns:
            str: Markdown for conclusion slide
        """
        return MarpTextRenderer._render_content_slide( slide )

    # =========================================================================
    # Presenter Notes
    # =========================================================================

    @staticmethod
    def _render_presenter_notes( notes ) -> str:
        """
        Render presenter notes as an HTML comment block.

        Marp displays these in presenter view only. Fields that are
        None or empty are omitted.

        Requires:
            - notes is a PresenterNotes instance (or has matching attributes)

        Ensures:
            - Returns HTML comment string or empty string if no content

        Returns:
            str: HTML comment block or empty string
        """
        if notes is None:
            return ""

        content_lines = []

        # Transition
        if notes.transition:
            content_lines.append( f"Transition: {notes.transition}" )
            content_lines.append( "" )

        # Talking points
        if notes.talking_points:
            content_lines.append( "Talking points:" )
            for point in notes.talking_points:
                content_lines.append( f"- {point}" )
            content_lines.append( "" )

        # Timing
        if notes.timing_seconds and notes.timing_seconds > 0:
            content_lines.append( f"Timing: {notes.timing_seconds}s" )

        # Emphasis
        if notes.emphasis:
            content_lines.append( f"Emphasis: {notes.emphasis}" )

        if not content_lines:
            return ""

        # Strip trailing empty lines
        while content_lines and content_lines[ -1 ] == "":
            content_lines.pop()

        inner = "\n".join( content_lines )
        return f"<!--\n{inner}\n-->"

    # =========================================================================
    # Visual Placeholders
    # =========================================================================

    @staticmethod
    def _render_visual_placeholder( slide ) -> str:
        """
        Emit a structured placeholder for Phase 7 visual rendering.

        Phase 7 will find these comments via regex and replace them
        with actual Mermaid blocks, images, or tables.

        Returns:
            str: Visual placeholder comment, or empty string for text_only slides
        """
        if slide.visual_type == "text_only":
            return ""

        description = slide.visual_description or "(no description provided)"
        return f"<!-- VISUAL: {slide.visual_type} | {description} -->"

    # =========================================================================
    # Template Interpolation
    # =========================================================================

    @staticmethod
    def _interpolate_template( template: str, presentation ) -> str:
        """
        Replace {title}, {speaker}, {date} placeholders in template strings.

        Requires:
            - template is a string (may contain placeholders)
            - presentation has title, speaker, date attributes

        Returns:
            str: Template with placeholders replaced
        """
        if not template:
            return ""

        result = template
        result = result.replace( "{title}", presentation.title or "" )
        result = result.replace( "{speaker}", presentation.speaker or "" )
        result = result.replace( "{date}", presentation.date or "" )

        return result.strip()


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for MarpTextRenderer."""
    import sys
    import os

    # Bootstrap PYTHONPATH
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root:
        src_path = os.path.join( lupin_root, "src" )
        if src_path not in sys.path:
            sys.path.insert( 0, src_path )

    from cosa.agents.presentation_generator.state import (
        PresentationModel, SlideModel, PresenterNotes
    )

    print( "=" * 60 )
    print( "MarpTextRenderer Smoke Test" )
    print( "=" * 60 )

    try:
        # Build a sample presentation
        presentation = PresentationModel(
            title            = "Three-Layer Caching at Scale",
            speaker          = "Jane Doe",
            date             = "2026-03-28",
            duration_minutes = 15,
            source_document  = "caching-article.md",
            total_slides     = 3,
            slides           = [
                SlideModel(
                    number       = 1,
                    arc_position = "opening",
                    type         = "title",
                    title        = "Three-Layer Caching at Scale",
                    subtitle     = "How We Achieved 3x Latency Improvement",
                    presenter_notes = PresenterNotes(
                        talking_points = [ "Welcome and introduce yourself" ],
                        timing_seconds = 30,
                    ),
                ),
                SlideModel(
                    number             = 2,
                    arc_position       = "body",
                    type               = "content",
                    title              = "Three-Layer Cache Eliminates Cold Starts",
                    visual_type        = "diagram",
                    visual_description = "Flowchart: L1 -> L2 -> L3 with hit-rate percentages",
                    content_bullets    = [
                        "L1: In-process cache -- handles 80% of requests",
                        "L2: Redis cluster -- shared across instances",
                        "L3: S3 with CloudFront -- cold storage fallback",
                    ],
                    presenter_notes    = PresenterNotes(
                        transition     = "So we've seen the problem -- now let's look at what we built.",
                        talking_points = [
                            "Explain the three cache layers left-to-right",
                            "Emphasize L1 handles 80% -- this is the key insight",
                        ],
                        timing_seconds = 75,
                        emphasis       = "The 80% L1 hit rate -- pause here",
                    ),
                ),
                SlideModel(
                    number       = 3,
                    arc_position = "closing",
                    type         = "conclusion",
                    title        = "Key Takeaways",
                    content_bullets = [
                        "Three-layer caching eliminates cold starts",
                        "L1 in-process cache is the biggest win",
                    ],
                    presenter_notes = PresenterNotes(
                        transition     = "Let me leave you with the main points.",
                        talking_points = [ "Recap the three main points" ],
                        timing_seconds = 45,
                    ),
                ),
            ],
        )

        # Render with default theme
        print( "\nTest 1: Render with default theme config..." )
        output = MarpTextRenderer.render( presentation, DEFAULT_THEME_CONFIG )
        assert "marp: true" in output, "Missing marp: true"
        assert "# Three-Layer Caching at Scale" in output, "Missing title"
        assert "<!-- _class: lead -->" in output, "Missing lead class"
        assert "Jane Doe | 2026-03-28" in output, "Missing speaker/date"
        assert "<!-- VISUAL: diagram |" in output, "Missing visual placeholder"
        assert output.count( "---" ) >= 4, f"Expected >=4 ---, got {output.count( '---' )}"
        print( "  PASS" )

        # Check slide separator count
        print( "\nTest 2: Slide separator count..." )
        # Frontmatter has 2 (open + close), then 2 separators between 3 slides
        # Total --- lines: 2 (frontmatter) + 2 (separators) = 4
        separator_lines = [ line for line in output.split( "\n" ) if line.strip() == "---" ]
        assert len( separator_lines ) == 4, f"Expected 4 --- lines, got {len( separator_lines )}"
        print( "  PASS" )

        # Check presenter notes
        print( "\nTest 3: Presenter notes rendering..." )
        assert "Transition: So we've seen the problem" in output, "Missing transition"
        assert "Talking points:" in output, "Missing talking points header"
        assert "Timing: 75s" in output, "Missing timing"
        assert "Emphasis: The 80% L1 hit rate" in output, "Missing emphasis"
        print( "  PASS" )

        # Check CSS
        print( "\nTest 4: CSS generation..." )
        assert "font-family: Inter" in output, "Missing body font"
        assert "color: #2563EB" in output, "Missing primary color"
        assert "JetBrains Mono" in output, "Missing code font"
        print( "  PASS" )

        # Empty presentation
        print( "\nTest 5: Empty presentation..." )
        empty = PresentationModel( title="Empty", total_slides=0 )
        empty_output = MarpTextRenderer.render( empty, DEFAULT_THEME_CONFIG )
        assert "marp: true" in empty_output, "Missing marp: true in empty"
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All MarpTextRenderer smoke tests passed" )
        print( f"{'=' * 60}" )
        print( f"\nGenerated output ({len( output )} chars):\n" )
        print( output )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
