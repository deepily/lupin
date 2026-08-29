"""
Canonical language-code → display-label map — the single source of truth.

Deliberately a LEAF module with NO imports. Importing any submodule of
`cosa.agents.podcast_generator` first runs that package's __init__, which eagerly
loads the orchestrator / api_client chain (mcp + pydantic, ~900 modules) — far
heavier than a label lookup needs, and the cause of an import-order unit-test
failure that once forced this map to be hand-copied into the DRP job (row
81040071). Keeping the map here lets both `podcast_generator.config` and
`deep_research_to_podcast.job` import ONE copy without that weight, so the two
labels can never drift and mislabel a language in front of an audience.
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
