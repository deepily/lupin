"""
Canonical language-code to display-label map: the single source of truth.

This is a leaf module with no imports. Importing any submodule of
`cosa.agents.podcast_generator` first runs that package's __init__, which loads
the orchestrator and api_client chain (mcp and pydantic, about 900 modules).
That is far heavier than a label lookup needs, and it breaks import order in
unit tests. Keeping the map here lets `podcast_generator.config` and
`deep_research_to_podcast.job` import one copy without that weight. The two
labels can then never drift and mislabel a language in front of an audience.
"""

# ISO language code -> human-readable display label. Unknown codes fall back to
# the raw code at the call site via .get( code, code ).
LANGUAGE_NAMES = {
    "en"    : "English",
    "es"    : "Spanish",
    "es-ES" : "Castilian Spanish (Spain)",
    "es-MX" : "Mexican Spanish",
    "es-AR" : "Argentinian Spanish",
}
