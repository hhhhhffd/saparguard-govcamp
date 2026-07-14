from __future__ import annotations


def classification_metrics(expected: list[str], predicted: list[str]) -> dict[str, object]:
    labels = sorted(set(expected) | set(predicted))
    matrix = {label: {other: 0 for other in labels} for label in labels}
    for actual, guess in zip(expected, predicted, strict=True):
        matrix[actual][guess] += 1
    per_class = {}
    for label in labels:
        true_positive = matrix[label][label]
        false_positive = sum(matrix[other][label] for other in labels if other != label)
        false_negative = sum(matrix[label][other] for other in labels if other != label)
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0
        )
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "support": sum(matrix[label].values()),
        }
    return {
        "accuracy": sum(actual == guess for actual, guess in zip(expected, predicted, strict=True))
        / len(expected)
        if expected
        else None,
        "macro_precision": sum(item["precision"] for item in per_class.values()) / len(per_class)
        if per_class
        else None,
        "macro_recall": sum(item["recall"] for item in per_class.values()) / len(per_class)
        if per_class
        else None,
        "macro_f1": sum(item["f1"] for item in per_class.values()) / len(per_class)
        if per_class
        else None,
        "per_class": per_class,
        "confusion_matrix": matrix,
    }


def entity_metrics(expected: list[set[str]], predicted: list[set[str]]) -> dict[str, object]:
    if not expected:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "false_positives": 0,
            "false_negatives": 0,
        }
    true_positive = sum(
        len(actual & guess) for actual, guess in zip(expected, predicted, strict=True)
    )
    false_positive = sum(
        len(guess - actual) for actual, guess in zip(expected, predicted, strict=True)
    )
    false_negative = sum(
        len(actual - guess) for actual, guess in zip(expected, predicted, strict=True)
    )
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
        "exact_message_accuracy": sum(
            actual == guess for actual, guess in zip(expected, predicted, strict=True)
        )
        / len(expected)
        if expected
        else None,
        "false_positives": false_positive,
        "false_negatives": false_negative,
    }
