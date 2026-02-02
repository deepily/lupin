# TODO

Last updated: 2026-02-02 (Session 115)

## Pending

### Tomorrow's Priority

- [ ] Reinstall the skills builder multi-modality slash commands from the planning-is-prompting repo and rerun discovery mode
- [x] **Run Deep Research dry-run smoke test** - Session 115: All 5 tests passed (login, submit, structure, polling, verification). Job dr-6aa5d16d completed in ~10s with $0.00 cost.
- [x] **Run Podcast Generator dry-run API smoke test** - Session 115: All tests passed. Job pg-dd026977 completed in ~10s with $0.00 cost.
- [x] **Run Research→Podcast dry-run API smoke test** - Session 115: All tests passed. Job rp-221fe28e completed in ~14s with $0.00 cost.

### job_state_transition Implementation (Session 107 - Complete)

- [x] Phase 1: Add job_state_transition to config files
- [x] Phase 2: Add _emit_job_state_transition method to FifoQueue
- [x] Phase 3: Add server emissions (7 transition points)
- [x] Phase 4: Client subscription to job_state_transition
- [x] Phase 5: Client handler (handleJobStateTransition, insertJobMetadata)
- [x] Phase 6: Badge-only handlers
- [x] Phase 7: Placeholder DOM nodes in renderJobCard()
- [x] Phase 8: Remove cruft - data structures
- [x] Phase 9: Remove cruft - methods
- [x] Phase 10: Remove cruft - logic
- [x] WebSocket smoke tests after Phase 10
- [ ] Manual browser verification of job transitions

### Bug Fix: Job Card Field Parity (Session 107 - For Next Session)

- [ ] **Test bug fix**: WebSocket cards now include 6 missing fields (status, has_interactions, is_cache_hit, started_at, completed_at, duration_seconds)
- [ ] Verify cards created via WebSocket match server-fetched cards after page refresh
- [ ] Test with mock job submission (success path)
- [ ] Test with mock job failure (error path)

### Implementation Plans

- [ ] **Config Migration**: Implement Claude Agent SDK config migration plan documented at `src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md`

### Browser Testing (Agentic Job Submission)

- [ ] **Test 1**: Deep Research submission - verify job queues with dr-xxxxxxxx ID
- [ ] **Test 2**: Research→Podcast (checkbox) - verify rp-xxxxxxxx prefix and chained routing
- [ ] **Test 3**: Podcast Generator - Direct path mode (immediate queue)
- [ ] **Test 4**: Podcast Generator - Description mode (fuzzy match → multiple choice)
- [ ] **Test 5**: Error handling - empty topic shows validation warning
- [ ] **Test 6**: Dry-run mode - Deep Research breadcrumb notifications
- [ ] **Test 7**: Dry-run mode - Podcast Generator breadcrumb notifications
- [ ] **Test 8**: Dry-run mode - Chained workflow (both sets of breadcrumbs)

### Verification Checklist

- [ ] Research card submits to `/api/deep-research/submit`
- [ ] Checkbox routes to `/api/deep-research-to-podcast/submit`
- [ ] Podcast card submits to `/api/podcast-generator/submit`
- [ ] Job IDs use correct prefixes (dr-, rp-, pg-)
- [ ] Jobs appear in queue UI after submission
- [ ] STT buttons work for voice input
- [ ] Loading spinners show during submission
- [ ] Error messages display correctly

### Architecture Review

- [ ] **Cache Hit Behavior**: Revisit cache hit logic in `running_fifo_queue.py:_format_cached_result()`. Currently propagates cached `answer_conversational` without re-running code. General rule should be: re-run the code instead of simply returning cached conversational answer. May need to distinguish between "answer cache" vs "computation cache". See Session 107 discussion.

### Future Considerations

- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.

### Carried Over from Session 102

- [x] Test math agent notification fixes (hard refresh, ask "What's 11+11?", verify console logs and TTS) - Session 109 ✅
- [ ] Verify both notifications appear in job card (not sender card)
- [ ] Future: Add `tts_raw` parameter to cosa-voice MCP server

### COSA Submodule (Needs Separate Commit)

- [ ] Commit API consistency fix: `deep_research.py` derives user_email from JWT
- [ ] Commit dry-run mode additions to routers and job classes
- [ ] Commit new `mock_clients.py` for Podcast Generator

## Completed (Recent)

- [x] **Math Agent TTS Fix**: job_id pattern + user_email pipeline - Session 109, 110
  - Fix: Updated regex in `notification_models.py` to accept compound hash format
  - Fix: Added `user_email` as first-class constructor parameter (Session 110)
  - Verified: TTS now works for math questions via /api/push
- [x] job_state_transition Phases 6-10 (badge handlers, DOM nodes, cruft removal) - Session 107
- [x] WebSocket smoke tests for job_state_transition - Session 107
- [x] Bug fix implementation: Add 6 missing fields to WebSocket metadata - Session 107
- [x] Rename `currentUser` to `currentUserEmail` in notifications.js - Session 106
- [x] Remove redundant `user_email` from Deep Research JS request body - Session 106
- [x] Fix job cards not rendering when queue collapsed - Session 105
- [x] Fix TTS notification duplication in job cards - Session 104
- [x] Add dry-run checkboxes to agentic job submission UI - Session 103

---

*Completed items older than 7 days can be removed or archived.*
