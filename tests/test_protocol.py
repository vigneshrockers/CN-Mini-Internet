import unittest

from stopwait.protocol import PacketError, decode_packet, encode_packet


class ProtocolTests(unittest.TestCase):
    def test_round_trip_data_and_ack(self):
        for kind in ("data", "ack"):
            packet = decode_packet(encode_packet(kind, "run-1", 2, 5, "hello" if kind == "data" else ""))
            self.assertEqual(packet["type"], kind)
            self.assertEqual(packet["seq"], 2)

    def test_crc_detects_modified_datagram(self):
        raw = bytearray(encode_packet("data", "run-1", 0, 1, "hello"))
        raw[raw.index(b"hello")] ^= 1
        with self.assertRaises(PacketError):
            decode_packet(bytes(raw))

    def test_invalid_sequence_rejected(self):
        with self.assertRaises(PacketError):
            encode_packet("data", "run-1", 4, 4, "x")


if __name__ == "__main__":
    unittest.main()
