---
capability: decision-proxy-learning-models
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.decision_proxy.bayesian_trust.BayesianLogisticRegression@1a36e567ff
  - cosa.agents.decision_proxy.conformal_wrapper.ConformalDecisionWrapper@fb9a2a2800
  - cosa.agents.decision_proxy.proxy_decision_embeddings.ProxyDecisionEmbeddings@5e3df3a239
  - cosa.agents.decision_proxy.cbr_decision_store.CBRDecisionStore@0f9d22a77f
  - cosa.agents.decision_proxy.cbr_decision_store.CBRPrediction@765fb1b2e7
  - cosa.agents.decision_proxy.prompts.icrl_decision.build_icrl_prompt@8870265226
  - cosa.agents.decision_proxy.prompts.icrl_decision.format_case_history@bad9a195a5
---
# Decision proxy learning models

These are the statistical parts the trust system draws on. They are a Bayesian regression, a conformal check and a case-based vote over stored decisions.

[[decision-proxy]] holds the tracker that uses the regression. [[decision-strategy-contract]] holds the interface they serve.

## Regression and conformal check
- `BayesianLogisticRegression` keeps a weight vector and a covariance for four features by default. `update` takes one observation (outcome 1 or 0) and refines both in place.
- `predict` returns a success probability and an uncertainty. `sample_rate` draws one weight vector from the posterior and returns that draw's probability.
- `posterior_mean_rate` scores the average feature vector seen so far, and gives 0.5 before any observation. `to_dict` and `from_dict` save and restore the state.
- `ConformalDecisionWrapper` is calibrated on probability and label pairs. With fewer than `min_calibration_size` (30) pairs it stays uncalibrated.
- `predict_set` returns `approve`, `reject` or both. `should_defer` is true when both are in the set, and also while uncalibrated.

## Case-based voting
- `ProxyDecisionEmbeddings` stores decision records with a 768-dimension question embedding, through `PredictionDecisionRepository`. Methods are `add_decision`, `find_similar`, `exists` and `update_ratification_state`.
- `find_similar` returns similarity percent and record pairs, best first, above a threshold that defaults to 0.75. A failure gives an empty list.
- `CBRDecisionStore.predict` fetches the top `top_k` cases for the category with no threshold, then takes the majority `decision_value`.
- `CBRPrediction.confidence` is the best similarity (as a fraction) times the share of cases that agree. With no cases the verdict is `None` and the confidence 0.0.
- `build_icrl_prompt` formats those cases into a prompt that asks for one word, `approved` or `requires_review`. `format_case_history` numbers the cases and writes `unknown` for a missing field.

## Don't
- Don't expect the store methods to raise. `ProxyDecisionEmbeddings` catches every exception and logs it only under `debug`.
- Don't expect `predict` to apply `confidence_threshold`. The store keeps the value and does not compare against it.
- Don't call `update_ratification_state` for a missing id and expect an error. It logs under `debug` and returns.
