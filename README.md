# Mini Internet and reliable-transfer demonstrations

This repository contains two layers:

1. `miniinternet` is the common virtual network: six independent Python processes exchange CRC-protected packets over configured UDP neighbor links. Routers forward by virtual destination using static tables.
2. `stopwait` is the existing best-effort, stop-and-wait, and optional sliding-window transfer prototype. It currently uses direct UDP endpoints; it has not yet been integrated as an application over the mini-internet.

The network layer is the checkpoint to build and demonstrate first. It uses only the Python standard library and keeps each serialized virtual packet at or below 1,200 bytes.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux
- No third-party runtime dependencies

## Install on Windows

Open PowerShell in this directory (the folder containing `pyproject.toml`) and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .
```

If PowerShell blocks environment activation, either use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that PowerShell window, or invoke the environment's Python directly as `.\.venv\Scripts\python.exe -m miniinternet.cli ...`.

On macOS/Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, and `python -m pip install -e .`.

## Core mini-internet demonstration

Run both 20-probe directions across the upper route:

```text
mini-internet demo --path upper --direction both --count 20
```

Then change only the selected static forwarding tables and run the lower route:

```text
mini-internet demo --path lower --direction both --count 20
```

Each command starts five device subprocesses and runs the sixth device as the probe host. The printed device logs include run ID, UTC timestamp, device, message ID/type, virtual source/destination, next hop, hop limit, and send/receive/forward/drop/timeout events. Both endpoints bind to localhost UDP ports configured in `config/topology-*.json`. The virtual packet is an application payload inside UDP, not a replacement for UDP/IP.

A single direction can be run with `mini-internet probe --config config/topology-upper.json --source H1 --destination H2 --count 20`. Run an individual long-lived process with `mini-internet device --config config/topology-upper.json --name RA`.

### Packet and routing rules

`miniinternet.packet.Packet` serializes virtual source/destination, hop limit, message type, message ID, payload, and IEEE CRC-32 as canonical JSON. Routers validate CRC and fields before forwarding, decrement hop limit by one, and recompute CRC. A router drops a packet received with hop limit at most one. A host sends only to its configured gateway. A router sends only to a next hop in its configured neighbor list. In this topology, `topology-upper.json` routes H1-to-H2 through RA-RB-RD; `topology-lower.json` routes it through RA-RC-RD. The response uses explicit reverse routes.

Each source device can configure per-neighbor `loss_probability`, `delay_ms`, `seed`, and `force_drop_first` in its `links` object. Delay is scheduled on a background queue, so it does not block packet reception. The seed and impairment location are logged at startup. The included configurations default to no loss and no added delay.

### Core error demonstrations

- Hop-limit loop: copy a topology file, lower `hop_limit` to `5`, and set `devices.RB.forwarding["10.0.0.2"]` to `RA`; run one probe. RA logs `hop_limit_exhausted` and the source logs a finite timeout.
- Unknown destination: run a probe with `--destination 192.0.2.99`; the first router logs `unknown_destination` and the host times out.
- Invalid packet: start the four routers and H2 (for example with separate `mini-internet device` commands in PowerShell windows), then run `mini-internet inject-invalid --config config/topology-upper.json`. RA logs `invalid_packet`. Stop the device processes with Ctrl+C.
- Forced loss: add `"links": {"RB": {"force_drop_first": 1}}` under device `RA`, then run probes. RA logs the deterministic injected drop; the baseline has no retransmission, so a reply may be missing.
- Random loss and added delay: configure `loss_probability` (for example `0.05`) and `delay_ms` (for example `25`) on a directed link. To impair both directions of a link pair, set the same values on each endpoint's `links` mapping.

## Core baseline experiment

Run the required 2-by-2 matrix (two delays, 0%/5% loss) with 20 probes and three repetitions per condition:

```text
mini-internet measure --config config/topology-upper.json --count 20 --repetitions 3 --delay-ms 0 25 --loss 0 0.05 --output results/core_baseline.jsonl
```

The measurement impairs both directions of the RA-RB link, keeps the upper path and message workload fixed, records deterministic per-run seeds, uses monotonic source-side RTT timing, and prints per-condition response fractions, timeout counts, mean RTT, and standard deviation across repetitions. The command writes the four aggregate JSON records to `results/core_baseline.jsonl`; keep that file with the experiment evidence. Choose an RTT timeout larger than the round-trip delay you configure by setting `--timeout`.

## Tests

```text
python -m unittest discover -s tests -v
```

The network tests check packet size/CRC validation, both static paths in both directions, finite unknown-destination/hop-loop behavior, and invalid next-hop configuration. The existing tests exercise the transfer prototype's best-effort, stop-and-wait, and sliding-window behavior.

## Existing Track B transfer prototype

The previous direct-UDP demonstrations remain available:

```text
reliable-transfer evidence
reliable-transfer compare --count 20 --repetitions 3 --rate 100 --delay 0.01
reliable-transfer reorder-demo
```

The Track B code includes CRC-32 for its own transfer datagrams and an optional sliding-window bonus, but those transfer datagrams still travel directly between host UDP endpoints. Before claiming the Track B extension is integrated, add a host transport adapter that encapsulates the transfer datagram inside a `DATA` or `ACK` virtual packet and carries it through the configured router path.
