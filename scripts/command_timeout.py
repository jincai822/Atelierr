#!/usr/bin/env python3
"""Run one command with a hard wall-clock timeout and signal its process group."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable

POLL_INTERVAL_SECONDS = 0.25


def wait_until_deadline(
    process: subprocess.Popen[bytes],
    deadline: float,
    *,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Wait using epoch time so a system sleep cannot pause the deadline."""
    while True:
        returncode = process.poll()
        if returncode is not None:
            return returncode
        remaining = deadline - now()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, 0)
        sleep(min(POLL_INTERVAL_SECONDS, remaining))


def stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate one process group, escalating to SIGKILL after five seconds."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        wait_until_deadline(process, time.time() + 5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    try:
        process = subprocess.Popen(command, start_new_session=True)
    except OSError as exc:
        print(f"ERROR: cannot start {command[0]}: {exc}", file=sys.stderr)
        return 127
    try:
        return wait_until_deadline(process, time.time() + args.seconds)
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: command timed out after {args.seconds:g}s: {command[0]}",
            file=sys.stderr,
        )
        stop_process_group(process)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
