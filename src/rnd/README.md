# R&D Documentation Index

Research and development documents for the Lupin project, organized by release version.

## Version Directory Index

Documents are archived into the branch/version where they were completed. Date prefixes on filenames determine assignment.

| Version | Period | Files | Subdirs | Focus |
|---------|--------|------:|--------:|-------|
| [v0.5.0](v0.0.5/) | ≤ 2025-07-10 | 7 | 1 | WebSocket TTS streaming, early notification design |
| [v0.6.0](v0.0.6/) | Jul 11 – Aug 1, 2025 | 11 | 0 | WebSocket user routing, progressive TTS, async bridge |
| [v0.7.0](v0.0.7/) | Aug 2 – Aug 15, 2025 | 12 | 0 | Fresh Queue UI, audio caching, smoke testing, job replay |
| [v0.8.0](v0.0.8/) | Aug 16 – Sep 27, 2025 | 5 | 1 | LanceDB migration, three-level question architecture |
| [v0.9.0](v0.0.9/) | Sep 28 – Oct 7, 2025 | 7 | 1 | JWT/OAuth auth system, admin user management |
| [v0.1.0](v0.1.0/) | Oct 8 – Dec 31, 2025 | 28 | 2 | SSE notifications, PostgreSQL, Cloud Run, sender-aware UI |
| [v0.1.1](v0.1.1/) | Jan 1 – Jan 28, 2026 | 18 | 3 | MCP integration, Docker Claude Code, deep research queue |
| [v0.1.3](v0.1.3/) | Jan 29 – Feb 4, 2026 | 11 | 1 | CJ Flow protocol, test remediation, runtime expeditor |
| [v0.1.4](v0.1.4/) | Feb 5 – Feb 16, 2026 | 29 | 2 | PEFT training, calculator agent, proxy design, SWE team |
| [v0.1.5](v0.1.5/) | Feb 17 – Mar 11, 2026 | 15 | 3 | Playwright E2E, trust proxy, voice I/O integration |
| [v0.1.6](v0.1.6/) | Mar 12 – present | 33 | 3 | CJ Flow persistence, timed execution + monopolize + pause, scheduling UI + voice runtime args, presentation generator, test isolation, bug fix expediter, SDK upgrade |

**Note**: v0.1.2 was released the same day as v0.1.1 (2026-01-28) — no documents fall in its window.

## How Documents Are Assigned

1. Each document's `YYYY.MM.DD-` date prefix determines its version assignment
2. Version boundaries are derived from git tag dates (release points)
3. Documents that straddle two branches are placed in the branch where they were **finished**
4. Subdirectories (multi-file research topics) move as a unit based on their date prefix

## Adding New Documents

New R&D documents should be placed directly in the **current version directory** (currently `v0.1.6/`). When a new version branch is created, create a new directory for it and place subsequent documents there.

Naming convention: `YYYY.MM.DD-descriptive-kebab-case-name.md`
