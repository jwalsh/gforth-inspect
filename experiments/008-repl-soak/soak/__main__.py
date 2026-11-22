"""python -m soak COMMAND ...   (run from experiments/008-repl-soak/, under uv: see the Makefile)

    run NAME --hours H [--slots N] [--min-live M] [--stall S] [--pace P]
    resume NAME                 continue a run whose harness stopped; the clock is kept
    status [NAME]               print the status file
    calibrate [--only NAME]     every planted fault red, then green
"""

from __future__ import annotations

import argparse
import json
import sys

from . import config


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="soak")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("name")
    run.add_argument("--hours", type=float, required=True)
    run.add_argument("--slots", type=int, default=10)
    run.add_argument("--min-live", type=int, default=8)
    run.add_argument("--stall", type=float, default=300.0)
    run.add_argument("--pace", type=float, default=1.0)
    run.add_argument("--short-minutes", type=float, nargs=2, default=(5, 60))
    run.add_argument("--seed", type=int)
    resume = commands.add_parser("resume")
    resume.add_argument("name")
    status = commands.add_parser("status")
    status.add_argument("name", nargs="?")
    calibrate = commands.add_parser("calibrate")
    calibrate.add_argument("--only")
    options = parser.parse_args(argv)

    if options.command in ("run", "resume"):
        from .run import Run
        if options.command == "run":
            runner = Run(options.name, options.hours, options.slots, options.min_live, options.stall,
                         options.pace, tuple(options.short_minutes), options.seed)
        else:
            saved = json.loads((config.state_root() / "runs" / options.name / "run.json").read_text())
            runner = Run(options.name, saved["hours"], saved["slots"], saved["min_live"], saved.get("stall", 300.0),
                         saved.get("pace", 1.0), tuple(saved.get("short_minutes", (5, 60))), resume=True,
                         guard_period=saved.get("guard_period", 600.0))
        return runner.main()
    if options.command == "status":
        path = (config.state_root() / "runs" / options.name / "status.txt") if options.name \
            else config.state_root() / "status.txt"
        print(path.read_text(), end="")
        return 0
    if options.command == "calibrate":
        from .calibrate import main as calibrate_main
        return calibrate_main(options.only)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
