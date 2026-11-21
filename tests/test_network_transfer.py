import unittest

from stopwait.network_scenarios import (
    run_network_comparison,
    run_network_reorder_demo,
    run_network_required_evidence,
)


class MiniInternetTransferTests(unittest.TestCase):
    def test_track_b_recovery_cases_cross_the_router_path(self):
        rows = run_network_required_evidence(count=5)
        self.assertEqual(len(rows), 5)
        for row in rows[:4]:
            self.assertTrue(row.complete, row)
            self.assertEqual(row.unique_delivered, row.total_messages)
        self.assertFalse(rows[4].complete)
        self.assertGreater(rows[1].retransmissions, 0)
        self.assertGreater(rows[2].retransmissions, 0)
        self.assertGreater(rows[3].invalid_packets, 0)

    def test_network_comparison_repeats_all_required_loss_conditions(self):
        rows = run_network_comparison(
            repetitions=3,
            count=5,
            loss_levels=(0.0, 0.05),
            rate=100.0,
            delay_ms=0.0,
        )
        self.assertEqual(len(rows), 12)
        self.assertEqual({row.loss_rate for row in rows}, {0.0, 0.05})
        self.assertEqual({row.mode for row in rows}, {"best-effort", "stop-and-wait"})
        for loss_rate in (0.0, 0.05):
            for mode in ("best-effort", "stop-and-wait"):
                matching = [row for row in rows if row.loss_rate == loss_rate and row.mode == mode]
                self.assertEqual(len(matching), 3)
                self.assertTrue(all(row.total_messages == 5 for row in matching))

    def test_sliding_window_reorders_on_the_routed_path(self):
        row = run_network_reorder_demo(count=5)
        self.assertTrue(row.complete, row)
        self.assertEqual(row.unique_delivered, 5)


if __name__ == "__main__":
    unittest.main()
