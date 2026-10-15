---
capability: multiplexer-render-flow-ratio
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.isNum@8a48bbe97e
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioWindowDays@45bf3dec50
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioPercentText@d39d0543ce
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioRoomText@5583b51122
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.formatFlowRatio@97e9f25f0f
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioReadoutText@80bf0db112
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioLongForm@ca6e514073
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioIsOpen@646ac36677
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioSettingsUsable@dcba9ecacb
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioThreshold@a7427bf444
  - src.lupin_app.static.js.multiplexer.render.flowRatioModel.flowRatioSourceLine@3a408ac981
  - src.lupin_app.static.js.multiplexer.render.flowRatioPanel.output@2b1bb1e2ee
  - src.lupin_app.static.js.multiplexer.render.flowRatioPanel.range@a1654cf100
  - src.lupin_app.static.js.multiplexer.render.flowRatioPanel.field@bc113b2eaa
  - src.lupin_app.static.js.multiplexer.render.flowRatioPanel.buildControls@24407d1794
  - src.lupin_app.static.js.multiplexer.render.flowRatioPanel.createFlowRatioPanel@b4c2b41c97
---
# Multiplexer flow-ratio render

Text helpers and the panel for the create gate readout, closed against new tickets over a window, with sliders for its threshold and window.

## Text (`flowRatioModel`)
- `isNum` is the shared number test. `flowRatioWindowDays( hours )` is whole days, at least 1, or null for an unusable window.
- `flowRatioPercentText( payload )` is the rounded percent, `∞` when nothing closed but something was created, else a dash.
- `flowRatioRoomText( payload )` reads `close_needed`, then `room_for`, then `FULL` at zero room. It reads the payload and computes nothing.
- `formatFlowRatio( payload, provisionalDays )` is the clause after the word Gate, or empty for an unusable payload. While a slider drags it says `recounting…` and withholds the old counts.
- `flowRatioReadoutText` wraps that clause as a middle dot, `Gate:` and the clause, or empty. `flowRatioLongForm` adds the hover caveat that creation counts every project and priority.

## Gate state
- `flowRatioIsOpen( payload, threshold )` is true when the ratio is strictly below the threshold, so equal reads closed. A missing threshold reads open. `flowRatioSettingsUsable( settings )` needs `allow_below` and `window_hours` as numbers.
- `flowRatioThreshold( settings, payload )` prefers usable settings, then the payload's `allow_below`, else NaN.
- `flowRatioSourceLine( settings )` says `saved override` when the window or threshold source is `override`, else `from config`.

## Panel (`flowRatioPanel`)
- `output`, `range` and `field` build a readout, a range input and a labelled pair. `buildControls` builds the hidden cluster, with its freeze checkbox checked in markup.
- `createFlowRatioPanel( { bus, store } )` returns the readout and the controls. It builds the controls once. Sliders repaint only for a different settings body, so a drag is left alone.
