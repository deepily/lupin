---
capability: judge-validation
pin_algorithm: py3.13.xaad549/ts5.9.3
pins: [
  cosa.agents.prediction_engine.answer_judge.JudgeReplyError@4c74edf80c, cosa.agents.prediction_engine.answer_judge.JudgeHashMismatch@c7bc5334df, cosa.agents.prediction_engine.answer_judge.build_user_prompt@afa783b4d9, cosa.agents.prediction_engine.answer_judge.parse_verdict@a1a8dad5a4, cosa.agents.prediction_engine.answer_judge.judge_model@ed2af9866f, cosa.agents.prediction_engine.answer_judge.judge_identity@b6c628e117, cosa.agents.prediction_engine.answer_judge.check_identity@0d8c6223bc, cosa.agents.prediction_engine.answer_judge.request_settings@04e170010f, cosa.agents.prediction_engine.answer_judge.make_judge@b1ab099588,
  cosa.research.judge_validation.capture.load_cases@7fb6af89d7, cosa.research.judge_validation.capture.capture_case@99f935164a, cosa.research.judge_validation.capture.replay_complete@0290fca8bb, cosa.research.judge_validation.capture.main@41d7711570,
  cosa.research.judge_validation.draw.pattern_of@d126f42d4e, cosa.research.judge_validation.draw.exclusion_of@248f0046cd, cosa.research.judge_validation.draw.eligible@6e15482d97, cosa.research.judge_validation.draw.draw_sample@799062a4e2, cosa.research.judge_validation.draw.card_rows@351e02eec0, cosa.research.judge_validation.draw.reader_files@baf3301be0, cosa.research.judge_validation.draw.write_sample@48ac1c4d2f, cosa.research.judge_validation.draw.main@36f0f21e0f,
  cosa.research.judge_validation.flips.read_pairs@ebe81789d3, cosa.research.judge_validation.flips.run_pair@677c3d7452, cosa.research.judge_validation.flips.result_path@b23d8f2d19, cosa.research.judge_validation.flips.run_set@ed6ad75b13, cosa.research.judge_validation.flips.main@35135918b0,
  cosa.research.judge_validation.labels.read_reader_labels@1e1a942364, cosa.research.judge_validation.labels.read_export@73143cb4cb, cosa.research.judge_validation.labels.settle@fb5f69b794, cosa.research.judge_validation.labels.main@c63aafe5c1,
  cosa.research.judge_validation.scoring.record_identity@bc88698227, cosa.research.judge_validation.scoring.read_identity@f7766c6813, cosa.research.judge_validation.scoring.says_material@c8de0bcf34, cosa.research.judge_validation.scoring.judge_row@c0c8df12ee, cosa.research.judge_validation.scoring.run_judge@483fca3119, cosa.research.judge_validation.scoring.proportion@31bcd2710f, cosa.research.judge_validation.scoring.weighted_rate@f077f02e61, cosa.research.judge_validation.scoring.agreement@2db518805c, cosa.research.judge_validation.scoring.arm_name@9dfccdc600, cosa.research.judge_validation.scoring.self_reference@c594362cd0, cosa.research.judge_validation.scoring.arm_bias@8327dc6d3f, cosa.research.judge_validation.scoring.check_labels@a1248bfbaf, cosa.research.judge_validation.scoring.pass_line@34d2b238e2, cosa.research.judge_validation.scoring.reader_agreement@9fa2b00def, cosa.research.judge_validation.scoring.build_report@16bef6e3e0, cosa.research.judge_validation.scoring.main@d3c8441295,
]
---
# The answer judge and its validation
The answer judge says whether a forecast keeps every restriction of the real answer and invents nothing. `cosa.research.judge_validation` checks it against human labels before it scores anything.

## The judge (`answer_judge`)
- `make_judge` returns `judge( predicted_text, actual_text )`. The model splits both texts into atoms; `parse_verdict` computes the two booleans from them.
- It calls bounded Claude Code. The model id is the INI key `principle learner answer judge model`.
- `judge_identity` hashes the model, the rubric `src/conf/prompts/answer-judge-rubric.txt` and the reader. Any difference raises `JudgeHashMismatch`.

## The sample and the labels (`draw`, `labels`)
- `draw` keeps only pairs the judge would be asked about, from the eligible arms. It writes the sample once, with blind answer and forecast files for the readers. A yes/no answer row shows the stance, and a blank condition reads "no condition added".
- `labels` settles one truth label per pair from two readers and Rick's export. Rick's answer decides over agreement.

## The report and the pairs (`scoring`, `flips`)
- `scoring run` judges the sample and resumes if interrupted. `scoring report` needs sensitivity and specificity of at least 0.90, with their lower bounds.
- A card type needs 30 cards in both its error and correct cells, or it reads "judge not validated".
- The report also splits agreement, per arm and card type, by whether the forecast refers to an earlier answer.
- `flips` runs 24 minimal pairs, once per judge identity and set. Keep those pairs for that run alone.

## The test fixtures (`capture`)
- `capture.py` runs fixture cases, kept apart from the 24 pairs, on the real model. It commits the prompts and replies under `src/tests/fixtures/answer_judge/`.
- Its replay refuses any request it did not record, apart from the random tag suffix.
