"""Launch a six-process network and run reproducible probe demonstrations."""
from __future__ import annotations
import json
import multiprocessing as mp
import statistics
import tempfile
import time
from pathlib import Path
from .config import load_config
from .runtime import Host, run_device


def run_probe(config_path: str, source: str, destination: str, count: int=20, interval: float=0.02, timeout: float=2.0) -> dict:
    cfg = load_config(config_path)
    if source not in cfg['devices'] or cfg['devices'][source]['role'] != 'host':
        raise ValueError('probe source must be a configured host')
    if destination in cfg['devices']:
        destination = cfg['devices'][destination]['virtual_address']
    context = mp.get_context('spawn')
    stop = context.Event()
    workers = []
    readiness = []
    for name, dev in cfg['devices'].items():
        if name == source:
            continue
        ready = context.Event()
        proc = context.Process(target=run_device, args=(str(Path(config_path).resolve()), name, stop, None, ready), name=f'mini-{name}')
        proc.start()
        workers.append(proc)
        readiness.append((name, ready))
    try:
        # Wait until every peer has bound its configured UDP port before probing.
        startup_deadline = time.monotonic() + 20.0
        for name, ready in readiness:
            remaining = startup_deadline - time.monotonic()
            if remaining <= 0 or not ready.wait(remaining):
                raise RuntimeError(f'device {name} did not become ready within 20 seconds')
            if any((p.exitcode is not None for p in workers)):
                raise RuntimeError(f'a network device exited during startup (while waiting for {name})')
        host = Host(str(Path(config_path).resolve()), source)
        try:
            summary = host.probe(destination, count, interval, timeout, stop)
        finally:
            host.close()
        return summary
    finally:
        stop.set()
        for proc in workers:
            proc.join(timeout=1.5)
        for proc in workers:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)

def run_both_directions(config_path: str, count: int=20, interval: float=0.02, timeout: float=2.0):
    cfg = load_config(config_path)
    hosts = [n for n, d in cfg['devices'].items() if d['role'] == 'host']
    if len(hosts) < 2:
        raise ValueError('topology needs at least two hosts')
    return [run_probe(config_path, hosts[0], hosts[1], count, interval, timeout), run_probe(config_path, hosts[1], hosts[0], count, interval, timeout)]


def run_baseline(config_path: str, count: int=20, repetitions: int=3, delays_ms: tuple[float, float]=(0.0, 25.0), loss_rates: tuple[float, float]=(0.0, 0.05), interval: float=0.02, timeout: float=3.0) -> list[dict]:
    """Run the required 2x2 delay/loss matrix with repeated fixed workloads."""
    if count < 20 or repetitions < 3:
        raise ValueError('core baseline requires at least 20 probes and 3 repetitions')
    base = load_config(config_path)
    rows = []
    with tempfile.TemporaryDirectory(prefix='mininet-baseline-') as temp_dir:
        path = Path(temp_dir) / 'topology.json'
        for delay in delays_ms:
            for loss in loss_rates:
                trial_fractions = []
                trial_mean_rtts = []
                trial_timeouts = []
                for rep in range(1, repetitions + 1):
                    cfg = json.loads(json.dumps(base))
                    cfg['quiet'] = True
                    cfg['run_id'] = f'baseline-d{delay:g}-l{loss:g}-r{rep}'
                    cfg['seed'] = 7000 + int(delay * 10) + int(loss * 10000) + rep
                    # Apply impairment to the documented bidirectional upper-path link.
                    for source, neighbor in (('RA', 'RB'), ('RB', 'RA')):
                        cfg['devices'][source].setdefault('links', {})[neighbor] = {'loss_probability': loss, 'delay_ms': delay, 'seed': cfg['seed'] + (0 if source == 'RA' else 1)}
                    path.write_text(json.dumps(cfg), encoding='utf-8')
                    result = run_probe(str(path), 'H1', 'H2', count, interval, timeout)
                    fraction = result['received'] / result['sent']
                    mean_rtt = statistics.mean(result['rtt_ms']) if result['rtt_ms'] else None
                    trial_fractions.append(fraction)
                    if mean_rtt is not None:
                        trial_mean_rtts.append(mean_rtt)
                    trial_timeouts.append(result['timeout_count'])
                rows.append({'delay_ms': delay, 'loss_probability': loss, 'repetitions': repetitions, 'probes_per_run': count, 'seeds': [7000 + int(delay * 10) + int(loss * 10000) + r for r in range(1, repetitions + 1)], 'response_fraction_by_run': trial_fractions, 'response_fraction_mean': statistics.mean(trial_fractions), 'response_fraction_stdev': statistics.pstdev(trial_fractions), 'successful_probe_mean_rtt_ms_by_run': trial_mean_rtts, 'successful_probe_mean_rtt_ms_mean': statistics.mean(trial_mean_rtts) if trial_mean_rtts else None, 'successful_probe_mean_rtt_ms_stdev': statistics.pstdev(trial_mean_rtts) if len(trial_mean_rtts) > 1 else 0.0 if trial_mean_rtts else None, 'timeout_count_by_run': trial_timeouts})
    return rows
