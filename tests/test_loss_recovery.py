import unittest

from stopwait.scenarios import run_required_evidence


class LossRecoveryTests(unittest.TestCase):
    def test_required_evidence_cases(self):
        # Run the five deterministic cases used in the recovery demonstration.
        rows = run_required_evidence(count=5)
        self.assertEqual(len(rows), 5)
        # The baseline, loss, lost-ACK, and corruption cases should recover.
        for row in rows[:4]:
            self.assertTrue(row.complete, row)
            self.assertEqual(row.unique_delivered, row.total_messages)
        # The unreachable receiver is the one case expected to fail boundedly.
        self.assertFalse(rows[4].complete)
        self.assertGreater(rows[1].retransmissions, 0)
        self.assertGreater(rows[2].retransmissions, 0)
        self.assertGreater(rows[3].invalid_packets, 0)


if __name__ == "__main__":
    unittest.main()
