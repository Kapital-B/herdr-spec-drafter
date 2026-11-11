"""herdr-spec-drafter: draft specs for your Linear tickets in visible Herdr agents."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import dispatcher
from .config import Config
from .linear import fetch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "bin" / "herdr-spec-drafter")
REPO = os.environ.get("HSD_REPO", "Kapital-B/herdr-spec-drafter")


def installed_version():
    """The release/branch this copy came from, or the git commit for a clone."""
    vfile = ROOT / "VERSION"
    if vfile.exists():
        return vfile.read_text().strip()
    if (ROOT / ".git").exists():
        out = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return "%s (git clone)" % out.stdout.strip()
    return "unknown"


def update(version=None):
    """Re-run the published installer, which replaces this downloaded copy."""
    if (ROOT / ".git").exists():
        print("This is a git clone (%s): update it with git pull." % ROOT)
        return 1
    url = "https://raw.githubusercontent.com/%s/main/install.sh" % REPO
    with urllib.request.urlopen(url, timeout=30) as resp:
        script = resp.read()
    with tempfile.NamedTemporaryFile("wb", suffix="-install.sh", delete=False) as f:
        f.write(script)
    try:
        # Run as a pipe so the installer downloads rather than treating its temp folder as a clone.
        args = ["bash", "-s", "--"] + (["--version", version] if version else [])
        return subprocess.run(args, stdin=open(f.name, "rb")).returncode
    finally:
        os.unlink(f.name)


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
    sub.add_parser("version", help="print the installed version")
    up = sub.add_parser("update", help="install the latest release (or --version REF)")
    up.add_argument("--version", dest="ref", help="release tag or branch")
    args = p.parse_args(argv)

    if args.cmd == "version":
        print(installed_version())
        return 0
    if args.cmd == "update":
        return update(args.ref)

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
