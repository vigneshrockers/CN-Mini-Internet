import unittest
from unittest.mock import Mock

from stopwait.udp_link import UdpLink


class UdpLinkTests(unittest.TestCase):
    def test_local_datagram_round_trip(self):
        receiver = UdpLink(("127.0.0.1", 0))
        sender = UdpLink(("127.0.0.1", 0), receiver.local_address)
        try:
            sender.send(b"packet")
            self.assertEqual(receiver.recv(0.5), b"packet")
        finally:
            sender.close()
            receiver.close()

    def test_connection_reset_is_treated_as_lost_datagram(self):
        receiver = UdpLink(("127.0.0.1", 0))
        original_socket = receiver.socket
        mock_socket = Mock()
        mock_socket.recvfrom.side_effect = [
            ConnectionResetError(10054, "connection reset"),
            (b"next packet", ("127.0.0.1", 12345)),
        ]
        receiver.socket = mock_socket
        try:
            self.assertEqual(receiver.recv(0.5), b"next packet")
            self.assertEqual(mock_socket.recvfrom.call_count, 2)
        finally:
            original_socket.close()


if __name__ == "__main__":
    unittest.main()
