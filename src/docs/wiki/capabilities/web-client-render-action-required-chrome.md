---
capability: web-client-render-action-required-chrome
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredChrome.projectBadge@76e905e73a
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredChrome.personaBadge@71e95cfe51
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredChrome.abstractIndicator@2c6c62bd11
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredChrome.abstractBlock@6b33186770
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredChrome.predictionHintBox@1429be246e
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredChrome.predictedText@f68024fe7d
---
# Action-required card chrome

Small builders for the badges, abstract and prediction hint that sit around an action-required card's prompt.

## What it does
- `projectBadge( senderId )` returns a `.mc-project-badge` span reading `[PROJECT]`. It returns null for an undefined id or when no project can be read from the id.
- The project comes from an id shaped `claude.code@<project>.deepily.ai` and is upper-cased.
- `personaBadge( persona )` returns a `.persona-badge` with the persona's icon and name, coloured through `--persona-color`. A borrowed persona also gets the `borrowed` class. A null or undefined persona gives null.
- `abstractIndicator( abstract )` returns the 📋 `.abstract-indicator` button, or null when the abstract is undefined or blank. The raw text rides on `data-abstract`, and the tooltip reads it.
- `abstractBlock( abstract )` returns a `.action-required-abstract` block holding the abstract as sanitized markdown, or null when blank.
- `predictionHintBox( item, vote )` always returns a box. A missing hint gives the `prediction-hint-cold` box reading "Learning, no prediction yet".
- Otherwise the box shows the predicted value, plus the strategy when the hint has one.
- `predictedText( responseType, value )` capitalizes a non-empty `yes_no` string, leaves other strings alone and turns other values into JSON.

## How the parts work together
`ActionRequiredRenderer` calls these builders and places the results around the prompt. The indicator feeds [[web-client-render-abstract-tooltip]]; the card forms are in [[web-client-render-action-required-interactive]].

## Invariants
- Vote controls are added only when `vote` is given. They are built from `vote.getVote( id_hash )` and the rounded confidence percent.
- The controls are null below 50 percent confidence, so a low-confidence hint shows no thumbs.
