---
capability: util-voice-config-stopwatch-and-torch
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.util.get_spoken_char_cap@642e509278
  - cosa.utils.util.get_tts_interaction_mode@22a445da4d
  - cosa.utils.util_stopwatch.Stopwatch@42a008126c
  - cosa.utils.util_stopwatch.Stopwatch.get_delta_ms@a2cec7d390
  - cosa.utils.util_stopwatch.Stopwatch.print@cd0d9bcf93
  - cosa.utils.util_pytorch.is_allocated_to_cpu@e8e08f1349
  - cosa.utils.util_pytorch.print_device_allocation@4f7a4d80fd
  - cosa.utils.util_pytorch.release_gpu_memory@e9fd57ffa5
---
# Voice settings, stopwatch and torch device helpers

Two voice settings from `cosa.utils.util`, `util_stopwatch` and `util_pytorch`. See also [[shared-utilities]].

## What it does
- `get_tts_interaction_mode()` returns `solo` or `chorus` from the `tts interaction mode` key. A missing key, a bad value or a config error all give `chorus`.
- `get_spoken_char_cap()` returns the int under `cosa voice spoken char cap`, default 500. It is the reject boundary for spoken text, and any config error gives the default.
- `Stopwatch( msg, silent )` records its start time and prints `msg` unless silent. As a context manager it restarts on entry and prints `Done in [N] ms` on exit.
- `Stopwatch.print( msg, prepend_nl, end, use_millis )` prints seconds, or `mm:ss` past 59 seconds, or milliseconds with `use_millis`. It joins the start message and `msg` with a space.
- `Stopwatch.get_delta_ms()` returns whole milliseconds since the start and stores `end_time`, `elapsed_time` and `delta_ms`.
- `is_allocated_to_cpu( model )` is True when any parameter is on the cpu. `print_device_allocation( model )` prints each parameter name and device.
- `release_gpu_memory( model )` moves the model to the cpu, collects garbage and empties the cuda cache when cuda exists.

## Don't
- `release_gpu_memory` moves the model to the cpu and leaves the caller's reference alone, still usable. The GPU memory is freed fully only once the caller drops its own reference.
- Do not use `Stopwatch.print` for hour-long runs. It reads `.seconds`, which wraps at one day.

## Invariants
- `Stopwatch.print` with `use_millis` ignores the `mm:ss` branch. A silent stopwatch prints nothing from any method.
