"""
io_models Unit Tests

Pydantic XML I/O model tests for the cosa.agents.io_models package
(xml_models + utils: util_xml_pydantic, xml_parser_factory,
prompt_template_processor) plus the agent-migration regression suites
(weather / bug_injector / iterative_debugging).

Relocated 2026-06-03 from the in-package dir src/cosa/agents/io_models/tests/
(which sat OUTSIDE the canonical green-gate collection roots and was therefore
never counted) into the canonical src/cosa/tests/unit/agents/ tree so the
existing 215-test suite is collected by the campaign gate — CoSA coverage
campaign, Cheech 🌿, blessed by Tiberius 👑. Test-relocation only, no prod edits.
"""
