# Bug Fix Queue

## Session: 2026.01.23 (Session 95)
**Owner**: claude.code@lupin.deepily.ai#6fa77d02

### Queued
(No bugs currently queued)

### Completed
- [x] cosa-voice MCP project detection order bug - CoSA detected as Lupin (ad-hoc) - Fixed prior to session
- [x] LanceDB/PostgreSQL permissions issue - database recreation blocked by wrong ownership/permissions (from Session 94 TODO)
  - Fixed: `lupin.lancedb` ownership changed from root:root to rruiz:rruiz
  - Fixed: `postgresql-dev-data` permissions changed from 700 to 750 (group r-x added)

---

## Previous Session: 2026.01.22 (Session 92)
**Owner**: claude.code@lupin.deepily.ai#40d6e532
**Status**: Carried over 1 bug to next session

---

## Previous Session: 2026.01.21 (Session 89)
- [x] Gist enhancement with abstract fields → commit: f24337f (ad-hoc)
