---
capability: web-client-jobs-and-session-panes
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.JobsPaneRenderer.createJobsPaneRenderer@a08bb5c22b
  - src.lupin_app.static.js.multiplexer.stores.jobViewFilter.isJobVisibleTo@8e1be83e5a
  - src.lupin_app.static.js.multiplexer.render.SubmitJobsPaneRenderer.createSubmitJobsPaneRenderer@ed1f7ef6d6
  - src.lupin_app.static.js.multiplexer.render.QaPaneRenderer.createQaPaneRenderer@fd9ff61c2e
  - src.lupin_app.static.js.multiplexer.render.SessionStripRenderer.createSessionStripRenderer@d72cf551f2
  - src.lupin_app.static.js.multiplexer.render.PersonaModalRenderer.createPersonaModalRenderer@1172120b30
  - src.lupin_app.static.js.multiplexer.render.NavBarRenderer.createNavBarRenderer@33e3f45501
  - src.lupin_app.static.js.multiplexer.render.ReadingPaneRenderer.createReadingPaneRenderer@4758bf7018
---
# Browser jobs and session panes

Seven renderers in `src/lupin_app/static/js/multiplexer/render/` drive the jobs, submit, Q&A, session strip, persona modal, nav bar and reading panes.

## Jobs pane
- Five buckets render in order: todo, running, done, dead and history. Todo and running start open, and the user's choice is kept in browser storage.
- A job that changes state goes to the end of its new bucket, and nothing sorts the list. History comes from `/api/job-history`: 20 rows from the last 30 days, with a window menu and Load more.
- Admins pick Mine, Not Mine or All Users. Everyone else sees only their own jobs, and a job with no `user_email` is always shown.
- Retry shows only on dead and history cards. It posts the saved question text to `/api/v2/ask`.

## Submit jobs pane
- Four cards submit Claude Code, Research, Test Suite and Resume (TFE) work. All use `/api/v2/submit` except Resume, which posts to `/api/v2/resume-job`.
- The store sends 200 turns for Interactive and 50 otherwise, but the page's Interactive option is disabled, so only 50 can be sent.
- Research sends 3.0 when the budget field parses to nothing or zero. Any other number goes through, even a negative one. The Test Suite card takes its auto-fix default from `/api/config/client`.

## Q&A pane
- A question goes to `/api/v2/ask`, or to `/api/v2/submit` when an agent is chosen. Any submit within 2 seconds of the last is dropped, even if that one failed.
- A finished job's answer is written into the pane and queued for speech unless the slider is at 0%. The TTS mode menu sets `instant` or `reliable` on the audio store.

## Sessions
- The session strip shows one icon per persona session, sorted by assignment time. The server assigns personas, and the page never chooses one.
- Clicking an icon focuses that sender and hides other senders' cards. Focus and the hide-inactive toggle are saved in browser storage only.
- The persona modal is a read-only popover with the icon, name, voice and a Borrowed row.
- The nav bar has the brand link, a menu button, Home, and Notifications and Profile when signed in. It shows the email with Logout, or a Login link.

## Reading pane
- It shows an abstract as rendered markdown, or a document in an iframe. It keeps up to ten entries for Back, and the split drags between 30% and 85%. An Action Required item takes the pane only in horizontal layout. Its split starts at 50% without being saved, a drag still applies, and the earlier ratio returns on exit. Close does nothing and opening another entry is refused.
