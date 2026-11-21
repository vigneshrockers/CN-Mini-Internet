import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from miniinternet.config import load_config, ConfigError
from miniinternet.runner import run_probe
from miniinternet.packet import Packet
from miniinternet.runtime import Host, Router
ROOT = Path(__file__).resolve().parents[1]

class MiniNetworkTests(unittest.TestCase):

    def _quiet_config(self, source='topology-upper.json', mutate=None):
        data = json.loads((ROOT / 'config' / source).read_text())
        data['quiet'] = True
        if mutate:
            mutate(data)
        temp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(data, temp)
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return temp.name

    def test_upper_and_lower_routes(self):
        for config in ('topology-upper.json', 'topology-lower.json'):
            with self.subTest(path=config):
                path = self._quiet_config(config)
                for source, destination in (('H1', 'H2'), ('H2', 'H1')):
                    result = run_probe(path, source, destination, 20, 0.005, 2.0)
                    self.assertEqual(result['received'], 20)
                    self.assertEqual(result['timeout_count'], 0)

    def test_unknown_destination_times_out_boundedly(self):
        result = run_probe(self._quiet_config(), 'H1', '192.0.2.99', 1, 0, 0.35)
        self.assertEqual(result['received'], 0)
        self.assertEqual(result['timeout_count'], 1)

    def test_hop_limit_loop_expires(self):

        def make_loop(cfg):
            cfg['hop_limit'] = 5
            cfg['devices']['RB']['forwarding']['10.0.0.2'] = 'RA'
        result = run_probe(self._quiet_config(mutate=make_loop), 'H1', 'H2', 1, 0, 0.35)
        self.assertEqual(result['received'], 0)
        self.assertEqual(result['timeout_count'], 1)

    def test_forced_loss_is_not_retransmitted_by_core(self):

        def force_drop(cfg):
            cfg['devices']['RA']['links'] = {'RB': {'force_drop_first': 1, 'seed': 77}}
        result = run_probe(self._quiet_config(mutate=force_drop), 'H1', 'H2', 1, 0, 0.35)
        self.assertEqual(result['received'], 0)
        self.assertEqual(result['timeout_count'], 1)

    def test_forced_drop_logs_reason_and_host_times_out(self):

        def force_drop(cfg):
            cfg['quiet'] = False
            cfg['run_id'] = 'forced-drop-test'
            cfg['devices']['RA']['links'] = {'RB': {'force_drop_first': 1, 'seed': 77}}
        path = self._quiet_config(mutate=force_drop)
        router = Router(path, 'RA')
        stop = threading.Event()
        router_thread = threading.Thread(target=router.run, args=(stop,), daemon=True)
        host = None
        router_thread.start()
        try:
            host = Host(path, 'H1')
            with self.assertLogs('miniinternet', level='INFO') as captured:
                result = host.probe('10.0.0.2', 1, 0, 0.25, stop)
            self.assertEqual(result['sent'], 1)
            self.assertEqual(result['received'], 0)
            self.assertEqual(result['timeout_count'], 1)
            self.assertTrue(any(('"reason": "forced_drop"' in line for line in captured.output)))
        finally:
            stop.set()
            if host is not None:
                host.close()
            router_thread.join(timeout=1)
        self.assertFalse(router_thread.is_alive())

    def test_invalid_packet_is_logged_and_router_receives_next_packet(self):

        def enable_logs(cfg):
            cfg['quiet'] = False
        path = self._quiet_config(mutate=enable_logs)
        cfg = load_config(path)
        router = Router(path, 'RA')
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        source = cfg['devices']['H1']['udp']
        destination = cfg['devices']['RA']['udp']
        sender.bind((source['host'], source['port']))
        try:
            valid = Packet('10.0.0.1', '10.0.0.2', 12, 'PROBE', 'after-invalid', b'valid packet').encode()
            with self.assertLogs('miniinternet', level='INFO') as captured:
                sender.sendto(b'not-a-valid-packet', (destination['host'], destination['port']))
                self.assertIsNone(router.receive())
                sender.sendto(valid, (destination['host'], destination['port']))
                received = router.receive()
            self.assertEqual(received.message_id, 'after-invalid')
            self.assertTrue(any(('"reason": "invalid_packet"' in line for line in captured.output)))
        finally:
            sender.close()
            router.close()

    def test_config_rejects_non_neighbor_next_hop(self):
        data = json.loads((ROOT / 'config/topology-upper.json').read_text())
        data['devices']['RA']['forwarding']['10.0.0.2'] = 'H2'
        temp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
        json.dump(data, temp)
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        with self.assertRaises(ConfigError):
            load_config(temp.name)
