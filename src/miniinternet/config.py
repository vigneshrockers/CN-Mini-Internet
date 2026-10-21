"""Topology loading and validation."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

class ConfigError(ValueError):
    pass

def load_config(path: str | Path) -> dict[str, Any]:
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read topology {path}: {exc}") from exc
    if not isinstance(cfg.get("devices"), dict) or not cfg["devices"]:
        raise ConfigError("topology must contain a non-empty devices object")
    devices = cfg["devices"]
    virtuals, endpoints = set(), set()
    for name, dev in devices.items():
        if not isinstance(dev, dict) or dev.get("role") not in {"host", "router"}:
            raise ConfigError(f"{name}: role must be host or router")
        if not isinstance(dev.get("virtual_address"), str) or not dev["virtual_address"]:
            raise ConfigError(f"{name}: missing virtual_address")
        if dev["virtual_address"] in virtuals:
            raise ConfigError(f"duplicate virtual address {dev['virtual_address']}")
        virtuals.add(dev["virtual_address"])
        ep = dev.get("udp", {})
        if not isinstance(ep.get("host"), str) or type(ep.get("port")) is not int or not 1 <= ep["port"] <= 65535:
            raise ConfigError(f"{name}: invalid UDP endpoint")
        if (ep["host"], ep["port"]) in endpoints:
            raise ConfigError(f"duplicate UDP endpoint {ep['host']}:{ep['port']}")
        endpoints.add((ep["host"], ep["port"]))
        dev.setdefault("neighbors", [])
        for neighbor in dev["neighbors"]:
            if neighbor not in devices or neighbor == name:
                raise ConfigError(f"{name}: invalid neighbor {neighbor}")
            if name not in devices[neighbor].get("neighbors", []):
                raise ConfigError(f"link {name}-{neighbor} must be configured bidirectionally")
        if dev["role"] == "host":
            gw = dev.get("gateway")
            if gw not in dev["neighbors"]:
                raise ConfigError(f"{name}: gateway must be a configured neighbor")
        else:
            routes = dev.get("forwarding", {})
            for dest, hop in routes.items():
                if dest not in virtuals and dest not in {d.get("virtual_address") for d in devices.values()}:
                    raise ConfigError(f"{name}: route uses unknown virtual destination {dest}")
                if hop not in dev["neighbors"]:
                    raise ConfigError(f"{name}: next hop {hop} is not a configured neighbor")
        for neighbor, settings in dev.get("links", {}).items():
            if neighbor not in dev["neighbors"]:
                raise ConfigError(f"{name}: impairment configured for non-neighbor {neighbor}")
            if not 0 <= float(settings.get("loss_probability", 0)) <= 1 or float(settings.get("delay_ms", 0)) < 0:
                raise ConfigError(f"{name}: invalid impairment for link to {neighbor}")
    cfg.setdefault("run_id", "mini-internet")
    cfg.setdefault("hop_limit", 12)
    return cfg
