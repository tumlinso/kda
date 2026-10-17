import math
import unittest

from kda_experiments.selection import confirm, rank


def rounds(*case_values):
    """Build rounds from one or more round vectors keyed by case id."""
    return [
        {case_id: [value] for case_id, value in vector.items()}
        for vector in case_values
    ]


class RankTests(unittest.TestCase):
    def test_equal_default_weights_use_weighted_geometric_benefit(self):
        cases = [{"id": "fast"}, {"id": "slow"}]
        values = {
            "base": rounds({"fast": 10.0, "slow": 10.0}),
            "balanced": rounds({"fast": 5.0, "slow": 40.0}),
        }
        ranked = rank(cases, values, "base", "minimize")
        self.assertEqual([entry["candidate_id"] for entry in ranked], ["base", "balanced"])
        self.assertAlmostEqual(ranked[1]["score"], math.sqrt(2.0 * 0.25))
        self.assertEqual(ranked[0]["score"], 1.0)

    def test_explicit_weights_change_case_contribution(self):
        cases = [{"id": "important", "weight": 9}, {"id": "minor", "weight": 1}]
        values = {
            "base": rounds({"important": 10.0, "minor": 10.0}),
            "candidate": rounds({"important": 5.0, "minor": 20.0}),
        }
        result = rank(cases, values, "base", "minimize")
        self.assertAlmostEqual(result[0]["score"], 2.0 ** 0.9 * 0.5 ** 0.1)

    def test_maximize_direction_rewards_larger_measurements(self):
        result = rank(
            [{"id": "case"}],
            {
                "base": rounds({"case": 20.0}),
                "candidate": rounds({"case": 40.0}),
            },
            "base",
            "maximize",
        )
        self.assertEqual(result[0], {"candidate_id": "candidate", "score": 2.0})

    def test_raw_samples_are_reduced_within_round_then_across_rounds(self):
        result = rank(
            [{"id": "case"}],
            {
                "base": [{"case": [1.0, 100.0, 100.0]}, {"case": [10.0, 10.0, 20.0]}],
                "candidate": [{"case": [2.0, 2.0, 100.0]}, {"case": [5.0, 15.0, 15.0]}],
            },
            "base",
            "minimize",
        )
        # Round medians are (100, 10) for base and (2, 15) for candidate;
        # their across-round medians are 55 and 8.5 respectively.
        self.assertAlmostEqual(result[0]["score"], 55.0 / 8.5)

    def test_rejects_case_and_round_mismatches(self):
        with self.assertRaisesRegex(ValueError, "duplicate case id"):
            rank([{"id": "x"}, {"id": "x"}], {"base": rounds({"x": 1})}, "base", "minimize")
        with self.assertRaisesRegex(ValueError, "missing cases"):
            rank([{"id": "x"}, {"id": "y"}], {"base": rounds({"x": 1})}, "base", "minimize")
        with self.assertRaisesRegex(ValueError, "same number of rounds"):
            rank(
                [{"id": "x"}],
                {"base": rounds({"x": 1}), "candidate": rounds({"x": 2}, {"x": 2})},
                "base",
                "minimize",
            )

    def test_rejects_bad_measurements_weights_and_direction(self):
        for invalid in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                rank([{"id": "x"}], {"base": rounds({"x": invalid})}, "base", "minimize")
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            rank([{"id": "x", "weight": 0}], {"base": rounds({"x": 1})}, "base", "minimize")
        with self.assertRaisesRegex(ValueError, "direction"):
            rank([{"id": "x"}], {"base": rounds({"x": 1})}, "base", "min")
        with self.assertRaisesRegex(ValueError, "direction"):
            rank([{"id": "x"}], {"base": rounds({"x": 1})}, "base", [])

    def test_large_finite_samples_keep_a_finite_median(self):
        result = rank(
            [{"id": "x"}],
            {"base": [{"x": [1.5e308, 1.5e308]}]},
            "base",
            "minimize",
        )
        self.assertEqual(result[0]["score"], 1.0)


