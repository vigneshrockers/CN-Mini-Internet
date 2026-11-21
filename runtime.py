"""Independent host/router UDP processes and non-blocking link impairment."""
from __future__ import annotations
import heapq
import json
import logging
import queue
import random
import socket
import threading
import time
import uuid
from typing import Any
from .config import load_config
from .packet import Packet, PacketError, MAX_DATAGRAM


class ScheduledSender:

    def __init__(self, sock: socket.socket, device: str, logger: logging.Logger):
        self.sock, self.device, self.logger = (sock, device, logger)
        self.items: list[tuple[float, int, bytes, tuple[str, int], dict[str, Any]]] = []
        self.cv = threading.Condition()
        self.counter = 0
        self.closed = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, data: bytes, endpoint: tuple[str, int], delay: float, meta: dict[str, Any]):
        due = time.monotonic() + max(0.0, delay)
        with self.cv:
            self.counter += 1
            heapq.heappush(self.items, (due, self.counter, data, endpoint, meta))
            self.cv.notify()

    def _run(self):
        while True:
            with self.cv:
                while not self.items and (not self.closed):
                    self.cv.wait()
                if self.closed and (not self.items):
                    return
                due, _, data, endpoint, meta = self.items[0]
                wait = due - time.monotonic()
                if wait > 0:
                    self.cv.wait(wait)
                    continue
                heapq.heappop(self.items)
            try:
                self.sock.sendto(data, endpoint)
                self.logger.info('%s', json.dumps({'event': 'send', 'next_hop': meta['next_hop'], 'message_id': meta['message_id'], 'message_type': meta['message_type'], 'src': meta['src'], 'dst': meta['dst'], 'hop_limit': meta['hop_limit'], 'scheduled_delay_ms': meta['delay_ms']}, sort_keys=True))
            except OSError as exc:
                self.logger.error('%s', json.dumps({'event': 'send_error', 'next_hop': meta['next_hop'], 'error': str(exc)}))

    def close(self):
        with self.cv:
            self.closed = True
            self.items.clear()
            self.cv.notify_all()
        self.thread.join(timeout=1)

def _logger(name: str, run_id: str, quiet: bool=False) -> logging.Logger:
    log = logging.getLogger(f'miniinternet.{name}.{uuid.uuid4().hex}')
    log.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter(f'%(asctime)sZ run={run_id} device={name} %(message)s'))
    h.formatter.converter = time.gmtime
    log.addHandler(h)
    if quiet:
        log.setLevel(logging.WARNING)
    return log

