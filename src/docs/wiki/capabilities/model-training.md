---
capability: model-training
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.training.peft_trainer.PeftTrainer@310aeed65a
  - cosa.training.xml_coordinator.XmlCoordinator@a32705732a
  - cosa.training.xml_prompt_generator.XmlPromptGenerator@c1eebae41b
  - cosa.training.xml_response_validator.XmlResponseValidator@8b49086124
  - cosa.training.quantizer.Quantizer@c2a93ea741
  - cosa.training.hf_downloader.HuggingFaceDownloader@ec08549f99
  - cosa.training.corpus_fingerprint.verify@1787dcfd51
  - cosa.training.conf.model_config_loader.load_model_config@ba69d124ed
---
# Model training

This capability builds XML fine-tuning data from a command corpus and trains a LoRA model on it. It then merges and quantizes the result.

## What it does
- `XmlCoordinator` reads the command manifests, expands placeholders, and builds the prompt table. It splits the table into train, test and validate JSONL files.
- `XmlPromptGenerator` loads the prompt templates and fills them with interjections, salutations and placeholder values. Both classes read the project root per instance when `path_prefix` is not given.
- `XmlResponseValidator` checks a model reply against the XML schema and the expected command. It reports per-check rates.
- `PeftTrainer` fine-tunes with LoRA, saves checkpoints, merges the adapter, and quantizes the merged model with `Quantizer`.
- `Quantizer` runs AutoRound on a loaded model and saves it. `HuggingFaceDownloader` fetches a repo snapshot.
- `load_model_config` maps a model name to one file in `training/conf/`.

## How a run goes
- Generate: `XmlCoordinator` writes three JSONL files under `src/ephemera/prompts/data`. A fingerprint file beside them records the corpus hash.
- Verify: `corpus_fingerprint verify` exits 0 on a match, 1 on a mismatch or missing stamp, and 2 when no dataset exists yet.
- Train: `PeftTrainer.run_pipeline` can validate before and after training, and after quantization. Validation uses a vLLM server.

## Research
- `src/cosa/research/` holds one study package, `phi4_flash_lite_study`. It replays frozen direct-message bodies against two models.
- It reads production code and does not train anything.

## Don't
- Don't regenerate the dataset to clear a mismatch. It rebuilds from the corpus on disk, so decide which side is current first.
- Don't expect a comment or blank-line edit to change the fingerprint. It hashes only the lines the loader reads.
- Don't train a model with no entry in `MODEL_CONFIG_MAP`.
- Don't run `--nuclear-kill-button` without sudo. The trainer exits with instructions.
- Related pages: [[xml-io-models]], [[agent-llm-clients]].
