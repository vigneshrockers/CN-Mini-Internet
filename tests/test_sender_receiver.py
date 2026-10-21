import threading
import unittest
import uuid

from stopwait.receiver import Receiver
from stopwait.sender import send_messages
from stopwait.simulated_link import ImpairedUdpLink, ImpairmentPolicy
from stopwait.udp_link import UdpLink


class TransferTests(unittest.TestCase):
    def make_pair(self, policy=None):
        policy = policy or ImpairmentPolicy()
        rx_raw = UdpLink(("127.0.0.1", 0))
        tx_raw = UdpLink(("127.0.0.1", 0), rx_raw.local_address)
        rx_raw.set_peer(tx_raw.local_address)
        return (ImpairedUdpLink(tx_raw, policy, "sender_to_receiver"),
                ImpairedUdpLink(rx_raw, policy, "receiver_to_sender"))

    def test_stop_and_wait_delivers_once_in_order(self):
        tx, rx = self.make_pair()
        run_id = str(uuid.uuid4())
        receiver = Receiver(rx, run_id, 4, linger=0.1)
        thread = threading.Thread(target=receiver.run, daemon=True)
        thread.start()
        try:
            result = send_messages(tx, run_id, ["a", "b", "c", "d"], timeout=0.1, rate=1000)
            thread.join(1)
            self.assertTrue(result.completed)
            self.assertEqual(receiver.delivered, ["a", "b", "c", "d"])
        finally:
            receiver.stop()
            tx.close()
            rx.close()


if __name__ == "__main__":
    unittest.main()
