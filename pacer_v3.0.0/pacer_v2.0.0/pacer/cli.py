from __future__ import annotations
import argparse
from .parser import parse
from .audit import audit
from .theatre import compile_theatre

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pacer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit"); a.add_argument("file")
    t = sub.add_parser("theatre"); t.add_argument("file"); t.add_argument("--phase")
    s = sub.add_parser("summary"); s.add_argument("file")
    ns = ap.parse_args(argv)
    plan = parse(ns.file)
    if ns.cmd == "audit":
        for msg in audit(plan): print(msg)
    elif ns.cmd == "theatre":
        print(compile_theatre(plan, ns.phase))
    else:
        phases = [p for g in plan.globals for p in g.phases]
        paces = [x for p in phases for x in p.paces]
        print(f"project={plan.project}")
        print(f"maturity={plan.maturity}")
        print(f"globals={len(plan.globals)} phases={len(phases)} paces={len(paces)} loop={plan.has_loop}")
    return 0