class ConfirmTests(unittest.TestCase):
    def test_stable_improvement_passes(self):
        result = confirm(
            [{"id": "x"}],
            rounds({"x": 10}, {"x": 10}, {"x": 10}, {"x": 10}),
            rounds({"x": 8}, {"x": 8}, {"x": 8}, {"x": 8}),
            "minimize",
            min_improvement=0.1,
            bootstrap_samples=300,
        )
        self.assertTrue(result["eligible"])
        self.assertEqual(result["reason"], "confirmed")
        self.assertAlmostEqual(result["score"], 1.25)
        self.assertGreater(result["ci_low"], 1.1)

    def test_slowdown_is_not_promoted(self):
        result = confirm(
            [{"id": "x"}],
            rounds({"x": 10}, {"x": 10}, {"x": 10}),
            rounds({"x": 12}, {"x": 12}, {"x": 12}),
            "minimize",
            bootstrap_samples=200,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "minimum_improvement_not_supported")
        self.assertLess(result["score"], 1.0)

    def test_maximize_direction_confirms_throughput_gain(self):
        result = confirm(
            [{"id": "items_per_second"}],
            rounds({"items_per_second": 100}, {"items_per_second": 100}),
            rounds({"items_per_second": 125}, {"items_per_second": 125}),
            "maximize",
            bootstrap_samples=100,
        )
        self.assertTrue(result["eligible"])
        self.assertAlmostEqual(result["score"], 1.25)

    def test_noisy_paired_rounds_are_inconclusive(self):
        result = confirm(
            [{"id": "x"}],
            rounds({"x": 1}, {"x": 100}),
            rounds({"x": 0.5}, {"x": 200}),
            "minimize",
            bootstrap_samples=2000,
            seed=5,
        )
        self.assertFalse(result["eligible"])
        self.assertLessEqual(result["ci_low"], 1.0)
        self.assertGreater(result["ci_high"], 1.0)

    def test_per_case_regression_gate_can_reject_an_overall_winner(self):
        result = confirm(
            [{"id": "main", "weight": 9}, {"id": "secondary", "weight": 1}],
            rounds(
                {"main": 10, "secondary": 10},
                {"main": 10, "secondary": 10},
                {"main": 10, "secondary": 10},
            ),
            rounds(
                {"main": 5, "secondary": 15},
                {"main": 5, "secondary": 15},
                {"main": 5, "secondary": 15},
            ),
            "minimize",
            max_regression=0.1,
            bootstrap_samples=200,
        )
        self.assertGreater(result["score"], 1.0)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "per_case_regression_limit_exceeded")
        self.assertFalse(result["per_case"]["secondary"]["eligible"])

    def test_identical_candidate_is_not_a_confirmed_improvement(self):
        result = confirm(
            [{"id": "x"}],
            rounds({"x": 1}, {"x": 2}, {"x": 3}),
            rounds({"x": 1}, {"x": 2}, {"x": 3}),
            "minimize",
            bootstrap_samples=200,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["reason"], "minimum_improvement_not_supported")

    def test_bootstrap_is_reproducible_for_the_same_seed(self):
        args = (
            [{"id": "x"}],
            rounds({"x": 10}, {"x": 12}, {"x": 8}, {"x": 11}),
            rounds({"x": 8}, {"x": 11}, {"x": 7}, {"x": 7}),
            "minimize",
        )
        first = confirm(*args, bootstrap_samples=500, seed=23)
        second = confirm(*args, bootstrap_samples=500, seed=23)
        self.assertEqual(first, second)

    def test_rejects_bad_round_counts_and_thresholds(self):
        incumbent = rounds({"x": 1}, {"x": 1})
        with self.assertRaisesRegex(ValueError, "at least 2 rounds"):
            confirm([{"id": "x"}], rounds({"x": 1}), rounds({"x": 1}), "minimize")
        with self.assertRaisesRegex(ValueError, "same number of paired rounds"):
            confirm([{"id": "x"}], incumbent, rounds({"x": 1}, {"x": 1}, {"x": 1}), "minimize")
        with self.assertRaisesRegex(ValueError, "max_regression"):
            confirm([{"id": "x"}], incumbent, incumbent, "minimize", max_regression=1.0)

    def test_rejects_duplicate_or_nonfinite_samples(self):
        with self.assertRaisesRegex(ValueError, "duplicate case id"):
            confirm([{"id": "x"}, {"id": "x"}], [], [], "minimize")
        bad = [{"x": [1.0, float("nan")]}, {"x": [1.0]}]
        with self.assertRaisesRegex(ValueError, "finite"):
            confirm([{"id": "x"}], bad, bad, "minimize")


if __name__ == "__main__":
    unittest.main()
