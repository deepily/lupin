---
capability: model-server-liveness-and-transcript-tail
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.model_server_liveness.ModelServerUnavailable@a34040df65
  - cosa.utils.model_server_liveness.discover_vllm_endpoints@df7e2470bf
  - cosa.utils.model_server_liveness.parse_vllm_endpoint@9b9a8546f9
  - cosa.utils.model_server_liveness.probe_endpoint@c839f55a74
  - cosa.utils.model_server_liveness.probe_endpoints@e488e5c688
  - cosa.utils.model_server_liveness.render_refusal@188dbc9d78
  - cosa.utils.model_server_liveness.require_live@ce674971d8
  - cosa.utils.transcript_tail.read_tail_bytes@d9b640760b
  - cosa.utils.transcript_tail.read_window_before@2694380be0
  - cosa.utils.transcript_tail.read_window_from@91cdf202b3
  - cosa.utils.transcript_tail.tail_jsonl@def5d63886
---
# Model-server liveness and transcript tail

Two small standard-library helpers. `model_server_liveness` refuses a long run when a vLLM endpoint is not answering. `transcript_tail` reads JSONL transcripts by byte offset for the console in [[session-transcript-console]]. The Whisper and embedding service is a different thing; see [[model-server]].

## What it does
- `parse_vllm_endpoint( spec )` returns `host:port` from a `vllm://host:port@model` string, or None for anything else, including non-strings.
- `discover_vllm_endpoints( config_mgr )` walks every key of the config manager, collects the distinct endpoints and returns them sorted.
- `probe_endpoint( endpoint, timeout_s=5.0, url_opener=None )` does a GET of `http://<endpoint>/v1/models` and returns `{ endpoint, alive, detail, models }`. It does not raise on a refusal, timeout, bad status or unreadable body; `detail` says which. A 200 with a body that is not a model list is `alive` False.
- `probe_endpoints` probes every endpoint, even after one fails. `render_refusal( results, context="" )` lists the silent ones first.
- `require_live( endpoints=None, config_mgr=None, ... )` returns the probe report when all answered. It raises `ModelServerUnavailable` (a `RuntimeError`) when any did not, or when there is nothing to probe. It raises `ValueError` given neither `endpoints` nor `config_mgr`.
- `tail_jsonl( path, offset=0 )` returns `( records, new_offset, rotated )`. If the file is shorter than `offset` it returns `( [], 0, True )` and no records, so the caller can reset its epoch.
- `read_tail_bytes( path, tail_bytes )` returns `( records, start_offset, next_offset )` for the last `tail_bytes` bytes, starting on a whole line. 0 means the whole file.
- `read_window_before( path, before_offset, max_bytes )` pages backwards. It returns `( [], 0, 0 )` at the top of the file.
- `read_window_from( path, since_offset, max_bytes )` reads forward from an offset. A `since_offset` past the end returns `( [], size, size )`.

## Don't
- Don't treat `require_live` passing as proof the right model is loaded. It checks that the endpoint answered and reports the model ids; it does not compare them.
- Don't read `( [], offset, False )` from the transcript functions as "quiet seat". A missing or unreadable path returns exactly that, and none of them raise.
- Don't expect a partial last line to be returned. It is left for the next read.

## Invariants
- The byte cap in the three window readers is a target. If one record is larger than the cap, that record is returned whole so a page always makes progress.
- Blank, malformed and non-object JSON lines are skipped.
- Every returned offset sits on a line boundary.
