import unittest
from miniinternet.packet import Packet, PacketError, MAX_DATAGRAM

class MiniPacketTests(unittest.TestCase):

    def test_encode_decode_and_crc(self):
        original = Packet('10.0.0.1', '10.0.0.2', 12, 'PROBE', 'abc', b'hello\x00world')
        raw = original.encode()
        self.assertLessEqual(len(raw), MAX_DATAGRAM)
        self.assertEqual(Packet.decode(raw), original)
        changed = raw.replace(b'aGVs', b'aGFs')
        with self.assertRaises(PacketError):
            Packet.decode(changed)

    def test_rejects_malformed_and_oversized(self):
        for raw in (b'{oops', b'x' * 1201):
            with self.subTest(raw=raw[:10]), self.assertRaises(PacketError):
                Packet.decode(raw)
        with self.assertRaises(PacketError):
            Packet('a', 'b', 1, 'BOGUS', 'm').encode()
        with self.assertRaises(PacketError):
            Packet('a', 'b', 1, 'PROBE', 'm', b'x' * 1200).encode()
