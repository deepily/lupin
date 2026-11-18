# authorized_by: task:94a8f561-ac7b-4de4-847b-7f37d0114da7
# author: Rick's resident expert (outside reviewer)
# added_by: Mr. Radio, at Rick's request (decision 6, 2026-11-18); uploaded by Rick 2026-11-18 10:39 EST; body unchanged
"""Compare history windows on the paired 50-target exports using only the Python standard library."""  # doc-lint: waive summary-length -- the expert's text, kept unchanged under decision 6

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re


def answer(notification):
    envelope = notification["response_value"]
    value = envelope.get("value", envelope)
    if notification["response_type"] in {"multiple_choice", "open_ended_batch"} and isinstance(value, str):
        return json.loads(value)
    return value


def stance(value):
    match = re.fullmatch(r"(yes|no|neither)(?:\s+\[comment:.*\])?", value.strip(), flags=re.I | re.S)
    return match.group(1).lower() if match else None


def windows(target):
    nearby = target["previous_notifications"]
    return {
        "target only": [],
        "last 1": nearby[:1],
        "last 3": nearby[:3],
        "last 5": nearby[:5],
        "last 3 questions": target["previous_questions"],
        "combined": target["context_ids_oldest_first"],
    }


def compatible_choice(previous_answers, header, labels):
    for notification in previous_answers:
        if notification["response_type"] == "multiple_choice":
            candidate = answer(notification)["answers"].get(header)
            if isinstance(candidate, str) and candidate in labels:
                return candidate
    return None


def score(target, sample, records, ids, counts):
    current = target["target_notification"]
    cutoff = datetime.fromisoformat(target["asked_at"])
    history = sorted((records[k] for k in ids), key=lambda r: r["notification"]["created_at"], reverse=True)
    counts["targets_with_history"] += bool(history)
    counts["links"] += len(history)
    previous_answers = []
    for record in history:
        n = record["notification"]
        assert datetime.fromisoformat(n["created_at"]) < cutoff
        status = next(link["answer_status_at_this_target"] for link in record["linked_targets"]
                      if link["target_notification_id"] == current["id"])
        counts["done_prefix"] += n["message"].strip().startswith("Done:")
        if status == "answered":
            assert datetime.fromisoformat(n["responded_at"]) <= cutoff
            actor = n["response_value"].get("answered_by") or {}
            if actor.get("user_id") == current["recipient_id"]:
                previous_answers.append(n)
    counts["targets_with_prior_answer"] += bool(previous_answers)

    # Exclude the three named test-account batches and the one possible arithmetic fixture
    # already identified in the first pilot. Score current answers only after choosing.
    if sample["answered_by"] != "rick" or current["id"].startswith("48a103a6"):
        return
    if current["response_type"] == "yes_no":
        prior = next((s for n in previous_answers if n["response_type"] == "yes_no"
                      and (s := stance(answer(n))) is not None), None)
        counts["stance_prior_used"] += prior is not None
        guess = prior or "yes"
        counts["stance_correct"] += guess == stance(answer(current))
        counts["stance_total"] += 1
    elif current["response_type"] == "multiple_choice":
        for field in current["response_options"]["questions"]:
            if field["multi_select"]:
                continue
            labels = [o["label"] for o in field["options"]]
            prior = compatible_choice(previous_answers, field["header"], labels)
            counts["choice_prior_used"] += prior is not None
            guess = prior or labels[0]
            counts["choice_correct"] += guess == answer(current)["answers"][field["header"]]
            counts["choice_total"] += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("context", type=Path)
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text())["predictions"]
    context = json.loads(args.context.read_text())
    by_id = {r["ref"]["notification_id"]: r for r in predictions}
    targets = context["targets"]
    assert len(by_id) == len(predictions) == len(targets)
    assert set(by_id) == {t["target_notification_id"] for t in targets}
    results = {}
    for target in targets:
        current = target["target_notification"]
        sample = by_id[current["id"]]
        assert current["id"] == target["target_notification_id"]
        assert sample["asked_at"] == target["asked_at"] == current["created_at"]
        assert sample["ref"]["prediction_log_id"] == target["prediction_log_id"]
        combined = target["context_ids_oldest_first"]
        assert len(combined) == len(set(combined)) == target["context_count"]
        assert set(combined) == set(target["previous_notifications"] + target["previous_questions"])
        for name, ids in windows(target).items():
            score(target, sample, context["records"], ids, results.setdefault(name, Counter()))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
