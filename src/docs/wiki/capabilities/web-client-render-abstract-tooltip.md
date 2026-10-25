---
capability: web-client-render-abstract-tooltip
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.abstractTooltip.computeTooltipPosition@40bd59430b
  - src.lupin_app.static.js.multiplexer.render.abstractTooltip.AbstractTooltipImpl@f6bf7380f9
  - src.lupin_app.static.js.multiplexer.render.abstractTooltip.AbstractTooltipImpl.constructor@c627ea1a8c
  - src.lupin_app.static.js.multiplexer.render.abstractTooltip.AbstractTooltipImpl.mount@a881e1fdac
  - src.lupin_app.static.js.multiplexer.render.abstractTooltip.AbstractTooltipImpl.unmount@324108ce01
  - src.lupin_app.static.js.multiplexer.render.abstractTooltip.createAbstractTooltip@4e40028d19
---
# Abstract tooltip

The floating 📋 popover that shows a card's abstract when the page is in vertical layout.

## What it does
- `createAbstractTooltip( deps )` returns the controller and adds nothing to the page until `mount()`. `AbstractTooltipImpl` is the class behind it.
- Its constructor takes `getLayoutMode` and an optional `schedule`, which defaults to `requestAnimationFrame`.
- `mount()` appends one `#abstract-tooltip` dialog to `<body>` and listens for document clicks and Escape. A second `mount()` does nothing.
- `unmount()` removes both listeners and the element. It does nothing when the tooltip was never mounted.
- A click on `.abstract-indicator` reads its raw `data-abstract` text and renders it as markdown into the tooltip. The × button, a click outside or Escape hides it.
- In `horizontal` layout the indicator click is ignored, because the Reading Pane owns it there.
- `computeTooltipPosition( indicator, tip, viewport )` returns `{ top, left }`. Top is 8 px below the indicator, or 8 px above it when below would come within 10 px of the viewport bottom. When it flips above, top is never under 10 px.
- Left centres the tip on the indicator and is clamped 10 px inside both viewport edges.

## How the parts work together
`abstractIndicator` in [[web-client-render-action-required-chrome]] puts the text on the indicator. On a click the tooltip is shown hidden, one scheduled frame later it is measured, and `computeTooltipPosition` places it before it becomes visible. Boot mounts one tooltip with the reading pane's layout mode.

## Don't
- Don't html-encode the abstract before it reaches `data-abstract`. The tooltip reads the raw value.
