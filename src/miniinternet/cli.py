"""Command-line tools for the virtual UDP mini-internet."""
from __future__ import annotations
import argparse
import json
import multiprocessing as mp
import socket
import threading
from pathlib import Path
from pathlib import Path
from .config import load_config
from .runner import run_probe, run_both_directions, run_baseline
from .runtime import run_device

def _parser():
    p=argparse.ArgumentParser(description="Run the configured UDP mini-internet")
    sub=p.add_subparsers(dest="command",required=True)
    demo=sub.add_parser("demo",help="launch all six devices and run probes")
    demo.add_argument("--config",default="config/topology-upper.json")
    demo.add_argument("--path",choices=("upper","lower"),default=None)
    demo.add_argument("--direction",choices=("H1-to-H2","H2-to-H1","both"),default="both")
    demo.add_argument("--count",type=int,default=20)
    demo.add_argument("--interval",type=float,default=0.02)
    demo.add_argument("--timeout",type=float,default=2.0)
    dev=sub.add_parser("device",help="start one configured host or router")
    dev.add_argument("--config",default="config/topology-upper.json");dev.add_argument("--name",required=True)
    probe=sub.add_parser("probe",help="run a probe session while launching the other five processes")
    probe.add_argument("--config",default="config/topology-upper.json");probe.add_argument("--source",default="H1");probe.add_argument("--destination",default="H2")
    probe.add_argument("--count",type=int,default=20);probe.add_argument("--interval",type=float,default=0.02);probe.add_argument("--timeout",type=float,default=2.0)
    measure=sub.add_parser("measure",help="run the required repeated 2x2 core baseline")
    measure.add_argument("--config",default="config/topology-upper.json")
    measure.add_argument("--count",type=int,default=20);measure.add_argument("--repetitions",type=int,default=3)
    measure.add_argument("--delay-ms",type=float,nargs=2,default=(0.0,25.0),metavar=("LOW","HIGH"))
    measure.add_argument("--loss",type=float,nargs=2,default=(0.0,0.05),metavar=("LOW","HIGH"))
    measure.add_argument("--interval",type=float,default=0.02);measure.add_argument("--timeout",type=float,default=3.0)
    measure.add_argument("--output",default=None,help="also save aggregate JSONL results to this path")
    inject=sub.add_parser("inject-invalid",help="send malformed bytes from a configured host endpoint to its gateway")
    inject.add_argument("--config",default="config/topology-upper.json");inject.add_argument("--source",default="H1");inject.add_argument("--bytes",default="not-a-valid-packet")
    return p

def main(argv=None):
    args=_parser().parse_args(argv)
    try:
        if args.command=="device":
            run_device(args.config,args.name,threading.Event());return 0
        if args.command=="probe":
            row=run_probe(args.config,args.source,args.destination,args.count,args.interval,args.timeout)
            print(json.dumps(row,sort_keys=True));return 0 if row["received"]==row["sent"] else 1
        if args.command=="measure":
            rows=run_baseline(args.config,args.count,args.repetitions,tuple(args.delay_ms),tuple(args.loss),args.interval,args.timeout)
            serialized=[json.dumps(row,sort_keys=True) for row in rows]
            for line in serialized: print(line)
            if args.output:
                output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
                output.write_text("\n".join(serialized)+"\n",encoding="utf-8")
            return 0
        if args.command=="demo":
            config=args.config
            if args.path:
                config=str(Path(args.config).parent/f"topology-{args.path}.json") if args.config=="config/topology-upper.json" else args.config
            if args.direction=="both": rows=run_both_directions(config,args.count,args.interval,args.timeout)
            elif args.direction=="H1-to-H2": rows=[run_probe(config,"H1","H2",args.count,args.interval,args.timeout)]
            else: rows=[run_probe(config,"H2","H1",args.count,args.interval,args.timeout)]
            for row in rows: print(json.dumps(row,sort_keys=True))
            return 0 if all(r["received"]==r["sent"] for r in rows) else 1
        if args.command=="inject-invalid":
            cfg=load_config(args.config);dev=cfg["devices"][args.source];gateway=cfg["devices"][dev["gateway"]]
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            try:
                sock.bind((dev["udp"]["host"],dev["udp"]["port"]))
                sock.sendto(args.bytes.encode(),(gateway["udp"]["host"],gateway["udp"]["port"]))
            finally: sock.close()
            return 0
    except (ValueError,OSError,RuntimeError) as exc:
        print(f"mini-internet: {exc}")
        return 2
    return 2

if __name__=="__main__": raise SystemExit(main())
