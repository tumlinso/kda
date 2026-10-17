"""Pure candidate ranking and paired confirmation statistics.

Input measurements are positive finite raw samples, grouped first by round and
then by workload case.  The functions in this module do not execute commands,
read project state, or make assumptions about what a metric means beyond its
declared direction.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any


_DIRECTIONS = {"minimize", "maximize"}


def _finite_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = "positive and finite" if positive else "finite"
        raise ValueError(f"{name} must be {qualifier}")
    return result


def _normalize_cases(cases: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[float]]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence) or not cases:
        raise ValueError("cases must be a non-empty sequence")

    case_ids: list[str] = []
    weights: list[float] = []
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"case {index} must be a mapping")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"case {index} must have a non-empty string id")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        weight = _finite_number(case.get("weight", 1.0), f"weight for case {case_id}", positive=True)
        case_ids.append(case_id)
        weights.append(weight)

    # Scale before summing to avoid overflow when individually valid weights
    # are large. Omitted weights are all one, so they receive equal influence.
    largest = max(weights)
    scaled = [weight / largest for weight in weights]
    denominator = math.fsum(scaled)
    return case_ids, [weight / denominator for weight in scaled]


def _validate_direction(direction: str) -> None:
    if not isinstance(direction, str) or direction not in _DIRECTIONS:
        raise ValueError("direction must be 'minimize' or 'maximize'")


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    # This form avoids overflowing when two large finite values are averaged.
    return float(ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2.0)


def _normalize_rounds(
    rounds: Sequence[Mapping[str, Sequence[float]]],
    case_ids: Sequence[str],
    name: str,
    *,
    minimum_rounds: int = 1,
) -> list[dict[str, float]]:
    if isinstance(rounds, (str, bytes)) or not isinstance(rounds, Sequence):
        raise ValueError(f"{name} must be a sequence of rounds")
    if len(rounds) < minimum_rounds:
        raise ValueError(f"{name} must contain at least {minimum_rounds} rounds")

    expected = set(case_ids)
    normalized: list[dict[str, float]] = []
    for round_index, round_result in enumerate(rounds):
        if not isinstance(round_result, Mapping):
            raise ValueError(f"{name} round {round_index} must be a mapping")
        actual = set(round_result)
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            detail = []
            if missing:
                detail.append(f"missing cases {sorted(missing)}")
            if extra:
                detail.append(f"unexpected cases {sorted(extra)}")
            raise ValueError(f"{name} round {round_index}: " + "; ".join(detail))

        round_values: dict[str, float] = {}
        for case_id in case_ids:
            samples = round_result[case_id]
            if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence) or not samples:
                raise ValueError(f"{name} round {round_index} case {case_id} needs raw samples")
            values = [
                _finite_number(sample, f"{name} round {round_index} case {case_id} sample", positive=True)
                for sample in samples
            ]
            round_values[case_id] = _median(values)
        normalized.append(round_values)
    return normalized


def _exp_finite(value: float, name: str) -> float:
    try:
        result = math.exp(value)
    except OverflowError as exc:
        raise ValueError(f"{name} is outside the finite numeric range") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} is outside the finite numeric range")
    return result


def _case_log_benefit(incumbent: float, candidate: float, direction: str) -> float:
    if direction == "minimize":
        return math.log(incumbent) - math.log(candidate)
    return math.log(candidate) - math.log(incumbent)


def _score_from_case_logs(case_logs: Sequence[float], normalized_weights: Sequence[float]) -> float:
    return _exp_finite(
        math.fsum(weight * log_value for weight, log_value in zip(normalized_weights, case_logs)),
        "weighted geometric score",
    )


def _aggregate_rounds(
    rounds: Sequence[Mapping[str, float]], case_ids: Sequence[str], indices: Sequence[int] | None = None
) -> dict[str, float]:
    selected = rounds if indices is None else [rounds[index] for index in indices]
    return {case_id: _median([result[case_id] for result in selected]) for case_id in case_ids}


def rank(
    cases: Sequence[Mapping[str, Any]],
    results: Mapping[str, Sequence[Mapping[str, Sequence[float]]]],
    incumbent: str,
    direction: str,
) -> list[dict[str, Any]]:
    """Rank candidate results by weighted geometric benefit over an incumbent.

    Each raw sample list is reduced to a median for its round and workload
    case. The median across rounds then supplies that case's comparison value.
    A score above 1 favors the candidate, 1 is a tie, and below 1 favors the
    incumbent. All candidates must have the same number of rounds and case
    identities so a ranking never compares different evaluation coverage.
    """
    case_ids, weights = _normalize_cases(cases)
    _validate_direction(direction)
    if not isinstance(results, Mapping) or not results:
        raise ValueError("results must map at least one candidate id to rounds")
    if not isinstance(incumbent, str) or incumbent not in results:
        raise ValueError("incumbent must identify a candidate in results")

    normalized: dict[str, list[dict[str, float]]] = {}
    round_count: int | None = None
    for candidate_id, candidate_rounds in results.items():
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("candidate ids must be non-empty strings")
        values = _normalize_rounds(candidate_rounds, case_ids, f"candidate {candidate_id}")
        if round_count is None:
            round_count = len(values)
        elif len(values) != round_count:
            raise ValueError("all candidates must have the same number of rounds")
        normalized[candidate_id] = values

    baseline = _aggregate_rounds(normalized[incumbent], case_ids)
    ranked: list[dict[str, Any]] = []
    for candidate_id, candidate_rounds in normalized.items():
        candidate = _aggregate_rounds(candidate_rounds, case_ids)
        case_logs = [
            _case_log_benefit(baseline[case_id], candidate[case_id], direction)
            for case_id in case_ids
        ]
        ranked.append({"candidate_id": candidate_id, "score": _score_from_case_logs(case_logs, weights)})

    ranked.sort(key=lambda entry: (-entry["score"], entry["candidate_id"]))
    return ranked


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    """Linearly interpolated percentile over an already sorted sample."""
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return float(sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction)


def confirm(
    cases: Sequence[Mapping[str, Any]],
    incumbent_rounds: Sequence[Mapping[str, Sequence[float]]],
    challenger_rounds: Sequence[Mapping[str, Sequence[float]]],
    direction: str,
    min_improvement: float = 0.0,
    max_regression: float = 0.0,
    bootstrap_samples: int = 2000,
    seed: int = 17,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Confirm a challenger with paired, round-level bootstrap intervals.

    The two sequences must contain fresh, paired measurements with identical
    case coverage. Bootstrap resampling uses one shared round-index sample for
    every case, preserving correlations between workloads. Promotion requires
    the overall lower confidence bound to exceed ``1 + min_improvement`` and
    every per-case lower bound to meet ``1 - max_regression``.
    """
    case_ids, weights = _normalize_cases(cases)
    _validate_direction(direction)
    min_improvement = _finite_number(min_improvement, "min_improvement")
    max_regression = _finite_number(max_regression, "max_regression")
    confidence = _finite_number(confidence, "confidence")
    if min_improvement < 0.0:
        raise ValueError("min_improvement must be non-negative")
    if max_regression < 0.0 or max_regression >= 1.0:
        raise ValueError("max_regression must be in [0, 1)")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int) or bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    incumbent = _normalize_rounds(incumbent_rounds, case_ids, "incumbent", minimum_rounds=2)
    challenger = _normalize_rounds(challenger_rounds, case_ids, "challenger", minimum_rounds=2)
    if len(incumbent) != len(challenger):
        raise ValueError("incumbent and challenger need the same number of paired rounds")

    def benefits(indices: Sequence[int] | None = None) -> dict[str, float]:
        incumbent_values = _aggregate_rounds(incumbent, case_ids, indices)
        challenger_values = _aggregate_rounds(challenger, case_ids, indices)
        return {
            case_id: _exp_finite(
                _case_log_benefit(incumbent_values[case_id], challenger_values[case_id], direction),
                f"benefit ratio for case {case_id}",
            )
            for case_id in case_ids
        }

    point_per_case = benefits()
    point_score = _score_from_case_logs(
        [math.log(point_per_case[case_id]) for case_id in case_ids], weights
    )

    rng = random.Random(seed)
    round_count = len(incumbent)
    score_samples: list[float] = []
    case_samples: dict[str, list[float]] = {case_id: [] for case_id in case_ids}
    for _ in range(bootstrap_samples):
        indices = [rng.randrange(round_count) for _ in range(round_count)]
        sample_benefits = benefits(indices)
        for case_id in case_ids:
            case_samples[case_id].append(sample_benefits[case_id])
        score_samples.append(
            _score_from_case_logs(
                [math.log(sample_benefits[case_id]) for case_id in case_ids], weights
            )
        )

    alpha = (1.0 - confidence) / 2.0
    score_samples.sort()
    ci_low = _percentile(score_samples, alpha)
    ci_high = _percentile(score_samples, 1.0 - alpha)
    per_case: dict[str, dict[str, Any]] = {}
    case_threshold = 1.0 - max_regression
    case_gate = True
    for case_id in case_ids:
        samples = sorted(case_samples[case_id])
        low = _percentile(samples, alpha)
        high = _percentile(samples, 1.0 - alpha)
        eligible = low >= case_threshold
        case_gate = case_gate and eligible
        per_case[case_id] = {
            "score": point_per_case[case_id],
            "ci_low": low,
            "ci_high": high,
            "eligible": eligible,
        }

    improvement_threshold = 1.0 + min_improvement
    improvement_gate = ci_low > improvement_threshold
    eligible = improvement_gate and case_gate
    if eligible:
        reason = "confirmed"
    elif not improvement_gate:
        reason = "minimum_improvement_not_supported"
    else:
        reason = "per_case_regression_limit_exceeded"

    return {
        "eligible": eligible,
        "reason": reason,
        "score": point_score,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "per_case": per_case,
    }
