# TODO

Last updated: 2026-01-28 (Session 107)

## Pending

### job_state_transition Implementation (Session 107 - In Progress)

- [x] Phase 1: Add job_state_transition to config files
- [x] Phase 2: Add _emit_job_state_transition method to FifoQueue
- [x] Phase 3: Add server emissions (7 transition points)
- [ ] Phase 4: Client subscription to job_state_transition
- [ ] Phase 5: Client handler (handleJobStateTransition, insertJobMetadata)
- [ ] Phase 6: Badge-only queue_*_update handlers
- [ ] Phase 7: Placeholder DOM nodes in renderJobCard()
- [ ] Phase 8: Remove cruft - data structures
- [ ] Phase 9: Remove cruft - methods
- [ ] Phase 10: Remove cruft - logic
- [ ] WebSocket smoke tests after Phase 10
- [ ] Manual browser verification of job transitions

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

### Carried Over from Session 102

- [ ] Test math agent notification fixes (hard refresh, ask "What's 11+11?", verify console logs and TTS)
- [ ] Verify both notifications appear in job card (not sender card)
- [ ] Future: Add `tts_raw` parameter to cosa-voice MCP server

### COSA Submodule (Needs Separate Commit)

- [ ] Commit API consistency fix: `deep_research.py` derives user_email from JWT
- [ ] Commit dry-run mode additions to routers and job classes
- [ ] Commit new `mock_clients.py` for Podcast Generator

## Completed (Recent)

- [x] Rename `currentUser` to `currentUserEmail` in notifications.js - Session 106
- [x] Remove redundant `user_email` from Deep Research JS request body - Session 106
- [x] Fix job cards not rendering when queue collapsed - Session 105
- [x] Fix TTS notification duplication in job cards - Session 104
- [x] Add dry-run checkboxes to agentic job submission UI - Session 103

---

*Completed items older than 7 days can be removed or archived.*
