import unittest

from stopwait.scenarios import run_comparison, run_reorder_demo


class ComparisonTests(unittest.TestCase):
    def test_three_trials_per_comparison_condition(self):
        rows = run_comparison(repetitions=3, count=4, loss_levels=(0.0,), base_delay=0.0)
        self.assertEqual(len(rows), 6)
        self.assertEqual({row.mode for row in rows}, {"best-effort", "stop-and-wait"})

    def test_sliding_window_reorders_and_delivers_in_order(self):
        row = run_reorder_demo(count=5)
        self.assertTrue(row.complete, row)
        self.assertEqual(row.unique_delivered, 5)


if __name__ == "__main__":
    unittest.main()
