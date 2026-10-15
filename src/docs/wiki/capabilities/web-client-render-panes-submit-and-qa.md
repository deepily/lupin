---
capability: web-client-render-panes-submit-and-qa
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.qaChrome.metricSpan@9c85660b43
  - src.lupin_app.static.js.multiplexer.render.templates.qaChrome.renderQaChrome@fb508d0699
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.el@2ab9973821
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.checkbox@da1a63f96e
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.labelled@8f8fc7073f
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.statusLine@4c4e78c03c
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.submitButton@6bffe5208e
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.cardHeader@a517606a01
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.scheduleRow@aab2ecb512
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.option@4469baf8b7
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.buildCcCard@466d447710
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.buildResearchCard@5f22c78f26
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.buildTestSuiteCard@81585035b7
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.buildTfeCard@3c6c56ed68
  - src.lupin_app.static.js.multiplexer.render.templates.submitJobsChrome.renderSubmitJobsChrome@a7f6ec266b
---
# Render panes: submit and question chrome

Pure element builders for the Submit Agentic Jobs pane and the question pane. Each returns handles and attaches no listeners.

## Question pane
- `renderQaChrome()` returns `QaChromeElements`. It holds the body, an empty agent select, mode badge and status, a mic button and the input. It also holds a speech-mode select, the submit button with spinner, the metrics strip, the interview box and the response box.
- The badge, spinner, metrics and interview box start hidden. The speech select offers instant and reliable, with instant chosen. The response starts as "No response yet...". `QaPaneRenderer` is the only caller.
- `metricSpan( label, valueId, testid )` is private. It builds one label and value pair, with the value starting as two dashes. It returns the wrapper and the value span.

## Submit pane
- `renderSubmitJobsChrome()` returns the body and four cards: Claude Code, research, test suite and test-fix resume. `SubmitJobsPaneRenderer` is the only caller.
- `buildCcCard`, `buildResearchCard` and `buildTestSuiteCard` return their card handles. Each starts collapsed with a right-pointing chevron, an empty status line, a hidden spinner and a checked dry-run box.
- `buildTfeCard` has no chevron and is always open. It holds a text area, a Resume button, a status line and a hidden candidates list.
- The test suite card offers grouped suite options with `integration,e2e` chosen. Its file path and fail-fast rows start hidden.
- `scheduleRow( prefix, withMonopolize )` adds a schedule checkbox and a hidden time input. The exclusive checkbox is left out when false, as for the test suite.
- Private helpers: `el` makes a tag with class and test id, `checkbox` sets id, test id and checked. `labelled` wraps a control in a label. `statusLine` makes the status div and `option` an option. `submitButton` makes a button plus spinner, and `cardHeader` a title plus chevron.

The cards share the helpers, so their ids and test ids follow one pattern. The renderers wire clicks, schedule reveal and submit calls on top. See [[web-client-render-panes-section-chrome]] for the headers that collapse these bodies.
