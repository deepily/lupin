---
capability: dm-rewrite-study-checks
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.research.phi4_flash_lite_study.arm_markers.ArmNotVerified@23f71b4e6a
  - cosa.research.phi4_flash_lite_study.arm_markers.assert_vertex_arm_markers@9e41d3e411
  - cosa.research.phi4_flash_lite_study.arm_markers.read_vertex_arm_markers@f1cee0a0b1
  - cosa.research.phi4_flash_lite_study.statistics.DiscordantFloorNotMet@62f52a07b1
  - cosa.research.phi4_flash_lite_study.statistics.FloorNotPreStated@19247f4c07
  - cosa.research.phi4_flash_lite_study.statistics.assert_floor_pre_stated@5c7920a868
  - cosa.research.phi4_flash_lite_study.statistics.mcnemar_exact@420e9fb9d2
  - cosa.research.phi4_flash_lite_study.statistics.must_fail_control@d40fda2591
  - cosa.research.phi4_flash_lite_study.statistics.scipy_version@f23ceccafa
  - cosa.research.phi4_flash_lite_study.statistics.wald_lower_bound@5369d8312c
  - cosa.research.phi4_flash_lite_study.statistics.wilson_interval@6e8c76e3fa
---
# DM rewrite study: arm checks and statistics

The proof that an arm reached its model, and the tests, in [[dm-rewrite-model-study]]. The callers are in [[dm-rewrite-study-replay]].

## What it does
- `read_vertex_arm_markers` reads the endpoint, model id, `vertexai` flag, project and API key off a built client. It calls no model and resolves no credentials.
- `assert_vertex_arm_markers` raises `AssertionError` naming the marker that failed: host `aiplatform.googleapis.com`, model `gemini-3.1-flash-lite`, `vertexai` true with a project, and no API key.
- `ArmNotVerified` is what the harness-facing wrapper raises. A green result means the arm is wired to Vertex, not that Flash-Lite answered.
- `mcnemar_exact` runs the exact binomial test on `b` and `c`, with p 1.0 for no discordant pairs. `wilson_interval` is closed-form and returns `( 0.0, 1.0 )` for no trials.
- `wald_lower_bound` exists only for `must_fail_control`, which shows at 6 of 6 that Wilson sits below Wald.
- `assert_floor_pre_stated` raises `FloorNotPreStated` for a missing floor, `ValueError` for one under 6, and `DiscordantFloorNotMet` for too few pairs.
- `scipy_version` reads the installed version at run time, and every result records it.

## Don't
- Don't use `statsmodels`. It is not installed, and its default interval is the Wald one this study refuses.
- Don't choose the floor after seeing `b` and `c`. It is stated before the first arm runs.
- Don't read `model_id` as a read-back. It compares the factory's own input to itself.

## Invariants
- Fewer than 6 discordant pairs cannot reach p below 0.05, whatever the split.
- `compare_arms` raises rather than returning a verdict under the floor.