class Device:

    def __init__(self, config_path: str, name: str):
        self.cfg = load_config(config_path)
        self.name = name
        self.device = self.cfg['devices'].get(name)
        if self.device is None:
            raise ValueError(f'device {name!r} is not in topology')
        self.run_id = str(self.cfg['run_id'])
        self.log = _logger(name, self.run_id, bool(self.cfg.get('quiet', False)))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.device['udp']['host'], self.device['udp']['port']))
        self.sock.settimeout(0.1)
        self.scheduler = ScheduledSender(self.sock, name, self.log)
        self.neighbors = self.device.get('neighbors', [])
        self.neighbor_eps = {n: (self.cfg['devices'][n]['udp']['host'], self.cfg['devices'][n]['udp']['port']) for n in self.neighbors}
        self.virtual_to_name = {d['virtual_address']: n for n, d in self.cfg['devices'].items()}
        self.rngs = {}
        self.forced_remaining = {}
        for n, options in self.device.get('links', {}).items():
            seed = int(options.get('seed', self.cfg.get('seed', 1)))
            self.rngs[n] = random.Random(seed)
            self.forced_remaining[n] = int(options.get('force_drop_first', 0))
            self.log.info('%s', json.dumps({'event': 'impairment_config', 'next_hop': n, 'loss_probability': options.get('loss_probability', 0), 'delay_ms': options.get('delay_ms', 0), 'seed': seed}))

    def send_packet(self, packet: Packet, next_hop: str):
        try:
            datagram = packet.encode()
        except PacketError as exc:
            self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'invalid_outbound_packet', 'detail': str(exc), 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
            return False
        if next_hop not in self.neighbor_eps:
            self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'invalid_next_hop', 'next_hop': next_hop, 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
            return False
        options = self.device.get('links', {}).get(next_hop, {})
        rng = self.rngs.get(next_hop)
        if self.forced_remaining.get(next_hop, 0) > 0:
            self.forced_remaining[next_hop] -= 1
            self.log.info('%s', json.dumps({'event': 'drop', 'reason': 'forced_drop', 'next_hop': next_hop, 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
            return False
        if rng and rng.random() < float(options.get('loss_probability', 0)):
            self.log.info('%s', json.dumps({'event': 'drop', 'reason': 'injected_loss', 'next_hop': next_hop, 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
            return False
        delay_ms = float(options.get('delay_ms', 0))
        self.scheduler.submit(datagram, self.neighbor_eps[next_hop], delay_ms / 1000, {'next_hop': next_hop, 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit, 'delay_ms': delay_ms})
        return True

    def receive(self):
        try:
            datagram, address = self.sock.recvfrom(65507)
        except socket.timeout:
            return None
        except ConnectionResetError:
            return None
        neighbor = next((n for n, ep in self.neighbor_eps.items() if ep == (address[0], address[1])), None)
        if neighbor is None:
            self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'unconfigured_sender', 'udp_peer': f'{address[0]}:{address[1]}'}))
            return None
        try:
            packet = Packet.decode(datagram)
        except PacketError as exc:
            self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'invalid_packet', 'detail': str(exc), 'next_hop': neighbor, 'bytes': len(datagram)}))
            return None
        self.log.info('%s', json.dumps({'event': 'receive', 'next_hop': neighbor, 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
        return packet

    def close(self):
        self.scheduler.close()
        self.sock.close()

class Router(Device):

    def run(self, stop: threading.Event):
        self.log.info('{"event":"ready","role":"router"}')
        try:
            while not stop.is_set():
                packet = self.receive()
                if packet is None:
                    continue
                dest_name = self.virtual_to_name.get(packet.destination)
                if dest_name is None:
                    self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'unknown_destination', 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
                    continue
                if packet.hop_limit <= 1:
                    self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'hop_limit_exhausted', 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
                    continue
                next_hop = self.device.get('forwarding', {}).get(packet.destination)
                if next_hop is None:
                    self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'unknown_route', 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': packet.hop_limit}))
                    continue
                forwarded = Packet(packet.source, packet.destination, packet.hop_limit - 1, packet.message_type, packet.message_id, packet.payload)
                self.log.info('%s', json.dumps({'event': 'forward', 'next_hop': next_hop, 'message_id': packet.message_id, 'message_type': packet.message_type, 'src': packet.source, 'dst': packet.destination, 'hop_limit': forwarded.hop_limit}))
                self.send_packet(forwarded, next_hop)
        finally:
            self.close()

class Host(Device):

    def __init__(self, config_path: str, name: str):
        super().__init__(config_path, name)
        self.pending: dict[str, tuple[float, str, bytes]] = {}
        self.received: dict[str, tuple[float, bytes]] = {}

    def send_probe(self, destination: str, payload: bytes, message_id: str | None=None):
        addr_to_name = self.virtual_to_name
        if destination not in addr_to_name:
            # Keep unknown virtual destinations available for the error-path demo.
            virtual = destination
        else:
            virtual = destination
        message_id = message_id or uuid.uuid4().hex
        packet = Packet(self.device['virtual_address'], virtual, int(self.cfg.get('hop_limit', 12)), 'PROBE', message_id, payload)
        self.pending[message_id] = (time.monotonic(), virtual, payload)
        self.send_packet(packet, self.device['gateway'])
        return message_id

    def serve(self, stop: threading.Event):
        self.log.info('{"event":"ready","role":"host"}')
        try:
            while not stop.is_set():
                packet = self.receive()
                if packet is None:
                    continue
                my_virtual = self.device['virtual_address']
                if packet.destination != my_virtual:
                    self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'host_wrong_destination', 'message_id': packet.message_id, 'dst': packet.destination}))
                    continue
                if packet.message_type == 'PROBE':
                    self.received[packet.message_id] = (time.monotonic(), packet.payload)
                    self.log.info('%s', json.dumps({'event': 'application_receive', 'message_id': packet.message_id, 'message_type': 'PROBE', 'payload': packet.payload.decode('utf-8', 'replace')}))
                    response = Packet(my_virtual, packet.source, int(self.cfg.get('hop_limit', 12)), 'ECHO', packet.message_id, packet.payload)
                    self.send_packet(response, self.device['gateway'])
                elif packet.message_type == 'ECHO':
                    sent = self.pending.get(packet.message_id)
                    if sent and packet.payload == sent[2]:
                        rtt_ms = (time.monotonic() - sent[0]) * 1000
                        self.pending.pop(packet.message_id, None)
                        self.log.info('%s', json.dumps({'event': 'probe_success', 'message_id': packet.message_id, 'rtt_ms': round(rtt_ms, 3), 'payload': packet.payload.decode('utf-8', 'replace')}))
                    else:
                        self.log.warning('%s', json.dumps({'event': 'drop', 'reason': 'unmatched_echo', 'message_id': packet.message_id}))
        finally:
            self.close()

    def probe(self, destination: str, count: int, interval: float, timeout: float, stop: threading.Event):
        if count < 1 or interval < 0 or timeout <= 0:
            raise ValueError('invalid probe count, interval, or timeout')
        self.log.info('{"event":"ready","role":"host"}')
        samples = []
        next_send = time.monotonic()
        for i in range(count):
            while not stop.is_set() and time.monotonic() < next_send:
                packet = self.receive()
                if packet is not None:
                    self._handle_probe_response(packet, samples)
            if stop.is_set():
                break
            self.send_probe(destination, f'probe-{i:04d}'.encode(), f'{self.run_id}-{i:04d}')
            next_send = max(next_send + interval, time.monotonic())
        deadline = time.monotonic() + timeout
        while self.pending and time.monotonic() < deadline and (not stop.is_set()):
            packet = self.receive()
            if packet is not None:
                self._handle_probe_response(packet, samples)
        missing = sorted(self.pending)
        for mid in missing:
            self.log.warning('%s', json.dumps({'event': 'timeout', 'message_id': mid, 'message_type': 'PROBE', 'src': self.device['virtual_address'], 'dst': destination}))
        self.pending.clear()
        summary = {'event': 'probe_summary', 'run_id': self.run_id, 'sent': count, 'received': len(samples), 'response_fraction': len(samples) / count, 'timeout_count': count - len(samples), 'rtt_ms': samples}
        self.log.info('%s', json.dumps(summary, sort_keys=True))
        return summary

    def _handle_probe_response(self, packet: Packet, samples: list[float]):
        my_virtual = self.device['virtual_address']
        if packet.destination != my_virtual:
            return
        sent = self.pending.get(packet.message_id)
        if packet.message_type == 'ECHO' and sent and (packet.payload == sent[2]):
            rtt = (time.monotonic() - sent[0]) * 1000
            samples.append(round(rtt, 3))
            self.pending.pop(packet.message_id, None)
            self.log.info('%s', json.dumps({'event': 'probe_success', 'message_id': packet.message_id, 'rtt_ms': round(rtt, 3), 'payload': packet.payload.decode('utf-8', 'replace')}))


def run_device(config_path: str, name: str, stop: threading.Event, probe: tuple[str, int, float, float] | None=None, ready_event=None):
    cfg = load_config(config_path)
    role = cfg['devices'].get(name, {}).get('role')
    if role == 'router':
        device = Router(config_path, name)
        if ready_event is not None:
            ready_event.set()
        device.run(stop)
    elif role == 'host':
        host = Host(config_path, name)
        if ready_event is not None:
            ready_event.set()
        if probe:
            host.probe(*probe, stop=stop)
        else:
            host.serve(stop)
    else:
        raise ValueError(f'unknown device {name}')
