"""herdr-spec-drafter: draft specs for your Linear tickets in visible Herdr agents."""

import argparse
import json
import sys
from pathlib import Path

from . import dispatcher
from .config import Config
from .linear import fetch

SCRIPT = str(Path(__file__).resolve().parent.parent / "bin" / "herdr-spec-drafter")


def main(argv=None):
    p = argparse.ArgumentParser(prog="herdr-spec-drafter", description=__doc__)
    p.add_argument("--config", help="config file (default: $HERDR_SPEC_DRAFTER_CONFIG or "
                                    "~/.config/herdr-spec-drafter/config.json)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start", help="start the hourly dispatcher in a Herdr tab")
    sub.add_parser("stop", help="stop the dispatcher (spec agents keep running)")
    once = sub.add_parser("once", help="run one round now")
    once.add_argument("--dry-run", action="store_true", help="show what would happen")
    sub.add_parser("loop", help="run rounds forever (what `start` runs)")
    la = sub.add_parser("launch", help="start a spec agent for one ticket now")
    la.add_argument("ticket")
    la.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="list launched tickets and their results")
    sub.add_parser("issues", help="list the matching Linear issues, in launch order")
    fo = sub.add_parser("forget", help="stop tracking a ticket so it can be launched again")
    fo.add_argument("ticket")
    sub.add_parser("config", help="print the effective config")
    args = p.parse_args(argv)

    cfg = Config.load(args.config)
    if args.cmd == "start":
        dispatcher.start_dispatcher(cfg, SCRIPT, args.config)
    elif args.cmd == "stop":
        dispatcher.stop_dispatcher()
    elif args.cmd == "once":
        dispatcher.run_once(cfg, dry_run=args.dry_run)
    elif args.cmd == "loop":
        dispatcher.loop(cfg)
    elif args.cmd == "launch":
        dispatcher.launch_one(cfg, args.ticket, dry_run=args.dry_run)
    elif args.cmd == "status":
        dispatcher.status(cfg)
    elif args.cmd == "issues":
        for i in fetch(cfg["linear"], cfg["connectors"]["linear"]):
            print("%-10s p%-2s %-10s %s" % (i.identifier, i.priority, i.state, i.title))
    elif args.cmd == "forget":
        dispatcher.forget(cfg, args.ticket)
    elif args.cmd == "config":
        print("# source: %s" % (cfg.source or "defaults only"))
        print(json.dumps(cfg.data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
